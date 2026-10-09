# QuantDesk: Real-Session Forensics (Phase K)

Read-only forensic audit, Phase K of the master protocol.

**Status: Phase K complete, awaiting review.** Local and uncommitted.

**Proposals are kept out of the canonical register.**
- The proposed findings (**K-01 … K-06**) and controls (**V-K1 … V-K4**) are **not** in the canonical register.
- The owner's Phase J decisions are recorded here as decisions. They are **not** applied to the register:
  - J-01 → P1;
  - J-02 P2 (P0 if live);
  - J-03 P2;
  - the other J findings as proposed;
  - corrections preserved: 22 armed triggers rejected, 67 breaking-news reads, 18 crops.

**What was not touched:**
- no production code, UI, configuration, workflow, schedule, permission, branch protection or account;
- not the engineer's session;
- nothing committed or pushed;
- no broker or credential use;
- Phase L not started.

**No reconstructed screen below was observed live in production.** Every UI capture is a local render: headless
Chromium at a fixed clock, of either production data or replay/synthetic data, as labelled.

---

## K0. Method and evidence classes

**Protocol (§ Phase K):**
- Select representative real sessions: profitable/trading, zero-trade, strongly trending, reversing, event-driven,
  provider/model degradation.
- For each, reconstruct: market state → available information → detected setups → rejected setups → armed setups →
  trigger levels → trigger hits → authorization gates → execution → outcome → learning → subsequent use.
- Compare with the journal and the UI; investigate disagreements; pay special attention to zero-trade sessions.

**Owner's minimum timeline points:**
1. open and first heartbeat;
2. an armed minute with its gate outcome;
3. a rejection and its reason in the UI;
4. the 12:20 handover;
5. close and last displayed state;
6. a `data.json` outage and recovery;
7. trade-detail explanation (synthetic).

| Tag | Meaning |
|---|---|
| **[prod]** | Production persisted record: journal copies `ecd03156` / `0143b5c`, `chains-2026` archives, GitHub run and job metadata |
| **[prod-render]** | Production data rendered locally at a simulated clock (not observed live) |
| **[replay-exact]** | Persisted inputs only (recorded bars, archived chains, a memory copy) through the repo's replay wiring. The replay omits the non-persisted inputs: news, brain, breadth, learner, research priors (I-04) |
| **[replay-subst]** | As replay-exact, plus Phase I's documented VIX substitution (all-zero prior-day VIX files dropped) |
| **[synth]** | Synthetic session (`simulate_sessions`, model chain) |
| **[synth-subst]** | Synthetic with a documented config substitution (`autolearn.require_approved_model: false` in the scratch config) so that the engine can trade |

**Harnesses** (all new, in `audit/probes/`):

| Harness | Purpose |
|---|---|
| `phase_k_sessions.py` | Per-session reconstruction from persisted evidence |
| `phase_k_prod_points.py` | Production evidence at the timeline points |
| `phase_k_timeline.py` | Minute-by-minute replay with the production 12:20 handover emulated (persist → stop → fresh engine on the same files); a snapshot plus the published site at each point |
| `phase_k_outage.py` | `data.json` outage and stuck-publish via Playwright request interception and the fake clock |
| `phase_k_trade_fixture.py` | A synthetic session where the engine trades by its own path |
| `phase_k_trade_sheet.py` | Renders the trade-detail sheet |
| `phase_j_*` | Reused for builds and renders |

---

## K1. Session selection and per-session reconstruction

All five recorded production sessions are **zero-trade**. Source: `audit/data/phase_k_sessions.json` [prod].

| Protocol type | Session | Why |
|---|---|---|
| Profitable / trading | **None in production** (0 trades since the 10-05 reset) | Synthetic only: 09-11 [synth-subst], § K2 point 7 |
| Zero-trade | 10-05 … 10-09 (all) | — |
| Strongly trending | **10-08** | NIFTY −1.63 % open→close, close location 0.12; 129/149 reads bearish |
| Reversing | **10-05** | NIFTY −0.45 % to 12:20, then +0.56 %; 27 bias flips |
| Event-driven | **10-07** | RBI MPC at 10:00: "scheduled event" and RBI breaking-news stand-asides |
| Provider / model degradation | **10-09** | 5 of 564 polls from Yahoo; slow steps of 51 s and 65 s. **All five sessions:** India VIX recorded as 0 (I-01) |

