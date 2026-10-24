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
- **Confirmed (24 Oct): our tape records real bid and ask**, and the size resting at the best bid and offer. The tape is Kotak-only by design (NSE's public chain and the
  model chain are excluded). In the one file checked, the 23 Oct morning (68,306 rows, 1,666 snapshots, five underlyings) a usable bid and ask is present on 99.8% of rows,
  and the median spread as a share of the mid widens with distance from spot, in either direction: about 0.45 to 0.5% within 0.25%, 0.5 to 0.75% at 0.75 to 1.5%, about 1.0 to 1.2%
  at 1.5 to 3%. Beyond 3% from spot it depends on the side, and **a cost model needs the out-of-the-money side**: calls 0.88% out of the money and 5.72% in the money, puts
  1.17% out of the money and 1.54% in the money (the pooled 'calls 2.2%' is driven by deep in-the-money calls). It also differs a lot between underlyings (NIFTY about
  0.5 to 0.6% across all strikes, FINNIFTY about 2.4 to 2.9%). One morning only; other days and the afternoon are not checked. The `chains-2026` release holds chain files from 29 Sep (16 sessions to
  23 Oct), earlier than the sentence above assumes; how many of those sessions are complete is not yet checked.

**Correction to the execution model (M8).** Paper fills are *simulated*, not real fills, and live trading is off. A model trained on
them would learn our own simulator. The cost model is therefore built from the **quotes in our chain tape** (spread by strike
distance, time of day, expiry day and stress). Labels for M4 to M6 ("P&L after costs") depend on it, so it comes early. Limit orders
and stops are modelled explicitly: a limit fills only when the market trades *through* the price (fill probability learned from
the tape), and a stop gets a slippage allowance by strike distance and liquidity.

## 4. Data status (details in [data/INTAKE_2026-10-24.md](data/INTAKE_2026-10-24.md))

- Index minutes (NIFTY, BANKNIFTY, INDIA VIX), 2015 to 14 May 2026: **imported and checked by the importer** (`quantdesk/ml/intake.py`, EXTERNAL_DATA.md), not yet
  independently verified. Their realised variance agrees with the older source (aeron7) within 10% on 99.8% of NIFTY sessions and 99.7% of BANKNIFTY sessions
  (from the intake report; not re-run here, and only to Feb 2023). The two may share an upstream, so that agreement is not independent evidence; Yahoo daily
  bars, NSE's official close and the desk's conventions are the anchors still to be used (P0.6).
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
| Check that journal text sent to the teacher holds nothing private (account numbers, keys, tokens). (The tape records bid and ask: confirmed, section 3.) | next session |
| First teaching run: confirm its log line after a session; spend stays inside its half of the $20. **24 Oct: not yet run** (the 23 Oct afternoon job ran on code from before the teaching step); the first one is Mon 26 Oct, check after 16:30 IST | next session |

## 7b. Baseline: the first 26 paper trades (read from the `journal` branch, 24 Oct)

Read-only, 12 to 23 Oct (9 sessions, 26 closed trades, every one a single-leg long option). Strike distance is the long leg's distance
out of the money as a percentage of the entry spot. Paper fills; a small sample; use as a starting point, not a conclusion.

- Total **+14,909** after 3,311 of fees. By sleeve: `orb` 8 trades, 4 wins, +22,512; `trend_break` 13, 6, +9,014; `va_reversion` 2, 1, -1,690;
  `vwap_trend` **3, 0 wins, -14,927**.
- By strike distance: up to 0.25% out of the money 3 trades (+1,451); 0.25 to 0.75% 13 trades (-5,562); over 0.75% 10 trades (+19,022).
  The owner's impression that near-the-money strikes carry the profit is **not visible** here, and 26 trades cannot settle it.
- **Concentration:** three `premium_target` winners made +60,197 (at 0.26%, 0.75% and 0.91% out of the money); the other 23 trades lost 45,288
  together. Exits: `invalidation` 7 trades (-39,568), `time_exit` 11 (-15,690), `premium_target` 3 (+60,197).
