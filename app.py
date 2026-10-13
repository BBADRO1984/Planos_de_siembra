"""
Planos de siembra — cargás cada ensayo con sus datos reales, lo ubicás y lo girás sobre el
mapa de tu lote (KMZ con fondo satelital) y exportás a Excel (una foto por ensayo) y a
Google Earth (KMZ con los ensayos). Cada ensayo muestra la parcela 1 (X) y el sentido de
siembra: entradas → de izquierda a derecha y tablones ↑ de abajo hacia arriba.

Ejecutar:  python -m streamlit run app.py   (o doble clic en INICIAR.bat)
"""
import io
from datetime import datetime
from functools import partial

import pandas as pd
import streamlit as st

from acceso import fondos_disponibles, puerta
from geo_kmz import angulo_para_alinear, lados_del_lote, procesar_kmz
from kmz_salida import generar_kmz
from lienzo import lienzo
from logica_planos import (
    COLORES_SUGERIDOS, VERSION, choques_con_referencias, dimensiones, fuera_del_lote, generar_workbook, nuevo_id,
    ocupacion, pct_del_lote, posicion_libre, rumbo_entradas_texto, rumbo_texto, superposiciones, tipos_conocidos,
    validar,
)

st.set_page_config(page_title="Planos de siembra", layout="wide")
puerta()          # si publicaste la app con una contraseña (ver acceso.py), la pide acá

NUEVO = "➕ Nuevo ensayo"
DEFECTO = dict(entradas=4, lineas=2, ancho_lineas=0.7, tablones=28, cable=6.0)
FONDOS, AVISOS_CONFIG = fondos_disponibles()


# ===================================================================== estado
def _campo_vacio():
    return {"ensayos": [], "lote": None, "lote_bytes": None, "lote_archivo": None, "lote_nonce": 0,
            "fit_n": 0, "ultimo": None}


if "campos" not in st.session_state:
    st.session_state.campos = {"Campo 1": _campo_vacio()}
    st.session_state.activo = "Campo 1"


def _flash(tipo, texto):
    st.session_state["_flash"] = (tipo, texto)


def fk(campo, sel, nonce, nombre):
    """Clave de cada casillero del formulario (cambia al cambiar de ensayo,
    así el formulario se recarga solo con los datos del ensayo elegido)."""
    return f"f|{campo}|{sel}|{nonce}|{nombre}"


def _siguiente_nombre(c):
    usados = {e["nombre"] for e in c["ensayos"]}
    n = len(c["ensayos"]) + 1
    while f"Ensayo {n}" in usados:
        n += 1
    return f"Ensayo {n}"


def _norm_angulo(a):
    """Ángulo entre 0 y 359.5, de a medio grado."""
    return (round(float(a) * 2) / 2) % 360


def _ensayo_por_id(c, eid):
    return next((x for x in c["ensayos"] if x["id"] == eid), None)


def _set_angulo(campo, e, a):
    """Cambia el ángulo y deja sincronizados el deslizador y el casillero."""
    e["angulo"] = _norm_angulo(a)
    st.session_state[f"gsl|{campo}|{e['id']}"] = e["angulo"]
    st.session_state[f"gnum|{campo}|{e['id']}"] = e["angulo"]


# ================================================================== callbacks
def cb_evento(campo):
    """El usuario soltó, giró o hizo clic en un ensayo del lienzo."""
    ev = st.session_state[f"lienzo_{campo}"].evento
    c = st.session_state.campos.get(campo)
    e = _ensayo_por_id(c, ev["id"]) if (ev and c) else None
    if e is None:
        return
    c["ultimo"] = e["id"]
    st.session_state[f"gsel_{campo}"] = e["nombre"]
    if ev["tipo"] == "mover":          # arrastrar solo mueve; el formulario no cambia
        e["cx"], e["cy"] = float(ev["x"]), float(ev["y"])
    elif ev["tipo"] == "rotar":
        _set_angulo(campo, e, ev["angulo"])
    else:                              # un clic simple lo carga en el formulario para editarlo
        st.session_state[f"sel_{campo}"] = e["nombre"]


def cb_cambio_seleccion(campo):
    """Eligió otro ensayo en el formulario: se resalta en el lienzo."""
    c = st.session_state.campos[campo]
    e = next((x for x in c["ensayos"] if x["nombre"] == st.session_state[f"sel_{campo}"]), None)
    if e:
        c["ultimo"] = e["id"]
        st.session_state[f"gsel_{campo}"] = e["nombre"]


