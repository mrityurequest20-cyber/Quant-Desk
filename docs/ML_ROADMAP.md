# ML roadmap: the self-improving desk

17 Oct 2026. A proposal from the engineer's side for the owner and the chief of staff to adopt, amend or reject. Nothing
here changes behaviour by itself: every item ships as its own `desk-request` issue and pull request, every research item
as a pre-registered spec first, and every item that touches orders, sizing or risk gets the `risk-compliance` agent's
CLEAR (AUTONOMY.md). Numbers are quoted from the repo's own records, with the file named. Thresholds marked *proposed*
are not fixed until a registered spec fixes them.

## 1. The short version

The goal: one learning system, not several. Every part of the desk (the trading engine, the brain, the sleeves, the
risk governor, the news readers) feeds one point-in-time record, learns from the same outcomes, and is promoted or
benched by the same evidence ladder. The desk gets better because its *process* gets better, not because a model got
bigger.

Four claims drive the plan, each backed by the desk's own results (section 2):

1. **Predict what is predictable.** The size of the next move is forecastable (HAR beat the desk's forecaster in 8 of 8
   locked cells). The sign of the next move is not (every pre-registered direction test failed or was rejected). Option
   premium is paid on the size of the move, so the ML edge is in pricing, filtering, sizing and costs, not in guessing
   direction. Direction stays in a capped "prove it" lane.
2. **Integration is mostly a data problem.** The learned models see 10 price features. The brain's 18 global markets,
   chain flow, breadth, order flow, FII/DII and news live in a separate voting system. Anything not recorded at decision
   time is lost for good, the way the chain tape was until 3 Oct. Recording comes first.
3. **Evidence, not model size, is the bottleneck.** Real point-in-time chain evidence stands at 11 sessions of the 28 the
   protocol needs (plan report, 16 Oct). More instruments (indices, stocks) is the cheapest way to more independent
   evidence, because a law that replicates on 180 stocks is worth more than a better fit on 2 indices.
4. **Deep learning earns its place or it doesn't ship.** There is none in the repo today. It enters as a pre-trained
   feature extractor and a challenger on the lanes where data is plentiful, under the same folds, the same locked test
   and a kill criterion. It never gets a shortcut.

## 2. Where we are (audited 17 Oct 2026)

### 2.1 What exists

| Piece | Where | What it does today |
|---|---|---|
| Learning loop | `autolearn/` | hash-chained ledger of every decision and outcome, purged walk-forward, a locked final test opened once, champion/challenger registry with model cards, drift (PSI, ECE), idempotent after-close cycle |
| Plan research | `autolearn/plans.py`, `policy.py`, `research.py` | labels the option plan the engine would trade (stop, target, fees, spread), three evidence classes never mixed, 28-session minimum before anything is fitted |
| Live learning memory | `intraday/learning.py`, `earn_in.py` | factor/news/reader/setup hit-rates and IC by horizon; the earn-in gate (placebo, BH, two-session confirmation) ships in shadow |
| Brain | `intraday/brain.py` (+ `chainflow`, `breadth`, `relstrength`, `orderflow`, `futures`) | 18 global markets rolled into 9 drivers, heavyweights pulse, flows; rule-based, hand-set priors, a probation rule for unproven drivers |
| Trading engine | `intraday/engine.py`, `playbook.py`, `analyst.py`, `risk.py` | setups (orb, trend_break, va_reversion, vwap_trend), a Monte Carlo EV layer, vetoes, risk limits |
| Risk governor | `intraday/governor.py` | tightens risk inside a hard envelope; ships in shadow |
| Sleeves | `intraday/sleeves.py` | pre-registered expiry sellers (A to E) on real quotes, paper |
| Language readers | `intraday/llm.py`, `news.py`, `nlp.py` | news NLP plus optional language-model readers; advisory only, with a spend budget |
| Org | `ops/org.py`, `.claude/agents/` | departments, audit rota, scorecard, trust levels |

Stack: numpy, pandas, scipy, pyarrow, pinned (`requirements.txt`). No scikit-learn, no gradient-boosting library, no
torch. Model artifacts are plain hashed JSON, no pickle. Inference is numpy-only. About 31,600 lines in `quantdesk/`
and 67 test files; the full suite takes about 27 minutes.

What you called the "deep brain" and the "deep learning board": I found no module under either name. I read them as the
**brain** (`brain.py` and its producers) and the **board** (the chief of staff plus the reviewers, i.e. the governance
around the learning loop). If you meant something else, say so; the plan only changes in section 4.

### 2.2 What the data has already told us

