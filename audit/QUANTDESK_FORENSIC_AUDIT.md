# QuantDesk Forensic Audit

Read-only, evidence-first, one phase at a time. No production code, config, data, spec, result, risk parameter or
workflow was changed. The only files written are under `audit/`.

| Artifact | Status |
|---|---|
| `QUANTDESK_FORENSIC_AUDIT.md` (this file) | live: the phase log, answers so far, scorecard |
| `QUANTDESK_FINDINGS_REGISTER.md` | live: every finding, cumulative |
| `QUANTDESK_ARCHITECTURE_MAP.md` | Phase A1: done |
| `QUANTDESK_DATA_LINEAGE.md` | Phases A2 + A3: done |
| `QUANTDESK_TRADING_STATE_MACHINE.md` | Phase B: done |
| `QUANTDESK_LEARNING_AUDIT.md` | Part C (models): done; Part D (learning): pending |
| `QUANTDESK_AI_AUDIT.md` | Phase G: pending |
| `QUANTDESK_RESEARCH_VALIDITY.md` | Phase E: pending |
| `QUANTDESK_REMEDIATION_PLAN.md` | at the end |
| `QUANTDESK_TEST_PLAN.md` | at the end; the Phase A probes are in `audit/probes/` |

## Phase tracker

| Phase | Scope | Status |
|---|---|---|
| A | System foundation: architecture, lineage, point-in-time | done |
| B | Trading decision pipeline: interpretation, setups, state machine, funnel, triggers | done |
| C | Models: direction, plan, EV/cost | **done, awaiting review** |
| D | Learning system: ledger, factors, lifecycle, recency, regime, no-trade, baseline, self-correction | not started |
| E | Research validity | not started |
| F | Options / futures / execution | not started |
| G | AI / LLM | not started |
| H | Data / reliability / operations | not started |
| I | Journal / auditability | not started |
| J | UI truthfulness | not started |
| K | Real-session forensics | not started |
| L | Adversarial audit | not started |

---

## Phase A: System foundation

### A.1 Objective

Establish, from runtime entry points rather than file names:
- what runs, who starts it, and where state lives (A1);
- how each data stream travels from provider to decision and learning, and how failures surface (A2);
- whether any decision-critical or learning-critical path can see the future, or differs between live and training
  (A3).

### A.2 Evidence base

| Ref | Value |
|---|---|
| Code | `main@c96909f` |
| Runtime state | `journal@ecd03156`: SQLite journal (675 thoughts, 72 decisions, 0 trades, 0 fills, 68 events, 3,907 headlines, 337 equity points), `memory.json`, autolearn tree, sleeves ledgers, 7 recorded sessions (2026-09-29 … 10-09) |
| Research priors | `research@201028be` (2026-10-03) |
| Public site | `gh-pages@4f13bd26` (`data.json` ≈ 2.5 MB) |
| Environment | an isolated venv built from `requirements.txt` → pandas 3.0.6 / numpy 2.5.3 / yfinance 1.7.0 / scipy 1.18.1 / pyarrow 25.0.1. That is what a GitHub runner would get today |

All state was fetched into a scratch directory with `git archive`. Nothing in the repo or on any branch was written.

### A.3 Files and runtime paths traced

| Path | Traced |
|---|---|
| Entry points | `quantdesk/__main__.py` → `cli.main` → subcommand `fn`; `intraday/cli.py:_live_engine`, `cmd_live`, `cmd_replay`; `autolearn/cli.py`; `data/cli.py` |
| Schedulers | `.github/workflows/*.yml` (22 workflows), `deploy/scheduler.py` (header), `wrangler.jsonc`, `deploy/run-session.sh`, `deploy/journal.sh`, `deploy/push-dir.sh`, `deploy/research.sh`, `deploy/warehouse-context.sh` |
| Bars | `intraday/feeds.py`, `intraday/kotak.py` (feed, chain, futures), `intraday/recorder.py`, `intraday/engine.py` (`start_session`, `step`, `_quant_state`, `_train_models`, `_learn`) |
| Learning loop | `autolearn/live.py`, `ledger.py`, `store.py`, `features.py`, `validation.py`, `cycle.py` (orchestration, `_ingest`, `gather`, `default_loader`) |
| News | `intraday/news.py` (parse, `relevant`, `state`), `journal/journal.py:news_add`, `intraday/learning.py:forward`, `grade_news` |
| EOD context | `data/warehouse.py`, `intraday/ivhist.py:load`, `intraday/brain.py:load_flows`, `GlobalFeed.market` |
| Chains replay / PIT | `intraday/chains.py:RecordedChains`, `save_chain` / `load_chain`, `fill_iv`; `autolearn/plans.py:at/after` |