def cb_slider(campo, eid):
    e = _ensayo_por_id(st.session_state.campos[campo], eid)
    if e is not None:
        _set_angulo(campo, e, st.session_state[f"gsl|{campo}|{eid}"])


def cb_numero(campo, eid):
    e = _ensayo_por_id(st.session_state.campos[campo], eid)
    if e is not None:
        _set_angulo(campo, e, st.session_state[f"gnum|{campo}|{eid}"])


def cb_girar(campo, eid, delta):
    e = _ensayo_por_id(st.session_state.campos[campo], eid)
    if e is not None:
        _set_angulo(campo, e, 0.0 if delta is None else e["angulo"] + delta)


def cb_alinear(campo, eid):
    """Gira el ensayo para que sus tablones corran paralelos al lado elegido del lote."""
    c = st.session_state.campos[campo]
    e = _ensayo_por_id(c, eid)
    if e is None or not c["lote"]:
        return
    lados = lados_del_lote(c["lote"])
    i = min(int(st.session_state.get(f"gal|{campo}", 0)), len(lados) - 1)
    _set_angulo(campo, e, angulo_para_alinear(lados[i]["ang"], e["angulo"]))


def cb_tipo_pill(tipo_key, pill_key):
    """Tocó un tipo ya usado o sugerido: se copia al casillero (que sigue siendo libre)."""
    v = st.session_state.get(pill_key)
    if v:
        st.session_state[tipo_key] = v
        st.session_state[pill_key] = None


def _leer_formulario(campo, sel):
    c = st.session_state.campos[campo]
    g = lambda n: st.session_state[fk(campo, sel, c["lote_nonce"], n)]
    return {
        "nombre": str(g("nombre")).strip(), "tipo": str(g("tipo")).strip(),
        "entradas": int(g("entradas")), "lineas": int(g("lineas")),
        "ancho_lineas": float(g("ancho_lineas")), "tablones": int(g("tablones")),
        "cable": float(g("cable")), "color": g("color"),
    }


def cb_agregar(campo):
    c = st.session_state.campos[campo]
    datos = _leer_formulario(campo, NUEVO)
    errores = validar(datos, {e["nombre"] for e in c["ensayos"]})
    if errores:
        return _flash("error", " ".join(errores))
    d = dimensiones(datos)
    poly = c["lote"]["poly"] if c["lote"] else None
    cx, cy = posicion_libre(c["ensayos"], d["ancho"], d["alto"], poly)
    e = {**datos, "id": nuevo_id(), "cx": cx, "cy": cy, "angulo": 0.0}
    c["ensayos"].append(e)
    c["ultimo"] = e["id"]
    st.session_state[f"gsel_{campo}"] = e["nombre"]
    # el formulario queda listo para el siguiente ensayo (mismos datos, nombre y color nuevos)
    st.session_state[fk(campo, NUEVO, c["lote_nonce"], "nombre")] = _siguiente_nombre(c)
    st.session_state[fk(campo, NUEVO, c["lote_nonce"], "color")] = COLORES_SUGERIDOS[len(c["ensayos"]) % len(COLORES_SUGERIDOS)]
    _flash("ok", f"'{e['nombre']}' agregado: {d['ancho']:g} m × {d['alto']:g} m = {d['area_ha']:.3f} ha. "
                 "Arrastralo en el mapa y girálo con el panel «Girar ensayo» o con el círculo naranja.")


def cb_guardar(campo):
    c = st.session_state.campos[campo]
    sel = st.session_state[f"sel_{campo}"]
    e = next((x for x in c["ensayos"] if x["nombre"] == sel), None)
    if e is None:
        return
    datos = _leer_formulario(campo, sel)
    errores = validar(datos, {x["nombre"] for x in c["ensayos"] if x is not e})
    if errores:
        return _flash("error", " ".join(errores))
    e.update(datos)                      # la posición y la rotación no se tocan
    c["ultimo"] = e["id"]
    st.session_state[f"sel_{campo}"] = e["nombre"]
    st.session_state[f"gsel_{campo}"] = e["nombre"]
    _flash("ok", f"Cambios guardados en '{e['nombre']}'.")


