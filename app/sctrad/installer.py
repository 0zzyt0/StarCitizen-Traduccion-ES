"""Instalación, copias de seguridad, restauración y desinstalación de la traducción.

Reglas de seguridad:
- Solo se escribe en dos rutas relativas fijas dentro de la carpeta del canal validada:
  data/Localization/<idioma>/global.ini y user.cfg.
- Antes de reemplazar nada se hace copia de seguridad; si algo falla se restaura.
- Nunca se sobrescribe un global.ini ajeno sin permiso explícito del jugador.
- En user.cfg solo se tocan las líneas g_language / g_languageAudio.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .errors import (ForeignFileError, GameRunningError, InstallError, IntegrityError,
                     PermissionNeededError, SCTradError)
from .fsutil import (atomic_copy, atomic_write_bytes, ensure_dir, free_space, is_writable_now,
                     safe_target, sha256_file)
from .gamepaths import GameInstall, is_valid_channel_dir
from .lock import FileLock
from .manifest import ChannelEntry
from .state import StateStore, now_iso
from .usercfg import apply_settings, get_setting, revert_settings

log = logging.getLogger(__name__)

ACTION_LABELS = {
    "instalar": "Instalación",
    "actualizar": "Actualización",
    "reparar": "Reparación",
    "restaurar": "Restauración",
    "desinstalar": "Desinstalación",
}


@dataclass
class Inspection:
    global_path: Path
    user_cfg_path: Path
    global_exists: bool
    global_sha: str | None
    recorded_sha: str | None
    ours: bool
    foreign: bool
    missing_ours: bool
    user_cfg_exists: bool
    current_language: str | None
    locked: bool


@dataclass
class BackupInfo:
    id: str
    created: str
    kind: str              # "original" (antes de instalar la traducción) | "auto" (versión anterior)
    version_before: str | None
    path: Path

    @property
    def label(self) -> str:
        fecha = self.created.replace("T", " ").replace("Z", " UTC")
        if self.kind == "original":
            return f"{fecha} — Estado original del juego (antes de la traducción)"
        return f"{fecha} — Traducción {self.version_before or 'desconocida'}"


class Installer:
    def __init__(self, cfg: AppConfig, store: StateStore, data_dir: Path,
                 is_game_running: Callable[[], bool]):
        self.cfg = cfg
        self.store = store
        self.data_dir = Path(data_dir)
        self.is_game_running = is_game_running
        self.op_lock = FileLock(self.data_dir / "operation.lock", timeout=3)

    # ------------------------------------------------------------------ rutas
    def _paths(self, install: GameInstall) -> tuple[Path, Path, Path]:
        channel_dir = Path(install.path)
        return (channel_dir,
                safe_target(channel_dir, self.cfg.translation_rel_path),
                safe_target(channel_dir, self.cfg.user_cfg_rel_path))

    def _record(self, install: GameInstall) -> dict | None:
        return self.store.snapshot()["installs"].get(install.key)

    def _backup_root(self, install: GameInstall) -> Path:
        h = hashlib.sha1(install.key.encode("utf-8")).hexdigest()[:12]
        return self.data_dir / "backups" / f"{install.channel}-{h}"

    # ------------------------------------------------------------- inspección
    def inspect(self, install: GameInstall, expected_sha: str | None = None) -> Inspection:
        """expected_sha: SHA-256 de la versión publicada. Si el archivo existente es idéntico
        (p. ej. copiado a mano), se considera nuestro y no se pide confirmación."""
        _, gpath, cpath = self._paths(install)
        rec = self._record(install) or {}
        recorded = (rec.get("files") or {}).get(self.cfg.translation_rel_path)
        exists = gpath.is_file()
        sha = sha256_file(gpath) if exists else None
        ours = bool(exists and ((recorded and sha == recorded) or (expected_sha and sha == expected_sha)))
        cfg_exists = cpath.is_file()
        lang = get_setting(cpath.read_bytes(), "g_language") if cfg_exists else None
        return Inspection(
            global_path=gpath, user_cfg_path=cpath, global_exists=exists, global_sha=sha,
            recorded_sha=recorded, ours=ours, foreign=bool(exists and not ours),
            missing_ours=bool(recorded and not exists), user_cfg_exists=cfg_exists,
            current_language=lang,
            locked=not (is_writable_now(gpath) and is_writable_now(cpath)),
        )

    def describe_plan(self, install: GameInstall, version: str, touch_user_cfg: bool = True,
                      expected_sha: str | None = None) -> list[str]:
        i = self.inspect(install, expected_sha)
        lines: list[str] = []
        if i.global_exists and expected_sha and i.global_sha == expected_sha and not i.recorded_sha:
            lines.append(f"Ya tienes esta misma versión ({version}) copiada a mano. El gestor la registrará para "
                         f"mantenerla actualizada:\n    {i.global_path}")
        elif i.global_exists and i.ours:
            lines.append(f"Se reemplazará la traducción instalada por la versión {version}:\n    {i.global_path}")
        elif i.global_exists:
            lines.append("⚠ Ya hay un global.ini que NO instaló este gestor (otra traducción o un archivo "
                         f"modificado). Se guardará una copia de seguridad y se sustituirá:\n    {i.global_path}")
        else:
            lines.append(f"Se creará el archivo de traducción (versión {version}):\n    {i.global_path}")
        if touch_user_cfg:
            want = self.cfg.user_cfg_settings.get("g_language")
            if not i.user_cfg_exists:
                lines.append(f"Se creará user.cfg con «g_language = {want}»:\n    {i.user_cfg_path}")
            elif i.current_language != want:
                antes = i.current_language or "sin definir"
                lines.append(f"En user.cfg se cambiará g_language ({antes} → {want}); el resto de líneas no se toca:\n"
                             f"    {i.user_cfg_path}")
            else:
                lines.append("user.cfg ya tiene el idioma español configurado; no se modificará.")
        lines.append("Antes de cambiar nada se hará una copia de seguridad que podrás restaurar.")
        return lines

    # --------------------------------------------------------------- copias
    def _create_backup(self, install: GameInstall, kind: str, version_before: str | None,
                       gpath: Path, cpath: Path) -> BackupInfo:
        root = self._backup_root(install)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bid = f"{stamp}-{kind}"
        n = 1
        while (root / bid).exists():
            n += 1
            bid = f"{stamp}-{kind}-{n}"
        bdir = root / bid
        (bdir / "files").mkdir(parents=True, exist_ok=False)
        meta = {
            "id": bid, "created": now_iso(), "kind": kind, "version_before": version_before,
            "install_path": install.path, "channel": install.channel,
            "files": {},
        }
        for name, p in (("global.ini", gpath), ("user.cfg", cpath)):
            if p.is_file():
                shutil.copy2(p, bdir / "files" / name)
                meta["files"][name] = {"existed": True, "sha256": sha256_file(p)}
            else:
                meta["files"][name] = {"existed": False}
        (bdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return BackupInfo(bid, meta["created"], kind, version_before, bdir)

    def list_backups(self, install: GameInstall) -> list[BackupInfo]:
        root = self._backup_root(install)
        out: list[BackupInfo] = []
        if not root.is_dir():
            return out
        for d in sorted(root.iterdir(), reverse=True):
            try:
                meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                out.append(BackupInfo(meta["id"], meta["created"], meta["kind"], meta.get("version_before"), d))
            except (OSError, ValueError, KeyError):
                continue
        return out

    def _prune_backups(self, install: GameInstall) -> None:
        rec = self._record(install) or {}
        protected = rec.get("original_backup")
        autos = [b for b in self.list_backups(install) if b.id != protected]
        for b in autos[self.cfg.max_backups_per_install:]:
            shutil.rmtree(b.path, ignore_errors=True)

    def _restore_files(self, bdir: Path, gpath: Path, cpath: Path, which: tuple[str, ...]) -> list[str]:
        meta = json.loads((bdir / "meta.json").read_text(encoding="utf-8"))
        problems: list[str] = []
        for name, p in (("global.ini", gpath), ("user.cfg", cpath)):
            if name not in which:
                continue
            info = meta["files"].get(name, {"existed": False})
            try:
                if info.get("existed"):
                    src = bdir / "files" / name
                    if sha256_file(src) != info.get("sha256"):
                        problems.append(f"La copia de {name} está dañada.")
                        continue
                    ensure_dir(p.parent)
                    atomic_copy(src, p)
                elif p.exists():
                    p.unlink()
            except (OSError, SCTradError) as e:
                problems.append(f"{name}: {e}")
        return problems

    # ----------------------------------------------------------- instalación
    def _preflight(self, install: GameInstall) -> tuple[Path, Path, Path]:
        if self.is_game_running():
            raise GameRunningError("Star Citizen está abierto. Ciérralo y vuelve a intentarlo.")
        channel_dir, gpath, cpath = self._paths(install)
        if not is_valid_channel_dir(channel_dir):
            raise InstallError(f"La carpeta {channel_dir} ya no parece una instalación válida de Star Citizen.")
        if not (is_writable_now(gpath) and is_writable_now(cpath)):
            raise GameRunningError("Los archivos del juego están en uso (¿el juego o el launcher están actualizando?). "
                                   "Se reintentará más tarde.")
        return channel_dir, gpath, cpath

    def install(self, install: GameInstall, staged: Path, entry: ChannelEntry, version: str,
                action: str = "instalar", allow_foreign: bool = False, touch_user_cfg: bool = True,
                progress: Callable[[str], None] | None = None) -> None:
        say = progress or (lambda _m: None)
        with self.op_lock:
            channel_dir, gpath, cpath = self._preflight(install)
            insp = self.inspect(install, entry.sha256)
            if insp.foreign and not allow_foreign:
                raise ForeignFileError(
                    "Hay un archivo de traducción que no instaló este gestor. Ábrelo y confirma si quieres sustituirlo."
                )
            staged = Path(staged)
            say("Verificando el archivo descargado…")
            if not staged.is_file() or staged.stat().st_size != entry.size or sha256_file(staged) != entry.sha256:
                raise IntegrityError("El archivo preparado no coincide con el manifiesto. Se volverá a descargar.")
            if free_space(channel_dir) < entry.size * 2 + 20 * 1024 * 1024:
                raise InstallError("No hay espacio libre suficiente en el disco del juego.")

            rec = self._record(install) or {}
            first = not rec.get("original_backup")
            say("Creando copia de seguridad…")
            try:
                backup = self._create_backup(install, "original" if first else "auto",
                                             rec.get("installed_version"), gpath, cpath)
            except OSError as e:
                raise InstallError(f"No se pudo crear la copia de seguridad: {e}") from e

            changes: dict[str, str | None] = {}
            try:
                say("Copiando la traducción…")
                ensure_dir(gpath.parent)
                atomic_copy(staged, gpath)
                if sha256_file(gpath) != entry.sha256:
                    raise IntegrityError("La comprobación del archivo instalado ha fallado.")
                if touch_user_cfg:
                    say("Configurando user.cfg…")
                    raw = cpath.read_bytes() if cpath.is_file() else None
                    new, changes = apply_settings(raw, self.cfg.user_cfg_settings, self.cfg.user_cfg_only_if_absent)
                    if changes:
                        atomic_write_bytes(cpath, new)
                    want = self.cfg.user_cfg_settings.get("g_language")
                    if want and get_setting(cpath.read_bytes(), "g_language") != want:
                        raise InstallError("No se pudo comprobar el idioma en user.cfg.")
            except BaseException as e:
                say("Error: restaurando el estado anterior…")
                problems = self._restore_files(backup.path, gpath, cpath, ("global.ini", "user.cfg"))
                if not problems:
                    shutil.rmtree(backup.path, ignore_errors=True)
                self.store.add_history(install.path, install.channel, action, version, "error", str(e))
                if problems:
                    raise InstallError(
                        "La instalación falló y no se pudo restaurar todo automáticamente. "
                        "Usa «Restaurar copia de seguridad». Detalle: " + "; ".join(problems)
                    ) from e
                raise

            with self.store.transaction() as s:
                r = s["installs"].setdefault(install.key, {})
                r.update({
                    "path": install.path, "channel": install.channel, "managed": True,
                    "installed_version": version, "installed_at": now_iso(),
                    "files": {self.cfg.translation_rel_path: entry.sha256},
                    "pending_version": None, "attention": None,
                })
                if action != "restaurar":
                    r.pop("hold_until_newer_than", None)
                if first:
                    r["original_backup"] = backup.id
                prev = r.setdefault("user_cfg_previous", {})
                for k, old in changes.items():
                    prev.setdefault(k, old)
            self._prune_backups(install)
            self.store.add_history(install.path, install.channel, action, version, "ok",
                                   f"{ACTION_LABELS.get(action, action)} completada")
            say("Hecho.")

    # ----------------------------------------------------------- restaurar
    def restore(self, install: GameInstall, backup_id: str) -> None:
        backups = {b.id: b for b in self.list_backups(install)}
        b = backups.get(backup_id)
        if not b:
            raise InstallError("No se encuentra esa copia de seguridad.")
        if b.kind == "original":
            self.uninstall(install)
            return
        with self.op_lock:
            _, gpath, cpath = self._preflight(install)
            rec = self._record(install) or {}
            current_version = rec.get("installed_version")
            problems = self._restore_files(b.path, gpath, cpath, ("global.ini",))
            if problems:
                self.store.add_history(install.path, install.channel, "restaurar", b.version_before, "error",
                                       "; ".join(problems))
                raise InstallError("No se pudo restaurar la copia: " + "; ".join(problems))
            sha = sha256_file(gpath) if gpath.is_file() else None
            with self.store.transaction() as s:
                r = s["installs"].setdefault(install.key, {"path": install.path, "channel": install.channel})
                r["installed_version"] = b.version_before
                r["files"] = {self.cfg.translation_rel_path: sha} if sha else {}
                r["managed"] = True
                r["pending_version"] = None
                if current_version:
                    # Tras volver atrás, no reinstalar automáticamente la versión descartada.
                    r["hold_until_newer_than"] = current_version
            self.store.add_history(install.path, install.channel, "restaurar", b.version_before, "ok",
                                   f"Restaurada la copia {b.id}")

    # --------------------------------------------------------- desinstalar
    def uninstall(self, install: GameInstall) -> list[str]:
        """Quita la traducción y deja el juego como estaba. Devuelve avisos (si algo no se tocó)."""
        notes: list[str] = []
        with self.op_lock:
            _, gpath, cpath = self._paths(install)
            if self.is_game_running():
                raise GameRunningError("Star Citizen está abierto. Ciérralo y vuelve a intentarlo.")
            rec = self._record(install) or {}
            insp = self.inspect(install)
            original = None
            if rec.get("original_backup"):
                original = next((b for b in self.list_backups(install) if b.id == rec["original_backup"]), None)
            try:
                if insp.global_exists and insp.ours:
                    if original:
                        problems = self._restore_files(original.path, gpath, cpath, ("global.ini",))
                        if problems:
                            raise InstallError("; ".join(problems))
                    else:
                        gpath.unlink()
                elif insp.global_exists:
                    notes.append("El global.ini actual no coincide con el instalado por el gestor; no se ha borrado.")
                if cpath.is_file() and rec.get("user_cfg_previous"):
                    raw = cpath.read_bytes()
                    new = revert_settings(raw, self.cfg.user_cfg_settings, rec["user_cfg_previous"])
                    if new != raw:
                        atomic_write_bytes(cpath, new)
                try:
                    if gpath.parent.is_dir() and not any(gpath.parent.iterdir()):
                        gpath.parent.rmdir()
                except OSError:
                    pass
            except PermissionNeededError:
                raise
            except PermissionError as e:
                raise PermissionNeededError("Hacen falta permisos de administrador para desinstalar.") from e
            except (OSError, SCTradError) as e:
                self.store.add_history(install.path, install.channel, "desinstalar", None, "error", str(e))
                raise InstallError(f"No se pudo desinstalar la traducción: {e}") from e
            with self.store.transaction() as s:
                s["installs"].pop(install.key, None)
            self.store.add_history(install.path, install.channel, "desinstalar", rec.get("installed_version"), "ok",
                                   "Traducción desinstalada" + (f" ({'; '.join(notes)})" if notes else ""))
        return notes
