"""GUI-Start: aime-gui  (python -m app gui)"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _crash_log(text: str):
    base = Path(os.environ.get("APPDATA", str(Path.home()))) / "AI-Mix-Engineer"
    try:
        base.mkdir(parents=True, exist_ok=True)
        (base / "start_error.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass


def main():
    try:
        from PySide6.QtWidgets import QApplication

        from .gui.main_window import MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("AI Mix Engineer")
        w = MainWindow()
        w.show()
        sys.exit(app.exec())
    except SystemExit:
        raise
    except Exception:
        _crash_log(traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
