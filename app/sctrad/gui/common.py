"""Piezas compartidas por el asistente y el gestor."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView, QMessageBox, QTreeWidget, QTreeWidgetItem, QWidget

from ..elevate import can_elevate, run_elevated
from ..errors import PermissionNeededError, SCTradError
from ..gamepaths import COMPATIBLE, INCOMPATIBLE
from ..service import (ST_FOREIGN, ST_MISSING, ST_NO_CHANNEL, ST_NOT_INSTALLED, ST_UP_TO_DATE, ST_UPDATE,
                       CheckResult, InstallStatus, UpdateService)
from .theme import BAD, MUTED, OK, WARN

STATE_COLORS = {
    ST_UP_TO_DATE: OK, ST_UPDATE: WARN, ST_MISSING: WARN, ST_FOREIGN: WARN,
    ST_NOT_INSTALLED: MUTED, ST_NO_CHANNEL: MUTED,
}
COLUMNS = ["Canal", "Carpeta del juego", "Versión del juego", "Traducción instalada", "Disponible", "Estado",
           "Compatibilidad"]


def fill_status_tree(tree: QTreeWidget, statuses: list[InstallStatus], checkable: bool = False,
                     checked_keys: set[str] | None = None) -> None:
    tree.clear()
    tree.setColumnCount(len(COLUMNS))
    tree.setHeaderLabels(COLUMNS)
    tree.setRootIsDecorated(False)
    for st in statuses:
        gi = st.install
        it = QTreeWidgetItem([
            gi.channel, gi.path, gi.game_version or "desconocida", st.installed_version or "—",
            st.available_version or "—", st.state_label, st.compat_label,
        ])
        it.setData(0, Qt.UserRole, gi.key)
        it.setForeground(5, QColor(STATE_COLORS.get(st.state, MUTED)))
        it.setForeground(6, QColor(OK if st.compat == COMPATIBLE else BAD if st.compat == INCOMPATIBLE else MUTED))
        tip = []
        if st.record and st.record.get("attention"):
            tip.append("⚠ " + st.record["attention"])
        if st.held:
            tip.append("Has vuelto a una versión anterior: no se actualizará automáticamente hasta que haya otra más nueva.")
        if gi.build:
            tip.append(f"Compilación del juego: {gi.build}")
        for c in range(len(COLUMNS)):
            it.setToolTip(c, "\n".join([gi.path, *tip]))
        if checkable:
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            installable = st.entry is not None
            if not installable:
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
            on = installable and checked_keys is not None and gi.key in checked_keys
            it.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
        tree.addTopLevelItem(it)
    tree.setTextElideMode(Qt.ElideMiddle)
    hdr = tree.header()
    hdr.setStretchLastSection(False)
    for c in range(len(COLUMNS)):
        hdr.setSectionResizeMode(c, QHeaderView.Stretch if c == 1 else QHeaderView.ResizeToContents)
    hdr.setSectionResizeMode(0, QHeaderView.Fixed)
    tree.setColumnWidth(0, 135 if checkable else 115)


@dataclass
class JobResult:
    ok: list[InstallStatus] = field(default_factory=list)
    errors: dict[str, SCTradError] = field(default_factory=dict)  # clave -> error
    needs_admin: list[InstallStatus] = field(default_factory=list)


def install_job(worker, service: UpdateService, res: CheckResult, statuses: list[InstallStatus], action: str,
                allow_foreign: bool, allow_incompatible: bool, touch_user_cfg: bool = True) -> JobResult:
    out = JobResult()
    for st in statuses:
        try:
            service.install_one(st, res.release, res.manifest, action=action, allow_foreign=allow_foreign,
                                allow_incompatible=allow_incompatible, touch_user_cfg=touch_user_cfg,
                                progress_bytes=worker.bytes_progress.emit, progress_text=worker.text.emit)
            out.ok.append(st)
            worker.text.emit(f"✔ {st.install.channel}: traducción {res.manifest.version} instalada.")
        except PermissionNeededError as e:
            out.needs_admin.append(st)
            out.errors[st.install.key] = e
            worker.text.emit(f"✖ {st.install.channel}: {e}")
        except SCTradError as e:
            out.errors[st.install.key] = e
            worker.text.emit(f"✖ {st.install.channel}: {e}")
    if res.manifest and not out.errors:
        service.cleanup_staging(res.manifest.version)
    return out


def offer_elevation(parent: QWidget, service: UpdateService, op: dict) -> tuple[list[str], dict[str, str]] | None:
    """Pregunta y ejecuta la operación con permisos de administrador. Devuelve (ok, errores) o None."""
    if not can_elevate():
        return None
    r = QMessageBox.question(
        parent, "Permisos de administrador",
        "Windows no permite escribir en la carpeta del juego con tu usuario.\n\n"
        "¿Quieres reintentar la operación con permisos de administrador? Solo se modificarán "
        "los archivos de la traducción (global.ini y user.cfg).",
    )
    if r != QMessageBox.Yes:
        return None
    try:
        result = run_elevated(op, service.data_dir)
    except SCTradError as e:
        QMessageBox.warning(parent, "Permisos de administrador", str(e))
        return None
    if result.get("fatal"):
        QMessageBox.warning(parent, "Permisos de administrador", result["fatal"])
        return None
    return result.get("ok", []), result.get("errors", {})


def show_error(parent: QWidget, title: str, exc: BaseException) -> None:
    msg = str(exc) if isinstance(exc, SCTradError) else f"Error inesperado: {exc}"
    QMessageBox.warning(parent, title, msg)
