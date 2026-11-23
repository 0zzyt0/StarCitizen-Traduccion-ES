"""Prueba de humo de la ventana única (sin pantalla)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SCTRAD_NO_ANIM", "1")
pytest.importorskip("PySide6")

from conftest import FakeClient, FakeHttp, build_release, ini_bytes, make_game  # noqa: E402
from sctrad.gamepaths import detect_installs  # noqa: E402
from sctrad.service import UpdateService  # noqa: E402


def _wait(ms=200):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _until(cond, tries=60):
    for _ in range(tries):
        _wait(100)
        if cond():
            return True
    return False


def test_simple_window_update_and_uninstall(tmp_path, cfg, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from sctrad import scheduler
    from sctrad.gui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    monkeypatch.setattr(scheduler, "apply_settings",
                        lambda svc, en, h=24: svc.store.update_settings(auto_update=en, task_registered=en))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    live = make_game(tmp_path / "game", "LIVE", user_cfg=b"r_DisplayInfo = 2\r\n")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes(), "PTU": ini_bytes("B=1\r\n")})
    svc = UpdateService(cfg, data_dir=tmp_path / "data", http=FakeHttp(routes), client=FakeClient(rel, small),
                        game_running=lambda: False,
                        detector=lambda: detect_installs(cfg, extra_roots=[tmp_path / "game" / "StarCitizen"]))
    from sctrad.gui.simple import SimpleWindow
    w = SimpleWindow(svc)
    w.show()
    assert _until(lambda: w.result is not None and not w.busy)
    assert "3dffb0" in w.btn_update.styleSheet()          # verde: hay algo que instalar
    assert svc.store.settings()["task_registered"]        # vigilante activado al abrir
    w.on_update()
    assert _until(lambda: not w.busy and w.result and not any(s.needs_action for s in w.result.statuses))
    g = live / "data/Localization/spanish_(spain)/global.ini"
    assert g.read_bytes() == ini_bytes()
    assert "ffc06b" in w.btn_update.styleSheet()          # naranja: al día
    assert w.btn_uninstall.isEnabled()
    w.on_uninstall()
    assert _until(lambda: not w.busy and not g.exists())
    from sctrad.usercfg import get_setting
    assert get_setting((live / "user.cfg").read_bytes(), "g_language") is None  # inglés
    w.close()


def test_temporary_channel_prompt_and_switch(tmp_path, cfg, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox
    from sctrad import scheduler
    from sctrad.gui.theme import apply_theme
    from sctrad.gui.simple import HoloSwitch, SimpleWindow

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    monkeypatch.setattr(scheduler, "apply_settings",
                        lambda svc, en, h=24: svc.store.update_settings(auto_update=en, task_registered=en))
    asked = []
    monkeypatch.setattr(SimpleWindow, "ask_channel", lambda self, st: asked.append(st.install.channel) or True)
    make_game(tmp_path / "game", "LIVE")
    eptu = make_game(tmp_path / "game", "EPTU")
    rel, small, routes = build_release(cfg, "2026.11.23.1", {"LIVE": ini_bytes(), "EPTU": ini_bytes("A=E\r\n")})
    svc = UpdateService(cfg, data_dir=tmp_path / "data", http=FakeHttp(routes), client=FakeClient(rel, small),
                        game_running=lambda: False,
                        detector=lambda: detect_installs(cfg, extra_roots=[tmp_path / "game" / "StarCitizen"]))
    w = SimpleWindow(svc)
    w.show()
    g = eptu / "data/Localization/spanish_(spain)/global.ini"
    # Primera vez: pregunta por EPTU y, al decir que sí, lo instala.
    assert _until(lambda: g.exists() and not w.busy and w.result is not None)
    assert asked == ["EPTU"] and svc.channel_enabled("EPTU") is True
    # Canales temporales ausentes en gris (interruptor bloqueado); EPTU con interruptor activo.
    assert not w.frame.findChild(HoloSwitch, "switch_HOTFIX").isEnabled()
    sw = w.frame.findChild(HoloSwitch, "switch_EPTU")
    assert sw.isEnabled() and sw.isChecked()
    # Apagar el interruptor y elegir «Sí» -> se quita la traducción de EPTU y no se vuelve a preguntar.
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    sw.setChecked(False)
    assert _until(lambda: not g.exists() and not w.busy)
    assert svc.channel_enabled("EPTU") is False
    _until(lambda: w.result is not None and not w.busy)
    assert asked == ["EPTU"]
    w.close()


def test_notice_panel(tmp_path, cfg, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from sctrad import scheduler
    from sctrad.gui.simple import SimpleWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(scheduler, "apply_settings",
                        lambda svc, en, h=24: svc.store.update_settings(auto_update=en, task_registered=en))
    client = FakeClient(notice="[PTU] Trabajando en la versión PTU 5.0\n".encode())
    svc = UpdateService(cfg, data_dir=tmp_path / "data", http=FakeHttp({}), client=client,
                        game_running=lambda: False, detector=lambda: [])
    w = SimpleWindow(svc)
    w.show()
    assert _until(lambda: w.ticker.isVisible())
    assert w.notice_lines[0].channel == "PTU"
    client.notice_bytes = b"# sin aviso\n"
    w.refresh_notice()
    assert _until(lambda: not w.ticker.isVisible())
    _until(lambda: not w.busy)
    w.close()
