#!/usr/bin/env bash
# One-shot setup for a Pi in the uploader cluster.
#   scp -r pi-uploader <user>@<pi>.local:~
#   ssh <user>@<pi>.local
#   cd pi-uploader && sudo ./scripts/setup.sh brain|tiktok|insta|clapper|web|overseer
#
# Tokens: on brain, leave them unset and the script generates both and prints them.
# On the lanes, pass the same LANE_TOKEN:  sudo LANE_TOKEN=xxxx ./scripts/setup.sh tiktok
# On overseer, pass brain's API_TOKEN:      sudo API_TOKEN=xxxx ./scripts/setup.sh overseer
# web needs no token. Add FUNNEL=1 on brain or web to publish it over public HTTPS.
set -euo pipefail

ROLE="${1:-}"
ROLES="brain|tiktok|insta|clapper|web|overseer"
case "$ROLE" in brain|tiktok|insta|clapper|web|overseer) ;; *) echo "usage: sudo $0 $ROLES"; exit 1;; esac
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
# keep this Pi's calibrated Clapper steps on re-runs (the repo copy is only a first guess)
KEEP_FLOW=(); [[ -f "$APP/lanes/clapper/clapper_flow.json" ]] && KEEP_FLOW=(--exclude lanes/clapper/clapper_flow.json)
rsync -a --delete --exclude venv "${KEEP_FLOW[@]}" "$SRC/" "$APP/"
if [[ $ROLE != web ]]; then   # web runs no Python
  python3 -m venv "$APP/venv"
  "$APP/venv/bin/pip" install -q --upgrade pip
fi
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
env_default() { grep -q "^$1=" "$ENVF" || echo "$1=$2" >> "$ENVF"; }   # add only if missing

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
  web)
    step "web: nginx static host (HTML games + files)"
    apt-get install -y nginx
    mkdir -p /srv/web/games /srv/web/files
    [[ -f /srv/web/index.html ]] || cp "$APP/web/site/index.html" /srv/web/index.html
    chown -R "$RUN_USER:$RUN_USER" /srv/web
    grep -q 'application/wasm' /etc/nginx/mime.types || \
      sed -i 's|^}|    application/wasm                      wasm;\n}|' /etc/nginx/mime.types
    cp "$APP/web/nginx-web.conf" /etc/nginx/sites-available/web
    ln -sf /etc/nginx/sites-available/web /etc/nginx/sites-enabled/web
    rm -f /etc/nginx/sites-enabled/default
    nginx -t
    if [[ "${FUNNEL:-0}" == 1 ]]; then
      step "Tailscale Funnel: public HTTPS -> web"
      tailscale funnel --bg 80 || echo "Funnel failed: enable HTTPS + Funnel for this node in the Tailscale admin console, then: sudo tailscale funnel --bg 80"
      tailscale funnel status || true
    fi
    UNIT=nginx.service
    ;;
  overseer)
    step "overseer: API + monitor"
    "$APP/venv/bin/pip" install -q -r "$APP/overseer/requirements.txt"
    mkdir -p /var/lib/overseer && chown "$RUN_USER:$RUN_USER" /var/lib/overseer
    if [[ -n "${API_TOKEN:-}" ]]; then set_env API_TOKEN "$API_TOKEN"; fi
    grep -q '^API_TOKEN=change-me$' "$ENVF" && echo "WARNING: API_TOKEN not set; re-run with API_TOKEN=<brain's> to enable job alerts/retry"
    grep -Eq '^TASK_TOKEN=.{16,}' "$ENVF" && ! grep -q '^TASK_TOKEN=change-me' "$ENVF"       || set_env TASK_TOKEN "$(openssl rand -hex 24)"
    env_default AGENTS "msi=ollama:http://msi:11434|qwen3:14b,macbook=ollama:http://macbook:11434,local=ollama:http://127.0.0.1:11434|qwen2.5:1.5b"
    env_default BRAIN_URL http://brain
    env_default SITES "web=http://web/health"
    env_default ALERT_URL ""
    env_default OLLAMA_MODEL qwen2.5:1.5b

    step "overseer: Ollama (localhost only, one model, one request at a time)"
    command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
    mkdir -p /etc/systemd/system/ollama.service.d
    cat > /etc/systemd/system/ollama.service.d/override.conf <<'OLL'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_KEEP_ALIVE=30m"
OLL
    systemctl daemon-reload && systemctl enable ollama && systemctl restart ollama
    for _ in $(seq 30); do curl -fs http://127.0.0.1:11434/api/tags >/dev/null && break; sleep 1; done
    MODEL="$(grep -m1 '^OLLAMA_MODEL=' "$ENVF" | cut -d= -f2)"
    ollama pull "${MODEL:-qwen2.5:1.5b}"
    add_swap
    UNIT=overseer.service
    sed "s/__USER__/$RUN_USER/" "$APP/systemd/overseer.service" > /etc/systemd/system/$UNIT
    ;;
esac

if [[ $ROLE == tiktok || $ROLE == insta || $ROLE == clapper ]]; then
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
[[ $UNIT == nginx.service ]] && systemctl reload nginx                        # pick up the web site config
step "Nightly backup (pi-backup.timer) -> /var/backups/pi-stack, copy sent to overseer"
cp "$APP/systemd/pi-backup.service" "$APP/systemd/pi-backup.timer" /etc/systemd/system/
if [[ $ROLE == overseer || $ROLE == brain ]]; then
  # overseer collects everyone's backups; brain collects overseer's
  cp "$APP/systemd/pi-backup-receiver.service" /etc/systemd/system/
  systemctl daemon-reload && systemctl enable --now pi-backup-receiver.service
fi
systemctl daemon-reload && systemctl enable --now pi-backup.timer
sleep 3
systemctl --no-pager --lines=5 status "$UNIT" || true
echo
echo "Done: $ROLE is set up. Tailscale IP: $(tailscale ip -4 2>/dev/null | head -1)"
if [[ $ROLE == overseer ]]; then
  echo
  systemctl --no-pager is-active ollama overseer || true
  curl -fsS --retry 5 --retry-delay 2 --retry-connrefused http://127.0.0.1:8200/health >/dev/null && echo "overseer /health: OK" || echo "overseer /health: NOT responding (journalctl -u overseer)"
  echo "TASK_TOKEN=$(grep -m1 '^TASK_TOKEN=' "$ENVF" | cut -d= -f2)   <- for POST http://overseer:8200/task"
  echo "Edit $ENVF (ALERT_URL=https://ntfy.sh/<topic>, AGENTS, BRAIN_URL), then: sudo systemctl restart overseer"
  echo "Status page: http://overseer:8200/"
fi
if [[ $ROLE == web ]]; then
  curl -fsS http://127.0.0.1/health >/dev/null && echo "web /health: OK" || echo "web /health: NOT responding (journalctl -u nginx)"
  echo "Put games in /srv/web/games/<name>/ and files in /srv/web/files/, e.g. from another tailnet machine:"
  echo "  rsync -av mygame/ $RUN_USER@web:/srv/web/games/mygame/"
  echo "Browse: http://web/"
fi