| Question | Result | Source |
|---|---|---|
| Index direction from price patterns (N1) | rejected | BACKLOG.md |
| 7 pre-registered intraday-direction hypotheses x 2 indices | 1 selected on dev (BANKNIFTY opening-range breakout, t 3.6); locked 2019 to Feb 2023: +3.55 bps, t 0.96, fail | prereg result `intraday_direction_v1` |
| Learned factor weights (D-01) | placebo p 0.70: indistinguishable from noise, so recorded, not applied | HANDOFF 16 Oct |
| Earn-in gate, first run | 0 of 336 items earned a place; 35 had data to test | `reports/2026-10-16_earn_in_gate.md` |
| Move-size forecast (L3) | HAR with intraday profile beat the desk's forecaster in 8 of 8 locked cells; QLIKE gain 13% to 35%; Diebold-Mariano t +4.6 to +12.7 | prereg result `vol_forecast_v1` |
| Expiry-eve premium (L1) | replicated on 5 unseen instruments, pooled +9.48 bps a week (t 4.98); but FINNIFTY carries 51% of the weight, and since Nov 2024 the pooled mean is +4.92 bps (t 1.42) | BACKLOG.md |
| Far wings (L2) | passed its test, not robust to sensitivity | BACKLOG.md |
| Buying ATM straddles | no bucket where buyers win; mean -6.3% (NIFTY), -5.7% (BANKNIFTY) of premium a session | QUANT_GAP_REVIEW.md |
| Real point-in-time plan evidence | 11 complete sessions, 17,418 plan outcomes, 33,633 chain snapshots; 28 needed | plan report 2026-10-16 |
| Paper account, 12 to 16 Oct | 14 trades, -2.95%; one trade carries the result | HANDOFF 16 Oct |

Read together: the desk has **one proven forecast (move size), one replicated premium (L1), and a lot of null results
on direction**. A roadmap that bets on direction repeats the null results. One that bets on move size, premium
richness, costs, sizing and regime builds on the only things that held up.

### 2.3 Integration gaps (what "holistic" has to fix)

1. **Two learners that don't talk.** `learning.py` (factor, news, setup records, gated by `earn_in`) and `autolearn/`
   (ledger, registry, plan gates) keep separate stores and separate promotion rules.
2. **The learned models are blind to the brain.** `FEATURES` in `quant.py` is 10 price/volume features; the plan model
   adds IV, quoted spread and DTE. Global drivers, heavyweights, flows, chain flow, breadth, relative strength, order
   flow and news tone never enter it. Register item A-01 (feature recording) is still open.
3. **The best result is not wired in.** `engine.py` (lines 126 and 1436) still builds the original `VolForecaster`;
   the HAR forecaster that won its locked test exists only in `autolearn/volstudy.py`.
4. **Two symbols.** `autolearn.symbols` is `[NIFTY, BANKNIFTY]`. A pair of instruments cannot replicate anything.
5. **The sleeves have no model layer.** They hold the only replicated premium and run on fixed rules.
6. **Stand-aside is an absorbing state** (register P1-5): a setup with a thin negative record is sized to zero and can
   never recover. That is the "rigid gate" failure the owner named.
7. **The cost model is unchecked against reality.** The fee model matches the 28 paper fills exactly, but the spread
   and slippage side is modelled, not measured.
8. **Little history for the rest.** 1-minute index history has a hole from 1 Mar 2023 to 2 Oct 2025 (aeron7 ends in
   early 2023, TrueData starts 3 Oct 2025); daily NSE data covers it, intraday does not.

### 2.4 Data inventory

| Dataset | Span | Granularity | Role in ML | Limits |
|---|---|---|---|---|
| aeron7 index minutes | 2010 to Feb 2023, about 3,030 sessions each, NIFTY and BANKNIFTY | 1 min | vol/regime/representation training; direction nulls | underlying only: never qualifies an option claim (EXTERNAL_DATA.md) |
| TrueData index candles | 3 Oct 2025 to 1 Oct 2026, 247 sessions | 1 min | the newest untouched out-of-sample year | same restriction |
| Yahoo 5-minute | rolling ~55 to 60 days | 5 min | live features, 60-day top-up | no history beyond the window |
| NSE F&O bhavcopy | since 2019, every index option and future | daily | IV/premium laws (L1 to L4), valuation | closes, not executable quotes |
| Stock options and futures | ~180 F&O stocks, backfilling from 2019 (`fo_stock_opts`) | daily | the panel for replication and cross-section | physical settlement; corporate-action adjustment not yet a table |
| BSE F&O | since 2024, SENSEX and BANKEX | daily | replication | short |
| `nse_index_close`, `participant_oi/vol`, `fii_dii`, `gift_nifty`, `corp_events` | 2019 on (the last three from collection start) | daily | regime, flows, event calendar | FII/DII and GIFT cannot be back-filled |
| Chain tape (Kotak) | recorded chains from 29 Sep 2026; NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY | ~1 min, bid/ask, OI | **the only qualifying option evidence**; spread, slippage, microstructure | 12 sessions recorded, 11 with complete real plans (plan report, 16 Oct) |
| Kotak option minutes | 30 days rolling, then archived every session | 1 min | option marks | short |
| Journal | 10 sessions: 5,883 headlines, 18,902 factor reads, 14 trades | event | language/factor/setup learning | tiny |
| Global markets (18) | live feed holds 5 days of 5-min and 3 months of daily | 5 min / daily | brain drivers | long history must be stored to be usable |

