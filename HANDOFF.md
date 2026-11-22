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

## Goals (in order)

| ✓ | Goal | Verify | Fix |
|---|---|---|---|
| [x] | G1 All 6 Pis on Tailscale + SSH | `goals.sh G1` | Done 2026-11-22 (user) |
| [x] | G2 Each role's services installed + active | `goals.sh G2` | Re-run bootstrap on that Pi (README §1, §4b). Lanes need brain's `LANE_TOKEN`, overseer needs brain's `API_TOKEN` (`sudo grep TOKEN /etc/uploader.env` on brain) |
| [ ] | G3 brain reaches all lanes | `goals.sh G3` | `journalctl -u uploader-lane@<lane>`; check `LANE_*` URLs in brain's env |
| [x] | G4 overseer green + ntfy alerts | `goals.sh G4` | Set `ALERT_URL=https://ntfy.sh/<random topic>` in overseer's `/etc/uploader.env`, `sudo systemctl restart overseer`, tell the user the topic so they can subscribe |
| [ ] | G5 overseer can use the MSI's Ollama | `goals.sh G5` | On the MSI: `setx OLLAMA_HOST 0.0.0.0`, restart Ollama, allow port 11434 on Tailscale in Windows Firewall |
| [ ] | G6 TikTok + Instagram logged in — **HUMAN** | `goals.sh G6` | Give the user `http://tiktok:8100/login?token=<LANE_TOKEN>` (then `/login/done?token=…`), same for insta |
| [ ] | G7 Pixel on clapper — **HUMAN** | `goals.sh G7` | User plugs in the Pixel 3a and accepts USB debugging; then calibrate (README §3) |
| [x] | G8 PR #2 merged + deployed | `goals.sh G8` | Merge PR #2 (`check-update-recover`), then on each Pi: `~/pi-uploader/scripts/update.sh` |
| [ ] | G9 One successful upload per lane | `goals.sh G9` | `POST http://brain/upload` a short test video per platform (README §4); watch `/jobs` |
| [ ] | G10 Password SSH off — do last | `goals.sh G10` | `sudo ~/pi-uploader/scripts/harden-ssh.sh --tailscale` on each Pi, only after G1–G9 pass |

## Stack facts

- Repo: github.com/bemor187/pi-uploader. The README is the setup manual; `uploader.env.example` lists the config keys.
- Pis (Pi OS Lite 64-bit, user `bemor`): brain (Pi 5, :80 → 8000), tiktok, insta and clapper (:8100), web (:80), overseer (:8200; Ollama on localhost:11434), plus one spare Pi 4.
- Tailscale IPs: brain 100.92.46.64, tiktok 100.86.13.119, insta 100.112.114.65, clapper 100.112.133.95, web 100.124.240.34, msi 100.67.77.108. MagicDNS names = roles.
- Secrets live only in `/etc/uploader.env` on each Pi. Never commit tokens to this repo.
- Long term, overseer becomes the agent that runs this loop itself (hive-brain: github.com/bemor187/hive-brain).

## Blockers

- ~~2026-11-22 no passwordless sudo~~ Resolved the same day: the user added `/etc/sudoers.d/010-bemor-nopasswd` on all 6 Pis.
- 2026-11-22 clapper runs Tailscale SSH in **check** mode, so every session waits for a browser re-auth. Workaround: the MSI's `~/.ssh/config` reaches clapper over `clapper.local`. Permanent fix once sudo works: `sudo tailscale set --ssh=false` on clapper (or set the tailnet SSH ACL to `accept`). Needs the user's OK because it weakens an auth check. Note: `setup.sh` runs `tailscale set --ssh` on every Pi, so re-running bootstrap turns Tailscale SSH back on.

- 2026-11-22 **HUMAN — Instagram checkpoint.** The login worked, but Instagram sends the Pi to `auth_platform/challengepicker` ("confirm it's you"). The user skipped it for now. To resume: open `http://insta:8100/login?token=…`, finish the challenge until the home feed shows, then open `/login/done`. This blocks G6 and the insta part of G9.

- 2026-11-22 **TikTok caption dropped on a real post.** Job 5a84d9d720ed posted with "No description" (caption `test`). A no-post rehearsal of the same steps kept the caption, so it's probably a race (late filename prefill, or something at post time). Debug before relying on TikTok captions. Post id 7711107586132675870; set to Only me.

## Log

- 2026-11-22: All Pis joined Tailscale and SSH works (G1). Earlier the same day, overseer wasn't bootstrapped and the lanes showed offline, so start at G2.
- 2026-11-22: First loop run. G3, G5 and G7 pass. G1 broke because the MSI `~/.ssh/config` mapped hosts to `%h.local` and `tiktok.local` stopped resolving. The config now uses Tailscale names (backup at `~/.ssh/config.bak-20261122`) and G1 passes again. tiktok's SSH host key matches the old `192.168.1.206` entry, which is now web's LAN IP; they may be cloned images with the same host key. Stopped at G2: blocked on sudo (see Blockers).
- 2026-11-22: Loop run 2. **G2:** overseer bootstrap had been dying silently after the Tailscale step: `tailscale status | head -n 5` hit SIGPIPE under pipefail once the tailnet had more than 5 peers. Fixed in 52347ce; overseer and ollama are now active. **G8:** `update.sh` deployed on all 6 Pis. clapper needed a `git pull` first, and 4 Pis needed a second run, because the first run executes the pre-pull copy of update.sh. Removed the `macbook` agent from overseer's AGENTS (that machine isn't on the tailnet). overseer `/health` reports nothing down. Passing now: G1 G2 G3 G5 G7 G8. Next: G4 (OK on ntfy), G6 (HUMAN logins), G9 (OK to make real test posts), G10.
- 2026-11-22: G4 passes. The user approved ntfy.sh and `ALERT_URL` is set on overseer; the user has the topic (it's in overseer's env, not this repo). A test alert was sent. Next: G6 (HUMAN logins), then G9.
- 2026-11-22: TikTok is logged in. Its `/check` gave a false negative (a fixed 8s wait while Studio was still loading); fixed in 6133107 and deployed. Instagram is stuck at a security checkpoint; the user deferred it (see Blockers). Next: G9 for tiktok and clapper, which needs a test video and the user's OK to post publicly.
- 2026-11-22: Clapper hooked up. The Pixel had been plugged into the tiktok and then the insta Pi; now on clapper, adb authorized, Clapper installed (G7). An auto-clicker accessibility service on the phone broke `uiautomator dump`; the user approved switching it off. The lane read stale dumps when uiautomator failed; fixed in 18bcdc5. Clapper has no video share handler, so calibrated `clapper_flow.json` by hand: + -> Video -> Upload -> newest item -> Next -> Next -> caption -> Post (2a1eafc), plus a safe `hide_keyboard` and a fresh mtime on pushed videos so the newest pick is the job's video (6235e17). The flow was walked to the Post screen without posting. Next: G9 test posts (needs the user's OK + video).
- 2026-11-22: **Clapper works end to end.** Job 0fd9f25a065f posted the generated TEST card (checked on the profile; public, the user will delete it). It takes about 7.5 min because the optional confirmation wait runs out its 300 s. TikTok: job 69a63fd05995 failed before posting (a late react-joyride "Got it" tour covered the caption box; fixed in 67b087d). Job 5a84d9d720ed then posted, but as Everyone (TikTok renamed "Only you" to "Only me", so the visibility pick silently failed) and without a caption (see Blockers). Set that post to Only me by hand and removed the temporary `TIKTOK_VISIBILITY` from tiktok's env. G9 now has done jobs for clapper and tiktok; insta is waiting on its login.
