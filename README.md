# Pi Uploader Cluster

A six-Pi stack (plus one spare Pi 4). At its core is a headless upload system for TikTok, Instagram and Clapper:
Grokbot / Claude Code POST a video to **brain**, which queues it and hands it to the right lane.
Once brain accepts the job, nothing else needs to stay on. Around it sit a static web host
(**web**) and an always-on AI tasker that watches everything (**overseer**). Setup, logins and day-to-day running are all done from a phone.

| Host | Model | Role | Service | Port |
|---|---|---|---|---|
| brain | Pi 5 4GB | API + SQLite queue + dispatcher, behind nginx | `uploader-brain` | 80 (nginx) → 8000 |
| tiktok | Pi 4 4GB | Playwright Chromium → TikTok Studio web | `uploader-lane@tiktok` | 8100 |
| insta | Pi 4 4GB | Playwright Chromium → instagram.com Reels | `uploader-lane@insta` | 8100 |
| clapper | Pi 4 4GB | ADB → Clapper app on Pixel 3a | `uploader-lane@clapper` | 8100 |
| web | Pi 4 4GB | nginx static host: HTML games + files | `nginx` | 80 |
| overseer | Pi 4 4GB | AI tasker (Ollama router) + cluster monitor/alerts | `overseer`, `ollama` | 8200 (11434 localhost only) |

Every Pi runs Raspberry Pi OS Lite 64-bit, and each one's Tailscale hostname is its role name.

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

Do the same for `insta` and `clapper`. `web` needs no token (`... | sudo bash -s web`),
and overseer takes brain's API_TOKEN (section 4b). To update later, re-run the same line; it pulls the latest code and keeps your config.
Health check from the phone's browser (Tailscale on): `http://brain/health`.

Turn on MagicDNS in the Tailscale admin console so `brain`, `tiktok` and the other hostnames resolve.
Disable key expiry for all the Pis there too.

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
   Notes from calibrating (2026-11-22): Clapper registers no video share handler, so the lane launches the app and the flow goes
   **+ → Video → Upload → newest video → Next → Next → caption → Post**, matched by resource id. Turn off any other accessibility
   service on the phone (auto-clickers etc.). They make `uiautomator dump` fail with "null root node", and the lane can't see the screen.
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

## 4b. Overseer (AI tasker + monitor)

```bash
curl -fsSL https://raw.githubusercontent.com/bemor187/pi-uploader/main/scripts/bootstrap.sh | sudo API_TOKEN=<brain's API_TOKEN> bash -s overseer
```

This installs Ollama, which listens on `127.0.0.1:11434` only and keeps one model loaded and one request at a time, with a 30m keep-alive.
It pulls `qwen2.5:1.5b`, starts `overseer` on :8200 and prints a **TASK_TOKEN**. Then edit `/etc/uploader.env`:

```
AGENTS=msi=ollama:http://msi:11434|qwen3:14b,macbook=ollama:http://macbook:11434,local=ollama:http://127.0.0.1:11434|qwen2.5:1.5b
ALERT_URL=https://ntfy.sh/<your-long-random-topic>
BRAIN_URL=http://brain
```

and run `sudo systemctl restart overseer`. MSI and MacBook need `OLLAMA_HOST=0.0.0.0` and must be on the tailnet.

- `POST http://overseer:8200/task` with `Authorization: Bearer $TASK_TOKEN` and `{"prompt": "..."}`. Tasks go to MSI first, then the MacBook, then the local model.
  Add `"agent": "msi"` (and optionally `"model"`) to pin a task to one agent.
- `http://overseer:8200/` shows the status page. `/health` returns JSON. `/digest?token=$TASK_TOKEN` gives a plain-English summary from the first healthy agent (`DIGEST_AGENT=<name>` pins one).
- Every 60s it checks each Ollama agent, brain, the three lanes, and the hosts in `SITES` (web by default). It sends an ntfy alert when one goes down (2 failed checks in a row) or comes back up, and for each newly failed upload.
- Auto-retry happens **once per job**, and only when brain says `lane unreachable:`. That means the lane never got the video, so it can't have been posted. Any other failure is alert-only.
- **Fleet over SSH** (`overseer/fleet.py`). overseer runs as `bemor` and logs into every Pi with Tailscale SSH (no keys; it relies on the tailnet SSH policy allowing it, and on passwordless sudo).
  Every 5 min it checks `ssh:<host>` (is the Pi alive at all, as opposed to just its service) and `os:<host>` (disk, memory, temperature, under-voltage/throttling, failed or inactive role units).
  Every 6 h it calls each lane's `/check` as `login:<lane>`: TikTok/Instagram logged in, and clapper's Pixel attached with Clapper installed. It reads `LANE_TOKEN` from brain.
  Each of these alerts like the other checks. `AUTO_RESTART=1` lets it restart a role's units when that role's health is down but its Pi still answers SSH. This is off by default because a restart mid-post can leave a half-made post.
