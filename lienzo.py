"""
Lienzo interactivo: muestra el lote (KMZ) sobre el mapa real y cada ensayo a escala (metros).

  - Fondo: imagen satelital (o calles) que se baja de internet y queda alineada con el lote.
  - Referencias del KMZ: otros polígonos, líneas y puntos del archivo (p. ej. siembras previas).
  - Arrastrar un ensayo              -> lo mueve.
  - Círculo naranja ⟳ (seleccionado) -> arrastrarlo lo GIRA (Shift = de a 15°).
  - Clic en un ensayo                -> lo selecciona.
  - Arrastrar el fondo               -> mueve el mapa.   Rueda -> zoom.   Doble clic -> encuadrar.
Cada ensayo muestra su sentido de siembra: una X en la parcela 1 (abajo a la izquierda), una flecha →
para las entradas (de izquierda a derecha) y una flecha ↑ para los tablones (de abajo hacia arriba).
La brújula muestra el norte real.
"""
import streamlit as st

_HTML = """
<div class="wrap">
  <canvas class="cv"></canvas>
  <div class="info">Pasá el mouse sobre un ensayo</div>
  <button class="fit" type="button">⤢ Encuadrar</button>
</div>
"""

_CSS = """
.wrap { position: relative; width: 100%; user-select: none; }
.cv { width: 100%; display: block; border: 1px solid #cfd8dc; border-radius: 8px;
      background: #eceff1; touch-action: none; cursor: default; }
.info { position: absolute; left: 8px; top: 8px; background: rgba(255,255,255,.92);
        padding: 4px 8px; border-radius: 6px; font: 12px/1.35 Arial, sans-serif;
        color: #222; pointer-events: none; max-width: 70%; }
.fit { position: absolute; right: 8px; top: 8px; padding: 4px 10px; border-radius: 6px;
       border: 1px solid #90a4ae; background: #fff; cursor: pointer; font: 12px Arial; }
.fit:hover { background: #eceff1; }
"""

