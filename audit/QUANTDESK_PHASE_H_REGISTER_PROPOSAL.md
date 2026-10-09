# Proposed register update: Phase H (H-01 … H-14, V-H1 … V-H9)

**Status: PROPOSAL ONLY.** Local and uncommitted.

- The canonical register (`audit/QUANTDESK_FINDINGS_REGISTER.md`) is **unchanged**. Nothing here takes effect until
  the owner approves it.
- Source: `audit/QUANTDESK_PHASE_H_RELIABILITY.md` (§ H10, § H11), checked against `audit/data/phase_h_det_tests.json`,
  `audit/probes/phase_h_det_tests.py`, `audit/probes/test_phase_h_probes.py` and the recorded run outputs.
- **Preservation rule (owner's instruction):**
  - Severity, status, evidence type, reproduction and acceptance criteria are copied from the Phase H report.
  - Where the closeout review found an evidence-backed reason to change one, the change is shown **explicitly** as
    "Proposed correction", with its evidence. The preserved value stays visible beside it.
- **IDs:**
  - H-xx IDs are proposed as-is: they fit the register's letter-per-phase scheme (A-, B-, …, G-).
  - The register numbers controls globally (V-01 … V-38), so V-H1 … V-H9 would become **V-39 … V-47** on approval.
- Severity scale (register header): P0 safety/integrity/live-trading · P1 major correctness · P2 important limitation
  · P3 moderate · P4 minor.
- Register precedent: a paper-only defect is not P0 ("Paper only, so not P0", E-01).

---

## 1. Summary table rows (as they would be appended)

| ID | Title | Sev | Status | Phase |
|---|---|---|---|---|
| H-01 | An exit interrupted after one leg fills is re-exited in full on restart: a naked short leg and inflated cash while the journal says "closed" | P1 | BROKEN (latent) | H2 |
| H-02 | An entry interrupted after the first leg leaves an orphan position: detected, but never resolved, priced or escalated | P2 | PARTIAL | H2 |
| H-03 | A position left open across days is dropped from the books and halts entries the next day; settlement of its expired legs is unverified ‡ | P2 | BROKEN (latent) ‡ | H3 |
| H-04 | CRITICAL states (reconciliation failure, safe mode, kill switch) and soft-failed workflow steps never reach an alert; no heartbeat watchdog | P2 | VERIFIED | H8 |
| H-05 | Self-review judges the wrong day when its cron is delivered after midnight IST; a real miss can be misdated and auto-closed | P3 | VERIFIED ‡ | H1 |
| H-06 | The file kill switch can't be used on the runners; the real kill switch (cancel) also stops the desk for the day and can strike mid-order | P3 | PARTIAL | H4 |
| H-07 | Safe mode ("no entries for the session") is forgotten at the 12:20 handover | P3 | BROKEN | H3 |
| H-08 | A missing or stale India VIX silently becomes 14.0 (or the last stale value) in the model's implied vol | P3 | VERIFIED (latent) | H6 |
| H-09 | The afternoon job runs the branch tip: code can change mid-session on state written by different code | P3 | VERIFIED (config); impact UNVERIFIED | H1 |
| H-10 | The journal is persisted only at job end, to a single force-pushed copy; a runner loss drops the job's state | P3 | VERIFIED (design); runner-loss outcome [infer] | H9 |
| H-11 | Plan studies are outside retention and grow ~7–8 MB per autolearn day inside the journal snapshot | P3 | VERIFIED | H9 |
| H-12 | The repo's handover and kill-switch recovery tests skip on every run (no CI coverage of restart recovery) | P3 | VERIFIED | H3 |
| H-13 | Pre-open GIFT Nifty prints are used without an age check (display only) | P4 | VERIFIED | H6 |
| H-14 | Retry policy is uneven and loop overruns are only WARN; a Kotak timeout is not retried | P4 | PARTIAL (overruns [prod]; timeout propagation UNVERIFIED) | H5 |

‡ = a proposed correction or clarification; see § 2.

**Severities:**
- **No severity change is proposed.**
- H-01 stays **P1** under the register's own precedent: it is latent and paper-only today, since no trade has ever
  been opened (B-02).
- Recommended standing rule: H-01 is to be re-rated **P0** the moment any live or real-money mode is enabled, because
  it is then a direct safety/integrity defect.

---

## 2. Findings, register-style

Field values are copied from the report unless marked **Proposed correction**.

**Evidence tags:**

| Tag | Meaning |
|---|---|
| [synth] | Executed on synthetic data in an isolated temp directory |
| [prod] | Production record (journal copy, GitHub) |
| [code] | Code reading with file:line |
| [infer] | Inference, not executed |

### [H-01] An interrupted exit is re-exited in full: naked short, inflated cash, journal "closed"
Severity: **P1** · Status: **BROKEN (latent)**

**Component**
- `intraday/engine.py:1227-1253` `_close`: issues `-l.qty` per journal leg, with no check of the broker's position.
- `:1376-1387` `_restore`: trusts `intraday_open`.
- `:896-913` `_reconcile`: halts entries only (`_blocked`, `:708-709`).
- `:1235-1238`: a rejected exit leg `continue`s and the trade is still marked closed.

**Evidence** [synth]

| Point | Value |
|---|---|
| After crash | broker `{NIFTY06OCT2625800CE: −65}`, cash ₹510,399.65; journal trade `open` |
| Restart | the trade is restored as open; reconcile `ok: false` ("25700CE: journal +65 vs broker +0") |
| End of day | broker `{NIFTY06OCT2625700CE: −65}`, cash ₹513,440.14; journal trade `closed` with 4 fills; `intraday_open.trades` `[]` |

**Reproduction**
`phase_h_det_tests.test8_exit_crash`; probe `test8_exit_crash_double_exits_into_a_phantom_naked_short`.

**Expected vs observed**
- Expected: the restart closes only what the broker still holds, or halts exits and asks.
- Observed: a naked short call; cash inflated; journal "closed".

**Impact**

| Mode | Impact |
|---|---|
| Paper | Phantom profit, an unpriced short |
| Research | Wrong P&L on a "closed" trade |
| Recovery | The recovery path itself creates the damage |
| Live | An unhedged short option that the desk believes is flat |

**Acceptance**
- Crash after each leg of a k-leg exit (k = 2, 4), then restart.
- The broker ends flat, or holds exactly the unclosed legs, flagged.
- Cash equals a single round trip; journal fills equal broker fills.
- Exits are idempotent against broker positions.
- A rejected exit leg leaves the trade open.

**Proposed corrections (wording and evidence only; severity and status preserved)**

1. **Drop the comparator "(vs ₹499,401.33 for a clean round trip)".**
   - That figure is test 16a/16b's end cash, a different scenario: restart at 11:32, a single close later in the day.
   - 8b closes one leg at 11:00 and the rest after its restart.
   - The inflation is still shown by the JSON alone: after the crash the account held only the short 25800CE leg,
     and at end of day it is short 25700CE instead.
   - The extra cash comes from selling a 25700CE that was no longer held.
2. **Exit path after restart.** The report says "the engine's own `_manage` → `_close`".
   - The JSON does not record the exit reason.
   - The harness runs `advance(b, "15:29")` and then `end_session()`.
   - So the second `_close` came from either `_manage` or the end-of-session square-off.
   - Proposed wording: "the engine's own `_close`, called by `_manage` or by the end-of-session square-off (exit
     reason not recorded)".
