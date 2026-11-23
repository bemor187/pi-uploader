"""fleet: SSH-based OS checks, lane login checks and allowlisted actions for overseer.

overseer runs as the Pi user and reaches every other Pi over Tailscale SSH (no keys to copy;
the tailnet policy decides who may log in). Nothing here runs arbitrary commands: each action
is a fixed command for a host listed in FLEET.

Checks (results land in overseer's STATE, so they show on / and /health and alert via ntfy):
  ssh:<host>    host answers SSH at all (distinguishes "Pi dead/unplugged" from "service down")
  os:<host>     disk, memory, temperature, under-voltage/throttling, failed or inactive units
  login:<lane>  lane /check: tiktok/insta logged in, clapper's Pixel attached + app installed
"""
import asyncio
import getpass
import json
import logging
import os
import socket
import time
from typing import Awaitable, Callable, Optional

import httpx

log = logging.getLogger("overseer.fleet")

SELF = socket.gethostname()
PI_USER = os.environ.get("PI_USER", "").strip() or getpass.getuser()
# host=unit+unit,...  the units that make up each host's role
DEFAULT_FLEET = ("brain=uploader-brain,tiktok=uploader-lane@tiktok,insta=uploader-lane@insta,"
                 "clapper=uploader-lane@clapper,web=nginx,overseer=overseer+ollama")
FLEET_INTERVAL = float(os.environ.get("FLEET_INTERVAL", "300"))
LOGIN_INTERVAL = float(os.environ.get("LOGIN_CHECK_H", "6")) * 3600
LOGIN_FIRST_DELAY = float(os.environ.get("LOGIN_FIRST_DELAY", "300"))
LOGIN_LANES = [s.strip() for s in os.environ.get("LOGIN_LANES", "tiktok,insta,clapper").split(",") if s.strip()]
DISK_WARN = float(os.environ.get("DISK_WARN_PCT", "90"))
MEM_WARN = float(os.environ.get("MEM_WARN_PCT", "95"))
TEMP_WARN = float(os.environ.get("TEMP_WARN_C", "80"))
# restart a role's units when its health check is DOWN but the Pi still answers SSH. Off by default:
# restarting a lane mid-post can leave a half-made post (it is never auto-retried, only alerted).
AUTO_RESTART = os.environ.get("AUTO_RESTART", "0") == "1"
RESTART_COOLDOWN = float(os.environ.get("RESTART_COOLDOWN", "3600"))
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=10"]


def parse_fleet(spec: str) -> dict:
    out = {}
    for item in filter(None, (s.strip() for s in spec.split(","))):
        name, _, units = item.partition("=")
        if name.strip():
            out[name.strip()] = [u.strip() for u in units.split("+") if u.strip()]
    return out


FLEET = parse_fleet(os.environ.get("FLEET", DEFAULT_FLEET))

# Runs on each Pi as `python3 - <units...>`; prints one JSON line. Stdlib only.
PROBE = r'''
import json, os, shutil, subprocess, sys
def run(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""
d = {}
d["uptime_h"] = round(float(open("/proc/uptime").read().split()[0]) / 3600, 1)
d["load1"] = round(os.getloadavg()[0], 2)
d["cpus"] = os.cpu_count()
m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
d["mem_pct"] = round(100 * (1 - m["MemAvailable"] / m["MemTotal"]))
du = shutil.disk_usage("/")
d["disk_pct"] = round(100 * du.used / du.total)
try:
    d["temp_c"] = round(int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000, 1)
except Exception:
    d["temp_c"] = None
t = run("vcgencmd", "get_throttled")
d["throttled"] = int(t.split("=")[1], 16) if "=" in t else None
d["failed_units"] = [l.split()[0] for l in run("systemctl", "--failed", "--no-legend", "--plain").splitlines() if l.strip()]
d["units"] = {u: run("systemctl", "is-active", u) or "unknown" for u in sys.argv[1:]}
print(json.dumps(d))
'''

ACTIONS = ("status", "logs", "check", "restart", "update", "reboot")
SELF_FORBIDDEN = {"restart", "update", "reboot"}  # would kill overseer mid-request; use SSH

