import json
import sys
from datetime import datetime, timezone

from conftest import ROOT, TEST_PRIV_B64, TEST_PUB_B64, make_cfg

sys.path.insert(0, str(ROOT / "tools"))
import build_release  # noqa: E402
import validate_translation  # noqa: E402

from sctrad.manifest import parse_manifest, verify_signature  # noqa: E402


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
    lines = [f"k{i}=valor {i}" for i in range(150)]
    (root / "LIVE/global.ini").write_bytes(_ini(lines))
    ref = tmp_path / "referencia"
    (ref / "LIVE").mkdir(parents=True)
    (ref / "LIVE/global.ini").write_bytes(_ini([f"k{i}=value {i}" for i in range(150)]))
    assert validate_translation.main(["--root", str(root), "--config", str(cfgp), "--referencia", str(ref)]) == 0
    bad = lines + ["k1=duplicada", "linea sin igual", "k200=canción"]
    (root / "LIVE/global.ini").write_bytes(_ini(bad))
    rep = validate_translation.Report()
    validate_translation.validate(root, json.loads(cfgp.read_text()), ref, rep)
    text = " ".join(rep.errors)
    assert "repetida" in text and "CLAVE=valor" in text and "tildes" in text
    # Marcador protegido perdido
    (ref / "LIVE/global.ini").write_bytes(_ini([f"k{i}=value {i}" for i in range(149)] + ["k149=Go to ~mission(Location) now\\n"]))
    (root / "LIVE/global.ini").write_bytes(_ini([f"k{i}=valor {i}" for i in range(149)] + ["k149=Ve ahora"]))
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
