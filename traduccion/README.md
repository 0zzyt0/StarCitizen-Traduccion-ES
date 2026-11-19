# Carpeta de publicación de la traducción

Sube aquí los archivos traducidos, uno por canal del juego:

```
traduccion/LIVE/global.ini
traduccion/PTU/global.ini
traduccion/EPTU/global.ini          (opcional)
traduccion/TECH-PREVIEW/global.ini  (opcional)
```

Cada vez que se suba un cambio a esta carpeta en la rama `main`, GitHub Actions valida los
archivos y, si todo está bien, publica una versión nueva que los gestores de los jugadores
instalan solos. Instrucciones completas en [docs/MANTENEDOR.md](../docs/MANTENEDOR.md).

- `compatibilidad.json`: versiones del juego de cada canal.
- `NOTAS.md`: notas de la versión que verán los jugadores.
- `validacion.json`: reglas de validación.
