# QuantDesk Phase H: Review Closeout

**Purpose:** a narrowly scoped, read-only closeout of Phase H. **Local and uncommitted.**

**Guarantees:**
- No earlier artifact was modified. SHA-256 at closeout:
  - `audit/data/phase_h_det_tests.json` `21533cc0…`
  - `audit/probes/phase_h_det_tests.py` `c9b90045…`
  - `audit/probes/test_phase_h_probes.py` `c87e89fd…`
  - `audit/QUANTDESK_PHASE_H_RELIABILITY.md` `f76c57c9…`
- The canonical register is unmodified (`git status`: not changed).
- No code or configuration change, no commit or push, no live API, broker or credential use.
- Phase I not started.

**Companion file (task 3):** `audit/QUANTDESK_PHASE_H_REGISTER_PROPOSAL.md`, the proposed register update. It is
separate from the register and awaits approval.

---

## 1. Probe runs: what actually ran

All runs used the scratchpad venv (Python 3.13.16, pytest 9.1.1) from the repo root. `$S` is the session
scratchpad.

| # | When (UTC, 2026-10-09) | Exact command | Result | Recorded output |
|---|---|---|---|---|
| R1 | 13:25:08 → 13:26:56 | `QD_JOURNAL=/tmp/qd_journal/intraday timeout 1800 $S/venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_h_probes.py 2>&1 \| tail -40` | **15 passed, 0 failed, 0 skipped in 106.97 s** | task output `bvfqmntl0.output` (exists) |
| R2 | 13:28:21 | `timeout 900 $S/venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_h_probes.py -k safe_mode 2>&1 \| tail -25` | **1 passed, 15 deselected in 4.67 s** (the 16th probe, alone) | **No file.** The output is recorded only in the session transcript (a foreground command) |
| **R3** | 13:28:31 → 13:30:30 | `QD_JOURNAL=/tmp/qd_journal/intraday timeout 1800 $S/venv/bin/python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_h_probes.py 2>&1 \| tail -15` | **16 passed, 0 failed, 0 skipped in 116.52 s** | task output `b6ywgr59t.output` (exists): `................ [100%]` / `16 passed in 116.52s (0:01:56)` / `[exited with code 0]` |
| R4 (closeout, new) | 17:06 → ~17:08 | `QD_JOURNAL=/tmp/qd_journal/intraday timeout 1800 $S/venv/bin/python -m pytest -o addopts="" -v -rA -p no:cacheprovider audit/probes/test_phase_h_probes.py` | **16 passed, 0 failed, 0 skipped in 101.26 s**, each test ID listed PASSED | `$S/closeout/probes_rerun_v.txt` |

### Did all 16 run together? Yes, in R3, verified as follows

1. R3 had no `-k` filter and reported 16 dots and `16 passed`.
2. The probe file was last modified at **13:28:18 UTC**: the safe-mode probe was added at that time. That is before
   R3 started at 13:28:31, and the file has not changed since (mtime and SHA-256 unchanged at closeout).
3. `--collect-only` on that same file collects exactly **16** items: 15 functions, one parametrized ×2.
4. R3 used `-q`, so it does not list test IDs. R4 is a **new** verbose run, made during this closeout, that lists all
   16 IDs as PASSED. R4 is reported as a separate run; it is not R3's output.

### How R1, R2 and R3 relate

| Run | Covers |
|---|---|
| R1 | The file **before** the safe-mode probe existed (15 items) |
| R2 | That probe alone |
| R3 | The verified final combined run |

---

## 2. Tests 8 and 16 vs the recorded JSON

### Provenance

| Fact | Evidence |
|---|---|
| `audit/data/phase_h_det_tests.json` is byte-identical to the scratch output `$S/phh/det_out.json` | SHA-256 `21533cc0…` for both |
| That output came from `$S/phh/det_tests.py` as written at 13:16:52, run at 13:16:54 → 13:18:38, exit 0, empty stderr | transcript; file mtimes |
| The repo harness differs from that version **only** in: (a) the `REPO` path line; (b) the `__main__` guard (`and len(sys.argv) == 1`); (c) the appended `test_kill_switch` and its `kill` entry point | unified diff against the transcript's original |
| The test 8 and test 16 function bodies are unchanged | same diff |

