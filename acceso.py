"""
Ajustes OPCIONALES para cuando la app se publica en internet. Si no configurás nada, la app se
comporta igual que en tu computadora.

Se configuran en «Secrets» de Streamlit Community Cloud (o en .streamlit/secrets.toml, o con
variables de entorno PLANOS_<NOMBRE>, por ejemplo PLANOS_PASSWORD):

  password       -> clave compartida del equipo; si existe, la app la pide antes de mostrar nada.
  satelite_esri  -> false = no ofrecer el satélite de Esri (si la empresa no tiene licencia para usarlo).
  satelite_url   -> otra fuente de mosaicos satelitales (con {z}, {x} y {y}); reemplaza a Esri.
  satelite_attr  -> texto de atribución que exige esa fuente (se muestra sobre el mapa).
  satelite_maxz  -> zoom máximo de esa fuente (por defecto 18).
"""
import hmac
import os

import streamlit as st

FONDO_ESRI = {
    "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "maxz": 18, "attr": "Imágenes © Esri, Maxar, Earthstar Geographics y la comunidad GIS",
}
FONDO_CALLES = {"url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "maxz": 19,
                "attr": "© colaboradores de OpenStreetMap"}
NOMBRE_SATELITE = "🛰️ Satélite"


def secreto(nombre, defecto=None):
    """Lee un ajuste de los Secrets de Streamlit o de la variable de entorno PLANOS_<NOMBRE>."""
    try:
        if nombre in st.secrets:
            return st.secrets[nombre]
    except Exception:          # no hay archivo de secretos: es lo normal en tu computadora
        pass
    return os.environ.get("PLANOS_" + nombre.upper(), defecto)


def _como_bool(valor, defecto=True):
    if valor is None:
        return defecto
    if isinstance(valor, str):
        return valor.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(valor)


def fondos_disponibles():
    """Devuelve (fondos, avisos): los fondos de mapa que se ofrecen y, si algún ajuste está mal, avisos."""
    fondos, avisos = {}, []
    url = secreto("satelite_url")
    if url:
        url = str(url).strip()
        if all(k in url for k in ("{z}", "{x}", "{y}")):
            try:
                maxz = int(secreto("satelite_maxz", 18))
            except (TypeError, ValueError):
                maxz = 18
            fondos[NOMBRE_SATELITE] = {"url": url, "maxz": maxz, "attr": str(secreto("satelite_attr", "") or "")}
        else:
            avisos.append("El ajuste «satelite_url» tiene que incluir {z}, {x} y {y}; se ignoró.")
            url = None
    if NOMBRE_SATELITE not in fondos and _como_bool(secreto("satelite_esri"), True):
        fondos[NOMBRE_SATELITE] = FONDO_ESRI
    fondos["🗺️ Calles"] = FONDO_CALLES
    fondos["Sin fondo"] = None
    return fondos, avisos


def puerta():
    """Si hay una clave configurada, la pide antes de mostrar la app (y corta la ejecución si no es correcta)."""
    clave = secreto("password")
    if not clave or st.session_state.get("_acceso_ok"):
        return
    st.title("🌱 Planos de siembra")
    st.caption("Acceso restringido al equipo.")
    with st.form("acceso"):
        escrita = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar", type="primary")
    if entrar:
        if hmac.compare_digest(escrita.encode("utf-8"), str(clave).encode("utf-8")):
            st.session_state["_acceso_ok"] = True
            st.rerun()
        st.error("Contraseña incorrecta.")
    st.stop()