def cb_eliminar(campo):
    c = st.session_state.campos[campo]
    sel = st.session_state[f"sel_{campo}"]
    c["ensayos"] = [x for x in c["ensayos"] if x["nombre"] != sel]
    c["ultimo"] = None
    st.session_state[f"sel_{campo}"] = NUEVO
    _flash("ok", f"'{sel}' eliminado.")


def cb_nuevo_campo():
    nombre = st.session_state.get("nuevo_campo_nombre", "").strip()
    if not nombre:
        return _flash("error", "Escribí un nombre para el campo.")
    if nombre in st.session_state.campos:
        return _flash("error", f"Ya existe un campo llamado '{nombre}'.")
    st.session_state.campos[nombre] = _campo_vacio()
    st.session_state.activo = nombre
    st.session_state["nuevo_campo_nombre"] = ""


def cb_eliminar_campo(campo):
    if len(st.session_state.campos) > 1:
        del st.session_state.campos[campo]
        st.session_state.activo = next(iter(st.session_state.campos))


def cb_quitar_lote(campo):
    c = st.session_state.campos[campo]
    c["lote"], c["lote_bytes"], c["lote_archivo"] = None, None, None
    c["lote_nonce"] += 1
    c["fit_n"] += 1


def cb_lote_poligono(campo):
    """El KMZ trae varios polígonos: el usuario eligió cuál es el lote. Los ensayos ya
    cargados se quedan en el mismo lugar del mundo (solo cambia el punto de origen)."""
    c = st.session_state.campos[campo]
    idx = st.session_state[f"lpol|{campo}|{c['lote_nonce']}"]
    try:
        nuevo = procesar_kmz(c["lote_bytes"], idx)
    except Exception as err:
        return _flash("error", f"No pude usar ese polígono: {err}")
    viejo = c["lote"]
    if nuevo["epsg"] == viejo["epsg"]:
        dx, dy = viejo["origen"][0] - nuevo["origen"][0], viejo["origen"][1] - nuevo["origen"][1]
        for e in c["ensayos"]:
            e["cx"] += dx
            e["cy"] += dy
    c["lote"] = nuevo
    c["fit_n"] += 1


# ===================================================================== pantalla
st.title("🌱 Planos de siembra")
st.caption(f"Versión {VERSION} · X en la parcela 1 y flechas de siembra · mapa satelital · KMZ para Google Earth · "
           "tipos de ensayo libres · giro de ensayos · hectáreas")

for _aviso in AVISOS_CONFIG:
    st.warning(_aviso)

if "_flash" in st.session_state:  # aviso flotante: no empuja el contenido ni mueve el lienzo
    tipo, texto = st.session_state.pop("_flash")
    st.toast(texto, icon="✅" if tipo == "ok" else "❌", duration="short" if tipo == "ok" else "long")

# ---- barra superior: campo + fondo del mapa
top = st.columns([2.2, 3.2, 1.9, 1.3, 1.3])
with top[0]:
    campo = st.selectbox("Campo", list(st.session_state.campos), key="activo")
with top[1]:
    fondo_nombre = st.radio("Fondo del mapa", list(FONDOS), horizontal=True, key="fondo",
                            help="El satélite y las calles se bajan de internet y se alinean solos con tu lote (hace falta el KMZ).")
with top[2]:
    st.write("")
    mostrar_refs = st.toggle("Referencias del KMZ", value=True, key="refs",
                             help="Otros polígonos, líneas y puntos que traiga tu KMZ (por ejemplo, lo que ya sembraste).")
with top[3]:
    st.write("")
    with st.popover("➕ Nuevo campo", width="stretch"):
        st.text_input("Nombre del campo", key="nuevo_campo_nombre")
        st.button("Crear campo", on_click=cb_nuevo_campo)
with top[4]:
    st.write("")
    if len(st.session_state.campos) > 1:
        with st.popover("🗑 Eliminar campo", width="stretch"):
            st.warning(f"Se borra '{campo}' con todos sus ensayos.")
            st.button("Sí, eliminar", on_click=cb_eliminar_campo, args=(campo,))

c = st.session_state.campos[campo]
poly = c["lote"]["poly"] if c["lote"] else None

