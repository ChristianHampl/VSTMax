"""Kopieren von Plug-in und MIDI-Skript, ohne echte Cubase-Ordner anzufassen."""

from pathlib import Path

from app.cubase_setup import bundle_arch, install_cubase_files


def _bundle(root: Path, arch: str) -> Path:
    bundle = root / "AIME.vst3"
    (bundle / "Contents" / arch).mkdir(parents=True)
    (bundle / "Contents" / arch / "AIME.vst3").write_bytes(b"MZ-fake")
    (bundle / "Contents" / "Resources").mkdir()
    return bundle


def test_install_copies_matching_bundle_and_script(tmp_path):
    bundle = _bundle(tmp_path / "src", "x86_64-win")
    script = tmp_path / "AIME_Bridge.js"
    script.write_text("var midiremote_api = 1\n", encoding="utf-8")
    plugin_dest = tmp_path / "VST3" / "AIME.vst3"
    scripts = [tmp_path / "Cubase" / "AIME_Bridge.js", tmp_path / "Cubase 15" / "AIME_Bridge.js"]
    (plugin_dest / "Contents" / "x86_64-win").mkdir(parents=True)
    (plugin_dest / "Contents" / "x86_64-win" / "alt.txt").write_text("alt", encoding="utf-8")

    result = install_cubase_files(bundle, script, plugin_dest, scripts, "x86_64-win")
    assert result["ok"]
    assert (plugin_dest / "Contents" / "x86_64-win" / "AIME.vst3").read_bytes() == b"MZ-fake"
    assert not (plugin_dest / "Contents" / "x86_64-win" / "alt.txt").exists()
    assert all(p.read_text(encoding="utf-8").startswith("var") for p in scripts)
    assert bundle_arch(plugin_dest) == "x86_64-win"


def test_wrong_architecture_is_not_copied(tmp_path):
    bundle = _bundle(tmp_path / "src", "x86_64-linux")
    dest = tmp_path / "VST3" / "AIME.vst3"
    result = install_cubase_files(bundle, tmp_path / "fehlt.js", dest, [], "x86_64-win")
    assert not result["ok"]
    assert not dest.exists()
    assert any("x86_64-linux" in m for m in result["messages"])
