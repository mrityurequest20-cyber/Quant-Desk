# QuantDesk Findings Register (cumulative)

Read-only forensic audit. This register grows phase by phase; IDs are stable once issued. A later phase may
upgrade, downgrade or close a finding, and records why in its row of the change log at the bottom.

**Evidence base (Phase A):**

| Ref | Value |
|---|---|
| Code (`main`) | `c96909f` (2026-10-09) |
| Runtime state (`journal` branch) | `ecd03156`: the snapshot saved at the 12:20 IST hand-over on 2026-10-09 |
| Research priors (`research` branch) | `201028be` (run of 2026-10-03) |
| Public site (`gh-pages`) | `4f13bd26` |
| Releases seen | `warehouse`, `chains-2026`, `option-minutes-2026`, `external-aeron7` (tags only; assets not downloaded in Phase A) |
| Python env for probes | isolated venv, `pip install -r requirements.txt` → pandas 3.0.6, numpy 2.5.3, yfinance 1.7.0 |

Status vocabulary: VERIFIED · PARTIAL · BROKEN · MISLEADING · UNVERIFIED · CONTRADICTED.
Severity: P0 safety/integrity/live-trading · P1 major correctness/research/learning · P2 important limitation ·
P3 moderate · P4 minor.

---

## Summary table

| ID | Title | Sev | Status | Phase |
|---|---|---|---|---|
| A-01 | The autolearn ledger has never recorded a live prediction | P1 | CONTRADICTED (claim) | A1/A2 |
| A-02 | Catch-up grading crashes at every session start and hand-over | P2 | BROKEN | A2 |
| A-03 | Unpinned dependencies changed runtime semantics (root cause of A-02) | P2 | VERIFIED | A1 |
| A-04 | Provider fallback leaves no per-bar provenance | P2 | PARTIAL | A2 |
| A-05 | Live 5-minute bars are bucketed by row count, so live and training features differ | P2 | BROKEN (latent) | A3 |
| A-06 | Every recorded session has a 12:20–12:21 hole (the hand-over) | P3 | VERIFIED | A2 |
| A-07 | `LockBox.verify` passes when the locked rows' count changes | P3 | CONTRADICTED (claim) | A3 |
| A-08 | `build_samples` back-fills σ from later bars | P4 | VERIFIED | A3 |
| A-09 | News is graded from publish time, not from when the desk saw it | P2 | MISLEADING | A3 |
| A-10 | Journal persistence is a force-pushed snapshot; the hash chains have no anchor | P2 | MISLEADING | A1/A2 |
| A-11 | Chain snapshots carry fetch time, not quote time; IV is back-solved from a stale LTP | P3 | PARTIAL | A2 |
| A-12 | Yahoo history is not stable within a day, so session model fits don't reproduce | P3 | VERIFIED (cause UNVERIFIED) | A2 |
| A-13 | Afternoon journal events are back-dated to 09:15 | P3 | VERIFIED | A2 |
| A-14 | Warehouse revisions overwrite rows with no history | P3 | VERIFIED | A2 |
| A-15 | Replay memory persists across replays: an earlier day can use later lessons | P3 | VERIFIED (code path) | A3 |
| A-16 | Futures volume gaps become 0, and pre-Kotak sessions have no volume at all | P3 | VERIFIED | A2 |
| A-17 | Kite ticks without an exchange timestamp get the wall clock | P4 | VERIFIED (code path; Kite untested) | A2 |
| A-18 | Yahoo 5m `completed()` uses a 1-minute bar length | P4 | VERIFIED (code path) | A2 |
| A-19 | The test suite has a wall-clock time bomb: `test_kotak` fails on every day after 2026-10-06 | P4 | VERIFIED | A1 |
| B-01 | The analyst's weighted evidence has no causal path to an executed trade under the current config | P2 | MISLEADING (README) | B1 |
| B-02 | Zero trades is structural: every directional plan is gated, and the only other path (iron fly) never clears EV | P2 | VERIFIED | B4 |
| B-03 | Gated opportunities on the confirm path are never journaled, and decision rows don't identify the gate or link to the setup | P2 | VERIFIED | B3 |
| B-04 | The armed lifecycle (armed / expired / not reached) is not persisted | P3 | VERIFIED | B3/B5 |
| B-05 | Dead or display-only features: max pain unreachable, `iv_move` orphan, prior-day value area unused, GEX/IVP/GIFT/flows narrative only | P3 | VERIFIED | B1 |
| B-06 | Setups are armed and shown as "Waiting at the level" though authorization can never pass | P3 | MISLEADING | B5 |
| B-07 | No-trade learning never grades plan-gate rejections of armed setups | P2 | BROKEN | B5 (→ D6) |
| B-08 | The breaking-news veto fires on retellings days after an event and on irrelevant stories; question-style previews are missed | P3 | VERIFIED | B1 |
| B-09 | Trigger engine gaps: LTP sampling misses, fire-time vetoes from the previous minute, repeated re-fires | P3 | PARTIAL | B5 |
| B-10 | Opening range, initial balance and session minutes count from the first bar present, not 09:15 | P3 | VERIFIED | B2 |
| B-11 | What-if `as_run` does not reproduce what ran (model chain, no memory, no learner, no brain, no breadth) | P3 | MISLEADING | B4 |
| C-01 | Even an approved plan model can't let a live directional plan through: the desk builds spreads, the gate takes single legs only | P1 | BROKEN (latent) | C2 |
| C-02 | The session DirectionModel's validation gate passes on random walks 10% of the time | P2 | VERIFIED | C1 |
| C-03 | No automatic demotion or rollback of a degraded champion | P2 | VERIFIED (missing) | C1 |
| C-04 | Two cost models: autolearn's futures STT is 2 bps vs the desk's 5 bps | P3 | CONTRADICTED (internal) | C3 |
| C-05 | The iron fly (the only non-directional setup) cannot pay its costs on an intraday hold | P2 | VERIFIED | C3 |
| C-06 | EV model limits: fixed IV, no calibration from outcomes, an unvalidated P(up) prior | P3 | PARTIAL | C3 |
| C-07 | Lockbox peeks are unbounded: one per cycle in which a candidate passes walk-forward | P3 | PARTIAL | C1 |
| C-08 | `FEATURE_VERSION` hashes source text: any edit (even a comment) invalidates every artifact and halts entries | P3 | VERIFIED | C1 |
| D-01 | Factor learning is indistinguishable from noise: placebo p = 0.70; noise "graduates" a factor in 78% of draws | P1 | MISLEADING | D2 |
| D-02 | Learning has a negligible effect on decisions: memory ON vs OFF changed 2 of 2,984 minute-decisions, 0 trades | P2 | VERIFIED | D2/D7 |
| D-03 | The learning record (`memory.json`) is aggregate-only, mixes provenance and cannot be replayed | P2 | VERIFIED | D1 |
| D-04 | No recency, no regime split, no demotion state; anti-predictive factors keep voting at 0.5× | P2 | VERIFIED | D3/D4/D5 |
| D-05 | No-trade learning is absent in production: no rejection class is counterfactually graded | P2 | BROKEN | D6 |
| D-06 | No baseline or control for learning; the "getting smarter" learning KPIs are null | P3 | VERIFIED | D7 |
| D-07 | Self-correction blind spot: self-review files only ERROR events, so the 8 WARN grading failures went unseen | P2 | VERIFIED | D8 |
| D-08 | Truncated graded-id lists let old headlines be graded again (latent duplicates) | P4 | VERIFIED | D1 |
| E-01 | The sleeves' forward ledger settles on a frozen index: Kotak bars freeze 15:15–15:28 every session; the gap reached −27 bps and flipped both NIFTY trades' sign; the rules use that P&L | P1 | MISLEADING | E5 |
| E-02 | Paper-account eligibility = "not rejected": a zero-edge sleeve qualifies ≈ 93% of the time after 10 trades | P2 | VERIFIED | E5 |
| E-03 | D1 drift enters every live EV without a registered study; its cost hurdle assumes fair option prices, which the desk's own results contradict | P3 | PARTIAL | E3 |
| E-04 | No program-wide multiplicity accounting: the experiment ledger covers 2 runs; the duplicate guard admits one-number variants | P2 | PARTIAL | E2 |
| E-05 | v2 re-tests the same held-out instruments (not a second holdout); the spec has no frozen sample end | P3 | PARTIAL | E2/E4 |
| E-06 | Result provenance gaps: 1 of 7 results stamped (dirty); the digest can't tell appends from revisions; edge inputs not archived | P3 | PARTIAL | E1/E7 |
| E-07 | L1's economics untested where most held-out weight sits (no quotes for FINNIFTY/MIDCPNIFTY/BANKEX/NIFTYNXT50; entry at the close) | P3 | UNVERIFIED | E4 |
| E-08 | L3 parity: the vol study's "desk" baseline omits the live IV blend; the better model is not deployed | P3 | PARTIAL | E6/E8 |
| E-09 | External minutes "verified" against Yahoo daily H/L/C on 80 sessions only | P4 | PARTIAL | E6 |
| F-01 | The model-chain fallback trades on fabricated data: exempt from the stale-chain gate; fabricated OI drives the OI-wall vote; fills labelled "option chain" | P2 | VERIFIED (latent) | F3 |
| F-02 | The 15:15–15:28 index freeze is in Kotak's index series (the future keeps trading) and also contaminates basis, 10.5% of graded factor reads and the sleeves' 15:20 deltas | P2 | VERIFIED | F2 |
| F-03 | Fixed r/q instead of the chain's forward: put−call ATM IV gaps of ±3 vol pts near expiry bias the 25-delta skew level | P4 | PARTIAL | F3 |
| F-04 | Paper fills ignore depth (10 lots at the price of 1) and fall back to stale chain prices with no move-away check | P3 | PARTIAL (latent) | F4 |
| F-05 | Exercise STT 0.125% in code vs 0.15% since 1 Apr 2026; paper expiry settlement charges none | P4 | PARTIAL | F4/F5 |
| F-06 | The Kite live adapter drops partial fills, stamps naive local time, ignores the futures roll and legs sequentially | P3 | BROKEN (latent) | F6 |
| F-07 | Calendar and contract edges: no holidays after 2026; 5-day futures history across a roll; the model chain can price unlisted weeklies | P4 | VERIFIED | F1 |

Verified-working controls (V-xx) and open questions (Q-xx) are at the end.

---

## Findings

