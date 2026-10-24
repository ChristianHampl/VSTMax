"""Offline-Mix-Renderer.

Signalkette pro Spur (identisch zum VST3-Plugin ``AIME Channel``):
DC-Filter -> Polarität/Laufzeit -> Trim -> Gate -> HPF/LPF -> statischer EQ ->
dynamischer EQ -> Kompressor -> De-Esser -> Sättigung -> Fader -> Pan/Breite.

Kompressor-, De-Esser-, Dyn-EQ- und Bus-Schwellen werden auf die im Plan
angegebene Ziel-Gain-Reduction kalibriert (Bisektion auf dem tatsächlichen Signal)
und in den Plan zurückgeschrieben, damit Plugins dieselben Werte erhalten.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from . import dsp
from . import loudness as lmod

AudioProvider = Callable[[str], np.ndarray]


def loudest_region(signals: list[np.ndarray], sr: int, length_s: float) -> tuple[int, int]:
    n = max((s.shape[0] for s in signals), default=0)
    L = int(length_s * sr)
    if n <= L:
        return 0, n
    hop = sr
    nb = n // hop
    energy = np.zeros(nb)
    for s in signals:
        x = dsp.ensure_2d(s)
        m = min(nb * hop, x.shape[0])
        e = np.mean(x[: (m // hop) * hop] ** 2, axis=1).reshape(-1, hop).mean(axis=1)
        e = e / (e.max() + 1e-20)  # jede Spur gleich gewichtet
        energy[: len(e)] += e
    w = max(1, L // hop)
    cs = np.concatenate([[0], np.cumsum(energy)])
    sums = cs[w:] - cs[:-w]
    start = int(np.argmax(sums)) * hop
    return start, min(n, start + L)


def _p95(gr: np.ndarray) -> float:
    return float(np.percentile(gr, 95)) if gr.size else 0.0


def _comp_p95(x, sr, thr, c, sidechain=None):
    lvl = dsp.block_rms(sidechain if sidechain is not None else x) if c.get("detector") == "rms" \
        else dsp.block_peak(sidechain if sidechain is not None else x)
    lvl_db = dsp.lin_to_db(lvl)
    target = dsp.compressor_gain_computer(lvl_db, thr, c["ratio"], c.get("knee_db", 6.0))
    bsr = sr / dsp.ENV_BLOCK
    gr = dsp.smooth_ballistics(target, dsp.time_coef(c["attack_ms"], bsr), dsp.time_coef(c["release_ms"], bsr), 0.0)
    active = lvl_db > (lvl_db.max() - 40 if lvl_db.size else 0)
    return _p95(gr[active]) if np.any(active) else 0.0


def _bisect(fn: Callable[[float], float], target: float, lo: float, hi: float, iters: int = 14) -> float:
    """Sucht Schwelle t mit fn(t) ~= target (fn monoton fallend in t)."""
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if fn(mid) > target:
            lo = mid
        else:
            hi = mid
    return round(0.5 * (lo + hi), 2)


def _calib_excerpt(x: np.ndarray, sr: int, max_s: float = 30.0) -> np.ndarray:
    n = int(max_s * sr)
    if x.shape[0] <= n:
        return x
    s, e = loudest_region([x], sr, max_s)
    return x[s:e]


def calibrate_comp(x: np.ndarray, sr: int, c: dict, sidechain: np.ndarray | None = None) -> float:
    xe = _calib_excerpt(dsp.ensure_2d(x), sr)
    sc = _calib_excerpt(dsp.ensure_2d(sidechain), sr) if sidechain is not None else None
    pk = float(dsp.lin_to_db(np.max(np.abs(xe if sc is None else sc)) + 1e-12))
    return _bisect(lambda t: _comp_p95(xe, sr, t, c, sc), c["target_gr_db"], pk - 60.0, pk + 1.0)


def calibrate_deesser(x: np.ndarray, sr: int, d: dict) -> float:
    xe = _calib_excerpt(dsp.ensure_2d(x), sr)
    _, high = dsp.split_band(xe, sr, d["freq"])
    lvl_db = dsp.lin_to_db(dsp.block_peak(high))
    pk = float(lvl_db.max()) if lvl_db.size else -60.0

    def f(t):
        target = np.clip(dsp.compressor_gain_computer(lvl_db, t, 4.0, 3.0), 0, d["range_db"])
        return float(np.percentile(target, 99.5)) if target.size else 0.0

    return _bisect(f, d["target_gr_db"], pk - 50.0, pk + 1.0)


def calibrate_dyn_band(x: np.ndarray, sr: int, d: dict, sidechain: np.ndarray | None) -> float:
    xe = dsp.ensure_2d(x)
    sc = dsp.ensure_2d(sidechain) if sidechain is not None else xe
    b, a = dsp.biquad_coeffs("bandpass", d["freq"], sr, 0.0, d["q"])
    band = dsp.apply_biquad(_calib_excerpt(sc, sr), b, a)
    lvl_db = dsp.lin_to_db(dsp.block_rms(band))
    pk = float(lvl_db.max()) if lvl_db.size else -60.0
    active = lvl_db > pk - 30

    def f(t):
        g = np.clip(dsp.compressor_gain_computer(lvl_db, t, 3.0, 6.0), 0, d["range_db"])
        return _p95(g[active]) if np.any(active) else 0.0

    return _bisect(f, d["target_gr_db"], pk - 50.0, pk + 1.0)


@dataclass
class TrackStats:
    pre_fader_lufs: float = float("-inf")
    post_fader_lufs: float = float("-inf")
    peak_dbfs: float = -150.0
    comp_gr: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)
    deesser: dict = field(default_factory=dict)
    dyn_eq: list = field(default_factory=list)


@dataclass
class MixResult:
    mix: np.ndarray
    sr: int
    buses: dict
    fx_returns: dict
    track_stats: dict
    bus_stats: dict
    headroom_gain_db: float
    region: tuple[int, int]


class MixRenderer:
    def __init__(self, plan: dict, provider: AudioProvider, sr: int, log: list | None = None):
        self.plan = plan
        self.provider = provider
        self.sr = sr
        self.log = log if log is not None else []
        self.tracks = {t["id"]: t for t in plan["tracks"]}

    # ------------------------------------------------------------ Bausteine
    def _raw(self, tid: str, region: tuple[int, int] | None) -> np.ndarray:
        x = dsp.ensure_2d(self.provider(tid))
        if region is not None:
            s, e = region
            x = x[s:e]
            if x.shape[0] < e - s:
                x = np.vstack([x, np.zeros((e - s - x.shape[0], x.shape[1]))])
        return x

    def _pre(self, tid: str, region) -> np.ndarray:
        """Quelle nach Reparatur und Trim (auch Sidechain-Quelle)."""
        t = self.tracks[tid]
        x = self._raw(tid, region).copy()
        if t.get("dc_remove"):
            x = dsp.remove_dc(x, self.sr)
        if t.get("invert_right") and x.shape[1] > 1:
            x[:, 1] = -x[:, 1]
        if t.get("polarity_invert"):
            x = -x
        if t.get("delay_samples"):
            x = dsp.fractional_delay(x, int(t["delay_samples"]))
        return x * dsp.db_to_lin(t["trim_db"])

    def process_track(self, tid: str, region=None, calibrate: bool = True) -> tuple[np.ndarray, TrackStats]:
        t = self.tracks[tid]
        sr = self.sr
        st = TrackStats()
        x = self._pre(tid, region)
        g = t.get("gate", {})
        if g.get("enabled"):
            x, st.gate = dsp.gate(x, sr, g["threshold_db"], g["range_db"], g["attack_ms"], g["hold_ms"], g["release_ms"])
        if t.get("hpf"):
            x = dsp.apply_eq_band(x, sr, {"type": "hpf", "freq": t["hpf"]["freq"], "order": t["hpf"].get("order", 2)})
        if t.get("lpf") and t["lpf"]["freq"] < 0.45 * sr:
            x = dsp.apply_eq_band(x, sr, {"type": "lpf", "freq": t["lpf"]["freq"], "order": t["lpf"].get("order", 2)})
        for band in t.get("eq", []):
            if abs(band.get("gain_db", 0.0)) > 0.01:
                x = dsp.apply_eq_band(x, sr, band)
        for d in t.get("dyn_eq", []):
            sc = self._pre(d["sidechain"], region) if d.get("sidechain") in self.tracks else None
            if calibrate and (d.get("calibrate") or d.get("threshold_db") is None):
                d["threshold_db"] = calibrate_dyn_band(x, sr, d, sc)
                d["calibrate"] = False
            x, s = dsp.dynamic_band(x, sr, d["freq"], d["q"], d["threshold_db"], d["range_db"], sc)
            st.dyn_eq.append(s)
        c = t.get("comp", {})
        if c.get("enabled"):
            if calibrate and c.get("calibrate"):
                c["threshold_db"] = calibrate_comp(x, sr, c)
                c["calibrate"] = False
            pre_lufs = lmod.integrated_loudness(x, sr)
            x, st.comp_gr = dsp.compress(x, sr, c["threshold_db"], c["ratio"], c["attack_ms"], c["release_ms"],
                                         c.get("knee_db", 6.0), c.get("makeup_db", 0.0), c.get("mix", 1.0))
            post = lmod.integrated_loudness(x, sr)
            if math.isfinite(pre_lufs) and math.isfinite(post) and c.get("auto_makeup", True):
                # Pegelneutral (Makeup), damit Balance nur über Fader läuft
                c["makeup_db"] = round(c.get("makeup_db", 0.0) + (pre_lufs - post), 2)
                x = x * dsp.db_to_lin(pre_lufs - post)
                c["auto_makeup"] = False
        de = t.get("deesser", {})
        if de.get("enabled"):
            if calibrate and (de.get("calibrate") or de.get("threshold_db") is None):
                de["threshold_db"] = calibrate_deesser(x, sr, de)
                de["calibrate"] = False
            x, st.deesser = dsp.deess(x, sr, de["freq"], de["threshold_db"], de["range_db"])
        sat = t.get("saturation", {})
        if sat.get("drive_db", 0) > 0.01:
            x = dsp.saturate(x, sat["drive_db"], sat.get("mix", 1.0))
        x = dsp.sanitize(x)
        st.pre_fader_lufs = lmod.integrated_loudness(x, sr)
        st.peak_dbfs = float(dsp.lin_to_db(np.max(np.abs(x)) + 1e-15))
        return x, st

    def place(self, tid: str, x: np.ndarray) -> np.ndarray:
        t = self.tracks[tid]
        y = x * dsp.db_to_lin(t["fader_db"])
        if y.shape[1] > 1:
            y = dsp.stereo_width(y, t.get("width", 1.0))
            if abs(t.get("pan", 0.0)) > 1e-3:
                y = dsp.pan_stereo(y, t["pan"])
            return y
        return dsp.pan_stereo(y, t.get("pan", 0.0))

    def set_faders(self, stats: dict[str, TrackStats], log: list | None = None):
        for tid, st in stats.items():
            t = self.tracks[tid]
            if t.get("target_lufs") is None or not math.isfinite(st.pre_fader_lufs):
                continue
            t["fader_db"] = round(float(np.clip(t["target_lufs"] - st.pre_fader_lufs, -40.0, 24.0)), 2)
            if log is not None:
                log.append({"track": tid, "param": "fader_db", "value": t["fader_db"],
                            "reason": f"Gemessene Lautheit nach Bearbeitung {st.pre_fader_lufs:.1f} LUFS -> "
                                      f"Ziel {t['target_lufs']:.1f} LUFS", "uncertain": False})

    # ------------------------------------------------------------ Mix
    def render(self, region=None, cache: dict | None = None, calibrate: bool = True,
               progress: Callable[[float, str], None] | None = None,
               cancel: Callable[[], bool] | None = None) -> MixResult:
        sr = self.sr
        enabled = [t for t in self.plan["tracks"] if t.get("enabled")]
        n = None
        bus_sums: dict[str, np.ndarray] = {}
        reverb_in = delay_in = None
        stats = {}
        for i, t in enumerate(enabled):
            if cancel and cancel():
                raise InterruptedError("Abgebrochen")
            tid = t["id"]
            if progress:
                progress(i / max(1, len(enabled)), f"Bearbeite {t['name']}")
            if cache is not None and tid in cache:
                x, st = cache[tid]
            else:
                x, st = self.process_track(tid, region, calibrate)
                if cache is not None:
                    cache[tid] = (x, st)
            stats[tid] = st
            y = self.place(tid, x)
            st.post_fader_lufs = st.pre_fader_lufs + t["fader_db"]
            if n is None:
                n = y.shape[0]
            m = min(n, y.shape[0])
            gid = t["group"]
            bus_sums.setdefault(gid, np.zeros((n, 2)))[:m] += y[:m]
            s = t.get("sends", {})
            if s.get("reverb_db") is not None:
                reverb_in = (reverb_in if reverb_in is not None else np.zeros((n, 2)))
                reverb_in[:m] += y[:m] * dsp.db_to_lin(s["reverb_db"])
            if s.get("delay_db") is not None:
                delay_in = (delay_in if delay_in is not None else np.zeros((n, 2)))
                delay_in[:m] += y[:m] * dsp.db_to_lin(s["delay_db"])
        if n is None:
            raise ValueError("Keine aktiven Spuren im Mix-Plan")
        if progress:
            progress(0.9, "Busse und Effekte")
        bus_stats = {}
        buses_out = {}
        for gid, x in bus_sums.items():
            b = self.plan["buses"].get(gid)
            y = x
            if b:
                if b.get("parallel"):
                    p = b["parallel"]
                    pc = p["comp"]
                    if calibrate and pc.get("calibrate"):
                        pc["threshold_db"] = calibrate_comp(x, sr, pc)
                        pc["calibrate"] = False
                    par, pst = dsp.compress(x, sr, pc["threshold_db"], pc["ratio"], pc["attack_ms"], pc["release_ms"],
                                            pc["knee_db"], pc["target_gr_db"])
                    par = dsp.saturate(par, p.get("saturation_db", 0.0))
                    y = y + par * p["amount"]
                    bus_stats[gid + ".parallel"] = pst
                c = b.get("comp", {})
                if c.get("enabled"):
                    if calibrate and c.get("calibrate"):
                        c["threshold_db"] = calibrate_comp(y, sr, c)
                        c["calibrate"] = False
                    y, bst = dsp.compress(y, sr, c["threshold_db"], c["ratio"], c["attack_ms"], c["release_ms"],
                                          c["knee_db"], c.get("makeup_db", 0.0))
                    bus_stats[gid] = bst
                if b.get("saturation", {}).get("drive_db", 0) > 0.01:
                    y = dsp.saturate(y, b["saturation"]["drive_db"])
                y = y * dsp.db_to_lin(b.get("fader_db", 0.0))
            buses_out[gid] = y
        fx_returns = {}
        fx = self.plan["fx"]
        if reverb_in is not None:
            r = fx["reverb"]
            fx_returns["reverb"] = dsp.convolve_stereo(reverb_in, dsp.make_reverb_ir(sr, r["decay_s"], r["predelay_ms"], r["damping_hz"]))
        if delay_in is not None:
            d = fx["delay"]
            fx_returns["delay"] = dsp.convolve_stereo(delay_in, dsp.make_delay_ir(sr, d["time_s"], d["feedback"], 6, d["damping_hz"]))
        mix = np.zeros((n, 2))
        for y in list(buses_out.values()) + list(fx_returns.values()):
            mix[: y.shape[0]] += y[:n]
        # Eingangsgain des Mixbus wird einmalig festgelegt (Peak = Headroom-Ziel) und
        # danach beibehalten, damit Kompressor-Schwellen reproduzierbar bleiben.
        mbus = self.plan["mix_bus"]
        if mbus.get("input_gain_db") is None:
            peak = float(np.max(np.abs(mix))) if mix.size else 0.0
            head = mbus.get("headroom_dbfs", -6.0)
            mbus["input_gain_db"] = round(head - 20 * math.log10(peak), 2) if peak > 0 else 0.0
        gain_db = mbus["input_gain_db"]
        mix = mix * dsp.db_to_lin(gain_db)
        mb = mbus.get("comp", {})
        if mb.get("enabled"):
            if calibrate and mb.get("calibrate"):
                mb["threshold_db"] = calibrate_comp(mix, sr, mb)
                mb["calibrate"] = False
            mix, bus_stats["mix_bus"] = dsp.compress(mix, sr, mb["threshold_db"], mb["ratio"], mb["attack_ms"],
                                                     mb["release_ms"], mb["knee_db"], 0.0)
        mix = dsp.sanitize(mix)
        peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        if peak > 0.99:  # Sicherheitsnetz gegen Übersteuerung vor dem Mastering
            mix = mix * (0.99 / peak)
        if progress:
            progress(1.0, "Mix fertig")
        return MixResult(mix, sr, buses_out, fx_returns, stats, bus_stats, gain_db,
                         region if region else (0, n))
