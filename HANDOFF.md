# HANDOFF — Pi stack to "fully working"

Any agent (Claude Code, Grok, Garlic, overseer) picking this up: **read this file, then run the loop.** Don't ask the user for steps you can do yourself.

## The loop

```
1. ./scripts/goals.sh              # from the MSI (Git Bash/WSL) or any Pi; read-only
2. Take the FIRST failing goal in the table below.
3. Do its "Fix" (SSH: ssh bemor@<host>; Tailscale SSH, no keys).
4. ./scripts/goals.sh <G#>         # verify that goal now passes. If not, debug; max 3 tries, then log it under Blockers.
5. Update this file: tick the box, add a dated line to Log, commit + push.
6. Repeat until goals.sh prints ALL GOALS PASS.
```

Stop and hand to the user only for the steps marked **HUMAN**. Give them the exact URL or instruction, wait, then re-run that goal. Ask before anything destructive: reflashing, deleting data, `ufw` changes or overwriting `/etc/uploader.env`.

## State at handoff (2026-11-22 21:55)

Working end to end: brain, tiktok (posts as the account default, caption + visibility verified), clapper (Pixel; about 7.5 min per post), web, overseer (ntfy alerts, MSI Ollama agent, nightly backups).
New tonight: **overseer watches the fleet over SSH** (`overseer/fleet.py`: `ssh:`/`os:`/`login:` checks, `GET /fleet`, `POST /fleet/<host>/<action>`); it can use **OpenAI-compatible agents** too. The **e-paper status screen** code is done, but the panel hardware is stuck (`docs/epaper.md`).
Every reachable Pi runs 19852ab.
**Left: insta (offline again, power), Instagram login + test Reel, clapper SSH, SSH hardening. Also replace weak power supplies.**

## Next steps (do in order)

1. `git pull && ./scripts/goals.sh`. Expect failures only from **insta** (G1 G2 G3 G6 G8 G9), plus G4 (under-voltage flags) and G10.
2. **HUMAN — insta power.** insta went dark twice on 2026-11-22: 15:41, and again about 1.5 h after the 20:03 power-cycle. Probably its power supply or cable (see the under-voltage blocker). Ask the user to swap its supply or cable, then power it on. Then `./scripts/goals.sh G1`, `G2`, `G3`, and `ssh bemor@insta 'sudo ~/pi-uploader/scripts/update.sh'` (it's behind; G8).
3. Instagram login, done from the PC because Meta rejects logins made on the Pi. Playwright + Chromium are **already installed on the MSI**.
   - **HUMAN:** the user runs `cd D:\pi-uploader\pi-uploader; python scripts\export-login.py insta` in their own PowerShell (it needs Enter typed in its window). They log in, approve any "was this you?", and press Enter. The script copies the session to `insta:~/uploader-state/insta-state.json`.
   - verify with `./scripts/goals.sh G6`. If it's still `logged_in: false` or checkpointed: open `http://insta:8100/login?token=<LANE_TOKEN>` for the user to clear the challenge, then `/login/done`.
4. G9 insta: **ask the user's OK first** (an Instagram Reel can't be posted privately; the user deletes it after). Then:
   `curl -X POST http://brain/upload -H "Authorization: Bearer $API_TOKEN" -F file=@test.mp4 -F "caption=pipeline test" -F platform=insta`
   and poll `/status/<job_id>` until done. Debug failures from `~/uploader-work/debug/` on insta.
5. Clapper SSH: ask the user to OK either `sudo tailscale set --ssh=false` on clapper or a tailnet ACL with `accept` instead of `check` for the Pis. Apply it and confirm `ssh bemor@clapper` works without re-auth. (overseer itself reached clapper fine over Tailscale SSH on 2026-11-22.)
6. G10: on each Pi, `sudo ~/pi-uploader/scripts/harden-ssh.sh --tailscale`. Confirm a fresh `ssh bemor@<host>` works **before** moving to the next Pi, and do clapper last. **Also confirm overseer can still SSH to every Pi afterwards** (`POST /fleet/<host>/status`), since fleet.py depends on it. Then `./scripts/goals.sh` should show ALL GOALS PASS.
7. **HUMAN — power supplies.** Under-voltage was seen on brain, tiktok, clapper and overseer (tiktok "under-voltage NOW" at about 20:02). Official 5V/3A for a Pi 4, 5V/5A (27W) for the Pi 5. G4 stays red until the flags clear (a reboot after swapping).
8. **e-paper: blocked on hardware.** The full record and the resume steps are in **`docs/epaper.md`**. HUMAN: clean `sudo poweroff`, reseat the ribbon, check the switches, ideally send a photo of the board. Then run the test command in that doc, and `sudo systemctl enable --now overseer-epaper`.
9. Optional: shorten Clapper's optional confirmation wait (it runs out its full 300 s on every post) in `lanes/clapper/` config, then do one more clapper test post with the user's OK.
10. Optional: turn on `AUTO_RESTART=1` in overseer's env once the user is comfortable with it (see README §4b).
11. **Power control is parked**; the notes are in `docs/power-control.md` (watchdog, GPIO reset/relay, smart plugs). Resume only when the user asks.
12. Don't build without the user's answer (see Open decisions): a Facebook lane, or Postiz.