### [A-01] The autolearn ledger has never recorded a live prediction
Severity: **P1** · Status: **CONTRADICTED** (the docs' claim, by the persisted state)

**Claim**
- `docs/ARCHITECTURE.md`: "The desk learns from its own predictions". Its diagram shows, for every completed 5-minute
  bar and each symbol: features → champion/challengers/rollback → "ledger: decision".
- `README.md` (§ The self-learning paper loop): "At every 5-minute bar it writes each registered model's prediction to
  an append-only, hash-chained ledger".

**Actual behavior**
- `LiveLearner.on_bar` returns before writing anything when no model is registered:
  - `quantdesk/autolearn/live.py:96-97`: `if not self.models and self.plan is None: return None`;
  - `quantdesk/autolearn/live.py:120-121`: `if not self.models: return None`.
- No model has ever been registered:
  - `autolearn/registry/state.json` (journal snapshot): `champion: null, challengers: []`;
  - the plan registry is the same.
- The only candidate trained (`baseline`) failed validation in every cycle. The 2026-10-08 cycle failed 7 gates:
  AUC 0.496, Brier skill −0.034, expectancy −4.0 bps, 20 trades.
- So there is no `runtime/intraday/autolearn/ledger/` directory at all, and every recorded cycle shows
  `outcomes_resolved: 0` (cycles 2026-10-03 … 10-08).

**Execution path**
`run-session.sh` → `intraday live` → `_live_engine` (`intraday/cli.py:114-116`) → `IntradayEngine.step` →
`_learn_step` → `LiveLearner.on_bar` → early return `None`. Nothing is persisted.

**Impact**
- The "prediction → outcome → evaluation" chain of the autolearn loop has produced zero records.
- The loop trains only offline, on Yahoo and recorded bars. Its own live predictions never enter it, because there
  are none.
- The baseline is never shadow-recorded, so there is no live record to compare a future challenger against.
- The hash chain, dedup and leakage guards of `Ledger` are correct in code (V-01), but have guarded nothing in
  production.

**Reproduction**
`audit/probes/test_phase_a_probes.py::test_livelearner_records_nothing_without_registered_model` and
`::test_persisted_state_facts` (both pass).

**Recommended fix (not applied)**
- Always ledger the feature vector and the baseline's prediction, with role `baseline`, so live evidence accumulates
  before any registration.
- Or change the docs to say the ledger is empty until a model registers.

**Confidence:** High.

### [A-02] Catch-up grading crashes at every session start and hand-over
Severity: **P2** · Status: **BROKEN**

**Claim**
`intraday/engine.py:607-610`: "At the start of a session it catches up on anything a crashed close left ungraded".
The README says the same: "It grades at the close, and catches up at the next open if a run died".

**Actual behavior**
- The journal's `events` table has `WARN learning grading failed: Cannot losslessly convert units` 8 times: every
  session start and hand-over from 2026-10-05 12:22 through 10-09 09:15.
- The only non-failing catch-up, 10-05 09:15, had nothing to grade ("0 news, 0 factors").
- Close-time grading succeeded on each day (`learning graded: …` at 15:31).

**Root cause (reproduced)**
- At session start, `self.bars` is Yahoo 1-minute history. Under pandas 3 + yfinance 1.7 its index is
  `datetime64[s]`; a live fetch of `^NSEI` in this session confirmed `datetime64[s, Asia/Kolkata]`.
- `learning.forward` calls `idx.searchsorted(t)` (`intraday/learning.py:124`) with a microsecond-precision
  `Timestamp` from the journal, which raises `ValueError: Cannot losslessly convert units`.
- The whole pass aborts in `_learn`'s `except` (`engine.py:620-622`). Nothing is graded, and the run continues.
- At the close the same call succeeds. The in-memory index then also holds the day's Kotak-polled bars. Kotak's
  timestamps are parsed from strings (`kotak.py:201`), and under pandas 3 every string format tried parses to `us`.
  `concat` of `s` with `us` up-casts the whole index, so grading succeeds by accident.
- The exact Kotak payload format is not observed (no key here), so this mechanism is inferred, not seen. It is
  consistent with every logged success and failure.
- The failing timestamps are the thoughts' `ts` (microsecond precision, e.g. `2026-10-09 12:18:04.408148`). News
  `ts` values have second precision.

Reproduction on a scratch copy of the journal: index unit `s` → FAIL, `ms` → FAIL, `us` → OK, `ns` → OK.

**Impact**
- The catch-up path has never worked in the recorded history.
- If Kotak is unavailable for a whole session (Yahoo-only bars), close-time grading will also fail. Factor, news and
  setup learning for that day would then be silently lost, with only a WARN event.

**Reproduction**
The script in the Phase A notes (`QUANTDESK_FORENSIC_AUDIT.md` § A.6). Read-only: it runs on a copy of the journal.

**Recommended fix**
Normalize every bar index to one unit (e.g. `.as_unit("ns")`) in `normalise_bars`, and pin dependencies (A-03).

**Confidence:** High.

### [A-03] Unpinned dependencies changed runtime semantics
Severity: **P2** · Status: **VERIFIED**

- **Claim:** "Deterministic" and "two runs are identical" (README § Backtesting, § How we know there's no
  look-ahead).
- **Actual:**
  - `requirements.txt` uses only lower bounds (`pandas>=2.1`, `yfinance>=0.2.54`, `numpy>=1.26`, …) and there is no
    lock file;
  - every GitHub run installs the newest versions; today that is pandas 3.0.6 and yfinance 1.7.0;
  - the datetime-resolution change between pandas 2 and 3 is what broke A-02.
- **Impact:**
  - a live, research or learning run cannot be reproduced bit-for-bit later;
  - a silent upstream change can disable learning (A-02) or alter features with no code change in this repo.
- **Fix:** a lock file (pip-tools / uv), with the versions recorded in every result's provenance (`research/provenance.py`
  already records the commit and data digests).
- **Confidence:** High.

### [A-04] Provider fallback leaves no per-bar provenance
Severity: **P2** · Status: **PARTIAL**

- **Claim:** "the session review says which source served" (README § Kotak Neo).
- **Actual:**
  - `KotakIntradayFeed.poll` (`intraday/kotak.py:434-453`) serves any minute Kotak fails from Yahoo, with no mark on
    the bars.
  - Prior-session history always comes from Yahoo (`history` → `super().history`, `kotak.py:408-414`), while today
    comes from Kotak. So prior-day levels (PDH/PDL, CPR) and today's bars come from different providers.
  - The recorder writes plain OHLCV with no source column (`intraday/recorder.py:26-36`).
  - Provenance survives only as an aggregate counter in the feed name. Journal state on 2026-10-09:
    `"feed": "kotak+yahoo (1 of 558 polls from Yahoo)"`. Which minute came from Yahoo can't be recovered.
  - The autolearn `gather()` picks one source per session (`autolearn/cycle.py:193-205`), but its store
    (`bars5/*.parquet`) keeps no source column. On the next cycle every stored session is just "store".
- **Impact:**
  - training data, replays and audits can't tell a Kotak bar from a Yahoo bar;
  - a provider-specific bias (timestamp convention, last-minute revision) can't be isolated.
- **Reproduction:** `::test_kotak_failure_silently_serves_yahoo_bars` (passes).
- **Fix:** a `source` column on every recorded bar and in `bars5`; a per-session source in the dataset manifest.
- **Confidence:** High.

### [A-05] Live 5-minute bars are bucketed by row count, so live and training features differ
Severity: **P2** · Status: **BROKEN (latent)**

**Claim**
- `autolearn/features.py` module docstring: "a model trained on one definition is never fed another".
- `FEATURE_VERSION` hashes the feature code to guarantee this.

**Actual behavior**
- The two live paths cut today's 1-minute bars by row count before resampling:
  - `IntradayEngine._quant_state` (`intraday/engine.py:1050-1056`): `n5 = len(today) // 5;
    five = to_5m(today.iloc[:n5 * 5])`;
  - `LiveLearner.on_bar` (`autolearn/live.py:100-102`): the same.
- The training path (`build_samples` via `samples_from_bars` → `to_5m(clean)`) buckets by clock.
- After any missing minute, the live path's last "completed" 5-minute bar holds only part of its minutes, and it is
  still stamped and used as complete. A-06 makes this certain every afternoon: 12:20–12:21 are always missing.
- At 12:30 the live last bar (12:25) contains 2 of its 5 minutes.

**Evidence on real data (2026-10-08 NIFTY recorded bars)**
At 12:30, 13:00, 14:00 and 15:00, the live-path features (`r5`, `vwap_z`, `rsi`) differ from the clock-path features:
4 of 4 afternoon checks.

**Impact**
- **Today:** the session DirectionModel is advisory, and it is "no edge" every day, so this has no trade effect.
  LiveLearner is inert (A-01).
- **The moment a champion is promoted:** its live inputs will differ from what it was validated on for every
  afternoon bar. That is train/serve skew, which no FEATURE_VERSION check can catch.

**Reproduction**
`::test_rowcount_bucketing_makes_partial_last_bar`, `::test_rowcount_bucketing_on_real_recorded_session` (both pass).

**Fix**
Select completed 5-minute buckets by clock (`bar_start + 5min <= now`), as `intraday/features.py:_completed` already
does for the analyst.

**Confidence:** High.

### [A-06] Every recorded session has a 12:20–12:21 hole (the hand-over)
Severity: **P3** · Status: **VERIFIED**

- **Evidence:**
  - every full recorded session in the snapshot (10-05 … 10-08, both indices) misses 12:20 and 12:21; 09-29 misses
    12:20;
  - the morning job stops at `--until 12:20`;
  - the afternoon engine loads its in-memory history from Yahoo (`start_session` → `feed.history`), but the recorder
    only writes *polled* bars (`engine.py:254-262`), never the history it loaded. So the two minutes are never written.
- **Impact:**
  - recorded data is what replays, the autolearn dataset (recorded wins a session with ≥ 60 5-minute bars,
    `cycle.py:198-202`) and the plan research use;
  - the 12:20 5-minute bar is built from 3 of 5 minutes, with the wrong open;
  - live (in-memory, gap-free) and replay (recorded, gapped) differ every afternoon, which is a parity break.
- **Fix:** record the afternoon's restored history for today, or backfill the gap from Kotak candles at hand-over.
- **Confidence:** High.

### [A-07] `LockBox.verify` passes when the locked rows' count changes
Severity: **P3** · Status: **CONTRADICTED** (the claim "the locked sessions still hash the same")

- **Code:** `autolearn/validation.py:136`:
  `return [] if fp == lock["fingerprint"] or len(part) != lock["rows"] else [...]`. Any change that also changes the
  row count is reported as "no problem".
- **Probe:** every locked label was flipped and one row dropped; `verify()` returned `[]`.
  `::test_lockbox_verify_silent_when_rowcount_changes` passes.
