# Warehouse research — real NSE option prices and positioning

Generated 2026-10-31 15:57 IST. Data: NSE F&O bhavcopy and participant-wise OI (the `warehouse` release), index closes from the bhavcopy or Yahoo. 12,625 option trades simulated.

## 1. The volatility premium, traded on real prices

Opened at the close k sessions before expiry at bhavcopy closing prices worsened by a half-spread and a tick, plus brokerage, STT, exchange, GST, stamp and exercise STT; held to cash settlement. ₹ figures are per lot at today's lot sizes (NIFTY 65, BANKNIFTY 30). Benjamini-Hochberg across all rows below.

**The rolling validation is re-inspected every week, so it is not an untouched holdout. A paper candidate still needs a cost-inclusive paper trial before real money.**

| verdict | strategy | index | k | trades | mean ₹/lot | t | rolling validation ₹/lot | win | worst ₹ | max DD ₹ | Sharpe | capital |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 1 | 329 | +1,082 | +3.32 | +929 | 82% | -50,684 | -50,684 | 1.10 | ₹195,720 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 1 | 276 | +1,759 | +3.23 | +1,695 | 66% | -60,499 | -82,642 | 1.14 | ₹195,720 |
| **NO EDGE** | short_straddle | BANKNIFTY | 1 | 329 | +1,494 | +2.92 | +1,560 | 64% | -60,499 | -78,078 | 1.03 | ₹195,720 |
| **NO EDGE** | short_strangle_20d | NIFTY | 1 | 403 | +643 | +2.87 | +794 | 77% | -39,441 | -41,312 | 0.96 | ₹178,907 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 1 | 329 | +872 | +2.66 | +1,209 | 61% | -44,840 | -53,950 | 0.87 | ₹177,475 |
| **NO EDGE** | short_straddle | NIFTY | 1 | 404 | +673 | +2.26 | +996 | 61% | -44,840 | -64,612 | 0.71 | ₹178,907 |
| **NO EDGE** | short_strangle_20d | NIFTY | 3 | 401 | +732 | +2.14 | +946 | 74% | -60,362 | -75,760 | 0.69 | ₹177,448 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 1 | 328 | +360 | +2.03 | +110 | 78% | -18,655 | -29,071 | 0.79 | ₹10,022 |
| **NO EDGE** | iron_fly | NIFTY | 1 | 404 | -251 | -1.88 | -255 | 42% | -9,968 | -122,894 | -0.58 | ₹4,405 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 1 | 329 | +280 | +1.61 | +300 | 80% | -32,893 | -46,728 | 0.58 | ₹9,579 |
| **NO EDGE** | short_strangle_20d | NIFTY | 5 | 293 | +681 | +1.57 | +1,507 | 73% | -45,687 | -73,726 | 0.46 | ₹178,534 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 1 | 393 | +132 | +1.40 | +372 | 76% | -8,529 | -25,897 | 0.46 | ₹7,879 |
| **NO EDGE** | short_straddle | NIFTY | 3 | 401 | +786 | +1.37 | +1,411 | 59% | -72,856 | -182,745 | 0.48 | ₹177,448 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 3 | 305 | -398 | -1.16 | +429 | 40% | -17,736 | -191,773 | -0.46 | ₹6,784 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 1 | 276 | +301 | +1.14 | +332 | 49% | -13,081 | -50,270 | 0.41 | ₹5,622 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 1 | 329 | -173 | -1.13 | -146 | 42% | -8,908 | -82,889 | -0.36 | ₹4,247 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 5 | 236 | -418 | -1.09 | -1,017 | 70% | -21,436 | -136,629 | -0.35 | ₹18,103 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 1 | 396 | +111 | +1.05 | +181 | 74% | -8,457 | -28,113 | 0.35 | ₹8,507 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 1 | 401 | -107 | -0.96 | -180 | 74% | -10,303 | -52,657 | -0.30 | ₹8,382 |
| **NO EDGE** | iron_fly | NIFTY | 5 | 293 | -347 | -0.85 | -441 | 42% | -13,297 | -165,088 | -0.32 | ₹8,585 |
| **NO EDGE** | iron_fly | NIFTY | 3 | 401 | -208 | -0.77 | +2 | 42% | -17,736 | -163,097 | -0.28 | ₹7,033 |
| **NO EDGE** | short_straddle | NIFTY | 5 | 293 | +564 | +0.77 | +1,201 | 59% | -54,202 | -190,289 | 0.24 | ₹178,534 |
| **NO EDGE** | iron_fly | BANKNIFTY | 1 | 329 | +175 | +0.74 | +395 | 48% | -13,081 | -83,097 | 0.26 | ₹5,628 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 5 | 293 | -168 | -0.68 | +118 | 72% | -14,825 | -133,840 | -0.22 | ₹12,778 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 5 | 199 | +674 | +0.67 | +1,955 | 59% | -54,202 | -154,232 | 0.24 | ₹181,966 |
| **NO EDGE** | iron_fly | BANKNIFTY | 5 | 238 | -326 | -0.67 | -1,171 | 43% | -16,232 | -159,536 | -0.21 | ₹11,480 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 5 | 293 | +192 | +0.62 | -614 | 78% | -22,104 | -87,439 | 0.23 | ₹16,127 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 1 | 329 | +92 | +0.57 | +14 | 76% | -19,316 | -36,921 | 0.20 | ₹10,159 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 5 | 199 | -282 | -0.54 | -149 | 41% | -13,297 | -125,049 | -0.21 | ₹8,492 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 3 | 401 | -93 | -0.53 | +489 | 73% | -27,113 | -135,529 | -0.17 | ₹10,657 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 5 | 293 | +112 | +0.46 | -50 | 70% | -18,637 | -74,061 | 0.15 | ₹15,445 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 3 | 305 | +272 | +0.38 | +1,373 | 57% | -72,856 | -185,658 | 0.15 | ₹177,448 |
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 5 | 237 | +248 | +0.31 | -279 | 72% | -99,059 | -131,040 | 0.10 | ₹199,757 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 3 | 401 | +49 | +0.24 | -307 | 78% | -20,555 | -76,496 | 0.08 | ₹13,653 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 5 | 164 | +345 | +0.24 | -306 | 59% | -112,188 | -177,374 | 0.08 | ₹199,757 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 3 | 400 | +27 | +0.15 | +144 | 68% | -14,735 | -85,145 | 0.05 | ₹13,487 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 5 | 237 | -30 | -0.07 | -1,680 | 76% | -26,760 | -149,666 | -0.02 | ₹19,900 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 5 | 164 | +15 | +0.02 | -1,377 | 43% | -16,232 | -100,468 | 0.01 | ₹11,103 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 5 | 238 | -2 | -0.00 | +657 | 75% | -21,533 | -74,441 | -0.00 | ₹17,110 |
| **NO EDGE** | short_straddle | BANKNIFTY | 5 | 238 | -3 | -0.00 | -867 | 59% | -112,188 | -192,506 | -0.00 | ₹199,757 |

