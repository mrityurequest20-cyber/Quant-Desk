# The asymmetry scout: finding trades that can pay several times what they risk

Status: **design and diagnosis only (31 Oct 2026).** No code, no config, no limit, no gate and no workflow changes. The
scout, when built, is **shadow-only**: it places nothing, sizes nothing and changes nothing the desk reads.

## 1. The question

The owner's ask: the desk's costs keep eating its gross profit, so find the trades where a win is worth several times the
risk, and say what the normal desk does not do that keeps it from taking them.

## 2. What the paper journal shows (measured, descriptive, small)

Source: the closed trades in the paper journal, 12 to 30 Oct 2026: **36 trades, 14 sessions**, all long index options (35
single options, 1 spread). This is the desk's own paper record, not a clean sample; it motivates the question and is **not
evidence for any rule**. Nothing below was tested.

| Fact | Number |
|---|---|
| Net P&L / fees paid / gross before fees | +₹12,123 / ₹4,712 / ₹16,835, so fees are **28% of gross** |
| Fee per round trip | ₹131 on average (₹72 to ₹267); about **1.3% of the money risked** per trade (≈₹10,000) |
| Mean / median R per trade | **+0.03R / -0.20R** (R = the planned loss) |
| Best / worst trade | **+2.16R** / -1.07R |
| Planned underlying reward:risk | median, 25th and 75th percentile all **2.00**; 28 of 36 at 2 or more, **4 of 36 at 3 or more** |
| Exits | 17 `time_exit` (-0.13R, -₹19k), 9 `invalidation` (-0.59R, -₹55k), 3 `premium_target` (+2.05R, **+₹60k**), 3 `underlying_target` (+0.84R), 3 `square_off`, 1 `premium_stop` |
| Winners / losers | 15 at +0.77R on average / 21 at -0.50R |
| Losers that had been 0.5R up first | 14% (median best open profit on a loser: 0.15R) |

Read plainly:

1. **The cost problem is a thin-edge problem.** A round trip costs about the same as it always did (~₹130). It is 28% of
   gross because the average trade earns only ~₹470 gross. A 3R winner is ~₹30,000 gross against ₹130 of fees: cost
   stops mattering when the winner is big, and matters a lot when the average trade makes 0.03R.
2. **Three trades made the whole profit.** The three `premium_target` exits (+₹60k) are bigger than the net result
   (+₹12k). Without them the desk lost about ₹48k over the period.
3. **No trade can win much more than 2R by construction** (next section). The best of 36 was 2.16R.

## 3. What the desk does not do (each point checked in the code)

| # | Not done | Where | Effect |
|---|---|---|---|
| 1 | **Never looks for large moves; every setup gets the same target.** Armed setups use a fixed `reward_risk` (2.0 for `trend_break` and `vwap_trend`, 1.5 for `orb`, the range width as a floor); the target is `fill ± max(reward_risk × risk, min_move)` | `playbook.py` `add(...)`, `fire()` | Planned R:R is 2.0 on nearly every trade regardless of the day, the range, the volatility regime or the room to the next level |
| 2 | **Wins are capped at about +2R in the option too.** Stop -30% of premium (1R), take-profit +60% of premium (2R), same for all four directional setups | `config/quantdesk.yaml` `playbook.*` `premium_stop`, `premium_target`; `engine.py` exit order | A trade that would have run 4R is closed at 2R |
| 3 | **No runner, no trail, no partial exit.** Each trade is all in, all out | `engine.py` exit rules (`invalidation`, `premium_stop`, `premium_target`, `underlying_target`, `breakeven_stop`, `time_exit`) | The right tail is cut off even when the trade is working |
| 4 | **A 45-minute "no progress" exit.** If the option has made less than 10% of its premium at minute 45 (60 for some setups) it is closed | `engine.py` `time_exit`; `time_stop_min` | 17 of 36 exits. Slow trends are stopped out before they pay; the winners that hit the target did so in a median 22 minutes |
| 5 | **Does not rank candidates by asymmetry.** It takes armed setups that clear a very low bar: EV ≥ ₹40 after costs and ≥ 0.05R, conviction ≥ 0.45 (0.55 for `trend_break`) | `quant.min_ev_inr`, `quant.min_ev_r`, `analyst.min_conviction`, `playbook.py` | Mediocre 2R setups and potentially large ones are treated the same |
| 6 | **Two instruments, four trades a day, two open.** No stocks, no other indices | `intraday.underlyings`, `risk.max_trades_per_day`, `risk.max_open` | The choice is among the few setups two indices arm in a day, not among every liquid F&O name; the shadow lab's stock runs show how much wider that pool is |
| 7 | **Deliberately skips expiry day (0-DTE)** and buys 0.45 delta options | `intraday.expiry_min_days: 1`, setups' `long_delta` | No cheap convex tickets, where the biggest percentage moves happen (and the fastest decay) |
| 8 | **No expansion score.** Nothing scores compression followed by expansion, event days, a gap-and-go open, or a volatility forecast above the implied one. The nearest things are `trend_break`'s tight-range filter (30-minute range ≤ 7.5 × ATR5), a pass/fail test, not a score; the HAR forecaster is shadow-only | `playbook.py` (no squeeze/expansion state found by search), `quant.vol_forecast.mode: shadow` | The desk cannot tell a day that can move 3 to 5 risk-units from one that cannot |
| 9 | **No measurement of "room" for a trend trade.** The distance from entry to the next real obstacle (previous day high/low, opening range, value-area edge, round number) in units of risk is not computed. Only the value-area fade checks that its target (the POC) lies ahead with room | `playbook.py` (the one "room" test is in `va_reversion`) | A 2R target can sit right under a wall |

