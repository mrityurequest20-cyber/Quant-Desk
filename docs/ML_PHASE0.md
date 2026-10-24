# ML Phase 0: the platform, built from our own data (started Sat 24 Oct 2026)

The owner started this on **24 Oct**, not in November, and wants everything **home-built**: our own data, our own code, small models
trained on CPU. No pre-trained models or hosted model services (Hugging Face and similar are parked, see
[MASTER_PLAN.md](MASTER_PLAN.md) section 11). This file is the work plan for Phase 0 of [ML_ROADMAP.md](ML_ROADMAP.md); that file
keeps the rules (section 2) and the model list. Where they differ on *dates*, [MASTER_PLAN.md](MASTER_PLAN.md) wins.

The model programme, the twin test for options and the open items are in [ML_RESEARCH_PLAN.md](ML_RESEARCH_PLAN.md).

## What Phase 0 is, and what it must never do

Phase 0 builds the tools every later model needs: a spec template, a dataset builder, labels, a leak-proof test harness, a model
card and a registry. It is **offline and read-only**:

- It does not import the live engine, write to a journal, place or size anything, or use a secret.
- No model is trained to *influence a decision* in Phase 0, and none is wired into the live loop. The first model work is M1
  (volatility against HAR); models that can affect trading wait for the P1 exit (the record is correct and recoverable, mid January).
- Every artifact is reproducible: the same inputs, code and settings give the same digest.

## Work items

| # | Item | Deliverable | Exit test | Needs |
|---|---|---|---|---|
| P0.1 | **Spec template and model-card format** | [ml/SPEC_TEMPLATE.md](ml/SPEC_TEMPLATE.md), [ml/MODEL_CARD_TEMPLATE.md](ml/MODEL_CARD_TEMPLATE.md) (in this change) | A spec written from the template passes `experiments --check` | nothing |
| P0.2 | **Data tiers and provenance** | A manifest per dataset: source, commit or date, row counts, sha256 of every file, status (`external_unverified` or `verified`), allowed uses (as [EXTERNAL_DATA.md](EXTERNAL_DATA.md)) | A dataset without a manifest is refused by the builder | nothing |
| P0.3 | **Dataset builder** | `python -m quantdesk ml build`: point-in-time tables, first from index minutes and daily bars for M1 (features at a decision time, labels over 30m / 60m / 120m / close that never reach past the session) | Two builds from the same inputs give identical digests; no table uses data after its decision time | P0.2 |
| P0.4 | **Leakage tests and purged walk-forward harness** | Splits with purge and embargo, a test that injects a known leak and must fail, a baseline comparison | The injected leak is caught; **the harness reproduces the locked HAR result on 2019 to Feb 2023** (8 of 8 cells) within a stated tolerance | P0.3 |
| P0.5 | **Registry and prediction-event schema** | Model id, version, provenance (data digests, code commit, training window), status (offline, shadow, applied), rolling grade; the journal event format for a live prediction (design only; the engine side is a later, reviewed change) | A model card is generated for every run and refuses to build without its provenance | P0.1, P0.4 |
| P0.6 | **Independent check of the 2023 to 2026 index minutes** | The import exists (P0.2); this is the check that can make it `external_verified`: Yahoo daily bars, the aeron7 overlap to Feb 2023, the Kotak overlap and NSE's official daily close, written as a `verification.json` that names the dataset digest; plus a source for 15 May to early Sep 2026 | Status `verified`, or rejected with reasons; coverage and quality report | **the owner's source (name, format, licence)** |
| P0.7 | **Labelled-setup counter** | The number of labelled shadow setups per week (live Shadow stage and the offline replay), in the Saturday digest; progress toward the 300 to 500 the entry filter needs | The digest line appears and matches the journal | the scope ladder's Shadow stage |
| P0.8 | **Retrain job** | A scheduled read-only workflow on CPU that rebuilds datasets and re-fits registered models (no write permission, no secret) | A drill run reproduces the committed HAR coefficients | P0.3 to P0.5; workflow review |

