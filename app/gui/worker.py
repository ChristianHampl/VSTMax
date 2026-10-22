"""Hintergrund-Ausführung langer Aufgaben mit Fortschritt und Abbruch (GUI bleibt bedienbar)."""

from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot


class Worker(QObject):
    progress = Signal(float, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Callable[[float, str], None], Callable[[], bool]], Any]):
        super().__init__()
        self._fn = fn
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            res = self._fn(lambda f, m: self.progress.emit(float(f), str(m)), self._cancel.is_set)
            self.finished.emit(res)
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}")


class _Relay(QObject):
    """Lebt im GUI-Thread; Signale aus dem Worker kommen dadurch als Queued Connection an."""

    def __init__(self, parent, on_done, on_fail, on_progress):
        super().__init__(parent)
        self._done, self._fail, self._prog = on_done, on_fail, on_progress

    @Slot(float, str)
    def progress(self, f, m):
        if self._prog:
            self._prog(f, m)

    @Slot(object)
    def done(self, res):
        if self._done:
            self._done(res)

    @Slot(str)
    def fail(self, msg):
        if self._fail:
            self._fail(msg)


def start_worker(parent: QObject, fn, on_done=None, on_fail=None, on_progress=None) -> tuple[QThread, Worker]:
    th = QThread(parent)
    w = Worker(fn)
    relay = _Relay(parent, on_done, on_fail, on_progress)
    w.moveToThread(th)
    th.started.connect(w.run)
    w.progress.connect(relay.progress, Qt.ConnectionType.QueuedConnection)
    w.finished.connect(relay.done, Qt.ConnectionType.QueuedConnection)
    w.failed.connect(relay.fail, Qt.ConnectionType.QueuedConnection)
    w.finished.connect(th.quit)
    w.failed.connect(th.quit)
    th.finished.connect(w.deleteLater)
    th.finished.connect(relay.deleteLater)
    th.start()
    return th, w
