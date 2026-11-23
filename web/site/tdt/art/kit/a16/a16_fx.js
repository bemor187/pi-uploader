/* A16 lighting + weather (Art, 2026-10-21). Load AFTER a14_skin.js (and after the main game script):
 *   <script src="../art/kit/a16/a16_fx.js"></script>
 * Draw-only, a14_skin style: wraps 4 existing globals, no inline edits, no state/RNG/timing writes.
 *   drawCar        -> + headlight cone (screen) + tail glow (lighter) on traffic/cops; hero tail glow
 *   drawHeroCone   -> baked cone sprite (replaces the per-frame radial gradient; brighter, same RGB family)
 *   drawLockBursts -> + pad-capture light pulse (PAD_RGB pad colour), drift tire sparks + skid glow, burnout smoke light
 *                     (world space, under the hero, over smoke/peds/traffic)
 *   drawTeach      -> + weather planes (3 parallax pattern fills) + vignette/grade, screen space, before the teach panel
 *   A14.bakeExtra  -> wet lamp reflections + neon sidewalk spill, painted ONCE into the A14 static cache
 * Flags: ?a16=0 all off · ?weather=0 no weather planes · prefers-reduced-motion: planes static, no drizzle, no sparkle twinkle.
 * Runtime: A16.weather / A16.light / A16.fx booleans; A16.RM. */
