"""Ventana única del gestor: un botón ACTUALIZAR (verde/naranja) y un botón DESINSTALAR."""

from __future__ import annotations

import html

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QVBoxLayout)

from .. import __version__, scheduler
from ..errors import PermissionNeededError, SCTradError
from ..service import (ST_FOREIGN, ST_MISSING, ST_NOT_INSTALLED, ST_UP_TO_DATE, ST_UPDATE, CheckResult,
                       InstallStatus, MissingChannel, UpdateService, compare_app_version)
from ..version_line import is_ours, short
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


class HoloSwitch(QAbstractButton):
    """Interruptor deslizante con el color del canal; en gris cuando está bloqueado."""

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.color = QColor(color)
        self.can_toggle = True
        self.setFixedSize(46, 22)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(46, 22)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        on = self.isChecked()
        col = QColor(self.color) if self.isEnabled() else QColor(GREY)
        track = QColor(col)
        track.setAlpha(150 if on else 35)
        p.setPen(QPen(col, 1.2))
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - d - 3 if on else r.left() + 3
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#eafcff") if on and self.isEnabled() else QColor("#5d7a90") if self.isEnabled() else col)
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        p.end()


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
        self.resize(820, 830)
        self.setMinimumSize(700, 720)

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

        # Avisos del equipo (archivo AVISO.txt del repositorio), en tiempo casi real.
        self.notice_frame = HoloFrame(title="Avisos")
        self.notice_box = QVBoxLayout(self.notice_frame)
        self.notice_box.setContentsMargins(18, 26, 18, 10)
        self.notice_box.setSpacing(4)
        self.notice_frame.hide()
        self.notice_lines: list = []
        self._notice_job = False
        lay.addWidget(self.notice_frame)

        self.frame = HoloFrame(title="Canales")
        self.grid = QGridLayout(self.frame)
        self.grid.setContentsMargins(18, 28, 18, 14)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(10)
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
        self.notice_timer = QTimer(self)
        self.notice_timer.setInterval(max(1, service.cfg.notice_refresh_minutes) * 60_000)
        self.notice_timer.timeout.connect(self.refresh_notice)
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
        for sw in self.frame.findChildren(HoloSwitch):
            sw.setEnabled(sw.can_toggle and not busy)
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
        heads = ["CANAL", "INSTALADA", "DISPONIBLE", "ESTADO", "TRADUCIR"]
        for c, h in enumerate(heads):
            lb = QLabel(h)
            lb.setObjectName("Kicker")
            self.grid.addWidget(lb, 0, c)
        for r, row in enumerate(self.service.channel_rows(res.statuses, res.manifest), start=1):
            if isinstance(row, MissingChannel):
                if row.optional:
                    text = "Inaccesible"
                    tip = ("Canal temporal no disponible: no está instalado en este PC o CIG lo tiene cerrado. "
                           "Cuando vuelva a aparecer se respetará tu elección del interruptor «Traducir».")
                else:
                    text, tip = "No instalado en este PC", "Este canal no está instalado en este PC."
                self.grid.addWidget(self._cell(row.channel, GREY, True, tip), r, 0)
                self.grid.addWidget(self._cell("—", GREY, tip=tip), r, 1)
                self.grid.addWidget(self._cell("—", GREY, tip=tip), r, 2)
                self.grid.addWidget(self._cell(text, GREY, tip=tip), r, 3)
                if row.optional:
                    self.grid.addWidget(self._switch(row.channel, row.enabled is True, False, tip), r, 4)
                continue
            st: InstallStatus = row
            col = CHANNEL_COLORS.get(st.install.channel, CYAN).name() if st.entry else "#7d97ab"
            path = st.install.path
            self.grid.addWidget(self._cell(st.install.channel, col, True, path), r, 0)
            inst = short(st.installed_label) if st.installed_label else ("Sin versión" if st.installed_exists else "—")
            avail = short(st.available_label) if st.available_label else (st.available_version or "—")
            self.grid.addWidget(self._cell(inst, "#d8f6ff", tip=st.installed_label or path), r, 1)
            self.grid.addWidget(self._cell(avail, "#d8f6ff", tip=st.available_label or ""), r, 2)
            text, color = STATE_TEXT.get(st.state, ("—", GREY))
            tip = st.state_label
            if not st.entry:
                text, color = "Sin traducción", "#7d97ab"
                tip = "Todavía no hay traducción publicada para este canal."
            elif st.enabled is False:
                text, color, tip = "Desactivado", GREY, "Has elegido no traducir este canal."
            elif st.enabled is None:
                text, color, tip = "Pendiente de decidir", "#ffc06b", "Activa «Traducir» para instalar la traducción."
            self.grid.addWidget(self._cell(text, color, tip=tip), r, 3)
            if st.optional:
                sw_tip = ("Activado: el gestor instala y mantiene la traducción en este canal. "
                          "Desactivado: no se toca.") if st.entry else "Todavía no hay traducción para este canal."
                self.grid.addWidget(self._switch(st.install.channel, st.enabled is True, bool(st.entry), sw_tip,
                                                 st), r, 4)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)

    def _switch(self, channel: str, checked: bool, enabled: bool, tip: str,
                st: InstallStatus | None = None) -> HoloSwitch:
        sw = HoloSwitch(CHANNEL_COLORS.get(channel, CYAN))
        sw.setObjectName(f"switch_{channel}")
        sw.setChecked(checked)
        sw.can_toggle = enabled
        sw.setEnabled(enabled and not self.busy)
        sw.setToolTip(tip)
        if st is not None:
            sw.toggled.connect(lambda on, st=st, sw=sw: self.on_toggle(st, on, sw))
        return sw

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
        self.refresh_notice()
        self.notice_timer.start()

    # ----------------------------------------------------------------- avisos
    def refresh_notice(self) -> None:
        if self._notice_job or not self.service.cfg.notice_path:
            return
        self._notice_job = True

        def done(lines):
            self._notice_job = False
            self.show_notice(lines)

        def failed(_e):
            self._notice_job = False

        Task(self, lambda _w: self.service.fetch_notice(), on_done=done, on_error=failed).start()

    def show_notice(self, lines) -> None:
        if lines == self.notice_lines:
            return
        self.notice_lines = list(lines)
        while self.notice_box.count():
            w = self.notice_box.takeAt(0).widget()
            if w:
                w.deleteLater()
        for ln in lines:
            col = CHANNEL_COLORS.get(ln.channel, QColor("#d8f6ff")).name() if ln.channel else "#d8f6ff"
            lb = QLabel(f"◆  {ln.text}")
            lb.setTextFormat(Qt.PlainText)
            lb.setWordWrap(True)
            lb.setAlignment(Qt.AlignCenter)
            lb.setFont(title_font(9.5))
            lb.setStyleSheet(f"color:{col}; letter-spacing:1px;")
            self.notice_box.addWidget(lb)
        self.notice_frame.setVisible(bool(lines))

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
        new = [st for st in res.statuses if st.needs_decision]
        if new:
            QTimer.singleShot(0, lambda: self._ask_new_channels(new))

    def ask_channel(self, st: InstallStatus) -> bool:
        """Pregunta (una sola vez) si traducir un canal temporal recién detectado."""
        ver = short(st.available_label) if st.available_label else st.available_version
        return QMessageBox.question(
            self, f"Canal {st.install.channel} detectado",
            f"Se ha detectado el canal {st.install.channel} de Star Citizen y hay traducción al español "
            f"disponible ({ver}).\n\n¿Quieres instalarla en este canal?\n\nSe recordará tu respuesta. Podrás "
            "cambiarla cuando quieras con el interruptor «Traducir».") == QMessageBox.Yes

    def _ask_new_channels(self, new: list[InstallStatus]) -> None:
        if self.busy:
            return
        yes = []
        for st in new:
            ok = self.ask_channel(st)
            self.service.set_channel_enabled(st.install.channel, ok)
            if ok:
                yes.append(st)
        self._install_channels(yes)

    def _install_channels(self, sts: list[InstallStatus]) -> None:
        """Recalcula el estado de esos canales (ya activados) e instala los que lo necesiten."""
        res = self.result
        if not res or not res.manifest:
            self.refresh()
            return
        snap = self.service.store.snapshot()
        fresh = [self.service.status_for(st.install, res.manifest, snap) for st in sts]
        pending = [st for st in fresh if st.needs_action]
        if pending:
            self._run_install(pending)
        else:
            self.refresh()

    def on_toggle(self, st: InstallStatus, on: bool, sw: HoloSwitch) -> None:
        if self.busy:
            sw.blockSignals(True)
            sw.setChecked(not on)
            sw.blockSignals(False)
            return
        ch = st.install.channel
        if on:
            self.service.set_channel_enabled(ch, True)
            self._install_channels([st])
            return
        ours = st.installed_exists and (st.record or is_ours(st.installed_label))
        if ours:
            ans = QMessageBox.question(
                self, f"Dejar de traducir {ch}",
                f"El canal {ch} tiene la traducción instalada.\n\n¿Quieres quitarla y dejar el canal en inglés?"
                "\n\nSí: se quita la traducción.\nNo: se deja como está, pero ya no se actualizará.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if ans == QMessageBox.Cancel:
                sw.blockSignals(True)
                sw.setChecked(True)
                sw.blockSignals(False)
                return
            self.service.set_channel_enabled(ch, False)
            if ans == QMessageBox.Yes:
                self._run_uninstall([st], f"Traducción quitada de {ch}: el canal está en inglés.")
                return
        else:
            self.service.set_channel_enabled(ch, False)
        self.refresh(f"El canal {ch} ya no se traducirá.")

    # ----------------------------------------------------------------- acciones
    def on_update(self) -> None:
        if self.busy:
            return
        res = self.result
        pending = [st for st in (res.statuses if res else []) if st.needs_action]
        if not pending or not res.manifest:
            self.refresh("No hay actualizaciones: ya tienes la última traducción.")
            return
        self._run_install(pending)

    def _run_install(self, pending: list[InstallStatus]) -> None:
        res = self.result
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
        self._run_uninstall(targets, "Traducción desinstalada: el juego está en inglés.")

    def _run_uninstall(self, targets: list[InstallStatus], ok_text: str) -> None:
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
            self.refresh(ok_text if not errors else None)

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