### The protocol chain per session [prod]

| Stage | 10-05 reversing | 10-06 trend up | 10-07 event | 10-08 strong trend down | 10-09 degraded |
|---|---|---|---|---|---|
| Market (NIFTY) | +0.10 %, range 1.00 %, am −0.45 / pm +0.56 | +0.76 %, close loc 1.00 | −0.39 %, range 0.76 % | **−1.63 %**, range 1.85 %, close loc 0.12 | +0.92 %, close loc 0.79 |
| Available info | feed kotak, chain kotak, **VIX 0 on 373/373** bars | kotak; VIX 0 372/373 | kotak; VIX 0 373/373 | kotak+yahoo (1/567); VIX 0 372/373 | kotak+yahoo (**5/564**); VIX 0 372/373; slow steps |
| Reads (sampled) | 149: bearish 67 / bullish 55, 27 flips | 151: bullish 131 | 153: mixed, 37 flips | 149: **bearish 129** | 141: bullish 132 |
| Stances | watching 113, aside 29, armed 3 | watching 86, aside 36, **armed 29** | **aside 79**, watching 57, range_sell 12, armed 5 | watching 61, aside 55, **armed 33** | watching 93, aside 32, armed 16 |
| Rejected (journal) | 7 EV floor | 1 EV, 3 no-plan-model | **38 EV floor** (24 distinct plans) | 5 EV, **17 no-plan-model** | 2 no-plan-model |
| Armed triggers hit → gate | 0 | 3 → all rejected "no approved plan model" | 0 | **17 → all rejected** | 2 → all rejected |
| Execution | 0 | 0 | 0 | 0 | 0 |
| Counterfactual: touch entry → 15:15 touch, 1 lot (§ caveats) | EV rows −₹1,008 (net of fees −₹2,606) | EV +₹460; armed +₹217 | EV +₹11,268 gross, **+₹1,026 net** after the recorded fees | EV −₹176; **armed +₹12,242 (12/17 winners, median +₹376/lot, fees not recorded)** | armed −₹863 |
| Learning (events) | "graded: … 2028 factors, **0 armed**"; 1 grading failed | 0 armed; 2 failed | 0 armed; 2 failed | 0 armed; 2 failed | 0 armed; 2 failed |
| Subsequent use: median learned multiplier in that day's reads | vix **1.020**, pcr 1.000 | vix 0.980, pcr 1.124 | vix 0.993 | vix 0.997 | vix **0.954**, pcr 1.148 |

**Counterfactual caveats:**
- 1 lot, held to 15:15.
- Entry at the plan's recorded touch prices; exit at the archived 15:15 touch.
- Fees only where the decision recorded them (EV rows).
- Re-fires overlap: armed triggers are counted per distinct plan, but only one position is allowed at a time.
- Not evidence of edge (1 day each, n small).

### What the zero-trade sessions show [prod]

1. **Every directional trigger that fired was rejected by the plan-model gate:** 22 of 22 (B-02).
2. On the strongest trend day (10-08) those 17 rejected triggers would, before fees, mostly have won at the touch
   (12/17). That is what the gate cost on that one day; it says nothing about whether the gate is right.
3. **No-trade learning never ran:** every session's grading line says "0 armed" although 22 armed triggers fired and
   were rejected (D-05, B-07 settled; confirmed).
4. **Subsequent use of fabricated input:**
   - the `vix` factor's learned multiplier moved 1.020 → 0.954 across the five sessions;
   - it was learning from the zero-VIX vote (I-01, J-01).
5. The catch-up grading failed at every session start and handover (A-02): 9 "grading failed" WARNs in 5 sessions,
   plus 1 "caught up: 0 …" on 10-05.

### Corrections to earlier proposals, from production metadata

