"""
Lectura y medición del lote desde un KMZ/KML, y conversión entre el plano local
(metros) y el mapa real (latitud/longitud).

- Lee TODOS los polígonos, líneas y puntos del KMZ. El polígono más grande (o el que
  elijas) es el LOTE; lo demás se muestra como referencias.
- Convierte a metros con la zona UTM detectada automáticamente (sirve en Argentina, USA
  o donde sea) y traslada todo para que la esquina inferior izquierda del lote sea (0, 0).
- Calcula la transformación al mapa web (para dibujar el fondo satelital) y permite
  volver de metros locales a latitud/longitud (para exportar a Google Earth).
"""
import io
import math
import re
import zipfile
import xml.etree.ElementTree as ET
from functools import lru_cache

import pyproj
from shapely.affinity import translate
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import transform

NOMBRES_RUMBO = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]


def nombre_rumbo(grados):
    return NOMBRES_RUMBO[int(((grados % 360) + 11.25) // 22.5) % 16]


def _tag(el):
    return el.tag.split("}")[-1]


def _parse_coords(texto):
    pts = []
    for tok in re.split(r"\s+", (texto or "").strip()):
        partes = tok.split(",")
        if len(partes) >= 2:
            try:
                pts.append((float(partes[0]), float(partes[1])))
            except ValueError:
                pass
    return pts


def _leer_kml_bytes(data):
    if data[:2] == b"PK":  # KMZ = zip con un .kml adentro
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            nombres = [n for n in z.namelist() if n.lower().endswith(".kml")]
            if not nombres:
                raise ValueError("El KMZ no contiene ningún archivo .kml")
            nombres.sort(key=lambda n: (n != "doc.kml", n))
            return z.read(nombres[0])
    return data


def leer_geometrias(data):
    """Devuelve {"poligonos": [...], "lineas": [...], "puntos": [...]} con coordenadas lon/lat."""
    root = ET.fromstring(_leer_kml_bytes(data))
    polis, lineas, puntos = [], [], []
    for pm in root.iter():
        if _tag(pm) != "Placemark":
            continue
        nombre = ""
        for ch in pm:
            if _tag(ch) == "name":
                nombre = (ch.text or "").strip()
        for g in pm.iter():
            t = _tag(g)
            if t not in ("Polygon", "LineString", "Point"):
                continue
            coords = next((_parse_coords(c.text) for c in g.iter() if _tag(c) == "coordinates"), [])
            if t == "Polygon" and len(coords) >= 3:
                polis.append({"nombre": nombre, "pts": coords})
            elif t == "LineString" and len(coords) >= 2:
                lineas.append({"nombre": nombre, "pts": coords})
            elif t == "Point" and coords:
                puntos.append({"nombre": nombre, "pts": coords[:1]})
    if not polis:  # plan B: cualquier lista de coordenadas con 3 o más puntos
        for el in root.iter():
            if _tag(el) == "coordinates":
                pts = _parse_coords(el.text)
                if len(pts) >= 3:
                    polis.append({"nombre": "", "pts": pts})
    return {"poligonos": polis, "lineas": lineas, "puntos": puntos}


def epsg_utm(lon, lat):
    zona = min(max(int(math.floor((lon + 180) / 6) + 1), 1), 60)
    return (32600 if lat >= 0 else 32700) + zona


@lru_cache(maxsize=32)
def _transf(origen, destino):
    return pyproj.Transformer.from_crs(f"EPSG:{origen}", f"EPSG:{destino}", always_xy=True)


def _poligono_valido(pts):
    p = Polygon(pts)
    if not p.is_valid:
        p = p.buffer(0)
    if isinstance(p, MultiPolygon):
        p = max(p.geoms, key=lambda g: g.area)
    return p


def procesar_kmz(data, indice=None):
    """KMZ/KML (bytes) -> dict con el lote en metros, sus medidas, las referencias y la
    transformación al mapa web. `indice` = qué polígono del archivo es el lote."""
    g = leer_geometrias(data)
    if not g["poligonos"]:
        raise ValueError("No encontré ningún polígono en el archivo")
    polys_ll = [_poligono_valido(p["pts"]) for p in g["poligonos"]]
    if indice is None or not (0 <= indice < len(polys_ll)):
        indice = max(range(len(polys_ll)), key=lambda i: polys_ll[i].area)
    poly_ll = polys_ll[indice]
    cen = poly_ll.centroid
    epsg = epsg_utm(cen.x, cen.y)
    a_utm = _transf(4326, epsg)
    poly_utm = transform(a_utm.transform, poly_ll)
    minx, miny, maxx, maxy = poly_utm.bounds
    poly = translate(poly_utm, xoff=-minx, yoff=-miny)
    ancho, alto = maxx - minx, maxy - miny

    def local(lon, lat):
        x, y = a_utm.transform(lon, lat)
        return [round(x - minx, 2), round(y - miny, 2)]

    refs = []
    for i, p in enumerate(g["poligonos"]):
        if i != indice:
            refs.append({"k": "poly", "n": p["nombre"], "c": [local(*q) for q in p["pts"]]})
    refs += [{"k": "line", "n": p["nombre"], "c": [local(*q) for q in p["pts"]]} for p in g["lineas"]]
    refs += [{"k": "pt", "n": p["nombre"], "c": [local(*q) for q in p["pts"]]} for p in g["puntos"]]

    # local (m) -> Web Mercator (m): transformación lineal medida en el centro del lote
    a_merc = _transf(epsg, 3857)
    cx0, cy0 = ancho / 2, alto / 2
    p0 = a_merc.transform(cx0 + minx, cy0 + miny)
    px = a_merc.transform(cx0 + 1000 + minx, cy0 + miny)
    py = a_merc.transform(cx0 + minx, cy0 + 1000 + miny)
    a, c_ = (px[0] - p0[0]) / 1000, (px[1] - p0[1]) / 1000
    b, d = (py[0] - p0[0]) / 1000, (py[1] - p0[1]) / 1000
    geo = {"m": [a, b, c_, d], "t": [p0[0] - a * cx0 - b * cy0, p0[1] - c_ * cx0 - d * cy0]}

    poligonos = []
    for p, pl in zip(g["poligonos"], polys_ll):
        poligonos.append({"nombre": p["nombre"], "area_ha": transform(a_utm.transform, pl).area / 10000.0})
    return {
        "poly": poly,
        "coords": [[round(x, 2), round(y, 2)] for x, y in poly.exterior.coords],
        "area_ha": poly.area / 10000.0,
        "ancho_m": ancho,
        "alto_m": alto,
        "epsg": epsg,
        "origen": (minx, miny),
        "geo": geo,
        "refs": refs,
        "poligonos": poligonos,
        "indice": indice,
        "centro_ll": (cen.y, cen.x),
    }


def local_a_lonlat(lote, x, y):
    """Metros locales del plano -> (lon, lat)."""
    ox, oy = lote["origen"]
    return _transf(lote["epsg"], 4326).transform(x + ox, y + oy)


def rumbo_vector(lote, dx, dy):
    """Rumbo real (0° = norte, sentido horario) de un vector (dx, dy) del plano local."""
    if not lote or not lote.get("geo"):
        return None
    a, b, c, d = lote["geo"]["m"]
    return math.degrees(math.atan2(a * dx + b * dy, c * dx + d * dy)) % 360


def rumbo_real(lote, angulo):
    """Rumbo real hacia donde apuntan los TABLONES de un ensayo girado `angulo`° (flecha ↑: T1 -> Tn)."""
    t = math.radians(angulo)
    return rumbo_vector(lote, -math.sin(t), math.cos(t))


def rumbo_entradas(lote, angulo):
    """Rumbo real hacia donde apuntan las ENTRADAS de un ensayo girado `angulo`° (flecha →: E1 -> En)."""
    t = math.radians(angulo)
    return rumbo_vector(lote, math.cos(t), math.sin(t))


def lados_del_lote(lote, minimo_m=15.0, max_lados=8):
    """Los lados más largos del lote, con su ángulo en el plano y su rumbo real."""
    pts = list(lote["poly"].exterior.coords)
    lados = []
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        dx, dy = x1 - x0, y1 - y0
        largo = math.hypot(dx, dy)
        if largo >= minimo_m:
            lados.append({"largo": largo, "ang": math.degrees(math.atan2(dy, dx)) % 180,
                          "rumbo": (rumbo_vector(lote, dx, dy) or 0.0) % 180})
    lados.sort(key=lambda l: -l["largo"])
    return lados[:max_lados]


def angulo_para_alinear(ang_lado, actual):
    """Ángulo del ensayo para que sus tablones corran paralelos a un lado del lote
    (elige entre los dos sentidos el más cercano al ángulo actual)."""
    base = (ang_lado - 90) % 180
    cands = [base, base + 180]
    dist = lambda a: min(abs(a - actual) % 360, 360 - abs(a - actual) % 360)
    return min(cands, key=dist) % 360
