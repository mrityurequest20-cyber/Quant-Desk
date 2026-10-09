# QuantDesk Trading Decision Pipeline (Phase B)

Read-only. Code `main@c96909f`; state `journal@ecd03156` (sessions 2026-10-05 … 10-09 morning). Finding IDs refer
to `QUANTDESK_FINDINGS_REGISTER.md`.

**Two evidence sources**
1. **The live journal.** The decisions are complete for the paths that write them. The thoughts are *sampled*: every
   5 min, on a bias flip, or on a trade.
2. **An instrumented replay** (`audit/probes/phase_b_replay_funnel.py`, output `audit/data/phase_b_funnel.json`) of
   2026-10-05 … 10-08 through today's engine, with as close to live inputs as the archive allows:
   - inputs:
     - recorded 1-minute bars;
     - the **real recorded option chains** from the `chains-2026` release;
     - a copy of the learning memory;
     - news visible from `seen_at`;
     - the production gating (`LiveLearner` with an empty registry);
   - stated differences from live:
     - no global brain and no breadth;
     - armed setups fire on each 1-minute bar's range, not the 5 s LTP;
     - Yahoo history for prior sessions;
   - fidelity check: 10-05 reproduces the live journal exactly (7 EV rejections, 0 trades). On the other days the
     replay records more armed fires than live (bar-range vs 5 s firing). The gating outcome, 0 trades, is the same.

---

## B1. Market interpretation: which inputs can change a trade?

The live chain is:

```
session_state (features.py) + chain_analytics + chainflow + futures + breadth + news + brain + quant
  → Analyst.assess → evidence [(factor, direction, weight × learned)] → score, conviction, bias, day_type, vol_view, vetoes
  → Playbook.scan / arm (setups need sign(score), conviction ≥ 0.45 / 0.55, day_type, levels)
  → _by_record → _by_relative_strength → _model_gates (plan_gate: directional plans removed with no approved plan model)
  → _approved (plan model) | _select_by_ev (Monte Carlo EV floor, global-stress size) → risk.size → live-book checks → open
```

**The decisive fact.** With `autolearn.require_approved_model: true` and an empty plan registry,
`LiveLearner.plan_gate` (`autolearn/live.py:176-189`) returns only plans with `direction == 0`. The one such setup is
`range_sell` (the iron fly).

**The only route to an executed trade today**
`range_sell` (`playbook.py:338-363`), then `_select_by_ev` with `p_up = 0.5` for non-directional plans
(`engine.py:1101`), then `risk.size`.

That route depends only on:
- **`day_type == "balance"`**, which needs `value_pos == "inside value"` (volume profile) and ADX5 < 22. The
  `trend` / `volatile` classifications use ib_ext, the OR break, close_loc and range_vs_avg.
- **`vol_view == "rich"`**: ATM IV ÷ mean(Parkinson RV of the last 30 minutes, 5-day RV) ≥ 1.15.
- **|score| ≤ 0.30.** This is the only way the weighted evidence touches an executable plan.
- **75 ≤ minutes ≤ 255**, `allow_short` (equity ≥ ₹3L), and the ATM/wing quotes.
- **The vetoes and blocks** (below), the EV floor `max(₹40, 0.05 R)`, the sizing, and the global-stress multiplier.

### Feature table

**Column key**

| Column | Meaning |
|---|---|
| Detected | the feature is computed live (seen in the 675 journaled reads) |
| Used for a trade? | does it have a causal path to an *executed* trade under the current config? |
| Weight | live evidence weight (median, after learned multipliers) |
| Stored | in `thoughts.evidence` / narrative |
| Learned | graded into `memory.json` by `grade_factors` |

**Trend and momentum**