These are **not** applied to any earlier report; they are proposed for review.

| Item | Was | Evidence | Proposed correction |
|---|---|---|---|
| **I-10** (proposed) | "Market data for some sessions is not persisted anywhere … 10-01 (a session of the pre-reset ₹20k account)" | `live.yml` runs: 09-30's run started 09:49Z = **15:19 IST** (late cron, which explains its 10 bars); 10-01's started 10:16Z = **15:46 IST, after the close**; no dispatched run either day [prod, GitHub] | **10-01 had no live session**, so there is no data to persist. The I-10 *effect* stands (replays and `memory` have no 10-01 record), but the cause is the pre-Worker scheduler (H1), not a persistence gap. Retitle as "No live session on 10-01 (and only 10 minutes on 09-30); the record's history has holes" |
| **J-05** (accepted) / D-03 | "10 sessions graded" mixes "bootstrap and pre-reset sessions" | `memory.bootstrap.days` = 09-24, 09-25, 09-28, **09-29, 09-30, 10-01** (Yahoo replays); live sessions = 10-05 … 10-09 [prod] | 6 of the 11 "graded sessions" are **bootstrap Yahoo replays**, including 10-01, a day the desk never ran. The J-05 qualification is unchanged; its evidence line should say so |

---

## K2. Timeline matrix (the owner's seven points)

**Key:**
- **Repro** = discrepancy classification: R reproduced · PR partially reproduced · NR not reproduced · U untestable.
- All UI cells are **local renders**.

### Point 1: Session open and first valid heartbeat

| Item | Value |
|---|---|
| Timestamp | 09:15–09:20 |
| Persisted input | Bars from 09:15; first thoughts **09:16:04** ("standing aside: first 5 minutes…"); session events back-dated 09:15 (A-13); first `equity` row 09:20:04 [prod, all 5 days] |
| Engine decision | 09:16: stand aside, first 5 minutes [replay-exact 10-05 = prod text] |
| Journal state | `intraday_open` for the day; equity ₹5.00 L |
| Heartbeat / API | First heartbeat 09:16; `data.json` published every 6 min from engine start (~08:31), so the first fresh publish is ~09:19 plus Pages latency [code + prod job timings] |
| Visible UI claim | 09:05 [prod-render]: "Closed · opens today 09:15 … Showing its last state from 09 Oct, 15:30" ✓. 09:16 replay [replay-exact]: "Live 09:16 · Standing aside: First 5 minutes" ✓. **09:17 [prod-render, previous-day data.json]: "Stale 3947 min" plus the banner "It hands over to a fresh runner at 12:20…"** |
| Repro | **PR**: the stale window at every open is reproduced on production data; its length (~4–6 min) is inferred from the publish cadence; Pages latency U → **K-03** |

### Point 2: Armed minute and actual gate outcome

| Item | Value |
|---|---|
| Timestamp | 10-05 09:30 [replay-exact]; 10-09 13:59 [prod] |
| Persisted input | 10-09 decision 73: armed 13:59:04 (trend_break BANKNIFTY ≥ 55,316.65), reached and rejected 13:59:22, "no approved plan model" [prod] |
| Engine decision | Replay 09:30: arm `orb` BANKNIFTY at 55,204.64 (expires 09:32) |
| Journal state | No decision row while armed (only when the level is hit) |
| Heartbeat / API | `armed: [orb 55,204.64]`; action "armed: orb: buy on a trade through 55,204.64" |
| Visible UI claim | "**Armed · Opening-range breakout call on BANKNIFTY at 55,204.64**" / "Waiting at the level" (the armed state Phase J could not render) |
| Repro | The armed display is faithful to the engine. That the gate can never authorise it is already MISLEADING (B-06, J-07; now rendered) |

### Point 3: Rejection, and whether the UI exposes its reason

