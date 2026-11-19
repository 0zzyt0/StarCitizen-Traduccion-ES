"""Pantalla de carga de Easy Anti-Cheat como archivo extra de la traducción."""
import json

import pytest

from conftest import FakeClient, FakeHttp, build_release, ini_bytes, make_game
from sctrad.errors import ManifestError
from sctrad.gamepaths import detect_installs
from sctrad.manifest import parse_manifest
from sctrad.service import ST_MISSING, ST_UP_TO_DATE, UpdateService

SPLASH_LIVE = b"\x89PNG-azul-LIVE"


def _svc(tmp_path, cfg, rel, small, routes):
    return UpdateService(cfg, data_dir=tmp_path / "data", http=FakeHttp(routes), client=FakeClient(rel, small),
                         game_running=lambda: False,
                         detector=lambda: detect_installs(cfg, extra_roots=[tmp_path / "game" / "StarCitizen"]))


def _install(svc):
    res = svc.check()
    for st in res.statuses:
        svc.install_one(st, res.release, res.manifest)
    return res


def test_splash_install_repair_and_uninstall(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    splash = live / "EasyAntiCheat" / "SplashScreen.png"
    rel, small, routes = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes()},
                                       extras={"LIVE": {"splash": SPLASH_LIVE}})
    svc = _svc(tmp_path, cfg, rel, small, routes)
    plan = "\n".join(svc.installer.describe_plan(svc.known_installs()[0], "x",
                                                 entry=svc.check().manifest.channels["LIVE"]))
    assert "Easy Anti-Cheat" in plan
    _install(svc)
    assert splash.read_bytes() == SPLASH_LIVE
    assert svc.check().statuses[0].state == ST_UP_TO_DATE
    # Un parche del juego devuelve el splash original -> se detecta y se repara solo.
    splash.write_bytes(b"SPLASH-ORIGINAL-CIG")
    assert svc.check().statuses[0].state == ST_MISSING
    assert svc.run_background() == []  # se repara en silencio
    assert splash.read_bytes() == SPLASH_LIVE
    # Desinstalar devuelve el original.
    svc.uninstall_one(svc.known_installs()[0])
    assert splash.read_bytes() == b"SPLASH-ORIGINAL-CIG"


def test_splash_can_be_disabled(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    splash = live / "EasyAntiCheat" / "SplashScreen.png"
    rel, small, routes = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes()},
                                       extras={"LIVE": {"splash": SPLASH_LIVE}})
    svc = _svc(tmp_path, cfg, rel, small, routes)
    _install(svc)
    svc.set_splash(False)
    assert splash.read_bytes() == b"SPLASH-ORIGINAL-CIG"
    assert svc.check().statuses[0].state == ST_UP_TO_DATE  # no lo marca para reparar
    assert svc.run_background() == []
    assert splash.read_bytes() == b"SPLASH-ORIGINAL-CIG"
    svc.set_splash(True)
    assert svc.check().statuses[0].state == ST_MISSING
    svc.run_background()
    assert splash.read_bytes() == SPLASH_LIVE


def test_splash_not_created_without_eac_folder(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    import shutil
    shutil.rmtree(live / "EasyAntiCheat")
    rel, small, routes = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes()},
                                       extras={"LIVE": {"splash": SPLASH_LIVE}})
    svc = _svc(tmp_path, cfg, rel, small, routes)
    _install(svc)
    assert not (live / "EasyAntiCheat").exists()
    assert svc.check().statuses[0].state == ST_UP_TO_DATE


def test_manifest_rejects_other_extra_targets(cfg):
    rel, small, _ = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes()},
                                  extras={"LIVE": {"splash": SPLASH_LIVE}})
    data = json.loads(small[cfg.manifest_asset])
    data["channels"]["LIVE"]["extras"]["splash"]["target"] = "Bin64/StarCitizen.exe"
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps(data).encode(), cfg)
    data["channels"]["LIVE"]["extras"]["splash"]["target"] = cfg.extra_targets["splash"]
    data["channels"]["LIVE"]["extras"]["splash"]["asset"] = "splash_LIVE.exe"
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps(data).encode(), cfg)
    # Un extra desconocido se ignora (compatibilidad hacia delante).
    data["channels"]["LIVE"]["extras"] = {"otro": {"asset": "otro_LIVE.png"}}
    assert parse_manifest(json.dumps(data).encode(), cfg).channels["LIVE"].extras == ()
