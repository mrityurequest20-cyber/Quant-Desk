# Warehouse research — real NSE option prices and positioning

Generated 2026-11-28 18:33 IST. Data: NSE F&O bhavcopy and participant-wise OI (the `warehouse` release), index closes from the bhavcopy or Yahoo. 12,729 option trades simulated.

## 1. The volatility premium, traded on real prices

Opened at the close k sessions before expiry at bhavcopy closing prices worsened by a half-spread and a tick, plus brokerage, STT, exchange, GST, stamp and exercise STT; held to cash settlement. ₹ figures are per lot at today's lot sizes (NIFTY 65, BANKNIFTY 30). Benjamini-Hochberg across all rows below.

**The rolling validation is re-inspected every week, so it is not an untouched holdout. A paper candidate still needs a cost-inclusive paper trial before real money.**

| verdict | strategy | index | k | trades | mean ₹/lot | t | rolling validation ₹/lot | win | worst ₹ | max DD ₹ | Sharpe | capital |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 1 | 330 | +998 | +3.02 | +658 | 82% | -50,684 | -50,684 | 0.98 | ₹232,687 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 1 | 277 | +1,624 | +2.95 | +1,295 | 66% | -60,499 | -82,642 | 1.02 | ₹232,687 |
| **NO EDGE** | short_strangle_20d | NIFTY | 1 | 407 | +605 | +2.70 | +651 | 77% | -39,441 | -41,312 | 0.89 | ₹201,899 |
| **NO EDGE** | short_straddle | BANKNIFTY | 1 | 330 | +1,382 | +2.67 | +1,147 | 64% | -60,499 | -78,078 | 0.93 | ₹232,687 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 1 | 333 | +848 | +2.61 | +1,167 | 61% | -44,840 | -53,950 | 0.84 | ₹201,245 |
| **NO EDGE** | short_straddle | NIFTY | 1 | 408 | +636 | +2.15 | +913 | 61% | -44,840 | -64,612 | 0.67 | ₹201,899 |
| **NO EDGE** | iron_fly | NIFTY | 1 | 408 | -268 | -2.03 | -267 | 42% | -9,968 | -122,894 | -0.61 | ₹4,548 |
| **NO EDGE** | short_strangle_20d | NIFTY | 3 | 405 | +678 | +1.97 | +853 | 74% | -60,362 | -75,760 | 0.63 | ₹197,727 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 1 | 329 | +323 | +1.82 | -8 | 78% | -18,655 | -29,071 | 0.69 | ₹10,035 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 1 | 330 | +287 | +1.65 | +309 | 80% | -32,893 | -46,728 | 0.59 | ₹9,601 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 1 | 397 | +135 | +1.40 | +409 | 76% | -8,529 | -25,897 | 0.46 | ₹7,922 |
| **NO EDGE** | short_straddle | NIFTY | 3 | 405 | +750 | +1.31 | +1,375 | 59% | -72,856 | -182,745 | 0.45 | ₹197,727 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 1 | 405 | -128 | -1.14 | -242 | 74% | -10,587 | -57,748 | -0.36 | ₹8,433 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 3 | 307 | -373 | -1.09 | +499 | 41% | -17,736 | -191,773 | -0.43 | ₹6,833 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 1 | 333 | -166 | -1.09 | -94 | 42% | -8,908 | -82,889 | -0.34 | ₹4,333 |
| **NO EDGE** | iron_condor_20_10 | BANKNIFTY | 5 | 237 | -395 | -1.05 | -1,013 | 70% | -21,436 | -136,629 | -0.33 | ₹18,178 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 1 | 277 | +274 | +1.04 | +251 | 49% | -13,081 | -50,270 | 0.37 | ₹5,630 |
| **NO EDGE** | iron_fly | NIFTY | 5 | 296 | -384 | -0.95 | -529 | 42% | -13,297 | -163,771 | -0.36 | ₹8,575 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 5 | 296 | -226 | -0.90 | +12 | 71% | -14,825 | -133,840 | -0.29 | ₹12,808 |
| **NO EDGE** | short_strangle_20d | NIFTY | 5 | 296 | +419 | +0.84 | +727 | 73% | -47,925 | -91,982 | 0.27 | ₹195,348 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 1 | 400 | +82 | +0.78 | +122 | 74% | -10,818 | -28,113 | 0.25 | ₹8,544 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 5 | 296 | +236 | +0.76 | -525 | 78% | -22,104 | -87,064 | 0.29 | ₹16,259 |
| **NO EDGE** | bear_call_30_15 | NIFTY | 3 | 405 | -133 | -0.74 | +343 | 72% | -27,113 | -135,529 | -0.24 | ₹10,691 |
| **NO EDGE** | iron_fly | BANKNIFTY | 5 | 239 | -355 | -0.72 | -1,155 | 43% | -16,232 | -166,849 | -0.23 | ₹11,459 |
| **NO EDGE** | iron_fly | NIFTY | 3 | 405 | -185 | -0.68 | +108 | 43% | -17,736 | -163,097 | -0.24 | ₹7,054 |
| **NO EDGE** | iron_fly_ivrv | NIFTY | 5 | 202 | -338 | -0.65 | -260 | 41% | -13,297 | -125,049 | -0.26 | ₹8,469 |
| **NO EDGE** | iron_fly | BANKNIFTY | 1 | 330 | +153 | +0.65 | +272 | 48% | -13,081 | -83,097 | 0.22 | ₹5,636 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 3 | 307 | +307 | +0.43 | +1,436 | 57% | -72,856 | -185,658 | 0.16 | ₹197,727 |
| **NO EDGE** | bull_put_30_15 | NIFTY | 3 | 405 | +80 | +0.39 | -178 | 79% | -20,555 | -76,183 | 0.14 | ₹13,657 |
| **NO EDGE** | short_strangle_20d | BANKNIFTY | 5 | 238 | +287 | +0.37 | -158 | 72% | -99,059 | -131,040 | 0.11 | ₹221,673 |
| **NO EDGE** | short_straddle | NIFTY | 5 | 296 | +268 | +0.35 | +367 | 59% | -56,699 | -190,289 | 0.11 | ₹195,348 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 1 | 330 | +50 | +0.30 | -126 | 75% | -19,316 | -41,725 | 0.10 | ₹10,166 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 5 | 296 | +63 | +0.26 | -153 | 69% | -18,637 | -74,061 | 0.08 | ₹15,465 |
| **NO EDGE** | short_straddle_ivrv | BANKNIFTY | 5 | 164 | +345 | +0.24 | -306 | 59% | -112,188 | -177,374 | 0.08 | ₹199,757 |
| **NO EDGE** | short_straddle_ivrv | NIFTY | 5 | 202 | +239 | +0.21 | +554 | 59% | -56,699 | -199,824 | 0.08 | ₹195,348 |
| **NO EDGE** | iron_condor_20_10 | NIFTY | 3 | 404 | +17 | +0.09 | +135 | 68% | -14,735 | -85,145 | 0.03 | ₹13,532 |
| **NO EDGE** | bear_call_30_15 | BANKNIFTY | 5 | 239 | -23 | -0.06 | +550 | 74% | -21,533 | -74,441 | -0.02 | ₹17,277 |
| **NO EDGE** | iron_fly_ivrv | BANKNIFTY | 5 | 164 | +15 | +0.02 | -1,377 | 43% | -16,232 | -100,468 | 0.01 | ₹11,103 |
| **NO EDGE** | bull_put_30_15 | BANKNIFTY | 5 | 238 | -8 | -0.02 | -1,597 | 76% | -26,760 | -149,666 | -0.01 | ₹19,885 |
| **NO EDGE** | short_straddle | BANKNIFTY | 5 | 239 | +11 | +0.01 | -814 | 59% | -112,188 | -192,506 | 0.00 | ₹221,673 |