| Item | Value |
|---|---|
| (a) Armed trigger rejected, exact replay 10-05 10:56 | Decision row: "trend_break reached its level 22,465.46 but standing aside: no approved plan model". **Same minute:** the engine re-arms the identical setup (`_fire_armed` clears, `_arm` re-arms from the same read); heartbeat action "armed: trend_break: sell on a trade through 22,465.46", `armed` lists it (expires 10:58). **UI: "Armed · Trend break put on NIFTY at 22,465.46 · Waiting at the level"**; the rejection appears nowhere. Production corroboration: 7 of 22 armed-trigger rejections are followed within 5 min by a read re-armed with the same setup (a lower bound; reads are sampled). **R → K-01** |
| (b) Armed trigger fired and rejected, substituted replay 10-08 09:44 | Decision row: "orb reached its level 22,473.15 but standing aside: no approved plan model". Heartbeat action **"watching: no setup has triggered"**. **UI: "Watching · no setup has triggered"**. Production corroboration: 10-09 decision 73 rejected at 13:59:22, and the next production read at 14:05:04 says "watching: no setup has triggered". **R** (substituted replay; production read consistent) **→ K-02** |
| (c) EV-floor rejection, substituted replay 10-08 11:03 | Decision row: "EV below the floor: … iron_fly EV ₹−510/lot … P(up) 0.49". Heartbeat action carries the reason. **UI: "Passed on a setup: Setup range_sell found but not worth it after costs: … iron_fly with EV ₹−510/lot (−0.04R, P(profit) 0%) at P(up) 0.49 …"**. The reason **is** exposed, with the I-07 P(up) mismatch (the iron fly used 0.5). **R** for the I-07 text carried into the UI; otherwise faithful |
| Wording note | The replay's gate text ("…(the learning loop is off)") differs from production's ("A directional option trade needs a model approved…") because the replay has no learner (B-11). Same gate, same outcome |

### Point 4: 12:20 runner handover

| Item | Value |
|---|---|
| Persisted input [prod, 10-05/08/09] | Morning trading step ended 12:21:12 (10-09 job timings); "handed over at 12:20 with 0 open position(s)" stamped 12:21:04. Afternoon job started 12:21:37, trading step 12:22:15. "grading failed" at 12:22:19–29 (A-02); afternoon session events back-dated 09:15 (A-13). Thoughts gap 6–7 min. `equity` rows at 12:20:04 and 12:25:04, ₹5.00 L both |
| Engine | Replay [replay-exact 10-05]: 12:20 persist and stop. Fresh engine at 12:21: `last_action {}`, `armed {}` (B-04), heartbeat still 12:20 until its first step. Production 10-09: BANKNIFTY armed at 12:18 and re-armed at 12:23 from the new read |
| Heartbeat / API | 12:20 (morning) → unchanged at restore → 12:21 after the first step; equity identical across all three |
| Visible UI claim | 12:20:30 "Live 12:20 · Watching"; 12:21:20 "Live 12:20" (restored); 12:21:40 "Live 12:21" |
| Repro | **NR**: no false stale state, no jump in account figures, stance consistent. Armed loss (B-04) is not visible as a discrepancy, because the read re-arms. Control **V-K1** |

### Point 5: Session close and last displayed state

| Item | Value |
|---|---|
| Persisted input [prod] | Last heartbeat **15:30:04**; `equity` 15:30:04 ₹5.00 L; review and LLM line 15:31:04; afternoon step ended 15:31:11 |
| Engine | Replay: `end_session` (square-off, review); the heartbeat is not rewritten after it |
| Visible UI claim | **[prod-render] 15:44: "Live 15:30"**; 15:31:30 replay: "Live 15:30" after `end_session`. At 20:00: "Closed · opens tomorrow 09:15", with the Now line still "Standing aside · a no-trade flag is up 15:30" |
| Repro | **R**: "Live" for up to 15 min after the session has ended → **K-04**. The stale Now line after close is J-11-like (cosmetic) |

### Point 6: Publishing / `data.json` outage and recovery

Method: real snapshots A = 12:20 and B = 12:21 (10-05 replay) served via request interception; fake clock.

