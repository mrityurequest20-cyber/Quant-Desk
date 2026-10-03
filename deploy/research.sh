#!/usr/bin/env bash
# research.sh: put the latest edge-research results (the `research` branch) where the engine reads them
# (runtime/research/edges.json). Without them the desk simply runs without research priors.
set -uo pipefail
rt=${QD_RUNTIME:-runtime}
mkdir -p "$rt/research"
if git fetch -q --depth 1 origin research 2>/dev/null && git show FETCH_HEAD:edges.json > "$rt/research/edges.json.tmp"; then
  mv "$rt/research/edges.json.tmp" "$rt/research/edges.json"
  git show FETCH_HEAD:links.json > "$rt/research/links.json" 2>/dev/null || rm -f "$rt/research/links.json"
  # the warehouse research: positioning verdicts (FII options, P4) and the buyer's edge by days to expiry / weekday
  for f in vrp_positioning.json buyer_edge.json; do
    git show "FETCH_HEAD:$f" > "$rt/research/$f" 2>/dev/null || rm -f "$rt/research/$f"
  done
  python3 -c "import json; r=json.load(open('$rt/research/edges.json')); print('research priors:', [f\"{x['id']} {x['symbol']}\" for x in r if x['verdict'] in ('PAPER CANDIDATE','EDGE')] or 'none')"
else
  rm -f "$rt/research/edges.json.tmp"
  echo "no research results yet"
fi