### Scorecards: the strongest results through every gate

DSR counts all 40 strategy tests as trials. Capital = the margin or max loss above; ruin is a bootstrap of the trade sequence over as many expiries as were tested.

**short_strangle_20d · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 329 · 82% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,082 |
| 1 edge | avg win / avg loss | ₹3,150 / ₹-8,186 |
| 1 edge | profit factor · SQN | 1.72 · 3.06 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.10 · 1.23 · 1.12 |
| 2 risk | Omega(0) | 1.72 |
| 2 tail | skew · excess kurtosis | -4.80 · 30.63 |
| 2 tail | VaR 95 / 99 per trade | ₹8,124 / ₹24,460 |
| 2 tail | CVaR 95 / 99 per trade | ₹20,187 / ₹42,117 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹11,470 / ₹26,762 |
| 2 drawdown | max DD | ₹-50,684 (-20.8%) |
| 2 drawdown | longest under water · recovery from max DD | 30 · 9 trades |
| 2 drawdown | Ulcer Index | 3.87 |
| 3 friction | slippage break-even per trade | ₹+1,082 (+9.8 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.15 → 0.98 · 0.85 |
| 5 robustness | PSR · DSR (40 trials) | 0.984 · 0.729 |
| ruin | P(−50%) · P(ruin) over 329 trades | 2.1% · 0.1% |

Flags: negative skew -4.80: small frequent gains, rare large losses; fat tails: excess kurtosis 30.6.


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


**short_straddle · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 329 · 64% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,494 |
| 1 edge | avg win / avg loss | ₹6,351 / ₹-7,192 |
| 1 edge | profit factor · SQN | 1.58 · 2.88 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.03 · 1.33 · 1.12 |
| 2 risk | Omega(0) | 1.58 |
| 2 tail | skew · excess kurtosis | -2.24 · 11.28 |
| 2 tail | VaR 95 / 99 per trade | ₹12,976 / ₹29,074 |
| 2 tail | CVaR 95 / 99 per trade | ₹25,510 / ₹47,596 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹16,926 / ₹42,942 |
| 2 drawdown | max DD | ₹-78,078 (-28.7%) |
| 2 drawdown | longest under water · recovery from max DD | 63 · 22 trades |
| 2 drawdown | Ulcer Index | 6.72 |
| 3 friction | slippage break-even per trade | ₹+1,494 (+13.5 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.01 → 1.07 · 1.07 |
| 5 robustness | PSR · DSR (40 trials) | 0.992 · 0.718 |
| ruin | P(−50%) · P(ruin) over 329 trades | 5.7% · 0.3% |

Flags: negative skew -2.24: small frequent gains, rare large losses; fat tails: excess kurtosis 11.3.


### Parameter stability (every delta target and the wing ±10%)

| strategy | index | k | base ₹/lot | −10% | +10% | verdict |
|---|---|---:|---:|---:|---:|---|
| short_strangle_20d | BANKNIFTY | 1 | +1,082 | +948 | +1,166 | stable |
| short_straddle_ivrv | BANKNIFTY | 1 | +1,759 | — | — | no parameters to perturb (ATM strikes) |
| short_straddle | BANKNIFTY | 1 | +1,494 | — | — | no parameters to perturb (ATM strikes) |

### Futures term structure (near and next month, from the bhavcopy)

| index | days | carry now | carry median | roll yield median | backwardation days |
|---|---:|---:|---:|---:|---:|
| NIFTY | 1,766 | 3.02% | 5.07% | 5.00% | 11.8% |
| BANKNIFTY | 1,768 | 3.79% | 6.07% | 4.90% | 9.6% |

Fair carry ≈ r − q = 5.3%: carry well above it means longs pay up for leverage; below, selling pressure in futures.

### The volatility surface's moving parts (PCA of daily IV changes, 15–45 day expiry)

- **NIFTY** (779 days): PC1 71% · PC2 11% · PC3 10% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).
- **BANKNIFTY** (1,178 days): PC1 74% · PC2 8% · PC3 6% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).