### A.4 What the persisted state shows (facts, not interpretation)

**Account and activity**
- The paper account was reset from ₹20,000 to ₹5,00,000 on 2026-10-05 (event: "no trades yet").
- Since then: 5 sessions (10-05 … 10-09 morning), **0 trades, 0 fills**.

**Autolearn**
- Champion: none, ever; no challenger.
- Ledger: none (A-01).
- 5 cycles have run; each validated only `baseline`, which failed. On 10-08 it failed 7 gates.
- The lockbox (09-22 … 10-01) has been created and never accessed.

**Plan research**
- `champion: null`.
- Real point-in-time track: "5 sessions, 28 needed".
- The modelled scenario track has 107,184 plan outcomes, which are labelled non-qualifying.

**Session direction model**
- "no edge out of sample" every session (AUC 0.47–0.51).

**Learning memory**
- Close-time grading ran every day: 51 / 135 / 300 / 176 news, ≈ 2,000–2,300 factor reads.
- Catch-up grading failed 8 of 8 times it had something to grade (A-02).

**Providers**
- Kotak served bars and chains on 10-05 … 10-09; Yahoo filled 1 of 558–567 polls on 10-08 and 10-09.
- LLM timeouts are logged on 10-05, 10-07 and 10-08 (Gemini 45 s, Ollama 90 s).

### A.5 Deterministic probes (`audit/probes/test_phase_a_probes.py`)

All 8 pass with the journal snapshot. Without it, 6 pass and 2 skip.

| Probe | Confirms |
|---|---|
| `test_rowcount_bucketing_makes_partial_last_bar` | A-05 |
| `test_rowcount_bucketing_on_real_recorded_session` (4/4 afternoon decisions on 2026-10-08 differ) | A-05, A-06 |
| `test_livelearner_records_nothing_without_registered_model` | A-01 |
| `test_lockbox_verify_silent_when_rowcount_changes` | A-07 |
| `test_build_samples_sig5_uses_later_bars` (and model features unchanged → V-03) | A-08, V-03 |
| `test_kotak_failure_silently_serves_yahoo_bars` | A-04 |
| `test_grade_news_uses_publish_time_not_seen_time` | A-09 |
| `test_persisted_state_facts` | A-01, A.4 |

### A.6 Reproduction of A-02 (read-only; runs on a copy of the journal)

```bash
git fetch origin journal && mkdir -p /tmp/qd && git archive FETCH_HEAD | tar -x -C /tmp/qd
python - /tmp/qd/intraday <<'EOF'
import sys, datetime as dt
from pathlib import Path
from quantdesk.journal.journal import Journal
from quantdesk.intraday import learning
from quantdesk.intraday.recorder import SessionRecorder
root = Path(sys.argv[1])
bars = SessionRecorder(root / "data").load_bars(["NIFTY", "BANKNIFTY"])
for unit in ("s", "ms", "us", "ns"):
    b = {k: v.set_axis(v.index.as_unit(unit)) for k, v in bars.items()}
    try:
        learning.grade_session(learning.Memory(None), Journal(root / "journal.db"), b, dt.date(2026, 10, 9)); print(unit, "OK")
    except Exception as e:
        print(unit, "FAIL", e)          # s, ms → "Cannot losslessly convert units" at learning.py:124
EOF
python -c "import yfinance as yf; print(yf.Ticker('^NSEI').history(period='2d', interval='1m').index.dtype)"   # datetime64[s, Asia/Kolkata]
```

### A.7 Baseline: the repository's own test suite

**Setup**
- Run in the same venv as the probes (pandas 3.0.6 / numpy 2.5.3 / yfinance 1.7.0), from the repo root, on
  2026-10-09.
- One pytest process per file, 4 in parallel, each capped at 300 s.
- The suite as one process did not finish within 20 min.

**Results**

| Outcome | Files | Tests |
|---|---|---|
| Green | 49 of 52 files | 423 tests in all files that finished |
| Failing: `tests/test_kotak.py` | 1 | `test_chain_from_the_live_book[live]` and `[docs]` (2 failures) |
| Over 300 s: `tests/test_handover.py`, `tests/test_plan_research.py` | 2 | slow, not failing: they pass in CI's full run (below) |