Two things that are **not** the cause (checked, so they are not guessed at): the structure (35 of 36 were single options,
so a spread is not capping the payoff) and the brokerage rate (about ₹130 a trade, unchanged).

## 4. Break-even arithmetic (why "high reward:risk" is not free)

With the stop at 1R and cost c ≈ 0.013R, a hit-or-stop trade with target k·R needs a hit rate above (1 + c) / (k + 1):

| Target k | 2R | 3R | 4R | 5R | 6R |
|---|---|---|---|---|---|
| Hit rate needed | 33.8% | 25.3% | 20.3% | 16.9% | 14.5% |

A far target is only worth taking where the chance of getting there is *higher than the market's price for it*. That is
the whole job of the scout: **identify the situations where the distribution of favourable moves has a fat right tail**,
and prove it on data it was not tuned on, before any desk rule changes.

## 5. The design

**Name:** asymmetry scout. **Job:** for every candidate setup, estimate whether it can reach k times its risk (k = 2, 3, 4,
6) before its invalidation, rank candidates by that, and **grade itself afterwards** on what the market did.

**Inputs (all point in time):** room to the next 1, 2 and 3 structural levels in units of risk; range compression and
expansion (range width and ATR relative to recent sessions); implied against forecast and realised volatility; day type,
gap, time of day, days to expiry; breadth and index-heavyweight state where recorded. Option side: on recorded real quotes,
the net payoff multiple of a far-out-of-the-money or spread ticket after real bid/ask and the statutory charges.

**Label (pre-registered before any result):** first passage. `reach_k` = 1 if the instrument's price reaches k × planned
risk in the trade's direction before touching the invalidation, within the session; stop wins ties; bars from the one
after the firing bar only. This extends the shadow lab's existing labelling; it needs no new data.

**Where it runs:**

| Stage | What | Gate to the next |
|---|---|---|
| S0 | This document (diagnosis, design). Docs only | review, CI |
| S1 | A pre-registered spec `asymmetry_scout_v0`: the candidate screens (a short, fixed list), the label, the pass rule (hit rate above the break-even in §4 with a lower confidence bound, after costs), the power calculation with session clustering, the kill rule, the disclosure of §2 (the idea came from reading 36 paper trades). Committed **alone**, before code or results | independent research review, CI, merge |
| S2 | Add the `reach_k` labels and the candidate features to the shadow lab (`shadow-replay`). Offline, no desk path | independent risk review, CI |
| S3 | One locked-test read on the lab corpus (index history and stocks) | pre-registered rule only |
| S4 | If S3 passes: the scout scores live candidates in shadow on the recorded tape and real quotes, journaled, never traded | graded on forward sessions |
| S5 | Only after S4: a **separate, independently reviewed proposal** for any desk change (for example a runner leg or a longer time exit on the screens that earned it), paper only | owner and reviewers |

## 5b. Scope widened (31 Oct 2026): not the desk's eight strategies, and a journal for December

