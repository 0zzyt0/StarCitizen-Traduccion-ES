"""Manifiesto de cada publicación de la traducción: lectura, validación y firma.

Formato (schema 1):
{
  "schema": 1,
  "translation_version": "2026.11.19.1",
  "published_at": "2026-11-19T10:00:00Z",
  "min_app_version": "1.0.0",
  "language_folder": "spanish_(spain)",
  "notes": "texto opcional",
  "channels": {
    "LIVE": {"asset": "global_LIVE.ini", "size": 123, "sha256": "...",
             "target": "data/Localization/spanish_(spain)/global.ini",
             "game_versions": ["4.3"]}
  }
}
La firma (manifest.json.sig) es la firma Ed25519, en base64, de los bytes exactos de manifest.json.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass

from . import __version__
from .config import AppConfig
from .errors import ManifestError
from .version import compare_versions, is_valid_version

SCHEMA = 1
ASSET_RE = re.compile(r"^global_[A-Z][A-Z0-9-]{1,20}\.ini$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
EXTRA_ASSET_RE = re.compile(r"^[a-z]{1,20}_[A-Z][A-Z0-9-]{1,20}\.png$")
MAX_EXTRA_BYTES = 10 * 1024 * 1024
GAMEVER_RE = re.compile(r"^(\*|\d{1,4}(\.\d{1,6}){0,3})$")


@dataclass(frozen=True)
class ExtraEntry:
    """Archivo adicional de un canal (p. ej. la pantalla de carga de Easy Anti-Cheat)."""
    id: str
    asset: str
    size: int
    sha256: str
    target: str


@dataclass(frozen=True)
class ChannelEntry:
    channel: str
    asset: str
    size: int
    sha256: str
    target: str
    game_versions: tuple[str, ...]
    extras: tuple[ExtraEntry, ...] = ()
    label: str | None = None   # valor de Personal_Translation_Version del archivo publicado


@dataclass(frozen=True)
class Manifest:
    version: str
    published_at: str
    min_app_version: str
    language_folder: str
    notes: str
    channels: dict[str, ChannelEntry]
    raw: bytes
    signature_status: str  # "firmado" | "sin firma"


def parse_manifest(raw: bytes, cfg: AppConfig, expected_version: str | None = None,
                   signature_status: str = "sin firma") -> Manifest:
    if len(raw) > 1024 * 1024:
        raise ManifestError("El manifiesto de la publicación es demasiado grande.")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ManifestError("El manifiesto de la publicación está dañado.") from e
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ManifestError("El manifiesto usa un formato que este gestor no reconoce. Actualiza el gestor.")
    version = data.get("translation_version")
    if not isinstance(version, str) or not is_valid_version(version):
        raise ManifestError("El manifiesto no indica una versión de traducción válida.")
    if expected_version is not None and compare_versions(version, expected_version) != 0:
        raise ManifestError(
            f"La versión del manifiesto ({version}) no coincide con la etiqueta de la publicación ({expected_version})."
        )
    min_app = data.get("min_app_version", "1.0.0")
    if not isinstance(min_app, str) or not is_valid_version(min_app):
        raise ManifestError("El manifiesto indica una versión mínima del gestor no válida.")
    if compare_versions(__version__, min_app) < 0:
        raise ManifestError(
            f"Esta traducción necesita el gestor {min_app} o superior (tienes {__version__}). "
            "Descarga el instalador nuevo desde GitHub."
        )
    lang = data.get("language_folder")
    if lang != cfg.language_folder:
        raise ManifestError("El manifiesto apunta a una carpeta de idioma distinta de la esperada.")
    channels_raw = data.get("channels")
    if not isinstance(channels_raw, dict) or not channels_raw:
        raise ManifestError("El manifiesto no contiene archivos de traducción.")
    expected_target = cfg.translation_rel_path
    channels: dict[str, ChannelEntry] = {}
    seen_assets: set[str] = set()
    for ch, entry in channels_raw.items():
        if ch not in cfg.channels:
            # Canal desconocido para esta versión del gestor: se ignora sin fallar.
            continue
        if not isinstance(entry, dict):
            raise ManifestError(f"Entrada del canal {ch} no válida en el manifiesto.")
        asset = entry.get("asset")
        size = entry.get("size")
        sha = entry.get("sha256")
        target = entry.get("target")
        gv = entry.get("game_versions", [])
        if not isinstance(asset, str) or not ASSET_RE.match(asset) or asset in seen_assets:
            raise ManifestError(f"Nombre de archivo no permitido para el canal {ch}.")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0 or size > cfg.max_payload_bytes:
            raise ManifestError(f"Tamaño de archivo no válido para el canal {ch}.")
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise ManifestError(f"Suma SHA-256 no válida para el canal {ch}.")
        if target != expected_target:
            raise ManifestError(f"Ruta de destino no permitida para el canal {ch}: {target!r}.")
        if not isinstance(gv, list) or any(not isinstance(x, str) or not GAMEVER_RE.match(x) for x in gv):
            raise ManifestError(f"Lista de versiones del juego no válida para el canal {ch}.")
        seen_assets.add(asset)
        extras: list[ExtraEntry] = []
        raw_extras = entry.get("extras", {}) or {}
        if not isinstance(raw_extras, dict):
            raise ManifestError(f"Archivos extra no válidos para el canal {ch}.")
        for ex_id, ex in raw_extras.items():
            allowed = cfg.extra_targets.get(ex_id)
            if allowed is None:
                continue  # extra desconocido para esta versión del gestor: se ignora
            if not isinstance(ex, dict):
                raise ManifestError(f"Archivo extra «{ex_id}» no válido para el canal {ch}.")
            e_asset, e_size, e_sha, e_target = ex.get("asset"), ex.get("size"), ex.get("sha256"), ex.get("target")
            if not isinstance(e_asset, str) or not EXTRA_ASSET_RE.match(e_asset) or e_asset in seen_assets:
                raise ManifestError(f"Nombre de archivo extra no permitido para el canal {ch}.")
            if not isinstance(e_size, int) or isinstance(e_size, bool) or not 0 < e_size <= MAX_EXTRA_BYTES:
                raise ManifestError(f"Tamaño de archivo extra no válido para el canal {ch}.")
            if not isinstance(e_sha, str) or not SHA_RE.match(e_sha):
                raise ManifestError(f"Suma SHA-256 de archivo extra no válida para el canal {ch}.")
            if e_target != allowed:
                raise ManifestError(f"Destino de archivo extra no permitido para el canal {ch}: {e_target!r}.")
            seen_assets.add(e_asset)
            extras.append(ExtraEntry(ex_id, e_asset, e_size, e_sha, e_target))
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 120 or any(c in label for c in "\r\n"):
            label = None
        channels[ch] = ChannelEntry(ch, asset, size, sha, target, tuple(gv), tuple(extras), label)
    if not channels:
        raise ManifestError("La publicación no contiene ningún canal compatible con este gestor.")
    notes = data.get("notes", "")
    return Manifest(
        version=version,
        published_at=str(data.get("published_at", "")),
        min_app_version=min_app,
        language_folder=lang,
        notes=notes if isinstance(notes, str) else "",
        channels=channels,
        raw=raw,
        signature_status=signature_status,
    )


def verify_signature(raw: bytes, signature: bytes | None, cfg: AppConfig) -> str:
    """Comprueba la firma Ed25519. Devuelve "firmado" o "sin firma"; lanza ManifestError si falla."""
    if not cfg.signing_public_key:
        if cfg.require_signature:
            raise ManifestError("No hay clave pública para comprobar la firma.")
        return "sin firma"
    if signature is None:
        if cfg.require_signature:
            raise ManifestError("La publicación no está firmada. Por seguridad no se instalará.")
        return "sin firma"
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(cfg.signing_public_key, validate=True))
        sig = base64.b64decode(signature.strip(), validate=True)
        pub.verify(sig, raw)
    except (InvalidSignature, binascii.Error, ValueError) as e:
        raise ManifestError(
            "La firma de la publicación no es válida. Por seguridad no se instalará.",
            detail=repr(e),
        ) from e
    return "firmado"


def sign_manifest(raw: bytes, private_key_b64: str) -> bytes:
    """Usado por la herramienta de publicación (no por el gestor)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64.strip(), validate=True))
    return base64.b64encode(key.sign(raw)) + b"\n"
