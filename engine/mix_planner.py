"""Regelbasierter Mix-Planer: erzeugt einen nachvollziehbaren JSON-Mix-Plan.

Jede Entscheidung wird mit Begründung protokolliert. Unsichere Entscheidungen
(z. B. bei niedriger Rollen-Konfidenz) werden markiert.
"""

from __future__ import annotations

import copy
import datetime as _dt
import math
from dataclasses import dataclass, field

import numpy as np

from .analysis import THIRD_OCTAVE_CENTERS, TrackAnalysis
from .classification import ROLE_GROUP, ROLE_LABELS_DE, Classification
from .masking import find_conflicts

PLAN_VERSION = 1
TRIM_TARGET_RMS = -18.0
TRIM_MAX_PEAK = -6.0
LOUDNESS_ANCHOR = -23.0  # Lautheit (LUFS) einer Spur mit balance_lu = 0 vor dem Mixbus

# Priorität bei Maskierung: höher gewinnt (die andere Spur wird abgesenkt)
ROLE_PRIORITY = {
    "lead_vocal": 100, "scream_vocal": 98, "snare": 90, "kick": 85, "bass": 80, "lead_guitar": 75,
    "toms": 70, "backing_vocal": 60, "rhythm_guitar": 55, "clean_guitar": 55, "synth": 40,
    "overheads": 35, "room": 30, "hihat": 30, "other": 10,
}

NO_HARSH_ROLES = {"kick", "toms", "bass", "hihat", "room"}


@dataclass
class TrackInput:
    id: str
    name: str
    analysis: TrackAnalysis
    classification: Classification
    role_override: str | None = None
    path: str | None = None

    @property
    def role(self) -> str:
        return self.role_override or self.classification.role

    @property
    def confidence(self) -> float:
        return 1.0 if self.role_override else self.classification.confidence


@dataclass
class PlanLog:
    entries: list = field(default_factory=list)

    def add(self, track: str | None, param: str, value, reason: str, uncertain: bool = False):
        self.entries.append({"track": track, "param": param, "value": value, "reason": reason,
                             "uncertain": bool(uncertain)})


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _merge_eq_moves(moves: list[dict]) -> list[dict]:
    """Fasst Glockenfilter im Abstand < 1/3 Oktave zusammen (keine Doppelabsenkungen)."""
    out: list[dict] = []
    for m in moves:
        if m["type"] != "bell":
            out.append(m)
            continue
        merged = False
        for o in out:
            if o["type"] == "bell" and abs(math.log2(o["freq"] / m["freq"])) < 1 / 3 and \
                    np.sign(o["gain_db"]) == np.sign(m["gain_db"]):
                o["gain_db"] = round(float(np.sign(o["gain_db"]) * min(abs(o["gain_db"]) + abs(m["gain_db"]) * 0.5,
                                                                         max(abs(o["gain_db"]), abs(m["gain_db"])) + 2)), 2)
                o["q"] = max(o["q"], m["q"])
                o.setdefault("reasons", []).append(m.get("origin", "profile"))
                merged = True
                break
        if not merged:
            out.append(m)
    return out


def detect_resonances(a: TrackAnalysis, lo: float, hi: float, max_cut: float, n: int = 2) -> list[dict]:
    lv = np.array(a.third_octave_db)
    res = []
    for i in range(2, len(lv) - 2):
        fc = THIRD_OCTAVE_CENTERS[i]
        if fc < lo or fc > hi:
            continue
        neigh = np.median(np.r_[lv[i - 2:i], lv[i + 1:i + 3]])
        excess = lv[i] - neigh
        if excess > 5.0 and lv[i] > lv.max() - 20:
            res.append((excess, fc))
    res.sort(reverse=True)
    out = []
    for excess, fc in res[:n]:
        cut = round(min(max_cut, (excess - 3.0) * 0.7), 2)
        out.append({"type": "bell", "freq": float(fc), "gain_db": -cut, "q": 4.0, "origin": "resonance",
                    "excess_db": round(float(excess), 2)})
    return out


