# Costs and holiday calendars for the 24/7 paper desk: what was read, where, and what is still unverified

Read on **6 Nov 2026** from Zerodha's own published pages, which are a primary source for Zerodha's fee schedule and a secondary
source (a broker republishing exchange circulars) for the holiday lists. The exchanges' own pages (MCX, the NSE circular archive)
refuse this sandbox (HTTP 403 / no answer), so the circulars themselves were not read.

* Charges: https://zerodha.com/charges (the page carries no "last updated" date; it was read on the day above)
* Holidays: https://zerodha.com/marketintel/holiday-calendar/

Nothing in this file changes a cost or a limit. It is the input to the M4 pull request that adds the MCX and currency cost
segments, which needs the independent risk review the plan requires for statutory costs.

## Zerodha's published charges (exact figures from the page)

Brokerage, GST (18% of brokerage + SEBI charges + transaction charges) and SEBI charges (Rs 10 per crore; Rs 1 per crore for
agricultural commodity futures) apply to every row below. Brokerage: futures 0.03% or Rs 20 per executed order, whichever is lower;
**options Rs 20 per executed order, flat**. Currency: no STT.

| Segment | STT / CTT | Transaction charge | Stamp (buy side) |
|---|---|---|---|
| NSE equity futures | 0.05% sell side | NSE 0.00183% | 0.002% |
| NSE equity options | 0.15% of premium, sell side; 0.15% of intrinsic value if bought and exercised | NSE 0.03553% of premium | 0.003% |
| NSE currency futures | none | NSE 0.00035% | 0.0001% |
| NSE currency options | none | NSE 0.0311% of premium | 0.0001% |
| MCX commodity futures | CTT 0.01% sell side (non-agri) | MCX 0.0021% | 0.002% |
| MCX commodity options | CTT 0.05% sell side (of premium) | MCX 0.0418% of premium | 0.003% |

Also on the page: the Investor Protection Fund charge (NSE currency options Rs 2 per lakh of premium, currency futures Rs 0.05 per
lakh) and an extra Rs 20 per order on an account with a debit balance. Neither is modelled yet.

### Where the repo's current NSE rates differ from that page

`config/quantdesk.yaml` `costs.segments` was set earlier; the page now says:

| Row | Config today | Zerodha's page | Difference |
|---|---|---|---|
| options `exchange` | 0.0003503 | 0.0003553 (0.03553%) | page is 1.4% higher |
| futures `exchange` | 0.0000173 | 0.0000183 (0.00183%) | page is 5.8% higher |

The other NSE rows (STT, stamp) match. These are fractions of a rupee per trade, so no result moves, but statutory rates are never
changed without review: this is a note, not a fix.

## Holiday calendars

* **NSE / BSE 2026** (16 weekday holidays): identical to `calendar.holidays` in the config. That list's own comment says it was
  cross-checked against NSE circular CMTR71775, so the page and the circular agree.
* **MCX 2026**, weekday full-day closures the page lists: 26 Jan (Republic Day), 3 Apr (Good Friday), 2 Oct (Gandhi Jayanti),
  25 Dec (Christmas). It also lists 15 Aug (Saturday) and 8 Nov (Sunday, the Diwali Muhurat session). **Not on the page, and not
  modelled:** MCX's partial-day closures, where the morning session is shut and the evening session runs, on many NSE holidays. A
  desk must not assume it knows MCX's hours on those days; quotes are required to fill, which is the only protection today.
* **NSE currency 2026**: no list is published on the page above. The page lists four *settlement* holidays (19 Feb, 19 Mar,
  1 Apr, 26 Aug). The currency segment's circular (NSE/CD/71962) declares 19 weekday holidays, and 20 after the 15 Jan amendment
  (NSE/CD/72233, reported but not read): 15 equity holidays + 4 = 19, and 16 + 4 = 20. So the segment is taken to be closed on the
  equity holidays plus those four dates. **That is an inference from counts, not a reading of the circular.**

`config/quantdesk.yaml` `markets:` carries the MCX and currency lists. They are used for **recording only**: `holiday_years` is
not set for either segment, so both stay unverified for trading (`python -m quantdesk markets today`).

## What would make them verified

1. Read MCX/TRD/636/2025 (MCX) and NSE/CD/71962 plus NSE/CD/72233 (NSE) from the exchanges, from a machine they do not block (a
   GitHub runner may be refused too: the NSE backfill already has to try that), and compare with the lists above.
2. Model MCX's partial-day sessions.
3. Only then set `markets.<segment>.holiday_years`, enter the segment's costs, add its underlyings to `paper.underlyings` and add it
   to `paper.cost_verified_segments`, each in a reviewed pull request.