- **Also:**
  - the lock (2026-09-22 … 10-01) is no longer the newest data: walk-forward fold 4 now tests 10-02 … 10-08, after it;
  - the lock's sessions exist only as long as Yahoo's ~60-day 5-minute history, plus the store, keeps them;
  - `gather()` protects them from retention (`cycle.py:208-209`), so this part is handled.
- **Fix:** treat a row-count change as a failure, unless the sessions aged out completely.
- **Confidence:** High.

### [A-08] `build_samples` back-fills σ from later bars
Severity: **P4** · Status: **VERIFIED**

- **Code:** `autolearn/features.py:163`: `lr.rolling(12, min_periods=4).std().bfill()`. The first 3 bars of each
  session get a σ computed from bars 1–4 (the future). `day_ret` (line 164) inherits it.
- **Scope:**
  - these columns are not model inputs (the probe confirms the model features stay unchanged);
  - they drive only the evaluation breakdowns `vol_regime` and `market_regime` (`autolearn/evaluate.py:178-180`);
  - those breakdowns are also tercile-cut on the whole test set.
- **The live path differs:** `Ledger.resolve` computes them causally (`ledger.py:173-179`). So regime breakdowns of
  validation and live records aren't comparable.
- **Reproduction:** `::test_build_samples_sig5_uses_later_bars` (passes).
- **Confidence:** High.

### [A-09] News is graded from publish time, not from when the desk saw it
Severity: **P2** · Status: **MISLEADING**

**Claim**
`intraday/learning.py:140`, `grade_news` docstring: "against the index's next 30 minutes from when the desk could act
on it".

**Actual behavior**
- `forward(bars.get(sym), r.ts, from_open=True, …)` (`learning.py:153`) uses `ts`, the publish time from the RSS
  feed. It does not use `seen_at`, the time the desk fetched the story, which the journal does store.
- The journal's 1,737 in-session-published headlines:
  - publish→seen lag: median **74 min**, 75th percentile 177 min, 90th percentile ≈ 20 h;
  - 1,246 have lag > 15 min, 104 of them high-impact.
- LLM reads are also graded from publish time, although they count live only from their arrival (`rd["at"]`).

**Impact**
- The news trust multipliers (`news_event`, `news_source`, `news_reader`) measure whether a headline called the
  30 minutes after it was *published*.
- The desk acted on it a median 74 minutes later. The learned trust describes windows the desk never traded.
- This biases trust toward stories whose move happened before the desk could see them.

**Contrast**
`deploy/whatif.py:89` correctly makes stories visible at `seen_at`. Live visibility is effectively seen-time
(V-08), so only the grading uses the wrong clock.

**Reproduction**
`::test_grade_news_uses_publish_time_not_seen_time`: a story seen at 11:15 is graded a full hit on the 10:00–10:30
move.

**Fix**
Grade from `max(ts, seen_at)`, and for LLM tones from the read's `at`.

**Confidence:** High.

### [A-10] Journal persistence is a force-pushed snapshot; the hash chains have no anchor
Severity: **P2** · Status: **MISLEADING**

**Claims**
- "Records are never edited … `autolearn verify` detects any edit or reordering" (`docs/ARCHITECTURE.md`).
- The ledger is "append-only".
- The sleeves ledger is "append-only".

**Actual behavior**
- All runtime state (journal DB, memory, autolearn registry and logs, sleeves ledgers) is saved by
  `deploy/journal.sh save` → `deploy/push-dir.sh`.
- That writes one parentless commit (`git commit-tree` without `-p`) and runs `git push -f`. Every save replaces the
  branch; earlier states become unreachable.
- The hash chains (`autolearn/store.py`) verify a file only against itself. Truncating the tail, or re-hashing after
  an edit, passes `verify`, and nothing outside the file holds a head hash.
- Concurrency:
  - `restate.yml` uses the group `journal-admin`, not `live-desk`;
  - it only waits for `live.yml` (`restate.yml:40-51`), not for `autolearn.yml` or `learn.yml`;
  - its restore → save window can interleave with a desk or learning run, and the last `push -f` wins. That is a lost
    update of either side.

**Impact**
- The "immutable" guarantees hold only inside one runner's lifetime.
- History can't be audited across days from the branch.
- A stale save can silently roll back ledgers. The sleeves ledger is append-only by design and saved the same way.

**Fix**
- Commit with a parent (or archive snapshots as release assets), and anchor each chain's head hash outside the
  snapshot, e.g. in the commit message or a separate append-only branch.
- Put every journal writer in one concurrency group.

**Confidence:** High (code). Exploitation in practice: UNVERIFIED (no evidence of an actual lost update).

### [A-11] Chain snapshots carry fetch time, not quote time; IV is back-solved from a stale LTP
Severity: **P3** · Status: **PARTIAL**

- Kotak chains get `attrs["ts"] = pd.Timestamp.now(tz=IST)` after the fetch completes (`intraday/kotak.py:288-289`).
- The response's own quote timestamps, if any, are not read. A stale book is therefore stamped as fresh.
- For PIT purposes this is conservative: a snapshot is never used before it was fetched.
- But quote freshness, the age of the last trade, can't be measured.
- `fill_iv` (`intraday/chains.py:353`) back-solves IV from the LTP when there is no two-sided quote. A last trade
  hours old becomes a valid-looking IV, and nothing flags it.
- **Fix:** keep each quote's exchange timestamp or last-trade time; flag IVs solved from the LTP.
- **Confidence:** Medium-high. Kotak's payload fields were not inspected live (no key in this environment).

### [A-12] Yahoo history is not stable within a day, so session model fits don't reproduce
Severity: **P3** · Status: **VERIFIED** (observation); cause **UNVERIFIED**

- `_train_models` fits on `history_bars(...)` filtered to `< day` (`engine.py:1016-1027`).
- Morning (09:15) and afternoon (12:21) fits on the same day used identical sample counts, yet reported different
  walk-forward metrics:

  | Day | Symbol | Morning | Afternoon |
  |---|---|---|---|
  | 2026-10-07 | NIFTY | AUC 0.490 / −2.18% (3,586 samples) | AUC 0.491 / −2.47% (3,586 samples) |
  | 2026-10-08 | NIFTY | log-loss skill −0.82% | −0.89% |

  The pattern repeats on the other days in the `events` table.
- So Yahoo returned different prior-day 5-minute values hours apart.
- The fitted data isn't fingerprinted or persisted, so a past session's model can't be rebuilt.
- **Impact:** low today (the model is advisory and fails its gate); a reproducibility gap in general.
- **Confidence:** High for the observation; the exact cause (Yahoo revisions vs. window edges) is unverified.

### [A-13] Afternoon journal events are back-dated to 09:15
Severity: **P3** · Status: **VERIFIED**

- `start_session` and `_train_models` stamp their events `session_bounds(day)[0]` (09:15).
- The afternoon job, which starts ≈ 12:21, therefore writes "session start", "ATM IV history" and "direction model"
  events dated 09:15. They appear after 12:22 rows in insertion order.
- A reconstruction by `ts` misplaces when the afternoon's model was fit and with which data.
- **Fix:** store both the logical session time and the wall-clock write time.
- **Confidence:** High.

### [A-14] Warehouse revisions overwrite rows with no history
Severity: **P3** · Status: **VERIFIED**

- `Warehouse.upsert` (`data/warehouse.py:96-116`): `drop_duplicates(keys, keep="last")`.
- The manifest is keyed `(table, date)`, also keep-last.
- `push` uploads with `--clobber`.
- Raw files aren't stored (by design; the manifest's SHA-256 identifies the bytes).
- A refetch or revision replaces rows and their provenance row silently.
- The module docstring says "writes each period once", but a month file is rewritten on every daily update.
- **Mitigation:** results record a digest of the data they read (`research/provenance.py`), so a changed input is
  detectable after the fact.
- **Confidence:** High.

### [A-15] Replay memory persists across replays: an earlier day can use later lessons
Severity: **P3** · Status: **VERIFIED** (code path)

- `cmd_replay` (`intraday/cli.py:388-389`) loads and updates the replay account's `memory.json` across runs unless
  `--fresh`.
- Replaying date X after replays of later dates uses factor, news and setup weights learned from after X. That is
  persistence leakage.
- Replays are not qualifying evidence, so the scope is limited.
- The live bootstrap (`learning.bootstrap`) replays chronologically into a fresh read, which is fine.
- **Confidence:** High (code). Not exercised in this phase.

### [A-16] Futures volume gaps become 0, and pre-Kotak sessions have no volume at all
Severity: **P3** · Status: **VERIFIED**

- `_with_futures`: `fb["volume"].reindex(out.index).fillna(0.0)` (`kotak.py:405`). A missing futures minute becomes a
  real-looking zero.
- The recorded 2026-09-29 and 09-30 sessions have volume 0 on every bar (Yahoo index bars, before Kotak), while later
  sessions carry futures volume.
- Volume-weighted features (VWAP, profile, relative volume) change their meaning across sessions in the same history
  window.
- `_day_features` falls back to equal weights only when the *whole* session's volume is 0
  (`intraday/quant.py:129`).
- **Confidence:** High.

### [A-17] Kite ticks without an exchange timestamp get the wall clock
Severity: **P4** · Status: **VERIFIED** (code path; the Kite path is untested per README)

- `feeds.py:199`: `ts = t.get("exchange_timestamp") or t.get("last_trade_time") or pd.Timestamp.now(tz=IST)`.
- A tick with no exchange timestamp is bucketed by the local clock, with no flag.

### [A-18] Yahoo 5m `completed()` uses a 1-minute bar length
Severity: **P4** · Status: **VERIFIED** (code path)

- `IntradayFeed.completed` uses `BAR = 1 minute` (`feeds.py:27, 92-94`). `history_bars` (`feeds.py:120-127`) applies
  it to 5-minute bars, so a still-forming 5-minute bar passes after 1 minute.
- **Current exposure:**
  - `_train_models` filters `< day` (excluded);
  - the cycle runs after the close;
  - `research.py:313` (VIX) and the cycle could be affected only if run mid-session.

### [A-19] The test suite has a wall-clock time bomb
Severity: **P4** · Status: **VERIFIED**

- `tests/test_kotak.py::test_chain_from_the_live_book[live|docs]` asserts that every IV is > 0. The fixture's
  expiry is fixed at 2026-10-06 (`tests/test_kotak.py:24`).
- The production code stamps the snapshot with `pd.Timestamp.now()` (`intraday/kotak.py:288`), and
  `time_to_expiry` clamps at 0 (`intraday/chains.py:44-48`).
