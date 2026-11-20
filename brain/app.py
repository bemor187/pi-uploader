"""brain: central upload API + SQLite job queue + per-lane dispatcher.

POST /upload        multipart: file, caption, platform ("tiktok", "insta", "clapper",
                    or a comma list like "tiktok,insta"), optional callback_url
GET  /status/{id}   job status
GET  /jobs          recent jobs
POST /retry/{id}    re-queue a failed job (media is kept on failure)
GET  /health        brain + lane reachability
"""
import asyncio
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
LANES = {
    "tiktok": os.environ.get("LANE_TIKTOK", "http://tiktok:8100"),
    "insta": os.environ.get("LANE_INSTA", "http://insta:8100"),
    "clapper": os.environ.get("LANE_CLAPPER", "http://clapper:8100"),
}
ALLOWED_EXT = {".mp4", ".mov", ".m4v", ".webm"}


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
    tasks = [asyncio.create_task(lane_worker(p)) for p in LANES]
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
    bad = [p for p in platforms if p not in LANES]
    if not platforms or bad:
        raise HTTPException(400, f"platform must be one or more of {sorted(LANES)}")
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"unsupported file type {ext}")

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
            "updated=? WHERE id=?",
            (time.time(), job_id),
        )
    return {"job_id": job_id, "status": "queued"}


@app.get("/health")
async def health():
    out = {"brain": "ok", "lanes": {}}
    async with httpx.AsyncClient(timeout=5) as c:
        for name, base in LANES.items():
            try:
                r = await c.get(base.rstrip("/") + "/health")
                out["lanes"][name] = r.json() if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception as e:
                out["lanes"][name] = f"unreachable: {type(e).__name__}"
    return out
