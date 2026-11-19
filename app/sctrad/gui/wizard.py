"""Asistente de instalación de la traducción (primera ejecución, instalar y actualizar)."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QTextBrowser, QTreeWidget,
                               QVBoxLayout, QWizard, QWizardPage)

from .. import __version__, scheduler
from ..errors import SCTradError
from ..gamepaths import INCOMPATIBLE, install_key
from ..service import ST_FOREIGN, ST_UP_TO_DATE, CheckResult, InstallStatus, UpdateService
from .common import JobResult, fill_status_tree, heading, install_job, offer_elevation
from .holo import AnimatedBackdropMixin, HoloFrame, HoloLogo, dark_titlebar, glow
from .theme import app_icon
from .workers import Task

P_WELCOME, P_INSTALLS, P_SUMMARY, P_PROGRESS, P_FINISH = range(5)
AUTO_TEXT = "Activar actualizaciones automáticas (se comprueba al abrir el RSI Launcher y al cerrar el juego)"
SPLASH_TEXT = ("Cambiar la pantalla de carga de Easy Anti-Cheat (azul en LIVE, violeta en PTU) "
               "para ver al arrancar que la traducción está instalada")


def _framed(title: str, *widgets, stretch: int | None = None) -> HoloFrame:
    f = HoloFrame(title=title)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 24, 16, 14)
    for w in widgets:
        lay.addWidget(w, stretch or 0)
    return f


class WelcomePage(QWizardPage):
    def __init__(self, wiz: "InstallWizard"):
        super().__init__()
        self.wiz = wiz
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(HoloLogo(230), 0, Qt.AlignTop)
        right = QVBoxLayout()
        right.addWidget(heading("Traducción al español", f"Star Citizen · Gestor de la traducción {__version__}",
                                kicker="Proyecto de la comunidad"))
        cfg = wiz.service.cfg
        intro = QLabel(
            "Este asistente instala la traducción al español del juego y la mantiene al día.<ul>"
            f"<li>Copia los textos en español en <b>data\\Localization\\{cfg.language_folder}</b>.</li>"
            f"<li>Añade <b>g_language = {cfg.user_cfg_settings.get('g_language')}</b> a <b>user.cfg</b> "
            "sin tocar tus otros ajustes.</li>"
            "<li>Cambia la pantalla de carga de Easy Anti-Cheat para que veas que está instalada.</li>"
            "<li>Guarda una copia de seguridad antes de cambiar nada.</li>"
            "<li>Comprueba si hay versión nueva al abrir el RSI Launcher y al cerrar el juego.</li></ul>"
            f"Origen: <a href='{cfg.repo_url}' style='color:#38d6ff'>{cfg.repo_url}</a><br>"
            "<span style='color:#6fa3b8'>No oficial: sin relación con Cloud Imperium Games.</span>"
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        intro.setTextFormat(Qt.RichText)
        right.addWidget(_framed("Qué hará", intro))
        top.addLayout(right, 1)
        root.addLayout(top)
        root.addStretch(1)
        self.status = QLabel("Conectando con GitHub…")
        self.status.setObjectName("Banner")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        self.retry = QPushButton("Reintentar")
        self.retry.clicked.connect(self.start_check)
        self.retry.hide()
        row.addWidget(self.retry)
        root.addLayout(row)
        self._busy = False

    def initializePage(self):
        if self.wiz.result is None:
            self.start_check()
        else:
            self.show_result(self.wiz.result)

    def _set_kind(self, kind: str):
        self.status.setObjectName(kind)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def start_check(self):
        if self._busy:
            return
        self._busy = True
        self.retry.hide()
        self._set_kind("Banner")
        self.status.setText("Conectando con GitHub…")
        Task(self, lambda w: self.wiz.service.check(), on_done=self.show_result, on_error=self.on_error).start()

    def on_error(self, exc):
        self._busy = False
        self._set_kind("Error")
        self.status.setText(f"No se pudo consultar GitHub: {exc}")
        self.retry.show()
        self.completeChanged.emit()

    def show_result(self, res: CheckResult):
        self._busy = False
        self.wiz.result = res
        if res.manifest:
            self._set_kind("Banner")
            extra = " (sin conexión: datos de la última consulta)" if res.offline else ""
            fecha = (res.manifest.published_at or "")[:10]
            firma = "firma verificada ✔" if res.manifest.signature_status == "firmado" else "sin firma"
            canales = " · ".join(res.manifest.channels)
            self.status.setText(f"TRADUCCIÓN DISPONIBLE <b>{res.manifest.version}</b> — publicada {fecha} — "
                                f"{firma} — canales {canales}{extra}")
        else:
            self._set_kind("Warning")
            self.status.setText(f"⚠ {html.escape(res.error or 'No hay traducción disponible.')}")
            self.retry.show()
        self.completeChanged.emit()

    def isComplete(self):
        return bool(self.wiz.result and self.wiz.result.manifest)


class InstallsPage(QWizardPage):
    def __init__(self, wiz: "InstallWizard"):
        super().__init__()
        self.wiz = wiz
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Elige dónde instalarla",
                              "Marca las instalaciones de Star Citizen que quieres traducir. "
                              "Solo se modificarán las que marques.", kicker="Paso 1 de 3"))
        self.tree = QTreeWidget()
        self.tree.itemChanged.connect(lambda *_: self.completeChanged.emit())
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("Subtitle")
        b = QPushButton("Examinar…")
        b.setToolTip("Elige la carpeta StarCitizen o la de un canal (LIVE, PTU…)")
        b.clicked.connect(self.browse)
        frame = _framed("Instalaciones detectadas", self.tree)
        lay.addWidget(frame, 1)
        row = QHBoxLayout()
        row.addWidget(self.info, 1)
        row.addWidget(b)
        lay.addLayout(row)

    def initializePage(self):
        res = self.wiz.result
        pre = self.wiz.preselect
        if pre is None:
            pre = {st.install.key for st in res.statuses
                   if st.entry and st.state != ST_UP_TO_DATE and (st.install.channel == "LIVE" or st.managed)}
            if not pre:
                first = next((st for st in res.statuses if st.entry), None)
                pre = {first.install.key} if first else set()
        fill_status_tree(self.tree, self.wiz.service.channel_rows(res.statuses, res.manifest), checkable=True,
                         checked_keys=pre)
        if not res.statuses:
            self.info.setText("No se ha encontrado Star Citizen automáticamente. Pulsa «Examinar…» y elige la "
                              "carpeta donde está instalado (por ejemplo …\\Roberts Space Industries\\StarCitizen).")
        else:
            self.info.setText("Los canales en gris no están instalados en este PC. Pasa el ratón por encima de una "
                              "fila para ver la ruta completa.")
        self.completeChanged.emit()

    def checked(self) -> list[InstallStatus]:
        keys = set()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.data(0, Qt.UserRole) and it.checkState(0) == Qt.Checked:
                keys.add(it.data(0, Qt.UserRole))
        return [st for st in self.wiz.result.statuses if st.install.key in keys]

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "Elige la carpeta de Star Citizen")
        if not d:
            return
        installs = self.wiz.service.add_custom_path(d)
        if not installs:
            QMessageBox.warning(self, "Carpeta no válida",
                                "Esa carpeta no parece una instalación de Star Citizen.\n\n"
                                "Elige la carpeta «StarCitizen» o la de un canal (LIVE, PTU…). Debe contener "
                                "Data.p4k o Bin64\\StarCitizen.exe.")
            return
        res = self.wiz.result
        known = {st.install.key for st in res.statuses}
        checked = {st.install.key for st in self.checked()}
        for gi in installs:
            if gi.key not in known:
                res.statuses.append(self.wiz.service.status_for(gi, res.manifest))
            checked.add(gi.key)
        fill_status_tree(self.tree, self.wiz.service.channel_rows(res.statuses, res.manifest), checkable=True,
                         checked_keys=checked)
        self.info.setText(f"Añadida: {', '.join(g.label for g in installs)}")
        self.completeChanged.emit()

    def isComplete(self):
        return bool(self.checked())

    def validatePage(self):
        self.wiz.selected = self.checked()
        return bool(self.wiz.selected)


class SummaryPage(QWizardPage):
    def __init__(self, wiz: "InstallWizard"):
        super().__init__()
        self.wiz = wiz
        self.setCommitPage(True)
        self.setButtonText(QWizard.CommitButton, "Instalar")
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Resumen", "Revisa exactamente qué se va a cambiar.", kicker="Paso 2 de 3"))
        self.text = QTextBrowser()
        lay.addWidget(_framed("Cambios previstos", self.text), 1)
        self.chk_foreign = QCheckBox("Entiendo que se sustituirá la traducción existente (se guarda una copia).")
        self.chk_incompat = QCheckBox("Instalar aunque la traducción no esté marcada como compatible con mi versión "
                                      "del juego.")
        for c in (self.chk_foreign, self.chk_incompat):
            c.toggled.connect(lambda *_: self.completeChanged.emit())
            lay.addWidget(c)
        self.chk_splash = QCheckBox(SPLASH_TEXT)
        self.chk_splash.toggled.connect(lambda *_: self._render_plan())
        lay.addWidget(self.chk_splash)
        self.chk_auto = QCheckBox(AUTO_TEXT)
        lay.addWidget(self.chk_auto)
        row = QHBoxLayout()
        row.addWidget(QLabel("Cuando haya una versión nueva:"))
        self.mode = QComboBox()
        self.mode.addItem("Instalarla automáticamente y avisarme", "silent")
        self.mode.addItem("Solo avisarme", "notify")
        row.addWidget(self.mode, 1)
        lay.addLayout(row)
        self.chk_auto.toggled.connect(self.mode.setEnabled)

    def _render_plan(self):
        svc, res = self.wiz.service, self.wiz.result
        parts = []
        for st in self.wiz.selected:
            gi = st.install
            plan = svc.installer.describe_plan(gi, res.manifest.version, touch_user_cfg=self.wiz.touch_user_cfg,
                                               expected_sha=st.entry.sha256 if st.entry else None,
                                               entry=st.entry, with_extras=self.chk_splash.isChecked())
            comp = st.compat_label
            if st.compat == INCOMPATIBLE:
                comp = (f"⚠ No compatible: la traducción declara {', '.join(st.entry.game_versions)} y tu juego es "
                        f"{gi.game_version}")
            color = "#b47bff" if gi.channel == "PTU" else "#38d6ff"
            items = "".join(f"<li style='margin-bottom:4px'>{html.escape(p).replace(chr(10), '<br>')}</li>"
                            for p in plan)
            parts.append(f"<p style='font-family:Orbitron;font-size:12pt;color:{color};margin:4px 0'>▸ {gi.channel}</p>"
                         f"<p style='color:#6fa3b8;margin:0'>{html.escape(gi.path)}<br>"
                         f"Juego: {gi.game_version or 'versión desconocida'} · {html.escape(comp)}</p><ul>{items}</ul>")
        self.text.setHtml("".join(parts))

    def initializePage(self):
        any_foreign = any(st.state == ST_FOREIGN for st in self.wiz.selected)
        any_incompat = any(st.compat == INCOMPATIBLE for st in self.wiz.selected)
        any_extras = any(st.entry and st.entry.extras for st in self.wiz.selected)
        s = self.wiz.service.store.settings()
        self.chk_splash.setVisible(bool(any_extras))
        self.chk_splash.setChecked(bool(s.get("splash", True)))
        self._render_plan()
        self.chk_foreign.setVisible(any_foreign)
        self.chk_foreign.setChecked(False)
        self.chk_incompat.setVisible(any_incompat)
        self.chk_incompat.setChecked(False)
        self.chk_auto.setChecked(bool(s.get("auto_update", True)))
        self.mode.setCurrentIndex(0 if s.get("mode", "silent") == "silent" else 1)
        self.completeChanged.emit()

    def isComplete(self):
        if self.chk_foreign.isVisible() and not self.chk_foreign.isChecked():
            return False
        if self.chk_incompat.isVisible() and not self.chk_incompat.isChecked():
            return False
        return True

    def validatePage(self):
        self.wiz.allow_foreign = self.chk_foreign.isVisible() and self.chk_foreign.isChecked()
        self.wiz.allow_incompat = self.chk_incompat.isVisible() and self.chk_incompat.isChecked()
        self.wiz.auto_update = self.chk_auto.isChecked()
        self.wiz.mode = self.mode.currentData()
        self.wiz.splash = self.chk_splash.isChecked() if self.chk_splash.isVisible() else None
        return True


class ProgressPage(QWizardPage):
    def __init__(self, wiz: "InstallWizard"):
        super().__init__()
        self.wiz = wiz
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Instalando", "No cierres esta ventana.", kicker="Paso 3 de 3"))
        self.current = QLabel("Preparando…")
        self.current.setObjectName("Kicker")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        frame = HoloFrame(title="Registro")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(16, 24, 16, 14)
        fl.addWidget(self.current)
        fl.addWidget(self.bar)
        fl.addWidget(self.log, 1)
        lay.addWidget(frame, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btn_retry = QPushButton("Reintentar")
        self.btn_retry.clicked.connect(self.retry)
        self.btn_admin = QPushButton("Reintentar como administrador")
        self.btn_admin.clicked.connect(self.retry_admin)
        for b in (self.btn_retry, self.btn_admin):
            b.hide()
            row.addWidget(b)
        lay.addLayout(row)
        self.done = False
        self.pending: list[InstallStatus] = []

    def initializePage(self):
        self.pending = list(self.wiz.selected)
        self.run()

    def append(self, s: str):
        self.log.appendPlainText(s)
        self.current.setText(s.upper())

    def on_bytes(self, done: int, total: int):
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(done * 1000 / max(total, 1)))
        self.bar.setFormat(f"{done / 1048576:.1f} / {total / 1048576:.1f} MB")

    def run(self):
        self.done = False
        self.btn_retry.hide()
        self.btn_admin.hide()
        self.bar.setRange(0, 0)
        self.completeChanged.emit()
        wiz = self.wiz

        def job(w):
            if wiz.splash is not None:
                w.text.emit("Aplicando preferencias…")
                wiz.service.set_splash(wiz.splash)
            r = install_job(w, wiz.service, wiz.result, self.pending, wiz.action, wiz.allow_foreign,
                            wiz.allow_incompat, wiz.touch_user_cfg)
            w.text.emit("Configurando las actualizaciones automáticas…")
            warn = scheduler.apply_settings(wiz.service, wiz.auto_update,
                                            int(wiz.service.store.settings().get("interval_hours", 24)))
            wiz.service.store.update_settings(mode=wiz.mode, first_run_done=True)
            return r, warn

        Task(self, job, on_done=self.finished, on_error=self.failed, on_text=self.append,
             on_bytes=self.on_bytes).start()

    def finished(self, payload):
        r, warn = payload
        r: JobResult
        self.wiz.job_ok.extend(st for st in r.ok if st not in self.wiz.job_ok)
        self.wiz.job_errors = r.errors
        self.wiz.sched_warning = warn
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.bar.setFormat("COMPLETADO")
        if warn:
            self.append(f"⚠ {warn}")
        if r.errors:
            self.pending = [st for st in self.pending if st.install.key in r.errors]
            self.append("Algunas instalaciones no se completaron. La traducción anterior se ha mantenido intacta.")
            self.btn_retry.show()
            if r.needs_admin:
                self.btn_admin.show()
        else:
            self.append("Todo listo.")
        self.done = True
        self.completeChanged.emit()

    def failed(self, exc):
        self.append(f"✖ {exc}")
        self.btn_retry.show()
        self.done = True
        self.completeChanged.emit()

    def retry(self):
        self.run()

    def retry_admin(self):
        op = {"op": "install", "paths": [st.install.path for st in self.pending], "action": self.wiz.action,
              "allow_foreign": self.wiz.allow_foreign, "allow_incompatible": self.wiz.allow_incompat,
              "touch_user_cfg": self.wiz.touch_user_cfg}
        out = offer_elevation(self, self.wiz.service, op)
        if out is None:
            return
        ok, errors = out
        for p in ok:
            self.append(f"✔ {p}: instalada con permisos de administrador.")
            key = install_key(p)
            self.wiz.job_errors.pop(key, None)
            self.wiz.job_ok.extend(st for st in self.pending if st.install.key == key)
        for p, e in errors.items():
            self.append(f"✖ {p}: {e}")
        self.pending = [st for st in self.pending if st.install.path in errors]
        if not self.pending:
            self.btn_retry.hide()
            self.btn_admin.hide()

    def isComplete(self):
        return self.done


class FinishPage(QWizardPage):
    def __init__(self, wiz: "InstallWizard"):
        super().__init__()
        self.wiz = wiz
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(HoloLogo(170), 0, Qt.AlignTop)
        right = QVBoxLayout()
        self.kicker = QLabel("ESTADO")
        self.kicker.setObjectName("Kicker")
        self.head = QLabel()
        self.head.setObjectName("Title")
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        right.addWidget(self.kicker)
        right.addWidget(self.head)
        right.addWidget(_framed("Resultado", self.body))
        right.addStretch(1)
        top.addLayout(right, 1)
        lay.addLayout(top, 1)
        self.chk_open = QCheckBox("Abrir el gestor de la traducción")
        self.chk_open.setChecked(True)
        lay.addWidget(self.chk_open)

    def initializePage(self):
        wiz = self.wiz
        version = wiz.result.manifest.version
        ok = wiz.job_ok
        if ok and not wiz.job_errors:
            self.head.setText("TRADUCCIÓN INSTALADA")
        elif ok:
            self.head.setText("INSTALADA EN PARTE")
        else:
            self.head.setText("NO SE HA PODIDO INSTALAR")
        lines = [f"<span style='color:#3dffb0'>✔</span> <b>{st.install.channel}</b>: versión {version}" for st in ok]
        lines += [f"<span style='color:#ff5d6c'>✖</span> <b>{k}</b>: {html.escape(str(e))}"
                  for k, e in wiz.job_errors.items()]
        s = wiz.service.store.settings()
        if s.get("auto_update") and s.get("task_registered"):
            modo = "se instalarán solas y te avisará" if s.get("mode") == "silent" else "te avisará para que las instales"
            auto = ("Actualizaciones automáticas <b>activadas</b>: al abrir el RSI Launcher y al cerrar el juego se "
                    f"comprueba GitHub; si hay una versión nueva, {modo}. Si no hay nada nuevo, no verás nada.")
        elif s.get("auto_update"):
            auto = f"⚠ No se pudo programar la comprobación automática: {html.escape(str(s.get('task_error')))}"
        else:
            auto = "Actualizaciones automáticas <b>desactivadas</b>. Puedes activarlas en el gestor."
        splash = ""
        if ok and s.get("splash", True) and any(st.entry and st.entry.extras for st in ok):
            splash = ("<br><br>Al iniciar Star Citizen verás la pantalla de carga de Easy Anti-Cheat de la "
                      "traducción (azul en LIVE, violeta en PTU): así sabes que está instalada.")
        tips = ("<br><br>Inicia Star Citizen como siempre: los textos aparecerán en español. "
                "Para volver al inglés, usa «Desinstalar traducción» en el gestor.")
        self.body.setText("<br>".join(lines) + "<br><br>" + auto + (splash + tips if ok else ""))
        self.chk_open.setVisible(wiz.first_run)


class InstallWizard(AnimatedBackdropMixin, QWizard):
    def __init__(self, service: UpdateService, result: CheckResult | None = None,
                 preselect: set[str] | None = None, action: str = "instalar", first_run: bool = False,
                 touch_user_cfg: bool = True, parent=None):
        super().__init__(parent)
        self._init_backdrop()
        self.service = service
        self.result = result
        self.preselect = preselect
        self.action = action
        self.first_run = first_run
        self.touch_user_cfg = touch_user_cfg
        self.selected: list[InstallStatus] = []
        self.allow_foreign = self.allow_incompat = False
        self.auto_update = True
        self.mode = "silent"
        self.splash: bool | None = None
        self.job_ok: list[InstallStatus] = []
        self.job_errors: dict[str, SCTradError] = {}
        self.sched_warning: str | None = None
        self.setWindowTitle("Traducción al español de Star Citizen — Instalación")
        self.setWindowIcon(app_icon())
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.NoCancelButtonOnLastPage, True)
        self.setButtonText(QWizard.NextButton, "Siguiente ›")
        self.setButtonText(QWizard.BackButton, "‹ Atrás")
        self.setButtonText(QWizard.FinishButton, "Finalizar")
        self.setButtonText(QWizard.CancelButton, "Cancelar")
        self.setButtonText(QWizard.CommitButton, "Instalar")
        for b in (QWizard.NextButton, QWizard.CommitButton, QWizard.FinishButton):
            btn = self.button(b)
            btn.setObjectName("Primary")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            glow(btn)
        self.setPage(P_WELCOME, WelcomePage(self))
        self.setPage(P_INSTALLS, InstallsPage(self))
        self.setPage(P_SUMMARY, SummaryPage(self))
        self.setPage(P_PROGRESS, ProgressPage(self))
        self.setPage(P_FINISH, FinishPage(self))
        if result is not None and result.manifest and not first_run:
            self.setStartId(P_INSTALLS)
        self.resize(980, 680)

    def paintEvent(self, ev):
        self._paint_backdrop()

    def showEvent(self, ev):
        super().showEvent(ev)
        dark_titlebar(self)

    @property
    def open_manager(self) -> bool:
        return self.page(P_FINISH).chk_open.isChecked() and self.first_run

    def reject(self):
        prog = self.page(P_PROGRESS)
        if self.currentId() == P_PROGRESS and not prog.done:
            QMessageBox.information(self, "Instalación en curso", "Espera a que termine la instalación.")
            return
        super().reject()
