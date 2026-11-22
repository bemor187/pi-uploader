"""overseer: always-on AI tasker + cluster monitor.

POST /task      {"prompt": "...", "system"?: "...", "agent"?: "msi", "model"?: "..."}
                Routed through AGENTS in order (MSI -> MacBook -> local); first that answers wins.
GET  /tasks     recent tasks
GET  /digest    plain-English cluster summary written by the local model
GET  /health    overseer ok + latest monitor snapshot (no auth)
GET  /          phone-friendly status page (no auth, read-only)

Monitor (every MONITOR_INTERVAL s): every agent's Ollama, brain, each lane, and the other
hosts in SITES (web). Sends an ntfy
alert (ALERT_URL) on down/up transitions and on each newly failed upload job.
Auto-retry: a failed job is retried via brain /retry at most ONCE, and only when brain's
detail starts with "lane unreachable:" -- brain sets that only on connect errors, i.e. the
lane never received the video, so it cannot have been posted.

Auth for /task, /tasks, /digest: "Authorization: Bearer $TASK_TOKEN" or ?token=$TASK_TOKEN.
"""
import asyncio
import html
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

log = logging.getLogger("overseer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATA = Path(os.environ.get("OVERSEER_DATA", "/var/lib/overseer"))
DB_PATH = DATA / "overseer.db"
TASK_TOKEN = os.environ.get("TASK_TOKEN", "")
API_TOKEN = os.environ.get("API_TOKEN", "")  # brain's token, for /jobs and /retry
BRAIN_URL = os.environ.get("BRAIN_URL", "http://brain").rstrip("/")
ALERT_URL = os.environ.get("ALERT_URL", "").strip()
INTERVAL = float(os.environ.get("MONITOR_INTERVAL", "60"))
DOWN_AFTER = int(os.environ.get("DOWN_AFTER", "2"))  # consecutive failures before "down"
TASK_TIMEOUT = float(os.environ.get("TASK_TIMEOUT", "600"))
DIGEST_AGENT = os.environ.get("DIGEST_AGENT", "local")
DEFAULT_AGENTS = (
    "msi=ollama:http://msi:11434|qwen3:14b,"
    "macbook=ollama:http://macbook:11434,"
    "local=ollama:http://127.0.0.1:11434|qwen2.5:1.5b"
)
LANES = {
    "tiktok": os.environ.get("LANE_TIKTOK", "http://tiktok:8100"),
    "insta": os.environ.get("LANE_INSTA", "http://insta:8100"),
    "clapper": os.environ.get("LANE_CLAPPER", "http://clapper:8100"),
}
# Other hosts in the stack: name=URL,...  Any HTTP status below 400 counts as up.
DEFAULT_SITES = "web=http://web/health"
SITES = {
    n.strip(): u.strip()
    for n, _, u in (s.partition("=") for s in os.environ.get("SITES", DEFAULT_SITES).split(",") if "=" in s)
    if n.strip() and u.strip()
}
RETRYABLE_PREFIX = "lane unreachable:"
# backups other Pis send here (scripts/backup.sh + backup-receiver.sh)
BACKUP_ROOT = Path(os.environ.get("BACKUP_ROOT", "/var/backups/pi-stack"))
BACKUP_MAX_AGE = float(os.environ.get("BACKUP_MAX_AGE_H", "36")) * 3600


def parse_agents(spec: str) -> list:
    """name=ollama:URL[|model],...  (order = routing priority)"""
    agents = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        name, _, rest = item.partition("=")
        kind, _, target = rest.partition(":")
        url, _, model = target.partition("|")
        if not name or kind != "ollama" or not url:
            log.warning("ignoring bad AGENTS entry %r", item)
            continue
        agents.append({"name": name.strip(), "url": url.strip().rstrip("/"),
                       "model": model.strip() or None})
    return agents


AGENTS = parse_agents(os.environ.get("AGENTS", DEFAULT_AGENTS))

# name -> {"ok": bool|None, "fails": int, "detail": str, "since": ts, "checked": ts, ...}
STATE: dict = {}


# ---------------------------------------------------------------- database
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, prompt TEXT,
                agent TEXT, model TEXT, status TEXT, response TEXT, ms INTEGER, tried TEXT);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, target TEXT, msg TEXT);
            -- one row per (job, failure) we've alerted on; updated distinguishes re-failures
            CREATE TABLE IF NOT EXISTS seen_failures (
                job_id TEXT, updated REAL, PRIMARY KEY (job_id, updated));
            -- a job id appears here at most once: the single auto-retry
            CREATE TABLE IF NOT EXISTS retries (job_id TEXT PRIMARY KEY, ts REAL, result TEXT);
            CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
            """
        )


def q(sql: str, args: tuple = ()) -> list:
    with db() as con:
        return [dict(r) for r in con.execute(sql, args).fetchall()]


def add_event(kind: str, target: str, msg: str):
    with db() as con:
        con.execute("INSERT INTO events (ts, kind, target, msg) VALUES (?,?,?,?)",
                    (time.time(), kind, target, msg[:2000]))
        con.execute("DELETE FROM events WHERE id < (SELECT MAX(id) - 2000 FROM events)")


# ---------------------------------------------------------------- alerts
async def alert(title: str, msg: str, priority: str = "default", tags: str = ""):
    log.warning("ALERT %s: %s", title, msg)
    await asyncio.to_thread(add_event, "alert", title, msg)
    if not ALERT_URL:
        return
    headers = {"Title": title.encode("ascii", "replace").decode(), "Priority": priority}
    if tags:
        headers["Tags"] = tags
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(ALERT_URL, content=msg.encode(), headers=headers)
    except Exception as e:
        log.warning("alert delivery failed: %s", e)


# ---------------------------------------------------------------- monitor
async def probe(c: httpx.AsyncClient, url: str, headers: Optional[dict] = None):
    try:
        r = await c.get(url, headers=headers or {})
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", None
        try:
            return True, "ok", r.json()
        except ValueError:
            return True, "ok", None
    except Exception as e:
        return False, f"unreachable: {type(e).__name__}", None


async def record(name: str, ok: bool, detail: str, extra: Optional[dict] = None):
    now = time.time()
    s = STATE.setdefault(name, {"ok": None, "fails": 0, "since": now})
    s.update(checked=now, detail=detail, **(extra or {}))
    if ok:
        s["fails"] = 0
        if s["ok"] is False:
            await alert(f"UP: {name}", f"{name} is back ({detail})", "default", "white_check_mark")
        if s["ok"] is not True:
            s["since"] = now
        s["ok"] = True
    else:
        s["fails"] += 1
        if s["fails"] >= DOWN_AFTER and s["ok"] is not False:
            s["ok"], s["since"] = False, now
            await alert(f"DOWN: {name}", f"{name} is down: {detail}", "high", "rotating_light")


async def check_failed_jobs(c: httpx.AsyncClient):
    if not API_TOKEN:
        return
    try:
        r = await c.get(f"{BRAIN_URL}/jobs?limit=200",
                        headers={"Authorization": f"Bearer {API_TOKEN}"})
        r.raise_for_status()
        jobs = r.json()
    except Exception as e:
        log.info("could not read brain /jobs: %s", e)
        return
    failed = [j for j in jobs if j.get("status") == "failed"]
    first_run = not q("SELECT v FROM meta WHERE k='jobs_baselined'")
    for j in failed:
        jid, upd = j["id"], j.get("updated") or 0
        if q("SELECT 1 FROM seen_failures WHERE job_id=? AND updated=?", (jid, upd)):
            continue
        with db() as con:
            con.execute("INSERT OR IGNORE INTO seen_failures VALUES (?,?)", (jid, upd))
        if first_run:
            continue  # failures from before overseer existed: record, don't alert or retry
        detail = (j.get("detail") or "")[:300]
        retried = bool(q("SELECT 1 FROM retries WHERE job_id=?", (jid,)))
        if detail.startswith(RETRYABLE_PREFIX) and not retried:
            try:
                rr = await c.post(f"{BRAIN_URL}/retry/{jid}",
                                  headers={"Authorization": f"Bearer {API_TOKEN}"})
                result = f"HTTP {rr.status_code}"
            except Exception as e:
                result = f"error {type(e).__name__}"
            with db() as con:
                con.execute("INSERT OR IGNORE INTO retries VALUES (?,?,?)",
                            (jid, time.time(), result))
            await alert(f"Upload failed: {j['platform']} {jid}",
                        f"{detail}\nLane never received it, so it was not posted. "
                        f"Auto-retried once ({result}).", "default", "repeat")
        else:
            why = "already auto-retried once" if retried else "may have posted; check the platform"
            await alert(f"Upload failed: {j['platform']} {jid}",
                        f"{detail}\nNot auto-retried ({why}). Manual: POST {BRAIN_URL}/retry/{jid}",
                        "high", "warning")
    if first_run:
        with db() as con:
            con.execute("INSERT OR REPLACE INTO meta VALUES ('jobs_baselined', ?)",
                        (str(time.time()),))


def latest_backups() -> dict:
    """host -> {"file", "mtime", "bytes"} for the newest backup received from each Pi."""
    out = {}
    try:
        hosts = [d for d in BACKUP_ROOT.iterdir() if d.is_dir() and d.name != "incoming"]
    except OSError:
        return out
    for d in hosts:
        try:
            files = sorted(d.glob("*.tgz"), key=lambda f: f.stat().st_mtime)
        except OSError:
            continue
        if files:
            st = files[-1].stat()
            out[d.name] = {"file": files[-1].name, "mtime": st.st_mtime, "bytes": st.st_size}
    return out


async def check_backups():
    for host, b in (await asyncio.to_thread(latest_backups)).items():
        age = time.time() - b["mtime"]
        await record(f"backup:{host}", age < BACKUP_MAX_AGE,
                     f"{b['file']} ({age / 3600:.0f}h old)" if age >= BACKUP_MAX_AGE
                     else f"ok ({age / 3600:.0f}h old)")


async def monitor_once():
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as c:
        async def agent(a):
            ok, detail, js = await probe(c, f"{a['url']}/api/tags")
            models = [m.get("name") for m in (js or {}).get("models", [])] if ok else None
            if ok and a["model"] and models is not None and a["model"] not in models:
                detail = f"ok, but model {a['model']} not pulled"
            await record(f"agent:{a['name']}", ok, detail,
                         {"models": models} if models is not None else None)

        async def lane(name, base):
            ok, detail, js = await probe(c, f"{base.rstrip('/')}/health")
            if ok and isinstance(js, dict) and js.get("busy"):
                detail = "ok (busy)"
            await record(f"lane:{name}", ok, detail)

        async def brain():
            ok, detail, _ = await probe(c, f"{BRAIN_URL}/health")
            await record("brain", ok, detail)

        async def site(name, url):
            try:
                r = await c.get(url)
                ok, detail = r.status_code < 400, f"HTTP {r.status_code}"
                if ok:
                    detail = "ok" if r.status_code == 200 else f"ok ({r.status_code})"
            except Exception as e:
                ok, detail = False, f"unreachable: {type(e).__name__}"
            await record(f"site:{name}", ok, detail)

        await asyncio.gather(*(agent(a) for a in AGENTS), brain(),
                             *(lane(n, u) for n, u in LANES.items()),
                             *(site(n, u) for n, u in SITES.items()))
        await check_failed_jobs(c)
    await check_backups()


async def monitor_loop():
    while True:
        try:
            await monitor_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("monitor pass crashed; continuing")
        await asyncio.sleep(INTERVAL)


# ---------------------------------------------------------------- task routing
def pick_model(a: dict, requested: Optional[str]) -> Optional[str]:
    if requested:
        return requested
    if a["model"]:
        return a["model"]
    models = STATE.get(f"agent:{a['name']}", {}).get("models") or []
    return models[0] if models else None


async def ask(a: dict, model: str, prompt: str, system: str = "", timeout: float = TASK_TIMEOUT):
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=5)) as c:
        r = await c.post(f"{a['url']}/api/chat",
                         json={"model": model, "messages": msgs, "stream": False})
        r.raise_for_status()
        return r.json()["message"]["content"]


class Task(BaseModel):
    prompt: str
    system: str = ""
    agent: Optional[str] = None   # pin to one agent
    model: Optional[str] = None   # only honoured together with agent


def auth(authorization: str = Header(default=""), token: str = ""):
    if not TASK_TOKEN:
        raise HTTPException(503, "TASK_TOKEN not configured")
    if authorization != f"Bearer {TASK_TOKEN}" and token != TASK_TOKEN:
        raise HTTPException(401, "bad or missing token")


# ---------------------------------------------------------------- app
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("agents (priority order): %s", [a["name"] for a in AGENTS])
    t = asyncio.create_task(monitor_loop())
    yield
    t.cancel()


app = FastAPI(title="overseer", lifespan=lifespan)


@app.post("/task", dependencies=[Depends(auth)])
async def task(t: Task):
    if t.agent:
        order = [a for a in AGENTS if a["name"] == t.agent]
        if not order:
            raise HTTPException(400, f"agent must be one of {[a['name'] for a in AGENTS]}")
    else:
        # skip agents the monitor already knows are down, but always keep the last (local)
        order = [a for i, a in enumerate(AGENTS)
                 if i == len(AGENTS) - 1 or STATE.get(f"agent:{a['name']}", {}).get("ok") is not False]
    tried, start = [], time.monotonic()
    for a in order:
        model = pick_model(a, t.model if t.agent else None)
        if not model:
            tried.append(f"{a['name']}: no model known")
            continue
        try:
            out = await ask(a, model, t.prompt, t.system)
        except Exception as e:
            tried.append(f"{a['name']}: {type(e).__name__}")
            log.info("task via %s failed: %s", a["name"], e)
            continue
        ms = int((time.monotonic() - start) * 1000)
        await asyncio.to_thread(_save_task, t.prompt, a["name"], model, "done", out, ms, tried)
        return {"agent": a["name"], "model": model, "response": out, "ms": ms, "tried": tried}
    await asyncio.to_thread(_save_task, t.prompt, None, None, "failed", "", 0, tried)
    raise HTTPException(503, {"error": "no agent could answer", "tried": tried})


def _save_task(prompt, agent, model, status, response, ms, tried):
    with db() as con:
        con.execute(
            "INSERT INTO tasks (created, prompt, agent, model, status, response, ms, tried) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), prompt[:4000], agent, model, status, response[:20000], ms,
             json.dumps(tried)))


@app.get("/tasks", dependencies=[Depends(auth)])
async def tasks(limit: int = 20):
    return await asyncio.to_thread(
        q, "SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (min(limit, 200),))


def snapshot() -> dict:
    return {k: {kk: v.get(kk) for kk in ("ok", "detail", "since", "checked", "models")}
            for k, v in sorted(STATE.items())}


@app.get("/backups")
async def backups():
    """newest backup per Pi (names and dates only, never contents)"""
    return await asyncio.to_thread(latest_backups)


@app.get("/health")
async def health():
    down = [k for k, v in STATE.items() if v.get("ok") is False]
    return {"overseer": "ok", "down": down, "alerts": bool(ALERT_URL),
            "agents": [a["name"] for a in AGENTS], "targets": snapshot()}


@app.get("/digest", dependencies=[Depends(auth)])
async def digest():
    events = await asyncio.to_thread(
        q, "SELECT ts, target, msg FROM events WHERE ts > ? ORDER BY id", (time.time() - 86400,))
    facts = {
        "now": time.strftime("%Y-%m-%d %H:%M"),
        "targets": {k: {"ok": v.get("ok"), "detail": v.get("detail"),
                        "since": time.strftime("%H:%M", time.localtime(v.get("since", 0)))}
                    for k, v in STATE.items()},
        "alerts_last_24h": [f"{time.strftime('%H:%M', time.localtime(e['ts']))} {e['target']}: "
                            f"{e['msg'][:200]}" for e in events[-40:]],
    }
    prompt = ("Summarize this home-cluster status for a phone notification. 3-6 short plain-English "
              "sentences: what is down right now, what failed recently, what needs a human. "
              "No markdown.\n\n" + json.dumps(facts, indent=1))
    a = next((x for x in AGENTS if x["name"] == DIGEST_AGENT), AGENTS[-1] if AGENTS else None)
    model = pick_model(a, None) if a else None
    if not model:
        return {"digest": None, "error": "no local model configured", "facts": facts}
    try:
        text = await ask(a, model, prompt, timeout=300)
    except Exception as e:
        return {"digest": None, "error": f"{a['name']}: {type(e).__name__}", "facts": facts}
    return {"digest": text.strip(), "agent": a["name"], "model": model}


@app.get("/", response_class=HTMLResponse)
async def page():
    def ago(ts):
        if not ts:
            return "-"
        s = int(time.time() - ts)
        return f"{s}s" if s < 120 else f"{s // 60}m" if s < 7200 else f"{s // 3600}h"

    rows = []
    for k, v in sorted(STATE.items()):
        color = {True: "#2a2", False: "#d33"}.get(v.get("ok"), "#999")
        label = {True: "UP", False: "DOWN"}.get(v.get("ok"), "…")
        rows.append(f"<tr><td><b style='color:{color}'>{label}</b></td><td>{html.escape(k)}</td>"
                    f"<td>{html.escape(str(v.get('detail', '')))}</td><td>{ago(v.get('since'))}</td></tr>")
    events = await asyncio.to_thread(
        q, "SELECT ts, target, msg FROM events ORDER BY id DESC LIMIT 15")
    ev = "".join(f"<li><small>{time.strftime('%m-%d %H:%M', time.localtime(e['ts']))}</small> "
                 f"<b>{html.escape(e['target'])}</b><br>{html.escape(e['msg'])}</li>" for e in events)
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<meta http-equiv=refresh content=30><title>overseer</title>
<style>body{{font:15px system-ui;margin:16px;max-width:720px}}table{{border-collapse:collapse;width:100%}}
td{{padding:6px 4px;border-bottom:1px solid #8883;vertical-align:top}}li{{margin:8px 0}}
@media(prefers-color-scheme:dark){{body{{background:#111;color:#ddd}}}}</style></head><body>
<h2>overseer</h2><p><small>alerts: {'on' if ALERT_URL else 'OFF (set ALERT_URL)'} ·
checks every {int(INTERVAL)}s · digest: <code>/digest?token=…</code></small></p>
<table>{''.join(rows) or '<tr><td>first check pending…</td></tr>'}</table>
<h3>Recent alerts</h3><ul>{ev or '<li>none</li>'}</ul></body></html>"""
