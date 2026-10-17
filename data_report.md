# Warehouse research — real NSE option prices and positioning

Generated 2026-10-17 14:07 IST. Data: NSE F&O bhavcopy and participant-wise OI (the `warehouse` release), index closes from the bhavcopy or Yahoo. 12,567 option trades simulated.

## 1. The volatility premium, traded on real prices

Opened at the close k sessions before expiry at bhavcopy closing prices worsened by a half-spread and a tick, plus brokerage, STT, exchange, GST, stamp and exercise STT; held to cash settlement. ₹ figures are per lot at today's lot sizes (NIFTY 65, BANKNIFTY 30). Benjamini-Hochberg across all rows below.

**The rolling validation is re-inspected every week, so it is not an untouched holdout. A paper candidate still needs a cost-inclusive paper trial before real money.**

| verdict | strategy | index | k | trades | mean ₹/lot | t | rolling validation ₹/lot | win | worst ₹ | max DD ₹ | Sharpe | capital |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 1 | 328 | +1,074 | +3.29 | +916 | 82% | -50,684 | -50,684 | 1.09 | ₹196,098 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 1 | 275 | +1,760 | +3.22 | +1,746 | 66% | -60,499 | -82,642 | 1.15 | ₹196,098 |
| **NO EDGE** | short_straddle | BANKNIFTY | 1 | 328 | +1,495 | +2.91 | +1,526 | 64% | -60,499 | -78,078 | 1.03 | ₹196,098 |
| **NO EDGE** | short_strangle_20d | NIFTY | 1 | 401 | +630 | +2.80 | +768 | 77% | -39,441 | -41,312 | 0.94 | ₹179,379 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 1 | 328 | +837 | +2.53 | +1,091 | 61% | -44,840 | -53,950 | 0.84 | ₹174,434 |
| **NO EDGE** | short_straddle | NIFTY | 1 | 402 | +644 | +2.16 | +935 | 61% | -44,840 | -64,612 | 0.68 | ₹179,379 |
| **NO EDGE** | iron_fly | NIFTY | 1 | 402 | -274 | -2.08 | -320 | 42% | -9,968 | -118,002 | -0.64 | ₹4,365 |
| **NO EDGE** | short_strangle_20d | NIFTY | 3 | 399 | +697 | +2.03 | +866 | 74% | -60,362 | -75,760 | 0.66 | ₹177,231 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 1 | 327 | +355 | +2.01 | +93 | 78% | -18,655 | -29,071 | 0.78 | ₹10,023 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 1 | 328 | +275 | +1.59 | +296 | 80% | -32,893 | -46,728 | 0.57 | ₹9,581 |
| **NO EDGE** | short_strangle_20d | NIFTY | 5 | 292 | +660 | +1.51 | +1,432 | 73% | -45,687 | -73,726 | 0.45 | ₹177,654 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 1 | 328 | -199 | -1.30 | -250 | 41% | -8,908 | -82,889 | -0.42 | ₹4,230 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 1 | 391 | +124 | +1.29 | +337 | 76% | -8,529 | -25,897 | 0.43 | ₹7,880 |
| **NO EDGE** | short_straddle | NIFTY | 3 | 399 | +717 | +1.24 | +1,209 | 59% | -72,856 | -182,745 | 0.44 | ₹177,231 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 1 | 275 | +314 | +1.18 | +404 | 49% | -13,081 | -50,270 | 0.43 | ₹5,623 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 3 | 304 | -392 | -1.14 | +472 | 40% | -17,736 | -191,773 | -0.46 | ₹6,759 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 5 | 235 | -371 | -0.98 | -831 | 70% | -21,436 | -125,072 | -0.32 | ₹18,115 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 1 | 394 | +103 | +0.98 | +163 | 74% | -8,457 | -28,113 | 0.33 | ₹8,514 |
| **NO EDGE** | iron_fly | NIFTY | 5 | 292 | -366 | -0.89 | -567 | 42% | -13,297 | -165,088 | -0.34 | ₹8,588 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 1 | 399 | -98 | -0.88 | -147 | 74% | -10,303 | -51,727 | -0.28 | ₹8,358 |
| **NO EDGE** | iron_fly | NIFTY | 3 | 399 | -229 | -0.84 | -84 | 42% | -17,736 | -163,097 | -0.30 | ₹7,016 |
| **NO EDGE** | iron_fly | BANKNIFTY | 1 | 328 | +186 | +0.78 | +391 | 48% | -13,081 | -83,097 | 0.27 | ₹5,629 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 5 | 292 | -177 | -0.71 | -4 | 72% | -14,825 | -133,840 | -0.23 | ₹12,779 |
| **NO EDGE** | short_straddle | NIFTY | 5 | 292 | +524 | +0.71 | +974 | 59% | -54,202 | -190,289 | 0.23 | ₹177,654 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 5 | 199 | +674 | +0.67 | +1,955 | 59% | -54,202 | -154,232 | 0.24 | ₹181,966 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 3 | 399 | -116 | -0.65 | +430 | 72% | -27,113 | -135,529 | -0.22 | ₹10,637 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 1 | 328 | +97 | +0.60 | +2 | 76% | -19,316 | -36,921 | 0.21 | ₹10,159 |
| **NO EDGE** | iron_fly | BANKNIFTY | 5 | 237 | -292 | -0.60 | -1,078 | 43% | -16,232 | -152,730 | -0.19 | ₹11,500 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 5 | 292 | +181 | +0.58 | -625 | 78% | -22,104 | -87,439 | 0.22 | ₹16,135 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 5 | 199 | -282 | -0.54 | -149 | 41% | -13,297 | -125,049 | -0.21 | ₹8,492 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 5 | 292 | +100 | +0.41 | -121 | 70% | -18,637 | -74,061 | 0.13 | ₹15,450 |
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 5 | 236 | +283 | +0.36 | -97 | 72% | -99,059 | -131,040 | 0.11 | ₹202,376 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 3 | 304 | +255 | +0.36 | +1,397 | 57% | -72,856 | -185,658 | 0.14 | ₹179,892 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 5 | 163 | +457 | +0.32 | +302 | 60% | -112,188 | -177,374 | 0.10 | ₹202,376 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 3 | 399 | +34 | +0.17 | -346 | 78% | -20,555 | -76,496 | 0.06 | ₹13,654 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 5 | 236 | +44 | +0.11 | -1,580 | 76% | -26,760 | -132,315 | 0.04 | ₹19,915 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 5 | 163 | +67 | +0.10 | -1,061 | 44% | -16,232 | -100,468 | 0.04 | ₹11,124 |
| **NO EDGE** | short_straddle | BANKNIFTY | 5 | 237 | +73 | +0.07 | -651 | 59% | -112,188 | -192,506 | 0.02 | ₹202,376 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 5 | 237 | -16 | -0.04 | +623 | 75% | -21,533 | -74,441 | -0.01 | ₹17,129 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 3 | 398 | +3 | +0.02 | +86 | 68% | -14,735 | -85,145 | 0.01 | ₹13,491 |

