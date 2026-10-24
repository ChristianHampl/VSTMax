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


def test_installer_pins_runtime_deps():
    # soundfile importiert typing_extensions, cffi braucht pycparser, mido packaging.
    # pynsist packt nur die hier genannten Raeder ein.
    cfg = open(os.path.abspath(os.path.join(os.path.dirname(ROOT_FILE), "..", "installer", "installer.cfg")),
               encoding="utf-8").read()
    for pin in ("typing_extensions==4.16.0", "pycparser==3.11", "packaging==26.3", "soundfile==0.14.0"):
        assert pin in cfg


def test_shortcut_working_directory_is_install_dir():
    nsi = open(os.path.abspath(os.path.join(os.path.dirname(ROOT_FILE), "..", "installer", "pyapp.nsi")),
               encoding="utf-8").read()
    assert 'SetOutPath "$INSTDIR"' in nsi
    assert "HOMEDRIVE" not in nsi


def test_preload_qt_is_noop_off_windows():
    from app.main import _preload_qt_dlls
    assert os.name != "nt"
    _preload_qt_dlls()


def test_preamble_source_is_ascii():
    # pynsist schreibt diese Datei in die Windows-Codepage. Ein Nicht-ASCII-Byte
    # (z. B. ue = FC) macht das Startskript fuer Python 3 unlesbar.
    path = os.path.join(os.path.dirname(ROOT_FILE), "..", "installer", "qt_preamble.py")
    open(os.path.abspath(path), "rb").read().decode("ascii")


def test_missing_plugins_do_not_override(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM_PLUGIN_PATH", "unchanged")
    assert _preamble().configure_qt(tmp_path) is None
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == "unchanged"
