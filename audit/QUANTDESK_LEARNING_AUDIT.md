# QuantDesk Models and Learning Audit

- **Part C (Phase C):** models: direction, plan/strategy, EV/cost.
- **Part D (Phase D):** the learning system. To be added.

Read-only. Code `main@c96909f`; state `journal@ecd03156`. Finding IDs refer to `QUANTDESK_FINDINGS_REGISTER.md`.
Probes: `audit/probes/test_phase_c_probes.py` (4/4 pass). Null simulations: § C.1.3.

---

## Part C: Models

There are **four model families**. Each one's place in the live decision is traced in Phase B.

| Family | Code | Fitted when | Decision authority today |
|---|---|---|---|
| Session DirectionModel | `intraday/quant.py:DirectionModel` | every session start (and again at hand-over) on 55 days of Yahoo 5-minute bars | if "validated": P(up) for EV (clipped 0.35–0.65) and a `model` evidence factor (weight 0.8). **Never validated in production** (AUC 0.47–0.51) |
| Autolearn direction candidates | `autolearn/models.py` (`baseline` = the same logistic; L1/L2/stumps disabled in config) | daily `autolearn cycle` | a promoted champion would filter entries (`entry_filter`). **Never registered** (A-01) |
| Plan policy | `autolearn/policy.py`, `autolearn/research.py` | daily `autolearn research`, once ≥ 28 real point-in-time sessions exist | **the gate on every directional trade** (`plan_gate`). **Never fitted:** 5 of 28 sessions |
| EV engine | `intraday/quant.py:EVEngine` + `execution/costs.py` | per candidate plan, per minute (Monte Carlo, 2,000 paths) | **the gate on the only reachable setup** (iron fly): EV ≥ max(₹40, 0.05 R) |

The daily multi-strategy desk (`strategies/`, `engine/`) is not run by any workflow (A1 map). Its 8 strategies are
out of scope here except as code.

### C.1 Direction models

#### C.1.1 Session DirectionModel: the chain

```
Yahoo 5m history (55 d, < today)  → features_5m → y = close(t+30m) > close(t), same session
  → fit: train older 70% of days, test newest 30% (one split) → valid iff test n ≥ 150, AUC ≥ 0.53, log-loss skill > 0
  → refit on all days → predict each completed 5m bar (row-count bucketed, A-05)
  → if valid: P(up) for EV (directional plans only, gated) + `model` evidence (score)
  → persistence: only the diagnostic event (AUC, skill, samples); no artifact, no data fingerprint (A-12)
  → outcome / evaluation / update: none. The next session re-fits from scratch; nothing is learned from its predictions.
```

| Item | Verdict |
|---|---|
| Features / labels | causal (V-03); same-session labels |
| Split | one day-grouped 70/30 holdout, re-inspected every session (a rolling validation, not a holdout) |
| Overlap | 30-minute labels on 5-minute rows: 6× overlap, which inflates the effective test size the AUC gate assumes |
| Null behaviour | **validates on pure random walks in 10% of fits** (20/200, § C.1.3). Refit every session for 2 indices, a false "validated" model is close to certain within weeks (C-02) |
| Persistence / replay | not persisted; morning and afternoon fits on the same samples disagree (A-12) |
| Promotion / demotion / rollback | n/a: re-decided each session |
| Future use | latent: under `require_approved_model` it can only change the directional P(up) and the score, which are gated (B-01) |

#### C.1.2 Autolearn candidates: the chain, proven only in tests

```
cycle: ingest → dataset (lockbox) → train (5-fold expanding walk-forward, Pipeline: base 80% / Platt + τ 20%, purged)
  → validate (cost-adjusted sim, block bootstrap, gates; paired vs the champion's recipe; lockbox for passers)
  → register (content-hashed JSON artifact + model card) → challenger
  → live: LiveLearner.on_bar ledgers every registered model's prediction (shadow) → Ledger.resolve outcome
  → paper: shadow_result from the ledger → promote: all checks → champion (old champion → rollback target)
  → live: the champion's signal filters entries (entry_filter); drift alarm → abstain
```

