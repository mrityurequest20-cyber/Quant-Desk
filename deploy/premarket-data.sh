#!/usr/bin/env bash
# premarket-data.sh WAREHOUSE HISTORY: what the pre-market brief reads (docs/PREMARKET.md), from public NSE tables.
#   WAREHOUSE  the last 3 months of every F&O stock's options (fo_stock_opts), the last 2 of the indices' (fo_bhav),
#              NSE's event calendar (corp_events) and the official index closes (nse_index_close)
#   HISTORY    results_history.parquet + history_built.txt: reused from the premarket branch when they were built
#              today (IST), else rebuilt from PREMARKET_HISTORY_MONTHS (default 24) months of fo_stock_opts;
#              tails.json (the EVT tail models) from the same branch: the brief reuses it when its date is today
# Needs GH_TOKEN (read: the release and the branch). Python is started without it in its environment. Never fails the job: the brief says what
# it lacked.
set -uo pipefail
PY=$(command -v python)              # setup-python's interpreter, by its full path from here on
export PATH=/usr/bin:/bin            # gh and every other tool from the system, never a script pip installed
wh=${1:-runtime/warehouse} hist=${2:-runtime/premarket-history}
months=${PREMARKET_HISTORY_MONTHS:-24}
mkdir -p "$wh" "$hist"
today=$(TZ=Asia/Kolkata date +%F)
pat() {      # --pattern TABLE_<month>.parquet for the last N months
  env -u GH_TOKEN "$PY" -c "import pandas as pd, sys
print(' '.join(f'--pattern {sys.argv[1]}_{p}.parquet' for p in pd.period_range(end=pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None), periods=int(sys.argv[2]), freq='M')))" "$1" "$2"
}
raw() { gh api "repos/$GITHUB_REPOSITORY/contents/$1?ref=premarket" -H "Accept: application/vnd.github.raw" 2>/dev/null; }
need=$months
if [ "$(raw history_built.txt | tr -d '[:space:]')" = "$today" ] && raw results_history.parquet > "$hist/results_history.parquet" \
   && [ -s "$hist/results_history.parquet" ]; then
  echo "results history: today's, from the premarket branch"
  echo "$today" > "$hist/history_built.txt"
  need=3
else
  rm -f "$hist/results_history.parquet" "$hist/history_built.txt"
fi
# The day's tail models (docs/PREMARKET.md): the brief reuses them when they were built today (it reads their date), so Yahoo is asked once a morning.
raw tails.json > "$hist/tails.json" 2>/dev/null && [ -s "$hist/tails.json" ] || rm -f "$hist/tails.json"
# shellcheck disable=SC2046
gh release download warehouse $(pat fo_stock_opts "$need") $(pat fo_bhav 2) --pattern 'corp_events_*.parquet' \
   --pattern 'nse_index_close_*.parquet' --dir "$wh" --clobber || echo "::warning::the warehouse download was incomplete"
echo "warehouse: $(ls "$wh" | wc -l) files, $(du -sh "$wh" | cut -f1)"
if [ ! -s "$hist/results_history.parquet" ]; then
  if env -u GH_TOKEN "$PY" -m quantdesk premarket history --warehouse "$wh" --out "$hist/results_history.parquet"; then
    echo "$today" > "$hist/history_built.txt"
  else
    echo "::warning::the results history was not built: the brief builds a short one from three months"
  fi
fi
exit 0