| Feature | Detected | Used for a trade? (how) | Weight | Stored | Learned | Verdict |
|---|---|---|---|---|---|---|
| VWAP side and slope | ✓ (675/675) | only via \|score\| ≤ 0.3 for the iron fly; directional bias → gated | 1.01 | ✓ | ✓ (n 211, hit 0.51) | PARTIAL |
| VWAP touch (5 m) | ✓ | `vwap_trend` setup / arming → gated | — | — | — | DIRECTIONAL-ONLY (gated) |
| EMA9/21 (5 m) | ✓ | score; `vwap_trend` / `trend_break` conditions → gated | 0.81 | ✓ | ✓ | PARTIAL |
| Supertrend (5 m) | ✓ | score only | 0.41 | ✓ | ✓ | PARTIAL |
| 15 m EMA20 slope (htf) | ✓ | score only | 0.59 | ✓ | ✓ | PARTIAL |
| RSI (5 m) | ✓ | score; **veto** at > 80 / < 20 (blocks all entries); `va_reversion` | 0.40 | ✓ | ✓ | USED (veto) |
| ADX (5 m) | ✓ | `day_type` (balance needs < 22) | — | narrative | — | USED (iron-fly eligibility) |

**Structure, volume and levels**

| Feature | Detected | Used for a trade? (how) | Weight | Stored | Learned | Verdict |
|---|---|---|---|---|---|---|
| Opening range | ✓ (630) | score; `orb` setups (gated); `day_type` | 1.05 | ✓ | ✓ | PARTIAL |
| Initial balance | ✓ | `day_type` (ib_ext) | — | levels | — | USED (iron-fly eligibility) |
| Session volume profile (POC/VAH/VAL) | ✓ | **`day_type` = balance (inside value)**; the iron fly's range; score | 0.58 | ✓ | ✓ | **USED** |
| Prior-day value area (p_poc/p_vah/p_val) | ✓ | `open_vs_pva` computed, **never read** | — | — | — | DEAD (B-05) |
| Prior-day high/low | ✓ | score only | 0.53 | ✓ | ✓ | PARTIAL |
| CPR | ✓ | score only | 0.40 | ✓ | ✓ | PARTIAL |
| 30-min range (flag) | ✓ | `trend_break` (gated) | — | — | — | DIRECTIONAL-ONLY |
| Relative volume | ✓ (when there is volume) | `orb` filter (gated) | — | — | — | DIRECTIONAL-ONLY |

**Order flow and futures**

| Feature | Detected | Used for a trade? (how) | Weight | Stored | Learned | Verdict |
|---|---|---|---|---|---|---|
| CVD (approximate, close-location) | ✓ (985/1000 reads) | score (×0.5 weight) | 0.30 | ✓ | ✓ | PARTIAL |
| CVD divergence | ✓ (161) | score | 0.50 | ✓ | ✓ | PARTIAL |
| Tick delta / footprint | ✗ (Kite only, untested) | — | — | — | — | NOT LIVE |
| Futures OI build-up | ✓ (224) | score | 0.39 | ✓ | ✓ | PARTIAL |
| Futures basis / carry change | ✓ (251) | score | 0.20 | ✓ | ✓ | PARTIAL |

**Options**

| Feature | Detected | Used for a trade? (how) | Weight | Stored | Learned | Verdict |
|---|---|---|---|---|---|---|
| PCR (OI) | ✓ (671) | score only (real chains only) | 0.32 | ✓ | ✓ (hit 0.57, n 51) | PARTIAL |
| OI walls | ✓ (671) | score; levels | 0.41 | ✓ | ✓ | PARTIAL |
| OI-wall shift, 25Δ skew trend | ✓ | **weight 0** (probation) | 0 | ✓ | ✓ | DISPLAY + LEARN ONLY |
| Max pain | ✗ **never** | unreachable: `is_expiry_day` is always False | — | — | — | DEAD (B-05) |
| ATM IV vs RV | ✓ | **`vol_view` → iron-fly eligibility**; spread choice | — | narrative | — | **USED** |
| IV percentile | ✓ | narrative only | — | narrative | — | DISPLAY-ONLY |
| Gamma / GEX / gamma flip | ✓ | narrative only ("untested here") | — | narrative | — | DISPLAY-ONLY |
| ATM spread % | ✓ | **veto** at > 6% | — | — | — | USED (veto) |
| Leg liquidity / live book | ✓ | blocks entry on a one-sided quote or > 15% slip | — | trade meta | — | USED |

