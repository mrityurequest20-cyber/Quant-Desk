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

*P0.2 status (24 Oct): built for the index minutes, `quantdesk/ml/intake.py` with `python -m quantdesk ml import`; `load()` refuses a dataset without a manifest, one whose manifest or partitions no longer hash to their digest, and unverified data unless asked. The tape tier (T2) is covered by `ml/tape.py` (below).*

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
- **P0.5 built** (`ml/modelcard.py`, `ml/events.py`, `python -m quantdesk ml card --run <run.json>`, `docs/ml/PREDICTION_EVENT.md`): a model card that refuses to build without its provenance
  (spec hash, a full 40-hex code commit, data manifests and digests by tier, a training window that ends on or before the cut-off, settings and seed, variants tried, baseline,
  an out-of-sample result whose interval contains its difference, leakage tests, status); it is written once per version and is tamper-evident (digest). Status is offline, shadow or
  applied, and `applied` needs the owner's recorded switch. A rolling grade and an automatic demotion that only tightens. The prediction/outcome journal events are design only:
  validated and mapped to the journal call, imported by nothing in the engine. The registry in `autolearn/registry.py` is not duplicated.
- **P0.1 exit test met** (`tests/test_ml_templates.py`): the template carries a machine-readable skeleton (one field per section, the kill threshold a number); a spec filled in from that skeleton is new to `experiments --check` (which tests *novelty*, not rigour: quality stays the research reviewer's job), and a reworded copy of a registered spec (`oi_shadow_v1`) is refused as the same experiment; changing its method makes it a different one.
- **Baseline comparison built** (`ml/baseline.py`, P0.4's deliverable): `oos_block` turns per-session losses of a model and of its baseline into the out-of-sample block a model card requires: the two means, their difference (model minus baseline, negative is better), a Newey-West interval (the desk's own `nw_t` formula, 5 lags, with a Student-t quantile on n-1 degrees of freedom) with its level and method, and the session count. The interval is approximate and says so: simulated coverage of the nominal 90% is 87% at 60 sessions, 88% at 100 and 90% at 250 for independent differences, and 81% to 84% when the differences have an autocorrelation of 0.5; below 10 sessions it was 69%. It refuses with fewer than 60 sessions, a flat difference, or a session key that is not an ISO date, and its output passes `modelcard.check_run`.
- **P0.7 built** (`ml/setups.py`, `web/export_site.py`, `deploy/cloudflare/watchdog.js`): the labelled-setup counter, read from the desk's real record. A labelled setup is a closed **paper trade** (its R is the label; journal `trades`) or an **armed setup the EV gate refused, graded by replay** (`learning.grade_armed`; the journal's `decisions` rows whose key the learning memory lists as graded, labelled when their 45-minute window closed). A third source, **shadow**, is reserved for the Shadow stage of the scope ladder and counts zero until that stage exists. Read-only and importing nothing from the desk (plain `sqlite3` in read-only mode and JSON). A setup counts once by id, in the Indian week its label became known; invalid records are listed, not counted. A replay setup that re-arms the same symbol and strategy within its 45-minute window is the same idea and counts once (the engine re-arms a level every minute), and one that fired as a paper trade on the same symbol within the window counts there only. The line gives the sessions and the session-symbol pairs, because setups from one day are not independent, and says "not available" (not zero) when the journal cannot be read, or what was not counted when it could be read in part. The site export publishes the block as `setups` in `data.json` (a failure there is recorded in the block, never a failed publish), and the watchdog's **W8 Saturday digest** reads it and adds the line; if `data.json` is down, has no `setups`, or says it errored, the digest says so in the line and still goes out. The exit test (the line matches the journal) is `tests/test_ml_setups.py::test_the_digest_line_matches_the_journal`, with the Worker side in `tests/test_watchdog.py`. Limits: the learning memory keeps only the last 2,000 graded armed keys (above the 500 the filter needs), so the replay part of the total can fall as old keys age out; a replay setup's label value is kept only as an aggregate there, so it counts but carries no outcome; the count is of setups, and statistics stay per session.