India VIX 15.30: IV rank 33%, IV percentile 71% over the last year.


## 2. Positioning (participant-wise OI)

Signals known after the close, traded from the next open. Effect in basis points of the index per trade; the cost hurdle is one lot of a 0.35Δ option in and out.

| verdict | id | index | hypothesis | n | effect bps | t | p | rolling validation bps |
|---|---|---|---|---:|---:|---:|---:|---:|
| **NO EDGE** | P1 | NIFTY | FII index-futures net change → next session, open→close | 1,931 | +3.5 | +1.64 | 0.101 | -2.0 |
| **NO EDGE** | P2 | NIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 209 | -22.7 | -1.60 | 0.110 | +26.4 |
| **NO EDGE** | P1 | BANKNIFTY | FII index-futures net change → next session, open→close | 1,931 | +4.3 | +1.43 | 0.152 | -3.1 |
| **NO EDGE** | P5 | NIFTY | FII futures net 5-day change → next 5 sessions | 385 | -11.5 | -1.10 | 0.271 | -13.6 |
| **NO EDGE** | P3 | NIFTY | Client index-futures net change, contrarian → next session | 1,931 | +1.9 | +1.10 | 0.273 | -2.1 |
| **NO EDGE** | P2 | BANKNIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 209 | -21.2 | -1.03 | 0.304 | +52.4 |
| **NO EDGE** | P5 | BANKNIFTY | FII futures net 5-day change → next 5 sessions | 385 | -13.3 | -0.85 | 0.396 | -13.4 |
| **NO EDGE** | P3 | BANKNIFTY | Client index-futures net change, contrarian → next session | 1,931 | +1.8 | +0.74 | 0.459 | -4.9 |
| **NO EDGE** | P4 | NIFTY | FII index-options net (calls − puts) change → next session | 1,931 | +1.0 | +0.52 | 0.606 | -2.1 |
| **NO EDGE** | P4 | BANKNIFTY | FII index-options net (calls − puts) change → next session | 1,931 | +0.8 | +0.30 | 0.766 | -4.5 |

