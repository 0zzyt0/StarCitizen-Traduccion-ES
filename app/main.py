"""Punto de entrada del gestor de la traducción al español de Star Citizen.

Uso:
  SCTraduccionES.exe                      Abre el gestor (o el asistente la primera vez)
  SCTraduccionES.exe --asistente          Abre directamente el asistente de instalación
  SCTraduccionES.exe --background-update  Comprobación silenciosa (la usa la tarea programada)
  SCTraduccionES.exe --uninstall-cleanup  Limpieza al desinstalar el programa
  SCTraduccionES.exe --elevated-op FILE   Uso interno (operación con permisos de administrador)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from sctrad import __version__  # noqa: E402
from sctrad.config import default_data_dir, load_config  # noqa: E402
from sctrad.errors import ConfigError  # noqa: E402
from sctrad.logsetup import setup_logging  # noqa: E402

MUTEX_NAME = "SCTraduccionES_Mutex"
_MUTEX = None


def _create_mutex():
    """Mutex con nombre: el instalador de Windows lo usa para pedir que se cierre el gestor antes de actualizarlo."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        return ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    except Exception:  # noqa: BLE001
        return None


def _fatal(msg: str) -> int:
    logging.getLogger(__name__).error(msg)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Traducción Star Citizen", msg)
    except Exception:  # noqa: BLE001
        if sys.stderr:
            print(msg, file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    # En el .exe sin consola stdout/stderr son None: se redirigen para que nada falle al escribir.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    p = argparse.ArgumentParser(prog="SCTraduccionES", add_help=True)
    p.add_argument("--background-update", action="store_true")
    p.add_argument("--uninstall-cleanup", action="store_true")
    p.add_argument("--asistente", action="store_true")
    p.add_argument("--elevated-op", metavar="FILE")
    p.add_argument("--version", action="version", version=__version__)
    args, _unknown = p.parse_known_args(argv)

    global _MUTEX
    _MUTEX = _create_mutex()  # se mantiene vivo durante la ejecución
    if args.elevated_op:
        import json

        data_dir = Path(json.loads(Path(args.elevated_op).read_text(encoding="utf-8"))["data_dir"])
        setup_logging(data_dir, "elevado")
        from sctrad.elevate import handle_elevated_op

        return handle_elevated_op(args.elevated_op)

    try:
        cfg = load_config()
    except ConfigError as e:
        setup_logging(default_data_dir(), "gestor")
        return _fatal(f"Error de configuración: {e}")
    data_dir = default_data_dir(cfg.app_id)
    setup_logging(data_dir, "segundo_plano" if args.background_update else "gestor")
    logging.getLogger(__name__).info("Inicio %s (args=%s)", __version__, sys.argv[1:])

    from sctrad.service import UpdateService

    service = UpdateService(cfg, data_dir=data_dir)
    from sctrad.gui import app as gui

    if args.background_update:
        return gui.run_background(service)
    if args.uninstall_cleanup:
        return gui.run_uninstall_cleanup(service)
    return gui.run_gui(service, force_wizard=args.asistente)


if __name__ == "__main__":
    sys.exit(main())
