"""Ventana única del gestor: un botón ACTUALIZAR (verde/naranja) y un botón DESINSTALAR."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from .. import __version__, scheduler
from ..errors import PermissionNeededError, SCTradError
from ..service import (ST_FOREIGN, ST_MISSING, ST_NOT_INSTALLED, ST_UP_TO_DATE, ST_UPDATE, CheckResult,
                       InstallStatus, MissingChannel, UpdateService, compare_app_version)
from ..version_line import short
from .common import offer_elevation, show_error
from .holo import CHANNEL_COLORS, CYAN, HoloFrame, HoloLogo, HoloSurface, dark_titlebar, glow
from .theme import app_icon, title_font
from .workers import Task

GREEN = ("#3dffb0", "#12a150", QColor(61, 255, 176))
ORANGE = ("#ffc06b", "#f57c00", QColor(255, 160, 60))
GREY = "#46627a"

STATE_TEXT = {
    ST_UP_TO_DATE: ("✔ Al día", "#3dffb0"),
    ST_UPDATE: ("⬆ Hay actualización", "#ffc06b"),
    ST_MISSING: ("⬆ Hay que reparar", "#ffc06b"),
    ST_NOT_INSTALLED: ("⬆ Sin instalar", "#ffc06b"),
    ST_FOREIGN: ("⬆ Otra traducción", "#ffc06b"),
}


def big_button_qss(colors) -> str:
    light, dark, _ = colors
    return (f"QPushButton {{ font-family: Orbitron; font-size: 17pt; font-weight: 800; letter-spacing: 4px;"
            f" color: #02140c; border: 2px solid {light}; border-radius: 6px; padding: 14px 40px;"
            f" background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {light}, stop:1 {dark}); }}"
            f" QPushButton:hover {{ border-color: white; }}"
            f" QPushButton:disabled {{ color: #2a4152; background: #0c1b2a; border-color: #1c3346; }}")


class SimpleWindow(QMainWindow):
    def __init__(self, service: UpdateService):
        super().__init__()
        self.service = service
        self.result: CheckResult | None = None
        self.busy = False
        self.setWindowTitle("Traducción al español de Star Citizen")
        self.setWindowIcon(app_icon())
        self.resize(820, 760)
        self.setMinimumSize(700, 680)

        root = HoloSurface()
        lay = QVBoxLayout(root)
        lay.setContentsMargins(28, 18, 28, 14)
        lay.setSpacing(8)
        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo_row.addWidget(HoloLogo(170))
        logo_row.addStretch(1)
        lay.addLayout(logo_row)
        k = QLabel("STAR CITIZEN · PROYECTO DE LA COMUNIDAD")
        k.setObjectName("Kicker")
        k.setAlignment(Qt.AlignCenter)
        lay.addWidget(k)
        t = QLabel("TRADUCCIÓN AL ESPAÑOL")
        t.setObjectName("Title")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        self.headline = QLabel("COMPROBANDO…")
        self.headline.setAlignment(Qt.AlignCenter)
        self.headline.setFont(title_font(10.5))
        self.headline.setStyleSheet("color:#38d6ff; letter-spacing:2px;")
        lay.addWidget(self.headline)

        self.frame = HoloFrame(title="Canales")
        self.grid = QGridLayout(self.frame)
        self.grid.setContentsMargins(18, 28, 18, 14)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(8)
        lay.addWidget(self.frame)

        lay.addSpacing(6)
        self.btn_update = QPushButton("ACTUALIZAR")
        self.btn_update.setMinimumWidth(380)
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.clicked.connect(self.on_update)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.btn_update)
        row.addStretch(1)
        lay.addLayout(row)
        self._paint_update(ORANGE)

        self.btn_uninstall = QPushButton("DESINSTALAR")
        self.btn_uninstall.setObjectName("Danger")
        self.btn_uninstall.setCursor(Qt.PointingHandCursor)
        self.btn_uninstall.setToolTip("Quita la traducción y deja el juego en inglés")
        self.btn_uninstall.clicked.connect(self.on_uninstall)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        row2.addWidget(self.btn_uninstall)
        row2.addStretch(1)
        lay.addLayout(row2)

        lay.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        lay.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        self.status.setOpenExternalLinks(True)
        lay.addWidget(self.status)
        foot = QHBoxLayout()
        self.footer = QLabel(f"Gestor {__version__}")
        self.footer.setObjectName("Subtitle")
        foot.addWidget(self.footer)
        foot.addStretch(1)
        self.btn_folder = QPushButton("Elegir carpeta del juego…")
        self.btn_folder.clicked.connect(self.choose_folder)
        self.btn_folder.hide()
        foot.addWidget(self.btn_folder)
        lay.addLayout(foot)
        self.setCentralWidget(root)
        QTimer.singleShot(60, self.start)

    def showEvent(self, ev):
        super().showEvent(ev)
        dark_titlebar(self)

    # ----------------------------------------------------------------- apariencia
    def _paint_update(self, colors) -> None:
        self.btn_update.setStyleSheet(big_button_qss(colors))
        glow(self.btn_update, colors[2], 34)

    def _set_busy(self, busy: bool, text: str = "") -> None:
        self.busy = busy
        self.btn_update.setEnabled(not busy)
        self.btn_uninstall.setEnabled(not busy and self._has_translation())
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
        if text:
            self.status.setText(html.escape(text))

    def _clear_grid(self) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _cell(self, text: str, color: str, bold: bool = False, tip: str = "") -> QLabel:
        lb = QLabel(text)
        lb.setStyleSheet(f"color:{color};")
        if bold:
            lb.setFont(title_font(9.5))
        if tip:
            lb.setToolTip(tip)
        return lb

    def _fill_channels(self, res: CheckResult) -> None:
        self._clear_grid()
        heads = ["CANAL", "INSTALADA", "DISPONIBLE", "ESTADO"]
        for c, h in enumerate(heads):
            lb = QLabel(h)
            lb.setObjectName("Kicker")
            self.grid.addWidget(lb, 0, c)
        for r, row in enumerate(self.service.channel_rows(res.statuses, res.manifest), start=1):
            if isinstance(row, MissingChannel):
                tip = "Este canal no está instalado en este PC."
                self.grid.addWidget(self._cell(row.channel, GREY, True, tip), r, 0)
                self.grid.addWidget(self._cell("—", GREY, tip=tip), r, 1)
                self.grid.addWidget(self._cell("—", GREY, tip=tip), r, 2)
                self.grid.addWidget(self._cell("No instalado en este PC", GREY, tip=tip), r, 3)
                continue
            st: InstallStatus = row
            col = CHANNEL_COLORS.get(st.install.channel, CYAN).name()
            path = st.install.path
            self.grid.addWidget(self._cell(st.install.channel, col, True, path), r, 0)
            inst = short(st.installed_label) if st.installed_label else ("Sin versión" if st.installed_exists else "—")
            avail = short(st.available_label) if st.available_label else (
                st.available_version or "Sin traducción para este canal")
            self.grid.addWidget(self._cell(inst, "#d8f6ff", tip=st.installed_label or path), r, 1)
            self.grid.addWidget(self._cell(avail, "#d8f6ff", tip=st.available_label or ""), r, 2)
            text, color = STATE_TEXT.get(st.state, ("—", GREY))
            if not st.entry:
                text, color = "Sin traducción publicada", GREY
            self.grid.addWidget(self._cell(text, color, tip=st.state_label), r, 3)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)

    def _has_translation(self) -> bool:
        return bool(self.result and any(st.installed_exists or st.record for st in self.result.statuses))

    # ----------------------------------------------------------------- comprobar
    def start(self) -> None:
        """Al abrir: asegura el vigilante (launcher/cierre del juego) y comprueba."""
        def ensure(_w):
            s = self.service.store.settings()
            if not (s.get("auto_update") and s.get("task_registered")):
                scheduler.apply_settings(self.service, True)
            else:
                scheduler.ensure_current(self.service)
            self.service.store.update_settings(first_run_done=True)
        Task(self, ensure, on_done=lambda _r: None, on_error=lambda e: None).start()
        self.refresh()

    def refresh(self, after_text: str | None = None) -> None:
        self._set_busy(True, "Comprobando la traducción publicada en GitHub…")
        def job(_w):
            r = self.service.check()
            self.service.adopt_identical(r)
            return r
        Task(self, job, on_done=lambda r: self._show(r, after_text), on_error=self._failed).start()

    def _failed(self, exc) -> None:
        self._set_busy(False)
        self.headline.setText("NO SE PUDO COMPROBAR")
        self.status.setText(html.escape(str(exc)))

    def _show(self, res: CheckResult, after_text: str | None = None) -> None:
        self.result = res
        self._fill_channels(res)
        pending = [st for st in res.statuses if st.needs_action]
        if pending:
            self._paint_update(GREEN)
            self.headline.setText("HAY UNA ACTUALIZACIÓN DISPONIBLE")
            self.headline.setStyleSheet("color:#3dffb0; letter-spacing:2px;")
        else:
            self._paint_update(ORANGE)
            if res.manifest and res.statuses:
                self.headline.setText("TIENES LA ÚLTIMA TRADUCCIÓN")
            elif not res.statuses:
                self.headline.setText("NO SE HA ENCONTRADO STAR CITIZEN")
            else:
                self.headline.setText("SIN DATOS DE GITHUB")
            self.headline.setStyleSheet("color:#ffc06b; letter-spacing:2px;")
        self._set_busy(False)
        msgs = []
        if after_text:
            msgs.append(html.escape(after_text))
        if res.error:
            msgs.append(("⚠ Sin conexión: " if res.offline else "⚠ ") + html.escape(res.error))
        if compare_app_version(res.app_release, __version__):
            msgs.append(f"Hay un gestor nuevo ({res.app_release.version}): "
                        f"<a style='color:#38d6ff' href='{res.app_release.html_url}'>descárgalo aquí</a>.")
        self.status.setText("<br>".join(msgs))
        self.btn_folder.setVisible(not res.statuses)
        pub = f" · Traducción publicada {res.manifest.version}" if res.manifest else ""
        self.footer.setText(f"Gestor {__version__}{pub} · Se comprueba al abrir el RSI Launcher y al cerrar el juego")

    # ----------------------------------------------------------------- acciones
    def on_update(self) -> None:
        if self.busy:
            return
        res = self.result
        pending = [st for st in (res.statuses if res else []) if st.needs_action]
        if not pending or not res.manifest:
            self.refresh("No hay actualizaciones: ya tienes la última traducción.")
            return
        self._set_busy(True, "Actualizando…")
        self.progress.setRange(0, 1000)

        def job(w):
            done, errors, admin = [], {}, []
            for st in pending:
                try:
                    w.text.emit(f"Instalando {st.install.channel}…")
                    action = "actualizar" if st.installed_exists else "instalar"
                    self.service.install_one(st, res.release, res.manifest, action=action, allow_foreign=True,
                                             allow_incompatible=True, progress_bytes=w.bytes_progress.emit,
                                             progress_text=w.text.emit)
                    done.append(st.install.channel)
                except PermissionNeededError as e:
                    admin.append(st)
                    errors[st.install.channel] = str(e)
                except SCTradError as e:
                    errors[st.install.channel] = str(e)
            if not errors:
                self.service.cleanup_staging(res.manifest.version)
            return done, errors, admin

        def finished(payload):
            done, errors, admin = payload
            if admin:
                op = {"op": "install", "paths": [st.install.path for st in admin], "action": "actualizar",
                      "allow_foreign": True, "allow_incompatible": True}
                out = offer_elevation(self, self.service, op)
                if out is not None:
                    ok, errs = out
                    for st in admin:
                        if st.install.path in ok:
                            errors.pop(st.install.channel, None)
                            done.append(st.install.channel)
            if errors:
                QMessageBox.warning(self, "Actualizar", "\n".join(f"{k}: {v}" for k, v in errors.items()))
            text = f"Traducción instalada en: {', '.join(done)}." if done else None
            self.refresh(text)

        Task(self, job, on_done=finished, on_error=lambda e: (self._set_busy(False), show_error(self, "Actualizar", e)),
             on_text=lambda s: self.status.setText(html.escape(s)),
             on_bytes=lambda a, b: (self.progress.setRange(0, 1000), self.progress.setValue(int(a * 1000 / max(b, 1))))
             ).start()

    def on_uninstall(self) -> None:
        if self.busy or not self.result:
            return
        targets = [st for st in self.result.statuses if st.installed_exists or st.record]
        if not targets:
            return
        names = ", ".join(st.install.channel for st in targets)
        if QMessageBox.question(self, "Desinstalar traducción",
                                f"Se quitará la traducción de: {names}.\n\nEl juego volverá a estar en inglés "
                                "y se restaurará la pantalla de carga anterior. ¿Continuar?") != QMessageBox.Yes:
            return
        self._set_busy(True, "Desinstalando…")

        def job(w):
            errors, admin = {}, []
            for st in targets:
                try:
                    self.service.uninstall_one(st.install)
                except PermissionNeededError as e:
                    admin.append(st)
                    errors[st.install.channel] = str(e)
                except SCTradError as e:
                    errors[st.install.channel] = str(e)
            return errors, admin

        def finished(payload):
            errors, admin = payload
            if admin:
                out = offer_elevation(self, self.service, {"op": "uninstall", "paths": [s.install.path for s in admin]})
                if out is not None:
                    for st in admin:
                        if st.install.path in out[0]:
                            errors.pop(st.install.channel, None)
            if errors:
                QMessageBox.warning(self, "Desinstalar", "\n".join(f"{k}: {v}" for k, v in errors.items()))
            self.refresh("Traducción desinstalada: el juego está en inglés." if not errors else None)

        Task(self, job, on_done=finished,
             on_error=lambda e: (self._set_busy(False), show_error(self, "Desinstalar", e))).start()

    def choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Elige la carpeta de Star Citizen")
        if not d:
            return
        if not self.service.add_custom_path(d):
            QMessageBox.warning(self, "Carpeta no válida",
                                "Esa carpeta no parece una instalación de Star Citizen.\n\nElige la carpeta "
                                "«StarCitizen» o la de un canal (LIVE, PTU…).")
            return
        self.refresh()

    def closeEvent(self, ev):
        if self.busy:
            QMessageBox.information(self, "Operación en curso", "Espera a que termine la operación actual.")
            ev.ignore()
            return
        super().closeEvent(ev)
