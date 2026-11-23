"""Comprueba si un global.ini (por ejemplo, una copia encontrada en otro sitio) procede de esta traducción.

  python tools/verificar_autoria.py huella  ARCHIVO [--sellos autoria/sellos]
      Calcula la huella SHA-256 del archivo y la busca en las publicaciones selladas. Si coincide, el archivo es
      idéntico byte a byte a uno publicado aquí, y el sello de OpenTimestamps prueba la fecha.

  python tools/verificar_autoria.py registro ARCHIVO --registro REGISTRO_PRIVADO.json
      Compara el archivo con las líneas de referencia de un registro privado del autor (que no está en el
      repositorio). Sirve aunque la copia se haya editado.

Código de salida: 0 si encuentra coincidencias, 1 si no, 2 si hay un error de uso.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path


def sha256_archivo(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def buscar_huella(huella: str, sellos: Path) -> list[tuple[str, str]]:
    """Devuelve [(etiqueta, nombre_de_archivo)] de las publicaciones selladas con esa huella."""
    out = []
    for sums in sorted(sellos.glob("*/SHA256SUMS.txt")):
        for linea in sums.read_text(encoding="utf-8").splitlines():
            partes = linea.split(None, 1)
            if len(partes) == 2 and partes[0].lower() == huella.lower():
                out.append((sums.parent.name, partes[1].strip().lstrip("*")))
    return out


def leer_ini(p: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    texto = p.read_bytes().decode("utf-8", errors="replace").lstrip("﻿")
    for linea in re.split(r"\r?\n", texto):
        if "=" in linea:
            k, v = linea.split("=", 1)
            d.setdefault(k.lstrip("﻿"), v)
    return d


def _fragmentos(texto: str) -> list[str]:
    texto = re.sub(r"\([^)]*\)", "", texto)
    return [f.strip().lower() for f in texto.split("/") if len(f.strip()) >= 8]


def comparar_registro(ini: dict[str, str], registro: dict) -> list[dict]:
    """Para cada línea de referencia: 'identica' (valor exacto), 'parcial' (aparece un fragmento distintivo) o 'ausente'."""
    todo = "\n".join(ini.values()).lower()
    res = []
    for t in registro.get("lineas", []):
        valor = ini.get(t["clave"])
        frags = _fragmentos(t.get("fragmentos", ""))
        if valor is not None and valor == t["ahora"]:
            estado = "identica"
        elif any(f in (valor or "").lower() for f in frags) or any(f in todo for f in frags):
            estado = "parcial"
        else:
            estado = "ausente"
        res.append({"clave": t["clave"], "estado": estado})
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("huella")
    h.add_argument("archivo")
    h.add_argument("--sellos", default=str(Path(__file__).resolve().parents[1] / "autoria" / "sellos"))
    m = sub.add_parser("registro")
    m.add_argument("archivo")
    m.add_argument("--registro", required=True)
    a = ap.parse_args(argv)

    archivo = Path(a.archivo)
    if not archivo.is_file():
        print(f"No existe el archivo {archivo}", file=sys.stderr)
        return 2

    if a.cmd == "huella":
        huella = sha256_archivo(archivo)
        print(f"SHA-256: {huella}")
        hits = buscar_huella(huella, Path(a.sellos))
        if not hits:
            print("No coincide byte a byte con ninguna publicación sellada (puede ser una copia modificada: "
                  "usa «registro»).")
            return 1
        for tag, nombre in hits:
            print(f"IDÉNTICO a {nombre} de la publicación {tag} "
                  f"(prueba de fecha: autoria/sellos/{tag}/SHA256SUMS.txt.ots)")
        return 0

    registro = json.loads(Path(a.registro).read_text(encoding="utf-8"))
    res = comparar_registro(leer_ini(archivo), registro)
    for r in res:
        print(f"{r['estado'].upper():9} {r['clave']}")
    n_id = sum(r["estado"] == "identica" for r in res)
    n_pa = sum(r["estado"] == "parcial" for r in res)
    print(f"\nCoincidencias: {n_id} idénticas y {n_pa} parciales de {len(res)} líneas de referencia.")
    return 0 if (n_id + n_pa) else 1


if __name__ == "__main__":
    sys.exit(main())
