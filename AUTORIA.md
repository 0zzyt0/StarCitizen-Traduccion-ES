# Autoría y fuente oficial

La traducción al español de Star Citizen de este repositorio es obra de **0zzyt0**.

## Única fuente oficial

- Repositorio: **https://github.com/0zzyt0/StarCitizen-Traduccion-ES**
- Instalador: [`StarCitizen_Traduccion_ES_Setup.exe`](https://github.com/0zzyt0/StarCitizen-Traduccion-ES/releases/latest/download/StarCitizen_Traduccion_ES_Setup.exe),
  publicado solo en la página *Releases* de este repositorio.

Cualquier copia de esta traducción descargada de otro sitio (webs, Discord, Google Drive, Nexus…) **no es oficial,
puede estar modificada y no recibe actualizaciones**. Las versiones antiguas que se distribuyeron por Google Drive ya
no tienen soporte.

## Cómo se protege la autoría

1. **Firma digital de cada publicación.** El archivo `manifest.json` de cada publicación `traduccion-v…` lleva una
   firma Ed25519 (`manifest.json.sig`) hecha con la clave privada del autor, que nunca sale de GitHub Actions.
   El manifiesto contiene la huella SHA-256 de cada `global.ini`. El gestor rechaza cualquier archivo que no esté
   firmado con esta clave.
   - Clave pública: `t+fWqISkUu/wJCa22z/FNR7TPmlEWDZdRIHMT+BjnRc=`
   - Huella de la clave (SHA-256): `9f3e:14a5:6a1e:8743:fa6f:c256:f37b:6ea8`
2. **Sello de tiempo en Bitcoin (OpenTimestamps).** Las huellas de cada publicación se sellan con
   [OpenTimestamps](https://opentimestamps.org) y las pruebas se guardan en [`autoria/`](autoria/README.md).
   Demuestran que esos archivos exactos existían en esa fecha, y no se pueden falsificar ni antedatar.
3. **Commits verificados.** Los cambios del repositorio aparecen en GitHub como *Verified* (firmados).
4. **Registros privados sellados.** El autor conserva pruebas privadas adicionales; su huella queda sellada en el
   tiempo en `autoria/registro/` sin revelar su contenido.
5. **Licencia.** [CC BY-NC-ND 4.0](LICENSE) para la traducción: se puede compartir sin cambios citando al autor; no
   se permite el uso comercial ni distribuir versiones modificadas o atribuirla a otra persona.

## ¿Has encontrado una copia sospechosa?

Abre una incidencia en el repositorio con el enlace. Cualquiera puede comprobar si un `global.ini` es idéntico a uno
publicado aquí:

```
python tools/verificar_autoria.py huella ruta/al/global.ini
```
