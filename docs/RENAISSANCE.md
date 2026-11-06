# The Renaissance: rebuilding the desk

The plan the rebuild follows, in order. A phase starts only when the one before it has met its exit criteria. A
change is merged only when it has passed the gate in section 2. Nothing here is skipped to save time.

**The goal.** Catch the large option moves, 2x to 6x within a session, that happen a few times a month, without
predicting direction. Every pre-registered direction test failed. What the evidence supports:

* volatility is forecastable (HAR, 8 of 8 locked cells);
* the expiry-eve premium replicates;
* option spikes cluster on expiry days and on results days, and they show up in the minutes after a move starts:
  OI unwinding, volume, IV lift, gamma walls breaking.

The desk is rebuilt on those facts.

## 1. Invariants: true at every commit, in every phase

1. **No real money.** Real money is only ever the owner's separate, written decision, after phase 6 and outside this
   plan.
2. **No secret** in the repository, in a log or in chat. Never ask for or accept a password or TOTP.
3. **Licensed or third-party data** (Kite ticks, vendor datasets) is never committed or published. Kite data leaves a
   runner only encrypted.
4. **Pre-registered specs and results** in `docs/prereg/` are never edited after a result exists. A new idea gets a
   new spec.
5. **Nothing is deleted irreversibly.** Before any removal, pre-change `main` goes to an `archive/` branch. Releases,
   the journal branch and recorded data are never deleted, and history is never rewritten.
6. **`docs/AUTONOMY.md` is the owner's rulebook.** On 6 Nov 2026 the owner lifted the old "never edit it" rule ("Give
   yourself the permission to edit the autonomy", then "no PR is required. You do it whatever you feel right."). The
   builder may edit it on its own judgment, but every edit's commit quotes the owner's words and says what changed and
   why, the owner is told after each edit, enabling real money still needs the owner's separate, explicit decision, and
   if branch protection refuses a direct edit the builder asks the owner and never works around it.
7. **No limit, gate or threshold is loosened** without the owner's written authorisation, quoted in the PR.
8. **The recorders never stop** because of a code change. A change that touches recording proves it on real market
   data before merge.

## 2. The gate: how every change gets in

| Step | What | Who |
|---|---|---|
| 1. Scope | One PR, one purpose, stated in its first line. Research and code that trades never share a PR. | builder |
| 2. Spec first | Anything that will produce a result (a study, a model, a rule) has its pre-registration merged **before** the code that reads the data: question, data, splits, metric, pass and kill thresholds, controls. | builder + research reviewer |
| 3. Build | Code, plus tests that fail without the change (mutation-checked for anything safety-relevant). | builder |
| 4. Prove | Repo fast checks, the full suite, `deploy/check_workflows.py`. Recorder changes: a live-market run. Data changes: a completeness and audit report. | builder |
| 5. Review | Independent review of the **exact head**. Research reviewer for claims, statistics and specs; risk reviewer for workflows, permissions, credentials, sizing, limits, anything that could place or size a trade. A NOT CLEAR blocks. A push after a review means a new review. | reviewers |
| 6. CI | `tests`, `doctor` and `Learnbot guard` green on the exact head. Cloudflare Workers Builds is ignored (owner's rule). | CI |
| 7. Merge | Squash, pinned to the reviewed sha, **one PR at a time**. The next PR is brought up to date and re-checked before it merges. | builder |
| 8. Watch | After merge: the first scheduled run of anything the PR touched is checked. A failure is fixed or reverted the same day. | builder |

The owner merges anything that changes authority, money or the plan itself. The builder may merge the rest once steps
1 to 7 are complete.

## 3. The phases

### Phase 0: clear the ground (now)

* #196: retire the paper desk, keep every recorder (`record.yml` replaces `live.yml`); about 35k lines out.
* #175: the pre-market brief (both reviews CLEAR; risk re-review of the last head pending).
* #163 (the owner's AUTONOMY.md), then #165 (Kite data authority to 31 Dec 2027).
* CI under 15 minutes. The suite went from ~40 to 10 minutes with the cleanup; add parallel runs if it grows.
* Close the stale PRs: #9, #67, #72, #74, #79, #136, #156, #159, #161.

**Exit:** `main` holds only recorders, research, ML, the brief and the app. The recorder ran a full session from
`main` and archived it. CI is green in under 15 minutes.

### Phase 1: data you can trust

* **Daily completeness report** for the recorder and the tape: minutes recorded, chains per minute, gaps. It goes in
  the run summary, and the watchdog alerts on a bad day.
* **NSE board-meeting backfill** (2019 onward) into the warehouse, so results history is real, not inferred.
* **A data audit** of the chains, tape, option minutes and stock minutes: duplicates, frozen prints, OI faults,
  timestamp drift. Faulty data is quarantined, never silently used.
* **The Kite token routine** made reliable, so the daily login is never forgotten.
* **The owner's decision** on buying historical minute option data (cost and licence).

**Exit:** 10 consecutive sessions recorded at ≥98% completeness, the backfill merged, and the audit report clean or
its faults quarantined.

### Phase 2: the volatility engine, live

* HAR (C), the seasonal baseline (B) and the old forecaster (A) forecast every morning. They are graded every evening
  on QLIKE against what happened.
* Champion and challenger, with promotion and demotion rules pre-registered.
* Its output is the expected move per index and per stock, for each session and each event: the ruler every later
  phase measures surprises against.

**Exit:** the pre-registered grading has run 20 sessions, and the champion is named by its rule, not by choice.

### Phase 3: the spike dataset

* **Pre-register the label:** an option reaches ≥2x (and ≥3x) of its price at a decision minute, before the close.
  Point-in-time liquidity; no open prints.
* **Features**, computed only from data available at that minute:
  * the move so far against the expected move;
  * the speed of the move;
  * option volume surge;
  * OI change and unwinding;
  * gamma walls crossed;
  * the IV change;
  * time of day and time to expiry;
  * the brief's flags (results, events).
* **A leakage test:** every feature is recomputed with all future bars changed, and must not move.

**Exit:** the builder and its tests are merged, and the dataset is reproducible from the recorded data by hash.

### Phase 4: the spike detector

1. A rules baseline first: simple, explainable thresholds.
2. Then an ML challenger (gradient boosting).
3. Both are fixed on development sessions only. They are judged on locked later sessions against two controls:
   **random entries** and **expiry-day lottery tickets**.
4. Pass condition, set in the spec: after costs, the expected value of the detector's entries beats both controls,
   with a lower confidence bound above zero, on the locked sessions.
5. Kill condition, also set in the spec: if it fails, nothing trades, the finding is recorded, and the next idea gets
   a new spec.

**Exit:** a pre-registered PASS. A FAIL ends phase 4 honestly and returns to phase 3 with a new spec.

### Phase 5: shadow live

* The passing detector runs live on the recorder's data. Every signal is journaled with its written thesis (the
  signals, the probability, why now), and nothing is traded.
