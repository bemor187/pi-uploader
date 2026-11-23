/* A7 density fill — Art-owned, deterministic. See art/A7_DENSITY.md.
 * buildDensity(cfg) -> { seed, blocks, buildings, clutter, lights, poles, plazas, courts, exclusions, stats }
 * Pure + seeded (mulberry32): same cfg -> identical output every load. No Math.random, no DOM.
 * Browser: <script src="../art/kit/density.js"></script> defines window.buildDensity (file:// safe; JSON fetch is not).
 * Node:    const { buildDensity } = require("./density.js");
 * All units are demo world units (wu = m x KIT_SCALE 10). Rect = {x, y, w, d} like kitFootprint().
 * A9 (2026-10-08, D23 G7): building trim (neon strip + spill) moved off the pad hues. Colour only: seed, RNG stream,
 * placements and counts are unchanged (density.json differs only in buildings[].neon). See art/A7_DENSITY.md "## A9".
 */
(function (root) {
  "use strict";
  const A7 = {
    SEED: 0xA7D3,           // 42963
    SIDEWALK: 32,           // sidewalk ring, from road edge into the block (C16 already paints the outer 12)
    LOT_GAP: 14,            // service gap between neighbouring buildings (shows lot ground)
    MAX_LOT: 230, MIN_LOT: 90, MIN_BLD: 70,
    SPLIT_MIN: 0.38, SPLIT_MAX: 0.62,
    KIT_GAP: 20,            // clearance around the 14 existing KIT_BUILDINGS footprints
    MAX_STRETCH: 1.25,      // sprite aspect stretch cap (A6 Fix 1: shop was 1.48x)
    LIGHT_SPACING: 240, LIGHT_INSET: 50, LIGHT_R: 90, LIGHT_A: 0.13, POLE_INSET: 16,
    JUNCTION_R: 190, JUNCTION_A: 0.14, HUB_A: 0.18, NW_A: 0.06,
    // C35c lamp warmth: alpha `w` per tier for the screen-blended sodium pool (a = legacy C35 source-over alpha, unused once C35c lands)
    WARM_A: { street: 0.30, junction: 0.30, hub: 0.16, nw: 0.08 },
    ALLEY_DARK_R: 380,      // no street pools within this of the alley centre (STYLE_GUIDE: alley underlit)
    DRIFT_GRACE: 80,        // PLAY-THIS L956 `INTER.r + 80` (C34); pass cfg.params.DRIFT_GRACE if Code retunes it
    CAR_R: 18,              // resolveKitCollision rad
    NEON_NEAR: 900          // building centre within this of HUB -> full neon + tube core; else 60 % neon, no core
  };
  // Sprite pixel sizes as drawn (manifest.json; shop is pre-rotated -90 deg at load, L360-363)
  const SPRITE_PX = { shop: [240, 194], warehouse: [250, 224], mid_rise: [223, 224], tower: [230, 250], corner_pad: [246, 151] };
  // A9 trim palette. Pads own cyan 184-190 deg (#33F2FF/#3EE0FF), gold 43 deg (#FFD15A), pink 343 deg (#FF2D6A);
  // sodium lamps own 26-35 deg (#FF8C32-#FFB347); the alley / lock ring own green 140 deg (#7DFFA8).
  // Keep-out = pad hue +-10 deg band + 25 deg margin: cyan 149-225, gold 8-78 (covers the lamp band), pink 308-18 (wraps),
  // plus alley green 115-165. Trim lives only in the cool window 225-308: blue -> violet -> orchid (+ one pale ice).
  // Two brightness tiers are unchanged: near hub (<= NEON_NEAR) alpha 1 + #F4F1EA tube core; outskirts alpha 0.6, no core.
  const TRIM = {
    cobalt: "#4361FF",   // 230 deg, sat 0.74  (was shop cyan #33F2FF, 184 deg = cyan pad)
    violet: "#8C59FF",   // 258 deg, sat 0.65  (mid_rise, unchanged)
    ice:    "#8C90D8",   // 237 deg, sat 0.35, luma 151 (kept under the pad luma)  (was warehouse orange #FF8C1F, 29 deg = lamp band, 14 deg from gold)
    orchid: "#D94DFF"    // 287 deg, sat 0.70  (was corner_pad green #7DFFA8 = alley, tower pink #FF2D6A = pink pad)
  };
  const TYPES = {        // DEMO_PAINT flats + A9 trim (KIT_BUILDINGS in PLAY-THIS still carry the pre-A9 neon until Code swaps them)
    shop:       { color: "#2E3A52", neon: TRIM.cobalt, hBand: "low",    weight: 30 },
    mid_rise:   { color: "#2A3348", neon: TRIM.violet, hBand: "medium", weight: 25 },
    warehouse:  { color: "#3A3530", neon: TRIM.ice,    hBand: "low",    weight: 22 },
    corner_pad: { color: "#2F3D38", neon: TRIM.orchid, hBand: "low",    weight: 13 },
    tower:      { color: "#1C2233", neon: TRIM.orchid, hBand: "tall",   weight: 10 }
  };
  function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  const R = (x, y, w, d) => ({ x, y, w, d });
  const inflate = (r, m) => R(r.x - m, r.y - m, r.w + 2 * m, r.d + 2 * m);
  const rr = (a, b) => a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.d && a.y + a.d > b.y;
  function rectCircle(r, cx, cy, rad) { const dx = Math.max(r.x - cx, 0, cx - r.x - r.w), dy = Math.max(r.y - cy, 0, cy - r.y - r.d); return dx * dx + dy * dy < rad * rad; }
  function segRectDist(r, x0, y0, x1, y1) { // min distance from segment to rect (sampled, 1 wu-ish)
    const n = Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 4); let m = 1e9;
    for (let i = 0; i <= n; i++) { const t = i / n, px = x0 + (x1 - x0) * t, py = y0 + (y1 - y0) * t;
      const dx = Math.max(r.x - px, 0, px - r.x - r.w), dy = Math.max(r.y - py, 0, py - r.y - r.d); m = Math.min(m, Math.hypot(dx, dy)); }
    return m; }
  function hitsZone(r, z) {
    if (z.kind === "rect") return rr(r, z);
    if (z.kind === "circle") return rectCircle(r, z.cx, z.cy, z.r);
    if (z.kind === "capsule") return segRectDist(r, z.x0, z.y0, z.x1, z.y1) < z.r;
    return false; }

  function buildDensity(cfg) {
    const P = Object.assign({}, A7, cfg.params || {});
    const rnd = mulberry32(P.SEED);
    const { WORLD, ROADS_EW, ROADS_NS, ROAD_EW_H, ROAD_NS_W, HUB, INTER, DONUT, BURNOUT, ALLEY, SPAWN } = cfg;
    const ewH = ROAD_EW_H / 2, nsH = ROAD_NS_W / 2;
    // ---- blocks = world minus road bands (row-major, NW first)
    const xs = [0], ys = [0];
    for (const c of ROADS_NS) xs.push(c - nsH, c + nsH); xs.push(WORLD.w);
    for (const c of ROADS_EW) ys.push(c - ewH, c + ewH); ys.push(WORLD.h);
    const blocks = [];
    for (let j = 0; j < ys.length; j += 2) for (let i = 0; i < xs.length; i += 2) {
      const b = R(xs[i], ys[j], xs[i + 1] - xs[i], ys[j + 1] - ys[j]);
      b.id = "B" + (j / 2) + (i / 2); // B<row><col>
      b.road = { n: j > 0, s: j < ys.length - 2, w: i > 0, e: i < xs.length - 2 }; // sides that face an arterial
      const s = P.SIDEWALK;
      b.inner = R(b.x + (b.road.w ? s : 0), b.y + (b.road.n ? s : 0), b.w - (b.road.w ? s : 0) - (b.road.e ? s : 0), b.d - (b.road.n ? s : 0) - (b.road.s ? s : 0));
      blocks.push(b);
    }
    // ---- exclusion zones (hard): pads, pink lane, alley court, spawn, existing kit
    const ex = [
      { id: "E1 drift circle", kind: "circle", cx: INTER.x, cy: INTER.y, r: INTER.r + P.DRIFT_GRACE + P.CAR_R + 12, plaza: true }, // C34: 360 + 80 grace + 18 car + 12 = 470
      { id: "E2 donut pad",    kind: "circle", cx: DONUT.x, cy: DONUT.y, r: DONUT.r + 110, plaza: true },   // 90 + 40 nearDonut + 18 car + 52
      { id: "E3 burnout box",  kind: "rect", x: BURNOUT.x - 80, y: BURNOUT.y - 80, w: BURNOUT.w + 160, d: BURNOUT.h + 160, plaza: true }, // 40 nearBurn + 40
      { id: "E4 gold->pink lane", kind: "capsule", x0: DONUT.x, y0: DONUT.y, x1: BURNOUT.x + BURNOUT.w / 2, y1: BURNOUT.y + BURNOUT.h / 2, r: 90, plaza: true },
      { id: "E5 alley court",  kind: "rect", x: ALLEY.x - 40, y: ALLEY.y - 40, w: (ROADS_NS[0] - nsH) - (ALLEY.x - 40), d: (ROADS_EW[0] - ewH) - (ALLEY.y - 40), dark: true }, // open to NS-900 (E) and EW-700 (S)
      { id: "E6 spawn",        kind: "circle", cx: SPAWN.x, cy: SPAWN.y, r: 140 }
    ];
    (cfg.kitRects || []).forEach((k, i) => ex.push(Object.assign({ id: "E7 kit#" + i, kind: "rect" }, inflate(k, P.KIT_GAP))));
    const clear = r => !ex.some(z => hitsZone(r, z));
    // shrink a lot away from blocking zones: best of 4 one-sided cuts (binary search), else drop
    function fit(lot) {
      if (clear(lot)) return lot;
      let best = null;
      const tries = [
        t => R(lot.x, lot.y, lot.w * t, lot.d), t => R(lot.x + lot.w * (1 - t), lot.y, lot.w * t, lot.d),
        t => R(lot.x, lot.y, lot.w, lot.d * t), t => R(lot.x, lot.y + lot.d * (1 - t), lot.w, lot.d * t)];
      for (const f of tries) { let lo = 0, hi = 1; for (let k = 0; k < 18; k++) { const m = (lo + hi) / 2; if (clear(f(m))) lo = m; else hi = m; }
        const c = f(lo); const snap = R(Math.round(c.x), Math.round(c.y), Math.floor(c.w), Math.floor(c.d));
        if (snap.w >= P.MIN_BLD && snap.d >= P.MIN_BLD && clear(snap) && (!best || snap.w * snap.d > best.w * best.d)) best = snap; }
      return best; }
    // ---- BSP lots
    function split(r, out) {
      const long = Math.max(r.w, r.d);
      if (long <= P.MAX_LOT || long < 2 * P.MIN_LOT + P.LOT_GAP) { out.push(r); return; }
      const t = P.SPLIT_MIN + rnd() * (P.SPLIT_MAX - P.SPLIT_MIN);
      if (r.w >= r.d) { const a = Math.round((r.w - P.LOT_GAP) * t); split(R(r.x, r.y, a, r.d), out); split(R(r.x + a + P.LOT_GAP, r.y, r.w - a - P.LOT_GAP, r.d), out); }
      else { const a = Math.round((r.d - P.LOT_GAP) * t); split(R(r.x, r.y, r.w, a), out); split(R(r.x, r.y + a + P.LOT_GAP, r.w, r.d - a - P.LOT_GAP), out); }
    }
    const buildings = [], clutter = [], plazaRects = [], leaves = [];
    for (const b of blocks) {
      const lots = []; split(b.inner, lots);
      for (const leaf of lots) {
       // blocked leaf: halve along the long axis and retry (down to MIN_BLD pieces), then one-sided cut; any loss -> leaf paved as forecourt
       const pieces = [], q = [leaf]; let lost = false;
       while (q.length) { const r = q.shift();
         if (!clear(r) && Math.max(r.w, r.d) >= 2 * P.MIN_BLD + P.LOT_GAP) { const a = Math.round((Math.max(r.w, r.d) - P.LOT_GAP) / 2);
           if (r.w >= r.d) q.unshift(R(r.x, r.y, a, r.d), R(r.x + a + P.LOT_GAP, r.y, r.w - a - P.LOT_GAP, r.d));
           else q.unshift(R(r.x, r.y, r.w, a), R(r.x, r.y + a + P.LOT_GAP, r.w, r.d - a - P.LOT_GAP)); lost = true; continue; }
         const f = fit(r); if (f !== r) lost = true; if (f) pieces.push(f); }
       leaves.push(Object.assign({ block: b.id, pieces: pieces.length, lost }, leaf));
       if (lost && !hitsZone(leaf, ex[4])) plazaRects.push(Object.assign({ block: b.id }, leaf)); // never pave the alley court
       for (const lot of pieces) {
        // frontage = lot edges flush with the sidewalk ring on a road side
        const I = b.inner, fr = [];
        if (b.road.n && lot.y === I.y) fr.push("n"); if (b.road.s && lot.y + lot.d === I.y + I.d) fr.push("s");
        if (b.road.w && lot.x === I.x) fr.push("w"); if (b.road.e && lot.x + lot.w === I.x + I.w) fr.push("e");
        // type pick: weights x fit; tower needs min side >= 150; corner_pad x3 on 2-frontage corner lots
        const cand = [];
        for (const id of Object.keys(TYPES)) {
          if (id === "tower" && Math.min(lot.w, lot.d) < 150) continue;
          const [pw, ph] = SPRITE_PX[id], a = pw / ph;
          const rotQ = (lot.w >= lot.d) === (a >= 1) ? 0 : 1;           // quarter turns so sprite long axis = lot long axis
          const sa = rotQ ? 1 / a : a, la = lot.w / lot.d, s = Math.max(la / sa, sa / la);
          let w = TYPES[id].weight * (id === "corner_pad" && fr.length >= 2 ? 3 : 1) / s;
          cand.push({ id, rotQ, sa, w });
        }
        let tot = cand.reduce((t, c) => t + c.w, 0), pick = rnd() * tot, c = cand[0];
        for (const k of cand) { pick -= k.w; if (pick <= 0) { c = k; break; } }
        // shrink long side to MAX_STRETCH, anchored to the frontage (keeps the street wall)
        let bw = lot.w, bd = lot.d; const la = bw / bd;
        if (la / c.sa > P.MAX_STRETCH) bw = Math.round(bd * c.sa * P.MAX_STRETCH);
        if (c.sa / la > P.MAX_STRETCH) bd = Math.round(bw / (c.sa * P.MAX_STRETCH));
        let bx = fr.includes("e") && !fr.includes("w") ? lot.x + lot.w - bw : lot.x;
        let by = fr.includes("s") && !fr.includes("n") ? lot.y + lot.d - bd : lot.y;
        const flip = rnd() < 0.5 ? 2 : 0;                                 // 180 deg variety
        const rot = ((c.rotQ + flip) % 4) * 90;
        // neon face: frontage facing the hub cross first (Vine x / 4th y), else first frontage; none for interior lots
        const cx = bx + bw / 2, cy = by + bd / 2, order = [];
        if (cx < HUB.x) order.push("e"); else order.push("w"); if (cy < HUB.y) order.push("s"); else order.push("n");
        order.push("n", "s", "e", "w");
        const face = fr.length ? order.find(f => fr.includes(f)) : null;
        const near = Math.hypot(cx - HUB.x, cy - HUB.y) <= P.NEON_NEAR;
        const T = TYPES[c.id];
        const bld = { block: b.id, type: c.id, x: bx, y: by, w: bw, d: bd, rot, color: T.color, neon: face ? T.neon : null, face,
          neonAlpha: face ? (near ? 1 : 0.6) : 0, core: !!(face && near), hBand: T.hBand };
        buildings.push(bld);
        // ---- rooftop clutter (visual only, no collision)
        const nw = Math.max(6, (face === "e" || face === "w" ? bw : bd) * 0.10);
        const roof = R(bx + 10 + (face === "w" ? nw + 8 : 0), by + 10 + (face === "n" ? nw + 8 : 0),
                       bw - 20 - (face === "e" || face === "w" ? nw + 8 : 0), bd - 20 - (face === "n" || face === "s" ? nw + 8 : 0));
        const n = c.id === "tower" ? 1 : Math.max(1, Math.min(4, Math.floor(bw * bd / 9000)));
        const placed = [];
        for (let k = 0; k < n; k++) for (let tr = 0; tr < 12; tr++) {
          const roll = rnd(); let it;
          const tankOk = c.id !== "tower" && Math.min(roof.w, roof.d) >= 60;
          if (tankOk && roll < 0.22) { const r = 14 + Math.floor(rnd() * 5); it = { kind: "tank", r, w: 2 * r, d: 2 * r }; }
          else if (roll < 0.62) { const v = rnd() < 0.5; it = { kind: "ac", w: v ? 16 : 24, d: v ? 24 : 16 }; }
          else it = { kind: "vent", w: 10, d: 10 };
          if (roof.w < it.w || roof.d < it.d) continue;
          it.x = Math.round(roof.x + rnd() * (roof.w - it.w)); it.y = Math.round(roof.y + rnd() * (roof.d - it.d));
          if (placed.some(p => rr(inflate(p, 6), it))) continue;
          placed.push(it); clutter.push(Object.assign({ block: b.id }, it)); break;
        }
       }
      }
    }
    // ---- parking-stall marks on paved forecourts (flat paint, no collision); never on pads/rings/alley/buildings
    const marks = [], padZones = ex.filter(z => z.plaza || z.dark), solid = buildings.concat(cfg.kitRects || []);
    for (const p of plazaRects) {
      const horiz = p.w >= p.d, long = horiz ? p.w : p.d, short = horiz ? p.d : p.w;
      if (short < 90 || long < 90) continue;
      const L = Math.min(54, short - 16), rows = short >= 140 ? [0, 1] : [0];
      for (const row of rows) for (let t = 12; t + 4 <= long - 12; t += 30) {
        const m = horiz ? R(p.x + t, row ? p.y + p.d - 8 - L : p.y + 8, 4, L) : R(row ? p.x + p.w - 8 - L : p.x + 8, p.y + t, L, 4);
        if (padZones.some(z => hitsZone(m, z)) || solid.some(o => rr(inflate(o, 6), m))) continue;
        marks.push(m); } }
    // ---- streetlights: poles alternate sides every LIGHT_SPACING; pools sit LIGHT_INSET into the asphalt
    const junction = [];
    for (const y of ROADS_EW) for (const x of ROADS_NS) junction.push({ x, y });
    const ac = { x: ALLEY.x + ALLEY.w / 2, y: ALLEY.y + ALLEY.h / 2 };
    const inJunction = (x, y) => ROADS_NS.some(c => Math.abs(x - c) < nsH + 40) && ROADS_EW.some(c => Math.abs(y - c) < ewH + 40);
    const lights = [], poles = [];
    function addLight(px, py, lx, ly) {
      if (Math.hypot(lx - ac.x, ly - ac.y) < P.ALLEY_DARK_R) return;            // underlit escape alley
      if (lx < 0 || ly < 0 || lx > WORLD.w || ly > WORLD.h) return;
      poles.push({ x: px, y: py }); lights.push({ kind: "street", tier: "street", x: lx, y: ly, r: P.LIGHT_R, a: P.LIGHT_A, w: P.WARM_A.street });
    }
    ROADS_EW.forEach((cy, ri) => { for (let k = 0, x = P.LIGHT_SPACING / 2 + ri * 60; x < WORLD.w; x += P.LIGHT_SPACING, k++) {
      if (inJunction(x, cy)) continue; const s = k % 2 ? 1 : -1;
      addLight(x, cy + s * (ewH + P.POLE_INSET), x, cy + s * (ewH - P.LIGHT_INSET)); } });
    ROADS_NS.forEach((cx, ri) => { for (let k = 0, y = P.LIGHT_SPACING / 2 + ri * 60; y < WORLD.h; y += P.LIGHT_SPACING, k++) {
      if (inJunction(cx, y)) continue; const s = k % 2 ? 1 : -1;
      addLight(cx + s * (nsH + P.POLE_INSET), y, cx + s * (nsH - P.LIGHT_INSET), y); } });
    for (const j of junction) {
      const hub = j.x === HUB.x && j.y === HUB.y, nw = j.x === ROADS_NS[0] && j.y === ROADS_EW[0];
      const tier = hub ? "hub" : (nw ? "nw" : "junction");
      lights.push({ kind: "junction", tier, x: j.x, y: j.y, r: P.JUNCTION_R, a: hub ? P.HUB_A : (nw ? P.NW_A : P.JUNCTION_A), w: P.WARM_A[tier] });
    }
    // ---- dark alley court (plazaRects = dropped/shrunk lots, paved so pad blocks don't read bare)
    const courts = ex.filter(z => z.dark).map(z => R(z.x, z.y, z.w, z.d));
    // ---- validation: no building in any exclusion zone or on a road band (incl. sidewalk ring)
    const roadsR = [];
    for (const c of ROADS_EW) roadsR.push(R(0, c - ewH - P.SIDEWALK, WORLD.w, ROAD_EW_H + 2 * P.SIDEWALK));
    for (const c of ROADS_NS) roadsR.push(R(c - nsH - P.SIDEWALK, 0, ROAD_NS_W + 2 * P.SIDEWALK, WORLD.h));
    const bad = buildings.filter(b => !clear(b) || roadsR.some(r => rr(b, r)) || buildings.some(o => o !== b && rr(b, o)));
    if (bad.length) throw new Error("A7 density: " + bad.length + " building(s) violate exclusions");
    return { seed: P.SEED, params: P, blocks, buildings, clutter, lights, poles, plazas: plazaRects, marks, leaves, courts, exclusions: ex,
      stats: { plazas: plazaRects.length, marks: marks.length, buildings: buildings.length, clutter: clutter.length, lights: lights.length, poles: poles.length } };
  }
  const api = { buildDensity, A7, TYPES, TRIM, SPRITE_PX, mulberry32 };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else Object.assign(root, api);
})(typeof window !== "undefined" ? window : globalThis);
