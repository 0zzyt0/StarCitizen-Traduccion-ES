"""Orquestación: comprobar, descargar, instalar y actualizar en segundo plano.

Este módulo no depende de Qt: lo usan tanto la interfaz como la tarea programada.
"""

from __future__ import annotations

import base64
import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import AppConfig, default_data_dir
from .downloader import download_verified
from .errors import (ForeignFileError, GameRunningError, IncompatibleError, ManifestError, NetworkError,
                     PermissionNeededError, SCTradError, BusyError)
from .gamepaths import (COMPAT_LABELS, INCOMPATIBLE, GameInstall, check_compat, detect_installs,
                        install_key, is_valid_channel_dir, make_install, normalize_user_path)
from .github import Release, ReleaseClient
from .installer import Installer
from .lock import FileLock
from .manifest import ChannelEntry, Manifest, parse_manifest, verify_signature
from .net import Http
from .procs import is_game_running
from .state import StateStore, now_iso
from .version import compare_versions, is_newer

log = logging.getLogger(__name__)

# Estados de cada instalación
ST_NOT_INSTALLED = "no_instalada"
ST_UP_TO_DATE = "actualizada"
ST_UPDATE = "actualizacion"
ST_MISSING = "falta"
ST_FOREIGN = "ajena"
ST_NO_CHANNEL = "sin_canal"
ST_UNKNOWN = "desconocido"

STATE_LABELS = {
    ST_NOT_INSTALLED: "No instalada",
    ST_UP_TO_DATE: "Actualizada",
    ST_UPDATE: "Actualización disponible",
    ST_MISSING: "Faltan archivos (reparar)",
    ST_FOREIGN: "Otra traducción / archivo modificado",
    ST_NO_CHANNEL: "Sin traducción para este canal",
    ST_UNKNOWN: "Sin datos de GitHub",
}


@dataclass
class InstallStatus:
    install: GameInstall
    record: dict | None
    installed_version: str | None
    available_version: str | None
    compat: str
    state: str
    entry: ChannelEntry | None
    held: bool = False

    @property
    def managed(self) -> bool:
        return bool(self.record and self.record.get("managed"))

    @property
    def state_label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)

    @property
    def compat_label(self) -> str:
        return COMPAT_LABELS.get(self.compat, self.compat)


@dataclass
class MissingChannel:
    """Canal del juego que no está instalado en este PC (se muestra en gris)."""
    channel: str
    path: str | None
    available_version: str | None = None


@dataclass
class CheckResult:
    release: Release | None
    manifest: Manifest | None
    statuses: list[InstallStatus] = field(default_factory=list)
    error: str | None = None
    offline: bool = False
    app_release: Release | None = None
    checked_at: str = ""


@dataclass
class Notice:
    title: str
    text: str
    kind: str = "info"  # info | ok | warning