Record = Callable[..., Awaitable[None]]
_record: Optional[Record] = None
_alert: Optional[Callable[..., Awaitable[None]]] = None
_event: Optional[Callable[[str, str, str], None]] = None
_state: dict = {}
_lanes: dict = {}
SNAP: dict = {}           # host -> latest probe dict (+ problems, checked)
_last_restart: dict = {}  # target -> ts
_lane_token: Optional[str] = None


def init(record: Record, alert, event, state: dict, lanes: dict):
    global _record, _alert, _event, _state, _lanes
    _record, _alert, _event, _state, _lanes = record, alert, event, state, lanes


# ---------------------------------------------------------------- ssh
async def run(host: str, cmd: str, stdin: Optional[str] = None, timeout: float = 60) -> tuple:
    """Run a shell command on host (locally if host is this machine). Returns (rc, output)."""
    argv = ["bash", "-c", cmd] if host == SELF else ["ssh", *SSH_OPTS, f"{PI_USER}@{host}", cmd]
    p = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(p.communicate(stdin.encode() if stdin else None), timeout)
    except asyncio.TimeoutError:
        p.kill()
        await p.wait()
        return 124, f"timed out after {int(timeout)}s"
    return p.returncode, out.decode(errors="replace")


async def probe(host: str) -> dict:
    rc, out = await run(host, "python3 - " + " ".join(FLEET.get(host, [])), stdin=PROBE, timeout=40)
    if rc != 0:
        raise RuntimeError((out.strip().splitlines() or [f"exit {rc}"])[-1][:200])
    return json.loads(out.strip().splitlines()[-1])


def problems(d: dict) -> list:
    p = []
    if d.get("disk_pct", 0) >= DISK_WARN:
        p.append(f"disk {d['disk_pct']}% full")
    if d.get("mem_pct", 0) >= MEM_WARN:
        p.append(f"memory {d['mem_pct']}% used")
    if d.get("temp_c") is not None and d["temp_c"] >= TEMP_WARN:
        p.append(f"{d['temp_c']}C hot")
    t = d.get("throttled")
    if t:
        if t & 0x1:
            p.append("under-voltage NOW (power supply/cable)")
        elif t & 0x10000:
            p.append("under-voltage since boot (weak power supply/cable)")
        if t & 0x4:
            p.append("CPU throttled now")
    for u, s in (d.get("units") or {}).items():
        if s != "active":
            p.append(f"{u} {s}")
    if d.get("failed_units"):
        p.append("failed: " + " ".join(d["failed_units"][:5]))
    return p


async def check_host(host: str):
    try:
        d = await probe(host)
    except Exception as e:
        await _record(f"ssh:{host}", False, f"ssh: {e}")
        return
    await _record(f"ssh:{host}", True, f"ok (up {d.get('uptime_h')}h)")
    probs = problems(d)
    old = SNAP.get(host, {}).get("problems")
    new = [p for p in probs if p not in (old or [])]
    if old and new and _state.get(f"os:{host}", {}).get("ok") is False:
        # already DOWN, so record() won't alert again: say what got worse
        await _alert(f"WORSE: os:{host}", f"{host} new problem: {'; '.join(new)}", "high", "warning")
    d.update(problems=probs, checked=time.time())
    SNAP[host] = d
    summary = f"ok (disk {d.get('disk_pct')}%, mem {d.get('mem_pct')}%, {d.get('temp_c')}C, load {d.get('load1')})"
    await _record(f"os:{host}", not probs, "; ".join(probs) or summary, down_after=1)


# ---------------------------------------------------------------- logins
async def lane_token() -> str:
    """brain's LANE_TOKEN is authoritative (overseer's own env may hold a random one)."""
    global _lane_token
    if _lane_token:
        return _lane_token
    rc, out = await run("brain", "sudo -n grep -m1 '^LANE_TOKEN=' /etc/uploader.env", timeout=30)
    if rc == 0 and "=" in out:
        _lane_token = out.strip().split("=", 1)[1].strip().strip('"\'')
    return _lane_token or os.environ.get("LANE_TOKEN", "")


