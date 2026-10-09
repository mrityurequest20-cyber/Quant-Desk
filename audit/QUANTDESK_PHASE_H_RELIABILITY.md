# QuantDesk: Operational Reliability and Failure Recovery (Phase H)

Read-only forensic audit: Phase H of the master protocol, as scoped in `audit/QUANTDESK_POST_G_CONSOLIDATION.md`
(option A) and approved by the owner.

**Status: Phase H complete, awaiting review.** This report is **local and uncommitted**.

- The proposed findings below (**H-01 … H-14**) and controls (**V-H1 … V-H9**) are **not** in the canonical register.
  - The approval says to update the register only if the existing audit workflow explicitly authorizes it.
  - Phase A–G updates to the register were made after each phase's report had been reviewed. Nothing explicitly
    authorizes an update before review.
  - So the proposals are kept here, separately, for review.
- **Nothing was changed:**
  - no production code, configuration, account state, journal history or trading state;
  - no workflow, schedule, trigger, permission, branch protection, or the autonomous engineer's session;
  - nothing was committed, pushed or merged.
  - Earlier reports and the register are unmodified.
- **Isolation:**
  - Every test ran in its own `tempfile.mkdtemp()` directory.
  - Inputs were a synthetic session (`simulate_sessions(seed=5)`), the replay feed, the "model" chain and the paper
    `IntradayBroker`.
  - No network, broker API, credential or real journal was used by any test.
  - Production evidence was read from **copies** of the `journal` branch made earlier in the session, read-only
    (SQLite `mode=ro`), plus GitHub's read API.
- **No defect was fixed.**

---

## H0. Objective, scope, baseline

**Protocol (§ Phase H):**

> provider failure · fallback · stale data · missing snapshots · retries · rate limits · scheduler · heartbeat · crash
> recovery · restart recovery · kill switch · secrets · logging · alerts · storage · performance · rebuild time.
> *A failure must never silently become valid-looking data.*

**Plus §8 deterministic tests:** 8 (crash between ledger/state update) and 16 (restart/recovery).

**Approved scope (nine areas, nothing else):**

| # | Area |
|---|---|
| H1 | Scheduler and heartbeat, including the 10-06 "missed" session |
| H2 | Crash recovery: §8 test 8 |
| H3 | Restart recovery: §8 test 16 |
| H4 | Kill switch |
| H5 | Retries and rate limits |
| H6 | Provider-failure sweep |
| H7 | Secrets |
| H8 | Logging and alerts |
| H9 | Storage, performance, rebuild |

**Out of scope:** settled A–G findings are cited, not re-audited.

### Baseline

| Item | Value |
|---|---|
| Repo HEAD | `8138494` (Phase G commit). Working tree is clean apart from untracked audit files (the consolidation report and the Phase H files below) |
| Production code read at | `main` = `c96909f`, the commit every production run in the evidence window ran on |
| Production evidence | Two read-only copies of the `journal` branch: `ecd03156` (earlier) and the 10-09 16:15 IST close snapshot (`journal_0143`); GitHub issue #4 and workflow-run metadata (self-review, live) |
| Test environment | Python venv in the scratchpad. Engine, journal and broker run on temp files |

**Evidence tags:**

| Tag | Meaning |
|---|---|
| [prod] | Production record (journal copy, GitHub runs or issues) |
| [synth] | Executed on synthetic data in an isolated temp directory |
| [code] | Code reading with file:line |
| [infer] | Inference, not executed |

### Artifacts produced (all untracked)

| File | What |
|---|---|
| `audit/probes/phase_h_det_tests.py` | The harness: tests 8a/8b, 16a/16b/16c and the kill switch on the real `IntradayEngine`, `Journal` and `IntradayBroker` |
| `audit/data/phase_h_det_tests.json` | The recorded outcomes of tests 8 and 16 (verbatim output of the harness) |
| `audit/probes/test_phase_h_probes.py` | 16 pytest probes. Each passing probe **confirms** the finding or control it names |
| `audit/QUANTDESK_PHASE_H_RELIABILITY.md` | This report |

**Probe run:**
- 15/15 passed in 107 s.
- A 16th probe (safe mode across the handover) was added afterwards and passed on its own (4.7 s).
- The final full run of all 16: **16 passed in 116.52 s** (§ H13).

---

## H-summary. Verdict per area

