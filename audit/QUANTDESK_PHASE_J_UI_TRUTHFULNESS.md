# QuantDesk: UI Truthfulness (Phase J)

Read-only forensic audit, Phase J of the master protocol.

**Status: Phase J complete, awaiting review.** Local and uncommitted.

**Proposals are kept out of the canonical register.**
- The proposed findings (**J-01 … J-11**) and controls (**V-J1 … V-J6**) are **not** in the canonical register.
- They are proposals, alongside the pending H and I proposals.

**What was not touched:**
- no production code, UI, configuration, workflow, schedule, permission or account state;
- not the engineer's session;
- nothing committed or pushed;
- no broker, credential or network service used.

**How the UI was rendered.**
- Headless Chromium (the pre-installed browser, via Playwright installed in a scratch venv) served a local folder on
  127.0.0.1.
- The data came from copies of production artifacts, or from journals the engine itself wrote in synthetic temp-dir
  sessions.
- **Every UI observation below was rendered and captured** (screenshot plus visible text), unless it is marked [code]
  (code reading only).
- Phase K has not been started.

---

## J0. Objective, scope, method

### Protocol (§ Phase J)

Audit these UI claims against backend behaviour:
1. learning
2. learned ×
3. factor weights
4. IC
5. champion
6. challenger
7. probation
8. research drift
9. standing aside
10. no-trade reasons
11. model status
12. Brain
13. technical indicators
14. global intelligence
15. opportunity status

Each is classified BACKEND-REAL / DISPLAY-ONLY / PARTIAL / MISLEADING.

### The owner's classification, mapped to the protocol's

| Owner's class | Protocol's class |
|---|---|
| Accurate and backend-supported | **BACKEND-REAL** |
| Partially supported | **PARTIAL** |
| Display-only | **DISPLAY-ONLY** |
| Misleading or contradicted | **MISLEADING** |
| Unverifiable from available evidence | **UNVERIFIABLE** |

### The UI under audit

| Surface | What it is | Code |
|---|---|---|
| The app (PWA): Desk · Chart · Trades · Brain · Feed | One page plus `app.js`, 1,551 lines | `quantdesk/web/static/app/index.html`, `app.js` |
| Data API | `/api/i/*`: state (the heartbeat), thoughts, news, trades, stats, chart | `quantdesk/web/intraday_api.py` |
| Published site (GitHub Pages) | The same app plus a shim answering `/api/i/*` from `data.json`, re-published by `live.yml` | `quantdesk/web/export_site.py` (`publish_site`, `site_data`) |

- The heartbeat (`state.intraday_live`, written by `engine._heartbeat`, `engine.py:1279-1325`) carries most of what
  the screens show:
  - per index: view, evidence (+ `learned`), quant, brain, chain, breadth;
  - `learning`, `autolearn`, `halts`, `health`, `positions`, `armed`, `global`.
- **The deployed site runs this exact app.** The gh-pages copy (`4f13bd26`, heartbeat 10-09 12:46) has an `app.js`
  byte-identical to the repo's (SHA-256 `5b021c63…`).

### Evidence sources and renders

All in `audit/data/phase_j_screens/`.

