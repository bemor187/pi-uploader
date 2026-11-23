const {chromium}=require('/tmp/pw/node_modules/playwright-core'); const fs=require('fs'); const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const INIT=fs.readFileSync('/tmp/pw/c38v.js','utf8').match(/const INIT=`([\s\S]*?)`;/)[1];
const CAR=[1300,1300,-0.55];
const CSS = process.argv[2] ? fs.readFileSync(process.argv[2],'utf8') : '';
const tag = process.argv[3] || 'raw';
(async()=>{ const b=await chromium.launch({executablePath:'/usr/bin/google-chrome'}); const out={};
 for(const [vn,vp] of [['land',{width:1280,height:720}],['phone',{width:390,height:844}]]){
  const p=await b.newPage({viewport:vp, deviceScaleFactor: vn==='phone'?2:1}); const errs=[]; p.on('pageerror',e=>errs.push(e.message));
  await p.addInitScript(INIT); await p.goto('http://127.0.0.1:8941/demo/PLAY-THIS.html?hud=a'); await sleep(800);
  await p.evaluate(()=>__step(5)); await p.keyboard.press('Enter'); await p.evaluate(()=>__step(200));
  if(CSS) await p.addStyleTag({content:CSS});
  await p.evaluate(([c])=>{ Object.assign(car,{x:c[0],y:c[1],a:c[2],vx:0,vy:0,speed:0}); state.shake=0; state.camX=c[0]+60; state.camY=c[1]-20; state.camZoom=0.58;
    state.driftTime=4.2; state.score=2365; state.policeBumps=1; state.combo=1.6; state.time=52; if(typeof renderHealth==='function') renderHealth(1,false); },[CAR]);
  await p.evaluate(()=>__step(2)); await p.evaluate(()=>{ state.shake=0; draw(); });
  await sleep(300);
  out[vn]=await p.evaluate(()=>{ const r=s=>{const e=document.querySelector(s); if(!e) return null; const b=e.getBoundingClientRect(); return [b.x,b.y,b.width,b.height].map(Math.round);};
    return {status:r('.a8-status'), strip:r('.a8-objective'), dock:r('.a8-dock'), style:r('.a8-status .pill.gold'), rep:r('#repChip'), hype:r('.a8-status .pill.cyan'), clock:r('.a8-status .pill.hot'), clip:r('.a8-status .pill.clip'), heat:r('.a8-status .heat'), bumps:r('#bumpMeter'), prog:r('.a8-objective .prog'), toast:r('.toast'), gdrift:document.getElementById('gDrift').innerText}; });
  out[vn].errs=errs;
  await p.screenshot({path:`/tmp/a8/huda-${tag}-${vn}.png`}); await p.close(); }
 console.log(JSON.stringify(out,null,0)); await b.close(); })();
