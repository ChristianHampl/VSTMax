"""Offline-DSP-Bausteine (NumPy/SciPy).

Die Algorithmen entsprechen dem C++-Kern in ``dsp/core`` (gleiche Filterformeln,
gleiche Kennlinien). Dynamik-Hüllkurven werden aus Performancegründen blockweise
(``ENV_BLOCK`` Samples) berechnet und anschließend linear interpoliert.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d
from scipy.signal import lfilter, resample_poly

ENV_BLOCK = 32
EPS = 1e-12


def db_to_lin(db):
    return np.power(10.0, np.asarray(db, dtype=np.float64) / 20.0)


def lin_to_db(x, floor_db: float = -150.0):
    x = np.maximum(np.abs(np.asarray(x, dtype=np.float64)), 10 ** (floor_db / 20.0))
    return 20.0 * np.log10(x)


def ensure_2d(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    return x[:, None] if x.ndim == 1 else x


def sanitize(x: np.ndarray) -> np.ndarray:
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


# ---------------------------------------------------------------- Biquads (RBJ)

def biquad_coeffs(kind: str, freq: float, sr: int, gain_db: float = 0.0, q: float = 0.7071) -> tuple[np.ndarray, np.ndarray]:
    """RBJ-Audio-EQ-Cookbook. Gibt (b, a) normiert auf a0 = 1 zurück."""
    freq = float(np.clip(freq, 10.0, 0.49 * sr))
    q = float(max(q, 0.05))
    A = 10 ** (gain_db / 40.0)
    w0 = 2 * math.pi * freq / sr
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    if kind == "bell":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif kind == "lowshelf":
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
        a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
    elif kind == "highshelf":
        sq = 2 * math.sqrt(A) * alpha
        b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
        a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    elif kind == "hpf":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "lpf":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif kind == "bandpass":  # 0 dB Spitzenverstärkung
        b = [alpha, 0.0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    else:
        raise ValueError(f"Unbekannter Filtertyp: {kind}")
    a0 = a[0]
    return np.array(b) / a0, np.array(a) / a0


def magnitude_db(b: np.ndarray, a: np.ndarray, freqs: np.ndarray, sr: int) -> np.ndarray:
    z = np.exp(-1j * 2 * np.pi * np.asarray(freqs) / sr)
    num = b[0] + b[1] * z + b[2] * z * z
    den = a[0] + a[1] * z + a[2] * z * z
    return 20 * np.log10(np.maximum(np.abs(num / den), EPS))


def apply_biquad(x: np.ndarray, b: np.ndarray, a: np.ndarray) -> np.ndarray:
    return lfilter(b, a, ensure_2d(x), axis=0)


def apply_eq_band(x: np.ndarray, sr: int, band: dict) -> np.ndarray:
    kind = band["type"]
    order = int(band.get("order", 2))
    b, a = biquad_coeffs(kind, band["freq"], sr, band.get("gain_db", 0.0), band.get("q", 0.7071))
    y = apply_biquad(x, b, a)
    if kind in ("hpf", "lpf") and order >= 4:  # 24 dB/Okt = zwei Butterworth-Stufen
        y = apply_biquad(y, b, a)
    return y


# ------------------------------------------------------------ Hüllkurven/Dynamik

def time_coef(ms: float, sr: float) -> float:
    ms = max(float(ms), 0.01)
    return math.exp(-1.0 / (ms * 0.001 * sr))


def block_peak(x: np.ndarray, block: int = ENV_BLOCK) -> np.ndarray:
    """Spitzenwert (max über Kanäle) je Block."""
    mono = np.max(np.abs(ensure_2d(x)), axis=1)
    n = len(mono)
    nb = int(math.ceil(n / block))
    pad = nb * block - n
    if pad:
        mono = np.concatenate([mono, np.zeros(pad)])
    return mono.reshape(nb, block).max(axis=1)


def block_rms(x: np.ndarray, block: int = ENV_BLOCK) -> np.ndarray:
    sq = np.mean(ensure_2d(x) ** 2, axis=1)
    n = len(sq)
    nb = int(math.ceil(n / block))
    pad = nb * block - n
    if pad:
        sq = np.concatenate([sq, np.zeros(pad)])
    return np.sqrt(sq.reshape(nb, block).mean(axis=1))


def smooth_ballistics(target: np.ndarray, attack_coef: float, release_coef: float, start: float) -> np.ndarray:
    """Attack/Release-Glättung eines Zielwerts (z. B. Gain Reduction in dB, >= 0)."""
    out = np.empty_like(target)
    s = start
    for i, t in enumerate(target):
        c = attack_coef if t > s else release_coef
        s = t + c * (s - t)
        out[i] = s
    return out


def expand_blocks(values: np.ndarray, n: int, block: int = ENV_BLOCK) -> np.ndarray:
    centers = np.arange(len(values)) * block + block / 2.0
    return np.interp(np.arange(n), centers, values)


def compressor_gain_computer(level_db: np.ndarray, threshold_db: float, ratio: float, knee_db: float) -> np.ndarray:
    """Statische Kennlinie, gibt Gain Reduction in dB (>= 0) zurück."""
    ratio = max(ratio, 1.0)
    slope = 1.0 - 1.0 / ratio
    over = level_db - threshold_db
    gr = np.zeros_like(level_db)
    if knee_db > 0:
        half = knee_db / 2.0
        in_knee = (over > -half) & (over < half)
        gr[in_knee] = slope * (over[in_knee] + half) ** 2 / (2 * knee_db)
        above = over >= half
        gr[above] = slope * over[above]
    else:
        above = over > 0
        gr[above] = slope * over[above]
    return gr


def compress(
    x: np.ndarray,
    sr: int,
    threshold_db: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
    knee_db: float = 6.0,
    makeup_db: float = 0.0,
    mix: float = 1.0,
    detector: str = "peak",
    sidechain: np.ndarray | None = None,
) -> tuple[np.ndarray, dict]:
    x = ensure_2d(x)
    sc = ensure_2d(sidechain) if sidechain is not None else x
    lvl = block_rms(sc) if detector == "rms" else block_peak(sc)
    lvl_db = lin_to_db(lvl)
    target = compressor_gain_computer(lvl_db, threshold_db, ratio, knee_db)
    bsr = sr / ENV_BLOCK
    gr = smooth_ballistics(target, time_coef(attack_ms, bsr), time_coef(release_ms, bsr), 0.0)
    gain = db_to_lin(-expand_blocks(gr, x.shape[0]) + makeup_db)
    y = x * gain[:, None]
    if mix < 1.0:
        y = mix * y + (1.0 - mix) * x
    stats = {
        "max_gr_db": float(gr.max()) if gr.size else 0.0,
        "avg_gr_db": float(gr[lvl_db > -60].mean()) if np.any(lvl_db > -60) else 0.0,
    }
    return y, stats


def gate(
    x: np.ndarray,
    sr: int,
    threshold_db: float,
    range_db: float = 40.0,
    attack_ms: float = 0.5,
    hold_ms: float = 30.0,
    release_ms: float = 80.0,
) -> tuple[np.ndarray, dict]:
    x = ensure_2d(x)
    lvl_db = lin_to_db(block_peak(x))
    is_open = lvl_db > threshold_db
    hold_blocks = max(1, int(hold_ms * 1e-3 * sr / ENV_BLOCK))
    is_open = maximum_filter1d(is_open.astype(np.float64), size=2 * hold_blocks + 1, origin=-hold_blocks) > 0
    target = np.where(is_open, 0.0, range_db)
    bsr = sr / ENV_BLOCK
    att = smooth_ballistics(target, time_coef(release_ms, bsr), time_coef(attack_ms, bsr), range_db)
    gain = db_to_lin(-expand_blocks(att, x.shape[0]))
    return x * gain[:, None], {"open_ratio": float(np.mean(is_open)) if is_open.size else 0.0}


def split_band(x: np.ndarray, sr: int, freq: float, q: float = 0.7071, kind: str = "hpf") -> tuple[np.ndarray, np.ndarray]:
    """Perfekt rekonstruierende Aufteilung: x = rest + band."""
    b, a = biquad_coeffs(kind, freq, sr, 0.0, q)
    band = apply_biquad(x, b, a)
    return ensure_2d(x) - band, band


def deess(x: np.ndarray, sr: int, freq: float, threshold_db: float, range_db: float = 8.0,
          attack_ms: float = 1.0, release_ms: float = 60.0) -> tuple[np.ndarray, dict]:
    rest, high = split_band(x, sr, freq)
    lvl_db = lin_to_db(block_peak(high))
    target = np.clip(compressor_gain_computer(lvl_db, threshold_db, 4.0, 3.0), 0, range_db)
    bsr = sr / ENV_BLOCK
    gr = smooth_ballistics(target, time_coef(attack_ms, bsr), time_coef(release_ms, bsr), 0.0)
    g = db_to_lin(-expand_blocks(gr, high.shape[0]))
    return rest + high * g[:, None], {"max_gr_db": float(gr.max()) if gr.size else 0.0}


def dynamic_band(x: np.ndarray, sr: int, freq: float, q: float, threshold_db: float, range_db: float,
                 sidechain: np.ndarray | None = None, attack_ms: float = 5.0, release_ms: float = 120.0,
                 ratio: float = 3.0) -> tuple[np.ndarray, dict]:
    """Dynamische Absenkung eines Bandes (optional durch ein anderes Signal gesteuert)."""
    x = ensure_2d(x)
    b, a = biquad_coeffs("bandpass", freq, sr, 0.0, q)
    band = apply_biquad(x, b, a)
    sc_band = apply_biquad(ensure_2d(sidechain), b, a) if sidechain is not None else band
    lvl_db = lin_to_db(block_rms(sc_band))
    target = np.clip(compressor_gain_computer(lvl_db, threshold_db, ratio, 6.0), 0, abs(range_db))
    bsr = sr / ENV_BLOCK
    gr = smooth_ballistics(target, time_coef(attack_ms, bsr), time_coef(release_ms, bsr), 0.0)
    g = db_to_lin(-expand_blocks(gr, x.shape[0]))
    y = x + (g[:, None] - 1.0) * band
    return y, {"max_gr_db": float(gr.max()) if gr.size else 0.0,
               "avg_gr_db": float(gr.mean()) if gr.size else 0.0}


def saturate(x: np.ndarray, drive_db: float, mix: float = 1.0, oversample: int = 2) -> np.ndarray:
    """tanh-Sättigung, pegelkompensiert, mit Oversampling gegen Aliasing."""
    if drive_db <= 0.01 or mix <= 0.0:
        return ensure_2d(x)
    x = ensure_2d(x)
    d = db_to_lin(drive_db)
    up = resample_poly(x, oversample, 1, axis=0) if oversample > 1 else x
    sat = np.tanh(up * d) / np.tanh(d)
    y = resample_poly(sat, 1, oversample, axis=0)[: x.shape[0]] if oversample > 1 else sat
    return mix * y + (1.0 - mix) * x


def pan_stereo(x: np.ndarray, pan: float) -> np.ndarray:
    """Constant-Power-Panning (-3 dB Mitte). Stereo-Quellen werden balanciert."""
    x = ensure_2d(x)
    pan = float(np.clip(pan, -1.0, 1.0))
    theta = (pan + 1.0) * math.pi / 4.0
    gl, gr = math.cos(theta), math.sin(theta)
    if x.shape[1] == 1:
        return np.column_stack([x[:, 0] * gl, x[:, 0] * gr])
    norm = math.sqrt(2.0)
    return np.column_stack([x[:, 0] * gl * norm, x[:, 1] * gr * norm])


def stereo_width(x: np.ndarray, width: float) -> np.ndarray:
    x = ensure_2d(x)
    if x.shape[1] < 2:
        return x
    m = 0.5 * (x[:, 0] + x[:, 1])
    s = 0.5 * (x[:, 0] - x[:, 1]) * width
    return np.column_stack([m + s, m - s])


def fractional_delay(x: np.ndarray, samples: int) -> np.ndarray:
    x = ensure_2d(x)
    if samples == 0:
        return x
    if samples > 0:
        return np.vstack([np.zeros((samples, x.shape[1])), x[:-samples]])
    s = -samples
    return np.vstack([x[s:], np.zeros((s, x.shape[1]))])


def remove_dc(x: np.ndarray, sr: int, freq: float = 10.0) -> np.ndarray:
    b, a = biquad_coeffs("hpf", freq, sr, 0.0, 0.7071)
    return apply_biquad(x, b, a)


# ------------------------------------------------------------- Oversampling/TP

def true_peak(x: np.ndarray, sr: int) -> float:
    """True Peak (linear) nach BS.1770-4 Annex 2: 4x Oversampling bei < 96 kHz."""
    x = ensure_2d(x)
    factor = 4 if sr < 96000 else 2
    up = resample_poly(x, factor, 1, axis=0, window=("kaiser", 8.0))
    return float(max(np.max(np.abs(up)), np.max(np.abs(x))))


def true_peak_limiter(
    x: np.ndarray,
    sr: int,
    ceiling_db: float = -1.0,
    lookahead_ms: float = 1.5,
    release_ms: float = 60.0,
) -> tuple[np.ndarray, dict]:
    """Lookahead-Limiter mit True-Peak-Erkennung (4x Oversampling)."""
    x = ensure_2d(x)
    n = x.shape[0]
    ceiling = 10 ** (ceiling_db / 20.0)
    factor = 4 if sr < 96000 else 2
    up = np.max(np.abs(resample_poly(x, factor, 1, axis=0, window=("kaiser", 8.0))), axis=1)
    tp = up.reshape(-1, factor)[:n].max(axis=1) if len(up) >= n * factor else np.max(np.abs(x), axis=1)
    tp = np.maximum(tp, np.max(np.abs(x), axis=1))
    req = np.minimum(1.0, ceiling / np.maximum(tp, EPS))
    la = max(1, int(lookahead_ms * 1e-3 * sr))
    # Symmetrisches Minimum (+-la) und anschließender gleitender Mittelwert (la)
    # garantieren an jeder Spitze g <= req und eine weiche Absenkung davor.
    g = minimum_filter1d(req, size=2 * la + 1, mode="nearest")
    g = uniform_filter1d(g, size=la + 1, mode="nearest")
    # Release: Gain darf nur langsam zurückkehren
    rel = time_coef(release_ms, sr / ENV_BLOCK)
    gb = g[: (n // ENV_BLOCK) * ENV_BLOCK].reshape(-1, ENV_BLOCK).min(axis=1) if n >= ENV_BLOCK else np.array([g.min()])
    grdb = -lin_to_db(gb)
    sm = smooth_ballistics(grdb, 0.0, rel, 0.0)
    g_rel = db_to_lin(-expand_blocks(sm, n))
    gain = np.minimum(g, g_rel)
    y = x * gain[:, None]
    # Sicherheitsstufe: verbleibende Inter-Sample-Spitzen hart korrigieren
    for _ in range(3):
        tp_now = true_peak(y, sr)
        if tp_now <= ceiling * 1.0001:
            break
        y = y * (ceiling / tp_now)
    gr_db = -lin_to_db(gain)
    return y, {
        "max_gr_db": float(gr_db.max()) if gr_db.size else 0.0,
        "mean_gr_db": float(gr_db.mean()) if gr_db.size else 0.0,
        "time_over_3db": float(np.mean(gr_db > 3.0)) if gr_db.size else 0.0,
        "latency_samples": 0,
    }


# --------------------------------------------------------------------- Effekte

def make_reverb_ir(sr: int, decay_s: float = 1.6, predelay_ms: float = 20.0, damping_hz: float = 6000.0,
                   seed: int = 7) -> np.ndarray:
    """Synthetische Stereo-Hall-Impulsantwort (exponentiell abklingendes, gefiltertes Rauschen)."""
    rng = np.random.default_rng(seed)
    n = int(sr * (decay_s * 1.2 + predelay_ms / 1000.0))
    t = np.arange(n) / sr
    env = np.exp(-6.91 * t / max(decay_s, 0.05))
    ir = rng.standard_normal((n, 2)) * env[:, None]
    b, a = biquad_coeffs("lpf", damping_hz, sr, 0.0, 0.7071)
    ir = lfilter(b, a, ir, axis=0)
    b, a = biquad_coeffs("hpf", 180.0, sr, 0.0, 0.7071)
    ir = lfilter(b, a, ir, axis=0)
    pre = int(sr * predelay_ms / 1000.0)
    ir = np.vstack([np.zeros((pre, 2)), ir])
    ir /= np.sqrt(np.sum(ir ** 2) / 2.0) + EPS
    return ir


def make_delay_ir(sr: int, time_s: float = 0.375, feedback: float = 0.35, repeats: int = 6,
                  damping_hz: float = 4500.0, pingpong: bool = True) -> np.ndarray:
    n = int(sr * time_s * (repeats + 1)) + 1
    ir = np.zeros((n, 2))
    for k in range(1, repeats + 1):
        idx = int(round(k * time_s * sr))
        if idx >= n:
            break
        amp = feedback ** (k - 1)
        ch = (k % 2) if pingpong else None
        if ch is None:
            ir[idx, :] = amp
        else:
            ir[idx, ch] = amp
    b, a = biquad_coeffs("lpf", damping_hz, sr, 0.0, 0.7071)
    ir = lfilter(b, a, ir, axis=0)
    return ir


def convolve_stereo(x: np.ndarray, ir: np.ndarray) -> np.ndarray:
    from scipy.signal import fftconvolve

    x = ensure_2d(x)
    if x.shape[1] == 1:
        x = np.column_stack([x[:, 0], x[:, 0]])
    y = np.column_stack([fftconvolve(x[:, c], ir[:, c])[: x.shape[0]] for c in range(2)])
    return y