| Source | How built | Clock (IST) | Files |
|---|---|---|---|
| **Deployed gh-pages copy** (production) | as deployed | 10-09 12:46:30 | `deployed_1246_*`, `focus_deployed_vix_evidence.png` |
| **Production close snapshot** (journal copy, 10-09 16:15) | `phase_j_site.py` → `publish_site` | 10-09 15:29:30 | `prod_1529_*` (6 tabs), `focus_prod_*` |
| Same, viewed on a later trading morning | as above | 10-12 10:00 | `prod_stale_mon1000_*`, `focus_prod_stale_banner.png` |
| Entry crash (orphan leg): the engine's own journal from Phase I's `phase_i_evidence.entry_crash` | `phase_j_site.py` | 09-29 15:29:30 | `fx_8a_*`, `focus_fx_8a_*` |
| Exit crash (naked short): from `exit_crash` | as above | 09-29 15:29:30 | `fx_8b_*`, `focus_fx_8b_*` |
| Safe mode: `phase_j_site.py --make safe` (engine's `enter_safe_mode`) | as above | 09-29 10:40:30 | `fx_safe_*`, `focus_fx_safe_*` |
| Kill switch: `--make kill` (engine's file kill switch) | as above | 09-29 10:40:30 | `fx_kill_*`, `focus_fx_kill_*` |

**One fixture adjustment, documented.**
- Synthetic journals lack the `intraday_account` record that production's `ensure_account` always writes.
- Without it, `IntradayAPI.pending_capital` replaces cash and equity with the configured capital.
- `phase_j_site.py` adds the record to the **copy** exactly as production writes it.
- No UI state is hand-made: every halt, equity figure and action shown was written by the engine.

---

## J-matrix. The 15 required claims

**Classification codes:** BR = BACKEND-REAL · P = PARTIAL · DO = DISPLAY-ONLY · M = MISLEADING · U = UNVERIFIABLE.

| # | Claim | Where shown (exact) | Displayed (observed) | Backend source | Class | Evidence | Finding |
|---|---|---|---|---|---|---|---|
| 1 | **Learning** | Brain → "What the desk has learned · *N* sessions graded"; Chart and Brain evidence "Track record · …" | "10 sessions graded"; buyer's edge 0.67×; factor IC table; probation list | `engine._learning_view` (`engine.py:1327-1343`) from `memory.json`; "sessions" = `len(memory.days)` | **M** | Rendered `focus_prod_learned.png`. Memory days include the bootstrap replays 09-24/25/28 and the pre-reset 09-29 … 10-01 (D-03). Factor learning is indistinguishable from noise (D-01, P1), with a negligible effect on decisions (D-02). 10 "grading failed" WARNs are not shown (A-02/D-07) | **J-05** |
| 2 | **Learned ×** | Evidence rows: tag "learned ×*m*" (`app.js:685`); "Track record · Global crude ×1.18 …" (`app.js:666`) | e.g. "ORB learned ×1.07", "**VIX learned ×0.95 · +1.00 · India VIX 0.00 (−100.0% today)**" | `analyst.learned` (memory reliability), applied to the weight | **M** | The multiplier is real and applied (V-I1), but presented as learned knowledge: D-01 (placebo p = 0.70) and the VIX multiplier is learned on a fabricated input (I-01) | **J-05**, **J-01** |
| 3 | **Factor weights** | Evidence rows: weight column and bar ("What's pushing the bias", Chart → Evidence) | e.g. ORB 1.07, VWAP 1.02, VIX 0.29 | Heartbeat `views[u].evidence[].weight` = the analyst's weights | **BR** | The displayed weight and direction are exactly those used; every production read's score recomputes from them (V-I1, 743/743) | (V-J4) |
| 4 | **IC** | Brain → "Factor IC by horizon"; "IC, last 30 → next 30 min +0.031 · t +0.3 · Not used yet" | IC per factor × {5, 15, 30, 60} min, coloured at \|t\| ≥ 2 | `learning.grade_ic` / `ic_table` (`learning.py:212-259`): weighted correlation, overlap weight min(1, 5/h) | **P** | The arithmetic is real. Not shown: no multiplicity control across 12 factors × 4 horizons (colouring implies significance); records mix bootstrap and live (D-03); D-01 | J-05 |
| 5 | **Champion** | Brain → Model lifecycle "Champion: none yet · session model" | "none yet · session model" | `autolearn.status()`; `registry/state.json` (empty) | **BR** | Matches the persisted registry (V-I7) | (V-J5) |
| 6 | **Challenger** | Model lifecycle "Challengers in shadow: none" | "none" | same | **BR** | as above | (V-J5) |
| 7 | **Probation** | Evidence rows tagged "probation" (weight 0); Brain "On probation: graded live, no vote yet · *n* of 30 graded · ×rel"; Brain "The wiring, measured" → Status "Probation" | e.g. "Crude (Brent) … Probation" | `analyst.PROBATION`/`graduated`; `brain._probation_weight` (`brain.py:408-410`); research links' `validated` | **P** | Graduation mechanics are real and reversible (V-19). But graduation happens on noise (D-01: 78 % of noise draws graduate). **"Probation" has two meanings**: a research link shown as "Probation" can still vote (global_crude, J-06) | J-06 |
| 8 | **Research drift** | Chart → Quant "Research drift −5.7 bps/day · t −3.4"; evidence "research … holds out of sample"; glossary "quant": "only count when they survive a holdout" | as shown | `research/edges.py` priors → `qstate.research_drift` → EV and the `research` factor | **P** | The number is real and decision-affecting (EV), sign replicated on official data (V-26). But it enters every live EV without a registered study (E-03); "survives a holdout" overstates E-04/E-05 | (E-03, cited) |
| 9 | **Standing aside** | Desk "Now": "Standing aside · a no-trade flag is up" + per-index reason; glossary "Why stand aside?" | "NIFTY Standing aside: Outside entry window 09:20–14:45" | Engine action text (`last_action`), parsed by `readAction` (`app.js:134-143`) | **P** | Reasons are the engine's own (231 of 743 production reads). The **glossary omits the three most common production reasons** (entry window 79, no approved plan model 39, scheduled event 27). Engine **halts** ("halted: …") are not classed as standing aside and fall to "Reading the market every minute" (J-03) | J-08, J-03 |
| 10 | **No-trade reasons** | Desk "Now", Feed → Desk log (sampled reads), Chart "Doing now" | e.g. "Standing aside: No approved plan model. A directional option trade needs a model…" | Thought actions (sampled, ≈ every 2–3 min) | **P** | The journal's **73 rejection decisions (EV, P(up), plan legs) are not served by any UI endpoint** (no `decisions` in `intraday_api.py` or `app.js`). Confirm-path gates are not journaled (B-03) | J-08 |
| 11 | **Model status** | Chart → Quant "Direction model Off · AUC 0.50", "P(up) used: coin flip + prior"; Brain lifecycle "recording only", "Directional entries: none: no approved plan model", "Real point-in-time evidence: 5 session(s) · 6902 plans · nothing approved", "Modelled chains … scenario analysis only" | as shown | `qstate`, `autolearn.status()`, `plan_research` | **BR** | Matches the backend (B-02, V-11, V-16); modelled-chain research labelled "scenario analysis only" | (V-J5) |
| 12 | **Brain** | Brain tab: Global regime ("Mixed · Score −0.17 · Global stress 0.7σ · Full size"), influence graph, flows, learning, lifecycle, markets board, wiring table | as shown | `brain.think` → `_brain_view`; the graph aggregates the read's own evidence by category | **P** | Regime, stress and graph are computed from real inputs. **"Above 2σ the desk cuts position size, down to half"** / "Full size" describes a control that can't bind (Q-07: applied after EV, which no plan passes). The regime glossary is contradicted (J-06) | J-06 |
| 13 | **Technical indicators** | Evidence rows (ORB, VWAP, EMA, Supertrend, CPR, RSI…); Chart levels chips and "Key levels" (PDH/PDL, OR, IB, CPR, VA, POC) | e.g. "CPR 22,284.43–22,389.68", chart PDH/PDL | Evidence = the engine's analyst; **chart levels are recomputed by the API from recorded bars** (`intraday_api._bar_levels`) | **P** | Evidence rows are exact (V-I1). Chart levels can disagree with the engine's: 10-05 chart PDL **22,616.60** vs engine **22,217.65** (prior day 10-01 unrecorded, I-10; the chart's "prior day" is 09-30's 10 bars) | **J-09** |
| 14 | **Global intelligence** | Desk "Global" strip; Brain "Global markets" board, "The wiring, measured" table; glossary "regime" | "only links the weekly research has validated on real data actually vote in the bias"; all 9 drivers "Probation" | `GlobalFeed` (Yahoo, 15-min `live` guard, V-H7); `brain._probation_weight` | **P** | Market data is real and staleness-labelled ("since 09:15" vs "last session"). **Contradicted:** `global_crude` carries vote weight in **194 of 501** production reads although the Crude link is not validated (shown "Probation") | **J-06** |
| 15 | **Opportunity status** | Desk "Waiting at the level" group, "Armed" tag, "Now: Armed · …"; Desk log "Waiting at the level: …" | e.g. "Armed · Trend break call on BANKNIFTY at 55,316.65" | `engine._arm` → `armed`; action "armed: …" → `readAction` "Waiting at the level" | **M** | **86 of 743** production reads carried "armed: …", which the app labels "Waiting at the level", while no directional entry could be authorised (B-02; all 22 armed triggers that reached their level were rejected "no approved plan model"). Settled B-06, confirmed on production data. Not rendered in this phase: no armed state was live at either render time | **J-07** |

**Totals:** BACKEND-REAL 4 (3, 5, 6, 11) · PARTIAL 8 (4, 7, 8, 9, 10, 12, 13, 14) · MISLEADING 3 (1, 2, 15) ·
DISPLAY-ONLY 0 · UNVERIFIABLE 0.

---

## J1. Owner-specified investigations

| Topic | What the UI shows (observed) | Verdict | Finding / control |
|---|---|---|---|
| **India VIX zero / −100 %** | Brain "What's pushing the bias": **"VIX · Volatility · learned ×0.95 · 0.29 · +1.00 · India VIX 0.00 (−100.0% today)"** with a green bullish bar. Same on the **deployed** site (12:46). No warning anywhere | MISLEADING | **J-01** |
| **Stale or substituted data provenance** | The Desk "Markets" hint shows the feed aggregate "kotak+yahoo (5 of 564 polls from Yahoo)" (which minutes: unknown, A-04). Model-chain fallback is disclosed in Quant: "No live option chain: priced off India VIX…" (rendered on the synthetic fixture), but max pain and dealer gamma from modelled OI still render (F-01). VIX validity: not checked (J-01). Global board: "since 09:15 IST" vs "last session" labels (V-H7) | PARTIAL | V-J2, J-01 |
| **Broker/journal disagreement, orphans** | Entry crash: **₹4.84 L, "Today −₹16,095", Open 0**, Trades "Flat: no open positions", Brain "Halts: none", pill "Live". Exit crash: **₹5.13 L, "Today +₹13,440", All-time −₹597, Open 0, "Flat: no open positions"**; the broker holds a naked −65 call | MISLEADING | **J-02**, **J-03** |
| **Safe mode** | "Now": "**Reading the market every minute**", per-index "Halted: safe mode (…)"; Brain "Halts: none"; pill "Live" | MISLEADING | **J-03** |
| **Kill switch** | Brain "Halts: kill switch · Entries are halted: kill switch."; per-index "Halted: kill switch (KILL) is set" | BACKEND-REAL (the headline is still generic) | V-J3 (+ J-03 headline) |
| **Heartbeat age / stale session** | Production data viewed at 10-12 10:00: pill **"Stale 3990 min"**, banner "The desk hasn't reported for 3990 min · showing 15:30. *It hands over to a fresh runner at 12:20, and a restart takes a few minutes…*". "Now" still shows 10-09's stance | Staleness flagged (control); cause text wrong; old stance as current | V-J1, **J-11** |
| **Equity, cash, positions, trade status when records disagree** | Equity = the engine's `cash + Σ marks of journal open trades` (`engine.py:183-188`); positions = `open_trades` (`engine.py:1294-1310`). The broker's positions are never shown | MISLEADING under disagreement | **J-02** |
| **News timestamps** | Feed age = `ago(r.ts)` (publish time, `app.js:1382`); `seen_at` is never displayed. A story first recorded 10-08 13:40 renders as "WSJ · **2 h ago**" on 10-09 15:29 (its `ts` was rewritten, I-02). Lost LLM reads (34 rows) are simply absent | MISLEADING | **J-04** |
| **Replayability, model provenance, learning, immutability** | **No replayability or immutability claim exists** in `app.js` or `index.html` (searched: "replay" appears only in a CLI hint; no "never edited" or "immutable"). Model provenance: lifecycle and Quant show model status but no model ID, commit or version (I-03); LLM reads shown as "Gemini 0.00" with no model ID (G-04). Learning: J-05 | No false immutability claim (accurate absence); provenance absent | J-05; I-03 / G-04 cited |
| **Paper vs modelled quotes vs broker evidence** | Footer "Paper trades only… Read-only: nothing here can place an order"; "Paper equity" label; published site has no controls (`renderControls` returns for `QD_PUBLISHED`). Glossary "paper": "simulated against **real** prices and **real** option chains, with **real** costs" (unconditional) | Paper labelled (control); "real chains, real costs" overstated | V-J6, **J-10** |

---

## J2. Proposed findings (not in the register)

Severity scale as in the register: P0 safety/integrity/live · P1 major correctness · P2 important limitation ·
P3 moderate · P4 minor.

### J-01: The zero India VIX is displayed as a valid, "learned", maximally bullish factor, on the deployed site too

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **MISLEADING** (production, rendered) |
| UI location | Brain → "What's pushing the bias" (also Chart → Evidence), row **VIX · Volatility** |
| Displayed claim | "learned ×0.95 · 0.29 · +1.00 · India VIX 0.00 (−100.0% today)", green bullish bar |
| Backend source | `engine._vix_state` → `analyst.py:233-235` → heartbeat `views[u].evidence` (no validity field) |
| Evidence | Rendered on the deployed gh-pages copy (`focus_deployed_vix_evidence.png`, 12:46) and the close snapshot (`focus_prod_vix_evidence.png`). Probe `test_zero_vix_is_served_to_the_ui_as_a_normal_factor` |
| Root cause | The data defect is I-01 (proposed); this finding is about presenting it as valid |
| Acceptance | An invalid series (≤ 0, or a ≥ 50 % one-minute move) is shown as "data invalid", never as a vote, a learned multiplier or a bar. A render test on a zero-VIX fixture finds no "India VIX 0.00" evidence row and finds a data-quality warning |

### J-02: Account equity, P&L and positions show the journal's view; broker-held orphan or naked legs are invisible and phantom P&L is displayed

| Field | Value |
|---|---|
| Severity | **P2** (P0 if any live mode is enabled; same rule as H-01) |
| Status | **MISLEADING (latent)**: rendered on engine-written synthetic crash journals; production has had 0 trades |
| UI location | Desk → Account ("Paper equity", "Today", "Open"); Trades → Positions; Desk "Open position" |
| Displayed claim | Entry crash: "₹4.84 L · Today −₹16,095 −3.22% · Trades 0 · Open 0"; "Flat: no open positions". Exit crash: "₹5.13 L · Today +₹13,440 +2.69% · All-time −₹597 · Open 0"; "Flat: no open positions" |
| Backend source | `engine.equity` (`engine.py:183-188`, broker cash plus marks of **journal** open trades only); heartbeat `positions` (`engine.py:1294-1310`, from `open_trades`); `intraday_api.state` |
| Evidence | `focus_fx_8a_account.png`, `focus_fx_8b_account.png`, `fx_8a_trades.png`, `fx_8b_trades.png`. Probes `test_entry_crash_shows_a_loss_with_no_position`, `test_exit_crash_shows_a_phantom_gain_and_no_naked_short`, `test_positions_and_equity_come_from_the_engine_not_the_broker` |
| Relation | H-01, H-02 (behaviour); I-06 (evidence) |
| Acceptance | Positions are rendered from broker positions with journal attribution. Any leg not in a journal trade is shown as "unattributed position" with its mark. Equity includes all broker positions. A disagreement state disables the P&L headline and shows a red reconciliation banner. Render tests on the 8a and 8b fixtures assert the orphan and short are visible and "Today" P&L is withheld |

### J-03: Safe mode and broker/journal disagreement are not shown as halts; the headline reads "Reading the market every minute" and the pill "Live"

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **MISLEADING** (rendered, engine-written fixtures) |
| UI location | Desk "Now" headline; status pill; Brain → Model lifecycle "Halts" |
| Displayed claim | Headline "Reading the market every minute"; per-index lines "Halted: safe mode (…)" / "Halted: broker and journal disagree (…)"; "Halts: none"; pill "Live" |
| Backend source | Heartbeat `halts.safe_mode` and `halts.reconcile` are present, but the Halts list uses only `kill_switch`, `journal`, `daily_loss` and model fault (`app.js:1252`). `readAction` has no "halted" class (`app.js:134-143`), so the headline falls through to the default (`app.js:482`). The pill ignores halts (`app.js:258-269`) |
| Evidence | `focus_fx_safe_now.png`, `focus_fx_safe_lifecycle.png`, `focus_fx_8a_now.png`, `focus_fx_8a_lifecycle.png`, `focus_fx_8b_*`. Probes `test_halts_fact_omits_safe_mode_and_reconcile`, `test_a_halted_action_has_no_status_class_and_falls_to_the_generic_headline` |
| Contrast | The kill switch **is** listed in Halts (V-J3) |
| Acceptance | Every heartbeat halt (`safe_mode`, `reconcile`, `kill_switch`, `journal`, `daily_loss`) produces a red headline, a pill state other than "Live", and an entry in "Halts". Render tests on the safe, 8a and kill fixtures assert all three |

### J-04: News ages are computed from rewritten publish times; first-seen time and lost LLM reads are not represented

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **MISLEADING** (production, rendered) |
| UI location | Feed → Headlines, Desk → Headlines: "*source* · *N* h ago" |
| Displayed claim | "WSJ (via Google News) · 2 h ago" for a story first recorded 10-08 13:40 |
| Backend source | `newsRow` → `ago(r.ts)` (`app.js:1382`); `news.ts` rewritten by later jobs (I-02); `seen_at` not served or displayed |
| Evidence | `prod_1529_text.json` (feed); I-02 measurements (2 of the 30 rewritten-`ts` rows are among the site's 120 headlines). Probe `test_feed_shows_publish_time_not_first_seen` |
| Acceptance | The Feed shows the immutable first-seen time (and publish time) once I-02 is fixed. A fixture with a re-fetched story renders the original age and its original reads |

### J-05: "What the desk has learned", "learned ×", Track record and IC present noise-level, mixed-provenance statistics as learning

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **MISLEADING** (protocol claims 1 and 2; 4 and 7 partial) |
| UI location | Brain → "What the desk has learned · 10 sessions graded"; evidence "learned ×*m*"; "Track record · …"; "Factor IC by horizon" |
| Displayed claim | Learned multipliers ×0.95 … ×1.18; "10 sessions graded"; IC cells coloured at \|t\| ≥ 2 |
| Backend source | `memory.json` via `_learning_view` and `analyst.learned` |
| Evidence | `focus_prod_learned.png`, `focus_prod_vix_evidence.png`. D-01 (placebo p = 0.70), D-02 (2/2,984 decisions changed), D-03 (bootstrap and pre-reset days in `memory.days`). Probe `test_sessions_graded_counts_bootstrap_and_pre_reset_days`. The VIX ×0.95 is learned on a fabricated input (I-01). A-02's 10 grading failures are not displayed |
| Acceptance | Learned figures carry a statistical label (CI or placebo result) or are relabelled "unvalidated tilt" (consolidation R7). "Sessions graded" counts live sessions separately from bootstrap and replay. IC cells show a multiplicity-adjusted significance. A UI test asserts the labels |

### J-06: Global intelligence: the UI says only validated links vote, but unvalidated drivers vote; the stress size-cut text describes a control that can't bind

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **MISLEADING** (contradicted) |
| UI location | Glossary "Global regime" (Brain "?"); Brain "The wiring, measured" → Status; Brain "Global stress … Full size"; glossary "Global stress" |
| Displayed claim | "only links the weekly research has validated on real data actually vote in the bias"; "Crude (Brent) … Probation"; "Above 2σ the desk cuts position size, down to half" |
| Backend source | `brain._probation_weight` (`brain.py:408-410`: weight 0.25 once n ≥ 30 and rel ≥ 1.15, validated or not); Q-07 (closed in Phase F: the size multiplier is applied after EV, which no plan passes) |
| Evidence | Production: `global_crude` weight > 0 in **194 of 501** reads, while the heartbeat's Crude driver has `validated: false`. Probes `test_unvalidated_global_drivers_vote_while_the_ui_says_only_validated_links_do`, `test_stress_size_cut_is_described_as_active` |
| Acceptance | Glossary and table distinguish "validated", "voting on live record (unvalidated)" and "context only". The stress text says when the cut can apply, or the cut is moved before EV. A test compares the voting factors with the displayed statuses |

### J-07: "Waiting at the level" shown while no entry can be authorised

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **MISLEADING** (settled **B-06**, now quantified on production data) |
| UI location | Desk "Now: Armed · …", "Waiting at the level" group, "Armed" tags; Desk log |
| Displayed claim | "Waiting at the level: …" |
| Backend source | `engine._arm`; `readAction` (`app.js:141`) |
| Evidence | 86 of 743 production reads carried "armed: …"; all 22 armed triggers that reached their level were rejected "no approved plan model" (decisions). **Not rendered this phase**: no armed state was active at the render times; classification rests on production data plus code |
| Acceptance | When the gate can't authorise (no approved model for the setup), the UI shows "Watching (entry gated: no approved model)" instead of "Waiting at the level". A render test on an armed fixture with an empty registry asserts it |

### J-08: No-trade reasons are partial: rejection decisions are never shown, and the "Why stand aside?" text omits the main production reasons

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **PARTIAL** |
| UI location | Desk "Now" → "Why stand aside?"; Desk log |
| Displayed claim | Glossary: "the first minutes after the open, a move too stretched to chase, breaking news, a stale option chain, global stress, or an EV that doesn't clear costs" |
| Backend source | Production reasons (743 reads): outside entry window **79**, breaking news 67 (in the glossary), no approved plan model **39**, scheduled event **27**, first 5 minutes 18 (in the glossary as "the first minutes after the open"). The 73 rejection rows (EV, P(up), plan) are in `decisions`, which no endpoint serves |
| Evidence | Probes `test_rejection_decisions_are_not_served_to_the_ui`, `test_stand_aside_glossary_omits_the_dominant_production_reasons`; B-03 |
| Acceptance | A "Decisions" view lists every rejection with its gate, EV and plan. The glossary lists every gate the engine can return (generated from the engine's gate list). A test compares the gate list with the glossary |

### J-09: Chart levels are recomputed from recorded bars and can contradict the engine's levels

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **MISLEADING** (when a prior day is missing or gappy) |
| UI location | Chart → level chips ("Prior day", "CPR"…), "Key levels" table |
| Displayed claim | PDH/PDL and CPR for 10-05 from 09-30's 10 bars |
| Backend source | `intraday_api._bar_levels` (from `data/<date>` CSVs). The engine's levels are only merged with `setdefault`, so the API's own values win (`intraday_api.py`, chart) |
| Evidence | 10-05: chart PDL **22,616.60** vs engine **22,217.65** (PDH 22,620.45 vs 22,610.55); 10-08 agrees within ~0.4 pt. Probe `test_chart_prior_day_levels_disagree_with_the_engine_after_an_unrecorded_day`. Relates to I-10, A-06 |
| Acceptance | The chart shows the engine's levels (from the thought or heartbeat) for the levels the engine used, or flags a disagreement. A test on 10-05 data shows the engine's PDL |

### J-10: "Paper trading" glossary claims real option chains and real costs unconditionally

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **PARTIAL** |
| UI location | Desk → Account "Paper equity ?" glossary |
| Displayed claim | "Every trade here is simulated against real prices and real option chains, with real costs (brokerage, STT, exchange fees, slippage)" |
| Backend source | The model-chain fallback trades on modelled quotes (F-01); fills ignore depth (F-04); exercise STT differs from statute (F-05) |
| Evidence | Probe `test_paper_glossary_claims_real_chains_and_costs_unconditionally`. The Quant panel does disclose the model-chain case (V-J2) |
| Acceptance | The glossary states when quotes are modelled, and the cost and fill simplifications. A trade made on the model chain is badged "modelled quotes" in Trades |

### J-11: The stale banner explains any staleness as a hand-over, and "Now" shows an old stance as current

| Field | Value |
|---|---|
| Severity | **P4** |
| Status | **PARTIAL** (staleness itself is flagged, V-J1) |
| UI location | Desk banner, "Now" line |
| Displayed claim | "The desk hasn't reported for 3990 min · showing 15:30. It hands over to a fresh runner at 12:20, and a restart takes a few minutes…"; "Now · Standing aside · a no-trade flag is up" |
| Backend source | `app.js:328`; `renderNow` doesn't consult `status.stale` |
| Evidence | `focus_prod_stale_banner.png`, `prod_stale_mon1000_text.json`. Probe `test_stale_banner_blames_a_handover_whatever_the_age` |
| Acceptance | The banner text depends on age and time of day (a missed session is not called a hand-over). "Now" is greyed or labelled with the heartbeat's age when stale |

---

## J3. Controls verified (proposed)

| ID | Control | Evidence |
|---|---|---|
| V-J1 | A stale heartbeat in session is flagged: pill "Stale *N* min" and a warning banner | `prod_stale_mon1000_*` |
| V-J2 | The model-chain fallback is disclosed: "No live option chain: priced off India VIX, so the chain reads above are the model's, not the market's." | `fx_8a_chart_text.json`; probe |
| V-J3 | The file kill switch appears as a halt with an explanation ("Halts: kill switch · Entries are halted: kill switch.") | `focus_fx_kill_lifecycle.png` |
| V-J4 | Displayed factor weights and directions are exactly those the engine used (V-I1) | heartbeat evidence = analyst evidence |
| V-J5 | Champion, challengers, model status and the directional-entry gate are displayed accurately ("none yet", "none", "Off · AUC 0.50", "none: no approved plan model"); modelled-chain research is labelled "scenario analysis only" | `focus_prod_lifecycle.png`, `focus_prod_quant.png` |
| V-J6 | The published site is read-only and labelled paper: no controls (`renderControls` returns for `QD_PUBLISHED`), and the footer "Paper trades only … nothing here can place an order" (consistent with the GET-only edge, Phase H) | `prod_1529_text.json` |

---

## J4. Unresolved questions and recommended follow-up tests

| # | Question | Follow-up (safe) | Phase |
|---|---|---|---|
| 1 | How does an **armed** state render (J-07)? | Fixture: synthetic session with anticipation on, render at an armed minute; assert the label | K / remediation test |
| 2 | Does the 12:20 hand-over show any transient false state (e.g. "Stale", or yesterday's equity)? | Render the morning and afternoon heartbeats around 12:20 on a copy | K |
| 3 | What does the app show if `data.json` publishing stops mid-session (Pages lag)? | Clock-advance test on the published shim (`QD_OFFLINE_CACHE` paths) | K |
| 4 | Is the VIX row the only invalid-data row? | Scan all evidence observations across sessions for 0, NaN or ±100 % values | L |
| 5 | Mobile vs desktop layout differences (`wide-only` groups such as the Desk log) | Render at desktop width | J follow-up |
| 6 | Trade-detail sheet ("Why this trade") truthfulness | Needs a trade; synthetic fixture with an entered and closed trade, render the sheet | K |

---

## J5. Limitations

| Limitation | Effect |
|---|---|
| Production has 0 trades | Trade-related UI (positions, history, calibration, trade sheets) observed only on synthetic, engine-written fixtures |
| Armed state not rendered | J-07 classified from production data plus code, not from a render |
| Renders use a fixed clock and headless Chromium at 430 px width | Desktop-only groups (`wide-only`) were not captured |
| The deployed site was rendered from the Phase A copy of `gh-pages` (10-09 12:46) | Not the live URL (no network calls by design) |
| Fixture adjustment | `intraday_account` added to synthetic copies, exactly as production writes it (§ J0) |
| Production heartbeats are only those in the two copies (12:46, 15:30) | — |

---

## J6. Tests and artifacts

**Executed:**
- **`audit/probes/test_phase_j_probes.py`** with `QD_JOURNAL` = the close copy: **16 passed in 41.54 s**
  (log `audit/data/phase_j_probe_run.txt`).
- **Renders** (headless Chromium via Playwright in the scratchpad venv `uivenv`, `chromium-1194`):
  - production close snapshot (6 tabs);
  - deployed gh-pages copy (2 tabs plus a focus crop);
  - stale view;
  - 4 engine-written fixtures (Desk, Brain, Trades, plus the Chart for 8a);
  - 18 focus crops.
  - All in `audit/data/phase_j_screens/` (48 files: PNG plus visible-text JSON).
- **Other checks:** chart-levels vs engine-levels check; deployed `app.js` hash comparison; global-driver vote count;
  stance counts.

**New files (all untracked):**
- `audit/QUANTDESK_PHASE_J_UI_TRUTHFULNESS.md` (this report)
- `audit/probes/test_phase_j_probes.py`, `phase_j_site.py`, `phase_j_shoot.py`, `phase_j_focus.py`
- `audit/data/phase_j_probe_run.txt`
- `audit/data/phase_j_screens/` (48 files)

---

## J7. Handoffs (listed only; Phase K not started)

| To | Item |
|---|---|
| **K** | Render each representative session's UI at key minutes (open, an armed minute, a rejection, the 12:20 hand-over, close) and compare with § I1's reconstruction; follow-ups 1–3 and 6 |
| **L** | Follow-up 4; attack "display equals decision" for every evidence row; the J-06 label contradictions |

---

## J8. Recommendation

1. **Accept Phase J for review.** All 15 required claims are classified with evidence: 4 BACKEND-REAL, 8 PARTIAL,
   3 MISLEADING. Every owner-specified topic is covered, with rendered evidence where it was safely reproducible.
2. **For remediation planning:** J-01, J-02 and J-03 matter most. The UI currently presents fabricated data as valid
   (J-01) and hides the two failure states Phase H found most dangerous (J-02, J-03).
3. **Phase K** should not start without a separate approval.
