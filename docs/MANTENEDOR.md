# Guía del mantenedor

Cómo funciona todo, cómo publicar una traducción nueva y cómo generar el instalador.

## Visión general

```
traduccion/<CANAL>/global.ini  ──push a main──►  Actions «Publicar traducción»
                                                   ├─ valida (formato, claves, marcadores, sin tildes)
                                                   ├─ versión nueva AAAA.M.D.N (siempre creciente)
                                                   ├─ manifest.json + firma Ed25519 + SHA256SUMS
                                                   └─ GitHub Release «traduccion-vAAAA.M.D.N» (latest)
                                                              │
Vigilante del jugador (arranca con Windows) ── al abrir RSI Launcher.exe / al cerrar StarCitizen.exe
  └─ GET /releases/latest → descarga manifest.json + .sig → verifica firma → descarga global_<CANAL>.ini
     y splash_<CANAL>.png → comprueba SHA-256 → juego cerrado y sin parchear → copia → instala → verifica
```

Hay dos tipos de publicación en el mismo repositorio, bien diferenciados en *Releases*:

| Título | Etiqueta | Qué contiene | Quién la crea | ¿«Latest»? |
|---|---|---|---|---|
| ⬇️ INSTALADOR — Gestor X.Y.Z (descarga aquí) | `app-vX.Y.Z` | `StarCitizen_Traduccion_ES_Setup.exe` (+ `.sha256`) | *Compilar instalador* | **Sí, siempre** |
| 🔄 Traducción AAAA.M.D.N — actualización automática | `traduccion-vAAAA.M.D.N` | `global_<CANAL>.ini`, `splash_<CANAL>.png`, `manifest.json(.sig)`, `SHA256SUMS.txt` | *Publicar traducción* | Nunca |

El workflow **Organizar releases** se ejecuta solo después de cada publicación: pone los títulos y textos, marca el
instalador como *Latest* y, si una traducción ha quedado encima, vuelve a crear la release del instalador (misma
etiqueta y mismos archivos) para que sea siempre la primera de la página. El enlace fijo
`https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases/latest/download/StarCitizen_Traduccion_ES_Setup.exe`
descarga siempre el instalador más reciente (es el botón del README). Los gestores buscan la traducción por su
etiqueta `traduccion-v…`, no por «Latest». (Al volver a crearse la release, su contador de descargas se reinicia.)

Las versiones de la traducción, del gestor y del juego son independientes.

## Configuración inicial (una sola vez)

### 1. Secreto de firma

Las publicaciones se firman para que nadie pueda colar archivos falsos a los jugadores. La clave pública ya está
en `config/app_config.json` (`signing_public_key`). La privada debe guardarse como secreto del repositorio:

1. GitHub → repositorio → **Settings → Secrets and variables → Actions → New repository secret**.
2. Nombre: `MANIFEST_SIGNING_KEY`. Valor: el contenido del archivo `MANIFEST_SIGNING_KEY.txt` que se te entregó.
3. Guarda una copia del archivo en un sitio seguro y fuera del repositorio (gestor de contraseñas, USB).
   **No lo subas nunca al repositorio.**

Si se pierde o se filtra la clave: genera un par nuevo (ver «Cambiar la clave de firma»), publica un gestor nuevo
y pide a los jugadores que lo instalen.

### 2. Permisos de Actions

**Settings → Actions → General → Workflow permissions**: deja «Read repository contents…» (los workflows piden
`contents: write` solo en el paso de publicación).

### 3. Primer instalador

Se genera solo: cada vez que cambia el código del gestor en `main`, el workflow **Compilar instalador** pasa las
pruebas, compila el .exe en un servidor Windows de GitHub, crea el instalador con Inno Setup y, si todavía no
existe, publica la release `app-v<versión>` (la versión sale de `app/sctrad/__init__.py`). Tarda unos 10 minutos. Comprueba en la
pestaña **Actions** que termina en verde y en **Releases** que está `StarCitizen_Traduccion_ES_Setup.exe`.