| Area | Verdict | Proposed findings |
|---|---|---|
| H1 Scheduler / heartbeat | **The 10-06 "missed session" was a false alarm.** The desk ran on 10-06. A self-review cron delivered 8 h late crossed midnight IST and judged the wrong day. The same mechanism can **hide** a real miss. There is no independent heartbeat watchdog | H-05, H-04, H-09 |
| H2 Crash recovery (test 8) | **Entry crash: fails closed but is never resolved.** The orphan leg stays at the broker all day, entries are halted, and no issue is filed. **Exit crash: unsafe.** The restart re-closes a leg already closed, leaving a **naked short** and inflated cash while the journal says "closed" | **H-01**, H-02 |
| H3 Restart recovery (test 16) | **Same-day restart (graceful or hard kill) recovers correctly:** positions, trade count, day-start equity, journal rows; the chain rebuilds in one step (control). **Not restored:** armed setups (B-04, settled) and **safe mode** (new). **Across days:** a position left overnight is discarded from the books and halts every later day | H-03, H-07 |
| H4 Kill switch | **The file kill switch works locally** (flattens once, halts, survives a restart on the same disk). On the runners it is **unreachable and not persisted**. The real kill switch is "cancel the run" → `--close-out`, which flattens correctly but also stops the desk for the day | H-06 |
| H5 Retries / rate limits | **Bounded and fail-safe, but uneven:** NSE (backoff), Kotak (one retry on 429/5xx, none on timeouts), Gemini (one retry plus a model fallback chain), Ollama/news (none). Three failed minutes put the engine in safe mode. Loop overruns of 51 s and 65 s were seen on 10-09 | H-14, H-07 |
| H6 Provider-failure sweep | **Most paths fail visibly or closed.** Two produce **plausible-but-invalid values**: a missing or stale India VIX → a silent **14.0** (or the last stale value) in the model chain's IV; and a stale GIFT print (display only). The global feed has a 15-minute "live" guard. Model-chain fallback: **0 of 743** recorded minute-reads in 5 sessions (Q-12, partial) | H-08, H-13 |
| H7 Secrets | **No exposure found** (control). Values come only from the environment. Only names or lengths are printed. The Kotak key goes in a header and is blanked for third-party downloads. No key pattern appears in the journal or site copies | — |
| H8 Logging / alerts | **The weakest area.** Self-review alerts on `ERROR` events and on `failure`/`timed_out`/`startup_failure` runs only. Reconciliation failure, safe mode and the kill switch are `CRITICAL`, and none is ever alerted. Seven workflow steps soft-fail to `::warning::`. Worker dispatch failures go to `console.log` only | **H-04** |
| H9 Storage / performance / rebuild | **The restore is fast** (0.13 s local extract plus integrity check, network excluded) and fails closed on an unreachable branch. **Weak points:** a single force-pushed copy, saved only at job end (a runner loss drops that job's state); plan studies (~7–8 MB each, 44 of 60 MB) are outside retention and grow unbounded. 3 of the 5 repo handover/kill-switch tests skip in CI | H-10, H-11, H-12 |

---

## H2/H3. §8 deterministic tests 8 and 16: recorded results

**Harness:** `audit/probes/phase_h_det_tests.py`.

**Raw output:** `audit/data/phase_h_det_tests.json`.

**Engine and broker:**
- Engine: the real `IntradayEngine`. Journal: SQLite on a temp path.
- Broker: the paper `IntradayBroker`. It saves `broker.json` atomically on every fill (`execution/broker.py` save).
- Feed: `ReplayFeed` over `simulate_sessions(days 2026-08-17…09-29, seed=5)`. Chain: "model".

**Why a trade is injected:**
- The current config takes no trades on synthetic sessions (B-02, structural).
- So each test opens a NIFTY call debit spread (long ATM CE, short CE two strikes up, 1 lot = 65) through the
  engine's own `_open`.
- Every later step runs the engine's own code.

**How a crash is simulated:**
- A `BaseException` is raised from inside `broker.execute` on its n-th call. This is after the broker has written the
  fill, and before the journal or state update.
- Then the journal connection is closed **without commit** (`die()`), which is what a killed process leaves.
- A new engine is built on the same files, as a restarted job would be.

### Test 8a: crash during entry, after leg 1 fills and before the journal/state update

| Step | Observed |
|---|---|
| After crash | broker `{NIFTY06OCT2625700CE: +65}`, cash ₹483,904.51 (dropped by the leg 1 debit); journal fills `[]`, trades `[]`, `intraday_open.trades` `[]` |
| Restart | `open_trades` `[]`; `_reconcile` → `ok: false`, "NIFTY06OCT2625700CE: journal +0 vs broker +65"; one **CRITICAL** event |
| Entry gate | `_blocked` → "halted: broker and journal disagree (…)" **(fail-closed: control)** |
| End of day (`end_session`) | broker **still** `{…25700CE: +65}`, cash unchanged. The orphan is never squared off, marked or settled; the journal has no record of it |
| Self-review on that day | `check_session(...)` → **`[]`**: no issue filed for a CRITICAL reconciliation failure |

**Result: PARTIAL PASS.**
- Detection and the entry halt work.
- Recovery does not exist: the orphan is never resolved, priced, alerted or squared off.
- **→ H-02** (and H-04 for the missing alert).

### Test 8b: crash during exit, after leg 1 closes and before the journal/state update

| Step | Observed |
|---|---|
| Opened | broker `{25700CE: +65, 25800CE: −65}`; journal trade `open` |
| After crash | broker `{25800CE: −65}` (the long leg was sold, cash ₹510,399.65); journal trade still `open` with both legs |
| Restart | `_restore` brings the trade back as open, with both legs; `_reconcile` → `ok: false`, "25700CE: journal +65 vs broker +0". Entries halted |
| Exit (the engine's own `_manage` → `_close`) | `_close` issues `-qty` for **both** legs from the journal's view. It **sells 25700CE again** (broker has 0 → **−65**) and buys back 25800CE (−65 → 0) |
| End of day | broker **`{NIFTY06OCT2625700CE: −65}`** (a **naked short call**), cash ₹513,440.14 (inflated by the second sale); journal: trade **`closed`**, 4 fills; `intraday_open.trades` `[]` |

**Result: FAIL.**
- The recovery path turns a crash into a position that nobody intended and that the books do not show.
- In paper, that means phantom cash and an unpriced short.
- In live, it would be an unhedged short option.
- The reconcile check detected the mismatch, but it only halts **entries**: exits still run on the journal's view.
- **→ H-01.**

### Test 16a / 16b: mid-session restart (graceful SIGTERM path / hard kill), open position at 11:30

The two variants gave identical results.

| State | Before | After restart | Verdict |
|---|---|---|---|
| Open trades | `[I…]` | same id | ✅ restored |
| `trades_today` / day-start equity | 1 / ₹500,000 | 1 / ₹500,000 | ✅ |
| Reconcile | — | `ok: true`, 2 positions | ✅ |
| Journal rows (thoughts 65, decisions 11) | 65 / 11 | 65 / 11 | ✅ every minute step is committed (hard kill loses nothing) |
| Chain cache | NIFTY, BANKNIFTY | `[]` → both after one step | ✅ rebuilt in one minute |
| Armed setups | (0 armed in this sample) | `{}` | ⚠️ not persisted by design (**B-04**, settled; not re-audited) |
| End of day | — | broker `{}`, cash ₹499,401.33, trade closed once | ✅ |

**Result: PASS for positions, risk state and journal; known gap for armed setups (B-04).**

**Extra probe (not in the JSON; see `test_safe_mode_is_not_carried_across_the_handover`):**
- Safe mode set in the morning process is `None` in the afternoon process.
- The entry gate no longer reports it.
- **→ H-07.**

### Test 16c: a position left open across days (the handover/close never ran)

| Observed | |
|---|---|
| Next day's `_restore` | `open_trades` `[]`. A **WARN** event: "1 position(s) from 2026-09-28 were never squared off; ignored" |
| Reconcile | `ok: false`: "NIFTY29SEP2625850CE: journal +0 vs broker +65; NIFTY29SEP2625950CE: journal +0 vs broker −65" → entries halted |
| Broker | Both legs still held, **although they expired 09-29**. They are never settled, marked or removed |

**Result: FAIL.**
- The trade is dropped from the books instead of being recovered.
- The expired legs are never settled.
- The halt has no exit path short of hand-editing `broker.json`.
- **→ H-03.**

### Repo's own recovery tests

`tests/test_handover.py`:

```
sss..   SKIPPED [3] tests/test_handover.py:45: no open position mid-session in the sample
2 passed, 3 skipped in 581.73s
```

- `_find_handover` (`tests/test_handover.py:35-45`) needs the engine to open a trade on synthetic data.
- It never does under the current config (B-02).
- So these three tests skip on every run:
  - `test_handover_resumes_the_session`
  - `test_handover_nobody_picked_up_is_closed_after_the_bell`
  - `test_kill_switch_squares_off_at_current_prices`
- **→ H-12.**

---

## H1. Scheduler and heartbeat

### How the desk is started [code]

| Layer | Behaviour |
|---|---|
| Cloudflare Worker cron | `*/10 2-9 * * MON-FRI` (`wrangler.jsonc:18`) dispatches `scheduler.yml` (`deploy/cloudflare/worker.js:29-48`). The result is only `console.log`ged (`:48`) |
| `scheduler.yml` | Also GitHub cron `*/10 * * * 0-5` (`scheduler.yml:10`). `deploy/scheduler.py`: start window 08:25–14:45, at most 3 starts per day; a run cancelled today means stay stopped |
| `wake.yml` | Sleeps until 08:30 IST, then starts `live.yml` |
| `live.yml` | **morning** job (timeout 355) hands over at 12:20 → **afternoon** job (`needs: morning`, `if: !cancelled()`, timeout 300, checks out `github.ref` = branch tip, `live.yml:107`). Concurrency group `live-desk` (`:31-32`) |
| `live.yml` own cron | `22 3 * * 1-5` = 08:52 IST (`:17`) |

### The 10-06 "missed session" [prod]

| Fact | Source |
|---|---|
| Issue #4 "[desk] The desk did not run on 2026-10-06" was created **2026-10-05T19:54:55Z = 01:24 IST on 10-06**, before the 10-06 session existed | GitHub issue #4 |
| Self-review run #3 (event `schedule`, the 17:10 IST cron for **10-05**) started 2026-10-05T19:44:01Z = **01:14 IST 10-06**, about 8 h late | Actions run 37365296128 |
| The CLI defaults `day` to "today, IST" (`intraday/cli.py:719-724`) → 10-06. `check_session` takes no `now`, so it cannot tell "not yet" from "missed" (`ops/selfreview.py:65-76`) | [code] + probe `test_self_review_judges_a_session_before_it_has_happened` |
| The desk ran on 10-06: two `session start` events (morning and handover), 151 minute-reads, chain `kotak` | journal copy |
| Issue #4 auto-closed at 10:45:57Z on 10-06, after the 10-06 session's `workflow_run` review | issue #4, run 37451864647 |
| Later scheduled self-reviews landed at **22:54, 23:27 and 23:29 IST** (10-06, 10-07, 10-08): 30 minutes from repeating the error | runs #5, #7, #9 |

**Conclusion:** a **false alarm**, caused by late cron delivery plus a date defaulted from the wall clock.

**The worse case [infer, from the same code]:**
- Suppose day D is genuinely missed. No live run means no `workflow_run` review.
- The only backstop is D's 17:10 cron. If it is delivered after midnight, it checks D+1 instead, and files
  "did not run on D+1".
- That issue then auto-closes when D+1 runs.
- D's miss is **never reported under its own date**.
- **→ H-05.** This partially contradicts **V-20** ("self-review detects … missed sessions").

### live.yml's own cron [prod]

| Run | Scheduled (IST) | Started (IST) |
|---|---|---|
| #9 10-05 | 08:52 | 16:07 |
| #11 10-06 | 08:52 | 16:00 |
| #13 10-07 | 08:52 | 15:53 |
| #15 10-08 | 08:52 | 16:13 |
| #17 10-09 | 08:52 | 16:12 |

- GitHub's cron is reliably about **7 h late**.
- Each late run starts after the close. `run_live` then either closes a handed-over session nobody ended
  (`engine.py:1536-1540`, a useful recovery path: **V-H6**) or returns "session is over".
- Its completion triggers self-review through `workflow_run`.
- This is why the Worker exists. The Worker is now the **single** on-time starter.

### Heartbeat [code]

- The engine writes a heartbeat (`engine.py:1322`: halts, safe mode, reconcile) into the journal and site.
- **Nothing watches it.**
  - No job checks "the heartbeat is older than N minutes during market hours".
  - The site is read-only (`worker.js:52-53`) and can't page anyone.
- A Worker dispatch failure (missing token, GitHub 5xx) is logged only to the Worker console (`worker.js:48`).
- **→ H-04.**

### Mid-session code changes [code]

- The afternoon job checks out the **branch tip** (`live.yml:107`, comment: "fixes pushed before the hand-over apply").
- The engineer can merge to `main` without review (G-01, settled).
- So the afternoon can run code that never ran in the morning, on state the morning wrote.
- C-08 (settled): any source edit changes `FEATURE_VERSION` and halts model-gated entries.
- **→ H-09.**

---

## H4. Kill switch

| Mechanism | Evidence | Result |
|---|---|---|
| File `runtime/KILL` (`engine.py:120, 936-946`; config `kill_switch_file: KILL`) | [synth] `test_kill_switch` | Flattens every open trade once; entries halted; `killed_after_restart: true` on the same disk. Clearing it logs a WARN and allows entries again. **Works (control V-H3)** |
| …on GitHub runners | [code] `deploy/journal.sh` saves only `runtime/intraday/**`; `KILL` lives at `runtime/KILL` | Not persisted between jobs; **there is no way to create it on a running runner**. The app's command channel (`intraday_cmds`, `web/intraday_api.py`) is local-only, and the public site is GET/HEAD only (`worker.js:52`) |
| "Cancel the run" (the documented production kill) | `live.yml:78-79, 124-125`: `if: cancelled()` → `intraday live --close-out`; [synth] `close_out` flattened, cash ₹499,985.02 | **Works (control V-H4)** |
| …side effects | `deploy/scheduler.py`: any run cancelled today → stay stopped | Cancel = **flatten and stop the desk for the rest of the day**. There is no "stop entries but keep managing". Next day: nothing records that the desk was killed, so it starts normally |
| …cancel during an entry or exit | [code] `run_live` SIGTERM → `SystemExit` from the handler (`engine.py:1556-1557`), raised wherever Python is: possibly between `broker.execute` and `journal.fill` inside `_open`/`_close` (`:1179-1185`, `:1234-1239`) | [infer] exactly test 8's window. Then `close_out` → `start_session` → the H-01/H-02 behaviour. **Not executed against a real signal**; the closest safe alternative is the test 8 harness, which raises at the same point |
| Kite live guard | `execution/kite.py` docstring: "no kill-switch file at runtime/KILL (touch it to stop all order flow instantly)" | True on a workstation, **not achievable on the hosted runners** |

**→ H-06.**

---

## H5. Retries and rate limits

| Provider | Code | Retry | Rate limit | On final failure |
|---|---|---|---|---|
| Kotak (chain, quotes, candles) | `intraday/kotak.py:132-160` | **1 retry** on HTTP 429/502/503/504 (honours `Retry-After`, capped at 5 s). **None** on timeouts or connection errors (`requests` raises out of `_get`) | `min_gap` 0.06 s between calls (< 25/s); quote batch halves when Kotak says "max value" | `KotakError` → caller falls back (chain: NSE → model; feed: Yahoo) or the step fails |
| NSE | `data/nse.py:55-90` | `tries` attempts, backoff 2 s, 4 s, …; 404 → `NotPublished` (no retry) | `gap` seconds between requests; cookie warm-up | `RuntimeError("NSE answered HTTP …")` |
| Yahoo (feed, global) | `intraday/feeds.py:106-112`, `intraday/brain.py:107-155` | None in the code (yfinance internals only) | — | Empty frame → no bars; the global feed records `health["global"] = "fail …"` |
| Gemini | `intraday/llm.py:240-258` | 1 retry after 1 s on 429/500/503, then the **next model** in a fallback chain of ≥ 6 (G-04) | — | `raise_for_status` → read skipped; logged at INFO (G-05) |
| Claude | `intraday/llm.py:184` | SDK `max_retries=2` | — | Never ran in production (G-06) |
| Ollama | `intraday/llm.py:287-307` | None | — | ReadTimeouts on 10-07 and 10-09 [prod], INFO only |
| News RSS | `intraday/news.py:333-338` | None (8 s timeout per source) | `refresh_min` between fetches | Source skipped |
| Engine loop | `engine.py:1599-1625` | — | — | Any exception escaping `step()` is ERROR-logged. **3 in a row → safe mode** (square off, no entries; config `max_step_failures: 3`) |

**Assessment:**
- Retries are bounded, so nothing loops forever, and the final failures are visible somewhere.
- The asymmetry is that Kotak, the primary feed, does not retry a timeout. Whether a Kotak timeout can escape `step()`
  depends on the caller's fallback. That was not exercised against a real outage, so it is **UNVERIFIED**.
- Production on 10-09 [prod]:
  - two loop overruns, "slow step: 51 s" (12:42) and "65 s" (13:24), WARN only;
  - 5 of 564 polls fell back to Yahoo.
- A 65 s step means one minute's decision was skipped or late.
- **→ H-14 (P4).**

---

## H6. Provider-failure sweep: what each failure becomes

| Input | Failure | What the desk sees | Plausible-but-invalid? | Evidence |
|---|---|---|---|---|
| Index bars (Kotak → Yahoo) | Kotak down | Yahoo bars (labelled; A-04 settled: no per-bar provenance) | Partly: A-04, A-12 (settled) | [prod] "kotak+yahoo (5 of 564 polls)" |
| Index bars | Both stale | `realtime_age` (`feeds.py:78`) → stale-feed handling | No | [code] |
| Option chain (Kotak → NSE → model) | Kotak and NSE down | **Model chain**: fabricated prices and OI, exempt from the stale-chain gate | **Yes: F-01 (settled)** | [code]; **[prod] 0 of 743 minute-reads used the model chain (742 kotak, 1 nse), 10-05…10-09** (Q-12, partial; reads are sampled every ~2–3 min, not every minute) |
| **India VIX** | Missing series or no bar ≤ ts | `model_state` → `vix = … else 14.0` (`engine.py:170`); a stale last bar is used with **no age check** | **Yes → H-08** | [synth] probe `test_missing_india_vix_becomes_a_silent_14`: IV = 0.14 × β |
| **GIFT Nifty** | Old print (e.g. 2 days old) | `parse_gift` accepts it; `preopen` computes an implied gap from it with no timestamp check (`engine.py:808-819`) | **Yes, display/narrative only** (B-05: GIFT never votes) **→ H-13** | [synth] probe `test_gift_print_has_no_age_check` |
| Global markets (Yahoo) | Fetch fails | `health["global"] = "fail …"`; intraday cues require a bar ≤ 15 min old (`brain.py:179`, `live`) or are dropped; `r30` needs `live` | No (control **V-H7**) | [code] |
| Global daily | Fetch returns empty | `_daily_day` latches for the day (`brain.py:117-118`), so no retry until tomorrow; `prior_ret` absent (not invented) | No: absent, not wrong | [code] |
| News / LLM | Timeout | Item read by rules only; LLM read missing; INFO log (G-05 settled) | No | [prod] |
| Journal restore | Branch unreachable | `journal.sh restore` **refuses** to start with an empty account (exit 1) unless the branch truly doesn't exist; SQLite `integrity_check` must be `ok` | No (control **V-H5**) | `deploy/journal.sh:12-40` |
| Warehouse / research fetch | Missing | `warehouse-context.sh` / `research.sh` skip with a warning | No (fails safe) | [code] |
| Broker/journal disagreement | Crash or hand edit | CRITICAL + entries halted | No (fail-closed), but see H-01/H-02/H-04 | [synth] |
| Expired legs left at the broker | Overnight orphan | Never settled; marked nowhere | **Yes: cash and positions are stale "valid-looking" balances → H-03** | [synth] 16c |
| Crash mid-exit | Restart | Journal "closed" while the broker holds a naked short; cash inflated | **Yes → H-01** | [synth] 8b |

### Failure → valid-looking-data paths (the exit criterion)

1. **Model-chain fallback** → fabricated quotes and OI used as if real (F-01, settled; production frequency 0/743).
2. **Missing or stale India VIX** → silent 14.0 or a stale level → model-chain IV and EV (H-08).
3. **Stale GIFT print** → implied gap and narrative (H-13, display only).
4. **Exit crash + restart** → the journal says flat and closed while the broker holds a naked short; cash looks richer (H-01).
5. **Overnight orphan** → expired legs carried at the broker forever, unpriced; account equity looks normal (H-03).
6. **Entry crash** → cash debited for a position the journal doesn't know; equity shown without it (H-02).
7. **Kotak → Yahoo bar fallback** → mixed-provider bars without per-bar provenance (A-04, settled).
8. **Kotak index freeze 15:15–15:28** → a frozen "close" (E-01/F-02, settled).

**Not "valid-looking" (fail visibly or closed):**
- stale feed;
- global cues;
- news and LLM timeouts;
- journal restore;
- warehouse fetch;
- the reconcile halt itself.

---

## H7. Secrets

| Check | Result | Evidence |
|---|---|---|
| Source of values | Environment only (`os.environ`); workflows map `secrets.*` → env per step | `live.yml`, `ai-check.yml`, `broker-check.yml`, `kotak-backfill.yml` |
| Printing | Names or presence only: `"no key (looked for …)"` (`intraday/cli.py:420`), `HAS_* = secrets.X != ''` booleans (`ai-check.yml`). Kotak prints the key **length** (`intraday/cli.py:604`), a minor disclosure, not the value | [code] |
| Transport | Kotak key as an `Authorization` header (`kotak.py:118`), explicitly **blanked** for third-party downloads (`kotak.py:465, 618`); Gemini as `x-goog-api-key`; Ollama as a Bearer header | [code] |
| Persistence | Pattern scan (`AIza…`, `sk-ant-…`) of the journal copy and the gh-pages copy: **no matches**. Error bodies saved are the server's response, not the request | [prod] |
| Live trading credentials | No workflow carries Kite credentials (V-38, settled) | — |
| `set -x` in workflows | None | grep |

**Verdict: no exposure found (control V-H8).**

**Limitation:**
- Workflow **logs** were not downloaded and scanned.
- GitHub masks registered secrets in logs. Fallback names that are not registered would have empty values.
- Values were never read, so a secret could not have been exposed by this audit.

---

## H8. Logging and alerts

**What reaches a human or the engineer (GitHub issues via self-review):**

| Signal | Level / outcome | Alerted? | Evidence |
|---|---|---|---|
| Engine exception | ERROR | ✅ `engine-errors` | `selfreview.py:78-84` |
| Missed session | — | ✅, but day misattribution (H-05) | `:65-76` |
| Workflow `failure` / `timed_out` / `startup_failure` | run conclusion | ✅ | `:214-226` |
| **Reconciliation failure** | **CRITICAL** | ❌ | probe `test_self_review_escalates_error_but_not_critical` |
| **Safe mode** | **CRITICAL** | ❌ | same probe |
| **Kill switch set** | **CRITICAL** | ❌ | `engine.py:942` |
| Overnight orphan "never squared off; ignored" | WARN | ❌ | `engine.py:1382-1383` |
| Slow step / loop falling behind | WARN | ❌ | [prod] 51 s, 65 s on 10-09 |
| Learning grading failed (A-02) | WARN | ❌ | [prod] **10 times** in the 10-09 copy (D-07, settled; cited only as evidence) |
| LLM timeouts | INFO | ❌ | G-05 (settled) |
| 7 soft-failed steps (`doctor`, learn bootstrap, archive ×2, sleeves, progress, backfill) | `::warning::`, job **green** | ❌ | `live.yml:61, 71, 97, 130, 133, 154, 159`; probe |
| Cancelled run | `cancelled` | ❌ (only failure-type conclusions count) | `selfreview.py:220` |
| Worker could not dispatch | `console.log` | ❌ | `worker.js:48` |
| Heartbeat stale during market hours | — | ❌ (no watcher) | — |

**Verdict:**
- The alerting is inverted relative to severity.
- The engine's most severe level (CRITICAL) is reserved for exactly the states that need a human: a broker/journal
  mismatch, safe mode, the kill switch.
- None of those three is ever surfaced.
- **→ H-04.** It extends D-07 (WARN) and G-05 (INFO); those are not re-audited.

---

## H9. Storage, performance, rebuild

| Measure | Value | Evidence |
|---|---|---|
| Journal snapshot (10-09) | **60 MB**: `autolearn/` 47 MB (of which `plan/studies` **44 MB**), `journal.db` 11 MB, `data/` 1.9 MB, `memory.json` 96 KB | [prod] `du` on the copy |
| Plan studies | 6 studies, **6.9–7.9 MB each**, one per autolearn day (10-03 … 10-08), growing | [prod] |
| Retention | `Cycle._retention` covers `datasets`, `runs`, `cycles`, run parquet, models and ledger months. **No `plan/studies`** (`autolearn/cycle.py:548-575`; studies written at `autolearn/research.py:607`) | probe `test_plan_studies_are_outside_autolearn_retention` |
| Projection [infer] | ≈ 7.5 MB × ~250 autolearn days ≈ **1.9 GB/year** in one force-pushed commit, all re-downloaded and re-uploaded by every job (`journal.sh`, `push-dir.sh`) | — |
| Restore time | **0.13 s** local extract plus `PRAGMA integrity_check` on the 60 MB copy (network fetch excluded; not measured on a runner) | [synth] scratch copy |
| Rebuild source | The `journal` branch is the **only** copy: force-pushed, single commit (`push-dir.sh`, A-10 settled). Option chains are kept separately as run artifacts and release tags | [code] |
| Durability window | The journal is saved **only at job end** (`live.yml` save steps). Inside the job, SQLite commits every minute and `broker.json` on every fill, but on the runner's disk. A runner loss (not a cancel) loses everything since the job started; the next job restores the previous snapshot | [code] + test 16b shows that **within** a disk nothing is lost |
| Loop performance | `slow_step_sec` 40 s; 10-09: 51 s and 65 s steps | [prod] |

**→ H-10, H-11.**

**Paper vs live consistency in the durability window:**
- In paper, a lost job loses the broker and the journal **together**, so the restored state is consistent, just old.
- In live, the real broker keeps the fills the restored journal doesn't have. That is test 8a at scale.

---

## H10. Proposed findings (for review; not in the register)

Format follows the register. The status vocabulary is the register's own: BROKEN, VERIFIED, PARTIAL, MISLEADING,
UNVERIFIED, CONTRADICTED. Impact is given for paper, research, recovery and live.

### H-01: An exit interrupted after one leg fills is re-exited in full on restart, leaving a naked short leg and inflated cash while the journal says "closed"

| Field | Value |
|---|---|
| Severity | **P1** (live-blocking) |
| Status | **BROKEN (latent)**. Confirmed on synthetic data. No production trade has been open yet (B-02), so it has never fired in production |
| Component | `intraday/engine.py:1227-1253` `_close`: issues `-l.qty` per journal leg with no check of the broker's actual position. `:1376-1387` `_restore` trusts `intraday_open`. `:896-913` `_reconcile` halts **entries** only (`_blocked`, `:708-709`); `_manage` and `end_session` still exit on the journal's view |
| Reproduction | `phase_h_det_tests.test8_exit_crash`; probe `test8_exit_crash_double_exits_into_a_phantom_naked_short`. Evidence [synth] |
| Expected | A restart after a partial exit closes only what the broker still holds (or halts exits and asks), and the books match the broker |
| Observed | Broker `{25700CE: −65}` (naked short call), cash ₹513,440.14 (vs ₹499,401.33 for a clean round trip), journal trade `closed`, `intraday_open.trades` `[]` |
| Realistic trigger | [infer] a cancelled run (the production kill switch, H-06) or a runner loss during `_close`; a broker rejection mid-exit (`_close` `continue`s on `fill is None` and still marks the trade closed: `:1235-1238`) |
| Impact: paper | Phantom profit and an unpriced short. Account equity and every downstream statistic are wrong |
| Impact: research | Learning and grading would read a "closed" trade with the wrong P&L |
| Impact: recovery | The recovery path itself creates the damage |
| Impact: live | An unhedged short option at the broker that the desk believes is flat |
| Acceptance | A test crashes after each leg of a k-leg exit (k = 2, 4) and restarts. The broker ends flat (or holds exactly the unclosed legs, flagged), cash equals a single round trip, and journal fills equal broker fills. Exits are idempotent against broker positions. A rejected exit leg leaves the trade open |

### H-02: An entry interrupted after the first leg leaves an orphan position that is detected but never resolved, priced or escalated

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **PARTIAL**. Fail-closed detection works; recovery doesn't exist. Confirmed [synth], latent in production |
| Component | `engine.py:1176-1192` `_open`: the broker fill comes before `journal.fill`, the trade append and `_persist`; the in-loop unwind covers rejection (`fill is None`) only, not an exception or signal. `:896-913` `_reconcile`. `ops/selfreview.py:78` |
| Reproduction | `test8_entry_crash`; probe `test8_entry_crash_fails_closed_but_orphans_the_position_silently` [synth] |
| Expected | A restart finds the orphan, records it, then flattens or adopts it, and raises an alert |
| Observed | Broker +65 CE all day, cash debited, journal empty, entries halted for the whole day, 1 CRITICAL event, self-review findings `[]`. End of day leaves the orphan in place |
| Impact: paper | Account equity excludes a held position. The desk silently stops trading for the day |
| Impact: research | That day's "no trade" is caused by an orphan, not a market decision |
| Impact: recovery | Manual `broker.json` edit required |
| Impact: live | A real naked leg with no stop and no owner |
| Acceptance | A crash after leg i of an entry leaves, after restart, either the leg flattened at the next step or adopted into a journaled "orphan" trade with a stop. A GitHub issue is filed the same day. A test covers both legs and both crash points |

### H-03: A position left open across days is dropped from the books; its expired legs are never settled; entries halt indefinitely

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **BROKEN (latent)** [synth] |
| Component | `engine.py:1376-1384` `_restore` (a different day's trades → WARN "…never squared off; ignored", returns `{}`). No expiry settlement for broker positions outside a journal trade. `_reconcile` halts every subsequent day |
| Reproduction | `test16_overnight`; probe `test16_position_left_overnight_is_ignored_and_halts_every_later_day` [synth] |
| Expected | Next session: restore and square off (or settle at expiry) the carried trade, journal it, alert |
| Observed | `open_trades` `[]`; broker still holds `NIFTY29SEP26 25850CE +65 / 25950CE −65` after their expiry; reconcile fails every day after; WARN only |
| Trigger | The afternoon job dies (timeout 300, runner loss) **and** the post-close `live.yml` run (which closes un-ended sessions: V-H6) is skipped, cancelled or > 1 day late |
| Impact: paper | The account is wedged: no entries until someone hand-edits state. Equity carries expired options at entry cost |
| Impact: research | Every later session is a silent no-trade |
| Impact: recovery | No automatic exit |
| Impact: live | An exercised or expired position never reconciled into the books |
| Acceptance | With a prior-day open trade in `intraday_open`, `start_session` squares it off at the next open (or settles it at the expiry close), records the fills, reconciles to `ok`, and files an issue. Expired broker legs are settled by a test |

### H-04: The engine's most severe states (CRITICAL: reconciliation failure, safe mode, kill switch) and soft-failed workflow steps never reach an alert; there is no heartbeat watchdog

| Field | Value |
|---|---|
| Severity | **P2** |
| Status | **VERIFIED** [code + synth + prod] |
| Component | `ops/selfreview.py:78` (`level == "ERROR"` only), `:220` (failure-type run conclusions only); `live.yml:61, 71, 97, 130, 133, 154, 159` (`|| echo "::warning::…"`); `deploy/cloudflare/worker.js:48` (`console.log`); no heartbeat consumer |
| Reproduction | Probes `test_self_review_escalates_error_but_not_critical`, `test_soft_failed_steps_keep_the_live_job_green`, `test_worker_dispatch_failure_is_only_logged`; test 8a `selfreview_findings: []` |
| Expected | Every CRITICAL event, every soft-failed operational step, a failed dispatch and a stale heartbeat in market hours each produce an alert the same day |
| Observed | None do. [prod] 10 WARN grading failures, 2 slow steps and LLM timeouts, all unalerted |
| Relation | Extends D-07 (WARN blind spot) and G-05 (INFO) to **CRITICAL** and to workflow steps. Root causes of those signals are not re-audited |
| Impact: paper | The account can be halted or wedged (H-02, H-03) for days unnoticed |
| Impact: research | Silent no-trade days contaminate any trade-rate statistic |
| Impact: recovery | MTTR is bounded by when a human happens to look |
| Impact: live | Unacceptable: a broker mismatch must page |
| Acceptance | A synthetic journal with one CRITICAL event yields a self-review finding; `live.yml` with a forced soft-fail produces a finding (or the step fails the job); a Worker dispatch failure creates an issue or notification; a stale-heartbeat check runs every N minutes in market hours, and a probe proves it fires |

### H-05: Self-review judges the wrong day when its cron is delivered after midnight IST; a genuinely missed day is reported under the wrong date and auto-closed

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** [prod + synth]. **Partially CONTRADICTS V-20** |
| Component | `ops/selfreview.py:65-76` (`check_session` has no `now`); `:282-289` (`review`); `intraday/cli.py:719-724` (`--day` defaults to "today, IST"); `selfreview.yml:11` (17:10 IST cron, delivered 5–8 h late) |
| Reproduction | Probe `test_self_review_judges_a_session_before_it_has_happened`; issue #4; run 37365296128 |
| Expected | The scheduled review checks the session it was scheduled for (the IST date of the scheduled time, or the last completed trading day); "not yet happened" is never "missed" |
| Observed | 10-05's review ran at 01:14 IST on 10-06 and filed "did not run on 2026-10-06". Later runs landed 23:27 and 23:29 IST, 30 minutes from a repeat |
| Impact: paper | False alarms consume the engineer's queue; a real miss can go unreported |
| Impact: research | — |
| Impact: recovery | Detection of a dead scheduler is unreliable |
| Impact: live | Same, more costly |
| Acceptance | A scheduled review delivered at any time before the next session's open checks the last completed trading day. A test with `now` = 01:14 IST D+1 and no D session files "did not run on D" |

### H-06: The file kill switch can't be used where the desk runs; the real kill switch (cancel) also stops the desk for the day and can strike mid-order

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **PARTIAL** (the mechanisms work; reach and semantics don't) [synth + code] |
| Component | `engine.py:120, 936-946` (`runtime/KILL`); `deploy/journal.sh` (saves `runtime/intraday` only); `worker.js:52-53` (read-only edge); `live.yml:78-79, 124-125` (`--close-out`); `deploy/scheduler.py` (cancelled → stay stopped); `engine.py:1556-1557` (SIGTERM → `SystemExit` anywhere); `execution/kite.py` docstring guard 3 |
| Reproduction | Probes `test_file_kill_switch_works_but_lives_outside_the_saved_journal`, `test_the_phone_app_cannot_reach_the_live_engine` [synth + code] |
| Expected | An operator can halt entries (with or without flattening) on the hosted desk within a minute; the state persists across jobs and days until cleared; a kill never interrupts an order half-done |
| Observed | The only remote kill is cancel → flatten and stop for the day. `KILL` is neither reachable nor persisted. The signal can land between a fill and its journal entry (→ H-01/H-02) [infer] |
| Impact: paper | Coarse; acceptable |
| Impact: research | — |
| Impact: recovery | A kill can cause a reconcile failure |
| Impact: live | The documented guard ("touch it to stop all order flow instantly") does not exist on the runners |
| Acceptance | A persisted kill flag (in the saved journal state) is settable remotely, honoured by the next minute step in both jobs and the next day, with "halt entries" and "flatten" modes. SIGTERM is deferred until the current order sequence completes (test: signal during `_open`/`_close` leaves broker = journal) |

### H-07: Safe mode ("no entries for the session") is forgotten at the 12:20 handover

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **BROKEN** [synth] |
| Component | `engine.py:127-128` (`health` in memory only), `:915-934` `enter_safe_mode`, `:1367-1374` `_persist` (saves risk state, not `safe_mode`); config `max_step_failures: 3 … no entries for the session` |
| Reproduction | Probe `test_safe_mode_is_not_carried_across_the_handover` [synth] |
| Expected | Safe mode persists for the rest of the trading day across the handover and any restart |
| Observed | The afternoon process has `health["safe_mode"] = None`; the entry gate no longer cites it |
| Impact: paper | After a failure storm in the morning, entries resume in the afternoon without anyone checking that the cause is gone |
| Impact: research | — |
| Impact: recovery | A restart silently clears a safety state |
| Impact: live | Same, with money |
| Acceptance | Safe mode is saved in `intraday_open`, restored by `_restore` for the same day, and cleared only by an explicit operator action or the next day. The probe above flips to asserting that safe mode persists |

### H-08: A missing or stale India VIX silently becomes 14.0 (or the last stale value) in the model's implied vol

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED (latent)** [synth + code] |
| Component | `engine.py:165-175` `model_state`: `vix = … if v is not None and len(v.loc[:ts]) else 14.0`; no age check on the last bar |
| Reproduction | Probe `test_missing_india_vix_becomes_a_silent_14` [synth] |
| Expected | A missing or stale VIX is flagged and blocks (or marks as degraded) anything priced off it |
| Observed | IV = 0.14 × `iv_beta`, no event, no flag |
| Reach | Feeds the model chain (F-01, settled), whose production use was 0/743 minute-reads in 10-05…10-09. Plus any other `model_state` caller (Phase I to enumerate) |
| Impact: paper | Mispriced fallback chain, EV and stops when it is used |
| Impact: research | Replays on days with VIX gaps price at 14 |
| Impact: recovery | — |
| Impact: live | Wrong premiums on a fallback path |
| Acceptance | `model_state` returns a staleness flag. With VIX missing or older than N minutes, the model chain is marked degraded and entries priced on it are refused; a test asserts the refusal and the event |

### H-09: The afternoon job runs the branch tip, so code can change mid-session on state written by different code

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** (configuration); impact **UNVERIFIED** (no observed incident) |
| Component | `.github/workflows/live.yml:107` (`ref: ${{ github.ref }}   # the branch tip`); G-01 (unreviewed merges, settled); C-08 (`FEATURE_VERSION` from source text, settled) |
| Reproduction | Probe `test_afternoon_job_runs_the_branch_tip_not_the_mornings_code` [code] |
| Expected | Both halves of a session run one recorded commit; any change waits for the next session (or is an explicit, journaled hot-fix) |
| Observed | Any push before 12:20 applies to the afternoon. The session record does not say which commit made which decision (Phase I) |
| Impact: paper | One "session" can be two systems |
| Impact: research | Per-session attribution is ambiguous |
| Impact: recovery | A bad push breaks the afternoon of a live session |
| Impact: live | Untested code mid-position |
| Acceptance | The afternoon checks out `needs.morning.outputs.sha` (or the morning's `github.sha`); the session start event records the commit for each job; a test reads both and asserts they are equal, or that a hot-fix flag is present |

### H-10: The journal is persisted only at job end, to a single force-pushed copy; a runner loss drops the job's state, and nothing can rebuild it

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** (design) [code]; runner-loss outcome [infer] |
| Component | `deploy/journal.sh` save (end of job only), `deploy/push-dir.sh` (force-push, 3 retries). Related to A-10 (settled: no anchor for the hash chains); this finding is about durability, not integrity |
| Reproduction | Code path. A runner-loss test was **not executed** (it can't be done safely on hosted runners). The closest alternative is test 16b, which shows no loss **on the same disk** |
| Expected | State reaches durable storage at least every few minutes and after every fill; a second copy (a release asset or an artifact with history) allows a rebuild |
| Observed | Up to 3–4 h of journal (fills, decisions, thoughts) exists only on the runner's disk |
| Impact: paper | Broker and journal are lost together: consistent but rolled back (the day's trades vanish) |
| Impact: research | Lost evidence days |
| Impact: recovery | No point-in-time restore |
| Impact: live | The real broker keeps fills the restored journal lacks (H-02 at scale) |
| Acceptance | An incremental save after each fill (or every N minutes) plus a retained history (e.g. daily tags or artifacts). A test kills the job after a fill and shows the next job restores that fill |

### H-11: Plan studies are outside retention and grow by ~7–8 MB per autolearn day inside the journal snapshot

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** [prod + code] |
| Component | `autolearn/research.py:607` (writes `plan/studies/<id>`); `autolearn/cycle.py:548-575` `_retention` (no studies) |
| Reproduction | Probe `test_plan_studies_are_outside_autolearn_retention`; `du` on the 10-09 copy: 44 of 60 MB, 6 studies |
| Expected | Studies are bounded (keep the last N plus anything a registered model or result references) or stored outside the per-run journal |
| Observed | Linear growth: ≈ 1.9 GB/year projected [infer], moved by every job's restore and save |
| Impact: paper | Slower start and save; eventually GitHub push limits, after which the save fails and H-10 widens |
| Impact: research | — |
| Impact: recovery | Restore time grows |
| Impact: live | Same |
| Acceptance | A retention rule for `plan/studies` with a test (N+1 studies → N kept, referenced studies protected); snapshot size flat across 10 synthetic cycles |

### H-12: The repo's handover and kill-switch recovery tests skip on every run, so restart recovery has no CI coverage

| Field | Value |
|---|---|
| Severity | **P3** |
| Status | **VERIFIED** [synth: the repo's own tests run locally] |
| Component | `tests/test_handover.py:35-45` (`_find_handover` skips when the engine opens no trade); B-02 (settled: no trades under the current config) |
| Reproduction | `pytest -rs tests/test_handover.py` → `2 passed, 3 skipped` ("no open position mid-session in the sample") |
| Expected | Recovery tests inject a position (as this audit's harness does) and never depend on the strategy trading |
| Observed | The resume, unclosed-handover and kill-switch-square-off tests are skipped |
| Impact: paper | Regressions in H-01…H-03-type code would pass CI |
| Impact: research | — |
| Impact: recovery | Untested |
| Impact: live | Untested |
| Acceptance | The three tests run (0 skipped) with an injected trade; a CI check fails on a skip in `test_handover.py` |

### H-13: Pre-open GIFT Nifty prints are used without an age check

| Field | Value |
|---|---|
| Severity | **P4** |
| Status | **VERIFIED**, display and narrative only (B-05: GIFT never votes) [synth] |
| Component | `data/nse.py:351` `parse_gift`; `engine.py:802-819` `preopen` → `gift_implied_gap(...)` without the print's timestamp |
| Reproduction | Probe `test_gift_print_has_no_age_check` (a 2-day-old print is accepted) |
| Expected | A print older than the last session close is labelled stale or ignored |
| Observed | Accepted and turned into an implied gap |
| Impact: paper / research / recovery / live | Misleading pre-open narrative; no decision impact today. If GIFT ever votes, this becomes P2 |
| Acceptance | `preopen` ignores prints older than the previous close, with a test |

### H-14: Retry policy is uneven and loop overruns are only WARN; a Kotak timeout is not retried

| Field | Value |
|---|---|
| Severity | **P4** |
| Status | **PARTIAL**. Overruns observed [prod]; timeout propagation **UNVERIFIED** |
| Component | `intraday/kotak.py:132-160` (retries 429/5xx once; no timeout retry); `intraday/llm.py:287-307` (Ollama, none); `intraday/news.py:333-338` (none); `engine.py:1620-1624` (slow step → WARN); config `slow_step_sec: 40` |
| Reproduction | [prod] 10-09 12:42 "slow step: 51 s", 13:24 "65 s"; code reading |
| Expected | A per-provider policy (retry on timeouts with jitter, a per-minute budget so a step can't exceed 60 s) and an alert when steps overrun |
| Observed | A 65 s step skips or delays a minute's decision; the cause is unrecorded |
| Impact: paper | Missed or late minutes |
| Impact: research | Gaps in minute-level records (A-06-like) |
| Impact: recovery | Three timeouts in a row → safe mode → (H-07) forgotten at handover |
| Impact: live | Late orders |
| Acceptance | Step timing broken down by provider is journaled; a fake-provider test with a timeout shows one retry and a bounded step time; overruns above a threshold count toward the H-04 alert |

---

## H11. Controls verified (proposed for the register's V-list)

| # | Control | Evidence |
|---|---|---|
| V-H1 | A same-day restart (graceful SIGTERM path or hard kill) restores open trades, closed trades, the trade count, day-start equity and the risk state; journal rows survive a hard kill (per-minute commit); reconcile is `ok`; the chain is rebuilt in one step | test 16a/16b [synth] |
| V-H2 | Broker/journal reconciliation runs at session start and **fails closed** (CRITICAL, entries halted) with an exact diff | test 8a/8b/16c [synth]; `engine.py:896-913` |
| V-H3 | The file kill switch flattens every open trade exactly once, halts entries, survives a restart on the same disk, and logs its clearing | `test_kill_switch` [synth] |
| V-H4 | Cancelling a live run squares off through `--close-out` at current prices and closes the session | `live.yml:78-79, 124-125`; `close_out` [synth] |
| V-H5 | Journal restore runs a SQLite integrity check and refuses to start an empty account when the branch exists but can't be fetched | `deploy/journal.sh:12-40` |
| V-H6 | A handed-over session that nobody closed is closed by the next run after the bell (the daily post-close `live.yml` cron does this) | `engine.py:1536-1540`; [prod] post-close runs |
| V-H7 | Global-market cues require a completed bar ≤ 15 min old; fetch failures are recorded in `health`, not filled | `brain.py:139-188` |
| V-H8 | Secrets: environment-only, never printed (names, presence or length only), header transport, blanked for third-party hosts; none found in journal or site copies | § H7 |
| V-H9 | Bounded retries everywhere (no unbounded loops); repeated step failure enters safe mode and squares off | § H5; `engine.py:1599-1617` |

---

## H12. Settled findings touched (cited, not re-audited)

| ID | How it appears in H |
|---|---|
| A-02 / D-07 | Grading failure: now **10** WARN events in the 10-09 copy, all unalerted (H-04 evidence) |
| A-04, A-12 | The Kotak → Yahoo fallback (5 of 564 polls on 10-09) |
| A-06 | The handover gap; H-14 overruns add minute gaps |
| A-10 | Single force-pushed snapshot (H-10 extends it to durability) |
| B-02 | Zero trades → H-01…H-03 latent in production, and H-12 (tests skip) |
| B-04 | Armed setups not restored (test 16: `armed {}`) |
| B-05 | GIFT display-only (bounds H-13) |
| C-08 | `FEATURE_VERSION` (raises the stakes of H-09) |
| E-01 / F-02 | Frozen index 15:15–15:28 (a valid-looking-data path; listed in § H6) |
| F-01 | Model-chain fallback; **Q-12 partially answered:** 0/743 minute-reads in production used it (10-05…10-09) |
| G-01 | Unreviewed merges to `main` (H-09) |
| G-05 | LLM failures at INFO (H-04 relation) |
| V-20 | **Partially contradicted** by H-05 |

---

## H13. Limitations and tests not executed

| Item | Why not | Closest safe alternative used |
|---|---|---|
| Real SIGTERM / GitHub cancel during an order | Would need a live run or a real signal in the order path | Test 8: an exception raised at the same point inside `broker.execute`; the SIGTERM path in 16a |
| Runner loss mid-job | Not safely reproducible on hosted runners without touching production | Code reading of the save points; 16b (same-disk hard kill) |
| Provider outages (Kotak, NSE, Yahoo, Gemini, Ollama) against real endpoints | No network or credential use allowed | Code reading plus the production record (fallback counts, timeouts) |
| Kotak timeout → step failure → safe mode | Needs a fake Kotak client wired through the live engine; outside the time-boxed harness | Code reading (H-14 marked UNVERIFIED) |
| Restore time on a GitHub runner (network) | Would need a workflow run | Local extract plus integrity check (0.13 s) |
| Workflow log secret scan | Logs not downloaded (a read of production logs was not needed to answer H7) | Code and workflow reading plus a pattern scan of the persisted journal and site |
| Cloudflare Worker dispatch history | No Cloudflare access | The Worker source; GitHub-side run timings |
| Test 16 with armed setups present | The synthetic sample armed 0 setups at the restart minute | B-04 (settled) already covers it by code |

**Probe results** (`audit/probes/test_phase_h_probes.py`):
- First full run: **15 passed in 106.97 s**.
- `test_safe_mode_is_not_carried_across_the_handover`, added afterwards: **1 passed in 4.67 s**.
- Final full run: **16 passed in 116.52 s**.

**Repo tests run:** `tests/test_handover.py` → **2 passed, 3 skipped** (581.73 s).

**Not run in Phase H:** the full repo suite. A-19 (settled) makes `test_kotak` fail on every day after 2026-10-06.

**Final full probe run:** `16 passed in 116.52s`.

---

## H14. Handoffs to Phases I–L (listed only; not started)

| To | Item |
|---|---|
| **I** (journal / auditability) | Which commit made each decision (H-09); whether orphan or crash events can be reconstructed from the journal alone (H-01/H-02); enumerate every `model_state` caller (H-08); fills vs broker ledger as an audit trail; whether the CRITICAL event's `data` is enough to repair state by hand |
| **J** (UI truthfulness) | Does the site show "halted: broker and journal disagree", safe mode or the kill switch prominently? Does it show equity including orphan legs (H-02/H-03)? Does the heartbeat display its age? |
| **K** (scorecard / final) | Readiness gates: H-01 (P1) and H-04 block any live mode; H-02/H-03/H-06/H-07 block an unattended paper claim of "self-healing" |
| **L** | Q-10/Q-11 (E → H handoffs) were not in the approved nine areas and remain open; carried forward |

---

## H15. Recommendation

1. **Accept Phase H as complete for review.**
   - All nine areas have evidence-backed conclusions or documented limitations.
   - Tests 8 and 16 have recorded outcomes.
   - The failure → valid-looking-data paths are enumerated (§ H6).
   - Every proposed finding has a severity, evidence and an acceptance test.
2. **Owner decision needed:** whether H-01 … H-14 and V-H1 … V-H9 go into the canonical register, as written or amended.
3. **For the remediation roadmap** (not done here, since fixing is out of scope), the order that matters most:
   - **H-01** (idempotent exits against broker positions);
   - **H-04** (alert on CRITICAL, soft-fails and a stale heartbeat);
   - then **H-02 / H-03** (orphan resolution);
   - then **H-07 / H-06** (persisted safety states).
   - These four groups are prerequisites for any unattended operation, and H-01/H-04 for any live mode.
4. **Phase I** should not start without a separate approval.
