"""Sellado de autoría con OpenTimestamps (lo usa GitHub Actions, workflow «Sellar autoría»).

Para cada publicación de la traducción (etiquetas traduccion-v…) guarda en autoria/sellos/<etiqueta>/ una copia de
SHA256SUMS.txt (huellas de todos los archivos publicados), manifest.json y su firma, y sella SHA256SUMS.txt con
OpenTimestamps: queda anclado en la cadena de bloques de Bitcoin con una fecha que nadie puede falsificar.
También sella los registros de autoria/registro/*.txt (huellas de documentos privados del autor).

Uso:
  python tools/sellar_autoria.py --repo OWNER/REPO [--releases-json releases.json] [--raiz autoria]

Necesita `gh` (con GH_TOKEN) y el cliente `ots` (pip install opentimestamps-client).
Un sello recién creado queda «pendiente» unas horas hasta que entra en un bloque; cada ejecución intenta
completar (ots upgrade) los pendientes.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PREFIX = "traduccion-v"
ARCHIVOS = ["SHA256SUMS.txt", "manifest.json", "manifest.json.sig"]
SELLADO = "SHA256SUMS.txt"


def etiquetas_pendientes(releases: list[dict], sellos: Path, prefix: str = PREFIX) -> list[str]:
    """Publicaciones de traducción (no borradores) que aún no tienen carpeta de sellos."""
    out = []
    for r in releases:
        tag = str(r.get("tag_name") or "")
        if r.get("draft") or not tag.startswith(prefix):
            continue
        nombres = {a.get("name") for a in r.get("assets") or []}
        if SELLADO not in nombres:
            continue
        if not (sellos / tag / (SELLADO + ".ots")).exists():
            out.append(tag)
    return sorted(out)


def registros_sin_sello(registro: Path) -> list[Path]:
    if not registro.is_dir():
        return []
    return sorted(p for p in registro.glob("*.txt") if not Path(str(p) + ".ots").exists())


def ots_pendientes(raiz: Path) -> list[Path]:
    return sorted(raiz.rglob("*.ots"))


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def descargar(repo: str, tag: str, destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in ARCHIVOS:
        r = _run(["gh", "release", "download", tag, "--repo", repo, "-p", nombre, "-D", str(destino), "--clobber"],
                 check=False)
        if r.returncode != 0 and nombre == SELLADO:
            raise RuntimeError(f"No se pudo descargar {nombre} de {tag}: {r.stderr.strip()}")


def sellar(archivo: Path) -> None:
    r = _run(["ots", "stamp", str(archivo)], check=False)
    if r.returncode != 0 or not Path(str(archivo) + ".ots").exists():
        raise RuntimeError(f"No se pudo sellar {archivo}: {r.stderr.strip()}")


def completar(ots: Path) -> str:
    """Intenta completar un sello pendiente. Devuelve 'completo' o 'pendiente'."""
    r = _run(["ots", "--no-bitcoin", "upgrade", str(ots)], check=False)
    bak = Path(str(ots) + ".bak")
    if bak.exists():
        bak.unlink()
    texto = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0 and "pending" not in texto.lower():
        return "completo"
    return "pendiente"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--releases-json", help="Lista de releases (gh api repos/R/releases); si falta, se consulta.")
    ap.add_argument("--raiz", default="autoria")
    a = ap.parse_args(argv)

    raiz = Path(a.raiz)
    sellos = raiz / "sellos"
    if a.releases_json:
        releases = json.loads(Path(a.releases_json).read_text(encoding="utf-8"))
    else:
        releases = json.loads(_run(["gh", "api", f"repos/{a.repo}/releases?per_page=100"]).stdout)

    resumen = []
    for tag in etiquetas_pendientes(releases, sellos):
        destino = sellos / tag
        descargar(a.repo, tag, destino)
        sellar(destino / SELLADO)
        resumen.append(f"- Sellada la publicación `{tag}`")
    for txt in registros_sin_sello(raiz / "registro"):
        sellar(txt)
        resumen.append(f"- Sellado el registro `{txt.name}`")

    completos = pendientes = 0
    for ots in ots_pendientes(raiz):
        if completar(ots) == "completo":
            completos += 1
        else:
            pendientes += 1
    resumen.append(f"- Sellos anclados en Bitcoin: {completos} · pendientes de confirmar: {pendientes}")

    texto = "### Sellos de autoría (OpenTimestamps)\n" + "\n".join(resumen) + "\n"
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
