"""Carga de la configuración del gestor y rutas de datos de la aplicación."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError


def resource_path(*parts: str) -> Path:
    """Ruta a un recurso empaquetado (funciona en desarrollo y con PyInstaller)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base, *parts)
    return Path(__file__).resolve().parents[2].joinpath(*parts)


def default_data_dir(app_id: str = "SC-Traduccion-ES") -> Path:
    """Carpeta de datos del usuario (estado, copias, registros, descargas)."""
    override = os.environ.get("SCTRAD_DATA_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / app_id
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / app_id.lower()


_CHANNEL_RE = re.compile(r"^[A-Z][A-Z0-9-]{1,20}$")
_LANG_RE = re.compile(r"^[a-z]+(_\([a-z_]+\))?$")
_HOST_RE = re.compile(r"^[a-z0-9.-]+$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class AppConfig:
    app_id: str
    app_name: str
    github_owner: str
    github_repo: str
    translation_tag_prefix: str
    app_tag_prefix: str
    manifest_asset: str
    manifest_signature_asset: str
    signing_public_key: str
    require_signature: bool
    language_folder: str
    user_cfg_settings: dict[str, str]
    user_cfg_only_if_absent: tuple[str, ...]
    channels: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    game_process_names: tuple[str, ...]
    search_roots: tuple[str, ...]
    launcher_logs: tuple[str, ...]
    default_check_interval_hours: int = 24
    max_backups_per_install: int = 5
    max_payload_bytes: int = 200 * 1024 * 1024
    scheduled_task_name: str = "SC-Traduccion-ES Actualizador"
    api_base: str = "https://api.github.com"
    extra: dict = field(default_factory=dict)

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.github_owner}/{self.github_repo}"

    @property
    def releases_url(self) -> str:
        return f"{self.repo_url}/releases"

    @property
    def translation_rel_path(self) -> str:
        """Ruta relativa (con '/') del archivo de traducción dentro de un canal."""
        return f"data/Localization/{self.language_folder}/global.ini"

    @property
    def user_cfg_rel_path(self) -> str:
        return "user.cfg"


def _require(d: dict, key: str, typ):
    if key not in d:
        raise ConfigError(f"Falta «{key}» en la configuración.")
    val = d[key]
    if not isinstance(val, typ):
        raise ConfigError(f"El valor de «{key}» en la configuración no es válido.")
    return val


def load_config(path: str | Path | None = None) -> AppConfig:
    p = Path(path) if path else resource_path("config", "app_config.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"No se encuentra la configuración: {p}") from e
    except (OSError, ValueError) as e:
        raise ConfigError(f"No se puede leer la configuración ({p}): {e}") from e
    return config_from_dict(data)


def config_from_dict(data: dict) -> AppConfig:
    if data.get("schema") != 1:
        raise ConfigError("Versión de configuración no compatible.")
    owner = _require(data, "github_owner", str)
    repo = _require(data, "github_repo", str)
    if not owner or not repo or not _NAME_RE.match(owner) or not _NAME_RE.match(repo):
        raise ConfigError("Configura «github_owner» y «github_repo» con valores válidos.")
    channels = tuple(_require(data, "channels", list))
    if not channels or any(not isinstance(c, str) or not _CHANNEL_RE.match(c) for c in channels):
        raise ConfigError("La lista de canales del juego no es válida.")
    lang = _require(data, "language_folder", str)
    if not _LANG_RE.match(lang):
        raise ConfigError("El nombre de la carpeta de idioma no es válido.")
    hosts = tuple(h.lower() for h in _require(data, "allowed_hosts", list))
    if any(not _HOST_RE.match(h) for h in hosts) or "api.github.com" not in hosts:
        raise ConfigError("La lista de servidores permitidos no es válida.")
    settings = _require(data, "user_cfg_settings", dict)
    for k, v in settings.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k) or not isinstance(v, str) or "\n" in v:
            raise ConfigError("Los ajustes de user.cfg no son válidos.")
    for name in (data.get("manifest_asset", ""), data.get("manifest_signature_asset", "")):
        if not _NAME_RE.match(name or ""):
            raise ConfigError("Nombre de archivo del manifiesto no válido.")
    require_sig = bool(data.get("require_signature", True))
    pub = data.get("signing_public_key", "") or ""
    if require_sig and not pub:
        raise ConfigError("Se exige firma pero no hay clave pública configurada.")
    return AppConfig(
        app_id=_require(data, "app_id", str),
        app_name=_require(data, "app_name", str),
        github_owner=owner,
        github_repo=repo,
        translation_tag_prefix=_require(data, "translation_tag_prefix", str),
        app_tag_prefix=_require(data, "app_tag_prefix", str),
        manifest_asset=data["manifest_asset"],
        manifest_signature_asset=data["manifest_signature_asset"],
        signing_public_key=pub,
        require_signature=require_sig,
        language_folder=lang,
        user_cfg_settings=dict(settings),
        user_cfg_only_if_absent=tuple(data.get("user_cfg_only_if_absent", [])),
        channels=channels,
        allowed_hosts=hosts,
        game_process_names=tuple(data.get("game_process_names", ["StarCitizen.exe"])),
        search_roots=tuple(data.get("search_roots", [])),
        launcher_logs=tuple(data.get("launcher_logs", [])),
        default_check_interval_hours=int(data.get("default_check_interval_hours", 24)),
        max_backups_per_install=max(1, int(data.get("max_backups_per_install", 5))),
        max_payload_bytes=int(data.get("max_payload_bytes", 200 * 1024 * 1024)),
        scheduled_task_name=str(data.get("scheduled_task_name", "SC-Traduccion-ES Actualizador")),
        api_base=str(data.get("api_base", "https://api.github.com")),
    )
