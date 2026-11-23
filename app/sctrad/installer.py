"""Instalación, copias de seguridad, restauración y desinstalación de la traducción.

Reglas de seguridad:
- Solo se escribe en rutas relativas fijas dentro de la carpeta del canal validada:
  data/Localization/<idioma>/global.ini, user.cfg y los archivos extra de la lista blanca
  de la configuración (p. ej. EasyAntiCheat/SplashScreen.png).
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
from .manifest import ChannelEntry, ExtraEntry
from .state import StateStore, now_iso
from .usercfg import CfgText, apply_settings, get_setting
from .version_line import is_ours, read_label

log = logging.getLogger(__name__)

ACTION_LABELS = {
    "instalar": "Instalación",
    "actualizar": "Actualización",
    "reparar": "Reparación",
    "restaurar": "Restauración",
    "desinstalar": "Desinstalación",
}
EXTRA_LABELS = {
    "splash": "la pantalla de carga de Easy Anti-Cheat (EasyAntiCheat\\SplashScreen.png)",
}


def _extra_key(ex_id: str) -> str:
    return f"extra-{ex_id}"


@dataclass
class Inspection:
    global_path: Path
    user_cfg_path: Path
    global_exists: bool
    global_sha: str | None
    recorded_sha: str | None
    ours: bool
    foreign: bool
    label: str | None
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

    def extra_paths(self, install: GameInstall, entry: ChannelEntry | None) -> list[tuple[ExtraEntry, Path]]:
        """Extras del manifiesto permitidos por la configuración y cuya carpeta ya existe en el juego."""
        out: list[tuple[ExtraEntry, Path]] = []
        if not entry:
            return out
        channel_dir = Path(install.path)
        for ex in entry.extras:
            if self.cfg.extra_targets.get(ex.id) != ex.target:
                continue
            p = safe_target(channel_dir, ex.target)
            if p.parent.is_dir():  # no se crean carpetas del juego que no existan
                out.append((ex, p))
        return out

    def extras_needing_repair(self, install: GameInstall, entry: ChannelEntry | None) -> list[str]:
        need = []
        for ex, p in self.extra_paths(install, entry):
            try:
                if not p.is_file() or sha256_file(p) != ex.sha256:
                    need.append(ex.id)
            except OSError:
                need.append(ex.id)
        return need

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
        label = read_label(gpath) if exists else None
        family = is_ours(label)  # lleva la línea «Traduccion 0zzyt0 …»: es esta traducción (otra versión)
        cfg_exists = cpath.is_file()
        lang = get_setting(cpath.read_bytes(), "g_language") if cfg_exists else None
        return Inspection(
            global_path=gpath, user_cfg_path=cpath, global_exists=exists, global_sha=sha,
            recorded_sha=recorded, ours=ours, foreign=bool(exists and not ours and not family), label=label,
            missing_ours=bool(recorded and not exists), user_cfg_exists=cfg_exists,
            current_language=lang,
            locked=not (is_writable_now(gpath) and is_writable_now(cpath)),
        )

    def describe_plan(self, install: GameInstall, version: str, touch_user_cfg: bool = True,
                      expected_sha: str | None = None, entry: ChannelEntry | None = None,
                      with_extras: bool = True) -> list[str]:
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
        if with_extras:
            for ex, p in self.extra_paths(install, entry):
                what = EXTRA_LABELS.get(ex.id, ex.target)
                lines.append(f"Se cambiará {what} por la de la traducción {install.channel}, para que veas al "
                             f"arrancar que está instalada. La original se guarda:\n    {p}")
        lines.append("Antes de cambiar nada se hará una copia de seguridad que podrás restaurar.")
        return lines

    # --------------------------------------------------------------- copias
    def _create_backup(self, install: GameInstall, kind: str, version_before: str | None,
                       files: dict[str, tuple[Path, str]]) -> BackupInfo:
        """files: nombre lógico -> (ruta en el juego, ruta relativa)."""
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
            "install_path": install.path, "channel": install.channel, "files": {},
        }
        for name, (p, rel) in files.items():
            if p.is_file():
                shutil.copy2(p, bdir / "files" / name)
                meta["files"][name] = {"existed": True, "sha256": sha256_file(p), "target": rel}
            else:
                meta["files"][name] = {"existed": False, "target": rel}
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
        protected = {rec.get("original_backup")}
        # También se conserva la copia más antigua que contiene cada extra (su estado original).
        for ex_id in (rec.get("extras") or {}):
            found = self._oldest_backup_with(install, _extra_key(ex_id))
            if found:
                protected.add(found[0].id)
        autos = [b for b in self.list_backups(install) if b.id not in protected]
        for b in autos[self.cfg.max_backups_per_install:]:
            shutil.rmtree(b.path, ignore_errors=True)

    def _oldest_backup_with(self, install: GameInstall, name: str) -> tuple[BackupInfo, dict] | None:
        for b in reversed(self.list_backups(install)):
            try:
                meta = json.loads((b.path / "meta.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if name in meta.get("files", {}):
                return b, meta["files"][name]
        return None

    def _restore_files(self, bdir: Path, mapping: dict[str, Path], which: tuple[str, ...] | None = None) -> list[str]:
        meta = json.loads((bdir / "meta.json").read_text(encoding="utf-8"))
        problems: list[str] = []
        for name, p in mapping.items():
            if which is not None and name not in which:
                continue
            info = meta["files"].get(name)
            if info is None:
                continue
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
    def _preflight(self, install: GameInstall, extra_targets: list[Path] | tuple = ()) -> tuple[Path, Path, Path]:
        if self.is_game_running():
            raise GameRunningError("Star Citizen está abierto. Ciérralo y vuelve a intentarlo.")
        channel_dir, gpath, cpath = self._paths(install)
        if not is_valid_channel_dir(channel_dir):
            raise InstallError(f"La carpeta {channel_dir} ya no parece una instalación válida de Star Citizen.")
        if not all(is_writable_now(p) for p in (gpath, cpath, *extra_targets)):
            raise GameRunningError("Los archivos del juego están en uso (¿el juego o el launcher están actualizando?). "
                                   "Se reintentará más tarde.")
        return channel_dir, gpath, cpath

    def install(self, install: GameInstall, staged: Path, entry: ChannelEntry, version: str,
                action: str = "instalar", allow_foreign: bool = False, touch_user_cfg: bool = True,
                progress: Callable[[str], None] | None = None,
                staged_extras: dict[str, Path] | None = None) -> None:
        say = progress or (lambda _m: None)
        with self.op_lock:
            extras = [(ex, p) for ex, p in self.extra_paths(install, entry)
                      if staged_extras and ex.id in staged_extras]
            channel_dir, gpath, cpath = self._preflight(install, [p for _, p in extras])
            insp = self.inspect(install, entry.sha256)
            if insp.foreign and not allow_foreign:
                raise ForeignFileError(
                    "Hay un archivo de traducción que no instaló este gestor. Ábrelo y confirma si quieres sustituirlo."
                )
            staged = Path(staged)
            say("Verificando los archivos descargados…")
            if not staged.is_file() or staged.stat().st_size != entry.size or sha256_file(staged) != entry.sha256:
                raise IntegrityError("El archivo preparado no coincide con el manifiesto. Se volverá a descargar.")
            for ex, _ in extras:
                sp = Path(staged_extras[ex.id])
                if not sp.is_file() or sp.stat().st_size != ex.size or sha256_file(sp) != ex.sha256:
                    raise IntegrityError("Un archivo extra preparado no coincide con el manifiesto.")
            needed = entry.size * 2 + sum(ex.size for ex, _ in extras) * 2 + 20 * 1024 * 1024
            if free_space(channel_dir) < needed:
                raise InstallError("No hay espacio libre suficiente en el disco del juego.")

            rec = self._record(install) or {}
            first = not rec.get("original_backup")
            mapping: dict[str, Path] = {"global.ini": gpath, "user.cfg": cpath}
            files = {"global.ini": (gpath, self.cfg.translation_rel_path), "user.cfg": (cpath, "user.cfg")}
            for ex, p in extras:
                mapping[_extra_key(ex.id)] = p
                files[_extra_key(ex.id)] = (p, ex.target)
            say("Creando copia de seguridad…")
            try:
                backup = self._create_backup(install, "original" if first else "auto",
                                             rec.get("installed_version"), files)
            except OSError as e:
                raise InstallError(f"No se pudo crear la copia de seguridad: {e}") from e

            changes: dict[str, str | None] = {}
            try:
                say("Copiando la traducción…")
                ensure_dir(gpath.parent)
                atomic_copy(staged, gpath)
                if sha256_file(gpath) != entry.sha256:
                    raise IntegrityError("La comprobación del archivo instalado ha fallado.")
                for ex, p in extras:
                    say("Cambiando la pantalla de carga de Easy Anti-Cheat…" if ex.id == "splash"
                        else f"Copiando {ex.target}…")
                    atomic_copy(Path(staged_extras[ex.id]), p)
                    if sha256_file(p) != ex.sha256:
                        raise IntegrityError(f"La comprobación de {ex.target} ha fallado.")
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
                problems = self._restore_files(backup.path, mapping)
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
                old_files = r.get("files") or {}
                extras_rec = dict(r.get("extras") or {})
                files_rec = {self.cfg.translation_rel_path: entry.sha256}
                for ex_id, target in extras_rec.items():  # extras anteriores no tocados ahora
                    if old_files.get(target):
                        files_rec[target] = old_files[target]
                for ex, _ in extras:
                    files_rec[ex.target] = ex.sha256
                    extras_rec[ex.id] = ex.target
                r.update({
                    "path": install.path, "channel": install.channel, "managed": True,
                    "installed_version": version, "installed_at": now_iso(),
                    "files": files_rec, "extras": extras_rec,
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

    # ------------------------------------------------------------- extras
    def restore_extras(self, install: GameInstall) -> list[str]:
        """Devuelve los archivos extra (splash) a su estado anterior a la traducción."""
        notes: list[str] = []
        rec = self._record(install) or {}
        channel_dir = Path(install.path)
        done: list[str] = []
        for ex_id, target in (rec.get("extras") or {}).items():
            try:
                p = safe_target(channel_dir, target)
            except SCTradError as e:
                notes.append(str(e))
                continue
            ours = (rec.get("files") or {}).get(target)
            if not p.is_file() or not ours or sha256_file(p) != ours:
                done.append(ex_id)  # ya no es el nuestro (p. ej. lo cambió un parche): no se toca
                continue
            found = self._oldest_backup_with(install, _extra_key(ex_id))
            if not found:
                notes.append(f"No hay copia del original de {target}; se deja como está.")
                continue
            problems = self._restore_files(found[0].path, {_extra_key(ex_id): p})
            if problems:
                notes.extend(problems)
            else:
                done.append(ex_id)
        if done:
            with self.store.transaction() as s:
                r = s["installs"].get(install.key)
                if r is not None:
                    for ex_id in done:
                        target = (r.get("extras") or {}).pop(ex_id, None)
                        if target:
                            (r.get("files") or {}).pop(target, None)
        return notes

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
            problems = self._restore_files(b.path, {"global.ini": gpath})
            if problems:
                self.store.add_history(install.path, install.channel, "restaurar", b.version_before, "error",
                                       "; ".join(problems))
                raise InstallError("No se pudo restaurar la copia: " + "; ".join(problems))
            sha = sha256_file(gpath) if gpath.is_file() else None
            with self.store.transaction() as s:
                r = s["installs"].setdefault(install.key, {"path": install.path, "channel": install.channel})
                files = {k: v for k, v in (r.get("files") or {}).items() if k != self.cfg.translation_rel_path}
                if sha:
                    files[self.cfg.translation_rel_path] = sha
                r["files"] = files
                r["installed_version"] = b.version_before
                r["managed"] = True
                r["pending_version"] = None
                if current_version:
                    # Tras volver atrás, no reinstalar automáticamente la versión descartada.
                    r["hold_until_newer_than"] = current_version
            self.store.add_history(install.path, install.channel, "restaurar", b.version_before, "ok",
                                   f"Restaurada la copia {b.id}")

    # --------------------------------------------------------- desinstalar
    def uninstall(self, install: GameInstall) -> list[str]:
        """Quita la traducción y deja el juego en INGLÉS (idioma de serie).

        - Borra data/Localization/<idioma>/global.ini (y la carpeta si queda vacía).
        - Quita de user.cfg la línea g_language con el idioma español (el juego vuelve al inglés) y la de
          g_languageAudio si la añadió el gestor. El resto de user.cfg no se toca.
        - Devuelve la pantalla de carga de Easy Anti-Cheat que había antes de instalar la traducción.
        Antes se guarda una copia de seguridad para poder deshacerlo.
        """
        notes: list[str] = []
        with self.op_lock:
            if self.is_game_running():
                raise GameRunningError("Star Citizen está abierto. Ciérralo y vuelve a intentarlo.")
            channel_dir, gpath, cpath = self._paths(install)
            rec = self._record(install) or {}
            files = {"global.ini": (gpath, self.cfg.translation_rel_path), "user.cfg": (cpath, "user.cfg")}
            try:
                if gpath.exists() or cpath.exists():
                    self._create_backup(install, "auto", rec.get("installed_version"), files)
                if gpath.exists():
                    gpath.unlink()
                try:
                    if gpath.parent.is_dir() and not any(gpath.parent.iterdir()):
                        gpath.parent.rmdir()
                except OSError:
                    pass
                notes += self.restore_extras(install)
                if cpath.is_file():
                    raw = cpath.read_bytes()
                    cfg_text = CfgText(raw)
                    lang = (cfg_text.get("g_language") or "").lower()
                    if lang == self.cfg.user_cfg_settings.get("g_language", "").lower() or lang.startswith("spanish"):
                        cfg_text.remove("g_language")
                    prev = rec.get("user_cfg_previous") or {}
                    if "g_languageAudio" in prev and prev["g_languageAudio"] is None:
                        cfg_text.remove("g_languageAudio", only_value=self.cfg.user_cfg_settings.get("g_languageAudio"))
                    new = cfg_text.to_bytes()
                    if new != raw:
                        atomic_write_bytes(cpath, new)
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
                                   "Traducción desinstalada: el juego vuelve al inglés"
                                   + (f" ({'; '.join(notes)})" if notes else ""))
        return notes
