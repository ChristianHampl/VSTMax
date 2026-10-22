"""Plugin-Link: Protokoll, Server, Capture-Ausrichtung, Zuordnung und Parameter-Push.

Der native Test verwendet den echten Hub-Code der Plug-ins (aime_link_client); Cubase selbst ist
dabei nicht beteiligt.
"""

import json
import os
import socket
import subprocess
import time

import numpy as np
import pytest
import soundfile as sf

from integration.plugin_link import protocol as pr
from integration.plugin_link.actions import match_instances, neutral_values, plan_values, push_plan
from integration.plugin_link.server import Instance, LinkServer
from integration.protocol import params as P


class FakePlugin:
    """Minimaler Python-Client im Protokoll der Plug-ins."""

    def __init__(self, port):
        self.s = socket.create_connection(("127.0.0.1", port))
        self.reader = pr.FrameReader()
        self.s.sendall(pr.frame(pr.HELLO, b'{"protocol":1,"client":"test"}'))

    def add(self, iid, plugin, name, sr=48000.0, ch=2):
        d = {"instance": f"{iid:016x}", "plugin": plugin, "channel_name": name, "channel_uid": "", "label": "",
             "sample_rate": sr, "channels": ch, "latency": 15}
        self.s.sendall(pr.frame(pr.INSTANCE_ADD, json.dumps(d).encode()))

    def audio(self, iid, pos, x, playing=True):
        self.s.sendall(pr.encode_audio(iid, pos, x, playing))

    def recv(self, timeout=2.0):
        self.s.settimeout(timeout)
        out = []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data = self.s.recv(65536)
            except socket.timeout:
                break
            if not data:
                break
            out += self.reader.feed(data)
            if out:
                break
        return out

    def close(self):
        self.s.close()


def test_framing_roundtrip():
    r = pr.FrameReader()
    msg = pr.encode_set_params(0xABC, {3: 1.5, 1: -2.0})
    assert r.feed(msg[:3]) == []
    [(t, p)] = r.feed(msg[3:])
    assert t == pr.SET_PARAMS
    assert p[:12] == (0xABC).to_bytes(8, "little") + (2).to_bytes(4, "little")
    x = np.arange(20, dtype=np.float32).reshape(10, 2)
    [(t, p)] = r.feed(pr.encode_audio(7, 4800, x))
    ch = pr.decode_audio(p)
    assert ch.instance == 7 and ch.pos == 4800 and np.array_equal(ch.samples, x)
    with pytest.raises(pr.ProtocolError):
        r.feed((0).to_bytes(4, "little") + b"\x01")


def test_server_capture_alignment_and_params(tmp_path):
    events = []
    with LinkServer(port=0, on_event=lambda k, d: events.append(k)) as srv:
        fp = FakePlugin(srv.port)
        fp.add(1, "channel", "Kick In")
        fp.add(2, "channel", "Vox Lead", ch=1)
        assert srv.wait_for(lambda xs: len(xs) == 2)
        srv.start_capture(tmp_path / "cap")
        [(t, p)] = fp.recv()
        assert t == pr.CAPTURE and p == b"\x01"
        a = np.full((256, 2), 0.25, np.float32)
        b = np.full((256, 1), -0.5, np.float32)
        fp.audio(1, 48000, a)
        fp.audio(1, 48256, a * 2)
        fp.audio(1, 48256 + 512, a)          # Lücke von 256 Frames -> Stille
        fp.audio(1, 48000, a * 3)            # zweiter Durchlauf überschreibt
        fp.audio(2, 48256, b)
        fp.audio(2, 0, b, playing=False)     # gestoppt: verworfen
        time.sleep(0.3)
        res = srv.stop_capture()
        fp.close()
    assert res.start_pos == 48000 and res.end_pos == 48256 + 768
    k = np.asarray(sf.read(res.files[f"{1:016x}"], always_2d=True)[0])
    v = np.asarray(sf.read(res.files[f"{2:016x}"], always_2d=True)[0])
    assert k.shape == (1024, 2) and v.shape == (1024, 1)
    assert np.allclose(k[:256], 0.75) and np.allclose(k[256:512], 0.5) and np.allclose(k[512:768], 0)
    assert np.allclose(v[:256], 0) and np.allclose(v[256:512], -0.5)
    assert res.instances[f"{1:016x}"]["channel_name"] == "Kick In"
    assert "instance" in events and "capture" in events
    assert not list((tmp_path / "cap").glob(".*"))  # Temp-Dateien aufgeräumt


