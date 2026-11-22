"""clapper lane: posts to Clapper on a USB-connected Pixel 3a through ADB.

Flow:
  1. adb push the video into /sdcard/DCIM/Uploader and have MediaStore index it
  2. fire an Android share intent (ACTION_SEND video/*) straight at the Clapper app
  3. walk Clapper's post screens using steps from clapper_flow.json, matching
     on-screen elements from `uiautomator dump` (text / content-desc / resource-id)

Clapper's screens aren't documented, so clapper_flow.json is a starting guess.
Calibrate it once with:  python -m lanes.clapper.dump_ui   (prints what's on screen).
"""
import asyncio
import base64
import json
import os
import re
import shlex
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from lanes.common.lane import DEBUG_DIR, LaneError, create_app

ADB = os.environ.get("ADB", "adb")
SERIAL = os.environ.get("ADB_SERIAL", "")
PACKAGE = os.environ.get("CLAPPER_PACKAGE", "com.newsclapper.video")
FLOW_FILE = Path(os.environ.get("CLAPPER_FLOW", str(Path(__file__).with_name("clapper_flow.json"))))
REMOTE_DIR = "/sdcard/DCIM/Uploader"


async def adb(*args: str, timeout: float = 120, check: bool = True) -> str:
    cmd = [ADB] + (["-s", SERIAL] if SERIAL else []) + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise LaneError(f"adb timed out: {' '.join(args)}")
    text = out.decode(errors="replace")
    if check and proc.returncode != 0:
        raise LaneError(f"adb {' '.join(args)} failed: {text.strip()}")
    return text


async def shell(cmd: str, **kw) -> str:
    return await adb("shell", cmd, **kw)


# ------------------------------------------------------------- device prep
async def ensure_device():
    out = await adb("get-state", check=False, timeout=15)
    if "device" not in out:
        raise LaneError(f"phone not available over adb ({out.strip()}); check USB cable and debugging authorization")
    await shell("input keyevent KEYCODE_WAKEUP")
    await shell("wm dismiss-keyguard", check=False)   # works when no PIN/pattern is set
    await shell("svc power stayon usb", check=False)


# ------------------------------------------------------------- UI helpers
_BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


