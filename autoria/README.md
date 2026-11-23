# Pruebas de autoría (OpenTimestamps)

Esta carpeta la mantiene sola GitHub Actions (workflow **Sellar autoría**). No hace falta tocarla.

- `sellos/<etiqueta>/` — una carpeta por cada publicación `traduccion-v…`:
  - `SHA256SUMS.txt`: huellas SHA-256 de todos los archivos publicados (cada `global.ini`, pantallas de carga,
    manifiesto y firma).
  - `SHA256SUMS.txt.ots`: el sello de OpenTimestamps de ese archivo.
  - `manifest.json` y `manifest.json.sig`: el manifiesto y su firma Ed25519 (ver [AUTORIA.md](../AUTORIA.md)).
- `registro/*.txt` + `.ots` — huellas de documentos privados del autor, selladas sin revelar su contenido.

Un sello recién creado queda **pendiente** unas horas hasta que entra en un bloque de Bitcoin. El workflow lo
completa en su ejecución diaria; a partir de ahí la prueba es definitiva y no depende de ningún servidor.

## Cómo comprobar un sello

**Sin instalar nada:** entra en <https://opentimestamps.org>, arrastra el archivo `.ots` y después el archivo
original (`SHA256SUMS.txt`). La web muestra la fecha del bloque de Bitcoin en que quedó registrado.

**Con el cliente oficial:** `pip install opentimestamps-client` y

```
ots verify autoria/sellos/<etiqueta>/SHA256SUMS.txt.ots
```

(para una comprobación completa necesita un nodo de Bitcoin; si no, usa la web).

Para enlazar un `global.ini` con su sello: calcula su SHA-256 y búscalo en `SHA256SUMS.txt`, o usa
`python tools/verificar_autoria.py huella ruta/al/global.ini`.
