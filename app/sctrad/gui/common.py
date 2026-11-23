"""Ayudas compartidas de la interfaz: permisos de administrador y mensajes de error."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from ..elevate import can_elevate, run_elevated
from ..errors import SCTradError
from ..service import UpdateService


def offer_elevation(parent: QWidget, service: UpdateService, op: dict) -> tuple[list[str], dict[str, str]] | None:
    """Pregunta y ejecuta la operación con permisos de administrador. Devuelve (ok, errores) o None."""
    if not can_elevate():
        return None
    r = QMessageBox.question(
        parent, "Permisos de administrador",
        "Windows no permite escribir en la carpeta del juego con tu usuario.\n\n"
        "¿Quieres reintentar la operación con permisos de administrador? Solo se modificarán "
        "los archivos de la traducción (global.ini, user.cfg y la pantalla de carga).",
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
