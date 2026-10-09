# QuantDesk: Journal and Auditability (Phase I)

Read-only forensic audit, Phase I of the master protocol.

**Status: Phase I complete, awaiting review.** Local and uncommitted.

**Proposals are kept out of the canonical register.**
- The proposed findings (**I-01 … I-10**) and controls (**V-I1 … V-I7**) are **not** in
  `audit/QUANTDESK_FINDINGS_REGISTER.md`.
- They are proposals for the owner's review, alongside the pending Phase H proposal.

**What was not touched:**
- no production code, configuration, workflow, schedule, permission or account state;
- no journal history, and not the autonomous engineer's session;
- nothing committed or pushed;
- no broker API, credential or live service used.

**How tests were run:**
- Production evidence was read from **copies** of the `journal` branch (SQLite `mode=ro`) and from `chains-2026` release
  assets downloaded earlier in this session.
- Every executed test ran in its own temp directory, on synthetic sessions or on copies of the production artifacts.
- Phase J has not been started.

---

## I0. Objective, scope, baseline

### Protocol (§ Phase I)

> Verify that the system can reconstruct: WHY DID WE TRADE? · WHY DID WE NOT TRADE? · WHAT DID THE SYSTEM KNOW THEN? ·
> WHAT MODEL/FACTOR/NEWS/REGIME INFORMATION WAS USED? · WHAT WOULD HAVE HAPPENED IF WE TRADED? · WHAT DID THE SYSTEM
> LEARN? · Can a historical decision be replayed from persisted evidence alone?

The owner's scope adds six investigation areas:
1. decision reconstruction;
2. journal/broker reconciliation;
3. crash and restart evidence;
4. `model_state` provenance;
5. replay and reproducibility;
6. evidence integrity.

**§8 test 17 (real-session replay)** is required here: it is the protocol's replay question. It was executed on two
recorded sessions (§ I5).

### Baseline

| Item | Value |
|---|---|
| Repo HEAD | `8138494` (unchanged). The working tree has only untracked audit files |
| Code that produced the evidence | `main` = `c96909f`: every live run 10-05 … 10-09 has `head_sha c96909f` (GitHub run metadata) |
| Journal snapshots (copies) | `ecd03156` (12:20 IST handover, 10-09), called **PREV**; `0143b5c` (16:15 IST close, 10-09), called **CLOSE** |
| Chain archive | `chains-2026` release. The full asset list was read: 86 assets (34 bars, 20 gift, 20 tape, 12 chains). 9 chain files were already downloaded (10-05 … 10-08 morning and afternoon; 10-09 morning) |
| Python | the scratchpad venv (Python 3.13.16, pandas 3.0.6, numpy 2.5.3) |

**Evidence tags:**

| Tag | Meaning |
|---|---|
| [prod] | Production record (journal copies, release assets, GitHub metadata) |
| [prod-replay] | The engine run in a temp dir on copies of production artifacts |
| [synth] | Synthetic session in a temp dir |
| [code] | Code reading with file:line |
| [infer] | Inference, not executed |

### Persisted-evidence inventory (what exists to reconstruct from)

| Store | Content | Mutability | Where |
|---|---|---|---|
| `journal.db` → `thoughts` | Sampled analyst reads (≈ every 2–3 min or on a bias flip): bias, score, conviction, **every factor's direction, weight and observation**, levels, a chain summary | Append-only in practice | journal branch |
| `decisions` | **Rejections only** (73 in production): free-text gate, plus `context` = `plan` text (legs, prices, IV, Δ) and `ev` or `armed` | Append-only in practice | journal branch |
| `trades`, `fills` | 0 in production since the 10-05 reset | `INSERT OR REPLACE` / `UPDATE` (trades); `UPDATE` by `restate_trade` (fills) | journal branch |
| `events` | Session, model-fit text, LLM cost lines, WARN/CRITICAL | Append-only in practice | journal branch |
| `news` | Headline, publish `ts`, `seen_at`, rules sentiment, `nlp` (LLM reads with `at`) | **`INSERT OR REPLACE` + `UPDATE nlp`** | journal branch |
| `equity`, `state` | Snapshots; `state` = current heartbeat, account, resume state | Overwritten | journal branch |
| `memory.json` | Aggregate factor and reader statistics (D-03) | Overwritten | journal branch |
| `autolearn/*` | Registries (both empty: no champion ever), cycles, datasets, plan studies | Overwritten (A-10) | journal branch |
| `data/<date>/*_1m.csv` | Recorded 1-minute bars (indices, futures, VIX), the GIFT print, the chain tape log | Appended per day | journal branch |
| `broker.json` | Cash and positions snapshot only (**no fill log, no order IDs**). Written only after a first fill: **absent** in production | Overwritten | journal branch |
| Chain snapshots | Full chains per fetch | Write-once assets | `chains-2026` release; 90-day run artifacts |
| Code, config, dependencies | Not in any record | — | Git history, GitHub run metadata only |

---

## I-summary. Can the system answer the protocol's questions?

| Question | Verdict | Why (key evidence) |
|---|---|---|
| **Why did we trade?** | **Untestable on production (0 trades). By design: PARTIAL** | An executed entry writes **no decision row**; its "why" lives only in the trade row, written **after** all fills (`engine.py:1176-1190`). After a mid-entry crash, the fill survives but the rationale is lost (I-06) |
| **Why did we not trade?** | **PARTIAL** | 73 rejection rows carry the plan and the gate text. But gated confirm-path opportunities are not journaled (B-03); the gate is free text (B-03); 33 of 51 EV rows print a P(up) the EV did not use (I-07) |
| **What did the system know then?** | **PARTIAL → BROKEN in places** | Bars are recorded (no per-bar source, A-04; a 12:20 hole, A-06; **no data at all for 10-01**, I-10). Chains are archived, but **only 22 of 73** decisions can be tied to a snapshot (I-07). **News "first seen" is overwritten** (I-02). **India VIX recorded as 0** (I-01). Global, breadth and heavyweight inputs are not persisted |
| **Model / factor / news / regime used?** | **Factors: YES (control V-I1). Model and news: PARTIAL** | Every thought's score, conviction and bias recompute exactly from its stored evidence (743/743), with the learned weights included. Model: text only, no artifact hash (I-03; LLM provenance G-04). News reads can be erased later (I-02) |
| **What would have happened?** | **YES for journaled rejections (control V-I4); NO for unjournaled gates** | 72 of 73 rejected plans can be valued afterwards from decision text plus archived chains. Gated confirm-path setups have no row (B-03) |
| **What did the system learn?** | **NO (event level)** | `memory.json` is aggregate-only and overwritten (D-03). Its `vix` factor was graded on fabricated input (I-01). Pre-10-05 records are gone (Q-05, A-10) |
| **Replay from persisted evidence alone?** | **NO** | 4 of 5 Kotak-era sessions **cannot run** (ZeroDivisionError on the recorded VIX). The one that runs reproduces **0 of 7** decisions. With a documented substitution, 10-08 reproduces 6 of 22 (I-04) |