async def check_login(c: httpx.AsyncClient, lane: str):
    base = _lanes.get(lane)
    if not base:
        return
    try:
        r = await c.get(f"{base.rstrip('/')}/check",
                        headers={"Authorization": f"Bearer {await lane_token()}"})
    except Exception as e:
        log.info("login check %s skipped: %s", lane, type(e).__name__)  # lane:<x> already alerts
        return
    if r.status_code == 409:
        log.info("login check %s skipped: lane busy", lane)
        return
    if r.status_code == 401:
        global _lane_token
        _lane_token = None  # refetch next time
    try:
        js = r.json()
    except ValueError:
        js = {}
    if r.status_code != 200:
        await _record(f"login:{lane}", False, f"HTTP {r.status_code}: {str(js)[:150]}", down_after=1)
        return
    if "logged_in" in js:
        ok = js["logged_in"] is True
        detail = "logged in" if ok else f"NOT logged in: {json.dumps(js)[:150]} -> {base}/login?token=..."
    else:  # clapper: phone + app
        ok = js.get("device") == "device" and bool(js.get("clapper_installed"))
        detail = "Pixel attached, Clapper installed" if ok else f"phone problem: {json.dumps(js)[:150]}"
    await _record(f"login:{lane}", ok, detail, down_after=1)


async def logins_once():
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as c:
        await asyncio.gather(*(check_login(c, l) for l in LOGIN_LANES))


# ---------------------------------------------------------------- self-heal
def _target_host(target: str) -> Optional[str]:
    if target == "brain":
        return "brain"
    if target.startswith("lane:"):
        return target.split(":", 1)[1]
    return None


async def auto_restart():
    if not AUTO_RESTART:
        return
    for target, s in list(_state.items()):
        host = _target_host(target)
        if not host or host not in FLEET or host == SELF or s.get("ok") is not False:
            continue
        if _state.get(f"ssh:{host}", {}).get("ok") is not True:
            continue  # Pi itself is gone: a restart can't help, a human must
        if time.time() - _last_restart.get(target, 0) < RESTART_COOLDOWN:
            continue
        _last_restart[target] = time.time()
        res = await do_action(host, "restart", who="auto")
        await _alert(f"Auto-restart: {host}",
                     f"{target} was down but {host} answers SSH, so restarted "
                     f"{' '.join(FLEET[host])}: {res['output'][-300:]}", "default", "wrench")


async def fleet_loop():
    next_login = time.time() + LOGIN_FIRST_DELAY
    while True:
        try:
            await asyncio.gather(*(check_host(h) for h in FLEET))
            await auto_restart()
            if LOGIN_LANES and time.time() >= next_login:
                next_login = time.time() + LOGIN_INTERVAL
                await logins_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("fleet pass crashed; continuing")
        await asyncio.sleep(FLEET_INTERVAL)


# ---------------------------------------------------------------- actions
async def do_action(host: str, action: str, lines: int = 200, who: str = "api") -> dict:
    if host not in FLEET:
        raise ValueError(f"host must be one of {sorted(FLEET)}")
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {list(ACTIONS)}")
    if host == SELF and action in SELF_FORBIDDEN:
        raise ValueError(f"'{action}' on overseer itself would kill this request; ssh in instead")
    units = " ".join(FLEET[host])
    if action == "status":
        try:
            d = await probe(host)
            d["problems"] = problems(d)
            return {"host": host, "action": action, "ok": True, "output": json.dumps(d), "data": d}
        except Exception as e:
            return {"host": host, "action": action, "ok": False, "output": str(e)}
    lines = max(10, min(int(lines), 1000))
    cmd, timeout = {
        "logs": (" ; ".join(f"echo '== {u}'; sudo -n journalctl -u {u} -n {lines} --no-pager -o short-iso"
                            for u in FLEET[host]), 60),
        "check": ("~/pi-uploader/scripts/check.sh", 180),
        "restart": (f"sudo -n systemctl restart {units} && systemctl is-active {units}", 120),
        "update": ("sudo -n ~/pi-uploader/scripts/update.sh", 900),
        "reboot": ("sudo -n systemd-run --on-active=3 systemctl reboot && echo 'rebooting in 3s'", 30),
    }[action]
    rc, out = await run(host, cmd, timeout=timeout)
    if action != "logs" and _event:
        await asyncio.to_thread(_event, "action", f"{action} {host}", f"by {who}, exit {rc}: {out[-500:]}")
    return {"host": host, "action": action, "ok": rc == 0, "rc": rc, "output": out[-20000:]}


def snapshot() -> dict:
    return {h: {"ssh": _state.get(f"ssh:{h}", {}).get("detail"), **SNAP.get(h, {})} for h in FLEET}
