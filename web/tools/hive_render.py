#!/usr/bin/env python3
"""Render hive-brain's NOW.md + projects/INDEX.md to a small JSON for the web hub.

usage: hive_render.py <hive-brain checkout> <out.json>
Only the Active / Needs Brian / Next up lists and the projects table leave the repo; nothing else.
Stdlib only (the web Pi runs no venv)."""
import json, re, subprocess, sys, time
from pathlib import Path

def plain(s: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)      # [text](link) -> text
    s = re.sub(r"[*`]+", "", s)
    return s.strip()

def sections(md: str) -> dict:
    out, cur = {}, None
    for line in md.splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            cur = h.group(1).strip().lower(); out[cur] = []; continue
        b = re.match(r"^\s*[-*]\s+(.+)$", line)
        if cur and b:
            item = plain(b.group(1))
            if item and item.lower() not in ("(nothing yet)", "none"):
                out[cur].append(item[:300])
    return out

def projects(md: str) -> list:
    rows = []
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not line.lstrip().startswith("|") or set(cells[0]) <= set("-: ") or cells[0].lower() == "project":
            continue
        rows.append({"name": plain(cells[0])[:120], "where": plain(cells[1])[:200], "status": plain(cells[2])[:60]})
    return rows

def main(root: str, dest: str):
    r = Path(root)
    now = sections((r / "NOW.md").read_text(encoding="utf-8")) if (r / "NOW.md").exists() else {}
    idx = (r / "projects" / "INDEX.md")
    try:
        commit = subprocess.run(["git", "-C", root, "log", "-1", "--format=%h %cs"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        commit = ""
    data = {
        "active": now.get("active", []), "needs_brian": now.get("needs brian", []), "next_up": now.get("next up", []),
        "projects": projects(idx.read_text(encoding="utf-8")) if idx.exists() else [],
        "commit": commit, "rendered_at": time.strftime("%Y-%m-%d %H:%M %Z"),
    }
    tmp = Path(dest + ".tmp"); tmp.write_text(json.dumps(data, indent=1), encoding="utf-8"); tmp.replace(dest)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
