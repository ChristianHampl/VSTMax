"""Audio-Import/-Export (WAV, FLAC, AIFF) mit Schutz der Originaldateien."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

SUPPORTED_EXTENSIONS = {".wav", ".wave", ".flac", ".aif", ".aiff"}

_SUBTYPE_BITS = {
    "PCM_U8": 8,
    "PCM_S8": 8,
    "PCM_16": 16,
    "PCM_24": 24,
    "PCM_32": 32,
    "FLOAT": 32,
    "DOUBLE": 64,
}

_EXPORT_SUBTYPES = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}


class AudioIOError(Exception):
    pass


@dataclass
class AudioData:
    samples: np.ndarray  # shape (frames, channels), float64, nominal range [-1, 1]
    sample_rate: int
    bit_depth: int | None = None
    subtype: str = ""
    path: str | None = None
    fmt: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def frames(self) -> int:
        return int(self.samples.shape[0])

    @property
    def duration(self) -> float:
        return self.frames / float(self.sample_rate) if self.sample_rate else 0.0

    def mono(self) -> np.ndarray:
        return self.samples.mean(axis=1)

    def info(self) -> dict:
        return {
            "path": self.path,
            "format": self.fmt,
            "subtype": self.subtype,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "frames": self.frames,
            "duration_s": round(self.duration, 4),
        }


def is_supported(path: str | os.PathLike) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def load_audio(path: str | os.PathLike) -> AudioData:
    p = Path(path)
    if not p.exists():
        raise AudioIOError(f"Datei nicht gefunden: {p}")
    if not is_supported(p):
        raise AudioIOError(f"Nicht unterstütztes Format: {p.suffix} (erlaubt: WAV, FLAC, AIFF)")
    try:
        info = sf.info(str(p))
        data, sr = sf.read(str(p), dtype="float64", always_2d=True)
    except Exception as exc:  # soundfile raises RuntimeError/LibsndfileError
        raise AudioIOError(f"Datei kann nicht gelesen werden: {p.name}: {exc}") from exc
    if data.size == 0:
        raise AudioIOError(f"Datei enthält keine Audiodaten: {p.name}")
    warnings: list[str] = []
    if not np.all(np.isfinite(data)):
        warnings.append("Ungültige Samples (NaN/Inf) gefunden und durch 0 ersetzt")
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)
    return AudioData(
        samples=data,
        sample_rate=int(sr),
        bit_depth=_SUBTYPE_BITS.get(info.subtype),
        subtype=info.subtype,
        path=str(p.resolve()),
        fmt=info.format,
        warnings=warnings,
    )


def file_fingerprint(path: str | os.PathLike, max_bytes: int = 4 * 1024 * 1024) -> str:
    """Schneller, stabiler Fingerabdruck (Größe + Anfang + Ende der Datei)."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with open(p, "rb") as fh:
        h.update(fh.read(max_bytes))
        if size > max_bytes:
            fh.seek(max(0, size - max_bytes))
            h.update(fh.read(max_bytes))
    return h.hexdigest()


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    g = np.gcd(int(sr_in), int(sr_out))
    up, down = int(sr_out) // g, int(sr_in) // g
    return resample_poly(x, up, down, axis=0)


def tpdf_dither(x: np.ndarray, bit_depth: int, rng: np.random.Generator | None = None) -> np.ndarray:
    """TPDF-Dither mit 1 LSB Spitze-Spitze pro Rechteckverteilung (Summe +-1 LSB)."""
    rng = rng or np.random.default_rng(0x5EED)
    lsb = 1.0 / (2 ** (bit_depth - 1))
    noise = (rng.random(x.shape) - rng.random(x.shape)) * lsb
    return x + noise


class ProtectedFileError(AudioIOError):
    pass


def write_audio(
    path: str | os.PathLike,
    samples: np.ndarray,
    sample_rate: int,
    bit_depth: int = 24,
    *,
    source_sample_rate: int | None = None,
    dither: bool = True,
    overwrite: bool = False,
    protected: set[str] | None = None,
) -> dict:
    """Schreibt WAV/FLAC/AIFF. Gibt ein Protokoll der ausgeführten Schritte zurück.

    - Resampling nur, wenn ``source_sample_rate`` von ``sample_rate`` abweicht.
    - Dither nur bei Reduktion auf 16/24 Bit Integer.
    - Originaldateien (``protected``) werden niemals überschrieben.
    """
    p = Path(path)
    if bit_depth not in _EXPORT_SUBTYPES:
        raise AudioIOError(f"Bit-Tiefe {bit_depth} nicht unterstützt (16, 24, 32 float)")
    resolved = str(p.resolve())
    if protected and resolved in protected:
        raise ProtectedFileError(f"Originaldatei darf nicht überschrieben werden: {p}")
    if p.exists() and not overwrite:
        raise ProtectedFileError(f"Datei existiert bereits (overwrite=False): {p}")
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if not np.all(np.isfinite(x)):
        raise AudioIOError("Export abgebrochen: Signal enthält NaN/Inf")
    steps: list[str] = []
    if source_sample_rate and source_sample_rate != sample_rate:
        x = resample(x, source_sample_rate, sample_rate)
        steps.append(f"Resampling {source_sample_rate} -> {sample_rate} Hz (polyphase)")
    subtype = _EXPORT_SUBTYPES[bit_depth]
    if bit_depth in (16, 24) and dither:
        x = tpdf_dither(x, bit_depth)
        steps.append(f"TPDF-Dither auf {bit_depth} Bit")
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if subtype != "FLOAT":
        clipped = int(np.sum(np.abs(x) > 1.0))
        if clipped:
            steps.append(f"WARNUNG: {clipped} Samples über 0 dBFS wurden begrenzt")
        x = np.clip(x, -1.0, 1.0)
    p.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(p), x, int(sample_rate), subtype=subtype)
    steps.append(f"Geschrieben: {p.name} ({sample_rate} Hz, {bit_depth} Bit {'float' if subtype == 'FLOAT' else 'PCM'})")
    return {"path": resolved, "steps": steps, "peak": peak}