| Item | Value |
|---|---|
| Steps | (1) A served: "Live 12:20". (2) HTTP 503 for 70 s: **"Offline 05 Oct, 12:20"** + banner "Offline. Showing the last saved state from 05 Oct, 12:20; data may be stale…". (3) 130 s: same. (4) B served: "**Live 12:21**", banner cleared. **Stuck publish** (A reachable, never updated, 16 min): "**Stale 17 min**" + the hand-over banner |
| Repro | Outage handling: a control (**V-K2**). Minor: a server-side 503 is labelled "Offline" although the device is online → **K-06**. The stuck case reproduces J-11 |
| Untestable | The real GitHub Pages deploy latency and failure modes (no network calls by design) |

### Point 7: Trade-detail explanation (synthetic entered-and-closed trade)

| Item | Value |
|---|---|
| Fixture [synth-subst] | Synthetic 09-11, with `require_approved_model: false` in the scratch config only. The engine took 3 trades by its own path |
| Trade | ORB long put NIFTY: armed 09:32, triggered 09:33 at 25,644.12, premium target hit 11:07, **+₹20,343, +1.97R, grade A**; fills 260 @ 132.21 → 211.10, fees ₹168 |
| Persisted | `trades.rationale` (trigger, read, thesis, structure, EV, P(up) source), `context`, `meta` (**`quote_source: "model"`, `fill_quotes: "option chain"`, `exit_quotes: "marked"`**), fills |
| UI "Why this trade" sheet | Rationale verbatim; market read; sizing ("risk budget ₹12,045 … 4 lots, binding: risk"); exit; review; lessons; fills table; "NET P&L, AFTER COSTS +₹20,343"; P(up) labelled "[prior tilt … (unvalidated)]". **No indication the quotes and fills were modelled** (`meta.fill_quotes` itself says "option chain") |
| Repro | Explanation faithful to the journal (control **V-K3**). The model-quote omission is **R** (synthetic) → **K-05** |

---

## K3. Discrepancy classification

| # | Discrepancy | Class | Evidence class |
|---|---|---|---|
| 1 | A trigger rejected by the gate is re-armed at the same level in the same minute; the UI shows "Waiting at the level"; the rejection is invisible | **Reproduced** | replay-exact + prod (7/22 lower bound) |
| 2 | A trigger that fired and was rejected is shown as "no setup has triggered" | **Reproduced** (substituted replay); production read consistent | replay-subst + prod |
| 3 | EV rejection text shows a P(up) the EV did not use (I-07) | **Reproduced** in the UI | replay-subst |
| 4 | "Stale … min" plus a hand-over explanation at every session open, until the first fresh publish | **Partially reproduced** (window length inferred; Pages latency untestable) | prod-render + code |
| 5 | "Live" for up to 15 min after the session ended | **Reproduced** | prod-render + replay |
| 6 | Handover shows a false or stale state, or jumps account figures | **Not reproduced** | replay-exact + prod |
| 7 | Outage not flagged, or not recovered | **Not reproduced** (handled). Minor: 503 labelled "Offline" (reproduced) | synth (real snapshots, fake server) |
| 8 | Stuck publish explained as a hand-over (J-11) | **Reproduced** | as above |
| 9 | Trade on modelled quotes shown with no "modelled" label; `fill_quotes` says "option chain" | **Reproduced** (synthetic) | synth-subst |
| 10 | A production profitable/trading session's UI | **Untestable** (none exists) | — |
| 11 | Production heartbeat and UI at any past minute | **Untestable** (heartbeat overwritten; the gh-pages copy holds only 12:46) | — |
| 12 | Zero-trade cause on all 5 sessions = the plan-model gate (22/22 triggers) plus the EV floor; no-trade learning never graded them | **Reproduced** (confirms B-02, D-05) | prod |

---

## K4. Proposed findings (not in the register)

