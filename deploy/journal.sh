#!/usr/bin/env bash
# journal.sh restore | save MESSAGE
# The desk's memory between runs on throwaway machines (GitHub Actions): the journal database,
# the paper broker's cash and positions, session reviews and the recorded 1m bars live on the
# orphan `journal` branch. Option-chain snapshots are too big for git; the workflow keeps them
# as run artifacts instead.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
branch=${JOURNAL_BRANCH:-journal}
rt=${QD_RUNTIME:-runtime}
case "${1:-}" in
  restore)
    mkdir -p "$rt"
    if git fetch -q --depth 1 origin "$branch" 2>/dev/null; then
      git archive FETCH_HEAD | tar -x -C "$rt"
      git rev-parse FETCH_HEAD > "$rt/.journal-restored-sha"   # C-12: the save replaces exactly this commit, or nothing
      if [ -f "$rt/intraday/journal.db" ]; then
        python3 - "$rt/intraday/journal.db" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as db:
    result = db.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    raise SystemExit(f"journal integrity check failed: {result}")
print("journal: SQLite integrity check passed")
PY
        python3 "$here/journal_counts.py" "$rt/intraday/journal.db" > "$rt/.journal-restored.json"
      fi
      echo "journal: restored $(du -sh "$rt/intraday" | cut -f1) from the $branch branch"
    else
      set +e
      git ls-remote --exit-code origin "refs/heads/$branch" >/dev/null 2>&1
      remote_status=$?
      set -e
      if [ "$remote_status" -eq 2 ]; then
        echo "journal: no $branch branch exists yet; starting a fresh paper account"
      else
        echo "journal: could not restore $branch (fetch failed; refusing to start with an empty account)" >&2
        exit 1
      fi
    fi
    ;;
  save)
    [ -d "$rt/intraday" ] || { echo "journal: nothing to save"; exit 0; }
    # C-01: the journal branch is the only copy and every save replaces it. Never push a record smaller than the
    # one this run restored (a failed or partial restore, a wrong runtime dir): fewer trades, fills, decisions or
    # events, or a lower last thought/news id. A deliberate account reset sets JOURNAL_ALLOW_SHRINK=1.
    # C-02: the one other shrink allowed is thoughts/news after a prune whose archive was downloaded back from its release
    # and verified (quantdesk/journal/durable.py leaves the permit); journal_counts.py only honours it for the commit restored.
    if [ -f "$rt/.journal-restored.json" ] && [ "${JOURNAL_ALLOW_SHRINK:-}" != "1" ]; then
      permit=()
      [ -f "$rt/.journal-prune-permit.json" ] && permit=(--pruned "$rt/.journal-prune-permit.json" --restored-sha "$(cat "$rt/.journal-restored-sha" 2>/dev/null || true)")
      python3 "$here/journal_counts.py" "$rt/intraday/journal.db" --not-below "$rt/.journal-restored.json" ${permit[@]+"${permit[@]}"} || {
        echo "::error::journal: refusing to save a record smaller than the one restored (see above); nothing pushed" >&2
        exit 1
      }
    fi
    snap=$(mktemp -d)
    trap 'rm -rf "$snap"' EXIT
    mkdir -p "$snap/intraday"
    ( cd "$rt/intraday" && tar -c --exclude='./data/*/chains' --exclude='./backfill' --exclude='*.tmp' --exclude='*-journal' . ) | tar -x -C "$snap/intraday"
    cat > "$snap/README.md" <<'MD'
# QuantDesk journal (machine-written)

State the live paper desk carries from one trading day to the next: `intraday/journal.db` (every
thought, decision, fill, trade and review), `intraday/broker.json` (paper cash and positions),
`intraday/reviews/*.md` (one written review per session) and `intraday/data/<date>/*_1m.csv` (the
bars it saw). Rewritten by the workflow after every run. Don't edit by hand.

Read it locally: `git fetch origin journal && git archive FETCH_HEAD | tar -x -C runtime`, then
`python -m quantdesk intraday trades` / `stats` / `review`, or `python -m quantdesk serve`.
MD
    # C-12: compare-and-swap. Every writer (desk, learning cycles, restate) restores, works, then saves; if another
    # one saved in between, a plain force-push would silently drop its work. The lease refuses that instead.
    lease=""
    [ -f "$rt/.journal-restored-sha" ] && lease=$(cat "$rt/.journal-restored-sha")
    PUSH_LEASE="$lease" PUSH_SHA_OUT="$rt/.journal-restored-sha" \
      "$here/push-dir.sh" "$snap" "$branch" "${2:-journal $(date '+%F %H:%M')}"
    ;;
  *)
    echo "usage: journal.sh restore | save MESSAGE" >&2
    exit 2
    ;;
esac
