"""Aviso para los jugadores publicado en el repositorio (archivo AVISO.txt).

El mantenedor escribe el texto en GitHub y todos los gestores abiertos lo muestran entre el titular y la lista
de canales. Formato del archivo (UTF-8):

    # Las líneas que empiezan por # no se muestran.
    [PTU] Trabajando en la versión PTU 5.0
    [LIVE] CANAL LIVE: NUEVA VERSIÓN EN CAMINO...
    Texto sin canal (color neutro)

Se muestran como texto plano (nunca HTML ni enlaces), como máximo MAX_LINES líneas de MAX_CHARS caracteres.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MAX_LINES = 4
MAX_CHARS = 160
MAX_BYTES = 8 * 1024

_TAG_RE = re.compile(r"^\[\s*([A-Za-z-]{2,20})\s*\]\s*(.*)$")


@dataclass(frozen=True)
class NoticeLine:
    text: str
    channel: str | None = None   # LIVE, PTU… para pintar la línea con el color del canal


def _clean(text: str) -> str:
    text = "".join(" " if unicodedata.category(c).startswith("C") else c for c in text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_CHARS].rstrip() + ("…" if len(text) > MAX_CHARS else "")


def parse_notice(data: bytes, channels: tuple[str, ...]) -> list[NoticeLine]:
    if not data or len(data) > MAX_BYTES:
        return []
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return []
    known = {c.upper(): c for c in channels}
    out: list[NoticeLine] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        channel = None
        m = _TAG_RE.match(line)
        if m and m.group(1).upper() in known:
            channel, line = known[m.group(1).upper()], m.group(2)
        line = _clean(line)
        if line:
            out.append(NoticeLine(line, channel))
        if len(out) >= MAX_LINES:
            break
    return out
