"""Frequenzmaskierung und zeitliche Überlappung zwischen Spuren."""

from __future__ import annotations

import math

import numpy as np

from .analysis import THIRD_OCTAVE_CENTERS, TrackAnalysis

# Rollenpaare, die im Rock/Metal typischerweise konkurrieren, mit relevantem Bereich (Hz)
CRITICAL_PAIRS = [
    ("kick", "bass", (35, 250)),
    ("bass", "rhythm_guitar", (80, 400)),
    ("rhythm_guitar", "lead_vocal", (800, 5000)),
    ("rhythm_guitar", "scream_vocal", (800, 5000)),
    ("lead_guitar", "lead_vocal", (600, 5000)),
    ("snare", "rhythm_guitar", (150, 6000)),
    ("kick", "rhythm_guitar", (1500, 6000)),
    ("synth", "lead_vocal", (300, 5000)),
    ("backing_vocal", "lead_vocal", (200, 6000)),
]


def temporal_overlap(a: TrackAnalysis, b: TrackAnalysis, active_db: float = -45.0) -> float:
    n = min(len(a.activity), len(b.activity))
    if n == 0:
        return 0.0
    aa = np.array(a.activity[:n]) > active_db
    bb = np.array(b.activity[:n]) > active_db
    denom = min(aa.sum(), bb.sum())
    if denom == 0:
        return 0.0
    return float(np.sum(aa & bb) / denom)


def band_levels(a: TrackAnalysis, gain_db: float = 0.0) -> np.ndarray:
    """Absolute Terzbandpegel (dB) inkl. Gain-Korrektur."""
    return np.array(a.third_octave_db) + gain_db


def masking_conflicts(a: TrackAnalysis, b: TrackAnalysis, freq_range: tuple[float, float],
                      gain_a: float = 0.0, gain_b: float = 0.0, max_conflicts: int = 2) -> list[dict]:
    """Findet Terzbänder, in denen beide Spuren stark und ähnlich laut sind."""
    la, lb = band_levels(a, gain_a), band_levels(b, gain_b)
    ta, tb = la.max(), lb.max()
    m = (THIRD_OCTAVE_CENTERS >= freq_range[0]) & (THIRD_OCTAVE_CENTERS <= freq_range[1])
    overlap = temporal_overlap(a, b)
    out = []
    for i in np.where(m)[0]:
        # beide Spuren müssen in diesem Band relevant sein (innerhalb 15 dB ihres Maximums)
        if la[i] < ta - 15 or lb[i] < tb - 15:
            continue
        diff = la[i] - lb[i]
        if abs(diff) > 6:
            continue
        sev = (1 - abs(diff) / 6) * overlap * (1 - max(ta - la[i], tb - lb[i]) / 15)
        if sev > 0.15:
            out.append({"freq": float(THIRD_OCTAVE_CENTERS[i]), "level_diff_db": round(float(diff), 2),
                        "severity": round(float(sev), 3), "overlap": round(overlap, 3)})
    out.sort(key=lambda c: c["severity"], reverse=True)
    # benachbarte Bänder zusammenfassen
    merged: list[dict] = []
    for c in out:
        if all(abs(math.log2(c["freq"] / m_["freq"])) > 0.5 for m_ in merged):
            merged.append(c)
        if len(merged) >= max_conflicts:
            break
    return merged


def find_conflicts(roles: dict[str, str], analyses: dict[str, TrackAnalysis],
                   gains: dict[str, float] | None = None) -> list[dict]:
    gains = gains or {}
    by_role: dict[str, list[str]] = {}
    for tid, r in roles.items():
        by_role.setdefault(r, []).append(tid)
    conflicts = []
    for ra, rb, rng in CRITICAL_PAIRS:
        for ta in by_role.get(ra, []):
            for tb in by_role.get(rb, []):
                if ta == tb:
                    continue
                for c in masking_conflicts(analyses[ta], analyses[tb], rng, gains.get(ta, 0.0), gains.get(tb, 0.0)):
                    conflicts.append({"a": ta, "b": tb, "role_a": ra, "role_b": rb, **c})
    conflicts.sort(key=lambda c: c["severity"], reverse=True)
    return conflicts


def masking_score(conflicts: list[dict]) -> float:
    return float(sum(c["severity"] for c in conflicts))
