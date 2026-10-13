"""
Salida a Google Earth: arma un KMZ con el lote y cada ensayo (con su ubicación y giro
reales), listo para abrir en Google Earth (PC o celular).

Cada ensayo es un polígono con su nombre y hectáreas; al hacer clic se ve la ficha con todos
los datos. Además, en la carpeta «Parcela 1 (X) y sentido de siembra»:
  - la parcela 1 con su contorno y una X,
  - una flecha → que muestra las entradas (E1 a En, de izquierda a derecha),
  - una flecha ↑ que muestra los tablones (T1 a Tn, de abajo hacia arriba).
Solo se pueden exportar los campos que tienen KMZ cargado (sin él no hay forma de saber
dónde están en el mundo).
"""
import io
import zipfile
from xml.sax.saxutils import escape

from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from geo_kmz import local_a_lonlat
from logica_planos import (
    PARCELA1_TEXTO, SENTIDO_TEXTO, dimensiones, marcas_ensayo, numeracion_texto, pct_del_lote, poligono,
    rumbo_entradas_texto, rumbo_texto,
)


def _kml_color(hexcolor, alfa=255):
    """'#RRGGBB' -> 'aabbggrr' (el orden de colores de KML)."""
    h = hexcolor.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"{alfa:02x}{b}{g}{r}"


def _coords(lote, puntos):
    out = []
    for x, y in puntos:
        lon, lat = local_a_lonlat(lote, x, y)
        out.append(f"{lon:.8f},{lat:.8f},0")
    return " ".join(out)


def _anillo(lote, poly_local):
    """Polígono local -> texto de coordenadas, cerrado y en sentido antihorario."""
    p = orient(poly_local, 1.0)
    return _coords(lote, list(p.exterior.coords))


def _descripcion(e, lote):
    d = dimensiones(e)
    ang = e.get("angulo", 0.0)
    pct = pct_del_lote(e, lote["poly"])
    filas = [
        ("Tipo de ensayo", e["tipo"]),
        ("Hectáreas", f"{d['area_ha']:.3f} ha ({d['area_m2']:,.0f} m²)"),
        ("% del lote", f"{pct:.1f}%" if pct is not None else "—"),
        ("Entradas", e["entradas"]),
        ("Líneas por entrada", e["lineas"]),
        ("Ancho entre líneas", f"{e['ancho_lineas']:g} m"),
        ("Tablones por entrada", e["tablones"]),
        ("Cable por parcela", f"{e['cable']:g} m"),
        ("Parcelas", f"{d['parcelas']:,}"),
        ("Tamaño de parcela", f"{d['ancho_entrada']:g} × {e['cable']:g} m"),
        ("Medidas del ensayo", f"{d['ancho']:g} × {d['alto']:g} m"),
        ("Parcela 1 (X)", PARCELA1_TEXTO),
        ("Sentido de siembra", SENTIDO_TEXTO),
        ("Rotación", f"{ang:g}°"),
        ("Rumbo de los tablones ↑", rumbo_texto(lote, ang) or "—"),
        ("Rumbo de las entradas →", rumbo_entradas_texto(lote, ang) or "—"),
        ("Numeración", numeracion_texto(e)),
    ]
    tabla = "".join(f"<tr><td><b>{escape(str(k))}</b></td><td>{escape(str(v))}</td></tr>" for k, v in filas)
    return f"<![CDATA[<table cellpadding='3'>{tabla}</table>]]>"


