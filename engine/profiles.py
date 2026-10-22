"""Genre-Profile laden (mit Vererbung) und Klangcharakter anwenden."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path

def _profile_dir() -> Path:
    """Repo-Layout (profiles/ neben engine/) und Installer-Layout (profiles/ im Programmordner)."""
    here = Path(__file__).resolve().parent
    for c in (here.parent / "profiles", here.parent.parent.parent / "profiles"):
        if (c / "_base.json").is_file():
            return c
    return here.parent / "profiles"


PROFILE_DIR = _profile_dir()


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def list_profiles(profile_dir: Path | None = None) -> list[dict]:
    d = profile_dir or PROFILE_DIR
    out = []
    for p in sorted(d.glob("*.json")):
        if p.name.startswith("_"):
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        out.append({"id": data["id"], "name": data["name"], "description": data.get("description", "")})
    return out


def load_profile(profile_id: str, profile_dir: Path | None = None) -> dict:
    d = profile_dir or PROFILE_DIR
    path = d / f"{profile_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Profil nicht gefunden: {profile_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    parent = data.get("extends")
    if parent:
        base = load_profile(parent, d)
        data = deep_merge(base, {k: v for k, v in data.items() if k != "extends"})
    return data


@dataclass
class Character:
    """Vom Nutzer einstellbarer Klangcharakter (wirkt auf die Profilwerte)."""

    brightness: float = 0.0     # -1 dunkel .. +1 hell
    punch: float = 0.5          # 0 weich .. 1 maximale Transienten/Parallelkompression
    width: float = 1.0          # 0.5 schmal .. 1.2 sehr breit
    vocal_level_db: float = 0.0  # -3 .. +3 dB Vocals relativ zum Profil
    dynamics: float = 0.5       # 0 dicht/laut .. 1 offen/dynamisch

    def clamp(self) -> "Character":
        self.brightness = max(-1.0, min(1.0, float(self.brightness)))
        self.punch = max(0.0, min(1.0, float(self.punch)))
        self.width = max(0.5, min(1.2, float(self.width)))
        self.vocal_level_db = max(-3.0, min(3.0, float(self.vocal_level_db)))
        self.dynamics = max(0.0, min(1.0, float(self.dynamics)))
        return self

    def to_dict(self) -> dict:
        return asdict(self)


VOCAL_ROLES = ("lead_vocal", "scream_vocal", "backing_vocal")
BRIGHT_ROLES = ("overheads", "rhythm_guitar", "lead_guitar", "lead_vocal", "scream_vocal", "backing_vocal", "snare")


def apply_character(profile: dict, ch: Character) -> dict:
    p = copy.deepcopy(profile)
    ch = ch.clamp()
    r = p["rules"]
    r["transient_preservation"] = min(1.0, r["transient_preservation"] * (0.7 + 0.6 * ch.punch))
    r["parallel_drums"] = max(0.0, min(0.6, r["parallel_drums"] * (0.5 + ch.punch)))
    r["guitar_double_pan"] = min(1.0, r["guitar_double_pan"] * ch.width)
    r["overhead_width"] = r["overhead_width"] * ch.width
    r["room_width"] = r["room_width"] * ch.width
    r["backing_vocal_spread"] = min(1.0, r["backing_vocal_spread"] * ch.width)
    for role in VOCAL_ROLES:
        if role in p["balance_lu"]:
            p["balance_lu"][role] += ch.vocal_level_db
    if abs(ch.brightness) > 1e-3:
        for role in BRIGHT_ROLES:
            eq = p["eq"].get(role)
            if eq is not None:
                eq.setdefault("moves", []).append(
                    {"type": "highshelf", "freq": 8000, "gain_db": round(2.0 * ch.brightness, 2), "q": 0.7,
                     "origin": "character"})
        p["mix_target"]["tilt_db_per_oct"] += 0.4 * ch.brightness
    gr_scale = 1.3 - 0.6 * ch.dynamics
    for dyn in p["dynamics"].values():
        if dyn.get("comp"):
            dyn["comp"]["target_gr_db"] = round(dyn["comp"]["target_gr_db"] * gr_scale, 2)
    p["master"]["target_lufs"] = round(p["master"]["target_lufs"] - (ch.dynamics - 0.5) * 2.0, 2)
    p["master"]["min_plr_db"] = round(p["master"]["min_plr_db"] + (ch.dynamics - 0.5) * 2.0, 2)
    p["character"] = ch.to_dict()
    return p
