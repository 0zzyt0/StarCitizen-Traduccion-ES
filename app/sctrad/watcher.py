"""Vigilante: lanza la comprobación al abrir el RSI Launcher y al cerrar Star Citizen.

Proceso mínimo que se inicia con la sesión de Windows (tarea programada). No carga Qt,
no usa la red ni la criptografía: cada pocos segundos toma una instantánea de los nombres
de los procesos y, cuando detecta uno de los dos eventos, lanza en un proceso aparte
`SCTraduccionES.exe --background-update`, que comprueba GitHub, instala si procede,
avisa solo si hay algo que contar y termina.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .errors import BusyError
from .lock import FileLock
from .procs import process_names
from .state import StateStore

log = logging.getLogger(__name__)

WATCH_ARG = "--vigilante"
EV_LAUNCHER = "launcher"
EV_GAME_CLOSED = "juego_cerrado"
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


class ProcessWatcher:
    """Detecta flancos: el launcher aparece / el juego desaparece."""

    def __init__(self, launcher_names, game_names, on_event: Callable[[str], None],
                 list_names: Callable[[], set[str]] = process_names,
                 clock: Callable[[], float] = time.monotonic,
                 launcher_cooldown: float = 600.0, game_cooldown: float = 60.0):
        self.launcher = {n.lower() for n in launcher_names}
        self.game = {n.lower() for n in game_names}
        self.on_event = on_event
        self.list_names = list_names
        self.clock = clock
        self.cooldown = {EV_LAUNCHER: launcher_cooldown, EV_GAME_CLOSED: game_cooldown}
        self.last_fired: dict[str, float] = {}
        names = self.list_names()
        # El launcher ya abierto al arrancar cuenta como evento; el juego ya abierto, no.
        self.launcher_prev = False
        self.game_prev = bool(names & self.game)

    def _fire(self, ev: str) -> None:
        now = self.clock()
        last = self.last_fired.get(ev)
        if last is not None and now - last < self.cooldown[ev]:
            log.info("Evento %s ignorado (hace poco que se comprobó).", ev)
            return
        self.last_fired[ev] = now
        log.info("Evento: %s", ev)
        self.on_event(ev)

    def step(self) -> None:
        names = self.list_names()
        launcher_now = bool(names & self.launcher)
        game_now = bool(names & self.game)
        if launcher_now and not self.launcher_prev:
            self._fire(EV_LAUNCHER)
        if self.game_prev and not game_now:
            self._fire(EV_GAME_CLOSED)
        self.launcher_prev = launcher_now
        self.game_prev = game_now


def background_command(origin: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--background-update", "--origen", origin]
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[1] / "main.py"
    return [str(pyw if pyw.exists() else exe), str(main), "--background-update", "--origen", origin]


def spawn_check(origin: str) -> None:
    flags = (CREATE_NO_WINDOW | DETACHED_PROCESS) if os.name == "nt" else 0
    try:
        subprocess.Popen(background_command(origin), close_fds=True, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        log.error("No se pudo lanzar la comprobación: %r", e)


def run_watcher(cfg: AppConfig, data_dir: Path, poll: float = 4.0, settings_every: float = 30.0,
                stop: threading.Event | None = None, spawn: Callable[[str], None] = spawn_check,
                list_names: Callable[[], set[str]] = process_names) -> int:
    lock = FileLock(Path(data_dir) / "vigilante.lock", timeout=0)
    try:
        lock.acquire()
    except BusyError:
        log.info("El vigilante ya está en marcha.")
        return 0
    store = StateStore(Path(data_dir), cfg.default_check_interval_hours)
    stop = stop or threading.Event()
    try:
        def enabled() -> bool:
            s = store.settings()
            return bool(s.get("auto_update")) and bool(s.get("task_registered"))

        if not enabled():
            log.info("Actualizaciones automáticas desactivadas: el vigilante no se queda en marcha.")
            return 0
        log.info("Vigilante iniciado (launcher: %s, juego: %s).", cfg.launcher_process_names, cfg.game_process_names)
        w = ProcessWatcher(cfg.launcher_process_names, cfg.game_process_names, spawn, list_names)
        last_settings = time.monotonic()
        while not stop.is_set():
            try:
                w.step()
            except Exception:  # noqa: BLE001 - el vigilante nunca debe caerse
                log.exception("Error en el vigilante")
            if time.monotonic() - last_settings >= settings_every:
                last_settings = time.monotonic()
                if not enabled():
                    log.info("Actualizaciones automáticas desactivadas: el vigilante se detiene.")
                    break
            stop.wait(poll)
        return 0
    finally:
        lock.release()