### K-01: A trigger rejected by the gate is re-armed at the same level within the same minute, so the UI keeps showing "Waiting at the level" for a level that was just reached and refused

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **MISLEADING** (reproduced) |
| UI location | Desk "Now" ("Armed · …"), "Waiting at the level" group, Desk log |
| Engine source | `engine._fire_armed` (`engine.py:455`; clears `armed[u]` at `:465`, then rejects via `_blocked` or the gates) then `_arm` (`engine.py:441-453`) re-arms from the same read each minute; heartbeat `armed` and `action` |
| Evidence | Exact replay 10-05 10:56: decision "trend_break reached its level 22,465.46 … no approved plan model" plus heartbeat "armed: trend_break … 22,465.46" plus render `focus_k1005_03_armed_rejected_now.png`. Production: 7 of 22 rejections followed within 5 min by a read re-armed with the same setup. Probes `test_rejected_trigger_is_rearmed_in_the_same_minute_exact_replay` (re-executes the replay), `test_rearm_rendered_as_waiting_at_the_level` |
| Relation | B-06, J-07 (armed while unauthorisable), B-09 (repeated re-fires), J-08 (reasons hidden) |
| Uncertainty | Production heartbeats at those minutes are not persisted; the production count is a lower bound from sampled reads |
| Acceptance | After a gate rejection, the same setup/level is not re-armed for the rest of that read (or is shown as "rejected: *gate*"); the Desk shows the last rejection and its gate for ≥ 5 min. A replay test on 10-05 asserts that at 10:56 the heartbeat shows the rejection, not "armed" |

### K-02: A trigger that fired and was rejected is reported as "no setup has triggered"

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **MISLEADING** (reproduced on a substituted replay; production read consistent) |
| UI location | Desk "Now" ("Watching · no setup has triggered"), Desk log |
| Engine source | When `_fire_armed` rejects and `_arm` doesn't re-arm, the minute's action falls back to `_maybe_enter`'s "watching: no setup has triggered" (`engine.py:736-737`) |
| Evidence | Replay 10-08 09:44 (`k1008_03_*`); production 10-09: decision 73 at 13:59:22, next read 14:05:04 "watching: no setup has triggered". Probe `test_fired_and_rejected_trigger_shown_as_no_setup_triggered` |
| Uncertainty | The production minute itself is not persisted (heartbeat overwritten) |
| Acceptance | The minute's action reports the trigger and its rejection; "no setup has triggered" never appears in a minute with a decision row for that symbol. Replay test on 10-08 09:44 |

### K-03: The published site shows "Stale … min" (and blames a hand-over) at the start of every session, until the first fresh publish

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **PARTIALLY REPRODUCED** |
| UI location | Status pill and Desk banner, 09:15 → first fresh publish |
| Source | `deploy/run-session.sh` (publish at engine start ~08:31, then every 6 min); first heartbeat 09:16; `app.js:258` (stale if age > 900 s in session); banner text `app.js:328` |
| Evidence | `prod_open_1012_091700_*` [prod-render]: "Stale 3947 min" plus the hand-over banner; 09:05: correctly "Closed · opens today 09:15". Probe `test_open_shows_stale_until_the_first_fresh_publish` |
| Uncertainty | Window length (~4–6 min) inferred from the cadence; the real Pages deploy latency is unmeasured; it is longer after weekends and holidays |
| Relation | J-11 (banner cause text) |
| Acceptance | Between 09:15 and the first heartbeat of the day, the UI shows "Starting · first read at ~09:16" (not "Stale"). A clock-advanced render test at 09:15–09:20 with the previous day's `data.json` asserts it |

### K-04: The status pill reads "Live" for up to 15 minutes after the session has ended

| Field | Value |
|---|---|
| Severity | **P4** |
| Status | **MISLEADING** (reproduced on production data) |
| UI location | Status pill |
| Source | `app.js:258-269`: "Closed" is chosen only when stale; a fresh heartbeat after 15:30 still yields "Live" |
| Evidence | `prod_close_1544_*` [prod-render]: "Live 15:30" at 15:44; replay after `end_session` at 15:31:30 the same. Probe `test_status_reads_live_after_the_close_on_production_data` |
| Acceptance | After 15:30 IST (or once the heartbeat carries `ended: true`), the pill reads "Closed". A render test at 15:31 and 15:44 |