- From 2026-10-06 15:30 IST onwards, T = 0 → IV `NaN` → 2 failures, on `main` as on any branch.
- **Impact:**
  - CI `tests` is red for reasons unrelated to any change, which hides real regressions;
  - it is also a small instance of A-11: the chain's time comes from the machine clock, not the data.
- **Fix:** freeze the clock in the test, or pass `ts` explicitly.

### [B-01] The analyst's weighted evidence has no causal path to an executed trade
Severity: **P2** · Status: **MISLEADING** (README § Intraday options desk, steps 2–4: "thinks … picks a setup … sizes and executes")

**Actual behavior**
- `require_approved_model: true` with an empty plan registry → `plan_gate` (`autolearn/live.py:176-189`) keeps only
  `direction == 0` plans.
- The one such setup is `range_sell` (iron fly). It is priced with `p_up = 0.5` (`engine.py:1101`).
- The 25+ weighted evidence factors (VWAP, EMA, Supertrend, CPR, OR, PCR, OI walls, CVD, futures OI/basis, VIX, news
  tone, research drift, global drivers) can affect an executable plan only through the iron fly's `|score| ≤ 0.30`
  eligibility test.
- Decision-relevant inputs today:
  - day type (ADX, IB extension, OR break, close location, **volume-profile value area**);
  - IV/RV (`vol_view`);
  - the vetoes (RSI extremes, ATM spread, events, breaking news, first 5 min, time window);
  - EV, sizing, global stress, the live book.
- `ARCHITECTURE.md` and `config` do say the analyst is advisory for directional trades. The README's intraday section
  still narrates the pre-gate pipeline.

**Evidence**
B1 table in `QUANTDESK_TRADING_STATE_MACHINE.md`; replay funnel.

**Impact**
- Most of what the app shows as "the desk's read" cannot currently produce a trade.
- Weighting and learning those factors (Phase D) changes no executed decision.

**Confidence:** High.

### [B-02] Zero trades is structural
Severity: **P2** · Status: **VERIFIED**

**Evidence**
- **Live journal, 10-05 … 10-09 AM:**
  - 21 armed directional setups reached their level → all rejected "no approved plan model";
  - 51 iron-fly plans → all "EV below the floor";
  - 0 trades.
- **Replay (2,984 index-minutes, real chains):**

  | Outcome | Index-minutes | Share |
  |---|---|---|
  | no setup | 2,093 | 70% |
  | vetoes / window | 602 | 20% |
  | plan-model gate | 215 | 7% |
  | EV floor | 74 | 2.5% |
  | executed | 0 | 0% |

  On the armed path, 40 levels were reached and 40 gated.
- **The plan registry needs 28 complete real point-in-time sessions; it had 5** (`plan/latest.json`).
- **The iron fly's EV after costs was:**
  - +₹18…+₹93/lot on 10-05 (below `max(₹40, 0.05 R)`);
  - −₹190…−₹531/lot on 10-07 and 10-08;
  - BANKNIFTY often 0 lots ("none fits").

**Counterfactual**
The 133 unique gated directional opportunities averaged **−0.07 R on the underlying** before option costs (median
−0.11 R). There is no evidence that the gate blocked profitable trades in this small, autocorrelated sample.

**Impact**
- No directional paper trade is possible for at least ~23 more complete recorded sessions.
- The paper account therefore generates no trade evidence. The setup/trade learning tables stay empty.

**Confidence:** High.

### [B-03] Gated opportunities on the confirm path are never journaled
Severity: **P2** · Status: **VERIFIED**

**Actual behavior**
- `_maybe_enter` (`engine.py:729-764`) returns "standing aside: no approved plan model…" when `plan_gate` removes a
  5-minute-confirmed directional setup. It writes **no decision row**.
- Only a sampled thought records it (every 5 min / on a bias flip): 35 in 5 live sessions, vs 215 index-minutes in the
  replay of 4 sessions.
- Where decision rows are written, every gate (model, EV, sizing, stress, liquidity, track record) uses
  `action = "rejected"`, and the gate is only in free text.
- No ID links SETUP → ARMED → TRIGGER → DECISION → TRADE. Re-fires of one breakout are separate rows.

**Impact**
- "Why didn't we trade at 10:42?" can't be answered from the journal for the confirm path.
- Rejected-opportunity counts can't be de-duplicated.

**Fix**
Write a decision row for every gate outcome, with a structured `gate` field and an `opportunity_id`.

**Confidence:** High.

### [B-04] The armed lifecycle is not persisted
Severity: **P3** · Status: **VERIFIED**

- `engine.armed` is in memory only. It is rebuilt each minute with a 2-minute TTL.
- Expiry, not-reached and cancellation leave no record.
- Arms appear only in the heartbeat to the site (`engine.py:1317`) and in sampled thoughts.

### [B-05] Dead or display-only features
Severity: **P3** · Status: **VERIFIED**

- **`max_pain` is unreachable.**
  - The analyst gets `is_expiry_day = self.expiry[u] == self.day` (`engine.py:296`).
  - `pick_expiry` drops expiries < 1 day away (`engine.py:180`, `intraday.expiry_min_days: 1`).
  - So it is never True: 0 of 675 live reads carry `max_pain`.
- **`iv_move`** has a weight (`analyst.py:21`) and is never computed.
- **`open_vs_pva` / the prior-day value area** is computed (`features.py:104`) and never read.
- **Narrative or site only:** gamma/GEX and the gamma flip (labelled "untested here"), IV percentile, GIFT Nifty, FII
  flows, the buyer's edge.
- **Zero weight (probation, displayed and graded):** breadth, breadth_div, oi_shift, skew_trend, the heavyweight
  pulse, and every global driver except crude.
- **Reproduction:** `test_phase_b_probes.py::test_expiry_day_is_never_today_so_max_pain_never_fires`.

### [B-06] Setups are armed and shown as waiting though authorization can never pass
Severity: **P3** · Status: **MISLEADING** (display)

- `_arm` / `Playbook.arm` don't consult `_model_gates`. Authorization happens only after the trigger
  (`_fire_armed`).
- Under the current config every armed setup is directional, so every one is rejected on reaching its level.
- Replay: 594 armed minute-reads → 40 fires → 0 authorizable.
- The site shows them as "Waiting at the level", and the thought text says "armed: …".
- **Reproduction:** `::test_arm_does_not_consult_the_plan_gate`.

### [B-07] No-trade learning never grades plan-gate rejections of armed setups
Severity: **P2** · Status: **BROKEN**

- `grade_armed` (`learning.py:320-351`) skips any decision without `context["target"]`.
- The plan-gate rejection path writes `{"armed", "plan"}` only (`engine.py:481`). Only the EV-rejection path writes
  `target` (`engine.py:500`).
- All 21 live armed rejections are ungraded. `memory.json` has no `armed_rejected` table, and every session logs
  "0 armed".
- The README's claim "Pre-break entries the EV gate refused are replayed …" is literally limited to the EV gate, which
  is never reached by armed setups.
- **Reproduction:** `::test_armed_rejections_by_plan_gate_are_never_graded` (21 real rows → 0 graded).
- **Confidence:** High.

### [B-08] Breaking-news veto false positives
Severity: **P3** · Status: **VERIFIED**

- `NewsDesk.state` sets `breaking` for any high-impact, non-recap, non-preview story published ≤ 15 min ago
  (`news.py:446-447`). Novelty is not considered.
- The RBI decision (2026-10-07 10:00) re-triggered 15-minute stand-asides on both indices via retellings:
  - all afternoon on 10-07;
  - through 10-08: a market recap ("Sensex, Nifty open in red following RBI repo rate hike"), an Adani stock pick,
    a bank lending-rate story;
  - on 10-09 ("RBI hikes repo rate to 5.50%; shifts policy stance").
- Also "Why Warren Buffett considers interest rates key to stock valuations" (10-07 15:03).
- A question-form preview, "Will RBI hike repo rate? MPC begins 3-day meet…", is not matched by `PREVIEW`
  (`news.py:131`).
- 18 distinct stories caused 67 live veto thoughts; the replay counts 124 index-minutes.
- **Reproduction:** `::test_retold_rbi_decision_two_days_later_still_vetoes`,
  `::test_question_style_preview_is_not_recognised_as_a_preview`.

### [B-09] Trigger engine gaps
Severity: **P3** · Status: **PARTIAL**

1. **LTP sampling misses.** With a working LTP, bar-range firing is switched off (`engine.py:256`). A level crossed
   and left between two 5 s polls never fires, and the minute bar's range doesn't catch it either.
2. **Stale authorization view.** `_fire_armed` authorizes against the **previous minute's** view and vetoes
   (`engine.py:458`). News is refreshed only in `step()`. A tick-fired entry can therefore ignore a breaking story or
   event that arrived inside the minute. The chain is repriced from a snapshot up to 12 minutes old (`_chain_at`).
3. **Re-fires.** Each recross of a level fires again after re-arming: ORB at 22,473 fired 09:43, 09:52 and 10:08 on
   2026-10-08. That produces duplicate decisions and duplicate "rejected opportunities".

**Reproduction:** `::test_bar_range_firing_disabled_when_live_price_works` (1); code (2); journal (3).

### [B-10] Opening range, initial balance and session minutes come from the first bar present
Severity: **P3** · Status: **VERIFIED**

- `session_state` uses `day.iloc[:15]` / `iloc[:60]` for the OR and IB, and `minutes = now − day.index[0]`
  (`features.py:97, 124-126`). These are rows from the first bar present, not clock windows from 09:15.
- **A late start** (2026-09-30: recorded bars begin 15:20) or a replay of a gapped recording computes the "opening
  range" from whatever bars come first, and thinks it is the open.
- **Live** is unaffected when the in-memory history already holds the morning (the afternoon restore from Yahoo).

### [B-11] What-if `as_run` does not reproduce what ran
Severity: **P3** · Status: **MISLEADING**

`deploy/whatif.py` runs the engine with:
- the model chain (its docstring says the real snapshots "aren't kept"; they are now, on `chains-2026`);
- `memory=None`: no learned weights or news trust;
- no learner: the plan gate takes its "learning loop off" branch;
- no brain and no breadth.

So `as_run` differs from the live run in pricing, weights and gating messages. This resolves Q-04.

### [C-01] Even an approved plan model can't let a live directional plan through
Severity: **P1** · Status: **BROKEN (latent)**

**Claim**
`autolearn/live.py` docstring: "Directional entries (`plan_gate`) … needs the plan registry's champion … Without such a
champion no directional trade is taken" (implying one *is* taken with it).

