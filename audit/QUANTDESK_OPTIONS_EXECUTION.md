# QuantDesk: Options, Futures and Execution (Phase F)

Read-only forensic audit, Phase F of the master protocol. Findings use the register's format and IDs
(`QUANTDESK_FINDINGS_REGISTER.md`). This file is an extra artifact for Phase F; the protocol's list has no dedicated
one.

**Status: Phase F complete, awaiting review.** No production code, configuration or state was changed.

---

## F0. Objective, scope, baseline

### Objective (master protocol)

Audit futures basis, OI, participant OI, the option chain, IV, Greeks, gamma, expiry, contract identity, rollover,
settlement, spreads, fills, slippage, quote freshness, broker timestamps and paper/live parity. "Verify displayed
information actually affects decisions."

### Modules covered

| Area | Modules |
|---|---|
| Contract identity and expiry | `core/calendar.py`, `core/types.py`, `config/quantdesk.yaml` (instruments, holidays) |
| Futures | `intraday/futures.py`, `intraday/kotak.py` (`KotakFutures`, `KotakIntradayFeed`) |
| Chain sources, IV, analytics | `intraday/chains.py` (Kotak → NSE → model fallback, `fill_iv`, `chain_analytics`) |
| Pricing and gamma | `options/pricing.py`, `options/gex.py` |
| Fills and marks | `intraday/engine.py` (`_open`, `_close`, `_live`), `intraday/sim.py` (`QuoteMarker`, `IntradayBroker`) |
| Costs | `execution/costs.py` |
| Settlement | `execution/broker.py` (`settle_expiry`), `intraday/sleeves.py` |
| Live broker | `execution/kite.py` |
| Context | `intraday/brain.py` (participant OI, stress) |
| Consumers | `intraday/analyst.py`, `intraday/playbook.py` |

### Baseline

| Item | Value |
|---|---|
| Start commit | `13a7c78`, clean tree |
| Tests for these modules (9 files: account, calendar, chainflow, execution_risk, kotak, kotak_backfill, options, sleeves, tape) | 100 passed, 3 skipped, **2 failed: pre-existing A-19** (`test_kotak.py::test_chain_from_the_live_book`, date bomb) |
| Evidence | journal snapshot `ecd03156`; `chains-2026` tapes 10-05 … 10-08 (5 underlyings, 1-minute snapshots with bid/ask/size); warehouse bhavcopies |

**Evidence tags:** [prod] production record · [replay] rerun on archived data · [synth] synthetic or fake ·
[infer] inference · [code] code reading.

---

## F1. Contract identity, expiry, lots, rollover

| Check | Result | Class |
|---|---|---|
| Every exchange-listed expiry (10-09 → 12-31) is on the desk's calendar (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX) | **Yes, all.** Includes the holiday shifts 10-19 (Dussehra), 11-09 (Diwali), 11-23 (Guru Nanak) | [replay] V-27 |
| Lot sizes vs the exchange files | **All match** (65 / 30 / 60 / 120 / 20 / 30) | [replay] V-27 |
| Holidays vs NSE's list | 16 configured = every NSE weekday holiday in 2026 (the 4 others fall on weekends) | [replay] |
| Holidays after 2026 | **None configured.** 2027-01-26 (Republic Day, a Tuesday) is treated as a trading day and a NIFTY expiry | [synth] F-07 |
| Desk weeklies the exchange has not listed yet | Desk NIFTY 11-17, 12-01 … 12-22 and SENSEX 12-03 … 12-24 are future weeklies; normal listing lag. Matters only where the calendar invents a contract (the model chain, F-01). | [replay] |
| Option contract identity | `Instrument.option` symbol = underlying + expiry + strike + right. Kotak tokens are resolved per chain row. Kite resolves by name, type, strike and expiry against its instrument dump. | [code] |
| Futures roll | Data side: near month, rolled `roll_days: 3` calendar days before expiry (`KotakFutures.active`). **The 5-day history is fetched on the currently active contract for all 5 days**, so across a roll the earlier days carry the next month's (thinner) volume. Execution side (Kite): **always the nearest future**, ignoring the roll (F-06). | [code] F-07 |

## F2. Futures basis, OI, participant OI

