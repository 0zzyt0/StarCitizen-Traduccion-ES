"""Comparación numérica de versiones (nunca lexicográfica: 1.10 > 1.9)."""

from __future__ import annotations

import re

_VER_RE = re.compile(r"^\d{1,9}(\.\d{1,9}){0,5}$")


def parse_version(text: str) -> tuple[int, ...]:
    t = (text or "").strip()
    if t[:1] in ("v", "V"):
        t = t[1:]
    if not _VER_RE.match(t):
        raise ValueError(f"Versión no válida: {text!r}")
    return tuple(int(p) for p in t.split("."))


def is_valid_version(text: str) -> bool:
    try:
        parse_version(text)
        return True
    except ValueError:
        return False


def compare_versions(a: str, b: str) -> int:
    """-1 si a<b, 0 si iguales, 1 si a>b. Rellena con ceros (1.2 == 1.2.0)."""
    pa, pb = parse_version(a), parse_version(b)
    n = max(len(pa), len(pb))
    pa += (0,) * (n - len(pa))
    pb += (0,) * (n - len(pb))
    return (pa > pb) - (pa < pb)


def is_newer(candidate: str, current: str | None) -> bool:
    if not current:
        return True
    try:
        return compare_versions(candidate, current) > 0
    except ValueError:
        # Versión local corrupta: se considera que hay que actualizar.
        return True


def version_from_tag(tag: str, prefix: str) -> str | None:
    if not tag or not tag.startswith(prefix):
        return None
    v = tag[len(prefix):]
    return v if is_valid_version(v) else None