class UpdateService:
    def __init__(self, cfg: AppConfig, data_dir: Path | None = None, http: Http | None = None,
                 client: ReleaseClient | None = None, game_running: Callable[[], bool] | None = None,
                 detector: Callable[[], list[GameInstall]] | None = None):
        self.cfg = cfg
        self.data_dir = Path(data_dir) if data_dir else default_data_dir(cfg.app_id)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = StateStore(self.data_dir, cfg.default_check_interval_hours)
        self.http = http or Http(cfg.allowed_hosts)
        self._client = client
        self.game_running = game_running or (lambda: is_game_running(cfg.game_process_names))
        self.detector = detector or (lambda: detect_installs(cfg))
        self.installer = Installer(cfg, self.store, self.data_dir, self.game_running)
        self.staging_dir = self.data_dir / "staging"

    # ----------------------------------------------------------- instalaciones
    def known_installs(self) -> list[GameInstall]:
        snap = self.store.snapshot()
        found: dict[str, GameInstall] = {}
        for gi in self.detector():
            found[gi.key] = gi
        extra_paths = list(snap.get("custom_paths", [])) + [r["path"] for r in snap["installs"].values() if "path" in r]
        for p in extra_paths:
            for gi in normalize_user_path(p, self.cfg):
                found.setdefault(gi.key, gi)
        # Instalaciones gestionadas cuya carpeta ya no existe: se muestran igualmente para poder limpiarlas.
        for key, r in snap["installs"].items():
            if key not in found and "path" in r:
                found[key] = GameInstall(r["path"], r.get("channel", "?"))
        return sorted(found.values(), key=lambda g: (self.cfg.channels.index(g.channel)
                                                      if g.channel in self.cfg.channels else 99, g.path.lower()))

    def add_custom_path(self, path: str) -> list[GameInstall]:
        installs = normalize_user_path(path, self.cfg)
        if installs:
            with self.store.transaction() as s:
                for gi in installs:
                    if gi.path not in s["custom_paths"]:
                        s["custom_paths"].append(gi.path)
        return installs

    def refresh_install(self, gi: GameInstall) -> GameInstall:
        p = Path(gi.path)
        return make_install(p, gi.channel) if is_valid_channel_dir(p) else gi

    # ---------------------------------------------------------------- GitHub
    def _client_with_cache(self) -> tuple[ReleaseClient, dict]:
        cache = dict(self.store.snapshot()["cache"].get("http", {}))
        if self._client is not None:
            self._client.cache = cache
            return self._client, cache
        return ReleaseClient(self.cfg, self.http, cache), cache

    def fetch_release(self) -> tuple[Release | None, Manifest | None, bool, str | None]:
        """Devuelve (publicación, manifiesto, sin_conexión, error)."""
        include_pre = self.store.settings().get("release_channel") == "beta"
        client, cache = self._client_with_cache()
        try:
            rel = client.latest_translation(include_prerelease=include_pre)
            if rel is None:
                with self.store.transaction() as s:
                    s["cache"]["http"] = cache
                return None, None, False, "Todavía no hay ninguna traducción publicada en GitHub."
            m_asset = rel.assets.get(self.cfg.manifest_asset)
            if not m_asset:
                raise ManifestError(f"La publicación {rel.tag} no contiene {self.cfg.manifest_asset}.")
            raw = client.download_small(m_asset)
            s_asset = rel.assets.get(self.cfg.manifest_signature_asset)
            sig = client.download_small(s_asset, 4096) if s_asset else None
            status = verify_signature(raw, sig, self.cfg)
            manifest = parse_manifest(raw, self.cfg, expected_version=rel.version, signature_status=status)
            with self.store.transaction() as s:
                s["cache"]["http"] = cache
                s["cache"]["release"] = rel.to_dict()
                s["cache"]["manifest_b64"] = base64.b64encode(raw).decode()
                s["cache"]["signature_b64"] = base64.b64encode(sig).decode() if sig else None
            return rel, manifest, False, None
        except NetworkError as e:
            log.warning("Sin conexión con GitHub: %s (%s)", e, e.detail)
            rel, man = self._cached_release()
            return rel, man, True, str(e)
        except ManifestError as e:
            log.error("Manifiesto rechazado: %s (%s)", e, e.detail)
            return None, None, False, str(e)

    def _cached_release(self) -> tuple[Release | None, Manifest | None]:
        c = self.store.snapshot()["cache"]
        try:
            if not c.get("release") or not c.get("manifest_b64"):
                return None, None
            rel = Release.from_dict(c["release"])
            raw = base64.b64decode(c["manifest_b64"])
            sig = base64.b64decode(c["signature_b64"]) if c.get("signature_b64") else None
            status = verify_signature(raw, sig, self.cfg)
            return rel, parse_manifest(raw, self.cfg, expected_version=rel.version, signature_status=status)
        except (SCTradError, ValueError, KeyError, TypeError):
            return None, None

    def fetch_app_release(self) -> Release | None:
        try:
            client, cache = self._client_with_cache()
            rel = client.latest_app()
            with self.store.transaction() as s:
                s["cache"]["http"] = cache
            return rel
        except SCTradError as e:
            log.info("No se pudo comprobar la versión del gestor: %s", e)
            return None

    # ----------------------------------------------------------------- estado
    def status_for(self, gi: GameInstall, manifest: Manifest | None, snap: dict | None = None) -> InstallStatus:
        snap = snap or self.store.snapshot()
        rec = snap["installs"].get(gi.key)
        installed = rec.get("installed_version") if rec else None
        entry = manifest.channels.get(gi.channel) if manifest else None
        available = manifest.version if (manifest and entry) else None
        compat = check_compat(gi.game_version, entry.game_versions) if entry else check_compat(gi.game_version, [])
        try:
            insp = self.installer.inspect(gi, entry.sha256 if entry else None)
        except SCTradError:
            insp = None
        # Un parche del juego (o el launcher) puede haber restaurado la pantalla de carga original.
        extras_broken = bool(insp and insp.ours and installed and entry and entry.extras
                             and snap["settings"].get("splash", True)
                             and self.installer.extras_needing_repair(gi, entry))
        held = bool(rec and rec.get("hold_until_newer_than") and available
                     and not is_newer(available, rec["hold_until_newer_than"]))
        if insp and insp.foreign:
            state = ST_FOREIGN
        elif insp and insp.missing_ours:
            state = ST_MISSING
        elif not installed or not (insp and insp.ours):
            state = ST_NOT_INSTALLED if manifest is None or entry else ST_NO_CHANNEL
        elif manifest is None:
            state = ST_UNKNOWN
        elif entry is None:
            state = ST_NO_CHANNEL
        elif is_newer(available, installed):
            state = ST_UPDATE
        elif extras_broken:
            state = ST_MISSING
        else:
            state = ST_UP_TO_DATE
        return InstallStatus(gi, rec, installed, available, compat, state, entry, held)

    def check(self, include_app: bool = True) -> CheckResult:
        rel, man, offline, err = self.fetch_release()
        snap = self.store.snapshot()
        statuses = [self.status_for(gi, man, snap) for gi in self.known_installs()]
        app_rel = self.fetch_app_release() if include_app and not offline else None
        res = CheckResult(rel, man, statuses, err, offline, app_rel, now_iso())
        with self.store.transaction() as s:
            s["last_check"] = {"time": res.checked_at, "result": "error" if err else "ok",
                               "available_version": man.version if man else None, "detail": err}
        return res

    # ------------------------------------------------------------ descargar
    def stage(self, rel: Release, manifest: Manifest, channel: str,
              progress: Callable[[int, int], None] | None = None,
              cancel: threading.Event | None = None) -> tuple[Path, ChannelEntry]:
        entry = manifest.channels.get(channel)
        if not entry:
            raise IncompatibleError(f"La versión {manifest.version} no incluye traducción para el canal {channel}.")
        asset = rel.assets.get(entry.asset)
        if not asset or asset.size != entry.size:
            raise ManifestError(f"El archivo {entry.asset} falta en la publicación o su tamaño no coincide.")
        dest = self.staging_dir / manifest.version / entry.asset
        path = download_verified(self.http, asset.url, dest, entry.size, entry.sha256, progress, cancel)
        return path, entry

    def stage_extras(self, rel: Release, manifest: Manifest, channel: str) -> dict[str, Path]:
        """Descarga y verifica los extras del canal (si el jugador los tiene activados)."""
        entry = manifest.channels.get(channel)
        if not entry or not entry.extras or not self.store.settings().get("splash", True):
            return {}
        out: dict[str, Path] = {}
        for ex in entry.extras:
            if self.cfg.extra_targets.get(ex.id) != ex.target:
                continue
            asset = rel.assets.get(ex.asset)
            if not asset or asset.size != ex.size:
                raise ManifestError(f"El archivo {ex.asset} falta en la publicación o su tamaño no coincide.")
            dest = self.staging_dir / manifest.version / ex.asset
            out[ex.id] = download_verified(self.http, asset.url, dest, ex.size, ex.sha256)
        return out

    def set_splash(self, enabled: bool) -> list[str]:
        """Activa o desactiva la pantalla de carga personalizada. Al desactivarla se restaura la original."""
        self.store.update_settings(splash=bool(enabled))
        notes: list[str] = []
        if not enabled:
            snap = self.store.snapshot()
            for gi in self.known_installs():
                rec = snap["installs"].get(gi.key)
                if rec and rec.get("extras"):
                    if self.game_running():
                        raise GameRunningError("Star Citizen está abierto. Ciérralo para restaurar la pantalla "
                                               "de carga original.")
                    notes += self.installer.restore_extras(gi)
        return notes

    def cleanup_staging(self, keep_version: str | None) -> None:
        if not self.staging_dir.is_dir():
            return
        for d in self.staging_dir.iterdir():
            if d.name != keep_version:
                shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------ instalar
    def install_one(self, st: InstallStatus, rel: Release, manifest: Manifest, action: str = "instalar",
                    allow_foreign: bool = False, allow_incompatible: bool = False,
                    touch_user_cfg: bool = True, progress_bytes=None, progress_text=None,
                    cancel: threading.Event | None = None) -> str:
        if st.compat == INCOMPATIBLE and not allow_incompatible:
            raise IncompatibleError(
                f"La traducción {manifest.version} no está marcada como compatible con tu versión del juego "
                f"({st.install.game_version})."
            )
        say = progress_text or (lambda _m: None)
        say(f"Descargando la traducción {manifest.version} ({st.install.channel})…")
        staged, entry = self.stage(rel, manifest, st.install.channel, progress_bytes, cancel)
        extras = self.stage_extras(rel, manifest, st.install.channel)
        self.installer.install(st.install, staged, entry, manifest.version, action=action,
                               allow_foreign=allow_foreign, touch_user_cfg=touch_user_cfg, progress=say,
                               staged_extras=extras)
        return manifest.version

    def uninstall_one(self, gi: GameInstall) -> list[str]:
        return self.installer.uninstall(gi)

    # ---------------------------------------------------- segundo plano
    def run_background(self, wait_for_game: bool = True, poll_seconds: float = 120,
                       max_wait_seconds: float = 8 * 3600,
                       sleep: Callable[[float], None] = time.sleep, origin: str = "programada") -> list[Notice]:
        """Comprobación desatendida. Solo devuelve avisos cuando hay algo que contar al jugador."""
        notices: list[Notice] = []
        bg_lock = FileLock(self.data_dir / "background.lock", timeout=0)
        try:
            bg_lock.acquire()
        except BusyError:
            log.info("Ya hay una comprobación en segundo plano en marcha.")
            return notices
        try:
            log.info("Comprobación en segundo plano (origen: %s).", origin)
            settings = self.store.settings()
            if not settings.get("auto_update", True):
                log.info("Actualizaciones automáticas desactivadas.")
                return notices
            rel, man, offline, err = self.fetch_release()
            with self.store.transaction() as s:
                s["last_check"] = {"time": now_iso(), "result": "error" if err else "ok",
                                   "available_version": man.version if man else None, "detail": err,
                                   "origin": origin}
            if offline or rel is None or man is None:
                log.info("Comprobación sin resultado: %s", err)
                return notices
            snap = self.store.snapshot()
            updates: list[InstallStatus] = []
            repairs: list[InstallStatus] = []
            for gi in self.known_installs():
                st = self.status_for(gi, man, snap)
                if not st.managed or st.held:
                    continue
                if st.state == ST_MISSING and not is_newer(man.version, st.installed_version or "0"):
                    repairs.append(st)  # restaurar nuestros propios archivos: siempre, sin preguntar
                elif st.state in (ST_UPDATE, ST_MISSING):
                    if st.compat == INCOMPATIBLE:
                        self._attention(st, f"La versión {man.version} no está marcada como compatible con "
                                            f"el juego {gi.game_version}. Se mantiene la traducción actual.")
                        self._notice_once(notices, f"incompat:{gi.key}:{man.version}", Notice(
                            "Actualización en pausa",
                            f"{gi.channel}: la traducción {man.version} es para otra versión del juego. "
                            "Se mantiene la actual.", "warning"))
                        continue
                    updates.append(st)
            if updates and settings.get("mode") == "notify":
                self._notice_once(notices, f"nueva:{man.version}", Notice(
                    "Nueva traducción disponible",
                    f"Versión {man.version} para {', '.join(st.install.channel for st in updates)}. "
                    "Abre el gestor para instalarla."))
                updates = []
            for st in repairs + updates:
                notices.extend(self._background_install(st, rel, man, wait_for_game, poll_seconds,
                                                        max_wait_seconds, sleep))
            self.cleanup_staging(man.version)
            return notices
        finally:
            bg_lock.release()

    def _notice_once(self, notices: list[Notice], key: str, notice: Notice) -> None:
        """Añade el aviso solo si no se mostró antes (evita repetirlo en cada apertura del launcher)."""
        with self.store.transaction() as s:
            seen = s["settings"].setdefault("notified", [])
            if key in seen:
                return
            seen.append(key)
            del seen[:-60]
        notices.append(notice)

    @staticmethod
    def game_files_busy(gi: GameInstall, window: float = 180.0) -> bool:
        """True si el launcher parece estar parcheando el juego (Data.p4k modificado hace muy poco)."""
        try:
            return time.time() - (Path(gi.path) / "Data.p4k").stat().st_mtime < window
        except OSError:
            return False

    def _attention(self, st: InstallStatus, text: str) -> None:
        with self.store.transaction() as s:
            r = s["installs"].get(st.install.key)
            if r is not None:
                r["attention"] = text

    def _background_install(self, st: InstallStatus, rel: Release, man: Manifest, wait_for_game: bool,
                            poll_seconds: float, max_wait_seconds: float, sleep) -> list[Notice]:
        gi = st.install
        action = "reparar" if st.state == ST_MISSING else "actualizar"
        try:
            staged, entry = self.stage(rel, man, gi.channel)
            extras = self.stage_extras(rel, man, gi.channel)
        except SCTradError as e:
            log.warning("Descarga fallida para %s: %s", gi.path, e)
            return []  # se reintentará en la próxima comprobación
        with self.store.transaction() as s:
            r = s["installs"].get(gi.key)
            if r is not None:
                r["pending_version"] = man.version
        if self.game_files_busy(gi):
            log.info("El juego se está actualizando (%s); se instalará en la próxima comprobación.", gi.path)
            return []
        waited = 0.0
        while self.game_running():
            if not wait_for_game or waited >= max_wait_seconds:
                log.info("El juego sigue abierto; la versión %s queda pendiente.", man.version)
                return []
            sleep(poll_seconds)
            waited += poll_seconds
        # Si el jugador borró user.cfg (p. ej. reinstalación del juego) se vuelve a crear; si existe se respeta.
        touch_cfg = not (Path(gi.path) / "user.cfg").exists()
        for attempt in range(3):
            try:
                self.installer.install(gi, staged, entry, man.version, action=action, touch_user_cfg=touch_cfg,
                                       staged_extras=extras)
                if action == "reparar":
                    log.info("%s: archivos de la traducción restaurados (%s).", gi.channel, man.version)
                    return []  # mantenimiento silencioso: no molesta al jugador
                return [Notice("Traducción actualizada",
                               f"{gi.channel}: instalada la versión {man.version}.", "ok")]
            except GameRunningError:
                if attempt == 2 or not wait_for_game:
                    return []
                sleep(poll_seconds)
            except BusyError:
                sleep(30)
            except (ForeignFileError, PermissionNeededError) as e:
                self._attention(st, str(e))
                out: list[Notice] = []
                self._notice_once(out, f"atencion:{gi.key}:{man.version}:{type(e).__name__}",
                                  Notice("La traducción necesita tu atención", f"{gi.channel}: {e}", "warning"))
                return out
            except SCTradError as e:
                self._attention(st, str(e))
                log.error("Actualización fallida en %s: %s (%s)", gi.path, e, e.detail)
                out = []
                self._notice_once(out, f"fallo:{gi.key}:{man.version}", Notice(
                    "No se pudo actualizar la traducción",
                    f"{gi.channel}: {e} Se mantiene la versión anterior.", "warning"))
                return out
        return []

    def channel_rows(self, statuses: list[InstallStatus], manifest: Manifest | None = None
                     ) -> list[InstallStatus | MissingChannel]:
        """Todas las instalaciones encontradas más una fila por cada canal que no está instalado,
        en el orden de la configuración (LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW)."""
        present = {st.install.channel for st in statuses}
        roots: list[str] = []
        for st in statuses:
            r = str(Path(st.install.path).parent)
            if r not in roots:
                roots.append(r)
        rows: list[InstallStatus | MissingChannel] = list(statuses)
        for ch in self.cfg.channels:
            if ch not in present:
                av = manifest.version if manifest and ch in manifest.channels else None
                rows.append(MissingChannel(ch, str(Path(roots[0]) / ch) if roots else None, av))
        order = {c: i for i, c in enumerate(self.cfg.channels)}

        def key(x):
            ch = x.channel if isinstance(x, MissingChannel) else x.install.channel
            return (order.get(ch, 99), isinstance(x, MissingChannel))
        return sorted(rows, key=key)

    # ------------------------------------------------------------- ajustes
    def set_managed(self, gi: GameInstall, managed: bool) -> None:
        with self.store.transaction() as s:
            r = s["installs"].get(gi.key)
            if r is not None:
                r["managed"] = managed

    def history(self) -> list[dict]:
        return list(reversed(self.store.snapshot()["history"]))


def compare_app_version(remote: Release | None, local: str) -> bool:
    if not remote:
        return False
    try:
        return compare_versions(remote.version, local) > 0
    except ValueError:
        return False


__all__ = ["UpdateService", "InstallStatus", "CheckResult", "Notice", "install_key", "compare_app_version"]
