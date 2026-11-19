"""Tarea del Programador de tareas de Windows para buscar actualizaciones.

Se crea una tarea del usuario actual (sin privilegios) con dos desencadenadores:
al iniciar sesión (con 2 minutos de retraso) y cada N horas. Si Windows no
permite crearla, se usa como alternativa la clave HKCU\\...\\Run (solo al iniciar sesión).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
BACKGROUND_ARG = "--background-update"
CREATE_NO_WINDOW = 0x08000000


def executable_command() -> tuple[str, str]:
    """(ejecutable, argumentos) para lanzar el modo segundo plano."""
    if getattr(sys, "frozen", False):
        return sys.executable, BACKGROUND_ARG
    # Modo desarrollo: pythonw + script principal.
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[1] / "main.py"
    return str(pyw if pyw.exists() else exe), f'"{main}" {BACKGROUND_ARG}'


def build_task_xml(command: str, arguments: str, interval_hours: int, user_id: str,
                   start: datetime | None = None) -> str:
    interval_hours = max(1, min(int(interval_hours), 24 * 7))
    start = (start or datetime.now() + timedelta(minutes=10)).replace(microsecond=0)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Busca e instala actualizaciones de la traducción al español de Star Citizen.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user_id)}</UserId>
      <Delay>PT2M</Delay>
    </LogonTrigger>
    <TimeTrigger>
      <Repetition>
        <Interval>PT{interval_hours}H</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{start.isoformat()}</StartBoundary>
      <Enabled>true</Enabled>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT9H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
    </Exec>
  </Actions>
</Task>
"""


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
                          if os.name == "nt" else 0, timeout=60)


def _current_user() -> str:
    dom = os.environ.get("USERDOMAIN")
    user = os.environ.get("USERNAME") or os.getlogin()
    return f"{dom}\\{user}" if dom else user


def register(task_name: str, interval_hours: int) -> tuple[bool, str, str | None]:
    """Crea o actualiza la tarea. Devuelve (ok, método, error)."""
    if os.name != "nt":
        return False, "", "Las tareas programadas solo están disponibles en Windows."
    command, arguments = executable_command()
    xml = build_task_xml(command, arguments, interval_hours, _current_user())
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-16") as f:
            f.write(xml)
        r = _run(["schtasks", "/Create", "/TN", task_name, "/XML", tmp, "/F"])
        if r.returncode == 0:
            _remove_run_key(task_name)
            return True, "schtasks", None
        err = (r.stderr or r.stdout or "").strip()
        log.warning("schtasks falló (%s): %s", r.returncode, err)
    except (OSError, subprocess.SubprocessError) as e:
        err = repr(e)
        log.warning("schtasks no disponible: %r", e)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    # Alternativa: iniciar con la sesión del usuario.
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, task_name, 0, winreg.REG_SZ, f'"{command}" {arguments}')
        return True, "run_key", f"No se pudo crear la tarea programada ({err}); se comprobará al iniciar sesión."
    except OSError as e:
        return False, "", f"No se pudo programar la comprobación automática: {err}; {e}"


def _remove_run_key(task_name: str) -> None:
    if os.name != "nt":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, task_name)
    except OSError:
        pass


def unregister(task_name: str) -> tuple[bool, str | None]:
    if os.name != "nt":
        return True, None
    _remove_run_key(task_name)
    try:
        r = _run(["schtasks", "/Delete", "/TN", task_name, "/F"])
        if r.returncode == 0 or not is_registered(task_name):
            return True, None
        return False, (r.stderr or r.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, repr(e)


def is_registered(task_name: str) -> bool:
    if os.name != "nt":
        return False
    try:
        r = _run(["schtasks", "/Query", "/TN", task_name])
        if r.returncode == 0:
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, task_name)
            return True
    except OSError:
        return False


def apply_settings(service, enabled: bool, interval_hours: int) -> str | None:
    """Sincroniza la tarea con los ajustes y los guarda. Devuelve un aviso o None."""
    name = service.cfg.scheduled_task_name
    if enabled:
        ok, method, err = register(name, interval_hours)
        service.store.update_settings(auto_update=True, interval_hours=interval_hours,
                                      task_registered=ok, task_method=method or None, task_error=err)
        return err
    ok, err = unregister(name)
    service.store.update_settings(auto_update=False, task_registered=not ok, task_method=None,
                                  task_error=err)
    return err
