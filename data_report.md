# Warehouse research — real NSE option prices and positioning

Generated 2026-10-24 14:26 IST. Data: NSE F&O bhavcopy and participant-wise OI (the `warehouse` release), index closes from the bhavcopy or Yahoo. 12,603 option trades simulated.

## 1. The volatility premium, traded on real prices

Opened at the close k sessions before expiry at bhavcopy closing prices worsened by a half-spread and a tick, plus brokerage, STT, exchange, GST, stamp and exercise STT; held to cash settlement. ₹ figures are per lot at today's lot sizes (NIFTY 65, BANKNIFTY 30). Benjamini-Hochberg across all rows below.

**The rolling validation is re-inspected every week, so it is not an untouched holdout. A paper candidate still needs a cost-inclusive paper trial before real money.**

| verdict | strategy | index | k | trades | mean ₹/lot | t | rolling validation ₹/lot | win | worst ₹ | max DD ₹ | Sharpe | capital |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 1 | 329 | +1,092 | +3.34 | +958 | 82% | -50,684 | -50,684 | 1.11 | ₹197,733 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 1 | 276 | +1,773 | +3.25 | +1,738 | 66% | -60,499 | -82,642 | 1.15 | ₹197,733 |
| **NO EDGE** | short_straddle | BANKNIFTY | 1 | 329 | +1,506 | +2.94 | +1,597 | 64% | -60,499 | -78,078 | 1.04 | ₹197,733 |
| **NO EDGE** | short_strangle_20d | NIFTY | 1 | 402 | +637 | +2.84 | +777 | 77% | -39,441 | -41,312 | 0.95 | ₹176,964 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 1 | 328 | +837 | +2.53 | +1,091 | 61% | -44,840 | -53,950 | 0.84 | ₹174,434 |
| **NO EDGE** | short_straddle | NIFTY | 1 | 403 | +648 | +2.17 | +946 | 61% | -44,840 | -64,612 | 0.68 | ₹176,964 |
| **NO EDGE** | short_strangle_20d | NIFTY | 3 | 400 | +719 | +2.10 | +930 | 74% | -60,362 | -75,760 | 0.68 | ₹178,534 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 1 | 328 | +366 | +2.06 | +128 | 78% | -18,655 | -29,071 | 0.80 | ₹10,039 |
| **NO EDGE** | iron_fly | NIFTY | 1 | 403 | -271 | -2.05 | -310 | 42% | -9,968 | -122,894 | -0.63 | ₹4,371 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 1 | 329 | +283 | +1.63 | +310 | 80% | -32,893 | -46,728 | 0.59 | ₹9,605 |
| **NO EDGE** | short_strangle_20d | NIFTY | 5 | 292 | +660 | +1.51 | +1,432 | 73% | -45,687 | -73,726 | 0.45 | ₹177,654 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 1 | 392 | +130 | +1.37 | +377 | 76% | -8,529 | -25,897 | 0.45 | ₹7,911 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 1 | 328 | -199 | -1.30 | -250 | 41% | -8,908 | -82,889 | -0.42 | ₹4,230 |
| **NO EDGE** | short_straddle | NIFTY | 3 | 400 | +741 | +1.29 | +1,277 | 59% | -72,856 | -182,745 | 0.45 | ₹178,534 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 1 | 276 | +304 | +1.15 | +339 | 49% | -13,081 | -50,270 | 0.41 | ₹5,630 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 3 | 304 | -392 | -1.14 | +472 | 40% | -17,736 | -191,773 | -0.46 | ₹6,759 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 5 | 236 | -384 | -1.02 | -916 | 70% | -21,436 | -128,601 | -0.33 | ₹18,182 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 1 | 395 | +106 | +1.01 | +160 | 74% | -8,457 | -28,113 | 0.34 | ₹8,511 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 1 | 400 | -111 | -1.00 | -184 | 74% | -10,303 | -52,657 | -0.31 | ₹8,355 |
| **NO EDGE** | iron_fly | NIFTY | 5 | 292 | -366 | -0.89 | -567 | 42% | -13,297 | -165,088 | -0.34 | ₹8,588 |
| **NO EDGE** | iron_fly | NIFTY | 3 | 400 | -239 | -0.87 | -117 | 42% | -17,736 | -163,097 | -0.32 | ₹7,036 |
| **NO EDGE** | iron_fly | BANKNIFTY | 1 | 329 | +178 | +0.75 | +401 | 48% | -13,081 | -83,097 | 0.26 | ₹5,638 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 5 | 292 | -177 | -0.71 | -4 | 72% | -14,825 | -133,840 | -0.23 | ₹12,779 |
| **NO EDGE** | short_straddle | NIFTY | 5 | 292 | +524 | +0.71 | +974 | 59% | -54,202 | -190,289 | 0.23 | ₹177,654 |
| **NO EDGE** | iron_fly | BANKNIFTY | 5 | 238 | -336 | -0.68 | -1,200 | 43% | -16,232 | -161,911 | -0.22 | ₹11,480 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 5 | 199 | +674 | +0.67 | +1,955 | 59% | -54,202 | -154,232 | 0.24 | ₹181,966 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 1 | 329 | +96 | +0.60 | +27 | 76% | -19,316 | -36,921 | 0.21 | ₹10,168 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 5 | 292 | +181 | +0.58 | -625 | 78% | -22,104 | -87,439 | 0.22 | ₹16,135 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 5 | 199 | -282 | -0.54 | -149 | 41% | -13,297 | -125,049 | -0.21 | ₹8,492 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 3 | 400 | -94 | -0.53 | +491 | 72% | -27,113 | -135,529 | -0.18 | ₹10,635 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 5 | 292 | +100 | +0.41 | -121 | 70% | -18,637 | -74,061 | 0.13 | ₹15,450 |
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 5 | 237 | +286 | +0.36 | -167 | 73% | -99,059 | -131,040 | 0.11 | ₹200,918 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 3 | 304 | +255 | +0.36 | +1,397 | 57% | -72,856 | -185,658 | 0.14 | ₹179,892 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 5 | 164 | +384 | +0.27 | -189 | 59% | -112,188 | -177,374 | 0.08 | ₹200,918 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 3 | 400 | +28 | +0.14 | -362 | 78% | -20,555 | -76,496 | 0.05 | ₹13,653 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 3 | 399 | +20 | +0.11 | +123 | 68% | -14,735 | -85,145 | 0.04 | ₹13,489 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 5 | 237 | -39 | -0.09 | -1,709 | 76% | -26,760 | -151,896 | -0.03 | ₹19,993 |
| **NO EDGE** | short_straddle | BANKNIFTY | 5 | 238 | +24 | +0.02 | -786 | 59% | -112,188 | -192,506 | 0.01 | ₹200,918 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 5 | 238 | +2 | +0.01 | +668 | 75% | -21,533 | -74,441 | 0.00 | ₹17,110 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 5 | 164 | +1 | +0.00 | -1,420 | 43% | -16,232 | -100,468 | 0.00 | ₹11,103 |