---

## I1. Decision reconstruction matrix

**Columns:** Recoverable? = from persisted evidence alone, without access to production. ✅ yes · ◐ partial · ❌ no.

| What must be recovered | For a **rejected** decision (production, n = 73) | For an **executed** trade (synthetic; 0 in production) | Gap / finding |
|---|---|---|---|
| Exact code commit | ❌ Not in any record. ◐ Externally: GitHub run metadata `head_sha` (here c96909f for all runs 10-05 … 10-09). The afternoon job runs the branch **tip**, not `head_sha` (H-09) | ❌ same | **I-03** |
| Configuration | ❌ Not recorded. ◐ The config file at that commit, if the commit is known; runtime flags live only in workflow YAML and run logs | ❌ same | I-03 |
| Dependency versions | ❌ Unpinned (A-03); only in the run's install log | ❌ same | I-03, A-03 |
| Model / version | ◐ Direction model: event **text** (AUC, samples), no artifact or hash. Plan registry: `state.json` (empty, `last_event: null`), consistent with every "no approved plan model" row (**V-I7**). LLM reader: no model ID (G-04) | ◐ same | I-03, G-04 |
| Timestamp of the decision | ✅ `ts` (feed clock) | ✅ fills `ts` = the bar minute, not wall time | Ambiguities in **I-08** (A-13, the reconcile event at 09:15, mixed clocks) |
| Market data: index bars | ◐ Recorded 1-minute bars; no per-bar source (A-04); 12:20 hole (A-06); **10-01 has no data anywhere**, 09-30 has 10 bars (I-10) | ◐ | A-04, A-06, **I-10** |
| Market data: India VIX | ❌ **Recorded as 0** on every Kotak session (I-01) | ❌ | **I-01** |
| Market data: option chain used | ◐ Archived chains exist, but the decision does not name its snapshot. **22/73** match the latest archived snapshot's touch prices; **21/22** armed plans carry off-tick (modelled) leg prices; **50/73** match no snapshot within 15 min | ◐ trade `meta` has `fill_quotes`, `leg_liquidity`, `legs_plan` | **I-07** |
| News the desk had seen | ◐ News table, but `seen_at`, `ts` and LLM reads are **overwritten** by later jobs (274 rows between two snapshots on one day) | ◐ | **I-02** |
| Global, breadth, heavyweight inputs | ❌ Not persisted (only their resulting factor observations in thoughts) | ❌ | I-04 |
| Factors used and their weights | ✅ for sampled minutes: thought evidence recomputes score, conviction and bias exactly (743/743; weights include the learned multipliers). ❌ for unsampled minutes: B-03 and the thought sampling interval | ✅ trade `context.evidence` | **V-I1** |
| Regime | ✅ thought `day_type`, trade `context.regime` | ✅ | — |
| Gate that rejected it | ◐ Free text (B-03). EV numbers in `context.ev` (✅). P(up) in the text disagrees with the one used in 33/51 rows | n/a | B-03, **I-07** |
| Why it traded (thesis, plan, EV) | n/a | ◐ trade row `rationale`, `context`, `meta`, written after all fills; **lost if the entry is interrupted**; no decision row | **I-06** |
| Counterfactual outcome | ✅ 72/73 valued mid-to-mid to 15:15 from plan text plus archived chains | ✅ | **V-I4** (gated setups ❌, B-03) |
| What it learned from it | ❌ aggregate `memory.json` only; overwritten daily | ❌ | D-03, I-01 |
| State at the time (memory, risk, open positions) | ◐ thought weights carry the learned multipliers; risk and memory state only as the current snapshot | ◐ `intraday_open` (current only) | D-03, I-04 |

---

## I2. Journal and broker reconciliation

**Only one ledger exists.**
- The paper broker persists `{cash, positions, fees_paid, fee_breakdown}` (`execution/broker.py:113-123`).
- It keeps no fill log, order IDs or timestamps: `self.fills` lives in memory.
- `broker.json` and the journal's `fills` are both written by the same process, so there is no independent second ledger.
- Independent reconciliation is therefore limited to **recomputing positions and cash from journal fills plus starting
  capital, and comparing with `broker.json`**.
- **Production cannot be reconciled at all:** there are 0 fills and no `broker.json` since the 10-05 reset.

**Production journal setting:** `Journal(p["journal"], autocommit_every=1)` (`intraday/cli.py:90`), so every journal
write is committed at once.

- **Phase H's harness used the library default (200).** Its test 8a JSON shows `journal_fills: []` because the buffered
  row was lost.
- Under the production setting, that row **survives**.
- Phase H's behavioural results (orphan, entry halt, double exit) are unchanged. What changes is what evidence remains;
  see § I3.

### Synthetic reconciliation results

Harness: `audit/probes/phase_i_evidence.py`. Output: `audit/data/phase_i_evidence.json`. Production journal setting;
the audit is run on the files only, with no engine.

