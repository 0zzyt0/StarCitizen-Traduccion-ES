"""Descarga verificada (tamaño + SHA-256) con reanudación de descargas parciales."""

from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path
from typing import Callable

from .errors import IntegrityError, NetworkError, SCTradError
from .fsutil import sha256_file
from .net import Http

ProgressCb = Callable[[int, int], None]


class Cancelled(SCTradError):
    pass


def download_verified(http: Http, url: str, dest: Path, expected_size: int, expected_sha256: str,
                      progress: ProgressCb | None = None, cancel: threading.Event | None = None) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.stat().st_size == expected_size and sha256_file(dest) == expected_sha256:
            if progress:
                progress(expected_size, expected_size)
            return dest
        dest.unlink()
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > expected_size:
        part.unlink()
        have = 0
    h = hashlib.sha256()
    headers = {"Accept": "application/octet-stream"}
    if 0 < have < expected_size:
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        headers["Range"] = f"bytes={have}-"
    elif have == expected_size:
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    if have < expected_size:
        resp = http.open(url, headers)
        try:
            if have and resp.status != 206:
                # El servidor no admite reanudar: empezar de cero.
                have = 0
                h = hashlib.sha256()
                mode = "wb"
            else:
                mode = "ab" if have else "wb"
            with open(part, mode) as f:
                done = have
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled("Descarga cancelada.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > expected_size:
                        raise IntegrityError("El archivo descargado es más grande de lo que indica el manifiesto.")
                    f.write(chunk)
                    h.update(chunk)
                    if progress:
                        progress(done, expected_size)
                f.flush()
                os.fsync(f.fileno())
        except IntegrityError:
            _unlink(part)
            raise
        except OSError as e:
            raise NetworkError("La descarga se interrumpió. Se reanudará en el próximo intento.", detail=repr(e)) from e
        finally:
            resp.close()
    size = part.stat().st_size
    if size != expected_size:
        raise NetworkError(
            f"Descarga incompleta ({size} de {expected_size} bytes). Se reanudará en el próximo intento."
        )
    if h.hexdigest() != expected_sha256:
        _unlink(part)
        raise IntegrityError("El archivo descargado está dañado (la suma SHA-256 no coincide). Se ha descartado.")
    os.replace(part, dest)
    return dest


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass
