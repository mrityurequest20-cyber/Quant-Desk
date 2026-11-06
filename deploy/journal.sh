#!/usr/bin/env bash
# journal.sh restore
# Restores the retired paper desk's record (the journal database, paper cash and positions, session reviews and the 1m
# bars it saw) from the orphan `journal` branch, read-only, for the app and the studies that read it. The desk was
# retired on 6 Nov 2026 and nothing writes the branch any more: the old `save` mode went with it, so no code path can
# replace that only copy.
set -euo pipefail
branch=${JOURNAL_BRANCH:-journal}
rt=${QD_RUNTIME:-runtime}
case "${1:-}" in
  restore)
    mkdir -p "$rt"
    if git fetch -q --depth 1 origin "$branch" 2>/dev/null; then
      git archive FETCH_HEAD | tar -x -C "$rt"
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
  *)
    echo "usage: journal.sh restore" >&2
    exit 2
    ;;
esac
