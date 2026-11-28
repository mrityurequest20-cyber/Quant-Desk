# MarketLens

A read-only analysis app for Indian index and stock derivatives. It covers NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY,
NIFTYNXT50, SENSEX and BANKEX, the 20 most-traded F&O stocks, and India VIX. The data comes from the exchanges' own
end-of-day files. Every number is explained in plain words, judged against its own history, and never turned into a
buy or sell call.

It is a separate project that lives in this repository. It reads Quant-Desk's public warehouse release, and that is
its only link to Quant-Desk.

## What it shows

| Page | What |
|---|---|
| Market pulse | India VIX, NIFTY's priced move, FII positioning and cash flow, the options map (every name's option price vs its actual movement), the calendar, and where options are most unusual |
| Volatility screener | All instruments side by side: IV, its percentile, realised vol, IV − RV, priced move, skew, PCR, carry, build-up, results |
| Who holds what | Participant-wise open interest since 2019: long shares, net futures, options stance, percentiles |
| FII / DII money | Cash-market net buying, streaks, running totals |
| Instrument pages | **Overview** (the story today, KPI tiles) · **Volatility** (IV vs RV, the premium, term structure, smile, skew history, volatility cone) · **Expected move** (the priced range, how often price stayed inside it since 2019, the curve) · **Options positions** (OI by strike, today's change, PCR) · **Futures** (carry, OI, 30-day build-up table, rollover by expiry) · **Events** (results with priced event move vs actual and IV crush, macro-day study, biggest days) |

A **Simple / Analyst** switch controls detail: Simple shows plain sentences, Analyst adds the method and the numbers
behind each sentence.

## Live mode (during market hours)

The app is served by the desk's Cloudflare Worker at `/lens/` (deploy/cloudflare/lens.js), the same origin as the private
live relay. Every 5 seconds (the relay's own update rate; paused while the page is hidden) it reads `/live/snapshot` with the owner's key, the `qd.livekey` the desk app already keeps
on the device, and recomputes live panels with `web/livecore.js`:

- price and day change
- front-expiry IV against the same expiry's close, plus its percentile against the past year
- the priced move and its range
- the live smile and 25-delta skew
- open interest added today by strike, and near-money PCR now vs at the close
- today's futures build-up against the same contract's close
- gamma by strike on the live chains (same rule as the close), with the hedgers' net and flip against the close's
- max pain on live open interest (today's expiring contract on expiry day)
- the day minute by minute: the at-the-money straddle of the front (or expiring) contract and its Black-76 vol, from
  the relay's one-close-a-minute series (`/live/series`), fetched once a minute
- every futures month the feed carries (current, near, far: `NIFTY-FUT`, `NIFTY-FUT-2027-01-25`, ...), each against its
  own close, with the calendar spread between months

`livecore.js` applies the same rules as `engine/vol.py`, line for line. `tests/test_live.py` and a real-chain parity
run check this: on 695 expiries over 40 sessions (the nearest six plus the monthlies), forward and straddle are identical and ATM IV agrees within 2e-6.

Prices older than 120 seconds, and options not traded today, are not used. Option chains may be up to 8 minutes old:
on Kotak alone the relay rotates each stock's chain through the calls its prices leave free (about every 6 minutes).
A chain is one call, so its strikes come from one moment and its own parity forward keeps the read consistent; a
chain older than 2 minutes is labelled with its age. Outside the session the panels step aside
and the page shows the analysis at the last close. Live prices are licensed, are read only with the owner's key, and
are never stored.

## Method, briefly

- **Implied vol** is computed from the bhavcopy itself. The forward comes from put-call parity at the strike where
  call and put prices are closest, then Black-76 is applied on the out-of-the-money side. Strikes that did not trade
  only have a theoretical settlement price, so they are kept out of the at-the-money numbers and the smile.
- **Which expiries**: each day the nearest six, plus the current, near and far monthly contract (the last expiry of
  each of the nearest three calendar months), labelled weekly / current month / near month / far month. A monthly
  contract must trade at least 0.2% of the busiest *monthly* near the money (not of an expiry-week weekly, which
  trades hundreds of times more); an expiry that did not trade at the money is withheld, never shown from settlement
  prices. Stocks' far month comes from the warehouse's `fo_stock_far` table.
- **Futures by month**: price, basis, carry (20+ days out only), open interest and its share, and the change against
  the same contract the session before, for every listed month.
- **Gamma by strike**: Black-76 gamma at each strike (vol off that expiry's liquid smile) x open interest x F^2 x 1%,
  in Rs crore of hedging per 1% move, over every expiry on the curve. The concentration (calls and puts) needs no
  assumption. For indices, the *hedgers'* net (Pro + FII, the desks that delta-hedge) is signed from NSE's own
  participant file (their net share of index call and put open interest), with the price where it flips. The file
  is one figure for all index options, so the net is an estimate and is labelled one; stocks get no net (the file
  lumps all stocks together).
  *Tested, not assumed:* since 2019, days with the hedgers short gamma were followed by bigger raw moves (NIFTY
  0.69% vs 0.51%), but measured against what options already priced that day the gap vanishes (0.57 vs 0.59 of the
  priced daily move, permutation p = 0.66; BANKNIFTY 0.58 vs 0.58). The app says so: the map shows where hedging
  sits, not a forecast.
- **The expiry in front**: max pain (the settlement with the least payout to option buyers), the biggest call and
  put strikes, the payout curve, and the straddle's decay against the square-root-of-time path.
  *Tested:* from the close before each expiry, did the settlement land closer to max pain than to the mirror point
  the same distance on the other side (a coin toss with no pull)? NIFTY 43% of 306 expiries (it settles *away* from
  max pain more often; two-sided p = 0.014), BANKNIFTY 50%, FINNIFTY 52%, stocks 40-47%, SENSEX 61% of 82 (p = 0.03,
  one of several tests). There is no pinning to trade on, and the page says that.
- **The curve between months**: constant-maturity 30, 60 and 90-day IV (only where the listed expiries reach the
  horizon), the 60-30 spread with its percentile, and each monthly contract's ATM IV and skew. **The roll between
  months**: ln(next future / this future) annualised over the days between their expiries, against the premium
  over spot.
- **The whole F&O market** (all ~220 F&O stocks, not just the app's twenty): each stock's at-the-money straddle IV
  (the nearest expiry at least a week out) ranked against its own past year, and the share of stocks with dear
  (80th percentile+) or cheap (20th-) options; each stock's futures day classed by price x OI on the same contracts,
  and the share of stocks in each class; NSE sector indices' realised vol against their own year. The straddle IV
  equals the engine's own straddle vol on every shared day (34,435 of them) and is within a median 0.05 vol points
  of its smile ATM vol; the vectorised futures classes match the instrument pages on all 34,662 stock-days.
- **How much of a stock's move is its own**: rolling 63-session regression on NIFTY and the stock's sector index;
  one minus the R-squared is the share of its variance its own events drive.
- **How it moves** (new tab; nothing directional): ATR, close-to-close against Parkinson / Garman-Klass /
  Yang-Zhang range vol, the overnight share of variance, gaps, compression (20-day range and band width against the
  year, NR7) and, for stocks, volume z-score, delivery % and Amihud illiquidity from NSE's cash bhavcopy. NSE's
  previous close is not adjusted for bonuses (Reliance 28 Oct 2024: 2,655.70 against an open of 1,337), so the
  app's own split list rescales history. *Tested:* after compressed days the next 10 sessions' realised vol rose
  against the recent vol (stocks about 1.08x against 0.91x), but measured against the IV options priced that day it
  was no larger (NIFTY 0.77 against 0.86, block-permutation p = 0.99): ordinary mean-reversion that options price.
- **Days like today** (Expected move tab): every past day in the same options state (IV cheap / normal / dear
  against its year, premium sign, curve inverted or not), and the 40 nearest days on the continuous readings (one
  per 10 sessions), against the baseline of every day: the next 21 sessions' realised vol as a share of the IV, and
  how often the price ended inside the IV's one-sigma range, with 90% moving-block bootstrap intervals and the
  before/after-2024 split. Tested to read fairly priced noise as an ordinary day and to find a planted effect.
- **30-day IV** interpolates total variance between expiries, so a weekly and a monthly calendar can be compared
  over the years.
- **The event move** is the extra variance in the front expiry over the forward variance to the next expiry,
  expressed as a one-day move.
- **Splits and bonuses** are detected from the one-day jump plus the lot-size change, then removed from the price
  history.
- **Percentiles** compare each day with the days before it.

## Run it

```
python -m marketlens fetch --dest wh          # the public warehouse tables (~500 MB)
python -m marketlens build --warehouse wh --out lensdata
python -m marketlens site --data lensdata --out site && (cd site && python -m http.server)
python -m pytest marketlens/tests
```

`.github/workflows/marketlens.yml` runs this after each warehouse update and publishes `site/` to the
`marketlens-site` branch.

## Commodities (MCX)

MCX's own files refuse automated reads (403, from GitHub's runners as well), and the MCX prices the desk receives
are licensed. So the public side shows the international benchmark each contract tracks (WTI, Henry Hub, COMEX gold,
silver, copper; with USDINR, the dollar index, US 10-year, CBOE VIX and S&P futures), its realised vol against its
year, and its import parity (the benchmark in the MCX unit in rupees, before duties). The live side, in the browser
with the owner's key, reads the MCX futures and option chains the relay carries with the same engine as NSE's: ATM
IV, priced move to the option expiry, smile, skew, open interest and max pain, with time to the 23:30 close. MCX
options are on the future; when the quoted future is an earlier month than the options' own underlying (copper's
December options while the near future is November's), it does not anchor the forward.

## Alerts

On by default. The desk's Worker evaluates the rules every ten minutes in market hours (NSE on trading days
09:20-15:30 IST, MCX on weekdays 09:05-23:30, the ban list in the evening once the site is rebuilt) and pushes each new
alert to the owner's phone through ntfy, the watchdog's channel. Rules: front-expiry IV at a one-year extreme, a move
of more than twice what options priced for the day, an index crossing the hedgers' gamma flip, an inverted curve, a
watchlist stock in or near the F&O ban, and an MCX commodity moving more than its options priced. Each fires at most
once a day (the relay keeps the keys sent); the Alerts page sets them (thresholds, on/off) with the owner's live key,
and the browser shows the same alerts while the app is open. The rules are one file (web/alertrules.js) used by both
the browser and the Worker (deploy/cloudflare/ holds byte-identical copies, checked by a test).

## Not yet in it

- MCX history (IV percentiles): there is no public MCX file to build it from; live MCX readings are not stored.
- The Claude-labelled news model, which is waiting on the owner's API key.
