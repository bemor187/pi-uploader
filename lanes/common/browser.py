"""Low-memory persistent Chromium for the Playwright lanes (Pi 4, 4 GB).

The browser is launched per job and closed afterwards, so at most one session
is ever alive and RAM is free between jobs. The persistent profile directory
keeps cookies across jobs and reboots.

Logging in (no other computer needed): open http://<lane>:8100/login?token=LANE_TOKEN
from any device on the tailnet (e.g. your phone). The lane starts a real Chromium
window on a virtual display and streams it to your browser through noVNC; log in
there, then hit /login/done. Cookies stay in the persistent profile.
(Fallback: a <platform>-state.json Playwright storage file dropped into STATE_DIR
is imported on the next job.)
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import async_playwright

PROFILE_ROOT = Path(os.environ.get("PROFILE_ROOT", str(Path.home() / "uploader-profiles")))
STATE_DIR = Path(os.environ.get("STATE_DIR", str(Path.home() / "uploader-state")))
HEADLESS = os.environ.get("HEADLESS", "1") != "0"   # set 0 and run under xvfb-run if a site blocks headless
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH") or None
USER_AGENT = os.environ.get(
    "USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36",
)
LOW_MEM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--no-first-run",
    "--mute-audio",
    "--renderer-process-limit=2",
    "--js-flags=--max-old-space-size=768",
    "--disable-features=Translate,MediaRouter,OptimizationHints",
    "--disable-blink-features=AutomationControlled",
]


def _import_state_if_new(platform: str, profile: Path):
    """Return cookies from <platform>-state.json if it is newer than the last import."""
    state = STATE_DIR / f"{platform}-state.json"
    marker = profile / ".state-imported"
    if not state.exists():
        return None
    if marker.exists() and marker.stat().st_mtime >= state.stat().st_mtime:
        return None
    return state, marker, json.loads(state.read_text()).get("cookies", [])


def _launch_kwargs(platform: str, headless: bool) -> dict:
    kwargs = dict(
        user_data_dir=str(PROFILE_ROOT / platform),
        headless=headless,
        args=LOW_MEM_ARGS + ([] if headless else ["--window-size=1280,900", "--window-position=0,0"]),
        user_agent=USER_AGENT,
        viewport={"width": 1280, "height": 860},
        locale="en-US",
    )
    if CHROMIUM_PATH:
        kwargs["executable_path"] = CHROMIUM_PATH
    else:
        kwargs["channel"] = "chromium"  # full Chromium "new headless", looks like a normal browser
    return kwargs


@asynccontextmanager
async def browser_page(platform: str):
    profile = PROFILE_ROOT / platform
    profile.mkdir(parents=True, exist_ok=True)
    pending = _import_state_if_new(platform, profile)
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(**_launch_kwargs(platform, HEADLESS))
        try:
            if pending:
                state, marker, cookies = pending
                if cookies:
                    await ctx.add_cookies(cookies)
                marker.touch()
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            page.set_default_timeout(30_000)
            yield page
        finally:
            await ctx.close()


async def try_click(page, locator, timeout=2500) -> bool:
    """Click if it shows up within timeout; never raise."""
    try:
        await locator.first.wait_for(state="visible", timeout=timeout)
        await locator.first.click()
        return True
    except Exception:
        return False


async def dismiss_popups(page, names=("Got it", "Not now", "Not Now", "Dismiss", "OK")):
    for n in names:
        await try_click(page, page.get_by_role("button", name=n, exact=True), timeout=800)


async def type_caption(page, text: str):
    """Insert caption text line by line (insert_text keeps emoji/unicode intact)."""
    lines = text.splitlines() or [""]
    for i, line in enumerate(lines):
        if i:
            await page.keyboard.press("Shift+Enter")
        if line:
            await page.keyboard.insert_text(line)


# ------------------------------------------------------------------ remote login (noVNC)
LOGIN_MINUTES = int(os.environ.get("LOGIN_MINUTES", "15"))
NOVNC_PORT = int(os.environ.get("NOVNC_PORT", "6080"))
NOVNC_WEB = os.environ.get("NOVNC_WEB", "/usr/share/novnc")
LOGIN_DISPLAY = os.environ.get("LOGIN_DISPLAY", ":42")  # xvfb-run -a uses :99+


class LoginSession:
    """Headful Chromium on Xvfb, viewable/controllable from a browser via noVNC."""

    def __init__(self, platform: str, url: str):
        self.platform, self.url = platform, url
        self.procs, self.pw, self.ctx, self.timer = [], None, None, None

    async def _spawn(self, *cmd):
        p = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        self.procs.append(p)

    async def start(self, on_timeout):
        await self._spawn("Xvfb", LOGIN_DISPLAY, "-screen", "0", "1280x900x24", "-nolisten", "tcp")
        await asyncio.sleep(1.5)
        await self._spawn("x11vnc", "-display", LOGIN_DISPLAY, "-forever", "-shared", "-nopw",
                          "-localhost", "-rfbport", "5900", "-quiet")
        await asyncio.sleep(1)
        await self._spawn("websockify", "--web", NOVNC_WEB, str(NOVNC_PORT), "localhost:5900")
        (PROFILE_ROOT / self.platform).mkdir(parents=True, exist_ok=True)
        self.pw = await async_playwright().start()
        kwargs = _launch_kwargs(self.platform, headless=False)
        kwargs["env"] = {**os.environ, "DISPLAY": LOGIN_DISPLAY}
        self.ctx = await self.pw.chromium.launch_persistent_context(**kwargs)
        page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        await page.goto(self.url, wait_until="domcontentloaded")
        self.timer = asyncio.create_task(self._expire(on_timeout))

    async def _expire(self, on_timeout):
        await asyncio.sleep(LOGIN_MINUTES * 60)
        await on_timeout()

    async def stop(self):
        if self.timer and self.timer is not asyncio.current_task():
            self.timer.cancel()
        for closer in (lambda: self.ctx and self.ctx.close(), lambda: self.pw and self.pw.stop()):
            try:
                c = closer()
                if c:
                    await c
            except Exception:
                pass
        for p in reversed(self.procs):
            if p.returncode is None:
                p.terminate()
                try:
                    await asyncio.wait_for(p.wait(), 5)
                except asyncio.TimeoutError:
                    p.kill()
        self.procs.clear()


def add_login_routes(app, platform: str, login_url: str):
    """GET /login?token=..  -> start session, redirect to noVNC.  GET /login/done?token=.. -> stop."""
    from fastapi import HTTPException, Request
    from fastapi.responses import HTMLResponse, RedirectResponse

    from lanes.common.lane import LANE_TOKEN

    state = {"session": None}
    lock: asyncio.Lock = app.state.lock

    def check(request: Request, token: str):
        hdr = request.headers.get("authorization", "")
        if LANE_TOKEN and token != LANE_TOKEN and hdr != f"Bearer {LANE_TOKEN}":
            raise HTTPException(401, "bad or missing token")

    async def finish():
        s = state["session"]
        state["session"] = None
        if s:
            await s.stop()
            if lock.locked():
                lock.release()

    @app.get("/login")
    async def login(request: Request, token: str = ""):
        check(request, token)
        if state["session"] is None:
            if lock.locked():
                raise HTTPException(409, "an upload is running; try again in a minute")
            await lock.acquire()  # no uploads while the profile is open for login
            s = LoginSession(platform, login_url)
            try:
                await s.start(finish)
            except Exception as e:
                await s.stop()
                lock.release()
                raise HTTPException(500, f"could not start login browser: {e}")
            state["session"] = s
        host = request.url.hostname
        return RedirectResponse(
            f"http://{host}:{NOVNC_PORT}/vnc.html?autoconnect=1&resize=scale&reconnect=1")

    @app.get("/login/done", response_class=HTMLResponse)
    async def login_done(request: Request, token: str = ""):
        check(request, token)
        await finish()
        return f"<h2>{platform}: login browser closed, session saved.</h2>"
