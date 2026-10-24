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
## Status (24 Oct 2026)

- **P0.2 done** (merged, #107): `python -m quantdesk ml import`; dataset `ml-intake-2-feae259bdba6`, still `external_unverified` until P0.6.
- **P0.3 built** (`quantdesk/ml/build.py`, `python -m quantdesk ml build --dataset <dir> --profile-end <date>`): the M1 table, one row per
  (symbol, day, decision minute, horizon), made by the study's own `volstudy` code (called, not copied) and equal to `volstudy.fit_har`'s frame bit for bit
  (458,623 rows for NIFTY and BANKNIFTY on the Kaggle source, 9 s). Labels never reach past the session (checked on every build and every load). The
  seasonal profile is a **fit**, so it is fitted on sessions up to `--profile-end` and every row carries `in_profile`; a study scores only rows with
  `in_profile == False`, or rebuilds per fold. The point-in-time canary (`ml/pit.py`) runs against the real builder in the tests: after a decision everything is
  replaced with different data and the decision's features must not move; a leak injected into the builder is caught.
  **Deviation from the exit test as worded ("identical digests"):** a table's identity (its folder name and manifest digest) is a hash of the input dataset's
  digest, the recipe and the source of the functions that make the rows, and is identical on any machine. The *values* are floats from numpy reductions that
  can differ in the last bit with memory alignment, so they are not hashed; the stored file is pinned by the sha256 of its bytes, and a rebuild is compared
  with a stated tolerance (rtol 1e-9; measured difference 0 on this machine).
- **P0.4 harness built** (`ml/splits.py`, `ml/pit.py`, `ml/reproduce.py`): purged walk-forward, combinatorial purged CV with embargo and its backtest paths, a verifier
  that the tests inject leaks against, and `python -m quantdesk ml reproduce --dataset <aeron7 dir>`, which reruns the locked HAR study into a scratch folder
  (refused inside `docs/prereg/results`) and compares **every number** with the committed result. Exit test met on 24 Oct: **8 of 8 cells, 1,132 numbers, largest
  difference 0**, nothing written under `docs/`. **Not yet:** the baseline comparison (a scorer that grades any model against HAR and the desk's forecaster
  on the same folds) lands with the evaluation toolkit.
- **A boundary note.** The builder calls the locked study's code, and that code reaches (through `autolearn.prereg` → `evaluate` → `features`) the desk's pure
  computation modules `intraday.quant`, `.chains`, `.feeds`, `.orderflow` and `options.*`. They hold a data-feed adapter and a broker adapter whose network
  clients and secrets are used only inside methods, never at import. `tests/test_ml_build.py` names those five modules as the only live-package modules an ml
  module may load, and fails on any other (orders, journal, risk, engine, web) or on `requests`, `kiteconnect`, `yfinance` or `anthropic` being loaded.

Target: Phase 0 done by **mid November**, as the ML roadmap says. If it slips, section 0's cut order in the master plan applies.

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

## What I need from the owner (only for P0.6)

*Update 24 Oct: the owner named the source (Kaggle `debashis74017/nifty-50-minute-data`) and it is imported. Still open: its licence (the owner chose not to chase it, so nothing is published) and a source for 15 May to early Sep 2026.*

The source of the Mar 2023 to Sep 2026 NIFTY and BANKNIFTY minutes: where it comes from, the file format and columns, the coverage, and whether
it may be redistributed (it will sit in a public repository's release unless you want it kept private). Nothing else in Phase 0 waits on you.
