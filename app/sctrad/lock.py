"""Bloqueo entre procesos (gestor y tarea en segundo plano no actúan a la vez)."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .errors import BusyError

_thread_locks: dict[str, threading.RLock] = {}
_guard = threading.Lock()


class FileLock:
    def __init__(self, path: Path, timeout: float = 10.0, busy_message: str | None = None):
        self.path = Path(path)
        self.timeout = timeout
        self.busy_message = busy_message or "Hay otra operación de la traducción en curso. Inténtalo en unos segundos."
        self._fh = None
        with _guard:
            self._tlock = _thread_locks.setdefault(str(self.path), threading.RLock())
        self._depth = 0

    def acquire(self) -> None:
        ok = self._tlock.acquire(timeout=self.timeout) if self.timeout > 0 else self._tlock.acquire(blocking=False)
        if not ok:
            raise BusyError(self.busy_message)
        if self._depth:
            self._depth += 1
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(self.timeout, 0)
        fh = open(self.path, "a+b")
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    fh.close()
                    self._tlock.release()
                    raise BusyError(self.busy_message)
                time.sleep(0.1)
        self._fh = fh
        self._depth = 1

    def release(self) -> None:
        if self._depth > 1:
            self._depth -= 1
            self._tlock.release()
            return
        fh, self._fh = self._fh, None
        self._depth = 0
        if fh:
            try:
                if os.name == "nt":
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            fh.close()
        self._tlock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
        return False