| Scenario | Fills → positions = `broker.json` | Fills → cash = `broker.json` | Per-trade fills vs trade row | Orphan fills | What else persists |
|---|---|---|---|---|---|
| Clean round trip | ✅ `{}` = `{}` | ✅ ₹499,402.31 | ✅ consistent | 0 | — |
| Entry interrupted after leg 1 | ✅ `+65 25700CE` both | ✅ ₹483,904.51 | — (**no trade row**) | **1** (a fill whose `trade_id` has no trade) | CRITICAL `{journal: {}, broker: {…: 65}}`, stamped **09:15** |
| Exit interrupted after leg 1, then restart | ✅ end `−65 25700CE` both | ✅ ₹513,440.14 | ❌ trade `closed` but fills net **−65** on 25700CE (fills +65, −65, −65) | 0 | CRITICAL stamped **09:15** |
| Position left overnight | ✅ both legs | ✅ ₹497,134.65 | ✅ trade row still **open** | 0 | `intraday_open` still lists it at next-day start; WARN stamped with the **wall clock** |

**Conclusions:**
- Positions and cash are **always** recomputable from fills. They agree with `broker.json` in every scenario
  (control **V-I2**), because the process writes both.
- Every interrupted sequence leaves a **detectable inconsistency** in the persisted record: an orphan fill, fills
  disagreeing with the trade status, or an open trade from a prior day.
- **However, nothing checks for it:**
  - `_reconcile` compares broker positions with the in-memory open trades only (`engine.py:896-913`);
  - it never reads fills;
  - it runs only at session start;
  - self-review ignores its CRITICAL event (H-04).
- **Partial fills.** The paper broker fills all-or-nothing; the Kite adapter drops partial fills (F-06, settled). The
  journal schema (`fills`: no order ID, no requested quantity) **cannot represent a partial fill**: a requested-vs-filled
  quantity is unrecoverable. [code] This is part of I-06.

---

## I3. Crash and restart evidence: what can be reconstructed from persisted records alone

Production journal setting. Synthetic, `phase_i_evidence.py`.

| Phase H case | Event | From persisted records alone | Missing to reconstruct it fully |
|---|---|---|---|
| **H-02** entry interrupted | Leg 1 filled, crash before leg 2 | ✅ instrument, qty, price, fee, time and trade ID of the orphan leg (`fills`); ✅ positions and cash; ✅ the CRITICAL diff | ❌ **why**: no trade row (written only after all fills, `engine.py:1186-1188`), no decision row for executed entries (all `journal.decision` calls are "rejected"). ❌ the intended leg 2 (plan). ❌ the correct time order: the CRITICAL event is stamped 09:15, before the 10:30 fill |
| **H-01** exit interrupted | Leg 1 closed, crash, restart re-closes both legs | ✅ the double sale is visible: three 25700CE fills (+65, −65, −65); ✅ the trade is "closed" with fills net −65; ✅ cash matches the broker | ❌ **which fill was the duplicate** (no order intent or close-reason per fill); ❌ that a restart happened between them (only the 09:15-stamped CRITICAL; no "restart" event with wall time) |
| **H-03** overnight carry | Position left open; next day starts | ✅ the trade row stays **open** indefinitely; ✅ fills consistent; ✅ the WARN "never squared off" | ❌ expiry settlement (never recorded, unverified, as in the Phase H closeout D5); the WARN is stamped with the wall clock, not the session time |

**Minimum evidence needed to reconstruct any fill/state crash unambiguously** [code + synth]:
1. a **pre-trade intent row** (decision or order intent: plan, legs, quantities, `opportunity_id`), written and committed
   **before** the first broker call;
2. per fill: order ID, requested quantity, intent (open, close or unwind), and the wall-clock write time;
3. a **restart event** with wall time and the reconcile diff, stamped when it happens (not 09:15);
4. a fills-vs-trades-vs-broker reconciliation that runs on persisted records, not on in-memory state.

---

## I4. `model_state` provenance

**Callers** [code]:
- `IntradayEngine.model_state` (`engine.py:165-175`) has **one** caller: `ModelOptionChain(…, state_fn=self.model_state, …)`
  (`engine.py:57`), via `ModelOptionChain.chain` (`chains.py:295-319`).
- That chain is used:
  - as the configured source in replays and what-ifs with `--chain model` (`intraday/cli.py:383-385`, `deploy/whatif.py`;
    B-11);
  - as the live fallback when the configured chain fails (`engine.py:346-362`).

**Inputs consumed:**
- `S` = the last recorded 1-minute close of the index (`self.bars[u]`), with no age check;
- `vix` = the last India VIX close ≤ ts, `else 14.0`;
- IV = VIX/100 × `iv_beta`.

**Is each input condition recorded and distinguishable?**

| Input condition | Recorded? | Distinguishable in the audit trail? | Evidence |
|---|---|---|---|
| Model chain in use | ✅ `thought.chain.source = "model"`; a WARN "pricing off the model chain (India VIX)" on the 1st and every 10th failure | ✅ | `engine.py:356-359`; production: 0 of 743 reads used it (742 kotak, 1 nse) |
| Spot used | ❌ not stored separately (the thought `spot` is the analyst's) | ◐ | [code] |
| VIX value and IV used | ❌ never recorded with the chain; the model chain is never written to disk (`engine.py:376`) | ❌ | [code] |
| **VIX missing** → 14.0 | ❌ silent | ❌ | H-08 [synth] |
| **VIX stale** | ❌ no age check | ❌ | H-08 [code] |
| **VIX present but 0** (the production condition, I-01) | Bars CSV shows 0; the thought `vix` observation shows "India VIX 0.00 (−100.0% today)" | ◐ only by reading the text | [prod] + [synth] below |
| Fabricated OI and spreads (model chain) | ◐ via `source = "model"` | ◐ | F-01 |

### Production failure mode, VIX = 0 (synthetic, prior days nonzero as in production)

Output: `audit/data/phase_i_vix_zero_model_chain.json`.

| Quantity | VIX normal | VIX 0 |
|---|---|---|
| `model_state` IV | 0.1551 | **0.0** (not 14 %) |
| ATM call (25,700 CE) LTP | ₹243.60 | **₹36.65** (−85 %) |
| ATM IV in chain analytics | 15.63 % | **NaN** |
| `_vix_state` | last 15.51, +4.6 % | last 0.0, **−100 %** → analyst vote +1.0 |

- If the prior day's VIX is also 0, `_vix_state` raises **ZeroDivisionError** on every step (`engine.py:420`).
- Live, `run_step` counts it, and 3 in a row means safe mode. A replay aborts.
- Probe: `test_zero_prior_day_vix_makes_every_step_raise`.
- **This refines H-08:** the failure production would actually hit is "VIX = 0 → IV = 0", not "missing → 14".

---

## I5. Replay and reproducibility (§8 test 17: real-session replay)

**Method** (`audit/probes/phase_i_replay.py`):
- copies of the journal branch's recorded bars and `memory.json`;
- `chains-2026` chain snapshots for the day;
- the repo's own replay wiring (`intraday/cli.py:397`: recorded chains; no news, brain, breadth, learner or research
  priors, none of which is persisted in replayable form);
