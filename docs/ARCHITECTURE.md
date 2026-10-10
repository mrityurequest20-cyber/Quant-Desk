# Architecture: the self-learning paper loop

The desk learns from its own predictions and promotes a better model only on evidence. Everything here is paper
trading: no code path places an order, and no language model can change a signal, a size, a limit or a promotion.

```
 live session (intraday/engine.py)                     after the close (autolearn.yml → `autolearn cycle`)
 ─────────────────────────────────                     ───────────────────────────────────────────────────
 every completed 5-minute bar, each symbol             a ingest    validate bars → bar store; resolve outcomes;
   features (FEATURE_VERSION) ─┐                                   ingest closed paper trades (once each)
   champion   → p, signal ─────┼─► ledger: decision    b dataset   features + 30-min labels, fingerprint,
   challengers→ p (shadow) ────┤   (append-only,                   the locked final test (created once)
   rollback   → p (shadow) ────┘    hash-chained)      c train     every candidate through identical purged
 champion signal 0 → no entry                                      walk-forward folds; final fit
 champion signal ±1 → only setups that agree           d validate  costs, metrics, block-bootstrap CIs, gates;
 at the close: outcomes for each decision ─► ledger                the locked test for those that pass
                                                       e register  passing candidates → challengers
 halts (fail closed): kill switch, stale feed,         f paper     shadow results per model from the ledger;
 journal check, unverifiable champion, drift alarm                 champion's paper trades; drift
 → no new entries                                      g promote   all gates → champion (old one = rollback
                                                                   target); otherwise reasons on record
```

## Modules (`quantdesk/autolearn/`)

