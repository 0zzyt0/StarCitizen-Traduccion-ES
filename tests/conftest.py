import base64
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

from sctrad.config import config_from_dict  # noqa: E402
from sctrad.github import Asset, Release  # noqa: E402
from sctrad.manifest import sign_manifest  # noqa: E402

TEST_KEY = Ed25519PrivateKey.generate()
TEST_PRIV_B64 = base64.b64encode(TEST_KEY.private_bytes(
    serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()
TEST_PUB_B64 = base64.b64encode(TEST_KEY.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def make_cfg(**over):
    data = json.loads((ROOT / "config" / "app_config.json").read_text(encoding="utf-8"))
    data["signing_public_key"] = TEST_PUB_B64
    data["search_roots"] = []
    data["launcher_logs"] = []
    data.update(over)
    return config_from_dict(data)


@pytest.fixture
def cfg():
    return make_cfg()


def make_game(root: Path, channel="LIVE", version="4.3.2", user_cfg: bytes | None = None) -> Path:
    d = root / "StarCitizen" / channel
    (d / "Bin64").mkdir(parents=True)
    (d / "Data.p4k").write_bytes(b"p4k")
    import os
    import time
    os.utime(d / "Data.p4k", (time.time() - 86400, time.time() - 86400))  # juego no se está parcheando
    (d / "EasyAntiCheat").mkdir()
    (d / "EasyAntiCheat" / "SplashScreen.png").write_bytes(b"SPLASH-ORIGINAL-CIG")
    (d / "Bin64" / "StarCitizen.exe").write_bytes(b"exe")
    if version:
        (d / "build_manifest.id").write_text(json.dumps({"Data": {"Branch": f"sc-alpha-{version}",
                                                                  "RequestedP4ChangeNum": "12345"}}))
    if user_cfg is not None:
        (d / "user.cfg").write_bytes(user_cfg)
    return d


def ini_bytes(text="Frontend_PU_Version=Version\r\nui_Hola=Hola mundo\r\n") -> bytes:
    return b"\xef\xbb\xbf" + text.encode("utf-8")


class FakeHttp:
    """Sirve URLs desde un diccionario: url -> bytes | Exception."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []
        self.allowed_hosts = ("api.github.com", "github.com")

    def open(self, url, headers=None):
        self.calls.append((url, dict(headers or {})))
        val = self.routes.get(url)
        if isinstance(val, Exception):
            raise val
        if val is None:
            from sctrad.errors import NetworkError
            raise NetworkError("404 en prueba")
        rng = (headers or {}).get("Range")
        status = 200
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            val = val[start:]
            status = 206

        class R:
            def __init__(s):
                s.status = status
                s.headers = {}
                s._b = io.BytesIO(val)

            def read(s, n=-1):
                return s._b.read(n)

            def close(s):
                pass
        return R()

    def get_bytes(self, url, max_bytes):
        r = self.open(url)
        return r.read(max_bytes + 1)


class FakeClient:
    """Sustituye a ReleaseClient con publicaciones preparadas en memoria."""

    def __init__(self, release=None, small=None, error=None):
        self.release = release
        self.small = small or {}
        self.error = error
        self.cache = {}

    def latest_translation(self, include_prerelease=False):
        if self.error:
            raise self.error
        return self.release

    def latest_app(self):
        return None

    def download_small(self, asset, max_bytes=1024 * 1024):
        if self.error:
            raise self.error
        return self.small[asset.name]


def build_release(cfg, version, payloads: dict[str, bytes], game_versions=None, sign=True,
                  tamper=False, key_b64=None, extras=None):
    """Devuelve (Release, FakeClient-small-dict, routes-de-descarga)."""
    channels = {}
    routes = {}
    assets = {}
    for ch, data in payloads.items():
        name = f"global_{ch}.ini"
        channels[ch] = {"asset": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "target": cfg.translation_rel_path,
                        "game_versions": (game_versions or {}).get(ch, ["4.3"])}
        url = f"https://github.com/o/r/releases/download/traduccion-v{version}/{name}"
        routes[url] = data
        assets[name] = Asset(name, url, len(data))
        for ex_id, ex_data in ((extras or {}).get(ch) or {}).items():
            ex_name = f"{ex_id}_{ch}.png"
            ex_url = f"https://github.com/o/r/releases/download/traduccion-v{version}/{ex_name}"
            routes[ex_url] = ex_data
            assets[ex_name] = Asset(ex_name, ex_url, len(ex_data))
            channels[ch].setdefault("extras", {})[ex_id] = {
                "asset": ex_name, "size": len(ex_data), "sha256": hashlib.sha256(ex_data).hexdigest(),
                "target": cfg.extra_targets[ex_id]}
    manifest = json.dumps({"schema": 1, "translation_version": version, "published_at": "2026-11-19T00:00:00Z",
                           "min_app_version": "1.0.0", "language_folder": cfg.language_folder,
                           "notes": "Notas", "channels": channels}).encode()
    small = {cfg.manifest_asset: manifest}
    assets[cfg.manifest_asset] = Asset(cfg.manifest_asset, "https://github.com/x/manifest.json", len(manifest))
    if sign:
        sig = sign_manifest(manifest, key_b64 or TEST_PRIV_B64)
        if tamper:
            small[cfg.manifest_asset] = manifest.replace(b"Notas", b"NotaS")
        small[cfg.manifest_signature_asset] = sig
        assets[cfg.manifest_signature_asset] = Asset(cfg.manifest_signature_asset, "https://github.com/x/sig", len(sig))
    rel = Release(f"traduccion-v{version}", version, version, "Notas de la versión", "2026-11-19", False,
                  "https://github.com/o/r/releases", assets)
    return rel, small, routes
