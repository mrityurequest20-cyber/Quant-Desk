# The pre-market brief

Before the open, the desk reads what today holds for **every F&O instrument** and writes it down with its reasons.
`premarket.yml` builds it every 15 minutes from 07:15 to 09:15 IST on weekdays; the app's **Today** tab shows it.

```
python -m quantdesk premarket history --warehouse runtime/warehouse     # each company's results history (once a day)
python -m quantdesk premarket brief   --warehouse runtime/warehouse --history runtime/premarket/results_history.parquet
```

It reads public data only: NSE's tables in the `warehouse` release, Yahoo and public RSS feeds. It never reads the Kite
feed, whose data is licensed to the subscriber. It places nothing, sizes nothing and changes no desk path. The
recording plan it writes is advisory: no recorder reads it yet.

## What a brief holds

| Part | Source | What it says |
|---|---|---|
| Universe | `fo_stock_opts`, `fo_bhav` (latest session) | Every F&O underlying, indices and stocks, with no list to keep and no cap: price, lot, strike step, option contracts and premium traded, active strikes, the futures OI change |
| Expiry | `fo_bhav` expiries | Which indices' options expire today, with the measured expiry-day record |
| Macro | config `calendar.events` + `quantdesk/premarket/macro_dates.json` | Today's events and those since the last close (FOMC, US CPI), each with its past sessions' index moves from `nse_index_close` and the measured evidence |
| Results | `corp_events` (NSE's event calendar) | Every F&O company reporting today, or reacting today to results after the last close: the move its options price for the event, against its own past results moves |
| Overnight | Yahoo (the desk's global list) | Last daily change of US, Asian and European indices, the dollar, crude, gold and US yields |
| Headlines | the desk's RSS feeds | Headlines that name an instrument (its company name, or its symbol when that is not an ordinary word) |
| Watch-list | all of the above | Every instrument ranked by reasons it can state; the recording plan spends Kite's subscription budget (3 connections x 3,000 instruments) down that list |

### The results comparison

For a company reporting today, the brief compares two numbers:

* **What the options price for this event.** The at-the-money straddle at the last close (nearest expiry at least
  7 days away), read as an annualised implied volatility. Then the variance above the stock's normal level (the median
  IV 30 to 10 sessions before), over the time left: `sqrt(max(iv^2 - iv_normal^2, 0) x dte / 365)`.
* **How far it moved on its past results.** The move from the close before to the close after each past results
  session.

The label is **cheap** when its past median move is at least 1.25x the price, **rich** at 0.8x or below, **fair** in
between, **no history** with fewer than 3 past events, and **already out** when IV collapsed at the last close (the
result already landed). Labels are hypotheses, not tested trading rules. A rule built on them needs its own
pre-registered test.

**Past events, and a bias the brief avoids.** NSE's calendar table in the warehouse only begins in October 2026. For
earlier years, the data has a fingerprint: on the session results land, IV on the same expiry falls while the stock
jumps. The brief finds those sessions (IV down at least 12% and a move at least 3x the stock's median) and shows them.
**It does not label from them**, because they are found *because* the stock jumped: in the first build their median
move was 4.7% against 3.3% for calendar events. Measured on the 144 calendar results meetings of October 2026, the
fingerprint was right 86% of the time and found a quarter of the events; those thresholds were chosen on the same
season, so both numbers are optimistic. The clean history is NSE's own board-meeting archive. Backfilling it is the
next step, and it has to run from GitHub's runners because NSE refuses this sandbox.

## What the data says about events and option spikes (exploratory, 3 Nov 2026)

This study was run before the brief existed. It was not pre-registered, so every number below is a lead, not evidence
for a rule. Data: NSE bhavcopy 2019 to 2026 for NIFTY and BANKNIFTY (near-money, nearest weekly, liquid by the
*previous* day's contracts), and every F&O stock's options from July to November 2026.

**Indices.** The outcome is a session where some near-money option closed at 3x or more of its open (a "spike").

* **Expiry days have the most spikes**: 22% of expiry sessions against 13% of others. But buying near-money options at
  the open on an expiry day lost 33% to 48% on average. They are lottery tickets.
* **FOMC mornings showed twice the spike rate, entirely because they were usually Thursday expiries.** On FOMC mornings
  that were not expiry days the rate was 3%, *below* the usual 12.5% (33 sessions).
* **RBI policy days**: 17.5% against 12.5% on other non-expiry sessions (57 sessions). Not significant.
* **Union Budget**: 13 sessions, too few to say anything.
* **General elections** (the 2019 and 2024 exit polls and results): the biggest spike days in the record. Twice a
  decade.
* **The opening gap** (known at 09:15): the largest fifth of gaps had a spike rate of 17.7% against about 13.5%. Weak,
  and not monotone across the fifths.
* Blind buying at the open on ordinary days was roughly break-even before costs (+2% to +10%, depending on how the rare
  10x outcomes are capped). The blind loss comes from expiry days.

**Stocks.** Results are where stock options spike.

* The stock moved about twice as far as usual: a median 3.3% from D-1 to D+1, against 1.6%.
* A near-money option closed at 3x its open on 17.7% of reaction days (D+1), against 6.5% on stocks with no results
  nearby.
* **The options already price it.** An ATM straddle bought at D-1's close and sold at D+1's close returned about +2.5%
  before costs (the control returned +0.3%), and lost after a 4% round trip. Implied moves were higher too: 6.2%
  against 5.3%.
* In that one season, options were **rich** on results on average: they priced 5.4%, the stock moved 3.3%, and the
  median straddle return was -10%.
* Open-to-close returns from the bhavcopy are not trustworthy for thin stock options. The open is the day's first trade,
  often a stale print. It made even ordinary in-the-money options look profitable (t = 5 to 7). Every result above
  uses closing prices.
* **Breadth.** Across all F&O stocks, 150 to 300 stock-sessions a month had some option close at 3x its open, spread
  over 15 to 20 sessions a month. The indices had about 3 such days a month. The counts use open prints, so they are
  inflated, but the order of magnitude is the point.

**So:** a scheduled event alone does not find spikes worth buying, because the market prices it. The brief does three
things with that:

* it tells the desk where to look today: results, expiry and the rare large macro event;
* it compares each company's price for its event with its own history: the testable idea;
* it ranks every instrument with its reasons.

Catching the spikes themselves needs in-move detection on intraday data. That is the spike detector, a separate piece
of work.

## Files

* `quantdesk/premarket/universe.py`: every F&O underlying from the bhavcopy.
* `quantdesk/premarket/history.py`: implied moves, the results calendar and fingerprint, per-event history, macro
  analogues.
* `quantdesk/premarket/brief.py`: assembles the brief, the watch-list, the recording plan, JSON and Markdown.
* `quantdesk/premarket/sources.py`: warehouse loader, Yahoo, RSS. Each fails soft and is named in `health`.
* `quantdesk/premarket/macro_dates.json`: past RBI, FOMC, Budget and election dates. FY25 and FY26 RBI dates are
  checked; the rest are compiled from public schedules and still to be checked line by line.
* `deploy/premarket-data.sh`, `.github/workflows/premarket.yml`: the morning job. It publishes to the `premarket`
  branch, one orphan commit per brief.
* The app's Today tab reads `brief.json` from that branch.

## Next

1. **Backfill NSE's past board meetings** into the warehouse, so every company has a clean results history.
2. **Pre-register the results test**: buy (or sell, defined-risk) the straddle by label, D-1 close to D+1 close, with
   costs.
3. **Let the recorders read the plan**: Kite records the watch-list's instruments, so intraday spike data exists for
   every name the desk cares about that day.
4. **The spike detector**: in-move features on that data, judged against blind entries and expiry-day lottery tickets.
