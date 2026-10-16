# The earn-in gate, first run on the real record (16 Oct 2026)

Owner request (16 Oct): the desk was learning without acting on it. Everything it learned was either applied raw, as
news and reader trust were, which D-01 showed were not distinguishable from noise, or recorded and never applied
(factor weights, probation votes, setup records). The gate (`quantdesk/intraday/earn_in.py`) is the path between the
two: an item reaches trading only after its own record beats a placebo out of sample. It ships in **shadow**. In
shadow the gate is computed and journaled every session and nothing else changes. The owner decides when to flip it
to `apply`.

## Method (from the D-01 follow-up)

1. **Data.** The memory keeps, besides each item's totals, a per-session × index block of its graded observations. A
   rebuild regenerates the blocks from the whole journal.
2. **Walk-forward lift.** For each session in time order, take the direction the record held on the earlier sessions
   only, and score it on this session's outcome. Sum the scores, per observation.
3. **Placebo.** Flip each session's outcome sign and re-run the whole walk-forward. A session is one block because
   NIFTY and BANKNIFTY share its move (+0.71). The flips are exhaustive up to 14 sessions (16,384 worlds), and a seeded
   4,000-world sample beyond that. p is the share of worlds at least as good.
4. **Earned.** An item is earned when it has at least 10 sessions, at least 30 observations, a positive lift, and a p
   that survives Benjamini-Hochberg at 5% across every eligible item in its table.
5. **Effect in `apply`.**
   - An earned item applies its recorded value; everything else is 1.0×.
   - A setup record can only resize conviction, between 0.6× and 1.3×, inside every risk cap. It never stands a setup
     aside, because a stood-aside setup takes no trades and its record could never recover (the absorbing state).
   - Re-tested every session, so an item can lose its place.

## First run

Memory rebuilt from `journal@dc836b7` (16 Oct close) with the block-recording code; 10-11 sessions per item.

**0 of 336 items earned a place. 15 had the data to be tested.**

| Table | Items | Eligible | Best p (item) | Earned |
|---|---|---|---|---|
| news_reader | 4 | 3 | 0.048 (rules, lift +0.036, 11 sessions) | 0 |
| news_event | 14 | 1 | 0.163 (market_recap, eligible) | 0 |
| news_source | 276 | 2 | 0.084 (ET Markets, eligible) | 0 |
| factor | 31 | 9 | 0.079 (global_europe) | 0 |
| setup | 11 | 0 | (trend_break: 6 trades over 4 sessions) | 0 |

The rules reader is the nearest: a nominal p of 0.048, which does not survive the multiple-comparison correction
(the first-rank threshold is 0.05 × 1/3). Each additional session gives the test more power.

## What `apply` would change on Monday

It would take news and reader trust back to 1.0×. Today they are applied raw, for example market_recap ×1.13,
ET Markets ×1.15, rules ×1.07, gemini ×0.94 after the C-07 rebuild. Nothing would be added. This is D-01's own
recommendation for news trust, which was never carried out.
