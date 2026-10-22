"""Messbasierte iterative Mix-Optimierung.

Ablauf je Iteration: Messwerte bestimmen -> größtes Problem wählen -> genau eine
Parameteränderung (innerhalb sicherer Grenzen) -> neu rendern -> Score vergleichen ->
übernehmen oder zurücknehmen. Alles wird protokolliert.
"""

from __future__ import annotations

import copy
import math
from typing import Callable

import numpy as np

from . import dsp
from .analysis import THIRD_OCTAVE_CENTERS, spectrum, third_octave
from .mixing import MixRenderer, MixResult
from .phase import mono_compatibility_db, stereo_correlation

LIMITS = {
    "fader_step_db": 0.5,
    "fader_max_dev_db": 3.0,  # max. Abweichung vom Balance-Ziel durch den Optimierer
    "dyn_range_max_db": 6.0,
    "eq_cut_max_db": 6.0,
    "mixbus_gr_max_db": 3.0,
    "width_min": 0.6,
}


def _band_energy(x: np.ndarray, sr: int, lo: float, hi: float) -> np.ndarray:
    """Bandenergie je 50-ms-Frame."""
    b1, a1 = dsp.biquad_coeffs("hpf", lo, sr, 0, 0.7071)
    b2, a2 = dsp.biquad_coeffs("lpf", hi, sr, 0, 0.7071)
    y = dsp.apply_biquad(dsp.apply_biquad(dsp.ensure_2d(x), b1, a1), b2, a2)
    hop = int(0.05 * sr)
    nb = y.shape[0] // hop
    if nb == 0:
        return np.zeros(1)
    return np.mean(y[: nb * hop] ** 2, axis=1).reshape(nb, hop).mean(axis=1)


def spectral_tilt(x: np.ndarray, sr: int) -> float:
    """Steigung (dB/Oktave) der Leistungsdichte zwischen 60 Hz und 12 kHz.

    Rosa Rauschen = -3 dB/Okt. Terzbandenergien steigen bei gleicher Dichte um
    +3 dB/Okt (Bandbreite proportional zur Frequenz), daher die Korrektur um -3,01.
    """
    f, p = spectrum(x, sr)
    tod = third_octave(f, p)
    m = (THIRD_OCTAVE_CENTERS >= 60) & (THIRD_OCTAVE_CENTERS <= 12000)
    xs = np.log2(THIRD_OCTAVE_CENTERS[m])
    return float(np.polyfit(xs, tod[m], 1)[0]) - 3.0103


