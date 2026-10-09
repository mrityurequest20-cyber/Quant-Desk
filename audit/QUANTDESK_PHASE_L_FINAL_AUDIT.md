# QuantDesk forensic audit — Phase L: final adversarial audit

*2026-10-09. Read-only. Local and uncommitted. This is the last phase before a consolidated implementation blueprint is
approved by the owner.*

**Status of everything below: PROPOSED.**
- The canonical register (`audit/QUANTDESK_FINDINGS_REGISTER.md`, SHA-256 `e49341c0…`) and every earlier report are
  unchanged. Probe `test_canonical_register_is_unchanged` checks the register.
- The new findings **L-01 … L-06**, the severity changes, the corrections and the blueprint are proposals for owner review.
- Nothing here authorizes live trading.

**Evidence classes** used throughout, as in Phases I–K:

| Tag | Meaning |
|---|---|
| `[prod]` | Production persisted data: journal, memory, recorded bars, chain archives, GitHub run and release metadata |
| `[prod-render]` | Production data rendered in headless Chromium |
| `[replay-exact]` | 10-05: persisted bars, chains and memory, with the repo's replay wiring |
| `[replay-subst]` | 10-06 … 10-09: as exact, but prior-day zero-VIX files are dropped (Phase I's documented substitution) |
| `[synth-tick]` | Replay plus an emulated live price: the next bar's O→L/H→C fed as four `tick()` prices inside each minute |
| `[synth]` | Synthetic fixture |
| `[code]` | Code inspection only |
| `[infer]` | Inference |

Production counts are **lower bounds** where the record is sampled (thoughts) or overwritten (heartbeat).

---

## 1. Decision memo

### Proven

| # | Claim | Evidence |
|---|---|---|
| P1 | **No armed-trigger outcome ever reaches the screen.** Coverage is every stepped minute of 5 sessions (1,870 minutes), on both trigger paths. All 60 replayed trigger hits were model-gate rejections. For all 60, the heartbeat action showed nothing and no thought was written; only a `decisions` row records them, and **no code under `quantdesk/web/` reads `decisions`** | `[replay-exact]` `[replay-subst]` `[synth-tick]` `[code]` |
| P2 | **All 22 production armed rejections came from the live-tick path.** They are stamped at seconds 0–57, while all 51 EV rows are at :04, the minute-step cadence. **0 of 22** is recorded in any thought | `[prod]` |
| P3 | **On the tick path the screen contradicts itself.** Rendered in Chromium: the headline says "Watching · no setup has triggered" while the NIFTY line says "Waiting at the level: Trend_break …", with nothing armed. The cause is that `tick()` writes the heartbeat without updating `last_action`, after `_fire_armed` emptied the armed list | `[synth-tick]` render; `[code]` |
| P4 | **The India VIX learned multiplier reconciles exactly with the record.** All 5 session multipliers (1.0196 → 0.9798 → 0.9934 → 0.9975 → 0.9538) are reproduced to 4 dp by re-grading the persisted thoughts against the recorded bars. The 10-09 12:20 PREV memory matches to 3·10⁻⁴. Since the reset, **100.67 of 100.83** graded weight units came from fabricated "India VIX 0.00 (−100%)" +1 votes. Without them the CLOSE multiplier would be 1.0208, not 0.9838 | `[prod]` |
| P5 | **The app's learning panel ranks VIX #2 of its top-12 IC table** (\|t\| 1.85). That IC is computed on a regressor with mean 0.999 and variance 0.0002, i.e. on the fabricated vote | `[prod]` `[code]` |
| P6 | **The VIX vote changes the replayed decision stream but no trade.** On 10-05 (exact replay) it changes bias in 29 of 750 symbol-minutes and the armed set in 46. With the vote removed, 2 more triggers fire; all are still rejected. Production made 0 trades | `[replay-exact]` `[replay-subst]` |
| P7 | **I-10's cause is verified against run metadata.** live.yml's only run on 09-30 was `schedule`, created 09:49:30Z (15:19 IST). On 10-01 it was created 10:16:38Z (15:46 IST) and lasted 80 s. The cron was `22 3 * * 1-5` (08:52 IST). There was no dispatch either day. The dispatcher (`scheduler.yml`) arrived in 3e2b99a, 10-02 09:37Z | `[prod]` (GitHub) |
| P8 | **The backup cron still runs the whole live pipeline after the close, every day** (created 10:23–10:43Z). It uploads duplicate archive assets, and its "morning" bars asset is the full day. It also saves the journal again; on 10-09 it changed no journal content | `[prod]` (GitHub) |
| P9 | **GitHub Pages last deployed on 10-08 at 10:46Z.** 389 of 389 runs are listed. gh-pages was pushed on 10-09, and the 10-09 live run reported success. At 18:35Z the site, and therefore the Worker that proxies it, **returned HTTP 404**. Build+deploy time for the 382 successful runs: median 27 s, max 147 s | `[prod]` (GitHub + HTTP) |
| P10 | **EV rejection text reports a P(up) that was not used.** Production: all 51 EV rows priced an iron fly (direction 0 → P(up) 0.50), and 33 of them print a different P(up). Replay: 14 of 41. The quant card's "P(up) used" says "coin flip + prior" | `[prod]` `[replay]` `[code]` |
| P11 | **A trigger hit while halted leaves no record** | `[synth]` on `[replay-exact]` |

### Indicated (not proven)

| # | Claim | Why only indicated |
|---|---|---|
| N1 | **The zero VIX comes from Kotak's candle payload, not from parsing.** The zeros sit only on Kotak-served minutes. The one nonzero bar per day has Yahoo-style float32 artefacts (e.g. 14.157500267…). On 10-08 the review counts 1 Yahoo poll and there is 1 nonzero bar. The candle path has no `> 0` guard, while `ltp()` has one | The raw Kotak payload has never been captured (A-11). Settling it needs a credentialed owner action |
| N2 | **Production screens showed "Waiting at the level" with nothing armed, about 22 times for a combined ~11 minutes** (675 s by code) | The path is proven, but the heartbeat is overwritten, so production screens are not recountable |
| N3 | **Viewers of the published site saw expired armed cards** | The mechanism is proven: TTL 2 min < 6-min publish cadence, and the app never checks `expires`. 138 of 315 replay publish points carried a card, and one production gh-pages snapshot has one. No viewer is observed |

### Unknown (marked unresolved; nothing invented)

- The Kotak INDIA VIX payload.
- Why Pages stopped deploying, when the 404 began, and what (if anything) was served during the 10-09 session.
- CDN/edge latency after deployment.
- How the ₹20k account's pre-10-05 trades, thoughts and events disappeared.
- What production would have decided without the VIX vote. News, the brain, breadth and the learner are not replayable (I-04).

Full list: §9.

### Prerequisites before any implementation

1. **The owner confirms that no live-trading mode is enabled anywhere.** This is the P0 condition of J-02 and H-01.
2. **The owner inspects Settings → Pages and the Cloudflare Worker and restores the published site (L-04),** or records why it is off.
3. **The owner decides on the proposed register changes** (§7) through their own process. This audit does not apply them.
4. **Governance controls (S0: G-01, G-02, A-19, A-03) come before any autonomous change** to the code below.
5. **Freeze the evidence before any rebuild:**
   - copy `memory.json`, `journal.db` and the gh-pages content;
   - keep the contaminated VIX record for audit, so the S2 rebuild cannot erase it.
6. **The owner captures one raw Kotak INDIA VIX candle response,** to settle N1 before the S2 design is fixed.

---

## 2. L1: decision-to-UI consistency attack

### Method

`audit/probes/phase_l_consistency.py` replays a recorded session minute by minute: the Phase K wiring, with the 12:20
hand-over emulated.

**Instrumentation (harness only; the class and the repo files are untouched).** It wraps the engine instance's own
methods: `_fire_armed`, `_blocked`, `playbook.fire` and `ev.evaluate`. For every armed-trigger hit it records:
- the real outcome;
- the decision and thought rows written;
- `last_action`;
- the heartbeat action and armed list;
- what the app shows.

**What the app shows** comes from a Python port of `app.js` `readAction` / `stance` / `renderNow`. The port reproduces
**10 of 10** Phase K Chromium renders: every headline and all 20 per-index lines (`phase_l_ui_port_check.json`).

**Two trigger paths:**
- `bar`: the repo's replay. Each new bar's range fires.
- `tick`: production's live price (Kotak LTP every 5 s), emulated `[synth-tick]`.

**Coverage:** 10-05 `[replay-exact]` and 10-06 … 10-09 `[replay-subst]`. The 10-09 afternoon chain archive was fetched
read-only from the `chains-2026` release, as the others were. Each path covers 5 sessions, 1,870 stepped minutes and 60
trigger hits.

### Results

| Measure (5 sessions) | bar path | tick path |
|---|---|---|
| Trigger hits / outcomes | 60 / 60 model-gate rejections | 60 / 60 model-gate rejections |
| Outcome in a `decisions` row | 60 | 60 |
| Outcome in the heartbeat action (what the UI reads) | **0** | **0** |
| Outcome in a thought (Desk log) | **0** | **0** |
| First screen after the hit | same level re-armed **8** (K-01) · other setup re-armed 6 · **"no setup has triggered" 41** (K-02) · standing aside (other reason) 5 | **"Waiting at the level" with nothing armed: 60** |
| The next minute's screen | — | same level re-armed 8 · armed 6 · "no setup has triggered" 41 · aside 5 |
| Minutes whose headline says "no setup has triggered" while a rejection was written that minute | 29 | 31 tick heartbeats |

| Session | Class | Hits | Same-level re-arm | "No setup has triggered" | Other re-arm / aside |
|---|---|---|---|---|---|
| 10-05 | `[replay-exact]` | 9 | 2 | 6 | 1 / 0 |
| 10-06 | `[replay-subst]` | 10 | 1 | 9 | 0 / 0 |
| 10-07 | `[replay-subst]` | 3 | 1 | 1 | 0 / 1 |
| 10-08 | `[replay-subst]` | 26 | 2 | 20 | 3 / 1 |
| 10-09 | `[replay-subst]` | 12 | 2 | 5 | 2 / 3 |

### Reproducible examples

- **10-05 10:56 (exact replay).** "trend_break reached its level 22,465.46 but standing aside: no approved plan model …".
  The heartbeat shows "armed: trend_break: sell on a trade through 22,465.46" and the headline reads "Armed · Trend break
  put on NIFTY at 22,465.46". This is K-01.
- **10-05 11:24 (exact replay).** The trend_break at 22,457.90 is rejected, and the heartbeat says "watching: no setup
  has triggered". This is K-02.
- **10-05 10:55:40 (tick path).** The rejection is followed by a heartbeat with "armed: trend_break …" and `armed: []`.
  Rendered in Chromium (`phase_l_screens/l1005_tick_rejected_105540_*`):

  ```
  NOW  Watching · no setup has triggered   10:55
  NIFTY Waiting at the level: Trend_break: sell on a trade through 22,465.46 (stop 22,511.70)
  ```

### Production (lower bounds; `phase_l_prod_consistency.json`)

| Measure | Value | Denominator |
|---|---|---|
| Armed rejections at the step cadence (:04) | **0** (seconds 0–57) | 22. EV rejections: 51 of 51 at :04 |
| Armed rejections recorded in any thought | **0** | 22 |
| A sampled thought exists in the next minute | 3 (1 same-level re-arm, 2 "no setup has triggered") | 22 |
| First sampled thought within 5 min | 5 same-level re-arm · 2 same setup at a new level · **6 "no setup has triggered"** · 8 standing aside · 1 none | 22 |
| By code: tick heartbeat "waiting with nothing armed" until the next step | about 675 s in total | 22 |

These agree with Phase K: 7 of 22 were re-armed with the same setup within 5 min.

### Other attack classes

| Class | Result | Evidence |
|---|---|---|
| **Same-minute re-arm** | Proven, 8 of 60 (above) | `[replay]` |
| **Repeated re-arm.** The same level is re-armed after repeated rejections | 10-05: 11:51 and 11:59 at 22,448.78 / 22,448.79 | `[replay-exact]` |
| **Expired triggers.** The app never compares `expires` with now. Ticks only fire unexpired setups (`_fire_armed:457`) | No expired setup fired (0 of 60). Expired cards stay on the **published** site: **L-03** | `[code]` `[replay]` `[prod]` |
| **Multiple setups** | More than one armed in 273 of 1,870 minutes; on more than one index in 178, where the headline names only `armed[0]`. The per-index lines list every setup, so this is **not misleading** and no finding is proposed | `[replay]` |
| **Silent blocked path** | A hit while halted clears the armed list and returns with no record. The control run at 10:56 writes 1 decision; the halted run writes 0 decisions and 0 thoughts: **L-02** | `[synth]` |
| **EV-floor P(up)** | The message prints the tilted P(up); a non-directional iron fly is evaluated at 0.50. Replay: 14 of 41 differ. Production: **33 of 51** differ, and 51 of 51 are iron fly. The quant card says "coin flip + prior" in 41 of 41. This is **I-07**, now fully covered. Evaluator arguments: `ev_calls` in the raw output | `[prod]` `[replay]` `[code]` |

### Root cause (demonstrated)

A single mechanism explains K-01, K-02, J-07, J-08 and L-02:

1. **`step()` discards `_fire_armed`'s result.** See `engine.py:257-258`.
2. **A model-gate rejection writes only a decision row.** This is by design: `engine.py:477-482` carries the comment
   "on the decision record only: this minute's read isn't formed yet".
3. **The minute's own `_think` then overwrites `last_action`.** See `engine.py:307` → `:1347`.
4. **`tick()` writes the heartbeat without touching `last_action`.** See `:565-574`.
5. **No endpoint serves `decisions`.**

This is proposed as **L-01**, the parent of a duplicate group (§5).

---

## 3. L2: invalid-input propagation (India VIX and other series)

### The chain, stage by stage

| Stage | What happens | Evidence | Status |
|---|---|---|---|
| Provider payload | Kotak `historical/details` candles for `nse_cm\|INDIA VIX` | — | **Unresolved:** the payload has never been captured |
| Parsing | `KotakClient.candles` takes `r[:6]` and `to_numeric`, with no range check. `KotakFeed.ltp` does guard `p > 0`; the candle path does not | `kotak.py:194-204, 415-426` `[code]` | Shown: zeros pass through unchanged |
| Validity checks | **None on the intraday path.** `data/validation.py:40` (the `INDIAVIX` flat-run exemption) is imported only by `ops/checks.py`, the daily system, so it is **not causal** here | grep, probe `test_candle_path_has_no_positive_guard_and_the_validation_exemption_is_off_path` | Shown |
| Recorded bars | 10-05 … 10-09: 372–373 of 373 bars have **all of OHLC = 0**. The one nonzero bar per day (10-06 09:49, 10-08 13:15, 10-09 13:22) carries float32 artefacts like the Yahoo-bootstrapped 09-29 file, while NIFTY/BANKNIFTY bars in the same minutes are clean 0.05 ticks. On 10-08 the review reports "1 of 567 polls from Yahoo", matching the 1 nonzero bar | `phase_l_series_scan.json` `[prod]` | Source split **indicated** (N1) |
| Factor | `_vix_state`: chg = 0 / prior close − 1 = −100%. With a recorded zero prior day, base 0 → ZeroDivisionError (replays only; production's prior days came from Yahoo) | `engine.py:411-420` | Shown (I-01, I-04) |
| Vote | `−clip(−1/0.06)` = **+1.0** (bullish), weight 0.3 × the learned multiplier. 742 of 743 production reads | `analyst.py:233-235` `[prod]` | Shown (I-01) |
| Decisions | Shifts score, bias and arming, and the EV prior tilt for directional structures. Replay counterfactual below | `[replay]` | Shown, replay only |
| Memory (grading) | `grade_factors` grades the constant +1 against the 30-minute forward move | below | Shown, exactly reconciled |
| Multiplier | `reliability = clip(2·(hits+10)/(n+20), 0.5, 1.5)` | below | Shown |
| IC table / UI | `ic_table` ranks `vix` #2 (shown in the app). The UI shows "India VIX 0.00 (−100.0% today)" as a learned bullish factor (J-01) | `phase_l_vix_ic.json` `[prod]` | Shown: **L-06** |
| Model chain | Would price at IV 0 (I-09) or a silent 14.0 (H-08). **Never used in production:** 0 "model chain" events; chain source `kotak`/`nse` on 743 of 743 reads | `[prod]` | Exposure only |
| Autolearn / research | `autolearn/research.py:313` and `research/edges.py` read Yahoo VIX, and `plans.py:324` uses VIX only if `> 0`. **Not contaminated.** I-01's P1 escalation condition is **not met** | `[code]` `[prod]` | Shown |

### The multiplier movement 1.020 → 0.954, reconciled (`phase_l_vix_learning.json`)

| Session | State before (n / hits) | Reconstructed multiplier | Recorded on the thoughts | Increment that session (n / hits; fabricated reads) |
|---|---|---|---|---|
| 10-05 | 116.33 / 59.50 | 1.0196 | 1.0196 | 20.17 / 7.17 (121 votes, all +1) |
| 10-06 | 136.50 / 66.67 | 0.9798 | 0.9798 | 19.83 / 10.83 (+0.17 / 0.17 real) |
| 10-07 | 156.50 / 77.67 | 0.9934 | 0.9934 | 19.67 / 10.17 |
| 10-08 | 176.17 / 87.83 | 0.9975 | 0.9975 | 20.17 / 5.33 |
| 10-09 | 196.33 / 93.17 | **0.9538** | **0.9538** | 20.83 / 13.50 |
| after 10-09 (CLOSE) | 217.17 / 106.67 | 0.9838 | — | — |

**What this means (without over-attributing).** The movement is entirely the grading of a constant bullish vote. It
measures whether NIFTY/BANKNIFTY rose over the next 30 minutes (46.7% of the time, weighted): **market direction, not
anything about volatility.**

- The state before 10-05 (n 116.3) is the bootstrap/pre-reset record (J-05), which the CLOSE memory cannot split further.
- The PREV snapshot reproduces the pre-10-09 state within 3·10⁻⁴. This independently confirms the method.

### Contaminated record vs affected trade

| Item | Contaminated? | Affected outcome? |
|---|---|---|
| 743 production thoughts (evidence) | Yes, 742 | Bias label different in 23 reads (I-01); arming and EV tilt shifted |
| `memory.json` `factor/vix` | Yes: 100.67 of 217.17 weight units since the reset | Multiplier 0.95–1.02 instead of ≈1.02. That multiplier scales a fabricated vote anyway |
| `memory.json` IC `vix` | Yes: computed almost entirely on the constant regressor | Displayed as the #2 learned signal (L-06) |
| Replayed decision stream | n/a | 10-05: 2 more triggers without the vote; 10-08: 1. All rejected (model gate) |
| Trades | n/a | **None.** Production made 0 trades |
| Autolearn / research datasets | No (Yahoo, guarded) | None |
| Recorded bars archive | Yes (5 VIX files) | Every replay of 10-06 … 10-09 needs a substitution (I-04) |

### Other series (`phase_l_series_scan.json`)

| Series | Result |
|---|---|
| Bar files (31) | **Only the 5 INDIAVIX files** have non-positive OHLC. No high < low, no close outside its range, no duplicate stamps. The only missing minutes are the hand-over hole: 12:20–12:21 on each post-reset session, 12:20 on 09-29 (A-06, as labelled) |
| Chains (10 archives, 687,002 rows) | 0 crossed books, 0 one-sided rows, 0 non-positive spot. **IV missing or ≤ 0 on 53,169 of 1,371,634 two-sided quotes (3.9%)**, mostly deep in-the-money (median |moneyness| ≈ 3%). Not decision-affecting as far as Phase F found (ATM analytics); recorded as an observation (U-L9) |
| Evidence observations | Only `vix` carries `0.00 (` / `nan` / `inf` (742 of 743) |

---

## 4. L3: historical data and scheduler corrections

### I-10 against the scheduler record (`phase_l_scheduler_runs.json`)

| Day | live.yml runs (all 17 are listed) | What it means |
|---|---|---|
| 09-29 | dispatch 01:40Z (cancelled), dispatch 02:05Z (cancelled), **dispatch 03:03Z–10:01Z (session)**, schedule 09:57Z | A real session, manually dispatched |
| 09-30 | **schedule only, created 09:49:30Z = 15:19 IST**, ran to 10:01Z | 10 bars (15:20–15:29) |
| 10-01 | **schedule only, created 10:16:38Z = 15:46 IST**, 80 s | No session |
| 10-02 | schedule 09:53Z | NSE holiday; exits |
| 10-05 … 10-09 | **dispatch 03:00Z by github-actions[bot]** (the Worker → scheduler.yml), plus a post-close schedule run at 10:23–10:43Z | Real sessions, plus L-05 |

**Separating the timeline from the cause:**
- **Observable timeline:** above.
- **Proximate cause (verified):** the only trigger on 09-30 and 10-01 was the `22 3 * * 1-5` cron (08:52 IST), and
  GitHub created those runs 6 h 27 m and 6 h 54 m late. The dispatcher that replaced it was added on 10-02 (3e2b99a,
  whose message records the same lateness).
- **Why GitHub delivered late:** external and unknowable from here. It is not needed.

**I-10 correction accepted, and its scheduler attribution is now confirmed against metadata.**

### Claims that label an absence, a replay limit or an overwrite as a persistence defect

| ID | Current wording | Phase L verdict | Proposed |
|---|---|---|---|
| **I-10** | "Market data for some sessions is not persisted anywhere" | **Mislabel** (absence, not a persistence defect) | Retitle: "No live session on 10-01 and 10 minutes on 09-30 (late cron); the record has holes". The completeness-check acceptance stays |
| **Q-05** | "Answered: … earlier trades … are not recoverable from the force-pushed journal branch (A-10)" | **Over-attributed** | The 10-05 08:31 auto-reset found **0 trades**, so the rows were already gone. Other evidence: news rows from 09-29 survive; no `DELETE` exists in the code; the 10-05 run **skipped** "Start a fresh paper account"; the journal branch is a single force-pushed commit. **Cause unresolved**; A-10 explains why it can't be recovered, not why it disappeared |
| **D-03** | "aggregate-only … cannot be replayed" | **Partly too strong** | The post-reset increments reconstruct exactly from thoughts and bars (§3); only the bootstrap/pre-reset part is unreplayable |
| **A-02** | "crashes at every session start and hand-over" | Wording | 9 of 10 since the reset (10-05 09:15 succeeded); still recurring on 10-09 |
| **A-06** | 12:20–12:21 hole | Correct as labelled (a recording gap by design of the hand-over) | — |
| **I-02** | News "first seen" overwritten | Correct (an overwrite, labelled as such) | — |
| **I-04** | Not replayable from persisted evidence | Correct, and it is a replay limitation, as labelled. L adds that factor grading *is* reconstructable | Note only |
| **J-05** | "10 sessions graded" | Clarified per owner: 6 of 11 are bootstrap Yahoo replays (09-24 … 10-01, including 10-01) | Carry |
| **K-01 … K-06 production renders** | "production" renders | They render **gh-pages branch content**. With L-04, whether that content was *served* on 10-09 is unknown | Caveat added |

### L-05: the backup cron after the close

On 10-05 … 10-09, live.yml's cron runs are created at 10:23–10:43Z, after the dispatched session ends. Both jobs run in
full:

| Job | Steps that ran | Duration |
|---|---|---|
| morning | restore → trade | 15 s |
| | save the journal | |
| | upload the "morning" Parquet | |
| afternoon | trade to the close | 16 s |
| | expiry sellers, progress | |
| | save the journal | |
| | upload | |
| | Kotak option minutes | 14 min |

Each day the release gains `…_morning-<late run>_bars/gift/tape.parquet`, which are **byte-identical in size to the
full-day afternoon assets**, and no chains.

On 10-09 the journal content was unchanged: the last event is 15:31:04 and the heartbeat is 15:30:04. The other days
were not checked (U-L7).

---

## 5. L4: status, provenance and observability recheck

### Cross-phase status after Phase L

| Area | Findings | State after L | Evidence class |
|---|---|---|---|
| Open | K-03 | "Stale" until the first in-session publish. Measured: the first deployment was created at 09:19:34–09:19:40 IST on 10-05 … 10-08 and builds in a median 27 s, so the window is about 5 min plus CDN (unmeasured). 10-09: no deployment at all (L-04) | `[prod]` `[prod-render]` |
| Hand-over | K (control), H-07, B-04 | Figures continuous; armed state and safe mode not carried (unchanged) | `[replay-exact]` |
| Close | K-04 | "Live 15:30" until 15:44 (unchanged) | `[prod-render]` |
| Stale data | J-11, K-03, L-03 | Expired armed cards added (L-03) | `[code]` `[replay]` `[prod]` |
| Outages | K-06, **L-04** | The site itself was down (404) after 10-09 with no alert | `[prod]` |
| Reconciliation and halts | J-03, H-04 | Unchanged: not shown as halts, never alerted | `[synth]` |
| Modelled quotes | K-05, F-01 | Unchanged; the model chain was never used in production (0 of 743) | `[synth]` `[prod]` |
| Decision visibility | J-07, J-08, K-01, K-02, **L-01, L-02** | 0 of 60 replay and 0 of 22 production trigger outcomes visible | all classes |
| Trade detail | K-05 | Unchanged (synthetic only; 0 production trades) | `[synth]` |

### Duplicates and shared root causes

The machine-readable version is `duplicate_groups` and `root_cause_families` in the JSON.

| Group | Parent | Members | Relation |
|---|---|---|---|
| Trigger outcome not shown | **L-01** | K-01, K-02, J-07, J-08, L-02, B-03 | RC5a. Keep the members as UI acceptance tests |
| India VIX zero | **I-01** | J-01, H-08, I-09, L-06 | One input defect on four surfaces: data, display, model chain, learning statistic |
| EV P(up) text | **I-07** | K's "I-07 in the UI" | Same defect |
| Operator surface health | **H-04** | L-04, K-03, K-04, K-06, J-11, L-03 | RC5b. One post-publish verification plus a status model closes most |
| Cron lateness | **H-05** | I-10, L-05 | RC6 |
| Restart state | **H-01** | H-02, H-03, H-07, I-06, J-02, B-04 | RC7 |

The post-G RC5 ("observability gaps") is split into **RC5a**, decision outcomes not propagated, and **RC5b**, the
operator surface's health not monitored. **RC6** (cron scheduling) and **RC7** (crash/restart state machine) are added.

### Pages latency (`phase_l_pages_latency.json`)

**Measurable read-only (partially).** From the `pages-build-deployment` run record (389 runs, all listed):

| Measure | Value |
|---|---|
| Build+deploy, created → updated (382 successful runs) | median **27 s**, p90 56 s, p99 115 s, max 147 s |
| Realised in-session cadence | 64–66 deployments per session, median gap 6.05 min, max 6.07 min (10-05 … 10-08) |

**Not measurable:**
- the CDN/edge cache after deployment;
- the `export-site` → push delay;
- what any browser rendered.

Together these give a lower bound on staleness at view time: up to about 6 min of publish cadence plus build time.

**L-04.** No deployment exists after 2026-10-08 10:46Z, although gh-pages was pushed through 10-09 16:14 IST
(`e80b0ed`). At 18:35Z, `GET …github.io/Quant-Desk/data.json`, `/Quant-Desk/`, `/index.html` and `/` all returned
**404** from GitHub. The Worker proxies that origin, so it would pass the 404 through
(`deploy/cloudflare/worker.js:51-83`).

The cause, the start time, and whether the 10-09 session was ever served are **unresolved**. They need the owner's Pages
settings and the Cloudflare logs.

### Do the controls have testable acceptance criteria that separate evidence classes?

**Mostly no.**
- Of the 109 pre-L findings, **8** have acceptance criteria that name two or more evidence classes
  (production / replay / synthetic; keyword count).
- Phase L gives each of its six findings a hand-written split.
- For the other 109 it adds a **template** split, marked `"template": true` in the JSON, which the owner must refine:
  - **synthetic:** the named probe flips;
  - **replay:** 0 occurrences on the recorded-session replays, where the defect is observable there;
  - **production:** 0 occurrences over ≥ 5 consecutive sessions from persisted records; "n/a" for latent paths that must
    not be provoked in production.

---

## 6. New findings (proposed)

### L-01: An armed trigger's outcome never reaches the screen

| Field | Value |
|---|---|
| Severity / status | **P3** / **VERIFIED**. The family's severity is that of its members (K-01, K-02, J-07, J-08: P3). Escalate to P2 if the model gate becomes passable, because sized-to-zero and blocked hits are equally invisible |
| Component | `engine.py:257-258` (result ignored); `:477-482` (decision only); `:565-574` (`tick()` heartbeat); `:1347` (`_think` overwrite); no `decisions` endpoint |
| Evidence | `[replay-exact]` `[replay-subst]` `[synth-tick]` `[prod]` `[code]`. The heartbeat is overwritten in production (lower bounds only) |
| Root cause | Demonstrated (§2) |
| Acceptance | Every armed hit produces exactly one outcome record that the UI shows for at least 1 minute. No heartbeat after a rejection says "armed" at the rejected level, or "no setup has triggered" |
| Acceptance: synthetic | Tick fixture: 0 heartbeats with an "armed:" action and no armed entry for that index |
| Acceptance: replay | `phase_l_consistency` over 5 sessions × 2 paths: 0 of N outcomes unshown (today 60 of 60 unshown on each path) |
| Acceptance: production | 5 sessions: every `decisions` row with `context.armed` has a matching thought or heartbeat outcome within 60 s |
| Regression | `test_every_replayed_trigger_rejection_is_hidden_from_the_screen` (flips) |

### L-02: A hit while halted leaves no record

| Field | Value |
|---|---|
| Severity / status | **P4** / **VERIFIED** `[synth]` (0 production occurrences observable) |
| Component | `engine.py:465-468` |
| Acceptance | A blocked hit writes a decision row with the halt reason. Synthetic: `phase_l_blocked_silent` shows 1 row at 10:56. Replay / production: n/a until a halt coincides with a hit |

### L-03: Published armed cards outlive their expiry

| Field | Value |
|---|---|
| Severity / status | **P3** / **VERIFIED** (mechanism); viewer exposure `[infer]` |
| Component | `anticipate.ttl_min: 2` (`config/quantdesk.yaml:173`); `PUBLISH_EVERY_MIN` 6 (`deploy/run-session.sh`); `app.js` `renderNow` / `armedRow` never compare `expires` |
| Evidence | 138 of 315 replay publish points carry an armed card. Production gh-pages snapshot: published 12:46:04, armed until 12:48:04, next publish about 12:52 |
| Acceptance | The app hides or greys entries with `expires` < now, or publishing every ≤ TTL. Synthetic: render at `expires` + 1 min shows no "Armed ·" headline. Production: 0 expired cards rendered live over 5 sessions of gh-pages snapshots |

### L-04: The published site is down (404) and Pages stopped deploying, with no alert

| Field | Value |
|---|---|
| Severity / status | **P2** / **OBSERVED** `[prod]`; cause and start time **UNRESOLVED** |
| Evidence | Pages runs: 389 listed, last 2026-10-08T10:46:21Z. gh-pages head `e80b0ed` at 10-09 10:44:55Z. HTTP 404 from GitHub at 18:35:51Z (`phase_l_pages_get_20261009T1835Z.txt`) |
| Risk | The operator's only window is down silently. Phase J/K "production renders" describe branch content, not necessarily served content |
| Acceptance | A post-publish check fetches the *served* `data.json`, compares its heartbeat `ts` with the pushed one, and alerts on a mismatch or a non-200. Synthetic: a 404 or stale body raises an alert. Production: every in-session publish is verified as served within 5 min over 5 sessions |
| Earliest stage | **S0**: an owner check of settings, before anything else relies on the site |

### L-05: The post-close backup cron runs the full pipeline

| Field | Value |
|---|---|
| Severity / status | **P4** / **VERIFIED** `[prod]` |
| Root cause | live.yml's cron is kept as a backup (3e2b99a) and is delivered after the close |
| Acceptance | A live.yml run started after 15:30 IST exits before restoring or saving the journal and uploads nothing. Production: 0 release assets from runs created after 10:00Z over 5 sessions |

### L-06: The learning IC table ranks a near-constant regressor

| Field | Value |
|---|---|
| Severity / status | **P3** / **VERIFIED** `[prod]` `[code]` |
| Component | `learning.ic_table` guards only `vx <= 1e-12` |
| Evidence | `vix` is #2 of the app's top 12 (\|t\| 1.85 at 5 min); direction mean 0.999, variance 0.0002 at every horizon |
| Acceptance | Factors below a stated floor on direction variance or distinct values are excluded and labelled. Production: the CLOSE memory no longer lists `vix` until it is rebuilt |

---

## 7. Reconciliation table (history preserved; nothing applied)

| ID | Before | Proposed after | Basis |
|---|---|---|---|
| **J-01** | P2 MISLEADING | **P1** | Owner decision (Phase J review) |
| **J-02** | P2 (P0 if live) | **P2; P0 if any live-trading mode is enabled** | Owner decision |
| **J-03** | P2 | **P2** (kept) | Owner decision |
| Other J | as reviewed | unchanged | Owner decision |
| **K-01** | P3 | **P3**; extended: 8 of 60 replay hits, child of L-01 | Owner (exact replay) + L1 |
| **K-02** | P3 | **P3**; extended: 41 of 60 replay hits, production lower bound 6 of 22, child of L-01 | Owner (substituted + production) + L1 |
| **K-03** | P3 | **P3**; deploy time now measured, CDN still not; 10-09 had no deployment (L-04) | Owner (partially reproduced) + L4 |
| **K-04** | P4 | **P4** | Owner |
| **K-05** | P3 | **P3** (synthetic only) | Owner |
| **K-06** | P4 | **P4** | Owner |
| **I-10** | P3 "not persisted anywhere" | **Retitled**; scheduler cause **verified** against run metadata | Owner correction + L3 |
| **J-05** | P2 | **P2**, clarified: 6 of 11 graded sessions are bootstrap Yahoo replays, including 10-01; L-06 added | Owner + L2 |
| **I-01** | P2; root cause UNVERIFIED | **P2**. Root cause still unverified, but indicated (N1). The `validation.py:40` exemption is **not** causal. P1 escalation **not met** (autolearn is clean). Learning effect reconciled exactly | L2 |
| **I-07** | P3; 33 of 51 | **P3**; cause pinned (iron fly at 0.5, 51 of 51); replay 14 of 41; UI card wording | L1 |
| **Q-05** | "Answered" (force-push) | **Re-opened: cause unresolved** | L3 |
| **A-02** | "every session start and hand-over" | "9 of 10 since the reset; still recurring" | L3 |
| **D-03** | "cannot be replayed" | "post-reset increments reconstruct exactly; the bootstrap part does not" | L2 |
| **H-05** | P3 | P3; the same mechanism generalises (I-10, L-05) | L3 |
| **RC5** | one family | **split into RC5a / RC5b; RC6 and RC7 added** | L4 |
| **L-01 … L-06** | — | **New**, as in §6 | L |

**Superseded:** none. K-01, K-02, J-07 and J-08 stay open as surface tests under the L-01 parent.

**Withdrawn:** none.

---

## 8. Consolidated register (proposed)

`audit/data/phase_l_consolidated_findings.json`, built by `audit/probes/phase_l_consolidate.py` from the post-G matrix
(A–G), the H proposal, and the I/J/K/L sections.

**Contents:**
- **115 findings**: A 19 · B 11 · C 8 · D 8 · E 9 · F 7 · G 6 · H 14 · I 10 · J 11 · K 6 · L 6.
- **Effective severity** (owner decisions applied *in the proposal only*): **P1 7** (A-01, C-01, D-01, E-01, G-01,
  H-01, J-01) · P2 36 · P3 55 · P4 17.

**Per-finding fields:**
- id, phase, severity, status;
- evidence class, with its derivation method (A–G from matrix codes, H–K keyword-derived and **to be reviewed**, L
  hand-assigned);
- confidence and uncertainty;
- root-cause family and whether it is demonstrated;
- related, duplicate group, risk if unresolved;
- acceptance and its split by evidence class (hand-written for L; template elsewhere);
- regression test, dependencies, roadmap item, earliest stage, gate;
- owner decision and Phase L update, where present.

**Earliest safe remediation stage:**

| Stage | Findings |
|---|---|
| S0 | A-03, A-19, G-01, G-02, L-04 |
| S1 | A-10, A-13, A-15, B-11, C-08, E-05, E-06, G-04, G-06, H-11, I-02, I-03, I-04, I-05, I-07, I-08, I-10 |
| S2 | A-04, A-06, A-11, A-12, A-14, A-16, A-18, B-10, D-03, F-01, F-02, G-03, H-08, H-13, I-01, I-09 |
| S3 | A-02, H-01, H-02, H-03, H-06, H-07, H-09, H-10, H-12, H-14, I-06 |
| S4 | J-01 … J-04, J-06 … J-11, K-01 … K-04, K-06, L-01 … L-03 |
| S5 | D-07, F-07, G-05, H-04, H-05, L-05 |
| S6 | A-01, A-05, B-02, B-03, B-04, B-06, B-07, B-08, B-09, C-01, C-05, C-06, D-05 |
| S7 | A-07, A-08, A-09, B-01, B-05, C-02, C-03, C-07, D-01, D-02, D-04, D-06, D-08, E-02, E-04, E-08, E-09, J-05, L-06 |
| S8 | C-04, E-01, E-03, E-07, F-03, F-04, F-05, K-05 |
| S9 | A-17, F-06 |

---

## 9. Implementation blueprint (dependency-ordered; proposed, not implemented)

### Stages

| Stage | Work | Depends on | Acceptance (exit) | Blockers |
|---|---|---|---|---|
| **S0** Owner decisions and guardrails | 1. Confirm no live mode is enabled (J-02/H-01 P0 condition). 2. Restore or explain the published site (L-04). 3. Branch protection with required review and CI (G-01, G-02); pin dependencies (A-03); CI green (A-19). 4. Freeze the evidence snapshots. 5. Decide on §7 | — | A test PR is blocked without human approval; CI green on `main` for 5 days; the served `data.json` equals the pushed one; snapshots hashed and stored | Owner action only. **Nothing below starts until S0 is done** |
| **S1** Evidence integrity and provenance | Append-only or anchored journal (A-10, I-05); provenance on every record: code, config, model, chain snapshot id (I-03, I-07, G-04); `seen_at` never overwritten (I-02); one clock (I-08, A-13); daily archive-completeness check (I-10); de-duplicated archive assets (L-05 data side) | S0 | A replay of a session reproduces its decisions from persisted evidence alone, **exact** on a fresh session (I-04); 100% of decisions matched to a snapshot; an edit to the journal is detected | Kotak/NSE inputs that are not persisted (news, brain, breadth) need a design decision on what to persist |
| **S2** Data-validity layer and rebuild | Quarantine non-positive or flat or stale series at ingest (I-01, F-02, A-04, A-16); fail closed on the model chain (F-01, H-08, I-09); per-bar provenance; **rebuild `memory.json` factor/vix and the IC from a quarantined record**, keeping the old one archived (D-03, L-06 data side) | S0, S1 (provenance), the N1 payload capture | **Synthetic:** fault injection, where a zero VIX is quarantined with WARN and the factor is absent. **Replay:** the 5 sessions re-run without substitution and without ZeroDivisionError. **Production:** 5 sessions, 0 zero-VIX bars recorded as valid, 0 "−100%" observations | N1 unresolved (payload); the owner decides whether the rebuild resets or re-grades |
| **S3** Crash, restart and order state | Idempotent exits and entries across a crash (H-01, H-02, I-06); overnight carry (H-03); persist safe mode and armed state across the hand-over (H-07, B-04); restart tests in CI (H-12); catch-up grading fixed (A-02) | S0 (A-03 pin), S1 | **Synthetic:** crash after each leg (k = 2, 4) ends flat or flagged, cash = one round trip; hand-over keeps safe mode. **Replay:** the 10-05 hand-over keeps the armed state. **Production:** 5 sessions, 0 "grading failed" | — |
| **S4** Decision-state propagation and UI truthfulness | One outcome record per trigger hit, shown in the UI (L-01, L-02, K-01, K-02, J-07, J-08); a decisions view; expiry-aware armed cards (L-03); a status model that is honest about halts, close, staleness and outage (J-03, K-03, K-04, K-06, J-11); VIX and learning display (J-01, J-05 surface); trade provenance badge (K-05 surface) | S1 (records), S2 (valid inputs), S3 (halts) | The `phase_l_consistency` harness on 5 sessions × 2 paths: **0** unshown outcomes, **0** "no setup has triggered" in a rejection minute; render tests at 09:16, 15:31 and 15:44; 503 and 404 wording; L-03 render at `expires` + 1 | Some UI wording depends on the S6 gate decision (what "armed" means if nothing can be authorized) |
| **S5** Observability, alerting, scheduling | Alert on CRITICAL and on soft-failed steps (H-04, D-07, G-05); post-publish served-content check (L-04 monitoring); the backup cron exits after the close (L-05); self-review dates fixed (H-05); an independent heartbeat watchdog | S0; S4 for the status model | **Synthetic:** a journal with one CRITICAL produces an alert; a late cron run uploads nothing. **Production:** 5 sessions with 0 unalerted CRITICAL or WARN-class failures and every publish verified | — |
| **S6** Deterministic end-to-end trade test, then the gate decision | Build R4: scan → arm → trigger → gates → fill → mark → exit → journal → learning in a synthetic session. Then the owner's **gate-architecture decision** (RC1: B-02, C-01, C-05, A-01) | S3, S4 (the e2e test asserts UI state too) | The e2e test asserts every row, ID and P&L; the decision is written; the e2e passes under the chosen design | **Owner decision.** The research says direction is unpredictable (N1 of post-G) |
| **S7** Statistical hygiene and learning claims | A placebo/CI gate before adoption (RC3: D-01, C-02, E-02, E-04); demotion (C-03, D-04); an IC degeneracy floor (L-06); relabel "learned" in the docs and UI (J-05, B-01) | S2 (clean record), S6 (what is adopted) | Null pass rate ≤ stated α (C-02, E-02); placebo p < α on a new sample or the claims withdrawn (D-01); `ic_table` excludes constant regressors | New data needed (a fresh sample) |
| **S8** Execution realism and economics | Depth-capped fills, one cost source, dated STT (F-04, C-04); settlement on the official close (E-01, F-05); `expiry_eve_entry_v1` decided (E-07); skew bias (F-03); modelled-quote labelling in records (K-05 data side) | S2, S6 | Re-derived sleeve trades equal the official-close values (as post-G R3); recorded quotes for every held-out instrument | Forward sample size per spec |
| **S9** Live-readiness controls | The order and partial-fill state machine on a fake broker (F-06, A-17); exchange timestamps; broker-side limits; a tested kill switch on the actual runtime (H-06) | S0–S8 | Fake-broker tests for fill, partial, cancel, reject, timeout and unwind | **The owner alone authorizes live trading. This audit does not** |

### Four readiness decisions (independent; passing one implies nothing about the others)

| Gate | Must demonstrate | Stages | Current state |
|---|---|---|---|
| **G1 Paper-system correctness and recovery** | Valid, fresh, sourced data; decisions traceable and **visible**; crash/restart safe; halts honest and alerted; replay reproduces decisions; the site serves what the desk did | S0–S6 | **Not met.** I-01 BROKEN; H-01 latent P1; L-01 (0 of 82 outcomes visible across replay and production); L-04 (site down) |
| **G2 Statistical strategy evidence** | Pre-registered held-out results, forward n per spec, power-adequate gates, learning separated from noise | S7 (+ S1, S2) | **Not met.** D-01 P1 (factor learning ≈ noise); E-02; the VIX record is contaminated |
| **G3 Executable trade economics and fill realism** | Depth-capped fills, real quotes for every traded instrument, correct settlement, current costs | S8 (+ S2) | **Not met.** E-01 P1; F-04; 0 production trades, so there is nothing to calibrate |
| **G4 Authorization for any live trading** | G1–G3, plus S9, plus governance (G-01), plus owner sign-off | S9 | **Not met and not authorized.** No recommendation to enable live trading is made |

---

## 10. Unresolved questions

| # | Question | What would settle it | Who |
|---|---|---|---|
| U-L1 | What does Kotak's candle endpoint return for `nse_cm\|INDIA VIX`? (I-01 root cause, N1) | One raw response captured during a session | Owner (credentials) |
| U-L2 | Why did GitHub Pages stop deploying after 10-08 10:46Z, and when did the 404 begin? Was anything served on 10-09? (L-04) | Settings → Pages; Pages deployment history; Cloudflare Worker logs | Owner |
| U-L3 | CDN/edge latency after deployment (K-03) | Timed fetches of the served `data.json` against its heartbeat during a session | Owner, or a monitored probe |
| U-L4 | How did the ₹20k account's trades, thoughts and events disappear before 10-05 08:31 while news rows from 09-29 survived? (Q-05) | Workflow logs from 10-02 … 10-04 for jobs that write `journal.db` (restate, learn, autolearn, live); any archive copy | Owner (logs older than this audit's reads) |
| U-L5 | What would production have decided without the VIX vote? | Not replayable: news, brain, breadth and learner inputs are not persisted (I-04). Only the replay sensitivity is known | — (S1 makes it answerable going forward) |
| U-L6 | How often did production screens show "waiting at the level" with nothing armed? (N2) | A persisted heartbeat history, or S4's outcome records | S1/S4 |
| U-L7 | Did the post-close backup runs change the journal on 10-05 … 10-08? (L-05) | Journal snapshots before and after each late run (not retained: force-push) | Not recoverable; monitor going forward |
| U-L8 | Did any viewer act on an expired armed card? (N3) | No viewer telemetry | — |
| U-L9 | Is the 3.9% IV gap on two-sided deep-ITM quotes decision-relevant anywhere outside ATM analytics? | A targeted check of chain-analytics consumers (Phase F scope) | S2 |
| U-L10 | Do the H–K evidence-class labels in the consolidated JSON hold under review? (keyword-derived) | Owner/reviewer pass over `evidence_class` for H–K | Owner |
| U-L11 | Do the template acceptance splits (109 findings) fit each finding? | Per-finding refinement before stage entry | Owner, per stage |
| U-L12 | `restate.yml` uses concurrency group `journal-admin`, not `live-desk`; its "waits for any running desk" lives in code. Is it race-free against the live and autolearn writers? | Code review plus a synthetic race test | S1 |

Carried from earlier phases and still open: Q-12 (model-chain fallback rate; 0 of 743 observed), A-11 (Kotak payload
never inspected), H's runner-loss outcome [infer], and Phase I's 50 decisions matching no snapshot.

---

## 11. Artifacts (local, uncommitted)

### Probes and generators (`audit/probes/`)

| Script | What it does |
|---|---|
| `phase_l_consistency.py` | Every-minute instrumented replay; bar and tick paths; Python port of `readAction` / `renderNow` |
| `phase_l_consistency_analyze.py` | Contradiction counts with denominators |
| `phase_l_ui_port_check.py` | The port against the Phase K Chromium renders |
| `phase_l_prod_consistency.py` | Production lower bounds |
| `phase_l_blocked_silent.py` | Synthetic halt fixture |
| `phase_l_vix_learning.py` | Multiplier reconciliation |
| `phase_l_vix_counterfactual.py` | Decision-stream sensitivity to the VIX vote |
| `phase_l_series_scan.py` | Invalid-series scan |
| `phase_l_pages_latency.py` | Pages deployment record |
| `phase_l_consolidate.py` | Builds the consolidated register |
| `test_phase_l_probes.py` | **21 probes, all passing.** Phase K's 10 probes re-run green |

### Raw outputs (`audit/data/`)

| File | Contents |
|---|---|
| `phase_l_consistency_raw/` | 10 gzipped per-session, per-path minute logs |
| `phase_l_consistency_summary.json` | Contradiction summary |
| `phase_l_prod_consistency.json` | Production lower bounds |
| `phase_l_ui_port_check.json` | UI port validation |
| `phase_l_blocked_silent.json` | Halt fixture result |
| `phase_l_vix_learning.json` | VIX multiplier reconciliation |
| `phase_l_vix_ic.json` | VIX IC ranking |
| `phase_l_vix_counterfactual_2026-10-05.json`, `_2026-10-08_subst.json` | VIX-vote counterfactuals |
| `phase_l_series_scan.json` | Invalid-series scan |
| `phase_l_scheduler_runs.json` | Scheduler run metadata |
| `phase_l_release_assets.json` | Release asset listing |
| `phase_l_pages_latency.json` | Pages deployment record |
| `phase_l_pages_get_20261009T1835Z.txt` | The 404 response headers |
| `phase_l_published_armed.json` | Published armed-card evidence |
| `phase_l_consolidated_findings.json` | The proposed A–L register |
| `phase_l_probe_run.txt` | Raw probe output |
| `phase_l_screens/` | Tick-path Chromium render |

### Reproduce

```
S=<scratch>                          # journal_0143/ (CLOSE snapshot, holds intraday/), chains_dl/ (10 chain parquets)
python audit/probes/phase_l_consistency.py $S/journal_0143 $S/chains_dl 2026-10-05 bar  out_1005_bar.json
python audit/probes/phase_l_consistency.py $S/journal_0143 $S/chains_dl 2026-10-08 tick out_1008_tick.json --drop-zero-prior-vix
python audit/probes/phase_l_consistency_analyze.py summary.json out_*.json
QD_JOURNAL=$S/journal_0143 QD_CHAINS=$S/chains_dl python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_l_probes.py
```

### Boundaries kept

- No change to production code, UI, config, workflows, schedules, permissions, branch protection, account state or
  running sessions.
- No broker credentials; no orders.
- Network reads only: GitHub API listings, the public `chains-2026` release asset, and four GETs of the public Pages URL.
- The canonical register and earlier reports are unchanged (hash checked).
- No commit, push or merge.
- No live trading authorized.
- No further autonomous phase launched.

**Phase L ends here, for owner review.**
