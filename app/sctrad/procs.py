"""Lista de procesos en ejecución (barata: una sola instantánea del sistema)."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def _toolhelp_names() -> set[str]:
    """Nombres de ejecutables con CreateToolhelp32Snapshot (Windows, sin abrir cada proceso)."""
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if not snap or snap == ctypes.c_void_p(-1).value:
        raise OSError("CreateToolhelp32Snapshot falló")
    names: set[str] = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            names.add(entry.szExeFile.lower())
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return names


def process_names() -> set[str]:
    """Nombres (en minúsculas) de los procesos en ejecución."""
    if os.name == "nt":
        try:
            return _toolhelp_names()
        except Exception as e:  # noqa: BLE001
            log.debug("Toolhelp no disponible: %r", e)
    try:
        import psutil

        return {(p.info.get("name") or "").lower() for p in psutil.process_iter(["name"])}
    except Exception as e:  # noqa: BLE001 - nunca debe tumbar el gestor
        log.warning("No se pudo enumerar procesos: %r", e)
        return set()


def running_game_processes(names: tuple[str, ...] | list[str]) -> list[str]:
    current = process_names()
    return [n for n in names if n.lower() in current]


def is_game_running(names: tuple[str, ...] | list[str]) -> bool:
    return bool(running_game_processes(names))


def kill_other_instances(exe_name: str, arg: str) -> int:
    """Termina otras copias del gestor lanzadas con un argumento (p. ej. --vigilante). Devuelve cuántas."""
    n = 0
    try:
        import psutil

        me = os.getpid()
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if p.info["pid"] == me or (p.info.get("name") or "").lower() != exe_name.lower():
                    continue
                if arg in (p.info.get("cmdline") or []):
                    p.terminate()
                    n += 1
            except (psutil.Error, OSError):
                continue
    except Exception as e:  # noqa: BLE001
        log.warning("No se pudieron detener otras instancias: %r", e)
    return n
