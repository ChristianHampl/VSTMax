"""Autopilot: Cubase-Projekt mit AIME-Plug-ins -> Aufnahme -> Analyse/Plan -> Werte zurück nach Cubase.

Ablauf (jeder Schritt einzeln aufrufbar, run() erledigt alles):
 1. capture(): alle AIME-Channel-Instanzen nehmen ihr Eingangssignal auf, während Cubase abspielt
    (Start/Stopp per MIDI-Remote-Bridge oder von Hand). Die Aufnahmen landen als neue WAV-Dateien im
    Arbeitsordner; Cubase-Projekt und Originalaufnahmen bleiben unberührt.
 2. plan(): Analyse, Rollen, Mix-Plan, Kalibrierung, Optimierung, Offline-Mix und Master wie im
    Offline-Modus (inkl. Export von Bericht, Presets und Referenz-Renderings).
 3. push(): Zuordnung Cubase-Kanal <-> Plan-Spur, Parameter an Channel/Bus/Master-Instanzen,
    Sends/Fader über MIDI Remote. Vorher wird ein Snapshot geschrieben (undo()).
"""

from __future__ import annotations

import datetime as dt
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from integration.plugin_link.actions import MatchResult, match_instances, neutral_values, plan_values
from integration.plugin_link.server import CaptureResult, Instance, LinkServer

from ..project.model import Project, TrackRef
from .pipeline import Cancelled, Pipeline, ProgressCb


@dataclass
class AutopilotOptions:
    profile_id: str = "modern_metal"
    purpose: str = "profile"
    optimize_iterations: int = 8
    capture_seconds: float | None = None   # None: warten, bis die Wiedergabe in Cubase stoppt
    stop_after_idle_s: float = 1.5
    max_capture_s: float = 20 * 60
    use_transport: bool = True             # Start/Stopp über die MIDI-Remote-Bridge, falls verbunden
    use_mixconsole: bool = True            # Sends/Fader über die Bridge setzen, falls verbunden
    neutral_console: bool = True
    overrides: dict[str, str] = field(default_factory=dict)  # Instanz (hex) -> Plan-Ziel