### Scorecards: the strongest results through every gate

DSR counts all 40 strategy tests as trials. Capital = the margin or max loss above; ruin is a bootstrap of the trade sequence over as many expiries as were tested.

**short_strangle_20d · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 328 · 82% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,074 |
| 1 edge | avg win / avg loss | ₹3,147 / ₹-8,186 |
| 1 edge | profit factor · SQN | 1.72 · 3.03 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.09 · 1.23 · 1.12 |
| 2 risk | Omega(0) | 1.72 |
| 2 tail | skew · excess kurtosis | -4.79 · 30.54 |
| 2 tail | VaR 95 / 99 per trade | ₹8,150 / ₹24,519 |
| 2 tail | CVaR 95 / 99 per trade | ₹20,187 / ₹42,117 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹11,501 / ₹26,799 |
| 2 drawdown | max DD | ₹-50,684 (-20.8%) |
| 2 drawdown | longest under water · recovery from max DD | 30 · 9 trades |
| 2 drawdown | Ulcer Index | 3.87 |
| 3 friction | slippage break-even per trade | ₹+1,074 (+9.7 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.15 → 0.97 · 0.84 |
| 5 robustness | PSR · DSR (40 trials) | 0.983 · 0.722 |
| ruin | P(−50%) · P(ruin) over 328 trades | 2.3% · 0.1% |

Flags: negative skew -4.79: small frequent gains, rare large losses; fat tails: excess kurtosis 30.5.


**short_straddle_ivrv · BANKNIFTY · k=1** — fails: N ≥ 300, DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 275 · 66% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,760 |
| 1 edge | avg win / avg loss | ₹6,388 / ₹-7,151 |
| 1 edge | profit factor · SQN | 1.72 · 3.19 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.15 · 1.53 · 1.09 |
| 2 risk | Omega(0) | 1.72 |
| 2 tail | skew · excess kurtosis | -2.12 · 11.66 |
| 2 tail | VaR 95 / 99 per trade | ₹12,409 / ₹28,771 |
| 2 tail | CVaR 95 / 99 per trade | ₹23,737 / ₹46,473 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹15,902 / ₹43,260 |
| 2 drawdown | max DD | ₹-82,642 (-29.3%) |
| 2 drawdown | longest under water · recovery from max DD | 41 · 18 trades |
| 2 drawdown | Ulcer Index | 6.05 |
| 3 friction | slippage break-even per trade | ₹+1,760 (+15.7 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.15 → 1.13 · 0.98 |
| 5 robustness | PSR · DSR (40 trials) | 0.995 · 0.789 |
| ruin | P(−50%) · P(ruin) over 275 trades | 2.7% · 0.1% |

Flags: negative skew -2.12: small frequent gains, rare large losses; fat tails: excess kurtosis 11.7.


**short_straddle · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 328 · 64% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,495 |
| 1 edge | avg win / avg loss | ₹6,376 / ₹-7,192 |
| 1 edge | profit factor · SQN | 1.58 · 2.87 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.03 · 1.34 · 1.13 |
| 2 risk | Omega(0) | 1.58 |
| 2 tail | skew · excess kurtosis | -2.23 · 11.24 |
| 2 tail | VaR 95 / 99 per trade | ₹13,017 / ₹29,081 |
| 2 tail | CVaR 95 / 99 per trade | ₹25,510 / ₹47,596 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹16,956 / ₹42,944 |
| 2 drawdown | max DD | ₹-78,078 (-28.7%) |
| 2 drawdown | longest under water · recovery from max DD | 63 · 22 trades |
| 2 drawdown | Ulcer Index | 6.72 |
| 3 friction | slippage break-even per trade | ₹+1,495 (+13.5 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.02 → 1.05 · 1.03 |
| 5 robustness | PSR · DSR (40 trials) | 0.992 · 0.716 |
| ruin | P(−50%) · P(ruin) over 328 trades | 5.4% · 0.3% |

Flags: negative skew -2.23: small frequent gains, rare large losses; fat tails: excess kurtosis 11.2.


### Parameter stability (every delta target and the wing ±10%)

| strategy | index | k | base ₹/lot | −10% | +10% | verdict |
|---|---|---:|---:|---:|---:|---|
| short_strangle_20d | BANKNIFTY | 1 | +1,074 | +939 | +1,154 | stable |
| short_straddle_ivrv | BANKNIFTY | 1 | +1,760 | — | — | no parameters to perturb (ATM strikes) |
| short_straddle | BANKNIFTY | 1 | +1,495 | — | — | no parameters to perturb (ATM strikes) |

### Futures term structure (near and next month, from the bhavcopy)

| index | days | carry now | carry median | roll yield median | backwardation days |
|---|---:|---:|---:|---:|---:|
| NIFTY | 1,758 | -3.87% | 5.07% | 4.99% | 11.7% |
| BANKNIFTY | 1,760 | 4.39% | 6.07% | 4.89% | 9.6% |

Fair carry ≈ r − q = 5.3%: carry well above it means longs pay up for leverage; below, selling pressure in futures.

### The volatility surface's moving parts (PCA of daily IV changes, 15–45 day expiry)

- **NIFTY** (773 days): PC1 71% · PC2 11% · PC3 10% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).
- **BANKNIFTY** (1,169 days): PC1 74% · PC2 8% · PC3 6% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).

India VIX 14.06: IV rank 26%, IV percentile 67% over the last year.


## 2. Positioning (participant-wise OI)

Signals known after the close, traded from the next open. Effect in basis points of the index per trade; the cost hurdle is one lot of a 0.35Δ option in and out.

| verdict | id | index | hypothesis | n | effect bps | t | p | rolling validation bps |
|---|---|---|---|---:|---:|---:|---:|---:|
| **NO EDGE** | P1 | NIFTY | FII index-futures net change → next session, open→close | 1,922 | +3.5 | +1.64 | 0.102 | -2.4 |
| **NO EDGE** | P2 | NIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 208 | -22.8 | -1.61 | 0.110 | +23.4 |
| **NO EDGE** | P1 | BANKNIFTY | FII index-futures net change → next session, open→close | 1,922 | +4.2 | +1.41 | 0.160 | -3.5 |
| **NO EDGE** | P5 | NIFTY | FII futures net 5-day change → next 5 sessions | 383 | -11.7 | -1.12 | 0.265 | -12.9 |
| **NO EDGE** | P3 | NIFTY | Client index-futures net change, contrarian → next session | 1,922 | +1.8 | +1.04 | 0.301 | -2.3 |
| **NO EDGE** | P2 | BANKNIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 208 | -20.9 | -1.01 | 0.315 | +52.4 |
| **NO EDGE** | P5 | BANKNIFTY | FII futures net 5-day change → next 5 sessions | 383 | -13.0 | -0.82 | 0.411 | -10.2 |
| **NO EDGE** | P3 | BANKNIFTY | Client index-futures net change, contrarian → next session | 1,922 | +1.9 | +0.75 | 0.453 | -4.8 |
| **NO EDGE** | P4 | NIFTY | FII index-options net (calls − puts) change → next session | 1,922 | +1.0 | +0.47 | 0.642 | -2.8 |
| **NO EDGE** | P4 | BANKNIFTY | FII index-options net (calls − puts) change → next session | 1,922 | +0.8 | +0.31 | 0.756 | -4.5 |

## 3. When does buying options pay? (the ATM straddle, real prices)

The nearest expiry's ATM straddle, bought and sold at bhavcopy prices with a half-spread and a tick each way on each leg (and fees). **Intraday**: bought at the opening prints at the strike nearest the index's open, sold at the close: what a buyer who squares off by the close lives through. **Overnight**: bought at the close, sold at the next close. P&L is on the premium paid. Move ratio: the index's |move| over the span against the move the straddle's own IV priced for a session (IV/√252·√(2/π)); the intraday span leaves out the overnight gap, so read it across rows, not against 1. FDR within each index × horizon × grouping; a verdict needs the newest third to keep the sign.

- **BANKNIFTY intraday**: 1,921 sessions 2019-01-01 → 2026-10-16; mean -5.7% on the premium, 29% of sessions profitable, median premium 1.64% of the index.
- **BANKNIFTY overnight**: 1,588 sessions 2019-01-01 → 2026-10-15; mean -5.9% on the premium, 28% of sessions profitable, median premium 1.58% of the index.
- **NIFTY intraday**: 1,920 sessions 2019-01-02 → 2026-10-16; mean -6.1% on the premium, 31% of sessions profitable, median premium 1.06% of the index.
- **NIFTY overnight**: 1,515 sessions 2019-01-02 → 2026-10-15; mean -5.8% on the premium, 31% of sessions profitable, median premium 1.00% of the index.

| verdict | index | horizon | by | group | n | mean | median | t | win | move ratio | realised > implied | discovery | validation |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 0 (expiry day) | 331 | -19.6% | -34.5% | -5.61 | 31% | 0.29× | 5% | -19.6% | -19.7% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 1 | 331 | -4.1% | -16.7% | -2.24 | 29% | 0.41× | 17% | -6.3% | +0.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 2 | 330 | -5.7% | -10.5% | -4.52 | 24% | 0.44× | 12% | -5.6% | -5.8% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 3 | 323 | +0.4% | -7.0% | +0.33 | 34% | 0.59× | 25% | +2.1% | -3.0% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 4–5 | 276 | -1.7% | -6.1% | -1.16 | 30% | 0.55× | 26% | -1.0% | -3.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 6–10 | 117 | -3.3% | -4.6% | -5.02 | 26% | 0.61× | 22% | -2.9% | -3.9% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 11+ | 213 | -2.4% | -3.9% | -5.81 | 28% | 0.58× | 28% | -2.9% | -1.4% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Mon | 382 | -0.5% | -5.7% | -0.42 | 33% | 0.54× | 22% | +0.9% | -3.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Tue | 387 | -5.7% | -8.8% | -3.51 | 27% | 0.48× | 16% | -4.4% | -8.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Wed | 384 | -6.4% | -10.6% | -3.03 | 27% | 0.40× | 15% | -4.5% | -10.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Thu | 388 | -13.4% | -9.7% | -4.91 | 30% | 0.37× | 10% | -17.3% | -5.8% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Fri | 380 | -2.4% | -5.6% | -2.23 | 30% | 0.61× | 30% | -2.7% | -1.9% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 1 | 331 | -16.4% | -34.5% | -3.99 | 32% | 0.59× | 24% | -15.6% | -17.8% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 2 | 330 | -6.8% | -18.8% | -3.57 | 24% | 0.61× | 27% | -8.8% | -2.8% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 3 | 321 | -5.6% | -13.4% | -3.98 | 23% | 0.58× | 25% | -5.5% | -5.9% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 4–5 | 276 | +2.4% | -6.8% | +1.63 | 34% | 0.88× | 44% | +3.2% | +0.8% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 6–10 | 117 | -3.5% | -5.0% | -4.19 | 22% | 0.64× | 30% | -2.7% | -5.0% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 11+ | 213 | -1.0% | -2.6% | -1.85 | 32% | 0.71× | 33% | -1.7% | +0.4% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Mon | 380 | -7.4% | -11.5% | -4.88 | 23% | 0.55× | 24% | -6.8% | -8.7% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Tue | 370 | -7.9% | -11.2% | -3.44 | 25% | 0.61× | 24% | -9.9% | -3.9% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Wed | 319 | -12.9% | -9.6% | -3.60 | 30% | 0.60× | 25% | -16.5% | -5.7% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Thu | 141 | -1.4% | -4.2% | -1.29 | 35% | 0.86× | 42% | -1.7% | -0.9% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Fri | 378 | +1.7% | -6.3% | +1.27 | 32% | 0.85× | 41% | +2.2% | +0.5% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 0 (expiry day) | 403 | -13.8% | -29.6% | -4.39 | 32% | 0.31× | 5% | -14.4% | -12.4% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 1 | 403 | -7.3% | -14.5% | -4.75 | 27% | 0.46× | 13% | -5.4% | -11.0% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 2 | 402 | -4.8% | -9.9% | -4.43 | 32% | 0.47× | 16% | -4.8% | -4.8% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 3 | 395 | -2.2% | -8.6% | -1.98 | 32% | 0.52× | 22% | -0.8% | -4.8% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 4–5 | 295 | -1.3% | -6.9% | -1.00 | 34% | 0.55× | 29% | -1.4% | -1.3% |
| **NO EDGE** | NIFTY | intraday | weekday | Mon | 382 | -3.2% | -8.3% | -2.47 | 33% | 0.50× | 19% | -1.1% | -7.3% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Tue | 386 | -6.2% | -10.9% | -3.17 | 31% | 0.43× | 14% | -3.8% | -11.0% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Wed | 384 | -7.5% | -12.7% | -4.49 | 25% | 0.44× | 12% | -6.4% | -9.8% |
| **NO EDGE** | NIFTY | intraday | weekday | Thu | 388 | -11.0% | -20.3% | -3.59 | 31% | 0.33× | 7% | -13.5% | -5.9% |
| **NO EDGE** | NIFTY | intraday | weekday | Fri | 380 | -2.5% | -7.0% | -2.27 | 34% | 0.60× | 31% | -2.4% | -2.7% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 1 | 403 | -10.4% | -24.8% | -3.06 | 35% | 0.65× | 29% | -10.3% | -10.5% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 2 | 402 | -7.6% | -14.8% | -5.16 | 30% | 0.70× | 27% | -6.7% | -9.3% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 3 | 394 | -4.1% | -12.4% | -3.19 | 28% | 0.68× | 29% | -4.9% | -2.5% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 4–5 | 294 | +0.7% | -8.5% | +0.48 | 34% | 0.90× | 44% | +1.9% | -1.7% |
| **BUYERS LOSE** | NIFTY | overnight | weekday | Mon | 378 | -7.9% | -14.4% | -4.84 | 25% | 0.58× | 23% | -5.8% | -12.1% |
| **NO EDGE** | NIFTY | overnight | weekday | Tue | 331 | -8.7% | -14.5% | -4.24 | 28% | 0.63× | 25% | -10.2% | -5.7% |
| **NO EDGE** | NIFTY | overnight | weekday | Wed | 369 | -8.3% | -15.9% | -2.36 | 34% | 0.65× | 29% | -9.9% | -5.0% |
| **NO EDGE** | NIFTY | overnight | weekday | Thu | 60 | -1.0% | -6.5% | -0.33 | 35% | 0.87× | 43% | +0.1% | -3.1% |
| **NO EDGE** | NIFTY | overnight | weekday | Fri | 377 | +0.5% | -8.2% | +0.38 | 37% | 0.95× | 46% | +1.2% | -0.9% |
