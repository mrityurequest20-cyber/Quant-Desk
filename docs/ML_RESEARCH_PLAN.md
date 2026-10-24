# Research plan and handover (24 Oct 2026)

Written at the end of the 23-24 Oct session so the next session starts warm. It records decisions the owner made in that session, the
design of the model programme, and what is still open. It changes no rule, spec, limit or result. Where it differs from
[MASTER_PLAN.md](MASTER_PLAN.md) on dates, the master plan wins; [ML_ROADMAP.md](ML_ROADMAP.md) keeps the standing ML rules and
[ML_PHASE0.md](ML_PHASE0.md) the Phase 0 work items.

## 1. The owner's direction (what the plan is for)

- A state-of-the-art desk, built in the open, target **August 2027**. The owner steers; the desk is built and judged by evidence.
- **Everything is home-built**: our own data and code, small models on CPU. Hugging Face and pre-trained models are parked. The
  live tick view is parked.
- **Train properly, in controlled conditions, shadow first.** A model is trained on data up to a cut-off, frozen, graded only on
  later sessions, and discarded if it does not hold up. No model is deployed because it looked good on the past.
- **The brain and the engine must develop with the models** (section 5), not stand still while the models improve.
- A read-out in **April or May 2027** of where each part stands, on forward records.

## 2. The model slate

Each model has its own spec, baseline, locked test, shadow and gate ([ML_ROADMAP.md](ML_ROADMAP.md) section 4). Whether the external (Kaggle)
data is trusted for it decides whether it gets a twin test.

| # | Model | Data | External data | Twin test |
|---|---|---|---|---|
| M1 | Volatility / move size | index minutes 2015 to May 2026 | cross-checked (section 4) | **No.** One pre-registered, one-shot out-of-sample evaluation of the locked HAR model on Mar 2023 to May 2026, written before the results are loaded |
| M2 | Regime | same plus VIX, breadth | same | No |
| M3 | Brain weights | our journal and news | none | No (own data only) |
| M4 | Entry filter | labelled setups (shadow records, counterfactuals) | none | No |
| M5 | Exits | replays | none | No |
| M6 | Sizing (tighten-only) | M4 outputs | none | No |
| M7 | Option mispricing and strike selection | our option tape plus Kaggle option history | **unverified** | **Yes** (section 3) |
| M8 | Execution costs | quotes in our chain tape | none | No (but see the correction in section 3) |
| M9 | Teacher (LLM) | journal text | none | Advisory only; never gates a trade |

## 3. Options: the twin test, and the cost-model correction

The Kaggle option sets (2020 to Oct 2024, and Sep 2024 to Mar 2026) hold traded prices only: **no bid or ask**, and the second set's
IV and Greeks are the author's own and unreliable. Nobody can confirm from here whether they are right, so for options we test
whether training on them helps, instead of assuming.

Three arms, identical in everything except the data (same model type, features compared on the common set, tuning budget, seed,
training cut-off and code hash), frozen before grading, graded on the same live sessions, scored session by session:

| Arm | Trained on | Features |
|---|---|---|
| A-full | our own option tape | everything we record, including quotes |
| A-common | our own option tape | only the features Kaggle also has |
| B | our tape plus Kaggle | the common features only |

- **B against A-common** shows what Kaggle adds. **A-full against A-common** shows what quotes add.
- The test cannot prove Kaggle's data is *right*; it shows whether it helps predict *our* tape.
- The score, the window (the owner suggested 60 sessions) and the margin that counts as a win are fixed in the spec before the shadow
  starts. A gap inside the margin is a tie and the window extends. Sixty sessions separate large differences only.
- Our own option tape began in Oct 2026 (about 28 sessions by late November), so arm A is not solid before about **Feb to Mar 2027**.
  Early gaps are not read as results. Apply-ready for options is not before mid 2027.
- Whether our tape records bid and ask is **to be confirmed** before the spec is written; the A-full arm depends on it.

**Correction to the execution model (M8).** Paper fills are *simulated*, not real fills, and live trading is off. A model trained on
them would learn our own simulator. The cost model is therefore built from the **quotes in our chain tape** (spread by strike
distance, time of day, expiry day and stress). Labels for M4 to M6 ("P&L after costs") depend on it, so it comes early. Limit orders
and stops are modelled explicitly: a limit fills only when the market trades *through* the price (fill probability learned from
the tape), and a stop gets a slippage allowance by strike distance and liquidity.

## 4. Data status (details in [data/INTAKE_2026-10-24.md](data/INTAKE_2026-10-24.md))

