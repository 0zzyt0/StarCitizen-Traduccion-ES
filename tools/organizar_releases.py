#!/usr/bin/env python3
"""Ordena la página Releases en dos grupos claros y deja el INSTALADOR siempre a primera vista.

- Instalador (app-vX.Y.Z): título «⬇️ INSTALADOR — Gestor X.Y.Z (descarga aquí)», marcado como «Latest»
  (aparece en la portada del repositorio y en .../releases/latest/download/StarCitizen_Traduccion_ES_Setup.exe).
  Los instaladores antiguos se renombran como versiones anteriores.
- Traducción (traduccion-vAAAA.M.D.N): título «🔄 Traducción … — actualización automática», nunca «Latest»,
  con un aviso al principio que enlaza al instalador.
- Si la publicación más reciente de la lista no es el instalador, se vuelve a crear la release del instalador
  (misma etiqueta y mismos archivos) para que quede la primera de la página.

Uso (en GitHub Actions, con GH_TOKEN):  python tools/organizar_releases.py --repo OWNER/REPO
      Simulación sin cambios:           python tools/organizar_releases.py --repo OWNER/REPO --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP_PREFIX = "app-v"
TR_PREFIX = "traduccion-v"
SETUP = "StarCitizen_Traduccion_ES_Setup.exe"
MARK = "<!-- sctrad:cabecera -->"
VER_RE = re.compile(r"^\d+(\.\d+){0,5}$")


def vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def version(tag: str, prefix: str) -> str | None:
    v = tag[len(prefix):] if tag.startswith(prefix) else ""
    return v if VER_RE.match(v) else None


def installer_link(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest/download/{SETUP}"


def installer_title(v: str) -> str:
    return f"⬇️ INSTALADOR — Gestor {v} (descarga aquí)"


def old_installer_title(v: str) -> str:
    return f"📦 Instalador anterior — Gestor {v}"


def translation_title(v: str, pre: bool) -> str:
    return f"🔄 Traducción {v} — {'beta, ' if pre else ''}actualización automática"


def installer_body(repo: str, v: str) -> str:
    return f"""{MARK}
## ⬇️ Descarga el instalador: [{SETUP}]({installer_link(repo)})

Es el **instalador de la traducción al español de Star Citizen**. Solo hay que descargarlo **una vez**:

1. Descarga **`{SETUP}`** (también está abajo, en *Assets*).
2. Ejecútalo. Si Windows muestra «Windows protegió su PC», pulsa **Más información → Ejecutar de todas formas**.
3. Sigue el asistente: detecta Star Citizen, instala la traducción y activa las actualizaciones automáticas.

Las publicaciones **🔄 Traducción …** de esta página son las **actualizaciones de los textos**: el gestor las
instala **solo** al abrir el RSI Launcher o al cerrar el juego. **No hay que descargarlas.**

Versión del gestor: **{v}** · Comprobación: `{SETUP}.sha256`
"""


def old_installer_body(repo: str, v: str) -> str:
    return f"""{MARK}
> ⚠️ **Versión anterior del gestor ({v}).** Descarga la última aquí: **[{SETUP}]({installer_link(repo)})**
"""


def translation_header(repo: str) -> str:
    return f"""{MARK}
> ℹ️ **No hace falta descargar nada:** si tienes el gestor de la traducción, esta actualización se instala sola.
> ¿Aún no lo tienes? **[⬇️ Descarga el instalador aquí]({installer_link(repo)})** (solo una vez).

