# TrueData daily research · truedata-1-f94705809b16

Data status **external_verified** (every bar checked against Yahoo). TrueData index candles are not option-chain, bid/ask, IV, trade-by-trade footprint, aggressor volume or order-book data, and never qualify an option strategy, a DTE change, a paper gate, a promotion or a profitability claim.

Three kinds of result are kept apart below:
- **Observed:** what the year looked like.
- **Historical evidence:** the pre-registered rules re-measured, and a causal replay.
- **Evidence of a profitable strategy:** none. Nothing here qualifies one.

## 1. Observed: the year (3 Oct 2025 → 1 Oct 2026)

| | NIFTY | BANKNIFTY | NIFTY 2010–23 | BANKNIFTY 2010–23 |
|---|---|---|---|---|
| Sessions | 247 | 247 | 3036 | 3032 |
| Total return | -9.9% | -2.0% |  |  |
| Annualised volatility | 13.5% | 17.0% | 18.5% | 24.5% |
| Max drawdown (close) | -15.2% (2026-03-30) | -18.3% (2026-03-30) |  |  |
| Best / worst day | 3.7% 2026-04-08 / -3.3% 2026-03-19 | 5.5% 2026-04-08 / -3.9% 2026-03-30 |  |  |
| Up days | 49.2% | 51.2% | 52.7% | 52.3% |
| Mean high–low range | 0.93% | 1.15% | 1.22% | 1.76% |
| Mean |opening gap| | 0.40% | 0.44% | 0.44% | 0.54% |
| Trend days (body ≥ 60% of range) | 37.2% | 34.8% | 40.5% | 38.9% |
| Range days (body ≤ 25% of range) | 23.5% | 25.9% | 21.9% | 23.1% |
| Lag-1 autocorrelation (±95% band) | -0.039 (±0.125) | -0.090 (±0.125) | -0.043 | +0.037 |
| Variance ratio (5) · z | 0.91 · -0.50 | 0.91 · -0.44 |  |  |
| Hurst (log price) | 0.51 | 0.55 |  |  |
| ADX(14) mean · share > 25 | 21.8 · 31.2% | 20.5 · 21.3% |  |  |

## 2. Historical evidence: the pre-registered daily rules (research/edges.py)

These rules were written before this data existed. research/edges.py also ran on Yahoo's full history, which contains these same prices, so this is a re-measurement of the latest year, not a fresh out-of-sample test. The cost hurdle is one lot of a 0.35Δ option, in index points. BH = Benjamini-Hochberg across all 10 tests.

| rule | index | trades | mean (bps) | mean (pts) | t (HAC) | p | hurdle (pts) | BH q<0.10 |
|---|---|---|---|---|---|---|---|---|
| D1 long open→close every day | NIFTY | 247 | -4.2 | -9.3 | -1.28 | 0.203 | 4.2 | no |
| D2 after a gap > 0.3%, the gap's direction open→close | NIFTY | 97 | +1.1 | +2.4 | +0.13 | 0.896 | 4.2 | no |
| D3 after a close-to-close fall > 1.5%, long open→close | NIFTY | 15 | -5.6 | -12.5 | -0.23 | 0.819 | 4.2 | no |
| D4 Tuesday (weekly expiry), long open→close | NIFTY | 49 | -22.5 | -50.5 | -2.44 | 0.018 | 4.2 | no |
| D5 turn of the month (last day + first 3), long open→close | NIFTY | 49 | -7.5 | -16.9 | -0.87 | 0.387 | 4.2 | no |
| D1 long open→close every day | BANKNIFTY | 247 | +3.9 | +21.0 | +0.92 | 0.356 | 9.5 | no |
| D2 after a gap > 0.3%, the gap's direction open→close | BANKNIFTY | 111 | +5.9 | +32.2 | +0.57 | 0.567 | 9.5 | no |
| D3 after a close-to-close fall > 1.5%, long open→close | BANKNIFTY | 17 | +5.2 | +28.1 | +0.29 | 0.773 | 9.5 | no |
| D4 Tuesday (weekly expiry), long open→close | BANKNIFTY | 49 | -11.4 | -62.1 | -1.10 | 0.275 | 9.5 | no |
| D5 turn of the month (last day + first 3), long open→close | BANKNIFTY | 49 | +4.7 | +25.4 | +0.45 | 0.656 | 9.5 | no |

## 3. Historical evidence: causal replay through a prediction ledger

Every call is written at 09:15 IST from closes up to the day before and that day's open. Its outcome (open → close) is attached only after the 15:30 close. A test proves that rewriting future prices never changes an earlier call. Net = signed index points minus the option cost hurdle. Balanced accuracy is 0.5 by definition for a rule that only ever says 'up'. No rule emits a probability, so calibration does not apply.

