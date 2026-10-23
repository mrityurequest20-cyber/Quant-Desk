# The desk master plan: the one plan we follow

Written 23 Oct 2026 at the owner's request: a single plan for making the desk institutional-grade (live execution, strategy
building, everything), with no historical data being bought, that the owner and the agents follow and nothing else.

This file is the single plan. It consolidates and sequences the earlier documents; it does not replace their detail:
[MASTER_PLAN_JUNE_2027.md](MASTER_PLAN_JUNE_2027.md) (definition of done), [ROADMAP_AUG_2027.md](ROADMAP_AUG_2027.md)
(milestones, owner-absent charter), [ML_ROADMAP.md](ML_ROADMAP.md) (models), [RELEASE_GATES.md](RELEASE_GATES.md) (the paper bar
before real money), [RECOVERY.md](RECOVERY.md) (runbook), [ARCHITECTURE.md](ARCHITECTURE.md), and the S0 to S9 stage sheet and
G1 to G4 gates of the forensic audit (`audit/QUANTDESK_PHASE_L_FINAL_AUDIT.md` sections 8 and 9, on the audit branch).
**Where they disagree with this file on order or dates, this file wins; section 10 lists every adjustment.** The hard limits in
[AUTONOMY.md](AUTONOMY.md) outrank this file and everything else: live trading off, ceilings tighten-only, halts and real money
the owner's alone, no secrets printed, no editing locked results.

How to read it: **VERIFIED** means checked in the repository or in a primary document on the date above. **TO VERIFY** means a
dependency this plan relies on that nobody has checked yet; each one has an owner and a date in section 12.

---

## 0. The rules of this plan

1. **One plan.** Work enters the queue only if it (a) protects or produces evidence, (b) is an item of the current phase in
   section 9, (c) is a research-queue item (section 5), or (d) the owner asks for it. Everything else goes to the parking lot
   (section 11). No new infrastructure outside the current phase.
2. **Evidence is calendar time.** Forward sessions, tape days and settled trades cannot be hurried and cannot be recovered. The
   first duty of the desk is that every session runs and is recorded (phase P0), because history is not being bought.
3. **Honest framing.** Institutional means institutional *process and controls*. It does not mean alpha, latency, or data depth the
   desk cannot get from free sources and one operator (section 1). The plan never promises profit; gates decide.
4. **Proportional review.** Review depth follows blast radius. Anything touching orders, brokers, credentials, risk limits,
   sizing, registered specs or results, or workflow permissions: full independent review, risk-compliance holds a veto, a CLEAR
   quoted on the exact head. Tooling that cannot touch trading: one independent review, at most two rounds, then ship with the
   remaining LOW findings listed in the pull request. (Learning-bot lesson: seven rounds on a tool that opens draft PRs was
   more than it was worth.)
5. **Live trading is built toward and never switched on by the plan.** Section 6 builds everything an institutional execution
   stack has so that the day the owner decides (G4) the system is ready. Nothing here flips `account.mode`, adds an order path, or
   raises a ceiling.
6. **Cut order if time slips:** (1) Tier 4 and Tier 3 trading, (2) stock-option paper trading, (3) M7 and M5 models, (4) sequence
   models. Never cut: data collection, the watchdog, the safety rails, the closed loop, the reports.

---

## 1. What "institutional" means for this desk, and what it cannot mean

An institutional desk is, in practice, ten capabilities. Honest status as of today:

| # | Pillar | Institutional standard | Where the desk is | Gap | Phase |
|---|---|---|---|---|---|
| 1 | **Operations and observability** | Every process scheduled, monitored, alerted; absence is detected | Cloudflare Worker is the alarm clock; GitHub cron has run 4.5 to 7 hours late; the only alert path is GitHub issues; nothing detects a session that did not start | Watchdog (section 3); runbooks; on-call is the owner | **P0** |
| 2 | **Data** | Owned, validated, lineage-tracked, point-in-time | Free sources (Kotak, Yahoo, NSE, BSE, news RSS); own minute tape since Oct 2026; bhavcopy 2019+; vendor index minutes to Feb 2023 (locked HAR study); no purchased history | Validity layer and quarantine (S2); provenance (S1); collection health per source | P1 |
| 3 | **Research integrity** | Pre-registration, multiple-testing control, independent validation | **Strong**: locked specs, method fingerprints, negative results kept, independent reviewers with veto, evidence ladder | A weekly research cadence that actually uses it (section 5) | P3 |
| 4 | **Execution and transaction-cost analysis** | Order state machine, pre-trade checks, reconciliation, TCA, best-execution record | Paper broker with modelled and real-quote fills; sleeves compare real fill cost with the model; the audit listed depth-capped fills, one cost source (S8) and an order state machine on a fake broker (S9) as open: statuses are re-triaged in P1 | Section 6 | P2 |
| 5 | **Risk** | Limits hierarchy, scenario stress, margin monitoring, kill switch drilled | Owner ceilings (per trade, per day, drawdown halt), tighten-only, halts owner-only; no multi-day drawdown halt in the intraday desk; no stress/scenario report; the audit listed the kill switch as not drilled on the real runtime (H-06; re-triaged in P1) | Section 7 | P2 and P5 |
| 6 | **Model lifecycle** | Registry, validation, champion/challenger, drift, demotion | HAR in shadow; autolearn registry exists; ML platform not built | [ML_ROADMAP.md](ML_ROADMAP.md) | P4 |
| 7 | **Controls and audit trail** | Change management, segregation of duties, append-only records | PR-only changes, required checks, independent reviewers; journal is not append-only or anchored (S1) | S1; reviewer rules already in force | P1 |
| 8 | **Security** | Least privilege, secret hygiene, rotation | Least-privilege workflows with pinned actions (checked by CI); **the repository is public** (VERIFIED): every spec, report and saved journal is world-readable; no rotation schedule | Owner decision on privacy; rotation calendar | P0 and P5 |
| 9 | **Continuity and recovery** | Backups, restore drills, RTO/RPO | [RECOVERY.md](RECOVERY.md) runbook; journal on a `journal` branch with integrity check on restore; chain snapshots as run artifacts (they expire) | A restore drill; confirm artifacts are archived for every session | P5 |
| 10 | **Reporting and governance** | Daily, weekly, monthly packs; a scoreboard | Weekly progress issue; weekly and monthly learning-bot reports (live from 23 Oct) | Daily digest; the scoreboard in section 8 | P0 and P5 |

