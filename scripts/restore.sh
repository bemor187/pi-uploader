#!/usr/bin/env bash
# Restore a backup made by backup.sh onto this Pi. Normally on a fresh card, after bootstrap:
#   1. flash Pi OS Lite 64-bit with the SAME hostname and user, then run the bootstrap line for the role
#   2. fetch the backup from overseer:
#        on overseer:   sudo tailscale file cp /var/backups/pi-stack/<host>/<newest>.tgz <host>:
#        on this Pi:    sudo tailscale file get ~/
#      (restoring overseer itself: its own backups are on brain, under /var/backups/pi-stack/overseer/)
#   3. sudo ~/pi-uploader/scripts/restore.sh ~/<host>-YYYYmmdd-HHMMSS.tgz
# It stops this Pi's services, puts the files back (tokens, logins, calibration, data), fixes
# ownership and restarts. Use --force to restore a backup taken on a different host name.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
FILE="${1:?usage: sudo restore.sh <backup.tgz> [--force]}"
[[ -f "$FILE" ]] || { echo "no such file: $FILE"; exit 1; }
HOST="$(hostname)"
SRC_HOST="$(basename "$FILE" | sed -E 's/-[0-9]{8}-[0-9]{6}\.tgz$//')"
if [[ "$SRC_HOST" != "$HOST" && "${2:-}" != --force ]]; then
  echo "backup is from '$SRC_HOST' but this Pi is '$HOST'. Re-run with --force if that's intended."; exit 1
fi
U="${SUDO_USER:-$(getent passwd 1000 | cut -d: -f1)}"
tar -tzf "$FILE" >/dev/null || { echo "backup is damaged"; exit 1; }
if tar -tzf "$FILE" | grep -qE '^(\./?|/)$|(^|/)\.\.(/|$)'; then
  echo "backup contains a root or '..' entry; refusing to restore it"; exit 1
fi

units=(uploader-brain uploader-lane@tiktok uploader-lane@insta uploader-lane@clapper overseer nginx)
active=()
for u in "${units[@]}"; do systemctl is-active --quiet "$u" && active+=("$u"); done
echo "stopping: ${active[*]:-(nothing running)}"
[[ ${#active[@]} -gt 0 ]] && systemctl stop "${active[@]}"

# keep the current env file next to the restored one, just in case
[[ -f /etc/uploader.env ]] && cp -a /etc/uploader.env "/etc/uploader.env.before-restore"
tar -xzpf "$FILE" -C / --no-overwrite-dir
echo "restored $(tar -tzf "$FILE" | wc -l) entries from $FILE"

# ownership: env file readable by the service user; data dirs owned by it
[[ -f /etc/uploader.env ]] && { chown root:"$U" /etc/uploader.env; chmod 640 /etc/uploader.env; }
for d in /var/lib/uploader /var/lib/overseer /srv/web /opt/uploader \
         "$(getent passwd "$U" | cut -d: -f6)"/{uploader-profiles,uploader-state,.android}; do
  [[ -e "$d" ]] && chown -R "$U:$U" "$d"
done

systemctl daemon-reload
[[ ${#active[@]} -gt 0 ]] && systemctl start "${active[@]}"
[[ -L /etc/nginx/sites-enabled/web || -L /etc/nginx/sites-enabled/uploader ]] && systemctl reload nginx || true
echo "done. Check it: ~/pi-uploader/scripts/check.sh"
