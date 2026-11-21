#!/usr/bin/env bash
# Run on a fresh Pi (from a phone SSH app or the Pi's own keyboard) - no other computer needed:
#   curl -fsSL https://raw.githubusercontent.com/bemor187/pi-uploader/main/scripts/bootstrap.sh | sudo bash -s brain
#   curl -fsSL .../bootstrap.sh | sudo LANE_TOKEN=xxxx bash -s tiktok
#   curl -fsSL .../bootstrap.sh | sudo API_TOKEN=<brain's> bash -s overseer
# Re-running it pulls the latest code and re-applies setup (keeps /etc/uploader.env).
set -euo pipefail
ROLE="${1:?usage: bootstrap.sh brain|tiktok|insta|clapper|overseer}"
REPO="${REPO:-https://github.com/bemor187/pi-uploader.git}"
U="${SUDO_USER:-$(logname)}"
DIR="$(getent passwd "$U" | cut -d: -f6)/pi-uploader"
command -v git >/dev/null || { apt-get update && apt-get install -y git; }
if [[ -d "$DIR/.git" ]]; then sudo -u "$U" git -C "$DIR" pull --ff-only; else sudo -u "$U" git clone "$REPO" "$DIR"; fi
exec "$DIR/scripts/setup.sh" "$ROLE"