* Graded forward against the same controls, for at least 40 sessions or 30 signals, whichever is later.

**Exit:** the forward record stays inside the backtest's range, judged by the rule written before phase 5 starts.

### Phase 6: paper trading

* **Fixed risk per shot:** at most 1% of paper equity.
* **A daily cap on shots and on loss.**
* **Exits:** losers cut at a fixed stop or after a fixed time without follow-through; winners partly taken at 2x and
  3x, the rest trailed.
* **Every trade carries its thesis.** A daily review compares each trade with its thesis.
* **The kill switch and the drawdown halt** come back first, before any entry code, with their own tests and risk
  review.

**Exit:** the owner decides. Nothing in this plan goes past paper.

### Phase 7: breadth

The same pipeline for F&O stocks, starting with the most liquid. Each new instrument family repeats phases 3 to 5 on
its own data before it trades.

## 4. Fault prevention, built in

* **Every phase's work is behind the gate.** No direct pushes to `main`.
* **Rollback is always one step:** revert the squash commit. Every removal has an archive branch.
* **The watchdog** checks that each scheduled job ran and that its data is complete. P1 alerts reach the owner's
  phone.
* **Incidents:** a failure gets a same-day fix or revert, and a short note in `remediation/` with the cause and the
  test that now catches it.
* **One owner decision at a time,** asked plainly, with a recommendation. Nothing waits on an unasked question.

## 5. The scoreboard (the app's Today tab and the weekly digest)

* Recorder completeness, by day.
* The volatility engine: QLIKE per model, and the champion.
* Spikes in the market this week, and how many the detector flagged (shadow or paper).
* The detector's hit rate against the random-entry and expiry-lottery controls.
* Paper P&L, with the share coming from the best three trades shown alongside.

## 6. Decisions the owner holds

1. Whether to buy historical minute option data, and from whom.
2. The merge of #163 and of anything that changes authority or the plan.
3. The start of phase 6 (paper trading) and, outside this plan, anything to do with real money.

## 7. The owner's direction of 6 Nov 2026: a 24/7 paper desk across every market except crypto

In the owner's words: "I want this trading desk to run 24/7 and take trades in the whole FNO universe, whether it is crude oil,
whether it is gold, whether it is forex, whether it is of any security, so that it can trade without any issue except crypto ...
take hundreds or whatever, the trade it want to take ... there is no cap on that. They say there is only a loss cap." On
strategies: "do not keep ... these are the strategies which I need to work with ... you have the whole strategies universe with
you. Use permutation, combination". And: "no money is involved in this right now. When money is involved, then I'll come into
picture." Later the same day: "Make this app to run 24/7."

What this changes in the plan: paper trading no longer waits for the spike detector (it replaces the line "the desk stays stopped
until the spike detector passes"), and the desk covers MCX commodities and NSE currency derivatives as well as NSE/BSE F&O.
What it does not change: paper only; real money needs the owner's separate yes; no secret in the repository; the gate in
section 2 applies to every piece below.

How "24/7" is meant. No market except crypto trades at the weekend, and none trades round the clock: NSE/BSE F&O 09:15-15:30,
NSE currency 09:00-17:00, MCX 09:00-23:30 (23:55 while US daylight saving time is in force), IST, Monday to Friday. So the desk
is always on and trades whenever any of them is open, about 09:00 to 23:30 on a trading day. A hosted job may run six hours, so a
day is split into chained jobs (the owner chose chained GitHub jobs over a server).

Order of work, each its own PR through the gate, safety first:
1. **M1, the market map** (`quantdesk/markets`): hours, the MCX close, calendars, and the job plan. Pure logic. Trading counts a
   segment as open only where its holiday calendar is verified; recording does not wait for that.
2. **M2, risk before entries**: the only caps are loss caps (a daily loss limit, the multi-day drawdown halt) and a kill switch;
   there is no cap on the number of trades or open positions. The paper broker and ledger, with costs for each segment from the
   broker's published schedule. Independent risk review.
3. **M3, the runner**: the chained jobs, saving and restoring state between them, the watchdog.
4. **M4, data** for MCX and currency (Kite and Kotak), with real costs.
5. **M5, the strategy factory**: strategies are built from combinations of signals, filters, entries, exits and sizes, and survive
   only a funnel built to stop luck (costs, multiple-testing control, random-entry controls, a locked holdout, then paper). Every
   trade carries its written thesis.
6. **M6, live on paper**: the first full day watched end to end.
