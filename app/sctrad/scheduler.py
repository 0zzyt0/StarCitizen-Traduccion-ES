"""Tarea del Programador de tareas de Windows que arranca el vigilante.

Se crea una tarea del usuario actual (sin privilegios) que, al iniciar sesión, lanza
`SCTraduccionES.exe --vigilante`. El vigilante comprueba las actualizaciones cuando se abre
el RSI Launcher y cuando se cierra Star Citizen. Si Windows no permite crear la tarea, se usa
como alternativa la clave HKCU\\...\\Run.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
WATCH_ARG = "--vigilante"
TASK_VERSION = 2  # 1 = comprobación periódica (gestor 1.0.x); 2 = vigilante del launcher/juego
CREATE_NO_WINDOW = 0x08000000


def executable_command() -> tuple[str, str]:
    """(ejecutable, argumentos) para lanzar el vigilante."""
    if getattr(sys, "frozen", False):
        return sys.executable, WATCH_ARG
    # Modo desarrollo: pythonw + script principal.
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[1] / "main.py"
    return str(pyw if pyw.exists() else exe), f'"{main}" {WATCH_ARG}'


def build_task_xml(command: str, arguments: str, user_id: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Comprueba la traducción al español de Star Citizen al abrir el RSI Launcher y al cerrar el juego.</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{escape(user_id)}</UserId>
      <Delay>PT30S</Delay>
    </LogonTrigger>
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
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT5M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
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


def register(task_name: str, interval_hours: int = 24) -> tuple[bool, str, str | None]:
    """Crea o actualiza la tarea y arranca el vigilante. Devuelve (ok, método, error)."""
    if os.name != "nt":
        return False, "", "Las tareas programadas solo están disponibles en Windows."
    command, arguments = executable_command()
    xml = build_task_xml(command, arguments, _current_user())
    fd, tmp = tempfile.mkstemp(suffix=".xml")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-16") as f:
            f.write(xml)
        r = _run(["schtasks", "/Create", "/TN", task_name, "/XML", tmp, "/F"])
        if r.returncode == 0:
            _remove_run_key(task_name)
            _run(["schtasks", "/Run", "/TN", task_name])  # arrancar el vigilante ya, sin esperar al reinicio
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
        _start_now(command, arguments)
        return True, "run_key", None
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


def _start_now(command: str, arguments: str) -> None:
    import shlex

    try:
        args = [command, *shlex.split(arguments, posix=False)]
        args = [a.strip('"') for a in args]
        subprocess.Popen(args, close_fds=True, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError as e:
        log.warning("No se pudo arrancar el vigilante: %r", e)


def stop_watcher() -> None:
    from .procs import kill_other_instances

    exe = Path(sys.executable).name if getattr(sys, "frozen", False) else "SCTraduccionES.exe"
    kill_other_instances(exe, WATCH_ARG)


def unregister(task_name: str) -> tuple[bool, str | None]:
    if os.name != "nt":
        return True, None
    _remove_run_key(task_name)
    stop_watcher()
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


def apply_settings(service, enabled: bool, interval_hours: int = 24) -> str | None:
    """Sincroniza la tarea con los ajustes y los guarda. Devuelve un aviso o None."""
    name = service.cfg.scheduled_task_name
    if enabled:
        # Se marca antes de registrar: el vigilante arranca enseguida y lee estos ajustes.
        service.store.update_settings(auto_update=True, interval_hours=interval_hours, task_registered=True)
        ok, method, err = register(name, interval_hours)
        service.store.update_settings(task_registered=ok, task_method=method or None, task_error=err,
                                      task_version=TASK_VERSION if ok else None)
        return err
    ok, err = unregister(name)
    service.store.update_settings(auto_update=False, task_registered=not ok, task_method=None,
                                  task_error=err)
    return err


def ensure_current(service) -> None:
    """Migra la tarea de una versión anterior del gestor a la actual (vigilante)."""
    if os.name != "nt":
        return
    s = service.store.settings()
    if s.get("auto_update") and s.get("task_registered") and s.get("task_version") != TASK_VERSION:
        log.info("Actualizando la tarea programada al modo vigilante.")
        apply_settings(service, True, int(s.get("interval_hours", 24)))
