import subprocess
import sys

import pytest

from integration.presets import vstpreset as V
from integration.protocol import params as P
from tests.conftest import ROOT


@pytest.mark.parametrize("plugin", ["channel", "bus", "master"])
def test_normalization_roundtrip(plugin):
    for p in P.expand(plugin):
        for v in (p["min"], p["max"], p["default"]):
            back = P.from_normalized(p, P.to_normalized(p, v))
            assert back == pytest.approx(float(v), rel=1e-9, abs=1e-9), p["key"]


def test_unique_ids():
    for plugin in ("channel", "bus", "master"):
        ids = [p["id"] for p in P.expand(plugin)]
        assert len(ids) == len(set(ids)), plugin


def test_generated_header_is_current():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_params.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_state_and_preset_roundtrip():
    vals = P.defaults("channel")
    vals.update(trim_db=-4.5, eq1_type=1, eq1_freq=3150.0, eq1_gain_db=-2.5, pan=-0.4)
    data = V.build_preset("channel", vals, "Gtr L")
    parsed = V.parse_preset(data)
    assert parsed["class_id"] == P.class_id_string(P.definitions()["plugins"]["channel"]["processor_uid"])
    state, label = V.decode_state(parsed["chunks"]["Comp"])
    pk = P.by_key("channel")
    assert label == "Gtr L"
    assert state[pk["eq1_freq"]["id"]] == 3150.0
    assert state[pk["pan"]["id"]] == -0.4
    assert pk["meter_gr_db"]["id"] not in state  # readonly wird nicht gespeichert


def test_channel_params_mapping():
    t = {"trim_db": -3.0, "fader_db": -6.0, "pan": 0.5, "width": 1.0, "delay_samples": 48,
         "hpf": {"freq": 80.0, "order": 4}, "eq": [{"type": "bell", "freq": 400, "gain_db": -3, "q": 2}],
         "dyn_eq": [{"freq": 2500, "q": 2, "threshold_db": -30, "range_db": 3, "sidechain": "vox"}],
         "comp": {"enabled": True, "threshold_db": -20, "ratio": 4, "attack_ms": 5, "release_ms": 100, "makeup_db": 2},
         "deesser": {"enabled": False}, "saturation": {"drive_db": 2.0}, "gate": {"enabled": False}}
    v, notes = P.channel_params(t, 48000)
    assert v["hpf_steep"] == 1.0 and v["hpf_freq"] == 80.0
    assert v["align_delay_ms"] == pytest.approx(1.0)
    assert v["dyn1_sidechain"] == 1.0
    assert v["output_db"] == -6.0
    assert any("Sidechain" in n for n in notes)


def test_export_plan_presets_includes_mixbus(tmp_path):
    plan = {"sample_rate": 48000, "tracks": [], "buses": {},
            "mix_bus": {"input_gain_db": -4.0, "comp": {"enabled": True, "threshold_db": -12, "ratio": 2,
                                                         "attack_ms": 30, "release_ms": 200, "knee_db": 6}},
            "master": {"true_peak_db": -1.0}}
    w = V.export_plan_presets(plan, tmp_path)
    assert "mix_bus" in w["buses"]
    st, _ = V.decode_state(V.parse_preset(open(w["buses"]["mix_bus"], "rb").read())["chunks"]["Comp"])
    assert st[P.by_key("bus")["input_db"]["id"]] == -4.0
