# TrueData Velocity 2.0 exports

`quantdesk/data/external_truedata.py` (import, audit, check, provider) and `quantdesk/research/truedata_study.py`
(research). Commands:

```
python -m quantdesk data truedata-import --source <export folder or a clone of the private repo holding it>
python -m quantdesk data truedata-verify        # every bar against Yahoo daily OHLC; sets the batch's status
python -m quantdesk data truedata-research      # stats, pre-registered rules, causal replay, backtester → research.md
python -m quantdesk --source truedata backtest  # the existing daily backtester on the verified TrueData batch
```

## Where the data lives

- **Raw export:** the private repository `quantdesk-truedata`, unchanged. Its git history and the manifest's sha256 of
  every file prove it.
- **Normalised batches:** `runtime/external/truedata/truedata-1-<batch>/` (not committed; `runtime/` is ignored). The
  batch id is a hash of every source file's path and sha256, so:
  - re-importing the same files is a verified no-op;
  - changed files make a new batch next to the old one;
  - a tampered partition fails the import (`ImmutableViolation`).
- **This repository (public)** holds only derived reports: `docs/truedata/QUALITY.md` and `RESEARCH.md`. They contain
  file hashes, counts and statistics, and no price rows. TrueData's licence is the reason the raw and normalised bars
  stay private.

## What the importer assumes: nothing it can check

| Question | How it is answered |
|---|---|
| Columns | Fields per row are counted. Date and time formats are tried on the whole column. Trailing numeric columns are `extra_1…n` with population stats. They are never called volume or OI unless their content supports it |
| Timeframe | From the timestamps: one constant time and one row per date means daily; otherwise the modal step within a day. A folder name (`Trade 1 Minute`, …) is only a hint, and a disagreement is reported |
| Time zone | Intraday: the share of timestamps inside 09:15–15:30 (NSE's session in IST). Daily: the constant end-of-day stamp is recorded as a marker, not a trade time |
| Bad rows | Rejected with line number and reason: wrong field count, unparsable date or time, non-numeric price, invalid OHLC |
| Duplicates | Identical rows are kept once. Conflicting rows for one timestamp are dropped, counted, and listed |
| Weekend sessions | Kept and flagged (e.g. the 1 Feb 2026 Budget-day session) |
| Missing sessions | A weekday absent from both TrueData and the independent reference is a market holiday; absent only from TrueData, it is a gap |
| Intraday coverage | Bars per session against 375 (1m) or 75 (5m), with start- or end-labelling detected |

Allowed uses: underlying features, direction research, regime research, development folds, daily backtests. It is
never option-chain, bid/ask, IV, trade-by-trade footprint, aggressor volume or order-book data, and never qualifies an
option strategy, a paper gate, a promotion or a profitability claim.

## The record

**Batch f94705809b16 (uploaded 4 Oct 2026, daily files only)**
- `NIFTY.txt` and `BANKNIFTY.txt`: 247 daily bars each, 3 Oct 2025 → 1 Oct 2026.
- 0 rejected rows and 0 duplicates.
- The four trailing columns are zero in every row: no volume or OI.
- **Independent check: 246 of 246 dates match Yahoo exactly** (median gap 0.00% on O, H, L, C). The one extra
  TrueData row is the Sunday 1 Feb 2026 Budget session, which Yahoo doesn't carry.
- The three absent weekdays (22 Oct, 5 Nov, 25 Dec 2025) are absent from Yahoo too: market holidays.
- Status `external_verified`.

Not uploaded yet: `Trade 1 Minute`, `Trade 5 Minute`, `Trade 1 Tick`. Their audit runs the same way once they're in
the private repo.

Research: [docs/truedata/RESEARCH.md](truedata/RESEARCH.md). In short:
- The year was calm next to 2010–23 (NIFTY 13.5% annualised vol vs 18.5%) and down (NIFTY −9.9%, max drawdown −15.2%
  on 30 Mar 2026).
- No persistence: lag-1 autocorrelation inside its noise band, variance ratio ≈ 0.91 (z −0.5), Hurst ≈ 0.5.
- None of the pre-registered daily rules survives multiple-testing correction on this year, and none clears the
  option cost hurdle with significance.
- The existing daily backtester cannot trade it at all: it needs 260 warm-up sessions, and the year has 247.
