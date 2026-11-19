# Traducción al español de Star Citizen

Traducción de la comunidad de los textos de Star Citizen al español, con un instalador para Windows que
**la instala y la mantiene actualizada sola**. Proyecto no oficial, sin relación con Cloud Imperium Games.

## Descargar e instalar

1. Descarga **`StarCitizen_Traduccion_ES_Setup.exe`** desde la
   [página de publicaciones](https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases?q=app-v&expanded=true)
   (la publicación que se llama «Gestor X.Y.Z (instalador)»).
2. Ejecútalo. No hace falta ser administrador.
   - Si Windows muestra «Windows protegió su PC», pulsa **Más información → Ejecutar de todas formas**.
     Aparece porque el instalador no está firmado con un certificado de pago; el código es público en este repositorio.
3. Al terminar se abre el asistente:
   - Detecta tus instalaciones de Star Citizen (LIVE, PTU, EPTU, TECH-PREVIEW). Si no encuentra el juego,
     pulsa **Examinar…** y elige la carpeta `StarCitizen` (por ejemplo
     `C:\Program Files\Roberts Space Industries\StarCitizen`).
   - Marca dónde quieres la traducción, revisa el resumen y pulsa **Instalar**.
4. Abre Star Citizen como siempre: los textos estarán en español.

Solo tienes que descargar el instalador **una vez**. Las traducciones nuevas llegan solas.

## Qué cambia en tu juego

En cada canal que elijas:

- Se copia `data\Localization\spanish_(spain)\global.ini` (los textos en español).
- En `user.cfg` se añade `g_language = spanish_(spain)` y, si no lo tenías, `g_languageAudio = english`
  (para no perder las voces). El resto de tus ajustes de `user.cfg` no se toca.
- Antes de cambiar nada se guarda una **copia de seguridad**.

## Actualizaciones automáticas

Si las activas (recomendado), el gestor crea una tarea ligera de Windows que comprueba GitHub al iniciar
sesión y cada 24 horas. No queda ningún programa abierto en segundo plano.

- Cuando hay una versión nueva, se descarga, se verifica (firma digital y SHA-256) y se instala sola.
  Recibirás una notificación de Windows.
- **Nunca** se cambia nada con Star Citizen abierto: la actualización espera a que cierres el juego.
- Si la versión nueva no está marcada como compatible con tu versión del juego, se pausa y se mantiene la actual.
- Si algo falla, se restaura automáticamente la versión anterior.

En el gestor, pestaña **Actualizaciones automáticas**, puedes:

- Activarlas o desactivarlas.
- Elegir entre *instalar automáticamente* o *solo avisarme*.
- Elegir el canal **Estable** (recomendado) o **Beta** (traducciones en pruebas).
- Cambiar cada cuántas horas se comprueba.

Para abrir el gestor: menú Inicio → **Traducción Star Citizen**. Ahí también tienes **Buscar ahora** e **Historial**.

## Volver atrás o quitar la traducción

- **Restaurar copia de seguridad…**: vuelve a una versión anterior de la traducción o al estado original del juego.
  Si vuelves a una versión anterior, no se actualizará sola hasta que salga otra más nueva.
- **Desinstalar traducción**: deja el juego exactamente como estaba (restaura la copia original y revierte
  `user.cfg`).
- Para quitar también el programa: Configuración de Windows → Aplicaciones → *Traducción al español de Star
  Citizen* → Desinstalar. Te preguntará si quieres quitar también la traducción del juego.

## Problemas frecuentes

| Problema | Solución |
|---|---|
| No encuentra el juego | Pulsa **Examinar…** / **Añadir carpeta…** y elige la carpeta `StarCitizen` o la de un canal (`LIVE`). |
| Pide permisos de administrador | Tu carpeta del juego no admite escritura con tu usuario. Acepta «Reintentar como administrador»: solo se tocan `global.ini` y `user.cfg`. |
| «Otra traducción / archivo modificado» | Ya había un `global.ini` que no instaló el gestor. Al instalar se guarda copia y se sustituye; al desinstalar se recupera. |
| «Compatibilidad no verificada» | No se pudo leer la versión del juego o la traducción no declara versiones. Normalmente funciona igual. |
| Sigue en inglés | Comprueba en el gestor que el canal que juegas (LIVE/PTU) está *Actualizada* y pulsa **Reparar**. |
| Sin conexión | El gestor muestra los últimos datos guardados y reintentará más tarde. Tu traducción instalada no se toca. |
| Salen textos tipo `@ui_...` | El juego se actualizó y añadió textos nuevos que aún no están traducidos; llegarán en la próxima versión. |

Los registros están en `%LOCALAPPDATA%\SC-Traduccion-ES\logs` (botón **Abrir carpeta de registros** en el gestor).
Si abres una incidencia, adjúntalos: no contienen contraseñas ni datos personales.

## Privacidad

El gestor solo se conecta a `api.github.com` y a los servidores de descarga de GitHub para consultar y bajar las
publicaciones de este repositorio. No envía ningún dato tuyo ni usa telemetría. Todo lo que guarda (ajustes,
historial, copias de seguridad) está en `%LOCALAPPDATA%\SC-Traduccion-ES`.

## Para el mantenedor

Ver [docs/MANTENEDOR.md](docs/MANTENEDOR.md) y [docs/CONFIGURACION.md](docs/CONFIGURACION.md).