**Not attainable with free data and one operator, and what we do instead**

| Institutional feature | Why not here | Substitute |
|---|---|---|
| Co-location, microsecond latency, tick-level book | Retail broker API, GitHub-hosted runners | Strategies that do not need speed: expiry-structure premium, volatility forecasting, minute-scale option selling; measure real fill cost instead of assuming it |
| Years of intraday option history | Not purchasing historical data | Forward tape (own), daily bhavcopy (free, deep), replay of own sessions; every claim is forward-tested and pre-registered |
| Capacity and market-impact modelling at size | Paper account of a few lakh rupees | State the capacity assumption in every spec; size stays tiny |
| Multi-venue smart order routing, prime brokerage | One retail broker | Not applicable |
| A guarantee of alpha | Nobody has one | Gates decide; a failed gate is a finished, useful result |

---

## 2. The chain: every link between "the market opens" and "a decision is on the record"

If any link breaks, a session is lost or its data is wrong. "Detected today" is what exists now; "Watchdog" is the check this
plan adds (section 3). Items marked TO VERIFY are in section 12.

| # | Link | How it fails | Detected today? | Watchdog check | Action / owner |
|---|---|---|---|---|---|
| 1 | **Trading calendar** (`calendar.holidays`, `holiday_years: [2026]`) | The 2027 list is not entered: from 1 Jan 2027 the desk treats NSE holidays as trading days (VERIFIED: only 2026 is complete) | Partly (a holiday-year guard exists) | W9 calendar | Enter the 2027 NSE list from the circular **by 15 Dec 2026** (owner or agent) |
| 2 | **Cloudflare Worker** (the alarm clock; 4 cron triggers; free plan allows 5) | Not deployed from `main`, trigger lost, plan limit, Cloudflare outage | **No** | W1, W2 | Owner confirms 4 triggers and last deploy (section 12) |
| 3 | **`GH_DISPATCH_TOKEN`** (Worker's key to start workflows) | Expires or is revoked: the Worker silently stops dispatching and the desk relies on GitHub's late cron | **No** | W7 expiry register | Owner records the expiry date; rotate 14 days before |
| 4 | **GitHub cron fallbacks** (`live.yml` 08:52 IST, `scheduler.yml` every 10 min, `collect-wide` 15:25/15:45 IST) | 4.5 to 7 hours late (VERIFIED in the audit and in `worker.js` comments) | Partly (scheduler logic) | W1 | Fallback only; Worker is primary |
| 5 | **GitHub Actions platform and runners** | Queue delay, outage, concurrency group `live-desk` blocking | **No** | W1, W9 | Public repo: standard-runner minutes are not a constraint (VERIFIED: `private: false`); TO VERIFY the account's Actions policy |
| 6 | **Session hand-off between jobs** (`live.yml` job limits 355 and 300 minutes; a session is 08:30 to 15:31) | A gap or duplicate at the hand-off; two desks on one journal | Partly (`tests/test_handover.py`) | W2 heartbeat gap | TO VERIFY behaviour in production over 5 sessions |
| 7 | **Kotak Neo session** (consumer key, token, TOTP) | Token or TOTP lapses: the desk silently falls back to Yahoo bars and NSE's public chain | Partly (`doctor` warns at start; `broker-check` is manual) | W2 reads the feed label | Owner: renewal procedure and expiry date (section 12) |
| 8 | **Yahoo** (via `yfinance`, unofficial) | Rate limit, format change, empty frames | Partly (readable error, stale-feed gate at 3 min, safe mode, square-off) | W2 | Keep as fallback only; never the sole source for a decision that matters |
| 9 | **NSE endpoints** (`nseindia.com`, `nsearchives`, chains, bhavcopy, index closes) | Anti-bot blocks on cloud IPs, cookie changes, UDiFF format change, HTML 200 pages | Partly (`NotPublishedHtml`, retries, data findings) | W3, W5 | Findings auto-filed; no second source for the chain beyond Kotak |
| 10 | **BSE / SENSEX** | No NSE row; Yahoo close only | By design, labelled | n/a | Documented in the v4 spec |
| 11 | **News feeds** (Google News RSS, Moneycontrol, ET, Mint, Business Standard; 2-minute cadence, 6 s deadline) | Feed dropped: breaking news invisible to the stand-aside gate | Partly (deadline clamp, per-feed errors) | W2 (news age) TO VERIFY field | Accept; the gate is conservative |
| 12 | **AI providers** (Anthropic for the teacher; Gemini, Ollama optional) | Key invalid, credit exhausted, usage limit | Yes in effect: the desk runs on its rules; WARN | W9 | Owner: billing alert; credit split is configured |
| 13 | **Journal persistence** (`deploy/journal.sh` to the `journal` branch; integrity check on restore; save replaces exactly the restored commit) | Save fails, branch race, corruption | Yes (refuses an empty start; integrity check) | W3 (save step) | [RECOVERY.md](RECOVERY.md); S1 makes it append-only |
| 14 | **Evidence storage** (option-minute releases; chain snapshots as run artifacts, which expire) | Artifact retention lapses before archiving; release limits | **No** | W5 archive check | TO VERIFY that `chain-archive` covers every session; sharded quarterly releases |
| 15 | **Published site and the Worker's proxy** | Pages stopped deploying and returned 404 on 9 Oct (VERIFIED in the audit); today's state unknown | Unknown | W2 fetches the published JSON | Owner: Settings, Pages, status |
| 16 | **Alert channel** | Only GitHub issues and the GitHub app; nothing for absence | Partly | The watchdog itself | Section 3 |
| 17 | **CI and branch protection** (required `tests`, `doctor`; add `Learnbot guard`) | A required check that never runs blocks merges; red `main` | Yes | n/a | Owner adds `Learnbot guard` (name confirmed on PR 94's own run) |
| 18 | **Claude routines** (weekly 09:47 and monthly 10:43 IST learning runs; PR babysitting) | Usage limit; a stored prompt that is stale; the monthly prompt still describes a conditional merge path | Partly | W8 weekly digest shows the last run | Owner deletes the conditional-merge clause from the monthly routine |
| 19 | **Secrets** (Kotak key; AI keys under many alias names; `CF_API_TOKEN` in `ai-check`; `GH_DISPATCH_TOKEN` on the Worker) | Leak, expiry, drift | CI checks permissions and pins only | W7 | Rotation calendar (section 12); never print |
| 20 | **Time** (IST versus UTC in every cron; Worker and GitHub crons are UTC) | An off-by-5.5-hours schedule | Tests for the Worker crons | W1 | Keep a table of every schedule in UTC and IST in the watchdog code |
| 21 | **The owner** (Kotak renewal, billing, decisions) | Unavailable | n/a | W8 digest, W7 reminders | The charter already assumes the owner is mostly absent: nothing here may need daily attention |
| 22 | **The watchdog itself** | The Worker or the alert service dies silently | n/a | W10 dead-man ping | Section 3 |

Schedules in force (VERIFIED from the workflows; UTC then IST): `live` 03:22 (08:52); `scheduler` every 10 min; Worker every 10
min 02:00 to 09:50 UTC weekdays, 09:55 (15:25) and 10:15 (15:45) for `collect-wide`, Sunday 12:00 (17:30); `autolearn` 10:40
(16:10); `selfreview` 11:40 (17:10); `org` 11:50 (17:20) Mon to Sat and 03:30 (09:00) Sunday; `data` 14:45 (20:15) weekdays and 02:40
(08:10) Monday to Saturday; `research` 04:17 (09:47) Saturday; `progress` 05:10 (10:40) Saturday.

---

## 3. The watchdog: alerts by push and by email

**Where it runs.** In the existing Cloudflare Worker (`deploy/cloudflare/worker.js`), on its existing cron firings (no new
trigger; the free plan allows five and four are used). It is the only component with a clock that does not depend on GitHub's cron.
It reads GitHub's public workflow-run list with the token it already has, and the published site's JSON through its existing
proxy. It sends alerts. It never starts a trade, touches a journal, or sees a secret other than its own.

**Checks.** Trading days only (the holiday list is copied into the Worker and a test fails if it differs from
`config/quantdesk.yaml`). All times IST.

| # | When | Check | Raises |
|---|---|---|---|
| W1 | 08:55, then every 10 min to 09:25 | A `Live paper desk` run exists for today and has started | P1 "desk not started" (the Worker also re-dispatches, as it does now) |
| W2 | 09:30, 11:00, 13:00, 15:00 | The run is still in progress; the published heartbeat is under 10 minutes old; the feed label (Kotak or Yahoo) and the halted flag | P1 stale heartbeat or halted; P2 "feed fell back to Yahoo". TO VERIFY that the published JSON carries `ts`, feed and halted |
| W3 | 15:50 | Live run completed successfully; sleeves step succeeded; journal save succeeded; `collect-wide` stocks (15:25) and minutes (15:45) runs exist and succeeded | P1 any missing or failed |
| W4 | 16:45 | Learning cycle (16:10) succeeded | P2 |
| W5 | 17:45 and 21:00 | Self-review (17:10), Org (17:20), Data warehouse (20:15) ran; archive covered today's chains | P2; P1 if the archive is missing |
| W6 | any time | Any watched workflow concluded failed or cancelled today (known-noise list excluded) | P1 or P2 with the run link |
| W7 | 07:30 daily | Credential expiry register (dates held as a Worker variable): within 14 days P2, 7 days P1, 2 days P1 again | |
| W8 | Saturday 12:00 | Weekly digest: sessions ran of expected, alerts sent, last learning-bot run, counted HAR sessions of 60, forward trades per sleeve | digest |
| W9 | 15 Dec and 15 Jun | Calendar check: next year's holiday list entered | P2 |
| W10 | every OK cycle | Optional ping to an external dead-man's-switch URL the owner supplies; if the Worker dies, that service alerts | |

**Severity, de-duplication, content.** P1 means a session or its data is at risk now: push at high priority and email. P2 means
look today: push at default priority, email in the digest. One alert per (check, day); one escalation after 30 minutes if
unresolved; one "resolved" message. Messages carry the check, the workflow, the time and a link. **They never carry a key, a
journal value or a position.**

**Channels, with what was verified against the primary documentation on 23 Oct 2026.**

*Push: ntfy.sh* (free, no account). VERIFIED from docs.ntfy.sh: publish with an HTTP POST to `ntfy.sh/<topic>`; headers `X-Title`,
`X-Priority` (1 to 5), `X-Tags`, `X-Click`; limits 60 requests burst then one per 5 seconds, 4,096 bytes a message, **250 messages a
day** on ntfy.sh; "the topic is essentially a password" (anyone who knows it can read and publish), so use 24 or more random
characters and keep it as a Worker secret, never in the repository. Open risk: the limiter is per visitor (IP), and Cloudflare
Workers share egress addresses, so an anonymous publisher might be throttled by neighbours; the fallback is a free ntfy account
with an access token, or self-hosting.

*Email: NOT ntfy.* VERIFIED: on ntfy.sh **anonymous email sending is disabled** (abuse); it needs a verified account and the free tier
allows 5 emails a day. So the "push and email from one free service with no accounts" idea does not hold. Options, in order:

1. **Worker dispatches a small `watchdog-alert.yml` workflow that opens or comments on a `desk:ops` issue as the Actions bot.**
   GitHub then emails the owner and pushes to the GitHub mobile app, with no new service or secret (the Worker already holds a
   dispatch token). It matters that the **bot** opens the issue: GitHub does not notify you of your own actions, so an issue
   created with the owner's personal token would send nothing. TO VERIFY with a five-minute test at build time. Weakness: if GitHub
   Actions itself is down, this path is down; ntfy push still arrives.
2. A verified ntfy account sending P1 alerts by email (5 a day is enough for P1).
3. A transactional email service with its own free tier (needs an account and an API key; specifics not verified).

Recommended default: ntfy push + option 1 for email. Optional hardening: the dead-man's-switch (W10).

**Build and review.** One pull request: worker code, the new workflow (`issues: write`, `contents: read`, pinned actions), tests
(pure functions for each check; a test that the holiday list matches the config; a test that no message contains a secret-shaped
string), a runbook paragraph. Touches a workflow and a token-holding Worker, so risk-compliance reviews it. **Owner steps** (section
12): install the ntfy app and pick the topic; `wrangler secret put` the topic and the expiry dates; optionally create the
dead-man's-switch.

**Limits, stated now.** The watchdog watches GitHub and the published site, not the market feed's correctness. It cannot detect a
wrong number, only a missing or stale one. If both ntfy and GitHub are down at once, no alert is delivered: the dead-man's-switch
is what covers that.

---

## 4. Data: what we collect, own and trust (no purchased history)

| Source | What it gives | Depth | Collected by | Trust controls |
|---|---|---|---|---|
| Kotak Neo | Live index and option quotes, chains, option-minute backfill | Days (backfill), forward tape since Oct 2026 | `live`, `kotak-backfill` | Token renewal; feed label; doctor |
| Yahoo (`yfinance`) | 1-minute bars (fallback), daily | Weeks of minutes | `live` | Stale gate; never sole source |
| NSE | Public chain, bhavcopy (daily F&O, UDiFF), index closes, indices | Bhavcopy 2019+ | `data`, `daily-history`, `collect-wide` | HTML-200 detection, retries, findings |
| BSE | SENSEX closes | Daily | via Yahoo | Labelled by design |
| Vendor minutes (already held) | Index minutes to Feb 2023 | 2007 to Feb 2023 | locked HAR study | Self-reported digests (disclosed) |
| Stock minutes and chains | Top F&O stocks | From Oct 2026 | `collect-wide`, `kotak-backfill` | Quarterly shards; health check |
| News RSS | Headlines for the stand-aside gate | Live only | `live` | Deadline clamp |
| Teacher lessons | Advisory text | Nightly | `live` (post-close) | Advisory only; never gates a trade |

**Data rules.** Add, never delete. Every record carries source and time (S1). A series that fails validity (non-positive, flat,
stale) is quarantined, never silently used (S2; the India VIX zero-bar incident is the standing example). Raw payloads for new
fields are captured once (the Kotak INDIA VIX candle is still uncaptured: owner action in section 12). Depth (best five bids and
asks) is the cheapest large upgrade to execution realism: TO VERIFY whether Kotak's feed provides it and whether we record it.

---

## 5. Strategy factory: how strategies are built, tested and promoted

**Pipeline (every strategy, no exceptions).**

1. **Idea** enters the research queue. Source: the memory's ranked proposals (`python -m quantdesk experiments`), the weekly
   inventory, a teacher hypothesis, or the owner.
2. **Pre-registration:** a committed spec before any code or result: question, data, statistic, decision rule, what would count as
   failing, number of variants tried, capacity assumption, cost assumption (2x stress), and the overlap with existing sleeves.
   `experiments --check` refuses a repeat by method fingerprint.
3. **Offline study** on free deep data (bhavcopy; held-out instruments; regimes split; multiple-testing correction; costs doubled
   and tripled). Result recorded, locked, negative results kept.
4. **Replay** on our own recorded tape where the strategy needs intraday structure.
5. **Forward paper sleeve** (its own spec and ledger), real quotes only for fills (the paper gate counts only trades filled at
   the live book on both legs).
6. **Gate** ([RELEASE_GATES.md](RELEASE_GATES.md)): at least 60 sessions and 30 closed trades, positive net P&L, profit factor at
   least 1.15 after costs, drawdown at most 10%, no failed risk/limit/kill-switch/reconciliation check. Pass means PAPER CANDIDATE,
   nothing more.
7. **Paper allocation** under the allocator and ceilings (tighten-only).
8. **Live eligibility** is the owner's alone (G4). A strategy reaches it only after sections 6 and 7 are built and drilled.

**Throughput rule.** At most three pre-registrations open at once; one new idea started a week; a monthly review closes, rejects
or promotes. Each closed idea writes one paragraph of what it taught. The learning bot drafts, the research-reviewer reviews, the
owner or an engineer session merges.

**First queue (from the memory, not invented).** (1) L1 current-regime caveat: +4.92 bps a week at t about 1.4 over 98 weeks since
Nov 2024, mostly composition. (2) L2 thin cost margin: break-even at 6.6x modelled costs (4.1x since Nov 2024); the cost gap is
measured by the sleeves. (3) L1 entries are bhavcopy closes, not executable quotes: `expiry_eve_entry_v1` decides this at 40 eves.
Candidate families to *evaluate* (each needs its own spec; none is promised): expiry-day structure variants with defined risk;
volatility-forecast-conditioned selling and buying (HAR first, then M1); calendar/overnight carry in shadow; stock-option
structures once stock minutes and chains have months of tape. Order: whichever the data can test soonest.

**Portfolio construction.** A registered allocator (BACKLOG item 9) sizes sleeves by earn-in eligibility; correlation between
sleeves is measured before capital is shared (v4 is a re-settlement of v1 to v3, not an independent sleeve, and is counted that
way in the research memory); a sleeve that fails its retirement rule is retired automatically.

---

### 5a. The strategy builder, end to end (what we are building toward)

The goal is a **strategy builder**: you describe an idea in plain words, and the desk turns it into a tested, paper-traded,
reported strategy, with no step skipped and no way to fool ourselves. It is a *pipeline with templates and checks*, not an AI that
invents profit. The AI's job is to propose, draft and test inside the same rules a human researcher would follow.

| Step | What it does | Who does it | Exists today? | Built in |
|---|---|---|---|---|
| **SB1 Idea card** | One short structured note: the idea, why it might work, what would prove it wrong | You, the learning bot, or a teacher lesson | The memory's proposals and teacher hypotheses exist; no common card | Nov (template) |
| **SB2 Spec drafter** | Turns a card into a pre-registration draft (question, data, statistic, decision rule, costs at 2x, capacity, variants) and checks it is not a repeat | An agent drafts; the research-reviewer approves | `experiments --check` and the spec format exist; a `strategy` command group that drafts one does not | Dec (v1) |
| **SB3 Study runner** | Runs the registered study on bhavcopy or our own tape in the `Study` workflow and locks the result | Automatic | `Study` workflow and locked results exist; not generic | Jan |
| **SB4 Sleeve generator** | Turns an approved spec into a forward paper sleeve with its own ledger, no bespoke code | Automatic | Sleeves exist for the expiry option-selling family only | Feb |
| **SB5 Gate evaluator** | Computes the paper gate ([RELEASE_GATES.md](RELEASE_GATES.md)) and the retirement rule per sleeve, weekly | Automatic | The gate command exists for one strategy at a time | Mar |
| **SB6 Allocator** | Sizes sleeves by earn-in eligibility, under the owner's ceilings | Automatic | Specified (BACKLOG 9), partly built | Apr |
| **SB7 Strategy report** | One page per strategy: idea, spec, study, forward record, costs, verdict, what it taught | Automatic, learning bot summarises | Reports exist ad hoc | Apr |

**What "self-improving" means here, exactly.** The loop (trade, nightly teacher, weekly learning bot, monthly review, retrain,
shadow, demote) gets *better at finding out what works and at dropping what does not*. It can propose ideas, draft specs, run
studies, retrain models, and demote a model that degrades without asking. It **cannot** raise an exposure, loosen a gate, flip an
apply mode, merge to `main` on its own authority, clear a halt, or switch live trading on: those stay yours. It does not promise
profit. A strategy that fails its gate is a finished, useful result.

---

## 6. Execution and live-readiness: the institutional stack, built paper-first

Everything below is built and tested on a fake broker and in paper. **None of it sends a live order.** The owner alone authorises
live (G4). This is audit stage S9 plus the pieces an institution would expect.

| Component | Institutional standard | Now | Build |
|---|---|---|---|
| **Order state machine** | new, pending, partial, filled, cancelled, rejected, unknown; idempotent client order IDs; every transition journaled | Paper broker; fills simulated | Fake-broker tests for fill, partial, cancel, reject, timeout, unwind (S9, A-17, F-06) |
| **Pre-trade checks** | Fat-finger, price band, max notional, duplicate order, order-rate limit, margin | Sizing and ceilings enforced outside any model's reach | Add price-band, duplicate and rate checks; property tests that no path exceeds a ceiling |
| **Reconciliation** | Start-of-day, intraday and end-of-day position and cash match against the broker | Paper reconcile health exists | A broker-position comparison on the dry run (below) |
| **Kill switch and halts** | One action stops everything; drilled | KILL file, halts owner-only; the audit's H-06 (a tested kill switch on the real runtime) to be re-triaged | Drill on the real runtime; record the drill |
| **Broker resilience** | Session refresh, reconnect, backoff, rate-limit handling | Kotak token is manual | Documented renewal; alert on lapse (W7) |
| **Market-data integrity** | One clock, staleness gates, exchange timestamps, validity layer | 3-minute stale gate; clock issues in the audit | S1 and S2 |
| **Smart execution** | Limit orders with a cap on chase; avoid market orders in thin wings; slice | Spread flags (wide above 25%) in sleeves | Depth-capped fills (S8); a quote-quality rule per leg |
| **TCA** | Implementation shortfall against arrival price; model error tracked | Sleeves record real versus modelled cost per leg | Generalise to every fill; monthly TCA table; recalibrate the cost model (ML M8) |
| **Best-execution record** | Immutable order and fill log with venue IDs | Journal rows | Append-only or anchored journal (S1) |
| **Post-trade** | P&L attribution; fees and STT reconciled to contract notes | Dated STT and fee model | Monthly reconciliation of modelled fees to the broker's statement once real fills exist |
| **Live dry run** | Build the exact broker order, validate it, never send it | None | A mode that constructs real order payloads, checks them against the broker's margin or validation call where one exists, and compares the would-be fill with the paper fill. TO VERIFY what Kotak's API offers |
| **Paper-to-live ladder** | Staged exposure with hard caps | n/a | **A proposal for the owner's G4 decision only:** dry run for 20 sessions, then the smallest defined-risk structure for a fixed number of sessions with a daily loss cap far below the paper ceilings, then step up only on the written gate. Not authorised by this plan |

**Live-eligibility checklist (all required; owner signs).** G1 to G3 met; S9 tests pass; this plan's section 7 drills done; the
[RELEASE_GATES.md](RELEASE_GATES.md) paper gate passed for each strategy to be traded; 90 clean paper sessions; broker-side limits
set; kill switch drilled in the last 30 days; the owner's written decision.

---

## 7. Risk framework

| Layer | Content | Status |
|---|---|---|
| **Ceilings** (owner's) | Risk per trade, trades a day, open trades, daily loss, outlay, drawdown halt; tighten-only; outside every model's reach | In force. The older daily engine (dormant: no workflow runs it) is being tightened so confidence cannot size above its per-trade limit (separate PR) |
| **Multi-day drawdown halt** | The intraday desk has none (only the older daily engine had `max_drawdown_halt`); a setup with a truly negative edge could lose up to the daily limit every day | **Gap. The owner picks the value.** Interim: a cumulative per-setup tripwire that alerts a person |
| **Scenario and stress** | Gap open, IV crush, expiry-day gamma, feed failure mid-position, double the modelled costs | New report per sleeve and for the book (P5) |
| **Margin and exposure monitor** | Margin utilisation and net delta/vega against limits, shown daily | Limits exist; a daily line in the digest (P5) |
| **Model risk** | Every model has a spec, a baseline, a locked test, shadow, a demotion rule; independent validation before apply | [ML_ROADMAP.md](ML_ROADMAP.md) rules 1 to 7 |
| **Operational risk** | Section 2 and the watchdog | P0 |
| **Independent review** | Monthly risk-compliance review of the whole system (quarterly in the learning-bot report) | In force |

---

## 8. The scoreboard (what the owner sees, weekly, without asking)

Sessions run of expected (target 100%); mean time to detect a missing session; tape sessions with at least 300 good minutes; forward
trades per sleeve and v4 eves settled; counted HAR sessions of 60; pre-registrations open, closed, rejected; audit register: open
P1 and P2 findings after re-triage; tests and mutation-checked guards; days since the last unalerted failure; Claude usage against
budget; milestone table (due, days late). Delivered by the Saturday digest (W8) and the learning bot's monthly report.

---

## 9. Phases and gates (the calendar)

| Phase | Window | In scope (and nothing else) | Exit test |
|---|---|---|---|
| **P0 Protect the evidence** | 23 Oct to 6 Nov | Finish the merge chain; verify the Worker, token and Kotak status (owner); build and deploy the watchdog (section 3); first observed start on Mon 26 Oct; first v4 settlement and HAR sessions; first weekly learning run (Sat 24 Oct); enter token expiry dates; owner decisions listed in section 12 | 10 consecutive trading days with every session run and alerted-on if not; watchdog drill: a deliberately stopped workflow produces a push and an email within 15 minutes |
| **P1 Trust the record (S1 to S3)** | 9 Nov to mid Jan | **Re-triage the audit's 115 findings against `main` first (two weeks)** so we stop fixing what is fixed; evidence integrity and provenance (append-only or anchored journal, one clock); data-validity layer and quarantine; crash, restart and order-state safety | A replayed session reproduces its decisions exactly from persisted evidence; zero zero-VIX-style bars recorded as valid over 5 sessions; restart tests in CI. **G1 in mid January** |
| **P2 Execution realism and live-readiness (S8, S9)** | Dec to Mar | Depth recording if available; TCA on all fills; depth-capped fills and one cost source; order state machine on a fake broker; pre-trade checks; reconciliation; kill-switch drill; the dry-run mode | S9 fake-broker tests pass; monthly TCA table; modelled versus real cost within a stated band. **G3 around April or later** |
| **P3 Strategy factory** | Continuous from Nov | Section 5 cadence; first queue; monthly review | One idea closed with a written lesson every month; zero repeats (fingerprint) |
| **P4 Models** | Platform from Nov; models from mid Jan | [ML_ROADMAP.md](ML_ROADMAP.md) Phase 0, then M1 to M8 as data allows | Each model: spec, locked test, shadow verdict. **ML-ready bar = S1 to S3 exit tests plus the discipline of section 0** |
| **P5 Institutional controls** | Jan to Apr | S4 to S7: honest UI and status, e2e deterministic trade test, observability complete, statistical hygiene (placebo and CI gate, demotion); stress/scenario report; margin monitor; daily digest; restore drill; security review (public repo decision, secret rotation); daily pack | **G2 around March.** Restore drill passes; e2e test asserts every row |
| **P6 Unattended loop and soak** | Apr to Jul | Four-week unattended run; auto-demotion drill; second independent audit; 90 clean paper sessions | Drill passed; 90 clean sessions |
| **P7 Acceptance** | 30 Jun, final 31 Aug | Acceptance against [MASTER_PLAN_JUNE_2027.md](MASTER_PLAN_JUNE_2027.md) section 1, then the handover report | Signed checklist |
| **G4 Live trading** | Never scheduled | The owner's decision under the section 6 checklist | Not a build target |

---

## 9a. Month by month (November 2026 to August 2027)

How to read a month: **Theme** is the one sentence. **Built** is engineering. **Strategy builder / Self-improvement** are the
steps from 5a and the loop that arrive that month. **You do** is your time, in hours, and it is deliberately small. **You will see**
is what appears without you asking. **Exit** is the recorded fact that says the month is done. If a month slips, section 0's cut
order applies and nothing else is added.

| Month | Theme |
|---|---|
| **Nov 2026** | Eyes open: nothing fails without you hearing about it |
| **Dec 2026** | Trust the record |
| **Jan 2027** | G1: the paper system is correct and recoverable; first model verdicts |
| **Feb 2027** | Ideas become paper strategies without bespoke code |
| **Mar 2027** | Execution is realistic; the statistics are clean (G2) |
| **Apr 2027** | Institutional controls and the live dry run |
| **May 2027** | The unattended month |
| **Jun 2027** | Acceptance |
| **Jul 2027** | Soak and scope decisions |
| **Aug 2027** | Handover |

**November 2026: Eyes open.**
- *Built:* the watchdog (section 3) with push and email; the merge queue finished (#87, #93, #88, #97 to #99); the audit's 115
  findings re-triaged against `main` so we know what is still open; ML Phase 0 started (dataset builder skeleton); the instrument
  registry designed.
- *Strategy builder:* SB1 idea-card template and the spec template written down; the first queue item (L1 regime caveat) drafted.
- *Self-improvement:* the learning bot's four weekly runs observed; its first monthly run is on **2 Nov** (covering October), the next on 2 Dec.
- *You do (about 2 h):* the five setup items in section 12; decide on merging the open PRs; try the watchdog drill once.
- *You will see:* a push and an email when something is wrong, a Saturday digest, draft PRs from the learning bot.
- *Exit:* ten trading days in a row with every session run, and a deliberately stopped workflow raising a push and an email within 15 minutes.

**December 2026: Trust the record.**
- *Built:* S1: an append-only or anchored journal, provenance on every decision (code, config, model, chain snapshot), one clock;
  the 2027 NSE holiday list (by 15 Dec); restore drill #1 from [RECOVERY.md](RECOVERY.md); S2 validity layer started.
- *Strategy builder:* SB2 v1, a `strategy` command that drafts a spec from an idea card and runs the repeat, overlap and cost
  checks; the L1 regime-caveat study registered through it.
- *Self-improvement:* the teacher's hypotheses flow into the idea queue; the 2 Nov and 2 Dec monthly reports reviewed.
- *You do (about 2 h):* review the monthly report; enter or approve the holiday list; decide the public/private question.
- *You will see:* the first one-page monthly pack against this plan's dates.
- *Exit:* a replayed session reproduces its decisions exactly from persisted evidence alone.

**January 2027: G1 and the first model verdicts.**
- *Built:* S2 finished (quarantine of invalid series); S3: crash, restart and order-state safety in CI; **G1 declared if its tests
  pass (mid-January)**; ML dataset builder and test harness (purged walk-forward, leakage tests) done; the soak counter starts.
- *Strategy builder:* SB3 study runner: a registered spec runs on bhavcopy in the `Study` workflow and its result is locked with no
  manual step; the first new-idea result recorded.
- *Self-improvement:* the quarterly independent risk-compliance review; the demotion rule exists for shadow models. The HAR shadow
  reaches 60 counted sessions at the earliest in late January and is read once.
- *You do (about 3 h):* G1 sign-off; read the quarterly review.
- *You will see:* the G1 checklist, the first locked result from the builder.
- *Exit:* zero invalid-series bars recorded as valid over 5 sessions; restart tests green.

**February 2027: Ideas become paper strategies.**
- *Built:* P2 begins: transaction-cost analysis on every fill; depth recording if the broker offers it; the order state machine on
  a fake broker.
- *Strategy builder:* **SB4 sleeve generator**: an approved spec becomes a forward paper sleeve with its own ledger and no bespoke
  code. First non-expiry sleeve starts in shadow.
- *Self-improvement:* **M1 (volatility ML versus HAR)** locked-test verdict; the monthly run proposes up to three research actions
  and at least one idea is closed each month with a written lesson.
- *You do (about 2 h):* approve or reject the monthly proposals.
- *You will see:* a strategy appear on the dashboard that you described in words.
- *Exit:* one new strategy runs as a paper sleeve end to end (card, spec, study, sleeve) without a line of bespoke code.

**March 2027: Realistic execution and clean statistics (G2).**
- *Built:* S8: depth-capped fills and one cost source; S9: pre-trade checks (price band, duplicate, rate), reconciliation, kill-switch
  drill; the stress/scenario report; the placebo and confidence-interval gate (S7); the HAR 31 March backstop.
- *Strategy builder:* **SB5 gate evaluator** computes the paper gate for every sleeve weekly; the forex/commodities go or no-go memo
  started (Tier 3).
- *Self-improvement:* auto-demotion drill scheduled for April.
- *You do (about 3 h):* G2 sign-off; the multi-day drawdown-halt value if still open.
- *You will see:* a weekly table of every strategy against the gate.
- *Exit:* **G2** around now; the kill-switch drill recorded.

**April 2027: Institutional controls and the live dry run.**
- *Built:* S4 to S6: honest status and UI, the deterministic end-to-end trade test; margin and exposure monitor in the daily digest;
  the **live dry-run mode** (builds the exact broker order, validates it, never sends; depends on what the broker's API offers,
  TO VERIFY); security review (secret rotation, public-repo decision made); the second independent audit; **G3** about now or a
  little later.
- *Strategy builder:* **SB6 allocator** and **SB7 strategy reports**. End of April is also the roadmap's switch to maintenance mode
  (usage budget in [ROADMAP_AUG_2027.md](ROADMAP_AUG_2027.md) section 5): mostly scripts, about three agent sessions a week.
- *Self-improvement:* the auto-demotion drill passed.
- *You do (about 3 h):* read the audit; decide anything it raises.
- *You will see:* one-page reports per strategy; the dry-run comparison started.
- *Exit:* the end-to-end test asserts every row; the audit's P1 findings are closed or explained.

**May 2027: The unattended month.**
- *Built:* nothing new. Fixes only.
- *Self-improvement:* the four-week run in which the desk, the learning bot and the retrain jobs run with no human in the loop; the
  dry run compares would-be live fills with paper fills for 20 sessions; the Tier 3 decision.
- *You do (about 1 h):* read the Saturday digests.
- *You will see:* that nothing needed you.
- *Exit:* four weeks with no manual engineering in the loop and no unalerted failure.

**June 2027: Acceptance.**
- *Built:* runbooks and documentation finished; the final month's independent review.
- *You do (about 3 h):* the acceptance review on 30 June against [MASTER_PLAN_JUNE_2027.md](MASTER_PLAN_JUNE_2027.md) section 1; a
  written pack on whether any strategy is a candidate for G4 and what the evidence is.
- *Exit:* a signed checklist. The 90-session soak completes around the end of May if no reset occurs.

**July 2027: Soak and scope.** Tier 4 (US and European options) in shadow or cut; fixes only; the quarterly review. *You do (about 1 h).*

**August 2027: Handover.** The final acceptance report on 31 August and the "what we learned" book: every idea tested, its verdict,
and whether anything earned its way toward live. *You do (about 3 h): decide what comes next.*

---

## 9b. The end state, and your part in it

**A day in August 2027, if the plan holds.** At 08:50 the Worker starts the desk; nothing tells you because nothing is wrong. The paper
desk runs its strategies; the watchdog stays quiet. After the close the teacher writes its lessons and the retrain jobs run. On
Saturday you get one digest: sessions run, strategies and their gate status, what the learning bot proposed, anything that needs
you. Once a month you get a one-page pack and a short list of decisions. That list is your job.

**How you add a strategy.** You write an idea in plain words, for example "sell expiry-day strangles only when the vol forecast is
well below implied". The desk makes an idea card, drafts a spec, the research-reviewer checks it is new, can fail and is powered, the
study runs on the free deep data, and, if it survives, a paper sleeve starts. After 60 sessions and 30 trades the gate reports. You
see a one-page report with a verdict, whichever way it goes.

**What stays yours, always.** Switching live trading on. Raising any ceiling. Clearing a halt. Anything that spends money. Keeping the
rules in [AUTONOMY.md](AUTONOMY.md).

**Your part, honestly.** You set direction and make the few decisions only you can. You do not need to read code. The most useful things
you can do are the five setup items, a monthly look at the pack, and saying "no" when something is not worth building. What you have
already built is the hard part: a desk that will not lie to itself.

---

## 10. Adjustments to the earlier plans (this file wins)

| Earlier statement | Now | Why |
|---|---|---|
| Learning bot live by 30 Nov (guard required on main) | **Merged 23 Oct**; the guard becomes a required check when the owner adds it | Built and reviewed |
| HAR graded live for 20 sessions; first M1 apply decision 31 Dec | HAR needs **60 counted sessions**, one stored read; earliest about late January, backstop 31 Mar 2027 | Research review found 20 sessions underpowered (about 50% on NIFTY) |
| ML platform Phase 0 in parallel with everything | Phase 0 runs, but **no model work before the P1 exit tests** | A model trained on an unvalidated record is not evidence |
| Many separate stabilisation items | Grouped as P1 (S1 to S3) then P2 and P5 | One order to follow |
| Review everything to the same depth | Proportional review (section 0, rule 4) | Cost of seven rounds on tooling |
| `expiry_seller_v4` counted as another experiment | Listed but **not counted** as independent (re-settlement of v1 to v3) | Avoids overstating evidence |
| Models and sleeves, no common way to add a strategy | **Strategy builder SB1 to SB7** (section 5a), delivered November to April | The owner's stated end goal: describe an idea, get a tested, paper-traded, reported strategy |
| 90 clean sessions at the end | The soak counter starts at G1 (mid January); 90 trading days end about the end of May | So acceptance in June is not the first time the claim is tested |

---

## 11. Parking lot (deliberately not now)

Forex and commodities trading, US and European options (Tier 3 and 4 stay evaluation only until the P1 and P2 exits); sequence
models; buying historical data; a second broker; a web UI redesign beyond S4's honesty fixes; any new strategy family before the
three queued ones are closed; real-money anything.

---

## 12. Owner checklist and open verifications (what only you can do, and by when)

**By Monday 26 Oct (before the first forward sessions):**
1. Cloudflare dashboard: confirm the `quant-desk` Worker shows **4 cron triggers** and was deployed from `main` after PR 92 (a red "Workers Builds" check on PRs is a different thing).
2. Record **`GH_DISPATCH_TOKEN` expiry** and its scope (it should have only what the Worker needs).
3. Confirm the Kotak token and TOTP status and write down how and when it is renewed.
4. Add **`Learnbot guard`** as a required check on `main` (the name was confirmed on its own PR run).
5. Delete the **conditional-merge clause** from the monthly learning routine's stored prompt.
6. Install the **ntfy** app, choose a long random topic, and give it to the Worker as a secret; tell me which email address should receive alerts.

**By 6 Nov:** Settings, Pages: is the published site up? Set a Claude billing alert. Decide the watchdog's optional dead-man's-switch.

**By 15 Dec:** the **2027 NSE holiday list** (or tell me to enter it from the circular, which I would then source and cite). Without it the desk treats 2027 holidays as trading days.

**Decisions only you can make (no deadline pressure, but they unblock phases):**
- Keep the repository **public**? Specs, reports and journal branches are world-readable. A private repository has a monthly Actions-minutes allowance (on the order of 2,000 free minutes; TO VERIFY the current figure) and a 7-hour daily session is far above that, so privacy has a real cost. Decide with that in mind.
- The **multi-day drawdown halt** value for the intraday desk (section 7).
- The standing **merge-permission paragraph** and the S0-04 review rule in `AUTONOMY.md`.
- `docs/principles.json` L3 wording: it says "locked 2019-26" and that HAR "beat the desk's forecaster"; the lock's sessions end 28 Feb 2023 and it beat the study's candidate A, not the live desk estimate.
- Disable non-production Cloudflare builds (they fail on every PR and are noise).
- Capture one raw Kotak INDIA VIX candle response (settles N1 before S2's design is fixed).
- Whether to buy any data later (out of scope for now).

**TO VERIFY at build or on first use (I will report each):** that the published JSON carries timestamp, feed and halted fields; that the Actions bot (not a personal token) produces a GitHub email and app push; whether Kotak's API exposes market depth and a pre-order validation call; what happens at the live-job hand-off over five production sessions; that `chain-archive` covers every session before artifacts expire; that the Worker still proxies the published site (the audit says it did); ntfy throttling from a shared Cloudflare address; the Actions policy on the account.

---

## 13. How this plan stays the plan

It is edited only by pull request. Each phase's exit test is a recorded fact (a report, a run, a drill), not a feeling. The learning
bot's monthly report currently flags slips against the milestone table in [ROADMAP_AUG_2027.md](ROADMAP_AUG_2027.md) section 3 (its
parser does not read section 9 yet), so the monthly report's author checks section 9's dates by hand until it does. If something is
not in this file and not an owner request, the answer is "parking lot".
