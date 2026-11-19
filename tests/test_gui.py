"""Prueba de humo de la interfaz (sin pantalla)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from conftest import FakeClient, FakeHttp, build_release, ini_bytes, make_game  # noqa: E402
from sctrad.gamepaths import detect_installs  # noqa: E402
from sctrad.service import UpdateService  # noqa: E402


def _wait(ms=400):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def test_wizard_installs_and_manager_opens(tmp_path, cfg, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from sctrad import scheduler
    from sctrad.gui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    monkeypatch.setattr(scheduler, "apply_settings",
                        lambda svc, en, h: svc.store.update_settings(auto_update=en, task_registered=en))
    live = make_game(tmp_path / "game", "LIVE")
    make_game(tmp_path / "game", "PTU", "4.4.0")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes(), "PTU": ini_bytes("B=1\r\n")})
    svc = UpdateService(cfg, data_dir=tmp_path / "data", http=FakeHttp(routes), client=FakeClient(rel, small),
                        game_running=lambda: False,
                        detector=lambda: detect_installs(cfg, extra_roots=[tmp_path / "game" / "StarCitizen"]))
    from sctrad.gui.wizard import InstallWizard
    w = InstallWizard(svc, first_run=True)
    w.show()
    for _ in range(20):
        _wait(100)
        if w.result:
            break
    assert w.result and w.result.manifest
    w.next(); _wait(200)   # instalaciones (LIVE marcada)
    w.next(); _wait(200)   # resumen
    w.next()               # instalar
    for _ in range(50):
        _wait(100)
        if w.currentPage().isComplete():
            break
    assert [s.install.channel for s in w.job_ok] == ["LIVE"]
    assert (live / "data/Localization/spanish_(spain)/global.ini").read_bytes() == ini_bytes()
    assert svc.store.settings()["first_run_done"]
    w.close()

    from sctrad.gui.manager import ManagerWindow
    m = ManagerWindow(svc)
    m.show()
    for _ in range(30):
        _wait(100)
        if m.result:
            break
    assert m.tree.topLevelItemCount() == 5  # LIVE y PTU + EPTU, HOTFIX y TECH-PREVIEW en gris
    from PySide6.QtCore import Qt
    greyed = [m.tree.topLevelItem(i).text(0) for i in range(5) if not m.tree.topLevelItem(i).flags() & Qt.ItemIsEnabled]
    assert greyed == ["EPTU", "HOTFIX", "TECH-PREVIEW"]
    assert m.hist.topLevelItemCount() >= 1
    m.close()
