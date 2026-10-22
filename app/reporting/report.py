"""Abschlussbericht (JSON + HTML mit eingebetteten SVG-Grafiken)."""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

import numpy as np

from engine.analysis import THIRD_OCTAVE_CENTERS, spectrum, third_octave


def _svg_spectrum(curves: list[tuple[str, list[float], str]], w: int = 640, h: int = 220) -> str:
    xs = np.log2(THIRD_OCTAVE_CENTERS)
    x0, x1 = xs.min(), xs.max()
    allv = [v for _, c, _ in curves for v in c if v is not None and math.isfinite(v)]
    if not allv:
        return ""
    vmax = max(allv)
    vmin = vmax - 60

    def px(i, v):
        return 40 + (xs[i] - x0) / (x1 - x0) * (w - 50), 10 + (1 - (max(v, vmin) - vmin) / (vmax - vmin)) * (h - 40)

    parts = [f'<svg width="{w}" height="{h}" xmlns="http://www.w3.org/2000/svg" style="background:#fafafa;border:1px solid #ddd">']
    for f in (50, 100, 200, 500, 1000, 2000, 5000, 10000):
        x = 40 + (math.log2(f) - x0) / (x1 - x0) * (w - 50)
        parts.append(f'<line x1="{x:.1f}" y1="10" x2="{x:.1f}" y2="{h - 30}" stroke="#e3e3e3"/>'
                     f'<text x="{x:.1f}" y="{h - 14}" font-size="10" text-anchor="middle">{f if f < 1000 else str(f // 1000) + "k"}</text>')
    for k, (label, c, col) in enumerate(curves):
        pts = " ".join(f"{px(i, v)[0]:.1f},{px(i, v)[1]:.1f}" for i, v in enumerate(c) if v is not None)
        parts.append(f'<polyline fill="none" stroke="{col}" stroke-width="1.8" points="{pts}"/>'
                     f'<text x="{50 + 120 * k}" y="22" font-size="11" fill="{col}">{html.escape(label)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def _tod(x, sr):
    f, p = spectrum(x, sr)
    t = third_octave(f, p)
    return (t - t.max()).tolist()


def _fmt(v, nd=1):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}" if math.isfinite(v) else "-"
    return html.escape(str(v))


def write_reports(pipe, out: Path, files: dict) -> dict:
    summary = pipe.summary()
    summary["files"] = files
    summary["plan_log"] = pipe.s.log
    jp = out / "report.json"
    jp.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    s = pipe.s
    mr = s.master_report or {}
    rows = []
    plan_tracks = {t["id"]: t for t in (s.plan or {}).get("tracks", [])}
    for t in summary["tracks"]:
        a = t["analysis"] or {}
        c = t["classification"] or {}
        pt = plan_tracks.get(t["id"], {})
        probs = "; ".join(p["message"] for p in a.get("problems", []))
        rows.append(f"<tr><td>{html.escape(t['name'])}</td><td>{html.escape(c.get('role_label', ''))}</td>"
                    f"<td>{_fmt(c.get('confidence', 0) * 100, 0)} %{' ⚠' if c.get('uncertain') else ''}</td>"
                    f"<td>{_fmt(a.get('peak_dbfs'))}</td><td>{_fmt(a.get('lufs'))}</td><td>{_fmt(a.get('crest_db'))}</td>"
                    f"<td>{_fmt(pt.get('trim_db'))}</td><td>{_fmt(pt.get('fader_db'))}</td><td>{_fmt(pt.get('pan'), 2)}</td>"
                    f"<td>{html.escape(probs)}</td></tr>")
    log_rows = "".join(
        f"<tr{' class=unc' if e.get('uncertain') else ''}><td>{html.escape(str(e.get('track') or '-'))}</td>"
        f"<td>{html.escape(str(e.get('param')))}</td><td><code>{html.escape(json.dumps(e.get('value'), ensure_ascii=False, default=str)[:160])}</code></td>"
        f"<td>{html.escape(str(e.get('reason')))}</td></tr>" for e in s.log)
    opt_rows = ""
    if s.optimization:
        opt_rows = "".join(
            f"<tr><td>{h['iteration']}</td><td>{html.escape(h['action'])}</td><td>{h['score']}</td>"
            f"<td>{'ja' if h['accepted'] else 'nein'}</td><td><code>{html.escape(json.dumps(h['metrics']))}</code></td></tr>"
            for h in s.optimization["history"])
    q = mr.get("quality", {})
    qflags = "".join(f"<li class='{f['severity']}'>{html.escape(f['message'])}</li>" for f in q.get("flags", [])) or "<li>Keine Auffälligkeiten</li>"
    spec = ""
    if s.mix is not None and s.master is not None:
        spec = _svg_spectrum([("Mix", _tod(s.mix, pipe.sr), "#1f77b4"), ("Master", _tod(s.master, pipe.sr), "#d62728")])
    ref_html = ""
    if s.reference:
        ref_html = ("<h2>Referenzvergleich</h2><p>" + html.escape(s.reference["note"]) + "</p><ul>" +
                    "".join(f"<li>{html.escape(x)}</li>" for x in s.reference["suggestions"]) + "</ul>" +
                    _svg_spectrum([("Mix", s.reference["mix"]["third_octave_db"], "#1f77b4"),
                                   ("Referenz", s.reference["reference"]["third_octave_db"], "#2ca02c")]))
    cons = "".join(f"<li>{html.escape(c['message'])}</li>" for c in summary["consistency"])
    before, after = mr.get("before", {}), mr.get("after", {})
    doc = f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>AI Mix Engineer - Bericht</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222;max-width:1200px}}
