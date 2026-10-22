"""Deterministische Spuranalyse: Pegel, Dynamik, Spektrum, Transienten, Stereo, Probleme."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.signal import find_peaks, welch

from . import loudness as lmod
from .dsp import ensure_2d
from .phase import mono_compatibility_db, side_to_mid_db, stereo_correlation

# ISO-Terzbandmitten 25 Hz .. 16 kHz
THIRD_OCTAVE_CENTERS = np.array([
    25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250,
    1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000, 12500, 16000,
], dtype=float)

NAMED_BANDS = {
    "sub": (20, 60),
    "bass": (60, 250),
    "low_mid": (250, 500),
    "mid": (500, 2000),
    "high_mid": (2000, 4000),
    "presence": (4000, 8000),
    "air": (8000, 20000),
}

FRAME_S = 0.05
SILENCE_DBFS = -60.0


@dataclass
class TrackAnalysis:
    name: str
    sample_rate: int
    channels: int
    duration_s: float
    bit_depth: int | None
    peak_dbfs: float
    true_peak_dbtp: float
    rms_dbfs: float
    active_rms_dbfs: float
    crest_db: float
    lufs: float
    lra_lu: float
    dc_offset: float
    clipped_samples: int
    clip_events: int
    silence_ratio: float
    is_silent: bool
    noise_floor_dbfs: float
    hit_level_dbfs: float
    dynamic_range_db: float
    centroid_hz: float
    rolloff_hz: float
    flatness: float
    zcr: float
    onset_rate: float
    sustain_ratio: float
    harmonicity: float
    f0_median_hz: float
    f0_spread: float
    band_db: dict = field(default_factory=dict)  # relativ zur Gesamtenergie
    third_octave_db: list = field(default_factory=list)
    correlation: float = 1.0
    side_mid_db: float = -120.0
    mono_compat_db: float = 0.0
    low_peak_hz: float = 0.0
    activity: list = field(default_factory=list)  # 100-ms-RMS (dBFS), für Überlappung
    problems: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, float) and not math.isfinite(v):
                d[k] = None
        return d


def _db(x: float, floor: float = -150.0) -> float:
    return 20 * math.log10(x) if x > 10 ** (floor / 20) else floor


def frame_rms_db(mono: np.ndarray, sr: int, frame_s: float = FRAME_S) -> np.ndarray:
    n = max(1, int(frame_s * sr))
    nb = len(mono) // n
    if nb == 0:
        return np.array([_db(float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0)])
    r = np.sqrt(np.mean(mono[: nb * n].reshape(nb, n) ** 2, axis=1))
    return 20 * np.log10(np.maximum(r, 1e-8))


def spectrum(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Leistungsdichtespektrum, über Kanäle gemittelt (keine Auslöschung durch Mono-Summe)."""
    x = ensure_2d(x)
    nper = min(8192, max(256, 2 ** int(math.log2(max(x.shape[0], 256)))))
    f, p = welch(x, fs=sr, nperseg=nper, noverlap=nper // 2, window="hann", detrend=False, axis=0)
    return f, p.mean(axis=1)


def band_energy_db(f: np.ndarray, p: np.ndarray, lo: float, hi: float, total: float) -> float:
    m = (f >= lo) & (f < hi)
    e = float(np.sum(p[m]))
    return 10 * math.log10(max(e, 1e-20) / max(total, 1e-20))


def third_octave(f: np.ndarray, p: np.ndarray) -> np.ndarray:
    out = []
    for fc in THIRD_OCTAVE_CENTERS:
        lo, hi = fc / 2 ** (1 / 6), fc * 2 ** (1 / 6)
        m = (f >= lo) & (f < hi)
        e = float(np.sum(p[m])) if np.any(m) else float(np.interp(fc, f, p)) * (hi - lo) / max(f[1] - f[0], 1e-9)
        out.append(10 * math.log10(max(e, 1e-20)))
    return np.array(out)


def _harmonicity(mono: np.ndarray, sr: int, active_mask: np.ndarray) -> tuple[float, float, float]:
    """Mittlere normierte Autokorrelationsspitze (80-1000 Hz) und f0-Statistik."""
    frame = 2048 if sr <= 50000 else 4096
    hop = int(FRAME_S * sr)
    idx = np.where(active_mask)[0]
    if idx.size == 0:
        return 0.0, 0.0, 0.0
    sel = idx[np.linspace(0, idx.size - 1, min(160, idx.size)).astype(int)]
    lag_min, lag_max = int(sr / 1000), int(sr / 70)
    vals, f0s = [], []
    win = np.hanning(frame)
    for k in sel:
        s = k * hop
        seg = mono[s:s + frame]
        if len(seg) < frame:
            continue
        seg = (seg - seg.mean()) * win
        spec = np.fft.rfft(seg, 2 * frame)
        ac = np.fft.irfft(np.abs(spec) ** 2)[:frame]
        if ac[0] <= 1e-12:
            continue
        ac = ac / ac[0]
        region = ac[lag_min:lag_max]
        if region.size < 3:
            continue
        pk, _ = find_peaks(region)
        if pk.size == 0:
            vals.append(0.0)
            continue
        j = int(pk[np.argmax(region[pk])])
        vals.append(float(max(region[j], 0.0)))
        if region[j] > 0.5:
            f0s.append(sr / (lag_min + j))
    if not vals:
        return 0.0, 0.0, 0.0
    h = float(np.median(vals))
    if f0s:
        f0 = np.array(f0s)
        med = float(np.median(f0))
        spread = float(np.std(12 * np.log2(f0 / med)))  # Halbtöne
    else:
        med, spread = 0.0, 0.0
    return h, med, spread


def _onsets(mono: np.ndarray, sr: int) -> tuple[float, np.ndarray]:
    hop = max(1, int(0.01 * sr))
    nb = len(mono) // hop
    if nb < 4:
        return 0.0, np.zeros(0)
    env = np.sqrt(np.mean(mono[: nb * hop].reshape(nb, hop) ** 2, axis=1))
    env_db = 20 * np.log10(np.maximum(env, 1e-8))
    rise = env_db[3:] - env_db[:-3]
    peaks, _ = find_peaks(rise, height=9.0, distance=5)
    peaks = peaks[env_db[peaks + 3] > max(SILENCE_DBFS, float(np.max(env_db)) - 40)]
    active_s = max(np.sum(env_db > SILENCE_DBFS) * hop / sr, 1e-3)
    return float(len(peaks) / active_s), peaks


def estimate_tempo(x: np.ndarray, sr: int, lo_bpm: float = 70.0, hi_bpm: float = 200.0) -> tuple[float, float]:
    """Tempo aus der Autokorrelation der Onset-Hüllkurve. Gibt (BPM, Konfidenz 0..1) zurück."""
    mono = ensure_2d(x).mean(axis=1)
    hop = max(1, int(0.01 * sr))
    nb = len(mono) // hop
    if nb < 200:
        return 120.0, 0.0
    env = np.sqrt(np.mean(mono[: nb * hop].reshape(nb, hop) ** 2, axis=1))
    flux = np.maximum(np.diff(np.log(env + 1e-6)), 0)
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    if ac[0] <= 0:
        return 120.0, 0.0
    ac /= ac[0]
    fps = sr / hop
    lags = np.arange(len(ac))
    lo_lag, hi_lag = int(fps * 60 / hi_bpm), int(fps * 60 / lo_bpm)
    seg = ac[lo_lag:hi_lag]
    if seg.size == 0:
        return 120.0, 0.0
    j = int(np.argmax(seg)) + lo_lag
    # parabolische Interpolation für Sub-Frame-Genauigkeit
    if 1 <= j < len(ac) - 1:
        a, b, c = ac[j - 1], ac[j], ac[j + 1]
        den = a - 2 * b + c
        off = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
    else:
        off = 0.0
    bpm = 60.0 * fps / (lags[j] + off)
    return float(bpm), float(max(0.0, min(1.0, ac[j])))


def analyze(samples: np.ndarray, sr: int, name: str = "", bit_depth: int | None = None) -> TrackAnalysis:
    x = ensure_2d(samples)
    # Lautester Einzelkanal statt Mono-Summe (robust bei gegenphasigem Stereo)
    mono = x[:, int(np.argmax(np.mean(x ** 2, axis=0)))] if x.shape[0] else x.mean(axis=1)
    n = x.shape[0]
    problems: list[dict] = []

    peak = float(np.max(np.abs(x))) if n else 0.0
    rms = float(np.sqrt(np.mean(x ** 2))) if n else 0.0
    power_sig = np.sqrt(np.mean(x ** 2, axis=1))  # kanalgemittelte Leistung, auslöschungsfrei
    frames_db = frame_rms_db(power_sig, sr)
    active = frames_db > SILENCE_DBFS
    silence_ratio = float(1.0 - np.mean(active)) if active.size else 1.0
    is_silent = peak < 10 ** (-80 / 20) or not np.any(active)
    if np.any(active):
        act_lin = 10 ** (frames_db[active] / 20)
        active_rms = _db(float(np.sqrt(np.mean(act_lin ** 2))))
    else:
        active_rms = -150.0
    crest = _db(peak) - _db(rms) if rms > 0 else 0.0

    lres = lmod.measure(x, sr, with_true_peak=True) if not is_silent else None
    lufs = lres.integrated_lufs if lres else float("-inf")
    tp = lres.true_peak_dbtp if lres else -150.0
    lra = lres.loudness_range_lu if lres else 0.0

    dc = float(np.max(np.abs(np.mean(x, axis=0)))) if n else 0.0
    # Clipping: >= 3 aufeinanderfolgende Samples nahe Vollaussteuerung
    hot = np.abs(x) >= 0.9995
    clip_samples, clip_events = 0, 0
    for c in range(x.shape[1]):
        h = hot[:, c].astype(np.int8)
        if not h.any():
            continue
        d = np.diff(np.concatenate([[0], h, [0]]))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        runs = ends - starts
        long = runs >= 3
        clip_events += int(np.sum(long))
        clip_samples += int(np.sum(runs[long]))

    if np.any(active):
        noise_floor = float(np.percentile(frames_db, 10))
        hit = float(np.percentile(frames_db[active], 95))
        dyn = float(np.percentile(frames_db[active], 95) - np.percentile(frames_db[active], 10))
        sustain = float(10 ** ((np.median(frames_db[active]) - hit) / 20))
    else:
        noise_floor, hit, dyn, sustain = -150.0, -150.0, 0.0, 0.0

    f, p = spectrum(x, sr) if not is_silent else (np.array([0.0, 1.0]), np.array([1e-20, 1e-20]))
    total = float(np.sum(p[f >= 20])) if not is_silent else 1e-20
    bands = {k: round(band_energy_db(f, p, lo, hi, total), 2) for k, (lo, hi) in NAMED_BANDS.items()}
    tod = third_octave(f, p)
    pw = p[f >= 20]
    fw = f[f >= 20]
    centroid = float(np.sum(fw * pw) / max(np.sum(pw), 1e-20)) if not is_silent else 0.0
    cums = np.cumsum(pw)
    rolloff = float(fw[np.searchsorted(cums, 0.85 * cums[-1])]) if (not is_silent and cums[-1] > 0) else 0.0
    m = (fw > 100) & (fw < 10000)
    flat = float(np.exp(np.mean(np.log(pw[m] + 1e-20))) / max(np.mean(pw[m]), 1e-20)) if np.any(m) and not is_silent else 0.0
    low_m = (f >= 30) & (f <= 150)
    low_peak = float(f[low_m][np.argmax(p[low_m])]) if np.any(low_m) and not is_silent else 0.0

    zc = np.mean(np.abs(np.diff(np.signbit(mono).astype(np.int8)))) * sr if n > 1 else 0.0
    onset_rate, _ = _onsets(mono, sr) if not is_silent else (0.0, None)
    harm, f0, f0s = _harmonicity(mono, sr, active) if not is_silent else (0.0, 0.0, 0.0)

    corr = stereo_correlation(x)
    smr = side_to_mid_db(x)
    mono_c = mono_compatibility_db(x)

    # 100-ms-Aktivität für Überlappungs-/Maskierungsanalyse
    act100 = frame_rms_db(power_sig, sr, 0.1)

    if is_silent:
        problems.append({"severity": "warning", "code": "silent", "message": "Spur ist (nahezu) stumm"})
    if clip_events:
        problems.append({"severity": "error", "code": "clipping",
                         "message": f"Clipping erkannt: {clip_events} Ereignisse ({clip_samples} Samples)"})
    if tp > 0.0:
        problems.append({"severity": "warning", "code": "true_peak_over",
                         "message": f"True Peak über 0 dBTP ({tp:.2f} dBTP)"})
    if dc > 0.005:
        problems.append({"severity": "warning", "code": "dc_offset",
                         "message": f"Gleichspannungsanteil {dc:.4f} ({_db(dc):.1f} dBFS)"})
    if not is_silent and peak < 10 ** (-30 / 20):
        problems.append({"severity": "info", "code": "low_level",
                         "message": f"Sehr niedriger Pegel (Peak {_db(peak):.1f} dBFS)"})
    if x.shape[1] >= 2 and not is_silent:
        if corr < -0.3:
            problems.append({"severity": "error", "code": "phase_inverted",
                             "message": f"Stereo-Kanäle gegenphasig (Korrelation {corr:.2f})"})
        elif mono_c < -6.0:
            problems.append({"severity": "warning", "code": "mono_compat",
                             "message": f"Schlechte Mono-Kompatibilität ({mono_c:.1f} dB)"})
        if smr < -40:
            problems.append({"severity": "info", "code": "fake_stereo",
                             "message": "Stereo-Datei ist praktisch mono (L = R)"})

    return TrackAnalysis(
        name=name,
        sample_rate=sr,
        channels=x.shape[1],
        duration_s=n / sr,
        bit_depth=bit_depth,
        peak_dbfs=_db(peak),
        true_peak_dbtp=tp,
        rms_dbfs=_db(rms),
        active_rms_dbfs=active_rms,
        crest_db=crest,
        lufs=lufs,
        lra_lu=lra,
        dc_offset=dc,
        clipped_samples=clip_samples,
        clip_events=clip_events,
        silence_ratio=silence_ratio,
        is_silent=bool(is_silent),
        noise_floor_dbfs=noise_floor,
        hit_level_dbfs=hit,
        dynamic_range_db=dyn,
        centroid_hz=centroid,
        rolloff_hz=rolloff,
        flatness=flat,
        zcr=float(zc),
        onset_rate=onset_rate,
        sustain_ratio=sustain,
        harmonicity=harm,
        f0_median_hz=f0,
        f0_spread=f0s,
        band_db=bands,
        third_octave_db=[round(float(v), 2) for v in tod],
        correlation=corr,
        side_mid_db=smr,
        mono_compat_db=mono_c,
        low_peak_hz=low_peak,
        activity=[round(float(v), 1) for v in act100],
        problems=problems,
    )
