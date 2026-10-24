"""Autopilot und Ordnerüberwachung Ende-zu-Ende (ohne Cubase: Plug-in-Seite simuliert)."""

import struct
import threading
import time

import numpy as np
import pytest

from app.orchestration.autopilot import Autopilot, AutopilotOptions
from app.orchestration.watcher import FolderWatcher, WatchOptions
from engine.audio_io import load_audio
from engine.synth import write_song
from integration.midi_remote.bridge import MidiRemoteBridge
from integration.midi_remote.simulator import CubaseSimulator
from integration.plugin_link import protocol as pr
from integration.plugin_link.server import LinkServer
from integration.protocol import params as P
from tests.test_plugin_link import FakePlugin

SR = 48000


@pytest.fixture(scope="module")
def short_song(tmp_path_factory):
    d = tmp_path_factory.mktemp("short")
    write_song(d, sr=SR, bars=2, with_problems=True, seed=5)
    return d


class FakeCubase(threading.Thread):
    """Spielt die Stems wie Cubase ab, sobald Capture aktiv ist, und sammelt empfangene Parameter."""

    def __init__(self, port, stems: dict[str, np.ndarray]):
        super().__init__(daemon=True)
        self.fp = FakePlugin(port)
        self.stems = stems
        self.ids = {name: 0x100 + k for k, name in enumerate(stems)}
        for name, iid in self.ids.items():
            self.fp.add(iid, "channel", name)
        self.fp.add(0x900, "bus", "Drums")
        self.fp.add(0x901, "master", "Stereo Out")
        self.params: dict[int, dict[int, float]] = {}
        self.stop_flag = False

    def run(self):
        start_pos = 96000  # Song beginnt bei Takt 3 im Projekt
        streamed = False
        while not self.stop_flag:
            for t, p in self.fp.recv(timeout=0.1):
                if t == pr.CAPTURE and p == b"\x01" and not streamed:
                    n = max(len(x) for x in self.stems.values())
                    for o in range(0, n, 256):
                        for name, x in self.stems.items():
                            self.fp.audio(self.ids[name], start_pos + o, x[o:o + 256].astype(np.float32))
                    for name in self.stems:  # Transport gestoppt
                        self.fp.audio(self.ids[name], start_pos + n, np.zeros((256, 2), np.float32), playing=False)
                    streamed = True
                elif t == pr.SET_PARAMS:
                    iid, cnt = struct.unpack_from("<QI", p, 0)
                    self.params[iid] = {struct.unpack_from("<I", p, 12 + 12 * k)[0]:
                                        struct.unpack_from("<d", p, 16 + 12 * k)[0] for k in range(cnt)}


def test_autopilot_capture_plan_push_undo(short_song, tmp_path):
    stems = {}
    for f in sorted(short_song.glob("*.wav")):
        x = load_audio(f).samples
        stems[f.stem] = np.column_stack([x[:, 0]] * 2) if x.shape[1] == 1 else x
    sim = CubaseSimulator(list(stems))
    bridge = MidiRemoteBridge(sim, feedback_timeout=0.02)
    sim.attach(bridge)
    with LinkServer(port=0) as srv:
        cub = FakeCubase(srv.port, stems)
        cub.start()
        assert srv.wait_for(lambda xs: len(xs) == len(stems) + 2)
        ap = Autopilot(srv, tmp_path / "work", AutopilotOptions(stop_after_idle_s=0.3, optimize_iterations=2),
                       bridge=bridge)
        res = ap.capture()
        assert sim.transport == ["start", "stop"]
        assert res.start_pos == 96000 and not res.warnings
        for hid, path in res.files.items():
            name = res.instances[hid]["channel_name"]
            y = load_audio(path).samples
            assert np.allclose(y, stems[name].astype(np.float32), atol=1e-7), name
        proj = ap.build_project(res)
        assert sorted(t.name for t in proj.tracks) == sorted(stems)
        ap.plan()
        report = ap.push()
        time.sleep(0.5)
        assert not report["failed"]
        assert len(report["sent"]) == len(stems) + 2, report
        assert set(cub.params) == set(cub.ids.values()) | {0x900, 0x901}
        plan_tracks = {t["name"]: t for t in ap.pipeline.s.plan["tracks"]}
        pk = P.by_key("channel")
        for name, iid in cub.ids.items():
            exp, _ = P.channel_params(plan_tracks[name], SR)
            assert abs(cub.params[iid][pk["output_db"]["id"]] - exp["output_db"]) < 1e-9
        assert "mixconsole" in report and not report["mixconsole"]["not_found"]
        # Undo: erster Push -> Plug-in-Defaults
        cub.params.clear()
        u = ap.undo()
        time.sleep(0.5)
        assert len(u["restored"]) == len(stems) + 2
        d = P.defaults("channel")
        some = cub.params[next(iter(cub.ids.values()))]
        assert some[pk["output_db"]["id"]] == d["output_db"]
        cub.stop_flag = True
    # Originale unberührt, Ausgaben nur im Arbeitsordner
    assert all(f.stat().st_size > 0 for f in short_song.glob("*.wav"))
    assert (ap.session / "export").exists()


def test_watcher_processes_stable_song_once(short_song, tmp_path):
    inbox, outbox = tmp_path / "in", tmp_path / "out"
    (inbox / "Song A").mkdir(parents=True)
    for f in sorted(short_song.glob("*.wav"))[:4]:
        (inbox / "Song A" / f.name).write_bytes(f.read_bytes())
    before = {p.name: p.read_bytes() for p in (inbox / "Song A").iterdir()}
    w = FolderWatcher(inbox, outbox, WatchOptions(settle_s=2.0, optimize_iterations=1))
    assert w.scan_once(now=time.time()) == []          # noch nicht stabil
    ev = w.scan_once(now=time.time() + 10)
    assert len(ev) == 1 and ev[0].status == "verarbeitet", ev
    assert w.scan_once(now=time.time() + 20) == []      # gleicher Stand -> nicht erneut
    assert {p.name: p.read_bytes() for p in (inbox / "Song A").iterdir()} == before
    with pytest.raises(ValueError):
        FolderWatcher(inbox, inbox / "out")