table{{border-collapse:collapse;width:100%;margin-bottom:18px}}td,th{{border:1px solid #ddd;padding:4px 6px;font-size:12px;vertical-align:top}}
th{{background:#f2f2f2}}tr.unc td{{background:#fff6e0}}li.fail{{color:#b00020}}li.warn{{color:#a06000}}code{{font-size:11px}}</style></head><body>
<h1>AI Mix Engineer - Bericht: {html.escape(pipe.p.name)}</h1>
<p>Profil <b>{html.escape(s.plan['profile']['name'] if s.plan else '-')}</b>, Sample-Rate {pipe.sr} Hz,
Tempo {summary['tempo']['bpm']} BPM (Konfidenz {summary['tempo']['confidence']}), Engine {summary['engine_version']}.</p>
<ul>{cons}</ul>
<h2>Master</h2>
<table><tr><th></th><th>Integrierte Lautheit</th><th>True Peak</th><th>LRA</th><th>PLR</th></tr>
<tr><td>Mix (vor Mastering)</td><td>{_fmt(before.get('integrated_lufs'))} LUFS</td><td>{_fmt(before.get('true_peak_dbtp'), 2)} dBTP</td><td>{_fmt(before.get('loudness_range_lu'))} LU</td><td>{_fmt(before.get('plr_db'))} dB</td></tr>
<tr><td>Master</td><td>{_fmt(after.get('integrated_lufs'))} LUFS</td><td>{_fmt(after.get('true_peak_dbtp'), 2)} dBTP</td><td>{_fmt(after.get('loudness_range_lu'))} LU</td><td>{_fmt(after.get('plr_db'))} dB</td></tr></table>
<p>Ziel: {_fmt(mr.get('settings', {}).get('target_lufs'))} LUFS / {_fmt(mr.get('settings', {}).get('true_peak_db'))} dBTP.
{html.escape(mr.get('target_note', ''))}</p>
<h3>Qualitätsprüfung: {html.escape(q.get('verdict', '-'))}</h3><ul>{qflags}</ul>
{spec}
{ref_html}
<h2>Spuren</h2>
<table><tr><th>Spur</th><th>Rolle</th><th>Konfidenz</th><th>Peak dBFS</th><th>LUFS</th><th>Crest dB</th><th>Trim dB</th><th>Fader dB</th><th>Pan</th><th>Probleme</th></tr>
{''.join(rows)}</table>
<h2>Iterative Optimierung</h2>
<table><tr><th>#</th><th>Aktion</th><th>Score</th><th>Übernommen</th><th>Messwerte</th></tr>{opt_rows}</table>
<h2>Bearbeitungsprotokoll</h2><p>Gelb markiert: unsichere Entscheidungen - bitte prüfen.</p>
<table><tr><th>Spur</th><th>Parameter</th><th>Wert</th><th>Begründung</th></tr>{log_rows}</table>
<p>Laufzeiten: <code>{html.escape(json.dumps(summary['timings']))}</code></p>
</body></html>"""
    hp = out / "report.html"
    hp.write_text(doc, encoding="utf-8")
    return {"json": str(jp), "html": str(hp)}
