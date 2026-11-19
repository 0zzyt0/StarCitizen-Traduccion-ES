"""Utilidades de archivos seguras: rutas confinadas, escritura atómica y hashes."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import time
from pathlib import Path, PurePosixPath

from .errors import InstallError, PermissionNeededError, UnsafePathError

FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_link_or_reparse(p: Path) -> bool:
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def safe_target(base: Path, rel: str) -> Path:
    """Une base + rel garantizando que el resultado queda dentro de base.

    Rechaza rutas absolutas, '..', unidades, y enlaces simbólicos o puntos de
    reanálisis en cualquier componente bajo base.
    """
    if not rel or "\\" in rel or ":" in rel or "\x00" in rel:
        raise UnsafePathError(f"Ruta no permitida: {rel!r}")
    pp = PurePosixPath(rel)
    if pp.is_absolute() or any(part in ("..", ".", "") for part in pp.parts):
        raise UnsafePathError(f"Ruta no permitida: {rel!r}")
    base = Path(base)
    if _is_link_or_reparse(base):
        raise UnsafePathError("La carpeta del juego es un enlace simbólico; no se escribirá en ella.")
    cur = base
    for part in pp.parts:
        cur = cur / part
        if _is_link_or_reparse(cur):
            raise UnsafePathError(f"Se ha encontrado un enlace simbólico en {cur}; no se escribirá en él.")
    try:
        resolved_base = base.resolve()
        resolved = cur.resolve()
    except OSError as e:
        raise UnsafePathError(f"No se puede resolver la ruta {cur}.") from e
    if resolved_base != resolved and resolved_base not in resolved.parents:
        raise UnsafePathError(f"La ruta {cur} queda fuera de la carpeta del juego.")
    return cur


def _retry_replace(src: Path, dst: Path, attempts: int = 5) -> None:
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            # En Windows el antivirus o el indexador pueden bloquear el archivo un instante.
            if i == attempts - 1:
                raise
            time.sleep(0.4 * (i + 1))


def atomic_write_bytes(dst: Path, data: bytes) -> None:
    dst = Path(dst)
    tmp = dst.with_name(f".{dst.name}.sctrad-tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _retry_replace(tmp, dst)
    except PermissionError as e:
        _silent_unlink(tmp)
        raise PermissionNeededError(
            f"Windows no permite escribir en {dst.parent}. Hacen falta permisos de administrador.",
            detail=repr(e),
        ) from e
    except OSError as e:
        _silent_unlink(tmp)
        raise InstallError(f"No se pudo escribir {dst}: {e.strerror or e}", detail=repr(e)) from e


def atomic_copy(src: Path, dst: Path) -> None:
    dst = Path(dst)
    tmp = dst.with_name(f".{dst.name}.sctrad-tmp")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            shutil.copyfileobj(fi, fo, 1024 * 1024)
            fo.flush()
            os.fsync(fo.fileno())
        _retry_replace(tmp, dst)
    except PermissionError as e:
        _silent_unlink(tmp)
        raise PermissionNeededError(
            f"Windows no permite escribir en {dst.parent}. Hacen falta permisos de administrador.",
            detail=repr(e),
        ) from e
    except OSError as e:
        _silent_unlink(tmp)
        raise InstallError(f"No se pudo copiar a {dst}: {e.strerror or e}", detail=repr(e)) from e


def ensure_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        raise PermissionNeededError(
            f"Windows no permite crear la carpeta {path}. Hacen falta permisos de administrador.",
            detail=repr(e),
        ) from e
    except OSError as e:
        raise InstallError(f"No se pudo crear la carpeta {path}: {e.strerror or e}") from e


def is_writable_now(path: Path) -> bool:
    """True si el archivo no existe o se puede abrir para escritura (no está bloqueado)."""
    if not path.exists():
        return True
    try:
        with open(path, "r+b"):
            return True
    except OSError:
        return False


def free_space(path: Path) -> int:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def _silent_unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass
