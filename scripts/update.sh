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
for u in uploader-brain uploader-lane@tiktok uploader-lane@insta uploader-lane@clapper; do
  systemctl is-enabled "$u" >/dev/null 2>&1 && systemctl restart "$u" && echo "restarted $u"
done
echo "updated to $(git -C "$SRC" log --oneline -1)"