**Why `test_kotak` fails**
- This is a time bomb in the test, not a library-version problem: A-19.
- The fake chain's expiry is fixed at `EXP = dt.date(2026, 10, 6)` (`tests/test_kotak.py:24`).
- `KotakOptionChain.chain` stamps the snapshot with the wall clock (`kotak.py:288`).
- `time_to_expiry` (`chains.py:44-48`) is therefore 0 on any day after 2026-10-06 15:30, and every IV is `NaN`.
- So the test fails on `main` too, from that date on.

**CI confirmation**
- GitHub Actions `tests` on this PR (`ci.yml`, CI-resolved versions): **445 passed, 2 failed, 6 skipped** in
  15 min 27 s.
- The 2 failures are exactly the A-19 pair. The proposed patch is in the PR comment, not applied (read-only audit).

**Effect on the audit**
- The probes already cover A-02's real failure, and no existing test catches it.
- No test in the suite exercises a `datetime64[s]` bar index.

### A.8 Findings (detail in the register)

| Severity | Findings |
|---|---|
| P1 | **A-01**: the autolearn ledger has never recorded a live prediction. "Learns from its own predictions" is contradicted by the state. |
| P2 | **A-02**: catch-up grading broken. **A-03**: unpinned dependencies (its root cause). **A-04**: no per-bar provenance. **A-05**: live/training feature skew. **A-09**: news graded on the wrong clock. **A-10**: force-pushed, unanchored "append-only" state. |
| P3 | A-06, A-07, A-11, A-12, A-13, A-14, A-15, A-16 |
| P4 | A-08, A-17, A-18, A-19 |

No P0 in Phase A:
- nothing found can place a real order;
- no lookahead was found in decision-critical model features, labels, splits, chain replay or EOD context.

### A.9 Unresolved questions (carried forward)

| ID | Question | Where it will be settled |
|---|---|---|
| Q-01 | Kotak candle timestamp convention | Phase H |
| Q-02 | Does the suite pass on CI's versions? (Answered in § A.7: mostly. One date-dependent failure, A-19, and 2 slow files) | § A.7 |
| Q-03 | Is the empty plan registry (with `require_approved_model`) the dominant cause of zero trades? | Phases B4, K |
| Q-04 | What-if replays run without the learning memory, so `as_run` ≠ live | Phases B, K |
| Q-05 | Where is the pre-reset ₹20k account's journal? | Phase K |

---

## Phase B: Trading decision pipeline

Full report: `QUANTDESK_TRADING_STATE_MACHINE.md`.

### B.1 Objective

Trace market data → interpretation → setup → arm → trigger → authorization → execution. Find which inputs actually
reach a decision, how setups and triggers move through states, and where every opportunity of the recorded sessions
disappeared.

### B.2 Files and runtime paths traced

| Area | Code |
|---|---|
| Engine | `intraday/engine.py`: `step`, `_maybe_enter`, `_blocked`, `_by_record`, `_by_relative_strength`, `_model_gates`, `_approved`, `_select_by_ev`, `_open`, `_arm`, `_fire_armed`, `_chain_at`, `tick`, `_think`, `_persist`, `run_live` |
| Interpretation | `intraday/analyst.py` (all); `intraday/features.py` (all) |
| Setups | `intraday/playbook.py` (all) |
| Gating | `autolearn/live.py` (`plan_gate`, `entry_filter`) |
| Learning hooks | `intraday/learning.py` (`grade_armed`); `intraday/news.py` (`state`, `PREVIEW`) |
| Config | `config/quantdesk.yaml` (`intraday.*`) |
| Replay tooling | `deploy/whatif.py` |

### B.3 Evidence

- **The live journal:** 72 decision rows, 675 thoughts, 68 events.
- **An instrumented replay** of 2026-10-05 … 10-08 through today's engine with the **real recorded option chains**
  from `chains-2026` (`audit/probes/phase_b_replay_funnel.py` → `audit/data/phase_b_funnel.json`). On 10-05 it
  reproduces the live decisions exactly.
- **6 deterministic probes**, all passing (`audit/probes/test_phase_b_probes.py`).

### B.4 Findings (detail in the register)

| Severity | Findings |
|---|---|
| P2 | **B-01**: the weighted evidence can't reach an executed trade. **B-02**: zero trades is structural. **B-03**: confirm-path gate rejections are unjournaled and gates are unlabelled. **B-07**: armed-rejection learning is dead. |
| P3 | B-04, B-05, B-06, B-08, B-09, B-10, B-11 |
| Verified working | V-09 … V-12: setups are really generated; plans are fully specified before entry; the fail-closed gate holds; features are clock-correct |

