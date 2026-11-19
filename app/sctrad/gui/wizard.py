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
from .common import JobResult, fill_status_tree, install_job, offer_elevation
from .theme import app_icon
from .workers import Task

P_WELCOME, P_INSTALLS, P_SUMMARY, P_PROGRESS, P_FINISH = range(5)


def _title(text: str, sub: str | None = None) -> list[QLabel]:
    t = QLabel(text)
    t.setObjectName("Title")
    out = [t]
    if sub:
        s = QLabel(sub)
        s.setObjectName("Subtitle")
        s.setWordWrap(True)
        out.append(s)
    return out


class WelcomePage(QWizardPage):
    def __init__(self, wiz: "InstallWizard"):
        super().__init__()
        self.wiz = wiz
        lay = QVBoxLayout(self)
        for w in _title("Traducción al español de Star Citizen", f"Gestor de la traducción · versión {__version__}"):
            lay.addWidget(w)
        cfg = wiz.service.cfg
        intro = QLabel(
            "Este asistente instala la traducción al español del juego y la mantiene actualizada.<br><br>"
            "<b>Qué hará:</b><ul>"
            f"<li>Copiar el archivo de textos en español en <code>data\\Localization\\{cfg.language_folder}</code> "
            "de la instalación de Star Citizen que elijas.</li>"
            f"<li>Añadir <code>g_language = {cfg.user_cfg_settings.get('g_language')}</code> a <code>user.cfg</code> "
            "sin tocar tus otros ajustes.</li>"
            "<li>Guardar una copia de seguridad antes de cambiar nada, para poder volver atrás.</li>"
            "<li>Si lo activas, buscar e instalar solo las nuevas versiones que se publiquen.</li></ul>"
            f"Origen de la traducción: <a href='{cfg.repo_url}'>{cfg.repo_url}</a><br>"
            "Es un proyecto de la comunidad, no oficial de Cloud Imperium Games."
        )
        intro.setWordWrap(True)
        intro.setOpenExternalLinks(True)
        intro.setTextFormat(Qt.RichText)
        lay.addWidget(intro)
        lay.addStretch(1)
        self.status = QLabel("Consultando la última traducción publicada en GitHub…")
        self.status.setObjectName("Banner")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch(1)
        self.retry = QPushButton("Reintentar")
        self.retry.clicked.connect(self.start_check)
        self.retry.hide()
        row.addWidget(self.retry)
        lay.addLayout(row)
        self._busy = False

    def initializePage(self):
        if self.wiz.result is None:
            self.start_check()
        else:
            self.show_result(self.wiz.result)

    def start_check(self):
        if self._busy:
            return
        self._busy = True
        self.retry.hide()
        self.status.setObjectName("Banner")
        self.status.setStyleSheet("")
        self.status.setText("Consultando la última traducción publicada en GitHub…")
        Task(self, lambda w: self.wiz.service.check(), on_done=self.show_result, on_error=self.on_error).start()

    def on_error(self, exc):
        self._busy = False
        self.status.setObjectName("Error")
        self.status.setStyleSheet("background:#450a0a;border:1px solid #f87171;border-radius:6px;padding:8px;")
        self.status.setText(f"No se pudo consultar GitHub: {exc}")
        self.retry.show()
        self.completeChanged.emit()

    def show_result(self, res: CheckResult):
        self._busy = False
        self.wiz.result = res
        if res.manifest:
            extra = " (sin conexión: datos de la última consulta)" if res.offline else ""
            fecha = (res.manifest.published_at or "")[:10]
            firma = "firma verificada ✔" if res.manifest.signature_status == "firmado" else "sin firma"
            canales = ", ".join(res.manifest.channels)
            self.status.setText(f"Traducción disponible: <b>{res.manifest.version}</b> · publicada {fecha} · "
                                f"{firma} · canales: {canales}{extra}")
        else:
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
        for w in _title("Elige dónde instalarla",
                        "Marca las instalaciones de Star Citizen que quieres traducir. "
                        "Solo se modificarán las que marques."):
            lay.addWidget(w)
        self.tree = QTreeWidget()
        self.tree.itemChanged.connect(lambda *_: self.completeChanged.emit())
        lay.addWidget(self.tree, 1)
        self.info = QLabel()
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        row = QHBoxLayout()
        b = QPushButton("Examinar…")
        b.setToolTip("Elige la carpeta StarCitizen o la de un canal (LIVE, PTU…)")
        b.clicked.connect(self.browse)
        row.addWidget(b)
        row.addStretch(1)
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
        fill_status_tree(self.tree, res.statuses, checkable=True, checked_keys=pre)
        if not res.statuses:
            self.info.setText("No se ha encontrado Star Citizen automáticamente. Pulsa «Examinar…» y elige la "
                              "carpeta donde está instalado (por ejemplo …\\Roberts Space Industries\\StarCitizen).")
        else:
            self.info.setText("Consejo: pasa el ratón por encima de una fila para ver más detalles.")
        self.completeChanged.emit()

    def checked(self) -> list[InstallStatus]:
        keys = set()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
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
        fill_status_tree(self.tree, res.statuses, checkable=True, checked_keys=checked)
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
        for w in _title("Resumen antes de instalar", "Revisa exactamente qué se va a cambiar."):
            lay.addWidget(w)
        self.text = QTextBrowser()
        lay.addWidget(self.text, 1)
        self.chk_foreign = QCheckBox("Entiendo que se sustituirá la traducción existente (se guarda una copia).")
        self.chk_incompat = QCheckBox("Instalar aunque la traducción no esté marcada como compatible con mi versión "
                                      "del juego.")
        for c in (self.chk_foreign, self.chk_incompat):
            c.toggled.connect(lambda *_: self.completeChanged.emit())
            lay.addWidget(c)
        self.chk_auto = QCheckBox("Activar actualizaciones automáticas (al iniciar sesión y cada 24 horas)")
        lay.addWidget(self.chk_auto)
        row = QHBoxLayout()
        row.addWidget(QLabel("Cuando haya una versión nueva:"))
        self.mode = QComboBox()
        self.mode.addItem("Instalarla automáticamente y avisarme", "silent")
        self.mode.addItem("Solo avisarme", "notify")
        row.addWidget(self.mode, 1)
        lay.addLayout(row)
        self.chk_auto.toggled.connect(self.mode.setEnabled)

    def initializePage(self):
        svc, res = self.wiz.service, self.wiz.result
        parts = []
        any_foreign = any_incompat = False
        for st in self.wiz.selected:
            gi = st.install
            plan = svc.installer.describe_plan(gi, res.manifest.version, touch_user_cfg=self.wiz.touch_user_cfg)
            comp = st.compat_label
            if st.compat == INCOMPATIBLE:
                any_incompat = True
                comp = (f"⚠ No compatible: la traducción declara {', '.join(st.entry.game_versions)} y tu juego es "
                        f"{gi.game_version}")
            if st.state == ST_FOREIGN:
                any_foreign = True
            items = "".join(f"<li>{html.escape(p).replace(chr(10), '<br>')}</li>" for p in plan)
            parts.append(f"<h3>{gi.channel}</h3><p style='color:#94a3b8'>{html.escape(gi.path)}<br>"
                         f"Juego: {gi.game_version or 'versión desconocida'} · {html.escape(comp)}</p><ul>{items}</ul>")
        self.text.setHtml("".join(parts))
        self.chk_foreign.setVisible(any_foreign)
        self.chk_foreign.setChecked(False)
        self.chk_incompat.setVisible(any_incompat)
        self.chk_incompat.setChecked(False)
        s = svc.store.settings()
        self.chk_auto.setChecked(bool(s.get("auto_update", True)))
        self.mode.setCurrentIndex(0 if s.get("mode", "silent") == "silent" else 1)
        hours = int(s.get("interval_hours", 24))
        self.chk_auto.setText(f"Activar actualizaciones automáticas (al iniciar sesión y cada {hours} horas)")
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
        return True