- comparison of the replay's thoughts and decisions with the journal's.

**Why only two days could be replayed.**
- The recorded India VIX for 10-05 … 10-09 is all zeros.
- `_vix_state` uses the prior day's last close as the base.
- 10-06, 10-07, 10-08 and 10-09 therefore raise ZeroDivisionError on the first step.
- Only 10-05 (prior day 09-30, a Yahoo-era day) runs as recorded.
- 10-08 was also run with a **documented substitution**: the mostly-zero VIX files for 10-05 … 10-07 are dropped, so the
  prior day is 09-30, as production effectively saw.

| | 10-05 (as persisted) | 10-08 (VIX substitution) |
|---|---|---|
| Thoughts: production / replay | 149 / 164 | 149 / 165 |
| Same minute and symbol | 35 | 52 |
| Same bias (of matched) | 28/35 | **52/52** |
| Median, max \|Δ score\| | 0.154, 0.610 | 0.034, 0.126 |
| Factors present only in production (not replayable) | news 35, heavy_pulse 28, breadth 24, global_* 97, basis 19, research 13, fut_oi 10, … | news 52, breadth 38, global_* 151, basis 26, heavy_pulse 23, research 18, fut_oi 11, … |
| Bar/chain factor sign agreement | `prev_day` **3/35**, `cpr` 18/35, `htf` 25/35, rest ≥ 28/35 | ≈ 100 % (e.g. `prev_day` 52/52, `pcr` 50/51) |
| **Decisions: production / replay / same minute, strategy and symbol** | **7 / 9 / 0** | **22 / 36 / 6** |

**Why 10-05's bar factors disagree.**
- The prior trading day, 10-01, has no persisted data (I-10), so the replay's "previous day" is 09-30.
- Live, the engine took history from Yahoo (A-04).
- When the prior day is recorded (10-08), bar and chain factors reproduce almost exactly. That is control **V-I6**.

### Non-reproducible inputs and mutable dependencies (sources of non-replay)

| Source | Type | Evidence |
|---|---|---|
| Global feed, breadth, heavyweights | not persisted | replay factor diff above |
| Research priors (`runtime/research`) | not in the journal | factor `research` missing |
| Basis and futures OI | futures bars are recorded, but futures OI is not, and the replay feed has no futures | factors `basis`, `fut_oi` missing |
| News and LLM reads | persisted but **mutated** (I-02); LLM outputs non-deterministic, with no model ID (G-04) | — |
| Memory | `memory.json` holds the current state only; the decision-time state is not kept (D-03) | — |
| Prior-day history | live = Yahoo (A-04, A-12: Yahoo not stable within a day); replay = recorded bars (gaps, I-10, A-06) | — |
| India VIX | recorded as 0 (I-01) | — |
| Code, config, dependencies | not recorded (I-03); unpinned (A-03) | — |
| Wall clock in events | I-08 | — |
| EV Monte Carlo | deterministic (seed 7, `quant.py:255, 275`) | not a source of non-replay |

**Retention:**
- Run artifacts: 90 days (`live.yml:91, 148`).
- Release assets: no expiry, but no history either; 10-01 is absent.
- Journal branch: single force-pushed commit (A-10).
- Plan studies: no retention (H-11).

---

## I6. Evidence integrity

| Check | Result | Evidence |
|---|---|---|
| Rows from the 12:20 snapshot vs the close snapshot: `events`, `decisions`, `thoughts`, `equity`, `fills`, `trades`, `checks` | **0 missing, 0 changed** (append-only in practice): control **V-I5** | `phase_i_snapshot_diff.json` |
| …`news` | **274 of 3,907 rows changed** (7.0 %): `seen_at` later in **all 274** (median +3.3 h, max +52.5 h); LLM reads lost in **34**; publish `ts` rewritten in 30 (max +56.4 h) | `phase_i_news_mutation.json` → **I-02** |
| Silent edit of a decision, deletion of an event, rewrite of a thought (scratch copy) | **All pass** `PRAGMA integrity_check`, `quick_check` and `Journal.integrity()` | probe `test_silent_edits_pass_every_integrity_check` → **I-05** |
| Hash chain or signature on journal rows | None (schema `journal.py:24-60`) | I-05; A-10 for the autolearn chains |
| Restating a trade | `UPDATE fills SET price=…` in place (`account.py:103`); the old price survives only in free text plus a WARN event (`:141`); `broker.json` rewritten non-atomically (`:125`) | I-05 |
| Branch history | One force-pushed parentless commit; earlier states unreachable (A-10). The journal itself starts 10-05 08:31; the earlier sessions' records are gone (Q-05) | settled |

---

## I7. Proposed findings (not in the register)

Format and severity scale follow the register: P0 safety/integrity/live · P1 major correctness · P2 important
limitation · P3 moderate · P4 minor.

