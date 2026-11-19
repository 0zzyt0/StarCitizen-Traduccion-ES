"""Estado local del gestor (JSON en la carpeta de datos del usuario).

Esquema (schema 1):
{
  "schema": 1,
  "settings": {
    "auto_update": bool, "mode": "silent" | "notify", "release_channel": "stable" | "beta",
    "interval_hours": int, "task_registered": bool, "task_method": "schtasks" | "run_key" | null,
    "task_error": str | null, "first_run_done": bool
  },
  "installs": {
    "<clave normalizada de la ruta>": {
      "path": str, "channel": str, "managed": bool,
      "installed_version": str | null, "installed_at": str | null,
      "files": {"data/Localization/.../global.ini": "<sha256>"},
      "user_cfg_previous": {"g_language": valor anterior | null, ...},
      "pending_version": str | null, "attention": str | null
    }
  },
  "custom_paths": [str],
  "history": [{"time", "path", "channel", "action", "version", "result", "detail"}],
  "cache": {"http": {url: {"etag", "data"}}, "manifest_b64", "signature_b64", "release": {...}},
  "last_check": {"time", "result", "available_version"}
}
"""

from __future__ import annotations

import copy
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .lock import FileLock

MAX_HISTORY = 300


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_state(interval_hours: int = 24) -> dict:
    return {
        "schema": 1,
        "settings": {
            "auto_update": True,
            "mode": "silent",
            "release_channel": "stable",
            "interval_hours": interval_hours,
            "task_registered": False,
            "task_method": None,
            "task_error": None,
            "first_run_done": False,
        },
        "installs": {},
        "custom_paths": [],
        "history": [],
        "cache": {"http": {}},
        "last_check": None,
    }


def _merge_defaults(data: dict, defaults: dict) -> dict:
    for k, v in defaults.items():
        if k not in data or (isinstance(v, dict) and not isinstance(data[k], dict)):
            data[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and k != "installs":
            _merge_defaults(data[k], v)
    return data


class StateStore:
    def __init__(self, data_dir: Path, interval_hours: int = 24):
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "state.json"
        self.interval_hours = interval_hours
        self._lock = FileLock(self.data_dir / "state.lock", timeout=15)

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema") != 1:
                raise ValueError("schema")
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError):
            # Estado dañado: se guarda una copia y se empieza de cero (las copias de seguridad siguen en disco).
            try:
                self.path.replace(self.path.with_suffix(f".corrupto-{datetime.now():%Y%m%d%H%M%S}.json"))
            except OSError:
                pass
            data = {}
        return _merge_defaults(data, default_state(self.interval_hours))

    def _write(self, data: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(".state.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def snapshot(self) -> dict:
        with self._lock:
            return self._read()

    @contextmanager
    def transaction(self):
        with self._lock:
            data = self._read()
            yield data
            self._write(data)

    # --- ayudas -------------------------------------------------------------
    def settings(self) -> dict:
        return self.snapshot()["settings"]

    def update_settings(self, **kwargs) -> None:
        with self.transaction() as s:
            s["settings"].update(kwargs)

    def add_history(self, path: str, channel: str, action: str, version: str | None,
                    result: str, detail: str = "") -> None:
        with self.transaction() as s:
            s["history"].append({
                "time": now_iso(), "path": path, "channel": channel, "action": action,
                "version": version, "result": result, "detail": detail[:500],
            })
            del s["history"][:-MAX_HISTORY]
