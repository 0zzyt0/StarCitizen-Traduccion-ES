import json
import sys
from datetime import datetime, timezone

from conftest import ROOT, TEST_PRIV_B64, TEST_PUB_B64, make_cfg

sys.path.insert(0, str(ROOT / "tools"))
import build_release  # noqa: E402
import validate_translation  # noqa: E402

from sctrad.manifest import parse_manifest, verify_signature  # noqa: E402


def _png(w, h):
    """PNG mínimo válido (sin dependencias)."""
    import struct
    import zlib

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00\x28\x5a" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _ini(lines, bom=True):
    body = "\r\n".join(lines) + "\r\n"
    return (b"\xef\xbb\xbf" if bom else b"") + body.encode()


def _config(tmp_path):
    cfg = json.loads((ROOT / "config/app_config.json").read_text(encoding="utf-8"))
    cfg["signing_public_key"] = TEST_PUB_B64
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def test_next_version_monotonic():
    d = datetime(2026, 11, 19, tzinfo=timezone.utc)
    assert build_release.next_version([], d) == "2026.11.19.1"
    assert build_release.next_version(["2026.11.19.1", "2026.11.19.9"], d) == "2026.11.19.10"
    assert build_release.next_version(["2026.11.20.3"], d) == "2026.11.20.4"  # reloj atrasado


def test_validation_detects_problems(tmp_path):
    cfgp = _config(tmp_path)
    root = tmp_path / "traduccion"
    (root / "LIVE").mkdir(parents=True)
    lines = [f"k{i}=valor {i}" for i in range(150)] + ["Personal_Translation_Version=Traduccion 0zzyt0 LIVE v4.10"]
    (root / "LIVE/global.ini").write_bytes(_ini(lines))
    ref = tmp_path / "referencia"
    (ref / "LIVE").mkdir(parents=True)
    (ref / "LIVE/global.ini").write_bytes(_ini([f"k{i}=value {i}" for i in range(150)]
                                               + ["Personal_Translation_Version=x"]))
    assert validate_translation.main(["--root", str(root), "--config", str(cfgp), "--referencia", str(ref)]) == 0
    bad = lines + ["k1=duplicada", "linea sin igual", "k200=canción"]
    (root / "LIVE/global.ini").write_bytes(_ini(bad))
    rep = validate_translation.Report()
    validate_translation.validate(root, json.loads(cfgp.read_text()), ref, rep)
    text = " ".join(rep.errors)
    assert "repetida" in text and "CLAVE=valor" in text and "tildes" in text
    # Marcador protegido perdido
    (ref / "LIVE/global.ini").write_bytes(_ini([f"k{i}=value {i}" for i in range(149)] + ["k149=Go to ~mission(Location) now\\n"]))
    (root / "LIVE/global.ini").write_bytes(_ini([f"k{i}=valor {i}" for i in range(149)] + ["k149=Ve ahora",
                                                "Personal_Translation_Version=Traduccion 0zzyt0 LIVE v4.10"]))
    rep = validate_translation.Report()
    validate_translation.validate(root, json.loads(cfgp.read_text()), ref, rep)
    assert any("marcadores" in e for e in rep.errors)


def test_build_release_signs_and_skips_unchanged(tmp_path, monkeypatch, capsys):
    cfgp = _config(tmp_path)
    root = tmp_path / "traduccion"
    (root / "LIVE").mkdir(parents=True)
    data = _ini([f"k{i}=valor {i}" for i in range(150)])
    (root / "LIVE/global.ini").write_bytes(data)
    (root / "compatibilidad.json").write_text(json.dumps({"LIVE": ["4.3"]}))
    rel = tmp_path / "releases.json"
    rel.write_text(json.dumps([{"tag_name": "traduccion-v2026.11.19.1", "draft": False},
                               {"tag_name": "app-v1.0.0", "draft": False}]))
    monkeypatch.setenv("MANIFEST_SIGNING_KEY", TEST_PRIV_B64)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "dist"
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel)]) == 0
    raw = (out / "manifest.json").read_bytes()
    cfg = make_cfg()
    assert verify_signature(raw, (out / "manifest.json.sig").read_bytes(), cfg) == "firmado"
    m = parse_manifest(raw, cfg)
    assert m.channels["LIVE"].game_versions == ("4.3",)
    assert (out / "global_LIVE.ini").read_bytes() == data
    from sctrad.version import compare_versions
    assert compare_versions(m.version, "2026.11.19.1") > 0
    # Sin cambios -> no publica
    prev = tmp_path / "prev.json"
    prev.write_bytes(raw)
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel), "--previous-manifest", str(prev)]) == 0
    assert "skip=true" in capsys.readouterr().out
    # Clave equivocada -> error
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import base64
    other = base64.b64encode(Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()
    monkeypatch.setenv("MANIFEST_SIGNING_KEY", other)
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel), "--force"]) == 1
    monkeypatch.delenv("MANIFEST_SIGNING_KEY")
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel), "--force"]) == 1


