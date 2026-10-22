from engine.analysis import analyze
from engine.audio_io import load_audio
from engine.classification import classify

EXPECTED = {"Kick In": "kick", "Snare Top": "snare", "Bass DI": "bass", "Gtr Rhythm L": "rhythm_guitar",
            "Gtr Rhythm R": "rhythm_guitar", "OH": "overheads"}


def _load(song_dir, name):
    a = load_audio(song_dir / f"{name}.wav")
    return a, analyze(a.samples, a.sample_rate, name, a.bit_depth)


def test_classification_with_names(song_dir):
    for name, role in EXPECTED.items():
        _, an = _load(song_dir, name)
        c = classify(an, name)
        assert c.role == role, (name, c.role, c.confidence)
        assert 0.0 < c.confidence <= 0.95


def test_classification_blind_drums_bass(song_dir):
    for name in ("Kick In", "Snare Top", "Bass DI"):
        _, an = _load(song_dir, name)
        c = classify(an, "Track 01")
        assert c.role == EXPECTED[name], (name, c.role)


def test_name_contradiction_is_flagged_uncertain(song_dir):
    _, an = _load(song_dir, "Kick In")
    c = classify(an, "Vocals Lead")
    assert c.role != "lead_vocal"
    assert c.uncertain and c.confidence <= 0.6
    assert any("widersprechen" in r for r in c.reasons)


def test_problem_detection(song_dir):
    _, clipped = _load(song_dir, "Gtr Clipped")
    assert any(p["code"] == "clipping" for p in clipped.problems)
    _, dc = _load(song_dir, "Noise DC")
    assert any(p["code"] == "dc_offset" for p in dc.problems)
    _, pad = _load(song_dir, "Synth Pad")
    assert any(p["code"] in ("phase_inverted", "mono_compat") for p in pad.problems)
