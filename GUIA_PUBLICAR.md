# Cómo publicar «Planos de siembra» para tus compañeros

La forma más simple y gratuita es **Streamlit Community Cloud**: subís estos archivos a GitHub, Streamlit los
convierte en una página web y le pasás el link a tu equipo. Lleva unos 20 minutos la primera vez.

## 1) Decidí tres cosas antes de publicar

**A. Quién puede entrar**

| Opción | Cómo funciona | Cuándo conviene |
|---|---|---|
| **Privada (recomendada)** | Repositorio *privado* en GitHub + app privada. Solo entran las personas que invites por mail (inician sesión). | Equipo chico y conocido. La cuenta gratuita permite **una** app privada. |
| **Pública con contraseña** | App pública + ajuste `password` (ver abajo). Quien tenga el link ve una pantalla de clave. | Equipo grande o con gente externa. Es una barrera simple, **no** una seguridad fuerte. |

**B. Dónde quedan los datos**
- La app **no guarda nada en disco ni en una base de datos**: los KMZ y los ensayos viven en la memoria de la sesión
  de cada persona y se pierden al cerrar la pestaña. Cada persona ve **solo lo suyo** (lo probé con dos sesiones a la vez).
- Pero el programa corre en **servidores de Streamlit (un tercero)**, no en la red de la empresa: los KMZ viajan hasta allá.
  Si las ubicaciones de los lotes son confidenciales, consultalo con TI antes de publicar (ver «Alternativa» más abajo).

**C. El mapa satelital**
- La app pide las imágenes satelitales **directamente a Esri** (servicio *World Imagery*). Según Esri, ese servicio no es de
  uso libre para empresas: requiere una licencia de ArcGIS y sus condiciones pueden cambiar.
- **Antes de dárselo a toda la empresa, confirmalo con TI.** Si no se puede usar, tenés dos salidas (ver «Ajustes opcionales»):
  ocultar el satélite (`satelite_esri = false`) o usar un proveedor con licencia (`satelite_url`).
- El fondo «Calles» usa OpenStreetMap (pide mostrar su atribución, que la app ya muestra; no es para uso masivo).

## 2) Paso a paso

1. **GitHub.** Entrá a github.com (creá la cuenta si no tenés). Botón **New repository** → nombre `planos-siembra` →
   elegí **Private** → **Create repository**.
2. **Subir los archivos.** En el repositorio nuevo: **uploading an existing file** → arrastrá **todo el contenido de esta carpeta**
   (los `.py`, `requirements.txt`, la carpeta `fuentes` y la carpeta `.streamlit`) → **Commit changes**.
   - **No subas `secrets.toml`** (la contraseña no tiene que quedar en GitHub). Los ajustes secretos se cargan en Streamlit (paso 4).
   - Si Windows no te deja ver `.streamlit` (es una carpeta oculta), no pasa nada: es opcional.
3. **Crear la app.** Entrá a **share.streamlit.io** con tu cuenta de GitHub → **Create app** → **Yup, I have an app** →
   elegí tu repositorio, la rama `main` y el archivo principal **`app.py`**. (Si GitHub pide permisos sobre el repositorio, aceptalos.)
4. **Ajustes avanzados.** **Advanced settings** → *Python version* **3.12** → en **Secrets** pegá, si querés, las líneas que
   necesites de `.streamlit/secrets.toml.example` (por ejemplo `password = "la-clave-del-equipo"`).
5. **Deploy.** La primera vez tarda unos minutos mientras instala las librerías. Al terminar te da un link tipo
   `https://tu-nombre.streamlit.app`.
6. **Compartir.** Dentro de la app, botón **Share** (arriba a la derecha): en una app privada, escribí los mails de tus compañeros y
   **Invite**; en una pública, simplemente pasá el link (y la contraseña, si la configuraste).
7. **Actualizar.** Si más adelante cambiás un archivo en GitHub (lápiz de edición → Commit), la app se actualiza sola.

## 3) Primera prueba (hacela vos antes de avisar al equipo)
Subí un KMZ de un lote → ¿se ve el satélite alineado? → agregá un ensayo → arrastralo y girá → ¿aparece la X en la parcela 1 y las
flechas → y ↑? → descargá el Excel y el KMZ para Google Earth. **Yo no pude probarlo en el Streamlit Cloud real**
(solo en un servidor equivalente), así que este chequeo es importante.

## 4) Lo que tenés que saber del plan gratuito
- **Se duerme** cuando nadie la usa durante un tiempo (las fuentes hablan de entre 12 horas y algunos días). La primera persona
  que entra después espera ~30–60 segundos a que despierte.
- **Recursos limitados y sin garantía de servicio.** Sirve para un equipo; no para algo crítico.
- **Sin guardado**: avisá al equipo que exporte el Excel/KMZ antes de cerrar la pestaña.
- Cada persona usa **su propio internet** para bajar los mosaicos del mapa.
- Si algo falla, quien tenga permiso de escritura en el repositorio puede ver los registros desde **Manage app**.

## 5) Alternativa: que lo publique TI dentro de la empresa
Si los datos no pueden salir de la red de la empresa, TI puede correrlo en cualquier servidor con Python 3.10 o más nuevo:

```
pip install -r requirements.txt
python -m streamlit run app.py --server.port 8501
```

detrás del acceso corporativo (VPN / inicio de sesión de la empresa). Los mismos ajustes se pueden dar como variables de entorno:
`PLANOS_PASSWORD`, `PLANOS_SATELITE_ESRI`, `PLANOS_SATELITE_URL`, `PLANOS_SATELITE_ATTR`, `PLANOS_SATELITE_MAXZ`.

## 6) Ajustes opcionales (Secrets)

| Ajuste | Para qué sirve |
|---|---|
| `password = "…"` | La app pide esta clave antes de mostrar nada. |
| `satelite_esri = false` | No ofrece el satélite de Esri (queda «Calles» y «Sin fondo»). |
| `satelite_url = "https://…/{z}/{x}/{y}…"` | Usa otra fuente satelital con licencia (reemplaza a Esri). Debe incluir `{z}`, `{x}` y `{y}`. |
| `satelite_attr = "© …"` | Texto de atribución que exige ese proveedor (se muestra sobre el mapa). |
| `satelite_maxz = 19` | Zoom máximo de esa fuente (por defecto 18). |

Documentación de Streamlit: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy ·
https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app