**Volatility, news, global and other context**

| Feature | Detected | Used for a trade? (how) | Weight | Stored | Learned | Verdict |
|---|---|---|---|---|---|---|
| India VIX change | ✓ | score only | 0.30 | ✓ | ✓ | PARTIAL |
| Realised vol (Parkinson 30 m, 5-day) | ✓ | `vol_view`; EV σ | — | — | — | USED |
| News tone | ✓ | score | 0.49 | ✓ | ✓ (n 61) | PARTIAL |
| Breaking news / scheduled event | ✓ | **veto** (15 min after; −15/+45 min around in-session events) | — | ✓ | — | **USED (veto)**, with false positives (B-08) |
| Global drivers (US, $, ₹, Asia, Europe, fear) | ✓ | **weight 0** (probation); risk-overlay size multiplier on stress | 0 | ✓ | ✓ | DISPLAY + LEARN; stress sizing only |
| Global crude | ✓ | weight 0.30 on 32% of reads (graduated on hit 0.59, n 53) | 0 / 0.30 | ✓ | ✓ | PARTIAL (Phase D: selection on noise) |
| Heavyweight pulse | ✓ | weight 0 | 0 | ✓ | ✓ | DISPLAY + LEARN ONLY |
| Breadth, breadth divergence | ✓ | weight 0 (probation) | 0 | ✓ | ✓ | DISPLAY + LEARN ONLY |
| BANKNIFTY vs NIFTY relative strength | ✓ | conviction tilt once the record has t ≥ 2; directional only → gated | — | narrative | ✓ (`rs`) | DIRECTIONAL-ONLY |
| Research drift (edges.json) | ✓ (330) | score; EV drift for directional plans | 0.30 | ✓ | ✓ | PARTIAL |
| Direction model (session-trained) | never valid (AUC 0.47–0.51) | P(up) only if valid → never | — | events | — | INERT |
| GIFT Nifty | ✓ | narrative / review / site only | — | state | — | DISPLAY-ONLY |
| FII flows (participant OI, cash) | ✓ | brain narrative only | — | — | — | DISPLAY-ONLY |
| Buyer's edge (bhavcopy history) | ✓ | narrative only | — | — | — | DISPLAY-ONLY |
| `iv_move` | ✗ | a weight in `DEFAULT_WEIGHTS`, never computed | — | — | — | ORPHAN (B-05) |

**Displayed but with no effect on decisions:** max pain (cannot even be computed live), IV percentile, gamma/GEX,
GIFT Nifty, FII flows, the buyer's edge, prior-day value area, breadth, heavyweight pulse, and every global driver
except crude.

---

## B2. Setup / playbook detection

Setups are **generated, not merely described**. In the replay of 4 sessions × 2 indices:

| Setup | Kind | Raised by `scan` (5 m confirmed) | Armed (minute-reads) |
|---|---|---|---|
| `orb` | directional | 52 | 58 |
| `trend_break` | directional | 122 | 379 |
| `vwap_trend` | directional | 16 | 157 |
| `va_reversion` | directional | 34 | — |
| `range_sell` (iron fly) | non-directional | 74 | — |

**Detection inputs**

| Setup | Needs |
|---|---|
| `orb` | `sign(score)`, conviction ≥ 0.45, OR done, 15–120 min, relative volume ≥ 0.8 |
| `trend_break` | conviction ≥ 0.55, trend/undetermined day, 60–330 min |
| `vwap_trend` | 45 min or later, trend/undetermined day, an EMA order agreeing |
| `va_reversion` | balance/undetermined day, \|score\| ≤ 0.4, RSI extremes |
| `range_sell` | as in B1 |