# ---- 1) lote
with st.expander("1️⃣ Lote real (KMZ)", expanded=c["lote"] is None):
    archivo = st.file_uploader("Subí el KMZ de este lote", type=["kmz", "kml"], key=f"kmz_{campo}_{c['lote_nonce']}")
    st.caption("🔒 Tus archivos y ensayos viven solo en tu sesión: no se guardan en el servidor y se pierden al cerrar o "
               "recargar la página. Exportá el Excel o el KMZ antes de salir.")
    if archivo is not None and c["lote_archivo"] != (archivo.name, archivo.size):
        try:
            c["lote"] = procesar_kmz(archivo.getvalue())
            c["lote_bytes"] = archivo.getvalue()
            c["lote_archivo"] = (archivo.name, archivo.size)
            c["fit_n"] += 1
            poly = c["lote"]["poly"]
        except Exception as err:
            st.error(f"No pude leer el KMZ: {err}")
    if c["lote"]:
        lote = c["lote"]
        m = st.columns(5)
        m[0].metric("Área", f"{lote['area_ha']:.2f} ha")
        m[1].metric("Ancho", f"{lote['ancho_m']:.0f} m")
        m[2].metric("Alto", f"{lote['alto_m']:.0f} m")
        m[3].metric("Zona UTM", f"EPSG:{lote['epsg']}")
        m[4].button("Quitar KMZ", on_click=cb_quitar_lote, args=(campo,))
        pols = lote["poligonos"]
        if len(pols) > 1:
            st.selectbox("Tu KMZ tiene varios polígonos: ¿cuál es el lote?", list(range(len(pols))), index=lote["indice"],
                         format_func=lambda i: f"{pols[i]['nombre'] or 'Sin nombre'} · {pols[i]['area_ha']:.2f} ha",
                         key=f"lpol|{campo}|{c['lote_nonce']}", on_change=cb_lote_poligono, args=(campo,),
                         help="Los demás polígonos se muestran como referencias (activá «Referencias del KMZ»).")
        if lote["refs"]:
            n_p = sum(r["k"] == "poly" for r in lote["refs"])
            n_l = sum(r["k"] == "line" for r in lote["refs"])
            n_pt = sum(r["k"] == "pt" for r in lote["refs"])
            st.caption(f"Referencias en el KMZ: {n_p} polígono(s), {n_l} línea(s), {n_pt} punto(s). "
                       "Se dibujan en rosa sobre el mapa.")
        lat, lon = lote["centro_ll"]
        st.link_button("🌐 Ver el lote en Google Maps (satélite)", f"https://www.google.com/maps/@{lat:.6f},{lon:.6f},17z/data=!3m1!1e3")
    else:
        st.caption("Sin KMZ no hay mapa de fondo ni ubicación real. Subilo para ubicar los ensayos sobre el campo y exportar a Google Earth.")

# ---- 2) ensayo + 3) mapa
col_form, col_mapa = st.columns([1, 2], gap="large")