Two kinds of feature exist, and the plan treats them differently:
- **Reconstructible** (price, bhavcopy, global daily, calendar): can be rebuilt over any history, so models can be
  trained on years.
- **Record-now-or-lose-forever** (chain flow from the live book, breadth, order flow, news tone, LLM reads, FII/DII
  intraday, governor state): only the days we record exist. Every session not recorded is gone.

## 3. Principles (the constitution for every model)

1. **Baseline or bust.** A model is added only when it beats the lane's simple baseline on the same folds, after costs
   (PLAN_RESEARCH.md already says this for plan models; it becomes global).
2. **One spine.** Every producer writes to the same point-in-time record; every consumer reads the same registry. No
   side stores.
3. **Fail closed, fail simple.** Every lane has a deterministic fallback chain: champion, rollback, lane baseline,
   rules, abstain.
4. **Models may tighten freely and loosen never.** Before a model earns more, its influence is advisory, then
   tighten-only, then a bounded size multiplier (section 5).
5. **A language model never decides.** It extracts, explains and drafts specs. It places no order, sizes nothing and
   writes no production code unreviewed.
6. **Count every trial.** One global trial ledger; deflated Sharpe and false-discovery control use the global count.
7. **Keep negative results.** A lane that fails is a result, recorded and not retried under another name (the method
   fingerprint already enforces this for specs).
8. **Leakage is a test, not a promise.** Every feature producer ships with the truncation test the price features
   already have: recompute on truncated inputs, require identical rows.
9. **Latency is a budget.** Live inference is numpy-only, no network calls, microseconds to a few milliseconds on top
   of a step that runs once a minute and has been seen taking 51 to 65 seconds.
10. **Calibrate the scientist.** The pipeline's own power and false-positive rate are measured on planted edges and
    planted nulls (ML-0.3) before anyone trusts what it says about the real thing.

## 4. Target architecture: the learning fabric

```
 DATA LAKE  immutable, hashed, provenance on every file (the warehouse pattern, extended)
   index minutes · bhavcopy (index, stock, BSE) · flows · events · chain tape · option minutes · global · news · journal
        │
        ▼
 FEATURE STORE (point-in-time, versioned, one contract)              LABEL STORE (multi-target, multi-horizon)
   price/vol · brain (global, heavyweights, flows) · chain flow ·      move size · range · tail · realised-vs-implied ·
   breadth · relative strength · order flow · calendar/events ·        cost/slippage · plan net R · setup outcome
   news and language tags · governor state                             each label carries its purge window (label_end)
        │                                                                       │
        └───────────────────────────────┬───────────────────────────────────────┘
                                        ▼
 LANES   each one: dataset → fit → predict → score → model card         (section 4.1)
   A vol & move size · B cost & execution · C regime · D events & tails · E panel (stocks) ·
   F direction (capped) · G meta-sizing & allocation · H language · J representation (deep)
                                        │
                                        ▼
 EVIDENCE LADDER + REGISTRY   spec → dev pass → locked pass → shadow → advisory → bounded influence
   global trial ledger · DSR · false-discovery control · drift · fallback chain       (section 5)
                                        │
                                        ▼
 SHADOW BUS → CONSUMERS    engine (setups, EV layer) · risk governor (tighten only) · sleeves (entry filters)
                           sizing/allocator · brain narrative · the app's model scoreboard
                                        │
                                        ▼
 OUTCOME LEDGER (hash-chained)   decision context + every model's prediction + the outcome, later
        └──────────► back into training; drift or decay demotes down the fallback chain
```

Every existing component gets one of three roles, so nothing is orphaned:

| Role | Components |
|---|---|
| **Producer** (writes features) | `brain.py` drivers and heavyweights, `chainflow`, `breadth`, `relstrength`, `orderflow`, `futures`, `ivhist`, `options/gex` and `surface`, `news`/`nlp`/language readers, warehouse flows and events |
| **Consumer** (reads forecasts) | `engine.py` (EV layer, strike and stop choice), `risk.py`, `governor.py`, `sleeves.py` (entry filter), the allocator, the app |
| **Feedback** (writes outcomes) | `journal.db`, the autolearn ledger, plan outcomes, sleeve ledgers, paper fills, rejection records (B-03) |

### 4.1 The lanes