def plan_mix(
    tracks: list[TrackInput],
    profile: dict,
    sr: int,
    tempo_bpm: float = 120.0,
    pair_results: dict[tuple[str, str], dict] | None = None,
    polarity_results: dict[tuple[str, str], dict] | None = None,
) -> dict:
    log = PlanLog()
    rules = profile["rules"]
    pair_results = pair_results or {}
    polarity_results = polarity_results or {}
    by_id = {t.id: t for t in tracks}
    active = [t for t in tracks if not t.analysis.is_silent]
    roles = {t.id: t.role for t in active}
    role_count: dict[str, int] = {}
    for r in roles.values():
        role_count[r] = role_count.get(r, 0) + 1

    plan_tracks: dict[str, dict] = {}
    for t in tracks:
        a = t.analysis
        role = t.role
        uncertain = t.confidence < 0.5
        tp: dict = {
            "id": t.id, "name": t.name, "path": t.path, "role": role,
            "role_label": ROLE_LABELS_DE.get(role, role),
            "role_confidence": round(t.confidence, 3), "role_source": "manual" if t.role_override else t.classification.source,
            "group": ROLE_GROUP.get(role, "other"), "enabled": not a.is_silent,
            "dc_remove": False, "polarity_invert": False, "invert_right": False, "delay_samples": 0,
            "trim_db": 0.0, "fader_db": 0.0, "pan": 0.0, "width": 1.0,
            "hpf": None, "lpf": None, "eq": [], "dyn_eq": [],
            "gate": {"enabled": False}, "comp": {"enabled": False}, "deesser": {"enabled": False},
            "saturation": {"drive_db": 0.0, "mix": 1.0},
            "sends": {"reverb_db": None, "delay_db": None},
            "target_lufs": None, "uncertain": uncertain, "notes": [],
        }
        plan_tracks[t.id] = tp
        if a.is_silent:
            tp["notes"].append("Spur stumm - deaktiviert")
            log.add(t.id, "enabled", False, "Spur enthält kein Signal")
            continue
        if uncertain:
            log.add(t.id, "role", role, f"Rollen-Konfidenz nur {t.confidence:.2f} - bitte prüfen", True)

        # 1) Reparatur / Gain-Staging
        if a.dc_offset > 0.005:
            tp["dc_remove"] = True
            log.add(t.id, "dc_remove", True, f"Gleichspannungsanteil {a.dc_offset:.4f}")
        if a.channels > 1 and a.correlation < -0.3:
            tp["invert_right"] = True
            log.add(t.id, "invert_right", True, f"Stereo-Kanäle gegenphasig (Korrelation {a.correlation:.2f}); "
                    "rechter Kanal wird invertiert", True)
        if a.clip_events:
            tp["notes"].append("Quelle enthält Clipping - nicht reparierbar, ggf. neu aufnehmen/exportieren")
            log.add(t.id, "warning", "clipping", f"{a.clip_events} Clipping-Ereignisse in der Quelle", True)
        trim = _clamp(min(TRIM_TARGET_RMS - a.active_rms_dbfs, TRIM_MAX_PEAK - a.peak_dbfs), -30.0, 24.0)
        tp["trim_db"] = round(trim, 2)
        log.add(t.id, "trim_db", tp["trim_db"], f"Gain-Staging: aktiver RMS {a.active_rms_dbfs:.1f} dBFS -> "
                f"ca. {a.active_rms_dbfs + trim:.1f} dBFS, Peak <= {TRIM_MAX_PEAK} dBFS")

        # 2) EQ
        eqp = copy.deepcopy(profile["eq"].get(role, profile["eq"]["other"]))
        tp["hpf"] = {"freq": eqp.get("hpf", 30), "order": 2}
        tp["lpf"] = {"freq": eqp.get("lpf", 20000), "order": 2}
        if role == "bass" or role == "kick":
            tp["hpf"]["order"] = 4
        moves = [dict(m, origin=m.get("origin", "profile")) for m in eqp.get("moves", [])]
        if role in ("rhythm_guitar", "lead_guitar", "clean_guitar", "lead_vocal", "scream_vocal",
                    "backing_vocal", "synth", "overheads", "bass"):
            lo = 300 if role == "bass" else 200
            for rmove in detect_resonances(a, lo, 8000, rules["resonance_cut_max_db"]):
                moves.append(rmove)
                log.add(t.id, "eq", rmove, f"Resonanz bei {rmove['freq']:.0f} Hz (+{rmove['excess_db']} dB über Umgebung)")
        b = a.band_db
        if role not in NO_HARSH_ROLES:
            harsh = b["high_mid"] - b["mid"]
            ref = {"lead_vocal": -6.0, "scream_vocal": -4.0, "backing_vocal": -6.0, "overheads": 2.0,
                   "snare": 2.0}.get(role, -5.0)
            if harsh > ref:
                cut = round(min(rules["harsh_cut_max_db"], (harsh - ref) * 0.6 + 1.0), 2)
                lo_h, hi_h = rules["harsh_band_hz"]
                f = math.sqrt(lo_h * hi_h)
                moves.append({"type": "bell", "freq": round(f), "gain_db": -cut, "q": 1.4, "origin": "harshness"})
                log.add(t.id, "eq", moves[-1], f"Härte: Hochmitten {harsh:+.1f} dB relativ zu Mitten (Ziel {ref:+.1f})")
        if role in ("rhythm_guitar", "lead_vocal", "backing_vocal", "clean_guitar", "synth", "toms", "kick"):
            mud = b["low_mid"] - b["mid"]
            ref = {"kick": 0.0, "toms": 2.0}.get(role, 2.0)
            if mud > ref:
                cut = round(min(rules["mud_cut_max_db"], (mud - ref) * 0.5 + 1.0), 2)
                lo_m, hi_m = rules["mud_band_hz"]
                moves.append({"type": "bell", "freq": round(math.sqrt(lo_m * hi_m)), "gain_db": -cut, "q": 1.2,
                              "origin": "mud"})
                log.add(t.id, "eq", moves[-1], f"Mulmigkeit: Tiefmitten {mud:+.1f} dB relativ zu Mitten")
        tp["eq"] = _merge_eq_moves(moves)

        # 3) Dynamik
        dyn = profile["dynamics"].get(role, profile["dynamics"]["other"])
        comp = dyn.get("comp")
        tpres = rules["transient_preservation"]
        if comp:
            target_gr = min(comp["target_gr_db"], rules["max_track_gr_db"])
            ratio = comp["ratio"]
            level_ref = a.hit_level_dbfs + trim + 3.0
            thr = level_ref - target_gr / max(1e-3, (1 - 1 / ratio))
            attack = comp["attack_ms"] * (0.5 + tpres) if role in ("kick", "snare", "toms", "bass") else comp["attack_ms"]
            tp["comp"] = {"enabled": True, "threshold_db": round(thr, 2), "ratio": ratio,
                          "attack_ms": round(attack, 2), "release_ms": comp["release_ms"],
                          "knee_db": comp.get("knee_db", 6), "makeup_db": 0.0, "mix": comp.get("mix", 1.0),
                          "target_gr_db": round(target_gr, 2), "calibrate": True}
            log.add(t.id, "comp", tp["comp"], f"Profil {profile['name']}: Ziel-Gain-Reduction {target_gr:.1f} dB, "
                    f"Attack {attack:.1f} ms (Transientenerhalt {tpres:.2f})")
        if dyn.get("gate") and rules.get("gate_drums", True) and ROLE_GROUP.get(role) == "drums":
            gap = a.hit_level_dbfs - a.noise_floor_dbfs
            if a.noise_floor_dbfs > -75 and gap > 18:
                thr = a.noise_floor_dbfs + trim + 0.4 * gap + 6.0
                tp["gate"] = {"enabled": True, "threshold_db": round(thr, 2), "range_db": 30.0 if role != "toms" else 40.0,
                              "attack_ms": 0.5, "hold_ms": 40.0 if role != "toms" else 120.0,
                              "release_ms": 80.0 if role != "toms" else 250.0}
                log.add(t.id, "gate", tp["gate"], f"Übersprechen erkannt (Grundpegel {a.noise_floor_dbfs:.1f} dBFS, "
                        f"Abstand {gap:.1f} dB)")
            else:
                log.add(t.id, "gate", False, "Kein relevantes Übersprechen - Gate nicht nötig")
        if dyn.get("deesser") and rules.get("deess_vocals", True):
            sib = b["presence"] - b["mid"]
            tp["deesser"] = {"enabled": True, "freq": 5500.0, "threshold_db": None, "range_db": 8.0,
                             "target_gr_db": 5.0 if sib > -12 else 3.0, "calibrate": True}
            log.add(t.id, "deesser", tp["deesser"], f"Vocal-Spur: Präsenz/Sibilanz {sib:+.1f} dB relativ zu Mitten")

        # 4) Sättigung
        drive = profile.get("saturation_db", {}).get(role, 0.0) * rules.get("saturation_amount", 1.0)
        if drive > 0:
            tp["saturation"] = {"drive_db": round(drive, 2), "mix": 1.0 if role != "lead_vocal" else 0.5}
            log.add(t.id, "saturation", tp["saturation"], "Profil-Sättigung für Durchsetzung/Obertöne")

        # 5) Sends
        sends = profile["fx"]["sends_db"].get(role, {})
        amt = rules.get("reverb_amount", 1.0)
        if sends:
            off = 20 * math.log10(max(amt, 1e-3))
            if "reverb" in sends:
                tp["sends"]["reverb_db"] = round(sends["reverb"] + off, 2)
            if "delay" in sends:
                tp["sends"]["delay_db"] = round(sends["delay"] + off, 2)
            log.add(t.id, "sends", tp["sends"], f"Effekt-Sends nach Profil (Hall-Faktor {amt:.2f})")

        # 6) Ziel-Lautheit
        bal = profile["balance_lu"].get(role, profile["balance_lu"].get("other", -12.0))
        n = role_count.get(role, 1)
        if role in ("backing_vocal", "synth", "other", "overheads", "room") and n > 1:
            bal -= 10 * math.log10(n)
        if role == "rhythm_guitar" and n > 2:
            bal -= 10 * math.log10(n / 2)
        tp["target_lufs"] = round(LOUDNESS_ANCHOR + bal, 2)
        log.add(t.id, "target_lufs", tp["target_lufs"], f"Balance-Ziel {bal:+.1f} LU relativ zum Anker "
                f"({LOUDNESS_ANCHOR} LUFS){' bei ' + str(n) + ' Spuren dieser Rolle' if n > 1 else ''}")

    # 7) Polarität / Laufzeit zwischen Drum-Mikrofonen
    for (ida, idb), res in polarity_results.items():
        if ida in plan_tracks and idb in plan_tracks and res.get("related"):
            if res.get("polarity_inverted"):
                plan_tracks[idb]["polarity_invert"] = True
                log.add(idb, "polarity_invert", True, f"Gegenphasig zu {by_id[ida].name} (Korrelation "
                        f"{res['correlation']:.2f})", abs(res["correlation"]) < 0.5)
            if abs(res.get("lag_samples", 0)) > 2 and plan_tracks[idb]["role"] not in ("overheads", "room"):
                plan_tracks[idb]["delay_samples"] = -int(res["lag_samples"])
                log.add(idb, "delay_samples", -int(res["lag_samples"]), f"Laufzeitausgleich zu {by_id[ida].name} "
                        f"({res['lag_ms']:.2f} ms)", True)

    # 8) Panorama
    _plan_panning(plan_tracks, by_id, rules, pair_results, log)

    # 9) Maskierung / Frequenzkonflikte
    # erwartete Gesamtverstärkung nach Balance: Ziel-Lautheit minus Quell-Lautheit
    gains = {tid: (plan_tracks[tid]["target_lufs"] - by_id[tid].analysis.lufs)
             if math.isfinite(by_id[tid].analysis.lufs) else 0.0 for tid in roles}
    conflicts = find_conflicts(roles, {t.id: t.analysis for t in active}, gains)
    _resolve_conflicts(plan_tracks, by_id, conflicts, rules, log)

    # 10) Busse, FX, Mixbus, Master
    delay_s = profile["fx"]["delay"]["note_beats"] * 60.0 / max(tempo_bpm, 40.0)
    buses = {}
    for gid, bdef in profile["buses"].items():
        members = [tid for tid, tp in plan_tracks.items() if tp["group"] == gid and tp["enabled"]]
        if not members:
            continue
        bus = {"id": gid, "members": members, "comp": {"enabled": False}, "saturation": {"drive_db": bdef.get("saturation_db", 0.0), "mix": 1.0},
               "fader_db": 0.0}
        if bdef.get("comp"):
            c = bdef["comp"]
            bus["comp"] = {"enabled": True, "threshold_db": -20.0, "ratio": c["ratio"], "attack_ms": c["attack_ms"],
                           "release_ms": c["release_ms"], "knee_db": c.get("knee_db", 6), "makeup_db": 0.0, "mix": 1.0,
                           "target_gr_db": c["target_gr_db"], "calibrate": True}
        if gid == "drums" and rules["parallel_drums"] > 0.01:
            bus["parallel"] = {"amount": round(rules["parallel_drums"], 3),
                               "comp": {"enabled": True, "threshold_db": -30.0, "ratio": 10.0, "attack_ms": 1.0,
                                        "release_ms": 80.0, "knee_db": 3.0, "makeup_db": 0.0, "mix": 1.0,
                                        "target_gr_db": 10.0, "calibrate": True},
                               "saturation_db": 3.0}
            log.add(None, "drums.parallel", bus["parallel"]["amount"], "Parallele Drum-Kompression (Profil/Punch)")
        buses[gid] = bus
        log.add(None, f"bus.{gid}", {"members": len(members), "comp": bus["comp"].get("enabled")}, "Bus-Gruppe angelegt")

    fx = {
        "reverb": dict(profile["fx"]["reverb"]),
        "delay": {"time_s": round(delay_s, 4), "feedback": profile["fx"]["delay"]["feedback"],
                  "damping_hz": profile["fx"]["delay"]["damping_hz"], "tempo_bpm": round(tempo_bpm, 2)},
    }
    mbc = profile["mix_bus"]["comp"]
    mix_bus = {"comp": {"enabled": bool(mbc), "threshold_db": -18.0, "ratio": mbc["ratio"], "attack_ms": mbc["attack_ms"],
                        "release_ms": mbc["release_ms"], "knee_db": mbc.get("knee_db", 6), "makeup_db": 0.0, "mix": 1.0,
                        "target_gr_db": mbc["target_gr_db"], "calibrate": True} if mbc else {"enabled": False},
               "headroom_dbfs": profile["mix_target"]["headroom_dbfs"]}

    return {
        "version": PLAN_VERSION,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "profile": {"id": profile["id"], "name": profile["name"], "character": profile.get("character")},
        "sample_rate": sr,
        "tempo_bpm": round(tempo_bpm, 2),
        "tracks": list(plan_tracks.values()),
        "buses": buses,
        "fx": fx,
        "mix_bus": mix_bus,
        "mix_target": profile["mix_target"],
        "master": dict(profile["master"]),
        "conflicts": conflicts[:30],
        "log": log.entries,
    }


