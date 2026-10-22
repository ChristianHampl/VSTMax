"""Orchestrierung: Import -> Analyse -> Rollen -> Plan -> Vorbereitung -> Optimierung ->
Mix -> Mastering -> Qualitätsprüfung -> Export -> Bericht.

Stufen sind getrennt aufrufbar (Analyse, Vorschau, finaler Export). Fortschritt und
Abbruch werden über Callbacks gemeldet, damit die GUI nicht blockiert.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from engine import __version__ as ENGINE_VERSION
from engine import analysis as an
from engine import classification as cl
from engine import loudness as lmod
from engine.audio_io import AudioData, file_fingerprint, load_audio, resample, write_audio
from engine.mastering import MasterSettings, master
from engine.mix_planner import TrackInput, plan_mix
from engine.mixing import MixRenderer, loudest_region
from engine.optimizer import Optimizer
from engine.phase import polarity_and_alignment, similarity
from engine.profiles import apply_character, load_profile
from engine.validation import check_project_consistency

from ..project.model import Project

ProgressCb = Callable[[float, str], None]


class Cancelled(Exception):
    pass


@dataclass
class RunState:
    infos: dict = field(default_factory=dict)
    analyses: dict = field(default_factory=dict)
    classes: dict = field(default_factory=dict)
    pairs: dict = field(default_factory=dict)
    polarity: dict = field(default_factory=dict)
    tempo: tuple = (120.0, 0.0)
    consistency: list = field(default_factory=list)
    context_log: list = field(default_factory=list)
    plan: dict | None = None
    log: list = field(default_factory=list)
    optimization: dict | None = None
    mix: np.ndarray | None = None
    master: np.ndarray | None = None
    master_report: dict | None = None
    reference: dict | None = None
    excerpt: tuple | None = None
    preview_original: np.ndarray | None = None
    preview_mix: np.ndarray | None = None
    timings: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


class AudioCache:
    """Lädt Spuren bei Bedarf (resampled, auf Projektlänge aufgefüllt), LRU-begrenzt."""

    def __init__(self, project: Project, sr: int, length: int, max_bytes: int = 1_500_000_000):
        self.p = project
        self.sr = sr
        self.length = length
        self.max_bytes = max_bytes
        self._c: OrderedDict[str, np.ndarray] = OrderedDict()

    def __call__(self, tid: str) -> np.ndarray:
        if tid in self._c:
            self._c.move_to_end(tid)
            return self._c[tid]
        a = load_audio(self.p.track(tid).path)
        x = a.samples
        if a.sample_rate != self.sr:
            x = resample(x, a.sample_rate, self.sr)
        if x.shape[0] < self.length:
            x = np.vstack([x, np.zeros((self.length - x.shape[0], x.shape[1]))])
        x = x[: self.length].astype(np.float32)
        self._c[tid] = x
        while sum(v.nbytes for v in self._c.values()) > self.max_bytes and len(self._c) > 1:
            self._c.popitem(last=False)
        return x


class Pipeline:
    def __init__(self, project: Project, progress: ProgressCb | None = None,
                 cancel: Callable[[], bool] | None = None):
        self.p = project
        self._progress = progress
        self._cancel = cancel
        self.s = RunState()
        self.sr: int | None = None
        self.length = 0
        self.audio: AudioCache | None = None
        self.profile: dict | None = None
        self.ml_model = None

    # ------------------------------------------------------------ Hilfen
    def progress(self, frac: float, msg: str):
        if self._progress:
            self._progress(max(0.0, min(1.0, frac)), msg)

    def check_cancel(self):
        if self._cancel and self._cancel():
            raise Cancelled("Vom Nutzer abgebrochen")

    def _sub(self, lo: float, hi: float) -> ProgressCb:
        return lambda f, m: self.progress(lo + (hi - lo) * f, m)

    def _active_tracks(self):
        return [t for t in self.p.tracks if t.enabled]

    # ------------------------------------------------------------ Stufen
    def load(self):
        t0 = time.time()
        tracks = self._active_tracks()
        if not tracks:
            raise ValueError("Keine Spuren im Projekt")
        infos = {}
        for i, t in enumerate(tracks):
            self.check_cancel()
            self.progress(0.02 + 0.03 * i / len(tracks), f"Lade {t.name}")
            a = load_audio(t.path)
            infos[t.id] = a.info() | {"warnings": a.warnings}
            fp = file_fingerprint(t.path)
            if t.fingerprint and t.fingerprint != fp:
                self.s.errors.append({"track": t.id, "message": "Datei hat sich seit dem Speichern geändert"})
            t.fingerprint = fp
        self.s.infos = infos
        srs = [i["sample_rate"] for i in infos.values()]
        self.sr = max(set(srs), key=srs.count)
        self.length = max(int(round(i["duration_s"] * self.sr)) for i in infos.values())
        self.s.consistency = check_project_consistency(list(infos.values()))
        self.audio = AudioCache(self.p, self.sr, self.length)
        if self.p.ml_model_path:
            try:
                self.ml_model = cl.load_onnx_model(self.p.ml_model_path)
            except Exception as exc:
                self.s.errors.append({"track": None, "message": f"ML-Modell nicht geladen: {exc}"})
        self.s.timings["load_s"] = round(time.time() - t0, 3)

    def analyze(self):
        if self.audio is None:
            self.load()
        t0 = time.time()
        tracks = self._active_tracks()
        drum_sum = None
        for i, t in enumerate(tracks):
            self.check_cancel()
            self.progress(0.05 + 0.25 * i / len(tracks), f"Analysiere {t.name}")
            x = self.audio(t.id).astype(np.float64)
            a = an.analyze(x, self.sr, t.name, self.s.infos[t.id].get("bit_depth"))
            self.s.analyses[t.id] = a
            self.s.classes[t.id] = cl.classify(a, Path(t.path).name, x, self.ml_model)
        # Kontext und Paaranalysen
        self.progress(0.3, "Vergleiche Spuren (Doubles, Duplikate, Phase)")
        roles = {tid: (self.p.track(tid).role_override or c.role) for tid, c in self.s.classes.items()}
        ids = list(roles)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                ga, gb = cl.ROLE_GROUP.get(roles[a]), cl.ROLE_GROUP.get(roles[b])
                if ga == gb and ga in ("guitars", "vocals", "keys"):
                    self.check_cancel()
                    self.s.pairs[(a, b)] = similarity(
                        self.audio(a), self.audio(b), self.sr,
                        np.array(self.s.analyses[a].third_octave_db), np.array(self.s.analyses[b].third_octave_db))
        self.s.context_log = cl.apply_context(self.s.classes, self.s.analyses, self.s.pairs)
        roles = {tid: (self.p.track(tid).role_override or c.role) for tid, c in self.s.classes.items()}
        for ref_role, others in (("kick", ("kick",)), ("snare", ("snare", "overheads"))):
            refs = [tid for tid, r in roles.items() if r == ref_role]
            if not refs:
                continue
            ref = max(refs, key=lambda tid: self.s.analyses[tid].lufs)
            for tid, r in roles.items():
                if tid != ref and r in others:
                    self.s.polarity[(ref, tid)] = polarity_and_alignment(self.audio(ref), self.audio(tid), self.sr, 8.0)
        for tid, r in roles.items():
            if cl.ROLE_GROUP.get(r) == "drums":
                x = self.audio(tid).astype(np.float64).mean(axis=1)
                drum_sum = x if drum_sum is None else drum_sum + x
        if drum_sum is not None:
            self.s.tempo = an.estimate_tempo(drum_sum, self.sr)
        self.s.timings["analyze_s"] = round(time.time() - t0, 3)

    def roles(self) -> dict[str, str]:
        return {tid: (self.p.track(tid).role_override or c.role) for tid, c in self.s.classes.items()}

    def make_plan(self) -> dict:
        if not self.s.analyses:
            self.analyze()
        self.progress(0.32, "Erstelle Mix-Plan")
        self.profile = apply_character(load_profile(self.p.profile_id), self.p.character)
        inputs = []
        for t in self._active_tracks():
            inputs.append(TrackInput(t.id, t.name, self.s.analyses[t.id], self.s.classes[t.id], t.role_override, t.path))
        bpm = self.s.tempo[0] if self.s.tempo[1] > 0.2 else 120.0
        plan = plan_mix(inputs, self.profile, self.sr, bpm, self.s.pairs, self.s.polarity)
        plan["log"] = [{"track": None, "param": "context", "value": e, "reason": e, "uncertain": False}
                       for e in self.s.context_log] + plan["log"]
        if self.s.tempo[1] <= 0.2:
            plan["log"].append({"track": None, "param": "tempo", "value": 120.0,
                                "reason": "Tempo nicht sicher erkannt - Delay auf 120 BPM", "uncertain": True})
        self.s.plan = plan
        self.s.log = plan["log"]
        return plan

    def prepare(self):
        """Volle Länge: Kalibrierung aller Dynamikstufen und Fader aus gemessener Lautheit."""
        if self.s.plan is None:
            self.make_plan()
        t0 = time.time()
        r = MixRenderer(self.s.plan, self.audio, self.sr, self.s.log)
        stats = {}
        tracks = [t for t in self.s.plan["tracks"] if t["enabled"]]
        for i, t in enumerate(tracks):
            self.check_cancel()
            self.progress(0.35 + 0.2 * i / len(tracks), f"Kalibriere {t['name']}")
            _, st = r.process_track(t["id"], None, calibrate=True)
            stats[t["id"]] = st
        r.set_faders(stats, self.s.log)
        self.s.timings["prepare_s"] = round(time.time() - t0, 3)

    def optimize(self):
        t0 = time.time()
        r = MixRenderer(self.s.plan, self.audio, self.sr, self.s.log)
        region = loudest_region([self.audio(t["id"]) for t in self.s.plan["tracks"] if t["enabled"]],
                                self.sr, self.p.excerpt_s)
        self.s.excerpt = region
        opt = Optimizer(r, region, self.s.log, self._sub(0.55, 0.75), self._cancel)
        res = opt.run(self.p.optimize_iterations)
        self.s.optimization = {k: v for k, v in res.items() if k != "result"}
        self.s.preview_mix = res["result"].mix
        orig = sum(self.audio(t["id"])[region[0]:region[1]].astype(np.float64).mean(axis=1, keepdims=True)
                   for t in self.s.plan["tracks"] if t["enabled"])
        orig = np.repeat(orig, 2, axis=1)
        self.s.preview_original = orig
        self.s.timings["optimize_s"] = round(time.time() - t0, 3)

    def render(self):
        t0 = time.time()
        r = MixRenderer(self.s.plan, self.audio, self.sr, self.s.log)
        res = r.render(None, cache=None, calibrate=True, progress=self._sub(0.75, 0.88), cancel=self._cancel)
        self.s.mix = res.mix
        self._mix_result = res
        self.s.timings["render_s"] = round(time.time() - t0, 3)
        return res

    def master_mix(self):
        t0 = time.time()
        self.progress(0.88, "Mastering")
        st = MasterSettings.from_profile(self.s.plan["master"], self.s.plan["mix_target"], self.p.purpose)
        if self.p.reference_path:
            self.progress(0.89, "Referenzvergleich")
            from engine.reference import compare

            ref = load_audio(self.p.reference_path)
            self.s.reference = compare(self.s.mix, ref.samples, self.sr, ref.sample_rate, self.p.reference_match)
            st.reference_eq = self.s.reference["suggested_master_eq"]
        y, rep = master(self.s.mix, self.sr, st, self.s.log)
        self.s.master = y
        self.s.master_report = rep
        self.s.timings["master_s"] = round(time.time() - t0, 3)
        return y, rep

    def preview_ab(self) -> tuple[np.ndarray, np.ndarray]:
        """Lautheitsangeglichene A/B-Vorschau (Original-Summe vs. Mix) des Ausschnitts."""
        a, b = self.s.preview_original, self.s.preview_mix
        la, lb = lmod.integrated_loudness(a, self.sr), lmod.integrated_loudness(b, self.sr)
        ga = -23 - la if math.isfinite(la) else 0.0
        gb = -23 - lb if math.isfinite(lb) else 0.0
        return a * 10 ** (ga / 20), b * 10 ** (gb / 20)

    # ------------------------------------------------------------ Export
    def output_folder(self) -> Path:
        base = Path(self.p.output_dir) if self.p.output_dir else Path.home() / "AI-Mix-Engineer-Exports"
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.p.name).strip() or "Projekt"
        return base / f"{safe}_{stamp}"

    def export(self, out: Path | None = None) -> dict:
        from integration.fallback.setup_sheet import write_setup_sheet
        from integration.presets.vstpreset import export_plan_presets

        from ..reporting.report import write_reports

        out = out or self.output_folder()
        out.mkdir(parents=True, exist_ok=True)
        protected = {str(Path(t.path).resolve()) for t in self.p.tracks}
        if self.p.reference_path:
            protected.add(str(Path(self.p.reference_path).resolve()))
        files = {}
        sr_out = self.p.export_sample_rate or self.sr
        bd = self.p.export_bit_depth
        self.progress(0.93, "Exportiere Audio")
        files["mix"] = write_audio(out / "mix_unmastered.wav", self.s.mix, sr_out, 32 if bd == 32 else 24,
                                   source_sample_rate=self.sr, dither=False, protected=protected)
        files["master"] = write_audio(out / "master.wav", self.s.master, sr_out, bd, source_sample_rate=self.sr,
                                      dither=bd < 32, protected=protected)
        if self.p.export_stems and hasattr(self, "_mix_result"):
            for gid, y in self._mix_result.buses.items():
                g = 10 ** (self._mix_result.headroom_gain_db / 20)
                files[f"stem_{gid}"] = write_audio(out / "stems" / f"{gid}.wav", y * g, sr_out, 24,
                                                   source_sample_rate=self.sr, dither=False, protected=protected)
        (out / "plan.json").write_text(json.dumps(self.s.plan, indent=2, ensure_ascii=False, default=_json_default),
                                       encoding="utf-8")
        files["presets"] = export_plan_presets({**self.s.plan, "_master_report": self.s.master_report}, out / "presets")
        files["setup_sheet"] = write_setup_sheet(self.s.plan, out / "setup_sheet.html")
        self.progress(0.97, "Erstelle Bericht")
        files["report"] = write_reports(self, out, files)
        self.progress(1.0, "Fertig")
        return {"folder": str(out), "files": files}

    def run_all(self, out: Path | None = None) -> dict:
        t0 = time.time()
        self.load()
        self.analyze()
        self.make_plan()
        self.prepare()
        self.optimize()
        self.render()
        self.master_mix()
        result = self.export(out)
        self.s.timings["total_s"] = round(time.time() - t0, 3)
        return result

    # ------------------------------------------------------------ Zusammenfassung
    def summary(self) -> dict:
        tracks = []
        for t in self._active_tracks():
            a = self.s.analyses.get(t.id)
            c = self.s.classes.get(t.id)
            tracks.append({
                "id": t.id, "name": t.name, "path": t.path,
                "info": self.s.infos.get(t.id),
                "analysis": a.to_dict() if a else None,
                "classification": c.to_dict() if c else None,
                "role": t.role_override or (c.role if c else None),
            })
        return {
            "engine_version": ENGINE_VERSION,
            "project": self.p.name,
            "profile": self.p.profile_id,
            "character": self.p.character.to_dict(),
            "sample_rate": self.sr,
            "tempo": {"bpm": round(self.s.tempo[0], 2), "confidence": round(self.s.tempo[1], 3)},
            "consistency": self.s.consistency,
            "tracks": tracks,
            "pairs": [{"a": a, "b": b, **v} for (a, b), v in self.s.pairs.items()],
            "polarity": [{"ref": a, "track": b, **v} for (a, b), v in self.s.polarity.items()],
            "optimization": self.s.optimization,
            "master": self.s.master_report,
            "reference": self.s.reference,
            "timings": self.s.timings,
            "errors": self.s.errors,
        }


def _json_default(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, tuple):
        return list(o)
    return str(o)


def deep_copy_plan(plan: dict) -> dict:
    return copy.deepcopy(plan)