*P0.2 status (24 Oct): built for the index minutes, `quantdesk/ml/intake.py` with `python -m quantdesk ml import`; `load()` refuses a dataset without a manifest, one whose manifest or partitions no longer hash to their digest, and unverified data unless asked. The option and tape tiers (T2) are not covered yet.*

Order: P0.1 and P0.2 first (this week), then P0.3 and P0.4 together. P0.6 can start now that the owner's source is imported. P0.7 and P0.8 are last.

Target: Phase 0 done by **mid November**, as the ML roadmap says. If it slips, section 0's cut order in the master plan applies.

## Status (24 Oct 2026)

- **P0.2 done** (merged, #107): `python -m quantdesk ml import`; dataset `ml-intake-2-feae259bdba6`, still `external_unverified` until P0.6.
- **P0.3 built** (`quantdesk/ml/build.py`, `python -m quantdesk ml build --dataset <dir> --profile-end <date>`): the M1 table, one row per
  (symbol, day, decision minute, horizon), made by the study's own `volstudy` code (called, not copied) and equal to `volstudy.fit_har`'s frame bit for bit
  (458,623 rows for NIFTY and BANKNIFTY on the Kaggle source, 9 s). Labels never reach past the session (checked on every build and every load). What a reader must know:
  - **The seasonal profile is a fit.** It is fitted on sessions up to `--profile-end` and every row carries `in_profile`. `load_table` withholds those rows by default
    (`scoring_only`), `splits.check_test_mask` refuses a fold that would score one, and a study that needs the profile refitted per fold rebuilds the table per fold
    (that is what the reproduction below does).
  - **Three things depend on the future by construction**, and are not features: `miss_frac` (the share of the *label* window that was missing), whether a row exists at all
    (windows more than 20% missing are dropped), and the profile of the `in_profile` rows. The point-in-time canary (`ml/pit.py`) runs against the real builder and a planted leak is caught,
    but it perturbs returns, never the missing-minute mask, so it cannot see the first two.
  - **Reserved window.** Rows from 1 Mar 2023 are the stretch kept for the one-shot, pre-registered evaluation of the locked HAR model; `load_table` withholds them unless a spec is named, and `build_tables` refuses a `profile_end` inside it (the profile would be fitted on the reserved stretch and contaminate every later row).
  - **Provenance.** Every row has a `tier`; the file's own metadata and the manifest carry the input's status and the `not_for` restriction; `load_table` refuses a table built from
    `external_unverified` data unless `allow_unverified=True`, and refuses a use outside the dataset's allowed uses. The status is part of the table's identity, so a rebuild after P0.6 is a new table.
  - **What the study dropped.** The manifest counts, per symbol, the sessions in the grid and with rows, the rows possible and kept, and lists the sessions lost (the study's own rules lose the first five sessions of a series
    and five after any break longer than four days; windows above 20% missing are dropped). The default dataset also omits the review sessions, among them the two highest-variance days of 2015 to 2026 for NIFTY (13 and 23 Mar 2020, EXTERNAL_DATA.md item 1).
  - **Leading gaps.** A session with no bar at the open is refused (`volstudy.grid` back-fills its first bars from a later close). The aeron7 data the locked study used has five such sessions for each index, the latest on 9 Jul 2018; the locked run included them, so
    the reproduction allows them explicitly and prints them. Their effect on the locked result is small (five sessions among thousands, all in the development years) but it is a look-ahead in the locked run that nobody had recorded; it has not been quantified.
  - **Identity, and a deviation from the exit test as worded ("identical digests").** The table's folder name is a hash of the input dataset's digest, status and tier, the recipe (symbols, `profile_end`, constants, the source of the functions that make the rows) and the builder version: identical on any machine. The manifest digest is not a pure function of the inputs
    (it also covers the parquet file's bytes). On this machine and under Python 3.11 and 3.13 the table's bytes were identical, but float values come from numpy reductions that can differ in the last bit elsewhere, so a rebuild is compared with a stated tolerance
    (`rtol` 1e-9 against the larger of the two values and the column's median magnitude) instead of a value hash. `intake.canonical_hash` would allow a 12-digit-rounded value hash; it was not used.
- **P0.4 harness built** (`ml/splits.py`, `ml/pit.py`, `ml/reproduce.py`, `ml/study.py`): purged walk-forward; combinatorial purged CV and its backtest paths; a verifier that the tests inject leaks against; a perturbation canary.
  **Features reach back in sessions, not days.** The M1 table's `x_prev5` and the A / B priors average the previous five sessions of the symbol's grid, which in thin stretches of the real data span up to 20 calendar days (the auditor measured 11 to 19 on the Kaggle table),
  so no time embargo can cover them. Every table row therefore carries `session` (its day's ordinal in the symbol's grid), and `splits.cpcv(..., session=, lookback_sessions=)` (or `build.cpcv_for`) also removes every training sample whose feature window contains a test session or an
  earlier test decision of its own day (`feature_window_hits`); `check_no_overlap` takes the same arguments to verify a split. `embargo` is a required keyword (negative refused) and `embargo=0` without a feature lookback must be acknowledged with `samples_independent=True`; the table's `session` column is written by the builder and pinned by the file's hash, and is not re-derived from the calendar at load (it matters only to another writer). A test builds a calendar with a thin stretch, shows the ten-day time embargo leaves leaks (found by brute force), and that the session-aware purge leaves none.
  **Exit test, met on 24 Oct through the platform:** `python -m quantdesk ml reproduce --dataset <aeron7 dir>` recomputes the locked study's dev selection, its lock and **the fitted seasonal profile** with `build_tables` per fold (profile fitted on that fold's training sessions only), `walk_forward` for the yearly folds and the study's own scorers, writes nothing, and compares
  **every number in the committed result: 1,132 numbers, 8 of 8 cells, largest difference 3.7e-14, about 22 s.** It first checks that the dataset's sessions are the ones the result was computed on and refuses before computing if not. It also refuses a split whose training sessions are not the sessions the profile was fitted on (a planted split that drops the oldest years is caught).
  Planted builder and split bugs fail it. `--through study` is the older route: it reruns `volstudy.run` into a scratch folder outside any git working tree, and shows only that the old study is deterministic and the committed file untampered. CI does not have the aeron7 data, so the real-data test is skipped there; a synthetic equivalent, with the planted bugs, runs in CI.
  **Not yet:** the baseline comparison (a scorer that grades any model against HAR and the desk's forecaster on the same folds) lands with the evaluation toolkit.
- **A boundary note.** The ml modules' own imports do not reach the engine, journal, risk or execution: the builder calls the locked study's code, which reaches (through `autolearn.prereg` → `evaluate` → `features`) the desk's pure
  computation modules `intraday.quant`, `.chains`, `.feeds`, `.orderflow` and `options.*`, whose network clients and secrets are used only inside methods, never at import. `tests/test_ml_build.py` is an **allowlist**: after each ml module has done its work (the builder
  builds and loads, `reproduce` imports the study) in a clean interpreter, the only `quantdesk` modules loaded must be the ml package, the study's own imports and those modules; any other, any socket opened or resolved, any process started, or any of `requests`, `kiteconnect`, `yfinance`,
  `anthropic` loaded, fails it. **The command line process is different:** `quantdesk.cli` builds every subcommand's parser, which imports the whole desk (58 modules, including the engine and the broker adapter). That is import only, nothing in it runs, and it was already so for `ml import`;
  the claim here is about the ml modules, not the process.
- **Review of the first head (`ad88888`).** Risk and compliance: CLEAR, no veto, five should-fixes. Auditor: NOT CLEAR, three blockers and eight should-fixes. All were made in the next commit except the ones listed here: the reproduction
  guard now refuses any folder inside the repository (symlinks and `..` resolved; the output name is the one the study writes), the tolerance is capped at 1e-6 and only `/lock/opened` is ignored, `embargo` is required and a missing time is refused, the exit test runs through the platform,
  the table's status and tier are in its identity and in the file, the leading-gap guard, the `tier` column, the scoring-only and reserved-window gates, the manifest accounting, the per-column tolerance, and tests for every surviving mutant. Said plainly and not changed:
  `volstudy.run` writes `"evidence": "external_verified (underlying only)"` into every result it produces (pre-existing); `--dataset` can point a reproduction at any dataset, in which case the comparison fails; and the reserved-window guard is against accident, not intent
  (anyone can name a spec file).
  **Second review (`2060e3d`).** Risk and compliance: CLEAR again (two should-fixes: tables never written inside a git working tree, and `load_table(dataset=)` re-deriving the status from the dataset's verification record). Auditor: NOT CLEAR, one blocker and six should-fixes, all made: the time embargo could not cover a five-*session* lookback (now the session-aware purge above,
  and the false "ten days is safe" claim is gone), the reproduction now compares the fitted profile (1,132 of 1,132 numbers, not 1,056), the split's training sessions must equal the profile window, a `profile_end` inside the reserved window is refused, the dataset must be the one the result was computed on, the provenance line names the source commit and importer,
  and the leading-gap guard is tested at minute 0 and not minute 1. Said plainly: a forger with write access to the table folder can still relabel a table unless the caller names the dataset; the five back-filled aeron7 sessions per index are an unquantified look-ahead in the locked run and want a desk-request issue.
- **OI shadow (`ml/oi.py`, `docs/prereg/oi_shadow_v1.json`, `python -m quantdesk ml oi --source <tape> --day <date>` and `ml oi-report`)**: open-interest features and a
  pre-registered test, offline and shadow only from Mon 26 Oct 2026. Nothing here votes, sizes, gates, enters or exits, and a promotion to live use is a separate, independently
  reviewed, tighten-only change behind the owner's apply switch after the 120-session read-out. It reads the desk's own chain tape (tier T2), never third-party data. Each session's
  tables are written once (a rerun must reproduce them or it refuses), carry the hash of the code that made them, and the report refuses sessions made by other code. 14 development
  sessions (5 to 23 Oct) fixed the definitions and are not evidence. The primary test is one regression per index (does wall strength predict containment beyond what the
  options market's own implied probability says, within a session); the spec states its power plainly (BANKNIFTY will likely be inconclusive). 40 advanced features (gamma and the
  gamma flip, wall dynamics, concentration, quote microstructure, volume, term, forward and skew) are recorded from the first session, exploratory: described, never tested for
  significance. A feed fault (OI above 1e12 or negative, about 1.1% of snapshots) quarantines the whole snapshot, never clipped. Tests: the module's 98-test file with every
  feature's expected value computed independently; mutation runs of 145 mutants (82 on the OI features, 63 on the advanced ones), the survivors being equivalent mutants.

## Data tiers

| Tier | What | Window | Status and use |
|---|---|---|---|
| T1 | Index 1-minute bars (aeron7 import) and daily bars, F&O bhavcopy | 2007 to Feb 2023 minutes; daily longer; bhavcopy 2019+ | The locked HAR lock used 2019 to Feb 2023. `external_unverified` until verified; underlying-price research only |
| T1b | Index 1-minute bars (owner's Kaggle source; every row of the import is tagged T1b: 2015-01-09 to 2026-05-15, so it overlaps T1 until Feb 2023, which is what lets P0.6 check the two against each other) | imported by P0.2 on 24 Oct, `external_unverified`; the independent check is P0.6; the hole from 15 May to early Sep 2026 is open | Same rules as T1. A **pre-registered, one-shot out-of-sample evaluation of the locked HAR model** on this stretch is written *before* the data is loaded |
| T2 | Our own point-in-time tape: option chains each minute, option minutes, stock minutes | Oct 2026 onwards (about 28 real sessions by late November) | The only source for option-level models. Never mixed with T1 without a provenance column |
| T3 | The journal: decisions, trades, rejections, thoughts, events, plan studies, shadow records | Since the desk started | Labels and counterfactuals |

T2 and T3 grow by about one session a day. There is no history to buy and none is needed to start.

## The rules Phase 0 adds to ROADMAP section 2

1. **Train, freeze, then grade forward.** A model is trained on data up to a cut-off date, frozen (code commit and data digests recorded), then graded only on
   sessions after that date. It is not re-tuned after seeing those results.
2. **One provenance column everywhere.** Each row says which tier it came from; the builder refuses to join tiers without saying so.
3. **A session is the unit.** Trades on NIFTY, BANKNIFTY and SENSEX on one day move together, so labelled setups are counted, but statistics are computed per session.
4. **Quarantine, don't repair.** A bar that fails validity (non-positive, flat, stale, impossible move) is dropped and counted, never silently fixed (the India VIX zero-bar incident is the example).
5. **Public repository.** Raw third-party data is not committed or published unless its licence allows redistribution. Datasets live in releases or
   artifacts with a manifest; a source with a restrictive licence stays out of the public repository (decide with the owner before import).
6. **Home-built.** Small models in our own code (gradient boosting, quantile regression, ridge, logistic). Neural networks only after the simpler models show signal and a spec earns them.

   *Dependencies (added by the PR that introduced `requirements-ml.txt`, 24 Oct).* Five specialist libraries, exact-pinned like `requirements.txt`, in a
   separate file so the desk's own installs are unchanged: `arch` (GARCH-family volatility benchmark for M1), `statsmodels` (quantile and OLS regression
   with robust errors, time-series tests for the leakage harness), `scikit-learn` (ridge, logistic, metrics, calibration), `lightgbm` (CPU gradient
   boosting) and `duckdb` (in-process SQL over the Parquet warehouse for point-in-time dataset builds). None is imported by the trading path: no
   workflow installs `requirements-ml.txt`, nothing outside `quantdesk/ml/` may import these libraries, and Phase 0 stays offline and read-only (above).
- **P0.8 built** (`quantdesk/ml/retrain.py`, `python -m quantdesk ml retrain [--dataset <dir>] [--out <new folder>]`, `.github/workflows/ml-retrain.yml`):
  a drill that refits every registered model (today `c_har`, the file the desk loads) from the aeron7 dataset and compares it field by field with the
  committed coefficients (P0.4's comparison: relative tolerance 1e-9, never wider than 1e-6; provenance is not compared as numbers). It also checks that the
  rebuilt dataset has the recorded source commit, importer and 1-minute partition hashes, and says `reproduced_on_different_inputs` when the numbers match
  but the inputs do not. **First drill (24 Oct, local, the true dataset): 809 numbers, largest difference exactly 0.** The workflow runs Sundays and on
  demand; `permissions: contents: read`, no secret, no token, no push or release, checkout without credentials, the report kept as a 30-day run
  artifact (a test pins all of that). It fetches the source repository at the commit recorded in the committed coefficients, imports it
  (`external_unverified`; the refit reads it anyway and the report says so), refits, and fails the run on any mismatch. The output folder must be outside
  every git tree or under the gitignored `runtime/`, and a report is written once. What it does not do yet: rebuild the Kaggle tables (that data stays
  out of the repository and out of CI), write a model card (a refit has no out-of-sample block until a model with one is registered), or retrain
  anything that is not in `retrain.registry()`; adding a model there is a reviewed change.

## What I need from the owner (only for P0.6)

*Update 24 Oct: the owner named the source (Kaggle `debashis74017/nifty-50-minute-data`) and it is imported. Still open: its licence (the owner chose not to chase it, so nothing is published) and a source for 15 May to early Sep 2026.*

The source of the Mar 2023 to Sep 2026 NIFTY and BANKNIFTY minutes: where it comes from, the file format and columns, the coverage, and whether
it may be redistributed (it will sit in a public repository's release unless you want it kept private). Nothing else in Phase 0 waits on you.