class Optimizer:
    def __init__(self, renderer: MixRenderer, region: tuple[int, int], log: list,
                 progress: Callable[[float, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None):
        self.r = renderer
        self.region = region
        self.log = log
        self.cache: dict = {}
        self.progress = progress
        self.cancel = cancel
        self.sr = renderer.sr

    # ------------------------------------------------------------ Messung
    def _placed(self, tid: str) -> np.ndarray:
        x, _ = self.cache[tid]
        return self.r.place(tid, x)

    def metrics(self, res: MixResult) -> dict:
        sr = self.sr
        plan = self.r.plan
        tracks = [t for t in plan["tracks"] if t.get("enabled")]
        m: dict = {}
        mix = res.mix
        pk = float(np.max(np.abs(mix))) + 1e-12
        rms = float(np.sqrt(np.mean(mix ** 2))) + 1e-12
        m["crest_db"] = 20 * math.log10(pk / rms)
        m["tilt_db_oct"] = spectral_tilt(mix, sr)
        m["mono_compat_db"] = mono_compatibility_db(mix)
        m["correlation"] = stereo_correlation(mix)
        vocals = [t["id"] for t in tracks if t["role"] in ("lead_vocal", "scream_vocal")]
        others = [t["id"] for t in tracks if t["id"] not in vocals and t["group"] != "vocals"]
        if vocals and others:
            v = sum(_band_energy(self._placed(t), sr, 1000, 4000) for t in vocals)
            o = sum(_band_energy(self._placed(t), sr, 1000, 4000) for t in others)
            act = v > (v.max() * 10 ** (-30 / 10))
            m["vocal_clarity_db"] = float(10 * np.log10((v[act].mean() + 1e-20) / (o[act].mean() + 1e-20))) if act.any() else None
        kicks = [t["id"] for t in tracks if t["role"] == "kick"]
        basses = [t["id"] for t in tracks if t["role"] == "bass"]
        if kicks and basses:
            k = sum(_band_energy(self._placed(t), sr, 40, 100) for t in kicks)
            b = sum(_band_energy(self._placed(t), sr, 40, 100) for t in basses)
            hits = k > np.percentile(k, 90)
            m["kick_bass_sep_db"] = float(10 * np.log10((k[hits].mean() + 1e-20) / (b[hits].mean() + 1e-20))) if hits.any() else None
        return m

    def score(self, m: dict) -> tuple[float, dict]:
        plan = self.r.plan
        tgt = plan["mix_target"]
        pen = {}
        cmin, cmax = tgt["crest_min_db"], tgt["crest_max_db"]
        pen["crest"] = max(0.0, cmin - m["crest_db"]) * 2.0 + max(0.0, m["crest_db"] - cmax) * 0.5
        pen["tilt"] = max(0.0, abs(m["tilt_db_oct"] - tgt["tilt_db_per_oct"]) - 0.5) * 1.0
        pen["mono"] = max(0.0, -4.5 - m["mono_compat_db"]) * 2.0 + max(0.0, 0.1 - m["correlation"]) * 10.0
        vc = m.get("vocal_clarity_db")
        if vc is not None:
            pen["vocal"] = max(0.0, 1.0 - vc) * 1.5 + max(0.0, vc - 7.0) * 1.0
        kb = m.get("kick_bass_sep_db")
        if kb is not None:
            owner_kick = any(d.get("origin") == "kick_bass" for t in plan["tracks"] if t["role"] == "bass"
                             for d in t.get("dyn_eq", []))
            want = 3.0 if owner_kick else -1.0
            pen["kick_bass"] = max(0.0, want - kb) * 1.0
        return float(sum(pen.values())), pen

    # ------------------------------------------------------------ Aktionen
    def _candidate_actions(self, pen: dict, m: dict) -> list[tuple[str, Callable[[dict], list[str] | None]]]:
        acts = []
        order = sorted(pen.items(), key=lambda kv: -kv[1])
        for key, val in order:
            if val <= 0.05:
                continue
            if key == "vocal":
                low = (m.get("vocal_clarity_db") or 0) < 1.0
                acts.append(("Vocal-Fader " + ("+" if low else "-") + "0.5 dB",
                             lambda p, up=low: self._adjust_fader(p, ("lead_vocal", "scream_vocal"), 0.5 if up else -0.5)))
                if low:
                    acts.append(("Gitarren-Ausweichen vor Vocals +1 dB", lambda p: self._adjust_dyn(p, "guitars", "masking", 1.0)))
            elif key == "kick_bass":
                acts.append(("Bass-Ausweichen bei Kick +1 dB", lambda p: self._adjust_dyn(p, "bass", "kick_bass", 1.0)))
                acts.append(("Kick-Fader +0.5 dB", lambda p: self._adjust_fader(p, ("kick",), 0.5)))
            elif key == "crest":
                low = m["crest_db"] < self.r.plan["mix_target"]["crest_min_db"]
                acts.append(("Mixbus-Kompression " + ("-" if low else "+") + "0.5 dB",
                             lambda p, lo=low: self._adjust_mixbus(p, -0.5 if lo else 0.5)))
                if low:
                    acts.append(("Parallele Drum-Kompression -0.05", lambda p: self._adjust_parallel(p, -0.05)))
            elif key == "mono":
                acts.append(("Stereobreite der breitesten Spur -0.1", self._reduce_width))
        return acts

    def _adjust_fader(self, plan, roles, delta) -> list[str] | None:
        changed = []
        for t in plan["tracks"]:
            if t["role"] in roles and t.get("enabled"):
                base = t.setdefault("fader_base_db", t["fader_db"])
                new = t["fader_db"] + delta
                if abs(new - base) > LIMITS["fader_max_dev_db"]:
                    continue
                t["fader_db"] = round(new, 2)
                changed.append(t["id"])
        return changed or None

    def _adjust_dyn(self, plan, group_or_role, origin, delta) -> list[str] | None:
        changed = []
        for t in plan["tracks"]:
            if not t.get("enabled"):
                continue
            if t["group"] != group_or_role and t["role"] != group_or_role:
                continue
            for d in t.get("dyn_eq", []):
                if d.get("origin") == origin and d["range_db"] + delta <= LIMITS["dyn_range_max_db"]:
                    d["range_db"] = round(d["range_db"] + delta, 2)
                    d["target_gr_db"] = d["range_db"]
                    d["calibrate"] = True
                    changed.append(t["id"])
        return changed or None

    def _adjust_mixbus(self, plan, delta) -> list[str] | None:
        c = plan["mix_bus"].get("comp", {})
        if not c.get("enabled"):
            return None
        new = c["target_gr_db"] + delta
        if new < 0.3 or new > LIMITS["mixbus_gr_max_db"]:
            return None
        c["target_gr_db"] = round(new, 2)
        c["calibrate"] = True
        return ["__mixbus__"]

    def _adjust_parallel(self, plan, delta) -> list[str] | None:
        b = plan["buses"].get("drums", {})
        p = b.get("parallel")
        if not p or p["amount"] + delta < 0:
            return None
        p["amount"] = round(p["amount"] + delta, 3)
        return ["__drums__"]

    def _reduce_width(self, plan) -> list[str] | None:
        cands = [t for t in plan["tracks"] if t.get("enabled") and t.get("width", 1.0) > LIMITS["width_min"]
                 and t["id"] in self.cache and self.cache[t["id"]][0].shape[1] > 1]
        if not cands:
            return None
        def side(t):
            x = self.cache[t["id"]][0]
            return float(np.mean((x[:, 0] - x[:, 1]) ** 2))
        t = max(cands, key=side)
        t["width"] = round(t["width"] - 0.1, 2)
        return [t["id"]]

    # ------------------------------------------------------------ Lauf
    def _render(self):
        return self.r.render(self.region, cache=self.cache, calibrate=True)

    def run(self, max_iter: int = 8) -> dict:
        res = self._render()
        m = self.metrics(res)
        s, pen = self.score(m)
        history = [{"iteration": 0, "score": round(s, 3), "metrics": _round(m), "penalties": _round(pen),
                    "action": "Ausgangszustand", "accepted": True}]
        tried: set[str] = set()
        for it in range(1, max_iter + 1):
            if self.cancel and self.cancel():
                break
            if self.progress:
                self.progress(it / max_iter, f"Optimierung Iteration {it}")
            acts = [(n, f) for n, f in self._candidate_actions(pen, m) if n not in tried]
            if not acts or s < 0.05:
                break
            name, fn = acts[0]
            backup = copy.deepcopy(self.r.plan)
            changed = fn(self.r.plan)
            if not changed:
                tried.add(name)
                self.log.append({"track": None, "param": "optimizer", "value": name,
                                 "reason": "Aktion an Sicherheitsgrenze - übersprungen", "uncertain": False})
                continue
            self.r.tracks = {t["id"]: t for t in self.r.plan["tracks"]}
            saved = {tid: self.cache.pop(tid) for tid in changed if tid in self.cache}
            res2 = self._render()
            m2 = self.metrics(res2)
            s2, pen2 = self.score(m2)
            accepted = s2 < s - 1e-3
            history.append({"iteration": it, "score": round(s2, 3), "metrics": _round(m2), "penalties": _round(pen2),
                            "action": name, "accepted": accepted})
            if accepted:
                self.log.append({"track": None, "param": "optimizer", "value": name,
                                 "reason": f"Score {s:.3f} -> {s2:.3f} (verbessert, übernommen)", "uncertain": False})
                res, m, s, pen = res2, m2, s2, pen2
                tried.discard(name)
            else:
                self.log.append({"track": None, "param": "optimizer", "value": name,
                                 "reason": f"Score {s:.3f} -> {s2:.3f} (keine Verbesserung, zurückgenommen)",
                                 "uncertain": False})
                self.r.plan.clear()
                self.r.plan.update(backup)
                self.r.tracks = {t["id"]: t for t in self.r.plan["tracks"]}
                for tid in changed:
                    self.cache.pop(tid, None)
                self.cache.update(saved)
                tried.add(name)
        for t in self.r.plan["tracks"]:
            t.pop("fader_base_db", None)
        return {"history": history, "final_score": round(s, 3), "final_metrics": _round(m), "result": res}


def _round(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, float):
            out[k] = round(v, 3) if math.isfinite(v) else None
        else:
            out[k] = v
    return out
