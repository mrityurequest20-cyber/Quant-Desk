#!/usr/bin/env bash
# warehouse-context.sh: what the live desk reads from the data warehouse release, into runtime/warehouse.
#   corp_events_*.parquet   heavyweights' results dates (context for the read)
#   fo_bhav_<month>.parquet the last 13 months of the F&O bhavcopy, for the ATM IV percentile (~2 MB a month)
#   participant_oi_*, fii_dii_*  FII index-futures positioning and cash flows (the brain's flows context; small)
# Never fails the job: without these files the desk trades the same, its read just has less context.
set -uo pipefail
months=$(python -c "import pandas as pd; print(' '.join(f'--pattern fo_bhav_{p}.parquet' for p in pd.period_range(end=pd.Timestamp.now(tz='Asia/Kolkata').tz_localize(None), periods=13, freq='M')))")
# shellcheck disable=SC2086
if gh release download warehouse --pattern 'corp_events_*.parquet' --pattern 'participant_oi_*.parquet' \
     --pattern 'fii_dii_*.parquet' $months --dir runtime/warehouse --clobber; then
  echo "warehouse context: $(ls runtime/warehouse | tr '\n' ' ')"
else
  echo "no warehouse yet"
fi
exit 0