| rule | index | calls | accuracy (95% CI) | balanced acc. | mean pts | net pts / call | max DD (pts) | t | sample |
|---|---|---|---|---|---|---|---|---|---|
| B_coin | NIFTY | 246 | 50.8% (45%–57%) | 0.508 | -0.7 | -4.9 | -3,273 | +0.03 | ok |
| B_persist | NIFTY | 246 | 49.2% (43%–55%) | 0.491 | -8.3 | -12.6 | -3,990 | -0.89 | ok |
| B_reverse | NIFTY | 246 | 50.8% (45%–57%) | 0.509 | +8.3 | +4.1 | -1,466 | +0.89 | ok |
| D1 | NIFTY | 246 | 48.0% (42%–54%) | 0.500 | -11.3 | -15.5 | -4,566 | -1.36 | ok |
| D2 | NIFTY | 97 | 52.6% (43%–62%) | 0.528 | +1.7 | -2.5 | -1,832 | +0.13 | ok |
| D3 | NIFTY | 15 | 53.3% (30%–75%) | 0.500 | -11.5 | -15.7 | -1,030 | -0.23 | **too small** |
| D4 | NIFTY | 49 | 26.5% (16%–40%) | 0.500 | -57.0 | -61.3 | -3,020 | -2.44 | ok |
| D5 | NIFTY | 48 | 43.8% (31%–58%) | 0.500 | -23.1 | -27.3 | -1,487 | -1.03 | ok |
| B_coin | BANKNIFTY | 246 | 53.3% (47%–59%) | 0.533 | +14.2 | +4.7 | -7,797 | +0.55 | ok |
| B_persist | BANKNIFTY | 246 | 46.7% (41%–53%) | 0.467 | -31.0 | -40.6 | -11,735 | -0.95 | ok |
| B_reverse | BANKNIFTY | 246 | 53.3% (47%–59%) | 0.533 | +31.0 | +21.5 | -7,157 | +0.95 | ok |
| D1 | BANKNIFTY | 246 | 49.6% (43%–56%) | 0.500 | +18.3 | +8.8 | -6,001 | +0.86 | ok |
| D2 | BANKNIFTY | 111 | 54.1% (45%–63%) | 0.539 | +27.9 | +18.4 | -6,346 | +0.57 | ok |
| D3 | BANKNIFTY | 17 | 58.8% (36%–78%) | 0.500 | +35.4 | +25.9 | -1,587 | +0.29 | **too small** |
| D4 | BANKNIFTY | 49 | 32.7% (21%–47%) | 0.500 | -69.7 | -79.3 | -4,530 | -1.10 | ok |
| D5 | BANKNIFTY | 48 | 50.0% (36%–64%) | 0.500 | +12.4 | +2.9 | -3,365 | +0.31 | ok |

By volatility regime (rv20 terciles of the year, computed only from prior closes). Each cell is n / accuracy / mean pts. Cells under 30 calls are flagged and shouldn't be read as results.

| rule | index | low vol | mid vol | high vol |
|---|---|---|---|---|
| B_coin | NIFTY | 81 / 51% / +11 | 78 / 50% / -16 | 73 / 53% / +9 |
| B_persist | NIFTY | 81 / 52% / +1 | 78 / 49% / -22 | 73 / 44% / -13 |
| B_reverse | NIFTY | 81 / 48% / -1 | 78 / 51% / +22 | 73 / 56% / +13 |
| D1 | NIFTY | 81 / 41% / -23 | 78 / 47% / -22 | 73 / 53% / +5 |
| D2 | NIFTY | 20 / 50% / -37 ⚠ | 32 / 47% / +9 | 42 / 60% / +19 |
| D3 | NIFTY | — | 4 / 75% / +132 ⚠ | 11 / 45% / -64 ⚠ |
| D4 | NIFTY | 17 / 6% / -103 ⚠ | 16 / 25% / -72 ⚠ | 13 / 54% / +19 ⚠ |
| D5 | NIFTY | 16 / 25% / -30 ⚠ | 16 / 44% / -67 ⚠ | 14 / 57% / +18 ⚠ |
| B_coin | BANKNIFTY | 81 / 59% / +24 | 79 / 56% / -7 | 72 / 46% / +28 |
| B_persist | BANKNIFTY | 81 / 46% / -45 | 79 / 42% / -118 | 72 / 50% / +47 |
| B_reverse | BANKNIFTY | 81 / 54% / +45 | 79 / 58% / +118 | 72 / 50% / -47 |
| D1 | BANKNIFTY | 81 / 52% / +28 | 79 / 51% / +19 | 72 / 43% / -9 |
| D2 | BANKNIFTY | 24 / 38% / -149 ⚠ | 36 / 50% / -14 | 47 / 66% / +153 |
| D3 | BANKNIFTY | — | 5 / 60% / +101 ⚠ | 12 / 58% / +8 ⚠ |
| D4 | BANKNIFTY | 18 / 39% / -38 ⚠ | 13 / 15% / -187 ⚠ | 15 / 40% / -17 ⚠ |
| D5 | BANKNIFTY | 16 / 44% / +41 ⚠ | 16 / 56% / -73 ⚠ | 14 / 43% / +52 ⚠ |

## 4. The existing daily backtester

- Status: scenario analysis only (option prices modelled from India VIX; index prices from TrueData).
- Strategies: vrp_condor, trend_spread, long_vol. Trades: 0.
- Why: the daily engine trades only after backtest.warmup_bars sessions; the TrueData year is shorter, so no strategy can act on it alone (the warm-up is not lowered: that would change the strategies) (warm-up 260 sessions, data 247).
- The equity strategies (trend_rider, breakout, mean_reversion, momentum, pairs) have no data here: the export holds only the two indices.

## Limits

- One year of **daily** bars, two indices. No intraday files were uploaded yet (1-minute, 5-minute, tick), so nothing here says anything about intraday behaviour.
- The export's four trailing columns are zero in every row, so there is no volume or open interest.
- Index candles are not option prices, bid/ask, IV, trade-by-trade footprint, aggressor volume or depth.
- About 50 calls per rule-year: an accuracy's 95% interval is about ±14 points wide. A real 55% edge can't be told from 50% in one year of daily data.