También se puede lanzar a mano (Actions → Compilar instalador → Run workflow); en ese caso el instalador queda
como *artifact* descargable de la ejecución, sin crear release.

## Publicar una traducción nueva

### Pantalla de carga de Easy Anti-Cheat

Cada canal puede llevar su imagen: `traduccion/LIVE/SplashScreen.png` (azul) y `traduccion/PTU/SplashScreen.png`
(violeta). PNG de **800x450**. Se publica junto con la traducción (`splash_LIVE.png`, `splash_PTU.png`), firmada
en el manifiesto, y el gestor la copia a `<canal>\EasyAntiCheat\SplashScreen.png` guardando la original.
Para cambiar la imagen basta con subir otra: no hace falta recompilar el gestor.

### Opción A — desde la web de GitHub (sin instalar nada)

1. Entra en la carpeta `traduccion/LIVE` del repositorio → **Add file → Upload files**.
2. Arrastra tu `global.ini` (debe llamarse exactamente así).
3. Repite con `traduccion/PTU` si toca.
4. Edita `traduccion/NOTAS.md` con los cambios y pon en `traduccion/compatibilidad.json` la versión confirmada del juego.
5. **Commit changes** directamente en `main`.

### Opción B — con git

```bash
cp ~/traducciones/global_ES_LIVE.ini traduccion/LIVE/global.ini
cp ~/traducciones/global_ES_PTU.ini  traduccion/PTU/global.ini
git add traduccion
git commit -m "Traducción parche 4.x.y"
git push
```

### Qué pasa después

En **Actions → Publicar traducción** verás dos pasos:

1. **Validar traducción**: si hay errores (claves repetidas, líneas rotas, tildes, marcadores perdidos…) el
   resumen de la ejecución los lista y **no se publica nada**. Corrige y vuelve a subir.
2. **Publicar release**: crea la release en borrador, sube los archivos, comprueba que lo subido es idéntico y
   solo entonces la hace pública y «latest».

Si subes los mismos archivos sin cambios, no se publica nada (para forzarlo: Run workflow → *forzar*).
Para una traducción en pruebas: Run workflow → *beta* (solo la reciben quienes elijan el canal Beta).

Los jugadores la recibirán la próxima vez que abran el RSI Launcher o cierren el juego, o al pulsar
**Buscar ahora** en el gestor.

### Comprobar la publicación

- **Releases**: debe aparecer «Traducción AAAA.M.D.N» con `global_<CANAL>.ini`, `splash_<CANAL>.png`,
  `manifest.json`, `manifest.json.sig` y `SHA256SUMS.txt`.
- En tu PC: abre el gestor → **Buscar ahora**: la columna *Disponible* muestra la versión nueva.

## Compatibilidad con versiones del juego

Antes de cada publicación, el mantenedor **confirma** a qué versión del juego corresponde cada `global.ini` y se
escribe en `traduccion/compatibilidad.json`, por ejemplo `{ "LIVE": ["4.10"], "PTU": ["5.0"] }`.
No se usa `Frontend_PU_Version` como fuente fiable porque CIG no siempre la actualiza. Si un canal queda en
`"auto"`, la herramienta la lee de esa línea como respaldo y deja un aviso en el registro de Actions.

- `4.10` acepta 4.10.0, 4.10.1, 4.10.3…
- Si el juego del jugador es de otra versión, la actualización automática **se pausa** y se mantiene su traducción
  actual; en el gestor puede instalarla a mano confirmando el aviso.
- Para forzarlo a mano (raro), pon una lista: `{ "LIVE": ["4.10", "5.0"] }`.

El gestor lee la versión del juego de `build_manifest.id` en la carpeta del canal; si no puede, muestra
«Compatibilidad no verificada».

## Validación con el inglés original (recomendado)

Sube el `global.ini` original en inglés a `referencia/<CANAL>/global.ini`. La validación comprobará que no faltan
claves y que se conservan `~mission(...)`, `<EM4>`, `%ls`, `{...}` y `\n`. Los niveles se ajustan en
`traduccion/validacion.json` (`error`, `aviso` o `ignorar`). La regla «sin tildes» también se configura ahí.

