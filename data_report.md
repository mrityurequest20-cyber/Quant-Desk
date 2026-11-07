# Warehouse research — real NSE option prices and positioning

Generated 2026-11-07 16:37 IST. Data: NSE F&O bhavcopy and participant-wise OI (the `warehouse` release), index closes from the bhavcopy or Yahoo. 12,649 option trades simulated.

## 1. The volatility premium, traded on real prices

Opened at the close k sessions before expiry at bhavcopy closing prices worsened by a half-spread and a tick, plus brokerage, STT, exchange, GST, stamp and exercise STT; held to cash settlement. ₹ figures are per lot at today's lot sizes (NIFTY 65, BANKNIFTY 30). Benjamini-Hochberg across all rows below.

**The rolling validation is re-inspected every week, so it is not an untouched holdout. A paper candidate still needs a cost-inclusive paper trial before real money.**

| verdict | strategy | index | k | trades | mean ₹/lot | t | rolling validation ₹/lot | win | worst ₹ | max DD ₹ | Sharpe | capital |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 1 | 329 | +1,082 | +3.32 | +929 | 82% | -50,684 | -50,684 | 1.10 | ₹195,720 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 1 | 276 | +1,759 | +3.23 | +1,695 | 66% | -60,499 | -82,642 | 1.14 | ₹195,720 |
| **NO EDGE** | short_straddle | BANKNIFTY | 1 | 329 | +1,494 | +2.92 | +1,560 | 64% | -60,499 | -78,078 | 1.03 | ₹195,720 |
| **NO EDGE** | short_strangle_20d | NIFTY | 1 | 404 | +588 | +2.58 | +619 | 77% | -39,441 | -41,312 | 0.87 | ₹191,385 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 1 | 331 | +798 | +2.39 | +1,050 | 61% | -44,840 | -53,950 | 0.79 | ₹191,385 |
| **NO EDGE** | iron_fly | NIFTY | 1 | 405 | -293 | -2.20 | -378 | 42% | -9,968 | -125,798 | -0.68 | ₹4,460 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 1 | 328 | +360 | +2.03 | +110 | 78% | -18,655 | -29,071 | 0.79 | ₹10,022 |
| **NO EDGE** | short_straddle | NIFTY | 1 | 405 | +587 | +1.94 | +735 | 61% | -44,840 | -64,612 | 0.62 | ₹191,385 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 1 | 329 | +280 | +1.61 | +300 | 80% | -32,893 | -46,728 | 0.58 | ₹9,579 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 1 | 331 | -206 | -1.35 | -214 | 41% | -8,908 | -82,889 | -0.43 | ₹4,313 |
| **NO EDGE** | short_strangle_20d | NIFTY | 3 | 402 | +517 | +1.34 | +277 | 73% | -60,362 | -83,749 | 0.46 | ₹185,725 |
| **NO EDGE** | short_strangle_20d | NIFTY | 5 | 294 | +557 | +1.24 | +1,085 | 73% | -45,687 | -73,726 | 0.37 | ₹177,448 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 3 | 305 | -416 | -1.21 | +373 | 40% | -17,736 | -191,773 | -0.48 | ₹6,784 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 1 | 276 | +301 | +1.14 | +332 | 49% | -13,081 | -50,270 | 0.41 | ₹5,622 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 5 | 236 | -418 | -1.09 | -1,017 | 70% | -21,436 | -136,629 | -0.35 | ₹18,103 |
| **NO EDGE** | iron_fly | NIFTY | 5 | 294 | -374 | -0.92 | -575 | 42% | -13,297 | -165,088 | -0.35 | ₹8,582 |
| **NO EDGE** | short_straddle | NIFTY | 3 | 402 | +538 | +0.88 | +597 | 58% | -72,856 | -182,745 | 0.32 | ₹185,725 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 1 | 402 | -98 | -0.88 | -138 | 74% | -10,303 | -52,657 | -0.28 | ₹8,379 |
| **NO EDGE** | iron_fly | NIFTY | 3 | 402 | -238 | -0.88 | -127 | 42% | -17,736 | -163,097 | -0.31 | ₹7,031 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 5 | 294 | -210 | -0.85 | -35 | 71% | -14,825 | -133,840 | -0.27 | ₹12,777 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 3 | 402 | -147 | -0.79 | +310 | 72% | -27,113 | -135,529 | -0.27 | ₹10,654 |
| **NO EDGE** | iron_fly | BANKNIFTY | 1 | 329 | +175 | +0.74 | +395 | 48% | -13,081 | -83,097 | 0.26 | ₹5,628 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 1 | 397 | +77 | +0.71 | +80 | 74% | -8,457 | -28,113 | 0.24 | ₹8,504 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 1 | 394 | +77 | +0.71 | +207 | 76% | -13,320 | -30,378 | 0.25 | ₹7,904 |
| **NO EDGE** | iron_fly | BANKNIFTY | 5 | 238 | -326 | -0.67 | -1,171 | 43% | -16,232 | -159,536 | -0.21 | ₹11,480 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 5 | 294 | +202 | +0.65 | -609 | 78% | -22,104 | -87,439 | 0.25 | ₹16,118 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 5 | 200 | -323 | -0.61 | -192 | 40% | -13,297 | -125,049 | -0.24 | ₹8,483 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 1 | 329 | +92 | +0.57 | +14 | 76% | -19,316 | -36,921 | 0.20 | ₹10,159 |
| **NO EDGE** | short_straddle | NIFTY | 5 | 294 | +412 | +0.55 | +637 | 59% | -54,202 | -190,289 | 0.18 | ₹177,448 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 5 | 200 | +451 | +0.43 | +1,295 | 58% | -54,202 | -154,232 | 0.16 | ₹177,448 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 5 | 294 | +81 | +0.33 | -173 | 69% | -18,637 | -74,061 | 0.11 | ₹15,439 |
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 5 | 237 | +248 | +0.31 | -279 | 72% | -99,059 | -131,040 | 0.10 | ₹199,757 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 3 | 402 | +58 | +0.28 | -296 | 78% | -20,555 | -76,496 | 0.10 | ₹13,659 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 5 | 164 | +345 | +0.24 | -306 | 59% | -112,188 | -177,374 | 0.08 | ₹199,757 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 3 | 401 | -24 | -0.13 | -24 | 68% | -14,735 | -85,145 | -0.05 | ₹13,504 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 3 | 305 | +71 | +0.10 | +774 | 57% | -72,856 | -185,658 | 0.04 | ₹185,725 |
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
| NIFTY | 1,771 | 0.18% | 5.06% | 5.00% | 11.9% |
| BANKNIFTY | 1,773 | -3.88% | 6.06% | 4.91% | 9.6% |

Fair carry ≈ r − q = 5.3%: carry well above it means longs pay up for leverage; below, selling pressure in futures.

### The volatility surface's moving parts (PCA of daily IV changes, 15–45 day expiry)

- **NIFTY** (782 days): PC1 71% · PC2 11% · PC3 10% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).
- **BANKNIFTY** (1,183 days): PC1 74% · PC2 8% · PC3 6% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).

India VIX 17.47: IV rank 44%, IV percentile 81% over the last year.


## 2. Positioning (participant-wise OI)

Signals known after the close, traded from the next open. Effect in basis points of the index per trade; the cost hurdle is one lot of a 0.35Δ option in and out.

| verdict | id | index | hypothesis | n | effect bps | t | p | rolling validation bps |
|---|---|---|---|---:|---:|---:|---:|---:|
| **NO EDGE** | P1 | NIFTY | FII index-futures net change → next session, open→close | 1,936 | +3.7 | +1.72 | 0.085 | -1.6 |
| **NO EDGE** | P2 | NIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 209 | -22.7 | -1.60 | 0.110 | +26.4 |
| **NO EDGE** | P1 | BANKNIFTY | FII index-futures net change → next session, open→close | 1,936 | +4.5 | +1.50 | 0.134 | -2.6 |
| **NO EDGE** | P3 | NIFTY | Client index-futures net change, contrarian → next session | 1,936 | +2.2 | +1.25 | 0.212 | -1.2 |
| **NO EDGE** | P2 | BANKNIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 209 | -21.2 | -1.03 | 0.304 | +52.4 |
| **NO EDGE** | P5 | NIFTY | FII futures net 5-day change → next 5 sessions | 386 | -10.1 | -0.95 | 0.340 | -9.6 |
| **NO EDGE** | P3 | BANKNIFTY | Client index-futures net change, contrarian → next session | 1,936 | +2.1 | +0.84 | 0.404 | -4.2 |
| **NO EDGE** | P5 | BANKNIFTY | FII futures net 5-day change → next 5 sessions | 386 | -12.5 | -0.80 | 0.426 | -10.8 |
| **NO EDGE** | P4 | NIFTY | FII index-options net (calls − puts) change → next session | 1,936 | +1.2 | +0.57 | 0.567 | -1.8 |
| **NO EDGE** | P4 | BANKNIFTY | FII index-options net (calls − puts) change → next session | 1,936 | +0.9 | +0.33 | 0.741 | -4.3 |

