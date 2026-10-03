# Quant gap review: the desk against a Strike-class analytics platform

October 2026. The question: from a quantitative and research standpoint, what does a professional Indian
market-analysis platform (Strike, strike.money, is the reference) show that this desk doesn't, and what would most
improve the desk's analysis and the evidence behind it? This is a NIFTY/BANKNIFTY intraday options desk on a ₹20k
paper account that only buys options until it has margin, so "useful" means one of two things: it changes what the
desk does in the next 30–60 minutes on those two indices, or it tells us whether what it does works.

## What a Strike-class platform shows

From Strike's public feature pages:

- the option chain with strike-wise OI, volume and **OI change**;
- OI build-up classification (long build-up, short covering and the rest);
- FII/DII cash and derivatives positioning;
- market breadth and diffusion indicators;
- heatmaps, sector rotation (RRG) and ratio charts;
- scanners, and a bulletin board for corporate actions.

## What the desk already has

| Area | In the desk | Where |
|---|---|---|
| Chain snapshot: PCR, PCR of today's ΔOI, max pain, OI walls, top OI adds, 25Δ skew, ATM IV, straddle | yes | `chains.chain_analytics` |
| IV percentile (same days to expiry, one year) | yes | `ivhist.py` |
| Dealer gamma (naive sign) and the gamma flip, implied forward | yes (context, not a vote) | `options/gex.py` |
| Futures OI build-up, basis and carry | yes | `futures.py` |
| FII/DII cash, FII index-futures positioning (participant OI) | yes, daily | `data/warehouse.py`, brain flows |
| Heavyweights pulse (11 names, ≈60% of NIFTY) | yes, on probation | `brain.py` |
| Global drivers with validated lead-lag | yes | `brain.py`, research |
| Order flow: OFI, VPIN, approx CVD | yes | `orderflow.py` |
| News NLP with surprises, plus language-model second readers | yes | `news.py`, `nlp.py`, `llm.py` |
| Learning: hit rate per factor, news type, reader, setup | yes | `learning.py` |
| Liquid F&O stocks ranking | yes | `stocks.py` |

The snapshot coverage is already at or past a retail platform's: dealer gamma, IV percentile, VPIN and the learning
loop are not things Strike shows.

## The gaps that matter, ranked

### 1. How the chain moves through the day (implemented)

The chain was read as a snapshot each refresh and then forgotten. Option desks trade on the changes instead: where
fresh writing is going and which way the walls are moving. Now (`intraday/chainflow.py`):

- **OI wall migration** since the first read of the session: a call wall moving down means writers are pressing on
  price, a put wall moving up means they're building a floor. This is a new direction factor, `oi_shift`.
- **The 25Δ risk reversal's 30-minute trend**: puts getting dearer than calls leans bearish. A new factor,
  `skew_trend`.
- **ATM IV's 30-minute trend**, in the narrative and on the Chart. For a desk that only buys options it is the
  difference between a vega tailwind and a crush.
- **PCR's 30-minute trend**, and **fresh call and put writing** (the strikes adding the most OI today) as chart
  levels, beside the walls.

Discipline: `oi_shift` and `skew_trend` start **on probation**. They are graded live from the first session and get
a vote only after 30 graded reads at 1.15× reliability, the same rule the brain's probation drivers follow. The app
shows them as "probation" until then.

### 2. Data backing: factor IC by horizon (implemented)

The learning loop graded each factor on one thing: did its direction call the next 30 minutes right? That says
nothing about how strong the call is or at what horizon it works. Now each factor gets an **information coefficient**
at 5, 15, 30 and 60 minutes:

- the IC is the correlation of the factor's direction with the forward move, with returns clipped at ±150 bps;
- its t-stat uses overlap-adjusted samples (reads are 5 minutes apart, so at 60 minutes each read counts 1/12);
- it is accumulated incrementally in the memory, seeded by the history bootstrap, and rebuilt with `learn --rebuild`.

It shows on the Brain tab and in the session review.

Why it matters: a factor whose IC peaks at 5 minutes is noise once a round trip's costs are paid. One that peaks at
60 minutes argues for longer time stops. This is the evidence the weights should eventually move on.

### 3. The buyer's edge: realised vs implied volatility (implemented)

For an account that can only buy options, whether the index moves more than the options priced in decides
everything else. At each close, for each index, the desk now records:

- the session's realised volatility, from 5-minute returns starting at the first live chain read;
- that against the ATM IV read at the open;
- the session's move against the move that IV implied.

Over the last 20 sessions this gives realised ÷ implied, the share of sessions where realised beat implied, and
move ÷ implied move. It is on the Brain tab and in the review. Persistently below 1× means the desk is paying for
movement it doesn't get. The answer then is fewer, more selective buys (only where the IC table and the EV gate agree)
or waiting for the margin to sell premium, not more trades.

### 4. Index breadth (next)

A NIFTY move carried by three heavyweights while most constituents fall is a fragile move, and breadth is the
cleanest intraday check for it. The fields needed:

- the share of the 50 constituents advancing;
- the share above their VWAP;
- the gap between equal-weighted and cap-weighted moves.

The data path exists: the Kotak quotes endpoint already batches up to 50 instruments a call. It needs the 50
equity tokens from the scrip master and one call a minute. It should go in on probation like the heavyweights pulse,
with its IC tracked from day one. It is not built yet because it needs a live Kotak session to verify the quote
fields (open, previous close, average traded price).

### 5. Relative strength: BANKNIFTY vs NIFTY, and sectors (next)

Which index to trade is a decision the desk makes implicitly. The BANKNIFTY/NIFTY ratio's intraday trend, and later
an RRG-style read of the sector indices, would make it explicit. It costs nothing on data the desk already has.

### 6. FII index options positioning (next)

The participant OI the warehouse already downloads has FII long and short positions in index calls and puts, not only
futures. Net FII option positioning is a daily context read for the brain: a regime input, not an intraday vote.

### 7. The buyer's edge over history (next)

Section 3 starts from today. The warehouse's bhavcopy has five years of index option closes, enough to compute the
daily ATM straddle's implied move against the next day's realised move per weekday and per days-to-expiry. That
answers on day one when buying options tends to pay (for example, close to expiry or around events) instead of waiting
20 sessions.

### What not to copy

- **Stock heatmaps and scanners across 200 names.** The F&O stocks ranking showed most stock options don't fit a ₹20k
  risk budget, so scanning them changes nothing the desk can do. The ranking already lists the ones that fit.
- **Bulletin boards, corporate actions and screeners.** Useful for a discretionary investor, not for an intraday
  index-options desk.

## How to read the new numbers

- A new factor gets weight only through the probation rule and the bounded learning multipliers (0.5×–1.5×).
- Before any factor's base weight is raised by hand, the IC table should show |t| ≥ 2 at the horizon the trades are
  held over, on at least a few hundred overlap-adjusted reads (roughly 20+ sessions).
- The buyer's edge needs 20+ sessions before it means anything. One volatile week proves nothing.
