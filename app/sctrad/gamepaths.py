"""Detección y validación de instalaciones de Star Citizen y de su versión."""

from __future__ import annotations

import json
import os
import re
import string
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig

COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
UNVERIFIED = "unverified"

COMPAT_LABELS = {
    COMPATIBLE: "Compatible",
    INCOMPATIBLE: "No compatible",
    UNVERIFIED: "Compatibilidad no verificada",
}


@dataclass(frozen=True)
class GameInstall:
    path: str          # carpeta del canal, p. ej. C:\...\StarCitizen\LIVE
    channel: str       # LIVE, PTU, ...
    game_version: str | None = None   # "4.3.2" si se pudo leer
    build: str | None = None          # número de compilación si se pudo leer

    @property
    def key(self) -> str:
        return install_key(self.path)

    @property
    def label(self) -> str:
        return f"{self.channel} — {self.path}"


def install_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def is_valid_channel_dir(path: Path) -> bool:
    """Una carpeta de canal válida contiene Data.p4k o Bin64/StarCitizen.exe."""
    try:
        if not path.is_dir():
            return False
        return (path / "Data.p4k").is_file() or (path / "Bin64" / "StarCitizen.exe").is_file()
    except OSError:
        return False


_BRANCH_VER_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def read_game_version(channel_dir: Path) -> tuple[str | None, str | None]:
    """Lee build_manifest.id (JSON) si existe. Devuelve (versión, compilación)."""
    f = channel_dir / "build_manifest.id"
    try:
        if not f.is_file() or f.stat().st_size > 256 * 1024:
            return None, None
        data = json.loads(f.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, ValueError):
        return None, None
    d = data.get("Data", data) if isinstance(data, dict) else {}
    if not isinstance(d, dict):
        return None, None
    version = None
    for key in ("Branch", "Version", "Tag"):
        val = d.get(key)
        if isinstance(val, str):
            m = _BRANCH_VER_RE.search(val)
            if m:
                version = m.group(1)
                break
    build = d.get("RequestedP4ChangeNum") or d.get("BuildId")
    return version, (str(build) if build else None)


def make_install(channel_dir: Path, channel: str) -> GameInstall:
    ver, build = read_game_version(channel_dir)
    return GameInstall(str(channel_dir), channel, ver, build)


def normalize_user_path(path: str | Path, cfg: AppConfig) -> list[GameInstall]:
    """Convierte una carpeta elegida por el jugador en instalaciones válidas.

    Acepta la carpeta del canal (…\\LIVE), la carpeta StarCitizen que contiene canales,
    o una subcarpeta del canal (por ejemplo …\\LIVE\\data).
    """
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        return []
    found: list[GameInstall] = []
    # ¿Es (o está dentro de) una carpeta de canal?
    for candidate in [p, *p.parents][:4]:
        name = candidate.name.upper()
        if name in cfg.channels and is_valid_channel_dir(candidate):
            return [make_install(candidate, name)]
    # ¿Contiene carpetas de canal?
    for ch in cfg.channels:
        sub = p / ch
        if is_valid_channel_dir(sub):
            found.append(make_install(sub, ch))
    return found


def _windows_drives() -> list[str]:
    if os.name != "nt":
        return []
    return [f"{d}:" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def _log_path_re(channels) -> re.Pattern:
    alts = "|".join(re.escape(c) for c in sorted(channels, key=len, reverse=True))
    return re.compile(r"([A-Za-z]:[\\/][^\"\r\n<>|*?]*?StarCitizen)[\\/]+(" + alts + r")\b", re.IGNORECASE)


def roots_from_launcher_logs(cfg: AppConfig) -> list[Path]:
    roots: list[Path] = []
    for raw in cfg.launcher_logs:
        f = Path(os.path.expandvars(raw))
        try:
            if not f.is_file():
                continue
            size = f.stat().st_size
            with f.open("rb") as fh:
                if size > 4 * 1024 * 1024:
                    fh.seek(size - 4 * 1024 * 1024)
                text = fh.read().decode("utf-8", errors="replace")
        except OSError:
            continue
        text = text.replace("\\\\", "\\")
        for m in _log_path_re(cfg.channels).finditer(text):
            r = Path(m.group(1))
            if r not in roots:
                roots.append(r)
    return roots


def candidate_roots(cfg: AppConfig) -> list[Path]:
    roots: list[Path] = []
    for drive in _windows_drives():
        for pattern in cfg.search_roots:
            roots.append(Path(pattern.replace("{drive}", drive)))
    for r in roots_from_launcher_logs(cfg):
        if r not in roots:
            roots.append(r)
    return roots


def detect_installs(cfg: AppConfig, extra_roots: list[Path] | None = None) -> list[GameInstall]:
    seen: set[str] = set()
    result: list[GameInstall] = []
    for root in [*(extra_roots or []), *candidate_roots(cfg)]:
        for ch in cfg.channels:
            d = root / ch
            if is_valid_channel_dir(d):
                k = install_key(str(d))
                if k not in seen:
                    seen.add(k)
                    result.append(make_install(d, ch))
    return result


def check_compat(game_version: str | None, patterns: tuple[str, ...] | list[str]) -> str:
    """Compara la versión del juego con las declaradas en el manifiesto.

    Un patrón "4.3" acepta 4.3, 4.3.0, 4.3.2…; "*" o lista vacía = sin declarar.
    """
    if not game_version:
        return UNVERIFIED
    pats = [p for p in patterns if p]
    if not pats or "*" in pats:
        return UNVERIFIED
    try:
        gv = [int(x) for x in game_version.split(".")]
    except ValueError:
        return UNVERIFIED
    for p in pats:
        try:
            pp = [int(x) for x in p.split(".")]
        except ValueError:
            continue
        if gv[: len(pp)] == pp:
            return COMPATIBLE
    return INCOMPATIBLE
