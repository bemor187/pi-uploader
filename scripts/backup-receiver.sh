#!/usr/bin/env bash
# Runs on overseer (and brain, which holds overseer's own backups) as pi-backup-receiver.service.
# Waits for Taildrop files, moves each backup to /var/backups/pi-stack/<host>/, keeps the newest 14.
set -uo pipefail
IN=/var/backups/pi-stack/incoming
ROOT=/var/backups/pi-stack
KEEP="${KEEP_RECEIVED:-14}"
U="$(getent passwd 1000 | cut -d: -f1)"
mkdir -p "$IN"
while true; do
  tailscale file get --wait --conflict=rename "$IN" || sleep 30
  for f in "$IN"/*.tgz; do
    [[ -e "$f" ]] || continue
    host="$(basename "$f" | sed -E 's/-[0-9]{8}-[0-9]{6}(\s*\([0-9]+\))?\.tgz$//')"
    [[ "$host" =~ ^[a-z0-9-]+$ ]] || { echo "skipping odd file $f"; mv "$f" "$f.rejected"; continue; }
    # root-owned; group = the Pi user so overseer's status page can see dates, not contents
    mkdir -p "$ROOT/$host"; chgrp "$U" "$ROOT" "$ROOT/$host"; chmod 750 "$ROOT" "$ROOT/$host"
    mv "$f" "$ROOT/$host/"; chmod 600 "$ROOT/$host/$(basename "$f")"
    echo "received $(basename "$f") from $host"
    ls -1t "$ROOT/$host"/*.tgz | tail -n +"$((KEEP + 1))" | xargs -r rm -f
  done
done
