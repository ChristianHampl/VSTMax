"""Projektmodell (.aime.json). Speichert nur Verweise auf Audiodateien, nie Kopien."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from engine.audio_io import is_supported
from engine.profiles import Character

PROJECT_SUFFIX = ".aime.json"


def _tid(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:24] or "track"
    return f"{slug}_{uuid.uuid4().hex[:6]}"


@dataclass
class TrackRef:
    path: str
    name: str = ""
    id: str = ""
    role_override: str | None = None
    enabled: bool = True
    fingerprint: str | None = None
    cubase_channel: str | None = None  # Spurname in Cubase (für Plugin-Link/MIDI Remote)
    cubase_channel_uid: str | None = None

    def __post_init__(self):
        if not self.name:
            self.name = Path(self.path).stem
        if not self.id:
            self.id = _tid(self.name)


@dataclass
class Project:
    name: str = "Neues Projekt"
    tracks: list[TrackRef] = field(default_factory=list)
    profile_id: str = "modern_metal"
    character: Character = field(default_factory=Character)
    purpose: str = "profile"  # siehe engine.mastering.PURPOSES
    reference_path: str | None = None
    reference_match: float = 0.5
    output_dir: str | None = None
    export_sample_rate: int | None = None  # None = wie Quelle
    export_bit_depth: int = 24
    export_stems: bool = True
    excerpt_s: float = 45.0
    optimize_iterations: int = 8
    ml_model_path: str | None = None
    path: str | None = None

    def add_files(self, paths: list[str]) -> list[str]:
        added, existing = [], {Path(t.path).resolve() for t in self.tracks}
        for p in paths:
            pp = Path(p)
            if pp.is_dir():
                added += self.add_files(sorted(str(c) for c in pp.iterdir()))
                continue
            if not is_supported(pp) or pp.resolve() in existing:
                continue
            self.tracks.append(TrackRef(path=str(pp.resolve())))
            existing.add(pp.resolve())
            added.append(str(pp))
        return added

    def track(self, tid: str) -> TrackRef:
        for t in self.tracks:
            if t.id == tid:
                return t
        raise KeyError(tid)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["character"] = self.character.to_dict()
        d.pop("path", None)
        d["format"] = "aime-project"
        d["version"] = 1
        return d

    def save(self, path: str | Path) -> str:
        p = Path(path)
        if not p.name.endswith(PROJECT_SUFFIX):
            p = p.with_name(p.name + PROJECT_SUFFIX)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        self.path = str(p)
        return str(p)

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if d.get("format") != "aime-project":
            raise ValueError("Keine AI-Mix-Engineer-Projektdatei")
        d.pop("format", None)
        d.pop("version", None)
        tracks = [TrackRef(**t) for t in d.pop("tracks", [])]
        ch = Character(**d.pop("character", {}))
        p = cls(tracks=tracks, character=ch, **d)
        p.path = str(path)
        return p
