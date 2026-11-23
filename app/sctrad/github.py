"""Consulta de publicaciones (GitHub Releases) del repositorio de la traducción."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field

from .config import AppConfig
from .errors import NetworkError, NotFoundError
from .net import Http
from .version import compare_versions, version_from_tag

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int


@dataclass
class Release:
    tag: str
    version: str
    name: str
    body: str
    published_at: str
    prerelease: bool
    html_url: str
    assets: dict[str, Asset] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tag": self.tag, "version": self.version, "name": self.name, "body": self.body,
            "published_at": self.published_at, "prerelease": self.prerelease, "html_url": self.html_url,
            "assets": {k: {"name": a.name, "url": a.url, "size": a.size} for k, a in self.assets.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Release":
        return cls(d["tag"], d["version"], d.get("name", ""), d.get("body", ""), d.get("published_at", ""),
                   bool(d.get("prerelease")), d.get("html_url", ""),
                   {k: Asset(a["name"], a["url"], int(a["size"])) for k, a in d.get("assets", {}).items()})


def _parse_release(raw: dict, prefix: str) -> Release | None:
    if not isinstance(raw, dict) or raw.get("draft"):
        return None
    tag = raw.get("tag_name") or ""
    version = version_from_tag(tag, prefix)
    if not version:
        return None
    assets: dict[str, Asset] = {}
    for a in raw.get("assets") or []:
        if not isinstance(a, dict):
            continue
        if a.get("state", "uploaded") != "uploaded":
            continue  # subida incompleta
        name, url, size = a.get("name"), a.get("browser_download_url"), a.get("size")
        if isinstance(name, str) and isinstance(url, str) and isinstance(size, int):
            assets[name] = Asset(name, url, size)
    return Release(tag, version, str(raw.get("name") or tag), str(raw.get("body") or ""),
                   str(raw.get("published_at") or ""), bool(raw.get("prerelease")),
                   str(raw.get("html_url") or ""), assets)


class ReleaseClient:
    def __init__(self, cfg: AppConfig, http: Http, cache: dict | None = None):
        self.cfg = cfg
        self.http = http
        self.cache = cache if cache is not None else {}

    @property
    def _base(self) -> str:
        return f"{self.cfg.api_base}/repos/{self.cfg.github_owner}/{self.cfg.github_repo}"

    def _get_cached(self, url: str):
        entry = self.cache.get(url) or {}
        status, data, etag = self.http.get_json(url, entry.get("etag"))
        if status == 304 and "data" in entry:
            return entry["data"]
        if status == 304:
            status, data, etag = self.http.get_json(url, None)
        self.cache[url] = {"etag": etag, "data": data}
        # Limitar el tamaño de la caché.
        if len(self.cache) > 8:
            for k in list(self.cache)[:-8]:
                self.cache.pop(k, None)
        return data

    def _list(self, prefix: str, include_prerelease: bool) -> Release | None:
        data = self._get_cached(f"{self._base}/releases?per_page=30")
        if not isinstance(data, list):
            raise NetworkError("GitHub devolvió una lista de publicaciones no válida.")
        best: Release | None = None
        for raw in data:
            rel = _parse_release(raw, prefix)
            if not rel or (rel.prerelease and not include_prerelease):
                continue
            if best is None or compare_versions(rel.version, best.version) > 0:
                best = rel
        return best

    def latest_translation(self, include_prerelease: bool = False) -> Release | None:
        """Última traducción publicada (no borradores; prereleases solo en el canal beta).

        La publicación marcada como «Latest» del repositorio es el INSTALADOR (para que los jugadores lo
        encuentren a primera vista), así que la traducción se busca en la lista filtrando por etiqueta y
        ordenando por versión numérica. Una sola petición, con caché ETag.
        """
        return self._list(self.cfg.translation_tag_prefix, include_prerelease)

    def latest_app(self) -> Release | None:
        return self._list(self.cfg.app_tag_prefix, False)

    def notice(self) -> bytes:
        """Contenido del archivo de aviso del repositorio (rama principal). b"" si no existe.
        Usa la API de contenidos con ETag: si no ha cambiado, GitHub responde 304 y no gasta cuota."""
        if not self.cfg.notice_path:
            return b""
        try:
            data = self._get_cached(f"{self._base}/contents/{self.cfg.notice_path}")
        except NotFoundError:
            return b""
        if not isinstance(data, dict) or data.get("type") != "file" or data.get("encoding") != "base64":
            raise NetworkError("GitHub devolvió un aviso no válido.")
        if int(data.get("size") or 0) > 8 * 1024:
            return b""
        try:
            return base64.b64decode(data.get("content") or "")
        except ValueError as e:
            raise NetworkError("GitHub devolvió un aviso no válido.") from e

    def download_small(self, asset: Asset, max_bytes: int = 1024 * 1024) -> bytes:
        if asset.size > max_bytes:
            raise NetworkError(f"El archivo {asset.name} es demasiado grande.")
        return self.http.get_bytes(asset.url, max_bytes)