The owner's instruction: the scout is **not limited to the desk's eight strategies**. It takes whatever trade it wants in whatever strategies exist
in the market, and makes its own. So the scout has three parts (PR #159):

1. **Any-minute baseline (`scout`)**: a candidate every 5 minutes, both directions, one uniform stop. The yardstick: what blind entries do.
2. **A strategy library (`scout-lab`)**: about 20 market-standard intraday strategies (opening-range and prior-day breakouts, range and
   Donchian breaks, VWAP and EMA trend plays, pullbacks, gap-and-go and gap reversal, opening-drive pullback, NR7, squeeze release, RSI and
   Bollinger reversion, failed breakdown, momentum ignition, pivot bounce, an afternoon trend), each with **its own structural stop**, each
   run over every index and stock and scored under **seven exit policies** (fixed 2R/3R/4R/6R, a 1R trailing exit, stop-only to the close,
   the desk's 45-minute exit).
3. **A rule miner**: random conjunctions of 1 to 3 conditions over 19 point-in-time features (and the strategy flags), fitted on the early
   years and judged on the later ones, **charged for every rule tried** and compared with the identical search on outcomes shifted inside
   each session (the null). New strategies are made this way, not written by hand.

Guards against fooling ourselves: R capped at 10 before any average; the median and the share of profit from the best 1% of trades shown;
a Bonferroni bar over strategy x policy cells (given for this run's cells and, beside it, for this run plus every earlier recorded run's); the null for the miner;
the sealed sessions (2023 on) **refused** by the code (an index run must name a last day (`--to`) before 2023-01-01; it is not silently shortened, and a grid file or a
read-out that holds sealed days is refused too). Standard errors are clustered by **day**, because NIFTY and BANKNIFTY of one day are one market.

**The journal.** Everything the scout does goes into one accident-evident, append-only log (hash-chained: an edit or deletion in the middle is found by `scout-log verify`; a cut tail or a rewrite that recomputes the hashes is not, and the time and author are self-asserted, so the head hash that every entry prints is copied outside the file before any claim rests on it) (`scout-log`, `quantdesk/intraday/scoutlog.py`, on the
desk's own `ChainLog`): every run with its parameters, code commit and data digest; every observation with its numbers and caveats; every
hypothesis with a status that later entries move on (never edit, always append); every decision and plan. It keeps a **running total of
everything tried**, because a claim made in December must be judged against all of it, not the last run. Entries hold aggregates and
parameters only, no raw prices. Written under `runtime/intraday/scout/`, which the desk's journal save already carries to the `journal`
branch once the scout runs on the runner; until then a snapshot is kept on a `scout-journal` branch.

**December.** The owner wants the full review then, with meaningful data. By then the forward days (index bars from the desk's tape, the
daily stock minutes) and the sealed sessions give the one confirmatory test, pre-registered against the running trial count.

## 6. Hard limits

- No order, no broker, no credential, no live trading. Paper only.
- No limit or gate is loosened. Position sizes, loss limits and the stale-feed halt stay as they are.
- Source minutes used offline are third party (`external_unverified`): the result is a research candidate, never evidence for a
  gate, a promotion or a profit claim. Only recorded real-quote sessions may support an option-P&L statement.
- A failed or inconclusive scout is a result: it is reported as such and the desk stays as it is.

## 5c. What the scout does not know (disclosed limits, 31 Oct 2026)

- **It is the exploratory step, not S1.** Section 5's S1 (a pre-registered spec, committed alone) is still ahead of any claim. Nothing the scout prints is confirmatory: its
  tables, cells and mined rules are hypotheses, and the confirmatory test is one pre-registered read on the sealed index sessions and forward stock days (December),
  judged against everything the journal says was tried (cells, mined rules, null searches and read-out looks).
- **The later-years slice is spent.** 2021-2022 is looked at by the leaderboard, the miner and the read-out tables in turn, so it stops being a holdout after the first look.
  The sealed 2023-on sessions are the holdout, and the code refuses them.
- **Cost.** Section 4's break-even uses c about 0.013R (the desk's measured fee per trade against the money risked on an option). The scout instead charges a flat
  **0.05R, assumed, not measured**, on underlying R: a real option cost per R varies with the stop distance. The two are different in kind and neither is measured on this data (neither includes a measured spread or slippage), so which is larger is not known. A "net R" column
  counts every trade that does not reach k as a full -1R, so it is a lower bound (trades that end at the close are marked above -1R in the lab's fixed-exit columns).
- **R cap.** R is capped at 10 before any average. That clips winners only (conservative for a mean, but it works against the right tail the scout is looking for), so
  the median and the best-1% share are shown beside it.
- **Fills.** Stops fill at their level with no gap risk; entries are at the next minute's open with no latency. The first minute of a session is required: a session without
  it is left out, never filled from a later close.
- **The 20 strategies were written by hand after the first any-minute run had been read.** Their constants (stop floor and cap, cooldown, thresholds) were not chosen
  blind, so the family they come from is larger than the 20 cells counted. The cell count understates the real number of choices.
- **The miner's null** shifts outcomes inside each session. It therefore tests within-session information only; day-level features (gap, opening-range width, weekday)
  stay tied to the session's outcomes in the shifted data, so for a rule built on them the null is conservative and its share is not a p-value. With n null searches the
  smallest share is 1/(n+1).
- **Stocks.** The stock set is the release's currently liquid F&O names over a few recent sessions: a liquidity (and so survivorship) selection, descriptive only, with the
  same assumed cost.
