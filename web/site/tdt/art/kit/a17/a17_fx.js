/* A17 D30 Hollywood tiles (Art, 2026-10-21). Load AFTER a14_skin.js:
 *   <script src="../art/kit/a17/a17_fx.js"></script>
 * Draw-only. Paints into the A14 static cache (no per-frame draws):
 *   A14.bakeTop(x)      landmarks (d30 landmarks[] -> lm_* tile by name) + Palladium frontage + 10 street-label decals
 *   A17.drawFill(ctx,b) called by a14 paintBuildings for density buildings whose b.type is an A17 fill skin id
 * Code: after building the D30 map, call  A17.setMap(D30)  (the parsed design/d30/d30_map.json object, or the same fields).
 *   ?a17=0 = off.  A17.ready() true once the spec + images are loaded (the cache is invalidated once at that point). */
(function(){
  if (/[?&]a17=0(&|$)/.test(location.search)) return;
  if (/[?&]map=d30(&|$)/.test(location.search) && !/[?&]a17=1(&|$)/.test(location.search)) return; // C71 (ADR-0002): d30 = ?a17=0 path (no landmark paint, beacon, fill skins; plain lots fallback) unless ?a17=1. Colliders come from D30_LOTS in PLAY-THIS.
  const BASE = window.A17_BASE || "../art/kit/a17/";   // A17_BASE: test pages outside demo/
  const A17 = window.A17 = { ok:false, spec:null, img:{}, lots:[], labels:[], map:null };
  A17.ready = () => A17.ok;
  const inval = () => { if (window.A14 && A14.cache) A14.cache.invalidate(); };
  fetch(BASE + "a17_kit.json").then(r => r.json()).then(spec => {
    A17.spec = spec; const files = [...Object.values(spec.landmarks).map(m => m.file), ...Object.values(spec.fills).flat().map(m => m.file), ...Object.values(spec.labels).map(m => m.file), spec.beacon.file];
    let left = files.length;
    for (const f of files){ const im = new Image(); im.onload = im.onerror = () => { if (--left === 0){ A17.ok = true; build(); inval(); } }; im.src = BASE + f + "@2x.png"; A17.img[f] = im; } });
  A17.setMap = m => { A17.map = m; build(); inval(); };
  function padZones(m){ const g = 40, z = [];
    if (m.INTER) z.push({x:m.INTER.x-m.INTER.r-g, y:m.INTER.y-m.INTER.r-g, w:2*(m.INTER.r+g), h:2*(m.INTER.r+g)});
    if (m.DONUT) z.push({x:m.DONUT.x-m.DONUT.r-g, y:m.DONUT.y-m.DONUT.r-g, w:2*(m.DONUT.r+g), h:2*(m.DONUT.r+g)});
    for (const k of ["BURNOUT","ALLEY"]) if (m[k]) z.push({x:m[k].x-g, y:m[k].y-g, w:m[k].w+2*g, h:m[k].h+2*g});
    return z; }
  const hit = (a, z) => z.some(r => a.x < r.x+r.w && a.x+a.w > r.x && a.y < r.y+r.h && a.y+a.h > r.y);
  function build(){
    const m = A17.map, S = A17.spec; if (!m || !S) return;
    const byName = {}; for (const [id, t] of Object.entries(S.landmarks)) byName[t.d30_name] = id;
    A17.lots = []; A17.unmatched = [];
    for (const L of (m.landmarks || [])){                              // A17b: match by `tile` first, then by name
      const id = (L.tile && S.landmarks[L.tile]) ? L.tile : byName[L.name]; if (!id){ A17.unmatched.push(L.tile || L.name); continue; }
      const t = S.landmarks[id]; let x = L.x, y = L.y;
      const facade = L.facade != null ? !!L.facade : t.mode === "facade";
      if (facade && L.facade == null){   // legacy map without facade fields: frontage on the next road south
        const sun = m.ROADS_EW.filter(cy => cy > L.y).sort((a,b) => a-b)[0]; if (sun == null) continue; y = sun - m.ROAD_EW_H/2 - 12 - t.lot_wu[1]; }
      A17.lots.push({ id, x, y, w:t.lot_wu[0], d:t.lot_wu[1], t, tall: facade ? -1 : t.wall_h, facade, collide: L.collide != null ? !!L.collide : !facade }); }
    A17.lots.sort((a, b) => a.tall - b.tall || a.y - b.y);          // facades first, then low -> tall
    A17.colliders = A17.lots.filter(l => l.collide).map(l => ({ id:l.id, x:l.x, y:l.y, w:l.w, d:l.d })); // for Code: draw-only facades excluded
    const fb = new Set((m.fill_blocks || []).flatMap(k => String(k).split('+'))); A17.fillMap = m.fill_tiles || {}; A17.fillBlocks = fb;
    const cap = A17.lots.find(l => l.t.beacon_wu); A17.beacon = cap ? { x: cap.x + cap.t.beacon_wu[0], y: cap.y + cap.t.beacon_wu[1] } : null;
    // street labels: one per street, at the segment midpoint nearest the hub that is clear of every pad zone (+40 wu)
    const zones = padZones(m), hub = m.HUB || {x:m.WORLD.w/2, y:m.WORLD.h/2}; A17.labels = [];
    const nm = m.names || {NS:{}, EW:{}}, lab = n => S.labels["lbl_" + String(n).toLowerCase().replace(/ /g, "_")];
    for (const cx of m.ROADS_NS){ const l = lab(nm.NS[cx]); if (!l) continue; const ys = [0, ...m.ROADS_EW, m.WORLD.h], c = [];
      for (let i = 0; i < ys.length-1; i++){ const y = (ys[i]+ys[i+1])/2, r = {x:cx-l.wu[1]/2, y:y-l.wu[0]/2, w:l.wu[1], h:l.wu[0]}; if (!hit(r, zones) && y > 200 && y < m.WORLD.h-200) c.push({y, d:Math.abs(y-hub.y)}); }
      c.sort((a,b) => a.d-b.d); if (c[0]) A17.labels.push({ l, x:cx + m.ROAD_NS_W/4, y:c[0].y, rot:Math.PI/2 }); }
    for (const cy of m.ROADS_EW){ const l = lab(nm.EW[cy]); if (!l) continue; const xs = [0, ...m.ROADS_NS, m.WORLD.w], c = [];
      for (let i = 0; i < xs.length-1; i++){ const x = (xs[i]+xs[i+1])/2, r = {x:x-l.wu[0]/2, y:cy-l.wu[1]/2, w:l.wu[0], h:l.wu[1]}; if (!hit(r, zones) && x > 300 && x < m.WORLD.w-300) c.push({x, d:Math.abs(x-hub.x)}); }
      c.sort((a,b) => a.d-b.d); if (c[0]) A17.labels.push({ l, x:c[0].x, y:cy + m.ROAD_EW_H/4, rot:0 }); }
  }
  const vis = (v, x, y, w, h) => !v || (x < v.x1 && x+w > v.x0 && y < v.y1 && y+h > v.y0);
  A17.paint = function(x, v){                                        // world-space ctx, optional cull rect {x0,y0,x1,y1}
    if (!A17.ok) return;
    for (const L of A17.labels){ const w = L.l.wu[0], h = L.l.wu[1]; if (!vis(v, L.x-w, L.y-w, 2*w, 2*w)) continue;
      x.save(); x.translate(L.x, L.y); x.rotate(L.rot); x.globalAlpha = 0.85; x.drawImage(A17.img[L.l.file], -w/2, -h/2, w, h); x.restore(); }
    for (const L of A17.lots){ const t = L.t; if (!vis(v, L.x - t.anchor_wu[0], L.y - t.anchor_wu[1], t.wu[0], t.wu[1])) continue;
      x.drawImage(A17.img[t.file], L.x - t.anchor_wu[0], L.y - t.anchor_wu[1], t.wu[0], t.wu[1]); }
  };
  A17.drawFill = function(ctx, b){                                   // density building with an A17 fill type -> nearest size, stretched to the footprint
    if (!A17.ok) return false;
    let sk = A17.spec.fills[b.type] ? b.type : null;                 // explicit skin id as type
    if (!sk && A17.fillMap && A17.fillMap[b.type] && (!A17.fillBlocks || !A17.fillBlocks.size || A17.fillBlocks.has(b.block))) sk = A17.fillMap[b.type]; // A17b: d30 fill_tiles, only in fill_blocks
    if (!sk || !A17.spec.fills[sk]) return false;
    const vs = A17.spec.fills[sk]; let best = vs[0], e = 1e9;
    for (const s of vs){ const k = Math.abs(Math.log(b.w/s.lot_wu[0])) + Math.abs(Math.log(b.d/s.lot_wu[1])); if (k < e){ e = k; best = s; } }
    const sx = b.w/best.lot_wu[0], sy = b.d/best.lot_wu[1];
    ctx.drawImage(A17.img[best.file], b.x - best.anchor_wu[0]*sx, b.y - best.anchor_wu[1]*sy, best.wu[0]*sx, best.wu[1]*sy); return true; };
  A17.drawLandmarkAt = (ctx, id, x, y) => { const t = A17.spec && A17.spec.landmarks[id]; if (!A17.ok || !t) return; ctx.drawImage(A17.img[t.file], x - t.anchor_wu[0], y - t.anchor_wu[1], t.wu[0], t.wu[1]); };
  // A17b: Capitol beacon, LIVE (not cached). One 2-frame sprite: core (source-over) + halo (lighter). 0.55..1.0 over 1.2 s; reduced motion = 1.0.
  const RM = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches); A17.RM = RM;
  A17.beaconAlpha = t => RM ? 1 : 0.775 + 0.225*Math.sin(2*Math.PI*t/1.2);
  A17.drawBeacon = function(ctx){
    const B = A17.beacon, im = A17.img.fx_beacon; if (!A17.ok || !B || !im) return;
    const z = state.camZoom, hw = W/2/z + 20, hh = H/2/z + 20; if (Math.abs(B.x - state.camX) > hw || Math.abs(B.y - state.camY) > hh) return;   // cull
    const a = A17.beaconAlpha(performance.now()/1000), F = A17.spec.beacon.frames_wu, px = im.width/2;
    ctx.save(); ctx.globalAlpha = a; ctx.drawImage(im, 0, 0, px, im.height, B.x - F/2, B.y - F/2, F, F);
    ctx.globalCompositeOperation = "lighter"; ctx.drawImage(im, px, 0, px, im.height, B.x - F/2, B.y - F/2, F, F); ctx.restore(); };
  if (typeof window.drawLockBursts === "function"){ const oLB = window.drawLockBursts;   // world space, after cars/peds, before the hero
    window.drawLockBursts = function(){ A17.drawBeacon(ctx); return oLB.apply(this, arguments); }; }
  if (window.A14){
    A14.bakeTop = x => { if (A17.map) A17.paint(x, window.a7View ? a7View() : null); };
    const oDB = window.drawDensityBuildings;                          // ?a14cache=0 live path: paint after the buildings
    window.drawDensityBuildings = function(ctx){ oDB(ctx); if (A17.map && !(A14.cache && A14.cache.on && window.DENSITY)) A17.paint(ctx, a7View()); };
  }
})();
