/* pi-web-hub: live dashboard for the Pi cluster.
 * Everything goes through same-origin nginx proxies on the web Pi (/api/...), so there's no CORS
 * and no token ever reaches the browser or this file. nginx injects tokens server-side when
 * /etc/uploader.env has them (see web/nginx-web.conf + scripts/web-hub.sh).
 * Every field is optional: a missing value renders as "—", never throws. */
(() => {
"use strict";
const POLL_MS = 15000;
const HOSTS = [
  { name: "brain",    role: "api + queue",      health: "/api/brain/health",     target: "brain" },
  { name: "tiktok",   role: "tiktok lane",      health: "/api/lane/tiktok/health",  target: "lane:tiktok",  login: "login:tiktok" },
  { name: "insta",    role: "instagram lane",   health: "/api/lane/insta/health",   target: "lane:insta",   login: "login:insta" },
  { name: "clapper",  role: "clapper lane",     health: "/api/lane/clapper/health", target: "lane:clapper", login: "login:clapper" },
  { name: "web",      role: "web hub (you)",    health: "/health",                target: "site:web" },
  { name: "overseer", role: "ai tasker + watch", health: "/api/overseer/health",  target: null },
];
const $ = (s, el = document) => el.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = v => (typeof v === "number" && isFinite(v) ? v : null);
const dash = v => (v === null || v === undefined || v === "" ? "—" : v);
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function get(url, ms = 8000) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), ms);
  try {
    const r = await fetch(url, { signal: ctl.signal, cache: "no-store", headers: { Accept: "application/json" } });
    let data = null; try { data = await r.json(); } catch (_) {}
    if (data && data._hub_down) return { ok: false, status: 0, data: null, err: "unreachable" };
    return { ok: r.ok, status: r.status, data };
  } catch (e) { return { ok: false, status: 0, data: null, err: e.name === "AbortError" ? "timeout" : "unreachable" }; }
  finally { clearTimeout(t); }
}
const ago = ts => {
  const t = num(ts); if (t === null) return "—";
  const s = Math.max(0, Date.now() / 1000 - t);
  if (s < 90) return Math.round(s) + "s ago"; if (s < 5400) return Math.round(s / 60) + "m ago";
  if (s < 172800) return Math.round(s / 3600) + "h ago"; return Math.round(s / 86400) + "d ago";
};
const when = ts => { const t = num(ts); return t === null ? "—" : new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }); };

// "ok (disk 40%, mem 31%, 47.2C, load 0.21)" -> metrics, when /fleet isn't available
function parseOs(detail) {
  const d = String(detail || ""), m = {};
  const g = (re) => { const x = d.match(re); return x ? parseFloat(x[1]) : null; };
  m.disk_pct = g(/disk (\d+(?:\.\d+)?)%/); m.mem_pct = g(/mem(?:ory)? (\d+(?:\.\d+)?)%/);
  m.temp_c = g(/(\d+(?:\.\d+)?)C\b/); m.load1 = g(/load (\d+(?:\.\d+)?)/);
  return m;
}

const state = { config: {}, health: {}, overseer: null, fleet: null, jobs: null, jobsErr: null, fleetErr: null, last: null };

async function poll() {
  const [cfg, ov, ...hs] = await Promise.all([get("/hub/config.json"), get("/api/overseer/health"), ...HOSTS.map(h => get(h.health))]);
  state.config = (cfg.ok && cfg.data) || {};
  state.overseer = ov.ok ? ov.data : null;
  HOSTS.forEach((h, i) => { state.health[h.name] = hs[i]; });
  const [fl, jb] = await Promise.all([
    state.config.overseer_token ? get("/api/overseer/fleet") : Promise.resolve(null),
    state.config.brain_token ? get("/api/brain/jobs?limit=200") : Promise.resolve(null),
  ]);
  state.fleet = fl && fl.ok && fl.data && typeof fl.data === "object" ? fl.data : null;
  state.fleetErr = !state.config.overseer_token ? "no TASK_TOKEN on web" : (fl && !fl.ok ? `HTTP ${fl.status || fl.err}` : null);
  state.jobs = jb && jb.ok && Array.isArray(jb.data) ? jb.data : null;
  state.jobsErr = !state.config.brain_token ? "no API_TOKEN on web" : (jb && !jb.ok ? `HTTP ${jb.status || jb.err}` : null);
  state.last = Date.now();
  render();
}

