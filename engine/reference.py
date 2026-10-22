"""Referenzvergleich unter gleichen Lautheitsbedingungen.

Die Referenz wird nie kopiert: Vorschläge werden gedämpft (``match_amount``) und
begrenzt. Die Referenzdatei wird nicht Teil des Exports.
"""

from __future__ import annotations

import math

import numpy as np

from . import dsp
from . import loudness as lmod
from .analysis import NAMED_BANDS, THIRD_OCTAVE_CENTERS, spectrum, third_octave
from .optimizer import spectral_tilt
from .phase import side_to_mid_db


def _band_width(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    b1, a1 = dsp.biquad_coeffs("hpf", lo, sr, 0, 0.7071)
    b2, a2 = dsp.biquad_coeffs("lpf", hi, sr, 0, 0.7071)
    y = dsp.apply_biquad(dsp.apply_biquad(dsp.ensure_2d(x), b1, a1), b2, a2)
    return side_to_mid_db(y)


def _onset_strength(x: np.ndarray, sr: int) -> float:
    m = dsp.ensure_2d(x).mean(axis=1)
    hop = int(0.01 * sr)
    nb = len(m) // hop
    env = np.sqrt(np.mean(m[: nb * hop].reshape(nb, hop) ** 2, axis=1)) + 1e-9
    d = np.diff(20 * np.log10(env))
    return float(np.mean(np.maximum(d, 0)))


def profile_of(x: np.ndarray, sr: int) -> dict:
    x = dsp.ensure_2d(x)
    if x.shape[1] == 1:
        x = np.column_stack([x[:, 0], x[:, 0]])
    lm = lmod.measure(x, sr)
    f, p = spectrum(x, sr)
    tod = third_octave(f, p)
    total = float(np.sum(p[f >= 20])) + 1e-20
    bands = {k: 10 * math.log10(float(np.sum(p[(f >= lo) & (f < hi)])) / total + 1e-20) for k, (lo, hi) in NAMED_BANDS.items()}
    st = lmod.short_term_series(x, sr, 1.0)
    st = st[st > -70]
    return {
        "loudness": lm.to_dict(),
        "third_octave_db": (tod - lm.integrated_lufs).tolist() if math.isfinite(lm.integrated_lufs) else tod.tolist(),
        "bands_db": bands,
        "tilt_db_oct": spectral_tilt(x, sr),
        "width_low_db": _band_width(x, sr, 30, 200),
        "width_mid_db": _band_width(x, sr, 200, 4000),
        "width_high_db": _band_width(x, sr, 4000, 16000),
        "onset_strength": _onset_strength(x, sr),
        "short_term_p10": float(np.percentile(st, 10)) if st.size else None,
        "short_term_p95": float(np.percentile(st, 95)) if st.size else None,
        "loudness_curve": [round(float(v), 2) for v in lmod.short_term_series(x, sr, 1.0)],
    }


def compare(mix: np.ndarray, ref: np.ndarray, sr_mix: int, sr_ref: int, match_amount: float = 0.5,
            max_eq_db: float = 2.0) -> dict:
    from .audio_io import resample

    if sr_ref != sr_mix:
        ref = resample(dsp.ensure_2d(ref), sr_ref, sr_mix)
    # Lautheitsangleich: beide auf -23 LUFS normalisieren (nur für den Vergleich)
    out = {}
    pm_raw = lmod.integrated_loudness(mix, sr_mix)
    pr_raw = lmod.integrated_loudness(ref, sr_mix)
    mixn = dsp.ensure_2d(mix) * dsp.db_to_lin(-23 - pm_raw)
    refn = dsp.ensure_2d(ref) * dsp.db_to_lin(-23 - pr_raw)
    pm, pr = profile_of(mixn, sr_mix), profile_of(refn, sr_mix)
    out["mix"], out["reference"] = pm, pr
    out["loudness_difference_lu"] = round(pr_raw - pm_raw, 2)
    diff_bands = {k: round(pr["bands_db"][k] - pm["bands_db"][k], 2) for k in pm["bands_db"]}
    out["band_difference_db"] = diff_bands
    out["tilt_difference"] = round(pr["tilt_db_oct"] - pm["tilt_db_oct"], 3)
    out["width_difference_db"] = {k: round(pr[k] - pm[k], 2) for k in ("width_low_db", "width_mid_db", "width_high_db")}
    out["transient_ratio"] = round(pr["onset_strength"] / max(pm["onset_strength"], 1e-6), 3)
    if pm["short_term_p95"] is not None and pr["short_term_p95"] is not None:
        out["dynamics"] = {
            "mix_spread_lu": round(pm["short_term_p95"] - pm["short_term_p10"], 2),
            "ref_spread_lu": round(pr["short_term_p95"] - pr["short_term_p10"], 2),
        }
    sugg = []
    eq = []
    centers = {"sub": 40, "bass": 120, "low_mid": 350, "mid": 1000, "high_mid": 2800, "presence": 5600, "air": 12000}
    for k, d in diff_bands.items():
        g = float(np.clip(d * match_amount, -max_eq_db, max_eq_db))
        if abs(g) >= 0.5:
            kind = "lowshelf" if k == "sub" else ("highshelf" if k == "air" else "bell")
            eq.append({"type": kind, "freq": float(centers[k]), "gain_db": round(g, 2), "q": 0.8})
            sugg.append(f"{k}: Referenz {d:+.1f} dB -> Vorschlag {g:+.1f} dB (gedämpft mit Faktor {match_amount})")
    if out["transient_ratio"] > 1.3:
        sugg.append("Referenz hat deutlich stärkere Transienten: weniger Bus-/Limiter-Kompression erwägen")
    elif out["transient_ratio"] < 0.75:
        sugg.append("Mix hat stärkere Transienten als die Referenz (gut für Dynamik; kein automatischer Eingriff)")
    wd = out["width_difference_db"]["width_mid_db"]
    if abs(wd) > 3:
        sugg.append(f"Stereobreite Mitten: Referenz {wd:+.1f} dB {'breiter' if wd > 0 else 'schmaler'}")
    out["suggested_master_eq"] = eq
    out["suggestions"] = sugg
    out["note"] = ("Vergleich bei gleicher Lautheit (-23 LUFS). Vorschläge sind gedämpft und begrenzt; "
                   "die Referenz wird nicht kopiert und nicht exportiert.")
    return out


__all__ = ["compare", "profile_of", "THIRD_OCTAVE_CENTERS"]