### I-01: The India VIX recorded since the Kotak switch is 0; every analyst read since 10-05 carries a fabricated "−100 % VIX" bullish vote

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **BROKEN** (production) |
| Component | `intraday/kotak.py:430-453` (`poll` → `kotak_bars("INDIAVIX")` from Kotak candles); `intraday/engine.py:411-420` `_vix_state`; `intraday/analyst.py:233-235` (vote `−clip(chg/0.06)` → +1.0 at −100 %); `engine.py:165-175` (`model_state`) |
| Reproduction | Probes `test_recorded_india_vix_is_zero_on_every_kotak_session`, `test_every_production_read_carries_a_fabricated_vix_vote`, `test_thought_scores_recompute_exactly_and_the_vix_vote_flips_bias_labels`; `phase_i_thought_recompute.json` |
| Evidence type | [prod] + [prod-replay] + [synth] |
| Expected | A VIX of 0 (or a −100 % move) is rejected as invalid data, flagged, and never voted, graded or used for pricing |
| Observed | **Bars:** 10-05 … 10-09 have 372–373 of 373 bars at 0 (one real print on 10-06, 10-08 and 10-09); 09-29 (Yahoo) has none. **Reads:** 742 of 743 production thoughts carry `vix` = "India VIX 0.00 (−100.0% today)", direction **+1.0**, weight ≈ 0.31. The mean score shift is +0.035 (max +0.075), and **23 reads (3.1 %) would have a different bias label** without it. **Learning:** the `vix` factor's memory record (n ≈ 217) mixes these grades in (D-03). **Replay:** the zeros make 4 of 5 Kotak-era sessions unreplayable (I-04). **Model chain:** would price at IV 0 (I-09) |
| Root cause | **UNVERIFIED**: whether Kotak's candle endpoint returns zero OHLC for INDIA VIX, or parsing zero-fills it. The Kotak payload has never been inspected (A-11) |
| Impact: paper | A systematic bullish tilt in every read; it moves arming thresholds and the EV P(up) tilt (`engine.py:1083`). No trade resulted, because all entries are gated (B-02) |
| Impact: research | Recorded VIX is unusable; any study on recorded data inherits zeros |
| Impact: recovery | — |
| Impact: live | A fabricated input in the decision path |
| Acceptance | **Data:** VIX bars ≤ 0, or a ≥ 50 % one-minute move, are quarantined, never recorded as valid, and raise WARN or above. **Vote:** the `vix` factor is absent (not +1) when VIX is invalid. **Probes:** a probe over 5 recorded sessions shows 0 zero-VIX bars and 0 "−100 %" observations. **Learning:** the `vix` memory entry is rebuilt or flagged |
| Escalation | Becomes **P1** if recorded zeros reach any training or research dataset. The autolearn VIX store currently comes from Yahoo, ends 10-01 and has no zeros: [prod] |

### I-02: The news record of "when the desk saw it" is overwritten by every new job; LLM reads are erased

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **BROKEN** (production) |
| Component | `intraday/news.py:340-370` (dedup against the in-memory `self.items` only; never reloaded from the journal); `intraday/engine.py:389-395`; `journal/journal.py:192-203` (`INSERT OR REPLACE INTO news`, `UPDATE news SET nlp`) |
| Reproduction | Probes `test_news_first_seen_and_llm_reads_are_overwritten_between_snapshots`, `test_news_dedup_lives_in_memory_and_news_add_replaces_rows`; `phase_i_news_mutation.json` (PREV vs CLOSE) |
| Evidence type | [prod] + [code] |
| Expected | `seen_at`, publish `ts` and every LLM read that existed at decision time are immutable once written |
| Observed | Between the 12:20 and 16:15 snapshots of one day, **274 rows** were rewritten. `seen_at` moved **later in all 274** (median +3.3 h, max +52.5 h; e.g. a story first seen 10-07 08:51 is now "first seen" 10-09 13:20). **34 lost their LLM reads**; 30 had their publish `ts` rewritten |
| Relation | **Undermines V-07 and V-08** (seen-time visibility in replays relies on `seen_at`); worsens A-09 (grading from `ts`); G-04 |
| Impact: paper | None directly on live decisions; the in-memory items drive the tone |
| Impact: research | Replays and what-ifs make stories visible later than the desk saw them, without the reads it had; news grading uses rewritten times |
| Impact: recovery | — |
| Impact: live | The audit trail of the news inputs is unreliable |
| Acceptance | A story's first `seen_at`, `ts` and every read are write-once; a restart re-reads known IDs from the journal. A test runs two jobs over the same feed and asserts unchanged rows. A snapshot diff across a handover shows 0 changed `seen_at` |

### I-03: No decision or trade record identifies the code, configuration, dependencies or model that produced it

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **VERIFIED** |
| Component | `journal/journal.py:24-60` (schema: no commit, config or version column); `push-dir.sh` (journal commit message = date only); `.github/workflows/live.yml:107` (afternoon checks out the branch tip, H-09); `requirements.txt` unpinned (A-03) |
| Reproduction | Probe `test_journal_records_no_code_config_or_model_provenance` (schema plus a scan of every event, decision and state value for the commit hash) |
| Evidence type | [code] + [prod] |
| Expected | Each session (and each decision) records the commit SHA, a config hash, dependency versions, and model artifact IDs and hashes |
| Observed | None present. The commit is recoverable only from GitHub run metadata (`head_sha`), which does not reflect the afternoon's branch-tip checkout. Run logs (with dependency versions) are not retained indefinitely. Model provenance: event text only (direction model), and no model ID (LLM, G-04) |
| Impact: paper | Behaviour changes can't be attributed |
| Impact: research | A result or decision can't be tied to the code that made it |
| Impact: recovery | Can't rebuild the exact runtime |
| Impact: live | A regulatory and audit gap |
| Acceptance | The session-start event carries `{commit, config_sha256, pip_freeze_sha256, model_ids}` for each job; decision rows reference the session. A probe asserts these keys are present and match the running checkout |

