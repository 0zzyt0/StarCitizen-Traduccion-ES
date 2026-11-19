"""Detección de procesos del juego."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def running_game_processes(names: tuple[str, ...] | list[str]) -> list[str]:
    wanted = {n.lower() for n in names}
    found: list[str] = []
    try:
        import psutil

        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if n in wanted:
                found.append(p.info["name"])
    except Exception as e:  # noqa: BLE001 - nunca debe tumbar el gestor
        log.warning("No se pudo enumerar procesos: %r", e)
    return found


def is_game_running(names: tuple[str, ...] | list[str]) -> bool:
    return bool(running_game_processes(names))
