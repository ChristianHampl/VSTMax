"""Ordnerüberwachung: Stem-Exporte aus Cubase automatisch mischen und mastern.

Jeder Unterordner des Eingangsordners gilt als ein Song (Dateien direkt im Eingangsordner als ein
Song "Eingang"). Ein Song wird verarbeitet, sobald sich seine Audiodateien `settle_s` Sekunden lang
nicht mehr verändert haben (Cubase schreibt beim Export nacheinander). Jeder Stand (Name, Größe,
Änderungszeit aller Dateien) wird nur einmal verarbeitet; der Status liegt im Ausgabeordner, in den
Eingangsordner wird nichts geschrieben.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from engine.audio_io import is_supported

from ..project.model import Project
from .pipeline import Pipeline


@dataclass
class WatchOptions:
    profile_id: str = "modern_metal"
    purpose: str = "profile"
    settle_s: float = 5.0
    min_files: int = 2
    optimize_iterations: int = 8


@dataclass
class WatchEvent:
    song: str
    status: str            # "verarbeitet" | "fehler"
    folder: str | None = None
    message: str = ""
    files: list[str] = field(default_factory=list)


def _song_groups(inbox: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for p in sorted(inbox.iterdir()):
        if p.is_dir() and not p.name.startswith("."):
            files = [f for f in sorted(p.iterdir()) if f.is_file() and is_supported(f)]
            if files:
                groups[p.name] = files
        elif p.is_file() and is_supported(p):
            groups.setdefault("Eingang", []).append(p)
    return groups


def _fingerprint(files: list[Path]) -> tuple[str, float]:
    h = hashlib.sha1()
    newest = 0.0
    for f in files:
        st = f.stat()
        h.update(f"{f.name}|{st.st_size}|{st.st_mtime_ns}".encode())
        newest = max(newest, st.st_mtime)
    return h.hexdigest(), newest


class FolderWatcher:
    def __init__(self, inbox: str | Path, outbox: str | Path, options: WatchOptions | None = None,
                 on_event: Callable[[WatchEvent], None] | None = None):
        self.inbox = Path(inbox)
        self.outbox = Path(outbox)
        if self.outbox.resolve() == self.inbox.resolve() or self.inbox.resolve() in self.outbox.resolve().parents:
            raise ValueError("Ausgabeordner darf nicht im überwachten Ordner liegen")
        self.opt = options or WatchOptions()
        self.on_event = on_event
        self.state_file = self.outbox / ".aime_watch_state.json"
        self.outbox.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, str] = json.loads(self.state_file.read_text()) if self.state_file.exists() else {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def scan_once(self, now: float | None = None) -> list[WatchEvent]:
        now = time.time() if now is None else now
        events = []
        for song, files in _song_groups(self.inbox).items():
            if len(files) < self.opt.min_files:
                continue
            fp, newest = _fingerprint(files)
            if self.state.get(song) == fp or now - newest < self.opt.settle_s:
                continue
            ev = self._process(song, files)
            self.state[song] = fp
            self.state_file.write_text(json.dumps(self.state, indent=2))
            events.append(ev)
            if self.on_event:
                self.on_event(ev)
        return events

    def _process(self, song: str, files: list[Path]) -> WatchEvent:
        p = Project(name=song, profile_id=self.opt.profile_id, purpose=self.opt.purpose,
                    optimize_iterations=self.opt.optimize_iterations, output_dir=str(self.outbox))
        p.add_files([str(f) for f in files])
        try:
            res = Pipeline(p).run_all()
            return WatchEvent(song, "verarbeitet", res["folder"], files=[str(f) for f in files])
        except Exception as exc:  # ein defekter Song darf die Überwachung nicht beenden
            return WatchEvent(song, "fehler", None, f"{type(exc).__name__}: {exc}", [str(f) for f in files])

    def start(self, interval_s: float = 2.0):
        def loop():
            while not self._stop.wait(interval_s):
                self.scan_once()

        self._thread = threading.Thread(target=loop, name="aime-watch", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