### Scorecards: the strongest results through every gate

DSR counts all 40 strategy tests as trials. Capital = the margin or max loss above; ruin is a bootstrap of the trade sequence over as many expiries as were tested.

**short_strangle_20d · BANKNIFTY · k=1** — fails: DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 330 · 82% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+998 |
| 1 edge | avg win / avg loss | ₹3,150 / ₹-8,492 |
| 1 edge | profit factor · SQN | 1.64 · 2.75 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 0.98 · 1.10 · 0.99 |
| 2 risk | Omega(0) | 1.64 |
| 2 tail | skew · excess kurtosis | -4.61 · 27.91 |
| 2 tail | VaR 95 / 99 per trade | ₹8,604 / ₹26,607 |
| 2 tail | CVaR 95 / 99 per trade | ₹21,274 / ₹42,290 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹12,121 / ₹26,849 |
| 2 drawdown | max DD | ₹-50,684 (-18.1%) |
| 2 drawdown | longest under water · recovery from max DD | 30 · 9 trades |
| 2 drawdown | Ulcer Index | 3.47 |
| 3 friction | slippage break-even per trade | ₹+998 (+9.0 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.16 → 0.63 · 0.55 |
| 5 robustness | PSR · DSR (40 trials) | 0.978 · 0.660 |
| ruin | P(−50%) · P(ruin) over 330 trades | 1.9% · 0.0% |

Flags: negative skew -4.61: small frequent gains, rare large losses; fat tails: excess kurtosis 27.9.


**short_straddle_ivrv · BANKNIFTY · k=1** — fails: N ≥ 300, DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 277 · 66% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+1,624 |
| 1 edge | avg win / avg loss | ₹6,360 / ₹-7,450 |
| 1 edge | profit factor · SQN | 1.64 · 2.88 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 1.02 · 1.34 · 0.95 |
| 2 risk | Omega(0) | 1.64 |
| 2 tail | skew · excess kurtosis | -2.14 · 10.92 |
| 2 tail | VaR 95 / 99 per trade | ₹12,430 / ₹30,768 |
| 2 tail | CVaR 95 / 99 per trade | ₹25,389 / ₹48,568 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹16,662 / ₹42,841 |
| 2 drawdown | max DD | ₹-82,642 (-25.9%) |
| 2 drawdown | longest under water · recovery from max DD | 41 · 18 trades |
| 2 drawdown | Ulcer Index | 5.41 |
| 3 friction | slippage break-even per trade | ₹+1,624 (+14.4 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 1.16 → 0.77 · 0.67 |
| 5 robustness | PSR · DSR (40 trials) | 0.991 · 0.714 |
| ruin | P(−50%) · P(ruin) over 277 trades | 2.4% · 0.1% |

Flags: negative skew -2.14: small frequent gains, rare large losses; fat tails: excess kurtosis 10.9.


**short_strangle_20d · NIFTY · k=1** — fails: profit factor > 1.5, DSR ≥ 0.95

| layer | metric | value |
|---|---|---:|
| 1 edge | N · win rate | 407 · 77% |
| 1 edge | expectancy (W·AvgWin − L·AvgLoss) | ₹+605 |
| 1 edge | avg win / avg loss | ₹2,407 / ₹-5,395 |
| 1 edge | profit factor · SQN | 1.49 · 2.50 |
| 2 risk | Sharpe · Sortino (annualised) · Calmar | 0.89 · 1.02 · 0.90 |
| 2 risk | Omega(0) | 1.49 |
| 2 tail | skew · excess kurtosis | -4.21 · 25.96 |
| 2 tail | VaR 95 / 99 per trade | ₹7,773 / ₹19,089 |
| 2 tail | CVaR 95 / 99 per trade | ₹15,456 / ₹29,694 |
| 2 tail | Cornish-Fisher VaR 95 / 99 | ₹9,082 / ₹22,892 |
| 2 drawdown | max DD | ₹-41,312 (-17.3%) |
| 2 drawdown | longest under water · recovery from max DD | 52 · 38 trades |
| 2 drawdown | Ulcer Index | 4.73 |
| 3 friction | slippage break-even per trade | ₹+605 (+5.2 bps of notional) |
| 5 robustness | Sharpe IS → OOS · OOS efficiency | 0.93 → 0.84 · 0.90 |
| 5 robustness | PSR · DSR (40 trials) | 0.975 · 0.596 |
| ruin | P(−50%) · P(ruin) over 407 trades | 1.5% · 0.1% |

Flags: negative skew -4.21: small frequent gains, rare large losses; fat tails: excess kurtosis 26.0.


### Parameter stability (every delta target and the wing ±10%)

| strategy | index | k | base ₹/lot | −10% | +10% | verdict |
|---|---|---:|---:|---:|---:|---|
| short_strangle_20d | BANKNIFTY | 1 | +998 | +870 | +1,076 | stable |
| short_straddle_ivrv | BANKNIFTY | 1 | +1,624 | — | — | no parameters to perturb (ATM strikes) |
| short_strangle_20d | NIFTY | 1 | +605 | +553 | +621 | stable |

### Futures term structure (near and next month, from the bhavcopy)

| index | days | carry now | carry median | roll yield median | backwardation days |
|---|---:|---:|---:|---:|---:|
| NIFTY | 1,787 | 4.10% | 5.04% | 5.02% | 11.9% |
| BANKNIFTY | 1,789 | 4.34% | 6.03% | 4.92% | 9.9% |

Fair carry ≈ r − q = 5.3%: carry well above it means longs pay up for leverage; below, selling pressure in futures.

### The volatility surface's moving parts (PCA of daily IV changes, 15–45 day expiry)

- **NIFTY** (794 days): PC1 71% · PC2 11% · PC3 10% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).
- **BANKNIFTY** (1,195 days): PC1 74% · PC2 8% · PC3 6% of the variance (read the loadings: PC1 ≈ level, PC2 ≈ skew, PC3 ≈ curvature).

India VIX 16.55: IV rank 39%, IV percentile 74% over the last year.


## 2. Positioning (participant-wise OI)

Signals known after the close, traded from the next open. Effect in basis points of the index per trade; the cost hurdle is one lot of a 0.35Δ option in and out.

| verdict | id | index | hypothesis | n | effect bps | t | p | rolling validation bps |
|---|---|---|---|---:|---:|---:|---:|---:|
| **NO EDGE** | P2 | NIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 214 | -26.9 | -2.03 | 0.043 | +12.7 |
| **NO EDGE** | P1 | NIFTY | FII index-futures net change → next session, open→close | 1,959 | +3.8 | +1.77 | 0.076 | -1.8 |
| **NO EDGE** | P1 | BANKNIFTY | FII index-futures net change → next session, open→close | 1,959 | +4.8 | +1.62 | 0.105 | -2.5 |
| **NO EDGE** | P2 | BANKNIFTY | FII long ratio at a 1-yr extreme → fade it over 5 sessions | 214 | -31.7 | -1.49 | 0.138 | +33.3 |
| **NO EDGE** | P5 | NIFTY | FII futures net 5-day change → next 5 sessions | 391 | +14.5 | +1.34 | 0.182 | +15.8 |
| **NO EDGE** | P5 | BANKNIFTY | FII futures net 5-day change → next 5 sessions | 391 | +15.0 | +1.02 | 0.308 | +19.2 |
| **NO EDGE** | P3 | NIFTY | Client index-futures net change, contrarian → next session | 1,959 | +1.6 | +0.93 | 0.354 | -1.7 |
| **NO EDGE** | P3 | BANKNIFTY | Client index-futures net change, contrarian → next session | 1,959 | +1.7 | +0.68 | 0.496 | -4.3 |
| **NO EDGE** | P4 | NIFTY | FII index-options net (calls − puts) change → next session | 1,959 | +0.8 | +0.39 | 0.695 | -2.4 |
| **NO EDGE** | P4 | BANKNIFTY | FII index-options net (calls − puts) change → next session | 1,959 | +0.9 | +0.32 | 0.751 | -4.2 |

## 3. When does buying options pay? (the ATM straddle, real prices)

The nearest expiry's ATM straddle, bought and sold at bhavcopy prices with a half-spread and a tick each way on each leg (and fees). **Intraday**: bought at the opening prints at the strike nearest the index's open, sold at the close: what a buyer who squares off by the close lives through. **Overnight**: bought at the close, sold at the next close. P&L is on the premium paid. Move ratio: the index's |move| over the span against the move the straddle's own IV priced for a session (IV/√252·√(2/π)); the intraday span leaves out the overnight gap, so read it across rows, not against 1. FDR within each index × horizon × grouping; a verdict needs the newest third to keep the sign.

- **BANKNIFTY intraday**: 1,948 sessions 2019-01-01 → 2026-11-27; mean -5.5% on the premium, 29% of sessions profitable, median premium 1.64% of the index.
- **BANKNIFTY overnight**: 1,616 sessions 2019-01-01 → 2026-11-26; mean -5.7% on the premium, 28% of sessions profitable, median premium 1.59% of the index.
- **NIFTY intraday**: 1,948 sessions 2019-01-02 → 2026-11-27; mean -6.0% on the premium, 31% of sessions profitable, median premium 1.07% of the index.
- **NIFTY overnight**: 1,540 sessions 2019-01-02 → 2026-11-26; mean -5.7% on the premium, 31% of sessions profitable, median premium 1.01% of the index.

| verdict | index | horizon | by | group | n | mean | median | t | win | move ratio | realised > implied | discovery | validation |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 0 (expiry day) | 333 | -18.8% | -34.5% | -5.32 | 32% | 0.29× | 5% | -19.8% | -16.8% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 1 | 333 | -3.8% | -16.7% | -2.05 | 29% | 0.41× | 17% | -6.4% | +1.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 2 | 332 | -5.4% | -10.1% | -4.20 | 25% | 0.45× | 13% | -5.7% | -4.7% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 3 | 324 | +0.3% | -7.0% | +0.25 | 33% | 0.59× | 25% | +2.4% | -3.8% |
| **NO EDGE** | BANKNIFTY | intraday | days to expiry | 4–5 | 278 | -1.7% | -6.1% | -1.16 | 31% | 0.56× | 27% | -1.1% | -3.1% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 6–10 | 121 | -3.5% | -5.0% | -5.36 | 26% | 0.63× | 22% | -3.1% | -4.3% |
| **BUYERS LOSE** | BANKNIFTY | intraday | days to expiry | 11+ | 227 | -2.2% | -3.5% | -5.25 | 29% | 0.58× | 29% | -2.8% | -1.2% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Mon | 388 | +0.1% | -5.7% | +0.08 | 33% | 0.56× | 22% | +0.6% | -1.0% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Tue | 390 | -5.8% | -8.8% | -3.56 | 27% | 0.48× | 16% | -4.8% | -7.7% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Wed | 390 | -6.3% | -10.4% | -3.04 | 27% | 0.40× | 15% | -4.6% | -9.8% |
| **BUYERS LOSE** | BANKNIFTY | intraday | weekday | Thu | 394 | -13.2% | -9.1% | -4.85 | 30% | 0.38× | 11% | -17.4% | -4.7% |
| **NO EDGE** | BANKNIFTY | intraday | weekday | Fri | 386 | -2.0% | -5.6% | -1.78 | 30% | 0.61× | 30% | -2.8% | -0.4% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 1 | 333 | -16.0% | -34.5% | -3.91 | 32% | 0.60× | 25% | -15.7% | -16.5% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 2 | 332 | -6.6% | -18.8% | -3.43 | 24% | 0.61× | 27% | -8.9% | -2.0% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 3 | 322 | -5.5% | -13.3% | -3.86 | 24% | 0.58× | 25% | -5.5% | -5.3% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 4–5 | 278 | +2.3% | -7.0% | +1.60 | 34% | 0.88× | 44% | +3.1% | +0.8% |
| **BUYERS LOSE** | BANKNIFTY | overnight | days to expiry | 6–10 | 122 | -3.5% | -5.3% | -4.51 | 22% | 0.67× | 32% | -2.3% | -6.0% |
| **NO EDGE** | BANKNIFTY | overnight | days to expiry | 11+ | 229 | -0.6% | -2.6% | -0.91 | 32% | 0.72× | 33% | -1.4% | +1.0% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Mon | 385 | -7.4% | -11.4% | -4.91 | 24% | 0.57× | 25% | -7.0% | -8.1% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Tue | 372 | -7.9% | -11.1% | -3.45 | 25% | 0.61× | 24% | -8.2% | -7.3% |
| **BUYERS LOSE** | BANKNIFTY | overnight | weekday | Wed | 325 | -12.5% | -9.1% | -3.51 | 30% | 0.60× | 26% | -15.9% | -5.7% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Thu | 147 | -0.6% | -4.2% | -0.42 | 35% | 0.88× | 42% | -1.7% | +1.8% |
| **NO EDGE** | BANKNIFTY | overnight | weekday | Fri | 384 | +1.9% | -6.1% | +1.43 | 32% | 0.85× | 41% | +2.2% | +1.3% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 0 (expiry day) | 409 | -13.3% | -29.4% | -4.26 | 32% | 0.31× | 5% | -14.1% | -11.8% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 1 | 408 | -7.2% | -14.6% | -4.79 | 27% | 0.47× | 13% | -5.7% | -10.3% |
| **BUYERS LOSE** | NIFTY | intraday | days to expiry | 2 | 407 | -4.5% | -9.8% | -4.11 | 32% | 0.48× | 17% | -4.9% | -3.7% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 3 | 401 | -2.2% | -8.5% | -2.03 | 32% | 0.52× | 22% | -0.9% | -4.7% |
| **NO EDGE** | NIFTY | intraday | days to expiry | 4–5 | 301 | -1.4% | -6.9% | -1.08 | 34% | 0.55× | 29% | -1.2% | -1.9% |
| **NO EDGE** | NIFTY | intraday | weekday | Mon | 388 | -2.8% | -8.3% | -2.08 | 33% | 0.50× | 19% | -1.3% | -5.8% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Tue | 389 | -6.4% | -11.0% | -3.33 | 31% | 0.43× | 14% | -4.0% | -11.2% |
| **BUYERS LOSE** | NIFTY | intraday | weekday | Wed | 390 | -7.4% | -12.6% | -4.47 | 26% | 0.44× | 13% | -5.5% | -11.0% |
| **NO EDGE** | NIFTY | intraday | weekday | Thu | 394 | -10.8% | -20.0% | -3.60 | 31% | 0.33× | 8% | -14.2% | -4.2% |
| **NO EDGE** | NIFTY | intraday | weekday | Fri | 386 | -2.2% | -6.9% | -1.95 | 35% | 0.61× | 31% | -2.6% | -1.4% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 1 | 409 | -10.2% | -24.8% | -3.04 | 36% | 0.65× | 29% | -10.2% | -10.1% |
| **BUYERS LOSE** | NIFTY | overnight | days to expiry | 2 | 408 | -7.6% | -14.6% | -5.30 | 29% | 0.70× | 27% | -7.0% | -8.8% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 3 | 400 | -3.8% | -12.4% | -2.89 | 28% | 0.69× | 30% | -4.9% | -1.4% |
| **NO EDGE** | NIFTY | overnight | days to expiry | 4–5 | 301 | +0.7% | -8.5% | +0.47 | 34% | 0.89× | 44% | +1.6% | -1.1% |
| **BUYERS LOSE** | NIFTY | overnight | weekday | Mon | 381 | -7.9% | -14.4% | -4.95 | 25% | 0.58× | 23% | -5.9% | -12.0% |
| **NO EDGE** | NIFTY | overnight | weekday | Tue | 331 | -8.7% | -14.5% | -4.24 | 28% | 0.63× | 25% | -10.2% | -5.7% |
| **NO EDGE** | NIFTY | overnight | weekday | Wed | 375 | -8.0% | -15.6% | -2.31 | 34% | 0.65× | 29% | -9.8% | -4.3% |
| **NO EDGE** | NIFTY | overnight | weekday | Thu | 66 | +0.1% | -6.3% | +0.04 | 36% | 0.87× | 44% | +1.1% | -1.8% |
| **NO EDGE** | NIFTY | overnight | weekday | Fri | 384 | +0.8% | -8.1% | +0.57 | 38% | 0.94× | 46% | +1.0% | +0.5% |
