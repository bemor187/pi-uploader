#!/usr/bin/env python3
"""Log a browser lane in from your PC instead of on the Pi.

Meta (and sometimes TikTok) rejects logins from a fresh automated browser on the Pi,
often with a misleading "wrong password". This opens a normal Chromium window on your
PC, you log in yourself (2FA included), and the session cookies are copied to the lane
Pi as ~/uploader-state/<platform>-state.json. The lane imports that file on its next job
(see lanes/common/browser.py), so no password is ever stored or typed on the Pi.

One-time setup on the PC (Windows: run in PowerShell; Tailscale must be on):
    pip install playwright
    python -m playwright install chromium

Use:
    python scripts/export-login.py insta          # log in, then press Enter in this window
    python scripts/export-login.py tiktok
    python scripts/export-login.py insta --no-send   # just write insta-state.json locally

Re-run whenever the lane reports logged_in: false.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

LOGIN_URLS = {
    "insta": "https://www.instagram.com/accounts/login/",
    "tiktok": "https://www.tiktok.com/login",
}
# Same identity the lanes use (lanes/common/browser.py), so the session looks continuous.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("platform", choices=sorted(LOGIN_URLS))
    ap.add_argument("--host", help="lane Pi to send to (default: same as platform)")
    ap.add_argument("--user", default="bemor")
    ap.add_argument("--user-agent", default=USER_AGENT)
    ap.add_argument("--no-send", action="store_true", help="only write the file locally")
    a = ap.parse_args()

    out = Path(f"{a.platform}-state.json").resolve()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=a.user_agent, viewport={"width": 1280, "height": 860}, locale="en-US")
        page = ctx.new_page()
        page.goto(LOGIN_URLS[a.platform])
        print(f"\nLog in to {a.platform} in the browser window (approve any 'was this you?' on your phone).")
        input("When you can see your feed, come back here and press Enter... ")
        ctx.storage_state(path=str(out))
        browser.close()

    cookies = out.read_text().count('"name"')
    print(f"Saved {cookies} cookies to {out}")
    if cookies < 3:
        sys.exit("That looks like you weren't logged in yet; run it again.")
    if a.no_send:
        return

    host = f"{a.user}@{a.host or a.platform}"
    subprocess.run(["ssh", host, "mkdir -p ~/uploader-state"], check=True)
    subprocess.run(["scp", str(out), f"{host}:uploader-state/{a.platform}-state.json"], check=True)
    out.unlink()  # don't leave a live session file lying around on the PC
    print(f"Sent to {host}:~/uploader-state/. It's imported on the lane's next job.")
    print(f"Check it: ./scripts/goals.sh G6   (or curl -H 'Authorization: Bearer $LANE_TOKEN' http://{a.host or a.platform}:8100/check)")


if __name__ == "__main__":
    main()