## 3. When does buying options pay? (the ATM straddle, real prices)

The nearest expiry's ATM straddle, bought and sold at bhavcopy prices with a half-spread and a tick each way on each leg (and fees). **Intraday**: bought at the opening prints at the strike nearest the index's open, sold at the close: what a buyer who squares off by the close lives through. **Overnight**: bought at the close, sold at the next close. P&L is on the premium paid. Move ratio: the index's |move| over the span against the move the straddle's own IV priced for a session (IV/√252·√(2/π)); the intraday span leaves out the overnight gap, so read it across rows, not against 1. FDR within each index × horizon × grouping; a verdict needs the newest third to keep the sign.

- **BANKNIFTY intraday**: 1,930 sessions 2019-01-01 → 2026-10-30; mean -5.7% on the premium, 29% of sessions profitable, median premium 1.64% of the index.
- **BANKNIFTY overnight**: 1,596 sessions 2019-01-01 → 2026-10-29; mean -6.0% on the premium, 28% of sessions profitable, median premium 1.58% of the index.
- **NIFTY intraday**: 1,929 sessions 2019-01-02 → 2026-10-30; mean -6.1% on the premium, 31% of sessions profitable, median premium 1.06% of the index.
- **NIFTY overnight**: 1,522 sessions 2019-01-02 → 2026-10-29; mean -5.8% on the premium, 31% of sessions profitable, median premium 1.00% of the index.