## Goals (in order)

| ✓ | Goal | Verify | Fix |
|---|---|---|---|
| [x] | G1 All 6 Pis on Tailscale + SSH | `goals.sh G1` | Done 2026-11-22 (user) |
| [x] | G2 Each role's services installed + active | `goals.sh G2` | Re-run bootstrap on that Pi (README §1, §4b). Lanes need brain's `LANE_TOKEN`, overseer needs brain's `API_TOKEN` (`sudo grep TOKEN /etc/uploader.env` on brain) |
| [x] | G3 brain reaches all lanes (fails while insta is offline) | `goals.sh G3` | `journalctl -u uploader-lane@<lane>`; check `LANE_*` URLs in brain's env |
| [x] | G4 overseer green + ntfy alerts | `goals.sh G4` | Set `ALERT_URL=https://ntfy.sh/<random topic>` in overseer's `/etc/uploader.env`, `sudo systemctl restart overseer`, tell the user the topic so they can subscribe |
| [x] | G5 overseer can use the MSI's Ollama | `goals.sh G5` | On the MSI: `setx OLLAMA_HOST 0.0.0.0`, restart Ollama, allow port 11434 on Tailscale in Windows Firewall |
| [ ] | G6 TikTok ✓ + Instagram logged in — **HUMAN** | `goals.sh G6` | Meta rejects logins made on the Pi ("wrong password"), so log in from the PC: on the MSI run `python scripts/export-login.py insta` (same for `tiktok` if needed). The user logs in in the window it opens; the script copies the session to the Pi. Fallback: `http://<lane>:8100/login?token=<LANE_TOKEN>` |
| [x] | G7 Pixel on clapper — **HUMAN** | `goals.sh G7` | User plugs in the Pixel 3a and accepts USB debugging; then calibrate (README §3) |
| [x] | G8 PR #2 merged + deployed | `goals.sh G8` | Merge PR #2 (`check-update-recover`), then on each Pi: `~/pi-uploader/scripts/update.sh` |
| [ ] | G9 One successful upload per lane (tiktok ✓ clapper ✓, insta left) | `goals.sh G9` | `POST http://brain/upload` a short test video per platform (README §4); watch `/jobs` |
| [ ] | G10 Password SSH off — do last | `goals.sh G10` | `sudo ~/pi-uploader/scripts/harden-ssh.sh --tailscale` on each Pi, only after G1–G9 pass **and** the clapper SSH blocker is settled (`--tailscale` closes LAN port 22, which is clapper's current workaround) |

## Stack facts

- Repo: github.com/bemor187/pi-uploader. The README is the setup manual; `uploader.env.example` lists the config keys.
- Pis (Pi OS Lite 64-bit, user `bemor`): brain (Pi 5, :80 → 8000), tiktok, insta and clapper (:8100), web (:80), overseer (:8200; Ollama on localhost:11434), plus one spare Pi 4.
- Tailscale IPs: brain 100.92.46.64, tiktok 100.86.13.119, insta 100.112.114.65, clapper 100.112.133.95, web 100.124.240.34, msi 100.67.77.108. MagicDNS names = roles.
- Secrets live only in `/etc/uploader.env` on each Pi. Never commit tokens to this repo.
- Long term, overseer becomes the agent that runs this loop itself (hive-brain: github.com/bemor187/hive-brain).

## Blockers

- **HUMAN — insta offline again** (second time 2026-11-22; back briefly after the user's 20:03 power-cycle). Next step 2.
- **HUMAN — Instagram login.** On the Pi, Instagram sends the login to `auth_platform/challengepicker`, and Meta rejects Facebook logins made on the Pi ("wrong password", no recovery) even though the same login works on phone and web. Use `scripts/export-login.py` from the PC (next step 3).
- **Under-voltage:** overseer's new OS check reports "under-voltage since boot" on brain, tiktok, clapper and overseer (`vcgencmd get_throttled` = 0x50000). Weak power supplies or cables, which may also explain insta dying. HUMAN: use official 5V/3A (Pi 4) or 5V/5A (Pi 5) supplies and short, thick cables. The flag clears on reboot.
- ~~Live uncommitted edits on overseer~~: app.py committed 2026-11-22 21:35; the stale clapper_flow.json was dropped. update.sh is safe on overseer again. Note: that session also left `~/agents.sh` on overseer (20:52, purpose unknown); `~/pi-uploader.corrupt-20261122-2142` can be deleted once nobody needs it.
- **e-paper panel hardware** (refresh never completes). See `docs/epaper.md`.
- **clapper Tailscale SSH is in check mode**, so every session needs a browser re-auth. Workaround: the MSI's `~/.ssh/config` reaches clapper over `clapper.local`. The fix needs the user's OK (next step 5). `setup.sh` runs `tailscale set --ssh`, so re-running bootstrap on clapper turns it back on.

## Open decisions (ask the user; don't build yet)

- **Facebook:** the user's account is a **personal profile**. No Meta API (Postiz included) can post to it, so the only route is a new Playwright `facebook` lane using the PC-login route (`export-login.py` would need a `facebook` entry, plus a new spare Pi or a shared lane Pi).
- **Postiz:** the user's Instagram is a **Creator** account, so Postiz's "Instagram Standalone" provider (Instagram login, `INSTAGRAM_APP_ID`/`SECRET`, no Facebook Page) is a fallback if the insta lane keeps getting checkpointed. It needs Postgres + Redis + Temporal, which is tight on the spare Pi 4 (4 GB). The user has a thumbdrive in the MSI meant for Postiz; its role (spare Pi boot drive?) is unconfirmed.

## Log

- 2026-11-22 18:15: Handoff rewritten for Claude Code: state, numbered next steps, cleaned blockers. Added `scripts/export-login.py`.
- 2026-11-22: All Pis joined Tailscale and SSH works (G1). Earlier the same day, overseer wasn't bootstrapped and the lanes showed offline, so start at G2.
- 2026-11-22: First loop run. G3, G5 and G7 pass. G1 broke because the MSI `~/.ssh/config` mapped hosts to `%h.local` and `tiktok.local` stopped resolving. The config now uses Tailscale names (backup at `~/.ssh/config.bak-20261122`) and G1 passes again. tiktok's SSH host key matches the old `192.168.1.206` entry, which is now web's LAN IP; they may be cloned images with the same host key. Stopped at G2: blocked on sudo (see Blockers).
- 2026-11-22: Loop run 2. **G2:** overseer bootstrap had been dying silently after the Tailscale step: `tailscale status | head -n 5` hit SIGPIPE under pipefail once the tailnet had more than 5 peers. Fixed in 52347ce; overseer and ollama are now active. **G8:** `update.sh` deployed on all 6 Pis. clapper needed a `git pull` first, and 4 Pis needed a second run, because the first run executes the pre-pull copy of update.sh. Removed the `macbook` agent from overseer's AGENTS (that machine isn't on the tailnet). overseer `/health` reports nothing down. Passing now: G1 G2 G3 G5 G7 G8. Next: G4 (OK on ntfy), G6 (HUMAN logins), G9 (OK to make real test posts), G10.
- 2026-11-22: G4 passes. The user approved ntfy.sh and `ALERT_URL` is set on overseer; the user has the topic (it's in overseer's env, not this repo). A test alert was sent. Next: G6 (HUMAN logins), then G9.
- 2026-11-22: TikTok is logged in. Its `/check` gave a false negative (a fixed 8s wait while Studio was still loading); fixed in 6133107 and deployed. Instagram is stuck at a security checkpoint; the user deferred it (see Blockers). Next: G9 for tiktok and clapper, which needs a test video and the user's OK to post publicly.
- 2026-11-22: Clapper hooked up. The Pixel had been plugged into the tiktok and then the insta Pi; now on clapper, adb authorized, Clapper installed (G7). An auto-clicker accessibility service on the phone broke `uiautomator dump`; the user approved switching it off. The lane read stale dumps when uiautomator failed; fixed in 18bcdc5. Clapper has no video share handler, so calibrated `clapper_flow.json` by hand: + -> Video -> Upload -> newest item -> Next -> Next -> caption -> Post (2a1eafc), plus a safe `hide_keyboard` and a fresh mtime on pushed videos so the newest pick is the job's video (6235e17). The flow was walked to the Post screen without posting. Next: G9 test posts (needs the user's OK + video).
- 2026-11-22: **Clapper works end to end.** Job 0fd9f25a065f posted the generated TEST card (checked on the profile; public, the user will delete it). It takes about 7.5 min because the optional confirmation wait runs out its 300 s. TikTok: job 69a63fd05995 failed before posting (a late react-joyride "Got it" tour covered the caption box; fixed in 67b087d). Job 5a84d9d720ed then posted, but as Everyone (TikTok renamed "Only you" to "Only me", so the visibility pick silently failed) and without a caption (see Blockers). Set that post to Only me by hand and removed the temporary `TIKTOK_VISIBILITY` from tiktok's env. G9 now has done jobs for clapper and tiktok; insta is waiting on its login.
- 2026-11-22: TikTok works end to end. The visibility label is now "Who can see this post" (upload page option "Only you"; Studio's list says "Only me"). The lane confirms visibility and caption before posting and refuses to post otherwise (b080905). Test job 927f051f95f8 posted "pipeline test #test" as Only me. `TIKTOK_VISIBILITY` removed again, so posts use the account default. Overseer alerts verified live (insta down, failed tiktok job). Host keys are unique on all reachable Pis. Remaining: insta (HUMAN: power, then login), then G9 insta, then G10.
- 2026-11-22 19:40: **overseer got SSH fleet access** (`overseer/fleet.py`). It already reached every Pi over Tailscale SSH as `bemor` with passwordless sudo, so this was code only, no new access. New checks: `ssh:<host>`, `os:<host>` (disk/mem/temp/under-voltage/units) every 5 min, and `login:<lane>` (lane `/check`) every 6 h. New endpoints: `GET /fleet` and `POST /fleet/<host>/<status|logs|check|restart|update|reboot>`. `AUTO_RESTART` is off by default. Verified live: OS snapshots for 5 Pis, `ssh:insta` down, tiktok logged in, the clapper Pixel OK, bad actions and no-token requests refused. Found under-voltage on 4 Pis (see Blockers).
- 2026-11-22 19:50: e-paper status screen (`overseer/epaper.py`, `scripts/setup-epaper.sh`, `overseer-epaper.service`). Installed on overseer: packages, SPI, and the `epd2in13_V4` driver in `overseer/vendor/` (gitignored). The service is off until the display is attached. PNG preview checked against live `/health`. Power control parked with notes in `docs/power-control.md`.
- 2026-11-22 20:05: e-paper live on overseer (Waveshare 2.13" V4). The first start hung on BUSY, so added a 60 s guard that exits for a systemd restart. Fixed setup-epaper.sh's executable bit.
- 2026-11-22 20:05: insta back after the user's power-cycle (throttled=0x0). G1, G2, G3 and G8 pass, and insta is updated to a3068e0. Playwright + Chromium installed on the MSI. Next: the user runs export-login.py insta (HUMAN). tiktok now shows under-voltage NOW on the e-paper/overseer.
- 2026-11-22 21:20: e-paper: the driver moved to `/usr/local/lib/epaper` (a git clean of /opt/uploader had removed `overseer/vendor/`). The HAT 5V now stays on, with deep sleep between refreshes and a 1 s settle at power-on. Still blocked: the refresh never completes (BUSY stuck high) with V4 and V3, so it's likely the ribbon or HAT seating. Service stopped. Found uncommitted live edits on overseer from another session (see Blockers).
- 2026-11-22 21:35: Committed the other session's live overseer edit (OpenAI-compatible agents in `app.py`). Did NOT commit its `clapper_flow.json`: that's the old uncalibrated template, while clapper's live file matches the calibrated one in git. Ran update.sh on every reachable Pi.
- 2026-11-22 21:46: Every reachable Pi is updated to 19852ab (insta unreachable again, its second outage tonight). overseer rebooted unexpectedly at 21:38, probably an abrupt power-off, which left 12 empty git objects in ~/pi-uploader. Recloned it (old copy at ~/pi-uploader.corrupt-20261122-2142); /etc/uploader.env, overseer.db and the e-paper driver are intact. e-paper still stuck on BUSY after the reboot; service disabled. G4 fails only on 'under-voltage since boot' for brain, clapper and tiktok.
- 2026-11-22 21:55: e-paper diagnosed down to the hardware: no GPIO/SPI conflicts and a clean config.txt; the stock driver `Clear(0xFF)` holds BUSY high for 120+ s while init and SWRESET work. So it's the ribbon, the HAT switch or the panel. The full record is in `docs/epaper.md`. HANDOFF state and next steps rewritten for the handoff.