**Futures read** (`futures.read`):
- **Basis** = LTP − index.
- **Carry** = log(F/S)/T (ACT/365 to 15:30).
- **OI build-up** over 30 minutes: four states; covering and unwinding count half.
- **Same-day carry change.**
- **OI units:** the desk computes the OI change as current − previous. Kotak's `oi.chg` field is actually the price
  change, and the desk correctly does not use it (V-30).

**The 15:15 freeze is vendor-side (answers Q-08)** [prod]:
- Kotak's 1-minute index candles are flat from 15:15 to ≈15:28 every session (E-01).
- The near-month future, fetched through the same client and the same `candles()` → `normalise_bars` path, keeps
  trading. On 10-06 the future moved 22,782 → 22,806 → 22,799 while the index sat at 22,717.70.
- The desk's aggregation treats both series identically, so the freeze is in Kotak's index series.
- **Consequences** (F-02):
  - "basis" swings ~24 points in 14 minutes from staleness alone;
  - **71 of the 675 graded factor reads (10.5%)** have 30-minute windows ending in frozen minutes;
  - the sleeves' 15:20 strike deltas use a 5-minute-stale spot.
- Entries (cut-off 14:45) and the engine's 15:15 square-off are not affected.

**Participant OI and FII/DII flows** (`brain.fii_positioning`) [code]:
- Point-in-time: rows up to the day before (V-05).
- Narrative only: "a regime input, not an intraday vote". No score or sizing input reads them (V-32).

**Global stress** (Q-07) [prod + code]:
- The size multiplier is applied after the EV gate, which no plan has passed (B-02, C-05), so it cannot bind today.
- Only the latest brain state is persisted (`state.intraday_live`: stress 0.78, ×1.0), so its history cannot be
  reconstructed.
- Q-07 is closed as unreachable and unrecorded.

## F3. Option chain, quote freshness, IV, Greeks, gamma

### Chain sources [code]

`FallbackChain(Kotak → NSE, NSE asked at most every 3 minutes)`. If both fail, the engine prices off
`ModelOptionChain`:
- prices from India VIX × beta plus a skew model;
- spreads modelled;
- **OI fabricated as a Gaussian bump ~0.8σ from spot, ×1.8 on "round" strikes**.

**F-01:**
- The model chain is exempt from the stale-chain gate.
- The playbook builds plans on it, EV prices them, and the paper broker fills them at modelled bid/ask.
- Only PCR is guarded against `source == "model"`. **OI walls (a vote) are computed from the fabricated OI.**
  Max pain is too, but it never votes (B-05).
- A WARN event is journaled, but the fill label reads "option chain", not "model".
- In production since 10-05: 0 fallback events, so the risk is latent.

### Freshness

- A-11 stands: Kotak chains are stamped at fetch time and IV is filled from the LTP when there is no two-sided quote.
- The stale gate is 12 minutes; the refresh is 1 minute for Kotak.
- New here: model chains bypass the gate entirely (F-01).

### Pricing [synth]

`phase_f3_pricing.py` (V-28):

| Check | Result |
|---|---|
| `bs_price` vs an independent BS | exact (max error 0.0 pts over 3,000 random contracts) |
| Delta vs finite difference | ≤ 3.5·10⁻⁵ |
| Gamma, relative error | ≤ 0.17% |
| Implied vol recovers the true vol | yes, except zero-time-value deep in-the-money options, where vol is unidentifiable and the solver floors it (correct) |

### Put/call parity with fixed r = 6.5%, q = 1.2% (F-03) [replay]

On the recorded chains (ATM, two-sided quotes, every 30 minutes), the chain's own forward
`K + e^{rT}(C − P)` differs from the desk's `S·e^{(r−q)T}`:

| Underlying, DTE | n | Median put − call ATM IV (vol pts) | Forward vs desk (bps) |
|---|---|---|---|
| NIFTY ≤ 2 d | 11 | **−3.24** | +7.0 |
| SENSEX ≤ 2 d | 11 | **+3.38** | −7.7 |
| NIFTY 2–7 d | 28 | +1.05 | −5.4 |
| NIFTY 7–15 d | 72 | −1.07 | +7.1 |
| BANKNIFTY 40 d + | 49 | −1.97 | +27.6 |
| MIDCPNIFTY 15–40 d | 50 | −0.28 | +2.6 |

- The ATM IV (the mean of the two sides) largely cancels the error.
- **The 25-delta skew level does not.** It takes the put IV at a put strike and the call IV at a call strike, so the
  forward error shows up directly as "skew" in the narrative and the app.