3. **"Entries halted" for 8b** is not recorded in the 8b JSON (there is no `blocked` field).
   - It follows from `reconcile.ok = false` and `engine.py:708-709`, and is recorded for 8a.
   - Tag it [code] for 8b.

### [H-02] An interrupted entry leaves an orphan: detected, never resolved or escalated
Severity: **P2** · Status: **PARTIAL**

**Component**
- `engine.py:1176-1192` `_open`: the broker fill happens before `journal.fill`, the trade append and `_persist`.
  The unwind covers `fill is None` only.
- `:896-913`. `ops/selfreview.py:78`.

**Evidence** [synth]

| Point | Value |
|---|---|
| After crash | broker `{NIFTY06OCT2625700CE: +65}`, cash ₹483,904.51; journal fills, trades and `intraday_open` all empty |
| Restart | reconcile `ok: false` ("journal +0 vs broker +65"); `_blocked` = "halted: broker and journal disagree (…)"; 1 CRITICAL event |
| End of day | unchanged; `selfreview_findings` `[]` |

**Reproduction**
`test8_entry_crash`; probe `test8_entry_crash_fails_closed_but_orphans_the_position_silently`.

**Expected vs observed**
- Expected: the orphan is flattened, or adopted and journaled, and an alert is raised.
- Observed: the orphan is held all day, entries are halted all day, and there is no alert.