def test_latest_tag_ignores_app_and_drafts(tmp_path):
    rel = [{"tag_name": "app-v2.0.0"}, {"tag_name": "traduccion-v2026.11.19.9"},
           {"tag_name": "traduccion-v2026.11.19.10"}, {"tag_name": "traduccion-v2026.12.1.1", "draft": True}]
    assert build_release.latest_published(rel, "traduccion-v") == "traduccion-v2026.11.19.10"


def test_build_release_includes_splash(tmp_path, monkeypatch):
    cfgp = _config(tmp_path)
    root = tmp_path / "traduccion"
    (root / "LIVE").mkdir(parents=True)
    (root / "LIVE/global.ini").write_bytes(_ini([f"k{i}=valor {i}" for i in range(150)]
                                                + ["Personal_Translation_Version=Traduccion 0zzyt0 LIVE v4.10"]))
    png = _png(800, 450)
    (root / "LIVE/SplashScreen.png").write_bytes(png)
    rep = validate_translation.Report()
    validate_translation.validate(root, json.loads(cfgp.read_text()), None, rep)
    assert not rep.errors and not any("PNG" in w or "800x450" in w for w in rep.warnings)
    rel = tmp_path / "releases.json"; rel.write_text("[]")
    monkeypatch.setenv("MANIFEST_SIGNING_KEY", TEST_PRIV_B64)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "dist"
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel)]) == 0
    m = parse_manifest((out / "manifest.json").read_bytes(), make_cfg())
    ex = m.channels["LIVE"].extras[0]
    assert ex.id == "splash" and ex.target == "EasyAntiCheat/SplashScreen.png"
    assert (out / "splash_LIVE.png").read_bytes() == png


def test_compat_auto_from_pu_version(tmp_path):
    f = tmp_path / "global.ini"
    f.write_bytes(_ini(["a=b", "Frontend_PU_Version=Alpha 4.10.3: Asedio a Orison\\nTraducido por: 0zzyt0"]))
    assert build_release.detect_game_version(f) == "4.10"
    assert build_release.resolve_compat("auto", f) == ["4.10"]
    assert build_release.resolve_compat(["5.0"], f) == ["5.0"]
    f.write_bytes(_ini(["a=b", "Frontend_PU_Version,P=Alpha 5.0: X"]))
    assert build_release.resolve_compat([], f) == ["5.0"]


def test_organizar_releases_plan():
    sys.path.insert(0, str(ROOT / "tools"))
    import organizar_releases as org
    repo = "o/r"
    rels = [
        {"id": 5, "tag_name": "traduccion-v2026.11.19.2", "name": "Traducción 2026.11.19.2", "body": "Notas X"},
        {"id": 6, "tag_name": "v1.3.0", "name": "x", "body": ""},
        {"id": 7, "tag_name": "v1.2.9", "name": "x", "body": ""},
        {"id": 4, "tag_name": "app-v1.1.0", "name": "Gestor 1.1.0 (instalador)", "body": ""},
        {"id": 3, "tag_name": "traduccion-v2026.11.19.1", "name": "t", "body": "Primera"},
    ]
    p = org.plan(rels, repo)
    e = {x["tag"]: x for x in p["edits"]}
    assert e["v1.3.0"]["name"].startswith("⬇️ INSTALADOR") and e["v1.3.0"]["make_latest"] == "true"
    assert e["v1.2.9"]["name"].startswith("📦 Instalador anterior")
    assert e["traduccion-v2026.11.19.2"]["make_latest"] == "false"
    assert "No hace falta descargar" in e["traduccion-v2026.11.19.2"]["body"]
    assert e["traduccion-v2026.11.19.2"]["body"].rstrip().endswith("Notas X")
    assert p["delete"] == ["app-v1.1.0"] and p["latest"] == "v1.3.0"
    assert p["reraise"] == "v1.3.0"  # una traducción va primera en la lista: hay que subir el instalador
    assert "app-v1.1.0" not in e
    # Idempotente y sin duplicar la cabecera
    for r in rels:
        if r["tag_name"] in e:
            r["name"], r["body"] = e[r["tag_name"]]["name"], e[r["tag_name"]]["body"].replace("\n", "\r\n")
    rels = [r for r in rels if r["tag_name"] != "app-v1.1.0"]
    rels.sort(key=lambda r: r["tag_name"] != "v1.3.0")  # tras volver a crearlo, el instalador va primero
    p2 = org.plan(rels, repo)
    assert p2["edits"] == [] and p2["delete"] == [] and p2["reraise"] is None
    # Sin instalador nuevo todavía: no se borra el antiguo
    assert org.plan([{"id": 1, "tag_name": "app-v1.2.0", "name": "", "body": ""}], repo)["delete"] == []


