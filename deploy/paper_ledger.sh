#!/usr/bin/env bash
# The paper ledger branch (docs/RECORDING.md, "Running the paper runner"): a backup and audit trail of the paper account, one file on the `paper-ledger` branch, only ever gaining commits.
#   paper_ledger.sh fetch   put a copy of the branch (or an empty orphan one if it does not exist yet) in $LEDGER_WORK; never touches the repository checkout
#   paper_ledger.sh push    add $ACCOUNT as account.json in $LEDGER_WORK, commit it, and push the branch (a fast-forward; never a force-push)
# The repository token (GH_TOKEN), when set, is passed to git as a masked one-off header: it is not written to any config and not printed. Everything happens in $LEDGER_WORK, a directory of its
# own, because switching the repository checkout to this branch would remove the code the verify step needs.
set -euo pipefail
branch=paper-ledger
work=${LEDGER_WORK:?LEDGER_WORK must name a directory for the branch}
remote=${LEDGER_REMOTE:-"${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-}.git"}
hdr=()
if [ -n "${GH_TOKEN:-}" ]; then
  b64="$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 -w0)"
  echo "::add-mask::$b64"
  hdr=(-c "http.extraheader=AUTHORIZATION: basic $b64")
fi
g() { git -C "$work" ${hdr[@]+"${hdr[@]}"} "$@"; }
case "${1:-}" in
  fetch)
    rm -rf "$work"; mkdir -p "$work"
    git -C "$work" init -q
    git -C "$work" remote add origin "$remote"
    if g fetch -q --depth 1 origin "$branch"; then
      git -C "$work" checkout -q -B "$branch" FETCH_HEAD
      echo "paper-ledger: the branch exists ($(git -C "$work" rev-parse --short HEAD))"
    elif g ls-remote --exit-code origin "refs/heads/$branch" > /dev/null 2>&1; then
      echo "paper-ledger: the branch exists but could not be fetched: not creating it again" >&2
      exit 1
    else
      git -C "$work" checkout -q --orphan "$branch"
      echo "paper-ledger: no branch yet; the first publish creates it"
    fi
    ;;
  push)
    : "${ACCOUNT:?ACCOUNT must name the file to publish}"
    cp "$ACCOUNT" "$work/account.json"
    git -C "$work" add account.json
    if git -C "$work" diff --cached --quiet; then echo "paper-ledger: nothing new to publish"; exit 0; fi
    git -C "$work" -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" commit -q -m "Paper ledger for $(date +%F)"
    g push -q origin "$branch"
    echo "paper-ledger: published"
    ;;
  *)
    echo "usage: paper_ledger.sh fetch|push" >&2
    exit 2
    ;;
esac
