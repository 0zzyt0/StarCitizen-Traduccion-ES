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
