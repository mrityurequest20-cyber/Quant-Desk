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

`python -m quantdesk ml import --source <folder> [--out DIR] [--version 18] [--reviewed FILE]`. The source is the owner's
`debashis74017/nifty-50-minute-data` (one CSV per symbol, `date,open,high,low,close,volume`, bar-start labels): NIFTY 50, NIFTY BANK and
INDIA VIX, 2015-01-09 to 2026-05-15. Every row is tagged tier `T1b`, which here means **this source, all years** (ML_PHASE0.md's first
table described T1b as only Mar 2023 to Sep 2026; the 2015 to Feb 2023 overlap with the aeron7 import is what lets P0.6 cross-check the
two). Status `external_unverified` until the independent check of P0.6; licence unknown, so nothing is published; the same allowed uses
and the same refusals as above (`ALLOWED_USES` and `FORBIDDEN_NOTE` are the aeron7 importer's own, imported, not restated). **There is
no volume**: it is 0 in every row of all three files, so no volume-based feature or check is possible.

**Rules** (pre-declared; every one is in the manifest, in the dataset identity, and pinned by a test):

| Check | Treatment |
|---|---|
| Header is not exactly `date,open,high,low,close,volume`; a listed file is missing; more than 1% of a file's rows unparsable; a file with no passing session; more 15:30 bars than 09:15 bars (an end-labelled file) | the import stops; nothing is guessed |
| Unparsable or non-finite row; bad price (≤ 0, high < low, open or close outside the range); negative or fractional volume | dropped and counted |
| A stamp 1 to 15 seconds past the minute | floored to the minute and counted. In this source it is 2015 only (10,682 to 10,740 rows per file) |
| A stamp more than 15 seconds past the minute | dropped and counted (11 per file), never rounded: `09:19:55` could belong to either neighbouring minute |
| Minutes outside 09:15 to 15:29 | dropped and counted |
| A minute with two identical bars / two different bars | one kept / both dropped (3, 2 and 3 minutes per file) |
| Fewer than 360 of the 375 regular minutes; a first or last bar more than 5 minutes from the open or the close; a 15:30 bar and no 09:15 bar on a day | session **rejected** (`short_session`, `truncated`, `end_labelled`; a short weekend session is also `weekend`). The last one catches a day labelled by its end inside a file that is otherwise bar-start, which the whole-file check cannot see |
| A one-minute **log** return above 5% (indices only); more than 3% of the bars stale (indices only); 10 or more consecutive stale bars; a weekend date with a full session | session goes to **review**: out by default |

A stale bar is `open = high = low = close = the previous close` on consecutive minutes. The jump rule is on log returns, the quantity a
realised variance is made of: a +5.05% simple move is a 4.93% log move and is not a jump; a -4.95% simple move is a 5.07% log move and
is. The volatility index is exempt from the jump and share rules (it is noisy by nature and prints flat minutes) but not from the run rule.

**Review, not a blanket drop.** The old rule dropped any session with a move above 5%, which deletes real crash days; and a hard
"weekend" rejection deleted the Budget Saturdays, which are real sessions. A big move, a frozen feed or a full weekend session is
either the market or a data fault, and only a person can tell. Those sessions are excluded and listed in `quality.md` with their
evidence and their **rank by realised variance** (so the cost of excluding them is visible). `quantdesk/ml/reviewed_sessions.json`
admits one. An entry names the reviewer and the date, the sha256 of the source file it was reviewed on, at least 40 characters and 6
words of evidence, and the number each code was reviewed against (`observed`); it applies only while the session has no hard
rejection, the entry covers **every** code the session trips, and the file and the numbers are the same. It ships empty. Its hash is
part of the dataset identity, so admitting a session is a new dataset, never an edit. **A study on the default set is censored at the
tail** (the highest-variance review session, 2020-03-13, ranks 1 of 2,789 for NIFTY): a spec must say so, or admit them first.

**Identity and integrity.** `dataset = ml-intake-2-<12 hex>`, from the source files' sha256 and metadata, the rules and the reviewed
list. The manifest holds each file's sha256 and drop counts, each partition's canonical content hash (independent of pandas version,
datetime unit and string dtype), every session's validation (numbers to 12 significant digits, so a different CPU cannot change the
digest), the code commit, and one dataset digest. The import time, the status, the source's version label and the code commit are
not part of the digest. A partition is written once; the same inputs reproduce the same digest, and a different digest in the same
folder is an `ImmutableViolation`. `load()` recomputes the manifest's digest and checks the folder name against it, refuses a
folder without a manifest, unverified data unless the caller says so, a use outside `ALLOWED_USES`, a symbol that is not in the
dataset, and a partition added, missing, or no longer hashing to the manifest. `external_verified` counts only when a
`verification.json` written by the P0.6 check names this digest and says it passed; the word in the manifest is not evidence.
**What this protects, and what it does not:** it catches an accidental or careless change (a hand-edited partition, a hand-edited
manifest, a different source file). It cannot stop someone who rewrites a partition, its hash in the manifest and the manifest's digest
together (the folder name covers the source files, the rules and the reviewed list, not the partitions); for that a spec records the digest it was run on and
passes it to `load(expected_digest=...)`, and the P0.6 record should carry a hash of the check's output. A reviewed entry's reviewer is free text and the
numbers it carries are compared only for the codes the session trips: the list is accountable through review of the commit that adds an entry.

