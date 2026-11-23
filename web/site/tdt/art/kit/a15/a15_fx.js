/* A15 fireworks FX helper v2 (A15b: aligned to design/D29_FIREWORKS.md §3 / §7). Art, draw-only: NO game rules.
 * Code owns charges, F key, landing point, colour rules (§7a), Style, heat, scatter, camFlash/shake.
 * Load after a14_skin.js:  <script src="../art/kit/a15/a15_fx.js"></script>
 *   A15.throwShell(x0,y0, x1,y1, color, {alts:[c2,c3], onBurst:s=>{...}})  shell: 0.6 s flight (36 wu arc + shadow) + 0.6 s fizz -> burst
 *       onBurst(s) runs on the burst frame BEFORE drawing: Code may re-pick s.color / s.alts (§7a recheck) and apply scatter/heat/etc.
 *   A15.burst(x, y, color, alts)   glow r260 (0.9 s, squared fade) + shock ring 0->260 in 0.35 s + 40 sparks (60/20/20) + core sprite + smoke
 *   A15.launch(x,y,tx,ty,color)    OPTIONAL vertical rocket trail (A15 v1), then burst; D29 does not use it
 *   A15.update(dt)                 world dt (C53 slow-mo stretches it). Call once per sim step; set A15.auto=false when you do.
 *                                  With A15.auto=true (default) draw() self-times with performance.now (previews/tests).
 *   A15.draw(ctx)                  world space, once per frame. Hook: right before `if(D25_ON) d25DrawPeds(false);`
 *   A15.dropShells()  (endRun: shells vanish, no burst)   A15.clear()  (resetRun)   A15.RM = true (reduced motion: glow+sparks x0.5)
 *   A15c: throwShell opts {flight, fuse, arc} (defaults 0.6 s / 0.6 s fizz after landing / 36 wu).
 *   A15c: A15.T.shellScale (default 1; D29 wants 1.5) scales shell+shadow+fizz.  A15.shellPass=true + A15.drawShells(ctx[, view]) = separate shell pass.
 *   A15.fx                         live list (plain objects) for the replay snapshot, same treatment as state.smoke.
 * Colours: "magenta" | "cyan" | "gold" | "green". Sizes in wu. Own LCG: never touches Math.random or game RNG. */