### B.5 Unresolved (carried forward)

| ID | Question | Phase |
|---|---|---|
| Q-06 | Is the iron-fly EV right? | C3 |
| Q-07 | Does global-stress sizing ever bind? | F / K |
| Q-05 | The pre-reset account | K |

---

## Phase C: Models

Full report: `QUANTDESK_LEARNING_AUDIT.md`, Part C.

### C.1 Objective

For every model family (the session DirectionModel, the autolearn candidates, the plan policy, the EV/cost engine),
prove or break the chain: training → validation → promotion → persistence → future use → evaluation → update. Also
test the validation gates against pure noise.

### C.2 Files and runtime paths traced

| Area | Code |
|---|---|
| Direction and EV | `intraday/quant.py` (DirectionModel, EVEngine, `load_research`) |
| Autolearn models | `autolearn/models.py`, `autolearn/cycle.py` (dataset … promote, retention), `autolearn/registry.py` (call sites), `autolearn/policy.py`, `autolearn/research.py` (develop, run, lockbox, register, forward) |
| Costs | `execution/costs.py`, `autolearn/evaluate.py:CostModel` |
| Display | `web/intraday_api.py:_calibration` |
| Config | `config/quantdesk.yaml` (`intraday.quant`, `intraday.setups`, `autolearn.*`) |
| Tests | `tests/test_autolearn.py` |

### C.3 Evidence

- **Null simulations on synthetic random walks:**
  - the session DirectionModel validated in **20/200**;
  - the autolearn cycle registered **0/20**.
- **Recorded EV contexts** of the 51 iron-fly rejections.
- **4 deterministic probes**, all passing (`audit/probes/test_phase_c_probes.py`), including a stub "approve-everything"
  plan champion that still rejects the live desk's spread plans.

### C.4 Findings (detail in the register)

| Severity | Findings |
|---|---|
| P1 | **C-01**: even an approved plan model rejects every live directional plan (spread vs single-leg mismatch) |
| P2 | **C-02**: the session model's gate passes noise 10% of the time. **C-03**: no automatic demotion. **C-05**: the iron fly can't pay intraday |
| P3 | C-04, C-06, C-07, C-08 |
| Verified working | V-13 … V-17: the autolearn gate is strict on noise; the full chain works in tests; hashed artifacts; a rigorous plan protocol; the EV arithmetic is consistent |

**Bottom line.** Under the current code and config the intraday engine has **no reachable path to a paper trade**:
- directional plans are gated now (B-02) and would still be rejected after approval (C-01);
- the iron fly fails EV (C-05).

The only paper trades the desk makes are the pre-registered expiry-seller sleeves.

### C.5 Unresolved (carried forward)

| ID | Question | Phase |
|---|---|---|
| Q-07 | Does global-stress sizing ever bind? | F / K |
| Q-05 | The pre-reset account | K |
| — | The STT and statutory rates themselves, against an external source | F |

---

## Answers so far to the final questions

Answers are partial: only what Phases A–C support. Every other question is still open.