- **T2 tape registered** (`ml/tape.py`, `python -m quantdesk ml import-tape --source <folder of <day>_<part>_chains.parquet files>`): P0.2 for the desk's own chain tape. It writes one `manifest.json` (per file: sha256, rows, session day, part, time range, underlyings, sources, snapshots, and faults **counted, never repaired**: implausible-OI snapshots by the bound `oi.OI_MAX`, crossed quotes, non-positive spot, implausible changes in OI, exact repeats of a row, **keys recorded twice with different values** (both rows quarantined, neither preferred), model-chain rows, rows outside the cash session; repeats are also looked for across the morning and afternoon files of one day, and the parts' time ranges are checked for overlap, in `day_checks`). The data is **referenced, not copied** (broker-feed data stays on the runner or in a private release; the manifest holds names, hashes and counts, so it may sit in a run artifact or a model card's provenance). A file that is not a tape (missing column, no timezone, rows from another day than its name, empty, unknown part, text where a number belongs) is rejected with its reason and never enters the manifest; two files for one session part are refused, not guessed. `load()` refuses a dataset without a manifest, a manifest that no longer hashes to its digest or whose folder name is not its identity, a missing or changed file (re-hashed on every load), and any use outside `oi_shadow`, `option_research`, `feature_building`, `replay`; by default it drops the model-chain rows (audit F-01), implausible-OI and implausible-change-in-OI snapshots, exact repeats, conflicting keys and out-of-session rows and says how many (`attrs["dropped"]`, first-match counts, and a log warning), repairing nothing. Rows come back sorted by underlying, expiry, ts, strike (so a `shift` or `diff` per strike never reads the future) with a `session` column (IST date). Not yet in a model card: the card's data statuses (`modelcard.py`) do not include `internal_recording`, which is a separate reviewed change. Tier column `T2` and `source_file` on every row. Same files give the same dataset; one more session is a different dataset. The OI shadow keeps reading the tape through `oi.py` and its pinned code: nothing it does changes. First registration on a real tape file (23 Oct morning): 68,306 rows, 10 implausible OI prints (410 rows in their snapshots).

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
- **OI daily check** (`quantdesk/ml/oi_daily.py`, `python -m quantdesk ml oi-daily --source <tape>`, `.github/workflows/oi-daily.yml`): the spec has the desk engineer run
  `ml oi` after each close; this runs the same grading for every forward weekday so far on a fresh machine each weekday at 17:47 IST (tape fetched from the `chains-YYYY`
  releases), so a trading day with no archived tape, or a session that no longer grades, fails the run the day it happens. A weekday without a tape is `holiday` if
  `config/quantdesk.yaml` lists it, `unknown` if the list does not cover the year, otherwise `missing`; only `missing` and `failed` fail the run, and a missing day stays
  failing until it is archived; a day with only the morning part archived, or an index with nothing to grade, is `partial` and fails too; an `unknown` day prints a warning
  annotation (from 1 Jan 2027 until the 2027 holiday list is entered, every tape-less weekday is `unknown`). **It is monitoring, not the record, and the owner should accept it:**
  the registered spec's `deployment` text says "nothing is added to a workflow" and has the desk engineer run `ml oi` after each close. This is a new, separate monitoring
  workflow that text did not anticipate. It changes no definition, no rule of the test and no table the read-out uses (its scratch tables, in `runtime/ml_oi_daily`, are thrown away with the machine; the tables that count are still the ones `ml oi`
  writes, reproducible from the archive). `contents: read`, no secret, a counts-only text summary kept 30 days.
- **Kite websocket attached to the desk** (`intraday/kitelive.py`, `intraday.kite.live: true`, `deploy/kite-token.sh`, `.github/workflows/kite-token.yml`; criteria `docs/ml/KITE_TRIAL.md` v2): owner decision
  of 25 Oct, the websocket is attached directly, not in shadow. With `KITE_DATA_KEY` and the day's token present, Kite serves the index bars (and the live index price); Kotak and Yahoo
  stay behind it as the automatic fallback for any minute Kite lacks, any compared minute that differs from the fallback by more than 0.5% (the comparison runs on a symbol's first poll, on
  every hole and on one poll in ten, so a minute that is not compared is served as Kite has it; the trial's E4 measures the share compared and rejected), and any failure (no token, expired token, library
  missing, silent socket): the desk then runs exactly as before. No order method is used and the broker, risk and sizing code are unchanged; Kite's bars and index price are the engine's price input
  like any feed's, so the views, the sizing inputs and the paper fills follow them (paper only); no tick-level order flow is added (separate,
  reviewed step). The day's token comes from a once-a-day manual run of the `Kite token` workflow with the login's request_token (the API secret encrypts the token on a `kite-token`
  branch; the live jobs read it in one optional step). The session review shows `kite (N minutes in K polls, R rejected) over <fallback>`.
- **P0.8 built** (`quantdesk/ml/retrain.py`, `python -m quantdesk ml retrain [--dataset <dir>] [--out <new folder>]`, `.github/workflows/ml-retrain.yml`):
  a drill that refits every registered model (today `c_har`, the file the desk loads) from the aeron7 dataset and compares it field by field with the
  committed coefficients (P0.4's comparison: relative tolerance 1e-9, never wider than 1e-6; provenance is not compared as numbers). It also checks that the
  rebuilt dataset has the recorded source commit, importer and 1-minute partition hashes, and says `reproduced_on_different_inputs` when the numbers match
  but the inputs do not. **First drill (24 Oct, local, the true dataset): 809 numbers, largest difference exactly 0.** The workflow runs Sundays and on
  demand; `permissions: contents: read`, no secret and no write token (the job's read-only token is used by checkout, which keeps no credentials), no push or release, the report kept as a 30-day run
  artifact (a test pins all of that). It fetches the source repository at the commit recorded in the committed coefficients, imports it
  (`external_unverified`; the refit reads it anyway and the report says so), refits, and fails the run on any mismatch. The output folder must be outside
  every git tree or under the gitignored `runtime/`, and a report is written once. What it does not do yet: rebuild the Kaggle tables (that data stays
  out of the repository and out of CI), write a model card (a refit has no out-of-sample block until a model with one is registered), or retrain
  anything that is not in `retrain.registry()`; adding a model there is a reviewed change.

## What I need from the owner (only for P0.6)

*Update 24 Oct: the owner named the source (Kaggle `debashis74017/nifty-50-minute-data`) and it is imported. Still open: its licence (the owner chose not to chase it, so nothing is published) and a source for 15 May to early Sep 2026.*

The source of the Mar 2023 to Sep 2026 NIFTY and BANKNIFTY minutes: where it comes from, the file format and columns, the coverage, and whether
it may be redistributed (it will sit in a public repository's release unless you want it kept private). Nothing else in Phase 0 waits on you.