(function(){
  const B = "../art/kit/a15/", C = ["magenta","cyan","gold","green"], IMG = {}, all = [];
  const add = k => { const im = new Image(); im.src = B + k + "@2x.png"; IMG[k] = im; all.push(im); };
  ["fw_trail","fw_spark","fw_smoke","fw_shell","fw_shell_shadow"].forEach(add); C.forEach(c => { add("fw_burst_"+c); add("fw_glow2_"+c); add("fw_sdot_"+c); });
  const HEX = { magenta:"#F03CF0", cyan:"#3EE0FF", gold:"#FFD15A", green:"#7DFFA8" };
  const T = { flight:0.6, fuse:1.2, arc:36, glowR:260, glowT:0.9, ringR:260, ringT:0.35, sparkN:40, sparkV:[140,260], drag:1.5, sparkLife:[0.9,1.3], sparkWu:6,
              coreWu:96, coreFps:12, smokeN:3, smokeLife:1.6, rise:0.75,
              shellScale:1 };   // A15c: shell + shadow + fizz size multiplier (D29 / C63 ruling 6 wants 1.5)
  let seed = 7; const rnd = () => (seed = (seed*16807) % 2147483647) / 2147483647;
  // A15c: one shell (shadow + body + fizz), world space. T.shellScale scales all three around the ground point.
  function drawShell(ctx, e, z){ const k = T.shellScale || 1, FL = e.flight ?? T.flight, AR = e.arc ?? T.arc, u = Math.min(1, e.age/FL), x = e.x0+(e.x1-e.x0)*u, y = e.y0+(e.y1-e.y0)*u, lift = e.age < FL ? AR*4*u*(1-u) : 0, h = AR ? lift/AR : 0;
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 0.6 - 0.3*h; const ss = (1 - 0.5*h)*k; ctx.drawImage(IMG.fw_shell_shadow, x-5*ss, y-3*ss, 10*ss, 6*ss);
    ctx.globalAlpha = 1; ctx.save(); ctx.translate(x, y - lift); ctx.rotate(e.a + (e.age < FL ? e.age*9 : 0)); const sc = (1 + 0.25*h)*k; ctx.drawImage(IMG.fw_shell, -4*sc, -2.5*sc, 8*sc, 5*sc); ctx.restore();
    if (e.age >= FL){ const f = Math.floor(e.age*30) % 2, s = 2.3/z*1.8*k; ctx.globalCompositeOperation = "lighter"; ctx.drawImage(IMG.fw_spark, f*32, 0, 32, 32, x+3*k-s/2, y-1*k-s/2, s, s); ctx.globalCompositeOperation = "source-over"; } }
  const fx = [], A15 = window.A15 = { T, IMG, HEX, fx, auto:true, RM:false, t:0, shellPass:false,
    ready: () => all.every(i => i.complete && i.naturalWidth),
    throwShell(x0, y0, x1, y1, color, o){ o = o || {}; const fl = o.flight ?? T.flight, s = {k:"shell", x0, y0, x1, y1, color, alts:o.alts||[], onBurst:o.onBurst, a:Math.atan2(y1-y0, x1-x0), age:0,
        flight:fl, fuse:o.fuse ?? (T.fuse - T.flight), arc:o.arc ?? T.arc}; fx.push(s); return s; }, // A15c: optional per-shell flight / fuse (fizz after landing) / arc; burst at flight+fuse (default 0.6+0.6 = D29 1.2 s)
    launch(x, y, tx, ty, color, alts){ fx.push({k:"trail", x, y, tx, ty, color, alts:alts||[], age:0}); },
    burst(x, y, color, alts){ alts = (alts && alts.length) ? alts : [color];
      fx.push({k:"glow", x, y, color, age:0}, {k:"ring", x, y, color, age:0}, {k:"core", x, y, color, age:0});
      for (let i = 0; i < T.sparkN; i++){ const u = i / T.sparkN, col = u < 0.6 ? color : alts[(u < 0.8 ? 0 : 1) % alts.length];
        const a = i * 2.399963 + rnd()*0.25, v = T.sparkV[0] + rnd()*(T.sparkV[1]-T.sparkV[0]);           // golden-angle spread, even ring
        fx.push({k:"spark", x, y, vx:Math.cos(a)*v, vy:Math.sin(a)*v, color:col, life:T.sparkLife[0] + rnd()*(T.sparkLife[1]-T.sparkLife[0]), age:0}); }
      for (let i = 0; i < T.smokeN; i++) fx.push({k:"smoke", x:x+(rnd()-0.5)*40, y:y+(rnd()-0.5)*40, f:i%4, age:0}); },
    // A15c option B: separate shell pass. Set A15.shellPass = true, then draw() skips shells and Code calls drawShells() later
    // (e.g. above the D24 teach overlay). view = {W, H, camX, camY, zoom, dpr} sets the world transform itself (use it from a
    // screen-space pass); omit view when ctx is already in world space. Returns the number of shells drawn.
    drawShells(ctx, view){ if (!A15.ready()) return 0; let n = 0; const z = view ? view.zoom : ((typeof state !== "undefined" && state.camZoom) || 1);
      ctx.save(); if (view){ const d = view.dpr || 1; ctx.setTransform(d*z, 0, 0, d*z, d*(view.W/2 - view.camX*z), d*(view.H/2 - view.camY*z)); }
      for (const e of fx) if (e.k === "shell"){ drawShell(ctx, e, z); n++; }
      ctx.restore(); return n; },
    dropShells(){ for (let i = fx.length-1; i >= 0; i--) if (fx[i].k === "shell" || fx[i].k === "trail") fx.splice(i,1); },
    clear(){ fx.length = 0; },
    update(dt){ A15.t += dt; const dk = Math.exp(-T.drag*dt);
      for (let i = fx.length-1; i >= 0; i--){ const e = fx[i]; e.age += dt;
        if (e.k === "shell"){ if (e.age >= (e.flight ?? T.flight) + (e.fuse ?? (T.fuse - T.flight))){ fx.splice(i,1); if (e.onBurst) e.onBurst(e); A15.burst(e.x1, e.y1, e.color, e.alts); } }
        else if (e.k === "trail"){ if (e.age >= T.rise){ fx.splice(i,1); A15.burst(e.tx, e.ty, e.color, e.alts); } }
        else if (e.k === "spark"){ if (e.age >= e.life){ fx.splice(i,1); continue; } e.x += e.vx*dt; e.y += e.vy*dt; e.vx *= dk; e.vy *= dk; }
        else { const L = e.k === "glow" ? T.glowT : e.k === "ring" ? T.ringT : e.k === "core" ? 8/T.coreFps : T.smokeLife; if (e.age >= L) fx.splice(i,1); } } },
    draw(ctx){ if (!fx.length || !A15.ready()) return;
      if (A15.auto){ const n = performance.now()/1000; A15.update(Math.min(0.05, A15._last ? n - A15._last : 0)); A15._last = n; }
      const rm = A15.RM ? 0.5 : 1, z = (typeof state !== "undefined" && state.camZoom) || 1;
      ctx.save(); ctx.globalCompositeOperation = "lighter";
      for (const e of fx){                                                     // pass 1 (additive): glow, ring, core, sparks, trail
        if (e.k === "glow"){ const u = 1 - e.age/T.glowT, R = T.glowR; ctx.globalAlpha = u*u*rm; ctx.drawImage(IMG["fw_glow2_"+e.color], e.x-R, e.y-R, 2*R, 2*R); }
        else if (e.k === "ring"){ const u = e.age/T.ringT; ctx.globalAlpha = 1 - u; ctx.strokeStyle = HEX[e.color]; ctx.lineWidth = 2/z; ctx.beginPath(); ctx.arc(e.x, e.y, Math.max(1, T.ringR*u), 0, Math.PI*2); ctx.stroke(); }
        else if (e.k === "core"){ const f = Math.min(7, Math.floor(e.age*T.coreFps)), s = T.coreWu; ctx.globalAlpha = 1; ctx.drawImage(IMG["fw_burst_"+e.color], f*384, 0, 384, 384, e.x-s/2, e.y-s/2, s, s); }
        else if (e.k === "spark"){ const s = T.sparkWu; ctx.globalAlpha = (1 - e.age/e.life)*rm; ctx.drawImage(IMG["fw_sdot_"+e.color], e.x-s/2, e.y-s/2, s, s); }
        else if (e.k === "trail"){ const u = e.age/T.rise, q = 1-(1-u)*(1-u), x = e.x+(e.tx-e.x)*q, y = e.y+(e.ty-e.y)*q, f = Math.floor(e.age*24)%6;
          ctx.globalAlpha = 1; ctx.save(); ctx.translate(x,y); ctx.rotate(Math.atan2(e.ty-e.y, e.tx-e.x)+Math.PI/2); ctx.drawImage(IMG.fw_trail, f*48, 0, 48, 192, -6, -6, 12, 48); ctx.restore(); } }
      ctx.globalCompositeOperation = "source-over";
      for (const e of fx){                                                     // pass 2 (normal): smoke, shell shadow + shell + fizz
        if (e.k === "smoke"){ const l = 1 - e.age/T.smokeLife, r = 6 + 12*(1-l); ctx.globalAlpha = l*0.45; ctx.drawImage(IMG.fw_smoke, e.f*128, 0, 128, 128, e.x-r*1.6, e.y-r*1.6, r*3.2, r*3.2); }
        else if (e.k === "shell" && !A15.shellPass) drawShell(ctx, e, z); }
      ctx.restore(); }
  };
})();
