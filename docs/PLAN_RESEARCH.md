# Plan-level research: what the option trade the desk buys would have made

`quantdesk/autolearn/plans.py` (labels), `policy.py` (the one model), `research.py` (the protocol),
`python -m quantdesk autolearn research`, run after every session by the `Learning cycle` workflow.

## Why this exists

The direction model was graded on "did the index go up in 30 minutes" against a futures cost of ~6 bps. The desk does
not trade futures; it buys options. Whether a call made money depends on the ask paid, the bid received, the ticks lost
to the queue, theta over the hold, the stop and target the engine enforces, and every fee. So the label is the outcome
of the exact plan, and the target is expected net P&L, not direction.

## Evidence classes (never combined)

Only two recorded sessions of real option chains exist. A chain modelled from bhavcopy IV is fine for plumbing and
sensitivity, but it is not evidence of an edge. Every plan outcome carries `quote_source`:

| `quote_source` | What it is | May it qualify a candidate? |
|---|---|---|
| `real_point_in_time` | Every price came from the desk's own recorded book (Kotak / NSE / Kite snapshots, never the model-chain fallback). See the three conditions below. | **Yes**, and only this |
| `real_eod_approximation` | Real bhavcopy prices, but end of day: open → close, stop by the daily low, modelled spread | No. Descriptive DTE and cost study |
| `modelled` | Priced by the desk's pricer (bhavcopy ATM IV, else India VIX × beta; skew model; measured or configured spread), or a real entry whose marks or exit had to be modelled | No. **Scenario analysis only** |

A `real_point_in_time` outcome meets all three of these:
- the entry was quoted at most `pit_max_age_min` (2) before the decision;
- every mark used for an exit decision was calibrated on a real snapshot at most `chain_stale_min` (12) old;
- the exit filled at a real bid at most 2 minutes after the trigger.

Only `real_point_in_time` may support:
- a positive-expectancy claim;
- a DTE or horizon policy change;
- champion promotion (`Registry.register` / `promote` refuse plan policies whose card lacks it, and the live learner
  faults on such a champion);
- paper-gate progression (`intraday paper-gate` counts only trades filled at the live book on both entry and exit);
- any statement that the strategy has an edge.

Every fitting and evaluation function refuses a frame that mixes classes (`research.one_class`).

## The plan, under the live engine's own rules

