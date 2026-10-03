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
