# Evolving with the market

The owner, 14 Nov 2026: *"The way we see market today, market may not behave the same way 2 months later, 3 months later, a year later. How our trading desk is
going to evolve in that process? What's the plan we should have? ... much more sophisticated, much more advanced, in a way that we are evolving with the market."*

A desk tuned to one market bleeds slowly when the market changes. This plan makes the desk notice the change, forget what no longer holds, shrink while it is unsure,
learn from history before it repeats, and re-check its own rules. Every step is paper money only and goes through the Renaissance gate (`docs/RENAISSANCE.md`).

## Where the desk stood (14 Nov 2026)

| Part | Adapts? | The gap |
|---|---|---|
| The strategy record (`auto2.Lab`) | No | A running total of every trade ever, with no forgetting. A record earned in one market is carried into the next. |
| Market-read weights (`marketread.py`) | Partly | Online logistic weights pulled towards a prior: one set for every kind of market. |
| HMM, CUSUM, Kalman (`regimes.py`, `kalman.py`) | Within a day | Refitted every session; nothing remembered across months. |
| The tail model (`tails.py`) | Daily refit | Does not say when today's tails stop looking like history. |
| Thresholds (cheap at 0.8x, three readings, the 1.5 sd stop, ...) | No | Set once by hand, never re-tested. |
| The news model | Scored (Brier) | Nothing acts on a falling score. |
| The inventor | Mutates the best | Not told when the market has changed, so it does not explore more then. |

## The design: six layers

1. **Sense.** A daily **market fingerprint**: what kind of market it is (phase 1, built). Later, a Bayesian online change-point detector on the fingerprint finds
   structural breaks that last weeks or months, not intraday wiggles (phase 4).
2. **Remember with context.** Every trade is tagged with the market it was taken in (phase 1, built). The record then forgets: it is discounted with a half-life of
   about 60 sessions, shortened for a while after a break (phase 2). It is estimated **by regime**, so strategy × regime is a hierarchical model, and Thompson sampling
   asks "how good is this in markets like today's?" (phase 3).
3. **Monitor and demote.** A Page-Hinkley watch on each live strategy's R and on each model's calibration. A strategy that falls well below its record goes to
   **probation** (shadow only), and a model that degrades loses voting weight. These only tighten, so they need no approval; promotion and anything that loosens is the
   owner's (phase 2).
4. **An unfamiliar-market guard.** When today's fingerprint is outside anything in the library (a statistical distance past its 99th percentile), live sizes halve and
   the shadow book explores more, with a red flag in the app (phase 4).
5. **A regime library.** The fingerprint of every past session the desk has closes for (2007 onwards for the indices): the 2008 crash, the 2013 taper, the 2016
   demonetisation, the 2020 crash, the 2022 rate hikes, the 2024-25 F&O rule changes. Strategies are replayed through them, so a new regime borrows its priors from the
   most similar past one (phase 5).
6. **Re-validate the rules.** Every threshold is re-tested walk-forward each month, choosing the plateau where results are stable, never the single best value. Many
   variants tried are corrected for (the deflated Sharpe ratio). A tightening applies itself; a loosening goes to the owner with the evidence. A market-rule change
   (lot sizes, weekly expiries, STT, margins; the news model tags `fno_rules` stories) freezes the affected strategies to shadow until they prove themselves again
   (phase 6).

**The advantage already in hand:** the shadow book trades every matching strategy, not only the ones chosen, so any new way of choosing (by regime, with forgetting) can
be tested exactly on the record already kept, before it touches paper money.

## The phases

