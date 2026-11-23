<p align="center">
  <img src="assets/icono.png" width="150" alt="Traducción al español de Star Citizen">
</p>

<h1 align="center">Traducción al español de Star Citizen</h1>

<p align="center">
  <a href="https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases/latest/download/StarCitizen_Traduccion_ES_Setup.exe">
    <img src="https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_DESCARGAR_INSTALADOR-Windows_10%2F11_(.exe)-38d6ff?style=for-the-badge&logo=windows&logoColor=white" height="46" alt="Descargar el instalador">
  </a>
</p>

<p align="center">
  <b>Descárgalo una sola vez:</b> instala la traducción y la mantiene actualizada sola.<br>
  <a href="https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases/latest">Página del instalador</a> ·
  <a href="https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases?q=INSTALADOR&expanded=true">Todos los instaladores</a> ·
  <a href="https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases?q=traduccion-v&expanded=true">Historial de traducciones</a>
</p>

Traducción de la comunidad de los textos de Star Citizen al español, con un instalador para Windows que
**la instala y la mantiene actualizada sola**. Proyecto no oficial, sin relación con Cloud Imperium Games.

> **¿Qué descargo de la página *Releases*?** Solo la publicación **⬇️ INSTALADOR — Gestor …** (siempre la primera,
> marcada como *Latest*). Las publicaciones **🔄 Traducción …** son las actualizaciones de los textos: el gestor las
> instala solo, **no hay que descargarlas**.

## Descargar e instalar

1. Descarga **[`StarCitizen_Traduccion_ES_Setup.exe`](https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases/latest/download/StarCitizen_Traduccion_ES_Setup.exe)**
   (el botón de arriba; o en *Releases*, la publicación **⬇️ INSTALADOR — Gestor …**).
2. Ejecútalo. No hace falta ser administrador.
   - Si Windows muestra «Windows protegió su PC», pulsa **Más información → Ejecutar de todas formas**.
     Aparece porque el instalador no está firmado con un certificado de pago; el código es público en este repositorio.
3. Se abre el gestor: una sola ventana con un botón grande.
   - **ACTUALIZAR en verde**: hay traducción nueva (o aún no la tienes). Púlsalo y listo.
   - **ACTUALIZAR en naranja**: ya tienes la última traducción.
   - **DESINSTALAR**: quita la traducción y deja el juego en **inglés**.
   - **AVISO**: si el equipo de la traducción publica un aviso (por ejemplo «Trabajando en la versión PTU 5.0»),
     aparece en una tira naranja encima de los canales, con el texto desplazándose.
4. Abre Star Citizen como siempre: los textos estarán en español.

Solo tienes que descargar el instalador **una vez**.

## Canales y versiones

La ventana muestra los canales **LIVE, PTU, EPTU, HOTFIX y TECH-PREVIEW**. Si el juego está en otra carpeta, usa
**Elegir carpeta del juego…**.

**HOTFIX, EPTU y TECH-PREVIEW son canales temporales**: CIG solo los abre en momentos concretos (a veces solo existe
LIVE). Cada uno tiene un interruptor **Traducir**:

| Situación del canal | Cómo se ve |
|---|---|
| No está instalado en tu PC o CIG lo tiene cerrado | En gris, **Inaccesible** (interruptor bloqueado) |
| Instalado, pero aún no hay traducción para él | En gris, **Sin traducción** |
| Instalado y con traducción | En color, con el interruptor activo |

La primera vez que aparece uno de estos canales con traducción disponible, el gestor te pregunta si quieres
traducirlo y **recuerda tu respuesta**. Si lo activas y CIG cierra el canal, cuando vuelva a abrirlo la traducción se
pondrá sola al abrir el RSI Launcher. Si lo desactivas, el gestor no lo toca (y te pregunta si quitarle la
traducción para dejarlo en inglés). LIVE y PTU se traducen siempre.