with col_form:
    st.subheader("2️⃣ Datos del ensayo")
    nombres = [e["nombre"] for e in c["ensayos"]]
    if st.session_state.get(f"sel_{campo}") not in [NUEVO] + nombres:
        st.session_state[f"sel_{campo}"] = NUEVO
    sel = st.selectbox("Ensayo", [NUEVO] + nombres, key=f"sel_{campo}",
                       help="Elegí uno existente para editarlo, o hacé clic sobre él en el mapa.",
                       on_change=cb_cambio_seleccion, args=(campo,))
    actual = next((e for e in c["ensayos"] if e["nombre"] == sel), None)
    base = actual or {
        "nombre": _siguiente_nombre(c), "tipo": "SROW", "color": COLORES_SUGERIDOS[len(c["ensayos"]) % len(COLORES_SUGERIDOS)],
        **DEFECTO,
    }
    K = lambda n: fk(campo, sel, c["lote_nonce"], n)

    def ini(clave, valor):
        """Valor inicial solo si el casillero todavía no existe (evita el choque
        con los valores que se asignan por código al agregar un ensayo)."""
        return {} if K(clave) in st.session_state else {"value": valor}

    nombre = st.text_input("Nombre del ensayo", key=K("nombre"), **ini("nombre", base["nombre"]))
    st.text_input("Tipo de ensayo (escribí el que quieras)", key=K("tipo"), placeholder="ej: SROW, Yield trial, Mi ensayo 2026…",
                  **ini("tipo", base["tipo"]))
    pill_key = f"pill|{campo}|{sel}|{c['lote_nonce']}"
    st.pills("Tipos ya usados o sugeridos (tocá uno para copiarlo)", tipos_conocidos(st.session_state.campos), key=pill_key,
             on_change=cb_tipo_pill, args=(K("tipo"), pill_key))
    n_ent = st.number_input("Cantidad de entradas", min_value=1, step=1, key=K("entradas"), **ini("entradas", int(base["entradas"])))
    n_lin = st.number_input("Líneas en cada entrada", min_value=1, step=1, key=K("lineas"), **ini("lineas", int(base["lineas"])))
    anc_lin = st.number_input("Ancho entre líneas (m)", min_value=0.01, step=0.05, format="%.2f",
                              key=K("ancho_lineas"), **ini("ancho_lineas", float(base["ancho_lineas"])))
    n_tab = st.number_input("Tablones (rangos) en cada entrada", min_value=1, step=1, key=K("tablones"), **ini("tablones", int(base["tablones"])))
    cable = st.number_input("Cable usado para sembrar cada parcela (m)", min_value=0.1, step=0.5, format="%.2f",
                            key=K("cable"), **ini("cable", float(base["cable"])))
    st.color_picker("Color", key=K("color"), **ini("color", base["color"]))

    prev = dimensiones({"entradas": n_ent, "lineas": n_lin, "ancho_lineas": anc_lin, "tablones": n_tab, "cable": cable})
    st.info(
        f"**Ancho de cada entrada:** {n_lin} × {anc_lin:g} = **{prev['ancho_entrada']:g} m**  \n"
        f"**Ancho total:** {n_ent} × {prev['ancho_entrada']:g} = **{prev['ancho']:g} m**  \n"
        f"**Alto:** {n_tab} × {cable:g} = **{prev['alto']:g} m**  \n"
        f"**Parcelas:** {n_ent} × {n_tab} = **{prev['parcelas']}** (de {prev['ancho_entrada']:g} × {cable:g} m)  \n"
        f"**Hectáreas:** {prev['ancho']:g} × {prev['alto']:g} = {prev['area_m2']:,.0f} m² = **{prev['area_ha']:.3f} ha**"
    )
    if actual is None:
        st.button("➕ Agregar al lote", type="primary", on_click=cb_agregar, args=(campo,), width="stretch")
    else:
        b1, b2 = st.columns(2)
        b1.button("💾 Guardar cambios", type="primary", on_click=cb_guardar, args=(campo,), width="stretch")
        b2.button("🗑 Eliminar", on_click=cb_eliminar, args=(campo,), width="stretch")