### I-04: A recorded session cannot be replayed from persisted evidence alone; decisions do not reproduce

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **VERIFIED** (§8 test 17 executed) |
| Component | `intraday/cli.py:359-397` (replay wiring: no news, brain, breadth, learner or research); inputs not persisted (§ I5 table); `engine.py:420` (crash on recorded VIX); I-10 (missing days) |
| Reproduction | `audit/probes/phase_i_replay.py` on the CLOSE copy plus `chains-2026` → `phase_i_replay_2026-10-05.json`, `phase_i_replay_2026-10-08_vix_substituted.json` |
| Evidence type | [prod-replay] |
| Expected | Replaying a session from persisted evidence reproduces its decisions (consolidation Decision 1, criterion 6) |
| Observed | 10-06 … 10-09 **cannot run** (ZeroDivisionError). 10-05: **0 of 7** decisions at the same minute; bias 28/35 on matched reads; `prev_day` factor 3/35. 10-08 (VIX substitution): factor-level match ≈ 100 %, but only **6 of 22** decisions, plus 30 extra |
| Relation | Extends B-11 (what-if `as_run`) and D-03 (memory) with an executed, quantitative replay |
| Impact: paper | Past decisions can't be re-derived to test a fix |
| Impact: research | No replay-based regression testing on real sessions |
| Impact: recovery | A disputed decision can't be re-run |
| Impact: live | Blocks an auditable decision trail |
| Acceptance | Every input to a decision is persisted (or deterministically re-fetchable with a content hash): global, breadth, research priors, futures OI, LLM reads (immutable), memory as of the session start, and code and config IDs. `replay --date D` on 5 recorded sessions reproduces ≥ 99 % of thought biases and 100 % of decision rows (minute, setup, gate) |

### I-05: Journal records are mutable and nothing can detect an edit or deletion

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **VERIFIED** |
| Component | `journal/journal.py:139-203` (`INSERT OR REPLACE` trades and news; `UPDATE` trades and news); `intraday/account.py:103, 125, 141` (`restate_trade` rewrites fills in place; non-atomic `broker.json` write); no row hashes or anchor; A-10 (force-push) |
| Reproduction | Probes `test_silent_edits_pass_every_integrity_check`, `test_restating_a_trade_rewrites_fills_in_place` |
| Evidence type | [prod copy] + [code] |
| Expected | Append-only records with a verifiable chain (row hash plus an external anchor); corrections as new rows that reference the original |
| Observed | A rejected decision rewritten as "entered", an event deleted and a thought flipped all pass `integrity_check`, `quick_check` and `Journal.integrity()`. Restatement replaces fill prices; the original survives only inside free text |
| Relation | Extends A-10 (autolearn and sleeves chains, branch force-push) to the journal DB itself |
| Impact: paper / research / recovery / live | The journal cannot serve as independent evidence |
| Acceptance | Each table is append-only (corrections as new rows), with a hash chain whose head is anchored outside the snapshot (e.g. in the commit message, or a separate append-only branch or release). A verifier detects the three edits above; a test asserts that detection |

### I-06: Interrupted entries and exits leave detectable evidence that nothing checks; an entry's rationale is lost; partial fills are unrepresentable

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **VERIFIED** [synth, production journal setting] |
| Component | `engine.py:1176-1192` (fills before the trade row; no intent row); `engine.py:481-1174` (every `journal.decision` is "rejected"); `engine.py:896-913` (`_reconcile`: broker vs in-memory open trades; no fills); `execution/broker.py:113-123` (no fill log); `journal.py:36-39` (`fills`: no order ID or requested quantity) |
| Reproduction | `audit/probes/phase_i_evidence.py` → `phase_i_evidence.json`; probes `test_production_opens_the_journal_with_autocommit_every_write`, `test_interrupted_entry_leaves_an_orphan_fill_that_reconcile_never_reads`, `test_interrupted_exit_shows_a_double_exit_in_fills`, `test_an_executed_entry_writes_no_decision_row` |
| Expected | Every order sequence is reconstructable: intent before the broker call, then a fill with order ID and requested quantity, then the outcome; an automated fills/trades/broker reconciliation on persisted data |
| Observed | Orphan fill (8a) and double exit (8b) **are** visible in `fills`, but `_reconcile` never reads them. 8a has no trade row and no decision row, so the plan and rationale are gone. No order IDs. A partial fill cannot be expressed |
| Refines Phase H | H-01/H-02 evidence was produced with `autocommit_every=200`; under production's `=1` the fills survive. Outcomes unchanged; evidence improved |
| Impact: paper | Crashes can be diagnosed by hand only |
| Impact: research | — |
| Impact: recovery | Automated repair impossible without intent rows |
| Impact: live | Mandatory before any live order path |
| Acceptance | An intent row is committed before the first broker call; fills carry the order ID, requested quantity and intent; a persisted-record reconciler flags orphan fills, fill/trade mismatches and stale open trades. Tests for both crash points pass with the reconciler flagging each case |

### I-07: Decisions don't identify the inputs they used; their text can misstate the value used

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** (production) |
| Component | `engine.py:1091-1112` (EV text prints the tilted P(up); non-directional structures use 0.5, `:1101`); decision `context` has no chain snapshot timestamp or ID; armed plans store modelled leg prices |
| Reproduction | Probes `test_decision_text_reports_a_p_up_the_ev_did_not_use`, `test_only_a_minority_of_decisions_match_an_archived_snapshot`; `phase_i_snapshot_ident.json` |
| Evidence type | [prod] + [prod-replay] |
| Expected | Each decision records the snapshot timestamp or ID and the exact numeric inputs used; text never contradicts `context` |
| Observed | 33 of 51 EV rows print P(up) ≠ `context.ev.p_up`. Only **22 of 73** decisions match an archived snapshot's touch prices (all EV rows, the latest snapshot, ~50 s earlier). 21 of 22 armed plans carry off-tick leg prices (modelled, not quotes). 50 match nothing within 15 min (cause **UNVERIFIED**) |
| Impact: paper | — |
| Impact: research | Can't tell which market state a decision priced |
| Impact: recovery | — |
| Impact: live | Weak decision audit trail |
| Acceptance | Decision `context` has `chain_ts` / `snapshot_id`, quote basis and every numeric input; text is generated from `context`; a probe matches 100 % of decisions to an archived snapshot |

### I-08: Ambiguous timestamps: events back-dated to the session open, and two clocks mixed in one table

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** |
| Component | `engine.py:911` (reconcile CRITICAL stamped `session_bounds(day)[0]`); `engine.py:179, 621, 627, 1382` (`pd.Timestamp.now()` wall clock) vs the feed clock elsewhere; A-13 (session events at 09:15) |
| Reproduction | Probe `test_reconcile_event_is_stamped_at_the_session_open_before_the_crash_it_reports`; `phase_i_evidence` temp journals (the 16c WARN carries the wall-clock date) |
| Evidence type | [synth] + [code] |
| Expected | Every row stores the event time and the write time (wall clock), labelled |
| Observed | A reconcile failure detected at 10:32 is stamped 09:15, before the 10:30 fill it reports. Replays and synthetic runs write wall-clock dates into session journals |
| Impact | Crash timelines and replays order events wrongly |
| Acceptance | A `written_at` column on all tables; reconcile and restart events use the detection time; a probe asserts event order equals causal order in the crash scenarios |