def test_hotfix_uses_live_translation(tmp_path, monkeypatch):
    cfgp = _config(tmp_path)
    root = tmp_path / "traduccion"
    (root / "LIVE").mkdir(parents=True)
    data = _ini([f"k{i}=valor {i}" for i in range(150)])
    (root / "LIVE/global.ini").write_bytes(data)
    (root / "LIVE/SplashScreen.png").write_bytes(_png(800, 450))
    (root / "compatibilidad.json").write_text(json.dumps({"LIVE": ["4.10"], "HOTFIX": "auto"}))
    rel = tmp_path / "releases.json"; rel.write_text("[]")
    monkeypatch.setenv("MANIFEST_SIGNING_KEY", TEST_PRIV_B64)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "dist"
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel)]) == 0
    m = parse_manifest((out / "manifest.json").read_bytes(), make_cfg())
    assert m.channels["HOTFIX"].sha256 == m.channels["LIVE"].sha256
    assert m.channels["HOTFIX"].game_versions == ("4.10",)
    assert m.channels["HOTFIX"].extras == () and m.channels["LIVE"].extras
    # Con su propia pantalla de carga, HOTFIX la usa (y sigue con el texto de LIVE).
    (root / "HOTFIX").mkdir()
    (root / "HOTFIX/SplashScreen.png").write_bytes(_png(800, 450) + b"")
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel), "--force"]) == 0
    m = parse_manifest((out / "manifest.json").read_bytes(), make_cfg())
    assert m.channels["HOTFIX"].extras[0].asset == "splash_HOTFIX.png"
    assert m.channels["HOTFIX"].sha256 == m.channels["LIVE"].sha256
    assert "HOTFIX (misma que LIVE)" in (tmp_path / "notas.md").read_text(encoding="utf-8")


def test_version_line_required_and_used(tmp_path, monkeypatch):
    cfgp = _config(tmp_path)
    root = tmp_path / "traduccion"
    (root / "PTU").mkdir(parents=True)
    base = [f"k{i}=valor {i}" for i in range(150)] + ["Frontend_PU_Version=Alpha 4.10.3: viejo"]
    (root / "PTU/global.ini").write_bytes(_ini(base))
    rep = validate_translation.Report()
    validate_translation.validate(root, json.loads(cfgp.read_text()), None, rep)
    assert any("falta la línea" in e for e in rep.errors)
    (root / "PTU/global.ini").write_bytes(_ini(base + ["Personal_Translation_Version=Traduccion 0zzyt0 LIVE v5.0"]))
    rep = validate_translation.Report()
    validate_translation.validate(root, json.loads(cfgp.read_text()), None, rep)
    assert any("dice canal LIVE" in e for e in rep.errors)
    (root / "PTU/global.ini").write_bytes(_ini(base + ["Personal_Translation_Version=Traducción 0zzyt0 PTU v5.0"]))
    (root / "compatibilidad.json").write_text(json.dumps({"PTU": ["4.10"]}))
    rep = validate_translation.Report()
    validate_translation.validate(root, json.loads(cfgp.read_text()), None, rep)
    assert not rep.errors and any("se usará la de la línea" in w for w in rep.warnings)
    rel = tmp_path / "releases.json"; rel.write_text("[]")
    monkeypatch.setenv("MANIFEST_SIGNING_KEY", TEST_PRIV_B64)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "dist"
    assert build_release.main(["build", "--root", str(root), "--config", str(cfgp), "--out", str(out),
                               "--releases-json", str(rel)]) == 0
    m = parse_manifest((out / "manifest.json").read_bytes(), make_cfg())
    assert m.channels["PTU"].label == "Traducción 0zzyt0 PTU v5.0"
    assert m.channels["PTU"].game_versions == ("5.0",)  # la línea manda sobre Frontend_PU_Version y la lista