## 3. When does buying options pay? (the ATM straddle, real prices)

The nearest expiry's ATM straddle, bought and sold at bhavcopy prices with a half-spread and a tick each way on each leg (and fees). **Intraday**: bought at the opening prints at the strike nearest the index's open, sold at the close: what a buyer who squares off by the close lives through. **Overnight**: bought at the close, sold at the next close. P&L is on the premium paid. Move ratio: the index's |move| over the span against the move the straddle's own IV priced for a session (IV/√252·√(2/π)); the intraday span leaves out the overnight gap, so read it across rows, not against 1. FDR within each index × horizon × grouping; a verdict needs the newest third to keep the sign.

- **BANKNIFTY intraday**: 1,935 sessions 2019-01-01 → 2026-11-06; mean -5.7% on the premium, 29% of sessions profitable, median premium 1.64% of the index.
- **BANKNIFTY overnight**: 1,601 sessions 2019-01-01 → 2026-11-05; mean -5.9% on the premium, 28% of sessions profitable, median premium 1.59% of the index.
- **NIFTY intraday**: 1,934 sessions 2019-01-02 → 2026-11-06; mean -6.0% on the premium, 31% of sessions profitable, median premium 1.06% of the index.
- **NIFTY overnight**: 1,526 sessions 2019-01-02 → 2026-11-05; mean -5.6% on the premium, 31% of sessions profitable, median premium 1.00% of the index.

