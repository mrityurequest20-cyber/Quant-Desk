# Reproducing the L1 evidence audit (4 Oct 2026)

The scripts read the warehouse at `/home/user/quant-desk/runtime/warehouse` (fo_bhav, bse_fo_bhav, nse_index_close)
and write their outputs next to themselves. **Copy this folder to a scratch location before running**, so nothing is
written into the repository, and never point them at `docs/prereg/results`.

| step | script | output |
|---|---|---|
| A | `a_trades.py` rebuilds v1 and v2 trades through the registered code path | `expiry_eve_law_v{1,2}_trades.csv.gz` |
| B | `b_stats.py` runs independent Newey–West statistics, a statsmodels cross-check, aggregation, lag and bootstrap sensitivity | `b_stats.json` |
| C | `c_impl.py` covers selected deltas, close vs last, leg liquidity, skipped expiries and their moves | `c_legs.csv.gz`, `c_skips.csv` |
| D | `d_diff.py` diffs v1 and v2 trade by trade and checks where v2's index levels come from | stdout |
| E | `e_regime.py` covers the pre/post Nov-2024 analysis, costs, leave-one-out and power | `e_regime.json` |

Run them with `PYTHONPATH=<repo>` from the repository root. `b_stats.py` needs statsmodels; it appends `../pylib` to the
path for an isolated install, so the desk's own numpy and pandas are never shadowed.

The outputs here are the ones the report cites. Input digests are in the report's header.
