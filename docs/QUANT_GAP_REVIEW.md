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

### 4. Index breadth (implemented)

A NIFTY move carried by three heavyweights while most constituents fall is a fragile move, and breadth is the
cleanest intraday check for it. Now (`intraday/breadth.py`), once a minute for each index's own stocks (NIFTY 50 and
Nifty Bank, about 57 names: 3 quotes calls):

- the share of members up on the day (Kotak's `per_change`) and the share above their own session VWAP (Kotak's
  `avg_cost`, the day's average traded price; both fields seen on a runner on 2 Oct 2026);
- the equal-weighted average move against the index's own move: negative means the index is being carried by its
  largest names;
- the 30-minute change of those shares (thrusts).

Members come from NSE's published index lists, else a built-in late-2025 list. Each stock's cash-market token comes
from the F&O scrip master's `pAssetCode`. Two new factors, both **on probation**: `breadth` (participation) and
`breadth_div` (a narrow move leans against the index). Their IC is tracked from the first session.

### 5. Relative strength: BANKNIFTY vs NIFTY (implemented)

Which index to trade used to be decided implicitly. Now (`intraday/relstrength.py`) the read carries:

- the BANKNIFTY/NIFTY ratio's move on the day and over the last 30 minutes;
- that 30-minute move in σ of its own history;
- BANKNIFTY's beta and correlation to NIFTY today.

Whether the leader keeps leading is measured before it is used. The learning loop grades every 5-minute point of every
whole session in the bars: the last 30 minutes of the ratio against its next 30, as an overlap-adjusted IC. It is
seeded from the bars the desk already loads. Only when that IC is positive with t ≥ 2 does the desk act on it:

- a plan long the laggard or short the leader has its conviction cut (×0.8);
- one going with relative strength gets a small lift (×1.1).

Sector rotation (RRG-style) is still to do.

### 6. FII index options positioning (implemented)

The brain's flows now carry FII net index-options positioning:

- net calls − net puts in contracts (> 0 leans long the index);
- its change on the day and over 5 sessions;
- its percentile over the past year;
- the same for clients, who are usually on the other side.

It sits on the Brain tab and in the narrative, next to the warehouse research's verdict on whether the change predicts
the next session (hypothesis P4). It is a regime input, not an intraday vote, and stays that way unless P4 passes.

### 7. The buyer's edge over history (implemented)

Section 3 starts from today. The warehouse research now answers on day one, from five years of bhavcopy
(`warehouse_research.buyer_edge`). It takes the nearest expiry's ATM straddle at real prices, with a half-spread and a
tick each way on every leg plus fees, in two versions:

- **bought at the opening prints and sold at the close**: what an intraday buyer lives through;
- **bought at the close and sold at the next close.**

Both are grouped by days to expiry and by weekday, with the move delivered against the move the straddle's own IV
priced. The statistics: Newey-West t, discovery on the older 2/3, rolling validation on the newest 1/3, and
Benjamini-Hochberg FDR within each family. The live desk loads the table (`buyer_edge.json` from the research branch)
and states, in the read and on the Chart's Quant panel, what history says about buying at today's point in the expiry
cycle.

**What it found** (first run, 3 Oct 2026; real NSE prices, Jan 2019 → Oct 2026, about 1,900 sessions per index):

| ATM straddle, bought at the open, sold at the close | NIFTY | BANKNIFTY |
|---|---:|---:|
| All sessions: mean on the premium | −6.3% | −5.7% |
| Sessions profitable | 31% | 29% |
| Expiry day (0 days to expiry) | −14.2% (median −31.7%) | −19.6% (median −34.5%) |
| 1 day to expiry | −7.5% | −4.1% |
| 2 days to expiry | −4.8% | −5.7% |
| 3 days | −2.2% | +0.4% |
| 4–5 days | −1.3% | −1.7% |

- **No bucket where buyers win**, on either index, intraday or overnight. Verdicts: "buyers lose" (FDR on the discovery
  data, and the newest third keeping the sign) on expiry day, 1–2 days out on NIFTY, and on Tuesday to Thursday.
- On expiry day the index out-moved what the straddle priced on **5%** of sessions.
- The least bad: 3+ days to expiry, and Mondays and Fridays. Both are "no edge", not an edge.

What it means for this desk: a straddle is the zero-skill baseline for a buyer. A directional buy that does no better
than a coin flip loses about what the straddle loses. So a NIFTY trade bought with 1 day to expiry has to earn back
roughly 7–8% of its premium from the direction call alone before it makes anything. The desk already never buys on
expiry day (`expiry_min_days: 1`), but 1-day weeklies are its usual pick on Mondays. The data argue for buying 3+ days
out (`expiry_min_days: 3`), at the cost of a larger premium per lot. That is a decision for the account's owner,
not a default this review changes.

### What not to copy

- **Stock heatmaps and scanners across 200 names.** The F&O stocks ranking showed most stock options don't fit a ₹20k
  risk budget, so scanning them changes nothing the desk can do. The ranking already lists the ones that fit.
- **Bulletin boards, corporate actions and screeners.** Useful for a discretionary investor, not for an intraday
  index-options desk.

## How to read the new numbers

- A new factor gets weight only through the probation rule and the bounded learning multipliers (0.5×–1.5×).
- Breadth, the narrow-move read and relative strength follow the same rule: no vote until their live record earns it.
- Before any factor's base weight is raised by hand, the IC table should show |t| ≥ 2 at the horizon the trades are
  held over, on at least a few hundred overlap-adjusted reads (roughly 20+ sessions).
- The buyer's edge needs 20+ sessions before it means anything. One volatile week proves nothing.