class ProgressPage(QWizardPage):
    def __init__(self, wiz: "InstallWizard"):
        super().__init__()
        self.wiz = wiz
        lay = QVBoxLayout(self)
        for w in _title("Instalando", "No cierres esta ventana."):
            lay.addWidget(w)
        self.current = QLabel("Preparando…")
        lay.addWidget(self.current)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(self.log, 1)
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
        self.current.setText(s)

    def on_bytes(self, done: int, total: int):
        self.bar.setRange(0, 1000)
        self.bar.setValue(int(done * 1000 / max(total, 1)))
        self.bar.setFormat(f"{done / 1048576:.1f} de {total / 1048576:.1f} MB")

    def run(self):
        self.done = False
        self.btn_retry.hide()
        self.btn_admin.hide()
        self.bar.setRange(0, 0)
        self.completeChanged.emit()
        wiz = self.wiz

        def job(w):
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
        self.bar.setFormat("")
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
        self.head = QLabel()
        self.head.setObjectName("Title")
        lay.addWidget(self.head)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        lay.addWidget(self.body)
        lay.addStretch(1)
        self.chk_open = QCheckBox("Abrir el gestor de la traducción")
        self.chk_open.setChecked(True)
        lay.addWidget(self.chk_open)

    def initializePage(self):
        wiz = self.wiz
        version = wiz.result.manifest.version
        ok = wiz.job_ok
        if ok and not wiz.job_errors:
            self.head.setText("¡Traducción instalada!")
        elif ok:
            self.head.setText("Instalación completada en parte")
        else:
            self.head.setText("No se ha podido instalar")
        lines = [f"✔ <b>{st.install.channel}</b>: versión {version}" for st in ok]
        lines += [f"✖ <b>{k}</b>: {html.escape(str(e))}" for k, e in wiz.job_errors.items()]
        s = wiz.service.store.settings()
        if s.get("auto_update") and s.get("task_registered"):
            modo = "se instalarán solas" if s.get("mode") == "silent" else "se te avisará"
            auto = f"Actualizaciones automáticas <b>activadas</b>: cuando se publique una versión nueva, {modo}."
        elif s.get("auto_update"):
            auto = f"⚠ No se pudo programar la comprobación automática: {html.escape(str(s.get('task_error')))}"
        else:
            auto = "Actualizaciones automáticas <b>desactivadas</b>. Puedes activarlas en el gestor."
        tips = ("<br><br>Inicia Star Citizen como siempre: los textos aparecerán en español. "
                "Si alguna vez quieres volver al inglés, usa «Desinstalar traducción» en el gestor.")
        self.body.setText("<br>".join(lines) + "<br><br>" + auto + (tips if ok else ""))
        self.chk_open.setVisible(wiz.first_run)