| Lane | Predicts | Baseline to beat | Challengers | Feeds | Evidence class needed |
|---|---|---|---|---|---|
| **A. Volatility and move size** | distribution of realised variance and range at 30m, 60m, 120m, close | desk `VolForecaster`, then HAR with profile (`C_har`) | HAR-X (adds ATM IV / India VIX, overnight gap, global overnight move, event flags, semivariance and jump terms), quantile / log-normal-t heads, gradient boosting, small TCN/LSTM | EV layer sigma, strike and stop width, governor volatility input, sleeve filter | underlying data for the forecast; real point-in-time for any claim about option P&L |
| **B. Cost and execution** | half-spread, slippage, fill probability by strike, time, DTE, volatility | `SpreadTable` and configured ticks | ridge/GBDT on tape; quantile heads | every EV floor, plan labels, sleeve cost checks | tape and paper fills |
| **C. Regime** | state (low-vol drift, trend, range, stress) and change alarms | session buckets, rv terciles | Markov-switching, Bayesian online change-point detection (BOCPD), clustering | conditioning for every other lane, drift alarm | underlying |
| **D. Events and tails** | event-day move multipliers, gap and tail quantiles, results/policy IV crush | none today (BACKLOG 2, 6) | HAR plus learned event multipliers, extreme-value (GPD) tails | event-aware selling, strike distance, size | bhavcopy + `corp_events` |
| **E. Panel (stocks, indices)** | cross-section of next-day absolute move relative to the implied move, IV rank dynamics, liquidity, replication of L1/L3/L4 | pooled regression with date-clustered errors | ridge, gradient boosting with monotone constraints, rank targets | which instruments the desk trades and sells; replication evidence | bhavcopy (daily), later intraday |
| **F. Direction (capped)** | sign of the next 30m to close, pooled across instruments and horizons | coin / drift (base rate by session) | `plan_logit`, boosted trees, deep encoders | advisory only | any promotion needs the plan-level lock |
| **G. Meta-sizing and allocation** | probability that this setup's signal pays, given the context; posterior edge per setup and sleeve | `setup_mult` as is | hierarchical (empirical-Bayes) shrinkage, Thompson sampling with a size floor, conformal abstention | size multiplier inside risk caps, sleeve allocator | paper trades, plan outcomes |
| **H. Language** | event type, surprise, which driver, reliability of the reader | rules reader | teacher (hosted model) to student (local classifier), headline embeddings plus a linear head | brain drivers, event flags | graded by the earn-in gate |
| **J. Representation (deep)** | no target of its own: self-supervised embeddings of bar windows | none (it is a feature) | masked-patch and contrastive encoders (TCN / patch-transformer style) | extra features for A, C, F | must beat the lane's baseline with and without it |

Lane A and B are the first two to ship because they have a proven signal (A) and a measurable, safe target (B).

## 5. The evidence ladder for models

Mirrors the principles ladder. A model sits on exactly one rung; moving up needs the rung's gate, moving down is
automatic on a drift or decay alarm.

| Rung | Gate to enter | What it may do |
|---|---|---|
| M0 idea | none | nothing |
| M1 registered | spec committed alone; method fingerprint unique | nothing |
| M2 dev pass | walk-forward / combinatorial purged CV, all gates, cost stress | nothing |
| M3 locked pass | locked test opened once, passed | nothing |
| M4 live shadow | at least 20 sessions logged beside the champion (*proposed*), no influence | nothing |
| M5 advisory | shown and journaled, graded live | nothing in the trade path |
| M6 bounded influence | calibration holds live; risk-compliance CLEAR | tighten-only (smaller size, wider stop, veto), or a size multiplier in 0.6 to 1.0 *(proposed)* |
| M7 earn-up | owner approval, a registered spec | multiplier above 1.0, up to the existing cap (1.15 in `earn_in.py`) |
| M8 real-money relevance | the owner, by hand | out of scope for this document |

Existing machinery maps onto it: `autolearn` register is M2 to M3, `promote` is M4 to M6; the plan registry is the same
for plan models; the earn-in gate is the M5 to M6 gate for learned tilts.

## 6. The loops that make it self-improving

| Loop | Cadence | What happens | Autonomy |
|---|---|---|---|
| **Fast** | every bar | features recorded; online calibration (recursive least squares / adaptive conformal intervals); bandit choice among setups inside caps | bounded by the governor; cannot loosen anything |
| **Daily** | after the close | ingest, outcomes, refit every lane on frozen protocols, validate, register challengers, shadow scoring, drift check, promote or bench | fully automatic up to M6; M7 needs the owner |
| **Weekly** | Saturday | model scoreboard in the plan and progress report; challenge the champion (placebo, leave-one-instrument-out, costs x2 and x3, pre/post Nov 2024 split, trial count); the research agent drafts specs from caveats | specs are drafts until the research-reviewer and the commit-alone rule pass |
| **Monthly** | first Saturday | retire or demote models by rule; data-scout review; architecture review of lane interfaces | engineer decides, records the decision |
| **Quarterly** | with the owner | ladder position of every lane; compute and data levers; what the owner still holds | owner |

What the loop may change on its own: model parameters, thresholds chosen on calibration slices, hyper-parameters
inside a registered grammar, challenger sets, and demotion. What it may never change: a risk limit, a gate, a
registered spec or result, the lock, a secret, or anything about real money (AUTONOMY.md, hard limits).

## 7. Evaluation, upgraded

Already in the repo: day-grouped walk-forward with purge and embargo, a once-only lock, block bootstrap, deflated
Sharpe in plan research, Benjamini-Hochberg and the placebo test in the earn-in gate, ECE with its noise floor, cost
stress in the law audit.

