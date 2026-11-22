"""brain: central upload API + SQLite job queue + per-platform dispatcher.

POST /upload        multipart: file, caption, platform ("tiktok", "insta", "clapper",
                    or a comma list like "tiktok,insta"), optional callback_url
GET  /status/{id}   job status
GET  /jobs          recent jobs
POST /retry/{id}    re-queue a failed job (media is kept on failure)
GET  /health        brain + lane/Postiz reachability

Routing: platforms listed in POSTIZ_PLATFORMS (default "tiktok,insta") are posted through
the Postiz public API on the postiz Pi; everything else goes to its lane Pi (clapper).
Set POSTIZ_PLATFORMS="" to send everything to the lanes again.

Postiz jobs go queued -> running -> submitted (Postiz accepted the post) -> done/failed.
A reconciler polls Postiz's post list (POSTIZ_POLL seconds, default 300: that endpoint
allows 30 calls/hour) and flips submitted jobs to done (with the post URL) or failed.
"""
import asyncio
import datetime as dt
import logging
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

log = logging.getLogger("brain")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

DATA = Path(os.environ.get("BRAIN_DATA", "/var/lib/uploader"))
DB_PATH = DATA / "jobs.db"
MEDIA = DATA / "media"
API_TOKEN = os.environ.get("API_TOKEN", "")
LANE_TOKEN = os.environ.get("LANE_TOKEN", "")
LANE_TIMEOUT = float(os.environ.get("LANE_TIMEOUT", "1800"))
MAX_CONNECT_ATTEMPTS = int(os.environ.get("MAX_CONNECT_ATTEMPTS", "5"))
PLATFORMS = ("tiktok", "insta", "clapper")
LANES = {
    "tiktok": os.environ.get("LANE_TIKTOK", "http://tiktok:8100"),
    "insta": os.environ.get("LANE_INSTA", "http://insta:8100"),
    "clapper": os.environ.get("LANE_CLAPPER", "http://clapper:8100"),
}
ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".webm"}

# ---- Postiz
POSTIZ_PLATFORMS = {p.strip().lower() for p in
                    os.environ.get("POSTIZ_PLATFORMS", "tiktok,insta").split(",") if p.strip()}
POSTIZ_API = os.environ.get("POSTIZ_API", "http://postiz/api/public/v1").rstrip("/")
POSTIZ_API_KEY = os.environ.get("POSTIZ_API_KEY", "")
POSTIZ_IDS = {  # integration (channel) ids; empty = look up by provider on first use
    "tiktok": os.environ.get("POSTIZ_TIKTOK_ID", ""),
    "insta": os.environ.get("POSTIZ_INSTA_ID", ""),
}
POSTIZ_PROVIDERS = {"tiktok": ("tiktok", "tiktok-business"),
                    "insta": ("instagram", "instagram-standalone")}
POSTIZ_POLL = float(os.environ.get("POSTIZ_POLL", "300"))
POSTIZ_GIVE_UP = float(os.environ.get("POSTIZ_GIVE_UP", str(6 * 3600)))
TIKTOK_PRIVACY = os.environ.get("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE")
TIKTOK_POSTING = os.environ.get("TIKTOK_POSTING", "DIRECT_POST")  # or UPLOAD (inbox draft)
POSTIZ_EXT = {".mp4"}  # Postiz only accepts video/mp4
_identifiers: dict = {}  # integration id -> provider identifier (from /integrations)


def route(platform: str) -> str:
    return "postiz" if platform in POSTIZ_PLATFORMS else "lane"


