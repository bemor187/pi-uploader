#!/usr/bin/env bash
# Waveshare 2.13" e-paper status screen on overseer (README "e-paper status screen").
#   sudo ~/pi-uploader/scripts/setup-epaper.sh           # deps, SPI, driver, unit (service left OFF)
#   sudo ~/pi-uploader/scripts/setup-epaper.sh --enable  # also start it; only with the display attached
# The driver must match the sticker on the display: set EPD_DRIVER=epd2in13_V4 (or _V2, _V3,
# epd2in13b_V4 ...) in /etc/uploader.env. With no display attached the driver can hang on BUSY.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
U="${SUDO_USER:-$(logname)}"
APP=/opt/uploader
DRIVER="${EPD_DRIVER:-$(grep -m1 '^EPD_DRIVER=' /etc/uploader.env 2>/dev/null | cut -d= -f2 || true)}"
DRIVER="${DRIVER:-epd2in13_V4}"

echo "== packages"
apt-get install -y -q python3-pil python3-spidev python3-gpiozero python3-lgpio fonts-dejavu-core >/dev/null

echo "== SPI"
REBOOT=0
if [[ ! -e /dev/spidev0.0 ]]; then
  raspi-config nonint do_spi 0
  modprobe spi_bcm2835 2>/dev/null || true
  udevadm settle 2>/dev/null || sleep 2
  [[ -e /dev/spidev0.0 ]] || REBOOT=1
fi
usermod -aG spi,gpio "$U"

echo "== driver $DRIVER"
V="$APP/overseer/vendor/waveshare_epd"
mkdir -p "$V"
RAW=https://raw.githubusercontent.com/waveshareteam/e-Paper/master/RaspberryPi_JetsonNano/python/lib/waveshare_epd
curl -fsSL "$RAW/epdconfig.py" -o "$V/epdconfig.py"
curl -fsSL "$RAW/$DRIVER.py" -o "$V/$DRIVER.py"
[[ -f "$V/__init__.py" ]] || touch "$V/__init__.py"
chown -R "$U:$U" "$APP/overseer/vendor"

echo "== service"
sed "s/__USER__/$U/" "$APP/systemd/overseer-epaper.service" > /etc/systemd/system/overseer-epaper.service
systemctl daemon-reload
if [[ "${1:-}" == --enable ]]; then
  [[ $REBOOT == 1 ]] && { echo "SPI needs a reboot first: sudo reboot, then re-run with --enable"; exit 1; }
  systemctl enable --now overseer-epaper
  echo "started; watch: journalctl -u overseer-epaper -f"
else
  echo "installed but OFF. Attach the display (power off first), then: sudo $0 --enable"
fi
[[ $REBOOT == 1 ]] && echo "NOTE: SPI was just enabled and needs a reboot."
exit 0
