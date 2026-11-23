"""Canales temporales (HOTFIX, EPTU, TECH-PREVIEW): preguntar la primera vez, recordar, «Inaccesible»."""
import shutil

import pytest

from conftest import FakeClient, FakeHttp, build_release, ini_bytes, make_cfg, make_game
from sctrad.errors import ConfigError
from sctrad.gamepaths import detect_installs
from sctrad.service import MissingChannel, UpdateService
from sctrad.usercfg import get_setting

GLOBAL = "data/Localization/spanish_(spain)/global.ini"


def _svc(tmp_path, cfg, payloads, version="2026.11.23.1"):
    rel, small, routes = build_release(cfg, version, payloads)
    return UpdateService(cfg, data_dir=tmp_path / "data", http=FakeHttp(routes), client=FakeClient(rel, small),
                         game_running=lambda: False,
                         detector=lambda: detect_installs(cfg, extra_roots=[tmp_path / "game" / "StarCitizen"]))


def _st(res, ch):
    return next(s for s in res.statuses if s.install.channel == ch)


def test_config_optional_channels(cfg):
    assert cfg.optional_channels == ("HOTFIX", "EPTU", "TECH-PREVIEW")
    with pytest.raises(ConfigError):
        make_cfg(optional_channels=["NOPE"])


def test_new_temporary_channel_asks_first(tmp_path, cfg):
    make_game(tmp_path / "game", "LIVE")
    eptu = make_game(tmp_path / "game", "EPTU")
    svc = _svc(tmp_path, cfg, {"LIVE": ini_bytes(), "EPTU": ini_bytes("A=E\r\n")})
    res = svc.check()
    live, ep = _st(res, "LIVE"), _st(res, "EPTU")
    assert live.enabled is True and not live.optional
    assert ep.optional and ep.enabled is None and ep.needs_decision and not ep.needs_action
    # El vigilante solo avisa (una vez) y no instala nada en el canal nuevo.
    notes = svc.run_background()
    assert [n.title for n in notes] == ["Canal EPTU detectado"]
    assert not (eptu / GLOBAL).exists()
    assert svc.run_background() == []
    # El jugador dice que sí -> ACTUALIZAR ya lo tiene en cuenta.
    svc.set_channel_enabled("EPTU", True)
    assert _st(svc.check(), "EPTU").needs_action


def test_disabled_channel_is_never_touched(tmp_path, cfg):
    hot = make_game(tmp_path / "game", "HOTFIX")
    svc = _svc(tmp_path, cfg, {"HOTFIX": ini_bytes("A=1\r\n")})
    svc.set_channel_enabled("HOTFIX", True)
    st = _st(svc.check(), "HOTFIX")
    res = svc.check()
    svc.install_one(st, res.release, res.manifest)
    svc.set_channel_enabled("HOTFIX", False)
    svc2 = _svc(tmp_path, cfg, {"HOTFIX": ini_bytes("A=2\r\n")}, "2026.11.24.1")
    st2 = _st(svc2.check(), "HOTFIX")
    assert st2.enabled is False and not st2.needs_action and not st2.needs_decision
    assert svc2.run_background() == []
    assert (hot / GLOBAL).read_bytes() == ini_bytes("A=1\r\n")


def test_closed_channel_is_inaccessible_and_comes_back(tmp_path, cfg):
    make_game(tmp_path / "game", "LIVE")
    tp = make_game(tmp_path / "game", "TECH-PREVIEW")
    payloads = {"LIVE": ini_bytes(), "TECH-PREVIEW": ini_bytes("A=T\r\n")}
    svc = _svc(tmp_path, cfg, payloads)
    svc.set_channel_enabled("TECH-PREVIEW", True)
    res = svc.check()
    svc.install_one(_st(res, "TECH-PREVIEW"), res.release, res.manifest)
    # CIG cierra el canal: la carpeta desaparece -> fila gris «Inaccesible» que recuerda la elección.
    shutil.rmtree(tp)
    res = svc.check()
    assert all(s.install.channel != "TECH-PREVIEW" for s in res.statuses)
    row = next(r for r in svc.channel_rows(res.statuses, res.manifest)
               if isinstance(r, MissingChannel) and r.channel == "TECH-PREVIEW")
    assert row.optional and row.enabled is True
    assert svc.run_background() == []          # no intenta escribir en una carpeta que no existe
    # El canal vuelve (instalación limpia): al abrir el launcher la traducción se pone sola.
    tp = make_game(tmp_path / "game", "TECH-PREVIEW")
    svc.run_background()
    assert (tp / GLOBAL).read_bytes() == ini_bytes("A=T\r\n")
    assert get_setting((tp / "user.cfg").read_bytes(), "g_language") == "spanish_(spain)"


def test_enabled_channel_without_record_installs_in_background(tmp_path, cfg):
    ep = make_game(tmp_path / "game", "EPTU", user_cfg=b"r_DisplayInfo = 2\r\n")
    svc = _svc(tmp_path, cfg, {"EPTU": ini_bytes("A=E\r\n")})
    svc.set_channel_enabled("EPTU", True)
    notes = svc.run_background()
    assert notes and notes[0].title == "Traducción instalada"
    assert (ep / GLOBAL).read_bytes() == ini_bytes("A=E\r\n")
    assert get_setting((ep / "user.cfg").read_bytes(), "g_language") == "spanish_(spain)"


def test_channel_without_published_translation(tmp_path, cfg):
    make_game(tmp_path / "game", "EPTU")
    svc = _svc(tmp_path, cfg, {"LIVE": ini_bytes()})
    st = _st(svc.check(), "EPTU")
    assert st.entry is None and not st.needs_decision and not st.needs_action
    assert svc.run_background() == []


def test_existing_managed_install_counts_as_enabled(tmp_path, cfg):
    """Quien ya tenía HOTFIX traducido con una versión anterior del gestor no recibe la pregunta."""
    make_game(tmp_path / "game", "HOTFIX")
    svc = _svc(tmp_path, cfg, {"HOTFIX": ini_bytes()})
    res = svc.check()
    svc.install_one(_st(res, "HOTFIX"), res.release, res.manifest)
    with svc.store.transaction() as s:
        s["settings"].pop("channels", None)
    assert svc.channel_enabled("HOTFIX") is True