function hostView(h) {
  const r = state.health[h.name] || {};
  const tg = (state.overseer && state.overseer.targets) || {};
  const t = h.target ? tg[h.target] : null;
  let status = r.ok ? "up" : (r.status === 0 && t && t.ok === true ? "up" : "down");
  let why = r.ok ? "health ok" : (r.err ? r.err : `HTTP ${r.status}`);
  if (!r.ok && t && t.ok === true) why += " from web; overseer sees it up";
  if (r.ok && h.name === "brain" && r.data && r.data.brain !== "ok") status = "warn";
  if (r.ok && r.data && r.data.busy) why = "busy (posting)";
  const f = (state.fleet && state.fleet[h.name]) || null;
  const osT = tg["os:" + h.name];
  const m = f ? f : parseOs(osT && osT.detail);
  const problems = (f && Array.isArray(f.problems) && f.problems) || (osT && osT.ok === false ? [osT.detail] : []);
  if (status === "up" && problems.length) status = "warn";
  const lg = h.login ? tg[h.login] : null;
  const ssh = (f && f.ssh) || (tg["ssh:" + h.name] && tg["ssh:" + h.name].detail) || null;
  return { status, why, m, problems, lg, ssh, units: f && f.units, uptime: f && f.uptime_h, checked: (f && f.checked) || (osT && osT.checked) };
}

function bar(label, v, unit, hiAt) {
  const n = num(v); const w = n === null ? 0 : Math.min(100, unit === "C" ? n : n);
  return `<div class="bar"><span>${label}</span><span class="t"><i class="${n !== null && n >= hiAt ? "hi" : ""}" style="width:${w}%"></i></span><span>${n === null ? "—" : n + (unit === "C" ? "°C" : "%")}</span></div>`;
}

function renderHosts(el) {
  el.innerHTML = HOSTS.map(h => {
    const v = hostView(h);
    const login = v.lg ? `<div class="kv">login: <b style="color:${v.lg.ok ? "var(--lime)" : "var(--hot)"}">${esc(v.lg.ok ? (v.lg.detail || "ok") : (v.lg.detail || "not logged in"))}</b></div>` : (h.login ? `<div class="kv">login: <b>— (overseer hasn't checked yet)</b></div>` : "");
    const units = v.units ? `<div class="kv">units: ${Object.entries(v.units).map(([u, s]) => `<b style="color:${s === "active" ? "var(--lime)" : "var(--hot)"}">${esc(u)}</b>`).join(" ")}</div>` : "";
    return `<article class="panel host ${v.status}">
      <div class="hd"><div><div class="name">${esc(h.name)}</div><div class="role">${esc(h.role)}</div></div>
      <span class="chip ${v.status}"><span class="dot"></span>${v.status.toUpperCase()}</span></div>
      <div class="bars">${bar("temp", v.m.temp_c, "C", 75)}${bar("disk", v.m.disk_pct, "%", 85)}${bar("mem", v.m.mem_pct, "%", 90)}</div>
      <div class="kv">link: <b>${esc(v.why)}</b>${v.uptime != null ? ` · up <b>${esc(v.uptime)}h</b>` : ""}${num(v.m.load1) !== null ? ` · load <b>${v.m.load1}</b>` : ""}</div>
      ${login}${units}
      ${v.problems.length ? `<div class="note bad">${v.problems.map(esc).join("<br>")}</div>` : ""}
      <div class="kv">metrics: <b>${v.checked ? ago(v.checked) : "—"}</b></div>
    </article>`;
  }).join("");
}

