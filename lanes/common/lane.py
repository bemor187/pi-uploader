"""Shared FastAPI receiver used by every lane.

A lane module provides:  async def upload(video: Path, caption: str, job_id: str) -> dict
and optionally:          async def check() -> dict   (login / device check)
"""
import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Awaitable, Callable, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

LANE_TOKEN = os.environ.get("LANE_TOKEN", "")
WORK = Path(os.environ.get("LANE_WORK", str(Path.home() / "uploader-work")))
DEBUG_DIR = WORK / "debug"


class LaneError(Exception):
    """Raised by a lane with a human-readable reason."""


def create_app(
    name: str,
    upload_fn: Callable[[Path, str, str], Awaitable[dict]],
    check_fn: Optional[Callable[[], Awaitable[dict]]] = None,
) -> FastAPI:
    WORK.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger(name)
    app = FastAPI(title=f"{name} lane")
    lock = asyncio.Lock()  # one upload at a time (one browser / one phone)
    app.state.lock = lock

    def auth(authorization: str = Header(default=""), token: str = ""):
        # header for scripts; ?token= so /check works from a phone browser
        if LANE_TOKEN and authorization != f"Bearer {LANE_TOKEN}" and token != LANE_TOKEN:
            raise HTTPException(401, "bad or missing token")

    @app.post("/run", dependencies=[Depends(auth)])
    async def run(job_id: str = Form(...), caption: str = Form(""), file: UploadFile = File(...)):
        if lock.locked():
            raise HTTPException(409, "busy")
        async with lock:
            ext = Path(file.filename or "v.mp4").suffix or ".mp4"
            safe_id = "".join(ch for ch in job_id if ch.isalnum() or ch in "-_")[:40] or "job"
            video = WORK / f"{safe_id}{ext}"
            with video.open("wb") as out:
                shutil.copyfileobj(file.file, out, 1 << 20)
            log.info("job %s: %d bytes, caption %d chars", safe_id, video.stat().st_size, len(caption))
            try:
                result = await upload_fn(video, caption, safe_id)
            except LaneError as e:
                log.error("job %s failed: %s", safe_id, e)
                raise HTTPException(500, str(e))
            except Exception as e:
                log.exception("job %s crashed", safe_id)
                raise HTTPException(500, f"{type(e).__name__}: {e}")
            finally:
                video.unlink(missing_ok=True)
        log.info("job %s done: %s", safe_id, result)
        return {"ok": True, "lane": name, **(result or {})}

    @app.get("/health")
    async def health():
        return {"lane": name, "busy": lock.locked()}

    if check_fn:
        @app.get("/check", dependencies=[Depends(auth)])
        async def check():
            if lock.locked():
                raise HTTPException(409, "busy")
            async with lock:
                return await check_fn()

    return app
