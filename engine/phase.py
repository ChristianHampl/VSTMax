"""Phasen-, Korrelations- und Duplikatanalyse."""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import fftconvolve

from .dsp import ensure_2d


def stereo_correlation(x: np.ndarray) -> float:
    x = ensure_2d(x)
    if x.shape[1] < 2:
        return 1.0
    l, r = x[:, 0], x[:, 1]
    den = math.sqrt(float(np.sum(l * l)) * float(np.sum(r * r)))
    if den < 1e-12:
        return 1.0
    return float(np.sum(l * r) / den)


def correlation_over_time(x: np.ndarray, sr: int, window_s: float = 0.4) -> np.ndarray:
    x = ensure_2d(x)
    if x.shape[1] < 2:
        return np.ones(1)
    n = int(window_s * sr)
    nb = x.shape[0] // n
    if nb == 0:
        return np.array([stereo_correlation(x)])
    l = x[: nb * n, 0].reshape(nb, n)
    r = x[: nb * n, 1].reshape(nb, n)
    num = np.sum(l * r, axis=1)
    den = np.sqrt(np.sum(l * l, axis=1) * np.sum(r * r, axis=1))
    valid = den > 1e-9
    out = np.ones(nb)
    out[valid] = num[valid] / den[valid]
    return out


def mono_compatibility_db(x: np.ndarray) -> float:
    """Pegeländerung (dB) der Mono-Summe (L+R)/2 relativ zum mittleren Kanalpegel.

    0 dB = identische Kanäle, ca. -3 dB = unkorreliert, stark negativ = Auslöschung.
    """
    x = ensure_2d(x)
    if x.shape[1] < 2:
        return 0.0
    stereo_e = 0.5 * (np.mean(x[:, 0] ** 2) + np.mean(x[:, 1] ** 2))
    mono_e = np.mean((0.5 * (x[:, 0] + x[:, 1])) ** 2)
    if stereo_e < 1e-20:
        return 0.0
    return float(10 * math.log10(max(mono_e, 1e-20) / stereo_e))


def side_to_mid_db(x: np.ndarray) -> float:
    x = ensure_2d(x)
    if x.shape[1] < 2:
        return -120.0
    m = 0.5 * (x[:, 0] + x[:, 1])
    s = 0.5 * (x[:, 0] - x[:, 1])
    em, es = np.mean(m * m), np.mean(s * s)
    if em < 1e-20:
        return 0.0 if es > 1e-20 else -120.0
    return float(10 * math.log10(max(es, 1e-20) / em))


def _limit_len(x: np.ndarray, sr: int, max_s: float) -> np.ndarray:
    n = int(max_s * sr)
    if x.shape[0] <= n:
        return x
    # energiereichsten Abschnitt verwenden
    hop = n // 4
    best, best_e = 0, -1.0
    for s in range(0, x.shape[0] - n, hop):
        e = float(np.sum(x[s:s + n] ** 2))
        if e > best_e:
            best, best_e = s, e
    return x[best:best + n]


def cross_correlation(a: np.ndarray, b: np.ndarray, sr: int, max_lag_ms: float = 10.0,
                      max_s: float = 30.0) -> tuple[float, int]:
    """Normierte Kreuzkorrelation (Mono). Gibt (Korrelation am Maximum, Lag in Samples) zurück.

    Positiver Lag: ``b`` ist gegenüber ``a`` verzögert.
    """
    a = ensure_2d(a).mean(axis=1)
    b = ensure_2d(b).mean(axis=1)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    ab = _limit_len(np.column_stack([a, b]), sr, max_s)
    a, b = ab[:, 0], ab[:, 1]
    den = math.sqrt(float(np.sum(a * a)) * float(np.sum(b * b)))
    if den < 1e-12:
        return 0.0, 0
    full = fftconvolve(b, a[::-1], mode="full")
    center = len(a) - 1
    m = int(max_lag_ms * 1e-3 * sr)
    seg = full[center - m:center + m + 1]
    idx = int(np.argmax(np.abs(seg)))
    return float(seg[idx] / den), idx - m


def polarity_and_alignment(a: np.ndarray, b: np.ndarray, sr: int, max_lag_ms: float = 10.0) -> dict:
    corr, lag = cross_correlation(a, b, sr, max_lag_ms)
    return {
        "correlation": round(corr, 4),
        "lag_samples": lag,
        "lag_ms": round(lag * 1000.0 / sr, 3),
        "polarity_inverted": bool(corr < -0.3),
        "related": bool(abs(corr) > 0.3),
    }


def envelope(x: np.ndarray, sr: int, hop_s: float = 0.02) -> np.ndarray:
    x = ensure_2d(x).mean(axis=1)
    hop = max(1, int(hop_s * sr))
    nb = len(x) // hop
    if nb == 0:
        return np.zeros(1)
    return np.sqrt(np.mean(x[: nb * hop].reshape(nb, hop) ** 2, axis=1))


def similarity(a: np.ndarray, b: np.ndarray, sr: int, spec_a: np.ndarray | None = None,
               spec_b: np.ndarray | None = None) -> dict:
    """Unterscheidet Duplikate, echte Doppelspuren und unabhängige Spuren.

    - ``waveform_corr`` hoch (>0.95): Kopie / Duplikat (Panning bringt keine echte Breite)
    - Hüllkurven- und Spektrumähnlichkeit hoch, Wellenform niedrig: echtes Double-Tracking
    """
    wc, lag = cross_correlation(a, b, sr, max_lag_ms=5.0)
    ea, eb = envelope(a, sr), envelope(b, sr)
    n = min(len(ea), len(eb))
    ea, eb = ea[:n], eb[:n]
    if n > 2 and np.std(ea) > 1e-9 and np.std(eb) > 1e-9:
        env_corr = float(np.corrcoef(ea, eb)[0, 1])
    else:
        env_corr = 0.0
    spec_dist = None
    if spec_a is not None and spec_b is not None:
        da = spec_a - np.mean(spec_a)
        db = spec_b - np.mean(spec_b)
        spec_dist = float(np.sqrt(np.mean((da - db) ** 2)))
    duplicate = abs(wc) > 0.95
    double_track = (not duplicate) and env_corr > 0.6 and abs(wc) < 0.6 and (spec_dist is None or spec_dist < 4.0)
    return {
        "waveform_corr": round(wc, 4),
        "lag_samples": lag,
        "envelope_corr": round(env_corr, 4),
        "spectral_distance_db": None if spec_dist is None else round(spec_dist, 3),
        "duplicate": bool(duplicate),
        "double_track": bool(double_track),
    }
