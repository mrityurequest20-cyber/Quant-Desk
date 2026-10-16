#!/usr/bin/env bash
# push-dir.sh DIR BRANCH MESSAGE
# Publish a folder as the whole content of BRANCH: one orphan commit, force-pushed, so the
# branch never accumulates history (the site and the journal state are snapshots, not logs).
# Skips the push when the content hasn't changed since the last push from this machine.
# Runs inside the repo checkout (it uses its remote and credentials) without touching the work tree.
set -euo pipefail
dir=$1 branch=$2 msg=${3:-update}
[ -d "$dir" ] || { echo "push-dir: no such folder $dir" >&2; exit 1; }
index=$(mktemp -u)
trap 'rm -f "$index"' EXIT
export GIT_INDEX_FILE=$index
git --work-tree="$dir" add -A -f .
tree=$(git write-tree)
stamp=".git/qd-last-tree-$branch"
if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$tree" ]; then
  echo "push-dir: $branch unchanged"
  exit 0
fi
commit=$(GIT_AUTHOR_NAME="quantdesk-bot" GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
         GIT_COMMITTER_NAME="quantdesk-bot" GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com" \
         git commit-tree "$tree" -m "$msg")
# PUSH_LEASE=<sha>: replace the branch only if it is still that commit (journal.sh: the one restored); the new commit
# is written to PUSH_SHA_OUT so a second save from the same run leases on it. Without PUSH_LEASE: a plain force-push.
if [ -n "${PUSH_LEASE:-}" ]; then
  force=(--force-with-lease="refs/heads/$branch:$PUSH_LEASE")
else
  force=(-f)
fi
for i in 1 2 3; do
  if git push -q "${force[@]}" origin "$commit:refs/heads/$branch"; then
    echo "$tree" > "$stamp"
    [ -n "${PUSH_SHA_OUT:-}" ] && echo "$commit" > "$PUSH_SHA_OUT"
    echo "push-dir: $branch ← $msg"
    exit 0
  fi
  if [ -n "${PUSH_LEASE:-}" ] && [ "$(git ls-remote origin "refs/heads/$branch" | cut -f1)" != "$PUSH_LEASE" ]; then
    echo "::error::push-dir: $branch moved since it was restored (another job saved it): refusing to overwrite its work" >&2
    exit 1
  fi
  sleep $((i * 5))
done
echo "push-dir: push to $branch failed" >&2
exit 1