- `GET /fleet` (TASK_TOKEN) returns every Pi's latest OS snapshot. `POST /fleet/<host>/<action>` runs one fixed action: `status`, `logs` (`?lines=`), `check`, `restart` (that Pi's role units), `update` (`update.sh`), `reboot`.
  There is no free-form command. `restart`, `update` and `reboot` are refused on overseer itself.

### e-paper status screen (optional)

A Waveshare 2.13" e-paper on overseer's GPIO header shows one row per Pi: **PI** (answers SSH), **OS** (disk/mem/temp/power), **AP** (its service) and **LG** (login/phone), with the issues on the right and the time in the header.
If the time stops moving, overseer itself is down, since e-paper keeps its last image with no power.
```bash
sudo ~/pi-uploader/scripts/setup-epaper.sh            # packages, SPI, driver; service stays off
# power off, plug the display onto the header, boot, then:
sudo ~/pi-uploader/scripts/setup-epaper.sh --enable
python3 /opt/uploader/overseer/epaper.py --png /tmp/e.png   # preview without a display
```
Set `EPD_DRIVER` in `/etc/uploader.env` to match the version on the display's sticker (default `epd2in13_V4`; also `epd2in13_V2`, `_V3`, `epd2in13b_V4`), then re-run setup.
`EPAPER_ROTATE=180` flips the image if the display is mounted upside down. It redraws when something changes and at least every 15 min.

## 4c. web (static games + files)

```bash
curl -fsSL https://raw.githubusercontent.com/bemor187/pi-uploader/main/scripts/bootstrap.sh | sudo bash -s web
```

nginx serves `/srv/web` (owned by your Pi user) on port 80, tailnet only:

| Path on the Pi | URL |
|---|---|
| `/srv/web/index.html` | `http://web/` (a starter page; setup never overwrites yours) |
| `/srv/web/games/<name>/index.html` | `http://web/games/<name>/` |
| `/srv/web/files/` | `http://web/files/` (directory listing) |
| — | `http://web/health` (for overseer) |

Copy things over from any tailnet machine: `rsync -av mygame/ bemor@web:/srv/web/games/mygame/`.
Games get `Cross-Origin-Opener/Embedder-Policy` headers, so threaded Godot/Unity web exports work, and `.wasm` is served as `application/wasm`.
To share games publicly, enable HTTPS + Funnel for `web` in the Tailscale admin console and re-run with `FUNNEL=1`.
The address becomes `https://web.<tailnet>.ts.net/`, and everything on the Pi is then public, files included.

## 5. Hardening (Phase 4)

Once Tailscale SSH works from your phone, run `sudo ~/pi-uploader/scripts/harden-ssh.sh --tailscale` on each Pi.
It turns off password SSH and closes port 22 on the LAN, so the only way in is Tailscale SSH under your tailnet login.
If you'd rather use regular keys, put one in `~/.ssh/authorized_keys` and run it without `--tailscale`.
setup.sh adds 2 GB of swap on the browser lanes when the OS uses dphys-swapfile. Newer Pi OS uses zram instead.

## Check, update, recover

