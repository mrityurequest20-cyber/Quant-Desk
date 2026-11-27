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

## Not yet in it

- MCX commodities. The warehouse has no MCX options, open interest or history, and the only MCX minutes come
  from a licensed broker feed that must not be published.
- The Claude-labelled news model, which is waiting on the owner's API key.
