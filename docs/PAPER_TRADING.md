# Paper trading by hand: the owner's runbook

**Paper money only.** Nothing here can reach a broker. Real money needs the owner's separate, explicit yes, and is not built.

## The picture

```
Build tab (you)  ->  relay queue  ->  paper runner (GitHub Actions)  ->  risk gate  ->  paper broker  ->  ledger
                                              ^ the gate decides; the app and the runner only carry the order
```

* You choose and size a trade in the **Build** tab (the market read, the news and the ideas are above the builder), write **why**, review it, and send it.
* The **paper runner** (started by the scheduler on trading days at 06:00 IST and running to midnight, in four parts) takes it through the risk gate within seconds, fills it at the **offer** (a buy) or the **bid** (a sell) with the real costs, and writes it into a hash-chained ledger.
* The **Paper** tab shows the account, the positions with your thesis, the orders and why any was refused, and the **kill switch**.

## The very first time (once, before the first trade)

The runner refuses to start without a saved account (a lost state must never silently begin the history again). Start it once by hand:
GitHub, Actions, **Paper runner**, Run workflow: tick **new_account**, set **handover** to about 5 minutes from now (IST, HH:MM), leave **until** as it is. When it is green, the account is on the relay and every later start finds it. Check the Paper tab shows an equity of 5,00,000.

## Placing a trade