- Index minutes (NIFTY, BANKNIFTY, INDIA VIX), 2015 to 14 May 2026: validated; realised variance agrees with the older source on 99.8%
  of sessions. Same upstream as the older source, so not independent of it; Yahoo daily bars and the desk's conventions are the anchors.
- Hole: **15 May to early Sep 2026** (about 75 sessions), still open. No option history between 25 Mar 2026 and our own tape.
- `external_unverified` applies to all of it until the importer's validation passes. None of it counts as evidence for a gate or a
  model promotion, and none of it goes in the public repository or a release until its licence is known.
- **Licences:** not known for `debashis74017`, `pariminikhil`, `kaalicharan9080`, `ayushsacri`; the owner has said not to chase them. The
  safe default stands: nothing third-party is published. The BANKNIFTY set of `sandeepkapri` declares MIT, which covers the compiler's work, not necessarily the provider's data.

## 5. The development ladder (how the engine and brain keep improving)

Every component has a rung, and moving up needs a registered rule plus the owner's switch. A model can only tighten (never raise an
exposure above the owner's ceilings, loosen a gate or touch the paper-mode switch), and a live component whose rolling score falls
below its baseline drops back to shadow by itself.

| Rung | Meaning |
|---|---|
| Recorded | graded every session, changes nothing (the brain's factor weights today, D-01: indistinguishable from noise) |
| Shadow | predicts live, graded against its baseline; the earn-in gate computes and journals what it *would* apply |
| Applied | owner flipped the switch after a passed gate |

- **Brain:** every call is graded against the next 30 minutes. The earn-in gate (walk-forward lift, last 60 sessions, placebo,
  multiplicity, two consecutive sessions, half the tilt) is in shadow mode; its own estimate is 6 to 12 weeks of sessions before
  anything passes. M3 replaces hand-set weights with learned ones, offline then shadow beside the hand weights.
- **Engine:** the v4 sleeves F to J start Mon 26 Oct (settled on NSE's official close). The HAR volatility shadow counts 60 sessions
  from 26 Oct (about late January), single stored read, backstop 31 Mar 2027.
- **To build:** a single view of every rung (status, graded sessions, score against baseline) in the Saturday digest and the master
  plan, so the owner sees the whole desk improving, not only the models.

## 6. Order of work

1. Phase 0 platform ([ML_PHASE0.md](ML_PHASE0.md)): importer with validation and manifest, dataset builder, leak-proof walk-forward
   harness that reproduces the locked HAR result, registry and prediction-event schema. Target mid November.
2. M1 (volatility) against HAR; the one-shot evaluation on Mar 2023 to May 2026, pre-registered before loading.
3. Read-only analyses on data we hold: the **strike-distance study** (win rate and average P&L by distance of strike from spot; the owner
   sees near-the-money strikes carrying most of the profit) and a **VWAP check** (the owner reports 0% winners; first confirm the trade
   count and whether the losses are the logic or the exit and cost rules). Split paper P&L by sleeve, strike distance and day to see how
   much of it is repeatable. Any resulting change enters as a new pre-registered version, never an edit of a locked rule.
4. M2, M3 (offline, then shadow), the spread and fill study from the chain tape (M8), then M4 to M6 as labelled setups accumulate.
5. Options (M7) with the twin test once the tape is long enough.

## 7. Open items

| Item | Owner of the next step |
|---|---|
| Kaggle licence lines: **the owner said not to worry about this.** Default kept without asking: the third-party data stays out of the repository and releases; only our own derived tables could ever be published | none |
| Worker alert drill (`WATCHDOG_TEST=1`, then remove it; then close issue #104): **the owner will do it in their own time** | owner, optional |
| Optional line in `docs/AUTONOMY.md` recording the teaching step (only the owner edits that file): **optional, the owner is fine without it** | owner, optional |
| 2027 holiday list by 15 Dec | next session |
| Multi-day drawdown halt value | owner |
| Scope ladder (more indices, stocks, commodities): admissions after the Phase 0 exit | next session, if the desk is doing well |
| Source for 15 May to early Sep 2026 index minutes, or accept the hole | next session |
| Confirm the tape records bid and ask; check that journal text sent to the teacher holds nothing private (account numbers, keys, tokens) | next session |
| First teaching run: confirm its log line after a session; spend stays inside its half of the $20 | next session |

## 8. Honest expectations

- ML will not conjure an edge. Direction research found none after costs. The realistic gains are volatility and move-size forecasts,
  regime reads, cost prediction, strike selection and tighter sizing.
- Most models will fail promotion. A failed gate is a result, recorded as one.
- The paper profit so far is a short, volatile sample. It is encouraging, not evidence. Judge by sleeve and by session, on forward records.
