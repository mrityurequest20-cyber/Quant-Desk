# The pre-market brief

Before the open, the desk reads what today holds for **every F&O instrument** and writes it down with its reasons.
`premarket.yml` builds it every 15 minutes from 06:00 to 09:15 IST on weekdays; the app's **Today** tab shows it.

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
| Tail risk | `nse_index_close`; Yahoo (stocks, MCX proxies in rupees, currencies) | Each paper underlying's conditional extreme-value model (1, 3, 5 and 10 sessions) with its out-of-sample backtest; built once a morning (`tails.json`), read by AUTO v2's tail check (docs/PAPER_TRADING.md) |
| News analogues | the same daily series as the tail models | For every paper underlying and every event kind (RBI, FOMC, budget, election, geopolitics, oil shock): its own past episodes, each weighted by how much the market then resembled today (trend, volatility regime, drawdown): P(up), the effective number of episodes, the closest dates (`news_analogs`, read by the news model) |
| Market fingerprint | the same daily series as the tail models; the overnight list; the calendar | What kind of market it is: NIFTY's volatility and its three-year percentile, direction, chop, the stocks' herding and dispersion, stress, crude's and the rupee's volatility, US VIX, the dollar, US yields and the next five days' events. Its key is one of nine regimes (volatility low / normal / high x up / down / range), with the day it began; the summary says it in a line (`fingerprint`, read by AUTO v2 to tag its trades; docs/EVOLUTION.md) |
| Coming up | config `calendar.events`; release rules; the brief's expiries and results | The scheduled events of the next 7 days in IST (`calendar`), each with its impact, its subjects and its source. Recurring releases follow their rule: the US jobs report on the first Friday at 08:30 New York, the EIA crude report on Wednesdays at 10:30 New York (US daylight saving applied), India's CPI on the 12th at 16:00. A config date of the same kind and day wins. Read by AUTO v2's event regime (`quantdesk/paper/eventcal.py`) |
| Watch-list | all of the above | Every instrument ranked by reasons it can state; the recording plan spends Kite's subscription budget (3 connections x 3,000 instruments) down that list |

### The results comparison

For a company reporting today, the brief compares two numbers:

* **What the options price for the results window.** The at-the-money straddle at the last close (nearest expiry at
  least 7 days away, both legs traded that session), read as an annualised implied volatility. The **event-implied
  move** is the variance above the stock's normal level, over the time left: `sqrt(max(iv^2 - iv_normal^2, 0) x dte
  / 365)`. The normal level is the median IV 30 to 10 sessions back, only on expiries that end before the event. An
  expiry that spans the event carries its premium. Two ordinary sessions at the normal IV are added (the window is D-1's
  close to D+1's), and the result is read back as an expected absolute move (x 0.7979). That is the straddle's own
  convention, so the comparison is like with like.
* **How far it moved on its past results:** the mean absolute move from the close before to the close after each past
  results session on NSE's calendar.

**Few events make most gaps chance.** With 3 to 8 past events, a perfectly fairly priced company shows a ratio far from
1 most of the time. At fixed 1.25x and 0.8x thresholds, 20% to 40% of fairly priced companies would be called cheap or
rich (simulated, fat-tailed moves). So the label is set by a **chance band**: the range of ratios a fairly priced
company shows 90% of the time with that many events (Student-t(4) moves, a fixed seed). The labels are:

* **cheap** when above the band and **rich** when below it;
* **within chance** inside the band;
* **no history** with fewer than 3 calendar events;
* **no implied move** when there is no clean pre-event window or traded straddle;
* **already out** when IV collapsed *and* the stock jumped at the last close.

Each row shows its ratio and band. Labels are hypotheses, not tested trading rules; a rule built on them needs its own
pre-registered test.

Known biases, not corrected:

* a change in market-wide volatility between the normal window and D-1 enters the event-implied move (no index or peer
  adjustment);
* in the last week of a monthly cycle, the dte >= 7 rule reads the thinner next-month expiry, which dilutes the event.

**Past events, and a bias the brief avoids.** NSE's calendar table in the warehouse only begins in October 2026. Older
results leave a fingerprint in the data: IV on the same expiry falls while the stock jumps. The brief finds those
sessions (IV down at least 12%, a move at least 3x the stock's median) and shows them, but **never labels from them**.
They are found *because* the stock jumped: in the first build their median move was 4.7%, against 3.3% for calendar
events.

How reliable the fingerprint is depends on the season:

* **In results season** (144 calendar meetings of October 2026, when most F&O companies report) it was right 86% of the
  time and found a quarter of the events. Those thresholds were chosen on that same season.
* **Outside results season** it still fires about 9 times a month (March, June, September, December), mostly on moves
  that are not results. Over the whole history its precision is much lower: roughly 0.55 to 0.65, by the research
  review's estimate.

The clean history is NSE's own board-meeting archive. Backfilling it is the next step, and it has to run from GitHub's
runners because NSE refuses this sandbox. A results meeting followed by another for the same company within 30 days
was rescheduled; NSE keeps both rows, so only the later one counts.

## What the data says about events and option spikes (exploratory, 3 Nov 2026)

This study was run before the brief existed and was not pre-registered, so every number below is a lead, not evidence
for a rule. The first draft picked options with same-day information (look-ahead). The independent research review
caught it, and the numbers here are from the corrected run. The run picks near-money options (within 2% of the
futures **open**) on the nearest expiry, keeping the more liquid half by the **previous** session's contracts. The data
is NSE bhavcopy 2019 to 2026 for NIFTY and BANKNIFTY. Counts are symbol-sessions: NIFTY and BANKNIFTY on one day are
two.

**Indices.** The outcome is a symbol-session where some selected option closed at 3x or more of its open (a "spike"):

* **Expiry days have the most spikes**: 20% of expiry symbol-sessions against 9% of others. But buying the selected
  options at the open on an expiry day lost 31% to 49% on average before costs, depending on how big winners are
  capped. They are lottery tickets.
* **On other days blind buying lost too**: -1.7% to -4.6% on average before costs.
* **FOMC mornings** (the Indian session after a decision) were usually Thursday expiries. On those, they spiked more
  often than other expiries on the same weekday:
  * NIFTY: 36% vs 22% (47 vs 268 symbol-sessions, z 2.0);
  * BANKNIFTY: 40% vs 18% (35 vs 201, z 2.9).

  FOMC mornings that were not expiry days had no 3x close in 44 symbol-sessions (28 days). That is too few to say more.
* **RBI policy days** (not expiry): 9.6% against 9.0% (73 symbol-sessions, 39 days). No difference.
* **Union Budget**: 20 symbol-sessions on 10 days. Too few.
* **General elections** (the 2019 and 2024 exit polls and results): 2 of 6 non-expiry symbol-sessions closed at 3x.
  4 June 2024 ranks 68th and 80th of 3,858 symbol-sessions by best close-to-open multiple. Twice a decade.
* **The opening gap** (known at 09:15): the largest fifth of gaps showed a higher spike rate in the first,
  same-day-selection run (17.7% against about 13.5%), but not monotonically across fifths. It has not been re-run with
  point-in-time selection.

The spike measure itself divides the close by the **open**, the day's first trade. Index option opens can be artifacts
too: one NIFTY session shows a best close/open of 2,257x. Treat spike rates as relative, between groups, not as
absolute odds.

**Stocks.** F&O results meetings of October 2026 (n = 119 to 151, depending on the measure):

* The stock moved about twice as far as usual: a median 3.3% from D-1 to D+1, against 1.6%.
* A near-money option closed at 3x its open on 17.7% of reaction days (D+1), against 6.5% for stocks with no results
  nearby. This uses open prints, which for thin stock options are often stale. Even ordinary in-the-money options
  looked profitable open-to-close (t 5 to 7). Only the gap between the groups means anything here.
* **The options price it.** Implied moves were higher before results (6.2% against 5.3%). An ATM straddle bought at
  D-1's close and sold at D+1's close (closing prices) had:
  * a median return of -10.8%;
  * a mean of +2.5% before costs, against +1.3% for the control;
  * a difference that is not significant (t 0.3).

  Both lose after a 4% round trip.
* **Breadth.** Across all F&O stocks, 150 to 300 stock-sessions a month had some option close at 3x its open, spread
  over 15 to 20 sessions a month. The indices had about 3 such days a month. The counts use open prints, so they are
  inflated, but the order of magnitude is the point.

**So:** a scheduled event alone does not find option spikes worth buying, because the market prices it. The brief does
three things with that:

* it shows where to look today: results, expiry and the rare large macro event;
* it compares each company's price for its event with its own history, inside a chance band;
* it ranks every instrument with its reasons.

Catching the spikes themselves needs in-move detection on intraday data. That is the spike detector, a separate piece
of work.

## Files

* `quantdesk/premarket/universe.py`: every F&O underlying from the bhavcopy.
* `quantdesk/premarket/history.py`: implied moves, the results calendar and fingerprint, per-event history, macro
  analogues.
* `quantdesk/premarket/brief.py`: assembles the brief, the watch-list, the recording plan, JSON and Markdown.
* `quantdesk/premarket/sources.py`: warehouse loader, Yahoo, RSS. Each fails soft and is named in `health`.
* `quantdesk/premarket/macro_dates.json`: past RBI, FOMC, Budget and election dates. FY25 to FY27 RBI dates are
  checked; the rest are compiled from public schedules and still to be checked line by line.
* `deploy/premarket-data.sh`, `.github/workflows/premarket.yml`: the morning job. It publishes to the `premarket`
  branch, one orphan commit per brief.
* The app's Today tab reads `brief.json` from that branch.

## Next

1. **Backfill NSE's past board meetings** into the warehouse, so every company has a clean results history.
2. **Pre-register the results test**: buy (or sell, defined-risk) the straddle by label, D-1 close to D+1 close, with
   costs, on calendar events the label did not see.
3. **Let the recorders read the plan**: Kite records the watch-list's instruments, so intraday spike data exists for
   every name the desk cares about that day.
4. **The spike detector**: in-move features on that data, judged against blind entries and expiry-day lottery tickets.
