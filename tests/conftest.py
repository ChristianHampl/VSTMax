from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.synth import write_song  # noqa: E402

SR = 48000


def _find_native(name: str) -> Path | None:
    env = os.environ.get("AIME_NATIVE_DIR")
    candidates = [Path(env)] if env else []
    candidates += [ROOT / "build" / "dsp", ROOT / "build" / "dsp" / "Release", ROOT / "build" / "native" / "dsp"]
    for c in candidates:
        for exe in (c / name, c / f"{name}.exe"):
            if exe.exists():
                return exe
    found = shutil.which(name)
    return Path(found) if found else None


@pytest.fixture(scope="session")
def aime_render() -> Path:
    exe = _find_native("aime_render")
    if exe is None:
        pytest.skip("aime_render nicht gebaut (cmake -S dsp -B build/dsp && cmake --build build/dsp)")
    return exe


@pytest.fixture(scope="session")
def song_dir(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("song")
    write_song(d, sr=SR, bars=4, with_problems=True, seed=3)
    return d


@pytest.fixture
def rng():
    return np.random.default_rng(1234)


def sine(freq: float, amp: float, seconds: float, sr: int = SR, channels: int = 2) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    x = amp * np.sin(2 * np.pi * freq * t)
    return np.column_stack([x] * channels)