def _name_side(name: str) -> int:
    n = name.lower()
    if any(s in n for s in (" l", "_l", "left", "links", "(l)", " li")) and not n.endswith("r"):
        return -1
    if any(s in n for s in (" r", "_r", "right", "rechts", "(r)", " re")):
        return 1
    return 0


def _plan_panning(plan_tracks: dict, by_id: dict, rules: dict, pair_results: dict, log: PlanLog):
    persp = -1 if rules.get("drum_perspective", "drummer") == "drummer" else 1
    tracks = [tp for tp in plan_tracks.values() if tp["enabled"]]
    stereo = {tp["id"] for tp in tracks if by_id[tp["id"]].analysis.channels > 1}

    def set_pan(tid, pan, reason, uncertain=False):
        plan_tracks[tid]["pan"] = round(float(_clamp(pan, -1, 1)), 3)
        log.add(tid, "pan", plan_tracks[tid]["pan"], reason, uncertain)

    for tp in tracks:
        if tp["id"] in stereo:
            w = {"overheads": rules["overhead_width"], "room": rules["room_width"]}.get(tp["role"], 1.0)
            tp["width"] = round(float(_clamp(w, 0.0, 1.5)), 3)
            log.add(tp["id"], "width", tp["width"], "Stereo-Quelle: Breite statt Panorama")
        elif tp["role"] in ("kick", "snare", "bass", "lead_vocal", "scream_vocal"):
            set_pan(tp["id"], 0.0, "Fundament/Fokus-Element mittig")

    # Rhythmusgitarren: echte Doubles hart L/R
    gtrs = [tp for tp in tracks if tp["role"] in ("rhythm_guitar", "clean_guitar") and tp["id"] not in stereo]
    used: set[str] = set()
    w = rules["guitar_double_pan"]
    for (a, b), info in sorted(pair_results.items(), key=lambda kv: -kv[1].get("envelope_corr", 0)):
        if a in used or b in used:
            continue
        ta, tb = plan_tracks.get(a), plan_tracks.get(b)
        if not ta or not tb or ta["role"] != tb["role"] or ta["role"] not in ("rhythm_guitar", "clean_guitar"):
            continue
        if info.get("double_track") or info.get("duplicate"):
            sa, sb = _name_side(ta["name"]), _name_side(tb["name"])
            left, right = (b, a) if (sa == 1 or sb == -1) else (a, b)
            if info.get("duplicate"):
                set_pan(left, -0.3, "Duplikat (Kopie) erkannt - nur leichte Verteilung, da hartes Panning "
                        "in Mono kollabiert", True)
                set_pan(right, 0.3, "Duplikat (Kopie) erkannt - nur leichte Verteilung", True)
                plan_tracks[left]["notes"].append("Kopie einer anderen Spur - echtes Double-Tracking empfohlen")
            else:
                set_pan(left, -w, f"Echtes Double-Tracking mit {plan_tracks[right]['name']} (Hüllkurve "
                        f"{info.get('envelope_corr', 0):.2f}, Wellenform {info.get('waveform_corr', 0):.2f})")
                set_pan(right, w, f"Echtes Double-Tracking mit {plan_tracks[left]['name']}")
            used.update((a, b))
    singles = [tp for tp in gtrs if tp["id"] not in used]
    side = -1
    for tp in singles:
        set_pan(tp["id"], side * rules["single_guitar_pan"], "Einzelne Gitarrenspur ohne Double - leicht seitlich",
                len(singles) == 1)
        side *= -1
    leads = [tp for tp in tracks if tp["role"] == "lead_guitar" and tp["id"] not in stereo]
    for i, tp in enumerate(leads):
        set_pan(tp["id"], (1 if i % 2 == 0 else -1) * rules["lead_guitar_pan"], "Leadgitarre nahe Mitte, versetzt zum Gesang")
    bvs = [tp for tp in tracks if tp["role"] == "backing_vocal" and tp["id"] not in stereo]
    for i, tp in enumerate(bvs):
        if len(bvs) == 1:
            set_pan(tp["id"], rules["backing_vocal_spread"] * 0.5, "Einzelnes Backing-Vocal leicht seitlich")
        else:
            set_pan(tp["id"], (-1 if i % 2 == 0 else 1) * rules["backing_vocal_spread"], "Backing-Vocals gespreizt")
    toms = sorted([tp for tp in tracks if tp["role"] == "toms" and tp["id"] not in stereo],
                  key=lambda tp: -by_id[tp["id"]].analysis.low_peak_hz)
    for i, tp in enumerate(toms):
        pos = 0.0 if len(toms) == 1 else -1 + 2 * i / (len(toms) - 1)
        set_pan(tp["id"], persp * -pos * rules["tom_spread"] if len(toms) > 1 else 0.0,
                f"Toms nach Tonhöhe verteilt ({'Drummer' if persp < 0 else 'Publikum'}-Perspektive)")
    for tp in tracks:
        if tp["role"] == "hihat" and tp["id"] not in stereo:
            set_pan(tp["id"], persp * 0.4, "Hi-Hat seitlich (Perspektive)")
        if tp["role"] == "synth" and tp["id"] not in stereo:
            set_pan(tp["id"], 0.3, "Mono-Synth leicht seitlich")


