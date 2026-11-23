/* A14 art pass skin (Art, 2026-10-20). Load AFTER the main game <script> in PLAY-THIS:
 *   <script src="../art/kit/a14/a14_skin.js"></script>
 * Draw-only. It overrides 5 global draw functions (drawDensityGround, drawDensityLights,
 * drawDensityBuildings, drawKitBuildings, drawCar) and exposes window.A14 for the two inline hooks
 * (peds + smoke) quoted in art/A14_ART_PASS.md. No state, collision, RNG or timing changes.
 * ?a14=0 turns it off; until the sprites load, the originals draw. Authored for zoom 0.80–0.96 (@2x = 4 px/wu). */
(function(){
  if (/[?&]a14=0(&|$)/.test(location.search)) return;
  const BASE = "../art/kit/a14/";
  const P = { // a14_kit.json "buildings" / "ground"
    bld: { teal:{roof:"#2F6F73",lit:"#3B8486",par:"#1E4B4E",ws:"#173A3D",we:"#1F4A4D"},
           tan:{roof:"#9C7E58",lit:"#B4936A",par:"#6E5940",ws:"#4A3C2B",we:"#5C4B36"},
           charcoal:{roof:"#3A3D45",lit:"#484C56",par:"#25272D",ws:"#191B20",we:"#22242A"} },
    map: { shop:"teal", corner_pad:"teal", warehouse:"tan", mid_rise:"charcoal", tower:"charcoal" },
    wallH: { low:14, medium:22, tall:34 }, lean:[-0.35,-0.65],
    side:"#4A4036", joint:"#3C342C", curb:"#8C8272", lot:"#1A1C22", xw:"rgba(214,208,194,0.62)" };
  const IMG = {}, names = ["car_a14_hero","car_a14_teal","car_a14_tan","car_a14_white","car_a14_slate","car_a14_van","car_a14_police",
    "roof_ac","roof_vent","roof_tank","roof_skylight","billboard_a14","smoke_a14","tree_a14",
    "npc_local_a14_red","npc_local_a14_teal","npc_local_a14_yellow","npc_local_a14_violet","npc_local_a14_brown","npc_local_a14_denim"];
  let left = names.length; const A14 = window.A14 = { ok:false, img:IMG, P };
  for (const n of names){ const im = new Image(); im.onload = () => { if (--left === 0) A14.ok = true; }; im.src = BASE + n + "@2x.png"; IMG[n] = im; }
  const hash = (a,b) => { let h = (Math.imul(a|0, 73856093) ^ Math.imul(b|0, 19349663)) >>> 0; h ^= h >>> 13; h = Math.imul(h, 0x5bd1e995) >>> 0; return (h ^ (h >>> 15)) >>> 0; };

  // ---------- peds / smoke hooks (called from the 2 inline edits) ----------
  const PED_VAR = ["npc_local_a14_red","npc_local_a14_teal","npc_local_a14_yellow","npc_local_a14_violet","npc_local_a14_brown","npc_local_a14_denim"];
  A14.pedSheet = p => { if (!A14.ok || p.type !== "local") return null; if (p._a14 == null) p._a14 = hash(Math.round(p.ph*1000), state.crowd.indexOf(p)) % PED_VAR.length; return IMG[PED_VAR[p._a14]]; };
  A14.PED_S = 24; // wu, was 16 (k multiplier still applies)
  A14.drawSmoke = (ctx, s) => { if (!A14.ok || s.col==="pink") return false; const im = IMG.smoke_a14, f = (hash(Math.round(s.r*10), 7) % 4), sz = 2*s.r*1.6;
    ctx.globalAlpha = Math.min(1, s.life*0.55) * (s.col==="pink" ? 0.9 : 1);
    ctx.drawImage(im, f*128, 0, 128, 128, s.x - sz/2, s.y - sz/2, sz, sz);
    if (s.col==="pink"){ ctx.globalCompositeOperation="source-atop"; } ctx.globalAlpha = 1; ctx.globalCompositeOperation="source-over"; return true; };

  // ---------- ground ----------
  const oGround = window.drawDensityGround;
  const paintGround = function(ctx){
    const v = a7View();
    for (const b of DENSITY.blocks){ if (!a7Vis(v,b.x,b.y,b.w,b.d)) continue; const I = b.inner;
      ctx.fillStyle = P.side; ctx.fillRect(b.x,b.y,b.w,b.d);
      ctx.strokeStyle = P.joint; ctx.lineWidth = 1.5; ctx.beginPath();           // 32 wu paver joints on the ring
      for (let x = b.x + 32; x < b.x + b.w; x += 32){ ctx.moveTo(x,b.y); ctx.lineTo(x,I.y); ctx.moveTo(x,I.y+I.d); ctx.lineTo(x,b.y+b.d); }
      for (let y = b.y + 32; y < b.y + b.d; y += 32){ ctx.moveTo(b.x,y); ctx.lineTo(I.x,y); ctx.moveTo(I.x+I.w,y); ctx.lineTo(b.x+b.w,y); }
      ctx.stroke();
      ctx.fillStyle = P.lot; ctx.fillRect(I.x,I.y,I.w,I.d);
      ctx.fillStyle = "#2B2620"; ctx.fillRect(I.x-3,I.y-3,I.w+6,3); ctx.fillRect(I.x-3,I.y+I.d,I.w+6,3); ctx.fillRect(I.x-3,I.y,3,I.d); ctx.fillRect(I.x+I.w,I.y,3,I.d); }
    ctx.fillStyle = P.side; for (const p of DENSITY.plazas) if (a7Vis(v,p.x,p.y,p.w,p.d)) ctx.fillRect(p.x,p.y,p.w,p.d);
    ctx.fillStyle = "rgba(200,208,224,0.22)"; for (const m of DENSITY.marks) if (a7Vis(v,m.x,m.y,m.w,m.d)) ctx.fillRect(m.x,m.y,m.w,m.d);
    ctx.fillStyle = "#10141F"; for (const c of DENSITY.courts) ctx.fillRect(c.x,c.y,c.w,c.d);
  };
  // after asphalt + dashes: warm the 12 wu road-side strip, light curb, crosswalks, then the original pools/poles
  const oLights = window.drawDensityLights;
  // A17c: road topology. PLAY-THIS can close road segments (ROAD_CUTS, d30: the Yucca cut; empty on the default map).
  // A cut {axis, c, from, to} removes road `c` between the cross-road centrelines `from`..`to` (same test as PLAY-THIS roadCutAt).
  // openSegs() = the painted extent of a road (junction boxes kept), legOpen() = does a junction approach lead onto a live road.
  const CUTS = () => (typeof ROAD_CUTS !== "undefined" && ROAD_CUTS) || [];
  const legOpen = (axis, c, along) => { const span = axis === "EW" ? WORLD.w : WORLD.h; if (along <= 0 || along >= span) return false;
    for (const k of CUTS()) if (k.axis === axis && k.c === c && along > k.from && along < k.to) return false; return true; };
  const openSegs = (axis, c) => { const span = axis === "EW" ? WORLD.w : WORLD.h, half = axis === "EW" ? ROAD_NS_W/2 : ROAD_EW_H/2; let segs = [[0, span]];
    for (const k of CUTS()){ if (k.axis !== axis || k.c !== c) continue; const c0 = k.from + half, c1 = k.to - half;
      segs = segs.flatMap(([a0, a1]) => (a1 <= c0 || a0 >= c1) ? [[a0, a1]] : [[a0, Math.min(a1, c0)], [Math.max(a0, c1), a1]].filter(q => q[1] - q[0] > 0.5)); }
    return segs; };
  A14.openSegs = openSegs; A14.legOpen = legOpen;
  A14.legs = () => { const out = [], eh = ROAD_EW_H/2, nh = ROAD_NS_W/2, D = 30;   // every junction approach (for tests/overlays)
    for (const cy of ROADS_EW) for (const cx of ROADS_NS){
      out.push({ x:cx-nh-D, y:cy, dir:"W", open:legOpen("EW", cy, cx-nh-D) }, { x:cx+nh+D, y:cy, dir:"E", open:legOpen("EW", cy, cx+nh+D) },
               { x:cx, y:cy-eh-D, dir:"N", open:legOpen("NS", cx, cy-eh-D) }, { x:cx, y:cy+eh+D, dir:"S", open:legOpen("NS", cx, cy+eh+D) }); }
    return out; };
  const paintStrips = function(ctx){
    { const eh = ROAD_EW_H/2, nh = ROAD_NS_W/2, sw = 12;
      const EW = ROADS_EW.map(cy => [cy, openSegs("EW", cy)]), NS = ROADS_NS.map(cx => [cx, openSegs("NS", cx)]);
      ctx.fillStyle = P.side;                                                   // 12 wu road-side strips, open segments only
      for (const [cy, sg] of EW) for (const [a0, a1] of sg){ ctx.fillRect(a0,cy-eh-sw,a1-a0,sw); ctx.fillRect(a0,cy+eh,a1-a0,sw); }
      for (const [cx, sg] of NS) for (const [a0, a1] of sg){ ctx.fillRect(cx-nh-sw,a0,sw,a1-a0); ctx.fillRect(cx+nh,a0,sw,a1-a0); }
      ctx.fillStyle = "#141820";                                                // keep junction boxes clear: only across legs that exist
      for (const cy of ROADS_EW) for (const cx of ROADS_NS){
        if (legOpen("NS", cx, cy-eh-1)) ctx.fillRect(cx-nh, cy-eh-sw, ROAD_NS_W, sw); if (legOpen("NS", cx, cy+eh+1)) ctx.fillRect(cx-nh, cy+eh, ROAD_NS_W, sw);
        if (legOpen("EW", cy, cx-nh-1)) ctx.fillRect(cx-nh-sw, cy-eh, sw, ROAD_EW_H); if (legOpen("EW", cy, cx+nh+1)) ctx.fillRect(cx+nh, cy-eh, sw, ROAD_EW_H);
        ctx.fillRect(cx-nh, cy-eh, ROAD_NS_W, ROAD_EW_H); }
      ctx.fillStyle = P.curb;                                                   // 4 wu curb on the asphalt edge, open segments only
      for (const [cy, sg] of EW) for (const [a0, a1] of sg){ ctx.fillRect(a0,cy-eh-2,a1-a0,4); ctx.fillRect(a0,cy+eh-2,a1-a0,4); }
      for (const [cx, sg] of NS) for (const [a0, a1] of sg){ ctx.fillRect(cx-nh-2,a0,4,a1-a0); ctx.fillRect(cx+nh-2,a0,4,a1-a0); }
      ctx.fillStyle = "#141820";
      for (const cy of ROADS_EW) for (const cx of ROADS_NS){ ctx.fillRect(cx-nh+2, cy-eh+2, ROAD_NS_W-4, ROAD_EW_H-4);    // reopen the box, then
        if (!legOpen("EW", cy, cx-nh-1)){ ctx.fillStyle = P.curb; ctx.fillRect(cx-nh-2, cy-eh+2, 4, ROAD_EW_H-4); ctx.fillStyle = "#141820"; }   // closed leg = kerb across the mouth (T-junction)
        if (!legOpen("EW", cy, cx+nh+1)){ ctx.fillStyle = P.curb; ctx.fillRect(cx+nh-2, cy-eh+2, 4, ROAD_EW_H-4); ctx.fillStyle = "#141820"; }
        if (!legOpen("NS", cx, cy-eh-1)){ ctx.fillStyle = P.curb; ctx.fillRect(cx-nh+2, cy-eh-2, ROAD_NS_W-4, 4); ctx.fillStyle = "#141820"; }
        if (!legOpen("NS", cx, cy+eh+1)){ ctx.fillStyle = P.curb; ctx.fillRect(cx-nh+2, cy+eh-2, ROAD_NS_W-4, 4); ctx.fillStyle = "#141820"; } }
      ctx.fillStyle = P.xw; const D = 44, st = 12;                                // zebra on every OPEN approach (A17c: none toward a cut / world edge)
      for (const cy of ROADS_EW) for (const cx of ROADS_NS){
        const xr = (x, y, w, h) => { if (Math.hypot(x+w/2-INTER.x, y+h/2-INTER.y) > INTER.r + 24) ctx.fillRect(x, y, w, h); }; // A14b: none inside the drift circle (INTER r360 + 24)
        const N = legOpen("NS", cx, cy-eh-D), S = legOpen("NS", cx, cy+eh+D), Wl = legOpen("EW", cy, cx-nh-D), E = legOpen("EW", cy, cx+nh+D);
        for (let x = cx-nh+14; x < cx+nh-14; x += 2*st){ if (N) xr(x, cy-eh-D-6, st, D); if (S) xr(x, cy+eh+6, st, D); }
        for (let y = cy-eh+14; y < cy+eh-14; y += 2*st){ if (Wl) xr(cx-nh-D-6, y, D, st); if (E) xr(cx+nh+6, y, D, st); } }
    }
  };
  // ---------- buildings: lit roof + S/E walls + parapet + rooftop props ----------
  function bldg(ctx, x, y, w, d, type, hBand, neon, face, neonA, near, seed){
    const c = P.bld[P.map[type] || "charcoal"], h = P.wallH[hBand] || 14, ox = h*P.lean[0], oy = h*P.lean[1], rx = x+ox, ry = y+oy;
    ctx.fillStyle = "rgba(4,5,9,0.45)"; ctx.fillRect(x+6, y+6, w, d);                         // contact shadow on the ground
    ctx.fillStyle = c.ws; ctx.beginPath(); ctx.moveTo(rx,ry+d); ctx.lineTo(rx+w,ry+d); ctx.lineTo(x+w,y+d); ctx.lineTo(x,y+d); ctx.fill();   // south wall
    ctx.fillStyle = c.we; ctx.beginPath(); ctx.moveTo(rx+w,ry); ctx.lineTo(x+w,y); ctx.lineTo(x+w,y+d); ctx.lineTo(rx+w,ry+d); ctx.fill(); // east wall
    if (hBand !== "low"){ ctx.fillStyle = "rgba(255,201,138,0.38)";                           // warm windows on the south face
      const rows = Math.max(1, Math.floor(-oy/8)); for (let r = 0; r < rows; r++){ const t = (r+0.5)/rows, yy = ry+d + (y+d-(ry+d))*t, xx = rx + (x-rx)*t;
        for (let wx = 8; wx < w-10; wx += 14) if (hash(seed+r, wx) % 3) ctx.fillRect(xx+wx, yy-1.5, 7, 3); } }
    if (neon && (face === "s" || face === "e")){ ctx.globalAlpha = neonA; ctx.fillStyle = neon;
      if (face === "s") ctx.fillRect(rx+6, ry+d+ (y-ry)*0.35, w-12, 4); else ctx.fillRect(rx+w+(x-rx)*0.4, ry+6, 4, d-12); ctx.globalAlpha = 1; }
    const g = ctx.createLinearGradient(rx, ry, rx+w, ry+d); g.addColorStop(0, c.lit); g.addColorStop(1, c.roof);
    ctx.fillStyle = g; ctx.fillRect(rx, ry, w, d);                                              // lit roof plane
    ctx.strokeStyle = c.par; ctx.lineWidth = 4; ctx.strokeRect(rx+2, ry+2, w-4, d-4);          // parapet
    ctx.fillStyle = "rgba(255,255,255,0.10)"; ctx.fillRect(rx, ry, w, 1.5); ctx.fillRect(rx, ry, 1.5, d);
    if (neon){ const r = face === "n" ? [rx+6, ry-1, w-12, 5] : face === "s" ? [rx+6, ry+d-4, w-12, 5] : face === "w" ? [rx-1, ry+6, 5, d-12] : [rx+w-4, ry+6, 5, d-12];
      ctx.save(); ctx.globalAlpha = Math.max(0.75, neonA); ctx.shadowColor = neon; ctx.shadowBlur = 14; ctx.fillStyle = neon; ctx.fillRect(r[0], r[1], r[2], r[3]); // A14b: neon tube on the roof edge (trim hue 225-308)
      ctx.shadowBlur = 0; ctx.globalAlpha = near ? 0.85 : 0.5; ctx.fillStyle = "#F4F1EA";
      if (r[2] > r[3]) ctx.fillRect(r[0]+3, r[1]+2, r[2]-6, 1.2); else ctx.fillRect(r[0]+2, r[1]+3, 1.2, r[3]-6); ctx.restore(); }
    // props: deterministic per building (seed = footprint position)
    const pr = [["roof_ac",14,11],["roof_ac",14,11],["roof_vent",7,7],["roof_skylight",18,12]]; if (hBand === "tall") pr.push(["roof_tank",16,16]);
    const n = Math.min(7, Math.floor(w*d/2600) + 1);
    for (let i = 0; i < n; i++){ const hs = hash(seed, i+1), p = pr[hs % pr.length]; if (p[1] > w-16 || p[2] > d-16) continue;
      const px = rx + 8 + (hs >>> 4) % Math.max(1, w-16-p[1]), py = ry + 8 + (hs >>> 12) % Math.max(1, d-16-p[2]);
      ctx.fillStyle = "rgba(0,0,0,0.35)"; ctx.fillRect(px+2, py+2, p[1], p[2]); ctx.drawImage(IMG[p[0]], px, py, p[1], p[2]); }
    if (near && hBand !== "low" && w >= 80 && hash(seed, 99) % 2 === 0) ctx.drawImage(IMG.billboard_a14, rx + w/2 - 32, ry + 6, 64, 22);
  }
  const TREE_AVOID = [ {x:INTER.x-INTER.r, y:INTER.y-INTER.r, w:2*INTER.r, h:2*INTER.r}, {x:DONUT.x-DONUT.r-40, y:DONUT.y-DONUT.r-40, w:2*DONUT.r+80, h:2*DONUT.r+80},
    {x:BURNOUT.x-40, y:BURNOUT.y-40, w:BURNOUT.w+80, h:BURNOUT.h+80}, {x:ALLEY.x-40, y:ALLEY.y-40, w:ALLEY.w+80, h:ALLEY.h+80} ];
  const oDB = window.drawDensityBuildings;
  const paintBuildings = function(ctx){
    oDB(ctx);                                    // clutter + original look first (clutter stays), then the A14 blocks on top
    const v = a7View();
    for (const b of DENSITY.buildings){ if (!a7Vis(v,b.x-40,b.y-40,b.w+80,b.d+80)) continue;
      if (window.A17 && A17.drawFill(ctx, b)) continue; /* A17: D30 fill skins by density type */
      bldg(ctx, b.x, b.y, b.w, b.d, b.type, b.hBand, b.neon, b.face, b.neonAlpha, b.core, hash(b.x, b.y)); }
    for (const pz of DENSITY.plazas){ if (!a7Vis(v,pz.x,pz.y,pz.w,pz.d) || pz.w < 60 || pz.d < 60) continue;  // ref 2 trees in plaza corners
      if (TREE_AVOID.some(r => pz.x < r.x+r.w && pz.x+pz.w > r.x && pz.y < r.y+r.h && pz.y+pz.d > r.y)) continue; // never on pads/alley
      if (hash(pz.x|0, pz.y|0) % 3) continue;                                                                 // ~1 plaza in 3 gets a tree
      ctx.drawImage(IMG.tree_a14, pz.x+6, pz.y+6, 40, 40); }
  };
  const oKB = window.drawKitBuildings;
  const paintKit = function(ctx){
    for (const b of KIT_BUILDINGS){ const c = kitToWorld(b.ax, b.az), w = b.w*KIT_SCALE, d = b.d*KIT_SCALE;
      bldg(ctx, c.x-w/2, c.y-d/2, w, d, b.id, b.hBand, b.neon, "e", 1, true, hash(c.x|0, c.y|0)); }
  };
  // ---------- A14b: baked static layers (perf) ----------
  // Region cache (one layer): ground + C16 roads + A14 strips/crosswalks + A7 sodium pools (static screen blend) + poles + density/kit
  // blocks/neon/trees/clutter are painted into one offscreen canvas covering the view + 30 % margin per side at the current px-per-wu
  // (zoom × DPR). Every frame only blits it at ~1:1. Re-bake when the canvas size/DPR changes or px-per-wu leaves ×0.87–1.15 (full bake).
  // When the view leaves the region (panning), the old pixels are shifted and only the exposed strips are painted.
  // A world-sized/tiled cache was tried first: headless Chrome falls off a cliff (~10 ms/frame) above ~5 MP of cached canvas,
  // so the layer stays view-sized under MAXPX. Live: pads, skids, smoke, peds, cars, HUD (everything drawn after drawDensityBuildings).
  // ?a14cache=0 = old live path (for A/B).
  const MARGIN = 0.30;
  A14.cache = { builds:0, on: !/[?&]a14cache=0(&|$)/.test(location.search) };
  function roadsC16(c){ const eh = ROAD_EW_H/2, nh = ROAD_NS_W/2, sw = 12;   // same paint as PLAY-THIS "C16 DEMO_PAINT roads"; A17c: open segments only
    const EW = ROADS_EW.map(cy => [cy, openSegs("EW", cy)]), NS = ROADS_NS.map(cx => [cx, openSegs("NS", cx)]);
    c.fillStyle="#141820"; for (const [cy, sg] of EW) for (const [a0,a1] of sg) c.fillRect(a0,cy-eh,a1-a0,ROAD_EW_H); for (const [cx, sg] of NS) for (const [a0,a1] of sg) c.fillRect(cx-nh,a0,ROAD_NS_W,a1-a0);
    c.fillStyle="#1E2433"; for (const [cy, sg] of EW) for (const [a0,a1] of sg){ c.fillRect(a0,cy-eh-sw,a1-a0,sw); c.fillRect(a0,cy+eh,a1-a0,sw); } for (const [cx, sg] of NS) for (const [a0,a1] of sg){ c.fillRect(cx-nh-sw,a0,sw,a1-a0); c.fillRect(cx+nh,a0,sw,a1-a0); }
    c.strokeStyle="#2A3142"; c.lineWidth=8; for (const [cy, sg] of EW) for (const [a0,a1] of sg) c.strokeRect(a0+4,cy-eh+4,a1-a0-8,ROAD_EW_H-8); for (const [cx, sg] of NS) for (const [a0,a1] of sg) c.strokeRect(cx-nh+4,a0+4,ROAD_NS_W-8,a1-a0-8);
    c.strokeStyle="rgba(200,208,224,0.62)"; c.setLineDash([24,20]); c.lineWidth=Math.max(3, 2/state.camZoom);
    for (const [cy, sg] of EW) for (const [a0,a1] of sg){ c.beginPath(); c.moveTo(a0,cy); c.lineTo(a1,cy); c.stroke(); } for (const [cx, sg] of NS) for (const [a0,a1] of sg){ c.beginPath(); c.moveTo(cx,a0); c.lineTo(cx,a1); c.stroke(); } c.setLineDash([]); }
  const MAXPX = (/[?&]map=d30(&|$)/.test(location.search) && !/[?&]dense=1(&|$)/.test(location.search)) ? 2.0e6 : 4.2e6; // C72 (ADR-0002): d30 bakes the density cache at <=2.0 MP (softer, ~half the blit fill); ?dense=1 = full 4.2 MP   // backing-pixel budget for the single cache canvas (headless Chrome falls off a cliff above ~5 MP of cached canvas)
  let C1 = document.createElement("canvas"), X1 = C1.getContext("2d"), C2 = document.createElement("canvas"), X2 = C2.getContext("2d"), L1 = null, R = null; // double buffer for pan shifts
  function bake(v, ppw, ctx){
    // one layer: ground + C16 roads + A14 strips/crosswalks + A7 sodium pools (static screen blend) + poles + density/kit blocks.
    // Margin shrinks (0.30 → 0.12) and then the bake density drops (k ≤ 1) only when the canvas is big (1080p+/DPR 2), to stay inside MAXPX.
    const cw = ctx.canvas.width, ch = ctx.canvas.height; let m = MARGIN;
    while (m > 0.12 && cw*ch*(1+2*m)*(1+2*m) > MAXPX) m -= 0.02;
    let w = Math.ceil(cw*(1+2*m)), h = Math.ceil(ch*(1+2*m)); const k = Math.min(1, Math.sqrt(MAXPX/(w*h))); w = Math.ceil(w*k); h = Math.ceil(h*k);
    const sc = ppw*k, cx = (v.x0+v.x1)/2, cy = (v.y0+v.y1)/2, r = {x0:cx - w/2/sc, y0:cy - h/2/sc, x1:cx + w/2/sc, y1:cy + h/2/sc, sc:ppw, k};
    const paintAll = (x, cl) => { const ov = window.a7View; window.a7View = () => cl;   // cull to the painted rect
      try { x.save(); x.setTransform(sc,0,0,sc,-r.x0*sc,-r.y0*sc); x.beginPath(); x.rect(cl.x0, cl.y0, cl.x1-cl.x0, cl.y1-cl.y0); x.clip();
            x.fillStyle = "#121722"; x.fillRect(cl.x0, cl.y0, cl.x1-cl.x0, cl.y1-cl.y0);
            paintGround(x); roadsC16(x); paintStrips(x); oLights(x); if (A14.bakeExtra) A14.bakeExtra(x); /* A16: wet reflections + neon spill */ paintBuildings(x); paintKit(x); if (A14.bakeTop) A14.bakeTop(x); /* A17: D30 landmarks + street labels */ x.restore(); }
      finally { window.a7View = ov; } };
    if (R && L1 && R.key === ctx.canvas.width + "x" + ctx.canvas.height && R.w === w && R.h === h && R.bsc === sc){
      // pan-only: snap to whole px, shift the old pixels, paint only the newly exposed strips (≈ 1/4 of a full bake)
      const dx = Math.round((r.x0 - R.x0)*sc), dy = Math.round((r.y0 - R.y0)*sc); r.x0 = R.x0 + dx/sc; r.y0 = R.y0 + dy/sc; r.x1 = r.x0 + w/sc; r.y1 = r.y0 + h/sc;
      if (Math.abs(dx) < w && Math.abs(dy) < h){
        X2.setTransform(1,0,0,1,0,0); X2.globalCompositeOperation = "copy"; X2.drawImage(C1, -dx, -dy); X2.globalCompositeOperation = "source-over";
        const strips = [];
        if (dx > 0) strips.push({x0:R.x1, y0:r.y0, x1:r.x1, y1:r.y1}); else if (dx < 0) strips.push({x0:r.x0, y0:r.y0, x1:R.x0, y1:r.y1});
        if (dy > 0) strips.push({x0:r.x0, y0:R.y1, x1:r.x1, y1:r.y1}); else if (dy < 0) strips.push({x0:r.x0, y0:r.y0, x1:r.x1, y1:R.y0});
        for (const st of strips) paintAll(X2, st);
        const t = C1; C1 = C2; C2 = t; const tx = X1; X1 = X2; X2 = tx;
        Object.assign(r, {w, h, bsc:sc}); R = r; L1 = C1; A14.cache.pans = (A14.cache.pans||0) + 1; return; } }
    if (C1.width !== w || C1.height !== h){ C1.width = w; C1.height = h; C2.width = w; C2.height = h; }
    paintAll(X1, r);
    Object.assign(r, {w, h, bsc:sc}); R = r; L1 = C1; A14.cache.builds++; A14.cache.k = +k.toFixed(2); A14.cache.px = w + "x" + h; }
  A14.cache.invalidate = () => { R = null; };
  function ensure(ctx){ if (!A14.cache.on || !DENSITY) return false; /* ?dense=0: no density layer -> old live path */ const m = ctx.getTransform(), ppw = Math.hypot(m.a, m.b), v = a7View(), size = ctx.canvas.width + "x" + ctx.canvas.height;
    if (!R || R.key !== size || ppw > R.sc*1.15 || ppw < R.sc*0.87 || v.x0 < R.x0 || v.y0 < R.y0 || v.x1 > R.x1 || v.y1 > R.y1){ const zb = !R || R.key !== size || ppw > R.sc*1.15 || ppw < R.sc*0.87; bake(v, zb ? ppw : R.sc, ctx); R.key = size; } return true; }
  function blit(ctx){ ctx.drawImage(C1, R.x0, R.y0, R.x1-R.x0, R.y1-R.y0); }
  window.drawDensityGround = function(ctx){ if (!A14.ok) return oGround(ctx); if (ensure(ctx)) return; paintGround(ctx); };  // cached: L1 covers it later
  window.drawKitBuildings  = function(ctx){ if (!A14.ok) return oKB(ctx);   if (ensure(ctx)) return; paintKit(ctx); };
  window.drawDensityLights = function(ctx){ if (A14.ok && ensure(ctx)) return blit(ctx); if (A14.ok) paintStrips(ctx); oLights(ctx); };
  window.drawDensityBuildings = function(ctx){ if (!A14.ok) return oDB(ctx); if (ensure(ctx)) return; paintBuildings(ctx); };  // cached: already in the layer

  // ---------- cars: body + darker roof ----------
  const TRAFFIC = ["car_a14_teal","car_a14_tan","car_a14_white","car_a14_slate"];
  const LEN = { car_a14_hero:45, car_a14_police:48, car_a14_van:49, car_a14_teal:45, car_a14_tan:45, car_a14_white:45, car_a14_slate:45 };
  const oCar = window.drawCar; let tN = 0;
  window.drawCar = function(x,y,a,color,roof,cop,hero,kind){
    if (!A14.ok) return oCar(x,y,a,color,roof,cop,hero,kind);
    let id = hero ? "car_a14_hero" : cop ? "car_a14_police" : null;
    if (!id){ const t = state.traffic.find(t => t.x === x && t.y === y);
      if (t){ if (!t._a14) t._a14 = (kind === "traffic_van") ? "car_a14_van" : TRAFFIC[(tN++) % TRAFFIC.length]; id = t._a14; } else id = "car_a14_white"; }
    const im = IMG[id], boost = hero ? clamp(0.67 / state.camZoom, 1, 1.2) : 1, L = LEN[id]*boost, Wd = L*im.height/im.width, px = 1/state.camZoom;
    ctx.save(); ctx.translate(x,y); ctx.rotate(a);
    if (hero && typeof c61Lift === "function") c61Lift(L, Wd);
    ctx.fillStyle = "rgba(4,5,9,0.5)"; ctx.fillRect(-L/2+3, -Wd/2+3, L, Wd);                    // contact shadow
    if (hero) drawHeroCone(L, Wd, px);
    if (hero){ ctx.shadowColor = "rgba(7,8,13,0.9)"; ctx.shadowBlur = 8; } // A14b: dark halo separates the hero from pink box/smoke
    ctx.drawImage(im, -L/2, -Wd/2, L, Wd); ctx.shadowBlur = 0;
    if (hero) drawHeroLamps(L, Wd, px);
    ctx.restore();
  };
})();
