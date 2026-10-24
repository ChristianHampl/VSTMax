"""Mastering-Schutz, Referenzvergleich, Album-Modus und externes (Nutzer-)Modell in der Klassifikation."""

import math
from pathlib import Path

import numpy as np

from engine import dsp
from engine import loudness as L
from engine.album import album_master
from engine.analysis import analyze
from engine.audio_io import load_audio, write_audio
from engine.classification import classify
from engine.mastering import MasterSettings, master
from engine.reference import compare
from tests.conftest import SR


def _mix(song_dir, names=("Kick In", "Snare Top", "Bass DI", "Gtr Rhythm L", "Gtr Rhythm R", "Vox Lead", "OH")):
    mix = None
    for nm in names:
        a = load_audio(song_dir / f"{nm}.wav").samples
        a = np.column_stack([a[:, 0]] * 2) if a.shape[1] == 1 else a
        mix = a * 0.3 if mix is None else mix + a * 0.3
    return mix * (0.5 / np.max(np.abs(mix)))


def test_master_hits_target_and_true_peak(song_dir):
    y, rep = master(_mix(song_dir), SR, MasterSettings(target_lufs=-14.0, true_peak_db=-1.0))
    assert abs(L.integrated_loudness(y, SR) + 14.0) < 0.5
    assert 20 * math.log10(dsp.true_peak(y, SR)) <= -1.0 + 0.1
    assert "target_note" not in rep


def test_master_refuses_overcompression(song_dir):
    s = MasterSettings(target_lufs=-4.0, true_peak_db=-1.0, max_limiter_gr_db=4.0, min_plr_db=8.0)
    y, rep = master(_mix(song_dir), SR, s)
    assert "target_note" in rep                         # Ziel bewusst verfehlt und dokumentiert
    assert L.integrated_loudness(y, SR) < -5.0
    assert rep["limiter"]["max_gr_db"] <= s.max_limiter_gr_db + 1.0


def test_reference_compare_is_damped_and_bounded(song_dir):
    mix = _mix(song_dir)
    ref = dsp.apply_eq_band(mix, SR, {"type": "highshelf", "freq": 5000, "gain_db": 8.0, "q": 0.7}) * 2.0
    out = compare(mix, ref, SR, SR, match_amount=0.5, max_eq_db=2.0)
    assert out["loudness_difference_lu"] > 3            # Referenz lauter
    assert out["band_difference_db"]["air"] > 4         # bei gleicher Lautheit heller
    air = [b for b in out["suggested_master_eq"] if b["freq"] == 12000.0]
    assert air and 0 < air[0]["gain_db"] <= 2.0         # gedämpft und begrenzt
    assert all(abs(b["gain_db"]) <= 2.0 for b in out["suggested_master_eq"])
    assert not any(isinstance(v, np.ndarray) for v in out.values())  # keine Audiodaten der Referenz


def test_album_uniform_and_relative(song_dir, tmp_path):
    base = _mix(song_dir)
    src = []
    for i, g in enumerate((0.25, 0.6, 1.0)):
        p = tmp_path / f"song{i}.wav"
        write_audio(p, base * g if i != 1 else dsp.apply_eq_band(base, SR, {"type": "lowshelf", "freq": 150,
                                                                             "gain_db": 4, "q": 0.7}) * g, SR, 24)
        src.append(str(p))
    before = [Path(p).read_bytes() for p in src]
    st = MasterSettings(target_lufs=-12.0, true_peak_db=-1.0)
    uni = album_master(src, tmp_path / "uni", st, mode="uniform")
    assert uni["loudness_spread_lu"] <= 0.6
    for s in uni["songs"]:
        y = load_audio(s["output"]).samples
        assert 20 * math.log10(dsp.true_peak(y, SR)) <= -1.0 + 0.15
    rel = album_master(src, tmp_path / "rel", st, mode="relative", relative_keep=0.5)
    t = [s["target_lufs"] for s in rel["songs"]]
    assert t[0] < t[1] < t[2]                           # leiser Song bleibt leiser
    assert [Path(p).read_bytes() for p in src] == before  # Quellen unverändert


def test_user_model_is_blended(song_dir):
    a = load_audio(song_dir / "Kick In.wav")
    an = analyze(a.samples, a.sample_rate, "Track 01", a.bit_depth)
    calls = []

    def model(samples, sr):
        calls.append((samples.shape, sr))
        return {"snare": 0.9, "kick": 0.1}

    c = classify(an, "Track 01", a.samples, model, model_weight=0.9)
    assert calls and c.source.endswith("+ml")
    assert c.probabilities["snare"] > c.probabilities.get("toms", 0)

    def broken(samples, sr):
        raise RuntimeError("defekt")

    c2 = classify(an, "Track 01", a.samples, broken)
    assert c2.role == "kick" and any("fehlgeschlagen" in r for r in c2.reasons)
