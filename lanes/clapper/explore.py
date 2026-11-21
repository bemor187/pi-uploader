"""Auto-map Clapper's posting screens. Never taps Post/Publish/Share.

    cd /opt/uploader && ./venv/bin/python -m lanes.clapper.explore          # report only
    cd /opt/uploader && ./venv/bin/python -m lanes.clapper.explore --apply  # also save clapper_flow.json

1. records a 6 s test clip on the phone (screenrecord), so no video file is needed
2. sends it to Clapper with the same share intent a real job uses
3. on each screen: dumps elements + saves a screenshot, taps the safest
   "advance" button (Next / Continue / Allow / OK ...), and stops when it reaches
   a screen with a Post-like button, or gets stuck
4. writes a report to ~/uploader-work/clapper-explore.txt and a proposed flow
   to ~/uploader-work/clapper_flow.proposed.json (--apply copies it into place)
"""
import asyncio
import json
import re
import shutil
import sys
from pathlib import Path

from lanes.clapper.app import (FLOW_FILE, PACKAGE, REMOTE_DIR, adb, dump_nodes, ensure_device,
                               open_share, push_and_index, shell, tap)
from lanes.common.lane import DEBUG_DIR, WORK

MAX_STEPS = 12
FINAL = re.compile(r"^(post|publish|share|upload|post now|share now)$", re.I)
ADVANCE = [  # in priority order
    re.compile(r"^(while using the app|only this time|allow|allow all)$", re.I),
    re.compile(r"^(next|continue|done|ok|got it|skip|not now|use video|confirm)$", re.I),
    re.compile(r"(^|\b)(next|continue)(\b|$)", re.I),
]
REPORT = WORK / "clapper-explore.txt"
PROPOSED = WORK / "clapper_flow.proposed.json"
lines: list[str] = []


def out(s=""):
    print(s)
    lines.append(s)


def label(n):
    return n["text"] or n["desc"] or n["id"].split("/")[-1]


def describe(nodes):
    for n in nodes:
        if n["text"] or n["desc"] or n["clickable"]:
            flags = ("C" if n["clickable"] else "-") + ("E" if n["enabled"] else "-")
            out(f"   {flags} ({n['x']:4},{n['y']:4}) text={n['text']!r} desc={n['desc']!r} "
                f"id={n['id']!r} class={n['class'].split('.')[-1]}")


def match_for(n):
    """Most stable matcher for a node: resource-id, else exact text, else desc."""
    if n["id"]:
        return {"id": n["id"]}
    if n["text"]:
        return {"text_re": f"^{re.escape(n['text'])}$"}
    return {"desc_re": f"^{re.escape(n['desc'])}$"}


def find_final(nodes):
    return next((n for n in nodes if n["enabled"] and (FINAL.match(n["text"].strip()) or FINAL.match(n["desc"].strip()))), None)


def find_advance(nodes):
    for rx in ADVANCE:
        for n in nodes:
            t = label(n).strip()
            if n["enabled"] and t and rx.search(t) and not FINAL.match(t):
                return n
    return None


async def screenshot(name):
    await shell(f"screencap -p /sdcard/{name}.png", check=False)
    await adb("pull", f"/sdcard/{name}.png", str(DEBUG_DIR / f"{name}.png"), check=False)
    await shell(f"rm -f /sdcard/{name}.png", check=False)


async def main(apply: bool):
    WORK.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    await ensure_device()
    pkgs = await shell("pm list packages", check=False)
    if f"package:{PACKAGE}" not in pkgs:
        sys.exit(f"Clapper package {PACKAGE} not installed; set CLAPPER_PACKAGE in /etc/uploader.env")

    out(f"== recording a 6 s test clip on the phone")
    await shell(f"mkdir -p {REMOTE_DIR}")
    await shell("input keyevent KEYCODE_HOME")
    clip_local = WORK / "explore-test.mp4"
    await shell(f"screenrecord --time-limit 6 {REMOTE_DIR}/rec.mp4", timeout=30, check=False)
    await adb("pull", f"{REMOTE_DIR}/rec.mp4", str(clip_local))
    await shell(f"rm -f {REMOTE_DIR}/rec.mp4", check=False)

    out("== sending it to Clapper via share intent")
    uri = await push_and_index(clip_local, "explore")
    await open_share(uri, "test caption from explore")
    await asyncio.sleep(6)

    steps = [{"label": "app loads", "action": "sleep", "seconds": 6}]
    last_sig, reached_final = None, False
    for i in range(1, MAX_STEPS + 1):
        nodes = await dump_nodes()
        await screenshot(f"explore-{i:02d}")
        fg = await shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp' | head -2", check=False)
        out(f"\n== screen {i}  (screenshot ~/uploader-work/debug/explore-{i:02d}.png)")
        out("   focus: " + " | ".join(l.strip() for l in fg.splitlines()))
        describe(nodes)

        final = find_final(nodes)
        edit = next((n for n in nodes if n["class"].endswith("EditText")), None)
        if final:
            out(f"\n>> reached the post screen: final button '{label(final)}' (NOT tapped)")
            if edit:
                steps += [
                    {"label": "caption field", "action": "tap", "match": match_for(edit) if edit["id"] else {"class": "android.widget.EditText"}, "timeout": 60},
                    {"label": "type caption", "action": "type_caption"},
                    {"label": "hide keyboard", "action": "key", "key": "KEYCODE_BACK"},
                ]
            else:
                out("   (no caption field on this screen; caption may be on an earlier screen or not supported)")
            steps += [
                {"label": "post button", "action": "tap", "match": {**match_for(final), "enabled": True}, "timeout": 60},
                {"label": "confirmation", "action": "wait", "match": {"any_re": "(posted|uploading|upload|processing|success|your video)"}, "timeout": 300, "optional": True},
            ]
            reached_final = True
            break

        sig = tuple(sorted((label(n), n["x"], n["y"]) for n in nodes))
        if sig == last_sig:
            out("\n>> screen did not change after the last tap; stopping")
            break
        last_sig = sig

        adv = find_advance(nodes)
        if not adv:
            out("\n>> no safe button to advance with; stopping here")
            break
        out(f"\n>> tapping '{label(adv)}'")
        steps.append({"label": f"tap {label(adv)}", "action": "tap", "match": match_for(adv),
                      "timeout": 60, "optional": bool(ADVANCE[0].search(label(adv)))})
        await tap(adv)
        await asyncio.sleep(3)

    # leave the phone clean: back out of the composer without posting
    for _ in range(4):
        await shell("input keyevent KEYCODE_BACK", check=False)
        await asyncio.sleep(0.7)
    await shell(f"rm -f {REMOTE_DIR}/explore.mp4", check=False)

    flow = {"_comment": "generated by lanes.clapper.explore", "steps": steps}
    PROPOSED.write_text(json.dumps(flow, indent=2))
    out(f"\n== proposed flow ({'COMPLETE' if reached_final else 'INCOMPLETE - did not reach a Post button'}):")
    out(json.dumps(flow, indent=2))
    if apply and reached_final:
        backup = FLOW_FILE.with_suffix(".json.bak")
        shutil.copy(FLOW_FILE, backup)
        shutil.copy(PROPOSED, FLOW_FILE)
        out(f"\n== applied to {FLOW_FILE} (previous saved as {backup.name}); "
            "restart: sudo systemctl restart uploader-lane@clapper")
    elif apply:
        out("\n== NOT applied (flow incomplete). Paste this report to Claude.")
    REPORT.write_text("\n".join(lines))
    print(f"\nreport saved to {REPORT}")


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv))
