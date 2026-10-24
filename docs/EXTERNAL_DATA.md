# External index minutes (aeron7/nifty-banknifty-intraday-data)

`quantdesk/data/external_aeron.py`, `python -m quantdesk data external-import / external-verify`,
`python -m quantdesk autolearn direction-study`, and the `External index data` workflow.

## What it is, and what it is not

The source is [github.com/aeron7/nifty-banknifty-intraday-data](https://github.com/aeron7/nifty-banknifty-intraday-data):
one-minute NIFTY and BANKNIFTY **index** bars, 2007 → early 2023, in year / month / day text files.

| Allowed (`ALLOWED_USES`) | Never |
|---|---|
| Underlying-price features | Historical option chains, bid/ask, IV, option execution |
| Direction research | Evidence to qualify an option strategy |
| Regime research | A DTE or horizon policy change |
| Development-fold testing | Paper-gate progress, champion promotion, any profitability claim |

`load()` refuses any other declared use. The dataset's status is **`external_unverified`** until the independent check
passes, and `load()` refuses unverified data unless the caller opts in explicitly. Even `external_verified` data keeps
these restrictions. The plan-level research (PLAN_RESEARCH.md) never reads it.

## The source format

The fields are `Symbol,YYYYMMDD,HH:MM,Open,High,Low,Close[,Volume[,OI]]`, in three variants: 7 fields (no volume / OI),
8 and 9.

Bars are labelled by their **end** minute: the regular session runs 09:16 … 15:30, with a 09:08 pre-open print and
15:31+ post-close prints around it. The importer:
- detects the labelling per file and re-labels every bar by its **start**, in timezone-aware IST (09:15 … 15:29,
  375 minutes, the desk's convention);
- normalises symbols (aliases → NIFTY / BANKNIFTY);
- reads only the index files `NIFTY.txt` / `BANKNIFTY.txt`. The `_F1` / `_F2` futures files and the stocks are
  ignored.

Index volume is 0 by nature. It is counted (`zero_volume`), not rejected. An absent volume column is `volume_absent`.

## Validation (per file, then per session)

| Check | Treatment |
|---|---|
| Unparsable rows, another symbol | dropped, counted per file |
| Bad prices (≤ 0, high < low, open / close outside the range) | dropped, counted |
| Invalid volume (present but negative / non-numeric) | dropped, counted |
| Out-of-order rows | counted; the session is sorted |
| Out-of-session minutes (pre-open, post-close) | dropped, counted |
| Duplicate minutes | identical: one kept; conflicting: both dropped, counted |
| Missing minutes, longest gap | counted; a session needs ≥ 360 of 375 minutes to be accepted |
| A one-minute move > 5% | the session is quarantined (rejected) |
| Weekend dates | rejected |
| The same session in two files | the file with the most valid minutes is used. Closes that differ by more than 0.05% on more than 5 minutes reject the session |

Before 2011 NSE opened at 09:55, so those sessions are short by design. They are rejected with that reason, not
silently padded.

## Output (immutable)

`runtime/external/aeron7/<importer version>-<source commit>/`:

- **`manifest.json`.** The source URL and commit, the importer version, every source file (path, **sha256**, symbol,
  rows, sessions, per-file validation counts), every partition's content hash, and every session's validation result.
  It also holds the status.
- **`1m/symbol=*/year=*.parquet`** (accepted sessions only, with `source_file`) and
  **`5m/symbol=*/year=*.parquet`** (with `n_1m`).
- **`horizons/symbol=*.parquet`.** 5-minute decision points with the desk's features. Each of 30m, 60m, 120m and
  close has its own label: `fwd_ret_*`, `y_*` and `label_end_*`, never reaching past the session.
- **`quality.json` / `quality.md`.** Coverage by year, missing-minute rates, duplicate and conflict counts, rejected
  sessions and rejected files.
- **`verification.json`.** The independent check.

A partition is written once. Re-importing the same source commit with the same importer must reproduce identical
partitions, or it fails (`ImmutableViolation`). A new source commit or importer version is a new dataset folder.

## The independent check

`external-verify` compares randomly chosen accepted sessions with Yahoo Finance's daily OHLC (^NSEI, ^NSEBANK): 80 per
symbol, seeded. The tolerances are pre-declared:
- the day's high and low from the minutes within **0.2%**;
- the last minute's close within **0.3%** (NSE's official close is computed over the last 30 minutes, so it is not a
  print).

The dataset becomes `external_verified` only if, for every symbol, at least 50 sessions were compared and **≥ 95%**
pass. The failures are listed, by year.

## The record so far (source commit 906fc2378b)

**Importer `aeron7-1`.**
- Of 3,139 index files, 2 were rejected and 756 rows were unparsable.
- 3,230 NIFTY and 3,190 BANKNIFTY sessions were accepted.
- The check, at the declared tolerances: **NIFTY 95.0% pass (exactly the bar), BANKNIFTY 90.0% FAIL**, so the
  dataset stayed `external_unverified`.
- The failures exposed an importer defect. Until NSE's December 2010 pre-open change the session opened at 09:00, and
  `aeron7-1` dropped those 09:00–09:14 minutes as out-of-session. That corrupted 2010's day lows and opening features.

**Importer `aeron7-2`.**
- It rejects those 09:00-open sessions, with the reason on record.
- A new dataset folder was written. `aeron7-1` stays as it was; immutable means fixed, not overwritten.
- 3,036 NIFTY and 3,032 BANKNIFTY sessions were accepted.
- The identical check: **NIFTY 98.7% (79 compared), BANKNIFTY 95.0% (80), both pass**. The median absolute gap is
  0.00% on day high and low and 0.05–0.07% on the close.
- Every remaining failure but one is a close-only gap of 0.3–0.6%: NSE's official close is a 30-minute weighted
  average, not the last print.
- BANKNIFTY sits exactly at the 95% bar. Status: `external_verified`, with the use restrictions unchanged.

The tolerances and the bar were not changed between the two runs. Only the importer defect the first run exposed was
fixed.

## Pre-registered intraday direction tests

`docs/prereg/intraday_direction_v1.json` fixed seven hypotheses × two indices, the statistic, the dev period
(→ 2018) and the lock period (2019 →), and both decision rules before any of them touched these data. They have a
literature or market-structure reason, and were not found by searching:
- intraday momentum (Gao, Han, Li & Zhou 2018), with and without the overnight gap;
- first-hour continuation;
- large-gap behaviour;
- the 30-minute opening-range breakout;
- momentum in high volatility.

The rules:
- one trade a day, so no overlapping samples;
- Newey-West t;
- Benjamini-Hochberg across all 14 dev tests, plus the futures round trip as a materiality bar;
- the selected tests' direction is frozen, and they are evaluated once on the lock period.

`python -m quantdesk autolearn prereg` runs dev (repeatable, deterministic). `--open-lock` evaluates the lock and
refuses ever after for the same spec hash. Results are kept in `docs/prereg/results/` under the spec's hash. Same
restrictions as the rest of this dataset: direction research only, no option or profitability claim.

### The record: intraday_direction_v1 (spec sha256 5367cc9ae63c…)

The spec was committed in d4b53d8 before any of these tests touched the data. Dev ran 2010–2018 (2,011 NIFTY and
2,008 BANKNIFTY sessions); the lock ran 2019 to Feb 2023 (1,023 each).
- **Intraday momentum (Gao et al.) does not appear** in either index: NIFTY +0.9 bps a day (t 1.6), BANKNIFTY −0.5.
  Nor does it in high volatility.
- **NIFTY first-hour continuation** was significant on dev (+5.1 bps, t 3.3, q 0.007), but below the 6.6 bps futures
  round trip, so it was not selected.
- **BANKNIFTY 30-minute opening-range breakout** was the one selection (+8.4 bps, t 3.6, q 0.005, in the follow
  direction). Its dev years were uneven (2013 +26, 2015 +19, 2012 −1.8, 2010 −5.0).
- **Lock (opened once, 3 Oct 2026): fail.** +3.55 bps a day over 952 days, t 0.96, one-sided p 0.17, −2.6 bps net of
  the hurdle. It decayed after 2018, the way a crowded, well-known rule does.

So no pre-registered intraday direction rule survived its untouched period at the futures cost. The lock for this
spec is spent. A new idea needs a new spec, committed before it runs.

### The record: vol_forecast_v1 (spec sha256 f2d4d047ee19…)

The spec was committed in 617ed1b before the study ran. The question: how well does the desk's VolForecaster
(realised part) forecast realised variance over the next 30m / 60m / 120m / to the close?
- **Dev (2013–2018 yearly folds, both indices).** The desk's forecaster lost to both alternatives in every year, on
  both indices, at every horizon (mean QLIKE 0.20–0.26). The seasonal version cut that by ~20–25%. HAR was best
  everywhere, so it was selected for all four horizons.
- **Calibration (dev).** On 30-minute horizons the desk expects moves 15–30% bigger than realised in the morning and
  midday (move ratio 0.70–0.87), and smaller in the last 90 minutes (~1.15). Its constant per-minute σ ignores the
  intraday volatility profile. Part of any ratio below 1 is fat tails, which a perfect variance forecast shows too.
- **Lock (2019 to Feb 2023, opened once on 4 Oct 2026): all 8 tests pass.** QLIKE gain over the desk's forecaster:
  - NIFTY: 20% (30m), 27% (60m), 35% (120m), 28% (close);
  - BANKNIFTY: 13% (30m), 18% (60m), 25% (120m), 21% (close);
  - Diebold-Mariano t: +4.6 to +12.7.

The first pre-registered result in this project to pass its locked period. Its use is fixed by the spec: only as the
desk's realised-volatility input. Whether it improves option plans is a question for plan research on real
point-in-time quotes, not for this study. The live forecaster's 30% IV blend was not tested here (no IV in this
dataset).