with col_mapa:
    st.subheader("3️⃣ Ubicá y girá los ensayos en el lote")

    # ---- panel de giro (siempre arriba del mapa)
    if c["ensayos"]:
        nombres_e = [e["nombre"] for e in c["ensayos"]]
        gkey = f"gsel_{campo}"
        if st.session_state.get(gkey) not in nombres_e:
            e0 = _ensayo_por_id(c, c["ultimo"]) or c["ensayos"][-1]
            st.session_state[gkey] = e0["nombre"]
        with st.container(border=True):
            st.markdown("**🔄 Girar ensayo**")
            g1, g2, g3 = st.columns([1.25, 2.3, 1.05])
            g1.selectbox("Ensayo a girar", nombres_e, key=gkey)
            e_sel = next(x for x in c["ensayos"] if x["nombre"] == st.session_state[gkey])
            c["ultimo"] = e_sel["id"]
            eid = e_sel["id"]
            sk, nk = f"gsl|{campo}|{eid}", f"gnum|{campo}|{eid}"
            g2.slider("Rotación (grados, antihorario)", 0.0, 359.5, step=0.5, format="%.1f°", key=sk,
                      on_change=cb_slider, args=(campo, eid),
                      **({} if sk in st.session_state else {"value": float(e_sel["angulo"])}))
            g3.number_input("o escribí los grados", min_value=0.0, max_value=359.5, step=1.0, format="%.1f", key=nk,
                            on_change=cb_numero, args=(campo, eid),
                            **({} if nk in st.session_state else {"value": float(e_sel["angulo"])}))
            bt = st.columns(5)
            bt[0].button("⟲ 15°", on_click=cb_girar, args=(campo, eid, 15), width="stretch", help="Girar 15° a la izquierda")
            bt[1].button("⟲ 90°", on_click=cb_girar, args=(campo, eid, 90), width="stretch", help="Girar 90° a la izquierda")
            bt[2].button("⟳ 90°", on_click=cb_girar, args=(campo, eid, -90), width="stretch", help="Girar 90° a la derecha")
            bt[3].button("⟳ 15°", on_click=cb_girar, args=(campo, eid, -15), width="stretch", help="Girar 15° a la derecha")
            bt[4].button("↑ 0°", on_click=cb_girar, args=(campo, eid, None), width="stretch", help="Volver a vertical")
            if c["lote"]:
                lados = lados_del_lote(c["lote"])
                if lados:
                    al1, al2 = st.columns([3.4, 1.1])
                    al1.selectbox("Alinear los tablones con un lado del lote", list(range(len(lados))), key=f"gal|{campo}",
                                  format_func=lambda i: (f"📐 Alinear con el lado {i + 1} · {lados[i]['largo']:.0f} m · "
                                                         f"rumbo {lados[i]['rumbo']:.0f}° / {(lados[i]['rumbo'] + 180) % 360:.0f}°"),
                                  label_visibility="collapsed")
                    al2.button("📐 Alinear", on_click=cb_alinear, args=(campo, eid), width="stretch",
                               help="Gira el ensayo para que sus tablones corran paralelos a ese lado del lote")
            d_sel = dimensiones(e_sel)
            rt, re_ = rumbo_texto(c["lote"], e_sel["angulo"]), rumbo_entradas_texto(c["lote"], e_sel["angulo"])
            st.caption(f"«{e_sel['nombre']}»: {d_sel['ancho']:g} × {d_sel['alto']:g} m = **{d_sel['area_ha']:.3f} ha**"
                       + (f" · tablones ↑ rumbo **{rt}** · entradas → rumbo **{re_}**" if rt else "")
                       + " · o arrastrá el círculo naranja ⟳ del mapa (Shift = de a 15°)")
    else:
        st.info("Agregá un ensayo con el formulario de la izquierda; después vas a poder arrastrarlo y girarlo acá.")

    st.caption("**X** = parcela 1 (abajo a la izquierda) · **→** entradas, de izquierda a derecha (E1 a En) · "
               "**↑** tablones, de abajo hacia arriba (T1 a Tn). Todo gira junto con el ensayo.")
    datos_lienzo = {
        "id": f"lienzo_{campo}",
        "lote": c["lote"]["coords"] if c["lote"] else None,
        "lote_ha": c["lote"]["area_ha"] if c["lote"] else None,
        "geo": c["lote"]["geo"] if c["lote"] else None,
        "base": FONDOS[fondo_nombre] if c["lote"] else None,
        "refs": c["lote"]["refs"] if c["lote"] else [],
        "mostrar_refs": mostrar_refs,
        "ensayos": [
            {"id": e["id"], "name": e["nombre"], "tipo": e["tipo"], "entradas": e["entradas"], "tablones": e["tablones"],
             "lineas": e["lineas"], "color": e["color"], "cx": e["cx"], "cy": e["cy"], "ang": e["angulo"],
             "w": dimensiones(e)["ancho"], "h": dimensiones(e)["alto"]}
            for e in c["ensayos"]
        ],
        "selected": c["ultimo"],
        "fit_token": f"{campo}:{c['fit_n']}:{'con' if c['ensayos'] else 'sin'}",
        "height": 640,
    }
    lienzo(f"lienzo_{campo}", datos_lienzo, partial(cb_evento, campo))

    pisados = superposiciones(c["ensayos"])
    if pisados:
        st.warning("⚠️ Se superponen: " + " · ".join(f"{a} con {b}" for a, b in pisados))
    afuera = [e["nombre"] for e in c["ensayos"] if fuera_del_lote(e, poly)]
    if afuera:
        st.warning("🟠 Se salen del lote: " + ", ".join(afuera))
    sobre_ref = choques_con_referencias(c["ensayos"], c["lote"])
    if sobre_ref:
        st.info("ℹ️ Pisan una referencia del KMZ (por ejemplo, una siembra previa): "
                + " · ".join(f"«{en}» con «{rn}» ({m2 / 10000:.3f} ha)" for en, rn, m2 in sobre_ref))

    # ---- cuánto del lote ocupan
    if c["ensayos"]:
        oc = ocupacion(c["ensayos"], poly)
        mm = st.columns(4)
        mm[0].metric("Hectáreas de los ensayos", f"{oc['suma_ha']:.3f} ha")
        if oc["lote_ha"] is not None:
            mm[1].metric("Ocupado del lote", f"{oc['ocupado_ha']:.3f} ha", f"{oc['pct_ocupado']:.1f}% del lote", delta_color="off")
            mm[2].metric("Libre", f"{oc['libre_ha']:.2f} ha")
            mm[3].metric("Lote", f"{oc['lote_ha']:.2f} ha")
        else:
            mm[1].caption("Subí el KMZ para ver qué parte del lote ocupan.")