Los archivos se publican **byte a byte**: el empaquetado nunca modifica la traducción.

## Nueva versión del gestor

1. Cambia `__version__` en `app/sctrad/__init__.py` (p. ej. `1.1.0`).
2. Commit y push a `main`. El workflow crea la release `app-v1.1.0` con el instalador nuevo.
   (También funciona crear la etiqueta: `git tag app-v1.1.0 && git push origin app-v1.1.0`.)

El gestor avisa a los jugadores de que hay una versión nueva del programa con un enlace (no se actualiza solo:
la actualización del programa es independiente de la de la traducción). Al ejecutar el instalador nuevo encima
del anterior se conservan ajustes, historial y copias.

Si un cambio futuro del manifiesto exigiera un gestor nuevo, sube `min_app_version` (la herramienta lo toma de
`min_app_version_for_payload` en `config/app_config.json`): los gestores antiguos lo detectarán y pedirán actualizar.

## Firma de código del .exe (opcional)

Sin firma, Windows SmartScreen muestra un aviso la primera vez. Si consigues un certificado de firma de código
(o un programa gratuito para proyectos libres, como SignPath Foundation), añade los secretos
`WINDOWS_CERT_PFX_BASE64` (el .pfx en base64) y `WINDOWS_CERT_PASSWORD`; el workflow firmará el .exe y el
instalador automáticamente.

## Cambiar la clave de firma

```bash
python -c "import base64;from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey as K;from cryptography.hazmat.primitives import serialization as s;k=K.generate();print('PRIVADA',base64.b64encode(k.private_bytes(s.Encoding.Raw,s.PrivateFormat.Raw,s.NoEncryption())).decode());print('PUBLICA',base64.b64encode(k.public_key().public_bytes(s.Encoding.Raw,s.PublicFormat.Raw)).decode())"
```

Pon la pública en `config/app_config.json`, la privada en el secreto `MANIFEST_SIGNING_KEY`, sube la versión del
gestor y publica el instalador nuevo. Los gestores antiguos rechazarán las publicaciones firmadas con la clave
nueva hasta que se actualicen.

## Desarrollo local

```bash
pip install -r requirements-dev.txt
python app/main.py                     # abrir el gestor
python app/main.py --background-update # simular la tarea programada
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Compilar el instalador en un PC con Windows (alternativa a GitHub Actions):

```powershell
pip install -r requirements-dev.txt
pyinstaller installer\SCTraduccionES.spec --noconfirm --clean
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 installer\setup.iss
# Resultado: Output\StarCitizen_Traduccion_ES_Setup.exe
```

## Estructura del proyecto

```
app/main.py                 punto de entrada (gestor, --background-update, --uninstall-cleanup)
app/sctrad/config.py        configuración
app/sctrad/gamepaths.py     detección de instalaciones, versión del juego, compatibilidad
app/sctrad/net.py           HTTPS con lista de servidores permitidos, reintentos, redirecciones validadas
app/sctrad/github.py        API de GitHub Releases (con caché ETag)
app/sctrad/manifest.py      manifiesto y firma Ed25519
app/sctrad/downloader.py    descarga con reanudación y SHA-256
app/sctrad/installer.py     instalación atómica, copias, restauración, desinstalación
app/sctrad/usercfg.py       edición mínima de user.cfg
app/sctrad/service.py       orquestación y modo segundo plano
app/sctrad/scheduler.py     Programador de tareas de Windows (arranca el vigilante al iniciar sesión)
app/sctrad/watcher.py       vigilante: detecta la apertura del RSI Launcher y el cierre de StarCitizen.exe
app/sctrad/elevate.py       reintento con permisos de administrador (UAC)
app/sctrad/gui/             interfaz PySide6 (asistente, gestor, notificaciones)
tools/validate_translation.py, tools/build_release.py   herramientas del workflow de publicación
installer/                  PyInstaller (.spec) e Inno Setup (.iss)
.github/workflows/          pruebas, publicar traducción, compilar instalador
tests/                      pruebas automáticas
```