**Directional plans are fully specified before entry**: invalidation, target, premium stop/target and time stop are
fixed at plan time, with a stop floored at 0.75 ATR5 (`playbook.py:213-226`).

Defect: the opening range, the initial balance and `minutes` are taken from the first bars *present*
(`features.py:97, 124-126`, `iloc[:15]`), not from 09:15 (B-10).

---

## B3. The trading state machine, as built

```
SETUP_DETECTED ──(scan: 5m close confirms)───────────────────────┐
     │                                                            ▼
     └─(arm: read favours it, level within 1.5 ATR5)→ ARMED ──(price/bar reaches level)→ TRIGGER_REACHED
            in memory only, TTL 2 min,                 │                                     │
            rebuilt every minute                       └─(TTL / next minute's re-arm)→ dropped silently
                                                                                             ▼
                        _blocked (kill, safe mode, reconcile, journal, learner fault, paused, stale feed,
                                  vetoes, no/stale chain, risk gate)  ── silent on the armed path
                        → _by_record (setup track record)            ── decision row (deduped 15 min)
                        → _model_gates: plan_gate → entry_filter     ── armed path: decision row; confirm path: NONE
                        → _approved (plan model) | _select_by_ev     ── decision row "EV below the floor"
                        → risk.size (0 lots)                         ── decision row
                        → global stress × size (0 lots)              ── decision row
                        → live book: one-sided leg / > 15% slip      ── decision row
                        → broker.execute → Trade + fills             ── trades / fills
```

### State by state

| Requested state | Exists? | Where | Persisted? |
|---|---|---|---|
| SETUP_DETECTED | implicit | `Playbook.scan`, `Playbook.arm` | sampled thought only (B-03) |
| ARMED | ✓ (`playbook.Armed`) | `engine.armed[u]` | **no** (heartbeat to the site; sampled thoughts) (B-04) |
| TRIGGER_REACHED | ✓ | `_fire_armed` | only via the rejection or trade that follows |
| TRIGGER_NOT_REACHED / EXPIRED / CANCELLED | ✗ (re-arm each minute; the TTL filter drops it) | — | **no** (B-04) |
| TRIGGER_HIT_REJECTED | ✓ | decision `action="rejected"` | partial: the `_blocked` path and `playbook.fire → None` are silent; **the gate is only in free text** (B-03) |
| TRIGGER_HIT_EXECUTED | ✓ | `_open` | trades + fills |
| AUTHORIZATION | ✓ | `_model_gates`, `_approved` / EV, `risk.size`, stress, live book | rejection rows for most gates |
| EXECUTED / REJECTED | ✓ | | |

### Conflations
- **One action for every rejection.** Model authorization, EV authorization, risk sizing and liquidity rejections all
  write the same `action = "rejected"`. Which gate fired is recoverable only by parsing `detail`.
- **No common ID.** No identifier links SETUP → ARMED → TRIGGER → DECISION → TRADE. Repeated fires of one breakout
  are separate rows: ORB at the same 22,473 level on 2026-10-08 fired 09:43, 09:52 and 10:08.
- **Hidden rejections on the confirm path.** When a 5 m-confirmed directional setup is removed by `plan_gate`,
  `_maybe_enter` returns a string. **No decision row is written**; it reaches the journal only as a sampled thought.
  - Replay: 215 such minute-decisions, 0 decision rows.
  - Live: 35 sampled thoughts over 5 sessions (B-03).

---

## B4. The opportunity funnel

### Live journal (decisions, complete for the paths that write them), 2026-10-05 … 10-09 12:20

