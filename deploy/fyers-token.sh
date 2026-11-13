#!/usr/bin/env bash
# The day's Fyers tokens, kept encrypted on the `fyers-token` branch (one file, fyers_token.enc), like Kite's (deploy/kite-token.sh). Encrypted with the app secret
# (FYERS_SECRET_ID, AES-256-CBC, PBKDF2) because the repository is public. Holds {"day", "access", "refresh"}: the refresh token lasts about 15 days, so most days the login
# (deploy/fyers_autologin.py) needs only it and the PIN.
#   fyers-token.sh load     env FYERS_SECRET_ID. Writes the stored refresh token to $RUNNER_TEMP/fyers_refresh (0600) and prints today=true|false to $GITHUB_OUTPUT
#                           (true: a token from today is stored already, so this run does not log in again).
#   fyers-token.sh store    env FYERS_SECRET_ID, GH_TOKEN. Encrypts $RUNNER_TEMP/fyers_login.json (the login's output) with today's date and pushes it to the branch.
#   fyers-token.sh export   env FYERS_SECRET_ID. Today's access token, masked, as FYERS_DATA_TOKEN in $GITHUB_ENV. Not today's, or anything wrong: nothing, and exit 0.
# Never prints a token. Market data only: what reads the token calls /data/quotes and /data/depth and nothing else.
set -uo pipefail
tmp=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
plain="$tmp/fyers_token.json"
enc="$tmp/fyers_token.enc"
trap 'rm -f "$plain" "$enc"' EXIT
umask 077
today=$(TZ=Asia/Kolkata date +%F)
py=/usr/bin/python3; [ -x "$py" ] || py=python3

fetch() {     # the stored file, decrypted to $plain; 1 when there is none or it does not decrypt
  [ -n "${FYERS_SECRET_ID:-}" ] || { echo "fyers token: no FYERS_SECRET_ID"; return 1; }
  git fetch -q --depth 1 origin fyers-token 2>/dev/null || { echo "fyers token: no fyers-token branch yet"; return 1; }
  git show FETCH_HEAD:fyers_token.enc > "$enc" 2>/dev/null || { echo "fyers token: the branch has no token file"; return 1; }
  openssl enc -d -aes-256-cbc -pbkdf2 -in "$enc" -out "$plain" -pass env:FYERS_SECRET_ID 2>/dev/null || { echo "fyers token: could not decrypt it (a new app secret?)"; return 1; }
}

field() {     # one field of $plain, only if it is token-shaped (a wrong key can still "decrypt": garbage never reaches GITHUB_ENV)
  "$py" -I -S - "$plain" "$1" <<'PY'
import json, re, sys
try:
    v = json.load(open(sys.argv[1])).get(sys.argv[2], "")
except Exception:
    v = ""
ok = re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) if sys.argv[2] == "day" else re.fullmatch(r"[A-Za-z0-9._-]{20,4096}", v)
print(v if isinstance(v, str) and ok else "")
PY
}

case "${1:-}" in
  load)
    rm -f "$tmp/fyers_refresh"
    is_today=false
    if fetch; then
      r=$(field refresh); [ -n "$r" ] && printf '%s' "$r" > "$tmp/fyers_refresh"
      [ "$(field day)" = "$today" ] && [ -n "$(field access)" ] && is_today=true
    fi
    echo "today=$is_today" >> "${GITHUB_OUTPUT:-/dev/null}"
    echo "fyers token: stored token from today: $is_today; stored refresh token: $([ -s "$tmp/fyers_refresh" ] && echo yes || echo no)"
    ;;
  store)
    src="$tmp/fyers_login.json"
    [ -s "$src" ] || { echo "fyers token: no login output to store"; exit 0; }
    [ -n "${FYERS_SECRET_ID:-}" ] && [ -n "${GH_TOKEN:-}" ] || { echo "::error::fyers token: FYERS_SECRET_ID or GH_TOKEN missing"; exit 1; }
    "$py" -I -S - "$src" "$plain" "$today" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
json.dump({"day": sys.argv[3], "access": d.get("access", ""), "refresh": d.get("refresh", "")}, open(sys.argv[2], "w"))
PY
    rm -f "$src" "$tmp/fyers_refresh"
    openssl enc -aes-256-cbc -pbkdf2 -salt -in "$plain" -out "$enc" -pass env:FYERS_SECRET_ID
    rm -f "$plain"
    work=$(mktemp -d)
    remote="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
    if git -C "$work" clone -q --depth 1 --branch fyers-token "$remote" . 2>/dev/null; then
      :                                                    # a new commit on top: the branch's history is never rewritten (docs/AUTONOMY.md)
    else
      git -C "$work" init -q
      git -C "$work" checkout -q --orphan fyers-token
    fi
    git -C "$work" config user.name "github-actions[bot]"
    git -C "$work" config user.email "41898282+github-actions[bot]@users.noreply.github.com"
    cp "$enc" "$work/fyers_token.enc"
    git -C "$work" add fyers_token.enc
    git -C "$work" commit -q -m "Fyers token for $today"
    git -C "$work" push -q "$remote" HEAD:refs/heads/fyers-token
    rm -rf "$work"
    echo "stored=true" >> "${GITHUB_OUTPUT:-/dev/null}"
    echo "fyers token: stored (encrypted) on the fyers-token branch"
    ;;
  export)
    fetch || { echo "fyers token: none for today; Fyers is not streamed"; exit 0; }
    [ "$(field day)" = "$today" ] || { echo "fyers token: the stored token is not today's; Fyers is not streamed"; exit 0; }
    token=$(field access)
    [ -n "$token" ] || { echo "fyers token: the stored access token is not token-shaped; Fyers is not streamed"; exit 0; }
    echo "::add-mask::$token"
    echo "FYERS_DATA_TOKEN=$token" >> "${GITHUB_ENV:-/dev/null}"
    echo "fyers token: today's token loaded (not shown)"
    ;;
  *)
    echo "usage: fyers-token.sh load | store | export" >&2
    exit 2
    ;;
esac
