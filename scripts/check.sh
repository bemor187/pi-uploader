#!/usr/bin/env bash
# Cluster health check. Run on any Pi (or any tailnet machine with curl):
#   ~/pi-uploader/scripts/check.sh            # every host
#   ~/pi-uploader/scripts/check.sh --deep     # also lane logins / phone (needs LANE_TOKEN)
# LANE_TOKEN is read from /etc/uploader.env when readable (sudo), or from the environment.
# Exit code = number of problems found (0 = all good).
set -uo pipefail
DEEP=0; [[ "${1:-}" == --deep ]] && DEEP=1
ENVF=/etc/uploader.env
if [[ -z "${LANE_TOKEN:-}" && -r $ENVF ]]; then
  LANE_TOKEN="$(grep -m1 '^LANE_TOKEN=' "$ENVF" | cut -d= -f2-)"
fi
BAD=0
ok()   { printf '  \033[32mOK\033[0m    %-9s %s\n' "$1" "$2"; }
fail() { printf '  \033[31mFAIL\033[0m  %-9s %s\n' "$1" "$2"; BAD=$((BAD+1)); }
get()  { curl -fsS -m "${2:-8}" "$1" 2>&1; }

echo "Pi stack check $(date '+%F %T') from $(hostname)"

# brain: API + its own view of the lanes
if out=$(get http://brain/health); then
  ok brain "$(echo "$out" | head -c 160)"
else fail brain "http://brain/health: $out"; fi

for lane in tiktok insta clapper; do
  if out=$(get "http://$lane:8100/health"); then ok "$lane" "$out"
  else fail "$lane" "http://$lane:8100/health: $out"; fi
  if [[ $DEEP == 1 ]]; then
    if [[ -z "${LANE_TOKEN:-}" ]]; then fail "$lane" "--deep needs LANE_TOKEN (run with sudo, or export it)"; continue; fi
    if out=$(curl -fsS -m 120 -H "Authorization: Bearer $LANE_TOKEN" "http://$lane:8100/check" 2>&1); then
      if echo "$out" | grep -qiE '"logged_in": *false|"ok": *false|not installed|no device'; then
        fail "$lane" "check: $(echo "$out" | head -c 200)"
      else ok "$lane" "check: $(echo "$out" | head -c 200)"; fi
    else fail "$lane" "check: $out"; fi
  fi
done

if out=$(get http://web/health); then ok web "$out"; else fail web "http://web/health: $out"; fi

if out=$(get http://overseer:8200/health 15); then
  down=$(echo "$out" | python3 -c 'import json,sys; print(",".join(json.load(sys.stdin).get("down",[])))' 2>/dev/null)
  if [[ -n "$down" ]]; then fail overseer "up, but reports down: $down"; else ok overseer "monitor sees everything up"; fi
else fail overseer "http://overseer:8200/health: $out"; fi

# latest backups received by overseer (see scripts/backup.sh)
if out=$(get http://overseer:8200/backups 15); then
  echo "$out" | python3 -c '
import json,sys,time
for h,v in sorted(json.load(sys.stdin).items()):
    age=(time.time()-v["mtime"])/3600
    flag="OK  " if age<36 else "OLD "
    print(f"  {flag}  backup    {h:<9} {v[\"file\"]} ({age:.0f}h ago)")' 2>/dev/null
fi

echo
[[ $BAD == 0 ]] && echo "All good." || echo "$BAD problem(s)."
exit $BAD
