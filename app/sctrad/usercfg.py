"""Edición conservadora de user.cfg: solo se tocan las líneas que gestionamos."""

from __future__ import annotations

import re

_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")
_BOM = "﻿"


class CfgText:
    def __init__(self, raw: bytes | None):
        self.had_bom = False
        if raw is None:
            self.lines: list[str] = []
            self.newline = "\r\n"
            self.trailing_newline = True
            return
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        if text.startswith(_BOM):
            self.had_bom = True
            text = text[1:]
        self.newline = "\r\n" if "\r\n" in text else ("\n" if "\n" in text else "\r\n")
        self.trailing_newline = text.endswith(("\n", "\r"))
        self.lines = text.splitlines()

    def get(self, key: str) -> str | None:
        val = None
        for line in self.lines:
            m = _LINE_RE.match(line)
            if m and m.group(1).lower() == key.lower() and not line.lstrip().startswith((";", "--", "#")):
                val = m.group(2)
        return val

    def set(self, key: str, value: str) -> None:
        new_line = f"{key} = {value}"
        replaced = False
        for i, line in enumerate(self.lines):
            m = _LINE_RE.match(line)
            if m and m.group(1).lower() == key.lower():
                self.lines[i] = new_line
                replaced = True
        if not replaced:
            self.lines.append(new_line)

    def remove(self, key: str, only_value: str | None = None) -> None:
        out = []
        for line in self.lines:
            m = _LINE_RE.match(line)
            if m and m.group(1).lower() == key.lower() and (only_value is None or m.group(2) == only_value):
                continue
            out.append(line)
        self.lines = out

    def to_bytes(self) -> bytes:
        text = self.newline.join(self.lines)
        if self.lines and self.trailing_newline:
            text += self.newline
        if self.had_bom:
            text = _BOM + text
        return text.encode("utf-8")


def apply_settings(raw: bytes | None, settings: dict[str, str],
                   only_if_absent: tuple[str, ...] = ()) -> tuple[bytes, dict[str, str | None]]:
    """Aplica los ajustes. Devuelve (bytes nuevos, {clave: valor anterior o None}) solo de lo cambiado."""
    cfg = CfgText(raw)
    changes: dict[str, str | None] = {}
    for key, value in settings.items():
        old = cfg.get(key)
        if key in only_if_absent and old is not None:
            continue
        if old == value:
            continue
        cfg.set(key, value)
        changes[key] = old
    return cfg.to_bytes(), changes


def revert_settings(raw: bytes, ours: dict[str, str], previous: dict[str, str | None]) -> bytes:
    """Deshace nuestros cambios si el valor actual sigue siendo el nuestro."""
    cfg = CfgText(raw)
    for key, prev in previous.items():
        current = cfg.get(key)
        if current != ours.get(key):
            continue  # el jugador lo cambió después: se respeta
        if prev is None:
            cfg.remove(key)
        else:
            cfg.set(key, prev)
    return cfg.to_bytes()


def get_setting(raw: bytes | None, key: str) -> str | None:
    if raw is None:
        return None
    return CfgText(raw).get(key)