Added (each is its own item, with a test):

| Addition | Why |
|---|---|
| Combinatorial purged cross-validation and the probability of backtest overfitting | on the large minute datasets, many train/test paths instead of one |
| One global trial ledger across lanes; deflated Sharpe over the global count | the number of things tried is the real denominator |
| Reality-check / superior-predictive-ability tests, and the Model Confidence Set for forecasts | compare many challengers to one baseline without picking the lucky one |
| Diebold-Mariano with the small-sample (Harvey-Leybourne-Newbold) correction | live shadow windows are short |
| Conformal intervals with an adaptive version for drift | calibrated ranges on move size and on every probability |
| Planted-edge and planted-null harness | measures the pipeline's power and false-positive rate (the earn-in review estimated 41% power at 20 sessions for a true 55% edge, which is the kind of number every gate should carry) |
| Leave-one-instrument-out and pre/post Nov 2024 reports on every pooled model | the L1 caveats were exactly this |
| Off-policy evaluation, once the bandit logs propensities | evaluate "what if we had traded that setup" without trading it |

## 8. Universe expansion (indices, stocks, everything)

Design rule: **every model is instrument-agnostic by construction, and every instrument family replicates before it
trades.** A symbol master (ML-0.5) holds, per instrument, the family, exchange, lot and tick history, expiry cycle,
hours, cost segment, liquidity tier, sector and, for indices, constituent weights over time.

| Tier | Instruments | Data | Use |
|---|---|---|---|
| 0 | NIFTY, BANKNIFTY | everything | full stack, trading |
| 1 | FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX, NIFTYNXT50 | bhavcopy and index close for all; tape for FINNIFTY, MIDCPNIFTY and SENSEX | replication of L1/L3/L4; sleeves D and E |
| 2 | the ~25 F&O stocks that pass the liquidity floor (`stocks.py`), the 11 heavyweights first; sector indices | daily now; **intraday bars must be recorded from now** | panel lane, heavyweight nowcast, event lane |
| 3 | all ~180 F&O stocks | daily bhavcopy since 2019 | replication, cross-section, earnings IV crush |
| 4 | other assets (commodities, currency, crypto) | none yet | only after a lane has replicated; each needs its own cost model, calendar and replication test |