async def dump_nodes() -> list[dict]:
    # Remove the old dump first: uiautomator fails ("null root node") on busy screens like
    # Clapper's autoplaying feed, and reading a stale file would show the previous screen.
    await shell("rm -f /sdcard/ui.xml; uiautomator dump /sdcard/ui.xml", check=False, timeout=30)
    xml = await shell("cat /sdcard/ui.xml", check=False)
    start = xml.find("<?xml")
    if start < 0:
        return []
    try:
        root = ET.fromstring(xml[start:].strip())
    except ET.ParseError:
        return []
    nodes = []
    for n in root.iter("node"):
        m = _BOUNDS.match(n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append({
            "text": n.get("text", ""), "desc": n.get("content-desc", ""),
            "id": n.get("resource-id", ""), "class": n.get("class", ""),
            "clickable": n.get("clickable") == "true", "enabled": n.get("enabled") == "true",
            "x": (x1 + x2) // 2, "y": (y1 + y2) // 2,
        })
    return nodes


def _matches(node: dict, match: dict) -> bool:
    """match keys: text, desc, id, class (exact) or text_re, desc_re, id_re, any_re (regex, case-insensitive)."""
    for key in ("text", "desc", "id", "class"):
        if key in match and node[key] != match[key]:
            return False
    for key in ("text", "desc", "id"):
        rk = f"{key}_re"
        if rk in match and not re.search(match[rk], node[key], re.I):
            return False
    if "any_re" in match and not any(re.search(match["any_re"], node[k], re.I) for k in ("text", "desc", "id")):
        return False
    if match.get("enabled") and not node["enabled"]:
        return False
    return True


async def find(match: dict, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while True:
        nodes = await dump_nodes()
        hits = [n for n in nodes if _matches(n, match)]
        if hits:
            return hits[match.get("index", 0)] if len(hits) > match.get("index", 0) else hits[0]
        if time.monotonic() > deadline:
            return None
        await asyncio.sleep(1.5)


async def tap(node: dict):
    await shell(f"input tap {node['x']} {node['y']}")


async def type_text(text: str):
    """Use ADBKeyBoard (full unicode/emoji) if installed, else `input text` (ASCII only)."""
    ime = await shell("settings get secure default_input_method", check=False)
    if "com.android.adbkeyboard" in ime:
        b64 = base64.b64encode(text.encode()).decode()
        await shell(f"am broadcast -a ADB_INPUT_B64 --es msg {b64}")
        return
    ascii_text = text.encode("ascii", "ignore").decode()
    if ascii_text != text:
        print("warning: non-ASCII characters dropped; install ADBKeyBoard for emoji/unicode")
    for i, line in enumerate(ascii_text.split("\n")):
        if i:
            await shell("input keyevent KEYCODE_ENTER")
        if line:
            esc = line.replace("%", r"\%").replace(" ", "%s")
            await shell(f"input text {shlex.quote(esc)}")


async def screenshot(job_id: str):
    try:
        await shell(f"screencap -p /sdcard/{job_id}.png", check=False)
        await adb("pull", f"/sdcard/{job_id}.png", str(DEBUG_DIR / f"{job_id}.png"), check=False)
        await shell(f"rm -f /sdcard/{job_id}.png", check=False)
    except Exception:
        pass


# ------------------------------------------------------------- media + intent
async def push_and_index(video: Path, job_id: str) -> str:
    remote = f"{REMOTE_DIR}/{job_id}{video.suffix}"
    await shell(f"mkdir -p {REMOTE_DIR}")
    await adb("push", str(video), remote, timeout=600)
    # adb push keeps the source mtime; the flow picks the NEWEST gallery item, so stamp it now
    # or an older clip would sort below existing videos and the wrong one would be posted.
    await shell(f"touch {remote}")
    await shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{remote}", check=False)
    name = Path(remote).name
    for _ in range(20):
        out = await shell(
            "content query --uri content://media/external/video/media --projection _id "
            f"--where \"_display_name='{name}'\"", check=False)
        m = re.search(r"_id=(\d+)", out)
        if m:
            return f"content://media/external/video/media/{m.group(1)}"
        await asyncio.sleep(1)
    raise LaneError("video pushed but MediaStore never indexed it")


async def open_share(uri: str, caption: str):
    await shell(f"am force-stop {PACKAGE}", check=False)
    cmd = (
        "am start -a android.intent.action.SEND -t video/mp4 "
        f"--eu android.intent.extra.STREAM {uri} "
        f"--es android.intent.extra.TEXT {shlex.quote(caption[:500])} "
        f"--grant-read-uri-permission -p {PACKAGE}"
    )
    out = await shell(cmd, check=False)
    if "Error" in out:
        # Fall back to just launching the app; the flow file can then pick from gallery.
        await shell(f"monkey -p {PACKAGE} -c android.intent.category.LAUNCHER 1", check=False)


# ------------------------------------------------------------- flow runner
async def run_flow(caption: str):
    flow = json.loads(FLOW_FILE.read_text())
    for i, step in enumerate(flow["steps"]):
        action, timeout = step["action"], step.get("timeout", 20)
        optional = step.get("optional", False)
        label = step.get("label", f"step {i}")
        if action == "sleep":
            await asyncio.sleep(step.get("seconds", 1))
            continue
        if action == "key":
            await shell(f"input keyevent {step['key']}")
            continue
        if action == "type_caption":
            await type_text(caption)
            continue
        if action == "hide_keyboard":
            # BACK only while the keyboard is up; a blind BACK would leave the composer.
            if "mInputShown=true" in await shell("dumpsys input_method", check=False):
                await shell("input keyevent KEYCODE_BACK")
                await asyncio.sleep(1)
            continue
        node = await find(step["match"], timeout)
        if node is None:
            if optional:
                continue
            raise LaneError(f"Clapper flow stuck at '{label}': nothing matched {step['match']}")
        if action == "tap":
            await tap(node)
            await asyncio.sleep(step.get("after", 1.5))
        elif action == "wait":
            pass
        else:
            raise LaneError(f"unknown flow action {action}")


async def upload(video: Path, caption: str, job_id: str) -> dict:
    remote = None
    try:
        await ensure_device()
        uri = await push_and_index(video, job_id)
        remote = f"{REMOTE_DIR}/{job_id}{video.suffix}"
        await open_share(uri, caption)
        await run_flow(caption)
        return {"detail": "posted to Clapper"}
    except Exception:
        await screenshot(job_id)
        raise
    finally:
        if remote:
            # leave the file a while so the app can finish reading it, then clean up
            await asyncio.sleep(int(os.environ.get("CLAPPER_CLEANUP_DELAY", "60")))
            await shell(f"rm -f {remote}", check=False)


async def check() -> dict:
    await ensure_device()
    pkgs = await shell("pm list packages", check=False)
    return {
        "device": (await adb("get-state", check=False)).strip(),
        "clapper_installed": f"package:{PACKAGE}" in pkgs,
        "clapper_candidates": [p.split(":", 1)[1] for p in pkgs.split() if "clapper" in p.lower()],
    }


app = create_app("clapper", upload, check)