**The record (Kaggle version 18, 24 Oct 2026; dataset `ml-intake-2-feae259bdba6`, digest `47d28d6376ca63af`, imported from a clean tree at code commit `10a40f5`).**

| | NIFTY | BANKNIFTY | INDIA VIX |
|---|---|---|---|
| Source rows / rows in the dataset | 1,048,738 / 1,042,414 | 1,048,705 / 1,042,415 | 1,048,338 / 1,030,412 |
| Sessions kept / in review / rejected (of) | 2,780 / 9 / 20 (2,809) | 2,780 / 8 / 21 (2,809) | 2,748 / 12 / 48 (2,808) |
| Rejected for: weekend / fewer than 360 minutes / truncated (a session can be several) | 6 / 19 / 7 | 6 / 20 / 7 | 6 / 47 / 7 |
| Stamps floored / dropped as ambiguous | 10,682 / 11 | 10,684 / 11 | 10,740 / 11 |
| Bad-price rows dropped | 0 | 0 | 2,547 |
| Missing-minute rate in the sessions kept | 0.008% | 0.008% | 0.009% |

Against the first version of this importer, the only change to what is kept is one session per symbol, 2015-01-19, whose first bar is
at 09:26: the new `truncated` rule drops it (checked: the new dataset's rows are a strict subset of the old, with identical bars).

- **Review queue (29 sessions).** All five full-length weekend sessions of each symbol (2015-02-28, 2020-02-01, 2024-01-20,
  2025-02-01, 2026-02-01); the dates of four are Union Budget days, but none is matched to an NSE circular, and 2024-01-20 has
  375 minutes when the two other special Saturdays of 2024 have 105, cause unknown. Their NIFTY variance ranks are 24, 54, 1606, 100
  and 34 of 2,789 (three of them, 2024-01-20, 2025-02-01 and 2026-02-01, fall inside the Mar 2023 to May 2026 evaluation window).
  **2017-07-10:** all three feeds are essentially frozen for about three hours (NIFTY: 165 of 375 bars stale, longest run 60; BANKNIFTY
  181, run 110; the VIX a run of 155); cause unknown. **2020-03-13:** NIFTY is flat 09:22 to 10:05 (44 bars) and 10:14 to 10:20
  (7 bars); BANKNIFTY 09:22 to 10:12 (51) and 10:14 to 10:20 (7); then in the same minute, 10:20 to 10:21, NIFTY moves +6.0% (log;
  +6.2% simple) and BANKNIFTY +5.9% (+6.0%). The pattern, a long flat stretch, a short active window, seven flat bars, a jump, fits a
  circuit-breaker halt, a pre-open call and a resumption (inferred from the exchange's rules, **not matched to an NSE notice**), and
  the active window's prints (for example NIFTY 8,476.15 at 10:07) look like indicative values. The provider's own daily bars agree
  only in part: the NIFTY daily low (8,555.15) equals the last print before the jump, but the minute series prints a low of 8,476.15,
  0.92% below it; the BANKNIFTY daily low (21,351.7) is below its minute low (21,397.45). So the minute and daily series disagree
  about this session, which is a reason to keep it out until someone decides. **2020-03-23:** 43 (NIFTY) and 50 (BANKNIFTY) flat bars,
  the same pattern, no jump. **2022-03-07:** NIFTY near-frozen in runs of 7, 5, 10 and 14 (37 of 372 bars stale) while BANKNIFTY has
  only 325 minutes: the one day in eleven years on which the indices disagree about a day. The VIX has seven sessions with frozen
  runs of 18 to 155 bars: three on dates already listed (2017-07-10, 13 and 23 Mar 2020) and four of its own (2019-12-02, 2020-01-06, 2020-03-24, 2021-12-06).
- **Correction to the intake report.** The 6% one-minute move is 13 March 2020, not the 4 June 2024 election result the report guessed.
- **For the HAR specification.** It must state: (1) the default set excludes the review sessions above, among them, for NIFTY, two of the
  three highest-variance days of 2015 to 2026 (ranks 1 and 3), so it is censored at the tail unless they are admitted first; (2) a daily or lagged series built
  from the kept sessions has multi-day gaps where a session is out (the overnight gap spanning the removed 23 Mar 2020 is -10.3% simple
  (-10.8% log) for NIFTY: the 24 Mar open against the last minute close of 20 Mar), so a "previous session" feature is the previous *kept* session; (3) a kept session can have up to 14 missing minutes inside
  it; realised variance as a sum of squared consecutive returns treats a gap as one return, and forward-filling to a regular grid would
  remove that variance; (4) there is no volume; (5) **what the Mar 2023 to May 2026 window itself loses** (NIFTY: 792 session rows through 14 May 2026, 786 of them weekdays and 6 weekend rows, 784 kept): the default set
  drops the window's 3rd and 10th highest-variance days (2026-02-01 and 2025-02-01, both scheduled Budget days; 4th and 7th for BANKNIFTY), so the full-sample
  ranks (34 and 100) understate the loss for a window evaluation: admit them first or say the evaluation is censored there; the hard-rejected special sessions
  (the Muhurat evenings of 2023-11-12, 2024-11-01 and 2025-10-21, the 105-minute Saturdays 2024-03-02 and 2024-05-18, and 15 May 2026) are part of the sample
  definition and the spec should list them; together with the review sessions they carry about 1.8% of the window's NIFTY variance; (6) the Monday after a dropped
  Budget day (2025-02-03, 2026-02-02) takes its lagged features from the Friday; (7) from March 2023 there is **no second source**: the aeron7 overlap ends in
  Feb 2023, so the 99.8% variance agreement says nothing about the window, and the only anchors are the provider's own daily file and Yahoo (P0.6, not done);
  (8) the locked HAR was fitted on the aeron7 data, so the realised-variance definition must be the same on both sides (close-to-close agrees across the
  sources; highs and lows differ on 12 to 15% of minutes, so no range-based input); (9) the last minute's close is not NSE's official close (0.05% median, 0.30%
  NIFTY and 0.44% BANKNIFTY at the 99th percentile); (10) the spec records the `expected_digest` it ran on; (11) the first 22 window sessions need minutes from before March 2023 for their lagged features: the
  spec must name which source supplies them (aeron7 and Kaggle agree on close-to-close variance and differ on highs and lows); (12) whether to admit any review session is
  decided and recorded **before** the evaluation run, because admitting one changes the dataset and its digest, and `expected_digest` is the digest after that decision;
  (13) 51 of the window's 837 weekdays have no row; all are exchange holidays (the 8 in 2026 match the desk's own holiday list, the 43 before it were matched from the
  data steward's knowledge of NSE's calendars), and the spec should record that check; (14) the window effectively ends on 14 May 2026: the cut-off 15 May session
  (246 NIFTY and 274 BANKNIFTY bars, 0.11% of the window's NIFTY variance) is rejected, so a target 'to the close' must not use it; (15) six kept window sessions have
  missing minutes (the largest, 7 on 2023-06-14 and 6 on 2024-04-23), so a realised variance defined on a regular grid must say what it does there.
- **Not done here, and the limits.** No independent check (P0.6: Yahoo daily bars, the aeron7 overlap to Feb 2023, NSE's official
  close). The only anchors so far are this provider's own daily file and the two indices against each other: the daily file agrees with
  the minute bars closely on 99% of kept days (high, low, close at the 99th percentile: NIFTY 0.05%, 0.05%, 0.30%; BANKNIFTY 0.09%, 0.12%,
  0.44%) but not on every day: the worst are NIFTY 0.68% on the high (2016-01-20), 0.35% on the low, 1.22% on the close (2015-08-10), BANKNIFTY
  1.05% (2015-03-09), 1.30% (2018-04-23) and 1.21% (2020-03-18); one NIFTY day and four BANKNIFTY days are off by more than 1% on the high, low or close (eight BANKNIFTY
  days if the open is included, the worst 2.91% on 2015-03-04). The BANKNIFTY daily file repeats three dates in the kept range (2015-06-29, 2015-07-02, 2015-08-10) as
  intraday snapshots with scrape-time stamps, not daily bars, and they are left out of this comparison. It is the same provider's, and 2015-08-10 looks like an error in the
  daily file (the minutes slide smoothly into their close); a feed that lags smoothly, a common-mode timestamp shift, or a history the
  provider reconstructed would not be seen. No exchange-holiday calendar is applied before the desk's own (the data steward's check against 46 known
  weekday holidays found none present, which is evidence, not proof; not re-run). The last session, 15 May 2026, stops at 13:20 (NIFTY), 13:48
  (BANKNIFTY) and 13:07 (VIX) and is rejected as short. The hole from 15 May to early September 2026 is still open.
