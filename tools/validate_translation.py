#!/usr/bin/env python3
"""Valida los archivos de traducción antes de publicarlos. NUNCA modifica los archivos.

Uso:
  python tools/validate_translation.py --root traduccion --config config/app_config.json [--referencia referencia]

Comprueba en cada traduccion/<CANAL>/global.ini:
  - codificación UTF-8 (avisa si falta el BOM), sin bytes nulos, tamaño razonable;
  - formato CLAVE=valor en cada línea, claves no vacías y sin espacios, sin claves repetidas;
  - regla «sin tildes» (configurable en traduccion/validacion.json);
  - si existe referencia/<CANAL>/global.ini (inglés original): claves que faltan y marcadores
    protegidos (~mision(...), <etiquetas>, %ls/%s/%d, {variables}, \\n) que falten en la traducción.
  - traduccion/compatibilidad.json bien formado.

Escribe «hay_archivos=true|false» en $GITHUB_OUTPUT. Sale con código 1 si hay errores.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_RULES = {
    "sin_tildes": True,
    "claves_faltantes": "error",     # error | aviso | ignorar (requiere referencia/)
    "marcadores_faltantes": "error",  # error | aviso | ignorar (requiere referencia/)
    "minimo_lineas": 100,
}
ACCENTS_RE = re.compile(r"[áéíóúÁÉÍÓÚ]")
TOKEN_RE = re.compile(r"~\w+\([^)]*\)|<[^<>\s][^<>]*>|%(?:ls|s|d|i|u|f|S|\.\d+f)|\{[^{}]*\}|\\n")
GAMEVER_RE = re.compile(r"^(\*|\d{1,4}(\.\d{1,6}){0,3})$")
KEY_RE = re.compile(r"^[^\s=]+$")


class Report:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.info: list[str] = []

    def error(self, msg: str, file: str | None = None):
        self.errors.append(msg)
        print(f"::error{' file=' + file if file else ''}::{msg}")

    def warn(self, msg: str, file: str | None = None):
        self.warnings.append(msg)
        print(f"::warning{' file=' + file if file else ''}::{msg}")

    def note(self, msg: str):
        self.info.append(msg)
        print(msg)


def parse_ini(data: bytes, rep: Report, label: str, strict: bool = True) -> dict[str, str] | None:
    if b"\x00" in data:
        rep.error(f"{label}: contiene bytes nulos (¿guardado como UTF-16?).", label)
        return None
    has_bom = data.startswith(b"\xef\xbb\xbf")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        rep.error(f"{label}: no es UTF-8 válido (byte {e.start}). Guárdalo como UTF-8 con BOM.", label)
        return None
    if strict and not has_bom:
        rep.warn(f"{label}: no tiene BOM UTF-8; el juego suele esperar «UTF-8 con BOM».", label)
    entries: dict[str, str] = {}
    dupes: list[str] = []
    bad: list[int] = []
    empty = 0
    for n, line in enumerate(text.split("\n"), 1):
        line = line[:-1] if line.endswith("\r") else line
        if not line.strip():
            empty += 1
            continue
        if line.lstrip().startswith((";", "#")):
            continue
        if "=" not in line:
            bad.append(n)
            continue
        key, value = line.split("=", 1)
        if not key or not KEY_RE.match(key):
            bad.append(n)
            continue
        if key in entries:
            dupes.append(key)
        entries[key] = value
    if bad and strict:
        rep.error(f"{label}: {len(bad)} línea(s) sin formato CLAVE=valor (p. ej. líneas {bad[:10]}).", label)
    if dupes and strict:
        rep.error(f"{label}: {len(dupes)} clave(s) repetida(s): {', '.join(dupes[:10])}", label)
    if empty > 1 and strict:
        rep.warn(f"{label}: {empty} líneas vacías.", label)
    crlf = text.count("\r\n")
    rep.note(f"{label}: {len(entries)} entradas · saltos {'CRLF' if crlf else 'LF'} · BOM {'sí' if has_bom else 'no'}")
    return entries


def norm_key(k: str) -> str:
    return k[:-2] if k.endswith(",P") else k


def apply_level(rep: Report, level: str, msg: str, label: str):
    if level == "error":
        rep.error(msg, label)
    elif level == "aviso":
        rep.warn(msg, label)


def validate(root: Path, config: dict, referencia: Path | None, rep: Report) -> list[str]:
    rules = dict(DEFAULT_RULES)
    rules_file = root / "validacion.json"
    if rules_file.is_file():
        try:
            rules.update(json.loads(rules_file.read_text(encoding="utf-8")))
        except ValueError as e:
            rep.error(f"validacion.json no es JSON válido: {e}", str(rules_file))
    max_bytes = int(config.get("max_payload_bytes", 200 * 1024 * 1024))
    channels_found: list[str] = []
    for ch in config["channels"]:
        f = root / ch / "global.ini"
        if not f.is_file():
            continue
        label = str(f)
        channels_found.append(ch)
        data = f.read_bytes()
        if not data:
            rep.error(f"{label}: está vacío.", label)
            continue
        if len(data) > max_bytes:
            rep.error(f"{label}: demasiado grande ({len(data)} bytes).", label)
            continue
        entries = parse_ini(data, rep, label)
        if entries is None:
            continue
        if len(entries) < int(rules["minimo_lineas"]):
            rep.error(f"{label}: solo {len(entries)} entradas; parece incompleto.", label)
        if rules.get("sin_tildes"):
            bad = [k for k, v in entries.items() if ACCENTS_RE.search(v)]
            if bad:
                rep.error(f"{label}: {len(bad)} valor(es) con tildes (regla «sin tildes»): {', '.join(bad[:15])}", label)
        ref = (referencia / ch / "global.ini") if referencia else None
        if ref and ref.is_file():
            ref_entries = parse_ini(ref.read_bytes(), rep, str(ref), strict=False) or {}
            es_norm = {norm_key(k): v for k, v in entries.items()}
            en_norm = {norm_key(k): v for k, v in ref_entries.items()}
            missing = [k for k in en_norm if k not in es_norm]
            extra = [k for k in es_norm if k not in en_norm]
            if missing:
                apply_level(rep, rules["claves_faltantes"],
                            f"{label}: faltan {len(missing)} clave(s) del inglés: {', '.join(missing[:15])}", label)
            if extra:
                rep.warn(f"{label}: {len(extra)} clave(s) que el inglés ya no trae: {', '.join(extra[:10])}", label)
            tok_bad = []
            for k, en in en_norm.items():
                es = es_norm.get(k)
                if es is None:
                    continue
                need = Counter(TOKEN_RE.findall(en))
                have = Counter(TOKEN_RE.findall(es))
                if any(have[t] < c for t, c in need.items()):
                    tok_bad.append(k)
            if tok_bad:
                apply_level(rep, rules["marcadores_faltantes"],
                            f"{label}: {len(tok_bad)} entrada(s) con marcadores protegidos que faltan "
                            f"(~mision(), <...>, %ls, {{...}}, \\n): {', '.join(tok_bad[:15])}", label)
        else:
            rep.note(f"{ch}: sin referencia en inglés (referencia/{ch}/global.ini); se omite la comparación.")
    compat = root / "compatibilidad.json"
    if compat.is_file():
        try:
            data = json.loads(compat.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("debe ser un objeto")
            for ch, vers in data.items():
                if ch.startswith("_"):
                    continue
                if ch not in config["channels"] or not isinstance(vers, list) or \
                        any(not isinstance(v, str) or not GAMEVER_RE.match(v) for v in vers):
                    raise ValueError(f"entrada no válida para {ch}")
        except ValueError as e:
            rep.error(f"compatibilidad.json no es válido: {e}", str(compat))
    elif channels_found:
        rep.warn("No existe traduccion/compatibilidad.json: los jugadores verán «Compatibilidad no verificada».")
    return channels_found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="traduccion")
    ap.add_argument("--config", default="config/app_config.json")
    ap.add_argument("--referencia", default="referencia")
    a = ap.parse_args(argv)
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    rep = Report()
    ref = Path(a.referencia) if a.referencia and Path(a.referencia).is_dir() else None
    found = validate(Path(a.root), config, ref, rep)
    if not found:
        rep.note("No hay ningún traduccion/<CANAL>/global.ini todavía: no se publica nada.")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"hay_archivos={'true' if found and not rep.errors else 'false'}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("## Validación de la traducción\n\n")
            f.write(f"Canales: {', '.join(found) or 'ninguno'}\n\n")
            for title, items in (("❌ Errores", rep.errors), ("⚠️ Avisos", rep.warnings), ("ℹ️ Datos", rep.info)):
                if items:
                    f.write(f"### {title}\n" + "".join(f"- {i}\n" for i in items) + "\n")
    print(f"\nResultado: {len(rep.errors)} error(es), {len(rep.warnings)} aviso(s).")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
