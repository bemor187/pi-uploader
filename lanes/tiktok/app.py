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
VISIBILITY = os.environ.get("TIKTOK_VISIBILITY", "")  # "", "Everyone", "Friends", "Only you" ("Only me" also accepted)
_VIS_NAMES = {"only you": ("Only you", "Only me"), "only me": ("Only you", "Only me")}
_VIS_LABEL = re.compile(r"^\s*Who can (see this post|watch this video)\s*$")
_VIS_VALUES = re.compile(r"^\s*(Everyone|Friends|Only you|Only me)\s*$")


async def _logged_in(page) -> bool:
    if "login" in page.url:
        return False
    return await page.locator('input[type="file"]').count() > 0


async def _click_through_tours(page, target, tries: int = 6):
    """Click target, clearing onboarding tours (react-joyride 'Got it' overlays) that pop up late."""
    for i in range(tries):
        await dismiss_popups(page)
        await try_click(page, page.locator(".react-joyride__tooltip button"), 800)
        try:
            await target.click(timeout=5_000)
            return
        except Exception:
            if i == tries - 1:
                raise
            await page.keyboard.press("Escape")
            await asyncio.sleep(1)


async def _set_visibility(page, want: str):
    """Pick who can see the post and confirm it took; raise (so nothing posts) if it can't be confirmed."""
    names = _VIS_NAMES.get(want.strip().lower(), (want.strip(),))
    label = page.get_by_text(_VIS_LABEL).first
    try:
        await label.wait_for(state="visible", timeout=15_000)
    except Exception:
        raise LaneError("can't find TikTok's 'Who can see this post' setting; not posting (visibility unconfirmed)")
    await label.scroll_into_view_if_needed()
    # the nearest ancestor that also holds the current value is the setting's container
    box = label.locator("xpath=ancestor::*[.//*[normalize-space(text())='Everyone' or normalize-space(text())='Friends'"
                        " or normalize-space(text())='Only you' or normalize-space(text())='Only me']][1]")

    async def current() -> str:
        vals = [t.strip() for t in await box.get_by_text(_VIS_VALUES).all_inner_texts()]
        return vals[0] if vals else ""

    if await current() in names:
        return
    await box.get_by_text(_VIS_VALUES).first.click(timeout=5_000)
    await asyncio.sleep(1)
    for n in names:
        opt = page.get_by_text(n, exact=True)
        if await opt.count():
            await opt.last.click(timeout=5_000)
            break
    await asyncio.sleep(1)
    got = await current()
    if got not in names:
        raise LaneError(f"TikTok visibility shows {got!r}, wanted {want!r}; not posting")


async def _ensure_caption(page, editor, caption: str):
    """Make sure the description holds the caption (TikTok can refill it with the filename late)."""
    first = next((ln.strip() for ln in caption.splitlines() if ln.strip()), "")
    if not first:
        return
    for _ in range(3):
        text = (await editor.inner_text()).strip()
        if first[:40] in text:
            return
        await _click_through_tours(page, editor)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await type_caption(page, caption)
        await page.keyboard.press("Escape")
        await asyncio.sleep(1)
    raise LaneError("caption didn't stick in TikTok's description box; not posting")


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
            await _click_through_tours(page, editor)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")  # TikTok prefills the filename
            await type_caption(page, caption)
            await page.keyboard.press("Escape")  # close any hashtag/mention suggestion box

            if VISIBILITY:
                await _set_visibility(page, VISIBILITY)

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

            # last look before posting: caption still there, visibility still right
            await _ensure_caption(page, editor, caption)
            if VISIBILITY:
                await _set_visibility(page, VISIBILITY)
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
