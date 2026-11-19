"""Puntos de entrada con interfaz: gestor, asistente, notificaciones y limpieza al desinstalar."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QLabel, QMessageBox,
                               QSystemTrayIcon, QVBoxLayout)

from .. import scheduler
from ..errors import SCTradError
from ..service import Notice, UpdateService
from .manager import ManagerWindow
from .theme import app_icon, apply_theme
from .wizard import InstallWizard

log = logging.getLogger(__name__)


def _app() -> QApplication:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SC-Traduccion-ES")
    app.setApplicationDisplayName("Traducción Star Citizen")
    apply_theme(app)
    return app


def manager_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parents[2] / "main.py")]


def run_gui(service: UpdateService, force_wizard: bool = False) -> int:
    app = _app()
    lock = QLockFile(str(service.data_dir / "gestor.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, "Traducción Star Citizen", "El gestor de la traducción ya está abierto.")
        return 0
    try:
        scheduler.ensure_current(service)
    except Exception:  # noqa: BLE001
        log.exception("No se pudo actualizar la tarea programada")
    first = force_wizard or not service.store.settings().get("first_run_done")
    if first:
        wiz = InstallWizard(service, first_run=True)
        wiz.exec()  # si se cancela, la próxima vez se vuelve a mostrar el asistente
        if not wiz.open_manager:
            lock.unlock()
            return 0
    win = ManagerWindow(service)
    win.show()
    rc = app.exec()
    lock.unlock()
    return rc


def show_notices(notices: list[Notice], timeout_ms: int = 12000) -> None:
    """Muestra notificaciones de Windows (bandeja) y termina sola."""
    if not notices:
        return
    app = _app()
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.info("Bandeja no disponible; avisos: %s", [n.text for n in notices])
        return
    tray = QSystemTrayIcon(app_icon())
    tray.setToolTip("Traducción Star Citizen")
    tray.show()

    def open_manager():
        try:
            subprocess.Popen(manager_command(), close_fds=True)
        except OSError as e:
            log.warning("No se pudo abrir el gestor: %r", e)
        app.quit()

    tray.messageClicked.connect(open_manager)
    tray.activated.connect(lambda *_: open_manager())
    icons = {"ok": QSystemTrayIcon.Information, "info": QSystemTrayIcon.Information,
             "warning": QSystemTrayIcon.Warning}
    title = notices[0].title if len(notices) == 1 else "Traducción Star Citizen"
    text = "\n".join(n.text for n in notices)
    kind = "warning" if any(n.kind == "warning" for n in notices) else notices[0].kind
    QTimer.singleShot(500, lambda: tray.showMessage(title, text, icons.get(kind, QSystemTrayIcon.Information),
                                                    timeout_ms))
    QTimer.singleShot(timeout_ms + 3000, app.quit)
    app.exec()
    tray.hide()


def run_background(service: UpdateService, origin: str = "manual") -> int:
    try:
        scheduler.ensure_current(service)
    except Exception:  # noqa: BLE001
        log.exception("No se pudo actualizar la tarea programada")
    try:
        notices = service.run_background(origin=origin)
    except SCTradError as e:
        log.error("Comprobación en segundo plano fallida: %s", e)
        return 1
    except Exception:  # noqa: BLE001
        log.exception("Error inesperado en segundo plano")
        return 1
    try:
        show_notices(notices)
    except Exception:  # noqa: BLE001
        log.exception("No se pudo mostrar la notificación")
    return 0


def run_uninstall_cleanup(service: UpdateService) -> int:
    """Lo llama el desinstalador de Windows antes de borrar el programa."""
    _app()
    scheduler.unregister(service.cfg.scheduled_task_name)
    managed = [gi for gi in service.known_installs() if gi.key in service.store.snapshot()["installs"]]
    dlg = QDialog()
    dlg.setWindowTitle("Desinstalar la traducción de Star Citizen")
    dlg.setWindowIcon(app_icon())
    lay = QVBoxLayout(dlg)
    lbl = QLabel("Se va a desinstalar el gestor de la traducción. La comprobación automática ya se ha eliminado.")
    lbl.setWordWrap(True)
    lay.addWidget(lbl)
    chk_game = QCheckBox("Quitar también la traducción del juego y dejarlo como estaba"
                         + (f" ({', '.join(g.channel for g in managed)})" if managed else ""))
    chk_game.setChecked(True)
    chk_game.setEnabled(bool(managed))
    lay.addWidget(chk_game)
    chk_data = QCheckBox("Borrar ajustes, registros y copias de seguridad del gestor")
    chk_data.setChecked(False)
    lay.addWidget(chk_data)
    bb = QDialogButtonBox(QDialogButtonBox.Ok)
    bb.button(QDialogButtonBox.Ok).setText("Continuar")
    bb.accepted.connect(dlg.accept)
    lay.addWidget(bb)
    dlg.exec()
    problems = []
    if chk_game.isChecked() and managed:
        if service.game_running():
            QMessageBox.warning(None, "Star Citizen está abierto",
                                "Cierra Star Citizen y pulsa Aceptar para quitar la traducción.")
        for gi in managed:
            try:
                problems += service.uninstall_one(gi)
            except SCTradError as e:
                problems.append(f"{gi.channel}: {e}")
    if problems:
        QMessageBox.warning(None, "Desinstalación", "Algunas cosas no se pudieron deshacer:\n\n" + "\n".join(problems)
                            + "\n\nPuedes borrar a mano la carpeta data\\Localization\\spanish_(spain) del juego.")
    if chk_data.isChecked() and not problems:
        import shutil

        logging.shutdown()
        shutil.rmtree(service.data_dir, ignore_errors=True)
    return 0
