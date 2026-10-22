"""MixConsole-Automatisierung aus dem Mix-Plan über die MIDI-Remote-Bridge.

Pegel, Pan und Bearbeitung liegen im AIME-Channel-Plug-in (Plugin-Link). Über die MixConsole werden
nur Dinge gesetzt, die das Plug-in nicht erreicht: Effekt-Sends (Send 1 = Reverb-FX, Send 2 = Delay-FX
laut Vorlage) und optional das Neutralisieren von Fader/Pan, damit nichts doppelt wirkt.
"""

from __future__ import annotations

from .bridge import MidiRemoteBridge


def apply_mixer_plan(bridge: MidiRemoteBridge, plan: dict, neutral_console: bool = True,
                     send_tolerance_db: float = 0.75) -> dict:
    report: dict = {"tracks": {}, "not_found": [], "uncalibrated": []}
    for t in plan.get("tracks", []):
        if not t.get("enabled", True):
            continue
        name = t.get("cubase_channel") or t["name"]
        strip = bridge.locate(name)
        if strip is None:
            report["not_found"].append(name)
            continue
        r: dict = {"strip": strip}
        if neutral_console:
            r["volume"] = bridge.set_volume_db(strip, 0.0).__dict__
            r["pan"] = bridge.set_pan(strip, 0.0).__dict__
        sends = t.get("sends") or {}
        for idx, key in ((1, "reverb_db"), (2, "delay_db")):
            db = sends.get(key)
            if db is None:
                continue
            res = bridge.set_send_db(strip, idx, float(db), send_tolerance_db)
            r[f"send{idx}"] = res.__dict__
        for k, v in r.items():
            if isinstance(v, dict) and not v.get("calibrated", True):
                report["uncalibrated"].append(f"{name}: {k}")
        report["tracks"][name] = r
    return report