### K-05: A trade made on modelled quotes is presented as a market result; its own record labels the fills "option chain"

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **MISLEADING** (reproduced on a synthetic trade with a documented gate substitution; production has no trades) |
| UI location | Trades → History row, and the "Why this trade" sheet ("NET P&L, AFTER COSTS"), Fills table |
| Source | `engine._open` sets `meta.fill_quotes` to "option chain" unless a live book quoted every leg (`engine.py:1176`) although `quote_source` is "model"; the sheet doesn't render `quote_source` |
| Evidence | `phase_k_trade_fixture.json` (`quote_source: "model"`, `fill_quotes: "option chain"`, `exit_quotes: "marked"`); `trade_orb_sheet.png`. Probe `test_trade_on_model_quotes_is_not_labelled_in_the_trade_sheet` |
| Relation | F-01, J-10 |
| Acceptance | `fill_quotes` names the actual source (`model` / `recorded` / `live book`); the sheet and history row badge model-priced trades ("modelled quotes"). Test on the synthetic fixture |

### K-06: A server-side outage is labelled "Offline"

| Field | Value |
|---|---|
| Severity | **P4** |
| Status | **PARTIAL** (the outage itself is flagged correctly) |
| UI location | Status pill and banner during a `data.json` failure |
| Source | `export_site.LIVE_SHIM` sets `QD_OFFLINE_CACHE = true` on any fetch failure; `app.js:260-263` |
| Evidence | `outage_k1005_log.json` step 2: HTTP 503 → "Offline 05 Oct, 12:20" |
| Acceptance | A non-2xx response from the host yields "Site not updating (HTTP 503)"; "Offline" is reserved for `navigator.onLine === false`. Render test with an intercepted 503 |

---

## K5. Controls verified (proposed)

| ID | Control | Evidence |
|---|---|---|
| V-K1 | The 12:20 handover keeps account figures continuous and the stance consistent; the UI stays "Live" through it | `phase_k_timeline_2026-10-05.json` points 05–07; renders `k1005_05/06/07_*`; production `equity` 12:20:04 → 12:25:04 |
| V-K2 | A `data.json` outage is flagged ("Offline … showing the last saved state … may be stale") and recovers automatically when data returns | `outage_k1005_log.json`; probe |
| V-K3 | The trade-detail sheet reproduces the persisted rationale verbatim, with sizing, exit, review and fills that match the journal (R, fees, lots) | `trade_orb_text.json` vs `phase_k_trade_fixture.json`; probe |
| V-K4 | Pre-open, the site states "Market closed · next session today 09:15 … Showing its last state from 09 Oct, 15:30" | `prod_open_1012_090500_*` |

---

## K6. Follow-up tests (one per reproduced discrepancy)

| Discrepancy | Follow-up test |
|---|---|
| K-01 (re-arm after rejection) | Replay 10-05 to 10:56 (as the probe); after a fix, assert heartbeat ≠ "armed" for the rejected level, and that the Desk shows the gate for ≥ 5 min. Extend to all 22 production rejections once their days are replayable (I-04) |
| K-02 ("no setup has triggered") | Replay 10-08 09:44; assert no minute has both a decision row and "no setup has triggered" for that symbol, across 5 replayed sessions |
| K-03 (stale at open) | Clock-advanced render at 09:15, 09:16, 09:18 and 09:20 with the previous day's `data.json`, then with the first fresh one; measure the real Pages deploy lag from gh-pages commit time vs Pages build time (needs Pages API access, owner-side) |
| K-04 (Live after close) | Render at 15:29, 15:31 and 15:44 on the 10-09 close data; assert "Closed" after 15:30 |
| I-07 in the UI (EV P(up)) | After the I-07 fix, render 10-08 11:03; assert the displayed P(up) equals `context.ev.p_up` |
| K-05 (model quotes) | Synthetic fixture; assert the "modelled quotes" badge and a correct `fill_quotes` |
| K-06 (503 = Offline) | Intercepted 503 render; assert the wording |
| J-11 (stuck-publish banner) | Stuck-publish render at +16 min; assert the banner names "site not updated", not a hand-over |
| Session forensics | After I-04's inputs are persisted, re-run `phase_k_sessions.py` plus an exact replay per session type and compare decisions minute for minute |

