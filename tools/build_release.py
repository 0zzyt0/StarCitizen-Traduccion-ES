#!/usr/bin/env python3
"""Prepara los archivos de una publicación de la traducción (lo usa GitHub Actions).

Subcomandos:
  latest-tag  --releases-json R --config C
      Imprime la etiqueta de la última publicación de la traducción (o nada).

  build --root traduccion --config C --out dist --releases-json R
        [--previous-manifest M] [--notes-file traduccion/NOTAS.md] [--force]
      Calcula la versión nueva (AAAA.M.D.N, siempre creciente), copia los global.ini tal cual
      (byte a byte, sin modificarlos), genera manifest.json, lo firma con la clave Ed25519 de la
      variable de entorno MANIFEST_SIGNING_KEY, comprueba la firma con la clave pública de la
      configuración y genera SHA256SUMS.txt y notas.md.
      Si nada ha cambiado respecto a la publicación anterior, no genera nada (skip=true).
      Escribe version, tag y skip en $GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

VER_RE = re.compile(r"^\d+(\.\d+){0,5}$")


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def existing_versions(releases: list, prefix: str) -> list[str]:
    out = []
    for r in releases:
        tag = (r or {}).get("tag_name") or ""
        if tag.startswith(prefix) and VER_RE.match(tag[len(prefix):]):
            out.append(tag[len(prefix):])
    return out


def latest_published(releases: list, prefix: str) -> str | None:
    best = None
    for r in releases:
        if r.get("draft"):
            continue
        tag = r.get("tag_name") or ""
        v = tag[len(prefix):] if tag.startswith(prefix) else ""
        if VER_RE.match(v) and (best is None or vtuple(v) > vtuple(best)):
            best = v
    return f"{prefix}{best}" if best else None


def next_version(existing: list[str], today: datetime | None = None) -> str:
    today = today or datetime.now(timezone.utc)
    base = (today.year, today.month, today.day)
    same_day = [vtuple(v) for v in existing if vtuple(v)[:3] == base]
    n = max((t[3] if len(t) > 3 else 0 for t in same_day), default=0) + 1
    cand = (*base, n)
    if existing:
        top = max(vtuple(v) for v in existing)
        top = top + (0,) * (4 - len(top)) if len(top) < 4 else top
        if cand <= top:
            cand = (*top[:-1], top[-1] + 1)
    return ".".join(str(x) for x in cand)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def gh_output(**kv):
    out = os.environ.get("GITHUB_OUTPUT")
    for k, v in kv.items():
        print(f"{k}={v}")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def build(a) -> int:
    config = json.loads(Path(a.config).read_text(encoding="utf-8"))
    root = Path(a.root)
    lang = config["language_folder"]
    target = f"data/Localization/{lang}/global.ini"
    compat = {}
    cf = root / "compatibilidad.json"
    if cf.is_file():
        compat = {k: v for k, v in json.loads(cf.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    files = {ch: root / ch / "global.ini" for ch in config["channels"] if (root / ch / "global.ini").is_file()}
    if not files:
        print("No hay archivos de traducción.")
        gh_output(skip="true", version="", tag="")
        return 0
    channels = {}
    for ch, f in files.items():
        channels[ch] = {"asset": f"global_{ch}.ini", "size": f.stat().st_size, "sha256": sha256(f),
                        "target": target, "game_versions": compat.get(ch, [])}

    releases = json.loads(Path(a.releases_json).read_text(encoding="utf-8")) if a.releases_json else []
    prefix = config["translation_tag_prefix"]
    prev = None
    if a.previous_manifest and Path(a.previous_manifest).is_file():
        try:
            prev = json.loads(Path(a.previous_manifest).read_text(encoding="utf-8"))
        except ValueError:
            prev = None
    if prev and not a.force:
        same = {ch: (e["sha256"], tuple(e.get("game_versions", []))) for ch, e in prev.get("channels", {}).items()}
        now = {ch: (e["sha256"], tuple(e["game_versions"])) for ch, e in channels.items()}
        if same == now:
            print("Los archivos no han cambiado desde la última publicación; no se publica nada.")
            gh_output(skip="true", version="", tag="")
            return 0

    version = next_version(existing_versions(releases, prefix))
    notes = ""
    if a.notes_file and Path(a.notes_file).is_file():
        notes = Path(a.notes_file).read_text(encoding="utf-8").strip()
    manifest = {
        "schema": 1,
        "translation_version": version,
        "published_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "min_app_version": config.get("min_app_version_for_payload", "1.0.0"),
        "language_folder": lang,
        "notes": notes[:4000],
        "channels": channels,
    }
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for ch, f in files.items():
        shutil.copyfile(f, out / f"global_{ch}.ini")  # copia exacta, sin tocar el contenido
        if sha256(out / f"global_{ch}.ini") != channels[ch]["sha256"]:
            print(f"::error::La copia de {ch} no coincide con el original.")
            return 1
    raw = json.dumps(manifest, ensure_ascii=False, indent=1).encode("utf-8")
    (out / "manifest.json").write_bytes(raw)

    key = os.environ.get("MANIFEST_SIGNING_KEY", "").strip()
    if key:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

        priv = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key, validate=True))
        sig = priv.sign(raw)
        pub_cfg = config.get("signing_public_key", "")
        if pub_cfg:
            try:
                Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_cfg)).verify(sig, raw)
            except Exception:  # noqa: BLE001
                print("::error::La clave MANIFEST_SIGNING_KEY no corresponde con signing_public_key de "
                      "config/app_config.json. Los jugadores rechazarían esta publicación.")
                return 1
        (out / "manifest.json.sig").write_bytes(base64.b64encode(sig) + b"\n")
    elif config.get("require_signature", True):
        print("::error::Falta el secreto MANIFEST_SIGNING_KEY en el repositorio (Settings → Secrets and variables "
              "→ Actions). Sin firma los jugadores no instalarán la publicación.")
        return 1

    sums = [f"{sha256(p)}  {p.name}" for p in sorted(out.iterdir())]
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    lines = [f"Traducción al español de Star Citizen — versión {version}", ""]
    if notes:
        lines += [notes, ""]
    lines.append("| Canal | Versiones del juego | Entradas | SHA-256 |")
    lines.append("|---|---|---|---|")
    for ch, f in files.items():
        n = sum(1 for line in f.read_bytes().split(b"\n") if b"=" in line)
        gv = ", ".join(channels[ch]["game_versions"]) or "sin declarar"
        lines.append(f"| {ch} | {gv} | {n} | `{channels[ch]['sha256'][:16]}…` |")
    lines += ["", "Esta publicación la instala y actualiza automáticamente el gestor "
                  "(StarCitizen_Traduccion_ES_Setup.exe). No hace falta descargar estos archivos a mano."]
    (out.parent / "notas.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    gh_output(skip="false", version=version, tag=f"{prefix}{version}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lt = sub.add_parser("latest-tag")
    lt.add_argument("--releases-json", required=True)
    lt.add_argument("--config", default="config/app_config.json")
    b = sub.add_parser("build")
    b.add_argument("--root", default="traduccion")
    b.add_argument("--config", default="config/app_config.json")
    b.add_argument("--out", default="dist")
    b.add_argument("--releases-json")
    b.add_argument("--previous-manifest")
    b.add_argument("--notes-file")
    b.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "latest-tag":
        config = json.loads(Path(a.config).read_text(encoding="utf-8"))
        releases = json.loads(Path(a.releases_json).read_text(encoding="utf-8"))
        tag = latest_published(releases, config["translation_tag_prefix"])
        print(tag or "")
        return 0
    return build(a)


if __name__ == "__main__":
    sys.exit(main())
