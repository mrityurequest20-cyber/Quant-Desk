#!/usr/bin/env bash
# Load the day's Kite access token into the job's environment (docs/ml/KITE_TRIAL.md, intraday.kite.live).
# The token is written once a day, encrypted with the API secret, to the `kite-token` branch by .github/workflows/kite-token.yml. This step is optional in every way: no secret,
# no branch yet, a file that does not decrypt, or an empty token all end in "the desk uses its existing feeds", never in a failed job. The secret is read from the environment
# of this step only; the token is masked in the logs before it is exported.
set -uo pipefail
[ -n "${KITE_DATA_SECRET:-}" ] || { echo "kite token: no KITE_DATA_SECRET; the desk uses its existing feeds"; exit 0; }
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
git fetch -q --depth 1 origin kite-token 2>/dev/null || { echo "kite token: no kite-token branch yet; existing feeds"; exit 0; }
git show FETCH_HEAD:kite_token.enc > "$tmp" 2>/dev/null || { echo "kite token: the branch has no token file; existing feeds"; exit 0; }
token=$(openssl enc -d -aes-256-cbc -pbkdf2 -in "$tmp" -pass env:KITE_DATA_SECRET 2>/dev/null) || { echo "kite token: could not decrypt it (a new API secret since it was written?); existing feeds"; exit 0; }
[ -n "$token" ] || { echo "kite token: empty; existing feeds"; exit 0; }
# a wrong key can still "decrypt" (CBC has no check): only a token-shaped value is ever exported, so garbage or a newline can never inject a line into GITHUB_ENV
[[ "$token" =~ ^[A-Za-z0-9]{16,64}$ ]] || { echo "kite token: the decrypted value is not token-shaped; existing feeds"; exit 0; }
echo "::add-mask::$token"
# not the names the broker adapter (execution/kite.py) reads: this token is for market data only and must never switch that adapter's credentials on
echo "KITE_DATA_TOKEN=$token" >> "${GITHUB_ENV:-/dev/null}"
echo "kite token: loaded for the session"
