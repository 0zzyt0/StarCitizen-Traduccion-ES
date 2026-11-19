import json

import pytest

from conftest import FakeClient, FakeHttp, build_release, ini_bytes, make_cfg, make_game
from sctrad.errors import (ConfigError, ForeignFileError, GameRunningError, IntegrityError, ManifestError,
                           NetworkError, UnsafePathError)
from sctrad.fsutil import safe_target
from sctrad.gamepaths import (COMPATIBLE, INCOMPATIBLE, UNVERIFIED, check_compat, detect_installs,
                              normalize_user_path, read_game_version)
from sctrad.manifest import parse_manifest, verify_signature
from sctrad.service import (ST_FOREIGN, ST_MISSING, ST_NOT_INSTALLED, ST_UP_TO_DATE, ST_UPDATE,
                            UpdateService)
from sctrad.usercfg import apply_settings, get_setting, revert_settings
from sctrad.version import compare_versions, is_newer, version_from_tag


# ------------------------------------------------------------------ versiones
def test_version_order_is_numeric():
    assert compare_versions("1.10", "1.9") == 1
    assert compare_versions("2026.11.19.10", "2026.11.19.9") == 1
    assert compare_versions("1.2", "1.2.0") == 0
    assert is_newer("2026.11.20.1", "2026.11.19.5")
    assert not is_newer("2026.11.19.1", "2026.11.19.1")
    assert not is_newer("2026.11.18.9", "2026.11.19.1")
    assert version_from_tag("traduccion-v2026.11.19.2", "traduccion-v") == "2026.11.19.2"
    assert version_from_tag("app-v1.0.0", "traduccion-v") is None


def test_config_rejects_bad_repo():
    with pytest.raises(ConfigError):
        make_cfg(github_owner="")
    with pytest.raises(ConfigError):
        make_cfg(require_signature=True, signing_public_key="")


# ------------------------------------------------------------------ rutas
def test_detect_and_custom_path(tmp_path, cfg):
    live = make_game(tmp_path, "LIVE", "4.3.2")
    make_game(tmp_path, "PTU", "4.4.0")
    found = detect_installs(cfg, extra_roots=[tmp_path / "StarCitizen"])
    assert {g.channel for g in found} == {"LIVE", "PTU"}
    assert normalize_user_path(live / "data", cfg)[0].channel == "LIVE"
    assert len(normalize_user_path(tmp_path / "StarCitizen", cfg)) == 2
    assert normalize_user_path(tmp_path / "nada", cfg) == []
    assert read_game_version(live) == ("4.3.2", "12345")


def test_no_game_detected(tmp_path, cfg):
    assert detect_installs(cfg, extra_roots=[tmp_path]) == []


def test_compat():
    assert check_compat("4.3.2", ["4.3"]) == COMPATIBLE
    assert check_compat("4.4.0", ["4.3"]) == INCOMPATIBLE
    assert check_compat(None, ["4.3"]) == UNVERIFIED
    assert check_compat("4.3.2", ["*"]) == UNVERIFIED


def test_safe_target_blocks_traversal(tmp_path):
    with pytest.raises(UnsafePathError):
        safe_target(tmp_path, "../fuera.ini")
    with pytest.raises(UnsafePathError):
        safe_target(tmp_path, "/abs/x")
    with pytest.raises(UnsafePathError):
        safe_target(tmp_path, "data\\x")
    (tmp_path / "out").mkdir()
    try:
        (tmp_path / "link").symlink_to(tmp_path / "out", target_is_directory=True)
    except OSError:
        pytest.skip("No se pueden crear enlaces simbólicos en este sistema")
    with pytest.raises(UnsafePathError):
        safe_target(tmp_path, "link/global.ini")