# ---------------------------------------------------------------- database
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    MEDIA.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, platform TEXT NOT NULL, caption TEXT,
                media_path TEXT, callback_url TEXT,
                status TEXT NOT NULL,          -- queued|running|done|failed
                attempts INTEGER DEFAULT 0, not_before REAL DEFAULT 0,
                detail TEXT, created REAL, updated REAL)"""
        )
        cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
        if "postiz_post_id" not in cols:
            con.execute("ALTER TABLE jobs ADD COLUMN postiz_post_id TEXT")
        # A job that was 'running' when brain died may or may not have posted.
        # Never auto-repost: mark it failed so a human can check and /retry.
        con.execute(
            "UPDATE jobs SET status='failed', detail='interrupted by brain restart; "
            "check the platform before retrying', updated=? WHERE status='running'",
            (time.time(),),
        )


def row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d.pop("media_path", None)
    return d


def claim_next(platform: str):
    con = db()
    try:
        con.execute("BEGIN IMMEDIATE")
        r = con.execute(
            "SELECT * FROM jobs WHERE platform=? AND status='queued' AND not_before<=? "
            "ORDER BY created LIMIT 1",
            (platform, time.time()),
        ).fetchone()
        if r:
            con.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1, updated=? WHERE id=?",
                (time.time(), r["id"]),
            )
        con.execute("COMMIT")
        return dict(r) if r else None
    finally:
        con.close()


def set_status(job_id: str, status: str, detail: str = "", not_before: float = 0):
    with db() as con:
        con.execute(
            "UPDATE jobs SET status=?, detail=?, not_before=?, updated=? WHERE id=?",
            (status, detail[:4000], not_before, time.time(), job_id),
        )


def get_job(job_id: str):
    with db() as con:
        return con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


# ---------------------------------------------------------------- dispatcher
async def notify(job_id: str):
    r = await asyncio.to_thread(get_job, job_id)
    if not r or not r["callback_url"]:
        return
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(r["callback_url"], json=row_to_dict(r))
    except Exception as e:  # webhook failures never affect the job
        log.warning("webhook for %s failed: %s", job_id, e)


async def run_job(job: dict):
    if route(job["platform"]) == "postiz":
        return await run_postiz_job(job)
    jid, platform = job["id"], job["platform"]
    media = Path(job["media_path"])
    if not media.exists():
        await asyncio.to_thread(set_status, jid, "failed", "media file missing")
        return
    url = LANES[platform].rstrip("/") + "/run"
    headers = {"Authorization": f"Bearer {LANE_TOKEN}"} if LANE_TOKEN else {}
    log.info("dispatching %s -> %s", jid, url)
    try:
        timeout = httpx.Timeout(LANE_TIMEOUT, connect=15)
        async with httpx.AsyncClient(timeout=timeout) as c:
            with media.open("rb") as fh:
                resp = await c.post(
                    url,
                    headers=headers,
                    data={"job_id": jid, "caption": job["caption"] or ""},
                    files={"file": (media.name, fh, "video/mp4")},
                )
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        # Lane never received the job: safe to retry with backoff.
        if job["attempts"] < MAX_CONNECT_ATTEMPTS:
            delay = min(600, 30 * 2 ** (job["attempts"] - 1))
            await asyncio.to_thread(
                set_status, jid, "queued", f"lane unreachable ({e}); retry in {delay}s",
                time.time() + delay,
            )
            return
        await asyncio.to_thread(set_status, jid, "failed", f"lane unreachable: {e}")
        await notify(jid)
        return
    except httpx.HTTPError as e:
        # Upload may have happened (e.g. read timeout). Do not auto-retry.
        await asyncio.to_thread(
            set_status, jid, "failed", f"lane error after send ({type(e).__name__}: {e}); "
            "check the platform before retrying",
        )
        await notify(jid)
        return

    if resp.status_code == 409:  # lane busy (shouldn't happen with one worker per lane)
        await asyncio.to_thread(set_status, jid, "queued", "lane busy", time.time() + 30)
        return
    if resp.status_code == 200:
        await asyncio.to_thread(set_status, jid, "done", resp.text)
        media.unlink(missing_ok=True)
    else:
        await asyncio.to_thread(set_status, jid, "failed", f"HTTP {resp.status_code}: {resp.text}")
    await notify(jid)


# ---------------------------------------------------------------- Postiz
def _pz_headers() -> dict:
    return {"Authorization": POSTIZ_API_KEY}


async def postiz_integration(c: httpx.AsyncClient, platform: str) -> tuple:
    """(integration id, provider identifier) for a platform."""
    iid = POSTIZ_IDS.get(platform) or ""
    if iid and iid in _identifiers:
        return iid, _identifiers[iid]
    r = await c.get(f"{POSTIZ_API}/integrations", headers=_pz_headers())  # 30/hour: cached
    r.raise_for_status()
    for it in r.json():
        _identifiers[it["id"]] = it.get("identifier", "")
    if iid:
        if iid not in _identifiers:
            raise ValueError(f"Postiz has no channel with id {iid} (POSTIZ_{platform.upper()}_ID)")
        return iid, _identifiers[iid]
    matches = [it for it in r.json() if it.get("identifier") in POSTIZ_PROVIDERS[platform]
               and not it.get("disabled")]
    if not matches:
        raise ValueError(f"no {platform} channel connected in Postiz")
    if len(matches) > 1:
        raise ValueError(f"several {platform} channels in Postiz; set POSTIZ_{platform.upper()}_ID "
                         f"to one of {[m['id'] + ' (' + str(m.get('name')) + ')' for m in matches]}")
    POSTIZ_IDS[platform] = matches[0]["id"]
    return matches[0]["id"], matches[0]["identifier"]


def postiz_settings(platform: str, identifier: str) -> dict:
    if platform == "tiktok":
        return {"__type": identifier or "tiktok", "title": "", "privacy_level": TIKTOK_PRIVACY,
                "duet": False, "stitch": False, "comment": True, "autoAddMusic": "no",
                "brand_content_toggle": False, "brand_organic_toggle": False,
                "video_made_with_ai": False, "content_posting_method": TIKTOK_POSTING}
    return {"__type": identifier or "instagram", "post_type": "post",
            "is_trial_reel": False, "collaborators": []}


async def _requeue_or_fail(job: dict, why: str):
    """Nothing was posted (Postiz unreachable / rate-limited): retry with backoff."""
    jid = job["id"]
    if job["attempts"] < MAX_CONNECT_ATTEMPTS:
        delay = min(600, 30 * 2 ** (job["attempts"] - 1))
        await asyncio.to_thread(set_status, jid, "queued", f"{why}; retry in {delay}s",
                                time.time() + delay)
        return
    # same prefix as the lanes so overseer's once-only safe auto-retry applies
    await asyncio.to_thread(set_status, jid, "failed", f"lane unreachable: postiz: {why}")
    await notify(jid)


async def run_postiz_job(job: dict):
    jid, platform = job["id"], job["platform"]
    media = Path(job["media_path"])
    if not media.exists():
        await asyncio.to_thread(set_status, jid, "failed", "media file missing")
        return
    if not POSTIZ_API_KEY:
        await asyncio.to_thread(set_status, jid, "failed", "POSTIZ_API_KEY not set on brain")
        return
    timeout = httpx.Timeout(LANE_TIMEOUT, connect=15)
    async with httpx.AsyncClient(timeout=timeout) as c:
        # 1. channel + media upload: nothing is posted yet, so any failure here is safe to retry
        try:
            iid, identifier = await postiz_integration(c, platform)
            with media.open("rb") as fh:
                up = await c.post(f"{POSTIZ_API}/upload", headers=_pz_headers(),
                                  files={"file": (media.name, fh, "video/mp4")})
            if up.status_code == 429:
                return await _requeue_or_fail(job, "postiz rate limit on upload")
            up.raise_for_status()
            m = up.json()
        except ValueError as e:  # config problem: a retry won't help until it's fixed
            await asyncio.to_thread(set_status, jid, "failed", f"postiz: {e}")
            await notify(jid)
            return
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                return await _requeue_or_fail(job, f"postiz HTTP {e.response.status_code}")
            await asyncio.to_thread(set_status, jid, "failed",
                                    f"postiz HTTP {e.response.status_code}: {e.response.text[:500]}")
            await notify(jid)
            return
        except httpx.HTTPError as e:
            return await _requeue_or_fail(job, f"postiz unreachable ({type(e).__name__})")

        # 2. create the post: past this point a lost reply may still mean it posted
        body = {
            "type": "now",
            "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "shortLink": False,
            "tags": [],
            "posts": [{
                "integration": {"id": iid},
                "value": [{"content": job["caption"] or "",
                           "image": [{"id": m["id"], "path": m["path"]}]}],
                "settings": postiz_settings(platform, identifier),
            }],
        }
        try:
            r = await c.post(f"{POSTIZ_API}/posts", headers=_pz_headers(), json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            return await _requeue_or_fail(job, f"postiz unreachable ({type(e).__name__})")
        except httpx.HTTPError as e:
            await asyncio.to_thread(set_status, jid, "failed",
                                    f"postiz error after send ({type(e).__name__}); "
                                    "check Postiz before retrying")
            await notify(jid)
            return
    if r.status_code == 429:
        return await _requeue_or_fail(job, "postiz rate limit (API_LIMIT) on create")
    if r.status_code != 200 and r.status_code != 201:
        why = f"postiz HTTP {r.status_code}: {r.text[:500]}"
        if r.status_code >= 500:
            why += "; check Postiz before retrying"
        await asyncio.to_thread(set_status, jid, "failed", why)
        await notify(jid)
        return
    try:
        res = r.json()
        post_id = (res[0] if isinstance(res, list) else res).get("postId")
    except Exception:
        post_id = None
    with db() as con:
        con.execute("UPDATE jobs SET status='submitted', postiz_post_id=?, detail=?, updated=? "
                    "WHERE id=?", (post_id, f"handed to Postiz (post {post_id}); publishing",
                                   time.time(), jid))
    if not post_id:  # can't track it; treat acceptance as done
        await asyncio.to_thread(set_status, jid, "done", "accepted by Postiz (no post id returned)")
        media.unlink(missing_ok=True)
        await notify(jid)


async def postiz_reconcile_once():
    with db() as con:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM jobs WHERE status='submitted' AND postiz_post_id IS NOT NULL")]
    if not rows:
        return
    start = min(r["created"] for r in rows) - 3600
    fmt = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{POSTIZ_API}/posts", headers=_pz_headers(),
                        params={"startDate": fmt(start), "endDate": fmt(time.time() + 86400)})
        r.raise_for_status()
        data = r.json()
    posts = {p["id"]: p for p in (data.get("posts", []) if isinstance(data, dict) else data)}
    for j in rows:
        p = posts.get(j["postiz_post_id"])
        state = (p or {}).get("state")
        if state == "PUBLISHED":
            await asyncio.to_thread(set_status, j["id"], "done",
                                    f"published: {p.get('releaseURL') or '(no URL)'}")
            Path(j["media_path"]).unlink(missing_ok=True)
        elif state == "ERROR":
            await asyncio.to_thread(set_status, j["id"], "failed",
                                    f"postiz: platform rejected it: {p.get('error') or 'no message'}")
        elif time.time() - j["created"] > POSTIZ_GIVE_UP:
            await asyncio.to_thread(set_status, j["id"], "failed",
                                    f"postiz: still {state or 'missing'} after "
                                    f"{int(POSTIZ_GIVE_UP // 3600)}h; check Postiz before retrying")
        else:
            continue
        await notify(j["id"])


async def postiz_reconciler():
    while True:
        try:
            await postiz_reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("postiz reconcile failed: %s", e)
        await asyncio.sleep(POSTIZ_POLL)


async def lane_worker(platform: str):
    while True:
        try:
            job = await asyncio.to_thread(claim_next, platform)
            if job:
                await run_job(job)
            else:
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("worker %s crashed; continuing", platform)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("routing: %s", {p: route(p) for p in PLATFORMS})
    tasks = [asyncio.create_task(lane_worker(p)) for p in PLATFORMS]
    if POSTIZ_PLATFORMS:
        tasks.append(asyncio.create_task(postiz_reconciler()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="brain uploader", lifespan=lifespan)


def auth(authorization: str = Header(default="")):
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(401, "bad or missing token")


# ---------------------------------------------------------------- endpoints
@app.post("/upload", dependencies=[Depends(auth)])
async def upload(
    file: UploadFile = File(...),
    caption: str = Form(""),
    platform: str = Form(...),
    callback_url: str = Form(""),
):
    platforms = [p.strip().lower() for p in platform.split(",") if p.strip()]
    bad = [p for p in platforms if p not in PLATFORMS]
    if not platforms or bad:
        raise HTTPException(400, f"platform must be one or more of {list(PLATFORMS)}")
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"unsupported file type {ext}")
    via_postiz = [p for p in platforms if route(p) == "postiz"]
    if via_postiz and ext not in POSTIZ_EXT:
        raise HTTPException(400, f"{', '.join(via_postiz)} go through Postiz, which only takes .mp4")

    tmp = MEDIA / f"incoming-{uuid.uuid4().hex}{ext}"
    with tmp.open("wb") as out:
        while chunk := await file.read(1 << 20):
            out.write(chunk)
    if tmp.stat().st_size == 0:
        tmp.unlink()
        raise HTTPException(400, "empty file")

    now, ids = time.time(), []
    with db() as con:
        for p in platforms:
            jid = uuid.uuid4().hex[:12]
            dest = MEDIA / f"{jid}{ext}"
            shutil.copyfile(tmp, dest)
            con.execute(
                "INSERT INTO jobs (id, platform, caption, media_path, callback_url, status, "
                "created, updated) VALUES (?,?,?,?,?, 'queued', ?, ?)",
                (jid, p, caption, str(dest), callback_url or None, now, now),
            )
            ids.append({"job_id": jid, "platform": p})
    tmp.unlink()
    out = {"jobs": ids}
    if len(ids) == 1:
        out["job_id"] = ids[0]["job_id"]
    return out


@app.get("/status/{job_id}", dependencies=[Depends(auth)])
async def status(job_id: str):
    r = await asyncio.to_thread(get_job, job_id)
    if not r:
        raise HTTPException(404, "no such job")
    return row_to_dict(r)


@app.get("/jobs", dependencies=[Depends(auth)])
async def jobs(limit: int = 50):
    with db() as con:
        rows = con.execute(
            "SELECT * FROM jobs ORDER BY created DESC LIMIT ?", (min(limit, 500),)
        ).fetchall()
    return [row_to_dict(r) for r in rows]


@app.post("/retry/{job_id}", dependencies=[Depends(auth)])
async def retry(job_id: str):
    r = await asyncio.to_thread(get_job, job_id)
    if not r:
        raise HTTPException(404, "no such job")
    if r["status"] != "failed":
        raise HTTPException(409, f"job is {r['status']}, only failed jobs can be retried")
    if not Path(r["media_path"]).exists():
        raise HTTPException(410, "media no longer on disk; re-upload instead")
    with db() as con:
        con.execute(
            "UPDATE jobs SET status='queued', attempts=0, not_before=0, detail='manual retry', "
            "postiz_post_id=NULL, updated=? WHERE id=?",
            (time.time(), job_id),
        )
    return {"job_id": job_id, "status": "queued"}


@app.get("/health")
async def health():
    out = {"brain": "ok", "routes": {p: route(p) for p in PLATFORMS}, "lanes": {}}
    async with httpx.AsyncClient(timeout=5) as c:
        if POSTIZ_PLATFORMS:
            base = POSTIZ_API.split("/api/")[0]
            try:
                r = await c.get(base + "/")
                out["postiz"] = "ok" if r.status_code < 400 else f"HTTP {r.status_code}"
            except Exception as e:
                out["postiz"] = f"unreachable: {type(e).__name__}"
            if not POSTIZ_API_KEY:
                out["postiz"] += " (POSTIZ_API_KEY not set)"
        for name, base in LANES.items():
            if route(name) != "lane":
                continue
            try:
                r = await c.get(base.rstrip("/") + "/health")
                out["lanes"][name] = r.json() if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception as e:
                out["lanes"][name] = f"unreachable: {type(e).__name__}"
    return out
