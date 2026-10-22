"""Qt-Plug-in-Pfade des Windows-Installers."""

import importlib.util
import os

ROOT_FILE = __file__


def _preamble():
    path = os.path.join(os.path.dirname(ROOT_FILE), "..", "installer", "qt_preamble.py")
    spec = importlib.util.spec_from_file_location("qt_preamble_under_test", os.path.abspath(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_windows_wheel_layout(tmp_path, monkeypatch):
    plat = tmp_path / "pkgs" / "PySide6" / "plugins" / "platforms"
    plat.mkdir(parents=True)
    (plat / "qwindows.dll").write_bytes(b"x")
    monkeypatch.delenv("QT_PLUGIN_PATH", raising=False)
    found = _preamble().configure_qt(tmp_path)
    assert found.endswith(os.path.join("PySide6", "plugins"))
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"].endswith("platforms")
    assert "qwindows" not in os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"]


def test_qt_subdir_layout(tmp_path, monkeypatch):
    plat = tmp_path / "pkgs" / "PySide6" / "Qt" / "plugins" / "platforms"
    plat.mkdir(parents=True)
    (plat / "libqxcb.so").write_bytes(b"x")
    found = _preamble().configure_qt(tmp_path)
    assert found.endswith(os.path.join("Qt", "plugins"))
    assert os.environ["QT_PLUGIN_PATH"] == found


def test_missing_plugins_do_not_override(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "unchanged")
    assert _preamble().configure_qt(tmp_path) is None
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == "unchanged"