### I-09: `model_state`'s inputs are not recorded; with production's zero VIX it prices at zero volatility, or crashes the step

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED (latent)**: the model chain was used 0 of 743 times in production |
| Component | `engine.py:165-175`, `:411-420`, `:57`; `chains.py:280-319`; `engine.py:376` (model chain never recorded) |
| Reproduction | `phase_i_vix_zero_model_chain.py` → JSON; probes `test_zero_vix_prices_the_model_chain_at_zero_volatility`, `test_zero_prior_day_vix_makes_every_step_raise` |
| Evidence type | [synth] |
| Expected | `model_state` returns its inputs plus a validity flag; invalid VIX blocks model-chain pricing; the inputs are journaled when the model chain is used |
| Observed | IV 0.0, ATM call ₹36.65 vs ₹243.60 (−85 %), chain ATM IV NaN; with prior-day VIX 0, `ZeroDivisionError` on every step |
| Refines | **H-08**: the production-relevant mode is "present but 0 → IV 0", not "missing → 14" |
| Impact: paper | Mispriced fallback, or a failure storm leading to safe mode |
| Impact: research | — |
| Impact: recovery | — |
| Impact: live | Same |
| Acceptance | VIX ≤ 0 or stale → model chain degraded and entries refused, with an event recording S, VIX, IV and ages. `_vix_state` never divides by a non-positive base; a probe with zero VIX passes without an exception |

### I-10: Market data for some sessions is not persisted anywhere

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** |
| Component | Recorder plus journal branch plus `chains-2026` release |
| Reproduction | Probe `test_no_recorded_market_data_for_2026_10_01`; the release asset list (all 86 read): no 10-01 asset |
| Evidence type | [prod] |
| Expected | Every session the desk ran has its bars and chains archived |
| Observed | 10-01 (a session of the pre-reset ₹20k account, D-03): no bars or chains on the branch or the release. 09-30: 10 bars. The journal itself starts 10-05 08:31 (Q-05) |
| Impact | Replays use the wrong prior day (10-05: `prev_day` 3/35); memory grades from 10-01 can't be re-derived |
| Acceptance | A daily completeness check (bars ≥ 370 per index, chains present) files an issue on a gap; a backfill path exists |

---

## I8. Controls verified (proposed)

| ID | Control | Evidence |
|---|---|---|
| V-I1 | Every production thought's score, conviction and bias recompute **exactly** from its persisted evidence (743/743); stored weights include the learned multipliers | `phase_i_thought_recompute.json`; probe |
| V-I2 | Positions and cash recompute exactly from journal fills plus starting capital, and equal `broker.json`, in every crash scenario | `phase_i_evidence.json` |
| V-I3 | Production commits every journal write at once (`autocommit_every=1`), so interrupted sequences leave fill evidence | `intraday/cli.py:90`; probe |
| V-I4 | 72 of 73 production rejections can be valued afterwards (mid to mid, to 15:15) from decision text plus archived chains | `phase_i_counterfactual.json`; probe |
| V-I5 | `events`, `decisions`, `thoughts`, `equity`, `fills`, `trades`, `checks`: 0 rows missing or changed between the 12:20 and close snapshots | `phase_i_snapshot_diff.json` |
| V-I6 | With the prior day recorded, bar- and chain-derived factors replay with ≈ 100 % sign agreement and 52/52 bias agreement (10-08) | `phase_i_replay_2026-10-08_vix_substituted.json` |
| V-I7 | Every "no approved plan model" rejection is consistent with the persisted registries (both empty, `last_event: null`) | `autolearn/registry/state.json`, `plan/registry/state.json` (CLOSE copy) |

---

## I9. Effect on earlier findings and controls (cited, not re-audited)

| ID | Effect |
|---|---|
| **H-08** (proposed) | Refined by I-09: the production mode is VIX = 0 → IV 0 (and a possible ZeroDivisionError), not VIX missing → 14 |
| **H-01 / H-02** (proposed) | Evidence refined by I-06: under the production journal setting the orphan and double-exit fills persist. Behaviour unchanged |
| **V-07 / V-08** | Undermined by I-02: `seen_at` is not first-seen after a restart |
| **B-11** | Extended by I-04 (executed replay, quantified) |
| **D-03** | Extended by I-01 (the `vix` factor graded on fabricated input) |
| **A-10** | Extended by I-05 (the journal DB itself) |
| **A-13** | Extended by I-08 (reconcile event; mixed clocks) |
| **A-04 / A-06 / A-11 / G-04 / B-03 / Q-05** | Cited as gaps in the matrix |
| **Q-12** | Production model-chain use is 0/743 (as in Phase H) |

---

## I10. Missing evidence and recommended follow-up tests

| # | Missing evidence | Follow-up test (safe; synthetic or on copies) | Phase |
|---|---|---|---|
| 1 | Root cause of the zero VIX (Kotak payload vs parsing) | Parse a captured Kotak candle payload for INDIA VIX through `normalise_bars`; needs a real payload (owner-provided, no credentials in the audit) | K / owner |
| 2 | Whether zero VIX bars reach autolearn or research datasets | Run one autolearn `gather()` on a copy with recorded VIX present; inspect `bars5/INDIAVIX` | K/L |
| 3 | Why 50 of 73 decisions match no archived snapshot | Trace `_select_by_ev` and the armed-plan repricing on a recorded session with snapshot IDs logged in a scratch build | L |
| 4 | The order behind the I-02 overwrites, and grading impact (A-09) | Two-job replay over one fixed feed file; regrade news before and after | L |
| 5 | Decision-level replay with all inputs | Not possible until I-04's inputs are persisted; re-run § I5 after remediation as the acceptance test | post-remediation |
| 6 | Restatement on real data | None in production (0 trades); synthetic restate of a closed trade, then the fills/broker reconciliation | L |
| 7 | Partial-fill representation | Fake-broker partial fill → journal → reconciliation (R8 in the consolidation) | remediation |
| 8 | Commit identity of afternoon jobs | Compare the `head_sha` of morning and afternoon jobs where `main` moved mid-day (none in 10-05 … 10-09) | K |
| 9 | Expiry settlement of carried legs (Phase H closeout D5) | Extend the overnight scenario past 15:30 on the expiry day | L |