# ------------------------------------------------------------------ user.cfg
def test_usercfg_merge_and_revert():
    raw = b"r_DisplayInfo = 2\r\ng_language = english\r\n"
    new, changes = apply_settings(raw, {"g_language": "spanish_(spain)", "g_languageAudio": "english"},
                                  ("g_languageAudio",))
    assert get_setting(new, "g_language") == "spanish_(spain)"
    assert get_setting(new, "g_languageAudio") == "english"
    assert b"r_DisplayInfo = 2\r\n" in new and new.endswith(b"\r\n")
    assert changes == {"g_language": "english", "g_languageAudio": None}
    back = revert_settings(new, {"g_language": "spanish_(spain)", "g_languageAudio": "english"}, changes)
    assert back == raw
    # Si el jugador cambió el valor después, no se toca.
    edited = new.replace(b"spanish_(spain)", b"french_(france)")
    assert get_setting(revert_settings(edited, {"g_language": "spanish_(spain)"}, {"g_language": "english"}),
                       "g_language") == "french_(france)"


def test_usercfg_keeps_existing_audio():
    raw = b"g_languageAudio = german_(germany)\n"
    new, changes = apply_settings(raw, {"g_language": "spanish_(spain)", "g_languageAudio": "english"},
                                  ("g_languageAudio",))
    assert get_setting(new, "g_languageAudio") == "german_(germany)"
    assert "g_languageAudio" not in changes


# ------------------------------------------------------------------ manifiesto
def test_manifest_signature_and_validation(cfg):
    rel, small, _ = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()})
    raw, sig = small[cfg.manifest_asset], small[cfg.manifest_signature_asset]
    assert verify_signature(raw, sig, cfg) == "firmado"
    m = parse_manifest(raw, cfg, expected_version="2026.11.19.1")
    assert m.channels["LIVE"].target == cfg.translation_rel_path
    with pytest.raises(ManifestError):
        verify_signature(raw.replace(b"Notas", b"Otras"), sig, cfg)
    with pytest.raises(ManifestError):
        verify_signature(raw, None, cfg)
    with pytest.raises(ManifestError):
        parse_manifest(raw, cfg, expected_version="2026.11.19.2")
    bad = json.loads(raw)
    bad["channels"]["LIVE"]["target"] = "../../Windows/evil.ini"
    with pytest.raises(ManifestError):
        parse_manifest(json.dumps(bad).encode(), cfg)


# ------------------------------------------------------------------ servicio
def _service(tmp_path, cfg, client, routes, running=lambda: False, game_root=None):
    root = game_root or tmp_path / "game"
    return UpdateService(cfg, data_dir=tmp_path / "data", http=FakeHttp(routes), client=client,
                         game_running=running,
                         detector=lambda: detect_installs(cfg, extra_roots=[root / "StarCitizen"]))


def _install_all(svc, res, **kw):
    for st in res.statuses:
        svc.install_one(st, res.release, res.manifest, **kw)


def test_fresh_install_then_equal_then_newer(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE", user_cfg=b"r_DisplayInfo = 2\r\n")
    v1 = ini_bytes("A=Uno\r\n")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": v1})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    res = svc.check()
    assert res.error is None and res.statuses[0].state == ST_NOT_INSTALLED
    _install_all(svc, res)
    g = live / "data/Localization/spanish_(spain)/global.ini"
    assert g.read_bytes() == v1
    assert get_setting((live / "user.cfg").read_bytes(), "g_language") == "spanish_(spain)"
    assert b"r_DisplayInfo = 2" in (live / "user.cfg").read_bytes()
    # Misma versión: nada que hacer.
    assert svc.check().statuses[0].state == ST_UP_TO_DATE
    assert svc.run_background() == []
    # Versión nueva -> la tarea en segundo plano la instala sola.
    v2 = ini_bytes("A=Dos\r\n")
    rel2, small2, routes2 = build_release(cfg, "2026.11.19.10", {"LIVE": v2})
    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2)
    assert svc2.check().statuses[0].state == ST_UPDATE
    notes = svc2.run_background()
    assert notes and notes[0].kind == "ok"
    assert g.read_bytes() == v2
    hist = svc2.history()
    assert hist[0]["action"] == "actualizar" and hist[0]["result"] == "ok"
    # Hay copia original + copia de la v1
    kinds = sorted(b.kind for b in svc2.installer.list_backups(res.statuses[0].install))
    assert kinds == ["auto", "original"]