---

## K7. Limitations

| Production evidence (used as such) | Synthetic or substituted evidence (labelled) |
|---|---|
| Journal copies (thoughts sampled ~2–3 min, decisions, events, `equity` every 5 min, news), recorded bars, `chains-2026` archives, GitHub run and job timings, `memory.json` | **Replays** use the repo's replay wiring: news, brain, breadth, learner and research priors are absent (not persisted) |
| The gh-pages copy (12:46 only) | 10-08 uses Phase I's VIX substitution |
| — | The trade fixture relaxes `require_approved_model` in a scratch config and uses the model chain |
| — | Outage tests serve real replay snapshots through intercepted requests with a fake clock |

**Further limitations:**
- **Never observed live:** any production screen at any minute. Every UI capture is a local render.
- Production heartbeats are overwritten (only 12:46 and 15:30 survive), so per-minute production UI states are
  reconstructed, not recovered.
- Thoughts are sampled, so production corroboration counts (e.g. 7/22) are lower bounds.
- Counterfactuals: 1 lot, touch-to-touch, fees only where recorded, re-fires overlapping, one day each. Not evidence of
  edge.
- No GitHub Pages latency or availability measurement (no network calls to Pages).

---

## K8. Tests and artifacts

**Executed:**
- **`audit/probes/test_phase_k_probes.py`**: **10 passed in 9.12 s** (log `audit/data/phase_k_probe_run.txt`). One
  probe re-executes the exact 10-05 replay to 10:56.
  - The first run had 1 failure, a whitespace bug **in the probe** ("Live\n15:30"). Fixed, and the probe was re-run.
- **Session reconstruction** (`phase_k_sessions.py`) and **production point extraction** (`phase_k_prod_points.py`).
- **Two timeline replays**: 10-05 exact (8 points captured; no EV rejection occurred in this replay) and 10-08
  substituted (9 points).
- **Renders**:
  - 10-05: 8 points;
  - 10-08: 2 rejection points;
  - production data at 09:05, 09:17 and 15:44;
  - outage and stuck scenarios (6 steps);
  - the trade sheet and history.
  - 41 files in `audit/data/phase_k_screens/`.

**New files (all untracked):**
- `audit/QUANTDESK_PHASE_K_SESSION_FORENSICS.md`
- `audit/probes/`: `test_phase_k_probes.py`, `phase_k_sessions.py`, `phase_k_prod_points.py`, `phase_k_timeline.py`,
  `phase_k_outage.py`, `phase_k_trade_fixture.py`, `phase_k_trade_sheet.py`
- `audit/data/`: `phase_k_sessions.json`, `phase_k_prod_points.json`, `phase_k_timeline_2026-10-05.json`,
  `phase_k_timeline_2026-10-08_vix_substituted.json`, `phase_k_trade_fixture.json`, `phase_k_probe_run.txt`
- `audit/data/phase_k_screens/` (41 files)

---

## K9. Handoffs to Phase L (listed only; not started)

- Attack K-01/K-02 across every replayable minute: no minute may carry both a decision row and a contradicting action.
- Test the "learning" claims against the VIX multiplier drift (fabricated input, I-01).
- Check whether any other factor learns from an invalid series.
- Verify the I-10 correction against the scheduler record (H1).
- Pages latency (owner-side measurement).

---

## K10. Recommendation

1. **Accept Phase K for review.**
   - Six protocol session types are covered: five from production, plus trading via a labelled synthetic fixture.
   - All seven timeline points are recorded with classified discrepancies.
   - Findings and controls are proposed separately; corrections to I-10 and J-05 are proposed, not applied.
2. **For remediation planning:** K-01/K-02 (rejected triggers shown as waiting, or as never triggered) and K-05
   (modelled-quote trades shown as market results) belong with J-07/J-08/J-10 in one "decision visibility" group.
   K-03/K-04/K-06 and J-11 belong in one "status truthfulness" group.
3. **Phase L** should not start without a separate approval.
