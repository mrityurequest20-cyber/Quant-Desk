# QuantDesk: a quantitative trading desk for Indian markets

QuantDesk is an automated trading system for **NSE equities and index options (NIFTY, BANKNIFTY)**. One engine runs every part of the desk, in order:

1. Reads charts and statistics.
2. Detects the market regime.
3. Runs eight quantitative strategies.
4. Sizes every trade through a risk manager.
5. Executes on a paper (or, when explicitly enabled, live Zerodha Kite) account.
6. Runs pre-market, intraday and post-market checks.
7. Keeps a journal that reviews and grades every trade.

The same code path runs backtests, paper trading and live trading. What you backtest is what trades.

> Not investment advice. Paper trading is the default. Live trading needs three separate opt-ins (see [Live trading](#live-trading)). Run it on paper for a few months before a single live lot.

```
data ─► analytics ─► regime ─► strategies ─► allocator ─► risk manager ─► broker ─► journal ─► review
 (Yahoo/CSV/       (indicators,  (HMM +      (8 books:     (regime ×      (sizing,       (paper /    (SQLite:     (grades,
  synthetic)        vol, GARCH,   trend/vol   trend, MR,    recent         limits, DD      Kite)       plans,       lessons,
                    stats, chart) rules)      momentum,     performance)   de-risk, kill   + Indian    fills,       daily/weekly
                                              pairs, 3×                    switch)         costs       checks)      reviews)
                                              options)
       └──────────── routine checks: pre-market ▸ intraday ▸ post-market ────────────┘
```

## Quick start

```bash
git clone https://github.com/mrityurequest20-cyber/Quant-Desk && cd Quant-Desk
pip install -r requirements.txt

python -m quantdesk --source synthetic demo       # the daily desk, offline, ~90 s
python -m quantdesk intraday replay --synthetic 5 # the intraday options desk, offline, ~1 min
python -m quantdesk serve --host 0.0.0.0          # the website, on your phone (prints a private link)
python -m pytest                                  # full test suite
```

The demo writes everything to `runtime/demo/`:

| File | What it is |
|---|---|
| `backtest_report.html` | Tearsheet with equity vs NIFTY, drawdown, monthly heatmap, P&L by strategy, risk statistics, a Monte Carlo drawdown distribution, and journal excerpts |
| `backtest_journal.db` | Every decision, fill, trade review and snapshot of the backtest |
| `market_analysis.txt` | The morning read for NIFTY, BANKNIFTY and RELIANCE, plus a universe scan |
| `paper_daily_log.md` | 12 simulated sessions of paper trading, each with pre-market checks, EOD cycle, post-market checks and the daily review |
| `paper_review.md`, `desk_report.html` | The multi-day journal review, plus checks and analysis as a page |

On real data, remove `--source synthetic`. Yahoo Finance is the default source (`RELIANCE.NS`, `^NSEI`, `^NSEBANK`, `^INDIAVIX`). You can also put CSVs in `data/csv/` and pass `--source csv`.

```bash
python -m quantdesk analyze NIFTY RELIANCE        # chart structure, stats, vol, regime, options read
python -m quantdesk options BANKNIFTY             # expected moves, model chain, costed structures
python -m quantdesk scan                          # universe dashboard
python -m quantdesk backtest --report bt.html --mc
python -m quantdesk backtest --strategies pairs,vrp_condor --start 2020-01-01
python -m quantdesk walkforward --strategy trend_rider --grid "fast=10,20;slow=50,100"
```

## The daily routine (paper or live)

```bash
python -m quantdesk schedule    # prints the cron lines below (IST)
```

| When (IST) | Command | What happens |
|---|---|---|
| 08:40 | `paper premarket` | Checks trading day, data freshness/quality, broker, kill switch, risk state, reconciliation, stops in place, expiry watch, event risk (RBI/FOMC), VIX level, and queued orders. A FAIL on a hard check blocks new entries for the day. |
| 09:20 (live only) | `--live paper open` | Executes queued orders against live Kite quotes |
| every 30 min | `paper intraday` | Stop breaches and proximity, intraday P&L vs the daily loss limit |
| 16:45 | `paper run` | EOD cycle. Fills yesterday's queue at today's open, then checks stops, marks to market, settles expiries, runs the risk state machine, lets strategies manage their trades and generate new ideas, sizes and queues them, and snapshots. It is idempotent and catches up on missed days. |
| 16:50 / Fri 18:00 | `paper review [--days 7]` | Daily and weekly journal review: P&L, per-strategy stats, grades, recurring lessons, risk events, failing checks |

Other commands:
- `paper status` shows the account.
- `journal trades|events|decisions|show --id …|export` reads the journal.
- `risk reset` re-arms the kill switch after a post-mortem.
- `touch runtime/KILL` stops all order flow instantly.

## Daily desk UI with GoCharting charts

`python -m quantdesk serve` (standard library only, `127.0.0.1` by default) serves the phone-friendly intraday app at `/` (see [The website](#the-website-use-it-from-your-phone)) and the daily desk at **`/daily`**, which has:
- a watchlist with regimes
- the chart
- the analysis for the selected symbol
- a paper order ticket
- open positions with Close buttons
- queued orders with Cancel
- the latest journal reviews
- routine checks

**Charting uses the [GoCharting SDK](https://gocharting.com/sdk/docs)**, integrated the way GoCharting's reference implementation ([gocharting-sdk-demo](https://github.com/GoChartingInc/gocharting-sdk-demo)) does it:

- **Datafeed** (`quantdesk/web/static/datafeed.js`)
  - `getBars` returns UDF arrays (`{s,t,o,h,l,c,v}`, unix seconds).
  - `resolveSymbol` supplies `segment` and `exchange_info`. Symbols are keyed `NSE:INDEX:NIFTY` and `NSE:EQUITY:RELIANCE`, with timezone `Asia/Kolkata`.
  - `searchSymbols` and polled `subscribeTicks` are also implemented.
- **Broker bridge:** QuantDesk's open positions (with stop/target), queued orders and fills go to `chartInstance.setBrokerAccounts(...)` every 20 s and after every action.
- **Trade from chart:** the SDK's `appCallback` events all route to the paper broker through the same kill switch and risk gate:
  - `PLACE_ORDER` places an order.
  - `CLOSE_POSITION` and the exit X close a position.
  - `MODIFY_POSITION` drags the stop or target.
  - `CANCEL_ORDER` cancels a queued order.

  Each action is journaled as a `manual` trade and gets a review like any other. Chart orders are paper-only by design.
- **Fallback:** if the SDK can't load (no network, no license, blocked domain), a built-in candlestick chart takes over. It shows SMA50/200, journal entry/exit markers, and open-trade stop, target and entry levels, with a crosshair tooltip. The desk always works.

**License:** `@gocharting/chart-sdk` is a private package, and production use needs a commercial license from GoCharting. QuantDesk loads the SDK's hosted build from `https://gocharting.com/sdk/library/<license-key>/index.umd.js`. It ships with the public demo key from GoCharting's own CodePen. Put your key in `web.gocharting.license_key` or `GOCHARTING_LICENSE_KEY`.

## Intraday options desk (real time)

`python -m quantdesk intraday live` runs from 09:15 to 15:30 IST in paper mode. Every closed minute it:

1. **reads the market:** new 1-minute bars (Kotak Neo candles, Yahoo, or Kite ticks) and a fresh option chain (Kotak's live book every minute, NSE's free chain every 3 minutes, Kite quotes, or a model). Everything is recorded to `runtime/intraday/data/`, so the desk builds its own intraday history.
2. **thinks:** the analyst gathers weighted **evidence** in six groups:
   - **trend:** VWAP side and slope, 5m EMA9/21, Supertrend, 15m slope
   - **structure:** opening range, initial balance, value area and POC, prior-day high/low, CPR
   - **momentum:** 5m RSI
   - **flow:** CVD slope and price/CVD divergence (tick delta when a tick feed is attached), the near-month future's
     open-interest build-up and its basis
   - **options:** PCR, OI walls, max pain on expiry day
   - **volatility:** India VIX change, ATM IV vs realised vol

   From that it forms a **bias, a conviction and a day type** (trend / balance / volatile). It gives a **premium view** (IV rich, fair or cheap), lists explicit **no-trade flags**, and writes a narrative. The read is journaled every 5 minutes, on every bias flip, and on every trade.
3. **picks a setup** from the playbook:
   - **opening-range breakout**
   - **trend pullback** to VWAP or EMA21
   - **flag breakout** (continuation after a 30-minute consolidation)
   - **value-area rejection** (fades only when the tape is balanced)
   - **range premium-selling iron fly** (balance day with rich IV)

   The structure follows the vol view: buy the option when premium is fair or cheap, a debit spread when it's rich, a defined-risk fly for range days. Strikes come from the real chain by delta. Each plan fixes its **invalidation level, targets, premium stop and time stop before entry**.

   **Buyer only below ₹3 lakh** (`intraday.short_legs_from_equity`). A sold option leg needs margin, and a ₹20k
   account doesn't have it. So below that equity the desk only buys calls and puts:
   - no debit spreads (their short leg), no iron fly, and no spread alternatives in the EV ranking;
   - the selling structures stay in the playbook, untouched;
   - once equity reaches the threshold they switch back on by themselves, and the journal says so.

   **Waiting at the level (anticipation).** The breakout and pullback setups don't only wait for a 5-minute candle to close beyond a level. Every minute the desk also *arms* the ones its read already favours, at the exact trigger: the OR high/low or the 30-minute range edge (a stop entry through it), or VWAP on a trend-day pullback (a limit entry back at it). It only arms them when the level is within 1.5 ATR5 and there's no no-trade flag. With Kotak, the index price is polled every 5 seconds, so an armed setup fires the moment price trades there; without a live price, each new 1-minute bar's range decides it (in replays too). Legs are repriced to the trigger price before the EV gate decides.
   - The 5-minute-close confirmation stays as a fallback (`intraday.anticipate.confirm_fallback`). A break the read only backs once it happens is still taken, just later.
   - In replays, armed entries filled within 0.04 points of their level, but the EV gate turned most down before the break: conviction tends to arrive *with* the breakout. Every armed fire and its verdict is journaled, so live sessions show whether pre-break entries would have paid.
   - The armed setups are on the app's Desk screen (*Waiting at the level*).
   - Stops and targets are checked on the same 5-second price, not once a minute.
4. **sizes and executes (simulated):**
   - **Sizing:** 1% of capital at risk to the plan's stop, scaled by conviction.
   - **Caps:** lots, premium outlay and margin.
   - **Daily limits:** 6 trades a day, 2 open, −2.5% daily stop, cooldown after 2 losses.
   - **Entry window:** new trades only between 09:20 and 14:45.
   - **Fills:** buys at the ask, sells at the bid, plus a tick, plus the full cost stack (STT 0.15% on premium sold). With Kotak, entries and exits use the bid/ask of that moment, and an entry is skipped if the live net premium has moved more than 15% against the plan (a real limit order wouldn't have filled).
5. **manages:** open options are marked with the IV implied by their last real quote, repriced with the live spot and minute-level time to expiry, so delta, gamma and theta all show up in P&L. Exits happen on invalidation, premium stop/target, underlying target, breakeven trail or time stop. Everything is squared off by 15:15.
6. **reviews:** every trade gets a grade and lessons. The session review (how the read evolved, the bias path, each trade's why and how it ended) goes to `runtime/intraday/reviews/<date>.md`.

```bash
python -m quantdesk intraday live                       # Yahoo 1m bars + NSE option chain (free; best effort)
python -m quantdesk intraday live --feed kotak --chain kotak # Kotak Neo bars + live bid/ask (the default with a key)
python -m quantdesk intraday kotak-check                # what KOTAK_CONSUMER_KEY can see
python -m quantdesk intraday live --feed kite --chain kite   # real-time ticks + real quotes (Kite Connect)
python -m quantdesk intraday replay --last 5            # re-run recorded real sessions through the same engine
python -m quantdesk intraday replay --synthetic 20      # offline practice on synthetic sessions
python -m quantdesk intraday thoughts -v                # what it thought, with the evidence
python -m quantdesk intraday trades --id <id>           # full rationale, sizing, review for one trade
python -m quantdesk intraday stats                      # by setup, structure, day type, exit, hour
python -m quantdesk intraday review                     # the written session review
```

**Data reality check.**
- Yahoo's 1-minute bars cover only ~7 days, may lag, and carry no volume for indices. With Kotak, the future's
  volume fills that in; otherwise the desk falls back to TWAP and a TPO (time) profile and flags it. So record every session.
- NSE's option-chain API is free but throttled and changes without notice (the v3 endpoint is used).
- Kite Connect (`KITE_API_KEY`/`KITE_ACCESS_TOKEN`) gives real-time ticks, depth and real option quotes.

**Kotak Neo (the default when a key is set).** `quantdesk/intraday/kotak.py` uses only the Trade API endpoints that
authenticate with the app's consumer key: quotes (5-level depth, 25 instruments a call), option chain, expiries
and 1-minute candles. That means **no TOTP, no MPIN, no daily login, and no static IP**: SEBI's static-IP rule
(from 1 Apr 2026) covers the order APIs, which the desk never calls. Every minute it fetches each underlying's
chain (41 strikes, 20 each side of the money) and the bid/ask of every contract in it plus the index, about 3
calls per underlying. Paper
fills use the book of that moment. If Kotak fails, the chain falls back to NSE (asked at most every 3 minutes)
and bars fall back to Yahoo, and the session review says which source served.

Setup:
1. Kotak Neo app or web → More → Trade API → the "Default Application" → copy the **consumer key**. Leave the IP
   fields empty; they matter only for real orders.
2. GitHub → this repo → Settings → Secrets and variables → Actions → New repository secret. Name
   `KOTAK_CONSUMER_KEY`, value the key.
3. Actions → **Broker check** → Run workflow. It prints index quotes, expiries, an option chain with bid/ask and
   IVs, a live quote and the latest candles. The live desk picks the key up on its next run.

**Futures: where the volume is.** An index has no volume and no open interest; its future has both. With
Kotak, the desk follows each index's near-month future (`quantdesk/intraday/futures.py`, `KotakFutures` in
`kotak.py`). It rolls to the next month 3 trading days before expiry (`intraday.futures.roll_days`).
- **Volume:** each minute's futures volume goes onto that minute's index bar (index prices are kept). The session
  volume profile, VWAP, relative volume and CVD are then built on real traded volume, not on time (TPO) as
  before. This works on the Yahoo fallback too.
- **Recording:** the future's own 1-minute bars are recorded as `NIFTY-FUT` / `BANKNIFTY-FUT`. The app's chart
  has an *Index / Futures* switch.
- **Open-interest build-up** over the last 30 minutes uses the classic four states: long build-up (price ↑,
  OI ↑), short build-up (price ↓, OI ↑), short covering and long unwinding. The last two are closing trades, so
  they count half. The result is the `fut_oi` evidence.
- **Basis:** futures minus spot, read as an annualised carry. A premium widening or shrinking since the first read
  of the day is the `basis` evidence.
- **Context:** OI against yesterday's close and the near/next calendar spread go in the narrative.

Option expiries (weekly NIFTY) and futures expiries (monthly) are tracked separately. The option chain uses its
own nearest weekly, and the futures read always uses the active monthly.

**Order flow and the GoCharting plan.** `quantdesk/intraday/orderflow.py` already computes:
- volume profile (POC, value area, high/low-volume nodes)
- footprint bars from ticks (buy/sell volume per price, delta, diagonal imbalances, stacked imbalances)
- CVD and divergences

With Kite, full-mode snapshots are classified with the quote rule and fed into it. A true tick-by-tick trade feed (e.g. what GoCharting's order-flow subscription is built on) plugs in through the same `Trade` records. When that data is attached, the analyst's `flow` evidence switches from the bar approximation to real delta.

**On synthetic sessions** (built-in simulator: trend, range, reversal and volatile days), with ₹5 lakh of capital, the desk made **+4.0% over 8 traded sessions** (10-session run, 40 trades, win rate 42%, profit factor 1.69, max drawdown −2.3%). Flag breakouts and ORB earned; VWAP pullbacks and value-area fades lost. That proves the machinery, not an edge. Judge it only on recorded real sessions (`intraday replay --last N`) and weeks of live paper trading.

**With the default ₹20,000 account**, the same 10 sessions lost **−19%**: 20 trades, 30% win rate, max drawdown −27.6%, ₹2,581 in costs. A small options account is a different game. The smallest position is one lot of a narrow NIFTY debit spread, which risks ₹1.2–1.6k (6–8% of the account). Each round trip also costs about ₹110–130, because the ₹20 flat brokerage is charged on each of the 4 orders a spread needs. That's why the ₹20k config caps the desk at 2 trades a day and only sizes into high-conviction plans. BANKNIFTY (monthly expiries only) is too expensive to trade at this size.

*Since 3 Oct 2026 the ₹20k desk is a buyer only* (see above): one lot of a 0.45-delta NIFTY weekly option, ≈₹5–6k of
premium against the 35% outlay cap, stopped at 30% of premium (₹1.5–1.8k). On the same 10 synthetic sessions that
gave 8 trades and **+₹4,298** (spreads with the quant layer: 7 trades, +₹108). That's synthetic data: it checks the
mechanics, not an edge.

**The quant decision layer on the same 10 sessions at ₹20k:** 7 trades instead of 20, costs of ₹559 instead of ₹2,581, net **+₹108 (+0.5%)** instead of −₹3,808, and max drawdown −13.5% instead of −27.6%. That's the EV gate refusing trades that can't pay their costs. It is not a proven edge: 7 trades, one +₹3,062 winner carried it, and the data is synthetic.

## The quant decision layer

Every trade has to pay for itself on paper before it's placed. For each signal the playbook raises, the desk runs these steps:

1. **Forecasts the move.** It estimates σ per minute from three sources: today's EWMA realised volatility, the prior sessions, and the ATM implied volatility. The horizon σ scales with √minutes.
2. **Asks whether there's a real directional edge.** A logistic regression is trained only on earlier sessions (about 55 days of 5m bars). It predicts whether the index is higher in 30 minutes from momentum, VWAP distance, range and opening-range position, EMA spread, RSI, time of day and the gap.
   - It has to pass a walk-forward test: out-of-sample AUC ≥ 0.53 *and* log-loss better than the base rate. Otherwise it's switched off and the journal says so.
   - A test checks the features are causal: recomputing on truncated data must give identical rows.
   - Without a validated model, P(up) comes from an explicit, labelled prior of 0.5 + 0.10 × the analyst's score.
3. **Prices every way to express the view.** Candidates are single long options at 0.30Δ and 0.40Δ, and 0.45/0.30 and 0.50/0.20 debit spreads. Each is simulated in a Monte Carlo over its holding period:
   - It's marked every 3 minutes in **business time**. IV is quoted per calendar year but the variance arrives in trading minutes; without this, every intraday option buyer would get a free edge.
   - It exits the way the engine would: invalidation, premium stop or target, underlying target, or time stop.
   - It pays the bid/ask again on the way out, and the full cost stack both ways.
4. **Trades only the best EV per rupee of risk that the account can hold, and only if EV ≥ max(₹40, 0.05R).** Otherwise the journal records why not, with the numbers.

What that arithmetic says for NIFTY (7-DTE options, 45-minute holds, realised vol = implied):

| Structure | Round-trip costs/lot | EV at a coin flip | Break-even P(right) |
|---|---:|---:|---:|
| 0.45/0.30 debit spread | ~₹200 | ≈ −₹270 | > 65% |
| single long call 0.35Δ | ~₹96 | ≈ −₹145 | ≈ 55% |

A small account should buy single options only when there's a real edge. It should almost never pay the double costs of a narrow spread.

## News

Every 4 minutes, in parallel, the desk reads these feeds (all reachable from GitHub's runners): ET Markets, ET Stocks, Moneycontrol, Mint, Business Standard, Google News (India and macro) and RBI press releases. For each story it:

- dedupes it across outlets
- tags what it's about: the index, banks, or macro
- scores the headline with a finance lexicon that knows the subject. Crude, inflation or yields rising is bad for Indian equities. It also understands "snaps losing streak", "higher for longer", and rate cuts and hikes.
- rates its impact
- **reads it with NLP** (`intraday/nlp.py`, rule-based and deterministic):
  - **event type:** policy, inflation, growth, earnings, flows, geopolitics, commodities, currency, regulation, global markets, ratings, corporate, or a market recap. Each type has its own half-life (a policy decision lasts hours, a recap minutes) and weight.
  - **surprise against expectations,** parsed from the numbers: "CPI 5.4% vs 5.0% expected" is bearish whatever the level, and "eases to 5.1% but above the 4.8% expected" is still bearish. It also reads beats and misses of estimates and RBI/Fed cuts, hikes and holds. The surprise is signed for Indian equities (inflation above expectations hurts, growth above helps) and outweighs how the words lean.
  - **index heavyweights** named in the story, as their approximate share of each index: HDFC Bank news is ~28% a BANKNIFTY story and ~13% a NIFTY one. "Reliance Power" is not Reliance Industries.
  - **certainty:** "may", "sources say", previews and questions count half.
  - **novelty:** TF-IDF cosine against the day's earlier stories, so a retelling counts less than the first report.

A recency-weighted tone (each story fading at its event's half-life, weighted by certainty and novelty) is one piece of evidence with modest weight; the read names the biggest surprise behind it. After a high-impact story (RBI, the Fed, the budget, a CPI print, war), not a preview, the desk takes no new entries for 15 minutes. A **recap of the market's own move** ("Stock market crash: Sensex tumbles 700 points") never counts as high impact and weighs less in the tone: the move is already on the desk's tape. On 29 Sep 2026 five such recaps kept it out of the morning's sell-off for 55 minutes. A headline that reports an outcome along with the move ("RBI cuts repo rate by 25 bps, Nifty rallies", "… as HDFC Bank misses estimates") is news, not a recap. A story is invisible until its publish time on the engine's clock, so replays never see the future. Everything is journaled, and it's all on the site's **News** tab.

**What-if replays.** `deploy/whatif.py` replays a recorded day (its real 1m bars, the headlines as the desk fetched them, and the prior sessions from Yahoo) under variants: the code as it ran that day, no news filter, no RSI filter, a lower conviction bar, the EV gate off, no stop floor. It prints each variant's trades and what kept it out. Run it from the Actions tab (**What-if replay**, with a date and optionally the commit that ran that day); the table lands in the run summary.

## Learning from its own calls

Every call the desk makes is graded against what the market did next (`intraday/learning.py`), and the record
changes how much it trusts each input. It grades at the close, and catches up at the next open if a run died.
- **News:** each headline's tone, where the story is about an index, against that index's next 30 minutes. It is
  tracked by event type, by source and by reader (the rules, and the LLM once one is wired). News that lands
  overnight is graded from the open, the first moment the desk could act on it. The record becomes a trust
  multiplier on that kind of story's tone: a type that has been wrong pulls toward neutral, one that has been
  right counts for more.
- **Evidence:** every factor in every read (VWAP, ORB, PCR, futures OI, news, global links …) is graded on whether
  its direction called the next 30 minutes. Reads are 5 minutes apart against a 30-minute horizon, so each counts
  as a sixth of an observation. The factor's weight is multiplied by twice its shrunk hit rate (60% → 1.2×), within
  0.5×–1.5×. The read says so: *"Track record: vwap ×1.18, pcr ×0.84"*.
- **Setups:** each closed trade's R by setup, and by setup × day type. After 8+ trades the setup's conviction is
  scaled 0.6×–1.3×. A setup that has lost 0.3R a trade or worse (shrunk) stands aside, with the record named in the
  decision.
- **Pre-break entries the EV gate refused** are replayed on the bars that followed: target or stop first, within
  45 minutes. That shows whether waiting for confirmation is costing the desk.

**Two research tables ride along:**
- **Factor IC by horizon.** Each factor's direction is correlated with the move 5, 15, 30 and 60 minutes later. The t-stats use overlap-adjusted samples, so you can see which factors predict and over what holding period.
- **The buyer's edge.** Each session's realised volatility is set against the ATM IV read at the open, as realised ÷ implied over 20 sessions. A desk that only buys options needs realised to beat implied.

Both are on the Brain tab and in the session review. The option chain is now also tracked through the day (`intraday/chainflow.py`): OI wall migration, the 25Δ skew's trend and ATM IV's trend. The first two are new factors **on probation**: graded live, no vote until 30 graded reads at 1.15×.

**More reads, each tested before it acts:**

- **Index breadth** (`intraday/breadth.py`, live with Kotak). The NIFTY 50 and Nifty Bank stocks, once a minute: the share advancing, the share above their own VWAP, and the equal-weighted move against the index's. Two factors on probation: `breadth`, and `breadth_div` (a narrow move leans against the index).
- **BANKNIFTY vs NIFTY** (`intraday/relstrength.py`). Which index is leading, by how much, and how unusual that is. The learning loop measures whether the leader of the last 30 minutes keeps leading. Only once that IC has t ≥ 2 does it tilt conviction toward the leader for longs and the laggard for shorts.
- **FII index options positioning** (Brain tab, flows). FII and client net calls − puts, their change and percentile over the year, with the research's verdict on whether the change predicts the next session.
- **The buyer's edge over five years of bhavcopy** (warehouse research section 3, `buyer_edge.json`). The ATM straddle bought at the open and sold at the close, and close to next close, at real prices after spreads and fees, by days to expiry and weekday. The desk states what history says for today in its read.

Why these: [the quant gap review](docs/QUANT_GAP_REVIEW.md).

### The self-learning paper loop

The desk now learns from its own predictions and promotes a better model only on evidence (`quantdesk/autolearn`,
[architecture](docs/ARCHITECTURE.md)).

- **Recording.** At every 5-minute bar it writes each registered model's prediction to an append-only, hash-chained
  ledger, with the features, versions, data fingerprint and costs, before the outcome is knowable. The outcome is
  written later.
- **The cycle.** After the close, the `Learning cycle` workflow (`learn` is taken by the bootstrap) runs:
  1. ingest the bars, outcomes and closed paper trades;
  2. rebuild the versioned dataset;
  3. retrain candidates through day-grouped walk-forward with purge and embargo (the current DirectionModel is the
     baseline, alongside L2, L1 and boosted-stump variants);
  4. calibrate them and fit an abstention threshold;
  5. simulate costs, with block-bootstrap intervals;
  6. check the locked final test;
  7. register challengers;
  8. score their live shadow record;
  9. promote only when every gate passes.
- **Live behaviour.** A promoted champion's signal gates entries, and when it is unsure it abstains, so there is no
  trade. Each stage is idempotent and resumable, and promotion is fail-closed and audited, with rollback.
- **Honesty.** On a random walk every candidate fails and nothing is promoted (tested). No accuracy figure is
  promised: the status report shows what was measured.

```bash
python -m quantdesk autolearn cycle             # all stages (idempotent; --stages train,validate; --offline; --force)
python -m quantdesk autolearn status            # champion, freshness, last cycle, drift, risk, paper record, recovery point
python -m quantdesk autolearn verify            # ledger + registry + journal integrity (exit 1 on any problem)
python -m quantdesk autolearn recover           # torn writes aside, registry state rebuilt, unfinished stages reset
python -m quantdesk autolearn rollback --reason "…"
```

Operating controls:
- **Kill switch:** `runtime/KILL` flattens and halts.
- **Halts:** stale feed, failed journal check, unverifiable champion and drift alarm all stop new entries.
- **Caps:** an exposure cap on total open premium sits on top of the daily-loss and position limits.
- **Ollama:** advisory only, never weighed into a signal.

Recovery steps: [RECOVERY.md](docs/RECOVERY.md). Gates: [RELEASE_GATES.md](docs/RELEASE_GATES.md).

**Headlines that share a window are one observation.** A night's forty stories are all judged on the same opening
move, so they split one observation between them. Counted one each, the 403 headlines of 29 Sep 2026 had scored "66%
right" (×1.31 trust); counted properly they're 24 observations at 48% (×0.98).

**It doesn't start empty.** When the record has no grades, the morning job (and **Actions → Learning bootstrap**)
replays the last week of real 1-minute sessions through the same analyst: recorded bars, plus Yahoo's week of 1-minute
history. It grades every read's factors against what the index actually did, and grades the saved headlines. Setups
are left out: a replay's fills come from a model chain, so the setup record is built only from the desk's own trades.
Run it locally with `intraday learn --bootstrap`.

Everything is shrunk toward "no change" by a prior worth 20 observations (8 for trades), so one good or bad day
can't swing it. The memory is `runtime/intraday/memory.json`; it is saved with the journal and survives an account
reset (that resets money, not knowledge). Each session review ends with **What the desk learned**.
`python -m quantdesk intraday learn` shows the record. `--rebuild` grades the whole journal again from the
recorded bars, and `intraday replay --no-learn` turns it off for a replay.

**The chart** (phone app → Chart) shows the last sessions, not just today: 2 for 1-minute, 3 for 5-minute, 5 for
15-minute.
- **Why:** a late start (30 Sep 2026: ten bars from 15:20) never leaves ten candles alone on the screen.
- **VWAP:** restarts at every open, with no line across the overnight gap.
- **Session profile:** today's, or the day before when today is only a stub (the legend names its date).
- **Levels:** computed from the bars themselves, so they're there even before the desk's first read: prior-day
  high and low, CPR, the opening range once 15 minutes have traded, the initial balance after an hour, the value
  area and today's range. OI walls come from the desk's read.
- **Header:** H/L and the change refer to today's bars only.

### Stocks with liquid options

The index desk trades NIFTY and BANKNIFTY. F&O stocks are ranked from the same daily NSE bhavcopy (warehouse table
`fo_stocks`, filled by the Data workflow). Liquidity is measured on near-month options:
- premium traded
- strikes that traded 100+ contracts
- futures volume and OI
- the ATM straddle (the market's priced move)

`python -m quantdesk intraday stocks` prints the ranking and whether this account can hold the smallest
defined-risk position: one lot of a one-strike debit spread, about half the strike step × the lot. At ₹20,000 the
answer is mostly no. RELIANCE (lot 500, ₹10 strikes) is ≈₹2,500 a lot, 12.5% of the account, over the desk's 8% risk
budget. So stocks are a watch list at this size, and the ranking says which ones fit as the account grows.

**Buying one lot of a call or put** (the buyer-only desk's question) is checked too: the premium within the 35% outlay
cap and the 30% premium stop within the risk budget, at the money first, then two strikes out. On 1 Oct 2026
(26 days to expiry), none of the 25 most liquid stocks fit ₹20k. The closest were:
- BHARTIARTL: ₹6,412 a lot, ₹1,924 at the stop
- HDFCBANK: ₹6,662 a lot, ₹1,999 at the stop
- SBIN: ₹7,837 a lot, ₹2,351 at the stop

All against a ₹1,600 budget. They come within reach in expiry week, as premiums shrink, or at about ₹25k. The
ranking prints **BUY OK** when one does.

The volume units, checked on the warehouse's Sep-2026 data:
- `TtlTradgVol` counts **contracts**: only ~1% of values are lot multiples, i.e. chance.
- Open interest is in **shares**: 96% are lot multiples.
- So OI is divided by the lot, and volumes are not.

### Language models as second readers

With a key in the environment, each provider reads the headlines about an index next to the rules
(`intraday/llm.py`):
- **Claude:** `claude-opus-5-5` through the official `anthropic` SDK, at low effort, with structured JSON output
  and server-side refusal fallbacks (`fallbacks: "default"`).
- **Gemini** and **Ollama:** through their REST APIs.

For each headline, each reader gives NIFTY's and BANKNIFTY's likely direction over the next 30–60 minutes and a
confidence.
- **Background:** reads run on a background thread, so a slow API never holds the trading loop.
- **Point in time:** a read counts only from the moment it arrived, so replays never see one early.
- **Graded like everything else:** each reader is graded on its own (`news_reader` in the record). The tone weighs
  the rules and each model by how often each has called the move: a model that keeps being wrong fades.
- **Reflection:** after the close, Claude reads the session review and the learning record. It writes up to five
  lessons and three things to watch at the open, into the review and the memory. Nothing it writes touches
  orders, sizing or risk.

Keys (repository secrets, passed by `live.yml`):
- `ANTHROPIC_API_KEY`, or `CLAUDE_API_KEY`, `CLAUDE_API`, `CLOUD_API_KEY`
- `GEMINI_API_KEY`, or `GOOGLE_API_KEY`
- `OLLAMA_API_KEY`

Run **Actions → AI check** to see which secret names exist (names only, never values) and get a test read from
each provider. Locally, run `python -m quantdesk intraday ai-check`.

**Cost:**
- Headlines go 12 per call, at most 40 calls per provider per day (`intraday.llm`).
- One Claude headline call is ~2k tokens in and ~1k out: about $0.03 at $4/$20 per million.
- A busy news day costs about $0.50–1.50 for Claude; the reflection is a few cents.
- The review ends with the day's calls, tokens and estimated cost.

## Edge research (real data)

`python -m quantdesk research`, run weekly on GitHub as the *Edge research* workflow, tests a fixed, pre-registered list of hypotheses on real NIFTY, BANKNIFTY and India VIX data from Yahoo: 19 years of daily bars, 2 years of hourly and 60 days of 5m. Each hypothesis is judged with Newey-West statistics, discovery-only Benjamini-Hochberg control, a realistic one-lot cost hurdle, and a chronological rolling-validation slice.

The newest third is re-inspected by each weekly run, so it is **rolling validation**, not a fresh holdout. Every
run is appended to `experiment_log.jsonl` with its code digest, data fingerprints, hypotheses, parameters and
results. A result that survives everything is a **PAPER CANDIDATE**: the paper desk uses it, and that is its forward
test. Before any real money, a strategy must clear the paper gate (`quantdesk intraday paper-gate`): at least 60
paper sessions, 30 closed trades, positive net P&L after costs, profit factor ≥ 1.15, max drawdown ≤ 10% and no
risk-limit incidents.

The report and the append-only ledger go to the `research` branch.
See [release gates](docs/RELEASE_GATES.md) for measurable operating and promotion criteria, and
[recovery steps](docs/RECOVERY.md) for journal restore, session replay and safe restart.

First run (29-Sep-2026), 25 tests:
- **NIFTY's intraday drift is negative.** Open→close averages −5.7 bps a day, about −13 points (t −3.44 over 4,669 days). It holds in the newest third (−4.6 bps). Returns accrue overnight, not in the session. The desk adds this as a small bearish drift to every EV and as low-weight evidence.
  - It's real but thin: the open→close σ is ~266 points. One lot of a 0.35Δ option is a half-Kelly bet on this edge only for an account of about ₹3.7 lakh. At ₹20k it's a lean, not a strategy.
- **The volatility risk premium.** India VIX exceeded the next 21 days' realised vol by ~3 vol points on average, 80% of the time (t ≈ 7). Option buyers overpay on average. Harvesting it means selling defined-risk premium, which needs roughly ₹1.5–3 lakh of margin.
- **No edge on this data:**
  - opening-range breakout
  - VWAP reversion
  - first-hour and Gao-style intraday momentum
  - late-day trend
  - 30-minute momentum
  - gap continuation
  - post-fall rebounds
  - turn of the month
  - Tuesday expiry
  - VIX-spike rebounds (promising out of sample, too few cases to pass)

  Most of the classic intraday setups the playbook uses have no statistical support here. The EV gate and the research priors are what keep the desk from trading them blindly.

## The data warehouse (real NSE data, 2019 →)

`quantdesk/data/` keeps NSE's public end-of-day data as Parquet tables on the **`warehouse`** GitHub release
(release assets, so the git history stays small). `data.yml` updates it at 20:15 and 08:10 IST and fills every
missing day by itself; run it from the Actions tab with a start date to backfill.

| table | what | from |
|---|---|---|
| `fo_bhav` | every NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50 future and option, daily: OHLC, close, settle, underlying, OI, contracts | Jan 2019 (both bhavcopy formats) |
| `participant_oi`, `participant_vol` | FII / DII / Pro / Client positions and volume by product | Jan 2019 |
| `fii_dii` | FII/FPI and DII cash buy/sell/net | from collection start (NSE shows only the latest day) |
| `gift_nifty` | GIFT Nifty prints with NIFTY's prior close | from collection start |
| `corp_events`, `nse_holidays` | board meetings/results; the exchange's holiday list | current |
| `manifest` | every file fetched: URL, SHA-256, size, rows | — |

Parsers were written against the real files (`NSE data probe` workflow prints them). `quantdesk data status` shows
coverage and checks the config's holidays against NSE's own list. The live desk also keeps its recorded sessions
(option-chain snapshots, 1-minute bars, GIFT prints) for good on yearly `chains-YYYY` releases: with Kotak's
minute-by-minute chains this becomes the desk's own intraday options history.

```bash
python -m quantdesk data update --from 2026-09-01          # fill missing days (add --release warehouse on GitHub)
python -m quantdesk data status                            # coverage, gaps, holiday check
python -m quantdesk research --warehouse runtime/warehouse # + the option-price and positioning research
```

**Events.** `calendar.events` carry IST times. An announcement inside the session (RBI at 10:00, the Budget at 11:00)
blocks new entries from 15 minutes before to 45 minutes after it; FOMC, US CPI and India CPI land after the close and
are context ("since the last close: …" the next morning) instead of whole-day vetoes. Heavyweights' results come from
NSE's event calendar as context. **GIFT Nifty**: before the open the desk reads it every few minutes and states the
gap it implies after the futures' carry; the review compares it with the actual open (context, untested).

**Research on it** (`research/warehouse_research.py`, weekly in `research.yml`): the volatility premium traded on real
option prices (8 pre-registered structures, k sessions before each expiry, real closes worsened by a half-spread and a
tick, full costs, cash settlement), and FII/client positioning as next-session signals. Discovery runs on the older
2/3 with Benjamini-Hochberg on those p-values; the newest 1/3 must confirm. Verdicts say whether a real effect fits a
₹20k account or needs more capital.

## The validation framework (six layers)

Every strategy is judged the same way, from its per-trade P&L (`analytics/scorecard.py`): the weekly research report
prints a full scorecard for its strongest results, and `quantdesk intraday stats` prints one for the paper account.
Nothing here adds a step to the daily process.

| layer | what | where |
|---|---|---|
| 1 edge | expectancy W·AvgWin − L·AvgLoss, profit factor > 1.5, SQN, N ≥ 300 | scorecard |
| 2 risk & tail | Sharpe, Sortino, Calmar, Omega; skew, excess kurtosis; VaR/CVaR 95 & 99 (historical and Cornish-Fisher); max DD, time under water, recovery, Ulcer Index; P(ruin) by bootstrap | scorecard, `risk/metrics.py` |
| 3 execution | slippage break-even (₹ and bps of notional); live fills at the Kotak bid/ask with an entry-slip guard; no entry when a leg has no two-sided quote; each leg's book logged at entry (`ok`/`wide`/`no quote`); the liquid strike band in the read; fill audit vs recorded quotes; VWAP z-score; OFI and VPIN (library) | scorecard, `intraday/kotak.py`, `deploy/audit_fills.py`, `analytics/models.py` |
| 4 derivatives | Greeks incl. vanna, volga, charm, speed; IV rank/percentile (India VIX, and each underlying's ATM IV against the past year at the same days to expiry); 25Δ skew; VRP (IV − RV); naive dealer GEX and gamma flip; options-implied carry; futures basis, carry and roll yield | `options/pricing.py`, `options/gex.py`, `intraday/ivhist.py`, chain read, research |
| 5 robustness | discovery/rolling-validation split with FDR on discovery p-values; OOS efficiency; PSR and DSR (trials counted); ±10% parameter stability; walk-forward | research, scorecard, `backtest/walkforward.py` |
| 6 models | GBM, OU (fit and half-life), Hurst, variance ratio, Kalman hedge ratio, GARCH, HMM, SVI; Heston (pricing and calibration), Hawkes, PCA of the vol surface, vector Kelly Σ⁻¹μ, Almgren-Chriss, Avellaneda-Stoikov | `analytics/stats.py`, `analytics/volatility.py`, `analytics/regime.py`, `options/surface.py`, `analytics/models.py` |

The live read only gains context lines (dealer gamma, implied carry, the IV percentile, the liquid strikes), never
votes: they are untested here. The heavy models are a research library, outside the live loop.

- **IV percentile.** Short-dated IV depends on days to expiry: over the past year NIFTY's ATM IV had a median of 13.9 one
  day before expiry and 11.0 five days out. So today's ATM IV is ranked only against past sessions with the same days to
  expiry (±1, or ±3 when that leaves fewer than 15). The history is the nearest expiry's ATM IV at each close, from the
  warehouse bhavcopy, using strikes that actually traded. `deploy/warehouse-context.sh` pulls the last 13 months (~2 MB a
  month) before each session.
- **Liquidity.** A contract's book is `no quote` (not two-sided), `wide` (spread > max(₹0.10, 3% of the mid)) or `ok`.
  The read gives the run of strikes around the money whose out-of-the-money side is `ok`. At entry each leg's book goes
  into the trade (`leg_liquidity`). When the live book answers but a leg has no two-sided quote, the desk stands aside,
  as it does when the book has moved away from the plan.

## The brain (global markets ↔ news ↔ India ↔ the decision)

The brain connects everything the desk sees into one picture, and it's honest about which connections are worth betting on.

- **Global markets.** It watches 18 markets via Yahoo, refreshed every 5 minutes:
  - US: S&P 500, Nasdaq, Dow and their futures; CBOE VIX; the 10-year yield.
  - Asia: Nikkei, Hang Seng, Kospi, Shanghai.
  - Europe: Euro Stoxx 50, DAX, FTSE.
  - Currencies and commodities: the dollar index, USD/INR, Brent, gold.

  For each market it tracks the last session that *finished before India opened*, the move since 09:15, and the last 30 minutes, all in σ units of that market's own history. Daily bars keep each exchange's own date, so Tokyo's same-day session is never mistaken for a prior one.
- **Drivers.** Markets roll up into drivers: US equities, Asia, Europe, the dollar, the rupee, crude, US rates, fear (US VIX) and gold. Each is signed the way it usually leans on Indian equities.
- **Measured links.** The weekly edge research measures every driver → NIFTY/BANKNIFTY link on real data:
  - *explanatory*: β and correlation to the opening gap, and same-5-minute co-movement
  - *predictive*: a lead that survives rolling validation, false-discovery control and the cost hurdle

  The brain **explains with the first and only votes with the second**, in the *measured* direction.
- **News → drivers.** Crude headlines attach to the crude node, Fed stories to rates, China to Asia, war to fear,
  by title and by the NLP event type (an OPEC story is a crude story even without the word "crude"). Each driver's
  news tone uses the news desk's blend of the rules and the language models. Rumours and retellings count less.
  The brain can see whether price and story agree.
- **The leaders.** The index heavyweights (HDFC Bank, ICICI Bank, Reliance, Infosys … SBI, Axis, Kotak) are
  polled like the global markets. Their index-weighted 30-minute move is the *heavyweight pulse*. When the index
  moves against its leaders, the read calls it a narrow move.
- **Flows.** Yesterday's FII share of index futures held long (participant OI, with a week-earlier comparison) and
  FII/DII cash flows go into the narrative, from the warehouse.
- **Probation.** A driver with no validated research link (and the heavyweight pulse) still reports its live
  30-minute move as evidence, with **zero weight**. The learning loop grades it like every other factor. After 30+
  graded reads at a shrunk hit rate of 57.5% or better, it gets a small vote (0.25, then scaled by its record). If
  the record slips, it drops back to zero. Validated links vote from the start; everything else has to earn a vote
  live.
- **Risk overlay.** Big global moves or a US VIX spike shrink size (volatility targeting). At a 1-lot account size, ≈4σ of global stress means standing aside.
- **What you see.** The site's **Brain** tab shows:
  - the risk regime
  - the influence graph (world → India read → bias → decision)
  - what's pushing the bias right now
  - today's gap, explained
  - the global markets board
  - the measured wiring

What the research says about global markets (29-Sep-2026, 87 tests):
- **The US close sets the Indian open.** S&P 500 → NIFTY gap: β +0.20, correlation +0.42. US VIX runs against it (−0.38).
- **The US no longer predicts the Indian session.** Trading NIFTY in the direction of the prior US session earned +6 bps a day over 2007–26 (t +3.2). In the newest third of the data it **reversed** (−4.7 bps). The move is now fully priced into the gap. A brain that "connects the US to India" naively would be betting on a dead edge.
- **No intraday lead-lag survives.** No global market's last 30 minutes predicts NIFTY's next 30.
- **One marginal survivor.** BANKNIFTY *fades* Europe's previous session (−5.4 bps, t −2.55, holdout p 0.09). That's the only global link that currently votes.

So global context mostly **explains**; it rarely **predicts**. The desk won't pretend otherwise, and the research re-tests all of it every Saturday. Probability of profit is not the target, because high-POP trades like selling far-OTM options can still lose on average. Expected value after costs is.

## The website (use it from your phone)

`python -m quantdesk serve` serves the phone app, plus the daily desk at `/daily`. It is designed like a trading platform, not a report. The design was made with Claude Design (the canvas: phone and desktop screens in dark and light, the icon, tokens, components and states; the brief is in [`design/claude-design-brief.md`](design/claude-design-brief.md)). The direction is "hairline terminal":
- **Look:** cool near-black and near-white surfaces, sections split by hairlines instead of floating cards, and dense rows.
- **Colour:** one ink-blue accent for interaction, green and red only for direction and P&L, and amber only for waiting and warnings.
- **Type:** Geist and Geist Mono (vendored, so it works offline) with tabular figures, so prices line up.
- **Themes:** dark, light or auto (it follows the phone's theme, or pick one in Settings).
- **Layout:** a bottom tab bar on the phone, and a labelled sidebar with two-column Desk and Chart screens from 1,024 px.
- **Icon:** a price path that tests a level, pulls back and breaks through it, the desk's core idea.

| Tab | What's there |
|---|---|
| **Desk** | the paper account (equity, today's P&L, all-time, trades used of the daily cap, how much of the daily loss limit is used); a watchlist row per index (price, change, a 5-minute sparkline against the prior close, IV and premium, the desk's bias and what it's doing *in plain words*, e.g. "Standing aside: 5m RSI 16, too stretched to chase"); one sentence on what the desk is doing overall; open positions with legs, live P&L and a track showing spot between the stop and the target; the global pulse strip; the latest headlines; today's closed trades. **Pause / Resume / Flatten** on your own desk |
| **Chart** | the index price, day high/low and VWAP; candles (1m/5m/15m) with volume, VWAP, prior-day / opening-range / value-area / CPR / IB / OI-wall levels as toggleable price lines, entry and exit markers, an OHLC readout on the crosshair, pinch-zoom and a full-screen mode; below it the desk's read (a −1…+1 bias gauge, conviction, day type, premium, no-trade flags, narrative), the evidence strongest first, a key-levels table with distance from spot, and the quant layer (30-min 1σ move in points, the direction model's out-of-sample AUC and whether it votes, the research drift) |
| **Trades** | **Positions**; **History** grouped by session with a day P&L; **Performance** (net, return, win rate, profit factor, avg R, drawdown, green days, costs, an equity curve against starting capital, P&L by setup, breakdowns by day type / structure / exit / hour / index, calibration of the edge the desk assumed vs what happened); **Reviews**. Tap any trade for its full story: P&L and R, risk, costs, hold time, entry and exit on the stop-to-target track, legs, why it was taken, the market read, sizing, exit, review, lessons, fills |
| **Brain** | the global risk regime and stress, today's gap explained, the influence graph (world → India read → bias → decision), what's pushing the bias, the global markets board (colour = good or bad for India) and the research-measured wiring |
| **Feed** | **Headlines**: news tone per index, breaking-news stand-asides, feed health, filters (index, high impact, bearish, bullish); **Desk log**: the desk's reasoning over time, trades highlighted, tap to see the evidence |

Every term of art has a **?** that explains it in plain words (bias, conviction, premium, R, grades, levels, regime, stress, VWAP), and Settings has the whole glossary. Pull down to refresh. Deep links work (`/#chart`, `/#trades/history`, `/#feed/log`), and so do the home-screen shortcuts (long-press the icon). The GoCharting chart lives on the daily desk (`/daily`); the phone app uses TradingView Lightweight Charts with the **session profile** drawn into the price pane: the POC bar, the value area tinted, and the rest muted. NIFTY and BANKNIFTY are indices and their bars carry no volume, so the profile (and the desk's own POC/VAH/VAL, which the value-area setups read) is by **time at price** (TPO, Market Profile's original form). Before this fix those levels were empty on live data. GoCharting's own volume profile would be empty for the same reason, and its SDK needs a commercial licence for a public site. The UDF endpoint (`/api/i/udf`) is ready if you get a key.

**On your phone:**

```bash
python -m quantdesk serve --host 0.0.0.0     # prints http://<your-LAN-IP>:8765/?token=…
```

Open that link once on the phone, on the same Wi-Fi. The token is remembered in an HttpOnly cookie. Then use **Add to Home Screen**: it installs like an app, full-screen, with its own icon.

**Away from home:** install [Tailscale](https://tailscale.com) on the computer and the phone, then open `http://<computer's tailscale name>:8765/?token=…`. Don't port-forward it to the open internet.

**Share a read-only snapshot:** `python -m quantdesk intraday export-site --account live --out site.html` writes the whole app plus an account's data as one HTML file. Host it anywhere static; the controls are off in a snapshot. For a site that stays current, use `--dir` (see [Running it every day by itself](#running-it-every-day-by-itself)).

The Pages app is intentionally a full paper-performance disclosure: balance/P&L, positions,
closed trades, up to 150 trade details, session reviews, recent reads, headlines and charts are
public. It contains no real broker account or credentials. See [release gates and disclosure](docs/RELEASE_GATES.md)
before adding any personal, live-account or private data.

**How the pieces fit:** the engine (`intraday live`) and the website are separate processes sharing the journal. Commands from the phone are queued, and the engine applies them on its next minute. Everything is paper-only; the website can pause, close or flatten, but never places real orders.

## Running it every day by itself

**Does it trade on its own when the market opens?** Yes, as long as the engine is running. Once
started, `intraday live` waits for 09:15 and then works alone until 15:30: it reads every minute,
thinks, takes and manages paper option trades, squares off at 15:15 and writes the day's review.
Something has to start it each morning, though. There are two ways to set that up so you never
touch it.

### A. GitHub Actions + GitHub Pages (free, no computer needed)

`.github/workflows/live.yml` runs the desk on GitHub's machines every weekday:

| IST | What happens |
|---|---|
| 08:25–08:52 | The `morning` job starts (see *Who starts it* below). It checks Yahoo/NSE reachability (`doctor`), restores the journal from the `journal` branch, and waits for the open |
| 09:15 | It trades on paper and re-publishes the website every 6 minutes |
| 12:20 | It hands over without squaring off. A hosted job may run for at most 6 h, and the session is 6h15m |
| 12:21 | The `afternoon` job restores the journal and resumes the same session: open positions, trades closed so far, the day's P&L, the loss streak, the cooldown |
| 15:15 | It squares off |
| 15:30 | It writes the session review, saves the journal, posts the review in the run summary, and keeps the day's bars and option chains as a 90-day artifact |

On NSE holidays both jobs exit within a minute.

**Who starts it.** GitHub's own scheduled events are best-effort: on 29 Sep – 1 Oct 2026 live.yml's 08:52 cron arrived at 15:19–15:46 IST, and the desk lost two sessions. So `scheduler.yml` checks every 10 minutes, around the clock, and starts the desk by `workflow_dispatch` (which runs at once) whenever it's an NSE trading day between 08:25 and 14:45 IST and no run is queued, running or done for the day (`deploy/scheduler.py`). A failed day is retried up to three times. A run you **cancelled** keeps the desk stopped for the rest of that day, so the kill switch still works. Live.yml's own cron stays as a backup; a late one finds the session over and exits.

That wasn't enough: GitHub throttles cron on this repository so hard that the 10-minute scheduler fired three times on 2 Oct 2026 (21:27, 01:46 and 05:18 IST). So **Cloudflare is the alarm clock**. The Worker's cron trigger (`wrangler.jsonc`: every 10 minutes, 07:30–15:20 IST, Mon–Fri) fires on the minute and asks GitHub to run `scheduler.yml` now. `scheduler.py` then decides exactly as above. One-time setup:
1. GitHub → Settings → Developer settings → Fine-grained tokens → *Generate new token*. Repository access: only `Quant-Desk`. Permissions: **Actions: Read and write**. Set an expiry you'll remember.
2. Cloudflare dashboard → Workers & Pages → the Worker → Settings → Variables and Secrets → **Add** → type *Secret*, name `GH_DISPATCH_TOKEN`, value the token.

Without the token the trigger logs why and does nothing (the Worker's Logs show it).

**Checking the fills.** `audit.yml` (Actions tab, optional date) downloads the recorded option chains from the live runs' artifacts and checks every paper fill against the bid/ask the market actually showed, with each trade's P&L at those quotes (`deploy/audit_fills.py`).

- **The live website** is at `https://mrityurequest20-cyber.github.io/Quant-Desk/`. It is the same phone app, **read-only**, re-published every ~6 minutes while the desk runs. The status pill reads **Live** while the heartbeat is fresh, **Closed** outside market hours and **Offline** when the connection or desk is unavailable; cached data is labelled as potentially stale. **Install it:** on Android, Chrome offers *Install app* (the app shows a card for it too); on iPhone, Safari → Share → *Add to Home Screen*. It then opens full-screen from its own icon, and a service worker keeps the last state readable offline.
- **On Cloudflare too.** Cloudflare Workers Builds deploys the `quantdesk` Worker from `main` with `npx wrangler deploy` (no build command). The Worker (`deploy/cloudflare/worker.js`, configured in `wrangler.jsonc`) passes every request to the GitHub Pages site above, so it serves exactly what the desk last published, with `data.json` never cached at the edge. It only redeploys when those two files change, not on every data update. The site itself is still published to Pages, so Pages must stay on.
- **App updates** reach the site on their own: `site.yml` re-publishes the site whenever `quantdesk/web/` changes on `main`, after any running desk has finished (a running desk keeps publishing with the code it started with).
- **The journal** lives on the `journal` branch: the SQLite journal, the paper broker, the reviews and the recorded 1m bars. To read it locally, run `git fetch origin journal && git archive FETCH_HEAD | tar -x -C runtime`, then `quantdesk intraday stats` or `quantdesk serve`.
- **Kill switch:** in the Actions tab, open the running *Live paper desk* run and press **Cancel**. Open paper positions are squared off at current prices (`live --close-out`), and the site and journal are saved.

One-time setup:
1. Create the repo on GitHub and push this code to `main`. Workflows are enabled by default.
2. Go to **Actions → Live paper desk → Run workflow** once to try it, or wait for the next weekday.
3. Once the first run has created the `gh-pages` branch, go to **Settings → Pages → Build and deployment → Deploy from a branch → `gh-pages` / root**.

Why the repo should be **public**:
- GitHub Pages is free only for public repos. A private repo needs a paid plan for Pages.
- Actions minutes are unlimited on public repos. A private repo's 2,000 free minutes a month last about five trading days, because the desk uses about 400 minutes a day.

Public also means your paper journal is public. It is paper, and it contains no keys: never commit Kite credentials. If you add Kite later, use repo **Secrets**.

Caveats:
- GitHub can start scheduled runs 5–20 minutes late. The engine back-fills the missed bars, but it takes no trades before it's running.
- GitHub pauses scheduled workflows in a repo with no activity for 60 days. If that happens, re-enable the workflow from the Actions tab.
- Runners are in the US, so the NSE chain is often unreachable. The desk then prices off the model chain (see Known limitations).

### B. Your own always-on machine (full controls, real NSE chains from India)

On a home PC, a Raspberry Pi 5 or an India-region VM, the phone app keeps **Pause / Resume / Flatten / Close**:

```bash
# Docker
echo "QUANTDESK_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(18))')" > .env
docker compose up -d --build          # `desk` trades every session, `web` serves the app on :8765

# or systemd: deploy/quantdesk-desk.service + deploy/quantdesk-web.service (install steps inside)
# or cron:    python -m quantdesk schedule   (prints the crontab lines)
```

Reach it from your phone over [Tailscale](https://tailscale.com): `http://<machine>:8765/?token=<token>`.

### Commands for unattended running

| Command | What it does |
|---|---|
| `quantdesk intraday doctor` | Can this machine see the market? Yahoo bars per symbol with their lag, NSE expiries and chain, today's calendar |
| `quantdesk intraday live` | Waits for 09:15 and trades today's session to the close |
| `… live --until 12:20 --handover` | Stops at 12:20 **without** squaring off; the next `live` run resumes the session |
| `… live --forever` | Trades every NSE session and sleeps in between (for Docker/systemd) |
| `… live --close-out` | Squares off today's open positions now and closes the session (the kill switch) |
| `quantdesk intraday command pause\|resume\|flatten\|close ID` | Controls the running engine from a terminal (the same queue the app uses) |
| `quantdesk intraday export-site --dir _site` | Writes the read-only site (index.html + data.json); the page re-reads data.json every minute |

## The quantitative stack

**Analytics** (`quantdesk/analytics/`):
- **Indicators:** EMA/SMA/Wilder, RSI, MACD, Bollinger, ATR, ADX/DI, Supertrend, Donchian, Keltner, stochastic, OBV, VWAP, Kaufman efficiency ratio, chandelier stops.
- **Realised volatility:** close-to-close, Parkinson, Garman-Klass, Rogers-Satchell, Yang-Zhang and EWMA, plus a vol cone.
- **GARCH(1,1)** by quasi-MLE, with the recursion run as an IIR filter. The rolling forecast is causal: it refits quarterly and filters forward.
- **Tests:** ADF with AIC lag choice and MacKinnon p-values, Engle-Granger cointegration, OU half-life, Hurst exponent (rolling and vectorised), Lo-MacKinlay variance ratio, and a Kalman-filter dynamic hedge ratio.
- **Regimes:** a 2-state Gaussian HMM (Baum-Welch, scaled forward-backward) fitted causally and forward-filtered, combined with trend and volatility rules into `trending_up | trending_down | range | stressed`.
- **Chart reading:** confirmed swing pivots, clustered support and resistance, HH/HL structure, floor pivots, candlestick patterns, gaps and 52-week context, all turned into a narrative.

**Options** (`quantdesk/options/`):
- BSM and Black-76 pricing, Greeks (checked against finite differences), and IV by Newton with a Brent fallback.
- Delta-to-strike solving that respects the smile.
- A parametric put-skew model plus SVI fitting for real chains.
- The NSE expiry calendar: NIFTY weekly on Tuesday; monthly on the last Tuesday; moved back a day when that day is a holiday.
- Multi-leg structures: condor, fly, verticals, straddle and strangle. Each reports max profit and loss, breakevens, net Greeks, probability of profit, and **expected P&L under your own vol forecast**, which is the number that says whether premium is rich or cheap.

**Strategies** (`quantdesk/strategies/`):

| Strategy | Market | Edge hypothesis | Entry → exit |
|---|---|---|---|
| `trend_rider` | stocks | Trends persist | Fresh EMA20/50 cross above SMA200 with ADX ≥ 20 → chandelier trail or opposite cross |
| `breakout` | stocks | Compression precedes expansion | 55-day high out of a Bollinger squeeze on volume → 20-day low |
| `mean_reversion` | stocks | Short-term overreaction in an uptrend reverts | z < −2 or RSI(3) < 15, above SMA200, rolling Hurst < 0.55 → z > 0 or 8 bars |
| `momentum` | stocks | 12-1 month cross-sectional momentum | Top 3 by risk-adjusted 12-1 month return, monthly rebalance with a rank buffer |
| `pairs` | stock futures | Cointegrated spreads mean-revert | Engle-Granger p < 0.05, half-life < 40 days, \|z\| > 2 → \|z\| < 0.4, z-stop 3.8, re-tested monthly |
| `vrp_condor` | index options | Variance risk premium (IV > forecast RV) | IV rank > 40%, IV − GARCH > 1.5 pts, not stressed, no event, positive model EV → 16Δ/6Δ condor, 50% TP, 1.5× SL, exit at 1 DTE |
| `trend_spread` | index options | Trends plus cheap IV | Confirmed index trend with IV rank < 55% → 55Δ/25Δ debit vertical |
| `long_vol` | index options | Vol too cheap vs forecast, or coiled | GARCH − IV > 2 pts or squeeze, IV rank < 25% → ATM straddle |

The **allocator** scales each idea's risk by a (strategy family × regime) weight and a shrunk tilt from the strategy's own recent R-multiples. Strategies never size positions or send orders.

**Risk** (`quantdesk/risk/`):
- Per-trade risk: 0.75% of equity to the stop; 2.5% worst-case loss for defined-risk option structures.
- Portfolio caps: total and per-strategy open risk, gross delta-notional, per-symbol exposure, net vega, net delta, margin, and orders per day.
- Linear de-risking from a 6% drawdown, reaching a **15% drawdown kill switch** that flattens and halts.
- A daily loss limit that blocks new entries.

**Costs** (`quantdesk/execution/costs.py`):
- Brokerage, STT, exchange charges, SEBI fee, stamp duty and GST, per segment.
- STT on F&O as revised in the Union Budget 2026-27: **0.15% on option premium (sell side) and 0.05% on futures**, effective 1-Apr-2026.
- Volatility-aware slippage for stocks and futures; half-spread for options.
- Current NSE lot sizes: **NIFTY 65, BANKNIFTY 30** (circular NSE/FAOP/70616).

**Backtesting** (`quantdesk/backtest/`):
- Event-driven and daily.
- **Decisions at the close of bar t fill at the open of t+1.**
- Stops fill intrabar at the worse of the open and the stop (the stop is assumed hit first if both the stop and the target are touched).
- Entries that gap through their stop are cancelled.
- Options are marked with VIX-based IV plus skew and settled at intrinsic on expiry.
- Deterministic.
- Walk-forward optimisation, trade-order and block bootstrap Monte Carlo, and the Probabilistic and **Deflated Sharpe Ratio**, so a backtest Sharpe gets discounted for sample length, fat tails and the number of variants tried.

**Journal** (`quantdesk/journal/`): SQLite with one row per trade, holding:
- the plan in words
- the context snapshot
- the sizing arithmetic
- fills with a cost breakdown
- MAE and MFE
- an automatic review

Grades weight **process 60% and outcome 40%**, so a planned −1R stop-out beats a lucky +2R that ignored the plan. Lessons are generated automatically, for example: round-tripped a 1R open profit, stopped out inside noise, costs ate 30% of gross, regime changed mid-trade. Every rejected idea is kept too, with the limit that bound it.

## How we know there's no look-ahead

`tests/test_causality.py` recomputes every indicator, every strategy's feature table, the GARCH forecast, the HMM and the regime frame on truncated history. It then asserts they equal the full-history values at the cut. Other tests check that:
- the engine fills at the next open
- stops gap correctly
- books reconcile to the rupee (Σ trade P&L = equity change; broker fees = trade fees)
- two runs are identical
- the paper runner never processes a day twice
- the kill switch blocks new orders but never closes
- the GoCharting datafeed adapter works against a live server, run under Node

## Results on the synthetic market (read the caveat)

There's no market data in the build environment, so the demo runs on a built-in simulator. The simulator is calibrated to NIFTY 2015-26: 11.3% CAGR, 15% vol, −39% max drawdown. It includes regime switching, GJR-GARCH clustering, crash jumps, a VIX with a variance risk premium, momentum, and cointegrated pairs.

On it, the combined book (2018 → Sep-2026, ₹20 L) returned **~5% CAGR at ~7% vol with a −15% max drawdown**. Buy-and-hold made 11.2% with a −39% drawdown. Sharpe against the 6.5% risk-free rate was about −0.2, after ₹1.9 L of costs. **That is not a good result, and it's reported as is.** Pairs, breakout and momentum made money. Trend-rider and mean-reversion lost it; the latter mostly to delivery STT. Synthetic data proves the machinery works; it says nothing about edge. Run `backtest` and `walkforward` on real NSE data, and trust only out-of-sample, cost-inclusive, DSR-adjusted numbers.

## Live trading

Live trading needs all of the following:
- `account.mode: live` in config
- the `--live` flag
- `KITE_API_KEY` / `KITE_ACCESS_TOKEN` in the environment
- `pip install kiteconnect`
- no `runtime/KILL` file

Every order is a marketable LIMIT inside a ±1% band, never a bare MARKET order, and there's a per-order notional cap. The Kite adapter follows the kiteconnect API but has **not been exercised against a real account**. Paper-trade first, then go live with one lot.

## Configuration

Everything is in `config/quantdesk.yaml`: account, universe, contract specs, costs, slippage, risk limits, strategy parameters, allocator weights, regime settings, calendar (2026 NSE holidays, events), check thresholds, desk UI and live guard rails. Overlay your own values with `--config my.yaml`.

**Re-verify lot sizes, STT, expiry weekday and holidays whenever NSE or SEBI issue a circular.** The holiday list is marked with which dates were cross-checked.

## Known limitations

- **Options history:** there's no free historical NSE option-chain data, so option P&L in backtests is model-priced (VIX × IV beta + skew). Real chains have wider, stickier spreads around events. Plug a chain source into `OptionPricer` and `SVI.fit` when you have one.
- **Futures:** futures are priced off spot, and basis and roll cost are ignored. Pair legs ignore lot rounding.
- **Intraday data:** the free path (Yahoo + NSE) is best effort. For real quotes add a Kotak Neo consumer key (or use Kite). The intraday desk models only index options on NIFTY and BANKNIFTY.
- **Kite:** the Kite path and GoCharting's full SDK are untested from this environment. Both are behind guards and have fallbacks.
- **GitHub-hosted runs:** the runners sit in US data centres. Yahoo works from there; NSE often refuses those IPs, and then options are priced off the model chain (India VIX + skew) rather than real quotes. The site says which chain is in use. For real chains, run the desk on a machine in India.

## Layout

```
quantdesk/                    (repo root)
  .github/workflows/          live.yml (the desk, every trading day), ci.yml (tests + doctor)
  deploy/                     run-session.sh, journal.sh, push-dir.sh, systemd units
  Dockerfile, docker-compose.yml
  config/quantdesk.yaml       all parameters
  quantdesk/
    analytics/                indicators, volatility, stats, regime (HMM), chart reading
    options/                  pricing, surface (skew/SVI), chain, structures
    strategies/               8 strategies + base contract
    risk/                     manager (sizing/limits/kill switch), allocator, metrics (PSR/DSR)
    execution/                costs, paper broker, Kite adapter
    engine/                   engine (backtest = paper = live), live runner (daily routine, chart orders)
    backtest/                 runner, walk-forward, Monte Carlo
    journal/                  SQLite journal, trade and period reviews
    ops/                      routine checks
    reporting/                HTML tearsheet, market analysis
    intraday/                 real-time desk: feeds, chains (Kotak/NSE/Kite/model), order flow, features, analyst,
                              playbook, quant (vol forecast, direction model, EV engine), news, brain (global
                              markets, drivers, measured links, risk overlay), risk, sim broker,
                              engine, recorder, synthetic sessions, CLI
    research/                 edge research on real data (pre-registered hypotheses, HAC, holdout, FDR)
    web/                      server (token auth), intraday API, mobile app (PWA), daily desk, GoCharting datafeed
    data/                     Yahoo, CSV, synthetic market, validation, the global universe
  tests/                      the test suite
```

## Sources for the market rules

- NSE lot-size revision (NIFTY 75→65, BANKNIFTY 35→30), circular NSE/FAOP/70616: [HDFC Sky](https://hdfcsky.com/news/nse-revises-market-lot-sizes-for-major-index-derivatives-effective-january-2026), [NSE circular](https://nsearchives.nseindia.com/content/circulars/FAOP70616.pdf)
- STT on F&O raised in Budget 2026-27: [ICICI Direct](https://www.icicidirect.com/futures-and-options/articles/stt-changes-in-budget-2026-what-f-o-traders-need-to-know), [ClearTax](https://cleartax.in/s/securities-transaction-tax-stt)
- NIFTY weekly expiry on Tuesday: [Share.Market](https://www.share.market/buzz/insights/weekly-expiry-days-in-indian-fo-markets/)
- NSE 2026 trading holidays (circular CMTR71775): [NSE](https://www.nseindia.com/resources/exchange-communication-holidays)
- GoCharting SDK: [docs](https://gocharting.com/sdk/docs), [reference demo](https://github.com/GoChartingInc/gocharting-sdk-demo)