class Autopilot:
    def __init__(self, server: LinkServer, workdir: str | Path, options: AutopilotOptions | None = None,
                 bridge=None, progress: ProgressCb | None = None, cancel: Callable[[], bool] | None = None):
        self.server = server
        self.workdir = Path(workdir)
        self.opt = options or AutopilotOptions()
        self.bridge = bridge
        self._progress = progress
        self._cancel = cancel
        self.capture_result: CaptureResult | None = None
        self.project: Project | None = None
        self.pipeline: Pipeline | None = None
        self.match: MatchResult | None = None
        self.log: list[dict] = []

    # ------------------------------------------------------------ Hilfen
    def progress(self, f: float, msg: str):
        self.log.append({"t": round(time.time(), 3), "msg": msg})
        if self._progress:
            self._progress(f, msg)

    def _check(self):
        if self._cancel and self._cancel():
            raise Cancelled("Vom Nutzer abgebrochen")

    def _session_dir(self) -> Path:
        d = self.workdir / dt.datetime.now().strftime("session-%Y%m%d-%H%M%S")
        d.mkdir(parents=True, exist_ok=False)
        return d

    # ------------------------------------------------------------ 1. Aufnahme
    def capture(self) -> CaptureResult:
        insts = [i for i in self.server.instances() if i.plugin == "channel"]
        if not insts:
            raise RuntimeError("Keine AIME-Channel-Instanz verbunden. Plug-in auf jede Spur legen und Cubase "
                               "mit laufender App öffnen.")
        unnamed = [i.hex_id for i in insts if not i.channel_name]
        if unnamed:
            self.progress(0.0, f"{len(unnamed)} Instanz(en) ohne Kanalnamen - Cubase meldet Namen erst nach "
                               "dem Öffnen der MixConsole oder Umbenennen der Spur")
        self.session = self._session_dir()
        folder = self.session / "capture"
        self.server.start_capture(folder)
        transport = self.bridge is not None and self.opt.use_transport
        if transport:
            self.bridge.transport("start")
        self.progress(0.02, "Aufnahme läuft - " + ("Cubase spielt ab" if transport else "bitte in Cubase abspielen"))
        t0 = time.monotonic()
        first = None
        try:
            while True:
                self._check()
                time.sleep(0.05)
                now = time.monotonic()
                el = now - t0
                if first is None and self.server.last_audio > t0:
                    first = self.server.last_audio
                if self.opt.capture_seconds is not None and first is not None and \
                        now - first >= self.opt.capture_seconds:
                    break
                if el > self.opt.max_capture_s:
                    break
                la, ls = self.server.last_audio, self.server.last_stopped
                if self.opt.capture_seconds is None and la > t0 and ls > la and now - la > self.opt.stop_after_idle_s:
                    break  # Transport gestoppt
                if self.opt.capture_seconds is None and la > t0 and now - la > max(5.0, self.opt.stop_after_idle_s * 3):
                    break  # keine Daten mehr (z. B. Projekt geschlossen)
                if self.server.stats["audio_chunks"]:
                    self.progress(min(0.2, 0.02 + el / 600), f"Aufnahme {el:.0f} s")
        finally:
            if transport:
                self.bridge.transport("stop")
            res = self.server.stop_capture()
        self.capture_result = res
        (self.session / "capture.json").write_text(json.dumps(res.__dict__, indent=2, ensure_ascii=False),
                                                   encoding="utf-8")
        if not res.files:
            raise RuntimeError("Keine Audiodaten aufgenommen. " + " ".join(res.warnings))
        return res

    # ------------------------------------------------------------ 2. Analyse + Plan
    def build_project(self, res: CaptureResult | None = None) -> Project:
        res = res or self.capture_result
        p = Project(name=f"Cubase-Capture {dt.datetime.now():%Y-%m-%d %H:%M}", profile_id=self.opt.profile_id,
                    purpose=self.opt.purpose, optimize_iterations=self.opt.optimize_iterations,
                    output_dir=str(self.session / "export") if hasattr(self, "session") else None)
        for hid, path in res.files.items():
            info = res.instances.get(hid, {})
            if info.get("plugin", "channel") != "channel":
                continue
            name = info.get("channel_name") or Path(path).stem
            p.tracks.append(TrackRef(path=path, name=name, cubase_channel=info.get("channel_name") or None,
                                     cubase_channel_uid=info.get("channel_uid") or None))
        self.project = p
        return p

    def plan(self, project: Project | None = None) -> dict:
        project = project or self.project
        pipe = Pipeline(project, progress=lambda f, m: self.progress(0.2 + 0.6 * f, m), cancel=self._cancel)
        out = Path(project.output_dir) if project.output_dir else None
        result = pipe.run_all(out)
        for t in pipe.s.plan["tracks"]:
            ref = next((r for r in project.tracks if r.id == t["id"]), None)
            if ref and ref.cubase_channel:
                t["cubase_channel"] = ref.cubase_channel
        self.pipeline = pipe
        return result

    # ------------------------------------------------------------ 3. Zurück nach Cubase
    def push(self, overrides: dict[str, str] | None = None) -> dict:
        if self.pipeline is None or self.pipeline.s.plan is None:
            raise RuntimeError("Kein Plan vorhanden")
        plan = self.pipeline.s.plan
        insts = self.server.instances()
        self.match = match_instances(insts, plan, overrides or self.opt.overrides)
        snap = self.snapshot_path()
        prev = self._last_snapshot()
        entries = {}
        for m in self.match.matches:
            vals = plan_values(plan, m, self.pipeline.s.master_report)
            if not vals:
                continue
            before = (prev or {}).get("by_channel", {}).get(f"{m.plugin}:{m.channel_name}")
            entries[m.instance] = {"plugin": m.plugin, "channel_name": m.channel_name, "target": m.target,
                                   "values": {str(k): v for k, v in vals.items()},
                                   "previous": before["values"] if before else None}
        snap.write_text(json.dumps({"created": dt.datetime.now().isoformat(timespec="seconds"), "entries": entries,
                                    "by_channel": {f"{e['plugin']}:{e['channel_name']}": e for e in entries.values()}},
                                   indent=2, ensure_ascii=False), encoding="utf-8")
        sent, failed = {}, []
        for hid, e in entries.items():
            ok = self.server.set_params(int(hid, 16), {int(k): v for k, v in e["values"].items()})
            (sent.__setitem__(hid, e["target"]) if ok else failed.append(hid))
        report = {"sent": sent, "failed": failed, "conflicts": self.match.conflicts,
                  "unmatched_tracks": self.match.unmatched_tracks, "snapshot": str(snap),
                  "unmatched_instances": [m.channel_name for m in self.match.matches if m.target is None]}
        if self.bridge is not None and self.opt.use_mixconsole:
            from integration.midi_remote.mixer import apply_mixer_plan

            self.progress(0.95, "Setze Sends/Fader über MIDI Remote")
            report["mixconsole"] = apply_mixer_plan(self.bridge, plan, self.opt.neutral_console)
        self.progress(1.0, f"{len(sent)} Plug-in-Instanzen aktualisiert")
        return report

    # ------------------------------------------------------------ Snapshots / Undo
    def snapshot_dir(self) -> Path:
        d = self.workdir / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def snapshot_path(self) -> Path:
        return self.snapshot_dir() / f"push-{dt.datetime.now():%Y%m%d-%H%M%S-%f}.json"

    def _last_snapshot(self) -> dict | None:
        snaps = sorted(self.snapshot_dir().glob("push-*.json"))
        return json.loads(snaps[-1].read_text(encoding="utf-8")) if snaps else None

    def undo(self) -> dict:
        """Stellt den Stand vor dem letzten Push wieder her (vorheriger AIME-Push oder Plug-in-Defaults).

        Grenzen: Werte, die zwischenzeitlich von Hand in Cubase geändert wurden, kennt die App nicht.
        """
        snaps = sorted(self.snapshot_dir().glob("push-*.json"))
        if not snaps:
            return {"restored": {}, "message": "Kein Snapshot vorhanden"}
        last = json.loads(snaps[-1].read_text(encoding="utf-8"))
        by_name = {f"{i.plugin}:{i.channel_name}": i for i in self.server.instances()}
        restored, missing = {}, []
        for e in last["entries"].values():
            inst: Instance | None = by_name.get(f"{e['plugin']}:{e['channel_name']}")
            if inst is None:
                missing.append(e["channel_name"])
                continue
            vals = {int(k): v for k, v in e["previous"].items()} if e.get("previous") else neutral_values(e["plugin"])
            if self.server.set_params(inst.id, vals):
                restored[inst.hex_id] = "vorheriger Push" if e.get("previous") else "Plug-in-Defaults"
        snaps[-1].rename(snaps[-1].with_suffix(".undone"))
        return {"restored": restored, "missing": missing}

    # ------------------------------------------------------------ alles
    def run(self) -> dict:
        res = self.capture()
        self.build_project(res)
        export = self.plan()
        push = self.push()
        summary = {"capture": res.__dict__, "export": export, "push": push, "log": self.log}
        (self.session / "autopilot.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str),
                                                     encoding="utf-8")
        return summary
