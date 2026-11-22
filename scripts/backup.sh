#!/usr/bin/env bash
# Back up what can't be re-created by bootstrap: config, tokens, logins, calibration, data.
#   sudo ~/pi-uploader/scripts/backup.sh            # this Pi -> /var/backups/pi-stack/ (+ send to overseer)
# A nightly timer (pi-backup.timer, installed by setup.sh) runs it. Each Pi keeps its last 7,
# and sends a copy to overseer with Taildrop (`tailscale file cp`), so a dead SD card loses nothing.
# overseer files received copies under /var/backups/pi-stack/<host>/ and sends its own to brain.
# Restore on a freshly bootstrapped Pi: sudo ~/pi-uploader/scripts/restore.sh <file.tgz>
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
HOST="$(hostname)"
U="${SUDO_USER:-$(getent passwd 1000 | cut -d: -f1)}"
H="$(getent passwd "$U" | cut -d: -f6)"
OUT=/var/backups/pi-stack
KEEP="${KEEP:-7}"
SEND_TO="${SEND_TO:-$([[ $HOST == overseer ]] && echo brain || echo overseer)}"
mkdir -p "$OUT"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT

paths=(etc/uploader.env)
add() { for p in "$@"; do [[ -e "/$p" ]] && paths+=("$p"); done; return 0; }

case "$HOST" in
  brain)
    # consistent copy of the live SQLite queue (no sqlite3 CLI needed)
    if [[ -f /var/lib/uploader/jobs.db ]]; then
      mkdir -p "$STAGE/var/lib/uploader"
      python3 -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()' \
        /var/lib/uploader/jobs.db "$STAGE/var/lib/uploader/jobs.db"
    fi
    add etc/nginx/sites-available/uploader ;;
  tiktok|insta)
    # browser profile = the login session; skip caches
    add "${H#/}/uploader-profiles" "${H#/}/uploader-state" ;;
  clapper)
    add opt/uploader/lanes/clapper/clapper_flow.json "${H#/}/.android/adbkey" "${H#/}/.android/adbkey.pub" ;;
  web)
    add srv/web ;;
  overseer)
    if [[ -f /var/lib/overseer/overseer.db ]]; then
      mkdir -p "$STAGE/var/lib/overseer"
      python3 -c 'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()' \
        /var/lib/overseer/overseer.db "$STAGE/var/lib/overseer/overseer.db"
    fi
    add etc/systemd/system/ollama.service.d/override.conf ;;
esac

FILE="$OUT/$HOST-$(date +%Y%m%d-%H%M%S).tgz"
# staged DB copies are added by name (never "." - restoring a "./" entry would reset / itself)
staged=(); while IFS= read -r -d '' e; do staged+=("$(basename "$e")"); done \
  < <(find "$STAGE" -mindepth 1 -maxdepth 1 -print0)
tar -czf "$FILE" \
  --exclude='*/Cache/*' --exclude='*/Code Cache/*' --exclude='*/GPUCache/*' \
  --exclude='*/Service Worker/CacheStorage/*' --exclude='*/SingletonLock' \
  -C / "${paths[@]}" ${staged[@]:+-C "$STAGE" "${staged[@]}"} 2>/dev/null \
  || [[ $? == 1 ]]   # 1 = a file changed while reading
chmod 600 "$FILE"
echo "backup: $FILE ($(du -h "$FILE" | cut -f1))"

# keep the newest $KEEP of this host's own backups
ls -1t "$OUT"/"$HOST"-*.tgz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f

if [[ "${NO_SEND:-0}" != 1 ]]; then
  if tailscale file cp "$FILE" "$SEND_TO:" 2>/tmp/backup-send.err; then
    echo "sent to $SEND_TO"
  else
    echo "WARNING: could not send to $SEND_TO: $(cat /tmp/backup-send.err)"; exit 2
  fi
fi
