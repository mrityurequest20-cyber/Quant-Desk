#!/usr/bin/env bash
# Restore the append-only experiment ledger before a scheduled research run.
set -euo pipefail
mkdir -p _research
if git fetch -q --depth 1 origin research 2>/dev/null; then
  if git show FETCH_HEAD:experiment_log.jsonl > _research/experiment_log.jsonl.tmp 2>/dev/null; then
    mv _research/experiment_log.jsonl.tmp _research/experiment_log.jsonl
  else
    printf '%s\n' '{"event":"ledger_initialized","note":"Earlier research reports predate the append-only experiment ledger and are not reconstructed."}' > _research/experiment_log.jsonl
  fi
else
  set +e
  git ls-remote --exit-code origin refs/heads/research >/dev/null 2>&1
  status=$?
  set -e
  if [ "$status" -eq 2 ]; then
    : > _research/experiment_log.jsonl
  else
    echo "could not fetch research branch; refusing to start an untracked experiment" >&2
    exit 1
  fi
fi
