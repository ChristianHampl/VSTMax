"""Lautheitsmessung nach ITU-R BS.1770-4 / EBU R128 (Tech 3341/3342).

Eigene Implementierung: K-Filter für beliebige Sample-Rates (bilineare Herleitung wie
in libebur128), Gating (absolut -70 LUFS, relativ -10 LU), Momentary (400 ms),
Short-term (3 s), Loudness Range (Tech 3342) und True Peak (4x Oversampling).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
from scipy.signal import lfilter

from .dsp import ensure_2d, true_peak

ABS_GATE = -70.0
REL_GATE_I = -10.0
REL_GATE_LRA = -20.0


def k_filter_coeffs(sr: int) -> list[tuple[np.ndarray, np.ndarray]]:
    # Stufe 1: High-Shelf (Kopf-Modell)
    f0 = 1681.974450955533
    G = 3.999843853973347
    Q = 0.7071752369554196
    K = math.tan(math.pi * f0 / sr)
    Vh = 10 ** (G / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / Q + K * K
    b1 = np.array([(Vh + Vb * K / Q + K * K) / a0, 2.0 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0])
    a1 = np.array([1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0])
    # Stufe 2: RLB-Hochpass
    f0 = 38.13547087602444
    Q = 0.5003270373238773
    K = math.tan(math.pi * f0 / sr)
    den = 1.0 + K / Q + K * K
    b2 = np.array([1.0, -2.0, 1.0])
    a2 = np.array([1.0, 2.0 * (K * K - 1.0) / den, (1.0 - K / Q + K * K) / den])
    return [(b1, a1), (b2, a2)]


def k_weight(x: np.ndarray, sr: int) -> np.ndarray:
    y = ensure_2d(x)
    for b, a in k_filter_coeffs(sr):
        y = lfilter(b, a, y, axis=0)
    return y


def _channel_weights(nch: int) -> np.ndarray:
    w = np.ones(nch)
    if nch == 5:
        w[3:] = 1.41
    elif nch >= 6:  # L R C LFE Ls Rs
        w[3] = 0.0
        w[4:6] = 1.41
    return w


def _block_energies(xk: np.ndarray, sr: int, block_s: float, overlap: float) -> np.ndarray:
    n = xk.shape[0]
    size = int(round(block_s * sr))
    step = max(1, int(round(size * (1.0 - overlap))))
    if n < size:
        return np.zeros(0)
    w = _channel_weights(xk.shape[1])
    csum = np.vstack([np.zeros((1, xk.shape[1])), np.cumsum(xk ** 2, axis=0)])
    starts = np.arange(0, n - size + 1, step)
    ms = (csum[starts + size] - csum[starts]) / size
    return ms @ w


def _to_lufs(e):
    return -0.691 + 10.0 * np.log10(np.maximum(e, 1e-20))


def integrated_from_blocks(z: np.ndarray) -> float:
    if z.size == 0:
        return float("-inf")
    l = _to_lufs(z)
    z1 = z[l > ABS_GATE]
    if z1.size == 0:
        return float("-inf")
    rel = _to_lufs(z1.mean()) + REL_GATE_I
    z2 = z1[_to_lufs(z1) > rel]
    if z2.size == 0:
        return float("-inf")
    return float(_to_lufs(z2.mean()))


@dataclass
class LoudnessResult:
    integrated_lufs: float
    momentary_max_lufs: float
    short_term_max_lufs: float
    loudness_range_lu: float
    true_peak_dbtp: float
    sample_peak_dbfs: float
    plr_db: float  # Peak-to-Loudness-Ratio (True Peak - integrierte Lautheit)

    def to_dict(self) -> dict:
        return {k: (None if (isinstance(v, float) and not math.isfinite(v)) else round(v, 3)) for k, v in asdict(self).items()}


def short_term_series(x: np.ndarray, sr: int, step_s: float = 0.1) -> np.ndarray:
    xk = k_weight(x, sr)
    z = _block_energies(xk, sr, 3.0, 1.0 - step_s / 3.0)
    return _to_lufs(z) if z.size else np.zeros(0)


def loudness_range(x: np.ndarray, sr: int, xk: np.ndarray | None = None) -> float:
    xk = k_weight(x, sr) if xk is None else xk
    z = _block_energies(xk, sr, 3.0, 2.9 / 3.0)  # Short-term, 10 Hz Rate
    if z.size == 0:
        return 0.0
    l = _to_lufs(z)
    z1 = z[l > ABS_GATE]
    if z1.size == 0:
        return 0.0
    rel = _to_lufs(z1.mean()) + REL_GATE_LRA
    l2 = _to_lufs(z1[_to_lufs(z1) > rel])
    if l2.size < 2:
        return 0.0
    return float(np.percentile(l2, 95) - np.percentile(l2, 10))


def integrated_loudness(x: np.ndarray, sr: int) -> float:
    xk = k_weight(x, sr)
    return integrated_from_blocks(_block_energies(xk, sr, 0.4, 0.75))


def measure(x: np.ndarray, sr: int, with_true_peak: bool = True) -> LoudnessResult:
    x = ensure_2d(x)
    xk = k_weight(x, sr)
    zm = _block_energies(xk, sr, 0.4, 0.75)
    integ = integrated_from_blocks(zm)
    mmax = float(_to_lufs(zm).max()) if zm.size else float("-inf")
    zs = _block_energies(xk, sr, 3.0, 2.9 / 3.0)
    smax = float(_to_lufs(zs).max()) if zs.size else float("-inf")
    lra = loudness_range(x, sr, xk)
    sp = float(np.max(np.abs(x))) if x.size else 0.0
    sp_db = 20 * math.log10(sp) if sp > 0 else float("-inf")
    if with_true_peak:
        tp = true_peak(x, sr)
        tp_db = 20 * math.log10(tp) if tp > 0 else float("-inf")
    else:
        tp_db = sp_db
    plr = tp_db - integ if math.isfinite(integ) and math.isfinite(tp_db) else float("nan")
    return LoudnessResult(integ, mmax, smax, lra, tp_db, sp_db, plr)
