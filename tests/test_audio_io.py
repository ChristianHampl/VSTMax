import numpy as np
import pytest

from engine.audio_io import AudioIOError, ProtectedFileError, file_fingerprint, load_audio, write_audio
from tests.conftest import SR, sine


def test_roundtrip_24bit(tmp_path):
    x = sine(440, 0.5, 0.5)
    p = tmp_path / "a.wav"
    write_audio(p, x, SR, 24)
    a = load_audio(p)
    assert a.sample_rate == SR and a.channels == 2
    assert np.max(np.abs(a.samples - x)) < 1e-6


def test_refuses_overwrite_and_protected(tmp_path):
    x = sine(440, 0.5, 0.1)
    p = tmp_path / "orig.wav"
    write_audio(p, x, SR, 24)
    fp = file_fingerprint(p)
    with pytest.raises(AudioIOError):
        write_audio(p, x * 0.1, SR, 24)
    with pytest.raises(ProtectedFileError):
        write_audio(p, x * 0.1, SR, 24, overwrite=True, protected={str(p.resolve())})
    assert file_fingerprint(p) == fp


def test_resample_on_export(tmp_path):
    x = sine(1000, 0.5, 1.0)
    r = write_audio(tmp_path / "b.wav", x, 44100, 24, source_sample_rate=SR)
    a = load_audio(tmp_path / "b.wav")
    assert a.sample_rate == 44100
    assert abs(a.frames - 44100) <= 2
    assert any("Resampling" in s or "resampl" in s.lower() for s in r["steps"])
