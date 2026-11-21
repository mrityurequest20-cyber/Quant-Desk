# Warehouse research — real NSE option prices and positioning

Generated 2026-11-21 18:13 IST. Data: NSE F&O bhavcopy and participant-wise OI (the `warehouse` release), index closes from the bhavcopy or Yahoo. 12,703 option trades simulated.

## 1. The volatility premium, traded on real prices

Opened at the close k sessions before expiry at bhavcopy closing prices worsened by a half-spread and a tick, plus brokerage, STT, exchange, GST, stamp and exercise STT; held to cash settlement. ₹ figures are per lot at today's lot sizes (NIFTY 65, BANKNIFTY 30). Benjamini-Hochberg across all rows below.

**The rolling validation is re-inspected every week, so it is not an untouched holdout. A paper candidate still needs a cost-inclusive paper trial before real money.**

| verdict | strategy | index | k | trades | mean ₹/lot | t | rolling validation ₹/lot | win | worst ₹ | max DD ₹ | Sharpe | capital |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 1 | 276 | +1,759 | +3.23 | +1,695 | 66% | -60,499 | -82,642 | 1.14 | ₹195,720 |
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 1 | 330 | +1,032 | +3.17 | +761 | 82% | -50,684 | -50,684 | 1.03 | ₹227,027 |
| **NO EDGE** | short_strangle_20d | NIFTY | 1 | 406 | +629 | +2.80 | +721 | 77% | -39,441 | -41,312 | 0.93 | ₹199,012 |
| **NO EDGE** | short_straddle | BANKNIFTY | 1 | 330 | +1,421 | +2.78 | +1,264 | 64% | -60,499 | -78,078 | 0.97 | ₹227,027 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 1 | 332 | +912 | +2.78 | +1,364 | 61% | -44,840 | -53,950 | 0.90 | ₹197,271 |
| **NO EDGE** | short_straddle | NIFTY | 1 | 407 | +674 | +2.26 | +996 | 61% | -44,840 | -64,612 | 0.70 | ₹199,012 |
| **NO EDGE** | iron_fly | NIFTY | 1 | 407 | -246 | -1.83 | -215 | 42% | -9,968 | -122,894 | -0.55 | ₹4,502 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 1 | 329 | +324 | +1.82 | -8 | 78% | -18,655 | -29,071 | 0.69 | ₹10,035 |
| **NO EDGE** | short_strangle_20d | NIFTY | 3 | 404 | +560 | +1.52 | +381 | 74% | -60,362 | -78,962 | 0.50 | ₹198,022 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 1 | 330 | +243 | +1.39 | +176 | 80% | -32,893 | -46,728 | 0.49 | ₹9,601 |
| **NO EDGE** | short_strangle_20d | NIFTY | 5 | 295 | +588 | +1.32 | +1,170 | 73% | -45,687 | -73,726 | 0.39 | ₹195,348 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 5 | 237 | -494 | -1.23 | -1,308 | 70% | -21,436 | -154,926 | -0.41 | ₹18,178 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 1 | 396 | +112 | +1.16 | +342 | 76% | -8,529 | -25,897 | 0.38 | ₹7,923 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 1 | 276 | +301 | +1.14 | +332 | 49% | -13,081 | -50,270 | 0.41 | ₹5,622 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 3 | 306 | -383 | -1.12 | +476 | 41% | -17,736 | -191,773 | -0.44 | ₹6,841 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 1 | 399 | +110 | +1.05 | +206 | 74% | -8,457 | -28,113 | 0.35 | ₹8,525 |
| **NO EDGE** | short_straddle | NIFTY | 3 | 404 | +588 | +0.99 | +761 | 58% | -72,856 | -182,745 | 0.35 | ₹198,022 |
| **NO EDGE** | iron_fly | NIFTY | 5 | 295 | -373 | -0.92 | -569 | 42% | -13,297 | -165,088 | -0.35 | ₹8,646 |
| **NO EDGE** | iron_fly | NIFTY | 3 | 404 | -230 | -0.85 | -66 | 42% | -17,736 | -163,097 | -0.30 | ₹7,026 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 1 | 332 | -134 | -0.85 | -5 | 42% | -8,908 | -82,889 | -0.27 | ₹4,328 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 3 | 404 | -147 | -0.80 | +321 | 72% | -27,113 | -135,529 | -0.27 | ₹10,679 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 5 | 295 | -196 | -0.80 | +6 | 72% | -14,825 | -133,840 | -0.25 | ₹12,793 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 1 | 404 | -87 | -0.78 | -111 | 75% | -10,303 | -52,657 | -0.25 | ₹8,416 |
| **NO EDGE** | iron_fly | BANKNIFTY | 5 | 239 | -376 | -0.76 | -1,216 | 43% | -16,232 | -171,748 | -0.24 | ₹11,629 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 5 | 295 | +220 | +0.71 | -550 | 78% | -22,104 | -87,439 | 0.27 | ₹16,185 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 1 | 330 | +103 | +0.64 | +34 | 76% | -19,316 | -36,921 | 0.22 | ₹10,166 |
| **NO EDGE** | iron_fly | BANKNIFTY | 1 | 330 | +151 | +0.63 | +264 | 48% | -13,081 | -83,097 | 0.22 | ₹5,636 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 5 | 201 | -321 | -0.61 | -208 | 41% | -13,297 | -125,049 | -0.24 | ₹8,558 |
| **NO EDGE** | short_straddle | NIFTY | 5 | 295 | +446 | +0.60 | +734 | 59% | -54,202 | -190,289 | 0.19 | ₹195,348 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 5 | 201 | +500 | +0.48 | +1,339 | 59% | -54,202 | -154,232 | 0.17 | ₹195,348 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 5 | 295 | +99 | +0.41 | -117 | 69% | -18,637 | -74,061 | 0.13 | ₹15,467 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 3 | 404 | +69 | +0.34 | -270 | 78% | -20,555 | -76,496 | 0.12 | ₹13,642 |
| **NO EDGE** | short_straddle | BANKNIFTY | 5 | 239 | -308 | -0.27 | -1,767 | 59% | -112,188 | -263,659 | -0.08 | ₹219,723 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 5 | 239 | -85 | -0.24 | +362 | 74% | -21,533 | -74,441 | -0.07 | ₹17,407 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 5 | 164 | +345 | +0.24 | -306 | 59% | -112,188 | -177,374 | 0.08 | ₹199,757 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 3 | 306 | +148 | +0.21 | +970 | 57% | -72,856 | -185,658 | 0.08 | ₹197,335 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 3 | 403 | -14 | -0.08 | -10 | 68% | -14,735 | -85,145 | -0.03 | ₹13,459 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 5 | 164 | +15 | +0.02 | -1,377 | 43% | -16,232 | -100,468 | 0.01 | ₹11,103 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 5 | 238 | -7 | -0.02 | -1,593 | 76% | -26,760 | -149,666 | -0.01 | ₹19,993 |
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 5 | 238 | +10 | +0.01 | -982 | 72% | -99,059 | -169,134 | 0.00 | ₹219,723 |