### Independent reproduction (closeout)

- `python audit/probes/phase_h_det_tests.py > $S/closeout/det_rerun.json` exited 0 with empty stderr.
- A structural comparison with the recorded JSON found **every field identical** (all five tests, all cash figures,
  positions, fills, reconcile details, WARN and CRITICAL texts, row counts).
- The only differences are the random 4-hex suffix of trade IDs, e.g. `I261009-0002-001f` → `I261009-0002-cae8`.
  These are generated per run and are not results.

### Report numbers vs the JSON

All of these match:
- 8a: ₹483,904.51; journal +0 vs broker +65.
- 8b: ₹496,362.97 → ₹510,399.65 → ₹513,440.14; end position −65 25700CE.
- 16a/16b: thoughts 65, decisions 11, reconcile 2 positions, end ₹499,401.33.
- 16c: the WARN text and both leg quantities.

### Discrepancies in the report's descriptions of tests 8/16

No artifact is wrong; these are wording and claim errors in the report (details in § 6):
- D1: the crash-mechanism description.
- D2: the 8b exit-path attribution.
- D3: the 8b "entries halted" claim.
- D4: the 8b cash comparator.
- **D5: 16c overstates what was observed** (the material one).

---

## 3. What was verified

- **Test 8a (entry crash), [synth]:**
  - fail-closed detection and an entry halt;
  - the orphan leg is kept all day;
  - no self-review finding;
  - one CRITICAL event.
- **Test 8b (exit crash), [synth]:**
  - the restart re-closes the already-closed leg → **naked short 25700CE −65**;
  - cash ₹513,440.14;
  - the journal says "closed".
- **Test 16a/16b (same-day restart, graceful-path simulation and hard kill), [synth]:**
  - positions, closed trades, trade count, day-start equity and journal rows restored;
  - reconcile ok;
  - the chain is rebuilt in one step;
  - armed setups are not restored (B-04).
- **Test 16c (overnight), [synth]:**
  - at the next session start, the trade is dropped with a WARN;
  - reconcile fails and entries are halted;
  - the legs are still at the broker.
- **Safe mode is lost at the handover** [synth] (H-07).
- **Kill switch** [synth] (H-06): flattens, persists on the same disk, sits outside `runtime/intraday`, `close_out`
  flattens.
- **Self-review:**
  - it judges a not-yet-happened day as missed: [synth] probe, plus [prod] issue #4 and run 37365296128;
  - it ignores CRITICAL events [synth].
- **Configuration facts [code]:** 7 soft-fail steps; Worker dispatch failure logged only; the afternoon job uses the
  branch tip; missing VIX → 14.0; GIFT age unchecked; plan studies outside retention.
- **Production facts [prod]:**
  - live.yml's cron about 7 h late every day;
  - slow steps of 51 s and 65 s;
  - 10 WARN grading failures;
  - the model chain used 0 of 743 times;
  - snapshot 60 MB, of which plan studies 44 MB.
- **Repo handover tests:** 2 passed, 3 skipped in 581.73 s (task output `bru78q4hz.output`).

---

## 4. What remains unverified