Known hazards, listed so they get tests rather than surprises: survivorship (build the stock universe from each day's
bhavcopy, never from today's list), corporate actions (an adjustment table is needed before any stock price panel),
lot-size and strike changes, holiday-shifted expiries, the Nov 2024 expiry-structure change, physical settlement on
stock options (exit before settlement, as BACKLOG 1 says).

## 9. The roadmap

"W0" is the week the roadmap is adopted. Phases overlap; weeks are effort, not promises. Two calendar anchors do not
move with effort: shadow windows (20 sessions is about 4 weeks) and real point-in-time evidence (17 more complete
sessions are needed; at five a week plus market holidays that is late November at the earliest, if the tape never
misses). Work items are ID'd so each becomes one issue and one PR. Throughput is set by the one nightly engineer shift,
the 27-minute CI and the owner's merge, which means a few small PRs a day, not a few large ones.

### Phase 0: record now, measure honestly (W0 to W3)

Everything time-critical goes first, because nothing here can be rebuilt later.

| ID | Item | Exit gate |
|---|---|---|
| ML-0.1 | **Context recorder (A-01).** At every 5-minute decision per symbol, write a versioned snapshot of every producer's output to the ledger: brain drivers and z-scores, heavyweights, flows, chain flow, breadth, relative strength, order flow, IV and India VIX, calendar flags, news counts and tone, language-reader outputs, governor state. Each producer gets a version hash. | at least 99% of decisions carry a full snapshot for 10 straight sessions; truncation test passes for every producer |
| ML-0.2 | **Start recording Tier-2 intraday bars** (liquid F&O stocks, sector indices, the 5 indices) from the live feed, archived as release assets like the tape. Store the 18 global markets' long daily history (and 5-minute going forward) in the warehouse. | coverage report: minutes recorded vs expected per symbol, 95% or better |
| ML-0.3 | **Planted-edge harness.** Synthetic sessions with a known edge (hit rate 51% to 56%, forecastable volatility, regime shifts) and exact nulls, run through the unchanged autolearn, earn-in and plan gates. | report of power and false-positive rate per gate in `docs/reports/`; a gate with a false-positive rate above its nominal level is a defect |
| ML-0.4 | **Lane interface and the global trial ledger.** One protocol (`dataset`, `fit`, `predict`, `score`, `card`) and one hash-chained `trials.jsonl`. | existing `baseline` and `plan_logit` run through it with identical numbers (regression test) |
| ML-0.5 | **Symbol master and data catalog** (section 8): one registry for instruments, one for datasets (span, granularity, allowed uses, evidence class, digests). | every dataset in section 2.4 and every instrument in Tiers 0 to 2 present |
| ML-0.6 | **Training extra.** Pinned `requirements-train.txt` (scikit-learn and a gradient-boosting library; torch deferred to Phase 4); an import-boundary test proving live code imports none of them, the pattern the language-model test already uses. | CI green; live path imports unchanged |

### Phase 1: the proven lane, and honest costs (W2 to W9)

| ID | Item | Exit gate |
|---|---|---|
| ML-1.1 | **Vol lane in shadow.** Move `C_har` out of `volstudy` into a model module; extend to HAR-X; output a predictive distribution (quantiles from standardized residuals), not a point sigma; log it beside `VolForecaster` for 20 or more sessions. A new spec (`vol_forecast_v2`) fixes the extra inputs and uses the TrueData year as a fresh locked period, since v1's lock is spent. Neither minute dataset carries implied vol, so IV enters at daily resolution (bhavcopy IV, India VIX) and can be tested there; an intraday IV term exists only on the tape and is forward-only. | locked-period QLIKE gain over `C_har` or over the desk's forecaster (spec decides), and live move ratio between 0.9 and 1.1 in every time-of-day bucket (the old one ranged 0.70 to 1.15) *(proposed)* |
| ML-1.2 | **Forecast-filtered selling (L1 x L3).** Pre-register: a sleeve sells only when implied variance exceeds the forecast variance by k (k fixed in the spec). Test on warehouse history first, forward on the sleeves second. This is BACKLOG 3's "then", and it joins the one replicated premium to the one locked forecast. | registered result in the ledger, whichever way it goes |
| ML-1.3 | **Cost and execution lane.** Predict half-spread, slippage and fill probability from the tape; compare with `SpreadTable` out of sample; compare predicted with realised slippage on paper fills as they accrue. | lower out-of-sample absolute error than `SpreadTable` with an interval that covers; cost-model version bumped |
| ML-1.4 | **Regime lane v1** (3 to 4 states plus change alarms). Judged by whether conditioning on it improves lane A and F calibration, not by profit. | per-regime calibration table improves on the unconditioned model |
| ML-1.5 | **One registry view.** Surface `Memory`, `earn_in`, the autolearn registry and the plan registry as one ladder (read-only first; no behaviour change). | the weekly report shows every model's rung |
| ML-1.6 | **Model scoreboard** in the app and the weekly progress report (section 10). | published for two consecutive Saturdays |

Flagship of the phase: ML-1.1 then ML-1.2. Once the forecast is wired in, the EV layer stops using the forecaster that
lost to both alternatives in every development year, and the sleeves get their first model-driven filter on top of a
premium that already replicated. The EV layer uses sigma in its Monte Carlo, so putting the new sigma in the trade path
is a sizing-adjacent change: it needs risk-compliance CLEAR and a shadow period first.

### Phase 2: widen the universe, prove it replicates (W4 to W14)

| ID | Item | Exit gate |
|---|---|---|
| ML-2.1 | **Replication battery**: L1 and L4 on stock options (BACKLOG 1), L3 pooled across indices and liquid stocks (BACKLOG 3), earnings IV crush (BACKLOG 6). Pooled by expiry month, errors clustered by date, leave-one-instrument-out. | registered results; principles moved up or down the ladder by their own rules |
| ML-2.2 | **Panel lane**: next-day absolute move relative to the implied move, IV-rank dynamics, liquidity; date-grouped CV, rank targets, sector-neutral. Not direction. | beats the pooled-regression baseline on the dev folds and holds on the untouched most recent year |
| ML-2.3 | **Event lane**: results and policy calendars (`corp_events`, RBI, budget, major US events) as features; HAR with learned event multipliers; event-aware selling rule (BACKLOG 2). | registered result on all 7 index instruments at once |
| ML-2.4 | **Heavyweight nowcast**: index fair value from the 11 heavyweights' live prices vs the index, as a feature for breadth divergence and relative-strength reads. Judged on IC by horizon like every factor. | IC with a t-statistic of 2 or more (in absolute value) at the holding horizon, or it stays unused |
| ML-2.5 | **Corporate-action adjustment table** and a point-in-time constituent history. | stock-panel tests pass on a known split/bonus fixture |

### Phase 3: the decision layer (W8 to W18)

| ID | Item | Exit gate |
|---|---|---|
| ML-3.1 | **Setup meta-model**: for each setup (orb, trend_break, va_reversion, vwap_trend), the probability of success given the context, with hierarchical shrinkage across setups and instruments; replaces the absorbing stand-aside (P1-5) with a posterior-based multiplier that has a floor above zero. | simulated lockout rate of zero-edge setups falls from the register's 11-12% to under 1% *(proposed)*, and the multiplier stays in the existing 0.6 to 1.2 scale |
| ML-3.2 | **Exploration policy**: Thompson sampling with a minimum paper size per setup so a thin record can still recover, logging each choice's propensity. | propensities present on 100% of choices; no position above the risk caps |
| ML-3.3 | **Allocator** across sleeves and setups: risk budgets from the posterior, half-Kelly cap, correlation-aware (BACKLOG 9); registered as a spec. | spec registered; applied only when a sleeve's registered eligibility rule says so |
| ML-3.4 | **Conformal abstention and governor inputs**: forecast-interval width, regime and drift state feed the governor's volatility scale (`s_vol`), tighten-only. | governor stays in shadow until the owner flips it; shadow log shows the tightening it would have made |
| ML-3.5 | **Plan model v2**: once 28 real sessions exist, `plan_logit` against a monotone-constrained boosted model, per DTE bucket, under the existing plan protocol and lock. | the existing development and lock gates |

### Phase 4: the deep lane (W14 to W28), only if Phases 1 to 3 delivered baselines

| ID | Item | Exit gate |
|---|---|---|
| ML-4.1 | **Pre-training corpus**: all 1-minute bars (aeron7, TrueData, recorded), volatility-normalised, with instrument identity. Self-supervised objectives (masked-patch reconstruction, contrastive) on small encoders (up to a few million parameters). Weights stored as hashed arrays, forward pass in numpy. | embeddings reproduce from the corpus digest; forward pass within the latency budget |
| ML-4.2 | **Deep challengers on lanes A, B and C only**: multi-horizon volatility, tape-based spread, regime. Compared with HAR-X and boosting on identical folds and the lock, using the Model Confidence Set. | **kill criterion:** no gain surviving false-discovery control after two registered attempts on a lane parks deep learning for that lane |
| ML-4.3 | **Embeddings as features** for lanes A, C and F; ablation with and without. | a feature stays only if the ablation says so |
| ML-4.4 | **Pre-trained time-series models as zero-shot challengers**, if they run on CPU, pin cleanly and the licence allows (untested; check before committing a spec). | same bar as any challenger |
| ML-4.5 | **Synthetic-world generator** (regime-switching, jumps, vol-of-vol, calibrated to history) for stress tests and augmentation. Never evidence of an edge. | generator reproduces the history's volatility clustering and tail statistics |
| ML-4.6 | **Distillation**: compile every winner to numpy / linear / small trees for the live path. | live step time unchanged within noise |

Honest expectation for this phase: small networks on a few thousand index-days rarely beat a well-specified HAR or
boosted model. The reason to build it anyway is that the pre-training corpus (16 years, many instruments) is the one
place deep learning has enough data to try, and the kill criterion makes the attempt cheap to abandon.

### Phase 5: the factory and autonomous research (W20 onward)

| ID | Item | Exit gate |
|---|---|---|
| ML-5.1 | **Model factory**: a bounded JSON grammar (lane, feature subset from the store, learner family, hyper-parameter ranges, target, horizon) that generates candidates, runs dev folds, logs every trial, and hands the top few to a spec draft. Never generates code. | every trial in the global ledger; deflated Sharpe uses the full count |
| ML-5.2 | **Research agent**: drafts pre-registered specs from the proposals list and the caveats; the research-reviewer checks repeat, power and falsifiability before commit (the existing rule). | drafts reviewed and committed alone; zero repeated experiments by fingerprint |
| ML-5.3 | **Teacher-to-student language lane** (register items S0 to S4): record every language-reader output with its outcome; a local student model must pass the placebo gate before it can weigh into anything; it carries on when the hosted model's budget ends. | student beats placebo on held-out sessions, or stays advisory |
| ML-5.4 | **Auto-demotion and retirement** by rule, down the fallback chain; monthly model review on the rota. | a seeded decay in the planted-edge harness triggers demotion within the expected window |
| ML-5.5 | **Weekly champion challenge** as an audit-rota item, run by someone who did not build the model. | on the Saturday audit |

### Calendar view (effort, not promises)

```
 W0   W2   W4   W6   W8   W10  W12  W14  W16  W18  W20  W24  W28
 P0 ██████
 P1      ████████████████
 P2           ██████████████████████
 P3                     ███████████████████
 P4                                     ████████████████████
 P5                                               ███████████████►
 anchors: shadow windows (20 sessions ≈ 4 wks)  ·  28 real point-in-time sessions ≈ late Nov at the earliest
```

## 10. How we know it is working: the model scoreboard

Added to the weekly progress report next to the evidence level. Every line says improved, same or worse.

| Group | Measures |
|---|---|
| Forecast skill | QLIKE and its gain over the lane baseline, Brier skill, pinball loss for quantiles, conformal coverage against nominal |
| Calibration | ECE beyond its noise floor, move ratio by time of day, per regime |
| Decision value | net expectancy R on real point-in-time with its interval, deflated Sharpe, probability of backtest overfitting, cost-stress survival (x2, x3) |
| Process | trials run and trials per promotion, models per ladder rung, time from drift alarm to demotion, share of defects the desk found itself |
| Data | real point-in-time sessions (n of 28), snapshot completeness, instruments and sessions per tier, tape coverage |
| Honesty | share of live claims backed by a locked result; planted-edge power and false-positive rate |

## 11. Risks, and what we do about them

| Risk | Why it is real here | Mitigation |
|---|---|---|
| The direction lane stays null | every test so far says so | cap the effort; the roadmap does not depend on it |
| Overfitting through volume of trials | more lanes and a factory multiply the number of tries | global trial ledger, deflated Sharpe over the global count, locks opened once |
| Small live samples | at a true 55% hit rate a gate passes 41% of the time at 20 sessions, 86% at 60 | lean on history for evidence and live for confirmation; report power next to every gate |
| Non-stationarity | the Nov 2024 change, expiry shifts, a mid-sample break in L1 | pre/post splits in every report; regime lane; drift demotion |
| Look-ahead in new features | many new producers, many chances | the truncation test is mandatory per producer; the auditor attacks it first |
| Complexity and maintenance | 31,600 lines and a 27-minute suite already | small PRs, a lane interface instead of ad-hoc code, shard the slowest tests (architecture audit) |
| Dependence on a hosted model | the budget ends | the student lane (ML-5.3); the desk already runs on rules if every key fails |
| Latency | steps of 51 to 65 s have been seen, and Kotak load is 65 to 89 calls a minute against a 25 requests-a-second limit | numpy-only inference, features computed once per bar, no network in model code |
| Compute | CPU runners only; free sources only | sizes proposed are CPU-feasible by estimate (not measured); if Phase 4 is not, that is the owner's compute lever |
| Data we cannot rebuild | tape, chain flow, news, FII/DII intraday | Phase 0 records first |
| A model that is right in backtest and wrong in the order book | the original sin of this desk (the L1 audit) | real point-in-time evidence is the only class that qualifies; modelled results stay scenario analysis |

## 12. Process: how this runs inside the org

- **Ownership.** Lanes belong to Research (A, C, D, E, F, J, factory), Orders (B), Risk & compliance reviews G and any
  M6 move, Data owns the lake, symbol master and recorders, Architecture owns the lane interface and latency budget,
  Internal audit attacks every promotion, the chief of staff carries the scoreboard into the weekly plan.
- **Rota.** Wednesday's research audit gains a model line (drift, calibration, trial count, ladder positions).
  Saturday's audit includes the champion challenge.
- **Shipping.** Each ML-x.y item is a `desk-request` issue, an `engineer/...` branch, a pull request, and the owner's
  merge. Specs are committed alone before code. Anything in the trade path needs risk-compliance CLEAR; anything from a
  department on probation gets an internal-audit pass first.
- **Decisions the engineer makes and records** (not questions): adding the training extra, the lane interface, the
  order of Phase 0 items, which instruments enter Tier 2.
- **Levers only the owner holds:** flipping the governor from shadow to tighten, any earn-up (M7), paid compute or
  data, and everything about real money.

## 13. The first ten days

In this order, because the first three cannot be recovered later:

1. **ML-0.1** context recorder. Every session without it is a session the integrated model can never train on.
2. **ML-0.2** start recording Tier-2 intraday bars and the global history.
3. **BACKLOG 1** (L1/L4 on stock options) keeps running; it needs no new code.
4. **ML-0.3** planted-edge harness, so every later gate comes with a measured power.
5. **ML-1.1 spec** (`vol_forecast_v2`) drafted and sent through the research-reviewer; code waits for the committed spec.
6. **ML-0.4** and **ML-0.5**, which every later item leans on.
7. **ML-0.6** training extra and the import-boundary test.
8. **ML-1.3 dataset check**: how many tape sessions and fills exist for the cost lane.

## 14. References behind the design choices

Cited from memory, not looked up this session; the research-reviewer should verify them before any is quoted in a spec.

- Corsi (2009), HAR realised-volatility model. Patton (2011), QLIKE as a robust loss for imperfect proxies.
- Diebold and Mariano (1995); Harvey, Leybourne and Newbold (1997); Hansen, Lunde and Nason (2011), Model Confidence Set.
- White (2000), Reality Check; Hansen (2005), superior predictive ability; Benjamini and Hochberg (1995).
- Bailey and Lopez de Prado (2014), deflated Sharpe; Bailey, Borwein, Lopez de Prado and Zhu (2017), probability of
  backtest overfitting; Lopez de Prado (2018), *Advances in Financial Machine Learning* (purged CV, embargo,
  meta-labeling, combinatorial CV).
- Gu, Kelly and Xiu (2020), machine learning in empirical asset pricing (panel methods, date-grouped evaluation).
- Vovk, Gammerman and Shafer (2005), conformal prediction; Gibbs and Candes (2021), adaptive conformal inference
  under distribution shift.
- Adams and MacKay (2007), Bayesian online change-point detection.
- Nie et al. (2023), patch-based time-series transformers; Yue et al. (2022), TS2Vec contrastive representations.
- Bollerslev, Tauchen and Zhou (2009), variance risk premium. Gao, Han, Li and Zhou (2018), intraday momentum (the
  hypothesis the desk tested and did not find).
- Russo et al. (2018), tutorial on Thompson sampling; Dudik, Langford and Li (2011), doubly robust policy evaluation.