| Day | Armed setup reached its level → **plan-model gate** | Iron fly → **EV below the floor** | Executed |
|---|---|---|---|
| 10-05 | 0 | 7 (NIFTY, EV +₹18…+₹93/lot, below max(₹40, 0.05 R)) | 0 |
| 10-06 | 3 (vwap_trend 1, trend_break 2) | 1 (BANKNIFTY −₹407, "none fits") | 0 |
| 10-07 | 0 | 38 (NIFTY −₹190…−₹255; BANKNIFTY −₹415…−₹531, P(profit) 0–15%) | 0 |
| 10-08 | 17 (orb 3, trend_break 14) | 5 (BANKNIFTY −₹417…−₹514) | 0 |
| 10-09 (AM) | 1 (vwap_trend) | 0 | 0 |
| **Total** | **21** | **51** | **0** |

### Replay: the full per-minute funnel (2026-10-05 … 10-08, 2 indices, 2,984 index-minutes)

The entry path returned:

| Outcome | Index-minutes | Share |
|---|---|---|
| no setup triggered | 2,093 | 70.1% |
| outside the 09:20–14:45 window | 324 | 10.9% |
| **plan-model gate** (a 5 m-confirmed directional setup removed) | **215** | **7.2%** |
| breaking-news veto | 124 | 4.2% |
| scheduled-event veto (RBI 10-07) | 122 | 4.1% |
| **EV floor** (iron fly) | **74** | **2.5%** |
| first-5-minutes veto | 32 | 1.1% |
| executed | **0** | 0% |

**Armed path:** 594 armed minute-reads → 40 levels reached → 40 rejected by the plan-model gate → 0 reached EV or risk.

**Where opportunities disappear:**
1. **No setup** (70%).
2. **Vetoes and the time window** (20%).
3. **For every directional setup that *was* found: the plan-model gate, 100% of the time.** Nothing directional has
   reached the EV gate, the risk gate or execution.
4. **The single non-directional path (iron fly): the EV floor, 100% of the time.**

### Counterfactual: did the rejected setups go on to work?

Each gated directional opportunity was scored on the underlying alone, with no option premium, spread, theta or
fees: target vs invalidation first within the plan's time stop, stop first on a two-touch bar.

| | Count | Stop first | Target first | Time stop | Mean R (underlying) | Median R |
|---|---|---|---|---|---|---|
| All gated (with repeats) | 264 | 78 | 58 | 128 | +0.19 | — |
| **Unique opportunities** | **133** | **56** | **21** | **56** | **−0.07** | **−0.11** |
| `orb` | 47 | 26 | 3 | 18 | −0.25 | −1.00 |
| `trend_break` | 61 | 23 | 5 | 33 | −0.05 | −0.13 |
| `vwap_trend` | 15 | 6 | 4 | 5 | +0.04 | −0.19 |
| `va_reversion` | 10 | 1 | 9 | 0 | +0.42 | +0.50 |

**Reading**
- Over these 4 sessions the blocked directional opportunities would have **lost** on the underlying before any
  option cost.
- So there is no evidence the gate is hiding profitable trades. The sample is 4 sessions, heavily autocorrelated, so
  this is no evidence of an edge either way.
- The `va_reversion` result is 10 rows, mostly one day.
- The repeated-row mean (+0.19) is inflated by duplicates of the same move: B-09, re-fires.

### Why did recent sessions produce zero trades? (final question 18)

**For directional setups:**
- `require_approved_model: true` + an empty plan registry → `plan_gate` removes every one.
- The plan registry cannot be populated until the real point-in-time track has 28 complete sessions: 15 training +
  5 folds + 8 locked. It had 5 on 2026-10-08 (`plan/latest.json`).
- After that a model must still pass its gates.
- **Earliest possible directional trade:** about 23 more complete recorded sessions away, and only if a model then
  qualifies.

**For the iron fly:**
- It qualified on 3 of 4 replayed days (balance day + rich IV + small \|score\|).
- The Monte Carlo EV after costs never cleared `max(₹40, 0.05 R)`:
  - 10-05 NIFTY was positive but tiny (+₹18…+₹93/lot);
  - 10-07 and 10-08 were negative (−₹190…−₹531/lot);
  - BANKNIFTY often "none fits" (0 lots at the ₹30k/lot credit margin).
