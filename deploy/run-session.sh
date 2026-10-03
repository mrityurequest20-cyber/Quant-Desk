#!/usr/bin/env bash
# run-session.sh [quantdesk intraday live args...]
# One runner's share of the trading day: the engine in the background, and the read-only live
# site re-exported every $PUBLISH_EVERY_MIN minutes (pushed to the gh-pages branch only when
# something changed), plus once more when the engine stops. On cancel the engine is stopped
# (every minute is committed to the journal, so nothing is lost); the workflow's `if: cancelled()`
# step then squares off open paper positions (`live --close-out`) with its own time budget.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
every=${PUBLISH_EVERY_MIN:-6}
site=${SITE_DIR:-_site}
pages=${PAGES_BRANCH:-gh-pages}

publish() {
  [ "${PUBLISH:-1}" = "1" ] || return 0
  python -m quantdesk intraday export-site --dir "$site" --sessions 2 >/dev/null \
    && "$here/push-dir.sh" "$site" "$pages" "site $(TZ=Asia/Kolkata date '+%F %H:%M') IST" \
    || echo "publish failed; next try in ${every} min"
}

# the chain tape (quantdesk/intraday/tape.py): real chains every minute for several expiries, in its own process so it
# can never hold the engine up. It stops at the same --until as the engine (or the close). TAPE=0 turns it off.
until=""
prev=""
for arg in "$@"; do
  [ "$prev" = "--until" ] && until="$arg"
  prev="$arg"
done
tape=""
if [ "${TAPE:-1}" = "1" ]; then
  python -m quantdesk intraday tape ${until:+--until "$until"} > "${TAPE_LOG:-tape.log}" 2>&1 &
  tape=$!
fi

python -m quantdesk intraday live "$@" &
engine=$!
stop_tape() {
  [ -n "$tape" ] && kill -TERM "$tape" 2>/dev/null && wait "$tape" 2>/dev/null
  [ -f "${TAPE_LOG:-tape.log}" ] && tail -n 12 "${TAPE_LOG:-tape.log}"
  tape=""
}
on_cancel() {
  echo "cancelled: stopping the engine"
  kill -TERM "$engine" 2>/dev/null
  wait "$engine" 2>/dev/null
  stop_tape
  exit 130
}
trap on_cancel TERM INT

publish
while kill -0 "$engine" 2>/dev/null; do
  for _ in $(seq $((every * 6))); do
    kill -0 "$engine" 2>/dev/null || break
    sleep 10
  done
  kill -0 "$engine" 2>/dev/null && publish
done
wait "$engine"
rc=$?
# the tape stops on its own at --until / the close; give it a minute to finish its last pass and print its report
for _ in $(seq 12); do
  [ -n "$tape" ] && kill -0 "$tape" 2>/dev/null || break
  sleep 5
done
stop_tape
publish
exit $rc
