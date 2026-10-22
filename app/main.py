"""GUI-Start: aime-gui  (python -m app gui)"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _crash_log(text: str) -> Path | None:
    base = Path(os.environ.get("APPDATA", str(Path.home()))) / "AI-Mix-Engineer"
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / "start_error.txt"
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None


def _show_error(text: str):
    path = _crash_log(text)
    shown = text if len(text) < 1200 else text[:1200] + "…"
    if path is not None:
        shown += f"\n\nGespeichert in:\n{path}"
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, shown, "AI Mix Engineer startet nicht", 0x10)
        except Exception:
            pass


def main():
    splash = None
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QLabel

        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("AI Mix Engineer")
        # Schwere Importe (numpy, scipy) laufen erst danach. Sonst bleibt der erste
        # Start über pythonw minutenlang ohne jedes Fenster.
        splash = QLabel("AI Mix Engineer startet …\nBeim ersten Mal kann das eine Minute dauern.")
        splash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        splash.setMinimumSize(460, 120)
        splash.setStyleSheet("background: #1e1e1e; color: white; font-size: 16px; padding: 16px;")
        splash.show()
        app.processEvents()

        from .gui.main_window import MainWindow

        w = MainWindow()
        w.show()
        splash.close()
        splash = None
        sys.exit(app.exec())
    except SystemExit:
        raise
    except Exception:
        if splash is not None:
            splash.close()
        _show_error(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
