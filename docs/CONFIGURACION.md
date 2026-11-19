# Configuración y formatos

## `config/app_config.json` (va dentro del .exe)

| Campo | Descripción |
|---|---|
| `github_owner`, `github_repo` | Repositorio público del que se descargan las traducciones. |
| `translation_tag_prefix` | Prefijo de las etiquetas de traducción (`traduccion-v`). |
| `app_tag_prefix` | Prefijo de las etiquetas del gestor (`app-v`). |
| `manifest_asset`, `manifest_signature_asset` | Nombres del manifiesto y su firma en cada release. |
| `signing_public_key` | Clave pública Ed25519 (base64) con la que se verifica la firma. |
| `require_signature` | Si es `true`, nunca se instala una publicación sin firma válida. |
| `language_folder` | Carpeta de idioma en `data\Localization` (`spanish_(spain)`). |
| `user_cfg_settings` | Líneas que se aseguran en `user.cfg`. |
| `user_cfg_only_if_absent` | Ajustes que solo se añaden si el jugador no los tiene (p. ej. `g_languageAudio`). |
| `channels` | Canales del juego soportados (`LIVE`, `PTU`, `EPTU`, `TECH-PREVIEW`). |
| `allowed_hosts` | Únicos servidores a los que se conecta el gestor (HTTPS). |
| `game_process_names` | Procesos que indican que el juego está abierto. |
| `search_roots` | Rutas donde buscar el juego en cada unidad (`{drive}` = `C:`, `D:`…). |
| `launcher_logs` | Registros del RSI Launcher de los que se extraen rutas de instalación. |
| `default_check_interval_hours` | Intervalo por defecto de la comprobación automática. |
| `max_backups_per_install` | Copias de versiones anteriores que se guardan (la original se conserva siempre). |
| `max_payload_bytes` | Tamaño máximo aceptado de un `global.ini`. |
| `scheduled_task_name` | Nombre de la tarea del Programador de tareas. |
| `min_app_version_for_payload` | (Opcional, solo publicación) versión mínima del gestor que se escribe en el manifiesto. |

Las rutas que se escriben en el juego están fijadas en el código y no se pueden cambiar desde el manifiesto:
`data/Localization/<language_folder>/global.ini` y `user.cfg`, siempre dentro de la carpeta de canal validada.

## Manifiesto de cada publicación (`manifest.json`, schema 1)

```json
{
  "schema": 1,
  "translation_version": "2026.11.19.1",
  "published_at": "2026-11-19T10:00:00Z",
  "min_app_version": "1.0.0",
  "language_folder": "spanish_(spain)",
  "notes": "Cambios de esta versión",
  "channels": {
    "LIVE": {
      "asset": "global_LIVE.ini",
      "size": 15234567,
      "sha256": "…64 hex…",
      "target": "data/Localization/spanish_(spain)/global.ini",
      "game_versions": ["4.3"]
    }
  }
}
```

`manifest.json.sig` = firma Ed25519 en base64 de los bytes exactos de `manifest.json`.
El gestor rechaza la publicación si: la firma no es válida, la versión no coincide con la etiqueta,
falta un archivo o su tamaño no coincide, el SHA-256 no coincide, la ruta de destino no es la permitida,
o el gestor es más antiguo que `min_app_version`.

## Datos locales del jugador (`%LOCALAPPDATA%\SC-Traduccion-ES`)

```
state.json     ajustes, instalaciones gestionadas, versión instalada, historial, caché de GitHub
backups\       copias de seguridad por instalación (original + últimas versiones)
staging\       descargas verificadas pendientes de instalar
logs\          registros (gestor.log, segundo_plano.log)
```

`state.json` (schema 1):

```json
{
  "schema": 1,
  "settings": {"auto_update": true, "mode": "silent|notify", "release_channel": "stable|beta",
               "interval_hours": 24, "task_registered": true, "task_method": "schtasks|run_key",
               "task_error": null, "first_run_done": true},
  "installs": {
    "c:\\...\\starcitizen\\live": {
      "path": "C:\\...\\StarCitizen\\LIVE", "channel": "LIVE", "managed": true,
      "installed_version": "2026.11.19.1", "installed_at": "…",
      "files": {"data/Localization/spanish_(spain)/global.ini": "<sha256>"},
      "user_cfg_previous": {"g_language": "english", "g_languageAudio": null},
      "original_backup": "20261119-101500-original",
      "pending_version": null, "attention": null, "hold_until_newer_than": null
    }
  },
  "custom_paths": [],
  "history": [{"time": "…", "path": "…", "channel": "LIVE", "action": "actualizar",
               "version": "…", "result": "ok", "detail": "…"}],
  "cache": {"http": {}, "release": {}, "manifest_b64": "…", "signature_b64": "…"},
  "last_check": {"time": "…", "result": "ok", "available_version": "…"}
}
```

## Tarea programada

Nombre: `SC-Traduccion-ES Actualizador` (usuario actual, sin privilegios). Desencadenadores: inicio de sesión
(+2 min) y cada N horas. Acción: `SCTraduccionES.exe --background-update`. Si Windows no permite crearla, se usa
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` (solo al iniciar sesión). Se elimina al desactivar las
actualizaciones o al desinstalar el programa.
