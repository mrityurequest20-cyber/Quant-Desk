# QuantDesk: Post-Phase-G Consolidation and Gap Analysis

Read-only. This is a decision document; it does not change the canonical register (`QUANTDESK_FINDINGS_REGISTER.md`)
or any phase report. **Local and uncommitted** at the time of writing. Date: 2026-10-09, after the 15:31 IST close.

---

## 1. Executive verdict

1. **The master protocol does not permit closing the audit.** It defines phases A–L and says "Do not silently skip
   phases". Phases H–L, two deterministic tests (crash and restart) and the two closing artifacts (remediation plan,
   test plan) are not done.
2. **Recommendation: A, start Phase H with a narrow scope** (§7).
   - Much of H's protocol list was already examined incidentally in A–G, so H must cover only what is still unexamined:
     - scheduler, heartbeat and missed sessions;
     - crash and restart recovery (deterministic tests 8 and 16);
     - kill switch;
     - retries and rate limits;
     - secrets and alerting;
     - storage, performance and rebuild time;
     - a provider-by-provider sweep for "failure → valid-looking data".
3. **A–G stand on re-verification.** Today I re-checked the consequential claims against the newer journal snapshot
   (`journal@0143b5c`, 10-09 close) and the live GitHub state. Nothing contradicts them.
   - Several claims gained evidence:
     - **E-01:** the desk's own 10-09 `official` events reproduce my earlier SENSEX arithmetic exactly (−₹7,342.81, −₹7,945.26).
     - **E-01, F-02:** the index froze again on 10-09 (14 minutes).
     - **D-01:** the placebo p is 0.57 on the extended sample.
     - **A-02:** grading failed twice again on 10-09.
     - **B-02:** still 0 trades.
4. **The system has no P0 finding.** Real money is technically unreachable (V-38).
5. **There are five P1 findings: A-01, C-01, D-01, E-01, G-01.** They trace to **five root causes** (§4). Two of them
   need decisions, not code:
   - the gate architecture (why nothing can trade);
   - governance (who may change the desk).
6. **One governance item is time-sensitive:** the engineer routine fires again 2026-10-10 17:40 IST into a session
   that can merge to an unprotected `main` (§6, §11).

---

## 2. Master-protocol scope and source availability

**Source.** The protocol ("QUANTDESK FORENSIC AUDIT — MASTER PROTOCOL", 16,654 characters) was **found verbatim** in
this session's original conversation record (the first user message, 2026-10-09T07:17Z) and re-read in full for this
review. It is authoritative here. No requirement below is inferred from a phase name.

### Scope by phase (exact protocol headings)

| Phase | Scope |
|---|---|
| A | A1 architecture; A2 data lineage; A3 point-in-time / leakage |
| B | B1 market interpretation (per-feature detected → transformed → used → weighted → stored → learned); B2 setup detection; B3 state machine; B4 funnel (incl. "did price later reach the trigger"); B5 trigger engine |
| C | C1 direction models; C2 plan models; C3 EV and cost |
| D | D1 ledger; D2 factor learning; D3 lifecycle; D4 recency; D5 regime; D6 no-trade; D7 baseline/control; D8 self-correction |
| E | Research validity, plus the DISCOVERED → … → APPROVED ladder per strategy |
| F | Options, futures, execution, and "verify displayed information actually affects decisions" |
| G | AI: trace each component INPUT → … → FUTURE USE; authority classes; failure modes. "AI must not silently become uncontrolled trading authority" |
| **H** | **Provider failure, fallback, stale data, missing snapshots, retries, rate limits, scheduler, heartbeat, crash recovery, restart recovery, kill switch, secrets, logging, alerts, storage, performance, rebuild time. "A failure must never silently become valid-looking data."** |
| **I** | **Can the system reconstruct: why we traded, why we didn't, what it knew then, what model/factor/news/regime information was used, what would have happened, what it learned? Can a historical decision be replayed from persisted evidence alone?** |
| **J** | **UI claims vs backend (15 named claims: learning, learned ×, factor weights, IC, champion, challenger, probation, research drift, standing aside, no-trade reasons, model status, Brain, indicators, global intelligence, opportunity status), each classified BACKEND-REAL / DISPLAY-ONLY / PARTIAL / MISLEADING** |
| **K** | **Real-session forensics: representative sessions (profitable/trading, zero-trade, trending, reversing, event-driven, degraded), each reconstructed end to end and compared with the journal and UI** |
| **L** | **Adversarial: actively falsify the major claims (15 listed attack classes). "Do not stop after proving the happy path."** |

### Mandatory method and evidence rules

- §1 the causal-chain proof standard;
- §2 runtime-first tracing;
- §3 claim → reality;
- §4 the status and severity vocabulary ("do not inflate");
- §5 negative-claim discipline;
- §6 the 12 forensic questions per subsystem;
- §10 the finding format.

### Deliverables and exit criteria

| Item | Requirement |
|---|---|
| §8 | 17 deterministic tests "where practical" |
| §9 | One phase at a time; "Do not silently skip phases"; a cumulative register |
| §11 | 10 artifacts |
| §12 | Final scorecard (18 areas) and the final report sections (WHAT WORKS … FINAL VERDICT) |
| §13 | 26 final questions the completed audit **must** answer |
| ABSOLUTE RULE | "PROVE THE CHAIN" MARKET DATA → … → FUTURE DECISION; "the audit is complete only when you can explain, with repository evidence, why QuantDesk behaved the way it did" |

