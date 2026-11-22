#!/usr/bin/env bash
# Goal checker for the handoff loop (see HANDOFF.md).
# Run from any tailnet machine with ssh + curl + python3 (the MSI via Git Bash/WSL, or any Pi):
#   ./scripts/goals.sh            # every goal
#   ./scripts/goals.sh G6         # one goal
# Prints PASS/FAIL per goal. Exit code = number of failed goals (0 = stack fully working).
# Read-only: it changes nothing on any machine.
set -uo pipefail
U="${PI_USER:-bemor}"
ONLY="${1:-}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new)
HOSTS=(brain tiktok insta clapper web overseer)
declare -A UNITS=(
  [brain]="uploader-brain" [tiktok]="uploader-lane@tiktok" [insta]="uploader-lane@insta"
  [clapper]="uploader-lane@clapper" [web]="nginx" [overseer]="overseer ollama"
)
FAILS=0
pass() { printf '\033[32mPASS\033[0m  %-4s %s\n' "$1" "$2"; }
fail() { printf '\033[31mFAIL\033[0m  %-4s %s\n' "$1" "$2"; FAILS=$((FAILS+1)); }
want() { [[ -z "$ONLY" || "$ONLY" == "$1" ]]; }
on()   { local h=$1; shift; "${SSH[@]}" "$U@$h" "$@" 2>&1; }
envval() { on "$1" "sudo -n grep -m1 '^$2=' /etc/uploader.env" | cut -d= -f2-; }
j()    { python3 -c "import json,sys; d=json.load(sys.stdin); $1" 2>/dev/null; }

if want G1; then  # every Pi reachable by Tailscale SSH
  bad=(); for h in "${HOSTS[@]}"; do on "$h" true >/dev/null || bad+=("$h"); done
  [[ ${#bad[@]} == 0 ]] && pass G1 "ssh ok to all 6 Pis" || fail G1 "no ssh: ${bad[*]}"
fi

if want G2; then  # each role's services installed + running
  bad=()
  for h in "${HOSTS[@]}"; do
    out=$(on "$h" systemctl is-active ${UNITS[$h]}) || true
    [[ -n "$out" && -z "$(echo "$out" | grep -vx active)" ]] || bad+=("$h(${UNITS[$h]}: $(echo $out))")
  done
  [[ ${#bad[@]} == 0 ]] && pass G2 "all role services active" || fail G2 "${bad[*]}"
fi

if want G3; then  # brain reaches all three lanes
  out=$(curl -fsS -m 20 http://brain/health 2>&1)
  bad=$(echo "$out" | j 'print(" ".join(k for k,v in d["lanes"].items() if not isinstance(v,dict)))') || bad="bad response: ${out:0:120}"
  [[ -z "$bad" ]] && pass G3 "brain sees tiktok insta clapper" || fail G3 "brain can't reach: $bad"
fi

if want G4; then  # overseer up, sees nothing down, alerts configured
  out=$(curl -fsS -m 20 http://overseer:8200/health 2>&1)
  r=$(echo "$out" | j 'print(("down:"+",".join(d["down"])) if d["down"] else ("" if d["alerts"] else "ALERT_URL not set"))') || r="unreachable: ${out:0:120}"
  [[ -z "$r" ]] && pass G4 "overseer green, ntfy alerts on" || fail G4 "$r"
fi

if want G5; then  # overseer can use the MSI's Ollama (OLLAMA_HOST=0.0.0.0 on the MSI)
  if on overseer "curl -fs -m 6 http://msi:11434/api/tags" >/dev/null; then pass G5 "overseer -> msi Ollama ok"
  else fail G5 "overseer can't reach http://msi:11434 (set OLLAMA_HOST=0.0.0.0 on MSI, restart Ollama)"; fi
fi

if want G6 || want G7; then LANE_TOKEN="${LANE_TOKEN:-$(envval brain LANE_TOKEN)}"; fi

if want G6; then  # TikTok + Instagram logged in (HUMAN: needs your login/2FA)
  bad=()
  for l in tiktok insta; do
    out=$(curl -fsS -m 150 -H "Authorization: Bearer $LANE_TOKEN" "http://$l:8100/check" 2>&1)
    echo "$out" | grep -qE '"logged_in": *true' || bad+=("$l(${out:0:80})")
  done
  [[ ${#bad[@]} == 0 ]] && pass G6 "tiktok + insta logged in" || fail G6 "not logged in: ${bad[*]}  -> http://<lane>:8100/login?token=\$LANE_TOKEN"
fi

if want G7; then  # Pixel attached + authorized on clapper (HUMAN: accept USB debugging)
  out=$(on clapper "adb get-state")
  [[ "$out" == *device* ]] && pass G7 "Pixel connected over adb" || fail G7 "adb: ${out:0:100}"
fi

if want G8; then  # PR #2 merged and deployed: check.sh + nightly backups on every Pi
  bad=()
  curl -fsI -m 10 https://raw.githubusercontent.com/bemor187/pi-uploader/main/scripts/check.sh >/dev/null || bad+=("PR#2 not merged to main")
  for h in "${HOSTS[@]}"; do
    out=$(on "$h" "test -x ~/pi-uploader/scripts/check.sh && systemctl is-active pi-backup.timer") || true
    [[ "$out" == *active* && "$out" != *inactive* ]] || bad+=("$h(not updated)")
  done
  [[ ${#bad[@]} == 0 ]] && pass G8 "checks + backups deployed everywhere" || fail G8 "${bad[*]}"
fi

if want G9; then  # one successful upload per lane
  API_TOKEN="${API_TOKEN:-$(envval brain API_TOKEN)}"
  out=$(curl -fsS -m 20 -H "Authorization: Bearer $API_TOKEN" "http://brain/jobs?limit=500" 2>&1)
  missing=$(echo "$out" | j 'ok={x["platform"] for x in d if x["status"]=="done"}; print(" ".join(p for p in ("tiktok","insta","clapper") if p not in ok))') || missing="can't read /jobs: ${out:0:100}"
  [[ -z "$missing" ]] && pass G9 "a done upload exists for every lane" || fail G9 "no done upload yet: $missing"
fi

if want G10; then  # password SSH off (do this last)
  bad=(); for h in "${HOSTS[@]}"; do on "$h" "test -f /etc/ssh/sshd_config.d/90-keys-only.conf" >/dev/null || bad+=("$h"); done
  [[ ${#bad[@]} == 0 ]] && pass G10 "SSH hardened everywhere" || fail G10 "not hardened: ${bad[*]}"
fi

echo; [[ $FAILS == 0 ]] && echo "ALL GOALS PASS" || echo "$FAILS goal(s) failing"
exit $FAILS
