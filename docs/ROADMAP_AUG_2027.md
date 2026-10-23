# Roadmap to August 2027: a self-improving, self-learning trading desk, built to run without the owner

Owner mandate (17 Oct 2026): free hand on scope (any market, any structure), deadline August 2027, the owner will not be
checking in. This supersedes the date in docs/MASTER_PLAN_JUNE_2027.md (its milestones through June stand; July and August
become soak, scope expansion and buffer). Real money stays off; that is the one switch only the owner flips, and it is
outside this roadmap.

## 1. Honest framing

- **What will exist in August 2027:** a paper-trading desk that collects its own data, trains and grades its own models,
  proposes its own improvements as reviewed pull requests, demotes anything that degrades, and reports on itself.
- **What nobody can promise:** that the desk is profitable, or that any model passes its gate. The gates decide that.
- **What a year of silence breaks if nobody prepares for it:** credentials that expire, billing that lapses, a broker API
  that changes. Section 4 lists what only the owner can set up before going quiet.
- Confidence (my estimate, 17 Oct 2026): core India desk with the full loop by March, about 75%; everything in the
  scope tiers below by August, about 55 to 60%; a statistically real paper profit by August, about 15 to 25%.

## 2. Scope tiers (each tier has a feasibility gate; a tier that fails its gate is cut, not forced)

| Tier | Scope | Window | Feasibility gate |
|---|---|---|---|
| 1 | NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY and liquid F&O stocks: data, paper trading, ML M1 to M8, overnight, allocator | Oct to Mar | Data collected 5 sessions without a gap per source |
| 2 | Global context as features and shadow signals: US and European index levels, futures, VIX/VSTOXX, rates, FX, crude, gold. No trading | Nov to Apr | Free or owner-keyed feed available from a CI runner |
| 3 | Forex and commodities evaluated; paper-traded only if a point-in-time quote feed, costs and instrument rules can be modelled | Mar to May | A written go or no-go memo with the data source named |
| 4 | US and European options paper-traded (index and liquid names) | May to Jul | Point-in-time option quotes available at acceptable cost; owner-provided key |
| Soak | Everything runs unattended; fixes only | Jul to Aug | 90 clean sessions per active market |

Execution is simulated paper in every tier, so no new broker is needed to trade paper; new markets need **data keys**.

## 3. Phase plan

| By | Deliverable |
|---|---|
| 31 Oct | Monday proof; #67 merged; collectors for 5 indices and F&O stocks with quarterly shards and a health check; ML Phase 0 |
| 30 Nov | Instrument registry; 5 indices on paper; M1 volatility vs HAR verdict; learning bot live; overnight rebuilt in shadow |
| 31 Dec | Stock options in shadow; M2 regime, M3 brain; first apply decisions |
| 31 Jan | M4 entry filter, M5 exits (counterfactual replays); stock paper trading |
| 28 Feb | M6 sizing (tighten-only), M8 costs; overnight gate look 1 reachable |
| 31 Mar | **Tier 1 complete.** Tier 3 memo started; Tier 2 features live |
| 30 Apr | Unattended-loop month; drift and auto-demotion drill; second independent audit; **switch to maintenance mode** (section 5) |
| 31 May | Tier 3 decided; Tier 4 data checked |
| 30 Jun | Core acceptance review (the June checklist) |
| 31 Jul | Tier 4 in shadow or cut; soak |
| 31 Aug | **Final acceptance and handover report** |

## 4. Owner-absent charter

**Runs with no human:** data collection, the nightly teacher, the weekly and monthly learning bot, retraining jobs,
drift monitoring, automatic demotion to shadow, the daily health check, and builds of items already on this roadmap.

**Never happens without the owner, whatever the circumstances:** real money, any `apply` flip that raises exposure, any
loosening of a ceiling or gate, clearing a halt, workflow permission widening, editing locked results. If one of these
is needed the roadmap item waits and is listed in the handover report. Nothing else is allowed to wait on the owner.

**Self-protection while nobody watches:**
- The desk is paper-only, so absence risks time and data, not money.
- Any halt, drawdown breach, failed collection or expired credential raises an alert (email or push) and the desk stands
  down safely; it does not improvise.
- A kill switch (one workflow, owner-only) stays available.
- Model degradation demotes to shadow automatically (tighten-only); promotion never happens without the owner.

**Standing permissions the owner writes down once** (so no waiting): (a) pull requests that have green `tests` and
`doctor` plus the independent reviewer's CLEAR that the repo's rules require may be merged by the engineer session;
(b) tighten-only changes (smaller sizes, extra filters) may be applied by the engineer session after a CLEAR; (c) every
other change waits. This is the owner's decision; nothing here assumes it.

**Owner checklist before going quiet** (only the owner can do these):
1. Add data-feed secrets for Tier 2 to 4 (an options-data provider key, Alpha Vantage or Twelve Data or TrueData) and set the
   billing on each to auto-renew.
2. Confirm the Claude API billing and the Anthropic key are good for twelve months; set a spend alert.
3. Document the Kotak token and TOTP renewal steps; if Kotak sessions need manual login, decide the fallback.
4. Set an alert channel (email or phone push) for desk alerts.
5. Add `Learnbot guard` as a required check on main after it has run once.
6. Pick a quarterly 30-minute check-in date as a safety valve. The roadmap works without it, but a year is long.

## 5. Usage budget (the binding constraint)

Phase 1, Oct to Mar, **build mode:** one build at a time, Haiku for mechanical work, Sonnet for builds, Sonnet at high
effort only for reviews that carry a veto, the main chat for judgement. Target: no more than two agent runs in flight and
no parallel review rounds; pause and resume rather than retry when the usage limit is hit.

Phase 2, Apr to Aug, **maintenance mode:** the autonomous loop is mostly scripts that cost nothing: collectors,
retraining on GitHub CPU, the health check, drift monitors. Claude is used for: the nightly teacher (about $0.20 a day
of API), one weekly learning-bot session, one monthly review, and fixes. Cap of about three agent sessions a week.

Usage guard: if any routine hits a usage limit it records the fact, backs off until the next scheduled slot, and never
retries in a loop. The weekly session count is part of the health report.

## 6. Cut order if the plan slips (decided now, applied without asking)

1. Tier 4 (US and European options trading), then 2. Tier 3 trading (forex and commodities stay as data and a memo),
3. stock option paper trading, 4. M7 option mispricing, 5. M5 exits, 6. the sequence-model experiments.
Never cut: data collection, the platform, the indices, the closed loop, the safety rails, the handover report.

## 7. Cadence and reporting

- Monthly: a milestone check against section 3 written into the remediation log; a slip of more than two weeks is
  flagged in the next alert.
- Quarterly: an independent risk review (risk-compliance) of the whole system; findings fixed or logged.
- August 2027: a handover report: what was built, every model's verdict with its evidence, the desk's paper record, what
  failed and why, what needs the owner, and what the next year should be.
