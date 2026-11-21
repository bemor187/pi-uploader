# Pi Uploader Cluster

Headless upload system for TikTok, Instagram and Clapper. Grokbot / Claude Code
POST a video to **brain**, which queues it and hands it to the right lane. Once
brain accepts the job, nothing else needs to stay on. Setup, logins and
day-to-day running are all done from a phone.

| Host | Model | Role | Service | Port |
|---|---|---|---|---|
| brain | Pi 5 4GB | API + SQLite queue + dispatcher, behind nginx | `uploader-brain` | 80 (nginx) → 8000 |
| tiktok | Pi 4 4GB | Playwright Chromium → TikTok Studio web | `uploader-lane@tiktok` | 8100 |
| insta | Pi 4 4GB | Playwright Chromium → instagram.com Reels | `uploader-lane@insta` | 8100 |
| clapper | Pi 4 4GB | ADB → Clapper app on Pixel 3a | `uploader-lane@clapper` | 8100 |

Everything except SSH is firewalled (ufw) to the `tailscale0` interface.
The job queue uses SQLite rather than Redis: one less daemon, and it survives reboots.

## 1. Set up each Pi (brain first), no other computer needed

SSH into the Pi from your phone (any SSH app, e.g. Termius, to `<user>@brain.local` on home Wi-Fi)
or use its own keyboard and monitor. Then run:

```bash
curl -fsSL https://raw.githubusercontent.com/bemor187/pi-uploader/main/scripts/bootstrap.sh | sudo bash -s brain
```

The script installs everything and prints a Tailscale login URL. Open it on your phone to join the Pi.
It turns on **Tailscale SSH** and sets up the role's software, `/etc/uploader.env`, the systemd unit and the firewall.
After that, any tailnet device (phone included) can reach `ssh <user>@brain` with no keys to copy.

**brain prints `API_TOKEN` and `LANE_TOKEN`. Save both** (a password manager on your phone works).
Give the lanes the same LANE_TOKEN:

```bash
curl -fsSL https://raw.githubusercontent.com/bemor187/pi-uploader/main/scripts/bootstrap.sh | sudo LANE_TOKEN=<from brain> bash -s tiktok
```

Do the same for `insta` and `clapper`. To update later, re-run the same line; it pulls the latest code and keeps your config.
Health check from the phone's browser (Tailscale on): `http://brain/health`.

Turn on MagicDNS in the Tailscale admin console so `brain`, `tiktok` and the other hostnames resolve.
Disable key expiry for the four Pis there too.

## 2. Log the browser lanes in, from your phone

On your phone (Tailscale connected), open:

```
http://tiktok:8100/login?token=<LANE_TOKEN>
```

The Pi starts a real Chromium window and streams it to your phone's browser (noVNC).
Log in normally, 2FA included, then open `http://tiktok:8100/login/done?token=<LANE_TOKEN>` to close it.
The session stays in the Pi's browser profile across reboots. Do the same at `http://insta:8100/login?...`.
Uploads pause while a login window is open, and it closes on its own after 15 minutes.

Verify at `http://tiktok:8100/check?token=<LANE_TOKEN>`; it should show `"logged_in": true`.
Repeat the login whenever a platform logs you out. The `/status` of failed jobs will say "not logged in".

If a site blocks headless Chromium, set `HEADLESS=0` in `/etc/uploader.env` and re-run setup.
The lane then runs a real browser inside a virtual display (xvfb).

## 3. Clapper phone (Pixel 3a)

1. On the phone: Developer options → **USB debugging** on. Connect it to the clapper Pi with a USB data cable.
   It needs USB debugging, not USB tethering.
2. On the Pi, run `adb devices` and accept the "Allow USB debugging" prompt on the phone (tick *Always allow*).
3. Remove the screen lock PIN, or set Screen lock to None, so the lane can wake and unlock the phone.
4. `curl -H "Authorization: Bearer $LANE_TOKEN" http://clapper:8100/check` shows whether Clapper is installed.
   It also lists candidate package names. Put the right one in `CLAPPER_PACKAGE` and run `sudo systemctl restart uploader-lane@clapper`.