### Scorecards: the strongest results through every gate

DSR counts all 40 strategy tests as trials. Capital = the margin or max loss above; ruin is a bootstrap of the trade sequence over as many expiries as were tested.

**short_straddle_ivrv · BANKNIFTY · k=1** — fails: N ≥ 300, DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 276 · 66% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,759 |
| 1 edge | avg win / avg loss | ₹6,360 / ₹-7,151 |
| 1 edge | profit factor · SQN | 1.72 · 3.20 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.14 · 1.52 · 1.08 |
| 2 risk | Omega(0) | 1.72 |
| 2 tail | skew · excess kurtosis | -2.13 · 11.71 |
| 2 tail | VaR 95 / 99 per trade | ₹12,409 / ₹28,764 |
| 2 tail | CVaR 95 / 99 per trade | ₹23,737 / ₹46,473 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹15,869 / ₹43,263 |
| 2 drawdown | max DD | ₹-82,642 (-29.3%) |
| 2 drawdown | longest under water · recovery from max DD | 41 · 18 trades |
| 2 drawdown | Ulcer Index | 6.04 |
| 3 friction | slippage break-even per trade | ₹+1,759 (+15.6 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.16 → 1.10 · 0.94 |
| 5 robustness | PSR · DSR (40 trials) | 0.995 · 0.791 |
| ruin | P(−50%) · P(ruin) over 276 trades | 2.6% · 0.1% |

Flags: negative skew -2.13: small frequent gains, rare large losses; fat tails: excess kurtosis 11.7.


**short_strangle_20d · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 330 · 82% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,032 |
| 1 edge | avg win / avg loss | ₹3,150 / ₹-8,305 |
| 1 edge | profit factor · SQN | 1.67 · 2.90 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.03 · 1.16 · 1.03 |
| 2 risk | Omega(0) | 1.67 |
| 2 tail | skew · excess kurtosis | -4.69 · 29.40 |
| 2 tail | VaR 95 / 99 per trade | ₹8,604 / ₹24,400 |
| 2 tail | CVaR 95 / 99 per trade | ₹20,602 / ₹42,117 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹11,714 / ₹27,144 |
| 2 drawdown | max DD | ₹-50,684 (-18.5%) |
| 2 drawdown | longest under water · recovery from max DD | 30 · 9 trades |
| 2 drawdown | Ulcer Index | 3.52 |
| 3 friction | slippage break-even per trade | ₹+1,032 (+9.3 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.16 → 0.78 · 0.67 |
| 5 robustness | PSR · DSR (40 trials) | 0.981 · 0.695 |
| ruin | P(−50%) · P(ruin) over 330 trades | 1.7% · 0.0% |

Flags: negative skew -4.69: small frequent gains, rare large losses; fat tails: excess kurtosis 29.4.


**short_strangle_20d · NIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 406 · 77% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+629 |
| 1 edge | avg win / avg loss | ₹2,408 / ₹-5,361 |
| 1 edge | profit factor · SQN | 1.51 · 2.60 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 0.93 · 1.06 · 0.94 |
| 2 risk | Omega(0) | 1.51 |
| 2 tail | skew · excess kurtosis | -4.26 · 26.44 |
| 2 tail | VaR 95 / 99 per trade | ₹7,099 / ₹19,141 |
| 2 tail | CVaR 95 / 99 per trade | ₹15,385 / ₹29,694 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹9,010 / ₹22,792 |
| 2 drawdown | max DD | ₹-41,312 (-17.5%) |
| 2 drawdown | longest under water · recovery from max DD | 52 · 38 trades |
| 2 drawdown | Ulcer Index | 4.78 |
| 3 friction | slippage break-even per trade | ₹+629 (+5.4 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 0.93 → 0.94 · 1.01 |
| 5 robustness | PSR · DSR (40 trials) | 0.978 · 0.626 |
| ruin | P(−50%) · P(ruin) over 406 trades | 1.4% · 0.1% |

Flags: negative skew -4.26: small frequent gains, rare large losses; fat tails: excess kurtosis 26.4.


### Parameter stability (every delta target and the wing ±10%)

| strategy | index | k | base ₹/lot | −10% | +10% | verdict |
|---|---|---:|---:|---:|---:|---|
| short_straddle_ivrv | BANKNIFTY | 1 | +1,759 | — | — | no parameters to perturb (ATM strikes) |
| short_strangle_20d | BANKNIFTY | 1 | +1,032 | +905 | +1,118 | stable |
| short_strangle_20d | NIFTY | 1 | +629 | +569 | +641 | stable |

### Futures term structure (near and next month, from the bhavcopy)

| index | days | carry now | carry median | roll yield median | backwardation days |
|---|---:|---:|---:|---:|---:|
| NIFTY | 1,780 | -11.94% | 5.05% | 5.01% | 12.0% |
| BANKNIFTY | 1,782 | -14.80% | 6.04% | 4.91% | 10.0% |

Fair carry ≈ r − q = 5.3%: carry well above it means longs pay up for leverage; below, selling pressure in futures.

### The volatility surface's moving parts (PCA of daily IV changes, 15–45 day expiry)

- **NIFTY** (789 days): PC1 71% · PC2 11% · PC3 10% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).
- **BANKNIFTY** (1,188 days): PC1 74% · PC2 8% · PC3 6% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).

India VIX 17.32: IV rank 44%, IV percentile 79% over the last year.


## 2. Positioning (participant-wise OI)

Signals known after the close, traded from the next open. Effect in basis points of the index per trade; the cost hurdle is one lot of a 0.35Δ option in and out.

| verdict | id | index | hypothesis | n | effect bps | t | p | rolling validation bps |
|---|---|---|---|---:|---:|---:|---:|---:|
| **NO EDGE** | P2 | NIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 211 | -24.7 | -1.75 | 0.081 | +19.2 |
| **NO EDGE** | P1 | NIFTY | FII index-futures net change → next session, open→close | 1,945 | +3.7 | +1.72 | 0.086 | -1.6 |
| **NO EDGE** | P1 | BANKNIFTY | FII index-futures net change → next session, open→close | 1,945 | +4.6 | +1.53 | 0.125 | -2.3 |
| **NO EDGE** | P2 | BANKNIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 211 | -26.2 | -1.25 | 0.212 | +36.3 |
| **NO EDGE** | P3 | NIFTY | Client index-futures net change, contrarian → next session | 1,945 | +2.1 | +1.24 | 0.214 | -1.3 |
| **NO EDGE** | P3 | BANKNIFTY | Client index-futures net change, contrarian → next session | 1,945 | +2.3 | +0.91 | 0.361 | -3.6 |
| **NO EDGE** | P5 | NIFTY | FII futures net 5-day change → next 5 sessions | 388 | -8.8 | -0.82 | 0.414 | -3.9 |
| **NO EDGE** | P5 | BANKNIFTY | FII futures net 5-day change → next 5 sessions | 388 | -9.8 | -0.61 | 0.539 | -1.3 |
| **NO EDGE** | P4 | NIFTY | FII index-options net (calls − puts) change → next session | 1,945 | +1.1 | +0.55 | 0.583 | -1.7 |
| **NO EDGE** | P4 | BANKNIFTY | FII index-options net (calls − puts) change → next session | 1,945 | +1.0 | +0.36 | 0.719 | -3.9 |

## 3. When does buying options pay? (the ATM straddle, real prices)

The nearest expiry's ATM straddle, bought and sold at bhavcopy prices with a half-spread and a tick each way on each leg (and fees). **Intraday**: bought at the opening prints at the strike nearest the index's open, sold at the close: what a buyer who squares off by the close lives through. **Overnight**: bought at the close, sold at the next close. P&L is on the premium paid. Move ratio: the index's |move| over the span against the move the straddle's own IV priced for a session (IV/√252·√(2/π)); the intraday span leaves out the overnight gap, so read it across rows, not against 1. FDR within each index × horizon × grouping; a verdict needs the newest third to keep the sign.

- **BANKNIFTY intraday**: 1,944 sessions 2019-01-01 → 2026-11-20; mean -5.6% on the premium, 29% of sessions profitable, median premium 1.64% of the index.
- **BANKNIFTY overnight**: 1,610 sessions 2019-01-01 → 2026-11-19; mean -5.8% on the premium, 28% of sessions profitable, median premium 1.59% of the index.
- **NIFTY intraday**: 1,943 sessions 2019-01-02 → 2026-11-20; mean -6.0% on the premium, 31% of sessions profitable, median premium 1.06% of the index.
- **NIFTY overnight**: 1,533 sessions 2019-01-02 → 2026-11-19; mean -5.7% on the premium, 31% of sessions profitable, median premium 1.01% of the index.

| verdict | index | horizon | by | group | n | mean | median | t | win | move ratio | realised > implied | discovery | validation |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 0 (expiry day) | 332 | -19.2% | -34.5% | -5.52 | 32% | 0.29× | 5% | -19.8% | -18.1% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 1 | 332 | -4.0% | -16.9% | -2.20 | 29% | 0.41× | 17% | -6.3% | +0.4% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 2 | 331 | -5.6% | -10.5% | -4.50 | 24% | 0.44× | 13% | -5.6% | -5.6% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 3 | 324 | +0.4% | -6.9% | +0.32 | 34% | 0.59× | 25% | +2.4% | -3.6% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 4–5 | 278 | -1.8% | -6.2% | -1.22 | 30% | 0.55× | 26% | -1.1% | -3.4% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 6–10 | 122 | -3.1% | -4.7% | -4.52 | 28% | 0.64× | 24% | -3.2% | -2.9% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 11+ | 225 | -2.4% | -3.6% | -5.99 | 28% | 0.58× | 28% | -2.9% | -1.5% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Mon | 387 | -0.6% | -5.7% | -0.54 | 33% | 0.56× | 22% | +0.6% | -3.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Tue | 390 | -5.8% | -8.8% | -3.56 | 27% | 0.48× | 16% | -4.8% | -7.7% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Wed | 389 | -6.3% | -10.5% | -3.06 | 27% | 0.40× | 15% | -4.3% | -10.5% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Thu | 393 | -13.2% | -9.2% | -4.84 | 30% | 0.38× | 11% | -17.4% | -4.7% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Fri | 385 | -2.0% | -5.6% | -1.75 | 30% | 0.61× | 30% | -2.7% | -0.5% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 1 | 332 | -16.1% | -34.5% | -3.94 | 32% | 0.59× | 25% | -15.7% | -17.0% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 2 | 331 | -6.8% | -18.8% | -3.58 | 24% | 0.61× | 27% | -8.8% | -2.8% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 3 | 322 | -5.6% | -13.3% | -3.97 | 24% | 0.58× | 25% | -5.5% | -5.7% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 4–5 | 278 | +2.4% | -6.8% | +1.61 | 34% | 0.89× | 45% | +3.1% | +0.8% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 6–10 | 122 | -3.2% | -5.2% | -3.81 | 22% | 0.67× | 32% | -2.3% | -5.1% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 11+ | 225 | -0.8% | -2.6% | -1.29 | 32% | 0.76× | 33% | -1.4% | +0.6% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Mon | 385 | -7.4% | -11.4% | -4.91 | 24% | 0.57× | 25% | -7.0% | -8.1% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Tue | 372 | -7.9% | -11.1% | -3.45 | 25% | 0.61× | 24% | -8.2% | -7.3% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Wed | 324 | -12.5% | -9.3% | -3.51 | 30% | 0.60× | 26% | -15.9% | -5.7% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Thu | 146 | -0.5% | -4.2% | -0.38 | 36% | 0.87× | 42% | -1.8% | +2.0% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Fri | 383 | +1.5% | -6.3% | +1.15 | 32% | 0.85× | 41% | +1.9% | +0.7% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 0 (expiry day) | 408 | -13.7% | -29.5% | -4.42 | 32% | 0.31× | 5% | -14.1% | -13.0% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 1 | 408 | -7.2% | -14.4% | -4.73 | 27% | 0.47× | 13% | -5.7% | -10.1% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 2 | 407 | -4.7% | -9.8% | -4.39 | 32% | 0.48× | 16% | -4.9% | -4.3% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 3 | 400 | -2.2% | -8.6% | -2.07 | 32% | 0.52× | 22% | -0.9% | -4.9% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 4–5 | 298 | -1.2% | -6.7% | -0.95 | 34% | 0.55× | 29% | -1.3% | -1.1% |
| **NO EDGE** | NIFTY | intraday | weekday | Mon | 387 | -3.3% | -8.3% | -2.58 | 33% | 0.50× | 18% | -1.3% | -7.5% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Tue | 389 | -6.4% | -11.0% | -3.33 | 31% | 0.43× | 14% | -4.0% | -11.2% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Wed | 389 | -7.4% | -12.7% | -4.46 | 26% | 0.44× | 13% | -5.5% | -11.1% |
| **NO EDGE** | NIFTY | intraday | weekday | Thu | 393 | -10.8% | -20.0% | -3.58 | 31% | 0.33× | 8% | -14.2% | -4.1% |
| **NO EDGE** | NIFTY | intraday | weekday | Fri | 385 | -2.2% | -7.0% | -1.97 | 35% | 0.61× | 31% | -2.5% | -1.6% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 1 | 408 | -10.4% | -24.9% | -3.11 | 36% | 0.65× | 29% | -10.2% | -10.9% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 2 | 407 | -7.5% | -14.5% | -5.15 | 30% | 0.71× | 28% | -7.0% | -8.5% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 3 | 399 | -3.8% | -12.4% | -2.91 | 28% | 0.68× | 30% | -4.9% | -1.5% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 4–5 | 297 | +0.6% | -8.5% | +0.42 | 34% | 0.90× | 44% | +1.7% | -1.6% |
| **BUYERS LOSE** | NIFTY | overnight | weekday | Mon | 381 | -7.9% | -14.4% | -4.95 | 25% | 0.58× | 23% | -5.9% | -12.0% |
| **NO EDGE** | NIFTY | overnight | weekday | Tue | 331 | -8.7% | -14.5% | -4.24 | 28% | 0.63× | 25% | -10.2% | -5.7% |
| **NO EDGE** | NIFTY | overnight | weekday | Wed | 374 | -8.0% | -15.5% | -2.29 | 34% | 0.65× | 29% | -10.1% | -3.7% |
| **NO EDGE** | NIFTY | overnight | weekday | Thu | 65 | -0.1% | -6.4% | -0.04 | 35% | 0.86× | 43% | +1.6% | -3.3% |
| **NO EDGE** | NIFTY | overnight | weekday | Fri | 382 | +0.3% | -8.2% | +0.24 | 37% | 0.94× | 46% | +1.0% | -0.9% |