| | Rule (the same code or the same rule as `intraday/engine.py`) |
|---|---|
| Strike | `StrikePicker.by_delta` at `long_delta` 0.45: the setups' buyer leg, in buyer-only mode |
| Vetoes | ATM call spread > `max_spread_pct` (the analyst's veto); no two-sided quote on the strike; a real chain older than the stale limit |
| Entry | the ask + `adverse_ticks` (IntradayBroker) |
| Exits | `_manage`'s order at every bar close, on mid marks:<br>- premium stop (−30%) → premium target (+60%) → breakeven (once past half the target, back to ≤ 0);<br>- time exit: held ≥ the horizon **and** gross < 10% of premium. A winner past its time stop is held, as in the engine;<br>- square-off at 15:15 |
| OHLC | A bar whose adverse extreme reaches the stop is a stop, even if the target was also touched: **stop first**. A target counts only at an observed close. **Intrabar ordering is never inferred.** |
| Fill | the next available bid − `adverse_ticks`. A stop touched inside a bar fills at the worse of that bid and the stop level, so **a gap through the stop costs the gap**. |
| Fees | `execution/costs.CostModel.fees` per order (brokerage, STT on the sell, exchange, SEBI, GST, stamp) |
| Marks between real snapshots | the engine's QuoteMarker: the snapshot's implied IV for the strike, its half-spread |

Horizons: 30m, 60m, 120m and close. Each is its own label and its own model. DTE buckets: 0, 1, 2, 3–5, 6+ trading
days, using the nearest listed expiry in each bucket. The engine's `expiry_min_days` counts calendar days; for "skip
0-DTE" (≥ 1) the two agree.

Causality:
- a snapshot prices only moments at or after its timestamp;
- bhavcopy IV and the listed expiries come only from earlier sessions;
- VIX comes only from completed bars;
- spread estimates come only from earlier sessions (`SpreadTable`).

Costs are versioned (`cost_model_version`: fee config, fee code, spread table, fill rules) and compared against the
paper broker's actual fills (`fills_report`; zero fills so far, so it is unverified and says so).

## The model: one simple baseline

`plan_logit`, per side:
- logistic P(net > 0) on the bar's features plus the plan's IV, quoted spread and DTE, Platt-calibrated on held-out
  sessions;
- expected net R = P × (average win R) − (1 − P) × (average loss R);
- trade the better side only when it clears τ, chosen on calibration sessions; otherwise abstain. τ = ∞ when nothing
  pays.

Another model is added only when it improves out-of-sample plan-level net results after costs. In the same spirit,
the direction loop's candidates are cut back to its baseline.

## The protocol

1. **Development folds choose everything.** Horizon, DTE bucket, threshold and features are chosen on a day-grouped,
   expanding walk-forward over the development sessions:
   - 5 folds after 15 training sessions;
   - training rows purged when their plan is still open at the block's start;
   - an embargo of the horizon (375 minutes for close).
2. **Every configuration tried is logged** to `plan/trials.jsonl` (hash-chained), with its frozen configuration hash:
   track, horizon, bucket, model spec, features, rules, cost version, code.
3. **Evaluation is the engine-constrained replay.** It runs the engine's `IntradayRisk` gate and sizing on the paper
   account:
   - `max_open` 1 across symbols;
   - 2 trades a day;
   - cooldown after 2 losses;
   - the daily loss limit, the 35% premium-outlay cap and cash;
   - the 09:20–14:45 window.

   A position blocks new entries until it exits, so overlapping plans are never counted as independent trades.
   Plans the account can't size are counted as `unaffordable`.
4. **Selection is pre-declared and on the real track only:** the highest 5% lower bound on expectancy R among
   configurations with at least `min_trades` replayed trades.
5. **The locked final period.**
   - It holds the newest `final_test_days` real sessions, and is set aside when the real track first has
     `min_real_sessions` (28).
   - It is opened **exactly once**, for the selected configuration, refitted on the sessions before it. The opening
     is logged in `plan/lock_access.jsonl`.
   - Newer sessions are then held back from development until the next lock forms.
6. **Approval** needs the development gates and the locked test:
   - development: ≥ 30 trades on ≥ 10 days, a lower CI bound on expectancy R > 0, PF ≥ 1.10, deflated Sharpe ≥ 0.95
     across all trials, ≥ 60% positive folds;
   - the locked test: ≥ 8 trades, expectancy R > 0, net > 0.

   An approved configuration becomes a plan **challenger**. It becomes the **champion** only through a forward record
   on later real sessions: ≥ 10 sessions, ≥ 15 trades, expectancy > 0, PF ≥ 1.10.
7. **No production change** (`expiry_min_days`, time stops, horizon) is ever made by the study; the report states what
   the evidence would support.

Below 28 real sessions the real track is **descriptive only**: nothing is fitted on it and no lock is spent. The
scenario track runs the same development machinery for sensitivity, labelled "scenario analysis only". It is never
selected, locked, registered or promoted, and sessions held for the real lock are excluded from it.

## The gate on live entries

`autolearn.require_approved_model: true`:

- A directional option trade needs the plan registry's champion (real point-in-time evidence only):
  - its DTE bucket must cover the trade's expiry;
  - it must give the plan an expected net R ≥ max(τ, 0);
  - the trade must be a single long option.
- The trade then runs on the champion's horizon as its time stop, sized by the risk engine. The Monte Carlo EV
  layer, which uses an unvalidated P(up), is bypassed for it.
- With no such champion, no directional trade is taken.
- The analyst's tilt, the narrative, LLM reads and the session-trained DirectionModel stay **advisory**: shown in the
  app and the journal, never the reason for a trade.

## Where real point-in-time evidence comes from

Only the desk's own recordings of Kotak's live book qualify. Until 3 Oct 2026 the desk recorded one expiry, at the
engine's refresh, on the few sessions it was awake for: 104 snapshots in all. Two changes raise that to about 375 per
series per session:
- the overnight waiter (`wake.yml`, deploy/scheduler.py) so the desk is up at the open;
- the chain tape (intraday/tape.py), which records the 3 nearest NIFTY expiries and 2 BANKNIFTY expiries every minute,
  across every DTE bucket.
`tape.csv` records each attempt, so missing minutes are measured, not guessed. The bar for qualifying (≥ 28 independent
real sessions) is unchanged.

## Reading the report

`plan/studies/<id>/report.md` has separate sections:
1. real point-in-time results;
2. modelled scenario results (scenario analysis only);
3. the EOD approximation;
4. the production change (none unless approved).

Each section gives its sessions, completed plan outcomes, data-quality exclusions by reason, every configuration tried
with its hash, and the locked-period result. A replay hash makes reruns comparable.