Para cada canal se ve la versión **instalada** y la **disponible**. Salen de la línea
`Personal_Translation_Version` del `global.ini`, por ejemplo `Traduccion 0zzyt0 PTU v5.0`: canal y versión del
juego a la que corresponde la traducción. HOTFIX usa la misma traducción que LIVE.

## Qué cambia en tu juego

En cada canal:

- Se copia `data\Localization\spanish_(spain)\global.ini` (los textos en español).
- En `user.cfg` se añade `g_language = spanish_(spain)` y, si no lo tenías, `g_languageAudio = english`
  (para no perder las voces). El resto de tus ajustes de `user.cfg` no se toca.
- Se cambia la **pantalla de carga de Easy Anti-Cheat** (`EasyAntiCheat\SplashScreen.png`) por la de la traducción
  de ese canal: **LIVE azul**, **PTU violeta**, **HOTFIX verde**, **EPTU naranja**, **TECH-PREVIEW**. Si al arrancar el
  juego la ves, la traducción está instalada.
- Antes de cambiar nada se guarda una **copia de seguridad**.

## Comprobación automática

No hay que configurar nada. Al abrir el gestor por primera vez se activa un **vigilante** muy ligero (unos 20 MB
de memoria, sin ventana) que comprueba GitHub en dos momentos:

- **Al abrir el RSI Launcher**: si hay una traducción nueva, se instala antes de que pulses «Jugar».
- **Al cerrar Star Citizen** (`StarCitizen.exe`).

Solo verás una notificación de Windows **cuando haya una actualización**. Si un parche del juego borra la traducción
o devuelve la pantalla de carga original, se vuelve a poner sola. **Nunca** se cambia nada con el juego abierto ni
mientras el launcher está parcheando. Cada descarga se verifica (firma digital y SHA-256) antes de instalarla.

## Desinstalar

- **DESINSTALAR** (en el gestor): quita la traducción de todos los canales, quita el español de `user.cfg` (el juego
  vuelve al **inglés**) y devuelve la pantalla de carga anterior. Se guarda una copia de seguridad.
- Para quitar también el programa: Configuración de Windows → Aplicaciones → *Traducción al español de Star
  Citizen* → Desinstalar. Te preguntará si quieres quitar también la traducción del juego.

## Problemas frecuentes

| Problema | Solución |
|---|---|
| No encuentra el juego | Pulsa **Elegir carpeta del juego…** y elige la carpeta `StarCitizen` o la de un canal (`LIVE`). |
| Pide permisos de administrador | Tu carpeta del juego no admite escritura con tu usuario. Acepta: solo se tocan `global.ini`, `user.cfg` y la pantalla de carga. |
| Sigue en inglés | Abre el gestor y pulsa **ACTUALIZAR** si está en verde. |
| No veo la pantalla de carga de la traducción | Pulsa **ACTUALIZAR** (se vuelve a poner si un parche la quitó). |
| Sin conexión | El gestor muestra los últimos datos guardados y reintentará más tarde. Tu traducción instalada no se toca. |
| Salen textos tipo `@ui_...` | El juego se actualizó y añadió textos nuevos que aún no están traducidos; llegarán en la próxima versión. |

Los registros están en `%LOCALAPPDATA%\SC-Traduccion-ES\logs`. Si abres una incidencia, adjúntalos: no contienen
contraseñas ni datos personales.

## Privacidad

El gestor solo se conecta a `api.github.com` y a los servidores de descarga de GitHub para consultar y bajar las
publicaciones de este repositorio. No envía ningún dato tuyo ni usa telemetría. Todo lo que guarda (ajustes,
historial, copias de seguridad) está en `%LOCALAPPDATA%\SC-Traduccion-ES`.

## Para el mantenedor

Ver [docs/MANTENEDOR.md](docs/MANTENEDOR.md) y [docs/CONFIGURACION.md](docs/CONFIGURACION.md).