| Requirement | Evidence | Verdict |
|---|---|---|
| Training / features / labels | `cycle._train`, `models.Pipeline` | VERIFIED (code) |
| Splits, OOS, purge / embargo | day-grouped, lockbox excluded; purge/embargo inert by construction (V-02) | VERIFIED |
| Calibration / abstention | Platt on the newer 20%; τ chosen on calibration only; τ = never if nothing pays | VERIFIED (code) |
| Registration gate under the null | **0 of 20 random-walk datasets registered** (§ C.1.3) | VERIFIED: strict (V-13) |
| Champion / challenger / promotion | `_promote`: walk-forward + lockbox + ≥ 10 shadow sessions, ≥ 60 signals, expectancy > 0, drawdown, risk, artifact verifies, paired vs the champion | VERIFIED in `tests/test_autolearn.py::test_full_cycle_registers_shadows_promotes_and_rolls_back` on a **synthetic planted signal with relaxed promotion gates** (3 sessions / 10 signals); **never in production** (A-01) |
| Demotion | **none automatic.** `_promote` judges challengers only; a drift alarm makes the champion abstain but keeps it champion; rollback is a CLI command only (`autolearn/cli.py:170`) (C-03) | MISSING |
| Rollback | `Registry.rollback` restores the previous champion (tested) | VERIFIED (manual) |
| Paper shadow | ledger-based; requires registration first (A-01) | VERIFIED (tests) / UNEXERCISED |
| Persistence | content-addressed JSON, hash-verified on load, feature-version checked | VERIFIED (V-15) |
| Fragility | `FEATURE_VERSION` hashes the *source text* (incl. comments and docstrings) of `_day_features`, `features_5m`, `to_5m`. Any edit invalidates every registered artifact → `fault` → **all entries halt** (fail closed) (C-08) | VERIFIED |
| Lockbox | peeks are logged, not capped; a peek happens every cycle in which a candidate passes walk-forward (C-07) | PARTIAL |
| Future unseen prediction | the chain exists end to end in tests only | UNVERIFIED in production |

#### C.1.3 Null simulations (read-only, synthetic random walks; `tests/test_autolearn.market(phi=0)`)

| Model | Setup | Result |
|---|---|---|
| Session DirectionModel | 200 random-walk histories of 52 sessions (the live window), `DirectionModel().fit` | **validated 20/200 = 10.0%**; AUC ≥ 0.53 in 15%; sd(AUC) 0.031; log-loss skill > 0 in 15% |
| Autolearn cycle (production config: `baseline`, the gates as configured) | 20 random-walk datasets × 2 symbols × 57 sessions, ingest → register | **registered 0/20**; AUCs 0.48–0.53, failing 2–7 gates each |

### C.2 Plan / strategy models

The protocol (`autolearn/research.py`, `docs/PLAN_RESEARCH.md`) is the most rigorous in the repository:

- the **real point-in-time** track alone can qualify (`passed = all(gates) and track == "real"`);
- every configuration (4 horizons × 5 DTE buckets × 1 candidate = 20) is logged with a hash;
- the selection rule is pre-declared (the highest 5% lower bound of expectancy R);
- the development gates include a **deflated Sharpe ratio** counting all configurations;
- the lock is opened once per generation;
- registration is a refit on dev + lock;
- **promotion needs a forward record** (≥ 10 sessions, ≥ 15 trades, expectancy > 0, PF ≥ 1.10).

| Requirement | State |
|---|---|
| Fitted? | **No.** 5 real point-in-time sessions of 28 (`plan/latest.json`, 2026-10-08) |
| Earliest approval | 28 complete recorded sessions (≈ 23 more), then a lock pass, then ≥ 10 forward sessions → **≈ 33+ more trading sessions** |
| prediction → outcome → evaluation → update → future use | designed (`forward` → `promote` → `LiveLearner.plan_gate`), **never run** |
| Scenario (modelled) track | 107,184 modelled plan outcomes on 57 sessions; labelled "scenario analysis only", cannot qualify | VERIFIED separation |
| **Fit with the live desk** | **The plan model approves single long options only** (`plan_gate`: `len(p.legs) != 1 → rejected`). **The live desk at ₹5L builds debit spreads for every directional setup**: `always_spread: true` on orb, vwap_trend, trend_break and va_reversion, plus `allow_short` (equity ₹5L ≥ ₹3L). An approved plan model would therefore still reject every live directional plan (C-01) | **BROKEN (latent)** |

