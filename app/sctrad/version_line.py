"""Línea de versión de la traducción dentro de global.ini.

Formato: Personal_Translation_Version=Traduccion 0zzyt0 <CANAL> v<X.Y>
Ejemplos: «Traduccion 0zzyt0 PTU v5.0», «Traducción 0zzyt0 LIVE v4.10».
"""

from __future__ import annotations

import re
from pathlib import Path

KEY = "Personal_Translation_Version"
_LINE_RE = re.compile(rb"(?:^|\n)Personal_Translation_Version(?:,P)?=([^\r\n]{0,200})")
LABEL_RE = re.compile(r"^Traducci(?:o|ó)n\s+0zzyt0\s+(LIVE|HOTFIX|PTU|EPTU|TECH-PREVIEW)\s+v(\d+(?:\.\d+){1,3})\s*$",
                      re.IGNORECASE)
AUTHOR_MARK = "0zzyt0"


def read_label_bytes(data: bytes) -> str | None:
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    m = _LINE_RE.search(data)
    if not m:
        return None
    return m.group(1).decode("utf-8", errors="replace").strip() or None


def read_label(path: Path) -> str | None:
    """Lee la línea de versión del global.ini indicado (None si no existe o no la tiene)."""
    try:
        return read_label_bytes(Path(path).read_bytes())
    except OSError:
        return None


def parse_label(label: str | None) -> tuple[str, str] | None:
    """«Traduccion 0zzyt0 PTU v5.0» -> ("PTU", "5.0")."""
    if not label:
        return None
    m = LABEL_RE.match(label.strip())
    return (m.group(1).upper(), m.group(2)) if m else None


def is_ours(label: str | None) -> bool:
    return bool(label and AUTHOR_MARK in label)


def short(label: str | None) -> str:
    """Texto corto para la interfaz: «PTU v5.0»."""
    p = parse_label(label)
    if p:
        return f"{p[0]} v{p[1]}"
    return label or "—"
