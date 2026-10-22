"""GUI (headless, Qt-Plattform 'offscreen') und Kommandozeile."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qapp():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _wait(win, qapp, timeout=300):
    end = time.time() + timeout
    while win._current is not None and time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()
    assert win._current is None, "Aufgabe nicht beendet"


def test_gui_full_flow(qapp, song_dir, tmp_path):
    from app.gui.main_window import MainWindow

    win = MainWindow()
    win.add_paths([str(song_dir)])
    n = len(list(song_dir.glob("*.wav")))
    assert win.table.rowCount() == n
    win.ed_out.setText(str(tmp_path / "out"))
    win.sp_iter.setValue(1)
    win.run_analyze()
    _wait(win, qapp)
    assert win.pipe is not None and len(win.pipe.s.classes) == n
    assert all(win.table.item(r, 4).text().endswith("%") for r in range(n))
    # manuelle Rollenkorrektur wirkt auf den Plan
    row = next(r for r in range(n) if win.table.item(r, 1).text() == "Vox Lead")
    cb = win.table.cellWidget(row, 2)
    cb.setCurrentIndex(cb.findData("scream_vocal"))
    win.run_preview()
    _wait(win, qapp)
    vox = next(t for t in win.pipe.s.plan["tracks"] if t["name"] == "Vox Lead")
    assert vox["role"] == "scream_vocal"
    a, b = win.pipe.preview_ab()
    assert a.shape == b.shape and a.shape[1] == 2
    win.run_export()
    _wait(win, qapp, 600)
    outs = list((tmp_path / "out").glob("*/master.wav"))
    assert len(outs) == 1
    assert "Master:" in win.log.toPlainText()
    win.close()


def test_gui_cubase_tab_lists_instances(qapp, tmp_path):
    from app.gui.main_window import MainWindow
    from tests.test_plugin_link import FakePlugin

    win = MainWindow()
    win.toggle_link(0)
    assert win.link is not None
    fp = FakePlugin(win.link.port)
    fp.add(0xAB, "channel", "Gitarre Ü")
    assert win.link.wait_for(lambda xs: len(xs) == 1)
    win.refresh_instances()
    assert win.inst_table.rowCount() == 1 and win.inst_table.item(0, 2).text() == "Gitarre Ü"
    fp.close()
    win.toggle_link()
    assert win.link is None
    win.close()


def _cli(*args, timeout=600):
    return subprocess.run([sys.executable, "-m", "app", *args], cwd=ROOT, capture_output=True, text=True,
                          timeout=timeout)


def test_cli_profiles_and_mix(song_dir, tmp_path):
    r = _cli("profiles")
    assert r.returncode == 0 and "modern_metal" in r.stdout and "streaming_loud" in r.stdout
    r = _cli("mix", str(song_dir), "--out", str(tmp_path), "--iterations", "1", "--profile", "thrash_metal",
             "--purpose", "streaming_loud", "--role", "Vox Lead=lead_vocal", "--brightness", "0.3")
    assert r.returncode == 0, r.stderr[-2000:]
    res = json.loads(r.stdout)
    assert (Path(res["folder"]) / "master.wav").exists()
    assert "thrash" in (Path(res["folder"]) / "plan.json").read_text(encoding="utf-8").lower()
    r = _cli("mix")
    assert r.returncode != 0 and "angeben" in r.stderr