1. Build tab: pick the index, the expiry and a structure (or use *Which strategy now, and why*, *Design one for this view* or *Ideas for your view*). Only structures the paper desk can open show **Send as a paper order**: long options on NIFTY, BANKNIFTY, FINNIFTY or MIDCPNIFTY, and, since 8 Nov 2026 (`paper.allow_short_legs: true`, the owner's order), **hedged packages with sold legs** (verticals, condors, butterflies): they go as ONE order, every leg opens together or none does, and the gate judges the worst case (a naked short call or a calendar is always refused; the long that covers a sold option cannot be sold before the sold option is bought back). A sold option never goes alone: only as a leg of a package. If the switch is turned off in the config, a structure with a sold leg is a what-if again.
2. Write the **strategy name** and the **thesis**: why this trade, now, and what would make you wrong (at least 20 characters; it is kept with the trade).
3. **Review order**: each leg, its price limit (two ticks or 2% above the offer you saw), the most you can lose. **Send paper order**.
4. Open the **Paper** tab. A fill shows under *Orders* as `filled`; a refusal shows the gate's reasons.

## What a refusal means

| It says | What it means |
|---|---|
| the quote is N s old / no usable two-sided quote | the price was not fresh (30 s) or had no bid and offer: wait, or pick a busier strike |
| it would risk X (the whole premium plus fees), over 2.5% of equity | too big: fewer lots |
| … would be lost against a loss budget | the open positions plus this one could take equity under today's 5% floor or the 10% drawdown floor |
| closed / does not trade today | outside 09:15-15:30 IST or a holiday |
| expired (waited N s) | the runner was not running for 2 minutes after you sent it (for example a hand-over at 11:50, 17:40 or 23:30): nothing was bought; send it again |
| the offer is X, above your limit | the price ran away from what you saw: nothing was bought |
| new orders wait: the relay could not be given the latest fills | the runner could not save to the relay for 30 s: exits still work |

## The brakes (you do not have to remember them)

* **Daily loss limit 5%** of the day's starting equity: no new entries for the day and everything held is sold.
* **Drawdown halt 10%** below the high-water mark: no new entries and everything is sold until **you** clear it (it is deliberately not in the app: tell the assistant).
* **Kill switch** (Paper tab, two taps): nothing opens and everything held is sold, until you resume.
* **15:20 IST:** anything expiring today is sold at the bid and not bought; **15:31:** what could not be sold is cash-settled at the index price.
* There is **no cap on the number of trades**: only the loss limits.

## If something is red

* **Paper tab says the runner has not reported:** Actions, *Paper runner*: is a run in progress? If the last one is red, open it: the log says why (the relay did not answer, a saved account did not verify, or two histories disagree). Orders wait two minutes and then expire, nothing is filled meanwhile. The scheduler starts it again within ten minutes up to three times a day; or Run workflow by hand.
* **11:50, 17:40 and 23:30 (a few minutes each):** the runner changes hands (a new job starts). An order sent then expires; send it again.
* **What trades when:** the runner is up from 06:00 to midnight, but the risk gate decides what can trade: NSE F&O from 09:15 to 15:30. MCX and currency are refused until their costs and holiday calendars are verified in the config; until then the evening is watched, not traded.
* The ledger backup on the `paper-ledger` branch is **off** (this repository is public: it would show every thesis and position). To turn it on, set the repository variable `PAPER_LEDGER_BACKUP` to `yes`.

More: docs/RECORDING.md ("The paper runner", "Running the paper runner"), docs/LIVE.md (the relay's routes).

## Special sessions (Muhurat trading)

On a day the exchange opens for a special window (Diwali Muhurat trading, 8 Nov 2026, 14:20 to 15:30 IST, NSE circular NSE/CMTR/76941), `config/quantdesk.yaml` `calendar.special_sessions` names it. That one entry opens the **paper gate** for NSE/BSE F&O inside the window and makes the **relay's Kotak poller** run inside it (`deploy/cloudflare/kotak.js` `SPECIAL_SESSIONS`; a test fails if the two disagree). Recorders, health reports, the scheduler and the watchdog do not know about it, so on such a day start what you need **by hand** (Actions, Run workflow):

1. **Kotak universe** (the option chains for the Build tab), any time before the window.
2. **Kite tick recorder**: `first_until` 15:35, `second_until` 15:36. It logs in to Kite by itself.
3. **Paper runner**: `handover` 14:05, `handover2` 15:35, `handover3` and `until` 15:36, leave `new_account` off.

Nothing else changes: the same risk gate, the same limits, paper money only.

## MCX and currency futures (owner's order, 13 Nov 2026)

"First, enable the MCX and the currency in the paper trading." The paper desk trades the **near-month futures** the Markets page
shows: crude oil and its mini, natural gas and its mini, gold and gold mini, silver and silver mini, copper, and USD, EUR, GBP and
JPY against the rupee. Futures only: no MCX or currency options.

**Opening a trade.** Open the instrument on Markets and press **Paper trade**. Then:
- choose Buy (long) or Sell (short) and the number of lots;
- set a **stop** (required) and, if you like, a target;
- name the strategy and write the thesis.

The ticket shows the price you would get, the risk to the stop, the margin and the reward to risk. The runner's gate
(`RiskGate.check_future`) decides.

**The rules:**
- **The stop bounds the risk.** The loss to the stop, plus a 0.1% slippage allowance and both sides' fees, must fit in
  `risk_per_trade` (2.5% of equity), exactly as an option's whole premium must. A stop more than 10% away is refused as a typo.
- **Margin, not cash.** A futures fill moves cash only by its fees; the profit or loss arrives on the close. The margin (lot x
  price x the contract's rate, from Zerodha's NRML rates) must fit in the equity left free. The loss budget counts each open
  future at its stop.
- **Intraday only.** Every futures position is closed 5 minutes before its segment's close: currency at 16:55; MCX at 23:25 (23:50
  while the US is on daylight saving). No new entry in the last 15 minutes. Nothing is held overnight, across a roll or into a
  delivery period.
- **Near expiry.** No new entry in an MCX contract's last 5 trading days (a tender or delivery period may start), or in a
  currency contract on its last trading day.
- **Contract identity.** Which contract month the board shows comes with each quote (`e`, from the feeds' instrument lists) and is
  recorded on the position. If the board's name moves to another month, the position has no price rather than a wrong one.
- **Stops and targets** are watched by the runner every cycle and closed at the bid (long) or the offer (short). The stop and
  target are in the sealed ledger row, so a restart rebuilds them; a saved file with a different stop fails verification.
- **Fills** are at the touch: a long at the offer, a short at the bid. The size can be at most what is displayed there.
- **Costs** (`costs.segments.mcx_futures` and `cds_futures`, from Zerodha's charges page):
  - MCX: commodity transaction tax 0.01% on the sale.
  - Currency: no STT.
  - Each also pays its exchange's charge and stamp duty on the buy.
  - Both pay brokerage of 20 rupees or 0.03% (whichever is lower), SEBI's fee and GST.
- **Calendars:** both segments are verified for 2026. On an NSE holiday that MCX does not list as a full closure, MCX trades only
  its evening session (from 17:00), the conservative reading. **2027 trades on neither until its holiday lists are entered.**

**What is not verified at the source:** the lots, margins, charges and holidays come from Zerodha's published pages (13 Nov 2026).
The exchanges' own sites refused the session that set this up. Check them against MCX's and NSE's contract specifications and
circulars.

**Not built:** AUTO does not trade futures; they are the owner's tickets only. There are no MCX or currency options.

## MCX and currency options (owner, 13 Nov 2026: "treated in the same way" as index and stock options)

**Data:**
- **MCX option chains** come from Fyers (`options-chain-v3`, three chains a cycle, in turn).
- **Currency options** come from Angel One: one FULL quote call gives price, OI and five-level depth; the window follows the price
  every half hour.
- **Kite** carries both in its hours, from its instrument list.
- **Routing:** they have their own route labels, `mopt` (Fyers, Kite, Kotak) and `copt` (Angel One, Fyers, Kite, Kotak), so each segment
  is shown from the broker the owner chose for it, futures and options alike. Names are the same as NSE options; a currency strike has
  decimals (`USDINR20NOV2684.25CE`).

**Trading:** from the chain and the strategy builder exactly as NSE options, by the owner or by AUTO v2:
- **Lot:** the future's.
- **Costs:** their own schedules (`costs.segments.mcx_options`: CTT 0.05% on the sale, MCX 0.0418%, stamp 0.003%;
  `cds_options`: no STT, NSE 0.0311% + IPFT, stamp 0.0001%; brokerage 20 rupees flat).
- **Slippage:** in each contract's own tick (`opt_tick`).
- **Pricing:** off the near-month future at rate 0 (Black-76: an option on a future).
- **Expiry:** sold from 15:20 on the trading day before expiry, never held into it (an MCX option turns into the future at expiry; a
  currency option expires at 12:30).

**AUTO v2's hours by segment:**

| Segment | First entry | Last entry | Day strategies out by |
|---|---|---|---|
| NSE | 09:20 | 15:00 | 15:15 |
| Currency | 09:10 | 16:15 | 16:40 |
| MCX | 09:10 | 22:45 | 23:10 |

A currency option's premium floor is 20 of its ticks.

## The market read (`quantdesk/paper/marketread.py`)

For each underlying, every 30 seconds, from the options, the future and the spot:

| Group | What it reads |
|---|---|
| Positioning | put/call ratio (OI, volume), max pain, the call wall (resistance) and the put wall (support) |
| Flow (against a quarter of an hour earlier) | the future's build-up (long build-up, short build-up, short covering, long unwinding); near-the-money call against put writing; the put/call ratio's change |
| Expectations | the straddle's implied move, skew (out-of-the-money put over call volatility) and its change, the near against next expiry's volatility, the future's premium (Kalman-smoothed, below) |

**Combining them (Bayesian evidence):** each reading is a signal s in [-1, 1] with a weight w (a log-likelihood ratio), and
P(up) = 1 / (1 + exp(-sum w*s)).
- **A vote at 0.65 or 0.35.** A read votes up at P(up) 0.65 or more and down at 0.35 or less, as one more vote in AUTO v2's view.
- **The rule is unchanged:** at least two readings agree and none disagrees, so the read alone never opens a trade.
- **The weights are priors**, set from what each reading is known to mean, not fitted.
- **Calibration:** every read is scored against what the future did over the next quarter hour (the Brier score: 0.25 is a coin toss,
  lower is better; `read_calibration` in the runner's state). That record will show which readings carry information.

## Regimes and change points (`quantdesk/paper/regimes.py`)

**Hidden Markov model.** Each underlying's one-minute log returns are modelled as coming from one of three hidden states, calm, active
and stressed, each with its own Gaussian, moving between them by a Markov chain.
- **Fitting:** Baum-Welch (expectation-maximisation with scaled forward-backward passes) on the last 390 minutes, every five minutes.
  Between fits, one forward step a minute gives P(state now | every return so far). The states are named by their variance.
- **Model selection:** the three-state model must beat a single Gaussian on the Bayesian information criterion (BIC = -2 log L + parameters x
  log n). If it doesn't, the series is one regime and nothing is called "stressed": reading noise as regimes is the classic way an HMM
  misleads.

**CUSUM change points (Page).** On returns standardised by a robust scale (1.4826 x the median absolute deviation):
- a two-sided cumulative sum for a shift in the mean (k = 0.5, h = 5);
- a one-sided sum for a rise in volatility, measured around an exponentially weighted running mean so a steady drift is not read as
  turbulence (k = 1, h = 10).

Calibrated on pure noise: about one false alarm per few hundred minutes. Nothing is tested before 30 returns exist.

**Use in AUTO v2:**
- **Drift change point.** A drift change point within the last 15 minutes is one more vote in the view, under the unchanged rule (at
  least two agree, none against), so it never opens a trade alone.
- **Stress or a volatility change point.** The stressed state (P >= 0.6) or a volatility change point puts the underlying in the event
  regime: no short-volatility structure is opened.
- **In the app:** the state and any fresh change point show on each underlying in the strategy lab.

## Kalman filtering (`quantdesk/paper/kalman.py`)

One model, used twice: a **local linear trend**, observation = level + noise, level moves by a slope plus shocks, slope wanders slowly.
The filter estimates (level, slope) after each observation; the slope over its standard error is a t-statistic.
- **No hand-set noise.** The three variances come from **maximum likelihood** (the prediction-error decomposition, concentrated over
  the overall scale, so only two ratios are searched).
- **Trend.** On each underlying's log one-minute closes (refitted every 5 minutes on the last 390). Its t-statistic, at |t| >= 2, is
  AUTO v2's **price vote**, in place of the raw five-minute move. On driftless random walks it voted 3.5% of the time (two-sided 5%
  nominal). "Flat" now also needs |t| < 1.
- **Price is one vote.** The Kalman trend, the raw move and a CUSUM drift all read the same prices. Only one of them counts (the trend
  once fitted, else the raw move, a CUSUM drift only when neither votes), so price alone can never satisfy "two readings agree".
- **Futures premium.** (future / spot - 1), read every 30 seconds, is smoothed the same way (fitted to the last two hours). The market
  read takes its change from the smoothed premium. On a simulated noisy premium the smoothed series was under half the raw prints' error.

## Extreme value theory: tail risk (`quantdesk/paper/tails.py`, `quantdesk/premarket/tailrisk.py`)

**The model (conditional EVT, McNeil and Frey 2000).** Each day's return is standardised by the volatility known the evening before (EWMA,
lambda 0.94). Each tail of the standardised returns beyond its 95th percentile (90th for a short history) is fitted with a **generalised
Pareto distribution** by probability-weighted moments; the body is the empirical distribution. Today's distribution = today's volatility x
history's shape. Horizons of 1, 3, 5 and 10 sessions are fitted on their own returns.

**Where the history comes from.** Built once a morning by the pre-market brief (`tails.json`, reused all morning), ten years where it exists:
- indices: NSE's official closes;
- stocks: Yahoo, adjusted for splits;
- MCX: a proxy, the international future in rupees (WTI x USD/INR for crude, COMEX gold x USD/INR for gold), with non-positive prices and
  roll steps dropped;
- currencies: Yahoo's spot rates.

**Measured, on distributions with known tails** (`tests/test_tails.py`):
- **The 99% level is right.** On Student-t(4), the 99% VaR is within 6% of the truth and the 99% ES within 8%; the normal model with
  the same variance understates both by 12% to 28%.
- **Backtest.** GARCH returns with t shocks pass their own out-of-sample backtest: 500 days, Kupiec's test.
- **Known bias.** The 99.9% level comes out about 17% too low, by moments and maximum likelihood alike (the t's tail approaches its
  power law slowly). The desk works at 99%.

**Use: the tail check.** A structure that sells options (bull put spread, bear call spread, iron condor, iron butterfly) sells a tail the
shadow record cannot price: a few weeks of trades rarely hold the day that costs most. Before one opens (shadow, live or on the day plan):
- **The test.** Its expected value to expiry is integrated over the fitted distribution. The volatility used is never below the last
  hour's realized volatility.
- **The rule.** It opens only if that expectation, net of costs, is at least 0R: the premium must pay for the tail.
- **No model, no check.** An underlying with no tail model is not checked, and the day plan names it.

**In the app:** each underlying's 1-day 99% expected shortfall, both sides; the brief's summary gives NIFTY's and BANKNIFTY's.

## The hierarchical record (AUTO v2's `Lab`)

A strategy's record is read through a **multilevel normal model**, fitted by empirical Bayes every time the record changes:
- **Levels.** Strategy mean R ~ N(its structure's mean, tau^2); each structure's mean ~ N(0, 0.25^2), anchored at zero edge after costs.
- **Tau is estimated, not set.** tau, the spread of strategies within a structure, comes from the record itself (DerSimonian-Laird,
  pooled over structures).
- **What it changes:**
  - A strategy with no trades starts from its structure's record instead of zero.
  - A short record is pulled towards its structure's.
  - A long record speaks for itself.
- **Correlated strategies are not independent evidence.** The 180-odd strategies of one structure trade the same market moments with
  other filters and exits. Their combined weight is divided by the design effect 1 + (m - 1) x 0.3.
- **Measured on a simulated record with known truth** (`tests/test_lab_hierarchy.py`): tau is recovered, each structure's sign is right,
  and the error against the true means is under a quarter of each strategy's raw average on short records.
- **The proof gate is unchanged:** 8 shadow trades of its own and a positive draw before any paper money.
- **In the app:** each structure's shared estimate, and the order thesis gives the strategy's shared estimate next to its own average.
- **Where it is kept:** on the private relay, in one stored value of at most 110,000 characters. Since 14 Nov 2026 the record is written as plain JSON while
  it fits and, past that, zlib-compressed into the same value (`{"v": 1, "stats": {}, "z": ...}`; the relay's checks are unchanged), so the whole catalogue
  with a record for every strategy fits in about 70,000 characters instead of losing a third of it. Read back, a compressed record may not inflate past 8 MB
  (storage is not trusted); only if even the compressed record were too large would the thinnest records be left out, the busiest kept.
  **Before rolling back** below 14 Nov 2026's commit 6a06ac5: older code reads the compressed record as empty and its next save would overwrite it, so keep a
  copy of the stored record first. A stored record that cannot be read at all (corrupted or tampered: only the runner's ingest key can write it) is started
  from zero and overwritten at the next save, as before.

### Tagged with the market (since 14 Nov 2026; docs/EVOLUTION.md, phase 1)

Every closed shadow trade is also added to its structure's record in today's market regime (the brief's fingerprint key, `unknown` without today's brief): `reg`, regime -> structure -> trades, sum of R, sum of R squared, wins. The latest 400 closes are kept whole (date, strategy, underlying, R, regime). Both live in the strategy record on the relay, private like the rest of it, and are read back validated (a regime or structure that is not a real one is dropped). A live trade's thesis ends with the market it was taken in. Nothing chooses by regime yet: that is phase 3, after a pre-registered test. The Paper tab's **Market regime** panel shows today's regime and each regime's trades and best structures.

## The strategy builder: every structure, which one now and why, and designs of its own

The app's Strategy tab (an instrument page) builds any defined-risk option structure on the live board. Owner, 13 Nov 2026: "The strategy builder must have access
to the every strategy which it can reason it out when to use which and create it's own if required."

**Every structure.** There are 16 written structures (the AUTO v2 catalogue's), and the legs can be any size: a butterfly's body is 2 lots. You can also use custom legs (any
number, any strike, any ratio), and the desk's own inventions (from AUTO v2's record) appear beside the written ones.

**Which strategy now, and why** (`QB.advise`, open under the structures). Every structure is scored against the desk's read of the underlying: AUTO v2's view, volatility
rich or cheap against realized, the event regime, expiry tomorrow, its P(up), the Kalman trend, and AUTO v2's shadow record for that structure. Each point is a written
reason, for or against:
- **Fit with the view:** fits (+3); near, e.g. a credit spread when the view is a range (+1.5); against (-4).
- **Volatility:** rich favours selling options and cheap favours buying them (+-2).
- **Event:** in an event, no volatility is sold (-5); a long-volatility structure gains (+1).
- **Expiry tomorrow:** decay favours a range sale and costs a bought option (+-1).
- **Conviction:** strong conviction (P(up) 0.7 or more, or 0.3 or less) favours an uncapped structure, mild a capped one (+1).
- **Trend:** the Kalman trend agrees or disagrees (+-1).
- **The desk's record:** 5 x mean R, capped at +-2, once there are 8 trades.

Below a best score of 3 the advisor says nothing fits and that standing aside is a position. You can replace the desk's view with your own.

**Design one for this view** (`QB.design`). It mutates the structures that fit the view (move a strike, add a wing, drop, double or flip a leg). It keeps defined-risk
results with up to 4 legs and 6 lots, priced on the board, within the per-trade loss limit.
- **Ranking:** by the average result IF THE VIEW IS RIGHT, per rupee of worst loss, after costs. "Right" is a zone at expiry built from the market's own expected move
  (up: the price to +1.5 moves; range: within half a move; big: beyond one move on either side). An either-way view must pay on BOTH sides.
- **Shown with it:** what the design does if the view is wrong. When a design is a structure that already has a name ("Bull call spread, 4 strikes wide"), it says so;
  otherwise it is "a structure of its own".
- **What it is not:** neither the advice nor a design is a forecast. At the market's own volatility, options are a fair bet before costs; the edge is the view.

## Strategy liberty and the inventor (`quantdesk/paper/inventor.py`)

**The written catalogue** now has 16 structures, 3,132 strategies:
- **The original ten:** long calls and puts, debit and credit spreads, iron condors and flies, straddles, strangles.
- **New:** call and put butterflies, broken-wing butterflies, call and put ratio backspreads.
- **Multi-lot legs:** a leg's size can be more than one lot (a butterfly's body is two).

**The desk writes its own.** Every morning the inventor mutates the structures of the best records so far, the way a trader tinkers: move
a strike, add a wing to cap a sold option, drop a leg, double one, flip one. A child is kept only if it is:
- **defined risk** (no net short call);
- **tradable** (1 to 4 legs, at most 6 lots, strikes within 4 steps of the money);
- **new in shape:** its payoff, made level- and scale-free, matches nothing known. A call condor is an iron condor by put-call parity,
  so it is not "new".

Its view is read from its own payoff.

**Inventions are held to a higher bar:**
- **More trades.** An invention needs 12 shadow trades of its own, not 8, then a positive Thompson draw. A desk that writes many
  strategies and keeps the best is fitting noise unless the bar rises with the number of tries.
- **Their own family.** Each invention starts its own family in the hierarchical record, anchored at zero edge.
- **Retirement.** One whose record is clearly negative (24 trades and mean + 2 sd below zero) is retired.
- **A cap.** At most 60 live; past that, the worst record goes first.
- **Persistence.** Inventions survive restarts in the stored record; tampered entries are dropped.

**What does not change:**
- **Defined risk.** Every structure must have a finite worst case, because that is what keeps the 2.5%-a-trade limit meaningful. A
  structure that could lose without limit is refused whoever writes it.
- **The limits.** The risk limits and the 1-lot size are untouched.

**The cost gate.** A structure whose round-trip costs exceed 30% of its risk is not opened. It is born at -0.3R, so a 0.5R stop means nothing.
A one-strike NIFTY butterfly or iron fly costs about half its risk to trade; the two-strike ones pass.

## The news model (`quantdesk/paper/newsmodel.py`, `quantdesk/premarket/analogs.py`)

A story moves instruments through channels, not only by naming them. Each story is read in three steps:
1. **Subjects:** crude, gas, gold, silver, base metals, the rupee, the dollar, US yields, the Fed, the RBI, inflation, growth, foreign
   flows, geopolitics, tariffs, China, Wall Street, the monsoon, IT spending, auto sales, the US FDA, telecom tariffs, F&O rules,
   fintech rules, bad loans, capex, electronics, cigarettes.
2. **Direction:** the direction word nearest the subject. "Crude jumps" is up; "rupee hits record low" is the rupee down; "RBI cuts"
   is rates down; "ceasefire" is geopolitical risk down.
3. **Channels:** each instrument's sensitivity to each subject going up. For example, crude up means:
   - CRUDEOIL +1.0;
   - the rupee pairs +0.3 (a dearer import bill);
   - the indices -0.3;
   - autos -0.2.

   The same story gives every instrument its own score.

**Present:** each instrument's channel score, summed over the last six hours of stories (impact x novelty x a two-hour half-life). A story
naming the instrument also counts by its tone.

**Past:** for each event kind under way (RBI, FOMC, budget, election, geopolitics, oil shock), the brief measures every instrument's own
past episodes, weighting each by how much the market then resembled the market now:
- the 20-session trend in standard deviations;
- volatility against its own past year;
- the drawdown from its 60-session high.

The weighted share of rises is the analogue's P(up). Its effective number of episodes says how much it can be trusted.

**Forecast:** log-odds = 1.5 x tanh(channel score) + sum over events of n_eff/(n_eff+4) x logit(the analogue's P(up)).
- **One vote.** At P(up) 0.65 or 0.35 it is the news vote in AUTO v2's view, under the unchanged two-agree rule. For an index with no
  opinion, AUTO v1's market-wide tone vote stands in. The pre-open plan uses the same model.
- **Event reach.** A high event reaches an instrument if its stories' subjects do (sensitivity 0.3 or more), so crude news reaches the
  rupee pairs. The event regime's reason then names the instrument's own past episodes and the closest dates.
- **Scored.** Every forecast with an opinion is scored against the next hour (Brier, per instrument; "news forecasts" in the app).

**Global markets** (14 Nov 2026). The brief's overnight moves of 18 markets go through the same channels:
- **The markets:** US, Asian and European indices, the VIX, the dollar index, USD/INR, Brent, gold and the US 10-year yield.
- **How a move counts:** each market's move is in units of its own typical day, capped at 3. The Nasdaq is Wall Street, the VIX is US fear, Brent is crude.
- **In the forecast:** 1.0 x tanh(global score / 2), on the brief's own session only.
- **No double counting:** in the pre-open plan an index already has the overnight markets as a vote of their own, so its news vote leaves them out.

**The sensitivities are priors** written from how these markets transmit shocks. The Brier record is what will say which hold.

## Instruments read differently

- **The market read has a profile per class**, each with its own weights and normal put/call ratio:
  - **index:** option OI positioning carries the most.
  - **stock:** OI is mostly calls written against holdings, so the normal PCR is about 0.6 and walls mean less.
  - **MCX:** the future's build-up leads; the chain is thin; no premium is read, since the underlying is the future.
  - **currency:** a future's premium is carry, not sentiment, so it is not read.
- **Each instrument learns its own weights.** Every scored outcome nudges them by online logistic regression, pulled back towards the
  class prior.
  - It learns from one outcome per 15-minute window, so overlapping reads are not counted as many.
  - A signal that works backwards for an instrument can flip sign.
  - The weights are kept with the strategy record across restarts, validated.
- **Thresholds are in each instrument's own volatility.** With the last hour's realized volatility known, a five-minute move votes at
  1.15 of its own five-minute standard deviations, and "calm" is under 1.15 of them. That is 0.10% for NIFTY at 12% a year, about
  0.02% for USD/INR, and far more for natural gas. Until then, the fixed NIFTY-set thresholds.
- **Already per instrument:** the HMM, CUSUM, Kalman trend, EVT tails, trading hours, costs and the news channels.

## Calendars and diagonals (14 Nov 2026)

**The gate's rule.** A sold option in an underlying's NEAREST expiry may be covered by a long option of a LATER expiry.
- **The worst case** is judged at the near expiry. The near legs count at their intrinsic value; the later longs at the least a European option can be
  worth: a call at least S(1 - q t) - K with any dividend yield q up to 2%, a put at least K(1 - r t) - S with any rate r up to 10%, t being the time it
  still has to run.
- **The price range** searched goes up to three times the highest strike.
- **What that costs:** a 1-week NIFTY call calendar's worst case is its debit plus about 1,900 rupees a lot (the dividend allowance at three times the
  strike); a put calendar's, its debit plus about 3,100 rupees (the rate allowance).
- **Still refused:** a sold leg in a later expiry (a reverse calendar), more near shorts than later longs, and selling the later long while it covers the near short.

**The strategy builder** offers the four too: Call calendar, Put calendar, Call diagonal, Put diagonal.
- **Building one:** the later leg goes on the next expiry's chain.
- **What it shows:** the payoff at the near expiry (the later option at its model value) and the worst loss the paper desk will count (the later option at its
  floor).
- **The advisor** reasons about them like any structure, and none is suggested into an event.

**AUTO v2** adds a call and a put calendar (same strike, at the money, near against next) and a call and a put diagonal (sell 1 or 2 strikes out of the money
in the near expiry, buy at the money in the next): 432 strategies.
- **Same treatment:** they are priced at the board's bid and offer and judged by the same worst case, shadow-tested and proof-gated.
- **Exits:** by the near expiry.
- **Events:** a calendar is short the near expiry's movement, so none is opened in the event regime. The market read's "event priced" (the near expiry's
  volatility above the next's) is such a regime.

## Futures in AUTO v2 (14 Nov 2026)

AUTO v2 also trades the MCX and currency near-month futures the paper desk allows (`paper.futures`).

**The strategies:** 12 of them.
- Long when its view is up, short when it is down.
- The stop is 0.5 or 1 day's standard deviation away (the brief's tail-model volatility, or the last hour's realized volatility if larger).
- The take-profit is 1, 2 or 3R, where R is the stop's distance plus the round trip's real costs (mcx_futures, cds_futures).
- Each is shadow-tested at the board's bid and offer, scored in R, and goes live only after 8 shadow trades and a positive Thompson draw.

**When none opens:**
- in the event regime, because an event can gap a future through its stop;
- within the contract's no-entry days before expiry;
- when the board does not say which contract month it is;
- when the book is wider than 0.2%;
- when the stop would be beyond the desk's 10% bound.

**A live entry:** one lot, buy or short, with its stop and target. The runner enforces both, squares it off before the close (futures are intraday) and allows
one position per contract. The pre-open plan stays with option structures.

## The Convexity desk (`quantdesk/paper/convex.py`, 14 Nov 2026)

The owner: "Direction, to be honest, is very hard to understand ... We want to have things of high risk to reward only ... 100, 200, 300, 400, 500, 1000%
return." So this book never forecasts direction. It buys both sides at once and wins when the move is big, whichever way it goes.

**Why it can work, and why blind buying does not:** a bought option makes five to ten times its price when the underlying moves much more than the option's
price assumed. On average, though, options price more movement than follows: that is the premium option sellers earn, and buying every day pays it. So the desk
buys only when one of four tests says the next move is priced **too small**:
- **Cheap options:** the options' move to expiry (implied volatility × √T) is at most 0.8 × what the tail model forecasts over the same trading days.
- **An event priced small:** a scheduled event that touches the instrument is before the expiry, within two sessions. The event's own move is split out of the
  near and next expiries (both contain it). It passes if that day's implied move is at most 0.8 × what this instrument did on past episodes of the same kind
  (weighted to today, at least 3 effective episodes: RBI, FOMC, the Budget, elections). Or, unscheduled: a high news event touching it while the options have
  not repriced.
- **Tails underpriced:** the structure's expected payoff over the fitted fat-tailed distribution (extreme value theory) is at least 1.25 × its cost. Far wings
  live here: they cost a few rupees, and option prices behave like a normal distribution that underweights the tails.
- **A quiet market breaking out:** the last hour's realized volatility is at most 0.6 × the daily forecast, and a fresh CUSUM change point says it has started
  to move (either way; the direction is not used), with the options not yet rich.

Every structure must also be worth at least 0.9 × its cost over the tail model, whatever its test.

**The structures:** a long straddle, a long strangle (1 or 2 strikes out) and long wings (1.5 or 2.5 forecast standard deviations out), each on the near or
next expiry. Every leg is bought, so the most a trade can lose is its premium. 40 strategies (structure × width × test × expiry).

**Sizing (the owner's choices, 14 Nov 2026):**
- 0.5% of the account a trade, premium and fees (₹2,500 on ₹5 lakh);
- at most 3% of the account spent on convexity premium in a calendar month (₹15,000), counted from the ledger, so a restart forgets nothing;
- at most 3 packages open, one per underlying.

The risk gate's own caps (2.5% a trade, 5% a day, 10% drawdown) apply on top, unchanged. On ₹5 lakh an at-the-money NIFTY straddle (about ₹15,000 a lot) does
not fit the stake. Far wings do, and they are the ones that can make 5 to 10 times. When a test passes but a lot does not fit, the app says so.

**Exits (the owner's choice: thirds):**
- a third sold at +100% of the premium (its cost is back);
- a third at +300%;
- the last third trailed: out when it gives back more than 35% of its peak gain;
- after a scheduled event: out 15 minutes after it, before the options' price collapses;
- the options repriced rich before the move came: out if it is not losing;
- five sessions without the move, or the session before expiry: out.

There is no price stop below that: the stake is the stop. One lot cannot be split, so it is trailed whole; two lots sell one at +100%.

**Evidence:** every convex strategy is traded in the shadow book with these exits and scored in R (capped at +20R). It trades paper money only when its family
(the structure) has 20 shadow trades, it has 5 of its own, and its hierarchical average is above zero. A good record here is many small losses and a few large
wins: the hit rate is not the measure, the average R is. Expect weeks of shadow trading before the first live trade.

**Both books trade (the owner's choice):** both are tested in shadow all day, and both go live only by the rules of plan-first trading below (the
day plan, important news, or a change in the live data that holds). Since then, a flat view's premium selling (an iron condor) is never planned or triggered, so it
trades in shadow only. The app's Paper tab has a Convexity
desk panel: the month's spend against its budget, the stake, what is open, what is proven, and which tests pass now on each underlying.

## The scheduled-events calendar (`quantdesk/paper/eventcal.py`, 14 Nov 2026)

The brief lists the next week's scheduled events. Each event touches instruments through the news model's channels. A named symbol is touched fully, and the
Budget or an election touches every Indian equity. AUTO v2 is in the event regime, and sells no volatility, when an event that touches an instrument is close:
- **A high event** (a policy decision, the Budget, an election, OPEC): from 24 hours before to 90 minutes after, if it touches with 0.3 or more. An RBI
  decision tomorrow at 10:00 keeps NIFTY's condors closed today.
- **A medium release** (CPI, the US jobs report, the EIA crude report, GDP, results): from two hours before to an hour after, if it touches directly (0.5 or
  more). The 21:00 EIA report reaches crude, not NIFTY.

Dates marked "by rule" follow the release's usual rule, and a holiday can move one; the owner's `calendar.events` wins. The pre-open plan uses the same regime.

## The news analyser and the event regime

- **The event watch.** The news job gathers the stories' own event types (`intraday/nlp.py`: policy, geopolitics, inflation, growth,
  flows, commodities, currency, and more) into active events: severity from impact x novelty x the type's weight, decayed by its
  half-life; tone from the stories' tones. At severity 2.5 an event is "high". It is in the digest (`events`) and the app's news panel.
- **What happened before.** The pre-market brief measures, from the warehouse's own closes, what NIFTY and BANKNIFTY did on past
  episodes of each kind: the median signed move, how often it fell, the worst, the five-session move
  (`history.macro_history`, `macro_dates.json`). The kinds now include geopolitical shocks (14 episodes, 2016 to 2025) and oil shocks
  (5). The app shows this line beside each event, and AUTO v2 writes it into its reasons.
- **News and data together.** When a high event touches an underlying (geopolitics, policy, inflation, growth: everything;
  commodities: MCX and the indices; currency events: currency), or the options price one (the near expiry's volatility above the
  next's), AUTO v2 is in the **event regime**: it opens no short-volatility structure (iron condor, iron fly), the trade that loses
  most when an event moves the market. Bought volatility and directional spreads stay open to it.
- **Same limits.** The loss caps, sizes and the proof gate are unchanged.

## AUTO v2: the paper desk writing, testing and choosing its own strategies (paper money only)

Since 13 Nov 2026 AUTO runs **v2** (`quantdesk/paper/auto2.py`). Your words: "a system which is sophisticated, advanced ... can take any strategy in its place, create its own strategy, permutation, combination, can trade."

* **It writes the strategies.** Every combination of the following, 1,836 strategies in all, each with a short id that says exactly what it is (for example `IC1.fran.1/0.5.d`: an iron condor one strike wide, flat view, rich volatility, any day, the near expiry, take profit at 1R, stop at 0.5R, out by the close):
  * a market context: direction up, down or flat; volatility rich, cheap or either; any day or the expiry eve;
  * a structure that suits it: long call or put, debit or credit spreads, iron condor or butterfly, long straddle or strangle;
  * a width, an expiry (the near one or the next), a take-profit, a stop, and out-by-the-close or up to three sessions.
* **It tests them.** Whenever a strategy's context holds for an underlying (the four indices and the 20 stocks), it is traded **in shadow**: no money, but at the real bid and offer of every leg, with the desk's real fees, closed by its own exits. Each result is scored in R (profit over the most it could have lost). The record is kept on the private relay, so it grows across sessions.
* **It chooses.** A strategy trades with paper money only after **8 shadow trades**, and then by **Thompson sampling** over a **hierarchical model** of the record (below): a short record is pulled towards its structure's, the best plausible draw wins, and a draw at or below zero does not trade. Capital flows to what has worked and away from what has not.
* **It trades** through the runner and the risk gate like your orders: one lot, a multi-leg structure as one package, sold options only inside a bounded structure. Its own exits close it, with sold legs bought back first. Your hand-placed orders work beside it.
* **What it sees:** direction from the same four readings as v1, and the volatility state: the options' at-the-money implied volatility against the volatility the price has shown over the last hour. Your own research found direction hard to forecast and volatility easier; the catalogue lets the record decide which contexts pay.
* **Where to watch it:** Positions → Strategy lab (the record's leaders, what is live, what it sees now), and the 15:50 push.
* **Bounds:** the risk gate's loss caps only (2.5% of the account a trade with fees, 5% a day, a 10% drawdown halt). No cap on trades, strategies or positions.
* **Switches:** off with the repository variable `PAPER_AUTO` = `no`; back to v1 with `PAPER_AUTO_ENGINE` = `v1`.
* **Not proven to make money.** The shadow record is the evidence it builds; the first days are mostly shadow trades.

### The day plan, 06:00 to 09:15 (owner's order, 13 Nov 2026)

"6 am to 9:15 am, the desk will plan the day by analysing options data, futures data and top to bottom predictive news analysis
and look for high risk to reward trades." Every ten minutes from 06:00 to 09:15, AUTO v2 builds a **day plan**
(`AutoPilotV2.plan`).

**What it reads:**
- **Options and futures:** last night's closing books from the relay (kept through the night since the board is stored): the
  at-the-money implied volatility, the closing book pressure, and the options' forward against the futures.
- **News:** the news engine's tone for each underlying.
- **Overnight markets:** the brief's US, Asian and European equity moves; their median is one vote for the indices.
- **The pre-market brief** (`premarket.yml`, now from 06:00): results today (options rich or cheap against the company's own
  history, which sets the volatility context), macro events, expiries, headlines naming the instrument, futures OI shifts.

**What it decides:**
- **A pre-open view** per underlying: up or down only when **three** readings agree and none disagrees (since 14 Nov 2026: "a
  strong direction"); with fewer, the reason is written down and no direction is planned. Flat when nothing moves.
- **Directional candidates:** the **overnight** strategies whose context holds, priced on the closing books, kept only if their
  reward to risk is **2 or better** (the take-profit against the structure's worst case, capped by what it can make).
- **Big-move candidates:** the Convexity desk's strategies whose test passes on the closing board (options cheap against the
  forecast, a scheduled event priced small, tails underpriced). The squeeze test needs the live tape, so it is never planned.
- **Not planned:** a flat view's premium selling (an iron condor expects no move: neither a big move nor a direction), day and
  swing strategies, and futures (intraday). All of them are still tested in shadow.
- **Ranking:** proven strategies first, then by measured expectancy in R, then by catalysts and reward to risk. At most two per
  underlying and ten in all. Each comes with its legs, rupees at risk and to gain per lot, and its reasons.

**At the open (since 14 Nov 2026: plan first, `PLAN_ONLY`):** the plan is the main way a trade is opened, in both books; the news and the data
exceptions below are the only others. The owner:
"every day it should analyze the news and everything ... prior we are deciding it ... not when the market opens. Then it's fine.
Okay, then it takes trade."
- **Taken:** from the segment's first entry time (09:20 for NSE), for 100 minutes, a planned strategy with its shadow record
  (8 trades and a positive Thompson draw; the Convexity desk's own gate for its strategies).
- **Decided before, not at the open:** the intraday view does not have to agree. A plan is dropped for the day only when it has
  been **contradicted**: the open's view is the opposite one, the underlying has already gone through the planned trade's
  volatility stop from the planned price, the trade now risks more than 1.5 times what the plan priced, a big-move trade's options
  have turned rich, or its event has passed.
- **Nothing else is opened during the day, except by the two exceptions below** (important news, a change in the live data) and a Convexity desk test that
  has held five minutes on the live board. Prices, news and every reading are still recorded, and every
  strategy is still traded in shadow, so the record keeps growing.
- **The exception: important news in the session, at any time** (the owner, 14 Nov 2026: "if during the trading time if any news
  comes up which could be important then also allow the system to trade", and "There is not like 45 minutes window ... in trading
  session also you can take a trade given that there is a news which is important or is relevant to our risk to reward part").
  The news counts for an instrument when a story is:
  - of today's session: published after today's plan was built, and not in the future;
  - of **high impact**, new (novelty 0.5 or more) and not a recap;
  - about the instrument: it names it, or its subjects move it by 0.3 or more through the news model's channels (crude news
    reaches the rupee, not an IT exporter).

  There is no time window. While such a story exists, the plan's own bar applies to the live board at any time in the session.
  A directional trade needs a **strong direction**: three or more live readings agreeing (book pressure, the options forward,
  the move, the news, the market read, the Kalman trend), **the news among them**, none against; then an overnight strategy
  with the volatility stop. A big-move trade needs a Convexity desk test to pass on the live board (for example a high news
  event the options have not repriced for). How long a story keeps counting is the market's answer: the news model's vote
  halves in two hours and is gone after six, and the other readings must still agree. One news-driven directional position per
  instrument at a time; same proof gates, sizing and risk gate. The trade's thesis names the headline.
- **And the same for the data** (the owner, 14 Nov 2026: "it's not only limited to news, it's also applies to data also. That if
  we feel the data is changing in the market and that particular sentiment change in the data ... is signaling us to that
  particular risk reward opportunity ... Same applies to there also"). The 06:00 to 09:15 plan is what the market could look like
  from last night's data; the live market is its own setup. At any time in the session, a directional trade the plan did not
  name may open when:
  - the live market shows a **strong direction**: three or more readings agreeing (book pressure, the options forward, price,
    the news, the options and OI market read), none against. **Price is one reading** however it is read (the five-minute
    move, or once fitted the Kalman trend, or a drift change point: one of them, never two);
  - it has **held for five minutes** without a gap, so a flicker is not a reason;
  - the pre-market read did not already say it (what the plan expected is not a new reason), **and the data has really shifted**
    (the owner's choice, 14 Nov 2026, "Stricter: real data shift"): the options and OI read's P(up) has moved 0.15 or more since
    the session's first read **towards** the direction (a read weakening towards neutral is not a shift) and agrees (a build-up appearing, the put-call ratio turning), or a fresh CUSUM change point is
    drifting the same way. The plan's silence alone is not a change;
  - the strategy offers a **reward to risk of 2 or better**, as on the plan (an overnight strategy, the volatility stop).

  A big-move trade opens when a Convexity desk test has held on the live board for five minutes: the test itself (for the tail
  test, the structure's EVT value) must pass at each sighting, and a gap of more than two minutes between sightings starts the
  clock again; the same for the live agreement. A planned strategy the plan's own checks refused (late, contradicted, dear) does
  not come back through a trigger, and every live-triggered trade needs the reward to risk of 2. A convex package is sized at
  its order's own limit price (the offer plus its slippage allowance), so the 0.5% stake is a ceiling on what a fill can cost.
  Same proof gates and risk gate; one live-triggered directional position per instrument at a time. The thesis says what changed.
- **Same limits:** the risk gate, the loss caps and the proof gate are the same as for any trade.
- **Unproven ideas:** an unproven strategy on the plan is shadow-traded like every other, and earns its way in.
- **Yesterday's plan** never steers today. Today's is kept with the strategy record (since 14 Nov 2026), so a restart after 09:15 still has it; read
  back, only its items that name a known strategy with a real planned price, spot and (if any) event time are kept, at most as many as a plan holds.

**Where to see it:** the Positions tab, the "Day plan" panel, above the strategy lab.

**What it is not:** a forecast that has been tested. The repository's own research found direction hard to forecast. The plan
writes down what the desk will look for and why. Whether planned trades do better than unplanned ones is for the record to show.

### Open shadow trades outlive a runner job (14 Nov 2026)

The paper desk runs as chained jobs with handovers (`paper-desk.yml`: 11:50, 17:40 and 23:30 IST, then the end of the day). Until 14 Nov 2026 a shadow trade still open at a handover was lost and never scored: a strategy held overnight could never be held overnight in shadow, and every record was built only from trades that resolved inside one job. Now the open shadow book is saved beside the strategy record, on the same two-minute cadence and at the end of every job, to the relay's `/paper/shadow` (the runner's INGEST key only, never the app's; compressed, in up to ten stored pieces). The next job reads it back with every field checked and closes each trade by its own exits. Dropped, not scored, and counted by reason (`shadow_carry` in the runner's state): a day trade from an earlier session, a trade past its expiry, an unknown strategy or instrument, anything malformed. A book too large for the relay keeps its longest-held trades and counts the rest (`left_out`). Like the record, it is private: it is never published.

### Held overnight, and a stop set by volatility (owner, 14 Nov 2026)

The owner: "my options, whether buying or selling, must have the overnight holding power", and the stop "based on the market
conditions. How much volatile the market is". His choices: an underlying-move stop, held until its exits say so.

**The overnight strategies:** every catalogue context also has two overnight variants (take-profit 2R or 3R of the structure's
worst case). They are the only directional strategies the plan names. Each is:
- **held past the close and across sessions**, with no session cap;
- **stopped by the underlying, not the premium:** out when the index or stock has moved against the trade by
  **1.5 × its daily standard deviation × √(sessions held)** since entry. The daily standard deviation is the tail model's (or the
  last hour's realized, if larger), taken at entry, so a volatile market gets a wide stop and a calm one a tight stop. Against
  an up view is down, against a down view is up, and against a short-volatility structure is a move either way. A long straddle
  and the Convexity desk want the move, so their premium is their stop. The entry price and volatility travel in the position's
  strategy name (`p24500 d1075`: spot 24,500, a 1.075% day), so a restart keeps the stop;
- **out by the close of the session before expiry**, so no position is held into an expiry day;
- bounded, as always, by the structure's own worst case and the risk gate.

The runner's forced sales (expiry, a stock option's last day, MCX and currency last holding days, the brakes, the kill switch)
still apply on top. A sold option is held overnight only as a leg of a defined-risk structure, so a gap cannot lose more than the
risk gate already allowed.

## AUTO v1: the paper desk deciding for itself (paper money only)

You said go on 8 Nov 2026: the desk may take trades by itself beside yours. Since 13 Nov 2026 it is **ON for every run** ("enable the self-trading ... a system which trades itself"): it trades the four index families and the 20 watchlist stocks. To switch it off, set the repository variable `PAPER_AUTO` to `no`. Your hand-placed orders are unchanged and work at the same time.

It looks for **high reward for little risk**, and it is **not an intraday-only system**.

* **Entry** (`quantdesk/paper/auto.py`, pure rules; every order's thesis spells out why): one lot, the first strike out of the money (more convexity for the same stop), of an expiry at least three days away. Only when at least two of four readings agree and none points the other way: resting bid/offer pressure around the money (calls against puts), the forward the options imply against the futures price (put-call parity), the index's own move over five minutes, and the **tone of the recent news** (the relay's digest: last two hours, medium or high impact, not recaps).
* **Risk and reward:** the most it can lose is the premium, and a stop caps that at **40% of the premium**. There is **no cap on the gain**: a trailing stop arms at +80% (twice the risk) and follows 30% below the peak, so a trade that works can run for several times what it risked. Most trades will lose their small stop; the winners pay for them. The peak is written into the ledger, so a restart or the night cannot loosen the trail.
* **Overnight:** ten minutes before the close each position gets a decision. It is **held** if its expiry is still at least two days away, it is under three calendar days old (a holiday counts as a day, so the carry over Tuesday 10 Nov is short), it is not well under its entry, the readings do not point the other way and the news is not against it; otherwise it is sold. In the morning it keeps its stop and trailing stop. It also leaves early when the readings turn the other way or strong news turns against it.
* **No cap on trades (owner, 8 Nov 2026: "do not keep any cap on the trades ... keep a cap on your losses").** There is no limit on the number of trades or open positions and no stop of AUTO's own: the bound is the risk gate's loss caps (2.5% a trade with fees, 5% a day, a 10% drawdown halt, and the loss budget that limits what can be open at once). The only guards left are against double-handling: it never adds to a contract already held, and it does not re-buy the same contract within five minutes of its last fill in it. The gate still applies to every one of its orders: the kill switch, the daily loss cap, the drawdown halt, quote freshness and size. It only ever sells **the lots it bought itself** (strategy name starts `AUTO v1`, quantity from its own ledger fills); yours are never touched, even if you buy the same contract. **Because it has no cap, AUTO may use up the whole loss budget, and then your own buys are refused with the gate's "loss budget" reason**; its open premium shares that budget with yours, a position carried overnight can limit the next day's buys, and the gate's flatten/trim act on all positions by size, not by who opened them. A fault in the autopilot cannot stop the runner or the brakes. **Before switching AUTO off, check the Paper tab for open `AUTO v1` positions**: with the autopilot off nothing manages their stops. After any entry order for an index and direction (filled or refused) it waits 60 seconds before another for that index and direction. **Ceiling to plan for:** the relay can hold an account of about 960 ledger rows (about 1.2 MB, 1.24 KB a row). An AUTO that trades freely can write 200 or more rows a day, so the ceiling can arrive in **3 to 4 days**. Past it the relay refuses every save of the account: the app's equity and positions go stale, order results are not posted back, and after 30 seconds new entries (yours too) wait, while exits, stops, the gate and the kill switch keep working on the runner. To keep that from happening AUTO **stops opening new positions once the ledger reaches 800 rows** (a storage guard, not a trade cap; it still manages and exits what it holds, and says so in its status line). To go on, the limit is raised (`MAX_CHUNKS` in `deploy/cloudflare/paper.js`) or the ledger is archived, both a deliberate change. AUTO also proposes nothing while the account is already stopped for the day or halted by the drawdown limit.
* **It is not proven.** Its readings are the ones the app's Flow panel logs and grades; until they have a record they are a hypothesis, and a high-reward/low-hit-rate style needs many trades to judge. Its trades, with the price it saw and what it paid (slippage), are the evidence. Judge it on the Paper tab by the `AUTO v1` strategy name.