_JS = r"""
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const root = parentElement;
  const wrap = root.querySelector('.wrap');
  const cv = root.querySelector('.cv');
  const info = root.querySelector('.info');
  const fitBtn = root.querySelector('.fit');
  const ctx = cv.getContext('2d');

  // Estado que sobrevive a los re-renders de Streamlit (zoom/pan y mosaicos del mapa no se pierden)
  const G = (window.__lienzoEstado = window.__lienzoEstado || {});
  const S = (G[data.id] = G[data.id] || { vx: 0, vy: 0, scale: 1, fit: null });
  const TC = (window.__lienzoTiles = window.__lienzoTiles || {});

  const H = data.height || 640;
  let W = Math.max(300, wrap.clientWidth || 900);
  const dpr = window.devicePixelRatio || 1;
  function resize() {
    W = Math.max(300, wrap.clientWidth || 900);
    cv.width = W * dpr; cv.height = H * dpr;
    cv.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();

  const lote = data.lote || null;                        // [[x,y],...]
  const loteHa = data.lote_ha || null;
  const geo = data.geo || null;                          // local (m) -> Web Mercator (m)
  const base = (geo && data.base) ? data.base : null;    // {url, maxz, attr}
  const refs = data.mostrar_refs ? (data.refs || []) : [];
  const ens = (data.ensayos || []).map(e => ({ ...e })); // copia local (se mueve/gira al arrastrar)
  let selected = data.selected || null;
  let drag = null, rot = null, pan = null, hover = null, cursor = null;

  const rad = d => d * Math.PI / 180;
  const sx = x => (x - S.vx) * S.scale;
  const sy = y => H - (y - S.vy) * S.scale;
  const wx = px => px / S.scale + S.vx;
  const wy = py => S.vy + (H - py) / S.scale;

  // ---- mapa real: local <-> Web Mercator <-> lat/lon ----
  const RM = 6378137, WORLD = 2 * Math.PI * RM;
  const toMerc = (x, y) => [geo.m[0] * x + geo.m[1] * y + geo.t[0], geo.m[2] * x + geo.m[3] * y + geo.t[1]];
  const fromMerc = (X, Y) => {
    const [a, b, c, d] = geo.m, dx = X - geo.t[0], dy = Y - geo.t[1], det = a * d - b * c;
    return [(d * dx - b * dy) / det, (-c * dx + a * dy) / det];
  };
  const lonlat = (x, y) => {
    const [X, Y] = toMerc(x, y);
    return [X / RM * 180 / Math.PI, (2 * Math.atan(Math.exp(Y / RM)) - Math.PI / 2) * 180 / Math.PI];
  };
  const NOM = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSO', 'SO', 'OSO', 'O', 'ONO', 'NO', 'NNO'];
  const nomRumbo = g => NOM[Math.floor((((g % 360) + 360) % 360 + 11.25) / 22.5) % 16];
  function rumboVec(ux, uy) {            // rumbo real (0° = norte, horario) de un vector del plano local
    if (!geo) return null;
    const X = geo.m[0] * ux + geo.m[1] * uy, Y = geo.m[2] * ux + geo.m[3] * uy;
    return ((Math.atan2(X, Y) * 180 / Math.PI) + 360) % 360;
  }
  const rumboTab = e => rumboVec(-Math.sin(rad(e.ang)), Math.cos(rad(e.ang)));   // tablones ↑
  const rumboEnt = e => rumboVec(Math.cos(rad(e.ang)), Math.sin(rad(e.ang)));    // entradas →

  // ---- geometría de un ensayo (centro cx,cy; w x h metros; ang grados antihorario) ----
  function esquinas(e) {
    const t = rad(e.ang), c = Math.cos(t), s = Math.sin(t);
    return [[-e.w / 2, -e.h / 2], [e.w / 2, -e.h / 2], [e.w / 2, e.h / 2], [-e.w / 2, e.h / 2]]
      .map(([lx, ly]) => [e.cx + lx * c - ly * s, e.cy + lx * s + ly * c]);
  }
  function bounds() {
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    const add = (x, y) => { minx = Math.min(minx, x); miny = Math.min(miny, y); maxx = Math.max(maxx, x); maxy = Math.max(maxy, y); };
    if (lote) lote.forEach(p => add(p[0], p[1]));
    ens.forEach(e => esquinas(e).forEach(p => add(p[0], p[1])));
    if (!isFinite(minx)) { minx = 0; miny = 0; maxx = 100; maxy = 100; }
    return { minx, miny, maxx, maxy };
  }
  function fit() {
    const b = bounds(), pad = 40;
    const bw = Math.max(1, b.maxx - b.minx), bh = Math.max(1, b.maxy - b.miny);
    S.scale = Math.min((W - 2 * pad) / bw, (H - 2 * pad) / bh);
    S.vx = b.minx - (W / S.scale - bw) / 2;
    S.vy = b.miny - (H / S.scale - bh) / 2;
  }
  if (S.fit !== data.fit_token) { fit(); S.fit = data.fit_token; }

  // ---- en pantalla: medias dimensiones en px (con mínimo visible) y rotación ----
  const MIN_PX = 6, HIT_PAD = 8, HANDLE_D = 40, HANDLE_R = 12, OFF_FLECHA = 9, MIN_FLECHA = 30, MIN_X = 10;
  const hwpx = e => Math.max(e.w * S.scale / 2, MIN_PX / 2);
  const hhpx = e => Math.max(e.h * S.scale / 2, MIN_PX / 2);
  function aLocal(px, py, e) {
    const t = rad(e.ang), c = Math.cos(t), s = Math.sin(t);
    const dx = px - sx(e.cx), dy = py - sy(e.cy);
    return { lx: dx * c - dy * s, ly: -dx * s - dy * c };
  }
  function dePantalla(e, lx, ly) {       // lx a la derecha del ensayo, ly hacia ARRIBA del ensayo (px desde el centro)
    const t = rad(e.ang), c = Math.cos(t), s = Math.sin(t);
    return [sx(e.cx) + lx * c - ly * s, sy(e.cy) - lx * s - ly * c];
  }
  function esquinasPx(e) {
    const hw = hwpx(e), hh = hhpx(e);
    return [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]].map(([lx, ly]) => dePantalla(e, lx, ly));
  }
  function handlePos(e) { return dePantalla(e, 0, hhpx(e) + HANDLE_D); }
  function hitHandle(px, py, e) { const h = handlePos(e); return Math.hypot(px - h[0], py - h[1]) <= HANDLE_R + 6; }
  function hit(px, py) {
    for (let i = ens.length - 1; i >= 0; i--) {
      const e = ens[i], l = aLocal(px, py, e);
      if (Math.abs(l.lx) <= hwpx(e) + HIT_PAD && Math.abs(l.ly) <= hhpx(e) + HIT_PAD) return e;
    }
    return null;
  }

  // ---- chequeos en vivo (la validación definitiva la hace Python) ----
  function inPoly(x, y, poly) {
    let ins = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) ins = !ins;
    }
    return ins;
  }
  function solapan(A, B) {                // SAT para rectángulos rotados; se ignoran 2 cm de roce
    for (const P of [A, B]) for (let i = 0; i < 4; i++) {
      const p1 = P[i], p2 = P[(i + 1) % 4];
      let nx = -(p2[1] - p1[1]), ny = p2[0] - p1[0]; const L = Math.hypot(nx, ny) || 1; nx /= L; ny /= L;
      let a0 = Infinity, a1 = -Infinity, b0 = Infinity, b1 = -Infinity;
      A.forEach(q => { const d = q[0] * nx + q[1] * ny; a0 = Math.min(a0, d); a1 = Math.max(a1, d); });
      B.forEach(q => { const d = q[0] * nx + q[1] * ny; b0 = Math.min(b0, d); b1 = Math.max(b1, d); });
      if (a1 <= b0 + 0.02 || b1 <= a0 + 0.02) return false;
    }
    return true;
  }
  function estado(e) {
    const A = esquinas(e);
    if (ens.some(o => o !== e && solapan(A, esquinas(o)))) return 'overlap';
    if (lote && !(A.concat([[e.cx, e.cy]])).every(p => inPoly(p[0], p[1], lote))) return 'out';
    return '';
  }

  const fmt = n => (Math.round(n * 100) / 100).toString();
  const haDe = e => e.w * e.h / 10000;
  function describe(e) {
    const st = estado(e), area = haDe(e), rt = rumboTab(e), re = rumboEnt(e);
    return `<b>${e.name}</b> · ${e.tipo}<br>${e.entradas} entradas × ${e.tablones} tablones · ${e.lineas} líneas/entrada<br>`
      + `${fmt(e.w)} m × ${fmt(e.h)} m = <b>${area.toFixed(3)} ha</b>` + (loteHa ? ` (${(area / loteHa * 100).toFixed(1)}% del lote)` : '') + `<br>`
      + `rotación ${fmt(e.ang)}° · centro X=${fmt(e.cx)} Y=${fmt(e.cy)}<br>`
      + `<b>X</b> parcela 1 (abajo a la izquierda) · <b>→</b> entradas · <b>↑</b> tablones`
      + (rt !== null ? `<br>↑ rumbo <b>${rt.toFixed(0)}° ${nomRumbo(rt)}</b> · → rumbo <b>${re.toFixed(0)}° ${nomRumbo(re)}</b>` : '')
      + (st === 'overlap' ? '<br><b style="color:#d32f2f">⚠ Se superpone con otro ensayo</b>' : '')
      + (st === 'out' ? '<br><b style="color:#ef6c00">⚠ Se sale del lote</b>' : '');
  }

  // ---- mosaicos del mapa de fondo ----
  const pedir = url => {
    let t = TC[url];
    if (t) return t;
    const keys = Object.keys(TC);
    if (keys.length > 700) keys.slice(0, 350).forEach(k => delete TC[k]);
    const img = new Image();
    t = TC[url] = { img, ok: false, err: false };
    img.onload = () => { t.ok = true; G.redibujar && G.redibujar(); };
    img.onerror = () => { t.err = true; G.redibujar && G.redibujar(); };
    img.src = url;
    return t;
  };
  function rango(z) {
    const n = Math.pow(2, z), ts = WORLD / n;
    const cs = [[0, 0], [W, 0], [0, H], [W, H]].map(([px, py]) => toMerc(wx(px), wy(py)));
    const X0 = Math.min(...cs.map(c => c[0])), X1 = Math.max(...cs.map(c => c[0]));
    const Y0 = Math.min(...cs.map(c => c[1])), Y1 = Math.max(...cs.map(c => c[1]));
    const tx0 = Math.max(0, Math.floor((X0 + WORLD / 2) / ts)), tx1 = Math.min(n - 1, Math.floor((X1 + WORLD / 2) / ts));
    const ty0 = Math.max(0, Math.floor((WORLD / 2 - Y1) / ts)), ty1 = Math.min(n - 1, Math.floor((WORLD / 2 - Y0) / ts));
    return { n, ts, tx0, tx1, ty0, ty1, cuenta: Math.max(0, tx1 - tx0 + 1) * Math.max(0, ty1 - ty0 + 1) };
  }
  function dibujarTile(img, tx, ty, ts) {
    const X0 = -WORLD / 2 + tx * ts, X1 = X0 + ts, Y0 = WORLD / 2 - ty * ts, Y1 = Y0 - ts;
    const P = (X, Y) => { const [x, y] = fromMerc(X, Y); return [sx(x), sy(y)]; };
    const TL = P(X0, Y0), TR = P(X1, Y0), BL = P(X0, Y1);
    const iw = img.naturalWidth || 256, ih = img.naturalHeight || 256;
    ctx.setTransform(dpr * (TR[0] - TL[0]) / iw, dpr * (TR[1] - TL[1]) / iw,
                     dpr * (BL[0] - TL[0]) / ih, dpr * (BL[1] - TL[1]) / ih, dpr * TL[0], dpr * TL[1]);
    ctx.drawImage(img, -0.4, -0.4, iw + 0.8, ih + 0.8);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  let tilesOk = 0, tilesErr = 0;
  function dibujarMapa() {
    tilesOk = 0; tilesErr = 0;
    const k = Math.hypot(geo.m[0], geo.m[2]);                    // m de Mercator por metro real
    let z = Math.round(Math.log2(WORLD * S.scale / (256 * k)) + 0.25);
    z = Math.max(1, Math.min(base.maxz || 18, z));
    while (z > 1 && rango(z).cuenta > 70) z--;
    for (const L of [z - 2, z - 1, z, z + 1]) {                 // los niveles ya cargados rellenan mientras llegan los nuevos
      if (L < 1 || L > (base.maxz || 18)) continue;
      const r = rango(L);
      if (r.cuenta > (L === z ? 70 : 160)) continue;
      for (let tx = r.tx0; tx <= r.tx1; tx++) for (let ty = r.ty0; ty <= r.ty1; ty++) {
        const url = base.url.replace('{z}', L).replace('{x}', tx).replace('{y}', ty);
        const t = L === z ? pedir(url) : TC[url];
        if (!t) continue;
        if (t.ok) { dibujarTile(t.img, tx, ty, r.ts); if (L === z) tilesOk++; }
        else if (t.err && L === z) tilesErr++;
      }
    }
  }

  // ---- dibujo ----
  function niceLen(maxMeters) {
    let best = 1;
    for (let p = -1; p < 6; p++) for (const b of [1, 2, 5]) { const v = b * Math.pow(10, p); if (v <= maxMeters) best = v; }
    return best;
  }
  function texto(t, x, y, colr, tam, alin) {                       // texto con halo blanco, legible sobre el satélite
    ctx.font = `bold ${tam}px Arial`; ctx.textAlign = alin || 'left'; ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round'; ctx.lineWidth = 3.5; ctx.strokeStyle = 'rgba(255,255,255,.92)'; ctx.strokeText(t, x, y);
    ctx.fillStyle = colr; ctx.fillText(t, x, y);
  }
  // X y flechas: se dibujan con el ctx ya trasladado y girado al centro del ensayo (eje y hacia abajo)
  function equis(x, y, w, h) {
    [['rgba(255,255,255,.95)', 4.5], ['#111', 2.2]].forEach(([col, lw]) => {
      ctx.strokeStyle = col; ctx.lineWidth = lw; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + w, y + h); ctx.moveTo(x + w, y); ctx.lineTo(x, y + h); ctx.stroke();
    });
  }
  function flecha(x0, y0, x1, y1) {
    const L = Math.hypot(x1 - x0, y1 - y0) || 1, ux = (x1 - x0) / L, uy = (y1 - y0) / L, nx = -uy, ny = ux;
    const hs = Math.min(10, Math.max(6, L * 0.2)), bx = x1 - ux * hs, by = y1 - uy * hs;
    [['rgba(255,255,255,.95)', 5, 2], ['#111', 2, 0]].forEach(([col, lw, extra]) => {
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = lw; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
      ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(bx, by); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x1 + ux * extra, y1 + uy * extra);
      ctx.lineTo(bx + nx * hs * .55, by + ny * hs * .55); ctx.lineTo(bx - nx * hs * .55, by - ny * hs * .55);
      ctx.closePath(); ctx.fill(); ctx.stroke();
    });
  }
  function dibujarRefs() {
    const col = '#E91E63';
    refs.forEach(r => {
      if (r.k === 'pt') {
        const [x, y] = r.c[0], X = sx(x), Y = sy(y);
        ctx.beginPath(); ctx.arc(X, Y, 5, 0, 2 * Math.PI); ctx.fillStyle = col; ctx.fill();
        ctx.lineWidth = 2; ctx.strokeStyle = '#fff'; ctx.stroke();
        if (r.n) texto(r.n, X + 9, Y, '#AD1457', 11);
        return;
      }
      ctx.beginPath();
      r.c.forEach((p, i) => { const X = sx(p[0]), Y = sy(p[1]); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
      if (r.k === 'poly') { ctx.closePath(); ctx.fillStyle = 'rgba(233,30,99,0.10)'; ctx.fill(); }
      ctx.lineWidth = 2; ctx.strokeStyle = col; ctx.setLineDash(r.k === 'line' ? [7, 4] : []); ctx.stroke(); ctx.setLineDash([]);
      if (r.n) {
        const m = r.c.reduce((a, p) => [a[0] + p[0] / r.c.length, a[1] + p[1] / r.c.length], [0, 0]);
        texto(r.n, sx(m[0]), sy(m[1]), '#AD1457', 11, 'center');
      }
    });
  }
  function brujula() {
    let nx = 0, ny = 1;                                            // norte real expresado en el plano local
    if (geo) { const det = geo.m[0] * geo.m[3] - geo.m[1] * geo.m[2]; nx = -geo.m[1] / det; ny = geo.m[0] / det; }
    const L = Math.hypot(nx, ny) || 1, vx = nx / L, vy = -ny / L;   // vector en pantalla (y hacia abajo)
    const cx = W - 58, cy = 86, r = 18;
    ctx.beginPath(); ctx.arc(cx, cy, r + 9, 0, 2 * Math.PI); ctx.fillStyle = 'rgba(255,255,255,.85)'; ctx.fill();
    ctx.strokeStyle = '#90a4ae'; ctx.lineWidth = 1; ctx.stroke();
    ctx.beginPath(); ctx.moveTo(cx + vx * r, cy + vy * r);
    ctx.lineTo(cx - vy * 6 - vx * 4, cy + vx * 6 - vy * 4); ctx.lineTo(cx + vy * 6 - vx * 4, cy - vx * 6 - vy * 4); ctx.closePath();
    ctx.fillStyle = '#d32f2f'; ctx.fill();
    ctx.beginPath(); ctx.moveTo(cx - vx * r * .8, cy - vy * r * .8);
    ctx.lineTo(cx - vy * 5, cy + vx * 5); ctx.lineTo(cx + vy * 5, cy - vx * 5); ctx.closePath(); ctx.fillStyle = '#607d8b'; ctx.fill();
    const L2 = r + 17;
    [['N', vx, vy, '#d32f2f'], ['E', -vy, vx, '#455a64'], ['S', -vx, -vy, '#455a64'], ['O', vy, -vx, '#455a64']].forEach(([t, dx, dy, c]) => {
      ctx.font = 'bold 11px Arial'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = c; ctx.fillText(t, cx + dx * L2, cy + dy * L2);
    });
  }
  function draw() {
    ctx.clearRect(0, 0, W, H);
    if (base) dibujarMapa();
    const conFondo = base && tilesOk > 0;
    if (lote && lote.length) {
      ctx.beginPath();
      lote.forEach((p, i) => { const X = sx(p[0]), Y = sy(p[1]); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
      ctx.closePath();
      ctx.fillStyle = conFondo ? 'rgba(255,235,59,0.08)' : 'rgba(21,101,192,0.10)'; ctx.fill();
      ctx.strokeStyle = conFondo ? '#FFEB3B' : '#1565C0'; ctx.lineWidth = conFondo ? 3 : 2; ctx.stroke();
    }
    dibujarRefs();
    ens.forEach(e => {
      const st = estado(e), sel = e.id === selected;
      const hw = hwpx(e), hh = hhpx(e);
      const borde = st === 'overlap' ? '#d32f2f' : st === 'out' ? '#ef6c00' : sel ? '#FFC107' : (conFondo ? '#ffffff' : '#263238');
      ctx.save();
      ctx.translate(sx(e.cx), sy(e.cy));
      ctx.rotate(-rad(e.ang));
      ctx.globalAlpha = st ? 0.6 : 0.82;
      ctx.fillStyle = e.color; ctx.fillRect(-hw, -hh, 2 * hw, 2 * hh);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = 'rgba(255,255,255,.75)'; ctx.lineWidth = 1;
      if (2 * hw / e.entradas >= 4) for (let k = 1; k < e.entradas; k++) { const X = -hw + 2 * hw * k / e.entradas; ctx.beginPath(); ctx.moveTo(X, -hh); ctx.lineTo(X, hh); ctx.stroke(); }
      if (2 * hh / e.tablones >= 5) for (let k = 1; k < e.tablones; k++) { const Y = -hh + 2 * hh * k / e.tablones; ctx.beginPath(); ctx.moveTo(-hw, Y); ctx.lineTo(hw, Y); ctx.stroke(); }
      ctx.lineWidth = sel ? 3 : 1.8; ctx.strokeStyle = borde;
      if (st === 'out') ctx.setLineDash([6, 4]);
      ctx.strokeRect(-hw, -hh, 2 * hw, 2 * hh); ctx.setLineDash([]);
      // sentido de siembra: X en la parcela 1 (abajo a la izquierda), → entradas, ↑ tablones
      const cw = Math.max(2 * hw / e.entradas, MIN_X), ch = Math.max(2 * hh / e.tablones, MIN_X);
      equis(-hw, hh - ch, cw, ch);
      flecha(-hw, hh + OFF_FLECHA, -hw + Math.max(2 * hw, MIN_FLECHA), hh + OFF_FLECHA);
      flecha(-hw - OFF_FLECHA, hh, -hw - OFF_FLECHA, hh - Math.max(2 * hh, MIN_FLECHA));
      if (sel) {   // manija de rotación: círculo naranja con flecha circular
        ctx.strokeStyle = '#ef6c00'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(0, -hh - 2); ctx.lineTo(0, -hh - HANDLE_D + HANDLE_R); ctx.stroke();
        ctx.beginPath(); ctx.arc(0, -hh - HANDLE_D, HANDLE_R, 0, 2 * Math.PI);
        ctx.fillStyle = '#ff9800'; ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2.5; ctx.stroke();
        ctx.beginPath(); ctx.arc(0, -hh - HANDLE_D, 5.5, -2.5, 1.2); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
        ctx.beginPath(); const ax = Math.cos(1.2) * 5.5, ay = -hh - HANDLE_D + Math.sin(1.2) * 5.5;
        ctx.moveTo(ax - 4, ay - 3); ctx.lineTo(ax + 1, ay + 4); ctx.lineTo(ax + 5, ay - 2); ctx.closePath(); ctx.fillStyle = '#fff'; ctx.fill();
      }
      ctx.restore();
    });
    // etiquetas (sin rotar, legibles): nombre + hectáreas + ángulo
    ens.forEach(e => {
      const hw0 = hwpx(e), hh0 = hhpx(e), Lh0 = Math.max(2 * hw0, MIN_FLECHA), Lv0 = Math.max(2 * hh0, MIN_FLECHA);
      const cp = esquinasPx(e).concat([dePantalla(e, -hw0, -(hh0 + OFF_FLECHA)), dePantalla(e, -hw0 + Lh0, -(hh0 + OFF_FLECHA)),
                                       dePantalla(e, -(hw0 + OFF_FLECHA), -hh0), dePantalla(e, -(hw0 + OFF_FLECHA), -hh0 + Lv0)]);
      const maxx = Math.max(...cp.map(p => p[0])) + 6;
      const cx = sx(e.cx), cy = sy(e.cy);
      const l1 = e.name, l2 = haDe(e).toFixed(3) + ' ha' + (e.ang ? ' · ' + fmt(e.ang) + '°' : '');
      ctx.font = 'bold 12px Arial'; const w1 = ctx.measureText(l1).width;
      ctx.font = '12px Arial'; const w2 = ctx.measureText(l2).width;
      const tw = Math.max(w1, w2);
      if (2 * hwpx(e) >= tw + 12 && 2 * hhpx(e) >= 38) {          // entra adentro del cuadro
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fff';
        ctx.font = 'bold 12px Arial'; ctx.fillText(l1, cx, cy - 8); ctx.font = '12px Arial'; ctx.fillText(l2, cx, cy + 8);
      } else {                                                      // al costado, con fondo
        const x = maxx + 7, y = cy - 17;
        ctx.fillStyle = 'rgba(255,255,255,.9)'; ctx.fillRect(x - 4, y, tw + 10, 34);
        ctx.strokeStyle = 'rgba(176,190,197,.9)'; ctx.lineWidth = 1; ctx.strokeRect(x - 4, y, tw + 10, 34);
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#263238';
        ctx.font = 'bold 12px Arial'; ctx.fillText(l1, x, y + 10); ctx.font = '12px Arial'; ctx.fillText(l2, x, y + 25);
      }
      if (e.id === selected) {                                      // rótulos de las flechas del ensayo seleccionado
        const hw = hwpx(e), hh = hhpx(e), Lh = Math.max(2 * hw, MIN_FLECHA), Lv = Math.max(2 * hh, MIN_FLECHA);
        // rótulos en los extremos de cada flecha, separados lo justo para no taparla sea cual sea el giro
        const rotulo = (px0, py0, dlx, dly, t) => {
          const p0 = dePantalla(e, px0, py0), p1 = dePantalla(e, px0 + dlx, py0 + dly);
          const ux = p1[0] - p0[0], uy = p1[1] - p0[1];
          ctx.font = 'bold 11px Arial';
          const d = 9 + 0.5 * (Math.abs(ux) * ctx.measureText(t).width + Math.abs(uy) * 12);
          texto(t, p0[0] + ux * d, p0[1] + uy * d, '#111', 11, 'center');
        };
        rotulo(-hw, -(hh + OFF_FLECHA), 0, -1, 'E1');                                   // debajo del inicio de la flecha →
        if (e.entradas > 1) rotulo(-hw + Lh, -(hh + OFF_FLECHA), 1, 0, `E${e.entradas}`);  // más allá de su punta
        rotulo(-(hw + OFF_FLECHA), -hh, -1, 0, 'T1');                                   // a la izquierda del inicio de la flecha ↑
        if (e.tablones > 1) rotulo(-(hw + OFF_FLECHA), -hh + Lv, 0, 1, `T${e.tablones}`);  // más allá de su punta
      }
    });
    // ángulo y rumbo en vivo mientras se gira
    if (rot) {
      const h = handlePos(rot.e), r = rumboTab(rot.e);
      const txt = fmt(rot.e.ang) + '°' + (r !== null ? ` · ↑ rumbo ${r.toFixed(0)}° ${nomRumbo(r)}` : '');
      ctx.font = 'bold 14px Arial'; const w = ctx.measureText(txt).width;
      ctx.fillStyle = 'rgba(255,255,255,.95)'; ctx.fillRect(h[0] + 16, h[1] - 12, w + 12, 24);
      ctx.strokeStyle = '#ef6c00'; ctx.lineWidth = 1.5; ctx.strokeRect(h[0] + 16, h[1] - 12, w + 12, 24);
      ctx.fillStyle = '#e65100'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle'; ctx.fillText(txt, h[0] + 22, h[1]);
    }
    brujula();
    // barra de escala, coordenadas del cursor y atribución del mapa
    const m = niceLen(110 / S.scale), px = m * S.scale, bx = 14, by = H - 16;
    ctx.fillStyle = 'rgba(255,255,255,.8)'; ctx.fillRect(bx - 6, by - 26, px + 40, 34);
    ctx.strokeStyle = '#37474f'; ctx.lineWidth = 3; ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx + px, by); ctx.stroke();
    ctx.fillStyle = '#37474f'; ctx.font = '12px Arial'; ctx.textAlign = 'left'; ctx.textBaseline = 'bottom';
    ctx.fillText(m + ' m', bx, by - 5);
    let lineaCursor = '';
    if (cursor) {
      lineaCursor = `X ${fmt(cursor.x)}  Y ${fmt(cursor.y)}`;
      if (geo) { const [lo, la] = lonlat(cursor.x, cursor.y); lineaCursor = `lat ${la.toFixed(6)}  lon ${lo.toFixed(6)}   ·   ` + lineaCursor; }
    }
    const atr = base ? (tilesErr > 0 && tilesOk === 0 ? '⚠ No se pudo cargar el mapa de fondo (¿sin internet?)' : (base.attr || '')) : '';
    ctx.font = '11px Arial'; ctx.textAlign = 'right'; ctx.textBaseline = 'bottom';
    const lineas = [lineaCursor, atr].filter(Boolean);
    lineas.forEach((t, i) => {
      const y = H - 5 - (lineas.length - 1 - i) * 16, w = ctx.measureText(t).width;
      ctx.fillStyle = 'rgba(255,255,255,.82)'; ctx.fillRect(W - w - 14, y - 14, w + 10, 16);
      ctx.fillStyle = (i === lineas.length - 1 && tilesErr > 0 && tilesOk === 0) ? '#c62828' : '#37474f'; ctx.fillText(t, W - 9, y);
    });
  }

  function setInfo() {
    const e = (drag && drag.e) || (rot && rot.e) || hover;
    info.innerHTML = e ? describe(e)
      : 'Arrastrá un ensayo para moverlo · círculo naranja ⟳ = girar · rueda = zoom · arrastrá el fondo = mover el mapa';
  }

  // ---- eventos (se reasignan en cada render: siempre ven los datos más nuevos) ----
  function pos(ev) { const r = cv.getBoundingClientRect(); return { px: ev.clientX - r.left, py: ev.clientY - r.top }; }
  const selEns = () => ens.find(e => e.id === selected) || null;

  cv.onpointerdown = ev => {
    const { px, py } = pos(ev);
    cv.setPointerCapture(ev.pointerId);
    const se = selEns();
    if (se && hitHandle(px, py, se)) {
      rot = { e: se, moved: false }; cv.style.cursor = 'grabbing';
    } else {
      const e = hit(px, py);
      if (e) {
        selected = e.id;
        drag = { e, sx: px, sy: py, ox: e.cx, oy: e.cy, moved: false };
        cv.style.cursor = 'grabbing';
      } else {
        pan = { sx: px, sy: py, vx: S.vx, vy: S.vy };
        cv.style.cursor = 'move';
      }
    }
    draw(); setInfo();
  };
  cv.onpointermove = ev => {
    const { px, py } = pos(ev);
    cursor = { x: wx(px), y: wy(py) };
    if (rot) {
      const e = rot.e;
      const raw = Math.atan2(wy(py) - e.cy, wx(px) - e.cx) * 180 / Math.PI - 90;
      let a = ((raw % 360) + 360) % 360;
      a = ev.shiftKey ? Math.round(a / 15) * 15 : Math.round(a * 2) / 2;
      e.ang = a % 360; rot.moved = true;
    } else if (drag) {
      const dxp = px - drag.sx, dyp = py - drag.sy;
      if (Math.hypot(dxp, dyp) > 3) drag.moved = true;
      if (drag.moved) {
        drag.e.cx = Math.round((drag.ox + dxp / S.scale) * 10) / 10;
        drag.e.cy = Math.round((drag.oy - dyp / S.scale) * 10) / 10;
      }
    } else if (pan) {
      S.vx = pan.vx - (px - pan.sx) / S.scale;
      S.vy = pan.vy + (py - pan.sy) / S.scale;
    } else {
      const se = selEns();
      if (se && hitHandle(px, py, se)) { hover = se; cv.style.cursor = 'grab'; }
      else { hover = hit(px, py); cv.style.cursor = hover ? 'grab' : 'default'; }
    }
    draw(); setInfo();
  };
  cv.onpointerup = ev => {
    if (rot) {
      if (rot.moved) setTriggerValue('evento', { tipo: 'rotar', id: rot.e.id, angulo: rot.e.ang });
    } else if (drag) {
      const e = drag.e;
      if (drag.moved) setTriggerValue('evento', { tipo: 'mover', id: e.id, x: e.cx, y: e.cy });
      else setTriggerValue('evento', { tipo: 'seleccionar', id: e.id });
    }
    drag = null; rot = null; pan = null; cv.style.cursor = 'default';
    try { cv.releasePointerCapture(ev.pointerId); } catch (_) {}
    draw(); setInfo();
  };
  cv.onpointerleave = () => { if (!drag && !rot && !pan) { hover = null; cursor = null; draw(); setInfo(); } };
  cv.onwheel = ev => {
    ev.preventDefault();
    const { px, py } = pos(ev);
    const k = ev.deltaY < 0 ? 1.18 : 1 / 1.18;
    const x = wx(px), y = wy(py);
    S.scale = Math.min(500, Math.max(0.02, S.scale * k));
    S.vx = x - px / S.scale;
    S.vy = y - (H - py) / S.scale;
    draw();
  };
  cv.ondblclick = () => { fit(); draw(); };
  fitBtn.onclick = () => { fit(); draw(); };

  if (G.onResize) window.removeEventListener('resize', G.onResize);
  G.onResize = () => { resize(); draw(); };
  window.addEventListener('resize', G.onResize);
  G.dibujo = draw;
  G.redibujar = () => { if (G.pend) return; G.pend = true; requestAnimationFrame(() => { G.pend = false; G.dibujo && G.dibujo(); }); };

  draw(); setInfo();
  return () => { cv.onpointerdown = cv.onpointermove = cv.onpointerup = cv.onwheel = null; if (G.dibujo === draw) G.dibujo = null; };
}
"""

_componente = st.components.v2.component("lienzo_ensayos", html=_HTML, css=_CSS, js=_JS)


def lienzo(key, data, on_evento):
    """`data`: id, lote, lote_ha, geo ({m, t}), base ({url, maxz, attr} | None), refs, mostrar_refs,
    ensayos (id, name, tipo, entradas, tablones, lineas, color, cx, cy, w, h, ang), selected,
    fit_token, height. `on_evento` se llama cuando el usuario suelta, gira o selecciona un
    ensayo; el evento está en st.session_state[key].evento."""
    return _componente(key=key, data=data, on_evento_change=on_evento, height="content")