(function(){
  const Q = location.search; if (/[?&]a16=0(&|$)/.test(Q)) return; if (/[?&]map=d30(&|$)/.test(Q) && !/[?&]a16=1(&|$)/.test(Q)) return; /* C70 (ADR-0002): d30 = same as ?a16=0 unless ?a16=1 */
  const BASE = "../art/kit/a16/";
  const RM = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);
  const A16 = window.A16 = { ok:false, RM, weather: /[?&]map=d30(&|$)/.test(Q) ? /[?&]weather=1(&|$)/.test(Q) : !/[?&]weather=0(&|$)/.test(Q), /* C68 (ADR-0002): d30 default off unless ?weather=1 */ light:true, fx:true, img:{} };
  const names = ["wx_drizzle","wx_fog","wx_sparkle","lt_vignette","lt_cone","lt_tail","fx_skidglow","fx_tirespark",
                 "fx_padpulse_drift","fx_padpulse_donut","fx_padpulse_burn","fx_smokelight","wet_streak"];
  let left = names.length, PAT = null;
  for (const n of names){ const im = new Image(); im.onload = () => { if (--left === 0){ A16.ok = true; if (window.A14 && A14.cache) A14.cache.invalidate(); } }; im.src = BASE + n + ".png"; A16.img[n] = im; }
  const I = A16.img, now = () => performance.now()/1000;

  // ---------- 1. weather + grade (screen space) ----------
  const PL = [ // far -> near. f = camera-pan factor, v = drift px/s, s = tile scale, a = alpha
    { n:"wx_sparkle", f:0.3, v:[0, 0],    s:1,   a:0.55 },
    { n:"wx_fog",     f:0.6, v:[9, 3],    s:1.5, a:1.0  },
    { n:"wx_drizzle", f:1.1, v:[70, 300], s:1,   a:0.55 } ];
  function planes(ctx){
    if (!PAT){ PAT = PL.map(p => ctx.createPattern(I[p.n], "repeat")); }
    const z = state.camZoom, t = RM ? 0 : now(), M = new DOMMatrix();
    ctx.save(); ctx.setTransform(dpr,0,0,dpr,0,0);
    for (let i = 0; i < PL.length; i++){ const p = PL[i];
      if (RM && p.n === "wx_drizzle") continue;                                    // reduced motion: no falling streaks
      const T = (I[p.n].width) * p.s, ox = (-(state.camX*z*p.f) + p.v[0]*t) % T, oy = (-(state.camY*z*p.f) + p.v[1]*t) % T;
      M.a = M.d = p.s; M.e = ox; M.f = oy; PAT[i].setTransform(M);
      ctx.globalAlpha = p.n === "wx_sparkle" && !RM ? p.a*(0.75 + 0.25*Math.sin(t*1.3)) : p.a;
      ctx.fillStyle = PAT[i]; ctx.fillRect(0, 0, W, H); }
    ctx.restore(); }
  function grade(ctx){ ctx.save(); ctx.setTransform(dpr,0,0,dpr,0,0); ctx.drawImage(I.lt_vignette, -W*0.04, -H*0.04, W*1.08, H*1.08); ctx.restore(); }
  A16.drawWeather = planes; A16.drawGrade = grade;     // exposed for previews / Code tests
  const oTeach = window.drawTeach;
  window.drawTeach = function(){ if (A16.ok){ if (A16.weather) planes(ctx); if (A16.light) grade(ctx); } return oTeach.apply(this, arguments); };

  // ---------- 2. cars: cones + tail glow ----------
  const oCone = window.drawHeroCone;
  window.drawHeroCone = function(L, Wd, px){
    if (!A16.ok || !A16.light) return oCone(L, Wd, px);
    if (state.mode === "end" && !REPLAY.on) return;
    const len = Math.max(2.4*L, 70*px), h = len*0.5;
    ctx.save(); ctx.globalCompositeOperation = "screen"; ctx.globalAlpha = 1; ctx.drawImage(I.lt_cone, 0.40*L, -h/2, len, h); ctx.restore(); };
  const oCar = window.drawCar;
  window.drawCar = function(x,y,a,color,roof,cop,hero,kind){
    oCar(x,y,a,color,roof,cop,hero,kind);
    if (!A16.ok || !A16.light) return;
    const L = hero ? 50 : (cop ? 48 : 45), Wd = L*0.46;
    ctx.save(); ctx.translate(x,y); ctx.rotate(a);
    if (!hero){ ctx.globalCompositeOperation = "screen"; ctx.globalAlpha = 0.55; ctx.drawImage(I.lt_cone, 0.44*L, -L*0.42, L*1.7, L*0.84); }
    ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = hero ? 0.75 : 0.5; const s = hero ? 20 : 15;
    ctx.drawImage(I.lt_tail, -0.5*L - s/2, -0.36*Wd - s/2, s, s); ctx.drawImage(I.lt_tail, -0.5*L - s/2, 0.36*Wd - s/2, s, s);
    if (hero) brakeFlare(L, Wd);
    ctx.restore(); };
  // A16b (A15c ticket): hero brake-light flare, reads window.HERO_BRAKING (Code, render-only). Draw-only: 80 ms attack / 180 ms release
  // envelope on wall-clock (never sim), 2 hot lamp flares + 1 soft red wash on the road behind. 3 drawImage, lighter. ?brake=0 off.
  const BRAKE_ON = !/[?&]brake=0(&|$)/.test(Q); A16.brakeK = 0; let bT = 0;
  function brakeFlare(L, Wd){ if (!BRAKE_ON) return; const now = performance.now(), dt = bT ? Math.min(0.1, (now - bT)/1000) : 0; bT = now;
    const on = !!window.HERO_BRAKING && !(state.mode === "end" && !REPLAY.on), k = A16.brakeK = on ? Math.min(1, A16.brakeK + dt/0.08) : Math.max(0, A16.brakeK - dt/0.18);
    if (k <= 0.01) return; const s = 34*(A16.RM ? 0.8 : 1);
    ctx.globalCompositeOperation = "lighter"; ctx.globalAlpha = k;
    ctx.drawImage(I.lt_tail, -0.5*L - s/2, -0.36*Wd - s/2, s, s); ctx.drawImage(I.lt_tail, -0.5*L - s/2, 0.36*Wd - s/2, s, s);
    ctx.globalCompositeOperation = "screen"; ctx.globalAlpha = 0.6*k; ctx.drawImage(I.lt_tail, -0.5*L - 58, -Wd*0.9, 62, Wd*1.8); }

  // ---------- 3. FX (world space, under the hero) ----------
  const PADK = { drift:"fx_padpulse_drift", donut:"fx_padpulse_donut", burn:"fx_padpulse_burn" }; // PAD_RGB keys only; alley green is never used here
  function fx(){
    const t = now();
    // pad-capture light pulse: same clock + colour as the C42 lock ring, soft screen pool 60 -> 260 wu over 0.6 s
    if (state.mode === "play" && C42.bursts.length){ ctx.save(); ctx.globalCompositeOperation = "lighter";
      for (const b of C42.bursts){ const u = (performance.now() - b.t)/600, k = PADK[b.pad]; if (u < 0 || u > 1 || !k) continue;
        const r = 60 + 200*(1 - Math.pow(1-u, 3)); ctx.globalAlpha = 0.95*(1-u); ctx.drawImage(I[k], car.x - r, car.y - r, 2*r, 2*r); }
      ctx.restore(); }
    // drift: skid glow + tire sparks at the rear wheels (slip from the same formula as update(), read-only)
    const sp = Math.hypot(car.vx, car.vy), lv = car.vx*Math.cos(car.a) + car.vy*Math.sin(car.a);
    const slip = (sp > 40 && lv >= 0) ? Math.abs(angDiff(car.a, Math.atan2(car.vy, car.vx))) : 0;
    const dr = slip > 0.35 && sp > 80 ? Math.min(1, (slip - 0.35)*2.5) : 0;
    if (dr > 0 && (state.mode === "play" || REPLAY.on)){
      const c = Math.cos(car.a), s = Math.sin(car.a), back = Math.atan2(-car.vy, -car.vx), f = Math.floor(t*24) % 4;
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      for (const side of [-1, 1]){ const wx = car.x - c*21 - s*side*11, wy = car.y - s*21 + c*side*11;
        ctx.globalAlpha = 0.55*dr; ctx.drawImage(I.fx_skidglow, wx - 17, wy - 17, 34, 34);
        if (dr > 0.4){ ctx.globalAlpha = Math.min(1, dr*1.2); ctx.save(); ctx.translate(wx, wy); ctx.rotate(back + side*0.25);
          ctx.drawImage(I.fx_tirespark, f*64, 0, 64, 64, -4, -28, 56, 56); ctx.restore(); } }
      ctx.restore(); }
    // burnout smoke light: pad-pink underglow while the pad pulse is live (locked pad -> muted warm, per G6), + red taillight bloom in the smoke
    const bp = state.burnPulse || 0, wl = state.wheelieA || 0;
    if (bp > 0.05 || wl > 0.05){ ctx.save(); ctx.globalCompositeOperation = "screen";
      if (bp > 0.05){ ctx.globalAlpha = (state.didBurn ? 0.18 : 0.45)*bp; const m = 70;
        ctx.drawImage(state.didBurn ? I.fx_skidglow : I.fx_smokelight, BURNOUT.x - m, BURNOUT.y - m, BURNOUT.w + 2*m, BURNOUT.h + 2*m); }
      const c = Math.cos(car.a), s = Math.sin(car.a), r = 46; ctx.globalAlpha = 0.5*Math.max(bp, wl);
      ctx.drawImage(I.lt_tail, car.x - c*30 - r, car.y - s*30 - r, 2*r, 2*r); ctx.restore(); }
  }
  const oLB = window.drawLockBursts;
  window.drawLockBursts = function(){ if (A16.ok && A16.fx) fx(); return oLB.apply(this, arguments); };

  // ---------- 4. baked: wet reflections + neon spill (A14 static cache, once per bake) ----------
  if (window.A14) A14.bakeExtra = function(x){
    if (!A16.ok || !A16.light || typeof DENSITY === "undefined" || !DENSITY) return;
    const v = a7View(), ewH = ROAD_EW_H/2, nsH = ROAD_NS_W/2;
    x.save(); x.beginPath(); for (const cy of ROADS_EW) x.rect(0, cy-ewH, WORLD.w, ROAD_EW_H); for (const cx of ROADS_NS) x.rect(cx-nsH, 0, ROAD_NS_W, WORLD.h); x.clip();
    x.globalCompositeOperation = "screen";
    for (const L of DENSITY.lights){ if (!a7Vis(v, L.x-20, L.y-10, 40, 100)) continue;           // sodium streak below each lamp, on asphalt only
      x.globalAlpha = Math.min(1, 0.55 + (L.w ?? L.a ?? 0.3)); x.drawImage(I.wet_streak, L.x - 9, L.y - 8, 18, 92); }
    x.restore();
    x.save(); x.globalCompositeOperation = "screen";                                             // neon spill: 54 wu from the lit face, density + kit
    const spill = (x0, y0, w, d, face, col, a) => { if (!col || !a7Vis(v, x0-60, y0-60, w+120, d+120)) return; let g;
      if (face === "s"){ g = x.createLinearGradient(0, y0+d, 0, y0+d+54); x.fillStyle = g; addS(g, col, a); x.fillRect(x0, y0+d, w, 54); }
      else if (face === "e"){ g = x.createLinearGradient(x0+w, 0, x0+w+54, 0); addS(g, col, a); x.fillStyle = g; x.fillRect(x0+w, y0, 54, d); }
      else if (face === "n"){ g = x.createLinearGradient(0, y0, 0, y0-54); addS(g, col, a); x.fillStyle = g; x.fillRect(x0, y0-54, w, 54); }
      else if (face === "w"){ g = x.createLinearGradient(x0, 0, x0-54, 0); addS(g, col, a); x.fillStyle = g; x.fillRect(x0-54, y0, 54, d); } };
    const addS = (g, col, a) => { g.addColorStop(0, col + hx(0.30*a)); g.addColorStop(0.5, col + hx(0.10*a)); g.addColorStop(1, col + "00"); };
    const hx = a => Math.round(Math.max(0, Math.min(1, a))*255).toString(16).padStart(2, "0");
    for (const b of DENSITY.buildings) spill(b.x, b.y, b.w, b.d, b.face, b.neon, Math.max(0.6, b.neonAlpha || 0.6));
    if (typeof KIT_ON !== "undefined" && KIT_ON && typeof KIT_BUILDINGS !== "undefined") for (const b of KIT_BUILDINGS){ const r = kitFootprint(b); spill(r.x, r.y, r.w, r.d, "e", b.neon, 1); }
    x.restore(); };
})();