| Item | Why | Closest evidence |
|---|---|---|
| Settlement of expired orphan legs, and the entry halt on days after the next one (H-03) | 16c stops at the next day's session start, which is the legs' own expiry day, before 15:30 | [code]: no settlement path for non-journal broker positions |
| A real SIGTERM or GitHub cancel landing mid-order (H-06 → H-01/H-02) | Needs a live run or a real signal in the order path | Test 8's exception at the same point |
| Runner loss mid-job (H-10) | Not safely reproducible on hosted runners | Code save points; 16b on the same disk |
| Kotak timeout → step failure → safe mode (H-14) | Needs a fake Kotak client wired through the engine | Code reading |
| A stale (not missing) VIX series (H-08) | Not executed | Code reading; the probe asserts no freshness check |
| A real missed day being misdated and auto-closed (H-05 consequence) | No real miss has happened | Inference from the same code path |
| Afternoon-tip impact (H-09) | No incident observed | Configuration only |
| Restore time on a runner (network) | Needs a workflow run | 0.13 s local |
| Workflow-log secret scan (H7) | Logs not downloaded | Code reading plus a scan of the persisted journal and site |
| Cloudflare dispatch history | No Cloudflare access | Worker source; GitHub run timings |
| The kill-switch cash figure (₹499,985.02) | Recorded only in the transcript, not in a saved artifact; the probe re-confirms the qualitative results only | Transcript stdout of `phase_h_det_tests.py kill` |

---

## 5. Priority remediation groups (for a later, separately approved phase; nothing fixed here)

| Rank | Group | Why first | Acceptance (from the proposal) |
|---|---|---|---|
| 1 | **H-01**: idempotent exits against broker positions | The only recovery path that **creates** risk: a naked short and false books | A crash after each leg of a k-leg exit leaves broker = journal, cash = one round trip, and a rejected leg keeps the trade open |
| 2 | **H-04**: alert on CRITICAL, soft-fails and a stale heartbeat | Every other failure here is silent without it, so MTTR is unbounded | A CRITICAL event → finding; soft-fail → finding; dispatch failure → notification; stale-heartbeat probe fires |
| 3 | **H-02 / H-03**: orphan resolution (entry crash, overnight carry) | Wedges the account and holds unmanaged legs | Flatten or adopt with a stop; prior-day trades squared off or settled; an issue filed; tests |
| 4 | **H-06 / H-07**: persisted safety states (kill flag, safe mode) | A safety state must survive the handover and restarts, and a kill must not tear an order in half | A persisted remote kill with halt and flatten modes; deferred SIGTERM; safe mode restored for the day |

---

## 6. Discrepancies between the report, the tests and the artifacts

None alters an artifact or a test result; all are in the report's prose or citations.

| # | Where | Discrepancy | Evidence | Proposed handling |
|---|---|---|---|---|
| **D5** | Report § H2/H3 16c, § H6, H-summary row H3, H-03 title, probe name | Claims that the expired legs "are never settled" and that entries halt "every later day" / "indefinitely". **Not observed**: d1 = 2026-09-29 is the legs' expiry day and the test stops at `start_session(d1)` | `phase_h_det_tests.py:206-220`; JSON `test16c_overnight_orphan` | Narrow H-03 to what was observed; mark the rest [code]/[infer] (proposal § 2, H-03). Severity P2 and status BROKEN (latent) kept, for the confirmed part |
| D4 | H-01 "Observed" | "cash ₹513,440.14 (vs ₹499,401.33 for a clean round trip)": the comparator is test 16's end cash, a different scenario | JSON 16a/16b vs 8b timelines | Drop the comparator; state the inflation from the 8b JSON alone |
| D2 | § H2/H3 8b table | "Exit (the engine's own `_manage` → `_close`)": the exit reason is not recorded; the harness runs `advance` then `end_session()` | `phase_h_det_tests.py:161-162` | "`_close`, called by `_manage` or the end-of-session square-off" |
| D3 | § H2/H3 8b "Restart" row | "Entries halted" is not recorded for 8b (no `blocked` field) | JSON `test8b_exit_crash` | Tag it [code] (it follows from reconcile `ok: false`; recorded for 8a) |
| D1 | § H2/H3 "How a crash is simulated" | Says the exception is raised "after the broker has written the fill". In fact it is raised on the n-th call **before** that call executes; the (n−1)-th fill is on disk and its journal row is lost uncommitted | `phase_h_det_tests.py:80-91` | Wording fix only; outcomes unchanged |
| D6 | H-05, H1 | `intraday/cli.py:719-724` cited for the self-review `--day`; `:724` is the `sleeves` parser | `cli.py:718-722` | Cite `:719` |
| D7 | § H6 global feed, V-H7 | `brain.py:179` cited for the 15-minute `live` test | It is `brain.py:182`, used at `:186` | Citation fix |
| D8 | H-06, H4 | `engine.py:1556-1557` for the SIGTERM handler | It is `:1557-1558` | Citation fix (off by one) |
| D9 | Report § H0, § H13 | The kill-switch run and the solo 16th-probe run are reported with figures, but neither has a saved output file | Transcript only | Recorded here as provenance; no claim retracted (the probes in R3 and R4 re-confirm the qualitative results) |
| D10 | H-05 status | "VERIFIED" covers the wrong-day judgement; the "real miss hidden" consequence is [infer] | issue #4; code | Split the evidence tag (proposal § 2, H-05) |

