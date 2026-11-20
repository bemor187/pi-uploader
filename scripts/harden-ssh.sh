#!/usr/bin/env bash
# Phase 4: turn off password SSH.
#   sudo ./scripts/harden-ssh.sh             # needs a key in ~/.ssh/authorized_keys
#   sudo ./scripts/harden-ssh.sh --tailscale # no keys: rely on Tailscale SSH (setup.sh enables it)
#                                            # and close port 22 on the LAN entirely
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
U="${SUDO_USER:-$(logname)}"
H="$(getent passwd "$U" | cut -d: -f6)"
if [[ "${1:-}" == --tailscale ]]; then
  tailscale status >/dev/null || { echo "Tailscale is not up; refusing."; exit 1; }
  echo "Make sure 'ssh $U@$(hostname)' over Tailscale works from your phone BEFORE continuing (Ctrl-C to abort)."; sleep 10
  ufw delete allow 22/tcp || true
else
  [[ -s "$H/.ssh/authorized_keys" ]] || { echo "No $H/.ssh/authorized_keys; add a key or use --tailscale."; exit 1; }
fi
cat > /etc/ssh/sshd_config.d/90-keys-only.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sshd -t && systemctl reload ssh
echo "Password SSH disabled. Test a new session with your key before closing this one."
