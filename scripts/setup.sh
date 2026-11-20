#!/usr/bin/env bash
# One-shot setup for a Pi in the uploader cluster.
#   scp -r pi-uploader <user>@<pi>.local:~
#   ssh <user>@<pi>.local
#   cd pi-uploader && sudo ./scripts/setup.sh brain|tiktok|insta|clapper
#
# Tokens: on brain, leave them unset and the script generates both and prints them.
# On the lanes, pass the same LANE_TOKEN:  sudo LANE_TOKEN=xxxx ./scripts/setup.sh tiktok
set -euo pipefail

ROLE="${1:-}"
case "$ROLE" in brain|tiktok|insta|clapper) ;; *) echo "usage: sudo $0 brain|tiktok|insta|clapper"; exit 1;; esac
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
RUN_USER="${SUDO_USER:-$(logname)}"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/uploader
ENVF=/etc/uploader.env
step() { echo; echo "==> $*"; }

step "System packages"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get full-upgrade -y
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip curl git rsync ufw

step "Tailscale"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
if ! tailscale status >/dev/null 2>&1; then
  echo "Open the URL below (phone is fine) to join this Pi ($ROLE) to your tailnet:"
  tailscale up --hostname="$ROLE" --ssh
else
  tailscale set --ssh   # Tailscale SSH: manage the Pi from any tailnet device, no keys to copy
fi
tailscale status | head -n 5

step "App code -> $APP"
mkdir -p "$APP"
rsync -a --delete --exclude venv "$SRC/" "$APP/"
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
chown -R "$RUN_USER:$RUN_USER" "$APP"

step "Config $ENVF"
if [[ ! -f $ENVF ]]; then
  API_TOKEN="${API_TOKEN:-$(openssl rand -hex 24)}"
  LANE_TOKEN="${LANE_TOKEN:-$(openssl rand -hex 24)}"
  sed -e "s/^API_TOKEN=.*/API_TOKEN=$API_TOKEN/" -e "s/^LANE_TOKEN=.*/LANE_TOKEN=$LANE_TOKEN/" \
      "$APP/uploader.env.example" > "$ENVF"
  chmod 640 "$ENVF"; chown root:"$RUN_USER" "$ENVF"
  [[ $ROLE == brain ]] && { echo "API_TOKEN=$API_TOKEN"; echo "LANE_TOKEN=$LANE_TOKEN   <- pass this to each lane's setup"; }
else
  echo "$ENVF exists; leaving it alone"
fi
set_env() { grep -q "^$1=" "$ENVF" && sed -i "s|^$1=.*|$1=$2|" "$ENVF" || echo "$1=$2" >> "$ENVF"; }

add_swap() {
  if command -v dphys-swapfile >/dev/null; then
    step "Swap -> 2 GB (dphys-swapfile)"
    dphys-swapfile swapoff || true
    sed -i 's/^#\?CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
    sed -i 's/^#\?CONF_MAXSWAP=.*/CONF_MAXSWAP=2048/' /etc/dphys-swapfile
    dphys-swapfile setup && dphys-swapfile swapon
  else
    echo "dphys-swapfile not present (newer Pi OS uses zram); current swap:"; swapon --show || true
  fi
}

LAUNCHER=""
case "$ROLE" in
  brain)
    step "brain: API + nginx"
    "$APP/venv/bin/pip" install -q -r "$APP/brain/requirements.txt"
    apt-get install -y nginx
    mkdir -p /var/lib/uploader && chown "$RUN_USER:$RUN_USER" /var/lib/uploader
    cp "$APP/nginx/uploader.conf" /etc/nginx/sites-available/uploader
    ln -sf /etc/nginx/sites-available/uploader /etc/nginx/sites-enabled/uploader
    rm -f /etc/nginx/sites-enabled/default
    nginx -t && systemctl enable --now nginx && systemctl reload nginx
    if [[ "${FUNNEL:-0}" == 1 ]]; then
      step "Tailscale Funnel: public HTTPS -> brain (API_TOKEN required on every request)"
      tailscale funnel --bg 80 || echo "Funnel failed: enable HTTPS + Funnel for this node in the Tailscale admin console, then: sudo tailscale funnel --bg 80"
      tailscale funnel status || true
    fi
    UNIT=uploader-brain.service
    sed "s/__USER__/$RUN_USER/" "$APP/systemd/uploader-brain.service" > /etc/systemd/system/$UNIT
    ;;
  tiktok|insta)
    step "$ROLE: Playwright + Chromium"
    "$APP/venv/bin/pip" install -q fastapi "uvicorn[standard]" python-multipart playwright
    apt-get install -y xvfb x11vnc novnc python3-websockify
    if sudo -u "$RUN_USER" "$APP/venv/bin/playwright" install chromium && \
       "$APP/venv/bin/playwright" install-deps chromium; then
      echo "Playwright Chromium installed"
    else
      echo "Playwright's Chromium failed on this OS; falling back to Debian's chromium package"
      apt-get install -y chromium
      set_env CHROMIUM_PATH /usr/bin/chromium
    fi
    sudo -u "$RUN_USER" mkdir -p "$RUN_HOME/uploader-state" "$RUN_HOME/uploader-profiles" "$RUN_HOME/uploader-work"
    grep -q '^HEADLESS=0' "$ENVF" && LAUNCHER="/usr/bin/xvfb-run -a"
    add_swap
    ;;
  clapper)
    step "clapper: ADB"
    "$APP/venv/bin/pip" install -q fastapi "uvicorn[standard]" python-multipart
    apt-get install -y adb
    # Google vendor id so the Pixel is accessible without root
    echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="18d1", MODE="0660", GROUP="plugdev"' > /etc/udev/rules.d/51-android.rules
    udevadm control --reload-rules && udevadm trigger
    usermod -aG plugdev "$RUN_USER"
    sudo -u "$RUN_USER" mkdir -p "$RUN_HOME/uploader-work"
    ;;
esac

if [[ $ROLE != brain ]]; then
  UNIT="uploader-lane@$ROLE.service"
  sed -e "s/__USER__/$RUN_USER/" -e "s|__LAUNCHER__ |${LAUNCHER}${LAUNCHER:+ }|" \
      "$APP/systemd/uploader-lane@.service" > /etc/systemd/system/uploader-lane@.service
fi

step "Firewall: SSH from anywhere on LAN, everything else only over Tailscale"
ufw allow 22/tcp >/dev/null
ufw allow in on tailscale0 >/dev/null
ufw --force enable

step "Enable $UNIT"
systemctl daemon-reload
systemctl enable --now "$UNIT"
sleep 3
systemctl --no-pager --lines=5 status "$UNIT" || true
echo
echo "Done: $ROLE is set up. Tailscale IP: $(tailscale ip -4 2>/dev/null | head -1)"