| Module | Job |
|---|---|
| `store.py` | Hash-chained append-only JSONL (`ChainLog`: seq, prev, hash; fsync'd appends; torn-line recovery) and atomic JSON writes |
| `features.py` | `FEATURE_VERSION` / `LABEL_VERSION` (hashes of the feature list and the code), `validate_bars`, `build_samples`, fingerprints |
| `ledger.py` | The immutable learning dataset: decisions before outcomes, outcomes later, leakage guards, retention by whole month |
| `validation.py` | Day-grouped walk-forward with purge and embargo, fold layout hash, the locked final test (`LockBox`) |
| `models.py` | Candidates (`baseline` = the live DirectionModel fit, L2 variants, L1, boosted stumps), Platt calibration, abstention τ, JSON artifacts |
| `evaluate.py` | Cost model, non-overlapping trade simulation, metrics, breakdowns, block bootstrap, fail-closed gates |
| `registry.py` | Champion / challenger registry: content-addressed models, model cards, hash-chained event log, promotion, rollback |
| `drift.py` | Feature PSI, prediction PSI, calibration (ECE beyond its noise floor), performance against the validation interval |
| `cycle.py` | Stages a–g, idempotent (input keys) and resumable (per-stage state), single-runner lock, retention |
| `live.py` | `LiveLearner`: per-bar decisions for every registered model, the champion's entry filter, faults |
| `plans.py` | Plan-level outcomes under the engine's own rules, with the evidence class (`real_point_in_time` / `real_eod_approximation` / `modelled`) on every row |
| `policy.py` | The one plan baseline: calibrated logistic P(net > 0) → expected net R → abstain |
| `research.py` | Real point-in-time track (the only qualifying one), modelled scenario track, EOD study, the engine-constrained replay, the once-only lock, the plan registry ([PLAN_RESEARCH.md](PLAN_RESEARCH.md)) |
| `status.py`, `cli.py` | `autolearn status / cycle / research / verify / recover / rollback` |

## The data contract

- **A decision** is written at the end of a completed 5-minute bar, with:
  - the features computed from bars up to that moment;
  - every registered model's prediction;
  - the data fingerprint, the costs assumed, the session state and the model versions.

  The ledger refuses a decision recorded at or after its label could be known (`LeakageError`), and refuses a second
  record for the same decision.
- **An outcome** is written only after the label window has closed. It is computed from the bars after the decision,
  using the existing label: the close 30 minutes later against the decision bar's close. Each model's simulated net
  bps is stored with it.
- **Records are never edited.** Every line carries the previous line's hash, and `autolearn verify` detects any edit
  or reordering. Retention deletes only whole closed months, with a tombstone in `manifest.jsonl`.
- **Replays and backfills** are labelled by source, and only `source="live"` counts as paper evidence.

## Validation

- **Walk-forward:** sessions minus the locked test; an expanding window over 5 contiguous test blocks after 15
  training sessions. Training rows whose label is still open at a block's start are purged. Decisions within the
  embargo (≥ 30 minutes, the horizon) before it are dropped. The layout is hashed with the data fingerprint.
- **Inside each fold:**
  - the base model fits the older 80% of the training sessions;
  - Platt calibration and the abstention threshold τ are fit on the newer 20%, purged.
  - τ maximises net bps per opportunity after costs with at least 10% coverage. If no τ pays, the model abstains on
    everything and fails the gates.
  - Nothing is chosen on test data.
- **The locked final test:**
  - It is the newest `final_test_days` (8) sessions at the moment enough data first exists (3× the lock). It is
    written to `lockbox.json` and never moves.
  - It never takes part in selection.
  - Only a candidate that passed walk-forward is scored on it: refit on the sessions before the lock, scored once,
    and the look is logged in `lockbox_access.jsonl`. Its "look count" is shown in `autolearn status`.
  - **Note:** there was no locked final period in the repository before this. The existing research protocol uses a
    rolling validation slice that every weekly run re-inspects. The lockbox is new and starts clean on the first cycle.
- **Intervals:** a circular block bootstrap over sessions (blocks of 3, seeded) for expectancy, net per day and win
  rate. A paired version compares a challenger with the champion's own recipe refitted on the same folds.

## Costs

- A signal is simulated as one unit of the index future:
  - entered `delay_bars` after the decision and held 30 minutes;
  - one position per symbol at a time, at most 6 a session.
- Round-trip costs come from config: ₹20 brokerage per order, STT 0.05% on the sell, exchange 0.173 bps per side,
  SEBI ₹10/crore, stamp 0.002% on the buy, GST 18% on brokerage and fees, a 0.5 bps half-spread and 1 bp slippage
  per side. STT, exchange fees and stamp duty are the desk's own (`costs.segments.futures`). That is about
  **8.9 bps per round trip** on NIFTY.
- The desk expresses the direction with options, which have extra decay. The warehouse research's buyer's-edge table
  measures that separately.

## Gates (measurable; all in `config/quantdesk.yaml` → `autolearn`)

Every check must pass, and a missing number fails its check.

| Stage | Gate |
|---|---|
| **Register** (walk-forward, out of sample) | data quality usable |
| | sample: ≥ 20 sessions, ≥ 600 labelled rows, ≥ 40 simulated trades |
| | calibration: ECE beyond its sampling-noise floor ≤ 0.03; Brier skill > 0 |
| | costs: net expectancy > 0 bps; bootstrap P(expectancy > 0) ≥ 0.80; profit factor ≥ 1.05 |
| | risk: max drawdown ≤ 1,500 bps and ≤ 20 average profit-days to recover; ≤ 12 trades a day |
| | vs the champion's recipe on the same folds: paired P(better) ≥ 0.70 |
| | the locked final test: ≥ 5 trades, net expectancy > 0 |
| **Promote** (live shadow paper record since registration) | ≥ 10 sessions; ≥ 60 simulated signals |
| | net expectancy > 0; drawdown ≤ 1,500 bps |
| | vs the champion on common sessions: paired P(better) ≥ 0.60 |
| | 0 risk-limit violations; the artifact verifies |
| | a challenger not promoted within 45 days is rejected |
| **Real money** | Out of scope: the existing paper gate (`intraday paper-gate`: 60 sessions, 30 closed trades, PF ≥ 1.15, drawdown ≤ 10%) is a minimum, and this loop never enables it. |

## Live safety

| Control | Behaviour |
|---|---|
| Kill switch | `runtime/KILL` present: flatten every paper position once, no new entries until it's removed |
| Stale feed | no entry when the last bar completed more than `stale_feed_min` (3) minutes ago inside the session |
| Abnormal spread | the analyst's veto when the ATM spread exceeds `max_spread_pct` |
| Session close | no entries outside 09:20–14:45; square-off at 15:15 |
| Daily loss | the risk gate stops entries for the day at the limit |
| Exposure | open premium ≥ `max_total_outlay` × equity: no new entry; `max_open` caps positions |
| Journal | `PRAGMA quick_check` at session start; failure halts entries |
| Reconciliation | at session start, broker positions must equal the legs of the journal's open trades; any difference halts entries and names each instrument |
| State durability | the paper broker's state is written atomically (temp file, fsync, rename); the session state is saved right after every entry and exit, and on SIGTERM / cancel |
| Engine failures | each minute's step is contained; 3 failures in a row → safe mode (square off every position, each exit on its own; no entries for the session); slow steps are reported |
| Model | an unverifiable champion artifact halts entries; a drift alarm makes the champion abstain |
| Language models | Ollama's reads are `advisory_only`: shown and graded, never weighed into the tone. `quantdesk/autolearn` imports no LLM code (a test checks). |
| Directional entries | `require_approved_model`: only with a plan champion promoted on real point-in-time evidence, and a positive expected net R from it for that plan's bucket; otherwise none. The analyst's tilt, narrative, LLM reads and direction models are advisory |

## Storage and cost

- Everything lives in `runtime/intraday/autolearn/` and is saved with the journal branch, which is rewritten on each
  save, so its history doesn't grow.
- Retention keeps 3 datasets, 4 run folders, 30 cycle records, 20 rejected models, 400 days of ledger and 250
  sessions of 5-minute bars (the locked sessions always).
- The ledger holds one line per symbol per bar, about 150 a day, and finished months are gzipped. The cycle takes
  seconds of CPU on a GitHub runner, and no services are added.
