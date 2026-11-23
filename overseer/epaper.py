#!/usr/bin/env python3
"""Fleet status on a Waveshare 2.13" e-paper attached to overseer (250x122, black/white).

Reads overseer's own GET /health (no auth) and draws one row per Pi:
    PI = answers SSH   OS = disk/mem/temp/power/units OK   APP = its service   LOG = login/phone
plus the problems at the bottom and the update time in the header. If the time stops moving,
overseer itself is dead (e-paper keeps the last image without power).

Redraws only when something changes, and at least every EPAPER_REFRESH s (default 900) so the
clock moves. A full refresh every time keeps it ghost-free, and at this rate wear is not a concern.

    python3 epaper.py                 # run forever (systemd: overseer-epaper.service)
    python3 epaper.py --png out.png   # render once to a PNG, no display needed
    python3 epaper.py --png out.png --url http://overseer:8200/health

Env: EPD_DRIVER (default epd2in13_V4; the version is printed on the display's sticker:
epd2in13_V2, epd2in13_V3, epd2in13_V4, epd2in13b_V4 ...), EPAPER_URL, EPAPER_REFRESH,
EPAPER_ROTATE (0 or 180, if mounted upside down). Driver files live in ./vendor/waveshare_epd
(scripts/setup-epaper.sh fetches them).
"""
import json
import logging
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("epaper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

W, H = 250, 122
URL = os.environ.get("EPAPER_URL", "http://127.0.0.1:8200/health")
REFRESH = float(os.environ.get("EPAPER_REFRESH", "900"))
POLL = float(os.environ.get("EPAPER_POLL", "60"))
ROTATE = int(os.environ.get("EPAPER_ROTATE", "0"))
DRIVER = os.environ.get("EPD_DRIVER", "epd2in13_V4")
HOSTS = ["brain", "tiktok", "insta", "clapper", "web", "overseer"]
APP = {"brain": "brain", "tiktok": "lane:tiktok", "insta": "lane:insta",
       "clapper": "lane:clapper", "web": "site:web", "overseer": "agent:local"}


def font(size: int, bold: bool = False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in ("/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts", "/Library/Fonts"):
        try:
            return ImageFont.truetype(f"{d}/{name}", size)
        except OSError:
            pass
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


F_HEAD, F_ROW, F_ROWB, F_FOOT = font(13, True), font(12), font(12, True), font(10)
F_SMALL, F_GLYPH = font(9), font(12, True)


def fetch(url: str = URL):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        log.info("health fetch failed: %s", e)
        return None


def short(target: str, detail: str) -> str:
    d = (detail or "").lower()
    if "under-voltage now" in d:
        return "LOW VOLTAGE now"
    if "under-voltage" in d:
        return "low-V since boot"
    if target.startswith("ssh:") or "unreachable" in d or "timed out" in d:
        return "unreachable"
    if "not logged in" in d:
        return "logged out"
    return (detail or "down")[:28]


def model(health) -> dict:
    """What to draw, without the clock (so it can be compared for 'changed')."""
    if health is None:
        return {"dead": True}
    t = health.get("targets", {})

    def st(key):
        return t.get(key, {}).get("ok") if key in t else "n/a"

    rows = [(h, st(f"ssh:{h}"), st(f"os:{h}"), st(APP[h]), st(f"login:{h}")) for h in HOSTS]
    # group identical problems: "brain tiktok: low-V since boot"
    groups: dict = {}
    for k in sorted(health.get("down", [])):
        kind, _, host = k.partition(":")
        msg = short(k, t.get(k, {}).get("detail", ""))
        if kind in ("lane", "agent", "site", "login") and t.get(f"ssh:{host}", {}).get("ok") is False:
            continue  # the Pi is unreachable; that row already says so
        groups.setdefault(msg, []).append(host or k)
    probs = [f"{' '.join(sorted(set(hs)))}: {m}" for m, hs in groups.items()]
    return {"dead": False, "rows": rows, "problems": probs}


def glyph(v) -> str:
    return {True: "✓", False: "✗", None: "?"}.get(v, "-")


def render(m: dict, now: float) -> Image.Image:
    img = Image.new("1", (W, H), 255)
    d = ImageDraw.Draw(img)
    clock = time.strftime("%a %H:%M", time.localtime(now))
    if m.get("dead"):
        d.rectangle((0, 0, W, 18), fill=0)
        d.text((4, 2), "overseer", font=F_HEAD, fill=255)
        d.text((W - 4, 2), clock, font=F_HEAD, fill=255, anchor="ra")
        d.text((W // 2, 55), "NO STATUS", font=font(24, True), fill=0, anchor="mm")
        d.text((W // 2, 85), "overseer :8200 not answering", font=F_ROW, fill=0, anchor="mm")
        return img
    rows, probs = m["rows"], m["problems"]
    up = sum(1 for r in rows if r[1] is True)
    # header
    d.rectangle((0, 0, W, 17), fill=0)
    d.text((4, 2), f"Pi fleet {up}/{len(rows)}", font=F_HEAD, fill=255)
    d.text((W - 4, 2), clock, font=F_HEAD, fill=255, anchor="ra")
    # table (left): host + PI/OS/APP/LOG glyphs
    cols = [3, 66, 84, 102, 120]
    TW = 136
    y = 19
    for x, h in zip(cols[1:], ("PI", "OS", "AP", "LG")):
        d.text((x + 6, y), h, font=F_SMALL, fill=0, anchor="ma")
    y += 11
    for host, *vals in rows:
        down = vals[0] is not True
        if down:
            d.rectangle((0, y - 1, TW, y + 13), fill=0)
        c = 255 if down else 0
        d.text((cols[0], y), host, font=F_ROWB if down else F_ROW, fill=c)
        for x, v in zip(cols[1:], vals):
            d.text((x + 6, y), glyph(v), font=F_GLYPH, fill=c, anchor="ma")
        y += 15
    # issues (right)
    d.line((TW + 2, 19, TW + 2, H), fill=0)
    x0, w = TW + 6, W - TW - 8
    if not probs:
        d.text(((TW + W) // 2, 62), "all good", font=F_HEAD, fill=0, anchor="mm")
        return img
    ly = 19
    for pr in probs:
        for i, ln in enumerate(wrap(d, pr, w - 6, F_FOOT)):
            if ly > H - 11:
                d.text((W - 3, H - 11), "…", font=F_FOOT, fill=0, anchor="ra")
                return img
            d.text((x0 + (0 if i == 0 else 6), ly), ln, font=F_FOOT, fill=0)
            ly += 11
        ly += 3
    return img


def wrap(d: ImageDraw.ImageDraw, text: str, width: int, f) -> list:
    out, cur = [], ""
    for w in text.split(" "):
        nxt = f"{cur} {w}".strip()
        if d.textlength(nxt, font=f) <= width:
            cur = nxt
        else:
            out.append(cur)
            cur = w
    return out + ([cur] if cur else [])


class Display:
    def __init__(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent / "vendor"))
        mod = __import__(f"waveshare_epd.{DRIVER}", fromlist=["EPD"])
        self.epd = mod.EPD()
        self.color = "b" in DRIVER.replace("epd2in13", "")[:2]  # epd2in13b_*: black + red planes

    def show(self, img: Image.Image):
        if ROTATE:
            img = img.rotate(ROTATE)
        e = self.epd

        def stuck(*_):  # the driver waits on BUSY forever; exit so systemd restarts us
            log.error("display update stuck for 60s (BUSY never released); exiting")
            os._exit(1)

        signal.signal(signal.SIGALRM, stuck)
        signal.alarm(60)
        try:
            e.init()
            buf = e.getbuffer(img)
            if self.color:
                e.display(buf, e.getbuffer(Image.new("1", img.size, 255)))
            else:
                e.display(buf)
            e.sleep()  # low power + protects the panel between refreshes
        finally:
            signal.alarm(0)


def main():
    if "--png" in sys.argv:
        out = sys.argv[sys.argv.index("--png") + 1]
        url = sys.argv[sys.argv.index("--url") + 1] if "--url" in sys.argv else URL
        render(model(fetch(url)), time.time()).save(out)
        print(f"wrote {out}")
        return
    disp = Display()
    last, last_draw = None, 0.0
    while True:
        m = model(fetch())
        if m != last or time.time() - last_draw >= REFRESH:
            try:
                disp.show(render(m, time.time()))
                last, last_draw = m, time.time()
                log.info("drew: %s", "dead" if m.get("dead") else m["problems"] or "all good")
            except Exception:
                log.exception("display update failed")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
