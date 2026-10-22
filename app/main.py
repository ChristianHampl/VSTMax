"""GUI-Start: aime-gui  (python -m app gui)"""

from __future__ import annotations

import sys


def main():
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AI Mix Engineer")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
