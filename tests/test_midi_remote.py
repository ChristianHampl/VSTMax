"""MIDI-Remote: Skript-Konsistenz, Kodierung (JS <-> Python) und Bridge-Logik gegen ein Testdouble.

Keiner dieser Tests läuft in Cubase. Das Verhalten der echten MixConsole (Fader-Kurve, Anzeige-
Callbacks) ist in STATUS.md als "nicht ausgeführt" geführt.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from integration.midi_remote.bridge import MidiRemoteBridge, decode_text, encode_text, load_mapping, parse_db, parse_pan
from integration.midi_remote.mixer import apply_mixer_plan
from integration.midi_remote.simulator import CubaseSimulator

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "integration" / "midi_remote" / "AIME" / "Bridge" / "AIME_Bridge.js"


def test_script_mapping_block_matches_json():
    src = SCRIPT.read_text(encoding="utf-8")
    m = re.search(r"// ---- BEGIN MAPPING.*?\nvar MAP = (\{.*?\})\n// ---- END MAPPING", src, re.S)
    assert m, "Mapping-Block fehlt"
    assert json.loads(m.group(1)) == load_mapping()
    assert SCRIPT.parent.name == "Bridge" and SCRIPT.parent.parent.name == "AIME"
    assert SCRIPT.name == "AIME_Bridge.js"  # Namenskonvention <Hersteller>_<Gerät>.js


def test_script_is_es5():
    src = SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line.split("//")[0] for line in src.splitlines())
    assert not re.search(r"\b(let|const|class)\s", code)
    assert "=>" not in code and "`" not in code


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js nicht installiert")
def test_script_runs_against_api_mock_and_encodes_like_python():
    r = subprocess.run(["node", str(ROOT / "tests" / "js" / "midiremote_mock.js"), str(SCRIPT), "Gesang Ä"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    used = set(out["used"])
    for member in ("api.makeDeviceDriver()", "api.makeDeviceDriver().mPorts.makeMidiInput()",
                   "api.makeDeviceDriver().mMapping.makePage()",
                   "api.makeDeviceDriver().mMapping.makePage().mHostAccess.mMixConsole.makeMixerBankZone()"):
        assert member in used
    assert any(p.endswith("mOnActivate") for p in out["callbacks"])
    b = MidiRemoteBridge(out_port=type("N", (), {"send": lambda self, d: None})())
    for msg in out["sent"]:
        b.on_midi(msg)
    assert b.hello == "AIME Bridge"
    assert set(b.titles.values()) == {"Gesang Ä"} and len(b.titles) == 8
    assert b.display[(0, 0)] == "-6.02 dB"
    assert abs(b.values[(0, 0)] - 0.5) < 1e-3


def test_text_and_display_parsing():
    assert decode_text(encode_text("Gitarre Ü – links")) == "Gitarre Ü – links"
    assert parse_db("-6.02 dB") == -6.02 and parse_db("−3,5") == -3.5 and parse_db("-oo") == float("-inf")
    assert parse_pan("C") == 0 and parse_pan("L50") == -0.5 and parse_pan("R100") == 1.0 and parse_pan("x") is None


def _rig(names):
    sim = CubaseSimulator(names)
    br = MidiRemoteBridge(sim, feedback_timeout=0.05)
    sim.attach(br)
    return sim, br


def test_calibrated_volume_send_pan_and_switches():
    sim, br = _rig(["Kick", "Snare", "Vox"])
    r = br.set_volume_db(2, -7.5)
    assert r.ok and r.calibrated and abs(r.reached + 7.5) <= 0.1
    assert sim.display_text(sim.channel("Vox"), "volume") == f"{r.reached:.2f} dB"
    s = br.set_send_db(0, 1, -18.0)
    assert s.calibrated and abs(s.reached + 18.0) <= 0.5
    p = br.set_pan(1, -0.3)
    assert p.calibrated and abs(p.reached + 0.3) <= 0.02
    br.set_switch(1, "mute", True)
    assert sim.channel("Snare")["mute"] == 1.0
    br.transport("start")
    br.transport("stop")
    assert sim.transport == ["start", "stop"]


def test_no_feedback_is_reported_not_guessed():
    class Silent:
        def send(self, d):
            pass

    br = MidiRemoteBridge(Silent(), feedback_timeout=0.02)
    r = br.set_volume_db(0, -3.0)
    assert not r.ok and not r.calibrated and "Rückmeldung" in r.message


def test_bank_navigation_and_mixer_plan():
    names = [f"Track {i}" for i in range(19)] + ["Vox Lead"]
    sim, br = _rig(names)
    assert br.locate("Track 3") == 3
    assert br.locate("Vox Lead") == (len(names) - 1) % 8 and sim.offset == 16
    assert br.locate("Track 9") == 1 and sim.offset == 8
    assert br.locate("Gibt es nicht", max_banks=5) is None
    plan = {"tracks": [{"id": "v", "name": "Vox Lead", "enabled": True, "sends": {"reverb_db": -14.0, "delay_db": -20.0}},
                       {"id": "t", "name": "Track 2", "enabled": True, "sends": {"reverb_db": None, "delay_db": None}},
                       {"id": "x", "name": "Fehlt", "enabled": True}]}
    rep = apply_mixer_plan(br, plan)
    assert rep["not_found"] == ["Fehlt"] and not rep["uncalibrated"]
    v = rep["tracks"]["Vox Lead"]
    assert abs(v["send1"]["reached"] + 14) <= 0.75 and abs(v["send2"]["reached"] + 20) <= 0.75
    assert abs(v["volume"]["reached"]) <= 0.1 and abs(v["pan"]["reached"]) <= 0.02
    assert sim.channel("Track 2")["send1"] == 0.0  # keine Sends geplant -> unverändert
