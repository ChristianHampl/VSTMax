"""Hauptfenster des AI Mix Engineer."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QSlider, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from engine.classification import ROLE_LABELS_DE, ROLES
from engine.mastering import PURPOSES
from engine.profiles import Character, list_profiles

from ..orchestration.pipeline import Pipeline
from ..project.model import PROJECT_SUFFIX, Project
from .worker import start_worker

CHAR_SLIDERS = [  # Schlüssel, Beschriftung, min, max, Schritt
    ("brightness", "Helligkeit (dunkel ↔ hell)", -1.0, 1.0, 0.05),
    ("punch", "Punch / Transienten", 0.0, 1.0, 0.05),
    ("width", "Stereobreite", 0.5, 1.2, 0.05),
    ("vocal_level_db", "Vocal-Pegel (dB)", -3.0, 3.0, 0.25),
    ("dynamics", "Dynamik (dicht ↔ offen)", 0.0, 1.0, 0.05),
]


class AudioPreview:
    """A/B-Wiedergabe über QtMultimedia (falls verfügbar)."""

    def __init__(self):
        self.sink = None
        self.buf = None
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices  # noqa: F401

            self.available = QMediaDevices.defaultAudioOutput() is not None and \
                not QMediaDevices.defaultAudioOutput().isNull()
        except Exception:
            self.available = False

    def play(self, x: np.ndarray, sr: int):
        if not self.available:
            return False
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

        self.stop()
        fmt = QAudioFormat()
        fmt.setSampleRate(int(sr))
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        pcm = (np.clip(x[:, :2], -1, 1) * 32767).astype("<i2").tobytes()
        self.buf = QBuffer()
        self.buf.setData(QByteArray(pcm))
        self.buf.open(QIODevice.OpenModeFlag.ReadOnly)
        self.sink = QAudioSink(QMediaDevices.defaultAudioOutput(), fmt)
        self.sink.start(self.buf)
        return True

    def stop(self):
        if self.sink is not None:
            self.sink.stop()
            self.sink = None


class MainWindow(QMainWindow):
    watch_event = Signal(str)  # aus dem Überwachungs-Thread

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI Mix Engineer – lokal, ohne Cloud")
        self.resize(1280, 820)
        self.project = Project()
        self.pipe: Pipeline | None = None
        self._jobs: list = []
        self._current = None
        self.preview = AudioPreview()
        self.link = None
        self.autopilot = None
        self.bridge = None
        self.watcher = None

        tabs = QTabWidget()
        tabs.addTab(self._build_project_tab(), "Projekt && Mix")
        tabs.addTab(self._build_cubase_tab(), "Cubase")
        tabs.addTab(self._build_album_tab(), "Album")
        tabs.addTab(self._build_watch_tab(), "Ordnerüberwachung")
        self.tabs = tabs

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.status = QLabel("Bereit")
        self.btn_cancel = QPushButton("Abbrechen")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_job)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setFixedHeight(150)

        bottom = QHBoxLayout()
        bottom.addWidget(self.progress, 3)
        bottom.addWidget(self.status, 4)
        bottom.addWidget(self.btn_cancel)
        root = QVBoxLayout()
        root.addWidget(tabs, 1)
        root.addLayout(bottom)
        root.addWidget(self.log)
        w = QWidget()
        w.setLayout(root)
        self.setCentralWidget(w)

        self.watch_event.connect(self.watch_log.appendPlainText)
        self.load_project(self.project)
        self._link_timer = QTimer(self)
        self._link_timer.timeout.connect(self.refresh_instances)
        self._link_timer.start(1000)

    # =============================================================== Projekt-Tab
    def _build_project_tab(self) -> QWidget:
        files = QHBoxLayout()
        for text, fn in (("Dateien hinzufügen …", self.add_files), ("Ordner hinzufügen …", self.add_folder),
                         ("Projekt öffnen …", self.open_project), ("Projekt speichern …", self.save_project),
                         ("Auswahl entfernen", self.remove_selected)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            files.addWidget(b)
        files.addStretch(1)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Aktiv", "Spur", "Rolle (Korrektur)", "Erkannt", "Sicherheit", "Hinweise"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        settings = QGroupBox("Einstellungen")
        form = QFormLayout()
        self.cb_profile = QComboBox()
        for p in list_profiles():
            self.cb_profile.addItem(p["name"], p["id"])
            self.cb_profile.setItemData(self.cb_profile.count() - 1, p["description"], Qt.ItemDataRole.ToolTipRole)
        self.cb_purpose = QComboBox()
        for k, v in PURPOSES.items():
            self.cb_purpose.addItem(v["name"], k)
        form.addRow("Genre-Profil", self.cb_profile)
        form.addRow("Mastering-Zweck", self.cb_purpose)
        self.sliders: dict[str, tuple[QSlider, float, float]] = {}
        for key, label, lo, hi, step in CHAR_SLIDERS:
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(0, int(round((hi - lo) / step)))
            s.setValue(int(round((getattr(Character(), key) - lo) / step)))
            val = QLabel()
            s.valueChanged.connect(lambda v, k=key, lab=val, lo=lo, st=step: lab.setText(f"{lo + v * st:+.2f}"))
            s.valueChanged.emit(s.value())
            row = QHBoxLayout()
            row.addWidget(s, 1)
            row.addWidget(val)
            form.addRow(label, row)
            self.sliders[key] = (s, lo, step)
        self.ed_reference = QLineEdit()
        self.ed_reference.setPlaceholderText("optional: Referenztrack (nur lokale Analyse)")
        b = QPushButton("…")
        b.clicked.connect(lambda: self._pick_file(self.ed_reference, "Referenztrack"))
        row = QHBoxLayout()
        row.addWidget(self.ed_reference, 1)
        row.addWidget(b)
        form.addRow("Referenz", row)
        self.ed_out = QLineEdit()
        self.ed_out.setPlaceholderText(str(Path.home() / "AI-Mix-Engineer-Exports"))
        b = QPushButton("…")
        b.clicked.connect(lambda: self._pick_dir(self.ed_out))
        row = QHBoxLayout()
        row.addWidget(self.ed_out, 1)
        row.addWidget(b)
        form.addRow("Ausgabeordner", row)
        self.cb_bits = QComboBox()
        for b_ in (24, 16, 32):
            self.cb_bits.addItem(f"{b_} Bit" + (" (Float)" if b_ == 32 else ""), b_)
        self.cb_sr = QComboBox()
        for sr in (None, 44100, 48000, 88200, 96000):
            self.cb_sr.addItem("wie Quelle" if sr is None else f"{sr} Hz", sr)
        self.chk_stems = QCheckBox("Bus-Stems exportieren")
        self.chk_stems.setChecked(True)
        self.sp_iter = QSpinBox()
        self.sp_iter.setRange(0, 30)
        self.sp_iter.setValue(8)
        fmt = QHBoxLayout()
        fmt.addWidget(self.cb_bits)
        fmt.addWidget(self.cb_sr)
        fmt.addWidget(self.chk_stems)
        form.addRow("Export", fmt)
        form.addRow("Optimierungsdurchläufe", self.sp_iter)
        settings.setLayout(form)

        actions = QHBoxLayout()
        self.btn_analyze = QPushButton("1. Analysieren")
        self.btn_preview = QPushButton("2. Mix-Vorschau berechnen")
        self.btn_export = QPushButton("3. Mischen, Mastern && Exportieren")
        self.btn_a = QPushButton("A: Original")
        self.btn_b = QPushButton("B: Mix")
        self.btn_stop = QPushButton("■")
        for b_ in (self.btn_a, self.btn_b, self.btn_stop):
            b_.setEnabled(False)
            if not self.preview.available:
                b_.setToolTip("Keine Audioausgabe verfügbar (QtMultimedia)")
        self.btn_analyze.clicked.connect(self.run_analyze)
        self.btn_preview.clicked.connect(self.run_preview)
        self.btn_export.clicked.connect(self.run_export)
        self.btn_a.clicked.connect(lambda: self.play_ab(0))
        self.btn_b.clicked.connect(lambda: self.play_ab(1))
        self.btn_stop.clicked.connect(self.preview.stop)
        for b_ in (self.btn_analyze, self.btn_preview, self.btn_export):
            actions.addWidget(b_)
        actions.addStretch(1)
        for b_ in (self.btn_a, self.btn_b, self.btn_stop):
            actions.addWidget(b_)

        left = QVBoxLayout()
        left.addLayout(files)
        left.addWidget(self.table, 1)
        left.addLayout(actions)
        lay = QHBoxLayout()
        lay.addLayout(left, 3)
        lay.addWidget(settings, 2)
        w = QWidget()
        w.setLayout(lay)
        return w

    def _pick_file(self, edit: QLineEdit, title: str):
        p, _ = QFileDialog.getOpenFileName(self, title, "", "Audio (*.wav *.aif *.aiff *.flac)")
        if p:
            edit.setText(p)

    def _pick_dir(self, edit: QLineEdit):
        p = QFileDialog.getExistingDirectory(self, "Ordner wählen")
        if p:
            edit.setText(p)

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Spuren hinzufügen", "", "Audio (*.wav *.aif *.aiff *.flac)")
        self.add_paths(paths)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Ordner mit Spuren")
        if d:
            self.add_paths([d])

    def add_paths(self, paths: list[str]):
        added = self.project.add_files(paths)
        self.pipe = None
        self.refresh_table()
        self.append_log(f"{len(added)} Datei(en) hinzugefügt")

    def remove_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            del self.project.tracks[r]
        self.pipe = None
        self.refresh_table()

    def open_project(self):
        p, _ = QFileDialog.getOpenFileName(self, "Projekt öffnen", "", f"AIME-Projekt (*{PROJECT_SUFFIX})")
        if p:
            self.load_project(Project.load(p))

    def load_project(self, p: Project):
        self.project = p
        self.pipe = None
        self._select(self.cb_profile, p.profile_id)
        self._select(self.cb_purpose, p.purpose)
        for k, (s, lo, step) in self.sliders.items():
            s.setValue(int(round((getattr(p.character, k) - lo) / step)))
        self.ed_reference.setText(p.reference_path or "")
        self.ed_out.setText(p.output_dir or "")
        self._select(self.cb_bits, p.export_bit_depth)
        self._select(self.cb_sr, p.export_sample_rate)
        self.chk_stems.setChecked(p.export_stems)
        self.sp_iter.setValue(p.optimize_iterations)
        self.refresh_table()

    def save_project(self):
        self.sync_project()
        p, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", self.project.name + PROJECT_SUFFIX,
                                           f"AIME-Projekt (*{PROJECT_SUFFIX})")
        if p:
            self.append_log(f"Projekt gespeichert: {self.project.save(p)}")

    @staticmethod
    def _select(cb: QComboBox, data):
        i = cb.findData(data)
        if i >= 0:
            cb.setCurrentIndex(i)

    def sync_project(self):
        p = self.project
        p.profile_id = self.cb_profile.currentData()
        p.purpose = self.cb_purpose.currentData()
        p.character = Character(**{k: lo + s.value() * step for k, (s, lo, step) in self.sliders.items()}).clamp()
        p.reference_path = self.ed_reference.text().strip() or None
        p.output_dir = self.ed_out.text().strip() or None
        p.export_bit_depth = self.cb_bits.currentData()
        p.export_sample_rate = self.cb_sr.currentData()
        p.export_stems = self.chk_stems.isChecked()
        p.optimize_iterations = self.sp_iter.value()
        for r, t in enumerate(p.tracks):
            t.enabled = self.table.cellWidget(r, 0).isChecked()
            t.role_override = self.table.cellWidget(r, 2).currentData()

    def refresh_table(self):
        tracks = self.project.tracks
        self.table.setRowCount(len(tracks))
        classes = self.pipe.s.classes if self.pipe else {}
        for r, t in enumerate(tracks):
            chk = QCheckBox()
            chk.setChecked(t.enabled)
            self.table.setCellWidget(r, 0, chk)
            it = QTableWidgetItem(t.name)
            it.setToolTip(t.path)
            it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(r, 1, it)
            cb = QComboBox()
            cb.addItem("automatisch", None)
            for role in ROLES:
                cb.addItem(ROLE_LABELS_DE.get(role, role), role)
            self._select(cb, t.role_override)
            cb.currentIndexChanged.connect(self._roles_changed)
            self.table.setCellWidget(r, 2, cb)
            c = classes.get(t.id)
            det = ROLE_LABELS_DE.get(c.role, c.role) if c else "–"
            conf = f"{c.confidence * 100:.0f} %" if c else "–"
            hint = ""
            if c:
                alts = ", ".join(f"{ROLE_LABELS_DE.get(a, a)} {p * 100:.0f} %" for a, p in c.alternatives[:2])
                hint = ("UNSICHER – bitte prüfen. " if c.uncertain else "") + (f"Alternativen: {alts}" if alts else "")
            for col, text in ((3, det), (4, conf), (5, hint)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if c and c.uncertain:
                    item.setBackground(Qt.GlobalColor.yellow)
                self.table.setItem(r, col, item)

    def _roles_changed(self, _i: int):
        if self.pipe is not None:
            self.pipe.s.plan = None  # neuer Plan nötig; Analyse bleibt gültig
            self.append_log("Rolle geändert - Plan wird beim nächsten Schritt neu berechnet")

    # =============================================================== Jobs
    def append_log(self, msg: str):
        self.log.appendPlainText(msg)

    def on_progress(self, f: float, msg: str):
        self.progress.setValue(int(f * 1000))
        self.status.setText(msg)

    def start_job(self, name: str, fn, on_done):
        if self._current is not None:
            QMessageBox.information(self, "Beschäftigt", "Es läuft bereits eine Aufgabe.")
            return False
        self.append_log(f"▶ {name}")
        self.btn_cancel.setEnabled(True)

        def done(res):
            self._current = None
            self.btn_cancel.setEnabled(False)
            self.progress.setValue(1000)
            self.status.setText(f"Fertig: {name}")
            self.append_log(f"✔ {name}")
            on_done(res)

        def fail(msg):
            self._current = None
            self.btn_cancel.setEnabled(False)
            self.status.setText("Fehler")
            self.append_log(f"✖ {name}: {msg}")

        th, w = start_worker(self, fn, done, fail, self.on_progress)
        self._current = w
        self._jobs.append((th, w))
        return True

    def cancel_job(self):
        if self._current is not None:
            self._current.cancel()
            self.append_log("Abbruch angefordert …")

    def _new_pipeline(self, progress, cancel) -> Pipeline:
        pipe = Pipeline(self.project, progress, cancel)
        return pipe

    def run_analyze(self):
        if not self.project.tracks:
            QMessageBox.information(self, "Keine Spuren", "Bitte zuerst Spuren hinzufügen.")
            return
        self.sync_project()

        def job(progress, cancel):
            pipe = self._new_pipeline(progress, cancel)
            pipe.load()
            pipe.analyze()
            return pipe

        def done(pipe):
            self.pipe = pipe
            self.refresh_table()
            unsure = [t.name for t in self.project.tracks if t.id in pipe.s.classes and pipe.s.classes[t.id].uncertain]
            for e in pipe.s.consistency + pipe.s.errors:
                self.append_log(f"Hinweis: {e}")
            if unsure:
                self.append_log("Unsichere Rollen (bitte prüfen): " + ", ".join(unsure))

        self.start_job("Analyse", job, done)

    def run_preview(self):
        self.sync_project()
        pipe_prev = self.pipe

        def job(progress, cancel):
            pipe = pipe_prev or self._new_pipeline(progress, cancel)
            pipe._progress, pipe._cancel = progress, cancel
            if not pipe.s.analyses:
                pipe.load()
                pipe.analyze()
            pipe.make_plan()
            pipe.prepare()
            pipe.optimize()
            return pipe

        def done(pipe):
            self.pipe = pipe
            for b in (self.btn_a, self.btn_b, self.btn_stop):
                b.setEnabled(self.preview.available)
            opt = pipe.s.optimization or {}
            self.append_log(f"Vorschau bereit. Optimierung: {json.dumps(opt, ensure_ascii=False, default=str)[:400]}")

        self.start_job("Mix-Vorschau", job, done)

    def play_ab(self, which: int):
        if not self.pipe or self.pipe.s.preview_mix is None:
            return
        a, b = self.pipe.preview_ab()
        self.preview.play(a if which == 0 else b, self.pipe.sr)

    def run_export(self):
        if not self.project.tracks:
            return
        self.sync_project()

        def job(progress, cancel):
            pipe = self._new_pipeline(progress, cancel)
            return pipe, pipe.run_all()

        def done(res):
            self.pipe, out = res
            self.refresh_table()
            after = (self.pipe.s.master_report or {}).get("after", {})
            self.append_log(f"Export: {out['folder']}")
            lufs, tp = after.get("integrated_lufs"), after.get("true_peak_dbtp")
            if lufs is not None and tp is not None:
                self.append_log(f"Master: {lufs:.1f} LUFS, True Peak {tp:.2f} dBTP")

        self.start_job("Mischen, Mastern, Exportieren", job, done)

    # =============================================================== Cubase-Tab
    def _build_cubase_tab(self) -> QWidget:
        info = QLabel(
            "Automatik mit Cubase: Auf jede Spur das Plug-in <b>AIME Channel</b>, auf Gruppen <b>AIME Bus</b> und "
            "auf den Stereo-Out <b>AIME Bus</b> (Mixbus) + <b>AIME Master</b> legen. Die Plug-ins verbinden sich "
            "lokal (127.0.0.1) mit dieser App. Ablauf: Aufnehmen (Cubase spielt den Song ab) → Analyse/Plan → "
            "Werte senden. Vor jedem Senden wird ein Snapshot gespeichert (Rückgängig).")
        info.setWordWrap(True)
        self.lbl_link = QLabel("Plugin-Link: aus")
        self.btn_link = QPushButton("Plugin-Link starten")
        self.btn_link.clicked.connect(self.toggle_link)
        self.ed_work = QLineEdit(str(Path.home() / "AI-Mix-Engineer-Cubase"))
        b = QPushButton("…")
        b.clicked.connect(lambda: self._pick_dir(self.ed_work))
        self.sp_seconds = QDoubleSpinBox()
        self.sp_seconds.setRange(0, 3600)
        self.sp_seconds.setSpecialValueText("bis Cubase stoppt")
        self.sp_seconds.setSuffix(" s")
        self.btn_midi = QPushButton("MIDI-Remote-Bridge verbinden")
        self.btn_midi.clicked.connect(self.connect_midi)
        self.lbl_midi = QLabel("MIDI Remote: nicht verbunden")

        self.inst_table = QTableWidget(0, 6)
        self.inst_table.setHorizontalHeaderLabels(["Instanz", "Plug-in", "Cubase-Kanal", "Samplerate", "Latenz",
                                                   "Zuordnung"])
        self.inst_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.btn_capture = QPushButton("1. Aufnehmen")
        self.btn_plan = QPushButton("2. Analyse && Plan")
        self.btn_push = QPushButton("3. Werte an Cubase senden")
        self.btn_undo = QPushButton("Letztes Senden rückgängig")
        self.btn_auto = QPushButton("Alles automatisch (1–3)")
        self.btn_capture.clicked.connect(lambda: self.run_autopilot("capture"))
        self.btn_plan.clicked.connect(lambda: self.run_autopilot("plan"))
        self.btn_push.clicked.connect(lambda: self.run_autopilot("push"))
        self.btn_undo.clicked.connect(lambda: self.run_autopilot("undo"))
        self.btn_auto.clicked.connect(lambda: self.run_autopilot("all"))

        top = QFormLayout()
        row = QHBoxLayout()
        row.addWidget(self.btn_link)
        row.addWidget(self.lbl_link, 1)
        top.addRow(row)
        row = QHBoxLayout()
        row.addWidget(self.ed_work, 1)
        row.addWidget(b)
        top.addRow("Arbeitsordner", row)
        top.addRow("Aufnahmedauer", self.sp_seconds)
        row = QHBoxLayout()
        row.addWidget(self.btn_midi)
        row.addWidget(self.lbl_midi, 1)
        top.addRow(row)
        acts = QHBoxLayout()
        for b_ in (self.btn_capture, self.btn_plan, self.btn_push, self.btn_undo, self.btn_auto):
            acts.addWidget(b_)
        lay = QVBoxLayout()
        lay.addWidget(info)
        lay.addLayout(top)
        lay.addWidget(self.inst_table, 1)
        lay.addLayout(acts)
        w = QWidget()
        w.setLayout(lay)
        return w

    def toggle_link(self, port: int | None = None):
        from integration.plugin_link.server import LinkServer

        if self.link is None:
            try:
                self.link = LinkServer(port=port if isinstance(port, int) else None).start()
            except OSError as exc:
                QMessageBox.warning(self, "Plugin-Link", f"Port belegt oder nicht verfügbar: {exc}")
                self.link = None
                return
            self.btn_link.setText("Plugin-Link stoppen")
            self.lbl_link.setText(f"Plugin-Link: lauscht auf 127.0.0.1:{self.link.port}")
        else:
            self.link.stop()
            self.link = None
            self.autopilot = None
            self.btn_link.setText("Plugin-Link starten")
            self.lbl_link.setText("Plugin-Link: aus")
        self.refresh_instances()

    def connect_midi(self):
        from integration.midi_remote.bridge import MidoPorts

        try:
            self._midi_ports = MidoPorts()
            self.bridge = self._midi_ports.open()
            self.lbl_midi.setText("MIDI Remote: verbunden" + (f" ({self.bridge.hello})" if self.bridge.hello else
                                                                "; noch keine Rückmeldung vom Skript"))
        except Exception as exc:
            self.bridge = None
            self.lbl_midi.setText(f"MIDI Remote: {exc}")

    def refresh_instances(self):
        insts = self.link.instances() if self.link else []
        matches = self.autopilot.match.by_instance() if self.autopilot and self.autopilot.match else {}
        self.inst_table.setRowCount(len(insts))
        for r, i in enumerate(sorted(insts, key=lambda x: (x.plugin, x.channel_name))):
            m = matches.get(i.hex_id)
            vals = [i.hex_id[-6:], i.plugin, i.channel_name or "(noch kein Name)", f"{i.sample_rate:.0f}",
                    str(i.latency), (m.target_name or f"– ({m.reason})") if m else ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.inst_table.setItem(r, c, it)
        if self.link:
            self.lbl_link.setText(f"Plugin-Link: 127.0.0.1:{self.link.port} – {len(insts)} Instanz(en)")

    def _get_autopilot(self):
        from ..orchestration.autopilot import Autopilot, AutopilotOptions

        self.sync_project()
        opt = AutopilotOptions(profile_id=self.project.profile_id, purpose=self.project.purpose,
                               optimize_iterations=self.project.optimize_iterations,
                               capture_seconds=self.sp_seconds.value() or None)
        if self.autopilot is None:
            self.autopilot = Autopilot(self.link, self.ed_work.text(), opt, bridge=self.bridge)
        else:
            self.autopilot.opt, self.autopilot.bridge = opt, self.bridge
        return self.autopilot

    def run_autopilot(self, step: str):
        if self.link is None:
            QMessageBox.information(self, "Plugin-Link", "Bitte zuerst den Plugin-Link starten.")
            return
        ap = self._get_autopilot()

        def job(progress, cancel):
            ap._progress, ap._cancel = progress, cancel
            if step == "capture":
                return ap.capture().__dict__
            if step == "plan":
                if ap.capture_result is None:
                    raise RuntimeError("Noch keine Aufnahme")
                ap.build_project()
                return ap.plan()
            if step == "push":
                return ap.push()
            if step == "undo":
                return ap.undo()
            return ap.run()

        def done(res):
            self.append_log(json.dumps(res, ensure_ascii=False, default=str)[:2000])
            if step in ("plan", "all") and ap.pipeline:
                self.project, self.pipe = ap.project, ap.pipeline
                self.refresh_table()
            if ap.match and ap.match.conflicts:
                self.append_log("Zuordnungskonflikte: " + "; ".join(ap.match.conflicts))
            self.refresh_instances()

        self.start_job(f"Cubase: {step}", job, done)

    # =============================================================== Album-Tab
    def _build_album_tab(self) -> QWidget:
        self.album_list = QListWidget()
        add = QPushButton("Mixdowns hinzufügen …")
        add.clicked.connect(self._album_add)
        clr = QPushButton("Liste leeren")
        clr.clicked.connect(self.album_list.clear)
        self.cb_album_mode = QComboBox()
        self.cb_album_mode.addItem("Einheitliche Lautheit", "uniform")
        self.cb_album_mode.addItem("Relative Unterschiede erhalten", "relative")
        self.cb_album_purpose = QComboBox()
        for k, v in PURPOSES.items():
            if v["target_lufs"] is not None:
                self.cb_album_purpose.addItem(f"{v['name']} ({v['target_lufs']} LUFS)", k)
        self.sp_tonal = QDoubleSpinBox()
        self.sp_tonal.setRange(0, 1)
        self.sp_tonal.setSingleStep(0.1)
        self.sp_tonal.setValue(0.5)
        self.ed_album_out = QLineEdit(str(Path.home() / "AI-Mix-Engineer-Album"))
        run = QPushButton("Album mastern")
        run.clicked.connect(self.run_album)
        form = QFormLayout()
        form.addRow("Modus", self.cb_album_mode)
        form.addRow("Zielwerte", self.cb_album_purpose)
        form.addRow("Tonaler Angleich (0–1)", self.sp_tonal)
        form.addRow("Ausgabe", self.ed_album_out)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(clr)
        row.addStretch(1)
        row.addWidget(run)
        lay = QVBoxLayout()
        lay.addWidget(self.album_list, 1)
        lay.addLayout(form)
        lay.addLayout(row)
        w = QWidget()
        w.setLayout(lay)
        return w

    def _album_add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Mixdowns", "", "Audio (*.wav *.aif *.aiff *.flac)")
        self.album_list.addItems(paths)

    def run_album(self):
        from engine.album import album_master
        from engine.mastering import MasterSettings

        songs = [self.album_list.item(i).text() for i in range(self.album_list.count())]
        if len(songs) < 2:
            QMessageBox.information(self, "Album", "Mindestens zwei Songs auswählen.")
            return
        pp = PURPOSES[self.cb_album_purpose.currentData()]
        st = MasterSettings(target_lufs=pp["target_lufs"], true_peak_db=pp["true_peak_db"])
        mode, tonal, out = self.cb_album_mode.currentData(), self.sp_tonal.value(), self.ed_album_out.text()

        self.start_job("Album-Mastering",
                       lambda progress, cancel: album_master(songs, out, st, mode=mode, tonal_match=tonal,
                                                             progress=progress, cancel=cancel),
                       lambda res: self.append_log(json.dumps(res, ensure_ascii=False, default=str)[:2000]))

    # =============================================================== Überwachung
    def _build_watch_tab(self) -> QWidget:
        self.ed_inbox = QLineEdit(str(Path.home() / "AI-Mix-Engineer-Eingang"))
        self.ed_outbox = QLineEdit(str(Path.home() / "AI-Mix-Engineer-Exports"))
        self.btn_watch = QPushButton("Überwachung starten")
        self.btn_watch.clicked.connect(self.toggle_watch)
        self.watch_log = QPlainTextEdit()
        self.watch_log.setReadOnly(True)
        hint = QLabel("In Cubase per <i>Audio-Mixdown exportieren → Kanal-Batch-Export</i> alle Spuren in einen "
                      "Unterordner des Eingangsordners exportieren. Jeder Unterordner = ein Song. Sobald die Dateien "
                      "stabil sind, wird automatisch gemischt, gemastert und exportiert. Profil/Zweck aus dem "
                      "Projekt-Tab.")
        hint.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Eingangsordner", self.ed_inbox)
        form.addRow("Ausgabeordner", self.ed_outbox)
        lay = QVBoxLayout()
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addWidget(self.btn_watch)
        lay.addWidget(self.watch_log, 1)
        w = QWidget()
        w.setLayout(lay)
        return w

    def toggle_watch(self):
        from ..orchestration.watcher import FolderWatcher, WatchOptions

        if self.watcher is None:
            self.sync_project()
            Path(self.ed_inbox.text()).mkdir(parents=True, exist_ok=True)
            try:
                self.watcher = FolderWatcher(self.ed_inbox.text(), self.ed_outbox.text(),
                                             WatchOptions(profile_id=self.project.profile_id,
                                                          purpose=self.project.purpose),
                                             on_event=lambda e: self.watch_event.emit(
                                                 f"{e.song}: {e.status} {e.folder or ''} {e.message}"))
            except ValueError as exc:
                QMessageBox.warning(self, "Überwachung", str(exc))
                self.watcher = None
                return
            self.watcher.start()
            self.btn_watch.setText("Überwachung stoppen")
            self.watch_log.appendPlainText(f"Überwache {self.ed_inbox.text()}")
        else:
            self.watcher.stop()
            self.watcher = None
            self.btn_watch.setText("Überwachung starten")

    def closeEvent(self, ev):
        if self._current is not None:
            self._current.cancel()
        for th, _ in self._jobs:
            th.quit()
            th.wait(3000)
        if self.watcher:
            self.watcher.stop()
        if self.link:
            self.link.stop()
        self.preview.stop()
        super().closeEvent(ev)