**Check everything** (from any Pi, or from your phone's SSH app):
```bash
~/pi-uploader/scripts/check.sh          # every Pi's health + the latest backup from each
sudo ~/pi-uploader/scripts/check.sh --deep   # also: are TikTok/Instagram still logged in, is the Pixel connected
```
It exits non-zero and prints FAIL lines when something's wrong. overseer also checks all of this every minute,
and sends an ntfy alert when a Pi goes down or a Pi's backup is more than 36 hours old.

**Update** (on each Pi, after changes are merged to `main`):
```bash
sudo ~/pi-uploader/scripts/update.sh
```
This pulls the code, installs any new Python dependencies, restarts the services, refreshes the backup timer, then runs `check.sh`.
It keeps `/etc/uploader.env`, browser logins and the Clapper calibration. Re-running the bootstrap line also works.
That path additionally upgrades the OS packages.

**Backups** run on their own: each Pi runs `pi-backup.timer` nightly around 03:30 and keeps its last 7 in `/var/backups/pi-stack/`.
It sends a copy to **overseer** with Taildrop. overseer files them under `/var/backups/pi-stack/<host>/` and keeps 14 per host.
overseer's own backups go to **brain**. Run one now with `sudo ~/pi-uploader/scripts/backup.sh`.

| Pi | What's backed up |
|---|---|
| all | `/etc/uploader.env` (tokens and settings) |
| brain | job queue database |
| tiktok, insta | browser profile, i.e. the platform login (caches skipped) |
| clapper | calibrated `clapper_flow.json`, the ADB key the Pixel trusts |
| web | everything in `/srv/web` |
| overseer | its database, the Ollama service settings |

Taildrop must be allowed in the Tailscale admin console (it's on by default for personal tailnets), and all the Pis must be logged in as you.

**Recover a Pi** (dead SD card, corruption, or swapping hardware):
1. In the Tailscale admin console, **delete the old machine**. Otherwise the new one joins as `<host>-1`.
2. Flash Raspberry Pi OS Lite 64-bit with Raspberry Pi Imager: **same hostname**, user `bemor`, SSH on.
3. Run that Pi's bootstrap line (section 1). Any token it prints doesn't matter, because the restore puts the old ones back.
4. Fetch its backup from overseer (for overseer itself, use brain):
   ```bash
   # on overseer:
   ls /var/backups/pi-stack/<host>/
   sudo tailscale file cp /var/backups/pi-stack/<host>/<newest>.tgz <host>:
   # on the new Pi:
   sudo tailscale file get ~/
   sudo ~/pi-uploader/scripts/restore.sh ~/<host>-*.tgz
   ```
5. Run `~/pi-uploader/scripts/check.sh`. On clapper, accept the USB-debugging prompt on the Pixel if it asks again.
   If TikTok or Instagram show `logged_in: false`, log in again through `/login` (section 2).

If brain is restored, everything queued up to its last backup comes back. Jobs that were running are marked failed, so you can check them and use `/retry`.

## Operations

```bash
sudo systemctl status uploader-brain            # or uploader-lane@tiktok, overseer, nginx (web)
systemctl list-timers pi-backup                  # when the next backup runs
journalctl -u pi-backup -n 20                    # last backup's output
journalctl -u uploader-lane@insta -f             # live logs
ls ~/uploader-work/debug/                         # failure screenshots (browser + phone)
sudo nano /etc/uploader.env && sudo systemctl restart <unit>
```
Updating code: `git -C ~/pi-uploader pull && sudo ~/pi-uploader/scripts/update.sh` pulls the code and restarts the services.
On web it reloads nginx. It doesn't upgrade system packages, and it keeps `/etc/uploader.env` and the Pi's Clapper steps. Re-running the bootstrap line also works, and it does a full upgrade.

## Known limits
- TikTok and Instagram change their web UIs. When a step breaks, the failure screenshot shows which one.
  The selectors are near the top of each `lanes/*/app.py`.
- Clapper's confirmation step is optional until calibrated, so before then "done" means the Post button was tapped.
- Automated posting can trigger platform checks (captchas, "suspicious login"). Uploading at human-like rates helps.

## Support my work 🙏

I build pi-uploader and my other projects on my own, with spare time and old hardware. My biggest project, [DarkGarlic LLM](https://github.com/bemor187/garlic-llm/tree/darkgarlic) (a language model on a PS4's GPU), has a Stage 2 planned: bigger models across several PS4s. It is waiting on hardware I cannot afford yet. If this has been useful to you, anything helps, and I am truly grateful.

**Hardware I am hoping for (used is perfect):** PS4 Pros, Dell PowerEdge servers (or similar rack servers), GPU compute or cloud credits, a gigabit network switch.

**Money, any amount:**

- Cash App: [$bemor187](https://cash.app/$bemor187)
- PayPal: [kultivatedkustoms@gmail.com](https://www.paypal.com/donate/?business=kultivatedkustoms%40gmail.com&currency_code=USD)

To donate hardware or compute, [open an issue](https://github.com/bemor187/pi-uploader/issues/new). A ⭐ or a share helps too. Thank you.