def test_capture_never_overwrites(tmp_path):
    d = tmp_path / "cap"
    d.mkdir()
    (d / "Kick In.wav").write_bytes(b"original")
    with LinkServer(port=0) as srv:
        fp = FakePlugin(srv.port)
        fp.add(1, "channel", "Kick In")
        assert srv.wait_for(lambda xs: len(xs) == 1)
        srv.start_capture(d)
        fp.recv()
        fp.audio(1, 0, np.zeros((256, 2), np.float32))
        time.sleep(0.2)
        res = srv.stop_capture()
        fp.close()
    assert (d / "Kick In.wav").read_bytes() == b"original"
    assert res.files[f"{1:016x}"].endswith("Kick In (2).wav")


def _plan():
    tracks = [{"id": "kick", "name": "Kick In", "enabled": True, "trim_db": -3.0, "fader_db": -6.0,
               "hpf": {"freq": 40.0, "order": 2}, "eq": [], "comp": {}, "gate": {}, "deesser": {}, "saturation": {}},
              {"id": "vox", "name": "Vox Lead", "enabled": True, "trim_db": 1.0, "fader_db": -2.0},
              {"id": "gl", "name": "Gtr Rhythm L", "enabled": True},
              {"id": "gr", "name": "Gtr Rhythm R", "enabled": True}]
    return {"sample_rate": 48000, "tracks": tracks,
            "buses": {"drums": {"comp": {"enabled": True, "threshold_db": -20, "ratio": 3, "attack_ms": 10,
                                         "release_ms": 120}}},
            "mix_bus": {"input_gain_db": -1.5, "comp": {}}, "master": {"true_peak_db": -1.0}}


def test_matching_rules():
    insts = [Instance(1, "channel", "Kick In"), Instance(2, "channel", "vox lead "), Instance(3, "channel", "Gtr Rhythm"),
             Instance(4, "bus", "Schlagzeug"), Instance(5, "bus", "Stereo Out"), Instance(6, "master", "Stereo Out"),
             Instance(7, "channel", "Tambourine")]
    r = match_instances(insts, _plan())
    m = r.by_instance()
    assert m[f"{1:016x}"].target == "kick" and m[f"{2:016x}"].target == "vox"
    assert m[f"{3:016x}"].target is None and any("Gtr Rhythm" in c for c in r.conflicts)  # L/R mehrdeutig
    assert m[f"{4:016x}"].target == "drums" and m[f"{5:016x}"].target == "mix_bus"
    assert m[f"{6:016x}"].target == "master" and m[f"{7:016x}"].target is None
    assert set(r.unmatched_tracks) == {"Gtr Rhythm L", "Gtr Rhythm R"}
    r2 = match_instances(insts, _plan(), overrides={f"{3:016x}": "gl"})
    assert r2.by_instance()[f"{3:016x}"].target == "gl"
    assert "Gtr Rhythm L" not in r2.unmatched_tracks


def test_plan_values_are_plain_and_complete():
    r = match_instances([Instance(1, "channel", "Kick In")], _plan())
    v = plan_values(_plan(), r.matches[0])
    pk = P.by_key("channel")
    assert v[pk["trim_db"]["id"]] == -3.0 and v[pk["output_db"]["id"]] == -6.0 and v[pk["hpf_freq"]["id"]] == 40.0
    assert all(not pk[k].get("readonly") for k in pk if pk[k]["id"] in v)
    assert len(neutral_values("master")) > 10


@pytest.mark.native
def test_link_with_native_hub(link_client, tmp_path):
    with LinkServer(port=0) as srv:
        env = dict(os.environ, AIME_LINK_PORT=str(srv.port))
        proc = subprocess.Popen([str(link_client), "--names", "Kick In,Vox Lead", "--seconds", "4"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert srv.wait_for(lambda xs: len(xs) == 2, timeout=5), "Hub hat sich nicht verbunden"
            srv.start_capture(tmp_path / "cap")
            time.sleep(1.2)
            res = srv.stop_capture()
            r = match_instances(srv.instances(), _plan())
            pushed = push_plan(srv, _plan(), r)
            assert len(pushed["sent"]) == 2 and not pushed["failed"]
            out, err = proc.communicate(timeout=10)
        finally:
            proc.kill()
    assert len(res.files) == 2 and not res.warnings, res.warnings
    for k, f in enumerate(sorted(res.files.values(), key=lambda p: "Vox" in p)):
        y, sr = sf.read(f, always_2d=True)
        assert sr == 48000 and len(y) > 0.8 * 48000
        n = np.arange(res.start_pos, res.end_pos)
        ref = 0.5 * np.sin(2 * np.pi * 100.0 * (k + 1) * n / 48000)  # Kick 100 Hz, Vox 200 Hz (link_client)
        assert np.max(np.abs(y[:, 0] - ref)) < 1e-5  # lückenlos und positionsgenau
    got = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    pk = P.by_key("channel")
    kick = {g["id"]: g["value"] for g in got if g["instance"] == f"{0x1000:016x}"}
    assert abs(kick[pk["trim_db"]["id"]] + 3.0) < 1e-6 and abs(kick[pk["output_db"]["id"]] + 6.0) < 1e-6
