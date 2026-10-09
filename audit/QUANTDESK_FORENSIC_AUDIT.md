# QuantDesk Forensic Audit

Read-only, evidence-first, one phase at a time. No production code, config, data, spec, result, risk parameter or
workflow was changed. The only files written are under `audit/`.

| Artifact | Status |
|---|---|
| `QUANTDESK_FORENSIC_AUDIT.md` (this file) | live: the phase log, answers so far, scorecard |
| `QUANTDESK_FINDINGS_REGISTER.md` | live: every finding, cumulative |
| `QUANTDESK_ARCHITECTURE_MAP.md` | Phase A1: done |
| `QUANTDESK_DATA_LINEAGE.md` | Phases A2 + A3: done |
| `QUANTDESK_TRADING_STATE_MACHINE.md` | Phase B: pending |
| `QUANTDESK_LEARNING_AUDIT.md` | Phases C/D: pending |
| `QUANTDESK_AI_AUDIT.md` | Phase G: pending |
| `QUANTDESK_RESEARCH_VALIDITY.md` | Phase E: pending |
| `QUANTDESK_REMEDIATION_PLAN.md` | at the end |
| `QUANTDESK_TEST_PLAN.md` | at the end; the Phase A probes are in `audit/probes/` |

## Phase tracker

| Phase | Scope | Status |
|---|---|---|
| A | System foundation: architecture, lineage, point-in-time | **done, awaiting review** |
| B | Trading decision pipeline: interpretation, setups, state machine, funnel, triggers | not started |
| C | Models: direction, plan, EV/cost | not started |
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
| Over 300 s: `tests/test_handover.py`, `tests/test_plan_research.py` | 2 | re-running with a 25-minute cap; result below |

**Why `test_kotak` fails**
- This is a time bomb in the test, not a library-version problem: A-19.
- The fake chain's expiry is fixed at `EXP = dt.date(2026, 10, 6)` (`tests/test_kotak.py:24`).
- `KotakOptionChain.chain` stamps the snapshot with the wall clock (`kotak.py:288`).
- `time_to_expiry` (`chains.py:44-48`) is therefore 0 on any day after 2026-10-06 15:30, and every IV is `NaN`.
- So the test fails on `main` too, from that date on.

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

## Answers so far to the final questions

Answers are partial: only what Phase A evidence supports. Every other question is still open.

| # | Question | Phase A answer |
|---|---|---|
| 1 | Is QuantDesk genuinely learning? | **Partly, and not via autolearn.** The autolearn loop retrains offline each day, but has no live predictions (A-01) and has promoted nothing. The memory-based grading of factors and news runs at the close (A.4). Whether it changes decisions is Phase D. |
| 4 | Is learning point-in-time safe? | **Mostly; news learning is not.** The order of updates is safe. News is graded on publish time the desk never had (A-09). Replay memory crosses time (A-15). The ledger guards are correct but unexercised. |
| 19 | Can every trade be reconstructed? | **Untestable so far:** 0 trades in the state. Structural gaps: no per-bar provenance (A-04), back-dated events (A-13), snapshot-only history (A-10). |
| 24 | Can the system detect and correct degradation? | **Partly:** the grading failure is logged only as a WARN and recurs daily without escalation (A-02). Phase D8. |
| 26 | What is NOT trustworthy (so far)? | Cross-day integrity of the journal-branch state (A-10); live-vs-training feature parity (A-05/06); the news trust multipliers (A-09); the catch-up grading (A-02). |

## Scorecard (rows filled only where Phase A has evidence)

| Area | Status | Severity | Evidence |
|---|---|---|---|
| Data integrity | PARTIAL | P2 | validation exists (`validate_bars`, warehouse manifest SHA); provenance lost per bar (A-04); revisions silent (A-12, A-14); hand-over hole (A-06); zero-volume sessions (A-16) |
| Point-in-time safety | PARTIAL | P2 | features, labels and splits clean (V-02, V-03, V-05); live/train skew (A-05); news clock (A-09); replay memory (A-15) |
| Reliability (foundation) | PARTIAL | P2 | unpinned dependencies broke learning (A-02, A-03); last-writer-wins state (A-10) |
| Auditability (foundation) | PARTIAL | P2 | no state history (A-10); back-dated events (A-13) |
| Technical analysis, setup detection, trigger/arming, models, factor/regime/no-trade learning, baseline, research validity, options/futures, execution, AI, UI truthfulness, self-correction | not yet audited | — | Phases B–L |
