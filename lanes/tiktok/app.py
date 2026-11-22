"""tiktok lane: uploads through TikTok Studio web with headless Chromium.

Selectors drift when TikTok changes its site. On failure a screenshot is
saved to ~/uploader-work/debug/<job>.png. Start there when a step breaks.
"""
import asyncio
import os
import re
import time
from pathlib import Path

from lanes.common.browser import add_login_routes, browser_page, dismiss_popups, try_click, type_caption
from lanes.common.lane import DEBUG_DIR, LaneError, create_app

UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload?from=upload"
PROCESS_TIMEOUT = int(os.environ.get("PROCESS_TIMEOUT", "900"))  # seconds for upload+processing
VISIBILITY = os.environ.get("TIKTOK_VISIBILITY", "")  # "", "Everyone", "Friends", "Only you"


async def _logged_in(page) -> bool:
    if "login" in page.url:
        return False
    return await page.locator('input[type="file"]').count() > 0


async def upload(video: Path, caption: str, job_id: str) -> dict:
    async with browser_page("tiktok") as page:
        try:
            await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            try:
                await page.locator('input[type="file"]').first.wait_for(state="attached", timeout=45_000)
            except Exception:
                pass
            if not await _logged_in(page):
                raise LaneError("not logged in to TikTok; open http://tiktok:8100/login?token=LANE_TOKEN to log in")

            await page.locator('input[type="file"]').first.set_input_files(str(video))

            # Caption editor (DraftJS contenteditable) appears once the file is accepted.
            editor = page.locator('div[contenteditable="true"]').first
            await editor.wait_for(state="visible", timeout=180_000)
            await dismiss_popups(page)
            await editor.click()
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")  # TikTok prefills the filename
            await type_caption(page, caption)
            await page.keyboard.press("Escape")  # close any hashtag/mention suggestion box

            if VISIBILITY:
                await try_click(page, page.get_by_text("Who can watch this video").locator(".."), 2000)
                await try_click(page, page.get_by_text(VISIBILITY, exact=True), 2000)

            post = page.locator('button[data-e2e="post_video_button"]')
            if await post.count() == 0:
                post = page.get_by_role("button", name=re.compile(r"^\s*Post\s*$"))

            # The Post button stays disabled until the upload/processing finishes.
            deadline = time.monotonic() + PROCESS_TIMEOUT
            while True:
                await dismiss_popups(page)
                btn = post.first
                if await btn.is_visible() and await btn.is_enabled() and \
                        (await btn.get_attribute("aria-disabled")) != "true" and \
                        (await btn.get_attribute("data-disabled")) != "true":
                    break
                if time.monotonic() > deadline:
                    raise LaneError("timed out waiting for TikTok to finish processing the video")
                await asyncio.sleep(3)

            await btn.click()
            # Optional "Continue to post?" / content-check dialog.
            await try_click(page, page.get_by_role("button", name=re.compile(r"Post now", re.I)), 5000)

            # Success = redirect to content manager or a confirmation message.
            ok_text = page.get_by_text(re.compile(r"(video has been (uploaded|posted)|Manage your posts)", re.I))
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if "/tiktokstudio/content" in page.url or await ok_text.count() > 0:
                    return {"detail": "posted to TikTok", "url": page.url}
                await asyncio.sleep(2)
            raise LaneError("clicked Post but never saw TikTok's confirmation; check the account")
        except Exception:
            try:
                await page.screenshot(path=str(DEBUG_DIR / f"{job_id}.png"), full_page=True)
            except Exception:
                pass
            raise


async def check() -> dict:
    async with browser_page("tiktok") as page:
        await page.goto(UPLOAD_URL, wait_until="domcontentloaded")
        # Studio's upload area can take well over 8s to render on a Pi; wait like upload() does.
        try:
            await page.locator('input[type="file"]').first.wait_for(state="attached", timeout=45_000)
        except Exception:
            await asyncio.sleep(2)
        shot = DEBUG_DIR / "tiktok-check.png"
        await page.screenshot(path=str(shot))
        return {"logged_in": await _logged_in(page), "url": page.url, "screenshot": str(shot)}


app = create_app("tiktok", upload, check)
add_login_routes(app, "tiktok", "https://www.tiktok.com/login")
