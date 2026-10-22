"""Kommandozeile: aime <befehl> ...  (python -m app <befehl> ...)"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _progress(f: float, msg: str):
    sys.stderr.write(f"\r[{f * 100:5.1f} %] {msg[:70]:<70}")
    sys.stderr.flush()


def _project(args):
    from engine.profiles import Character

    from .project.model import Project

    if args.project:
        p = Project.load(args.project)
    else:
        if not args.inputs:
            sys.exit("Bitte Audiodateien/Ordner oder --project angeben")
        p = Project(name=args.name or Path(args.inputs[0]).stem)
        p.add_files(args.inputs)
    if args.profile:
        p.profile_id = args.profile
    if args.purpose:
        p.purpose = args.purpose
    if args.out:
        p.output_dir = args.out
    if args.reference:
        p.reference_path = args.reference
    if args.iterations is not None:
        p.optimize_iterations = args.iterations
    if args.bit_depth:
        p.export_bit_depth = args.bit_depth
    ch = p.character.to_dict()
    for k in ch:
        v = getattr(args, k, None)
        if v is not None:
            ch[k] = v
    p.character = Character(**ch).clamp()
    for spec in args.role or []:
        name, role = spec.split("=", 1)
        for t in p.tracks:
            if t.name == name:
                t.role_override = role
    return p


def cmd_mix(args):
    from .orchestration.pipeline import Pipeline

    p = _project(args)
    if not p.tracks:
        sys.exit("Keine unterstützten Audiodateien gefunden")
    res = Pipeline(p, _progress).run_all()
    sys.stderr.write("\n")
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


def cmd_analyze(args):
    from .orchestration.pipeline import Pipeline

    p = _project(args)
    pipe = Pipeline(p, _progress)
    pipe.analyze()
    sys.stderr.write("\n")
    print(json.dumps(pipe.summary(), indent=2, ensure_ascii=False, default=str))


def cmd_profiles(_args):
    from engine.mastering import PURPOSES
    from engine.profiles import list_profiles

    for pr in list_profiles():
        print(f"{pr['id']:<20} {pr['name']} - {pr['description']}")
    print("\nVerwendungszwecke (--purpose):")
    for k, v in PURPOSES.items():
        print(f"{k:<20} {v['name']}")


def cmd_album(args):
    from engine.album import album_master
    from engine.mastering import PURPOSES, MasterSettings

    st = MasterSettings()
    pp = PURPOSES.get(args.purpose or "conservative")
    if pp and pp["target_lufs"] is not None:
        st.target_lufs, st.true_peak_db = pp["target_lufs"], pp["true_peak_db"]
    if args.lufs is not None:
        st.target_lufs = args.lufs
    res = album_master(args.songs, args.out, st, mode=args.mode, tonal_match=args.tonal_match, progress=_progress)
    sys.stderr.write("\n")
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


def cmd_watch(args):
    from .orchestration.watcher import FolderWatcher, WatchOptions

    w = FolderWatcher(args.inbox, args.outbox, WatchOptions(profile_id=args.profile or "modern_metal",
                                                            purpose=args.purpose or "profile", settle_s=args.settle),
                      on_event=lambda e: print(json.dumps(e.__dict__, ensure_ascii=False), flush=True))
    print(f"Überwache {args.inbox} -> {args.outbox} (Strg+C beendet)", file=sys.stderr)
    try:
        while True:
            w.scan_once()
            time.sleep(2)
    except KeyboardInterrupt:
        pass


def cmd_autopilot(args):
    from integration.plugin_link.server import LinkServer

    from .orchestration.autopilot import Autopilot, AutopilotOptions

    bridge, ports = None, None
    if args.midi:
        from integration.midi_remote.bridge import MidoPorts

        ports = MidoPorts()
        bridge = ports.open()
    opt = AutopilotOptions(profile_id=args.profile or "modern_metal", purpose=args.purpose or "profile",
                           capture_seconds=args.seconds, use_transport=bool(bridge), use_mixconsole=bool(bridge))
    with LinkServer(on_event=lambda k, d: print(f"[link] {k}: {json.dumps(d, ensure_ascii=False)}", file=sys.stderr)) as srv:
        print(f"Plugin-Link lauscht auf 127.0.0.1:{srv.port}. Warte auf AIME-Plug-ins ...", file=sys.stderr)
        if not srv.wait_for(lambda xs: any(i.plugin == "channel" for i in xs), timeout=args.wait):
            sys.exit("Keine AIME-Channel-Instanz verbunden")
        time.sleep(1.0)  # weitere Instanzen melden sich
        ap = Autopilot(srv, args.work, opt, bridge=bridge, progress=_progress)
        if args.undo:
            print(json.dumps(ap.undo(), indent=2, ensure_ascii=False))
            return
        res = ap.run()
        sys.stderr.write("\n")
        print(json.dumps(res["push"], indent=2, ensure_ascii=False, default=str))
    if ports:
        ports.close()


def cmd_gui(_args):
    from .main import main as gui_main

    gui_main()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="aime", description="AI Mix Engineer (lokal, ohne Cloud)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def proj_args(p):
        p.add_argument("inputs", nargs="*", help="Audiodateien oder Ordner")
        p.add_argument("--project", help=".aime.json-Projekt statt Dateien")
        p.add_argument("--name")
        p.add_argument("--profile", help="Genre-Profil (aime profiles)")
        p.add_argument("--purpose", help="Mastering-Zweck (aime profiles)")
        p.add_argument("--out", help="Ausgabeordner (Standard: ~/AI-Mix-Engineer-Exports)")
        p.add_argument("--reference", help="Referenztrack")
        p.add_argument("--iterations", type=int)
        p.add_argument("--bit-depth", type=int, choices=[16, 24, 32])
        p.add_argument("--role", action="append", help='Rolle korrigieren: "Spurname=lead_vocal"')
        for k, h in (("brightness", "-1..1"), ("punch", "0..1"), ("width", "0.5..1.2"), ("vocal_level_db", "-3..3"),
                     ("dynamics", "0..1")):
            p.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float, help=h)

    p = sub.add_parser("mix", help="Mischen, Mastern, Exportieren")
    proj_args(p)
    p.set_defaults(fn=cmd_mix)
    p = sub.add_parser("analyze", help="Nur Analyse + Klassifikation (JSON)")
    proj_args(p)
    p.set_defaults(fn=cmd_analyze)
    p = sub.add_parser("profiles", help="Genre-Profile und Mastering-Zwecke anzeigen")
    p.set_defaults(fn=cmd_profiles)
    p = sub.add_parser("album", help="Album-Mastering mehrerer Mixdowns")
    p.add_argument("songs", nargs="+")
    p.add_argument("--out", required=True)
    p.add_argument("--mode", choices=["uniform", "relative"], default="uniform")
    p.add_argument("--purpose")
    p.add_argument("--lufs", type=float)
    p.add_argument("--tonal-match", type=float, default=0.5)
    p.set_defaults(fn=cmd_album)
    p = sub.add_parser("watch", help="Ordner überwachen und neue Stem-Exporte automatisch verarbeiten")
    p.add_argument("inbox")
    p.add_argument("outbox")
    p.add_argument("--profile")
    p.add_argument("--purpose")
    p.add_argument("--settle", type=float, default=5.0)
    p.set_defaults(fn=cmd_watch)
    p = sub.add_parser("autopilot", help="Cubase-Autopilot über AIME-Plug-ins (Plugin-Link)")
    p.add_argument("--work", required=True, help="Arbeitsordner für Aufnahmen, Exporte, Snapshots")
    p.add_argument("--profile")
    p.add_argument("--purpose")
    p.add_argument("--seconds", type=float, help="feste Aufnahmedauer (sonst bis Cubase stoppt)")
    p.add_argument("--midi", action="store_true", help="MIDI-Remote-Bridge nutzen (Transport, Sends)")
    p.add_argument("--wait", type=float, default=120.0, help="max. Wartezeit auf Plug-ins (s)")
    p.add_argument("--undo", action="store_true", help="letzten Push rückgängig machen")
    p.set_defaults(fn=cmd_autopilot)
    p = sub.add_parser("gui", help="Grafische Oberfläche starten")
    p.set_defaults(fn=cmd_gui)
    return ap


def main(argv: list[str] | None = None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