**Impact**

| Mode | Impact |
|---|---|
| Paper | Equity excludes a held leg; the desk stops for the day silently |
| Research | A "no trade" day caused by an orphan |
| Recovery | A manual `broker.json` edit is required |
| Live | A naked leg with no stop and no owner |

**Acceptance**
- After a crash after leg i of an entry, the leg is flattened at the next step, or adopted as a journaled orphan
  trade with a stop.
- An issue is filed the same day.
- Tests cover both legs and both crash points.

**Proposed correction (wording only)**
- The report's § H2/H3 says the exception is raised "after the broker has written the fill".
- In the harness, `crash_on_call(eng, n)` raises on the n-th call **before it executes**
  (`phase_h_det_tests.py:80-91`).
- For 8a (n = 2):
  - leg 1's broker fill is on disk;
  - leg 1's journal fill row was buffered, and is lost when the connection is closed without commit;
  - leg 2 never reaches the broker.
- The outcome is unchanged; only the description is.

### [H-03] Overnight orphan dropped from the books; next-day entries halted ‡
Severity: **P2** · Status: **BROKEN (latent)**, narrowed (see the proposed correction)

**Component**
- `engine.py:1376-1384` `_restore`: a different day's trades → WARN "…never squared off; ignored", returns `{}`.
- There is no expiry settlement for broker positions outside a journal trade [code].
- `_reconcile` halts entries.

**Evidence** [synth]

| Point | Value |
|---|---|
| Day 0 | trade opened on d0 = 2026-09-28, process killed at 11:00 |
| Start of d1 = 2026-09-29 | `open_trades` `[]`; WARN "1 position(s) from 2026-09-28 were never squared off; ignored"; reconcile `ok: false` on both legs; broker still `{NIFTY29SEP2625850CE: +65, NIFTY29SEP2625950CE: −65}` |

**Reproduction**
`test16_overnight`; probe `test16_position_left_overnight_is_ignored_and_halts_every_later_day`.

**Proposed correction (evidence-backed): narrow the claim to what was observed**
- d1 (09-29) is the legs' **own expiry day**, and the test stops at `start_session(d1)`, before the 15:30 expiry.
- So these report statements were **not observed**:
  - "although they expired 09-29. They are never settled, marked or removed" (report § H2/H3 16c, § H6, the H-03
    title);
  - "entries halt indefinitely" / "every later day".
- What **is** confirmed:
  - the trade is dropped from the books;
  - entries are halted at the next session start;
  - the legs are still at the broker.
- Settlement after expiry, and the halt on later days, are **[code]/[infer]**: no settlement path exists for
  non-journal broker positions, and `_reconcile` would keep failing while they are held. They are **UNVERIFIED by
  execution**.
- Proposed title: "A position left open across days is dropped from the books and halts entries the next day;
  settlement of its expired legs is unverified".
- The probe's name ("…halts_every_later_day") also overstates. The artifact is left unchanged; this note records the
  gap.
- **Closest safe check, not run (out of closeout scope):** extend `test16_overnight` to advance d1 past 15:30 and
  start a d2 session.

**Impact**

| Mode | Impact |
|---|---|
| Paper | The account is wedged until state is hand-edited (next day confirmed; later days [infer]) |
| Research | Silent no-trade sessions |
| Recovery | No automatic exit |
| Live | Positions never reconciled |

**Acceptance (preserved)**
- With a prior-day open trade in `intraday_open`, `start_session` squares it off at the next open (or settles it at
  the expiry close), records the fills, reconciles to `ok`, and files an issue.
- Expired broker legs are settled by a test.