**Dependencies between phases.** The protocol states none. The natural ones:
- I (auditability) and K (session forensics) reuse H's provider-failure facts;
- K needs B's funnel;
- L attacks everything.

**Outstanding after G:**
- phases H, I, J, K and L;
- deterministic tests 8 and 16;
- artifacts 9 and 10 (remediation plan, test plan);
- the final report sections;
- final answers to Q19, Q20, Q24, Q25 and Q26, which are provisional and depend on H–L.

---

## 3. Consolidated A–G findings

### Legend

| Code | Meaning |
|---|---|
| **Class** | **D** confirmed defect · **L** latent unsafe path (reachable code, not yet triggered) · **H** unverified hypothesis · **G** evidence/coverage gap |
| **Evidence** | **PO** production observation · **AR** archived replay · **ST** synthetic test · **CI** code inspection · **INF** inference · **EXT** external source |
| **Repro** | **Y** = re-executed or re-observed by a second method or on a later snapshot (today's re-runs count) · **P** = a deterministic probe exists, run by the same auditor · **N** = single observation or inference |
| **Blocks** | **P** safe paper trading · **R** trustworthy research · **A** autonomous engineering · **L** eventual live trading |

**Caveat on "independent".** Every finding comes from one auditor (this agent), so no finding has been reproduced by an
*independent party*.

**Note on status labels.** Phase statuses describe the *claim* the finding tests. "VERIFIED" on a finding means the
*defect* is verified; it does not mean the feature works.

Severity and status are copied unchanged from the register.

| ID | Sev | Status | Component / behaviour | Evid. | Repro | Class | Blocks | Overlaps / depends | Acceptance test for closure |
|---|---|---|---|---|---|---|---|---|---|
| A-01 | P1 | CONTRADICTED | `autolearn/live.py`: the ledger never records a live prediction | PO ST | P | D | R L | ← C-01, B-02 (no registered model) | ≥ 1 live prediction per session for a registered model, outcome joined; probe flips |
| A-02 | P2 | BROKEN | Catch-up grading crash (time units) | PO | **Y** (2 failures on 10-09) | D | R | ← A-03; hidden by D-07 | 5 sessions with 0 "grading failed"; unit test across s/ms/us/ns |
| A-03 | P2 | VERIFIED | Unpinned dependencies | CI | P | D | R A L | root of A-02 | Lockfile; CI installs from it |
| A-04 | P2 | PARTIAL | Feed fallback has no per-bar source | ST | P | D | P R | family RC2 with F-01, F-02 | Every bar carries its source; mixed sessions flagged |
| A-05 | P2 | BROKEN (latent) | Live 5-minute bucketing ≠ training | ST AR | P | L | P L | latent while C-01 holds | Live/training feature-parity test on a recorded session |
| A-06 | P3 | VERIFIED | 12:20 hand-over hole | PO | P | D | P R | → B-10; H scope | No unmarked gap minutes |
| A-07 | P3 | CONTRADICTED | `LockBox.verify` ignores row-count change | ST | P | D | R | — | Verify fails on any change |
| A-08 | P4 | VERIFIED | σ back-filled from later bars | ST | P | D | R | — | Probe flips |
| A-09 | P2 | MISLEADING | News graded from publish time | ST | P | D | R | ↔ G-04, G-05 | Grading keyed on `seen_at` |
| A-10 | P2 | MISLEADING | Force-pushed journal; unanchored hashes | PO CI | P | D | R A L | I scope | Append-only or anchored history; tamper test |
| A-11 | P3 | PARTIAL | Chain fetch time ≠ quote time; IV from stale LTP | CI | N | H | P | ↔ F-01, F-04 | Quote timestamps stored; LTP-IV flagged |
| A-12 | P3 | VERIFIED | Yahoo history unstable intraday | PO | N | D | R | ↔ E-06 | Archived inputs; refit reproduces |
| A-13 | P3 | VERIFIED | Afternoon events back-dated | PO | P | D | R | I scope | Event time = actual time |
| A-14 | P3 | VERIFIED | Warehouse overwrites rows | CI | Y (v2 unaffected, V-21) | D | R | ↔ E-06 | Versioned rows or per-day digests |
| A-15 | P3 | VERIFIED (code path) | Replay memory leaks across replays | CI | N | L | R | — | Replay-isolation test |
| A-16 | P3 | VERIFIED | Futures volume gaps → 0 | PO | P | D | P | RC2 | Gaps as NaN, flagged |
| A-17 | P4 | VERIFIED (code path) | Kite ticks stamped with the wall clock | CI | N | L | L | ↔ F-06 | Exchange time required |
| A-18 | P4 | VERIFIED (code path) | Yahoo 5m `completed()` length | CI | N | L | P | — | Probe |
| A-19 | P4 | VERIFIED | Date-bomb test; CI red on `main` | PO | **Y** (CI today) | D | **A** | blocks the required-check control for G-01 | Suite green on any date (frozen clock) |
| B-01 | P2 | MISLEADING | Evidence score ↛ trade | CI AR | P | D | P R | ← B-02 | Path documented, or README corrected |
| B-02 | P2 | VERIFIED | Zero trades is structural | PO AR | **Y** (0 trades on 10-09) | D | P R L | ← C-01, C-05, A-01 | Deterministic e2e simulated trade passes the gates (R4) |
| B-03 | P2 | VERIFIED | Confirm-path rejections unjournaled | PO | P | D | R | I scope | Every rejection row: gate id + setup id |
| B-04 | P3 | VERIFIED | Armed lifecycle not persisted | CI PO | P | D | P R | H/I scope (restart) | Survives restart in a test |
| B-05 | P3 | VERIFIED | Dead / display-only features | CI | P | D | R | J scope | Wired or labelled |
| B-06 | P3 | MISLEADING | "Waiting at the level" though unauthorisable | CI | P | D | R | ← B-02; J | UI shows the blocking gate |
| B-07 | P2 | BROKEN | Plan-gate rejections never graded | CI ST | P | D | R | ↔ D-05 | Probe flips |
| B-08 | P3 | VERIFIED | Breaking-news veto false positives | ST | P | D | P | — | Probes flip |
| B-09 | P3 | PARTIAL | Trigger engine gaps | CI PO | N | D | P | — | Tick-level replay test |
| B-10 | P3 | VERIFIED | OR/IB from the first bar present | CI PO | N | D | P | ← A-06 | Anchored to 09:15 |
| B-11 | P3 | MISLEADING | What-if `as_run` ≠ what ran | CI | N | D | R | I/K scope | `as_run` replay = journal |
| C-01 | P1 | BROKEN (latent) | Approved plan model still rejects spreads | ST | P | L | P R | RC1 | Approved model + spread plan passes, in a test |
| C-02 | P2 | VERIFIED | Session model passes noise 10% | ST | Y (200 sims) | D | R | RC3 | Null pass rate ≤ stated α |
| C-03 | P2 | VERIFIED (missing) | No auto demotion | CI | P | D | R L | — | Degraded champion demoted in a test |
| C-04 | P3 | CONTRADICTED | Two cost models | CI | P | D | R | ↔ F-05, E-03 | One cost source |
| C-05 | P2 | VERIFIED | Iron fly can't pay its costs | PO CI | N | D | P | RC1 | Design decision recorded |
| C-06 | P3 | PARTIAL | EV uncalibrated | CI | N | G | P L | needs trades (← B-02) | Calibration on realised outcomes |
| C-07 | P3 | PARTIAL | Lockbox peeks unbounded | CI | N | D | R | — | Peek budget enforced |
| C-08 | P3 | VERIFIED | Feature-version hash on source text | CI | N | D | P | — | Semantic version test |
| D-01 | P1 | MISLEADING | Factor learning ≈ noise | AR | **Y** (p 0.57 on 10-09 data) | D | R | RC3; ↔ C-02, G-05 | Placebo p < α on a new sample, or claims withdrawn |
| D-02 | P2 | VERIFIED | Learning changes 0.07% of decisions | AR | N | D | R | ← B-01 | Measured effect with a CI |
| D-03 | P2 | VERIFIED | Memory aggregate-only, unreplayable | PO | P | D | R | I scope | Event-level ledger replays |
| D-04 | P2 | VERIFIED | No recency, regime or demotion | ST | P | D | R | RC3 | Probes flip |
| D-05 | P2 | BROKEN | No-trade learning absent | CI PO | N | D | R | ↔ B-07 | Counterfactual grading runs |
| D-06 | P3 | VERIFIED | No baseline or control | CI | N | D | R | RC3 | ON/OFF control with power |
| D-07 | P2 | VERIFIED | Self-review blind to WARN | ST | P | D | A | ↔ G-05, A-02; H scope | WARN failures raise issues |
| D-08 | P4 | VERIFIED | Truncated ids regraded | ST | P | L | R | — | Probe flips |
| E-01 | P1 | MISLEADING | Sleeves settle on a frozen index | PO | **Y** (desk's own 10-09 events) | D | P R L | ← F-02 (root) | Official-close settlement; flat-run quarantine; ledger re-derived under a new spec |
| E-02 | P2 | VERIFIED | Paper gate passes zero edge ≈ 93% | ST INF | P | D | R L | RC3 | False eligibility ≤ 5% under the null |
| E-03 | P3 | PARTIAL | D1 drift in live EV, unregistered | CI AR INF | P | D/H | R | ↔ C-04, C-06 | Registered, or removed |
| E-04 | P2 | PARTIAL | No program-wide multiplicity | CI PO | P | D | R | RC3 | Ledger complete; family count reported |
| E-05 | P3 | PARTIAL | v2 reuses the holdout; no frozen sample | PO | Y | D | R | RC4 | Specs fix the sample end |
| E-06 | P3 | PARTIAL | Result provenance gaps | PO | P | D | R | ↔ A-12, A-14; RC4 | Every result stamped, clean tree |
| E-07 | P3 | UNVERIFIED | L1 economics on illiquid held-out names | PO | N | G | R L | ← F-04 | Recorded quotes; entry_v1 decided |
| E-08 | P3 | PARTIAL | L3 baseline ≠ live forecaster | CI | P | D | R | — | Re-run vs the live forecaster |
| E-09 | P4 | PARTIAL | External data verified shallowly | CI | N | G | R | — | Minute-level checks |
| F-01 | P2 | VERIFIED (latent) | Model-chain fallback tradeable; fabricated OI votes | ST CI | P | L | P L | RC2; ↔ A-04 | Fault-injection: no entry on a model chain |
| F-02 | P2 | VERIFIED | Vendor index freeze 15:15–15:28 | PO | **Y** (10-09) | D | P R | root of E-01; RC2 | Detection and quarantine test |
| F-03 | P4 | PARTIAL | Skew-level bias | AR | N | D | R | — | IV on the implied forward |
| F-04 | P3 | PARTIAL (latent) | Fills ignore depth | ST AR | P | L | P L | ↔ E-07, A-11 | Depth-capped fill test |
| F-05 | P4 | PARTIAL | Exercise STT 0.125% vs 0.15% | CI EXT | P | D | R L | ↔ C-04 | Dated rate |
| F-06 | P3 | BROKEN (latent) | Kite partial fills dropped | ST | P | L | L | ↔ A-17 | Partial-fill accounting test |
| F-07 | P4 | VERIFIED | Calendar ends 2026 | ST | P | L | P | — | Fail closed on a missing year |
| G-01 | P1 | VERIFIED | Engineer: unreviewed merge authority | PO CI | **Y** (GitHub re-read today) | D | **A** (indirectly all) | RC4; ↔ A-19 | Test PR blocked without human approval (§6) |
| G-02 | P2 | CONTRADICTED | Documented autonomy ≠ observed | PO | Y | D | A | RC4 | Owner decision (Q-13) recorded; shift reports |
| G-03 | P3 | VERIFIED (latent) | Malformed LLM output → confident read | ST | P | L | P | — | Probe flips |
| G-04 | P3 | VERIFIED | No model/prompt provenance | CI ST | P | D | R | ↔ A-09 | Model, prompt hash and raw text stored |
| G-05 | P3 | VERIFIED | LLM failures at INFO; trust untested | PO | Y | D | A R | ↔ D-07, D-01 | WARN plus CI on trust |
| G-06 | P4 | VERIFIED | Claude never ran; cost untracked | PO | Y | D | — | — | Cost per provider recorded |

### Counts

| Group | Count |
|---|---|
| Findings | 68 |
| P0 / P1 / P2 / P3 / P4 | 0 / 5 / 23 / 30 / 10 |
| Confirmed defects (D) | 52 |
| Defect and hypothesis mixed (D/H) | 1: E-03 (the cost-of-the-same-order claim is inference) |
| Latent unsafe paths (L) | 11: A-05, A-15, A-17, A-18, C-01, D-08, F-01, F-04, F-06, F-07, G-03 |
| Unverified hypotheses (H) | 1: A-11 (Kotak payload never inspected live) |
| Evidence / coverage gaps (G) | 3: C-06, E-07, E-09 |

### Components that passed their defined checks (V-01 … V-38)

- point-in-time features, labels and replays (V-02 … V-06);
- fail-closed gating (V-11);
- the autolearn registration gate on noise (V-13);
- hashed artifacts (V-15);
- L1 reproduction and robustness (V-21 … V-24);
- statistics code (V-23);
- contract identity and pricing (V-27, V-28);
- the candle-label convention (V-29);
- live-order guards (V-31);
- LLM bounding inside the engine (V-34 … V-37);
- real money unreachable (V-38).

Each passing probe covers **only** the behaviour it tests, not its whole subsystem.

---

## 4. Cross-phase dependency map

### The seven relationships, each re-checked today

The code has not changed: `main` is still `c96909f`.

```
(1) DATA → SETTLEMENT → STRATEGY CLAIMS
    F-02 vendor index freeze (re-seen 10-09) ──► E-01 sleeve settlement on the 15:00–15:29 mean (half frozen)
       ├─► sleeve rules (cost check, consistency z, eligibility) run on the wrong P&L ──► E-02 gate (already powerless)
       ├─► F-02: basis after 15:15, 10.5% of factor grades ──► D-01 input contaminated (D-01 holds anyway)
       └─► L1's only forward evidence (4 trades) is mis-settled; history settles on official closes (V-21) ──► E-07 open

(2) MODEL CHAIN → FABRICATED OI → ELIGIBILITY
    Kotak + NSE fail ─► F-01 model chain (no stale gate) ─► OI walls vote (0.4) ─► score ─► iron fly |score|≤0.3
    eligibility ─► EV (C-05: never passes today) ─► latent; on any future EV-passing setup, fills at modelled quotes

(3) GATES → NO TRADES → NO EVIDENCE
    plan registry empty (A-01) + plan gate single-leg only (C-01) ─► every directional plan rejected
    iron fly uneconomic intraday (C-05) ─────────────────────────► every non-directional plan rejected
    ═► B-02: 0 trades (re-seen 10-09) ═► no calibration (C-06), no fill evidence (F-04 latent), no trade learning,
       an unreachable stress sizing (Q-07), a learning ledger with no outcomes (A-01)

(4) PAPER FILLS → P&L RELIABILITY
    F-04 depth ignored + A-11 stale quote time + F-01 model quotes + F-05/C-04 cost drift
       ─► engine P&L would be optimistic, but has 0 trades (latent)
    sleeves: real 15:20 quotes and a cost gap logged (V-25), but settlement wrong (E-01)

(5) LEARNING → INFLUENCE
    D-01 (noise) + D-04 (no recency/demotion) + G-05 (reader trust untested) ─► weights
       ─► B-01: the score's only routes to a trade are closed ─► D-02: 0.07% of decisions change, 0 trades

(6) HOLDOUTS → REPRODUCIBILITY → ECONOMICS
    V-21/V-24 (L1 robust, reproduces) ── but E-05 (one holdout exposure), E-04 (no family count),
    E-06/A-14 (provenance) ─► statistically sound, economically unproven: E-07 + E-01 + F-04 + entry_v1 (0 decided)

(7) GOVERNANCE
    unprotected main + 0 PRs + same-model reviewers (G-01) ─► can change any node above
    A-19 keeps CI red ─► "no red pushes" can be neither honoured nor enforced as a required check
    risk-limit tests read config ─► loosening passes · spec guard only for specs with results ─► the record is mutable
    A-03 unpinned deps ─► the same code can behave differently tomorrow (A-02)
```

### Root causes (the smallest set that explains most findings)

| RC | Root cause | Explains | Fix type |
|---|---|---|---|
| **RC1** | **The authorization chain is closed by design mismatch:** a gate that needs a model that cannot exist for the plans the desk builds, plus the only alternative being uneconomic | A-01, B-01, B-02, B-06, B-07, C-01, C-05, C-06, D-02, D-05, Q-07, and the latency of A-05, F-04, F-06 (~14) | **A decision first** (the research says direction is unpredictable, N1), then code |
| **RC2** | **No data-validity layer:** provenance, freshness and quarantine are not first-class, so failures become valid-looking data | A-04, A-06, A-11, A-16, B-10, E-01, F-01, F-02, A-12, A-14, E-06, G-04 (~12) | Code (detection, quarantine, fail-closed) |
| **RC3** | **Adoption without nulls:** signals and gates are adopted on point estimates with no placebo or CI | C-02, D-01, D-04, D-06, E-02, E-03, E-04, G-05 (~8) | Method: tests and relabelling before code |
| **RC4** | **Unenforced governance and integrity:** prose limits, unprotected `main`, mutable records, drifting dependencies | G-01, G-02, A-03, A-19, A-10, E-05, E-06, D-07 (~8) | Settings plus tests |
| **RC5** | **Observability gaps:** state and rejections not persisted or not surfaced | B-03, B-04, B-11, A-13, D-03, D-07, G-05 (~7) | Mostly H/I scope, **not yet audited** |

A rewrite is **not** indicated. Each RC is local: one gate decision, one data-validity layer, one statistical-method
rule, one governance setting, one logging pass.

---

## 5. Mandatory audit coverage matrix

**Gap types:**

| Code | Meaning |
|---|---|
| **MAG** | mandatory audit gap |
| **REM** | remediation item (understood) |
| **VAL** | validation gap |
| **OPT** | optional |

| Protocol requirement | Addressed in (artifact) | Evidence | Verification status | Remaining gap | Type |
|---|---|---|---|---|---|
| §1–6 method rules (chain proof, runtime-first, claim → reality, vocabulary, negative-claim discipline, 12 questions) | all phase reports; register (file:line refs) | per finding | Applied | Some register statuses mix claim and defect wording | OPT |
| A1 architecture | ARCHITECTURE_MAP | CI | Done | — | — |
| A2 lineage | DATA_LINEAGE | CI PO | Done | — | — |
| A3 PIT / leakage | DATA_LINEAGE, V-02 … V-06 | ST CI | Done | — | — |
| B1–B5 | TRADING_STATE_MACHINE | AR PO ST | Done | B4 "did price later reach the trigger" done for one replay set (−0.07 R on 133) | VAL (K extends it) |
| C1–C3 | LEARNING_AUDIT (C) | ST AR PO | Done | EV calibration impossible (0 trades) | VAL |
| D1–D8 | LEARNING_AUDIT (D) | AR ST PO | Done | — | — |
| E (16 items + ladder) | RESEARCH_VALIDITY | AR PO ST | Done | Illiquid economics, entry_v1 pending | VAL |
| F (17 items + displayed vs decision) | OPTIONS_EXECUTION | PO AR ST EXT | Done | No live broker evidence (forbidden) | VAL |
| G (trace, authority, 11 failure modes) | AI_AUDIT | PO ST CI | Done | No live-model adversarial test (read-only) | OPT |
| **H** data, reliability, operations (17 items) | partly touched: A-02, A-04, A-06, A-10, D-07, E-01, F-01, F-02, G-05 | partial | **Not audited as a phase** | scheduler, heartbeat, crash and restart, kill switch, retries, rate limits, secrets, alerts, storage, performance, rebuild time | **MAG** |
| **I** journal / auditability (6 questions + replay) | partly touched: B-03, B-04, B-11, D-03, A-10, A-13 | partial | **Not audited** | Systematic reconstruction test per question; replay from persisted evidence alone | **MAG** |
| **J** UI truthfulness (15 claims) | partly touched: B-05, B-06, C-06 | partial | **Not audited** | Each UI claim classified BACKEND-REAL / DISPLAY-ONLY / PARTIAL / MISLEADING | **MAG** |
| **K** real-session forensics (6 session types) | B replay of 4 sessions (zero-trade) | AR | **Not audited** | Trending, reversing, event-driven and degraded sessions; journal/UI comparison. "Profitable/trading": none exist (0 trades) | **MAG** |
| **L** adversarial (15 classes) | many attacked in passing (leakage V-02…, duplicates D-08, stale data F-02, hidden fallback A-04/F-01) | partial | **Not audited as a phase** | Systematic falsification pass | **MAG** |
| §8 tests 1, 2, 3, 9, 10, 12, 15, 17 | B, C, D, G probes and replays | ST AR | Done | — | — |
| §8 tests 4 (risk rejects), 5 (rejected later triggers), 6 (late outcome), 7 (duplicate outcome), 11 (regime change), 13 (no-trade counterfactual), 14 (stale chain/provider) | partial: C-05 sizing → 0 lots; B4 counterfactual; D-08; V-01; D-04; D-05; F-01 | ST AR CI | Partial | Explicit tests for 4, 6, 11, 13, 14 | VAL (H/L) |
| §8 test 8 (crash between ledger and state update) | — | — | **Not run** | — | **MAG (H)** |
| §8 test 16 (restart / recovery) | — | — | **Not run** | — | **MAG (H)** |
| §11 artifacts 1–8 | present | — | Done | — | — |
| §11 artifacts 9–10 (remediation plan, test plan) | — | — | **Missing** (protocol: "at the end") | — | **MAG (closing)** |
| §12 scorecard, 18 rows | FORENSIC_AUDIT | — | 16 filled | UI truthfulness pending; Reliability and Auditability are "foundation only" | **MAG (J, H, I)** |
| §12 final report sections | — | — | **Not written** | — | **MAG (closing)** |
| §13 Q1–18, 21–23 | FORENSIC_AUDIT | — | Answered | — | — |
| §13 Q19, Q20, Q24, Q25, Q26 | FORENSIC_AUDIT | — | **Provisional** | Need H, I, K, L | **MAG** |
| ABSOLUTE RULE ("explain why it behaved as it did") | B-02, C-01, C-05 | PO AR | **Met for the zero-trade behaviour** | Chain past EXECUTION is untestable in production (no trades); needs the deterministic e2e test | VAL |

---

## 6. Governance assessment (G-01 and G-02 separately)

Re-verified today, 2026-10-09, read-only.

| Question | Evidence | Answer |
|---|---|---|
| Can the engineer modify and merge consequential changes without human approval? | `main` `protected: false`; PR #9 (this audit) is the only PR in the repo's history; 112 of 114 `main` commits are Claude's, pushed directly; AUTONOMY.md "merge the branch into main … the owner is not in the loop" | **Yes** (G-01) |
| Are branch protections and required checks enforced? | No protection on any branch; no CODEOWNERS; `ci.yml` runs but is not required, and is red on `main` (A-19) | **No** |
| Do the risk-limit tests survive a loosened config? | `tests/test_intraday.py:312-313` derives its thresholds from `cfg.get("intraday.risk.daily_loss_limit")` (probe) | **No.** Loosening passes. |
| Can registered specs and results be altered or deleted undetected? | `test_every_recorded_result_matches_its_spec_as_registered` guards only specs that have results; sleeve and entry-check specs are unguarded; deleting a result together with an edit passes (probe) | **Partly** |
| Can it change its own schedule or permissions? | The session's tools include `create_trigger`, `update_trigger`, `delete_trigger`, `fire_trigger`; `permission_mode: auto` | **Schedule: yes.** GitHub permissions: no evidence of the tools needed |
| Does the documented autonomy match the observed behaviour? | No `main` commit since 10-04; audit issues #6–#8 open (#6 overdue); session blocked "need_input" after the owner rejected a tool call at 12:21 UTC; scorecard owner_found 8 vs self_found 2 | **No** (G-02) |

**Time-sensitive.** The routine "Quant-Desk engineer shift" fires next at **2026-10-10 12:10 UTC (17:40 IST)** and
delivers a new "Shift time … every judgement call is yours" turn into the same session. Today's block is therefore
**not durable**: the next shift can resume and merge to `main`. The real-money barrier is technical and unaffected
(V-38).

### Controls to implement and independently verify before consequential autonomous merges

1. **Protect `main`:** pull request required, one human approval, dismiss stale approvals, no force-push or deletion,
   **required status check: CI**.
   - *Dependency:* A-19 must be fixed first, or every merge blocks.
   - *Verification:* a test PR from the engineer cannot merge without the owner's approval.
2. **CODEOWNERS** (owner) on:
   - `quantdesk/intraday/{engine,risk,playbook,sim,sleeves}.py`, `quantdesk/execution/`;
   - `config/`, `docs/prereg/`, `docs/principles.json`;
   - `.github/workflows/`, `.claude/`.
   - *Verification:* a PR touching each path requests the owner.
3. **Pinned risk ceilings:** a test asserting `intraday.risk.*` and the drawdown halts are ≤ committed ceilings.
   - *Verification:* loosening any one makes CI fail.
4. **Registered-record manifest:** hashes of every spec, result and ledger file at registration; CI fails on any change
   or deletion.
   - *Verification:* editing an unresulted spec or deleting a result fails.
5. **Dependency lock** (A-03). *Verification:* CI installs from the lockfile only.
6. **Routine governance (owner-only):** the engineer's prompt and its trigger tools reviewed. The engineer should not
   hold `update_trigger` / `create_trigger` over its own routine unless the owner wants that.

---

## 7. Recommended decision on Phase H

### Recommendation: A, start Phase H with a narrow scope

**Why not B (close the audit and remediate):**
- The protocol forbids it. H–L, deterministic tests 8 and 16, artifacts 9–10 and five final answers are outstanding.
  "Do not silently skip phases."
- Substantively, the least-examined risks are operational: a crash between ledger and state, restart recovery, the
  kill switch, a silent scheduler failure (issue #4: "the desk did not run on 2026-10-06"). They could reorder the
  remediation priorities.

**Why not C (narrow investigation first):**
- The decision does not hinge on an open fact. Every remaining gap is already a named protocol phase.
- A "narrow investigation" would be an unofficial, partial Phase H with weaker exit criteria.

### Phase H scope

Only what A–G did not already establish; reuse A-02, A-04, A-06, A-10, D-07, E-01, F-01, F-02 and G-05 without
re-auditing them.

| # | Item (protocol words) | What to establish | Method (read-only) |
|---|---|---|---|
| H1 | Scheduler, heartbeat | The Cloudflare cron → `scheduler.yml` → waiter chain: what happens when a link fails (the 10-06 missed session, issue #4); is there a heartbeat; how fast is a miss detected | Workflows, run history, issues #4/#5 |
| H2 | Crash recovery (§8 test 8) | A kill between the ledger write and the state write: what is lost, duplicated or inconsistent | Synthetic run in a temp dir |
| H3 | Restart recovery (§8 test 16) | Morning → afternoon hand-over and a mid-session restart: armed state (B-04), open positions, learner, chain cache, memory | Synthetic run plus the 12:20 hand-over record |
| H4 | Kill switch | File and app paths: flatten, entries halted, survives restart | Synthetic engine run |
| H5 | Retries, rate limits | Kotak, NSE, Yahoo, Gemini, Ollama, news: retry, back-off, rest periods; what a throttle produces downstream | Code plus journal errors |
| H6 | Provider-failure sweep | For every provider not yet covered (GIFT, global feed, news, VIX, India-VIX-for-model, warehouse fetchers), does a failure produce valid-looking data? | Fault injection on fakes |
| H7 | Secrets | Exposure in logs or artifacts; scope per workflow; rotation | Workflow and log review (no values read) |
| H8 | Logging, alerts | Which failures reach the owner (issues, push) and which die at INFO/WARN (extends D-07, G-05) | Code plus journal |
| H9 | Storage, performance, rebuild time | Journal and warehouse growth, the force-push snapshot size (A-10), runner time budgets, time to rebuild state from releases | Measurement on a scratch copy |

**Exit criteria:**
- Each H1–H9 is classified (VERIFIED / PARTIAL / BROKEN / MISLEADING / UNVERIFIED) with file:line or run evidence.
- §8 tests 8 and 16 have been run, with results recorded.
- H-xx findings are in the register.
- No production change.
- Out of scope: general code review, fixes, and I–L topics (logged as hand-offs).

---

## 8. Prioritized remediation roadmap (proposed; not implemented)

Ordered by risk and dependency. **Human review = independent owner approval required.**

| # | Work item | Findings | Problem | Why at this position | Depends on / components | Tests and acceptance criteria | Regression risk | Human review |
|---|---|---|---|---|---|---|---|---|
| R0 | **Governance controls** (§6, items 1–6), plus fixing A-19 and A-03 first | G-01, G-02, A-19, A-03 | Unreviewed authority over everything below | Every later fix would otherwise be changed by the same unreviewed path | GitHub settings; tests; lockfile | §6 verifications; CI green on `main` for 5 consecutive days | Merges slow down; CI flakiness becomes blocking | **Yes** (owner applies the settings) |
| R1 | **Record and risk integrity tests** | G-01, E-05, E-06, A-10 | Mutable specs, results and limits | Protects the evidence the audit relies on | R0 | Manifest test; risk-ceiling test; anchored journal hash (or append-only branch) | False failures on legitimate new specs (needs a registration step) | Yes |
| R2a | **Evidence first:** fault-injection and freshness measurement | F-01, F-02, A-04, A-11, Q-08, Q-12 | Unknown fallback rate; vendor freeze cause | Decides the R2b design | Phase H (H6) | Measured fallback frequency; vendor answer on the 15:15 freeze | none (read-only) | No |
| R2b | **Fail-closed market data:** no entries on a model chain; flat-run / stale detection and quarantine; per-bar provenance | F-01, F-02, A-04, A-16, A-11, B-10 | Failures become valid-looking data | Highest paper-desk correctness risk once anything trades | R0, R2a; `chains.py`, `engine.py`, `feeds.py`, `kotak.py`, `recorder.py` | Fault-injection tests (Kotak + NSE down → standing aside, logged WARN); a synthetic frozen run is flagged and excluded from settlement, basis and grading; every bar carries its source | Fewer trading minutes; false freeze flags in genuinely quiet markets | Yes |
| R3 | **Sleeve settlement correction** (new spec `expiry_seller_v4`; v1/v3 ledgers kept frozen) | E-01, F-05 | Forward evidence mis-settled | The desk's only forward evidence | R2b (detection), R1 (spec guard) | Re-derived 4 trades equal the official-close values (A-NIFTY −₹3,419; B −₹1,838; D −₹7,342.81; E −₹7,945.26); ongoing ledger uses the official close | Changes the historical-forward comparison | **Yes** (spec) |
| R4 | **Deterministic end-to-end simulated-trade test** | B-02, B-03, B-04, C-01, C-05, A-01 | The chain past EXECUTION has never run | Needed before any gate redesign; also closes the ABSOLUTE RULE validation gap | none (test only) | A synthetic session drives one plan through scan → arm → trigger → model/EV/risk → fill → mark → exit → journal → learning; asserts every row, ID and P&L | none (test harness) | No |
| R5 | **Gate architecture decision** (directional trading at all? plan-model compatibility; iron fly economics) | RC1: B-02, C-01, C-05, A-01, B-06, B-07 | Nothing can trade | A decision, informed by N1 (direction not predictable) and R4 | R4; research (owner) | A written decision; R4 passes under the chosen design | High: it changes what the desk trades | **Yes** |
| R6 | **Realistic paper fills and costs** | F-04, A-11, C-04, F-05, E-03 | Optimistic simulated P&L | Must precede any P&L claim from the engine | R2b; `sim.py`, `costs.py` | Depth-capped fills (an order above the best size walks or rejects); one cost source; dated STT; move-away check on chain-price entries | Fewer and costlier paper fills | Yes |
| R7 | **Statistical claims hygiene:** placebo or CI before any adoption; relabel learning in docs and UI | D-01, D-02, D-04, D-06, C-02, E-02, E-04, G-05, B-01 | Signals adopted on noise | Not a safety issue today (D-02: ~no effect); a truthfulness issue | Phase J (UI) | A placebo/CI gate in graduation; README/UI wording matches D-01/D-02; an E-02 gate with power | none (mostly relabelling) | Yes (claims) |
| R8 | **Order and partial-fill accounting before any live use** | F-06, A-17 | Live adapter unsafe | Only needed before live, but must precede it | R0 | Partial-fill, cancel, reject and timeout state-machine tests on a fake broker; exchange timestamps | none until live | **Yes** |
| R9 | **Independent validation of strategy economics** | E-07, E-01, E-02, E-04 | L1 economics unproven | Gate to live authorization | R3, R6; `expiry_eve_entry_v1` | entry_v1 decided per its spec; recorded quotes for every held-out instrument; forward ledger on official settlement, n per spec | none | **Yes** (independent reviewer) |
| R10 | Hygiene: LLM provenance and parsing, calendar years, A-08, A-07, C-07, C-08, D-08, F-03, F-07 | G-03, G-04, G-06, F-07, … | Minor defects | Low risk | R0 | The respective probes flip | Low | No |

**Evidence before code:** R2a, R5 (decision) and R9 (data collection) need evidence or decisions, not code.

---

## 9. End-to-end readiness criteria

These are four separate decisions; passing one implies nothing about the others.

### Decision 1: System correctness (paper)

| # | Must demonstrate | Test / evidence |
|---|---|---|
| 1 | Valid, fresh, correctly sourced market data | Per-bar provenance; flat-run and stale quarantine tests; fault injection for every provider (no valid-looking data on failure); 5 recorded sessions with no unflagged freeze |
| 2 | Traceable signals and plan eligibility | R4 e2e test, plus every decision row carrying setup id, gate id and inputs (B-03) |
| 4 | Order and partial-fill accounting in simulation | Fake-broker state-machine tests (fill, partial, cancel, reject, timeout, unwind) |
| 6 | Accurate P&L, settlement and journal | Settlement on the official close; journal rows reconcile to fills; replay of a session from persisted evidence reproduces its decisions (Phase I) |
| 8 | Safe rejection when dependencies fail | Fault injection: chain, feed, model, LLM, journal faults → standing aside, WARN or above, and an issue filed |

### Decision 2: Statistical strategy evidence

| # | Must demonstrate | Test / evidence |
|---|---|---|
| 7 | Reproducible research | Every result stamped with a clean tree and a data manifest; specs with a frozen sample end; an independent rerun matches (as V-21); program-wide family count |
| — | Strategy evidence | Pre-registered held-out test passed (L1: done) plus forward paper n per spec on correct settlement, with a power-adequate gate (fixes E-02) |

### Decision 3: Executable economics

| # | Must demonstrate | Test / evidence |
|---|---|---|
| 5 | Realistic costs, spreads, liquidity | Depth-capped fills; recorded quotes for every traded instrument; `expiry_eve_entry_v1` decided; current statutory rates, dated |

### Decision 4: Live-trading authorization

| # | Must demonstrate | Test / evidence |
|---|---|---|
| 3 | Independently enforced risk controls | Pinned ceilings in CI; kill switch tested (Phase H); broker-side limits |
| 9 | Human-governed consequential changes | §6 controls verified by test PRs |
| — | Owner sign-off | Decisions 1–3 passed, plus R8, plus static-IP and order-API compliance. **The owner alone flips it.** |

---

## 10. Unresolved questions, assumptions and evidence limitations

### Open questions from the register

| Q | Question |
|---|---|
| Q-08 | Why Kotak freezes the index after 15:15 (vendor) |
| Q-09 | Program-wide hypothesis count since inception |
| Q-10 | Illiquid held-out spreads |
| Q-11 | Frozen minutes in autolearn labels |
| Q-12 | Model-chain fallback rate on runners |
| **Q-13** | **The owner's intent on unreviewed merges** |

### Limitations

| Limitation | Effect |
|---|---|
| **Single auditor** | A–G and this consolidation are by the same agent. "Reproduced" means re-executed by that agent on newer data or by a second method, not by an independent party. The register itself has had no external review. |
| Journal history | Force-pushed (A-10); pre-10-05 events are unrecoverable. Production evidence covers 10-05 … 10-09 (5 sessions). |
| No credentials | No Kotak, Kite or LLM keys in the audit environment. Kotak payload fields (A-11), live-model behaviour (G) and broker order paths (F-06, on a fake only) were not exercised against the real services. |
| External systems | Cloudflare (Workers build logs, cron), NSE (blocked from this environment) and the claude.ai routine internals were seen only through their GitHub/API surfaces. |
| No trades | Every finding about fills, P&L, calibration and outcome learning is latent or untestable in production. |
| Not repeated today | B replay funnel, D ON/OFF replay, C null simulations and the E/F measurement scripts. Their committed outputs were reproduced earlier the same day (E/F byte-identical). |
| Code state | Unchanged since `c96909f`, so code-based conclusions stand. |

### Assumptions

- The newer journal (`0143b5c`) is representative of the same configuration. It is: same code.
- Today's owner interruption of the engineer is an observation; its intent is unknown.

---

## 11. Exact next action requiring owner approval

**One decision from the owner, before 2026-10-10 17:40 IST:**

> Approve **Phase H** with the scope and exit criteria in §7, **and** state whether the autonomous engineer may merge
> to `main` while the audit continues.

**Recommended answer to the second part: no.** Either pause the "Quant-Desk engineer shift" routine, or apply the §6
branch protection. A change to `main` mid-audit moves the evidence base (`c96909f`), and G-01 is open.

The auditor will not touch the routine, the session or GitHub settings. Those actions are the owner's.