def _resolve_conflicts(plan_tracks: dict, by_id: dict, conflicts: list[dict], rules: dict, log: PlanLog):
    handled: set[tuple[str, str, int]] = set()
    for c in conflicts[:20]:
        a, b = c["a"], c["b"]
        ra, rb = c["role_a"], c["role_b"]
        if {ra, rb} == {"kick", "bass"}:
            continue  # separat behandelt
        pa, pb = ROLE_PRIORITY.get(ra, 10), ROLE_PRIORITY.get(rb, 10)
        winner, loser = (a, b) if pa >= pb else (b, a)
        key = (winner, loser, int(round(math.log2(c["freq"]) * 3)))
        if key in handled:
            continue
        handled.add(key)
        rw = plan_tracks[winner]["role"]
        amount = round(min(rules["masking_cut_max_db"], 1.0 + 3.0 * c["severity"]), 2)
        if rw in ("lead_vocal", "scream_vocal") and plan_tracks[loser]["group"] == "guitars":
            amount = round(min(rules["vocal_guitar_duck_db"] + c["severity"], rules["masking_cut_max_db"] + 1), 2)
            d = {"freq": c["freq"], "q": 1.2, "range_db": amount, "threshold_db": None, "sidechain": winner,
                 "target_gr_db": amount, "calibrate": True, "origin": "masking"}
            plan_tracks[loser]["dyn_eq"].append(d)
            log.add(loser, "dyn_eq", d, f"Maskierung mit {plan_tracks[winner]['name']} bei {c['freq']:.0f} Hz "
                    f"(Schwere {c['severity']:.2f}) - dynamische Absenkung nur wenn Gesang aktiv")
        else:
            m = {"type": "bell", "freq": c["freq"], "gain_db": -amount, "q": 2.0, "origin": "masking"}
            plan_tracks[loser]["eq"] = _merge_eq_moves(plan_tracks[loser]["eq"] + [m])
            log.add(loser, "eq", m, f"Maskierung mit {plan_tracks[winner]['name']} bei {c['freq']:.0f} Hz "
                    f"(Schwere {c['severity']:.2f}) - Platz für {ROLE_LABELS_DE.get(rw, rw)}")
    # Gitarren weichen im Präsenzbereich des Gesangs dynamisch aus (Sidechain)
    vocals = [tp for tp in plan_tracks.values() if tp["role"] in ("lead_vocal", "scream_vocal") and tp["enabled"]]
    if vocals and rules.get("vocal_guitar_duck_db", 0) > 0:
        lead = max(vocals, key=lambda tp: 1 - by_id[tp["id"]].analysis.silence_ratio)
        lv = np.array(by_id[lead["id"]].analysis.third_octave_db)
        m = (THIRD_OCTAVE_CENTERS >= 1000) & (THIRD_OCTAVE_CENTERS <= 4000)
        f_pres = float(THIRD_OCTAVE_CENTERS[m][int(np.argmax(lv[m]))])
        for g in plan_tracks.values():
            if g["group"] != "guitars" or not g["enabled"]:
                continue
            if any(d.get("origin") == "masking" and d.get("sidechain") == lead["id"] for d in g["dyn_eq"]):
                continue
            d = {"freq": f_pres, "q": 1.2, "range_db": rules["vocal_guitar_duck_db"], "threshold_db": None,
                 "sidechain": lead["id"], "target_gr_db": rules["vocal_guitar_duck_db"], "calibrate": True,
                 "origin": "masking"}
            g["dyn_eq"].append(d)
            log.add(g["id"], "dyn_eq", d, f"Platz für {plan_tracks[lead['id']]['name']}: dynamische Absenkung bei "
                    f"{f_pres:.0f} Hz (Präsenzmaximum des Gesangs), nur wenn Gesang aktiv")
    # Kick/Bass-Abstimmung
    kicks = [tp for tp in plan_tracks.values() if tp["role"] == "kick" and tp["enabled"]]
    basses = [tp for tp in plan_tracks.values() if tp["role"] == "bass" and tp["enabled"]]
    if kicks and basses:
        kick = max(kicks, key=lambda tp: by_id[tp["id"]].analysis.lufs)
        kf = by_id[kick["id"]].analysis.low_peak_hz or 60.0
        owner = rules["low_end_owner"]
        for bass in basses:
            bf = by_id[bass["id"]].analysis.low_peak_hz or 80.0
            if owner == "kick":
                d = {"freq": float(_clamp(kf, 40, 120)), "q": 1.4, "range_db": rules["kick_bass_duck_db"],
                     "threshold_db": None, "sidechain": kick["id"], "target_gr_db": rules["kick_bass_duck_db"],
                     "calibrate": True, "origin": "kick_bass"}
                bass["dyn_eq"].append(d)
                log.add(bass["id"], "dyn_eq", d, f"Kick besitzt das Sub-Fundament: Bass weicht bei {d['freq']:.0f} Hz "
                        "dynamisch aus, wenn die Kick spielt")
            else:
                m = {"type": "bell", "freq": float(_clamp(bf, 50, 150)), "gain_db": -2.0, "q": 1.5, "origin": "kick_bass"}
                kick["eq"] = _merge_eq_moves(kick["eq"] + [m])
                d = {"freq": float(_clamp(kf, 40, 120)), "q": 1.4, "range_db": rules["kick_bass_duck_db"],
                     "threshold_db": None, "sidechain": kick["id"], "target_gr_db": rules["kick_bass_duck_db"],
                     "calibrate": True, "origin": "kick_bass"}
                bass["dyn_eq"].append(d)
                log.add(kick["id"], "eq", m, f"Bass besitzt das Sub-Fundament: Kick bei {m['freq']:.0f} Hz abgesenkt")