No discrepancy was found between the JSON and the harness, or between the JSON and an independent rerun (other than
the random ID suffixes).

---

## 7. Why live trading remains blocked

**Phase H adds blockers on top of the consolidation's Decision 4 criteria** (`QUANTDESK_POST_G_CONSOLIDATION.md` § 9):

1. **H-01:** the restart path can create an unhedged short option that the books show as flat.
2. **H-04:** a broker/journal mismatch, safe mode or kill switch raises no alert.
3. **H-02 / H-03:** orphan legs are held with no stop and no owner; the overnight carry is dropped from the books.
4. **H-06:**
   - The documented live guard ("touch `runtime/KILL` to stop all order flow instantly", `execution/kite.py`) cannot be
     used on the hosted runners.
   - The only remote kill (cancel) can interrupt an order sequence.
   - Criterion 3 ("kill switch tested (Phase H)") is therefore **not met** for live.
5. **H-07:** a safety state is silently cleared at the handover.

**Already-settled blockers that still stand:**
- F-06: the Kite adapter drops partial fills.
- C-01 / B-02: no directional plan can pass, so H-01…H-03 have never been exercised in production.
- G-01: unreviewed merge authority.
- E-07 / E-01: economics not independently validated.
- R8: order and partial-fill accounting.

**Technically:** no workflow carries live credentials (V-38). Authorization is the owner's decision alone.

---

## 8. Remaining mandatory audit phases

| Phase | Protocol scope | Inputs handed over from H |
|---|---|---|
| **I**: Journal / auditability | Why we traded or didn't; what the system knew; model, factor, news and regime inputs; counterfactuals; what it learned; replay from persisted evidence | Commit per decision (H-09); reconstructing crash and orphan events (H-01/H-02); `model_state` callers (H-08); whether the CRITICAL event data suffices for manual repair |
| **J**: UI truthfulness | UI claims vs backend (learning, weights, champion or challenger, probation …) | How halts, safe mode, kill and orphan equity are shown; heartbeat age |
| **K**: Real session forensics | Reconstruct representative real sessions end to end, incl. zero-trade and provider/model degradation | 10-09 slow steps; the Kotak→Yahoo fallback minutes; the 10-06 false alarm |
| **L**: Adversarial audit | Falsify major claims: state not persisted, persisted state never consumed, hidden fallback, silent provider substitution … | D5 (16c) follow-up; H-07-type in-memory safety state; Q-10/Q-11 carried forward |

**Next step:** Phase I only on a separate approval.

---

## 9. Closeout artifacts (new, local, uncommitted)

| File | Content |
|---|---|
| `audit/QUANTDESK_PHASE_H_CLOSEOUT.md` | This note |
| `audit/QUANTDESK_PHASE_H_REGISTER_PROPOSAL.md` | Proposed register rows and entries H-01 … H-14, V-39 … V-47 (= V-H1 … V-H9), the V-20 annotation, the Q-12 partial answer, the change-log row |
| Scratchpad (not in the repo) | `closeout/det_rerun.json` (harness rerun), `closeout/probes_rerun_v.txt` (R4 verbose log) |