## Kaggle index minutes (`quantdesk/ml/intake.py`, P0.2)

`python -m quantdesk ml import --source <folder> [--out DIR] [--version 18] [--reviewed FILE]`. Tier T1b of
[ML_PHASE0.md](ML_PHASE0.md). The source is the owner's `debashis74017/nifty-50-minute-data` (one CSV per symbol,
`date,open,high,low,close,volume`, bar-start labels): NIFTY 50, NIFTY BANK and INDIA VIX, 2015-01-09 to 2026-05-15. Status
`external_unverified` until the independent check of P0.6; licence unknown, so nothing is published; the same allowed uses and the
same refusals as above (`ALLOWED_USES` and `FORBIDDEN_NOTE` are the aeron7 importer's own, imported, not restated).

**Rules** (pre-declared; every one is in the manifest, and a test pins each number):

| Check | Treatment |
|---|---|
| Header is not exactly `date,open,high,low,close,volume`; a listed file is missing | the import stops; nothing is guessed |
| Unparsable or non-finite row; bad price (≤ 0, high < low, open or close outside the range); negative or fractional volume | dropped and counted |
| A stamp 1 to 15 seconds past the minute | floored to the minute and counted. In this source it is 2015 only (about 10,700 rows per file) |
| A stamp more than 15 seconds past the minute | dropped and counted (11 per file), never rounded |
| Minutes outside 09:15 to 15:29 | dropped and counted |
| A minute with two identical bars / two different bars | one kept / both dropped |
| Weekend date; fewer than 360 of the 375 regular minutes | session **rejected** (the special Saturday, Sunday and Muhurat sessions land here) |
| A one-minute move above 5% (indices only, not the VIX); 10 or more consecutive flat bars repeating the previous close | session goes to **review**: out by default |

**Review, not a blanket drop.** The old rule dropped any session with a move above 5%, which deletes real crash days. A move that
big, or a run of stale bars, is either the market (a halt and its rebound) or a data fault (a frozen feed), and only a person can
tell. Those sessions are excluded and listed in `quality.md` with their evidence (the other index moving the same way within a
minute; both indices disagreeing about the day). `quantdesk/ml/reviewed_sessions.json` admits one, with evidence of at least 40
characters, the codes it covers, and no hard rejection. It ships empty. Its hash is part of the dataset identity, so admitting a
session is a new dataset, never an edit.

**Identity.** `dataset = ml-intake-1-<12 hex>`, from the source files' sha256, the rules and the reviewed list. The manifest holds
each file's sha256 and drop counts, each partition's canonical content hash (independent of pandas version, datetime unit and
string dtype), every session's validation, and one dataset digest. The import time, the status and the source's version label are
not part of the digest. A partition is written once; the same inputs reproduce the same digest anywhere, and a different digest in
the same folder is an `ImmutableViolation`. `load()` also refuses: a folder without a manifest, unverified data unless the caller
says so, a use outside `ALLOWED_USES`, a partition added, missing, or no longer hashing to the manifest.

**The record (Kaggle version 18, 24 Oct 2026; digest `d5115969ec8a94ea`).**

| | NIFTY | BANKNIFTY | INDIA VIX |
|---|---|---|---|
| Rows | 1,048,738 | 1,048,705 | 1,048,338 |
| Sessions kept / in review / rejected (of) | 2,781 / 4 / 24 (2,809) | 2,781 / 3 / 25 (2,809) | 2,749 / 7 / 52 (2,808) |
| Rejected for: weekend / fewer than 360 minutes (a session can be both) | 11 / 19 | 11 / 20 | 11 / 47 |
| Stamps floored / dropped as ambiguous | 10,682 / 11 | 10,684 / 11 | 10,740 / 11 |
| Bad-price rows dropped | 0 | 0 | 2,547 |
| Missing-minute rate in the sessions kept | 0.009% | 0.009% | 0.010% |

- **Review queue (14 sessions).** 2017-07-10: a freeze of 60 (NIFTY) to 110 (BANKNIFTY) bars, cause unknown. 2020-03-13: flat
  bars during the morning, then a +6.0% (NIFTY) and +5.9% (BANKNIFTY) move in the *same minute*, 10:20 to 10:21; the provider's
  own daily low (8,555.15) is the last print before the jump. Both indices corroborate each other, which fits a halt and a
  rebound on resumption; not yet matched to an NSE notice. 2020-03-23: 43 and 50 flat bars, also both indices. 2022-03-07: NIFTY has
  a 14-bar freeze while BANKNIFTY has only 325 minutes, the one day in 11 years the two indices disagree about. The VIX has seven
  (stale runs of 18 to 155 bars).
- **Correction to the intake report.** The 6% one-minute move is 13 March 2020, not the 4 June 2024 election result the report
  guessed.
- **Not done here.** No independent check (P0.6: Yahoo daily bars, the aeron7 overlap to Feb 2023, NSE's official close); no
  exchange-holiday calendar for the years before the desk's own; the last session, 15 May 2026, is cut off at 13:20 and is
  rejected as short; the hole from 15 May to early September 2026 is still open.