### Scorecards: the strongest results through every gate

DSR counts all 40 strategy tests as trials. Capital = the margin or max loss above; ruin is a bootstrap of the trade sequence over as many expiries as were tested.

**short_strangle_20d · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 329 · 82% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,092 |
| 1 edge | avg win / avg loss | ₹3,161 / ₹-8,186 |
| 1 edge | profit factor · SQN | 1.73 · 3.09 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.11 · 1.24 · 1.13 |
| 2 risk | Omega(0) | 1.73 |
| 2 tail | skew · excess kurtosis | -4.79 · 30.52 |
| 2 tail | VaR 95 / 99 per trade | ₹8,124 / ₹24,460 |
| 2 tail | CVaR 95 / 99 per trade | ₹20,187 / ₹42,117 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹11,479 / ₹26,849 |
| 2 drawdown | max DD | ₹-50,684 (-20.7%) |
| 2 drawdown | longest under water · recovery from max DD | 30 · 9 trades |
| 2 drawdown | Ulcer Index | 3.84 |
| 3 friction | slippage break-even per trade | ₹+1,092 (+9.9 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.15 → 1.00 · 0.87 |
| 5 robustness | PSR · DSR (40 trials) | 0.984 · 0.734 |
| ruin | P(−50%) · P(ruin) over 329 trades | 2.0% · 0.1% |

Flags: negative skew -4.79: small frequent gains, rare large losses; fat tails: excess kurtosis 30.5.


**short_straddle_ivrv · BANKNIFTY · k=1** — fails: N ≥ 300, DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 276 · 66% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,773 |
| 1 edge | avg win / avg loss | ₹6,382 / ₹-7,151 |
| 1 edge | profit factor · SQN | 1.73 · 3.22 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.15 · 1.54 · 1.09 |
| 2 risk | Omega(0) | 1.73 |
| 2 tail | skew · excess kurtosis | -2.13 · 11.71 |
| 2 tail | VaR 95 / 99 per trade | ₹12,409 / ₹28,764 |
| 2 tail | CVaR 95 / 99 per trade | ₹23,737 / ₹46,473 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹15,865 / ₹43,234 |
| 2 drawdown | max DD | ₹-82,642 (-29.1%) |
| 2 drawdown | longest under water · recovery from max DD | 41 · 18 trades |
| 2 drawdown | Ulcer Index | 6.01 |
| 3 friction | slippage break-even per trade | ₹+1,773 (+15.8 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.16 → 1.12 · 0.97 |
| 5 robustness | PSR · DSR (40 trials) | 0.995 · 0.797 |
| ruin | P(−50%) · P(ruin) over 276 trades | 2.5% · 0.1% |

Flags: negative skew -2.13: small frequent gains, rare large losses; fat tails: excess kurtosis 11.7.


**short_straddle · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 329 · 64% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,506 |
| 1 edge | avg win / avg loss | ₹6,370 / ₹-7,192 |
| 1 edge | profit factor · SQN | 1.58 · 2.90 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.04 · 1.35 · 1.13 |
| 2 risk | Omega(0) | 1.58 |
| 2 tail | skew · excess kurtosis | -2.24 · 11.28 |
| 2 tail | VaR 95 / 99 per trade | ₹12,976 / ₹29,074 |
| 2 tail | CVaR 95 / 99 per trade | ₹25,510 / ₹47,596 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹16,923 / ₹42,917 |
| 2 drawdown | max DD | ₹-78,078 (-28.5%) |
| 2 drawdown | longest under water · recovery from max DD | 63 · 22 trades |
| 2 drawdown | Ulcer Index | 6.68 |
| 3 friction | slippage break-even per trade | ₹+1,506 (+13.6 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.01 → 1.10 · 1.09 |
| 5 robustness | PSR · DSR (40 trials) | 0.992 · 0.724 |
| ruin | P(−50%) · P(ruin) over 329 trades | 5.4% · 0.3% |

Flags: negative skew -2.24: small frequent gains, rare large losses; fat tails: excess kurtosis 11.3.


### Parameter stability (every delta target and the wing ±10%)

| strategy | index | k | base ₹/lot | −10% | +10% | verdict |
|---|---|---:|---:|---:|---:|---|
| short_strangle_20d | BANKNIFTY | 1 | +1,092 | +954 | +1,174 | stable |
| short_straddle_ivrv | BANKNIFTY | 1 | +1,773 | — | — | no parameters to perturb (ATM strikes) |
| short_straddle | BANKNIFTY | 1 | +1,506 | — | — | no parameters to perturb (ATM strikes) |

### Futures term structure (near and next month, from the bhavcopy)

| index | days | carry now | carry median | roll yield median | backwardation days |
|---|---:|---:|---:|---:|---:|
| NIFTY | 1,762 | -9.45% | 5.07% | 4.99% | 11.8% |
| BANKNIFTY | 1,764 | -7.59% | 6.07% | 4.90% | 9.6% |

Fair carry ≈ r − q = 5.3%: carry well above it means longs pay up for leverage; below, selling pressure in futures.

### The volatility surface's moving parts (PCA of daily IV changes, 15–45 day expiry)

- **NIFTY** (777 days): PC1 71% · PC2 11% · PC3 10% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).
- **BANKNIFTY** (1,173 days): PC1 74% · PC2 8% · PC3 6% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).

India VIX 16.86: IV rank 41%, IV percentile 79% over the last year.


## 2. Positioning (participant-wise OI)

Signals known after the close, traded from the next open. Effect in basis points of the index per trade; the cost hurdle is one lot of a 0.35Δ option in and out.

| verdict | id | index | hypothesis | n | effect bps | t | p | rolling validation bps |
|---|---|---|---|---:|---:|---:|---:|---:|
| **NO EDGE** | P1 | NIFTY | FII index-futures net change → next session, open→close | 1,926 | +3.5 | +1.65 | 0.100 | -1.9 |
| **NO EDGE** | P2 | NIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 209 | -22.7 | -1.60 | 0.110 | +26.4 |
| **NO EDGE** | P1 | BANKNIFTY | FII index-futures net change → next session, open→close | 1,926 | +4.3 | +1.44 | 0.149 | -3.0 |
| **NO EDGE** | P5 | NIFTY | FII futures net 5-day change → next 5 sessions | 384 | -11.6 | -1.10 | 0.270 | -13.8 |
| **NO EDGE** | P3 | NIFTY | Client index-futures net change, contrarian → next session | 1,926 | +1.9 | +1.08 | 0.280 | -2.2 |
| **NO EDGE** | P2 | BANKNIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 209 | -21.2 | -1.03 | 0.304 | +52.4 |
| **NO EDGE** | P5 | BANKNIFTY | FII futures net 5-day change → next 5 sessions | 384 | -13.1 | -0.84 | 0.404 | -12.9 |
| **NO EDGE** | P3 | BANKNIFTY | Client index-futures net change, contrarian → next session | 1,926 | +1.9 | +0.77 | 0.440 | -4.7 |
| **NO EDGE** | P4 | NIFTY | FII index-options net (calls − puts) change → next session | 1,926 | +1.0 | +0.50 | 0.616 | -2.2 |
| **NO EDGE** | P4 | BANKNIFTY | FII index-options net (calls − puts) change → next session | 1,926 | +0.9 | +0.32 | 0.751 | -4.3 |

## 3. When does buying options pay? (the ATM straddle, real prices)

The nearest expiry's ATM straddle, bought and sold at bhavcopy prices with a half-spread and a tick each way on each leg (and fees). **Intraday**: bought at the opening prints at the strike nearest the index's open, sold at the close: what a buyer who squares off by the close lives through. **Overnight**: bought at the close, sold at the next close. P&L is on the premium paid. Move ratio: the index's |move| over the span against the move the straddle's own IV priced for a session (IV/√252·√(2/π)); the intraday span leaves out the overnight gap, so read it across rows, not against 1. FDR within each index × horizon × grouping; a verdict needs the newest third to keep the sign.

- **BANKNIFTY intraday**: 1,925 sessions 2019-01-01 → 2026-10-23; mean -5.7% on the premium, 29% of sessions profitable, median premium 1.64% of the index.
- **BANKNIFTY overnight**: 1,592 sessions 2019-01-01 → 2026-10-22; mean -5.9% on the premium, 28% of sessions profitable, median premium 1.58% of the index.
- **NIFTY intraday**: 1,924 sessions 2019-01-02 → 2026-10-23; mean -6.1% on the premium, 31% of sessions profitable, median premium 1.06% of the index.
- **NIFTY overnight**: 1,518 sessions 2019-01-02 → 2026-10-22; mean -5.8% on the premium, 31% of sessions profitable, median premium 1.00% of the index.

| verdict | index | horizon | by | group | n | mean | median | t | win | move ratio | realised > implied | discovery | validation |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 0 (expiry day) | 331 | -19.5% | -34.5% | -5.59 | 32% | 0.29× | 5% | -19.6% | -19.4% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 1 | 331 | -4.1% | -16.7% | -2.25 | 29% | 0.41× | 17% | -6.3% | +0.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 2 | 330 | -5.6% | -10.3% | -4.46 | 25% | 0.45× | 13% | -5.6% | -5.5% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 3 | 323 | +0.4% | -7.0% | +0.30 | 33% | 0.59× | 25% | +2.1% | -3.1% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 4–5 | 276 | -1.8% | -6.1% | -1.17 | 30% | 0.54× | 26% | -1.0% | -3.4% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 6–10 | 117 | -3.3% | -4.8% | -5.10 | 27% | 0.63× | 24% | -2.9% | -4.0% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 11+ | 217 | -2.5% | -3.8% | -5.96 | 27% | 0.57× | 28% | -3.0% | -1.4% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Mon | 383 | -0.5% | -5.7% | -0.44 | 33% | 0.56× | 22% | +0.8% | -3.0% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Tue | 387 | -5.7% | -8.8% | -3.51 | 27% | 0.48× | 16% | -4.4% | -8.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Wed | 385 | -6.3% | -10.6% | -3.02 | 27% | 0.40× | 15% | -4.5% | -10.0% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Thu | 389 | -13.4% | -9.7% | -4.91 | 30% | 0.37× | 10% | -17.3% | -5.8% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Fri | 381 | -2.4% | -5.6% | -2.19 | 30% | 0.61× | 30% | -2.7% | -1.7% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 1 | 331 | -16.3% | -34.5% | -3.97 | 32% | 0.59× | 25% | -15.6% | -17.6% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 2 | 330 | -6.8% | -18.8% | -3.60 | 24% | 0.61× | 27% | -8.8% | -2.9% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 3 | 321 | -5.6% | -13.4% | -3.97 | 24% | 0.58× | 25% | -5.5% | -5.8% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 4–5 | 276 | +2.3% | -7.2% | +1.58 | 34% | 0.88× | 44% | +3.2% | +0.5% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 6–10 | 117 | -3.4% | -5.0% | -4.21 | 22% | 0.66× | 31% | -2.7% | -4.9% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 11+ | 217 | -1.1% | -2.7% | -1.92 | 32% | 0.71× | 33% | -1.8% | +0.4% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Mon | 381 | -7.4% | -11.4% | -4.88 | 23% | 0.55× | 24% | -6.9% | -8.5% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Tue | 370 | -7.9% | -11.2% | -3.44 | 25% | 0.61× | 24% | -9.9% | -3.9% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Wed | 320 | -12.9% | -9.6% | -3.61 | 30% | 0.60× | 25% | -16.8% | -5.1% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Thu | 142 | -1.3% | -4.2% | -1.19 | 35% | 0.86× | 42% | -1.7% | -0.5% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Fri | 379 | +1.6% | -6.3% | +1.24 | 32% | 0.85× | 41% | +2.2% | +0.4% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 0 (expiry day) | 404 | -13.6% | -29.5% | -4.34 | 32% | 0.31× | 5% | -14.2% | -12.5% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 1 | 404 | -7.4% | -14.6% | -4.91 | 26% | 0.46× | 13% | -5.4% | -11.3% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 2 | 403 | -4.6% | -9.8% | -4.19 | 32% | 0.48× | 17% | -4.8% | -4.2% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 3 | 396 | -2.2% | -8.6% | -2.01 | 32% | 0.52× | 22% | -0.9% | -4.8% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 4–5 | 295 | -1.3% | -6.9% | -1.00 | 34% | 0.55× | 29% | -1.4% | -1.3% |
| **NO EDGE** | NIFTY | intraday | weekday | Mon | 383 | -3.1% | -8.3% | -2.42 | 33% | 0.50× | 19% | -1.1% | -7.1% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Tue | 386 | -6.2% | -10.9% | -3.17 | 31% | 0.43× | 14% | -3.8% | -11.0% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Wed | 385 | -7.4% | -12.7% | -4.45 | 25% | 0.44× | 12% | -6.4% | -9.5% |
| **NO EDGE** | NIFTY | intraday | weekday | Thu | 389 | -11.0% | -20.0% | -3.60 | 31% | 0.33× | 7% | -13.7% | -5.6% |
| **NO EDGE** | NIFTY | intraday | weekday | Fri | 381 | -2.5% | -7.0% | -2.28 | 34% | 0.61× | 31% | -2.5% | -2.5% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 1 | 404 | -10.2% | -24.8% | -3.02 | 35% | 0.65× | 29% | -10.0% | -10.7% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 2 | 403 | -7.7% | -14.7% | -5.33 | 29% | 0.70× | 27% | -6.7% | -9.7% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 3 | 395 | -4.0% | -12.4% | -3.08 | 28% | 0.68× | 30% | -4.8% | -2.3% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 4–5 | 294 | +0.7% | -8.5% | +0.48 | 34% | 0.90× | 44% | +1.9% | -1.7% |
| **BUYERS LOSE** | NIFTY | overnight | weekday | Mon | 378 | -7.9% | -14.4% | -4.84 | 25% | 0.58× | 23% | -5.8% | -12.1% |
| **NO EDGE** | NIFTY | overnight | weekday | Tue | 331 | -8.7% | -14.5% | -4.24 | 28% | 0.63× | 25% | -10.2% | -5.7% |
| **NO EDGE** | NIFTY | overnight | weekday | Wed | 370 | -8.3% | -15.7% | -2.37 | 34% | 0.65× | 29% | -9.9% | -5.0% |
| **NO EDGE** | NIFTY | overnight | weekday | Thu | 61 | -1.0% | -6.4% | -0.35 | 34% | 0.86× | 43% | +0.1% | -3.2% |
| **NO EDGE** | NIFTY | overnight | weekday | Fri | 378 | +0.6% | -8.1% | +0.43 | 37% | 0.95× | 46% | +1.2% | -0.4% |