- The probation factor `skew_trend` uses the 30-minute *change* in `skew_25d`. That cancels a forward bias that is
  constant within the day, so it is affected only as far as the error drifts (e.g. through the session near expiry).
- The desk already computes the chain's implied forward (`gex.implied_forward`) but uses it only for display.

### Gamma (GEX) [code]

- Naive dealer-sign convention, labelled in the code as "context, never a vote".
- The analyst uses it only in narrative text (V-32).
- OI units are handled (Kotak reports shares, NSE contracts).

## F4. Spreads, fills, slippage, costs

### Fill model [code]

| Event | Price | Checks |
|---|---|---|
| Entry with a live book | Each leg at the live ask (buy) / bid (sell), + 1 tick (`adverse_ticks`) | Skip if any leg is not two-sided, or the net premium moved > 15% against the plan |
| Entry without a live book | The plan's chain price, + 1 tick | Chain may be up to 12 minutes old; **no move-away check** |
| Exit with a live book | Live bid/ask, + 1 tick | — |
| Exit without a live book | `QuoteMarker`: Black-Scholes at the last calibrated IV and the current spot, ∓ half the last spread | — |
| Premium stops and targets | Black-Scholes marks (IV recalibrated at each chain refresh), not quotes | — |

### Depth (F-04) [replay]

`phase_f4_depth.py`: best-level sizes within ±4 strikes on the nearest expiry, every 15 minutes:

| | Median best size | Best levels < 1 lot | Best levels < 10 lots (`max_lots`) |
|---|---|---|---|
| NIFTY | 195 = 3 lots | 0% | **81%** |
| BANKNIFTY | 60 = 2 lots | 0% | **99%** |

- The engine never reads `bidq`/`askq` (probe). Any order fills in full at top-of-book + 1 tick: 10 lots at the same
  price as 1.
- At the ₹5L account's typical 1–3 lots this is mostly harmless. Above the best-level size the paper fill is optimistic.
- Latent: the engine has 0 trades (B-02).

### Spreads [replay]

On NIFTY and SENSEX expiry eves, real half-spreads are about half the research cost model's (E-07). The intraday
engine uses the live book itself, not a model, when Kotak answers.

### Costs [code + external]

- Brokerage ₹20/order.
- Options STT 0.15% of premium on sells.
- NSE exchange 0.03503%, SEBI ₹10/crore, stamp 0.003% on buys, GST 18%. These match the 2026 schedule as the desk
  states it.
- **Exercise STT is 0.125%** (`warehouse_research.STT_EXERCISE`, sleeves, specs). Secondary sources report it rose to
  **0.15% on 1 Apr 2026**, alongside the 0.10 → 0.15% sale rate the desk already uses. So the research and sleeves mix
  the post-April sale rate with the pre-April exercise rate. The primary circular was not opened.
- `PaperBroker.settle_expiry` charges **no** exercise STT.
- The amounts are small: 0.025% of the intrinsic value of exercised long legs (F-05).
- C-04 stands: autolearn futures STT is 2 bps vs 5 bps.

## F5. Settlement and expiry handling

| Path | Expiry handling | Finding |
|---|---|---|
| Intraday engine | Never holds to expiry: skips 0-DTE (`expiry_min_days: 1`), squares off at 15:15 | none |
| Daily desk (`engine/engine.py`) | `PaperBroker.settle_expiry` at intrinsic value, no exercise STT | Not scheduled in production (architecture map); F-05 |
| Sleeves | 15:00–15:29 mean of frozen minutes | **E-01** (P1, Phase E); F-02 adds the root cause |
| Research (laws, wings) | Official close (`nse_index_close`) / BSE bhavcopy underlying | correct |

## F6. Paper/live parity and broker timestamps

### Live paths [code]

- **The intraday engine has no live broker.** Kotak is data-only and the engine always uses `IntradayBroker` (paper).
- The only real-order code is `KiteBroker`, reachable only from the daily desk's `paper --live`, behind
  `account.mode: live` (config: `paper`) plus the `--live` flag plus credentials (V-31).

### Latent defects in `KiteBroker` (F-06) [synth]

Probe with a fake Kite API; nothing left the process.