def test_older_release_is_not_installed(tmp_path, cfg):
    make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.5", {"LIVE": ini_bytes("A=5\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    old, small_o, routes_o = build_release(cfg, "2026.11.19.4", {"LIVE": ini_bytes("A=4\r\n")})
    svc2 = _service(tmp_path, cfg, FakeClient(old, small_o), routes_o)
    assert svc2.check().statuses[0].state == ST_UP_TO_DATE
    assert svc2.run_background() == []


def test_incompatible_build_pauses_auto(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE", version="4.3.2")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes("A=1\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    rel2, small2, routes2 = build_release(cfg, "2026.11.20.1", {"LIVE": ini_bytes("A=2\r\n")},
                                          game_versions={"LIVE": ["4.4"]})
    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2)
    notes = svc2.run_background()
    assert notes and notes[0].kind == "warning"
    assert (live / "data/Localization/spanish_(spain)/global.ini").read_bytes() == ini_bytes("A=1\r\n")


def test_network_failure_keeps_installed_and_uses_cache(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    svc_off = _service(tmp_path, cfg, FakeClient(error=NetworkError("sin red")), {})
    res = svc_off.check()
    assert res.offline and res.manifest and res.manifest.version == "2026.11.19.1"
    assert res.statuses[0].state == ST_UP_TO_DATE
    assert svc_off.run_background() == []
    assert (live / "data/Localization/spanish_(spain)/global.ini").exists()


def test_corrupted_download_is_rejected(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()})
    url = next(iter(routes))
    routes[url] = routes[url][:-3] + b"XYZ"
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    res = svc.check()
    with pytest.raises(IntegrityError):
        _install_all(svc, res)
    assert not (live / "data/Localization/spanish_(spain)/global.ini").exists()


def test_tampered_manifest_is_rejected(tmp_path, cfg):
    make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()}, tamper=True)
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    res = svc.check()
    assert res.manifest is None and "firma" in res.error.lower()