**Actual behavior**
- `plan_gate` rejects every plan with `len(p.legs) != 1 or p.legs[0].ratio != 1` ("the plan model covers single long
  options only", `live.py:198-200`).
- At ₹5L the desk builds a **debit spread** for every directional setup:
  - `Playbook._directional` adds a short leg when `allow_short and (always_spread or rich)` (`playbook.py:232-236`);
  - `always_spread: true` for orb, vwap_trend, trend_break and va_reversion (`config/quantdesk.yaml` → `intraday.setups`);
  - `allow_short` is on because equity ₹5,00,000 ≥ `short_legs_from_equity` ₹3,00,000.
- The single-option alternatives exist only inside `_select_by_ev`, which runs *after* the gate.

**Impact**
The ≈ 33-session path to the first directional trade (28 real sessions + a lock + 10 forward) ends in the same
rejection, unless config or code changes. Combined with C-05, the engine has no reachable trade path.

**Reproduction**
`test_phase_c_probes.py::test_approved_plan_model_still_rejects_every_live_directional_plan`: with a stub champion
that approves everything, the 2-leg plan is rejected and the 1-leg plan is approved.

**Fix**
Align the plan the model was trained on with the plan the engine builds: either gate the single-leg variant, or train
and approve spreads.

**Confidence:** High.

### [C-02] The session DirectionModel's validation gate passes on noise
Severity: **P2** · Status: **VERIFIED**

**Claim**
README: "It has to pass a walk-forward test: out-of-sample AUC ≥ 0.53 *and* log-loss better than the base rate.
Otherwise it's switched off".

**Actual behavior**
- The gate is one 70/30 day split (`quant.py:226-238`), re-run every session (and at hand-over), with 6×-overlapping
  30-minute labels.
- **On 200 pure random-walk histories of the live window size it validated 20 (10.0%)**; AUC ≥ 0.53 in 15%,
  sd(AUC) 0.031 (`audit` null simulation).
- Refit 2× per session per index, a spurious "validated" model is close to certain within weeks.
- When valid, it sets P(up) for EV (±0.15) and adds a `model` evidence factor at weight 0.8.
- Live fits so far: AUC 0.47–0.51, consistent with the null.

**Impact**
Latent: it acts only on directional plans, which are gated (B-01, C-01).

**Reproduction**
`::test_session_direction_model_validates_on_random_walks`.

**Confidence:** High.

### [C-03] No automatic demotion or rollback of a degraded champion
Severity: **P2** · Status: **VERIFIED (missing)**

- `Cycle._promote` judges challengers only (`cycle.py:499`). The champion's shadow record is computed in `_paper` but
  never acted on.
- A drift alarm makes the champion abstain (`live.py:132-133`) while it stays champion.
- `Registry.rollback` has a single caller: the operator CLI (`autolearn/cli.py:170`).
- **Impact:** a promoted champion that degrades keeps its role until a human acts. The "degradation → … → rollback"
  chain (D8) has no automatic link.
- **Reproduction:** `::test_no_automatic_champion_demotion`.

### [C-04] Two cost models disagree on futures STT
Severity: **P3** · Status: **CONTRADICTED** (internal)

- `autolearn.costs.stt_sell_bps: 2.0` (0.02%) vs `costs.segments.futures.stt_sell: 0.0005` (0.05%, the post-Budget
  2026-27 rate the README cites).
- The autolearn simulation's round trip (≈ 5.8 bps) is ≈ 3 bps cheaper than the desk's own schedule. That biases
  registration toward passing.
- `docs/ARCHITECTURE.md` repeats the 0.02% figure.
- **Reproduction:** `::test_autolearn_and_desk_cost_models_disagree_on_futures_stt`.

### [C-05] The iron fly cannot pay its costs on an intraday hold
Severity: **P2** · Status: **VERIFIED** (answers Q-06)

- The 51 recorded EV rejections show an internally consistent Monte Carlo:
  - 2-hour holds;
  - fees ₹228–332 and exit spread ₹23–100 per lot;
  - theta over ≤ 120 trading minutes too small to cover them.
- Results:
  - BANKNIFTY (13–14 DTE): **P(profit) 0%**, EV −₹400…−₹530;
  - NIFTY 6-DTE: −₹190…−₹255;
  - NIFTY 1-DTE: +₹18…+₹93, against a 0.05 R floor ≈ ₹221.
- BANKNIFTY also sizes to 0 lots: a max loss of ₹13.8–15.5k per lot exceeds the 2.5% × conviction budget.
- **Impact:** the only non-directional setup in the playbook is economically closed by the desk's own model.
  Together with B-02 and C-01, the intraday engine has no reachable path to a trade.

### [C-06] EV model limits
Severity: **P3** · Status: **PARTIAL**

- **Fixed IV per leg:** no vega or IV dynamics. The iron fly's own "vol crush" thesis is not modelled.
- **Normal increments.**
- **Exit fees on the entry mid.**
- **An explicit unvalidated prior** P(up) = 0.5 + 0.10 × score for directional plans.
- **No feedback from realised outcomes.** The app's "calibration" table (`web/intraday_api.py:211-231`) is
  display-only, and there are 0 trades to compare. EV accuracy is UNVERIFIED.

### [C-07] Lockbox peeks are unbounded
Severity: **P3** · Status: **PARTIAL**

- `_lockbox_check` runs (and logs a peek) for every candidate that passes walk-forward, in every cycle
  (`cycle.py:395-414`).
- Peeks are counted, not capped. Repeated looks erode "final".
- The plan track's `PlanLock` opens once per generation, which is better.
- See also A-07.

### [C-08] `FEATURE_VERSION` hashes source text
Severity: **P3** · Status: **VERIFIED**

- `FEATURE_VERSION` = sha256 of `inspect.getsource` of `_day_features`, `features_5m` and `to_5m` (`features.py:33-42`),
  including comments and docstrings.
- Any edit to those functions makes every registered artifact fail `from_artifact` → `LiveLearner.fault` → `_blocked`
  halts **all** entries ("halted: …").
- Fail-closed by design, but an availability hazard on a cosmetic change.

### [D-01] Factor learning is indistinguishable from noise
Severity: **P1** · Status: **MISLEADING**

**Claims**
- README: "the record changes how much it trusts each input".
- `learning.py`: "One good or bad day can't swing it; a consistent record does".
- Brain: probation drivers "have to earn a vote live".

**Actual behavior**
- **Grading the 675 live reads** (2026-10-05 … 10-09) with the production grader: best shrunk hit rate 0.581
  (`global_crude`).
- **300 sign-flip placebos** (each factor × index × session multiplied by a random ±1; persistence and window overlap
  kept, any link to returns destroyed):
  - placebo median best 0.592, 95th percentile 0.630;
  - **real vs placebo p = 0.70**;
  - noise "graduates" ≥ 1 factor (n ≥ 30, reliability ≥ 1.15) in **78%** of draws; the live record graduates 1.
- **Factor signs persist:** P(next read same sign) = 0.89. Weighted n overstates independent evidence many times over.
- **No confidence interval or multiple-testing control** enters any rule (30 factors screened daily).
- **Production memory** (which also contains bootstrap replays): multipliers 0.78–1.07. `global_crude` graduated on a
  shrunk hit of 0.592 and votes at 0.30. That is consistent with chance.

**Reproduction**
`audit/probes/phase_d_factor_placebo.py <journal>/intraday 300`.

**Impact**
- Every learned weight and every graduation so far is statistically unsupported.
- Because of D-02 the trading impact is small. As a learning claim it does not hold.

**Confidence:** High for the evidence in the snapshot (5 live sessions). A longer record could change the verdict.

### [D-02] Learning has a negligible effect on decisions
Severity: **P2** · Status: **VERIFIED**

**Evidence**
The Phase B replay was re-run with the learning memory off (`NO_MEMORY=1`) vs on (the snapshot copy), 4 sessions × 2
indices:
- **2 of 2,984** minute-decisions changed outcome class;
- mean \|Δscore\| 0.005 (max 0.016);
- 0 trades either way.

**The two changes** (`audit/data/phase_d_learning_ab.json`):

| When | Score with memory → without | Outcome with memory → without |
|---|---|---|
| 10-07 12:20 NIFTY | 0.2993 → 0.3069 | iron fly eligible, then EV-rejected → no setup |
| 10-08 11:34 BANKNIFTY | −0.3995 → −0.4043 | a directional setup raised, then gated → no setup |

This is exactly the B-01 path.

**Impact**
The learning loop runs every session, and its output barely touches what the desk does.

### [D-03] The learning record is aggregate-only, mixes provenance and cannot be replayed
Severity: **P2** · Status: **VERIFIED**

- `memory.json` stores only `{n, hits, sum, sum2}` per key. There are no per-observation records, evidence IDs or
  hash chain.
- **One record, several sources, no tags:**
  - the bootstrap replays: 6 sessions, 6,025 factor grades, the model chain, no news/brain/breadth, Yahoo bars with
    no index volume, so `vwap` was TWAP;
  - the pre-reset ₹20k account's sessions (09-29 … 10-01);
  - the live sessions.
- **Three days** (09-24, 09-25, 09-28) have no recorded bars.
- **The bootstrap's reads** lived in an in-memory scratch journal and are gone.
- **`learn --rebuild`** regrades the current journal only. The record can't be reproduced from persisted evidence.
- **Reproduction:** `test_phase_d_probes.py::test_memory_mixes_bootstrap_and_live_sessions_without_tags`.

### [D-04] No recency, no regime split, no demotion state
Severity: **P2** · Status: **VERIFIED**

- **No recency.** Sums accumulate forever with no decay. A factor right 70% for 300 reads then 30% for 100 stays
  up-weighted.
- **No regime split.** Factor statistics are global. Only setups have a day-type split, and that is empty (0 trades).
- **Floor, not demotion.** The multiplier floor is 0.5×: a factor right 20% of 1,000 times still votes in its original
  direction at half weight.
- **Lifecycle.** States are probation → graduated only, recomputed every close. No transition is persisted.
- **Reproduction:** `::test_factor_reliability_has_no_recency`, `::test_anti_predictive_factor_is_floored_not_removed`.

### [D-05] No-trade learning is absent in production
Severity: **P2** · Status: **BROKEN**

- Only armed setups rejected by the EV gate are designed to be counterfactually graded (`grade_armed`, report-only).
  That path never fires: armed setups are rejected by the plan-model gate, without `target` (B-07).
- None of these is graded:
  - confirm-path gate rejections;
  - iron-fly EV rejections;
  - sizing, stress and liquidity rejections;
  - any veto (first 5 min, window, event, breaking news, RSI, spread, stale data);
  - "no setup".
- No rejection outcome changes future behaviour.

### [D-06] No baseline or control for learning
Severity: **P3** · Status: **VERIFIED**

- No ON/OFF comparison or control path exists.
- `ops/progress.py` ("Is the desk getting smarter?") tracks research and process KPIs. Its learning KPIs
  (`forecast_skill`, `signal_hit_rate`) come from the empty autolearn ledger and are `null` every day.
- No claim that learning improved performance can be supported.

### [D-07] Self-correction blind spot
Severity: **P2** · Status: **VERIFIED**

- `selfreview.check_session` raises an issue only for `level == "ERROR"` events (`ops/selfreview.py:78`).
- The catch-up grading failure is logged as `WARN` (`engine.py:621`). It recurred 8 times over 5 sessions (A-02) and
  was never filed.
- **Reproduction:** `::test_self_review_ignores_warn_level_learning_failures`.

### [D-08] Truncated graded-id lists let headlines be graded again
Severity: **P4** · Status: **VERIFIED** (latent)

- `Memory.save` keeps only the last 5,000 news ids (2,000 trades or armed).
- `grade_session` re-reads 7 days of news.
- Once more than 5,000 headlines have been graded inside that window, the oldest ids are graded again.
- Today about 1,567 have been graded in total, so it hasn't happened yet.
- **Reproduction:** `::test_truncated_graded_news_ids_are_regraded`.

---

### [E-01] The sleeves' forward ledger settles on a frozen index
Severity: **P1** · Status: **MISLEADING**

**Claim**
- `expiry_seller_v1/v3`: settlement = "the mean of the 15:00–15:29 one-minute index closes the desk recorded on expiry
  day (NSE's index close is built from the last 30 minutes)".
- The forward ledger is the desk's only forward evidence for L1/L2.

**Actual behavior** [prod]
- **The feed freezes.** On every recorded session the Kotak index bars freeze from 15:15: O = H = L = C and unchanged
  for 12–14 minutes, while volume keeps changing.
  - NIFTY then jumps to the official close in the 15:29 bar.
  - The chain tape's spot freezes the same way (SENSEX never jumps).
  - Option bid/ask keep updating every minute.
- **About half of the settlement window is stale.** The mean vs the 15:29 bar was −27 … +16 bps across sessions.
- **2026-10-06 NIFTY expiry:**
  - registered settle 22,714.88 vs NSE official 22,776.10 (−26.9 bps);
  - A-NIFTY goes from **+₹560 to −₹3,419**;
  - B-NIFTY goes from **+₹2,142 to −₹1,838**.
- **2026-10-08 SENSEX expiry:**
  - settle 71,438.50 vs the BSE bhavcopy underlying 71,593.24 (−21.6 bps);
  - D/E losses are overstated by ≈ ₹3,095/lot [infer].
- **The rules use the stale P&L.** `sleeves.assess` (`sleeves.py:206`) uses `pnl_rs`, the registered settlement, for
  the cost check, consistency z, tail rule and eligibility. The official P&L is a diagnostic `official` event only.
- **Mixed conventions.** The history the consistency z compares against settles on the official close.
- **Secondary.** The 15:20 entry picks strikes by delta from a 5-minute-stale spot.

**Evidence**
- `audit/probes/phase_e_frozen_minutes.py` → `audit/data/phase_e_frozen_minutes.txt`.
- Journal `sleeves/expiry_seller_v1.jsonl` (`settle` and `official` events).
- `chains-2026` tapes for 10-05/07/08.

**Reproduction**
`test_phase_e_probes.py::test_official_close_flips_the_sign_of_both_nifty_sleeve_trades`,
`::test_recorded_index_freezes_from_1515_every_full_session`, `::test_sleeve_rules_use_registered_settlement_pnl`.

**Impact**
- The forward record of the desk's one validated edge is computed on stale data.
- Its retirement and eligibility rules run on that record.
- Paper only, so not P0.

**Recommended fix**
- A new spec (`expiry_seller_v4`) settling on the exchange's official close.
- Flag flat-bar runs at record time.
- Keep the v1/v3 ledgers frozen and report both conventions.

**Confidence:** High for the freeze and its P&L effect. Root cause located in Phase F: Kotak's index series (F-02, Q-08).

### [E-02] Paper-account eligibility means "not rejected"
Severity: **P2** · Status: **VERIFIED**

**Claim**
`expiry_seller_v1` `eligibility`: sleeve A becomes eligible for the ₹5L paper account with ≥ 10 settled trades, the cost
check passed and consistency not rejected.

**Actual behavior**
- **Simulation** [synth]: with the production `assess()` and A_NIFTY's history (mean ₹118, sd ₹2,232), a sleeve with a
  **true edge of zero** is eligible after 10 trades in ≈ 93% of 2,000 simulations.
- **Analytical** [infer]: 93% for A_NIFTY and 90% for A_BANKNIFTY.
- **A_NIFTY's own history** is t 1.05 over 391 expiries: not significant.

**Mitigations**
- The spec's `no_profit_claim` says the forward test cannot show profitability.
- Eligibility is "reported, never applied automatically".

**Reproduction**
`test_phase_e_probes.py::test_paper_gate_admits_a_zero_edge_sleeve`.

**Recommended fix**
- Require positive forward evidence: a one-sided lower bound > 0, or a sequential test on pooled forward trades.
- Or relabel the status "not rejected". A new spec either way.

**Confidence:** High.

### [E-03] The D1 drift steers every live EV without a registered study, on a hurdle that assumes fair option prices
Severity: **P3** · Status: **PARTIAL**

**Evidence**
- **The effect is real** [replay]: on NSE's official OHLC, NIFTY open → close −6.30 bps/day, t −3.85, 2019–2026 (V-26).
- **It enters every live EV** [code]:
  - `quant.load_research` turns the edges.json D1 row (`PAPER CANDIDATE`) into `drift.per_min`;
  - `engine.py:1100` passes it to `ev.evaluate` as the base drift of every plan;
  - no `docs/prereg` spec covers it.
- **The hurdle assumes fair option prices** [code]: one 0.35Δ option round trip, justified by "theta is paid for by
  gamma".
  - The desk's V1 (VIX above realised), L1 and L4 all say short-dated buyers pay a premium.
  - Back-of-envelope [infer]: the VRP drag on a 0.35Δ weekly near expiry is several index points per intraday hold,
    the same order as the ≈ 5 pts of D1 that the option captures.

**Impact**
Nil today (no trade path: B-02, C-01). A latent mis-pricing once anything can trade.

**Reproduction**
`phase_e_d1_official.py`; `test_phase_e_probes.py::test_d1_drift_becomes_the_live_ev_base_drift`.

**Recommended fix**
- Register D1 before it steers EV.
- Add an IV-premium term to the hurdle, or switch the prior off.

**Confidence:** High for the facts; medium for the cost-of-the-same-order inference.

### [E-04] No program-wide multiplicity accounting
Severity: **P2** · Status: **PARTIAL**

**Evidence** [prod + code]
- **The ledger is thin.** `research/experiment_log.jsonl` has 7 lines: an init line plus 2 runs of the
  edges/warehouse research on 2026-10-03 (87 tests each). "Earlier research reports predate the append-only experiment
  ledger and are not reconstructed."
- **Registered studies never write to it**: `laws`, `wings`, `law_audit`, `autolearn/prereg`, `volstudy`, the sleeves'
  decisions.
- **BH is per run family.** It is applied within each run, not across the program, and the weekly re-run re-inspects
  the same rolling-validation slice.
- **The duplicate guard is a registry, not a multiplicity control.** `memory.method_fingerprint` refuses exact
  (reworded) repeats only. A one-number variant (v2 with t > 1.5) is "new": no identical match, nearest v2 at
  similarity > 0.9.
- **Discovery cells.** The desk's own L1 audit counts ≥ 48 discovery cells before L1.

**Impact**
- L1's held-out test is a single pre-registered rule, so its p is not inflated.
- "Found"/"candidate" items (D1, the edges list, L4) carry an unknown family size.

**Reproduction**
`test_phase_e_probes.py::test_fingerprint_guard_admits_a_one_number_variant`, `::test_experiment_ledger_does_not_cover_the_program`.

**Recommended fix**
- Every registered run appends to the ledger.
- Report a running family count.
- Reconstruct the pre-ledger reports.

**Confidence:** High.

### [E-05] v2 re-tests the same held-out instruments, and its spec has no frozen sample
Severity: **P3** · Status: **PARTIAL**

**Evidence** [prod]
- **Timing.** The v1 result was committed at 02:40Z (pooled t 4.46, replicated). The v2 spec was committed at
  08:07Z: same five held-out instruments, same rule, only the spot source changed. So v2 is a corrected re-test after
  v1's held-out result had been seen, not a second holdout.
- **Principles.** `docs/principles.json` rests L1/L2 "replicated" on v2. Legitimate as a correction, but it is one
  exposure of the held-out data.
- **No frozen sample.** `expiry_eve_law_v2.json` has no end date. Re-running today gives 289 weeks, +9.27 bps, t 4.82
  (the registered result: 288 weeks, +9.48, t 4.98). The registered sample exists only as the stored file; the cutoff
  2026-10-01 is not recorded anywhere but the result's span.

**Reproduction**
`phase_e_repro_v2.py`, `phase_e_v2_post.py`; `test_phase_e_probes.py::test_v2_spec_has_no_frozen_sample`.

**Recommended fix**
- Specs fix their sample end.
- The ladder records how many exposures each held-out set has had.

**Confidence:** High.

### [E-06] Result provenance gaps
Severity: **P3** · Status: **PARTIAL**

**Evidence** [prod + code]
- **Stamping.** Only `expiry_eve_law_v2_audit` carries a provenance stamp, and its code state is `dirty: true` (commit
  `c511e5ace1ab`). v1, v2, wings_v1, N1 and vol_forecast_v1 have none.
- **The digest design** (`provenance.data_digest`: a hash over whole yearly files) changes with every daily append. It
  cannot separate appended rows from revised ones; today's digests all differ from the recorded ones.
  - The v2 rows were verified unrevised by exact reproduction instead (V-21).
- **Edge research inputs are not archived.** Yahoo `period=max` is re-downloaded each run; only a sha256 is logged,
  so drift is detectable but `edges.json` cannot be re-derived.
- **Two spec-hash schemes coexist** (raw bytes vs canonical JSON). `memory.registry` handles both.

**Reproduction**
`test_phase_e_probes.py::test_registered_results_mostly_lack_provenance`.

**Recommended fix**
- Stamp every result and refuse a dirty tree.
- Use per-day digests.
- Archive the research inputs.

**Confidence:** High.

### [E-07] L1's economics are untested where most of its held-out weight sits
Severity: **P3** · Status: **UNVERIFIED**

**Evidence** [prod]
- **Measured spreads are conservative.** Real expiry-eve half-spreads (~0.12–0.30Δ, 15:00–15:30) are 0.050 on NIFTY
  and 0.075 on SENSEX, vs the model's 0.100 and 0.165: about 0.5×.
- **The rest is unmeasured.** No quotes were ever recorded for FINNIFTY (51% of the pooled weight), MIDCPNIFTY,
  BANKEX or NIFTYNXT50.
- **Entry is not executable as tested.** The entry is the bhavcopy close (a last trade on only 26.8% of rows). The
  pre-registered `expiry_eve_entry_v1` measures this and is collecting (0 decided).
- **Decay.** The held-out mean in 2024 is +1.4 bps on 202 trades (L2 −1.6).

**Reproduction**
`phase_e_eve_spreads.py` → `audit/data/phase_e_eve_spreads.txt`; `phase_e_l1_robust.py`.

**Recommended fix**
Tape the eves of every held-out instrument; let `expiry_eve_entry_v1` decide.

**Confidence:** Medium (2 eves measured).

### [E-08] L3 parity: the study's "desk" baseline is not the production forecaster, and the winner is not deployed
Severity: **P3** · Status: **PARTIAL**

**Evidence** [code]
- **The baseline differs from production.** `volstudy.py` defines A_desk as "the desk's forecaster without IV".
  Production's `VolForecaster` blends 30% ATM IV (`iv_weight = 0.3`).
- **The winner is not deployed.** The study found the desk's forecaster mis-scaled by time of day (move ratio
  0.73–1.23) and beaten by HAR by 13–35% QLIKE. The live EV Monte Carlo still runs `VolForecaster`; no HAR or seasonal
  model exists in `intraday/quant.py`.

**Reproduction**
`test_phase_e_probes.py::test_vol_study_baseline_excludes_the_live_iv_blend`.

**Recommended fix**
Re-run the comparison against the live forecaster (with IV), then decide on deployment.

**Confidence:** High.

### [E-09] External minutes are verified shallowly
Severity: **P4** · Status: **PARTIAL**

**Evidence** [code]
- `data/external_aeron.verify` compares 80 seeded random sessions per symbol with Yahoo's daily H/L/C, within
  tolerances.
- It does not check minute-level values or timestamps. Minute-level errors that preserve the daily extremes pass.
- The studies on these data (N1, L3) are labelled "external_verified (underlying only)".

**Recommended fix**
Minute-level spot checks against NSE OHLC (warehouse 2019–2023).

**Confidence:** High for the code; unknown for the data's actual quality.

### [F-01] The model-chain fallback trades on fabricated data
Severity: **P2** · Status: **VERIFIED** (latent)

**Claim**
`engine._refresh_chain`: "NSE blocks many cloud IPs … the desk must not stop because of it. Price off the model chain
(India VIX + skew) and say so in the journal."

**Actual behavior**
- **The fallback.** When Kotak and NSE both fail, `ModelOptionChain` supplies the chain:
  - prices from VIX × beta plus a skew model;
  - modelled spreads;
  - **OI fabricated** as a Gaussian bump ~0.8σ from spot, ×1.8 on round strikes.
- **It bypasses the stale gate.** `_blocked` exempts `source == "model"` from the stale-chain check.
- **It is traded on.** Plans are built on it, EV prices them, and `IntradayBroker` fills them at the modelled bid/ask.
- **The fill is mislabelled.** The fill label is "option chain"; `meta.quote_source` does say "model".
- **Fabricated OI votes.** `chain_analytics` computes call and put walls (and max pain) from the fabricated OI. The
  analyst guards **only PCR** against `source == "model"`, so the OI walls (vote 0.4) vote on a synthetic signal.
  Max pain would too, but it is unreachable anyway (B-05).
- **The only signal is a WARN.** The journal gets a WARN on the 1st and every 10th failure.

**Evidence**
`engine.py:336-376, 724`; `chains.py:280-319, 409-461`; `analyst.py:168-190`.
Production: 0 fallback events in the journal since 10-05.

**Reproduction**
`test_phase_f_probes.py::test_model_chain_fallback_yields_oi_walls_and_max_pain_from_fabricated_oi`,
`::test_model_chain_is_exempt_from_the_stale_chain_gate_and_used_on_failure`.

**Impact**
- On a Kotak outage the paper desk can trade on invented quotes, and the analyst votes on invented OI.
- The protocol's rule: "a failure must never silently become valid-looking data".

**Recommended fix**
- No entries on a model chain (or an explicit opt-in).
- No OI-derived votes from it.
- Label fills "model".

**Confidence:** High (code and synthetic run). The production trigger rate is unknown (Q-12).

### [F-02] The 15:15 index freeze is vendor-side and reaches basis, learning and the sleeves' entries
Severity: **P2** · Status: **VERIFIED**

**Evidence** [prod]
- **The future keeps trading.** On 10-06 Kotak's NIFTY index candles sit at 22,717.70 from 15:15 to 15:28, while the
  near-month future, fetched by the same client through the same `candles()` → `normalise_bars` path, trades
  22,782 → 22,806 → 22,799. Same on 10-08.
- **So the freeze is in Kotak's index series** (answers Q-08), not the desk's aggregation.
- **Its consumers beyond E-01's sleeve settlement:**
  - "basis" (future − index) swings ~24 pts in 14 minutes from staleness alone;
  - **71 of 675 graded factor reads (10.5%)** have 30-minute windows that end in frozen minutes;
  - the sleeves' 15:20 eve entries compute deltas from a 5-minute-stale spot.
- **Not affected:** entries (cut-off 14:45) and the engine's 15:15 square-off.

**Reproduction**
`test_phase_f_probes.py::test_index_freezes_while_the_future_keeps_trading`,
`::test_a_tenth_of_graded_factor_reads_end_in_the_frozen_minutes`.

**Recommended fix**
- Flag flat index runs while the future moves.
- Exclude them from settlement, basis and grading.
- Raise it with Kotak.

**Confidence:** High.

### [F-03] Fixed r/q instead of the chain's forward biases the skew level
Severity: **P4** · Status: **PARTIAL**

**Evidence** [replay]
- **The forward is off.** On the recorded chains, the chain-implied forward differs from the desk's `S·e^{(r−q)T}`
  (r 6.5%, q 1.2%) by 3–28 bps.
- **The put−call ATM IV gap** is −3.2 (NIFTY) / +3.4 (SENSEX) vol pts at ≤ 2 DTE and ±1–2 elsewhere.
- **What it touches.** The ATM IV mean largely cancels. The 25-delta skew level does not (narrative, app). The
  probation `skew_trend` uses the 30-minute change, which cancels a constant bias.
- Asynchronous spot and quote snapshots may contribute.

**Reproduction**
`phase_f3_pricing.py` → `audit/data/phase_f3_pricing.txt`.

**Recommended fix**
Solve IV on the chain's implied forward (already computed by `gex.implied_forward`).

**Confidence:** Medium.

### [F-04] Paper fills ignore depth and fall back to stale chain prices
Severity: **P3** · Status: **PARTIAL** (latent: 0 trades)

**Evidence**
- **The fill rule** [code]: every leg fills in full at top-of-book + 1 tick. The engine never reads `bidq`/`askq`.
  - Probe: 650 units fill at the same price as 65.
- **Real depth** [replay]: the median best-level size within ±4 strikes is 3 lots (NIFTY) / 2 lots (BANKNIFTY);
  81% / 99% of best levels are below the 10-lot cap.
- **Fallback prices.** Without a live book:
  - entries fill at the plan's chain price (the chain may be up to 12 minutes old) with **no move-away check**;
  - exits fill at Black-Scholes marks ∓ half the last spread.

**Reproduction**
`phase_f4_depth.py`; `test_phase_f_probes.py::test_paper_fill_takes_any_size_at_top_of_book_plus_one_tick`.

**Recommended fix**
- Cap fills at the best-level size, or walk the book.
- Apply the move-away check to chain-price entries.

**Confidence:** High.

### [F-05] Exercise STT out of date; paper settlement charges none
Severity: **P4** · Status: **PARTIAL**

**Evidence**
- **The code's rate.** `warehouse_research.STT_EXERCISE = 0.00125` is used by the research and the sleeves, and the
  sleeve specs freeze 0.125%.
- **The current rate.** Secondary sources (brokers' and finance publications citing NSE/FATAX/73524 of 31 Mar 2026)
  report the exercise rate rose to 0.15% on 1 Apr 2026, with the sale rate going 0.10 → 0.15%. The desk already uses
  0.15% for sales. The primary circular was not opened.
- **Paper settlement.** `PaperBroker.settle_expiry` charges no exercise STT at all (daily desk, not scheduled).
- **Magnitude:** 0.025% of the intrinsic value of exercised long legs.

**Reproduction**
`test_phase_f_probes.py::test_exercise_stt_is_the_pre_april_2026_rate_and_paper_settlement_ignores_it`.

**Recommended fix**
- A date-effective rate.
- A new sleeve spec, since the old ones are frozen.

**Confidence:** Medium on the statutory rate; high on the code.

### [F-06] The Kite live adapter: latent execution defects
Severity: **P3** · Status: **BROKEN** (latent)

**Reachability**
Only the daily desk's `paper --live` with `account.mode: live` (config: `paper`) plus credentials. The intraday desk
has no live broker.

**Evidence** [synth, with a fake Kite API; nothing left the process]
- **Partial fills are lost.** 130 of 650 filled, then the timeout: the order is cancelled and `execute` returns
  `None`. `filled_quantity` is never read, so the 130 held at the broker are unknown to the desk.
- **Fills are stamped `pd.Timestamp.now()`:** naive local time, not the exchange's.
- **Futures symbology** = always the nearest expiry; the data side rolls 3 days early.
- **Multi-leg orders go leg by leg** with 20-second waits.
- **The docstring says** "Untested against the real API".

**Reproduction**
`test_phase_f_probes.py::test_kite_adapter_drops_a_partially_filled_order`, `::test_kite_futures_symbology_ignores_the_roll`.

**Recommended fix**
Before any live use: partial-fill accounting, exchange timestamps, roll-consistent symbology, an atomic multi-leg
policy, and a sandbox test.

**Confidence:** High.

### [F-07] Calendar and contract edges
Severity: **P4** · Status: **VERIFIED**

- **Holidays.** Configured for 2026 only. 2027-01-26 (Republic Day, Tuesday) counts as a trading day and a NIFTY
  expiry.
- **Futures history across a roll.** The 5-day history is fetched on the currently active contract, so across a roll
  earlier days carry the next month's volume.
- **Unlisted weeklies.** The model chain draws expiries from the calendar, so it can price weeklies the exchange has
  not listed.

**Reproduction**
`test_phase_f_probes.py::test_holidays_end_in_2026_so_republic_day_2027_is_an_expiry`; `phase_f1_expiries.py`.

**Recommended fix**
- Per-year holidays from the warehouse, failing closed when a year is missing.
- Per-contract history across rolls.

**Confidence:** High.

## Verified-working controls (all phases)

| ID | Control | Evidence |
|---|---|---|
| V-01 | Ledger leakage guards, as code: a decision recorded at or after `label_end` is refused; an outcome before `label_end` is refused; a duplicate `decision_id` is refused; outcomes come from bars at or after the decision only | `autolearn/ledger.py:65-105, 155-185`. **Never exercised in production (A-01).** |
| V-02 | Walk-forward is day-grouped and expanding, with the lockbox excluded. `purged: 0 / embargoed: 0` in every fold is *correct*: the 30-minute labels never cross a session and folds start at 09:15. The guards are structurally inert, not broken. | `autolearn/validation.py:49-82`; cycle 2026-10-08 fold table |
| V-03 | Model features are causal row by row: changing bar 3 leaves row 0's features unchanged | `intraday/quant.py:112-147`; probe A-08; `tests/test_causality.py` |
| V-04 | Recorded-chain replay returns the newest snapshot at or before t (`RecordedChains.chain`, `chains.py:332-337`); plan research's `at()` does the same with a maximum age (`autolearn/plans.py:262-271`) | code |
| V-05 | EOD context is point-in-time: participant OI and flows `end=day−1` (`brain.py:495`); ATM IV history `end=today−1` (`ivhist.py:57`) and `d < today` (`:73`); global prior session `date < today` (`brain.py:165`); session model `< day` (`engine.py:1021`) | code |
| V-06 | `ReplayFeed` is causal: history before the open only, polls only completed minutes | `feeds.py:250-263` |
| V-07 | What-if replays make stories visible at `seen_at` | `deploy/whatif.py:89` |
| V-08 | Live news is effectively seen-time (an item exists only after its fetch); LLM reads count only from arrival (`rd["at"] > now` → skipped) | `news.py:398-401`, `engine.py:390` |

| V-09 | Setups are generated from live state, not merely described: replay `scan` raised 298 plans, `arm` 594 armed reads; live decisions show fires at the exact armed levels | replay funnel; journal decisions |
| V-10 | Pre-entry plan specification: invalidation, target, premium stop/target and time stop are fixed at plan time; the stop is floored at 0.75 ATR5 | `playbook.py:213-226` |
| V-11 | The fail-closed directional gate works as designed: no directional plan reached EV, risk or execution without an approved plan model, on either entry path | live journal; replay |
| V-12 | Session features (5 m/15 m indicators) use clock-completed bars only | `features.py:_completed` |

| V-13 | The autolearn registration gate is strict: **0/20 random-walk datasets registered** | null simulation (`QUANTDESK_LEARNING_AUDIT.md` § C.1.3) |
| V-14 | The full autolearn chain (train → validate → register → shadow ledger → promote → steer → fail closed on tamper → rollback) works, **in tests only** (synthetic planted signal, relaxed promotion gates) | `tests/test_autolearn.py::test_full_cycle_registers_shadows_promotes_and_rolls_back` |
| V-15 | Model artifacts are content-hashed JSON (no pickle), verified on load with a feature-version check | `models.Pipeline.from_artifact`, `policy.PlanPolicy.from_artifact` |
| V-16 | The plan-research protocol: real-PIT-only qualification, every configuration logged and hashed, a pre-declared selection rule, a DSR counting configurations, the lock opened once per generation, forward gates before promotion | `autolearn/research.py:513-796` |
| V-17 | The EV Monte Carlo is internally consistent on the recorded decisions (cost and theta arithmetic reproduces P(profit) and EV) | journal decision contexts |

| V-18 | The factor and news grading arithmetic is implemented as documented: shrinkage prior 20, 1/6 overlap weight, bounded 0.5×–1.5× multipliers, headlines sharing a window split one observation | `intraday/learning.py`; probes |
| V-19 | Probation graduation is reversible and recomputed every close (no stuck promotions) | `engine._apply_memory`, `brain._probation_weight` |
| V-20 | Self-review detects multi-session zero-trade streaks and missed sessions | `ops/selfreview.py:check_trading`, `check_session` |

| V-21 | `expiry_eve_law_v2` reproduces bit-exactly from today's warehouse with HEAD code (cutoff 2026-10-01): all instruments' n/means, pooled 288 weeks / +9.4754 / t 4.9772 and 288 / +5.4807 / t 3.6338 | `phase_e_repro_v2.py` → `audit/data/phase_e_repro_v2.json` |
| V-22 | All 7 registered results match their spec hashes; every spec was committed before its result and never edited after; the N1 and vol locks were opened once, after their specs | git history; `memory.registry` |
| V-23 | BH (0/2,000 mismatches), PSR and DSR (equal to 1e-6) and NW match reference implementations; NW size 5.4% (iid t3), 8.1% (AR(1) .5) | `phase_e_stats_check.py` |
| V-24 | L1's held-out result is robust on its own data and convention: ACF ≈ 0, block-bootstrap p < 5e-5, best 5 weeks = 11% of the total, NW lag 0–10 gives t 4.54–4.98 | `phase_e_l1_robust.py`, `phase_e_v2_post.py` |
| V-25 | The sleeve and entry-check specs are honest about power, use real quotes, log the cost gap, are append-only and fix their retirement rules in advance; `expiry_eve_entry_v1` has a power analysis and a decision table | `docs/prereg/expiry_seller_v*.json`, `expiry_eve_entry_v1.json` |
| V-26 | D1's sign and size replicate on NSE's official OHLC (NIFTY −6.30 bps/day, t −3.85, 2019–2026): not a Yahoo artifact | `phase_e_d1_official.py` |
| V-27 | Contract identity: every exchange-listed expiry (10-09 → 12-31) for the 6 configured underlyings is on the desk calendar, holiday shifts included; all lot sizes match the bhavcopies; holidays = NSE's weekday list | `phase_f1_expiries.py` |
| V-28 | Pricing: `bs_price` exact vs an independent BS; delta/gamma match finite differences; the IV solver recovers vol (floored only where unidentifiable) | `phase_f3_pricing.py` |
| V-29 | Kotak 1-minute candles are labelled by bar start (answers Q-01): snapshot spot inside bar t0 87% vs t0+1 43% (n = 7,936), so `completed()` admits only finished minutes | `phase_f6_bar_label.py` |
| V-30 | Option OI change is computed as current − previous (Kotak's `oi.chg` is a price change and is not used); OI units (shares vs contracts) handled for GEX; PCR, walls and max pain are unit-invariant | `tests/test_kotak.py`, `chains.py:455` |
| V-31 | Live-order guards: `KiteBroker` needs `account.mode: live` + `--live` + credentials; kill-switch file; marketable LIMIT with a 1% band; notional cap. Config is `paper`. | `execution/kite.py:1-91` |
| V-32 | GEX and participant OI are honestly labelled context and never vote | `analyst.py:309-320`, `brain.py:481` |
| V-33 | With a live book, an entry is skipped if any leg is not two-sided or the net premium moved > 15% against the plan | `engine.py:1158-1175` |

---

## Open questions (carried forward)

| ID | Question | Phase |
|---|---|---|
| Q-01 | ~~Kotak candle timestamps: bar start or bar end?~~ **Answered in Phase F: bar start (V-29).** Original question: bar start (as the docstring says) or bar end? This decides whether `completed()` admits a forming bar. Needs a Kotak key, or the archived chains and option minutes compared with NSE. | A2 → H |
| Q-02 | ~~Does the test suite pass on CI's versions?~~ Answered: CI ran 445 passed, 2 failed (A-19, date-dependent), 6 skipped (§ A.7) | A1 |
| Q-03 | ~~Is the empty plan registry the dominant cause of 0 trades?~~ Answered in B-02: it explains 100% of directional rejections; the iron fly fails EV | B4 |
| Q-04 | ~~What-if parity?~~ Answered: B-11 | B |
| Q-05 | ~~Where is the pre-reset journal?~~ Answered: on 10-05 the journal had 0 trades, so `ensure_account` only changed the capital (no archive). Earlier trades of the ₹20k account (the README cites 29 Sep) are not recoverable from the force-pushed journal branch (A-10); their sessions still feed `memory.json` (D-03) | D |
| Q-06 | ~~Is the iron-fly EV right?~~ Answered: internally consistent; the setup can't pay intraday (C-05) | C3 |
| Q-07 | ~~Does the global-stress size multiplier ever bind live?~~ **Closed in Phase F: unreachable (applied after EV, which no plan passes) and unrecorded (only the latest brain state is persisted)** | F |
| Q-08 | ~~Root cause of the 15:15–15:28 index freeze?~~ **Answered in Phase F: Kotak's index series (the future, same code path, keeps trading; F-02).** Why Kotak freezes it is still open (ask the vendor) | E → F |
| Q-09 | How many hypotheses has the research program tested since inception? (The ledger starts 2026-10-03; earlier reports are not reconstructed) | E |
| Q-10 | Real expiry-eve spreads for FINNIFTY, MIDCPNIFTY, BANKEX and NIFTYNXT50 (no quotes recorded) | E → H |
| Q-11 | Do the frozen minutes bias autolearn's "close" labels and any grading window that ends after 15:15? | E → H |
| Q-12 | How often would the model-chain fallback (F-01) trigger on GitHub-hosted runners, where NSE blocks many cloud IPs and a Kotak outage leaves no real chain? | F → H |

---

## Change log

| Date | Phase | Change |
|---|---|---|
| 2026-10-09 | A | Register created: A-01 … A-18, V-01 … V-08, Q-01 … Q-05 |
| 2026-10-09 | A | A-19 added after the test-suite baseline; Q-02 answered |
| 2026-10-09 | B | B-01 … B-11, V-09 … V-12 added; Q-03, Q-04 answered; Q-06, Q-07 opened |
| 2026-10-09 | C | C-01 … C-08, V-13 … V-17 added; Q-06 answered |
| 2026-10-09 | D | D-01 … D-08, V-18 … V-20 added; Q-05 answered |
| 2026-10-09 | E | E-01 … E-09, V-21 … V-26, Q-08 … Q-11 added. No earlier finding's severity or status changed; A-12, A-14, B-02, C-02, C-04 and D-01 reassessed (`QUANTDESK_RESEARCH_VALIDITY.md` § Reassessment) |
| 2026-10-09 | F | F-01 … F-07, V-27 … V-33, Q-12 added; Q-01 and Q-08 answered, Q-07 closed. E-01's root cause located (F-02). No earlier severity changed. |