---
"""


def same(a: str | None, b: str | None) -> bool:
    n = lambda x: (x or "").replace("\r\n", "\n").strip()  # noqa: E731
    return n(a) == n(b)


def strip_header(body: str) -> str:
    body = (body or "").replace("\r\n", "\n")
    if MARK in body:
        _, _, rest = body.partition(MARK)
        rest = rest.split("\n---\n", 1)[1] if "\n---\n" in rest else ""
        return rest.lstrip("\n")
    return body


def plan(releases: list[dict], repo: str) -> dict:
    """Calcula los cambios. Devuelve {"edits": [...], "reraise": tag | None, "latest": tag | None}."""
    rels = [r for r in releases if not r.get("draft")]
    apps = sorted(((version(r["tag_name"], APP_PREFIX), r) for r in rels if version(r["tag_name"], APP_PREFIX)),
                  key=lambda x: vt(x[0]), reverse=True)
    edits = []
    newest_app = apps[0][1] if apps else None
    for i, (v, r) in enumerate(apps):
        title = installer_title(v) if i == 0 else old_installer_title(v)
        body = installer_body(repo, v) if i == 0 else old_installer_body(repo, v)
        if r.get("name") != title or not same(r.get("body"), body):
            edits.append({"id": r["id"], "tag": r["tag_name"], "name": title, "body": body,
                          "make_latest": "true" if i == 0 else "false"})
    for r in rels:
        v = version(r["tag_name"], TR_PREFIX)
        if not v:
            continue
        title = translation_title(v, bool(r.get("prerelease")))
        body = translation_header(repo) + strip_header(r.get("body") or "")
        if r.get("name") != title or not same(r.get("body"), body):
            edits.append({"id": r["id"], "tag": r["tag_name"], "name": title, "body": body,
                          "make_latest": "false"})
    reraise = None
    if newest_app and rels:
        newest_created = max(rels, key=lambda r: r.get("created_at") or "")
        if newest_created["id"] != newest_app["id"]:
            reraise = newest_app["tag_name"]
    return {"edits": edits, "reraise": reraise, "latest": newest_app["tag_name"] if newest_app else None}


def gh(*args: str, input_: str | None = None) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=input_)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def apply(repo: str, p: dict, dry: bool) -> None:
    for e in p["edits"]:
        print(f"Editar {e['tag']}: {e['name']}")
        if not dry:
            payload = json.dumps({"name": e["name"], "body": e["body"], "make_latest": e["make_latest"]})
            gh("api", "-X", "PATCH", f"repos/{repo}/releases/{e['id']}", "--input", "-", input_=payload)
    tag = p["reraise"]
    if not tag:
        print("El instalador ya es la primera publicación de la lista.")
        return
    print(f"Subir {tag} a la primera posición (se vuelve a crear la release con los mismos archivos).")
    if dry:
        return
    info = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "name,body,assets"))
    with tempfile.TemporaryDirectory() as d:
        gh("release", "download", tag, "--repo", repo, "-D", d)
        files = sorted(str(f) for f in Path(d).iterdir())
        expected = {a["name"] for a in info["assets"]}
        if {Path(f).name for f in files} != expected or not files:
            raise RuntimeError("No se descargaron todos los archivos del instalador; no se toca nada.")
        notes = Path(d) / "notas.md"
        notes.write_text(info["body"] or "", encoding="utf-8")
        gh("release", "delete", tag, "--repo", repo, "--yes")  # la etiqueta se conserva
        last = None
        for attempt in range(4):
            try:
                gh("release", "create", tag, "--repo", repo, "--verify-tag", "--title", info["name"],
                   "--notes-file", str(notes), "--latest", *files)
                break
            except RuntimeError as err:
                last = err
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"No se pudo volver a crear {tag}: {last}")
    print(f"{tag} vuelve a estar el primero y marcado como «Latest».")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--releases-json", help="(pruebas) lista de releases en JSON en lugar de consultar GitHub")
    a = ap.parse_args(argv)
    if a.releases_json:
        releases = json.loads(Path(a.releases_json).read_text(encoding="utf-8"))
    else:
        releases = json.loads(gh("api", f"repos/{a.repo}/releases?per_page=100"))
    p = plan(releases, a.repo)
    apply(a.repo, p, a.dry_run or bool(a.releases_json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