| # | Question | Answer so far |
|---|---|---|
| 1 | Is QuantDesk genuinely learning? | **Partly, and not via autolearn.** The autolearn loop retrains offline but has no live predictions (A-01). The memory grading runs at the close (A.4), but under the current gate it cannot change an executed decision except through the iron fly's \|score\| test (B-01). Phase D. |
| 3 | What learning changes future decisions? | **Today: almost none that reaches execution.** The autolearn models never registered (A-01); the plan model can't be fitted yet; even when approved it can't pass the live plans (C-01). The memory weights touch only the iron fly's \|score\| test (B-01). Phase D |
| 4 | Is learning point-in-time safe? | **Mostly; news learning is not** (A-09). Replay memory crosses time (A-15). |
| 10 | Are technical indicators actually used? | **Computed, weighted, stored and learned. For execution they matter only through** the iron fly's eligibility (day type: ADX, IB, OR; \|score\| ≤ 0.3) and the RSI veto. Every directional use is gated (B-01). |
| 11 | Is Volume Profile / Market Profile actually used? | **Yes, the session value area:** it decides the "balance" day type, which the only executable setup (iron fly) requires, and it bounds that trade. The prior-day value area is computed but never read (B-05). Market Profile (TPO) is used only as the volume fallback. |
| 12 | Are futures / OI / options / IV / gamma used? | **IV/RV: yes** (iron-fly eligibility, spread choice). **ATM spread / leg liquidity: yes** (vetoes, entry checks). **PCR, OI walls, futures OI, basis:** score only. **OI shift, skew trend:** zero weight. **Gamma/GEX, IV percentile:** display only. **Max pain:** unreachable (B-05). |
| 13 | Are setups actually detected? | **Yes** (V-09): 298 confirmed plans and 594 armed reads in 4 replayed sessions. |
| 14 | Are setups armed before authorization? | **Yes, and every one under the current config is then rejected** (B-06). |
| 15 | Can valid setups be hidden by later gates? | **Yes.** The plan-model gate removes 100% of directional setups. On the confirm path this writes no decision row (B-03). |
| 16 | Does the trigger engine work? | **Mechanically yes** (fires at the armed levels), with gaps: LTP sampling, the previous minute's veto view at fire time, re-fires (B-09). |
| 17 | Where do opportunities disappear? | No setup 70% · vetoes and window 20% · **plan-model gate 7% (every directional setup)** · **EV floor 2.5% (every iron fly)** · executed 0 (B-02). |
| 18 | Why did recent zero-trade sessions produce zero trades? | See B-02. Phase C adds: **directional trades stay impossible even after a plan model is approved** (C-01), and the iron fly cannot pay costs intraday (C-05). The engine has no reachable trade path. |
| 18 (cont.) | Phase B: **The directional gate needs 28 real point-in-time sessions (5 so far) and an approved model; the iron fly never cleared the EV floor; the rest was no setup or vetoed** (B-02). The gated opportunities averaged −0.07 R on the underlying: no sign the gate cost money. |
| 19 | Can every trade be reconstructed? | Untestable (0 trades). Gaps: A-04, A-10, A-13, B-03. |
| 20 | Can important rejected opportunities be reconstructed? | **Armed-path, EV, sizing and liquidity rejections: yes** (decision rows). **Confirm-path gate rejections: no**, sampled thoughts only (B-03). No opportunity ID; the gate is only in free text. |
| 24 | Can the system detect and correct degradation? | **Detect: partly** (drift report, PSI/ECE). **Correct: no automatic demotion or rollback** (C-03); the grading failure is only a WARN (A-02). Phase D8. |
| 25 | What is production-ready? (so far) | The fail-closed gating (V-11), the autolearn registration and lockbox discipline (V-13), hashed artifacts (V-15), the plan-research protocol (V-16), the ledger guards in code (V-01). None of them has produced a promoted model. |
| 26 | What is NOT trustworthy so far? | Cross-day state integrity (A-10); live-vs-training parity (A-05/06); news trust (A-09); catch-up grading (A-02); the "why not" record on the confirm path (B-03); armed-rejection learning (B-07); breaking-news vetoes (B-08); what-if `as_run` (B-11); the session DirectionModel's "validated" status (C-02); the path to any directional trade (C-01). |

## Scorecard (rows filled only where Phases A–C have evidence)

| Area | Status | Severity | Evidence |
|---|---|---|---|
| Data integrity | PARTIAL | P2 | A-04, A-06, A-12, A-14, A-16 |
| Point-in-time safety | PARTIAL | P2 | clean features, labels and splits (V-02, V-03, V-05, V-12); A-05, A-09, A-15 |
| Technical analysis | PARTIAL | P2 | computed correctly on clock-completed bars (V-12); no causal path to execution except iron-fly eligibility and the RSI veto (B-01); OR/IB from the first bar present (B-10) |
| Setup detection | VERIFIED (mechanics) | P3 | V-09, V-10; dead or display-only inputs (B-05) |
| Trigger / arming | PARTIAL | P3 | fires at the levels; arms before authorization (B-06); not persisted (B-04); sampling and race gaps (B-09) |
| Models | PARTIAL | P1 | the autolearn gate is strict on noise (V-13) and the chain works in tests (V-14), but never in production (A-01); session-model gate weak (C-02); plan model unfitted, and incompatible with the live plans (C-01); no automatic demotion (C-03); EV consistent (V-17), uncalibrated (C-06) |
| Execution (reachability) | BROKEN | P1 | no reachable path to an engine trade: B-02 + C-01 + C-05 |
| No-trade learning | BROKEN (armed path) | P2 | B-07 (Phase D will complete) |
| Reliability (foundation) | PARTIAL | P2 | A-02, A-03, A-10 |
| Auditability | PARTIAL | P2 | A-10, A-13, B-03, B-11 |
| Factor/regime learning, baseline, research validity, options/futures, fills, AI, UI truthfulness, self-correction | not yet audited | — | Phases D–L |