### C.3 EV / cost model

**EVEngine** (`intraday/quant.py:254-321`)
- Underlying paths: normal log-returns at the forecast σ (70% realised blend + 30% ATM IV), with drift from P(up) for
  30 minutes only, plus the research drift. Same seed for every candidate.
- Legs: repriced by Black-Scholes at each leg's **fixed** entry IV, in business time (T falls 1/(375 × 252) per
  trading minute).
- Exits: invalidation, target, premium stop/target, time stop (min(time stop, minutes to square-off)).
- Costs: entry at ask/bid, exit pays the half-spread again, statutory fees both ways (exit fees on the entry mid).
- Output: EV per lot, EV/R, P(profit), CVaR5.

**Cost stack** (`execution/costs.py` + `config.costs`)

| Item | Value |
|---|---|
| Brokerage | ₹20 per order |
| Options STT | 0.15% on the sell side (Budget 2026-27, per README; not externally verified here) |
| Exchange | 3.503 bps |
| SEBI | ₹10 / crore |
| Stamp | 0.003% on the buy |
| GST | 18% |
| Paper fills | bid/ask ± 1 tick; with a live book, the book of that moment, skipped beyond 15% slip |

| Check | Result |
|---|---|
| **Q-06: the iron fly's EV** | **Internally consistent; the setup can't pay intraday.** Recorded decision contexts: 2-hour holds of 1–14-DTE ATM flies. Costs: fees ₹228–332 + exit spread ₹23–100 per lot. Against that: ≈ ₹300–560 of theta over ≤ 120 trading minutes, minus short-gamma losses. Results: NIFTY 1-DTE +₹54…+₹93 (below the 0.05 R floor ≈ ₹221); 6-DTE −₹190…−₹255; BANKNIFTY 13–14-DTE −₹400…−₹530 with **P(profit) 0%** (no path covers costs). BANKNIFTY "none fits": max loss ₹13.8–15.5k per lot exceeds the 2.5% × conviction risk budget (C-05) |
| IV dynamics | none: each leg keeps its entry IV, so the iron fly's own thesis ("theta **and a vol crush** pay") is only half-modelled (C-06) |
| P(up) source | a validated model (never), else an **explicit unvalidated prior** 0.5 + 0.10 × score, for directional plans (gated) |
| Liquidity / spread | ATM spread veto > 6%; leg liquidity class at entry; a one-sided quote → skip; > 15% slip → skip | VERIFIED (code) |
| Latency | not modelled in EV; live fills use the book at fire time (Phase F) |
| Calibration from real outcomes | **none**: the app's calibration table (`web/intraday_api.py:_calibration`) is display-only, nothing feeds back into EVEngine, and there are 0 trades to compare (C-06) | UNVERIFIED |
| A second cost model | autolearn simulates one index-future unit with `autolearn.costs`: STT 2.0 bps vs the desk's futures STT 5 bps (`costs.segments.futures.stt_sell` 0.0005, post-Budget). The autolearn round trip ≈ 5.8 bps vs ≈ 8.8 bps on the desk's own schedule (C-04) | CONTRADICTED (internal) |

### C.4 What can trade, given Phases B and C

| Path | Status |
|---|---|
| Directional, now | blocked: no plan model (B-02) |
| Directional, after ≈ 33 sessions and an approved plan model | **still blocked**: spread vs single-leg mismatch (C-01), unless config or code changes |
| Iron fly | blocked: its EV cannot clear the floor on an intraday hold (C-05) |
| Sleeves (expiry sellers, `intraday sleeves`) | **the only paper trades on record**: `expiry_seller_v1` and `v3` each show 2 opens and 2 settlements in the snapshot. A separate pre-registered path outside the engine. Phase F |

**Under the current code and config, the intraday engine has no reachable path to an executed paper trade.** The only
paper trades the desk makes are the pre-registered expiry-seller sleeves.
