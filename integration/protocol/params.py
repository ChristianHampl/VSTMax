"""Plugin-Parameterdefinitionen (aus plugin_params.json) und Abbildung Mix-Plan -> Parameter."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

PARAMS_JSON = Path(__file__).resolve().parent / "plugin_params.json"
EQ_TYPES = {"off": 0, "bell": 1, "lowshelf": 2, "highshelf": 3}


@lru_cache(maxsize=1)
def definitions() -> dict:
    return json.loads(PARAMS_JSON.read_text(encoding="utf-8"))


def expand(plugin: str) -> list[dict]:
    """Flache Parameterliste inkl. expandierter Gruppen (eq1_freq, dyn2_range_db, ...)."""
    out = []
    for p in definitions()["plugins"][plugin]["params"]:
        if "group" in p:
            for i in range(p["count"]):
                for j, f in enumerate(p["fields"]):
                    q = dict(f)
                    q["id"] = p["base_id"] + i * p["stride"] + j
                    q["key"] = f"{p['group']}{i + 1}_{f['key']}"
                    q["name"] = f"{p['group'].upper()} {i + 1} {f['name']}"
                    if q["type"] == "choice":
                        q["min"], q["max"] = 0, len(q["choices"]) - 1
                    out.append(q)
        else:
            out.append(dict(p))
    return sorted(out, key=lambda q: q["id"])


def by_key(plugin: str) -> dict[str, dict]:
    return {p["key"]: p for p in expand(plugin)}


def class_id_string(uid: list[str]) -> str:
    return "".join(u.upper().rjust(8, "0") for u in uid)


def to_normalized(p: dict, value: float) -> float:
    lo, hi = float(p["min"]), float(p["max"])
    v = min(max(float(value), lo), hi)
    if p["type"] == "log":
        return math.log(v / lo) / math.log(hi / lo)
    if p["type"] in ("bool",):
        return 1.0 if v >= 0.5 else 0.0
    if p["type"] == "choice":
        return round(v) / max(1, hi)
    return (v - lo) / (hi - lo)


def from_normalized(p: dict, norm: float) -> float:
    lo, hi = float(p["min"]), float(p["max"])
    n = min(max(float(norm), 0.0), 1.0)
    if p["type"] == "log":
        return lo * math.exp(n * math.log(hi / lo))
    if p["type"] == "bool":
        return 1.0 if n >= 0.5 else 0.0
    if p["type"] == "choice":
        return float(round(n * hi))
    return lo + n * (hi - lo)


def defaults(plugin: str) -> dict[str, float]:
    return {p["key"]: float(p["default"]) for p in expand(plugin)}


def _clip_note(notes: list, key: str, p: dict, v: float):
    if v < p["min"] or v > p["max"]:
        notes.append(f"{key}={v:.2f} außerhalb {p['min']}..{p['max']} - begrenzt")


def channel_params(t: dict, sample_rate: float | None = None) -> tuple[dict[str, float], list[str]]:
    """Mix-Plan-Spur -> AIME-Channel-Parameter (Klartextwerte)."""
    notes: list[str] = []
    v = defaults("channel")
    v["trim_db"] = t.get("trim_db", 0.0)
    v["polarity_invert"] = float(bool(t.get("polarity_invert")))
    v["invert_right"] = float(bool(t.get("invert_right")))
    v["dc_remove"] = float(bool(t.get("dc_remove")))
    g = t.get("gate", {})
    if g.get("enabled"):
        v.update(gate_on=1.0, gate_threshold_db=g["threshold_db"], gate_range_db=g["range_db"],
                 gate_attack_ms=g["attack_ms"], gate_hold_ms=g["hold_ms"], gate_release_ms=g["release_ms"])
    if t.get("hpf"):
        v["hpf_freq"] = t["hpf"]["freq"]
        v["hpf_steep"] = 1.0 if t["hpf"].get("order", 2) >= 4 else 0.0
    if t.get("lpf"):
        v["lpf_freq"] = t["lpf"]["freq"]
    eq = [b for b in t.get("eq", []) if abs(b.get("gain_db", 0)) > 0.05 and b["type"] in EQ_TYPES]
    if len(eq) > 8:
        eq = sorted(eq, key=lambda b: -abs(b["gain_db"]))
        notes.append(f"{len(eq) - 8} kleinste EQ-Bänder nicht übertragbar (max. 8)")
        eq = eq[:8]
    for i, b in enumerate(eq, start=1):
        v[f"eq{i}_type"] = float(EQ_TYPES[b["type"]])
        v[f"eq{i}_freq"] = b["freq"]
        v[f"eq{i}_gain_db"] = b["gain_db"]
        v[f"eq{i}_q"] = b.get("q", 0.7071)
    dyn = t.get("dyn_eq", [])
    if len(dyn) > 2:
        notes.append(f"{len(dyn) - 2} dynamische Bänder nicht übertragbar (max. 2)")
    sc_sources = {d["sidechain"] for d in dyn[:2] if d.get("sidechain")}
    if len(sc_sources) > 1:
        notes.append("Mehrere Sidechain-Quellen - das Plugin hat nur einen Sidechain-Eingang; "
                     f"nur '{sorted(sc_sources)[0]}' wird verwendet")
    for i, d in enumerate(dyn[:2], start=1):
        v.update({f"dyn{i}_on": 1.0, f"dyn{i}_freq": d["freq"], f"dyn{i}_q": d["q"],
                  f"dyn{i}_threshold_db": d.get("threshold_db") if d.get("threshold_db") is not None else -30.0,
                  f"dyn{i}_range_db": d["range_db"]})
        if d.get("sidechain") and d["sidechain"] == sorted(sc_sources)[0]:
            v[f"dyn{i}_sidechain"] = 1.0
            notes.append(f"Dyn-Band {i}: Sidechain-Eingang in Cubase mit Spur '{d['sidechain']}' verbinden")
    if t.get("delay_samples") and sample_rate:
        v["align_delay_ms"] = 1000.0 * t["delay_samples"] / sample_rate
    c = t.get("comp", {})
    if c.get("enabled"):
        v.update(comp_on=1.0, comp_threshold_db=c["threshold_db"], comp_ratio=c["ratio"], comp_attack_ms=c["attack_ms"],
                 comp_release_ms=c["release_ms"], comp_knee_db=c.get("knee_db", 6.0), comp_makeup_db=c.get("makeup_db", 0.0),
                 comp_mix=c.get("mix", 1.0))
    de = t.get("deesser", {})
    if de.get("enabled") and de.get("threshold_db") is not None:
        v.update(deess_on=1.0, deess_freq=de["freq"], deess_threshold_db=de["threshold_db"], deess_range_db=de["range_db"])
    s = t.get("saturation", {})
    v["sat_drive_db"] = s.get("drive_db", 0.0)
    v["sat_mix"] = s.get("mix", 1.0)
    v["output_db"] = t.get("fader_db", 0.0)
    v["pan"] = t.get("pan", 0.0)
    v["width"] = t.get("width", 1.0)
    pk = by_key("channel")
    for k, val in v.items():
        _clip_note(notes, k, pk[k], val)
    return v, notes


def bus_params(b: dict) -> tuple[dict[str, float], list[str]]:
    notes: list[str] = []
    v = defaults("bus")
    c = b.get("comp", {})
    if c.get("enabled"):
        v.update(comp_on=1.0, comp_threshold_db=c["threshold_db"], comp_ratio=c["ratio"], comp_attack_ms=c["attack_ms"],
                 comp_release_ms=c["release_ms"], comp_knee_db=c.get("knee_db", 6.0), comp_makeup_db=c.get("makeup_db", 0.0))
    p = b.get("parallel")
    if p:
        pc = p["comp"]
        v.update(par_amount=p["amount"], par_threshold_db=pc["threshold_db"], par_ratio=pc["ratio"],
                 par_attack_ms=pc["attack_ms"], par_release_ms=pc["release_ms"], par_makeup_db=pc.get("target_gr_db", 10.0),
                 par_drive_db=p.get("saturation_db", 0.0))
    v["sat_drive_db"] = b.get("saturation", {}).get("drive_db", 0.0)
    v["output_db"] = b.get("fader_db", 0.0)
    return v, notes


def master_params(report: dict | None, plan_master: dict) -> tuple[dict[str, float], list[str]]:
    notes: list[str] = []
    v = defaults("master")
    if report:
        for i, b in enumerate(report.get("eq", [])[:4], start=1):
            v.update({f"eq{i}_type": float(EQ_TYPES.get(b["type"], 1)), f"eq{i}_freq": b["freq"],
                      f"eq{i}_gain_db": b["gain_db"], f"eq{i}_q": b.get("q", 0.7)})
        bc = report.get("bus_comp")
        if bc:
            v.update(comp_on=1.0, comp_threshold_db=bc["threshold_db"], comp_ratio=bc["ratio"],
                     comp_attack_ms=bc["attack_ms"], comp_release_ms=bc["release_ms"], comp_knee_db=bc["knee_db"],
                     comp_makeup_db=bc.get("makeup_db", 0.0))
        v["limiter_gain_db"] = report.get("gain_db", 0.0)
        notes.append("Limiter-Drive bezieht sich auf den Mixpegel des Offline-Renderings; in Cubase am AIME-Master-"
                     "Lautheitsmesser nachkontrollieren")
    v["limiter_on"] = 1.0
    v["ceiling_dbtp"] = plan_master.get("true_peak_db", -1.0)
    pk = by_key("master")
    for k, val in v.items():
        _clip_note(notes, k, pk[k], val)
    return v, notes


def mixbus_params(mix_bus: dict) -> tuple[dict[str, float], list[str]]:
    """Mixbus (Stereo Out, vor AIME Master): fester Eingangsgain + Glue-Kompressor."""
    notes: list[str] = []
    v = defaults("bus")
    v["input_db"] = mix_bus.get("input_gain_db") or 0.0
    c = mix_bus.get("comp", {})
    if c.get("enabled") and c.get("threshold_db") is not None:
        v.update(comp_on=1.0, comp_threshold_db=c["threshold_db"], comp_ratio=c["ratio"], comp_attack_ms=c["attack_ms"],
                 comp_release_ms=c["release_ms"], comp_knee_db=c.get("knee_db", 6.0), comp_makeup_db=0.0)
    pk = by_key("bus")
    for k, val in v.items():
        _clip_note(notes, k, pk[k], val)
    return v, notes


def normalized_map(plugin: str, values: dict[str, float]) -> dict[int, float]:
    pk = by_key(plugin)
    return {pk[k]["id"]: to_normalized(pk[k], val) for k, val in values.items() if not pk[k].get("readonly")}
