"""Cliente HTTPS mínimo: solo servidores permitidos, reintentos y redirecciones validadas."""

from __future__ import annotations

import json
import logging
import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlparse

from . import __version__
from .errors import NetworkError, RateLimitError

log = logging.getLogger(__name__)


class Response(Protocol):
    status: int
    headers: dict

    def read(self, n: int = -1) -> bytes: ...
    def close(self) -> None: ...


@dataclass
class SimpleResponse:
    status: int
    headers: dict
    _body: object  # objeto con read()/close()

    def read(self, n: int = -1) -> bytes:
        return self._body.read(n)

    def close(self) -> None:
        try:
            self._body.close()
        except Exception:  # noqa: BLE001
            pass


def check_url(url: str, allowed_hosts: tuple[str, ...]) -> None:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https" or host not in allowed_hosts:
        raise NetworkError(f"Conexión bloqueada: el servidor «{host or url}» no está permitido.")


class _ValidatingRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl, self.allowed_hosts)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlparse(newurl).hostname != urlparse(req.full_url).hostname:
            # No reenviar cabeceras propias de la API a otros servidores.
            for h in ("Authorization", "If-none-match", "If-None-Match"):
                new.headers.pop(h, None)
                new.unredirected_hdrs.pop(h, None)
        return new


class Http:
    """Peticiones GET con reintentos y espera exponencial."""

    def __init__(self, allowed_hosts: tuple[str, ...], timeout: float = 25.0, retries: int = 3,
                 sleep: Callable[[float], None] = time.sleep, opener=None):
        self.allowed_hosts = tuple(h.lower() for h in allowed_hosts)
        self.timeout = timeout
        self.retries = retries
        self.sleep = sleep
        if opener is None:
            ctx = ssl.create_default_context()
            opener = urllib.request.build_opener(
                urllib.request.HTTPSHandler(context=ctx),
                _ValidatingRedirect(self.allowed_hosts),
            )
        self.opener = opener
        self.user_agent = f"SC-Traduccion-ES/{__version__}"

    def open(self, url: str, headers: dict | None = None) -> Response:
        check_url(url, self.allowed_hosts)
        hdrs = {"User-Agent": self.user_agent}
        hdrs.update(headers or {})
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, headers=hdrs, method="GET")
            try:
                resp = self.opener.open(req, timeout=self.timeout)
                final = resp.geturl() if hasattr(resp, "geturl") else url
                check_url(final, self.allowed_hosts)
                return SimpleResponse(getattr(resp, "status", 200), {k.lower(): v for k, v in resp.headers.items()}, resp)
            except urllib.error.HTTPError as e:
                hd = {k.lower(): v for k, v in (e.headers or {}).items()}
                if e.code == 304:
                    return SimpleResponse(304, hd, e)
                if e.code in (403, 429) and (hd.get("x-ratelimit-remaining") == "0" or e.code == 429):
                    reset = hd.get("x-ratelimit-reset")
                    when = ""
                    if reset and reset.isdigit():
                        when = " Se podrá volver a consultar a las " + time.strftime("%H:%M", time.localtime(int(reset))) + "."
                    if e.code == 429 and attempt < self.retries:
                        self.sleep(min(30, 2 ** attempt * 2))
                        continue
                    raise RateLimitError("GitHub ha limitado temporalmente las consultas." + when) from e
                if 500 <= e.code < 600 and attempt < self.retries:
                    last_exc = e
                    self.sleep(2 ** attempt)
                    continue
                if e.code == 404:
                    raise NetworkError("No se ha encontrado el recurso en GitHub (404). ¿Existe el repositorio y es público?") from e
                raise NetworkError(f"GitHub respondió con un error ({e.code}).") from e
            except NetworkError:
                raise
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, ssl.SSLError) as e:
                last_exc = e
                if attempt < self.retries:
                    self.sleep(2 ** attempt)
                    continue
        raise NetworkError(
            "No se puede conectar con GitHub. Comprueba tu conexión a Internet.", detail=repr(last_exc)
        )

    def get_json(self, url: str, etag: str | None = None, max_bytes: int = 4 * 1024 * 1024):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if etag:
            headers["If-None-Match"] = etag
        resp = self.open(url, headers)
        try:
            if resp.status == 304:
                return 304, None, resp.headers.get("etag", etag)
            body = resp.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise NetworkError("La respuesta de GitHub es demasiado grande.")
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                raise NetworkError("GitHub devolvió una respuesta no válida.") from e
            return resp.status, data, resp.headers.get("etag")
        finally:
            resp.close()

    def get_bytes(self, url: str, max_bytes: int) -> bytes:
        resp = self.open(url, {"Accept": "application/octet-stream"})
        try:
            body = resp.read(max_bytes + 1)
        finally:
            resp.close()
        if len(body) > max_bytes:
            raise NetworkError("El archivo descargado es más grande de lo esperado.")
        return body