### [H-04] CRITICAL states and soft-failed steps never alert; no heartbeat watchdog
Severity: **P2** · Status: **VERIFIED**

**Component**
- `ops/selfreview.py:78` (`level == "ERROR"` only); `:220` (failure-type run conclusions only).
- `.github/workflows/live.yml:61, 71, 97, 130, 133, 154, 159` (`|| echo "::warning::…"`).
- `deploy/cloudflare/worker.js:48` (`console.log`).
- No heartbeat consumer.

**Evidence** [code + synth + prod]
- Probes `test_self_review_escalates_error_but_not_critical`, `test_soft_failed_steps_keep_the_live_job_green`,
  `test_worker_dispatch_failure_is_only_logged`.
- Test 8a `selfreview_findings: []`.
- Production: 10 WARN grading failures, 2 slow steps and LLM timeouts, all unalerted.
- Extends D-07 and G-05.

**Impact**

| Mode | Impact |
|---|---|
| Paper | Halts and wedges go unnoticed |
| Research | Silent no-trade days |
| Recovery | MTTR is unbounded |
| Live | Unacceptable |

**Acceptance**
- A CRITICAL event → a self-review finding.
- A forced soft-fail → a finding, or a failed job.
- A Worker dispatch failure → an issue or notification.
- A stale-heartbeat check in market hours, proven by a probe.

### [H-05] Self-review judges the wrong day after a late cron ‡
Severity: **P3** · Status: **VERIFIED**. **Partially contradicts V-20.**

**Component**
- `ops/selfreview.py:65-76` (no `now`), `:282-289`; `.github/workflows/selfreview.yml:11`.
- `intraday/cli.py`: the self-review `--day` default ("today, IST").

**Evidence**

| Tag | Point |
|---|---|
| [prod] | Issue #4 created 2026-10-05T19:54:55Z (01:24 IST 10-06) by run 37365296128, the 10-05 cron delivered at 01:14 IST |
| [prod] | The desk ran on 10-06 (2 `session start` events) |
| [prod] | Later runs landed at 22:54, 23:27 and 23:29 IST |
| [synth] | Probe `test_self_review_judges_a_session_before_it_has_happened` |

**Proposed clarifications (evidence type and citation)**
- The status VERIFIED applies to the wrong-day judgement ([prod] + [synth]).
- The consequence "a real miss is reported under the wrong date and auto-closed" is **[infer]** from the same code.
  It was not observed: no day has actually been missed.
- **Citation fix:**
  - The self-review `--day` argument is `intraday/cli.py:719`, in the parser at `:718-722`.
  - `:724` belongs to `sleeves`.
  - The report cites `cli.py:719-724`.

**Acceptance (preserved)**
- A scheduled review delivered at any time before the next session's open checks the last completed trading day.
- A test with `now` = 01:14 IST D+1 and no session on D files "did not run on D".

**Register cross-reference:** annotate **V-20** as "partially contradicted by H-05 (day attribution)".

### [H-06] Kill switch: the file is unreachable on runners; cancel stops the day and can strike mid-order
Severity: **P3** · Status: **PARTIAL**

**Component**
- `engine.py:120, 936-946`; `deploy/journal.sh` (saves `runtime/intraday` only).
- `worker.js:52-53`; `live.yml:78-79, 124-125`; `deploy/scheduler.py`.
- `engine.py:1557-1558` (SIGTERM → `SystemExit`; report cites `:1556-1557`, off by one).
- `execution/kite.py` docstring guard 3.

**Evidence**
- [synth] probes `test_file_kill_switch_works_but_lives_outside_the_saved_journal`,
  `test_the_phone_app_cannot_reach_the_live_engine`.
- [infer] a signal landing between a fill and its journal entry.

**Provenance note (no change to status)**
- The kill-switch run's detailed output (e.g. `close_out` end cash ₹499,985.02, trade `I261009-0002-739f` closed, 4
  fills) is recorded **only in the session transcript**. It was the stdout of `python phase_h_det_tests.py kill` at
  2026-10-09 13:20 UTC. No saved artifact exists.
