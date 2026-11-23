# e-paper status screen: status and debugging record

**Status (2026-11-22 21:55): blocked on hardware.** The code is done and deployed on overseer, and `overseer-epaper.service` is **disabled**.
The panel accepts commands, but every screen refresh hangs: BUSY goes high and never comes back down.

## What it is
- Display: **Waveshare 2.13" V4** (black/white, 250x122), plugged onto overseer's (Pi 4) 40-pin header.
- Code: `overseer/epaper.py` reads overseer's `GET /health` and draws one row per Pi (PI/OS/AP/LG) plus the issues list.
  `python3 /opt/uploader/overseer/epaper.py --png /tmp/e.png` renders a preview with no display; the layout is verified.
- Install: `scripts/setup-epaper.sh` installs the packages, enables SPI, puts the driver in `/usr/local/lib/epaper/waveshare_epd`, and installs the unit.
  The driver lives outside `/opt/uploader` on purpose: a git clean there deleted the old `overseer/vendor/` copy.
- Pins (Waveshare HAT standard): RST GPIO17, DC GPIO25, CS GPIO8 (CE0), BUSY GPIO24, PWR GPIO18, SPI0.

## Timeline
| Time | What happened |
|---|---|
| ~19:59–20:02 | Draws **completed**: about 2.2 s each, BUSY released, "drew" logged. Unknown whether the glass actually changed; the user later said it "isn't drawing". |
| 20:43–20:52 | Another session worked on overseer (made `/opt/uploader` a git clone; the driver dir vanished). |
| 21:13 onward | Every refresh hangs on BUSY, including with the **stock** Waveshare driver calls (init, Clear, sleep). |
| 21:38 | overseer rebooted (probably an abrupt power-off). Still hangs afterwards. |

## Tests done (all on overseer)
- **No conflicts:** nothing else holds `/dev/gpiochip0` or `/dev/spidev0.0`; `config.txt` is clean (`dtparam=spi=on`, no conflicting overlays); no other unit or cron touches the display.
- **Raw pins:** BUSY reads 1 with PWR off and PWR on, then drops to 0 after a RST pulse. So the panel controller is alive and responds to reset.
  BUSY reading 1 with PWR "off" suggests this HAT revision may not actually switch panel power on GPIO18.
- **Init:** reset, then BUSY releases instantly; SWRESET (0x12), then BUSY releases in about 10 ms; the init commands go through.
- **Refresh:** `TurnOnDisplay` (0x22/0x20) sets BUSY high and it **stays high for 120+ s** (a normal full refresh is about 2 s). This happens with `Clear(0xFF)` alone, and with the V4 and V3 drivers.
- Power: `vcgencmd get_throttled` = 0x0 on overseer now (it showed "under-voltage since boot" earlier tonight, before the reboot).

**Conclusion:** commands reach the controller, but the panel's refresh (charge pump/driving the glass) never completes.
That points to the **flex ribbon between the glass and the HAT board**, or the HAT's **Display Config** switch, or a damaged panel. It is not our code, since the stock calls fail the same way.

## Next steps (HUMAN first)
1. Power overseer **off cleanly** (`sudo poweroff`, wait for the green LED to stop) before touching the hardware. Yanking power at 21:38 corrupted files.
2. **Ribbon:** open the HAT's FPC connector latch, reseat the glass's flex cable fully (contacts facing the right way, square), and close the latch.
3. **Switches:** on the universal "e-Paper Driver HAT", set **Display Config = B** and **Interface Config = 0** (4-wire SPI). The dedicated "2.13inch e-Paper HAT (V4)" has none. A **photo** of both sides of the board would identify which one this is.
4. Check the HAT sits on all 40 pins, not shifted by a row.
5. Then test (as an agent):
   ```bash
   ssh bemor@overseer 'cd /tmp && timeout 60 python3 -c "
   import sys; sys.path.insert(0, \"/usr/local/lib/epaper\")
   from waveshare_epd import epd2in13_V4 as m; e = m.EPD(); e.init(); e.Clear(0xFF); e.sleep(); print(\"OK\")"'
   ```
   `OK` within about 5 s plus a visible flash means it's fixed. Then `sudo systemctl enable --now overseer-epaper` and check `journalctl -u overseer-epaper` for `drew:`.
6. If it still hangs after reseating: try the official Waveshare demo (`examples/epd_2in13_V4_test.py` from github.com/waveshareteam/e-Paper), then suspect a damaged panel or ribbon and contact Waveshare or replace it.

## Code notes for whoever resumes
- `epaper.py` keeps the HAT's 5V on between refreshes and uses the panel's own deep sleep (0x10/0x01) instead of `EPD.sleep()`, which also cuts the 5V. It adds a 1 s settle at first power-on and closes SPI before each `init()`. This change was made **while** debugging and is untested on a working panel. If it misbehaves once the hardware is fixed, go back to the stock `e.init(); e.display(buf); e.sleep()`.
- A 30 s SIGALRM guard exits the process if BUSY sticks, and systemd restarts it after 30 s.
- `update.sh` restarts `overseer-epaper` only if it's enabled.