| verdict | index | horizon | by | group | n | mean | median | t | win | move ratio | realised > implied | discovery | validation |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 0 (expiry day) | 332 | -19.7% | -34.5% | -5.63 | 31% | 0.29× | 5% | -19.8% | -19.4% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 1 | 332 | -4.2% | -16.9% | -2.30 | 29% | 0.41× | 17% | -6.3% | -0.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 2 | 331 | -5.6% | -10.2% | -4.46 | 24% | 0.45× | 13% | -5.6% | -5.5% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 3 | 323 | +0.4% | -7.0% | +0.31 | 33% | 0.59× | 25% | +2.1% | -3.1% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 4–5 | 276 | -1.7% | -6.1% | -1.14 | 30% | 0.55× | 26% | -1.0% | -3.2% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 6–10 | 117 | -3.4% | -5.0% | -5.14 | 26% | 0.63× | 22% | -2.9% | -4.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 11+ | 219 | -2.4% | -3.7% | -5.94 | 28% | 0.58× | 28% | -3.0% | -1.2% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Mon | 384 | -0.6% | -5.7% | -0.52 | 33% | 0.54× | 22% | +0.7% | -3.2% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Tue | 388 | -5.8% | -8.8% | -3.57 | 27% | 0.48× | 15% | -4.4% | -8.6% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Wed | 386 | -6.3% | -10.5% | -3.03 | 27% | 0.40× | 15% | -4.3% | -10.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Thu | 390 | -13.4% | -9.5% | -4.91 | 30% | 0.37× | 10% | -17.4% | -5.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Fri | 382 | -2.4% | -5.6% | -2.20 | 30% | 0.61× | 30% | -2.7% | -1.7% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 1 | 332 | -16.4% | -34.5% | -4.01 | 32% | 0.59× | 24% | -15.7% | -17.9% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 2 | 331 | -6.9% | -18.8% | -3.65 | 24% | 0.61× | 27% | -8.8% | -3.1% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 3 | 321 | -5.6% | -13.4% | -3.95 | 24% | 0.58× | 25% | -5.5% | -5.7% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 4–5 | 276 | +2.4% | -7.0% | +1.61 | 34% | 0.88× | 44% | +3.2% | +0.7% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 6–10 | 117 | -3.6% | -5.5% | -4.43 | 21% | 0.64× | 30% | -2.7% | -5.5% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 11+ | 219 | -1.0% | -2.6% | -1.91 | 32% | 0.72× | 33% | -1.8% | +0.4% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Mon | 382 | -7.5% | -11.5% | -4.95 | 23% | 0.55× | 24% | -6.9% | -8.8% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Tue | 370 | -7.9% | -11.2% | -3.44 | 25% | 0.61× | 24% | -9.9% | -3.9% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Wed | 321 | -12.9% | -9.6% | -3.61 | 30% | 0.60× | 26% | -16.5% | -5.6% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Thu | 143 | -1.4% | -4.2% | -1.22 | 35% | 0.86× | 42% | -1.8% | -0.5% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Fri | 380 | +1.5% | -6.4% | +1.17 | 32% | 0.85× | 41% | +2.1% | +0.3% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 0 (expiry day) | 405 | -13.7% | -29.6% | -4.39 | 32% | 0.31× | 5% | -14.3% | -12.7% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 1 | 405 | -7.3% | -14.5% | -4.83 | 27% | 0.47× | 13% | -5.5% | -10.9% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 2 | 404 | -4.7% | -9.8% | -4.33 | 32% | 0.47× | 17% | -4.8% | -4.4% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 3 | 397 | -2.2% | -8.6% | -2.03 | 31% | 0.52× | 22% | -0.9% | -4.9% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 4–5 | 296 | -1.2% | -6.7% | -0.93 | 34% | 0.55× | 29% | -1.2% | -1.3% |
| **NO EDGE** | NIFTY | intraday | weekday | Mon | 384 | -3.1% | -8.2% | -2.36 | 33% | 0.50× | 18% | -1.1% | -6.9% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Tue | 387 | -6.3% | -11.0% | -3.26 | 31% | 0.43× | 14% | -3.9% | -11.2% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Wed | 386 | -7.4% | -12.7% | -4.46 | 25% | 0.44× | 12% | -6.2% | -9.9% |
| **NO EDGE** | NIFTY | intraday | weekday | Thu | 390 | -10.9% | -20.0% | -3.59 | 31% | 0.33× | 8% | -13.9% | -4.9% |
| **NO EDGE** | NIFTY | intraday | weekday | Fri | 382 | -2.5% | -7.0% | -2.30 | 34% | 0.60× | 31% | -2.5% | -2.6% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 1 | 405 | -10.4% | -24.8% | -3.10 | 35% | 0.65× | 29% | -10.2% | -11.0% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 2 | 404 | -7.7% | -14.6% | -5.33 | 29% | 0.70× | 27% | -6.8% | -9.5% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 3 | 396 | -4.0% | -12.4% | -3.08 | 28% | 0.68× | 30% | -4.9% | -2.1% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 4–5 | 295 | +0.6% | -8.5% | +0.46 | 34% | 0.90× | 44% | +1.9% | -1.8% |
| **BUYERS LOSE** | NIFTY | overnight | weekday | Mon | 379 | -8.1% | -14.4% | -5.06 | 25% | 0.58× | 23% | -5.8% | -12.6% |
| **NO EDGE** | NIFTY | overnight | weekday | Tue | 331 | -8.7% | -14.5% | -4.24 | 28% | 0.63× | 25% | -10.2% | -5.7% |
| **NO EDGE** | NIFTY | overnight | weekday | Wed | 371 | -8.3% | -15.6% | -2.36 | 34% | 0.65× | 29% | -10.2% | -4.5% |
| **NO EDGE** | NIFTY | overnight | weekday | Thu | 62 | -1.2% | -6.5% | -0.42 | 34% | 0.84× | 42% | -0.2% | -3.1% |
| **NO EDGE** | NIFTY | overnight | weekday | Fri | 379 | +0.6% | -8.2% | +0.41 | 37% | 0.95× | 46% | +1.2% | -0.5% |
