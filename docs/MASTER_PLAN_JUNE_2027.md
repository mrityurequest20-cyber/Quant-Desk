# Master plan: a self-improving trading desk by 30 June 2027

> Extended on 17 Oct 2026: the deadline is now August 2027 and the scope is open (docs/ROADMAP_AUG_2027.md). The
> milestones below through June stand as the core acceptance.

Mandate (owner, 17 Oct 2026): by June 2027 the desk is fully self-improving and self-learning, hands-off as far as
safety allows. The structure may change top to bottom. Nothing later than June 2027.

## 0. What is promised, and what is not

**Promised (engineering deliverables, dated below):** the data pipeline, the learning platform, the models, the multi-instrument
paper desk, the closed improvement loop, the safety rails and the monitoring. All built, tested, reviewed and running.

**Not promised, because nobody honest can:** that any model beats its baseline, or that the desk is profitable. The gates
decide that on evidence. A model that fails its gate is a finished, useful result. "Self-improving" means the loop runs
on its own and promotes only what is proven; it does not mean every attempt succeeds.

**Stays with the owner, by the standing hard rules:** the real-money switch, flipping any `apply`, merging pull requests,
clearing halts. Hands-off means these cost the owner minutes a week, not that the safety rules disappear.
Real money stays off throughout; going live is the owner's decision after June.

## 1. Definition of done (checked on 30 June 2027, every item testable)

1. **Data:** automated daily collection for NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY (chains and option minutes),
   the top ~50 F&O stocks (cash, futures, option chains and minutes), global and macro series; a daily health check; at
   least 6 months of live tape by June; bulk storage that cannot hit file-count limits.
2. **Platform:** dataset builder, test harness (purged walk-forward, leakage tests), model registry, scheduled retrain job,
   drift monitor, automatic demotion of a degrading model to shadow.
3. **Models (docs/ML_ROADMAP.md, M1 to M8):** each has a registered spec and a final verdict (promoted to apply, kept in
   shadow, or rejected) with its evidence on file. At least the volatility model graded live for 20+ sessions.
4. **Desk:** paper-trades NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY and liquid stock options, under unchanged
   ceilings. Overnight carry and the defined-risk allocator run in shadow with their gates evaluated.
5. **Closed loop, running unattended:** trade, then nightly Claude teaching, then weekly and monthly learning bot, then
   registered study, then a promotion proposal as a pull request, then the owner's single flip.
6. **Safety:** ceilings enforced outside every model's reach, tighten-only, kill switch, auto-demotion drill passed,
   monthly independent risk review on file, 90 consecutive clean paper sessions.
7. **Operations:** alerts for any failed collection or run, a runbook, and a usage budget the loop stays within.

## 2. Architecture changes (what changes top to bottom)

| Layer | Now | Target |
|---|---|---|
| Data | Tape and minutes for 2 indices in the engine; patchy collectors | One collector framework per source, quarterly-sharded releases, health checks, point-in-time stores |
| Instruments | NIFTY and BANKNIFTY traded | Instrument registry (lot, costs, exchange segment, calendar, margin) so adding one is configuration plus validation |
| Models | Hand rules plus HAR in shadow | Registry of versioned models behind one prediction-event schema, each with its own gate |
| Loop | Teacher, learning bot, sleeves, manual engineering | Scheduled, PR-based, owner flips apply |
| Safety | Reviews by agents per change | Same, plus continuous drift monitoring and automatic demotion |

## 3. Milestones

| By | Milestone | Exit test |
|---|---|---|
| 31 Oct | Monday proof done; #67 merged; **collection expansion** (all 5 indices, stock cash, futures and chains, quarterly shards, health check); ML platform Phase 0 started | Collectors run in CI for 5 sessions with no gap |
| 30 Nov | Instrument registry; all 5 indices paper-traded; **M1 volatility ML vs HAR** locked test done; overnight rebuild in shadow; learning bot live (guard required on main) | Locked-test verdict on file; 20 sessions of multi-index paper |
| 31 Dec | Stock options in shadow; **M2 regime, M3 brain weights** offline then shadow; first apply flip decision for M1 if it passed | Registered verdicts for M2 and M3 |
| 31 Jan | **M4 entry filter and M5 exits** (needs ~300 labelled setups from counterfactuals and shadow); stock paper trading on | Calibration report |
| 28 Feb | **M6 sizing (tighten-only) and M8 cost model**; overnight gate look 1 reachable | Sizing never exceeds ceilings (property tests) |
| 31 Mar | Forex and commodities **evaluated** (data and instrument fit); M7 option mispricing on 4+ months of tape | Go or no-go memo with evidence |
| 30 Apr | Full unattended loop run for four weeks; drift and auto-demotion drill; second independent safety audit | Drill passed; no manual engineering needed in the loop |
| 31 May | 90-session soak; documentation, runbook, alerts | 90 clean sessions |
| 30 Jun | **Acceptance review** against section 1 with the owner | Signed checklist |

One month of slack is built in: the plan is complete in May if nothing slips.

## 4. How the work is run (usage is the binding constraint)

- One build at a time, sequenced as short stories; Haiku for mechanical work, Sonnet for builds, Sonnet at high effort for
  the reviews that carry a veto, and the main chat for judgement.
- Training runs on GitHub CPU and costs no Claude usage; Claude is used for the teacher, news text, builds and reviews.
- Every change goes through a pull request with green checks and the reviewer the rules require.
- A weekly owner touchpoint of about fifteen minutes: merge what passed, flip what you approve.
- The remediation log and this plan are updated at every milestone.

## 5. Top risks

1. **Usage limits** stall builds: mitigated by sequential builds and cheap models for cheap work.
2. **Data gaps** (Kotak keeps about 30 days of minutes; quotes are not historical): collection first, health check, alerts.
3. **No model passes its gate:** possible. The deliverable is still the loop; the verdicts are the evidence.
4. **Stock options are heavier than the indices** (lot sizes, costs, margin, liquidity): stocks run in shadow before paper trading.
5. **A safety regression from a fast build:** every change is reviewed; ceilings sit outside model code; monthly audit.

## 6. First 10 days

1. Extend the collectors: all five indices, stock chains and option minutes, quarterly shards, health check; run the 30-day
   backfill with the new code before the window drops those days.
2. Monday 19 Oct: the live proof; merge #67 if clean.
3. Tuesday 20 Oct (market closed): ML Phase 0 (dataset builder, harness, registry) and the instrument registry design.
4. Rebuild overnight carry to the final specs (branch `specs-final`).
5. Re-audit the learning bot, then the owner adds its guard as a required check on main.