function renderChips(el) {
  el.innerHTML = HOSTS.map(h => { const v = hostView(h); return `<span class="chip ${v.status}"><span class="dot"></span>${esc(h.name)}</span>`; }).join("");
}

function authNotes(el) {
  const c = state.config, out = [];
  if (!c || c.brain_token === undefined) out.push(`<div class="note">hub config not found (/hub/config.json). Showing unauthenticated /health only.</div>`);
  else {
    if (!c.brain_token) out.push(`<div class="note">Upload queue locked: add brain's <b>API_TOKEN</b> to /etc/uploader.env on web, then <b>sudo ~/pi-uploader/scripts/update.sh</b>. Showing /health only.</div>`);
    if (!c.overseer_token) out.push(`<div class="note">Fleet metrics limited: add overseer's <b>TASK_TOKEN</b> to /etc/uploader.env on web for /fleet. Using overseer /health summaries.</div>`);
  }
  if (!state.overseer) out.push(`<div class="note bad">overseer /health unreachable, so login status and per-host metrics are unknown.</div>`);
  el.innerHTML = out.join("");
}

function renderTargets(el) {
  const tg = (state.overseer && state.overseer.targets) || null;
  if (!tg) { el.innerHTML = `<p class="muted">overseer offline.</p>`; return; }
  const rows = Object.entries(tg).filter(([k]) => /^(agent|backup|site|lane|login|brain)/.test(k));
  el.innerHTML = `<div class="strip">${rows.map(([k, v]) => `<span class="chip ${v && v.ok === true ? "up" : v && v.ok === false ? "down" : "unk"}" title="${esc(v && v.detail)}"><span class="dot"></span>${esc(k)}</span>`).join("") || '<span class="muted">no targets yet</span>'}</div>
    <div class="kv">alerts: <b>${state.overseer.alerts ? "ntfy on" : "log only"}</b> · agents: <b>${esc((state.overseer.agents || []).join(", ") || "—")}</b> · down: <b style="color:${(state.overseer.down || []).length ? "var(--hot)" : "var(--lime)"}">${esc((state.overseer.down || []).join(", ") || "none")}</b></div>`;
}

let filter = "all";
function renderJobs(el, statsEl, limit) {
  if (!state.jobs) {
    statsEl && (statsEl.innerHTML = "");
    el.innerHTML = `<div class="note">${state.jobsErr ? "Queue unavailable: " + esc(state.jobsErr) : "loading…"}. brain /jobs needs its API_TOKEN, which nginx on web injects when it's in /etc/uploader.env.</div>`;
    return;
  }
  const jobs = state.jobs.filter(j => j && typeof j === "object");
  const count = s => jobs.filter(j => j.status === s).length;
  if (statsEl) statsEl.innerHTML = ["queued", "running", "done", "failed"].map(s => `<div class="panel stat"><div class="n st-${s}" style="color:${{ queued: "var(--cyan)", running: "var(--gold)", done: "var(--lime)", failed: "var(--hot)" }[s]}">${count(s)}</div><div class="l">${s}</div></div>`).join("");
  const shown = jobs.filter(j => filter === "all" || j.status === filter || j.platform === filter).slice(0, limit || 200);
  el.innerHTML = shown.length ? `<table class="jobs"><thead><tr><th>job</th><th>lane</th><th>status</th><th>caption</th><th>detail</th><th>tries</th><th>updated</th></tr></thead><tbody>${shown.map(j => `<tr>
    <td>${esc(dash(j.id))}</td><td>${esc(dash(j.platform))}</td><td><span class="st ${esc(j.status)}">${esc(dash(j.status))}</span></td>
    <td class="detail">${esc(String(j.caption || "").slice(0, 80)) || "—"}</td><td class="detail">${esc(dash(j.detail))}</td><td>${esc(dash(j.attempts))}</td><td title="${esc(when(j.updated))}">${ago(j.updated || j.created)}</td></tr>`).join("")}</tbody></table>`
    : `<p class="muted">no jobs match.</p>`;
}