| Defect | Detail |
|---|---|
| **Partial fills are lost** | 130 of 650 filled, then the 20 s timeout: the order is cancelled and `execute` returns `None`. The engine sees no fill while 130 are held at the broker. `filled_quantity` is never read. |
| Naive fill timestamp | `pd.Timestamp.now()`: local, no timezone, not the exchange's time |
| Futures symbology ignores the roll | Always the nearest future, even on expiry day; the data side rolls 3 days earlier |
| Legging risk | Multi-leg structures go leg by leg, up to 20 s each. The intraday engine's paper unwind ("at entry price") has no live equivalent. |
| Untested | "Untested against the real API from this repo's CI" (its own docstring) |

### Broker timestamps (answers Q-01) [replay]

`phase_f6_bar_label.py`:
- Chain-tape snapshots are fetched ≈14 s into each minute (n = 7,936).
- The snapshot spot lies inside the bar labelled with the **same** minute 87% of the time, vs 43% for the next
  minute's bar.
- **Kotak 1-minute candles are labelled by bar start**, as the docstring says. `completed()` therefore admits only
  finished minutes (V-29).
- Chain timestamps remain fetch time (A-11).

---

## F7. Displayed vs decision-affecting

The final question 12: "Are futures / OI / options / IV / gamma actually used?"

| Input | Where it acts | Class | Reaches a trade today? |
|---|---|---|---|
| Chain prices and bid/ask | Strike selection (delta), plan premiums, EV, live-book skip checks, fills | **Decision** | Only via plans; none pass (B-02) |
| ATM IV (`vol_view` = IV/RV) | Iron fly needs "rich"; directional spreads when rich | **Decision** | Iron fly fails EV (C-05) |
| ATM spread % | Veto above `max_spread_pct` | **Decision** (veto) | Yes, as a veto |
| Leg IV in EV | Fixed per leg (C-06) | **Decision** | EV gate |
| PCR (OI) | Analyst vote 0.3 (not on a model chain) | Score | Only via the iron fly's \|score\| ≤ 0.3 and the EV P(up) prior (B-01) |
| OI walls | Analyst vote 0.4 (**also on a model chain**, F-01) | Score | as above |
| Max pain (expiry day, > 180 min left) | Analyst vote 0.3, but `is_expiry_day` is never True | **Dead** (B-05) | No |
| Futures OI build-up | Analyst vote 0.4 | Score | as above |
| Futures carry change | Analyst vote 0.2 | Score | as above |
| OI shift, skew trend (`chainflow`) | Probation factors: votes only once graduated | Score (probation) | as above (`skew_trend` uses the 30-minute change, so the F-03 level bias mostly cancels) |
| GEX and gamma flip | Narrative only | **Display-only** (honestly labelled) | No |
| IV percentile, IV trend | Narrative only | **Display-only** | No |
| Implied forward | Computed, not used | **Display-only** | No |
| Participant OI, FII/DII flows | Narrative only | **Display-only** (honestly labelled) | No |
| Futures volume on index bars | VWAP, volume profile, CVD, relative volume, i.e. the setups' inputs | **Decision** | Via setups (B) |
| Global stress multiplier | Lot sizing after EV | Decision | **Unreachable** (Q-07) |

**Answer to question 12.** Options data is used for structure, pricing, vetoes and EV. OI, futures and PCR are used as
score votes, and the score's path to an executed trade is very narrow (B-01). Gamma and participant OI are context
only, and say so. Nothing in this group currently ends in a trade, because the gates above it close every path (B-02,
C-01, C-05).

---

## Coverage matrix

| Protocol item | Covered in | Status |
|---|---|---|
| Futures basis | F2 | Covered: correct maths; post-15:15 basis contaminated (F-02) |
| OI | F2, F3 | Covered: OI change computed correctly (V-30); model-chain OI fabricated (F-01) |
| Participant OI | F2 | Covered: display-only, PIT (V-05, V-32) |
| Option chain | F3 | Covered: sources, fallback, freshness (A-11, F-01) |
| IV | F3 | Covered: solver correct (V-28); forward bias (F-03) |
| Greeks | F3 | Covered (V-28) |
| Gamma | F3 | Covered: GEX display-only (V-32) |
| Expiry | F1 | Covered (V-27; F-07 for 2027) |
| Contract identity | F1 | Covered (V-27) |
| Rollover | F1 | Covered: data roll vs Kite symbology (F-06), 5-day history across a roll (F-07) |
| Settlement | F5 | Covered (E-01, F-02, F-05) |
| Spreads | F4 | Covered (E-07 for research; the live book for the engine) |
| Fills | F4 | Covered (F-04) |
| Slippage | F4 | Covered: 1 tick on bid/ask; no depth (F-04) |
| Quote freshness | F3, F4 | Covered (A-11, F-01, F-04) |
| Broker timestamps | F6 | Covered (V-29 answers Q-01; F-06 Kite) |
| Paper/live parity | F6 | Covered: no live path for the intraday desk; Kite latent defects (F-06) |
| Displayed info affects decisions | F7 | Covered: the table above |