---

## I11. Implications for implementation planning

All of these are later work; nothing was changed in this phase.

1. **Data validity gate first (I-01).**
   - A single invalid input (zero VIX) silently entered every read, the learning record and the replay path for five
     sessions.
   - A per-series validity check (≤ 0, a flat run, ≥ X % jumps, staleness) with quarantine and WARN belongs before any
     model or strategy work. It also covers H-08 and I-09.
2. **An immutable, provenance-stamped journal is the foundation for every later fix (I-03, I-05, I-02, I-08):**
   - session provenance (commit, config hash, dependencies, model IDs);
   - write-once rows with `written_at`;
   - news first-seen preserved;
   - a hash chain anchored outside the force-pushed branch.
   - Without it, no remediation can be verified against history.
3. **Intent-before-execution and a persisted-record reconciler (I-06)** are prerequisites for H-01/H-02/H-03 fixes and
   for R8 (order and partial-fill accounting).
4. **Replayability as the acceptance harness (I-04).**
   - Persist every decision input (or a content hash plus a re-fetch path).
   - Make `replay --date D` the regression test that reproduces the journal's decisions.
   - The consolidation's Decision 1, criterion 6 depends on it.
5. **Archive completeness (I-10)** is cheap and should run daily.
6. **Sequencing:** do (1) and (2) before the H-01 … H-07 recovery fixes, so the fixes are provable on persisted
   evidence. (3) goes with H-01/H-02.

---

## I12. Limitations

| Limitation | Effect |
|---|---|
| Production has 0 trades and 0 fills since 10-05 | "Why did we trade?" and journal/broker reconciliation are tested on synthetic sessions only |
| No Kotak payload, credentials or network calls | The I-01 root cause is UNVERIFIED |
| Only two journal snapshots (one day apart in time-of-day, same day) | I-02 measured within one day; cross-day mutation rate not measured |
| Chain archives downloaded for 9 parts | 10-09 afternoon not downloaded, so decision 73 is unmatched for that reason |
| Replay | Uses the repo's replay wiring, which omits news, brain, breadth and learner. A faithful replay with those inputs is impossible because they aren't persisted, which is the finding itself |
| 10-08 replay | Uses a **documented VIX substitution** (mostly-zero prior-day files dropped); it is not "persisted evidence alone" |
| Thought sampling | Thoughts are sampled (≈ every 2–3 min or on a bias flip), so minute-level reconstruction outside sampled minutes is not possible |
| `phase_i_replay.py` provenance | Edited between the 10-05 run and the 10-08 run (the substitution rule). The 10-05 run did not use the flag, so its output is unaffected; noted for provenance |

---

## I13. Tests and artifacts

**Executed:**
- **`audit/probes/test_phase_i_probes.py`** (19 probes) with `QD_JOURNAL` = CLOSE copy, `QD_JOURNAL_PREV` = PREV copy,
  `QD_CHAINS` = the downloaded chain archive.
  - First run: 18 passed, 1 failed. The failure was a bug **in the probe**: it inspected `type(class)._reconcile`. Fixed.
  - **Final run: 19 passed in 90.86 s** (log `audit/data/phase_i_probe_run.txt`).
  - Without the data variables: 9 passed, 10 skipped (clean skip).
- **Measurement scripts** (outputs in `audit/data/`):

| Script | Output |
|---|---|
| `phase_i_thought_recompute.py` | `phase_i_thought_recompute.json` |
| `phase_i_snapshot_diff.py` | `phase_i_snapshot_diff.json` |
| `phase_i_news_mutation.py` | `phase_i_news_mutation.json` |
| `phase_i_counterfactual.py` | `phase_i_counterfactual.json` |
| `phase_i_snapshot_ident.py` | `phase_i_snapshot_ident.json` |
| `phase_i_vix_zero_model_chain.py` | `phase_i_vix_zero_model_chain.json` |
| `phase_i_evidence.py` | `phase_i_evidence.json` |
| `phase_i_replay.py` | `phase_i_replay_2026-10-05.json`, `phase_i_replay_2026-10-08_vix_substituted.json` |

**New files (all untracked):**
- `audit/QUANTDESK_PHASE_I_AUDITABILITY.md`
- `audit/probes/test_phase_i_probes.py`, `phase_i_evidence.py`, `phase_i_replay.py`, `phase_i_thought_recompute.py`,
  `phase_i_snapshot_diff.py`, `phase_i_news_mutation.py`, `phase_i_counterfactual.py`, `phase_i_snapshot_ident.py`,
  `phase_i_vix_zero_model_chain.py`
- `audit/data/phase_i_*.json` (9 files)

---

## I14. Handoffs (listed only; not started)

| To | Item |
|---|---|
| **J** (UI truthfulness) | Does the site show "India VIX 0.00 (−100%)" as a real reading? Does it present news "seen at" times that I-02 rewrote? Does any UI claim "every decision is replayable" or "records are never edited"? |
| **K** (session forensics) | Use § I1's matrix per session type; quantify the VIX vote's effect on arming in each session; the 10-05 vs 10-08 replay contrast |
| **L** (adversarial) | Follow-ups 2, 3, 4, 6 and 9 above; attack the "append-only" claims (A-10, I-05) and silent provider substitution (A-04, I-01) |

---

## I15. Recommendation

1. **Accept Phase I for review.** All six questions and the replay question have evidence-backed verdicts. The matrix,
   missing evidence and follow-ups are listed.
2. **Owner decisions needed:**
   - whether I-01 … I-10 and V-I1 … V-I7 go into the register (with the Phase H proposal);
   - whether **I-01** (production-confirmed fabricated input) should be raised to P1.
3. **Phase J** should not start without a separate approval.
