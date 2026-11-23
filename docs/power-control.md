# Power control: notes for later (parked 2026-11-22)

Goal: overseer can power-cycle a Pi that is hung, or that has lost power, without a human.
Today it can only `POST /fleet/<host>/reboot` over SSH (see `overseer/fleet.py`). That needs the Pi to still answer SSH.
On 2026-11-22 insta went fully dark (no ping or SSH, Tailscale offline), and only a human could bring it back.

## What we know
- **Under-voltage:** brain, tiktok, clapper and overseer report "under-voltage since boot" (`vcgencmd get_throttled` = `0x50000`).
  Fix the supplies before adding switching: official 5V/3A for a Pi 4, 5V/5A (27W) for the Pi 5, with short, thick cables.
  overseer's `os:<host>` check flags this, and the flag clears on reboot.
- **Hardware on hand:** breadboards, assorted Pi HATs (models not yet listed), and a Waveshare 2.13" e-paper. The e-paper is used for the status screen; see README "e-paper status screen".
- Physical layout not yet confirmed: are all the Pis within a short wire of overseer?

## Options, cheapest first
| # | Option | Cost | Fixes hang | Fixes lost power | Notes |
|---|---|---|---|---|---|
| 1 | Hardware watchdog: `dtparam=watchdog=on` in `/boot/firmware/config.txt` + `RuntimeWatchdogSec=15` in `/etc/systemd/system.conf` | free | yes (self) | no | Needs a reboot per Pi; ask the user first. Easiest win. |
| 2 | SSH `reboot` action (done) | free | partly | no | Only if SSH still answers. |
| 3 | GPIO reset wire: overseer GPIO -> transistor/optocoupler -> target's reset (Pi 4: 2-pin **RUN** header; Pi 5: **J2** power-button pads; short = boot, long = shutdown) | ~free | yes | no | Short wires plus a shared ground, or an optocoupler. Can't help a Pi that has lost power. |
| 4 | Relay on each Pi's 5V USB-C line (relay HAT/module on overseer + USB-C breakouts) | ~$10–20 | yes | yes | Switch the low-voltage DC side only. **Never switch mains on a breadboard.** Common relay HATs have 3–4 channels, so 5 Pis need two boards. |
| 5 | Local-API smart plug per Pi: TP-Link Kasa EP10/KP115 (`python-kasa`) or Tasmota/Athom (HTTP `cm?cmnd=Power%20Off`) | ~$10–20 each | yes | yes | No cloud; overseer calls it over the LAN. |
| 6 | Smart strip with per-outlet control: Kasa HS300 (6 outlets) | ~$50–60 | yes | yes | One device for the whole rack. Best value if not building. |

PoE with a managed switch was rejected: it needs a HAT on every Pi and costs much more.

**Blind spot in every option:** overseer can't power-cycle itself. Have brain watch overseer, using the same mechanism in reverse.

## Planned overseer integration (whichever hardware)
- New `overseer/power.py` with one function, `cycle(host)`, plus a `POWER` env map, e.g. `POWER=insta=kasa:192.168.1.50,tiktok=gpio:17`.
- In `fleet.py`: when `ssh:<host>` has been down 10 min **and** the matching lane/brain check is down, power-cycle at most once an hour per host, then send an ntfy alert. Also add a `power` action to `POST /fleet/<host>/<action>`.
- Never cycle a Pi while brain shows a job `running` on that lane (a half-made post). Check `GET brain/jobs` first.

## To resume
1. Ask the user for the HAT models, the physical layout, and the budget (build vs. buy).
2. Apply option 1 (watchdog) on each Pi with the user's OK, one Pi at a time; clapper last.
3. Pick 3/4 (build) or 5/6 (buy), then implement `power.py` as above. Test on web first: it has nothing in flight.
