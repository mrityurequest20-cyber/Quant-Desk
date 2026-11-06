#!/usr/bin/env bash
# The automatic Kite login, in two steps that never share an environment (deploy/kite_autologin.py has the why):
#   kite-autologin.sh login     env KITE_DATA_KEY, KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET. Standard-library Python
#                               only (system python3 -I -S: no site-packages), so no third-party code runs beside the password. Writes the request_token.
#   kite-autologin.sh exchange  env KITE_DATA_KEY, KITE_DATA_SECRET. `quantdesk data kite-token` turns the request_token into
#                               the day's access token (the authority-date check included), which is exported masked as
#                               KITE_DATA_TOKEN, the data path's name, never the broker adapter's.
# Market data only: nothing here, or in what reads the token, calls an order, position, holding, margin or profile method.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
tmp=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
req="$tmp/kite_request_token"
tok="$tmp/kite_access_token"
case "${1:-}" in
  login)
    rm -f "$req"
    py=/usr/bin/python3; [ -x "$py" ] || py=python3      # the system Python, not the job's pip-filled one
    "$py" -I -S "$here/kite_autologin.py" --out "$req"     # -S: no site-packages, so no installed package's .pth code runs beside the password
    ;;
  exchange)
    [ -s "$req" ] || { echo "kite login: no request token (login not configured or it failed); nothing to exchange"; exit 0; }
    trap 'rm -f "$req" "$tok"' EXIT
    KITE_REQUEST_TOKEN=$(cat "$req") python -m quantdesk data kite-token --out "$tok"
    token=$(cat "$tok")
    [[ "$token" =~ ^[A-Za-z0-9]{16,64}$ ]] || { echo "::error::kite login: the access token is not token-shaped; not exported"; exit 1; }
    echo "::add-mask::$token"
    echo "KITE_DATA_TOKEN=$token" >> "${GITHUB_ENV:-/dev/null}"
    echo "kite login: today's access token loaded (not shown)"
    ;;
  *)
    echo "usage: kite-autologin.sh login | exchange" >&2
    exit 2
    ;;
esac
