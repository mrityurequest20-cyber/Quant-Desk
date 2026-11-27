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

## Method, briefly

- **Implied vol** is computed from the bhavcopy itself. The forward comes from put-call parity at the strike where
  call and put prices are closest, then Black-76 is applied on the out-of-the-money side. Strikes that did not trade
  only have a theoretical settlement price, so they are kept out of the at-the-money numbers and the smile.
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
- Live intraday data. That needs a broker feed served privately, never on a public page.
- The Claude-labelled news model, which is waiting on the owner's API key.
