#!/usr/bin/env bash
# Hand the Angel One session from the login step (deploy/angel_autologin.py, which wrote it to $RUNNER_TEMP/angel.json, mode 0600) to the feed step: masked, as ANGEL_DATA_TOKEN in
# $GITHUB_ENV, and the file deleted. No secret is needed here. Not there or not token-shaped: nothing is exported, and the feed says so and streams nothing.
set -uo pipefail
f="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/angel.json"
[ -s "$f" ] || { echo "angel session: none (the login did not run or failed); Angel One is not streamed"; exit 0; }
py=/usr/bin/python3; [ -x "$py" ] || py=python3
token=$("$py" -I -S - "$f" <<'PY'
import json, re, sys
try:
    v = json.load(open(sys.argv[1])).get("jwt", "")
except Exception:
    v = ""
print(v if isinstance(v, str) and re.fullmatch(r"[A-Za-z0-9._-]{20,4096}", v) else "")
PY
)
rm -f "$f"
[ -n "$token" ] || { echo "angel session: not token-shaped; Angel One is not streamed"; exit 0; }
echo "::add-mask::$token"
echo "ANGEL_DATA_TOKEN=$token" >> "${GITHUB_ENV:-/dev/null}"
echo "angel session: loaded for the feed (not shown)"