5. **Map Clapper's screens automatically** (never posts):
   `cd /opt/uploader && ./venv/bin/python -m lanes.clapper.explore --apply`
   It records a test clip on the phone, walks Clapper's screens up to the Post button, and saves the steps.
   If it gets stuck, it writes a report to `~/uploader-work/clapper-explore.txt`. To calibrate by hand instead: Clapper's screens aren't documented, so `lanes/clapper/clapper_flow.json` is a first guess.
   Step through one post by hand, running this on each screen:
   `cd /opt/uploader && ./venv/bin/python -m lanes.clapper.dump_ui`
   Then edit the matches in `/opt/uploader/lanes/clapper/clapper_flow.json` to fit.
6. Optional: install [ADBKeyBoard](https://github.com/senzhk/ADBKeyBoard) and set it as the default keyboard so captions keep emoji.
   Without it, non-ASCII characters are dropped.

## 4. Submitting jobs (Grokbot / Claude Code)

```bash
curl -X POST http://brain/upload \
  -H "Authorization: Bearer $API_TOKEN" \
  -F "file=@clip.mp4" \
  -F "caption=New drop 🔥 #fyp" \
  -F "platform=tiktok,insta,clapper" \
  -F "callback_url=http://optional-webhook/endpoint"
# -> {"jobs":[{"job_id":"a1b2c3d4e5f6","platform":"tiktok"}, ...]}  (plus "job_id" when one platform)

curl -H "Authorization: Bearer $API_TOKEN" http://brain/status/a1b2c3d4e5f6
# status: queued | running | done | failed, with detail

curl -H "Authorization: Bearer $API_TOKEN" http://brain/jobs
curl -X POST -H "Authorization: Bearer $API_TOKEN" http://brain/retry/a1b2c3d4e5f6
```

`http://brain` works for anything on your tailnet.

### Submitting from outside the tailnet (cloud agents)
If the agent runs somewhere that can't join Tailscale, expose brain over public HTTPS with Tailscale Funnel:
first enable HTTPS and Funnel for brain in the Tailscale admin console, then on brain run `sudo FUNNEL=1 ~/pi-uploader/scripts/setup.sh brain`.
The endpoint becomes `https://brain.<tailnet>.ts.net/upload`, and API_TOKEN is required on every request.
The lanes, noVNC and SSH stay tailnet-only.

### Retry behaviour (no double posts)
- Lane unreachable: brain retries automatically with backoff (30s, 60s, … up to 5 attempts).
- Lane reachable but the result is unclear (timeout, brain restarted mid-job): marked `failed`
  with a note to check the platform. It never auto-reposts. Use `/retry` once you've checked.
- Failed jobs keep their media on brain, so `/retry` works without re-uploading.

## 5. Hardening (Phase 4)

Once Tailscale SSH works from your phone, run `sudo ~/pi-uploader/scripts/harden-ssh.sh --tailscale` on each Pi.
It turns off password SSH and closes port 22 on the LAN, so the only way in is Tailscale SSH under your tailnet login.
If you'd rather use regular keys, put one in `~/.ssh/authorized_keys` and run it without `--tailscale`.
setup.sh adds 2 GB of swap on the browser lanes when the OS uses dphys-swapfile. Newer Pi OS uses zram instead.

## Operations

```bash
sudo systemctl status uploader-brain            # or uploader-lane@tiktok etc.
journalctl -u uploader-lane@insta -f             # live logs
ls ~/uploader-work/debug/                         # failure screenshots (browser + phone)
sudo nano /etc/uploader.env && sudo systemctl restart <unit>
```
Updating code: `git -C ~/pi-uploader pull && sudo ~/pi-uploader/scripts/update.sh` pulls the code and restarts the services. It doesn't upgrade system packages, and it keeps `/etc/uploader.env` and the Pi's Clapper steps. Re-running the bootstrap line also works, and it does a full upgrade.

## Known limits
- TikTok and Instagram change their web UIs. When a step breaks, the failure screenshot shows which one.
  The selectors are near the top of each `lanes/*/app.py`.
- Clapper's confirmation step is optional until calibrated, so before then "done" means the Post button was tapped.
- Automated posting can trigger platform checks (captchas, "suspicious login"). Uploading at human-like rates helps.
