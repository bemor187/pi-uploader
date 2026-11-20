"""insta lane: posts a Reel through instagram.com with headless Chromium.

Selectors drift when Instagram changes its site. On failure a screenshot is
saved to ~/uploader-work/debug/<job>.png.
"""
import asyncio
import os
import re
import time
from pathlib import Path

from lanes.common.browser import add_login_routes, browser_page, dismiss_popups, try_click, type_caption
from lanes.common.lane import DEBUG_DIR, LaneError, create_app

HOME = "https://www.instagram.com/"
SHARE_TIMEOUT = int(os.environ.get("PROCESS_TIMEOUT", "900"))
KEEP_ORIGINAL_CROP = os.environ.get("INSTA_ORIGINAL_CROP", "1") == "1"


async def _logged_in(page) -> bool:
    if "/accounts/login" in page.url:
        return False
    if await page.locator('input[name="username"]').count():
        return False
    return await page.locator('svg[aria-label="New post"], svg[aria-label="Create"]').count() > 0


def _dialog(page):
    return page.locator('div[role="dialog"]').last


async def _next(page):
    btn = _dialog(page).get_by_role("button", name="Next", exact=True)
    await btn.first.wait_for(state="visible", timeout=60_000)
    await btn.first.click()
    await asyncio.sleep(1.5)


async def upload(video: Path, caption: str, job_id: str) -> dict:
    async with browser_page("insta") as page:
        try:
            await page.goto(HOME, wait_until="domcontentloaded")
            await asyncio.sleep(5)
            await dismiss_popups(page)  # "Turn on notifications? -> Not Now", "Save login info?"
            if not await _logged_in(page):
                raise LaneError("not logged in to Instagram; open http://insta:8100/login?token=LANE_TOKEN to log in")

            await page.locator('svg[aria-label="New post"], svg[aria-label="Create"]').first.click()
            # Newer UI shows a small menu: Post / Live video / Ad
            await try_click(page, page.locator('svg[aria-label="Post"]'), 3000) or \
                await try_click(page, page.get_by_role("link", name="Post", exact=True), 1500)

            file_input = page.locator('div[role="dialog"] input[type="file"], form[enctype] input[type="file"]')
            await file_input.first.wait_for(state="attached", timeout=30_000)
            await file_input.first.set_input_files(str(video))

            # "Video posts are now shared as reels" notice
            await try_click(page, page.get_by_role("button", name="OK", exact=True), 6000)

            if KEEP_ORIGINAL_CROP:
                if await try_click(page, page.locator('svg[aria-label="Select crop"]'), 8000):
                    await try_click(page, page.get_by_text("Original", exact=True), 3000)

            await _next(page)  # crop -> edit
            await _next(page)  # edit -> caption

            box = page.locator('div[aria-label^="Write a caption"][contenteditable="true"]')
            await box.first.wait_for(state="visible", timeout=30_000)
            await box.first.click()
            await type_caption(page, caption)

            await _dialog(page).get_by_role("button", name="Share", exact=True).first.click()

            done = page.get_by_text(re.compile(r"(reel|post) has been shared", re.I))
            done_img = page.locator('img[alt="Animated checkmark"]')
            err = page.get_by_text(re.compile(r"(couldn.t be shared|something went wrong)", re.I))
            deadline = time.monotonic() + SHARE_TIMEOUT
            while time.monotonic() < deadline:
                if await done.count() or await done_img.count():
                    return {"detail": "posted to Instagram"}
                if await err.count():
                    raise LaneError("Instagram reported the post could not be shared")
                await asyncio.sleep(3)
            raise LaneError("clicked Share but never saw Instagram's confirmation; check the account")
        except Exception:
            try:
                await page.screenshot(path=str(DEBUG_DIR / f"{job_id}.png"), full_page=True)
            except Exception:
                pass
            raise


async def check() -> dict:
    async with browser_page("insta") as page:
        await page.goto(HOME, wait_until="domcontentloaded")
        await asyncio.sleep(6)
        await dismiss_popups(page)
        shot = DEBUG_DIR / "insta-check.png"
        await page.screenshot(path=str(shot))
        return {"logged_in": await _logged_in(page), "url": page.url, "screenshot": str(shot)}


app = create_app("insta", upload, check)
add_login_routes(app, "insta", "https://www.instagram.com/accounts/login/")