# ---- hectáreas y datos por ensayo
if c["ensayos"]:
    st.subheader("Hectáreas y datos por ensayo")
    filas = []
    for e in c["ensayos"]:
        d = dimensiones(e)
        pct = pct_del_lote(e, poly)
        filas.append({
            "Ensayo": e["nombre"], "Tipo": e["tipo"], "Hectáreas (ha)": round(d["area_ha"], 3),
            "% del lote": round(pct, 2) if pct is not None else None, "Rotación (°)": e["angulo"],
            "Rumbo tablones ↑": rumbo_texto(c["lote"], e["angulo"]), "Rumbo entradas →": rumbo_entradas_texto(c["lote"], e["angulo"]),
            "Entradas": e["entradas"], "Líneas/entrada": e["lineas"], "Entre líneas (m)": e["ancho_lineas"],
            "Cable (m)": e["cable"], "Tablones": e["tablones"], "Parcelas": d["parcelas"],
            "Ancho (m)": d["ancho"], "Alto (m)": d["alto"],
            "Centro X (m)": round(e["cx"], 1), "Centro Y (m)": round(e["cy"], 1),
        })
    df = pd.DataFrame(filas)
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={"Hectáreas (ha)": st.column_config.NumberColumn(format="%.3f")})
    total_ha = sum(dimensiones(e)["area_ha"] for e in c["ensayos"])   # suma sin redondear (igual que el Excel)
    st.caption(f"**Total:** {total_ha:.3f} ha en {len(df)} ensayo(s) · {int(df['Parcelas'].sum()):,} parcelas")

# ---- exportar
st.divider()
st.subheader("📊 Exportar")
total = sum(len(cc["ensayos"]) for cc in st.session_state.campos.values())
if total == 0:
    st.info("Agregá al menos un ensayo para poder exportar.")
else:
    # copia de lo que hay ahora: los archivos se arman recién al hacer clic en descargar
    snapshot = [{"nombre": n, "ensayos": [dict(e) for e in cc["ensayos"]], "lote": cc["lote"]}
                for n, cc in st.session_state.campos.items() if cc["ensayos"]]
    stamp = f"{datetime.now():%Y%m%d_%H%M}"
    x1, x2 = st.columns(2)

    def _excel_bytes():
        buf = io.BytesIO()
        generar_workbook(snapshot).save(buf)
        return buf.getvalue()

    with x1:
        st.markdown("**Excel** — hoja Resumen (hectáreas y % del lote) y, por campo, el mapa a escala y una ficha con foto "
                    "de cada ensayo (con la X de la parcela 1 y las flechas de siembra).")
        st.download_button("⬇️ Descargar Excel de todos los campos", data=_excel_bytes, file_name=f"plano_siembra_{stamp}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary",
                           width="stretch", on_click="ignore")

    georref = [s for s in snapshot if s["lote"]]
    sin_kmz = [s["nombre"] for s in snapshot if not s["lote"]]
    with x2:
        st.markdown("**Google Earth** — un KMZ con el lote y cada ensayo ubicado y girado donde lo pusiste (al hacer clic "
                    "se ve su ficha), más la parcela 1 con su X y las flechas de entradas → y tablones ↑.")
        if georref:
            st.download_button("🌍 Descargar KMZ para Google Earth", data=lambda: generar_kmz(georref)[0],
                               file_name=f"ensayos_{stamp}.kmz", mime="application/vnd.google-earth.kmz", type="primary",
                               width="stretch", on_click="ignore")
            if sin_kmz:
                st.caption("No van al KMZ porque no tienen KMZ de lote: " + ", ".join(sin_kmz))
        else:
            st.info("Para exportar a Google Earth cargá el KMZ del lote: sin él no sabemos dónde está en el mundo.")