def test_game_running_blocks_and_defers(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes("A=1\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    rel2, small2, routes2 = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes("A=2\r\n")})
    state = {"running": True, "polls": 0}

    def running():
        return state["running"]

    def fake_sleep(_s):
        state["polls"] += 1
        if state["polls"] >= 2:
            state["running"] = False

    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2, running=running)
    with pytest.raises(GameRunningError):
        svc2.install_one(svc2.check().statuses[0], rel2, svc2.check().manifest)
    notes = svc2.run_background(poll_seconds=1, sleep=fake_sleep)
    assert notes and notes[0].kind == "ok" and state["polls"] == 2
    assert (live / "data/Localization/spanish_(spain)/global.ini").read_bytes() == ini_bytes("A=2\r\n")
    # Si el juego no se cierra a tiempo, queda pendiente sin tocar nada.
    rel3, small3, routes3 = build_release(cfg, "2026.11.19.3", {"LIVE": ini_bytes("A=3\r\n")})
    svc3 = _service(tmp_path, cfg, FakeClient(rel3, small3), routes3, running=lambda: True)
    assert svc3.run_background(poll_seconds=10, max_wait_seconds=20, sleep=lambda s: None) == []
    rec = svc3.store.snapshot()["installs"][svc3.known_installs()[0].key]
    assert rec["pending_version"] == "2026.11.19.3" and rec["installed_version"] == "2026.11.19.2"


def test_failed_replacement_rolls_back(tmp_path, cfg, monkeypatch):
    live = make_game(tmp_path / "game", "LIVE", user_cfg=b"g_language = english\r\n")
    g = live / "data/Localization/spanish_(spain)/global.ini"
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes("A=1\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    rel2, small2, routes2 = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes("A=2\r\n")})
    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2)
    import sctrad.installer as inst_mod
    from sctrad.errors import InstallError

    def boom(*a, **k):
        raise InstallError("fallo simulado al escribir user.cfg")
    (live / "user.cfg").write_bytes(b"g_language = english\r\n")  # forzar que haya que escribir user.cfg
    monkeypatch.setattr(inst_mod, "atomic_write_bytes", boom)
    res = svc2.check()
    with pytest.raises(InstallError):
        svc2.install_one(res.statuses[0], res.release, res.manifest, action="reparar", allow_foreign=True)
    assert g.read_bytes() == ini_bytes("A=1\r\n")  # restaurado
    assert svc2.store.snapshot()["installs"][res.statuses[0].install.key]["installed_version"] == "2026.11.19.1"


def test_foreign_file_needs_confirmation(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    g = live / "data/Localization/spanish_(spain)/global.ini"
    g.parent.mkdir(parents=True)
    g.write_bytes(b"otra traduccion")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    res = svc.check()
    assert res.statuses[0].state == ST_FOREIGN
    with pytest.raises(ForeignFileError):
        _install_all(svc, res)
    _install_all(svc, res, allow_foreign=True)
    assert g.read_bytes() == ini_bytes()
    # Desinstalar devuelve la otra traducción original.
    svc.uninstall_one(res.statuses[0].install)
    assert g.read_bytes() == b"otra traduccion"


def test_identical_manual_copy_is_adopted(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    g = live / "data/Localization/spanish_(spain)/global.ini"
    g.parent.mkdir(parents=True)
    g.write_bytes(ini_bytes())
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    res = svc.check()
    assert res.statuses[0].state == ST_NOT_INSTALLED
    _install_all(svc, res)  # sin allow_foreign: no pide confirmación
    assert svc.check().statuses[0].state == ST_UP_TO_DATE


def test_uninstall_restores_original_state(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE", user_cfg=b"r_DisplayInfo = 2\r\n")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    res = svc.check()
    _install_all(svc, res)
    svc.uninstall_one(res.statuses[0].install)
    assert not (live / "data/Localization/spanish_(spain)").exists()
    assert (live / "user.cfg").read_bytes() == b"r_DisplayInfo = 2\r\n"
    assert svc.check().statuses[0].state == ST_NOT_INSTALLED


def test_missing_file_is_repaired_in_background(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes()})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    g = live / "data/Localization/spanish_(spain)/global.ini"
    g.unlink()
    assert svc.check().statuses[0].state == ST_MISSING
    assert svc.run_background() == []  # reparación silenciosa
    assert g.exists()


def test_no_install_while_launcher_patches(tmp_path, cfg):
    import os
    live = make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes("A=1\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    rel2, small2, routes2 = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes("A=2\r\n")})
    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2)
    os.utime(live / "Data.p4k")  # el launcher acaba de escribir el juego
    assert svc2.run_background(origin="launcher") == []
    assert (live / "data/Localization/spanish_(spain)/global.ini").read_bytes() == ini_bytes("A=1\r\n")
    os.utime(live / "Data.p4k", (0, 0))
    assert svc2.run_background(origin="juego_cerrado")[0].kind == "ok"


def test_incompatible_warning_only_once(tmp_path, cfg):
    make_game(tmp_path / "game", "LIVE", version="4.3.2")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes("A=1\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    rel2, small2, routes2 = build_release(cfg, "2026.11.20.1", {"LIVE": ini_bytes("A=2\r\n")},
                                          game_versions={"LIVE": ["4.4"]})
    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2)
    assert len(svc2.run_background()) == 1
    assert svc2.run_background() == []


def test_rollback_holds_auto_update(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes("A=1\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    rel2, small2, routes2 = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes("A=2\r\n")})
    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2)
    svc2.run_background()
    gi = svc2.known_installs()[0]
    auto = [b for b in svc2.installer.list_backups(gi) if b.kind == "auto"][0]
    svc2.installer.restore(gi, auto.id)
    g = live / "data/Localization/spanish_(spain)/global.ini"
    assert g.read_bytes() == ini_bytes("A=1\r\n")
    assert svc2.run_background() == []  # no reinstala la 2 descartada
    assert g.read_bytes() == ini_bytes("A=1\r\n")


def test_notify_mode_does_not_install(tmp_path, cfg):
    live = make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes("A=1\r\n")})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    _install_all(svc, svc.check())
    svc.store.update_settings(mode="notify")
    rel2, small2, routes2 = build_release(cfg, "2026.11.19.2", {"LIVE": ini_bytes("A=2\r\n")})
    svc2 = _service(tmp_path, cfg, FakeClient(rel2, small2), routes2)
    notes = svc2.run_background()
    assert len(notes) == 1 and "disponible" in notes[0].title
    assert svc2.run_background() == []  # no repite el aviso
    assert (live / "data/Localization/spanish_(spain)/global.ini").read_bytes() == ini_bytes("A=1\r\n")


def test_download_resume(tmp_path, cfg):
    from sctrad.downloader import download_verified
    import hashlib
    data = b"x" * 1000 + b"y" * 1000
    url = "https://github.com/o/r/releases/download/t/global_LIVE.ini"
    http = FakeHttp({url: data})
    dest = tmp_path / "global_LIVE.ini"
    (tmp_path / "global_LIVE.ini.part").write_bytes(data[:700])
    download_verified(http, url, dest, len(data), hashlib.sha256(data).hexdigest())
    assert dest.read_bytes() == data
    assert http.calls[-1][1].get("Range") == "bytes=700-"


def test_disallowed_host(cfg):
    from sctrad.net import Http
    h = Http(cfg.allowed_hosts)
    with pytest.raises(NetworkError):
        h.open("https://evil.example.com/x")
    with pytest.raises(NetworkError):
        h.open("http://github.com/x")


def test_release_client_picks_translation_when_installer_is_latest(cfg):
    import json as _json
    from sctrad.github import ReleaseClient

    class Http:
        def __init__(self):
            self.urls = []

        def get_json(self, url, etag=None):
            self.urls.append(url)
            data = [
                {"tag_name": "v1.2.0", "draft": False, "prerelease": False, "assets": []},
                {"tag_name": "traduccion-v2026.11.19.10", "draft": False, "prerelease": False, "assets": []},
                {"tag_name": "traduccion-v2026.11.19.9", "draft": False, "prerelease": False, "assets": []},
                {"tag_name": "traduccion-v2026.11.20.1", "draft": False, "prerelease": True, "assets": []},
                {"tag_name": "traduccion-v2026.12.1.1", "draft": True, "prerelease": False, "assets": []},
            ]
            return 200, _json.loads(_json.dumps(data)), "etag"
    h = Http()
    c = ReleaseClient(cfg, h)
    assert c.latest_translation().version == "2026.11.19.10"
    assert c.latest_translation(include_prerelease=True).version == "2026.11.20.1"
    assert c.latest_app().version == "1.2.0"
    assert all("/releases/latest" not in u for u in h.urls)


def test_channel_rows_show_missing_channels(tmp_path, cfg):
    from sctrad.service import MissingChannel
    make_game(tmp_path / "game", "LIVE")
    rel, small, routes = build_release(cfg, "2026.11.19.1", {"LIVE": ini_bytes(), "HOTFIX": ini_bytes()})
    svc = _service(tmp_path, cfg, FakeClient(rel, small), routes)
    res = svc.check()
    rows = svc.channel_rows(res.statuses, res.manifest)
    assert [r.channel if isinstance(r, MissingChannel) else r.install.channel for r in rows] == \
        ["LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW"]
    hot = rows[3]
    assert isinstance(hot, MissingChannel) and hot.available_version == "2026.11.19.1"
    assert hot.path.endswith("HOTFIX")
    # Sin juego encontrado: todos los canales en gris, sin ruta
    empty = UpdateService(cfg, data_dir=tmp_path / "d2", http=FakeHttp({}), client=FakeClient(rel, small),
                          game_running=lambda: False, detector=lambda: [])
    rows = empty.channel_rows([], None)
    assert len(rows) == 5 and all(isinstance(r, MissingChannel) and r.path is None for r in rows)


def test_hotfix_channel_detected(tmp_path, cfg):
    make_game(tmp_path, "HOTFIX", "4.10.0")
    found = detect_installs(cfg, extra_roots=[tmp_path / "StarCitizen"])
    assert [g.channel for g in found] == ["HOTFIX"]