- The probe re-confirms every qualitative claim: killed, 0 open, broker `{}`, still killed after a same-disk restart,
  `rt/KILL` location, the `journal.sh` save scope, and `close_out` leaving the broker flat. It does **not** re-confirm
  the cash figure.

**Acceptance (preserved)**
- A persisted kill flag, settable remotely, honoured by both jobs and the next day, with "halt entries" and "flatten"
  modes.
- SIGTERM is deferred until the order sequence completes; a test sends a signal during `_open`/`_close` and finds
  broker = journal.

### [H-07] Safe mode is forgotten at the 12:20 handover
Severity: **P3** · Status: **BROKEN**

**Component**
`engine.py:127-128` (`health` in memory), `:915-934`, `:1367-1374` (`_persist` omits `safe_mode`); config
`max_step_failures: 3 … no entries for the session`.

**Evidence** [synth]
Probe `test_safe_mode_is_not_carried_across_the_handover`: the afternoon process has `health["safe_mode"] = None`, and
the entry gate no longer cites it.

**Acceptance (preserved)**
- Safe mode is saved in `intraday_open` and restored for the same day.
- It is cleared only by the operator or the next day.
- The probe is inverted to assert that it persists.

### [H-08] Missing or stale India VIX → silent 14.0 or a stale level
Severity: **P3** · Status: **VERIFIED (latent)**

**Component**
`engine.py:165-175` `model_state` (`… else 14.0`; no age check).

**Evidence**
- [synth] probe `test_missing_india_vix_becomes_a_silent_14`: the missing case; IV = 0.14 × β.
- [code] the stale case (the probe asserts there is no `Timedelta` freshness check in the source; not executed with a
  stale series).
- Production reach: the model chain was used 0 of 743 times, 10-05 … 10-09 [prod].

**Acceptance (preserved)**
- A staleness flag from `model_state`.
- With VIX missing or stale, the model chain is degraded and entries priced on it are refused.
- A test asserts the refusal and the event.

### [H-09] The afternoon job runs the branch tip
Severity: **P3** · Status: **VERIFIED** (configuration); impact **UNVERIFIED**

**Component**
`.github/workflows/live.yml:107`; G-01; C-08.

**Evidence** [code]
Probe `test_afternoon_job_runs_the_branch_tip_not_the_mornings_code`.

**Acceptance (preserved)**
- The afternoon checks out the morning's SHA.
- Each job's session-start event records its commit.
- A test asserts equality, or that a hot-fix flag is present.

### [H-10] Journal persisted only at job end, to a single force-pushed copy
Severity: **P3** · Status: **VERIFIED** (design) [code]; runner-loss outcome [infer]

**Component**
`deploy/journal.sh` save, `deploy/push-dir.sh`. Related to A-10.

**Evidence**
- [code] the save points.
- [synth] test 16b: no loss on the same disk.
- A runner-loss test was **not executed** (not safely reproducible).

**Acceptance (preserved)**
- An incremental save after each fill (or every N minutes) plus a retained history.
- A test kills the job after a fill and the next job restores that fill.

### [H-11] Plan studies outside retention; unbounded growth
Severity: **P3** · Status: **VERIFIED**

**Component**
`autolearn/research.py:607`; `autolearn/cycle.py:548-575`.

**Evidence**
- [prod] the 10-09 copy: 44 of 60 MB, 6 studies of 6.9–7.9 MB.
- [synth/code] probe `test_plan_studies_are_outside_autolearn_retention`.
- Projection ≈ 1.9 GB/year [infer].

**Acceptance (preserved)**
- A retention rule (N+1 → N, referenced studies protected).
- Snapshot size flat across 10 synthetic cycles.

### [H-12] Repo recovery tests skip on every run
Severity: **P3** · Status: **VERIFIED**

**Component**
`tests/test_handover.py:35-45` (`_find_handover` skips when no trade opens); B-02.

