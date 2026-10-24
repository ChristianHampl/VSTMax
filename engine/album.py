"""Album-Modus: einheitliches Mastering mehrerer Songs.

- gemeinsame Ziel-Lautheit (``uniform``) oder Erhalt beabsichtigter Unterschiede (``relative``)
- Angleich der Tonalbalance an den Album-Median (gedämpft, begrenzt)
- gemeinsame True-Peak-Grenze, einheitliche Exportformate
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import loudness as lmod
from .audio_io import load_audio, resample, write_audio
from .mastering import MasterSettings, master
from .optimizer import spectral_tilt


def album_master(
    song_paths: list[str],
    out_dir: str | Path,
    settings: MasterSettings,
    mode: str = "uniform",
    relative_keep: float = 0.5,
    tonal_match: float = 0.5,
    sample_rate: int | None = None,
    bit_depth: int = 24,
    progress=None,
    cancel=None,
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    songs = []
    for i, p in enumerate(song_paths):
        if cancel and cancel():
            raise InterruptedError("Abgebrochen")
        if progress:
            progress(i / max(1, len(song_paths)) * 0.3, f"Analysiere {Path(p).name}")
        a = load_audio(p)
        x = a.samples
        lufs = lmod.integrated_loudness(x, a.sample_rate)
        songs.append({"path": a.path, "name": Path(p).stem, "sr": a.sample_rate, "lufs": lufs,
                      "tilt": spectral_tilt(x, a.sample_rate)})
    finite = [s["lufs"] for s in songs if math.isfinite(s["lufs"])]
    mean_lufs = float(np.mean(finite)) if finite else settings.target_lufs
    album_tilt = float(np.median([s["tilt"] for s in songs]))
    sr_out = sample_rate or max(set(s["sr"] for s in songs), key=[s["sr"] for s in songs].count)
    results = []
    protected = {s["path"] for s in songs}
    for i, s in enumerate(songs):
        if cancel and cancel():
            raise InterruptedError("Abgebrochen")
        if progress:
            progress(0.3 + 0.7 * i / max(1, len(songs)), f"Mastere {s['name']}")
        st = MasterSettings(**{k: v for k, v in settings.__dict__.items()})
        if mode == "relative" and math.isfinite(s["lufs"]):
            st.target_lufs = settings.target_lufs + relative_keep * (s["lufs"] - mean_lufs)
        st.target_tilt_db_oct = (1 - tonal_match) * s["tilt"] + tonal_match * album_tilt
        a = load_audio(s["path"])
        x = a.samples
        if a.sample_rate != sr_out:
            x = resample(x, a.sample_rate, sr_out)
        log: list = []
        y, rep = master(x, sr_out, st, log)
        dest = out / f"{i + 1:02d} {s['name']} (Master).wav"
        w = write_audio(dest, y, sr_out, bit_depth, overwrite=True, protected=protected)
        results.append({"name": s["name"], "source": s["path"], "output": w["path"],
                        "source_lufs": round(s["lufs"], 2) if math.isfinite(s["lufs"]) else None,
                        "target_lufs": round(st.target_lufs, 2), "report": rep, "log": log})
    lufs_out = [r["report"]["after"]["integrated_lufs"] for r in results if r["report"]["after"]["integrated_lufs"] is not None]
    summary = {
        "mode": mode,
        "album_tilt_db_oct": round(album_tilt, 3),
        "loudness_spread_lu": round(float(np.max(lufs_out) - np.min(lufs_out)), 2) if lufs_out else None,
        "sample_rate": sr_out,
        "bit_depth": bit_depth,
        "songs": results,
    }
    return summary
