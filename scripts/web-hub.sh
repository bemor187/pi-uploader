#!/usr/bin/env bash
# web Pi: deploy the PI//GRID hub and (re)generate its nginx token includes + hive-brain feed.
# Called by setup.sh web and update.sh; safe to re-run any time (idempotent).
#   sudo /opt/uploader/scripts/web-hub.sh            # deploy site + includes + hive feed, reload nginx
#   sudo /opt/uploader/scripts/web-hub.sh --hive     # just refresh the hive feed (the timer runs this)
#
# Optional lines in /etc/uploader.env on web (all optional; the hub degrades without them):
#   API_TOKEN=<brain's>     -> dashboard can read brain /jobs (GET only via nginx)
#   TASK_TOKEN=<overseer's> -> dashboard can read overseer /fleet (GET only via nginx)
#   HIVE_TOKEN=<GitHub fine-grained token, read-only Contents on bemor187/hive-brain>
#       or put a read-only deploy key at /etc/web-hub/hive_deploy_key instead
#   WEB_TAILNET=tail85ba4a.ts.net   (auto-detected from tailscale when unset)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
APP="${APP:-/opt/uploader}"
ENVF="${ENVF:-/etc/uploader.env}"
WEB="${WEB_ROOT:-/srv/web}"
INC="${NGINX_INC:-/etc/nginx/web-hub}"
HIVE_REPO="${HIVE_REPO:-bemor187/hive-brain}"
HIVE_DIR=/var/cache/web-hub/hive-brain
RUN_USER="${RUN_USER:-${SUDO_USER:-$(stat -c %U "$WEB" 2>/dev/null || echo root)}}"
envget() { [[ -f $ENVF ]] && grep -m1 "^$1=" "$ENVF" | cut -d= -f2- | tr -d '"'"'"' \r' || true; }
usable() { [[ -n $1 && $1 != change-me* && $1 =~ ^[A-Za-z0-9._~+/=-]{16,}$ ]]; }   # no quotes/semicolons: safe in nginx

hive() {
  local tok key out="$WEB/hub/hive.json"
  tok="$(envget HIVE_TOKEN)"; key=/etc/web-hub/hive_deploy_key
  mkdir -p "$WEB/hub" /var/cache/web-hub
  if usable "$tok"; then
    local hdr; hdr="Authorization: Basic $(printf 'x-access-token:%s' "$tok" | base64 -w0)"
    export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.extraHeader GIT_CONFIG_VALUE_0="$hdr" GIT_TERMINAL_PROMPT=0
    local url="https://github.com/$HIVE_REPO.git"
  elif [[ -f $key ]]; then
    export GIT_SSH_COMMAND="ssh -i $key -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
    local url="git@github.com:$HIVE_REPO.git"
  else
    rm -f "$out"; echo "hive feed: off (no HIVE_TOKEN or $key)"; return 0
  fi
  if [[ -d $HIVE_DIR/.git ]]; then
    git -C "$HIVE_DIR" fetch -q --depth 1 origin HEAD && git -C "$HIVE_DIR" reset -q --hard FETCH_HEAD
  else
    rm -rf "$HIVE_DIR"; git clone -q --depth 1 "$url" "$HIVE_DIR"
  fi || { echo "hive feed: fetch failed (token/key valid? repo $HIVE_REPO)"; return 0; }
  chmod 700 /var/cache/web-hub
  python3 "$APP/web/tools/hive_render.py" "$HIVE_DIR" "$out" && chmod 644 "$out" && echo "hive feed: $(git -C "$HIVE_DIR" log -1 --format=%h)"
}

if [[ ${1:-} == --hive ]]; then hive; exit 0; fi

echo "==> web hub: site -> $WEB"
mkdir -p "$WEB/games" "$WEB/files" "$WEB/hub"
# hub-owned folders are replaced wholesale; games/, files/ and anything else you add are never touched
for d in assets dash queue tdt; do
  rm -rf "$WEB/.$d.new"; cp -a "$APP/web/site/$d" "$WEB/.$d.new"
  rm -rf "$WEB/$d"; mv "$WEB/.$d.new" "$WEB/$d"
done
# index.html: install if missing, still the old starter, or a previous hub copy; a hand-made page is kept
if [[ ! -f $WEB/index.html ]] || grep -q -e 'pi-web-hub' -e "setup.sh only writes it when it's missing" "$WEB/index.html"; then
  cp "$APP/web/site/index.html" "$WEB/index.html"
else
  echo "keeping your custom $WEB/index.html (the hub is still at /dash/, /queue/ and /tdt/)"
fi
chown -R "$RUN_USER:$RUN_USER" "$WEB"

echo "==> web hub: nginx includes -> $INC (tokens stay root-only)"
install -d -m 700 "$INC"
suffix="$(envget WEB_TAILNET)"
if [[ -z $suffix ]] && command -v tailscale >/dev/null; then
  suffix="$(tailscale status --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("MagicDNSSuffix",""))' 2>/dev/null || true)"
fi
suffix="${suffix#.}"; [[ $suffix =~ ^[A-Za-z0-9.-]*$ ]] || suffix=""
umask 077
printf 'set $hub_suffix "%s";\n' "${suffix:+.$suffix}" > "$INC/env.conf"
api="$(envget API_TOKEN)"; task="$(envget TASK_TOKEN)"; b=false; o=false
if usable "$api"; then printf 'proxy_set_header Authorization "Bearer %s";\n' "$api" > "$INC/brain-auth.conf"; b=true; else rm -f "$INC/brain-auth.conf"; fi
if usable "$task"; then printf 'proxy_set_header Authorization "Bearer %s";\n' "$task" > "$INC/overseer-auth.conf"; o=true; else rm -f "$INC/overseer-auth.conf"; fi
umask 022
printf '{"brain_token":%s,"overseer_token":%s,"tailnet":"%s","deployed":"%s"}\n' "$b" "$o" "$suffix" "$(date '+%Y-%m-%d %H:%M %Z')" > "$WEB/hub/config.json"
echo "tailnet suffix: ${suffix:-<none: set WEB_TAILNET in $ENVF>}  brain /jobs: $([[ $b == true ]] && echo on || echo 'off (add API_TOKEN)')  overseer /fleet: $([[ $o == true ]] && echo on || echo 'off (add TASK_TOKEN)')"

hive

# refresh the hive feed every 15 min
if [[ -d /etc/systemd/system && ${WEB_HUB_NO_TIMER:-0} != 1 ]]; then
  cp "$APP/systemd/web-hub-hive.service" "$APP/systemd/web-hub-hive.timer" /etc/systemd/system/
  systemctl daemon-reload && systemctl enable --now web-hub-hive.timer >/dev/null 2>&1 || true
fi