**Evidence** [synth]
`pytest -q -rs tests/test_handover.py` → `2 passed, 3 skipped in 581.73s` ("no open position mid-session in the
sample"). Recorded output: background task `bru78q4hz`.

**Acceptance (preserved)**
- The three tests run with an injected trade (0 skipped).
- CI fails on a skip in `test_handover.py`.

### [H-13] GIFT prints used without an age check
Severity: **P4** · Status: **VERIFIED** (display only; B-05)

**Component**
`data/nse.py:351` `parse_gift`; `engine.py:802-819` `preopen`.

**Evidence** [synth]
Probe `test_gift_print_has_no_age_check`: a 2-day-old print is accepted.

**Acceptance (preserved)**
`preopen` ignores prints older than the previous close, with a test.

### [H-14] Uneven retries; overruns only WARN; Kotak timeouts not retried
Severity: **P4** · Status: **PARTIAL**

**Component**
`intraday/kotak.py:132-160`; `intraday/llm.py:287-307`; `intraday/news.py:333-338`; `engine.py:1620-1624`.

**Evidence**
- [prod] 10-09 "slow step: 51 s" at 12:42 and "65 s" at 13:24.
- [code] the retry table.
- Timeout → step failure → safe mode: **UNVERIFIED**.

**Acceptance (preserved)**
- Per-provider step timing in the journal.
- A fake-provider timeout test shows one retry and a bounded step.
- Overruns count toward the H-04 alert.

---

## 3. Verified-working controls (proposed V-39 … V-47)

| Proposed ID | Report ID | Control | Evidence |
|---|---|---|---|
| V-39 | V-H1 | A same-day restart (graceful SIGTERM-path simulation, or hard kill) restores open trades, closed trades, the trade count, day-start equity and risk state; journal rows survive a hard kill; reconcile `ok`; the chain is rebuilt in one step | Tests 16a/16b [synth]; JSON `test16a_graceful_restart`, `test16b_hard_kill_restart` |
| V-40 | V-H2 | Broker/journal reconciliation at session start **fails closed** (CRITICAL, entries halted) with an exact diff | Tests 8a/8b/16c [synth]; `engine.py:896-913` |
| V-41 | V-H3 | The file kill switch flattens once, halts entries, survives a same-disk restart, logs its clearing | `test_kill_switch` [synth] (detailed output in the transcript only) |
| V-42 | V-H4 | Cancelling a live run squares off through `--close-out` and closes the session | `live.yml:78-79, 124-125`; `close_out` [synth] |
| V-43 | V-H5 | Journal restore runs a SQLite integrity check and refuses an empty account when the branch exists but can't be fetched | `deploy/journal.sh:12-40` [code] |
| V-44 | V-H6 | A handed-over session nobody closed is closed by the next run after the bell | `engine.py:1536-1540` [code]; post-close `live.yml` runs [prod] |
| V-45 | V-H7 | Global-market cues need a completed bar ≤ 15 min old; fetch failures are recorded, not filled | `brain.py:139-188` [code]. **Citation fix:** the 15-min test is `brain.py:182`, used at `:186` (the report's § H6 table cites `:179`) |
| V-46 | V-H8 | Secrets: environment only; never printed (names, presence or length); header transport; blanked for third-party hosts; none found in journal or site copies | Report § H7 [code + prod]. Workflow logs were not scanned (limitation preserved) |
| V-47 | V-H9 | Bounded retries everywhere; repeated step failure enters safe mode and squares off | Report § H5; `engine.py:1599-1617` [code]. Note H-07: safe mode does not survive the handover |

---

## 4. Other register edits proposed

| Item | Proposed edit |
|---|---|
| V-20 | Add: "Partially contradicted by H-05: a late-delivered scheduled review judges the wrong day" |
| Q-12 | Add a partial answer: "Production 10-05…10-09: 0 of 743 recorded minute-reads used the model chain (742 kotak, 1 nse); reads are sampled every ~2–3 min. Runner-IP blocking frequency still unmeasured." |
| Q-10, Q-11 | Unchanged (E → H handoffs outside the approved nine areas); carried forward |
| Change log | `2026-10-09 \| H \| H-01 … H-14, V-39 … V-47 added; Q-12 partially answered; V-20 annotated (H-05). No earlier severity changed.` |
| Evidence base | Add the 10-09 16:15 IST close journal snapshot (read-only copy) and Actions runs 37365296128 (self-review) and live.yml runs #9–#17 |
