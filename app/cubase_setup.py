"""Kopiert das mitgelieferte Windows-Plug-in und das MIDI-Remote-Skript an die Cubase-Orte.

Keine Administratorrechte: das Plug-in landet im Benutzerordner, den Cubase ebenfalls durchsucht
(``%LOCALAPPDATA%\\Programs\\Common\\VST3``). Es werden nur die AIME-Dateien ersetzt.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def bundle_arch(bundle: Path) -> str:
    contents = bundle / "Contents"
    if not contents.is_dir():
        return ""
    for d in sorted(contents.iterdir()):
        if d.is_dir() and d.name != "Resources":
            return d.name
    return ""


def _search_roots() -> list[Path]:
    here = Path(__file__).resolve()
    return list(dict.fromkeys(here.parents[:5]))


def find_bundle() -> Path | None:
    rels = [Path("AIME.vst3"), Path("payload") / "AIME.vst3",
            Path("build") / "plugins" / "VST3" / "Release" / "AIME.vst3",
            Path("build") / "plugins" / "VST3" / "Debug" / "AIME.vst3"]
    for root in _search_roots():
        for rel in rels:
            p = root / rel
            if (p / "Contents").is_dir():
                return p
    return None


def find_script() -> Path | None:
    rels = [Path("AIME_Bridge.js"),
            Path("integration") / "midi_remote" / "AIME" / "Bridge" / "AIME_Bridge.js"]
    for root in _search_roots():
        for rel in rels:
            p = root / rel
            if p.is_file():
                return p
    return None


def vst3_user_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "Programs" / "Common" / "VST3"


def documents_dir() -> Path:
    if sys.platform == "win32":
        import ctypes

        buf = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    return Path.home() / "Documents"


def midi_destinations() -> list[Path]:
    steinberg = documents_dir() / "Steinberg"
    found = []
    if steinberg.is_dir():
        for child in sorted(steinberg.iterdir()):
            if child.is_dir() and child.name.lower().startswith("cubase"):
                found.append(child / "MIDI Remote" / "Driver Scripts" / "Local" / "AIME" / "Bridge" / "AIME_Bridge.js")
    if not found:
        found.append(steinberg / "Cubase" / "MIDI Remote" / "Driver Scripts" / "Local" / "AIME" / "Bridge"
                     / "AIME_Bridge.js")
    return found


def install_cubase_files(bundle: Path | None, script: Path | None, plugin_dest: Path,
                         script_dests: list[Path], required_arch: str) -> dict:
    messages: list[str] = []
    ok = True
    if bundle is None:
        ok = False
        messages.append("Kein Plug-in-Paket gefunden. Bitte den Windows-Installer (Setup) verwenden.")
    else:
        arch = bundle_arch(bundle)
        if arch != required_arch:
            ok = False
            messages.append(f"Das gefundene Plug-in ist für „{arch or 'unbekannt'}“ gebaut. "
                            f"Cubase auf diesem Rechner braucht „{required_arch}“.")
        else:
            if plugin_dest.exists():
                shutil.rmtree(plugin_dest)
            plugin_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(bundle, plugin_dest)
            messages.append(f"Plug-in installiert: {plugin_dest}")
    if script is None:
        ok = False
        messages.append("MIDI-Remote-Skript nicht gefunden.")
    else:
        for dest in script_dests:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(script, dest)
            messages.append(f"MIDI-Skript installiert: {dest}")
    if ok:
        messages.append("Cubase neu starten. Danach im Plug-in-Manager AIME Channel, AIME Bus und AIME Master prüfen.")
    return {"ok": ok, "messages": messages}


def install_for_this_machine() -> dict:
    if sys.platform != "win32":
        return {"ok": False, "messages": [
            "Diese Einrichtung gilt für Windows mit Cubase. Hier kannst du exportierte Spuren über den Tab "
            "„Projekt & Mix“ mischen, das Plug-in selbst wird auf diesem System nicht nach Cubase kopiert."]}
    return install_cubase_files(find_bundle(), find_script(), vst3_user_dir() / "AIME.vst3",
                                midi_destinations(), "x86_64-win")
