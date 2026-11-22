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
| [ ] | G2 Each role's services installed + active | `goals.sh G2` | Re-run bootstrap on that Pi (README §1, §4b). Lanes need brain's `LANE_TOKEN`, overseer needs brain's `API_TOKEN` (`sudo grep TOKEN /etc/uploader.env` on brain) |
| [ ] | G3 brain reaches all lanes | `goals.sh G3` | `journalctl -u uploader-lane@<lane>`; check `LANE_*` URLs in brain's env |
| [ ] | G4 overseer green + ntfy alerts | `goals.sh G4` | Set `ALERT_URL=https://ntfy.sh/<random topic>` in overseer's `/etc/uploader.env`, `sudo systemctl restart overseer`, tell the user the topic so they can subscribe |
| [ ] | G5 overseer can use the MSI's Ollama | `goals.sh G5` | On the MSI: `setx OLLAMA_HOST 0.0.0.0`, restart Ollama, allow port 11434 on Tailscale in Windows Firewall |
| [ ] | G6 TikTok + Instagram logged in — **HUMAN** | `goals.sh G6` | Give the user `http://tiktok:8100/login?token=<LANE_TOKEN>` (then `/login/done?token=…`), same for insta |
| [ ] | G7 Pixel on clapper — **HUMAN** | `goals.sh G7` | User plugs in the Pixel 3a and accepts USB debugging; then calibrate (README §3) |
| [ ] | G8 PR #2 merged + deployed | `goals.sh G8` | Merge PR #2 (`check-update-recover`), then on each Pi: `~/pi-uploader/scripts/update.sh` |
| [ ] | G9 One successful upload per lane | `goals.sh G9` | `POST http://brain/upload` a short test video per platform (README §4); watch `/jobs` |
| [ ] | G10 Password SSH off — do last | `goals.sh G10` | `sudo ~/pi-uploader/scripts/harden-ssh.sh --tailscale` on each Pi, only after G1–G9 pass |

## Stack facts

- Repo: github.com/bemor187/pi-uploader. The README is the setup manual; `uploader.env.example` lists the config keys.
- Pis (Pi OS Lite 64-bit, user `bemor`): brain (Pi 5, :80 → 8000), tiktok, insta and clapper (:8100), web (:80), overseer (:8200; Ollama on localhost:11434), plus one spare Pi 4.
- Tailscale IPs: brain 100.92.46.64, tiktok 100.86.13.119, insta 100.112.114.65, clapper 100.112.133.95, web 100.124.240.34, msi 100.67.77.108. MagicDNS names = roles.
- Secrets live only in `/etc/uploader.env` on each Pi. Never commit tokens to this repo.
- Long term, overseer becomes the agent that runs this loop itself (hive-brain: github.com/bemor187/hive-brain).

## Blockers

- (none logged yet)

## Log

- 2026-11-22: All Pis joined Tailscale and SSH works (G1). Earlier the same day, overseer wasn't bootstrapped and the lanes showed offline, so start at G2.
