"""Ventana principal del gestor: instalaciones, actualizaciones automáticas e historial."""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QProgressBar, QPushButton, QRadioButton, QTabWidget, QTextBrowser,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import __version__, scheduler
from ..errors import PermissionNeededError
from ..service import ST_MISSING, ST_UPDATE, CheckResult, InstallStatus, UpdateService, compare_app_version
from .common import fill_status_tree, offer_elevation, show_error
from .holo import AnimatedBackdropMixin, HoloFrame, HoloLogo, HoloSurface, dark_titlebar, glow
from .theme import app_icon
from .wizard import InstallWizard
from .workers import Task

ACTION_NAMES = {"instalar": "Instalar", "actualizar": "Actualizar", "reparar": "Reparar",
                "restaurar": "Restaurar", "desinstalar": "Desinstalar"}
ORIGINS = {"launcher": "al abrir el RSI Launcher", "juego_cerrado": "al cerrar el juego",
           "manual": "manual", "programada": "programada"}


def _framed(title: str, inner_layout) -> HoloFrame:
    f = HoloFrame(title=title)
    inner_layout.setContentsMargins(16, 26, 16, 14)
    f.setLayout(inner_layout)
    return f


class RestoreDialog(AnimatedBackdropMixin, QDialog):
    def __init__(self, parent, backups):
        super().__init__(parent)
        self._init_backdrop()
        self.setWindowTitle("Restaurar copia de seguridad")
        lay = QVBoxLayout(self)
        lbl = QLabel("Elige a qué estado quieres volver. Restaurar el «estado original» equivale a desinstalar "
                     "la traducción. Si vuelves a una versión anterior, no se actualizará automáticamente "
                     "hasta que se publique otra más nueva.")
        lbl.setWordWrap(True)
        lay.addWidget(lbl)
        self.list = QListWidget()
        for b in backups:
            it = QListWidgetItem(b.label)
            it.setData(Qt.UserRole, b.id)
            self.list.addItem(it)
        if backups:
            self.list.setCurrentRow(0)
        lay.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Restaurar")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("Cancelar")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(660, 380)

    def paintEvent(self, ev):
        self._paint_backdrop()

    def selected_id(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None


class ManagerWindow(QMainWindow):
    def __init__(self, service: UpdateService):
        super().__init__()
        self.service = service
        self.result: CheckResult | None = None
        self.busy = False
        self.setWindowTitle("Traducción al español de Star Citizen — Gestor")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)

        central = HoloSurface()
        root = QVBoxLayout(central)
        root.setContentsMargins(22, 16, 22, 10)
        head = QHBoxLayout()
        head.setSpacing(18)
        head.addWidget(HoloLogo(134))
        titles = QVBoxLayout()
        titles.setSpacing(2)
        k = QLabel("STAR CITIZEN · PROYECTO DE LA COMUNIDAD")
        k.setObjectName("Kicker")
        titles.addStretch(1)
        titles.addWidget(k)
        t = QLabel("TRADUCCIÓN AL ESPAÑOL")
        t.setObjectName("Title")
        titles.addWidget(t)
        self.sub = QLabel(f"Gestor {__version__}")
        self.sub.setObjectName("Subtitle")
        titles.addWidget(self.sub)
        titles.addStretch(1)
        head.addLayout(titles, 1)
        self.btn_check = QPushButton("Buscar ahora")
        self.btn_check.setObjectName("Primary")
        self.btn_check.clicked.connect(lambda: self.refresh())
        glow(self.btn_check)
        head.addWidget(self.btn_check, 0, Qt.AlignVCenter)
        root.addLayout(head)

        self.banner = QLabel()
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.setOpenExternalLinks(True)
        self.banner.setTextFormat(Qt.RichText)
        self.banner.hide()
        root.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_installs(), "INSTALACIONES")
        self.tabs.addTab(self._tab_auto(), "ACTUALIZACIONES")
        self.tabs.addTab(self._tab_history(), "HISTORIAL")
        root.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self.progress = QProgressBar()
        self.progress.setMaximumWidth(260)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        QTimer.singleShot(50, self.refresh)

    def showEvent(self, ev):
        super().showEvent(ev)
        dark_titlebar(self)

    # ----------------------------------------------------------- pestañas
    def _tab_installs(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 14, 10, 10)
        self.tree = QTreeWidget()
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self.open_folder())
        inner = QVBoxLayout()
        inner.addWidget(self.tree)
        lay.addWidget(_framed("Instalaciones de Star Citizen", inner), 1)
        row = QHBoxLayout()
        self.btn_install = QPushButton("Instalar / actualizar…")
        self.btn_install.setObjectName("Primary")
        self.btn_install.clicked.connect(self.install_selected)
        self.btn_repair = QPushButton("Reparar")
        self.btn_repair.setToolTip("Vuelve a instalar la versión publicada, la pantalla de carga y comprueba user.cfg")
        self.btn_repair.clicked.connect(self.repair_selected)
        self.btn_restore = QPushButton("Restaurar copia…")
        self.btn_restore.clicked.connect(self.restore_selected)
        self.btn_uninstall = QPushButton("Desinstalar traducción")
        self.btn_uninstall.setObjectName("Danger")
        self.btn_uninstall.clicked.connect(self.uninstall_selected)
        self.btn_add = QPushButton("Añadir carpeta…")
        self.btn_add.clicked.connect(self.add_folder)
        for b in (self.btn_install, self.btn_repair, self.btn_restore, self.btn_uninstall):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_add)
        lay.addLayout(row)
        self.attention = QLabel()
        self.attention.setObjectName("Warning")
        self.attention.setWordWrap(True)
        self.attention.hide()
        lay.addWidget(self.attention)
        return w

    def _tab_auto(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 14, 10, 10)
        inner = QVBoxLayout()
        inner.setSpacing(10)
        self.chk_auto = QCheckBox("Activar actualizaciones automáticas")
        inner.addWidget(self.chk_auto)
        desc = QLabel("Se comprueba GitHub <b>al abrir el RSI Launcher</b> y <b>al cerrar Star Citizen</b>, en "
                      "segundo plano y sin molestar. Solo verás un aviso cuando haya una actualización. "
                      "Nunca se cambia nada con el juego abierto ni mientras el launcher está parcheando.")
        desc.setWordWrap(True)
        desc.setObjectName("Subtitle")
        desc.setTextFormat(Qt.RichText)
        inner.addWidget(desc)
        grid = QGridLayout()
        grid.setVerticalSpacing(10)
        self.rb_silent = QRadioButton("Instalar las actualizaciones automáticamente y avisarme")
        self.rb_notify = QRadioButton("Solo avisarme cuando haya una actualización")
        grp = QButtonGroup(w)
        grp.addButton(self.rb_silent)
        grp.addButton(self.rb_notify)
        grid.addWidget(self.rb_silent, 0, 0, 1, 2)
        grid.addWidget(self.rb_notify, 1, 0, 1, 2)
        grid.addWidget(QLabel("Canal de publicaciones:"), 2, 0)
        self.cb_channel = QComboBox()
        self.cb_channel.addItem("Estable (recomendado)", "stable")
        self.cb_channel.addItem("Beta — versiones de prueba", "beta")
        grid.addWidget(self.cb_channel, 2, 1)
        grid.setColumnStretch(2, 1)
        inner.addLayout(grid)
        lay.addWidget(_framed("Actualizaciones automáticas", inner))

        inner2 = QVBoxLayout()
        self.chk_splash = QCheckBox("Pantalla de carga de Easy Anti-Cheat de la traducción "
                                    "(azul en LIVE, violeta en PTU)")
        inner2.addWidget(self.chk_splash)
        d2 = QLabel("Indica al arrancar el juego que la traducción está instalada. Si un parche del juego la "
                    "devuelve a la original, se vuelve a poner sola. Al desactivarla se restaura la original.")
        d2.setWordWrap(True)
        d2.setObjectName("Subtitle")
        inner2.addWidget(d2)
        lay.addWidget(_framed("Apariencia", inner2))

        row = QHBoxLayout()
        b = QPushButton("Guardar ajustes")
        b.setObjectName("Primary")
        b.clicked.connect(self.save_settings)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.lbl_task = QLabel()
        self.lbl_task.setWordWrap(True)
        self.lbl_task.setTextFormat(Qt.RichText)
        lay.addWidget(self.lbl_task)
        lay.addStretch(1)
        self.chk_auto.toggled.connect(self._auto_toggled)
        return w

    def _tab_history(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 14, 10, 10)
        self.hist = QTreeWidget()
        self.hist.setHeaderLabels(["FECHA", "CANAL", "ACCIÓN", "VERSIÓN", "RESULTADO", "DETALLE"])
        self.hist.setRootIsDecorated(False)
        self.hist.setAlternatingRowColors(True)
        i1 = QVBoxLayout()
        i1.addWidget(self.hist)
        lay.addWidget(_framed("Historial de actualizaciones", i1), 2)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        i2 = QVBoxLayout()
        i2.addWidget(self.notes)
        lay.addWidget(_framed("Notas de la última versión", i2), 1)
        row = QHBoxLayout()
        b = QPushButton("Abrir carpeta de registros")
        b.clicked.connect(lambda: self._open_path(self.service.data_dir / "logs"))
        row.addWidget(b)
        b2 = QPushButton("Ver publicaciones en GitHub")
        b2.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.service.cfg.releases_url)))
        row.addWidget(b2)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    # ------------------------------------------------------------ utilidades
    def _set_busy(self, busy: bool, text: str = ""):
        self.busy = busy
        self.btn_check.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        if text:
            self.statusBar().showMessage(text)
        self._update_buttons()

    def _open_path(self, p: Path):
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _selected(self) -> list[InstallStatus]:
        if not self.result:
            return []
        keys = {it.data(0, Qt.UserRole) for it in self.tree.selectedItems() if it.data(0, Qt.UserRole)}
        return [st for st in self.result.statuses if st.install.key in keys]

    def _update_buttons(self):
        sel = self._selected()
        has_manifest = bool(self.result and self.result.manifest)
        idle = not self.busy
        self.btn_install.setEnabled(idle and has_manifest)
        self.btn_repair.setEnabled(idle and has_manifest and bool(sel) and all(st.entry for st in sel))
        self.btn_restore.setEnabled(idle and len(sel) == 1)
        self.btn_uninstall.setEnabled(idle and bool(sel) and any(st.record for st in sel))
        self.btn_add.setEnabled(idle)

    # ------------------------------------------------------------ refrescar
    def refresh(self):
        if self.busy:
            return
        self._set_busy(True, "Conectando con GitHub…")
        Task(self, lambda w: self.service.check(), on_done=self._show_result, on_error=self._check_failed).start()

    def _check_failed(self, exc):
        self._set_busy(False)
        show_error(self, "Buscar actualizaciones", exc)

    def _show_result(self, res: CheckResult):
        self._set_busy(False)
        self.result = res
        selected = {it.data(0, Qt.UserRole) for it in self.tree.selectedItems()}
        fill_status_tree(self.tree, self.service.channel_rows(res.statuses, m := res.manifest))
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.UserRole) in selected:
                it.setSelected(True)
        if not selected and self.tree.topLevelItemCount() and self.tree.topLevelItem(0).data(0, Qt.UserRole):
            self.tree.topLevelItem(0).setSelected(True)
        parts = [f"Gestor {__version__}"]
        if m:
            parts.append(f"Traducción publicada {m.version} ({(m.published_at or '')[:10]})")
        parts.append("Comprobado " + res.checked_at.replace("T", " ").replace("Z", " UTC"))
        self.sub.setText("  ·  ".join(parts))
        banners = []
        if res.error:
            pre = "Sin conexión con GitHub" if res.offline else "Aviso"
            banners.append(f"⚠ {pre}: {html.escape(res.error)}")
        if compare_app_version(res.app_release, __version__):
            banners.append(f"Hay una nueva versión del gestor ({res.app_release.version}). "
                           f"<a href='{res.app_release.html_url}' style='color:#38d6ff'>Descárgala aquí</a>.")
        n_up = sum(1 for st in res.statuses if st.state in (ST_UPDATE, ST_MISSING))
        if n_up:
            banners.append(f"Hay {n_up} instalación(es) con actualización o reparación pendiente. "
                           "Pulsa «Instalar / actualizar…».")
        if not res.statuses:
            banners.append("No se ha encontrado Star Citizen. Pulsa «Añadir carpeta…» y elige dónde está instalado.")
        self.banner.setText("<br>".join(banners))
        self.banner.setVisible(bool(banners))
        att = [f"{st.install.channel}: {st.record['attention']}" for st in res.statuses
               if st.record and st.record.get("attention")]
        self.attention.setText("⚠ " + "<br>⚠ ".join(html.escape(a) for a in att) if att else "")
        self.attention.setVisible(bool(att))
        notes = (res.release.body if res.release and res.release.body else (m.notes if m else "")) or "Sin notas."
        self.notes.setMarkdown(notes)
        self._load_settings()
        self._load_history()
        self._update_buttons()
        self.statusBar().showMessage("Comprobación terminada.", 5000)

    def _load_history(self):
        self.hist.clear()
        for h in self.service.history():
            it = QTreeWidgetItem([
                h.get("time", "").replace("T", " ").replace("Z", ""), h.get("channel", ""),
                ACTION_NAMES.get(h.get("action"), h.get("action", "")), h.get("version") or "—",
                "Correcto" if h.get("result") == "ok" else "Error", h.get("detail", ""),
            ])
            it.setToolTip(5, f"{h.get('path', '')}\n{h.get('detail', '')}")
            self.hist.addTopLevelItem(it)
        for c in range(5):
            self.hist.resizeColumnToContents(c)

    def _load_settings(self):
        s = self.service.store.settings()
        self.chk_auto.setChecked(bool(s.get("auto_update")))
        (self.rb_silent if s.get("mode", "silent") == "silent" else self.rb_notify).setChecked(True)
        self.cb_channel.setCurrentIndex(1 if s.get("release_channel") == "beta" else 0)
        self.chk_splash.setChecked(bool(s.get("splash", True)))
        self._auto_toggled(self.chk_auto.isChecked())
        if s.get("auto_update") and s.get("task_registered"):
            txt = "<span style='color:#3dffb0'>●</span> Vigilante activo: se inicia con Windows."
            if s.get("task_error"):
                txt += f"<br>⚠ {html.escape(s['task_error'])}"
        elif s.get("auto_update"):
            txt = "⚠ Las actualizaciones están activadas pero la tarea no está creada. Pulsa «Guardar ajustes»."
            if s.get("task_error"):
                txt += f"<br>{html.escape(s['task_error'])}"
        else:
            txt = "<span style='color:#6fa3b8'>●</span> Actualizaciones automáticas desactivadas."
        lc = self.service.store.snapshot().get("last_check")
        if lc:
            origin = ORIGINS.get(lc.get("origin", "manual"), lc.get("origin", ""))
            txt += (f"<br>Última comprobación: {lc.get('time', '').replace('T', ' ').replace('Z', ' UTC')}"
                    f" ({origin})")
        self.lbl_task.setText(txt)

    def _auto_toggled(self, on: bool):
        for w in (self.rb_silent, self.rb_notify):
            w.setEnabled(on)

    def save_settings(self):
        enabled = self.chk_auto.isChecked()
        splash = self.chk_splash.isChecked()
        channel = self.cb_channel.currentData()
        if channel == "beta" and self.service.store.settings().get("release_channel") != "beta":
            if QMessageBox.question(self, "Canal beta",
                                    "Las versiones beta son traducciones en pruebas y pueden tener errores. "
                                    "¿Quieres recibirlas?") != QMessageBox.Yes:
                self.cb_channel.setCurrentIndex(0)
                channel = "stable"
        self.service.store.update_settings(mode="silent" if self.rb_silent.isChecked() else "notify",
                                           release_channel=channel)
        splash_changed = splash != bool(self.service.store.settings().get("splash", True))
        self._set_busy(True, "Guardando ajustes…")

        def job(w):
            warn = scheduler.apply_settings(self.service, enabled)
            notes = self.service.set_splash(splash) if splash_changed else []
            return warn, notes

        def done(payload):
            warn, notes = payload
            self._set_busy(False)
            msgs = [m for m in [warn, *notes] if m]
            if msgs:
                QMessageBox.warning(self, "Ajustes", "\n".join(msgs))
            else:
                self.statusBar().showMessage("Ajustes guardados.", 5000)
            if splash_changed and splash:
                # Volver a poner la pantalla de carga en las instalaciones gestionadas.
                self.refresh()
            else:
                self._load_settings()

        Task(self, job, on_done=done,
             on_error=lambda e: (self._set_busy(False), show_error(self, "Ajustes", e), self._load_settings())).start()

    # ------------------------------------------------------------- acciones
    def _run_wizard(self, preselect: set[str] | None, action: str, touch_user_cfg: bool = True):
        wiz = InstallWizard(self.service, self.result, preselect=preselect, action=action,
                            touch_user_cfg=touch_user_cfg, parent=self)
        wiz.exec()
        self.refresh()

    def install_selected(self):
        sel = self._selected()
        keys = {st.install.key for st in sel if st.entry} or None
        self._run_wizard(keys, "actualizar" if sel and all(st.installed_version for st in sel) else "instalar")

    def repair_selected(self):
        sel = self._selected()
        if not sel:
            return
        self._run_wizard({st.install.key for st in sel}, "reparar")

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Elige la carpeta de Star Citizen")
        if not d:
            return
        if not self.service.add_custom_path(d):
            QMessageBox.warning(self, "Carpeta no válida",
                                "Esa carpeta no parece una instalación de Star Citizen.\n\nElige la carpeta "
                                "«StarCitizen» o la de un canal (LIVE, PTU…).")
            return
        self.refresh()

    def open_folder(self):
        sel = self._selected()
        if sel:
            self._open_path(Path(sel[0].install.path))

    def restore_selected(self):
        sel = self._selected()
        if len(sel) != 1:
            return
        gi = sel[0].install
        backups = self.service.installer.list_backups(gi)
        if not backups:
            QMessageBox.information(self, "Restaurar", "No hay copias de seguridad para esta instalación.")
            return
        dlg = RestoreDialog(self, backups)
        if dlg.exec() != QDialog.Accepted or not dlg.selected_id():
            return
        bid = dlg.selected_id()
        self._do(lambda w: self.service.installer.restore(gi, bid), "Restaurando copia…",
                 {"op": "restore", "paths": [gi.path], "backup_id": bid}, "Copia restaurada.")

    def uninstall_selected(self):
        sel = [st for st in self._selected() if st.record]
        if not sel:
            return
        names = ", ".join(st.install.channel for st in sel)
        if QMessageBox.question(self, "Desinstalar traducción",
                                f"Se quitará la traducción de: {names}.\n\nEl juego volverá a estar como antes de "
                                "instalarla (textos, pantalla de carga y user.cfg). ¿Continuar?"
                                ) != QMessageBox.Yes:
            return

        def job(w):
            notes = []
            for st in sel:
                notes += self.service.uninstall_one(st.install)
            return notes
        self._do(job, "Desinstalando…", {"op": "uninstall", "paths": [st.install.path for st in sel]},
                 "Traducción desinstalada.")

    def _do(self, fn, text: str, elevated_op: dict, ok_text: str):
        self._set_busy(True, text)

        def done(notes):
            self._set_busy(False)
            if notes:
                QMessageBox.information(self, "Aviso", "\n".join(notes))
            self.statusBar().showMessage(ok_text, 6000)
            self.refresh()

        def failed(exc):
            self._set_busy(False)
            if isinstance(exc, PermissionNeededError):
                out = offer_elevation(self, self.service, elevated_op)
                if out is not None:
                    ok, errors = out
                    if errors:
                        QMessageBox.warning(self, "Resultado", "\n".join(f"{k}: {v}" for k, v in errors.items()))
                    else:
                        self.statusBar().showMessage(ok_text, 6000)
                self.refresh()
                return
            show_error(self, "Operación no completada", exc)
            self.refresh()

        Task(self, fn, on_done=done, on_error=failed).start()

    def closeEvent(self, ev):
        if self.busy:
            QMessageBox.information(self, "Operación en curso", "Espera a que termine la operación actual.")
            ev.ignore()
            return
        super().closeEvent(ev)
