"""Mastering: Tonal-Korrektur, Bus-Kompression, True-Peak-Limiting, Qualitätsprüfung.

Lautheitsziel und True-Peak-Grenze hängen vom Verwendungszweck ab. Wenn das Ziel nur
mit unzulässiger Limiter-Arbeit (Überkompression) erreichbar wäre, wird das Ziel
bewusst verfehlt und dies im Bericht dokumentiert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import dsp
from . import loudness as lmod
from .optimizer import spectral_tilt
from .validation import compare_quality

# Zielprofile nach Verwendungszweck (konservativ, wenn nichts angegeben)
PURPOSES = {
    "conservative": {"name": "Konservativ / Streaming-normalisiert", "target_lufs": -14.0, "true_peak_db": -1.0},
    "streaming_loud": {"name": "Streaming laut", "target_lufs": -10.0, "true_peak_db": -1.0},
    "cd_club": {"name": "CD / Club", "target_lufs": -9.0, "true_peak_db": -0.3},
    "broadcast_r128": {"name": "Rundfunk EBU R128", "target_lufs": -23.0, "true_peak_db": -1.0},
    "profile": {"name": "Genre-Profil", "target_lufs": None, "true_peak_db": None},
}


@dataclass
class MasterSettings:
    target_lufs: float = -14.0
    true_peak_db: float = -1.0
    max_limiter_gr_db: float = 4.0
    min_plr_db: float = 8.0
    bus_comp: bool = True
    eq_enabled: bool = True
    eq_max_db: float = 1.5
    target_tilt_db_oct: float = -4.5
    reference_eq: list = field(default_factory=list)  # optionale Korrekturen aus Referenzvergleich

    @classmethod
    def from_profile(cls, profile_master: dict, mix_target: dict, purpose: str = "profile") -> "MasterSettings":
        s = cls(
            target_lufs=profile_master.get("target_lufs", -14.0),
            true_peak_db=profile_master.get("true_peak_db", -1.0),
            max_limiter_gr_db=profile_master.get("max_limiter_gr_db", 4.0),
            min_plr_db=profile_master.get("min_plr_db", 8.0),
            bus_comp=profile_master.get("bus_comp", True),
            eq_max_db=profile_master.get("eq_max_db", 1.5),
            target_tilt_db_oct=mix_target.get("tilt_db_per_oct", -4.5),
        )
        p = PURPOSES.get(purpose)
        if p and p["target_lufs"] is not None:
            s.target_lufs = p["target_lufs"]
            s.true_peak_db = p["true_peak_db"]
        return s


def _tilt_eq(tilt_err: float, max_db: float) -> list[dict]:
    """Korrigiert eine Steigungsabweichung (dB/Okt) mit zwei sanften Shelves."""
    if abs(tilt_err) < 0.3:
        return []
    g = float(np.clip(-tilt_err * 1.5, -max_db, max_db))
    return [
        {"type": "lowshelf", "freq": 150.0, "gain_db": round(-g / 2, 2), "q": 0.6},
        {"type": "highshelf", "freq": 4000.0, "gain_db": round(g / 2, 2), "q": 0.6},
    ]


def master(mix: np.ndarray, sr: int, s: MasterSettings, log: list | None = None) -> tuple[np.ndarray, dict]:
    log = log if log is not None else []
    x = dsp.ensure_2d(mix).copy()
    if x.shape[1] == 1:
        x = np.column_stack([x[:, 0], x[:, 0]])
    before = lmod.measure(x, sr)
    report: dict = {"settings": s.__dict__.copy(), "before": before.to_dict(), "steps": []}

    # 1) EQ (subtil)
    eq_bands: list[dict] = []
    if s.eq_enabled:
        tilt = spectral_tilt(x, sr)
        err = tilt - s.target_tilt_db_oct
        eq_bands = _tilt_eq(err, s.eq_max_db)
        report["tilt_before_db_oct"] = round(tilt, 3)
        if eq_bands:
            log.append({"track": "master", "param": "eq", "value": eq_bands,
                        "reason": f"Spektrale Steigung {tilt:.2f} dB/Okt, Ziel {s.target_tilt_db_oct:.2f}"})
    for band in s.reference_eq:
        eq_bands.append(band)
        log.append({"track": "master", "param": "eq", "value": band, "reason": "Referenzvergleich (gedämpft)"})
    for band in eq_bands:
        x = dsp.apply_eq_band(x, sr, band)
    report["eq"] = eq_bands

    # 2) Bus-Kompression (Glue, max ca. 1.5-2 dB)
    if s.bus_comp:
        c = {"ratio": 1.8, "attack_ms": 30.0, "release_ms": 250.0, "knee_db": 8.0, "target_gr_db": 1.5}
        from .mixing import calibrate_comp

        thr = calibrate_comp(x, sr, c)
        pre = lmod.integrated_loudness(x, sr)
        x, cst = dsp.compress(x, sr, thr, c["ratio"], c["attack_ms"], c["release_ms"], c["knee_db"])
        post = lmod.integrated_loudness(x, sr)
        makeup = 0.0
        if math.isfinite(pre) and math.isfinite(post):
            makeup = pre - post
            x *= dsp.db_to_lin(makeup)
        report["bus_comp"] = {"threshold_db": thr, **c, "makeup_db": round(makeup, 3), "stats": cst}
        log.append({"track": "master", "param": "bus_comp", "value": thr,
                    "reason": f"Glue-Kompression {c['ratio']}:1, Ziel {c['target_gr_db']} dB GR"})

    # 3) Gain + True-Peak-Limiter (iterativ auf Ziel-LUFS, mit Überkompressionsschutz)
    pre_limit = x.copy()
    cur = lmod.integrated_loudness(x, sr)
    gain = s.target_lufs - cur if math.isfinite(cur) else 0.0
    achieved_target = True
    lim_stats: dict = {}
    y = x
    for it in range(6):
        y, lim_stats = dsp.true_peak_limiter(x * dsp.db_to_lin(gain), sr, s.true_peak_db)
        lufs = lmod.integrated_loudness(y, sr)
        tp = 20 * math.log10(dsp.true_peak(y, sr) + 1e-12)
        over = lim_stats["max_gr_db"] > s.max_limiter_gr_db + 0.5 or (tp - lufs) < s.min_plr_db - 0.25
        report["steps"].append({"iteration": it, "gain_db": round(gain, 2), "lufs": round(lufs, 2),
                                "true_peak_dbtp": round(tp, 2), "limiter_max_gr_db": round(lim_stats["max_gr_db"], 2),
                                "plr_db": round(tp - lufs, 2), "overcompressed": bool(over)})
        if over:
            achieved_target = False
            gain -= max(0.5, lim_stats["max_gr_db"] - s.max_limiter_gr_db, (s.min_plr_db - (tp - lufs)))
            continue
        if abs(lufs - s.target_lufs) <= 0.2:
            break
        gain += s.target_lufs - lufs
    # Endgültige Kontrolle
    after = lmod.measure(y, sr)
    if achieved_target is False or abs(after.integrated_lufs - s.target_lufs) > 0.5:
        msg = (f"Ziel {s.target_lufs:.1f} LUFS nicht ohne Überkompression erreichbar - erreicht "
               f"{after.integrated_lufs:.1f} LUFS (Limiter max. {lim_stats.get('max_gr_db', 0):.1f} dB, "
               f"PLR {after.plr_db:.1f} dB)")
        report["target_note"] = msg
        log.append({"track": "master", "param": "target", "value": round(after.integrated_lufs, 2), "reason": msg,
                    "uncertain": True})
    report["gain_db"] = round(gain, 2)
    report["limiter"] = {"ceiling_dbtp": s.true_peak_db, **{k: round(v, 3) if isinstance(v, float) else v
                                                            for k, v in lim_stats.items()}}
    report["after"] = after.to_dict()
    gm = pre_limit * dsp.db_to_lin(gain)
    report["quality"] = compare_quality(gm, y, sr, s)
    return y, report