- **Rerun with the fixed tool (24 Oct, `python -m quantdesk ml trades --journal <journal.db> --sleeve vwap_trend`).** Same 26 trades. Totals: +14,908.7 net of 3,311.3 fees (the table
  above rounds to +14,909 and its buckets sum to +14,911; pnl in the journal is net of fees, checked against the engine). With the buckets fixed in code (`quantdesk/ml/tradesplit.py`: strike
  distance against the entry spot, buckets closed below and open above), the split is 2 trades (+5,342) up to 0.25%, 13 (-30,552) from 0.25% to 0.75%, and 11 (+40,119) beyond. The
  earlier table differs because **two trades flipped bucket**, both by rounding to two decimals with an inclusive upper edge: a `va_reversion` loss at 0.2549% (-3,891) was counted in
  the first bucket, and an `orb` `premium_target` winner at 0.7527% (+21,098) in the middle one. Eight trades lie within 0.03 of one of the two edges, and the single trade 0.003 past
  0.75% moved 21k of P&L: the split follows a hundredth of a percent, which is what "26 trades cannot settle it" means.
  Without the desk's best three trades the other 23 lose 45,288 (the report's "All" line). Per cell the same exclusion is shown only from 10 trades and is trivially negative for a
  cell that is already losing: of the sleeves only `trend_break` (13 trades) qualifies, at -32,540. The VWAP check: all three `vwap_trend` trades had the underlying move *against*
  the trade at exit (-0.08%, -0.17%, -0.15%). With three trades and exit-time spot only, that does not separate the signal from the exit rules (an invalidation exit fires because the
  spot has already moved against the trade); it is a reason to look again at 30
  trades, not a finding.
- **Strike distance or the underlying? (24 Oct, `ml trades` prints this block too).** Premium paid is about the same in every bucket (32,600 to 34,400 on average: positions are
  sized by outlay), so distance changes how many contracts, not how much money is at risk. What moves the P&L is whether the underlying moved the trade's way by exit: the return on
  the premium follows the underlying's move almost one for one (correlation 0.94; about +100% of premium per +1% of the underlying), and **distance is uncorrelated with the move
  (-0.03) and with the return (+0.03)**. The underlying moved the trade's way in 12 of 26 trades (2 of 2 at up to 0.25%, 4 of 13 at 0.25% to 0.75%, 6 of 11 beyond). The five trades
  that ended on a target exit (three premium targets, two underlying targets) made +79.6k; the other 21 lost 64.7k together. So on this sample the strike is not where the profit comes from, and the near-the-money
  impression is not supported; what the data does say is that the entries are right about half the time and the exits decide the size. Still 26 trades, still descriptive.
- To redo it: restore the `journal` branch (`git fetch --depth 1 origin journal`, `git archive FETCH_HEAD`), open `intraday/journal.db`
  read-only (`mode=ro`), table `trades`, strikes in the `legs` JSON.

## 7c. Rebuilding the scratch data (the session's scratch folder does not carry over)

The Kaggle files were downloaded with `kagglehub` into a scratch cache: `debashis74017/nifty-50-minute-data`,
`pariminikhil/nifty-option-chain-3-oct-24-to-24-mar-26`, `sandeepkapri/banknifty-data-upto-2024`, `kaalicharan9080/nse-future-and-options-data`,
`ayushsacri/indian-nifty-and-banknifty-options-data-2020-2024` (6.6 GB), `vivek603/stock-market-data`. Download each into its own empty
directory and read it with `python -I`; never commit or publish any of it.

## 8. Honest expectations

- ML will not conjure an edge. Direction research found none after costs. The realistic gains are volatility and move-size forecasts,
  regime reads, cost prediction, strike selection and tighter sizing.
- Most models will fail promotion. A failed gate is a result, recorded as one.
- The paper profit so far is a short, volatile sample. It is encouraging, not evidence. Judge by sleeve and by session, on forward records.