class InstallWizard(QWizard):
    def __init__(self, service: UpdateService, result: CheckResult | None = None,
                 preselect: set[str] | None = None, action: str = "instalar", first_run: bool = False,
                 touch_user_cfg: bool = True, parent=None):
        super().__init__(parent)
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
        self.job_ok: list[InstallStatus] = []
        self.job_errors: dict[str, SCTradError] = {}
        self.sched_warning: str | None = None
        self.setWindowTitle("Instalar la traducción al español de Star Citizen")
        self.setWindowIcon(app_icon())
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnLastPage, True)
        self.setOption(QWizard.NoCancelButtonOnLastPage, True)
        self.setButtonText(QWizard.NextButton, "Siguiente >")
        self.setButtonText(QWizard.BackButton, "< Atrás")
        self.setButtonText(QWizard.FinishButton, "Finalizar")
        self.setButtonText(QWizard.CancelButton, "Cancelar")
        self.setButtonText(QWizard.CommitButton, "Instalar")
        self.setPage(P_WELCOME, WelcomePage(self))
        self.setPage(P_INSTALLS, InstallsPage(self))
        self.setPage(P_SUMMARY, SummaryPage(self))
        self.setPage(P_PROGRESS, ProgressPage(self))
        self.setPage(P_FINISH, FinishPage(self))
        if result is not None and result.manifest and not first_run:
            self.setStartId(P_INSTALLS)
        self.resize(860, 620)

    @property
    def open_manager(self) -> bool:
        return self.page(P_FINISH).chk_open.isChecked() and self.first_run

    def reject(self):
        prog = self.page(P_PROGRESS)
        if self.currentId() == P_PROGRESS and not prog.done:
            QMessageBox.information(self, "Instalación en curso", "Espera a que termine la instalación.")
            return
        super().reject()
