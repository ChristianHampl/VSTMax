"""Hilfe-Tab: Einrichtung und Bedienung im Fenster, ohne externe Dateien lesen zu müssen."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QHBoxLayout, QListWidget, QPushButton, QTextBrowser, QVBoxLayout, QWidget

HELP_DIR = Path(__file__).resolve().parents[1] / "help"

TOPICS = [
    ("start.md", "Start"),
    ("cubase.md", "Cubase einrichten"),
    ("bedienung.md", "Songs mischen"),
    ("automatik.md", "Automatik, Album, Ordner"),
    ("probleme.md", "Wenn etwas hakt"),
    ("stand.md", "Was schon geprüft ist"),
]


class HelpPanel(QWidget):
    def __init__(self, on_install):
        super().__init__()
        self._topics = []
        self.topics = QListWidget()
        for name, title in TOPICS:
            path = HELP_DIR / name
            self._topics.append(path.read_text(encoding="utf-8") if path.is_file() else f"(fehlt: {name})")
            self.topics.addItem(title)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.topics.currentRowChanged.connect(self._show)
        self.topics.setCurrentRow(0)
        self.topics.setFixedWidth(220)

        install = QPushButton("Für Cubase einrichten")
        install.setToolTip("Kopiert AIME.vst3 und das MIDI-Remote-Skript in die Cubase-Ordner deines Benutzerkontos")
        install.clicked.connect(on_install)

        row = QHBoxLayout()
        row.addWidget(self.topics)
        row.addWidget(self.view, 1)
        lay = QVBoxLayout()
        lay.addWidget(install)
        lay.addLayout(row, 1)
        self.setLayout(lay)

    def _show(self, row: int):
        if 0 <= row < len(self._topics):
            self.view.setMarkdown(self._topics[row])