| verdict | index | horizon | by | group | n | mean | median | t | win | move ratio | realised > implied | discovery | validation |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 0 (expiry day) | 332 | -19.6% | -34.5% | -5.61 | 32% | 0.29× | 5% | -19.8% | -19.1% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 1 | 332 | -4.2% | -16.9% | -2.30 | 29% | 0.41× | 17% | -6.3% | -0.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 2 | 331 | -5.6% | -10.2% | -4.45 | 24% | 0.45× | 13% | -5.6% | -5.5% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 3 | 324 | +0.4% | -6.9% | +0.32 | 34% | 0.59× | 25% | +2.4% | -3.5% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 4–5 | 278 | -1.7% | -6.1% | -1.15 | 31% | 0.54× | 26% | -1.1% | -3.0% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 6–10 | 119 | -3.4% | -5.0% | -5.22 | 26% | 0.63× | 23% | -3.0% | -4.2% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 11+ | 219 | -2.4% | -3.7% | -5.94 | 28% | 0.58× | 28% | -3.0% | -1.2% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Mon | 385 | -0.6% | -5.7% | -0.51 | 33% | 0.53× | 22% | +0.7% | -3.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Tue | 389 | -5.8% | -8.8% | -3.56 | 27% | 0.48× | 15% | -4.5% | -8.4% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Wed | 387 | -6.3% | -10.5% | -3.03 | 27% | 0.40× | 15% | -4.2% | -10.6% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Thu | 391 | -13.4% | -9.3% | -4.91 | 30% | 0.37× | 10% | -17.4% | -5.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Fri | 383 | -2.3% | -5.6% | -2.13 | 30% | 0.61× | 30% | -2.8% | -1.4% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 1 | 332 | -16.3% | -34.5% | -3.98 | 32% | 0.59× | 25% | -15.7% | -17.6% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 2 | 331 | -6.7% | -18.8% | -3.51 | 24% | 0.61× | 27% | -8.8% | -2.6% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 3 | 322 | -5.6% | -13.3% | -3.95 | 24% | 0.58× | 25% | -5.5% | -5.6% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 4–5 | 278 | +2.4% | -6.8% | +1.61 | 34% | 0.88× | 44% | +3.1% | +0.8% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 6–10 | 119 | -3.6% | -5.0% | -4.49 | 21% | 0.64× | 30% | -2.8% | -5.2% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 11+ | 219 | -1.0% | -2.6% | -1.91 | 32% | 0.72× | 33% | -1.8% | +0.4% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Mon | 383 | -7.5% | -11.4% | -4.95 | 23% | 0.56× | 25% | -7.0% | -8.5% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Tue | 371 | -7.9% | -11.2% | -3.44 | 25% | 0.61× | 24% | -8.1% | -7.4% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Wed | 322 | -12.6% | -9.5% | -3.54 | 30% | 0.60× | 26% | -16.5% | -5.0% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Thu | 144 | -1.1% | -4.2% | -0.96 | 35% | 0.86× | 42% | -1.7% | +0.2% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Fri | 381 | +1.5% | -6.3% | +1.17 | 32% | 0.85× | 41% | +2.0% | +0.6% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 0 (expiry day) | 406 | -13.6% | -29.5% | -4.34 | 32% | 0.31× | 5% | -14.3% | -12.3% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 1 | 406 | -7.3% | -14.4% | -4.87 | 27% | 0.47× | 13% | -5.5% | -11.0% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 2 | 405 | -4.7% | -9.8% | -4.34 | 32% | 0.48× | 17% | -4.8% | -4.3% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 3 | 398 | -2.2% | -8.6% | -2.02 | 32% | 0.52× | 22% | -0.9% | -4.8% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 4–5 | 297 | -1.3% | -6.9% | -0.96 | 34% | 0.55× | 29% | -1.3% | -1.2% |
| **NO EDGE** | NIFTY | intraday | weekday | Mon | 385 | -3.1% | -8.3% | -2.39 | 33% | 0.50× | 18% | -1.1% | -7.0% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Tue | 388 | -6.4% | -11.0% | -3.30 | 31% | 0.43× | 14% | -3.9% | -11.3% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Wed | 387 | -7.4% | -12.7% | -4.47 | 25% | 0.44× | 13% | -6.1% | -10.1% |
| **NO EDGE** | NIFTY | intraday | weekday | Thu | 391 | -10.9% | -20.0% | -3.59 | 31% | 0.33× | 8% | -13.9% | -4.9% |
| **NO EDGE** | NIFTY | intraday | weekday | Fri | 383 | -2.4% | -7.0% | -2.13 | 34% | 0.61× | 31% | -2.5% | -2.1% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 1 | 406 | -10.0% | -24.8% | -2.97 | 36% | 0.65× | 29% | -10.2% | -9.8% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 2 | 405 | -7.4% | -14.5% | -5.01 | 30% | 0.70× | 27% | -6.9% | -8.4% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 3 | 397 | -4.0% | -12.4% | -3.11 | 28% | 0.68× | 29% | -4.9% | -2.2% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 4–5 | 296 | +0.7% | -8.5% | +0.47 | 34% | 0.90× | 44% | +1.8% | -1.6% |
| **BUYERS LOSE** | NIFTY | overnight | weekday | Mon | 380 | -7.9% | -14.4% | -4.87 | 25% | 0.58× | 23% | -5.9% | -11.9% |
| **NO EDGE** | NIFTY | overnight | weekday | Tue | 331 | -8.7% | -14.5% | -4.24 | 28% | 0.63× | 25% | -10.2% | -5.7% |
| **NO EDGE** | NIFTY | overnight | weekday | Wed | 372 | -8.0% | -15.5% | -2.28 | 34% | 0.65× | 29% | -10.2% | -3.6% |
| **NO EDGE** | NIFTY | overnight | weekday | Thu | 63 | -0.2% | -6.4% | -0.06 | 35% | 0.86× | 43% | +1.6% | -3.8% |
| **NO EDGE** | NIFTY | overnight | weekday | Fri | 380 | +0.7% | -8.1% | +0.46 | 37% | 0.95× | 46% | +1.1% | -0.2% |
