"""Qualitätsprüfungen: Überkompression, Verzerrung, Clipping, Projektkonsistenz."""

from __future__ import annotations

import math

import numpy as np

from . import dsp
from . import loudness as lmod
from .phase import mono_compatibility_db


def _crest(x: np.ndarray) -> float:
    pk = float(np.max(np.abs(x))) + 1e-12
    rms = float(np.sqrt(np.mean(x ** 2))) + 1e-12
    return 20 * math.log10(pk / rms)


def _short_crest(x: np.ndarray, sr: int) -> float:
    """Median-Crest-Faktor über 400-ms-Fenster (empfindlich für Transientenverlust)."""
    x = dsp.ensure_2d(x).mean(axis=1)
    n = int(0.4 * sr)
    nb = len(x) // n
    if nb < 2:
        return _crest(x)
    seg = x[: nb * n].reshape(nb, n)
    pk = np.max(np.abs(seg), axis=1) + 1e-12
    rms = np.sqrt(np.mean(seg ** 2, axis=1)) + 1e-12
    act = rms > rms.max() * 10 ** (-30 / 20)
    return float(np.median(20 * np.log10(pk[act] / rms[act])))


def compare_quality(reference: np.ndarray, processed: np.ndarray, sr: int, settings=None) -> dict:
    """Vergleicht pegelangepasstes Signal vor dem Limiter mit dem Ergebnis."""
    ref = dsp.ensure_2d(reference)
    y = dsp.ensure_2d(processed)
    n = min(ref.shape[0], y.shape[0])
    ref, y = ref[:n], y[:n]
    flags: list[dict] = []
    res = {}
    if not np.all(np.isfinite(y)):
        flags.append({"severity": "fail", "code": "nan", "message": "Ergebnis enthält NaN/Inf"})
        return {"verdict": "fail", "flags": flags, "metrics": {}}
    res["crest_before_db"] = _short_crest(ref, sr)
    res["crest_after_db"] = _short_crest(y, sr)
    res["crest_drop_db"] = res["crest_before_db"] - res["crest_after_db"]
    lb = lmod.measure(ref, sr, with_true_peak=False)
    la = lmod.measure(y, sr)
    res["lra_before"] = lb.loudness_range_lu
    res["lra_after"] = la.loudness_range_lu
    res["plr_db"] = la.plr_db
    res["true_peak_dbtp"] = la.true_peak_dbtp
    resid = ref - y
    e_y = float(np.mean(y ** 2)) + 1e-20
    res["limiter_residual_db"] = 10 * math.log10(float(np.mean(resid ** 2)) / e_y + 1e-20)
    b, a = dsp.biquad_coeffs("hpf", 5000, sr, 0, 0.7071)
    hr = dsp.apply_biquad(resid, b, a)
    hy = dsp.apply_biquad(y, b, a)
    res["hf_residual_db"] = 10 * math.log10((float(np.mean(hr ** 2)) + 1e-20) / (float(np.mean(hy ** 2)) + 1e-20))
    res["clipped_samples"] = int(np.sum(np.abs(y) >= 0.9999))
    res["mono_compat_db"] = mono_compatibility_db(y)

    if res["crest_drop_db"] > 5.0:
        flags.append({"severity": "fail", "code": "overcompressed",
                      "message": f"Transienten stark reduziert (Crest -{res['crest_drop_db']:.1f} dB)"})
    elif res["crest_drop_db"] > 3.0:
        flags.append({"severity": "warn", "code": "compressed",
                      "message": f"Deutliche Transientenreduktion (Crest -{res['crest_drop_db']:.1f} dB)"})
    min_plr = getattr(settings, "min_plr_db", 8.0) if settings else 8.0
    if math.isfinite(res["plr_db"]) and res["plr_db"] < min_plr - 0.5:
        flags.append({"severity": "warn", "code": "low_plr",
                      "message": f"Peak-to-Loudness-Ratio {res['plr_db']:.1f} dB unter Ziel {min_plr:.1f} dB"})
    if res["limiter_residual_db"] > -18.0:
        flags.append({"severity": "fail", "code": "distortion",
                      "message": f"Limiter entfernt viel Signal ({res['limiter_residual_db']:.1f} dB) - hörbare Verzerrung wahrscheinlich"})
    elif res["limiter_residual_db"] > -26.0:
        flags.append({"severity": "warn", "code": "limiter_audible",
                      "message": f"Limiter-Eingriff möglicherweise hörbar ({res['limiter_residual_db']:.1f} dB)"})
    if res["lra_before"] - res["lra_after"] > 3.0:
        flags.append({"severity": "warn", "code": "lra_collapse",
                      "message": f"Loudness Range um {res['lra_before'] - res['lra_after']:.1f} LU reduziert"})
    if res["clipped_samples"]:
        flags.append({"severity": "fail", "code": "clipping", "message": f"{res['clipped_samples']} Samples auf Vollaussteuerung"})
    ceiling = getattr(settings, "true_peak_db", -1.0) if settings else -1.0
    if res["true_peak_dbtp"] > ceiling + 0.1:
        flags.append({"severity": "fail", "code": "true_peak",
                      "message": f"True Peak {res['true_peak_dbtp']:.2f} dBTP über Grenze {ceiling:.1f}"})
    if res["mono_compat_db"] < -6.0:
        flags.append({"severity": "warn", "code": "mono", "message": f"Mono-Kompatibilität schwach ({res['mono_compat_db']:.1f} dB)"})
    verdict = "fail" if any(f["severity"] == "fail" for f in flags) else ("warn" if flags else "ok")
    return {"verdict": verdict, "flags": flags,
            "metrics": {k: (round(v, 3) if isinstance(v, float) and math.isfinite(v) else v) for k, v in res.items()}}


def check_project_consistency(infos: list[dict]) -> list[dict]:
    """Prüft Sample-Rate und Länge aller Spuren (infos aus AudioData.info())."""
    issues = []
    if not infos:
        return [{"severity": "fail", "code": "empty", "message": "Keine Spuren geladen"}]
    srs = {i["sample_rate"] for i in infos}
    if len(srs) > 1:
        issues.append({"severity": "warn", "code": "sample_rate_mismatch",
                       "message": f"Unterschiedliche Sample-Rates {sorted(srs)} - werden auf die häufigste umgerechnet"})
    durs = [i["duration_s"] for i in infos]
    if max(durs) - min(durs) > 0.05:
        issues.append({"severity": "info", "code": "length_mismatch",
                       "message": f"Spurlängen unterschiedlich ({min(durs):.2f}-{max(durs):.2f} s); kürzere werden mit Stille aufgefüllt. "
                                  "Für Cubase-Stems: immer ab Projektanfang exportieren."})
    return issues
