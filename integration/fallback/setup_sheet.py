"""Setup-Sheet (HTML) für die manuelle Übernahme des Mix-Plans in Cubase."""

from __future__ import annotations

import html
from pathlib import Path

GROUP_NAMES = {"drums": "Drums", "bass": "Bass", "guitars": "Guitars", "vocals": "Vocals", "keys": "Keys", "other": "Other"}


def _pan_text(p: float) -> str:
    if abs(p) < 0.005:
        return "C"
    return f"{'L' if p < 0 else 'R'}{round(abs(p) * 100)}"


def write_setup_sheet(plan: dict, path: str | Path) -> str:
    rows = []
    name_of = {t["id"]: t["name"] for t in plan["tracks"]}
    for t in plan["tracks"]:
        if not t.get("enabled"):
            continue
        side = []
        for d in t.get("dyn_eq", []):
            if d.get("sidechain"):
                side.append(f"Sidechain von <b>{html.escape(name_of.get(d['sidechain'], d['sidechain']))}</b> "
                            f"({d['freq']:.0f} Hz, max. {d['range_db']:.1f} dB)")
        sends = []
        if t["sends"].get("reverb_db") is not None:
            sends.append(f"FX Reverb {t['sends']['reverb_db']:.1f} dB")
        if t["sends"].get("delay_db") is not None:
            sends.append(f"FX Delay {t['sends']['delay_db']:.1f} dB")
        width_txt = "" if t.get("width", 1) == 1 else " / Breite {:.2f}".format(t["width"])
        rows.append(
            "<tr>"
            f"<td>{html.escape(t['name'])}</td>"
            f"<td>{html.escape(t['role_label'])} ({t['role_confidence']:.0%}){' ⚠' if t.get('uncertain') else ''}</td>"
            f"<td>AIME Channel - {html.escape(t['name'])}.vstpreset</td>"
            f"<td>{GROUP_NAMES.get(t['group'], t['group'])}</td>"
            f"<td>{_pan_text(t['pan'])}{width_txt}</td>"
            f"<td>{t['fader_db']:+.1f} dB (im Plugin: Output)</td>"
            f"<td>{'<br>'.join(sends) or '-'}</td>"
            f"<td>{'<br>'.join(side) or '-'}</td>"
            f"<td>{'<br>'.join(html.escape(n) for n in t.get('notes', [])) or ''}</td>"
            "</tr>")
    fx = plan["fx"]
    doc = f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Cubase Setup-Sheet</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px;font-size:13px;vertical-align:top}}th{{background:#f0f0f0}}h1{{font-size:20px}}
.note{{background:#fff8e1;padding:10px;border:1px solid #f0d080}}</style></head><body>
<h1>Cubase Setup-Sheet - Profil {html.escape(plan['profile']['name'])}</h1>
<p class="note">Diese Liste überträgt den Mix-Plan in Cubase, falls Plugin-Link/MIDI-Remote nicht genutzt werden.
1) Gruppenkanäle anlegen (Drums, Bass, Guitars, Vocals, Keys) und Spurausgänge darauf routen.
2) Auf jede Spur <b>AIME Channel</b> als ersten Insert laden und das genannte Preset laden.
3) Auf Gruppenkanäle <b>AIME Bus</b> mit dem jeweiligen Preset. Auf den Stereo-Out zuerst
<b>AIME Bus</b> mit dem Preset „Mixbus (Stereo Out)“, danach <b>AIME Master</b>.
4) FX-Kanäle: Reverb (Decay {fx['reverb']['decay_s']} s, Predelay {fx['reverb']['predelay_ms']} ms) und
Delay ({fx['delay']['time_s'] * 1000:.0f} ms = {fx['delay']['tempo_bpm']} BPM, Feedback {fx['delay']['feedback']:.0%}).
5) Panorama bei Mono-Spuren im Cubase-Panner setzen (Plugin-Pan wirkt nur bei Stereo-Spuren).
6) Cubase-Fader auf 0 dB lassen - die Pegel stecken im Plugin-Output.</p>
<table><tr><th>Spur</th><th>Rolle</th><th>Preset</th><th>Gruppe</th><th>Pan</th><th>Pegel</th><th>Sends</th><th>Sidechain</th><th>Hinweise</th></tr>
{''.join(rows)}</table></body></html>"""
    Path(path).write_text(doc, encoding="utf-8")
    return str(path)
