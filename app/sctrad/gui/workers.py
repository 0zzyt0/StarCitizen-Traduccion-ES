"""Ejecuta tareas largas fuera del hilo de la interfaz.

Las señales del hilo de trabajo se reenvían a través de un QObject que vive en el
hilo principal, de modo que las funciones de respuesta siempre se ejecutan en el
hilo de la interfaz.
"""

from __future__ import annotations

import logging
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, Slot

log = logging.getLogger(__name__)


class _Worker(QObject):
    finished = Signal(object)
    failed = Signal(object)
    text = Signal(str)
    bytes_progress = Signal(int, int)

    def __init__(self, fn: Callable, args, kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs

    @Slot()
    def run(self):
        try:
            result = self.fn(self, *self.args, **self.kwargs)
        except BaseException as e:  # noqa: BLE001
            log.error("Error en tarea: %s\n%s", e, traceback.format_exc())
            self.failed.emit(e)
        else:
            self.finished.emit(result)


class Task(QObject):
    """Task(parent, fn, *args, on_done=…, on_error=…, on_text=…, on_bytes=…).start()

    fn(worker, *args) recibe el worker, que tiene las señales .text y .bytes_progress.
    """

    done = Signal(object)
    error = Signal(object)
    text = Signal(str)
    progress = Signal(int, int)

    _running: set["Task"] = set()

    def __init__(self, parent, fn: Callable, *args, on_done=None, on_error=None, on_text=None,
                 on_bytes=None, **kwargs):
        super().__init__(parent)
        self.thread = QThread()
        self.worker = _Worker(fn, args, kwargs)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.text.connect(self._on_text)
        self.worker.bytes_progress.connect(self._on_bytes)
        for sig, cb in ((self.done, on_done), (self.error, on_error), (self.text, on_text),
                        (self.progress, on_bytes)):
            if cb:
                sig.connect(cb)

    def start(self) -> "Task":
        Task._running.add(self)
        self.thread.start()
        return self

    @Slot(str)
    def _on_text(self, s):
        self.text.emit(s)

    @Slot(int, int)
    def _on_bytes(self, a, b):
        self.progress.emit(a, b)

    @Slot(object)
    def _on_finished(self, result):
        self._stop()
        self.done.emit(result)

    @Slot(object)
    def _on_failed(self, exc):
        self._stop()
        self.error.emit(exc)

    def _stop(self):
        self.thread.quit()
        self.thread.wait(5000)
        Task._running.discard(self)