| Phase | What | Exit test |
|---|---|---|
| **1. Fingerprint and tags** (built 14 Nov 2026) | The brief's daily fingerprint; every closed shadow trade tagged with its regime; live theses say the market; the app's Market regime panel | 30 sessions of fingerprints; every closed shadow trade tagged (none `unknown` on a day the brief ran) |
| 2. Forgetting and probation | A discounted record beside the cumulative one; Page-Hinkley demotion of live strategies; model weights cut on falling calibration | Pre-registered: on the shadow record, choosing with the discounted record does at least as well as with the cumulative |
| 3. Choosing by regime | Strategy × regime hierarchical model; Thompson sampling on today's regime | Pre-registered off-policy test on 60+ sessions of shadow trades |
| 4. Breaks and the unfamiliar market | Change points on the fingerprint; automatic size halving | Finds the library's known breaks within 10 sessions |
| 5. The regime library | Fingerprints back to 2007; strategies replayed through them; priors by similarity | Similarity priors beat flat priors on regimes held out |
| 6. Re-validation and rule changes | Monthly walk-forward plateau reports; loosening only with the owner; the rule-change freeze | The first monthly report reviewed |
| 7. Capital between books | The convexity, directional and other books weighted by their regime record, always under the owner's caps | Pre-registered; the owner signs off |

## Phase 1: the fingerprint (`quantdesk/premarket/fingerprint.py`)

Every morning the brief (`premarket.yml`) computes it from the same years of daily closes the tail models read (37 instruments: indices, stocks, MCX, currency):

- **Volatility:** NIFTY's 20-session realized volatility, and its percentile over three years. Low under the 33rd, high over the 80th.
- **Its trend:** against the same measure 20 sessions earlier.
- **Direction:** NIFTY's 60-session move in its own daily standard deviations. Up or down past 1.5, else a range.
- **Chop:** the 5-session variance ratio over a year (under 1, moves reverse).
- **Herding and dispersion:** the stocks' average pairwise correlation over 60 sessions, and the spread of their 20-session moves.
- **Stress:** the distance from the one-year high, and the days of the last 60 past 2.5 one-year standard deviations.
- **Cross-asset:** crude's and the rupee's volatility percentiles.
- **What only the brief knows:** the overnight US VIX, the dollar and US 10-year yields, and the events of the next five days.

The **key** is one of nine regimes: volatility (low / normal / high) × direction (up / down / range). There are few on purpose, so each collects enough trades to say
something. The brief's summary says it in a line ("Market: high volatility (88th percentile), trending down, stocks moving together; this regime (high/down) since
6 Nov."), with "since" taken from the last 60 sessions' keys. It is a description, not a forecast. The function computes the fingerprint at any past date from the
closes up to it, never ahead; phase 5 builds the library with it.

**The tags (AUTO v2, `Lab.tag`):** every closed shadow trade adds its R to its structure's record **in today's regime** (`reg`: regime → structure → n, sum R,
sum R², wins). The latest 400 trades are kept whole (date, strategy, underlying, R, regime) for the later phases' replays. A day without today's brief is tagged
`unknown`. A live trade's thesis ends with the market it was taken in.

**Where it is kept:** the fingerprint, made from public prices, is in the public brief. The tags are trading results, so they stay **private**: they live in the
strategy record on the relay (compressed; `docs/PAPER_TRADING.md`), as the session reviews do. Results are never put in this public repository. That costs nothing.
Raw tick history beyond GitHub's 90-day artifacts would need private storage (Cloudflare R2: 10 GB free, then about $0.015 a GB a month) for phase 5's intraday
replays. The daily library needs only the closes the desk already fetches.

**In the app:** the Today tab's brief has the Market line. The Paper tab's **Market regime** panel shows today's regime and since when, and each regime seen with its
shadow trades and its best structures by mean R (5 trades or more).

## Honest limits

- No method sees a regime change the moment it happens. The unfamiliar-market guard and probation cover that gap.
- More adaptivity means more ways to overfit. Everything goes through pre-registration, out-of-sample tests and the deflated Sharpe ratio.
- Some breaks have no precedent. Then the job is to shrink and learn fast, not to be right at once.
- Evidence by regime is thin at first (few trades per regime). Pooling and the library help, but the first real verdicts need about three months of tags.