def generar_kml(campos, titulo="Planos de siembra"):
    """campos: lista de {"nombre", "ensayos", "lote"}. Devuelve (texto_kml, campos_omitidos)."""
    omitidos = [c["nombre"] for c in campos if not c.get("lote")]
    con_lote = [c for c in campos if c.get("lote") and c["ensayos"]]
    estilos = {}
    for c in con_lote:
        for e in c["ensayos"]:
            estilos[e["id"]] = e["color"]

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f"<name>{escape(titulo)}</name><open>1</open>",
           '<Style id="lote"><LineStyle><color>ffd0782a</color><width>3</width></LineStyle>'
           '<PolyStyle><fill>0</fill><outline>1</outline></PolyStyle></Style>',
           # parcela 1: contorno negro y relleno blanco translúcido
           '<Style id="parcela1"><LineStyle><color>ff111111</color><width>3</width></LineStyle>'
           '<PolyStyle><color>88ffffff</color><fill>1</fill><outline>1</outline></PolyStyle></Style>',
           '<Style id="equis"><LineStyle><color>ff111111</color><width>4</width></LineStyle></Style>',
           # flechas blancas (se ven sobre el campo, afuera del ensayo)
           '<Style id="flecha"><LineStyle><color>ffffffff</color><width>5</width></LineStyle></Style>',
           '<Style id="rotulo"><IconStyle><scale>0</scale></IconStyle>'
           '<LabelStyle><color>ffffffff</color><scale>0.85</scale></LabelStyle></Style>']
    for eid, color in estilos.items():
        out.append(f'<Style id="e_{eid}"><LineStyle><color>{_kml_color(color)}</color><width>2</width></LineStyle>'
                   f'<PolyStyle><color>{_kml_color(color, 150)}</color><fill>1</fill><outline>1</outline></PolyStyle></Style>')

    for c in con_lote:
        lote = c["lote"]
        out.append(f"<Folder><name>{escape(c['nombre'])}</name><open>1</open>")
        out.append("<Placemark><name>Lote</name><styleUrl>#lote</styleUrl><Polygon><tessellate>1</tessellate>"
                   f"<outerBoundaryIs><LinearRing><coordinates>{_anillo(lote, lote['poly'])}</coordinates>"
                   "</LinearRing></outerBoundaryIs></Polygon></Placemark>")
        out.append("<Folder><name>Ensayos</name><open>1</open>")
        for e in c["ensayos"]:
            d = dimensiones(e)
            out.append(
                f"<Placemark><name>{escape(e['nombre'])} · {d['area_ha']:.3f} ha</name>"
                f"<description>{_descripcion(e, lote)}</description><styleUrl>#e_{e['id']}</styleUrl>"
                f"<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>"
                f"{_anillo(lote, poligono(e))}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>")
        out.append("</Folder>")
        out.append("<Folder><name>Parcela 1 (X) y sentido de siembra</name>")
        for e in c["ensayos"]:
            m = marcas_ensayo(e)
            n = escape(e["nombre"])
            out.append(f"<Placemark><name>Parcela 1 · {n}</name><styleUrl>#parcela1</styleUrl><Polygon><tessellate>1</tessellate>"
                       f"<outerBoundaryIs><LinearRing><coordinates>{_anillo(lote, Polygon(m['parcela1']))}</coordinates>"
                       "</LinearRing></outerBoundaryIs></Polygon></Placemark>")
            out.append(f"<Placemark><name>X · {n}</name><styleUrl>#equis</styleUrl><MultiGeometry>"
                       + "".join(f"<LineString><tessellate>1</tessellate><coordinates>{_coords(lote, l)}</coordinates></LineString>"
                                 for l in m["equis"]) + "</MultiGeometry></Placemark>")
            out.append(f"<Placemark><name>→ entradas E1 a E{e['entradas']} · {n}</name><styleUrl>#flecha</styleUrl>"
                       f"<LineString><tessellate>1</tessellate><coordinates>{_coords(lote, m['flecha_entradas'])}</coordinates></LineString></Placemark>")
            out.append(f"<Placemark><name>↑ tablones T1 a T{e['tablones']} · {n}</name><styleUrl>#flecha</styleUrl>"
                       f"<LineString><tessellate>1</tessellate><coordinates>{_coords(lote, m['flecha_tablones'])}</coordinates></LineString></Placemark>")
            cx, cy = m["centro_parcela1"]
            out.append(f"<Placemark><name>X parcela 1 · {n}</name><styleUrl>#rotulo</styleUrl>"
                       f"<Point><coordinates>{_coords(lote, [(cx, cy)])}</coordinates></Point></Placemark>")
        out.append("</Folder></Folder>")
    out.append("</Document></kml>")
    return "\n".join(out), omitidos


def generar_kmz(campos, titulo="Planos de siembra"):
    """Devuelve (bytes_del_kmz, campos_omitidos)."""
    kml, omitidos = generar_kml(campos, titulo)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml.encode("utf-8"))
    return buf.getvalue(), omitidos