async function renderHive(el) {
  const r = await get("/hub/hive.json");
  if (!r.ok || !r.data) { el.innerHTML = `<div class="note">Hive brain feed not configured. Put a read-only token in /etc/uploader.env on web as <b>HIVE_TOKEN</b> (or a deploy key at /etc/web-hub/hive_deploy_key), then run update.sh.</div>`; return; }
  const d = r.data, list = (xs, n = 8) => Array.isArray(xs) && xs.length ? `<ul>${xs.slice(0, n).map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<p class="muted">none</p>`;
  const projects = Array.isArray(d.projects) ? d.projects : [];
  el.innerHTML = `<div class="hive">
    <div class="panel pad"><h4>Active now</h4>${list(d.active)}</div>
    <div class="panel pad"><h4>Needs Brian</h4>${list(d.needs_brian)}</div>
    <div class="panel pad"><h4>Projects</h4>${projects.length ? `<ul>${projects.slice(0, 16).map(p => `<li><b>${esc(p.name)}</b>${p.status ? ` <span class="muted">· ${esc(p.status)}</span>` : ""}</li>`).join("")}</ul>` : '<p class="muted">none</p>'}</div>
  </div><div class="kv">hive-brain ${esc(d.commit || "")} · rendered ${esc(d.rendered_at || "—")}</div>`;
}

// terminal readout on the landing page
function termLines() {
  const L = [];
  L.push(`<span class="m">$</span> <span class="c">pi-grid</span> --status`);
  HOSTS.forEach(h => { const v = hostView(h); L.push(`  ${h.name.padEnd(9)} <span class="${v.status === "up" ? "" : v.status === "warn" ? "g" : "h"}">[${v.status.toUpperCase().padEnd(4)}]</span> ${num(v.m.temp_c) !== null ? v.m.temp_c + "°C" : "  —  "}  ${esc(v.why)}`); });
  if (state.jobs) { const f = state.jobs.filter(j => j.status === "failed").length, q = state.jobs.filter(j => j.status === "queued" || j.status === "running").length; L.push(`  queue     ${q} in flight · <span class="${f ? "h" : ""}">${f} failed</span>`); }
  else L.push(`  queue     <span class="g">locked (${esc(state.jobsErr || "no token")})</span>`);
  return L;
}
let typed = false;
function renderTerm(el) {
  const lines = termLines();
  if (typed || reduced) { el.innerHTML = lines.join("\n") + '\n<span class="cursor"></span>'; return; }
  typed = true; let i = 0;
  const step = () => { el.innerHTML = lines.slice(0, ++i).join("\n") + '\n<span class="cursor"></span>'; if (i < lines.length) setTimeout(step, 140); };
  step();
}

function render() {
  const page = document.body.dataset.page;
  const hosts = $("#hosts"), chips = $("#chips"), term = $("#term"), notes = $("#notes"), targets = $("#targets"), jobs = $("#jobs"), stats = $("#stats");
  hosts && renderHosts(hosts); chips && renderChips(chips); term && renderTerm(term); notes && authNotes(notes); targets && renderTargets(targets);
  jobs && renderJobs(jobs, stats, page === "home" ? 6 : 200);
  const ls = $("#last"); ls && (ls.textContent = "sync " + new Date(state.last).toLocaleTimeString());
}

function clock() { const c = $("#clock"); if (c) c.textContent = new Date().toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }); }

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".filters button").forEach(b => b.addEventListener("click", () => {
    filter = b.dataset.f; document.querySelectorAll(".filters button").forEach(x => x.classList.toggle("on", x === b)); render();
  }));
  clock(); setInterval(clock, 1000);
  const hive = $("#hive"); hive && renderHive(hive);
  poll(); setInterval(() => { if (!document.hidden) poll(); }, POLL_MS);
});
})();
