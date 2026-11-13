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

1. Build tab: pick the index, the expiry and a structure (or use *Ideas for your view*). Only structures the paper desk can open show **Send as a paper order**: long options on NIFTY, BANKNIFTY, FINNIFTY or MIDCPNIFTY, and, since 8 Nov 2026 (`paper.allow_short_legs: true`, the owner's order), **hedged packages with sold legs** (verticals, condors, butterflies): they go as ONE order, every leg opens together or none does, and the gate judges the worst case (a naked short call or a calendar is always refused; the long that covers a sold option cannot be sold before the sold option is bought back). A sold option never goes alone: only as a leg of a package. If the switch is turned off in the config, a structure with a sold leg is a what-if again.
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
| Expectations | the straddle's implied move, skew (out-of-the-money put over call volatility) and its change, the near against next expiry's volatility, the future's premium |

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
* **It chooses.** A strategy trades with paper money only after **8 shadow trades**, and then by **Thompson sampling**: a short record is shrunk towards zero, the best plausible draw wins, and a draw at or below zero does not trade. Capital flows to what has worked and away from what has not.
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
- **A pre-open view** per underlying: up or down when at least two readings agree and none disagrees; flat when nothing moves.
- **Candidates:** every catalogue strategy whose context holds, priced on the closing books, kept only if its reward to risk
  is **2 or better** (the strategy's own take-profit against its stop, capped by what the structure can make).
- **Ranking:** proven strategies first, then by measured expectancy in R, then by catalysts and reward to risk. At most two per
  underlying and ten in all. Each comes with its legs, rupees at risk and to gain per lot, and its reasons.

**At the open:** from 09:20, for each underlying, AUTO v2 takes a **planned** strategy first, but only if its context still holds
on the live board, it has its `MIN_TRADES` shadow record, and its Thompson draw is positive. Otherwise it chooses as before. A
planned trade's thesis says so.
- **Same limits:** the plan changes the order of choice, not the limits. The risk gate, the loss caps, the proof gate and the
  sizes are the same as for any trade.
- **Unproven ideas:** an unproven strategy on the plan is shadow-traded like every other, and earns its way in.
- **Yesterday's plan** never steers today.

**Where to see it:** the Positions tab, the "Day plan" panel, above the strategy lab.

**What it is not:** a forecast that has been tested. The repository's own research found direction hard to forecast. The plan
writes down what the desk will look for and why. Whether planned trades do better than unplanned ones is for the record to show.

## AUTO v1: the paper desk deciding for itself (paper money only)

You said go on 8 Nov 2026: the desk may take trades by itself beside yours. Since 13 Nov 2026 it is **ON for every run** ("enable the self-trading ... a system which trades itself"): it trades the four index families and the 20 watchlist stocks. To switch it off, set the repository variable `PAPER_AUTO` to `no`. Your hand-placed orders are unchanged and work at the same time.

It looks for **high reward for little risk**, and it is **not an intraday-only system**.

* **Entry** (`quantdesk/paper/auto.py`, pure rules; every order's thesis spells out why): one lot, the first strike out of the money (more convexity for the same stop), of an expiry at least three days away. Only when at least two of four readings agree and none points the other way: resting bid/offer pressure around the money (calls against puts), the forward the options imply against the futures price (put-call parity), the index's own move over five minutes, and the **tone of the recent news** (the relay's digest: last two hours, medium or high impact, not recaps).
* **Risk and reward:** the most it can lose is the premium, and a stop caps that at **40% of the premium**. There is **no cap on the gain**: a trailing stop arms at +80% (twice the risk) and follows 30% below the peak, so a trade that works can run for several times what it risked. Most trades will lose their small stop; the winners pay for them. The peak is written into the ledger, so a restart or the night cannot loosen the trail.
* **Overnight:** ten minutes before the close each position gets a decision. It is **held** if its expiry is still at least two days away, it is under three calendar days old (a holiday counts as a day, so the carry over Tuesday 10 Nov is short), it is not well under its entry, the readings do not point the other way and the news is not against it; otherwise it is sold. In the morning it keeps its stop and trailing stop. It also leaves early when the readings turn the other way or strong news turns against it.
* **No cap on trades (owner, 8 Nov 2026: "do not keep any cap on the trades ... keep a cap on your losses").** There is no limit on the number of trades or open positions and no stop of AUTO's own: the bound is the risk gate's loss caps (2.5% a trade with fees, 5% a day, a 10% drawdown halt, and the loss budget that limits what can be open at once). The only guards left are against double-handling: it never adds to a contract already held, and it does not re-buy the same contract within five minutes of its last fill in it. The gate still applies to every one of its orders: the kill switch, the daily loss cap, the drawdown halt, quote freshness and size. It only ever sells **the lots it bought itself** (strategy name starts `AUTO v1`, quantity from its own ledger fills); yours are never touched, even if you buy the same contract. **Because it has no cap, AUTO may use up the whole loss budget, and then your own buys are refused with the gate's "loss budget" reason**; its open premium shares that budget with yours, a position carried overnight can limit the next day's buys, and the gate's flatten/trim act on all positions by size, not by who opened them. A fault in the autopilot cannot stop the runner or the brakes. **Before switching AUTO off, check the Paper tab for open `AUTO v1` positions**: with the autopilot off nothing manages their stops. After any entry order for an index and direction (filled or refused) it waits 60 seconds before another for that index and direction. **Ceiling to plan for:** the relay can hold an account of about 960 ledger rows (about 1.2 MB, 1.24 KB a row). An AUTO that trades freely can write 200 or more rows a day, so the ceiling can arrive in **3 to 4 days**. Past it the relay refuses every save of the account: the app's equity and positions go stale, order results are not posted back, and after 30 seconds new entries (yours too) wait, while exits, stops, the gate and the kill switch keep working on the runner. To keep that from happening AUTO **stops opening new positions once the ledger reaches 800 rows** (a storage guard, not a trade cap; it still manages and exits what it holds, and says so in its status line). To go on, the limit is raised (`MAX_CHUNKS` in `deploy/cloudflare/paper.js`) or the ledger is archived, both a deliberate change. AUTO also proposes nothing while the account is already stopped for the day or halted by the drawdown limit.
* **It is not proven.** Its readings are the ones the app's Flow panel logs and grades; until they have a record they are a hypothesis, and a high-reward/low-hit-rate style needs many trades to judge. Its trades, with the price it saw and what it paid (slippage), are the evidence. Judge it on the Paper tab by the `AUTO v1` strategy name.