- Whether that EV is right is Phase C3.

**The remaining minutes:** no setup, or vetoed (time window, the RBI event, breaking news).

---

## B5. The anticipation / trigger engine

| Aspect | As built | Verdict |
|---|---|---|
| Trigger calculation | `Playbook.arm`: ORB at the OR high/low ± 0.10 ATR5 (stop entry); `trend_break` at the 30-min range edge ± buffer; `vwap_trend` at VWAP ± buffer (limit). Only if the level is within 1.5 ATR5, there are no vetoes, and conviction ≥ 0.45 | VERIFIED |
| Price monitoring | `run_live`: `engine.tick()` every `tick_sec` (5 s) with Kotak LTP between minute steps (`engine.py:537-575`) | VERIFIED (code); live fires in the journal at the exact levels (e.g. 22,473.15 / .03 / .18 vs the armed 22,473) |
| Bar fallback | Without a working LTP, each new 1-minute bar's range fires (`bar_fill`: the level, or the open on a gap). **With a working LTP, bar-range firing is off** (`engine.py:256`). A level touched and left between two 5 s polls is never fired (B-09) | PARTIAL |
| TTL / expiry | 2 min, rebuilt every minute; expired setups are silently dropped (B-04) | VERIFIED, not persisted |
| Stale data | `_blocked` re-checks feed staleness and chain age at fire time. The chain is repriced by Black-Scholes from the last snapshot (up to `chain_stale_min` = 12 min old) (`_chain_at`) | PARTIAL |
| Post-trigger gates | the same as the confirm path (`_by_record`, `_model_gates`, `_approved` / EV, `risk.size`, live book) | VERIFIED |
| Authorization before arming | **none**: setups are armed and shown as "Waiting at the level" although `plan_gate` will reject every one (B-06) | MISLEADING (display) |
| Armed-state persistence | none: memory plus the heartbeat (`engine.py:1317`). A restart or hand-over loses it; harmless, since it is rebuilt next minute | VERIFIED |
| Missed triggers | the LTP sampling gap (above); and arming is skipped whenever the minute's entry path returned anything other than "watching…", e.g. a gated confirm-path setup or an EV rejection (`engine.py:444`) | PARTIAL |
| Race conditions | `_fire_armed` authorizes against the **previous minute's** view and vetoes (`self.views[u]`, `engine.py:458`). News refreshes only in `step()`, so a breaking story that lands mid-minute does not block a tick-fired entry until the next step (B-09) | PARTIAL |
| Re-fire | one shot per read, re-armed next minute. The same level fires again on each recross: ORB 3× on 10-08, each a separate decision and a separate "rejected opportunity" (B-09) | VERIFIED |
| No-trade learning for armed rejections | `grade_armed` needs `context["target"]`, which the plan-gate rejection path never writes (`engine.py:481`). All 21 live armed rejections are ungraded; the memory logs "0 armed" every session (B-07) | BROKEN |

---

## Phase B probes (`audit/probes/test_phase_b_probes.py`, all 6 pass)

| Probe | Confirms |
|---|---|
| `test_expiry_day_is_never_today_so_max_pain_never_fires` | B-05 |
| `test_armed_rejections_by_plan_gate_are_never_graded` (21 real rows → 0 graded) | B-07 |
| `test_retold_rbi_decision_two_days_later_still_vetoes` | B-08 |
| `test_question_style_preview_is_not_recognised_as_a_preview` | B-08 |
| `test_arm_does_not_consult_the_plan_gate` | B-06 |
| `test_bar_range_firing_disabled_when_live_price_works` | B-09 |

Plus the replay harness `audit/probes/phase_b_replay_funnel.py`. It needs the journal snapshot and the
`chains-2026` assets for the days replayed, and Yahoo for prior sessions.
