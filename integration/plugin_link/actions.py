"""Zuordnung Cubase-Kanäle <-> Mix-Plan und Parameter-Push über den Plugin-Link."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from integration.protocol import params as P

from .server import Instance, LinkServer

BUS_ALIASES = {
    "drums": ["drums", "drum", "schlagzeug", "kit", "drum bus", "drums bus"],
    "bass": ["bass", "bass bus", "low end"],
    "guitars": ["guitars", "guitar", "gitarren", "gitarre", "gtr", "gtrs", "guitar bus"],
    "vocals": ["vocals", "vocal", "vox", "gesang", "vox bus", "vocal bus"],
    "keys": ["keys", "synths", "synth", "orchestra", "orch"],
    "other": ["other", "fx", "sonstiges"],
}
MIXBUS_ALIASES = ["stereo out", "mix bus", "mixbus", "mix", "main", "master bus", "summe"]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")).strip()


@dataclass
class Match:
    instance: str
    plugin: str
    channel_name: str
    target: str | None             # Plan-Spur-ID, Bus-ID, "mix_bus" oder "master"
    target_name: str | None
    score: float
    reason: str


@dataclass
class MatchResult:
    matches: list[Match] = field(default_factory=list)
    unmatched_tracks: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def by_instance(self) -> dict[str, Match]:
        return {m.instance: m for m in self.matches}


def _score(a: str, b: str) -> float:
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def match_instances(instances: list[Instance], plan: dict, overrides: dict[str, str] | None = None,
                    min_score: float = 0.75) -> MatchResult:
    """Ordnet Instanzen eindeutig zu. overrides: Instanz (hex) -> Ziel, hat Vorrang (manuelle Korrektur).

    Kanalzüge: exakter Name (oder TrackRef.cubase_channel im Plan), sonst Ähnlichkeit >= min_score.
    Unsichere/mehrdeutige Fälle werden NICHT automatisch zugeordnet, sondern als Konflikt gemeldet.
    """
    overrides = overrides or {}
    res = MatchResult()
    tracks = [t for t in plan.get("tracks", []) if t.get("enabled", True)]
    used: set[str] = set()
    ch_inst = [i for i in instances if i.plugin == "channel"]
    pending: list[tuple[float, Instance, dict, str]] = []
    for inst in ch_inst:
        if inst.hex_id in overrides:
            continue
        cands = []
        for t in tracks:
            names = [t["name"]] + ([t["cubase_channel"]] if t.get("cubase_channel") else [])
            s = max(_score(inst.channel_name, n) for n in names)
            cands.append((s, t))
        cands.sort(key=lambda c: -c[0])
        if not cands or cands[0][0] < min_score:
            res.matches.append(Match(inst.hex_id, "channel", inst.channel_name, None, None,
                                     cands[0][0] if cands else 0.0, "keine passende Plan-Spur"))
            continue
        if len(cands) > 1 and cands[0][0] < 1.0 and cands[0][0] - cands[1][0] < 0.05:
            res.conflicts.append(f"'{inst.channel_name}' passt ähnlich gut zu '{cands[0][1]['name']}' und "
                                 f"'{cands[1][1]['name']}' - bitte manuell zuordnen")
            res.matches.append(Match(inst.hex_id, "channel", inst.channel_name, None, None, cands[0][0], "mehrdeutig"))
            continue
        pending.append((cands[0][0], inst, cands[0][1], "exakter Name" if cands[0][0] == 1.0 else "ähnlicher Name"))
    for s, inst, t, why in sorted(pending, key=lambda p: -p[0]):
        if t["id"] in used:
            res.conflicts.append(f"'{inst.channel_name}': Plan-Spur '{t['name']}' ist bereits zugeordnet")
            res.matches.append(Match(inst.hex_id, "channel", inst.channel_name, None, None, s, "doppelt"))
            continue
        used.add(t["id"])
        res.matches.append(Match(inst.hex_id, "channel", inst.channel_name, t["id"], t["name"], s, why))

    buses = plan.get("buses", {})
    for inst in instances:
        if inst.hex_id in overrides or inst.plugin == "channel":
            continue
        if inst.plugin == "master":
            res.matches.append(Match(inst.hex_id, "master", inst.channel_name, "master", "Master", 1.0, "Plug-in-Typ"))
            continue
        n = norm(inst.channel_name)
        target = None
        if any(n == norm(a) for a in MIXBUS_ALIASES) and plan.get("mix_bus"):
            target = "mix_bus"
        else:
            for gid in buses:
                if n == norm(gid) or any(n == norm(a) for a in BUS_ALIASES.get(gid, [])):
                    target = gid
                    break
        if target and target in used:
            res.conflicts.append(f"Bus '{target}' mehrfach in Cubase vorhanden ('{inst.channel_name}')")
            target = None
        if target:
            used.add(target)
        res.matches.append(Match(inst.hex_id, inst.plugin, inst.channel_name, target, target, 1.0 if target else 0.0,
                                 "Busname" if target else "kein passender Bus"))

    for hid, target in overrides.items():
        inst = next((i for i in instances if i.hex_id == hid), None)
        if inst is None:
            continue
        name = next((t["name"] for t in tracks if t["id"] == target), target)
        res.matches.append(Match(hid, inst.plugin, inst.channel_name, target, name, 1.0, "manuell"))
        used.add(target)
    res.unmatched_tracks = [t["name"] for t in tracks if t["id"] not in used]
    return res


def plan_values(plan: dict, match: Match, master_report: dict | None = None) -> dict[int, float]:
    """Klarwerte (ID -> Wert) für das Ziel einer Zuordnung; leere Map, wenn nicht anwendbar."""
    if match.target is None:
        return {}
    if match.plugin == "channel":
        t = next((t for t in plan["tracks"] if t["id"] == match.target), None)
        if t is None:
            return {}
        vals, _ = P.channel_params(t, plan.get("sample_rate"))
        plugin = "channel"
    elif match.plugin == "bus" and match.target == "mix_bus":
        vals, _ = P.mixbus_params(plan["mix_bus"])
        plugin = "bus"
    elif match.plugin == "bus":
        vals, _ = P.bus_params(plan["buses"][match.target])
        plugin = "bus"
    elif match.plugin == "master":
        vals, _ = P.master_params(master_report, plan.get("master", {}))
        plugin = "master"
    else:
        return {}
    pk = P.by_key(plugin)
    return {pk[k]["id"]: float(v) for k, v in vals.items() if not pk[k].get("readonly")}


def push_plan(server: LinkServer, plan: dict, result: MatchResult, master_report: dict | None = None) -> dict:
    sent, failed = {}, []
    for m in result.matches:
        vals = plan_values(plan, m, master_report)
        if not vals:
            continue
        if server.set_params(int(m.instance, 16), vals):
            sent[m.instance] = {"target": m.target, "channel_name": m.channel_name, "count": len(vals)}
        else:
            failed.append(m.instance)
    return {"sent": sent, "failed": failed}


def neutral_values(plugin: str) -> dict[int, float]:
    """Neutrale Defaults (Undo/Zurücksetzen eines Pushes)."""
    return {p["id"]: float(p["default"]) for p in P.expand(plugin) if not p.get("readonly")}