**Not tested:**
- A real Kotak or Kite order: no credentials, and forbidden by the audit rules.
- NSE chain fallback behaviour live: NSE is blocked from this environment.
- The NIFTYNXT50 instrument: not configured on the desk.

## Proven / suggestive / untested

**Proven:**
- The freeze is vendor-side, and its reach into basis and learning (F-02).
- The model-chain fallback mechanics (F-01).
- Depth vs order sizes (F-04).
- The Kite partial-fill loss (F-06, on a fake API).
- Pricing correctness (V-28).
- The start-labelled candles (V-29).
- Expiry and lot identity (V-27).
- Exercise STT in code = 0.125% (F-05).

**Suggestive:**
- That the statutory exercise STT is now 0.15%: secondary sources; the primary circular was not read.
- That F-03's parity gap comes from fixed q and r rather than asynchronous spot and quote snapshots. Both plausibly
  contribute.

**Untested:**
- The live Kite and Kotak order behaviour.
- The NSE fallback under real throttling.
- How often the model-chain fallback would trigger in a GitHub-hosted runner. NSE blocks many cloud IPs, so a Kotak
  outage would very likely end on the model chain.

## Proposed findings (register)

| ID | Title | Sev | Status |
|---|---|---|---|
| F-01 | The model-chain fallback trades on fabricated data: exempt from the stale gate; fabricated OI drives the OI-wall vote; fills labelled "option chain" | P2 | VERIFIED (latent: 0 fallbacks since 10-05) |
| F-02 | The 15:15–15:28 index freeze is in Kotak's index series and also contaminates basis, 10.5% of graded factor reads and the sleeves' 15:20 deltas | P2 | VERIFIED |
| F-03 | Fixed r/q instead of the chain's forward: put−call ATM IV gaps of ±3 vol pts near expiry bias the 25-delta skew level | P4 | PARTIAL |
| F-04 | Paper fills ignore depth (10 lots at the price of 1) and fall back to stale chain prices without a move-away check | P3 | PARTIAL (latent) |
| F-05 | Exercise STT 0.125% vs 0.15% since Apr 2026; paper settlement charges none | P4 | PARTIAL |
| F-06 | The Kite live adapter drops partial fills, stamps naive local time, ignores the futures roll, legs sequentially | P3 | BROKEN (latent: no scheduled path) |
| F-07 | Calendar and contract edges: no holidays after 2026; 5-day futures history across a roll; the model chain can price unlisted weeklies | P4 | VERIFIED |

**Controls:** V-27 … V-33. **Questions:** Q-01 answered (start-labelled), Q-07 closed (unreachable, unrecorded),
Q-08 answered (vendor-side). New: Q-12, the model-chain fallback rate in production conditions.

## Remediation (not implemented: awaiting review)

| Priority | Fix | Addresses |
|---|---|---|
| 1 | On a model chain: refuse entries (or require an explicit flag), never vote OI walls, label fills "model" | F-01 |
| 2 | Detect flat index runs (O = H = L = C unchanged ≥ 3 minutes with the future moving) at record time; exclude them from settlement, basis and grading. Ask Kotak about the index feed after 15:15. | F-02, E-01 |
| 3 | Solve IV against the chain-implied forward (already computed by `implied_forward`); report skew on forward moneyness | F-03 |
| 4 | Cap fills at the best-level size or walk the book; apply the move-away check to chain-price entries too | F-04 |
| 5 | `STT_EXERCISE` → 0.15% from 2026-04-01, by date; charge it in `settle_expiry` (a new sleeve spec, since the old ones froze 0.125%) | F-05 |
| 6 | Before any live use of Kite: handle partial fills, use exchange timestamps, roll-consistent symbology, an atomic multi-leg policy, and a sandbox test | F-06 |
| 7 | Load holidays per year from the warehouse's `nse_holidays_*` and fail closed when a year is missing; fetch futures history per contract across rolls | F-07 |
