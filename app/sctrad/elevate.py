"""Reintento con permisos de administrador (solo cuando Windows lo exige).

El gestor funciona sin privilegios. Si la carpeta del juego no admite escritura,
se lanza una copia del gestor elevada (UAC) que ejecuta SOLO la operación pedida
(instalar / reparar / desinstalar / restaurar) sobre las carpetas indicadas, y
devuelve el resultado en un archivo JSON.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from pathlib import Path

from .errors import SCTradError

log = logging.getLogger(__name__)

ELEVATED_ARG = "--elevated-op"


def can_elevate() -> bool:
    return os.name == "nt"


def _command(op_file: Path) -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, f'{ELEVATED_ARG} "{op_file}"'
    main = Path(__file__).resolve().parents[1] / "main.py"
    return sys.executable, f'"{main}" {ELEVATED_ARG} "{op_file}"'


def run_elevated(op: dict, data_dir: Path, timeout_ms: int = 15 * 60 * 1000) -> dict:
    if not can_elevate():
        raise SCTradError("La elevación de permisos solo está disponible en Windows.")
    import ctypes
    from ctypes import wintypes

    folder = Path(data_dir) / "elevated"
    folder.mkdir(parents=True, exist_ok=True)
    op_file = folder / f"op-{uuid.uuid4().hex}.json"
    res_file = op_file.with_suffix(".result.json")
    op = dict(op, data_dir=str(data_dir), result_file=str(res_file))
    op_file.write_text(json.dumps(op, ensure_ascii=False), encoding="utf-8")

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE),
        ]

    exe, params = _command(op_file)
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = params
    info.nShow = 0
    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32
    try:
        if not shell32.ShellExecuteExW(ctypes.byref(info)):
            err = ctypes.GetLastError()
            if err == 1223:
                raise SCTradError("Has cancelado la solicitud de permisos de administrador.")
            raise SCTradError(f"No se pudo solicitar permisos de administrador (error {err}).")
        kernel32.WaitForSingleObject(info.hProcess, timeout_ms)
        kernel32.CloseHandle(info.hProcess)
        try:
            return json.loads(res_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise SCTradError("La operación con permisos de administrador no devolvió resultado.") from e
    finally:
        for f in (op_file, res_file):
            try:
                f.unlink()
            except OSError:
                pass


def handle_elevated_op(op_path: str) -> int:
    """Se ejecuta dentro del proceso elevado."""
    from .config import load_config
    from .gamepaths import install_key
    from .service import UpdateService

    op_file = Path(op_path)
    op = json.loads(op_file.read_text(encoding="utf-8"))
    result: dict = {"ok": [], "errors": {}}
    try:
        cfg = load_config()
        svc = UpdateService(cfg, data_dir=Path(op["data_dir"]))
        wanted = {install_key(p) for p in op.get("paths", [])}
        kind = op.get("op")
        if kind == "install":
            res = svc.check(include_app=False)
            if not res.manifest or not res.release:
                raise SCTradError(res.error or "No hay traducción disponible.")
            for st in res.statuses:
                if st.install.key not in wanted:
                    continue
                try:
                    svc.install_one(st, res.release, res.manifest, action=op.get("action", "instalar"),
                                    allow_foreign=bool(op.get("allow_foreign")),
                                    allow_incompatible=bool(op.get("allow_incompatible")),
                                    touch_user_cfg=bool(op.get("touch_user_cfg", True)))
                    result["ok"].append(st.install.path)
                except SCTradError as e:
                    result["errors"][st.install.path] = str(e)
        elif kind in ("uninstall", "restore"):
            for gi in svc.known_installs():
                if gi.key not in wanted:
                    continue
                try:
                    if kind == "uninstall":
                        svc.uninstall_one(gi)
                    else:
                        svc.installer.restore(gi, op["backup_id"])
                    result["ok"].append(gi.path)
                except SCTradError as e:
                    result["errors"][gi.path] = str(e)
        else:
            raise SCTradError("Operación no reconocida.")
    except Exception as e:  # noqa: BLE001
        log.exception("Fallo en operación elevada")
        result["fatal"] = str(e)
    Path(op["result_file"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return 0 if not result.get("fatal") and not result["errors"] else 1
