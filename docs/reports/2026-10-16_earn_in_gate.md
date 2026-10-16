# The earn-in gate, first run on the real record (16 Oct 2026)

Owner request (16 Oct): the desk was learning without acting on it. Everything it learned was either applied raw, as
news and reader trust were, which D-01 showed were not distinguishable from noise, or recorded and never applied
(factor weights, probation votes, setup records). The gate (`quantdesk/intraday/earn_in.py`) is the path between the
two: an item reaches trading only once its own record has held up out of sample. It ships in **shadow**. In shadow it
is computed and journaled every session and nothing else changes. The owner decides when to flip it to `apply`.

## What it establishes, and what it doesn't

It establishes that an item's record is **stable out of sample**: the direction the earlier sessions showed kept
holding on the next ones, beyond what flipping sessions at random produces. A consistently wrong reader earns a
downward tilt in the same way a consistently right one earns an upward one. It is not proof of a trading edge.

The research reviewer's power estimate (300 simulated paths per cell): an item with a true 55% hit rate and about 20
effective observations per session passes in 41% of paths at 20 sessions, 60% at 30 and 86% at 60 (one item; less
under Benjamini-Hochberg). A 52% edge is essentially never earned. Expect 6-12 weeks before anything earns.

## Method (the D-01 follow-up's, with the research review's corrections of 16 Oct)

1. **Data.** The memory keeps, besides each item's totals, a per-session × index block of its graded observations:
   n, hits, the sum, the share of bullish calls, and the share of up moves. A rebuild regenerates the blocks.
2. **Excess against the day's base rate.** A hit counts only beyond what a coin with the same bias would have scored
   that session: `hits − n·(π·u + (1−π)·(1−u))`. The first version measured against 0.5; a bullish reader in a
   rising week then looked skilled. The rules reader's 55% was its tone mix matching the days' direction: lift +0.036,
   p 0.048 against 0.5; lift −0.003, p 0.60 against the base rate. Setups score their real R.
3. **Walk-forward lift** over the last 60 sessions: the direction the earlier sessions' excess held, scored on the next.
4. **Placebo.** Flip each session's excess sign and re-run. A session is one block, because NIFTY and BANKNIFTY share
   its move. p is the share of worlds at least as good: all 2^D worlds up to 14 sessions, else 4,000 seeded.
5. **Multiplicity and repeated looks.** Benjamini-Hochberg at 5% over every item tested in a table (a lift ≤ 0 counts
   as p = 1). An item earns its place by passing **two sessions in a row**, and keeps it until p exceeds 2α.
6. **Effect in `apply`.**
   - An earned item applies **half** its recorded tilt (winner's curse); everything else is 1.0×.
   - A setup record can only resize conviction, between 0.75× and 1.15×, inside every risk cap.
   - It never stands a setup aside: a stood-aside setup takes no trades, so its record could never recover.

Known looseness (accepted for a gate, documented): news_event, news_source and news_reader are overlapping slices of
the same rules series, and Gemini and Ollama read the same headlines, so those tables are dependent. Each table is its
own 5% family.

## First run (corrected method)

Memory rebuilt from `journal@dc836b7` (16 Oct close) with the block-recording code; 10-11 sessions.

**0 of 336 items have earned a place. 35 had the data to be tested; none passed today.**

| Table | Tested | Nearest (p, lift, sessions) |
|---|---|---|
| factor | 28 | breadth 0.0039 (+0.054, 10); vwap 0.0078; value 0.0078; htf 0.0078; ema_5m 0.022 |
| news_reader | 3 | ollama 0.117; gemini 0.332; rules 0.60 (lift −0.003) |
| news_event | 2 | – |
| news_source | 2 | – |
| setup | 0 | trend_break: 6 trades over 4 sessions |

With 28 factors tested, BH's first-rank threshold is 0.05/28 = 0.0018. At 10 sessions the smallest p a factor can
reach is about 0.001, so breadth and vwap are the nearest to earning. They show within-session discrimination after
the drift is removed.

## What `apply` would change on Monday

It would take news and reader trust back to 1.0×. Today they are applied raw (market_recap ×1.13, ET Markets ×1.15,
rules ×1.07). Nothing would be added. This is D-01's own recommendation for news trust, which was never carried out.
