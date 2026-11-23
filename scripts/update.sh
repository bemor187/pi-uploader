#!/usr/bin/env bash
# Quick code update without re-running full setup (no apt upgrade):
#   sudo ~/pi-uploader/scripts/update.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
U="${SUDO_USER:-$(logname)}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
sudo -u "$U" git -C "$SRC" pull --ff-only
rsync -a --exclude venv --exclude lanes/clapper/clapper_flow.json "$SRC/" /opt/uploader/
chown -R "$U:$U" /opt/uploader
# pick up new Python dependencies
if systemctl is-enabled uploader-brain >/dev/null 2>&1; then
  /opt/uploader/venv/bin/pip install -q -r /opt/uploader/brain/requirements.txt
fi
if systemctl is-enabled overseer >/dev/null 2>&1; then
  /opt/uploader/venv/bin/pip install -q -r /opt/uploader/overseer/requirements.txt
fi
for u in uploader-brain uploader-lane@tiktok uploader-lane@insta uploader-lane@clapper overseer overseer-epaper; do
  if systemctl is-enabled "$u" >/dev/null 2>&1; then systemctl restart "$u" && echo "restarted $u"; fi
done
# web: refresh the nginx site config (your files in /srv/web are untouched)
if [[ -L /etc/nginx/sites-enabled/web ]]; then
  cp /opt/uploader/web/nginx-web.conf /etc/nginx/sites-available/web
  nginx -t && systemctl reload nginx && echo "reloaded nginx (web)"
fi
# nightly backup: install or refresh the timer (and the receiver on overseer / brain)
cp /opt/uploader/systemd/pi-backup.service /opt/uploader/systemd/pi-backup.timer /etc/systemd/system/
case "$(hostname)" in
  overseer|brain) cp /opt/uploader/systemd/pi-backup-receiver.service /etc/systemd/system/
                  systemctl daemon-reload; systemctl enable pi-backup-receiver >/dev/null 2>&1
                  systemctl restart pi-backup-receiver ;;
esac
systemctl daemon-reload; systemctl enable --now pi-backup.timer >/dev/null 2>&1 || true
echo "updated to $(git -C "$SRC" log --oneline -1)"
sleep 3
"$SRC/scripts/check.sh" || echo "(problems above may just be services still starting; re-run scripts/check.sh in a minute)"
