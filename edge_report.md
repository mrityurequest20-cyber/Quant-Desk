# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-10-10 16:08 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 09-Oct-2026 (4,677 bars)
- daily BANKNIFTY: 17-Sep-2007 → 09-Oct-2026 (4,692 bars)
- daily INDIAVIX: 03-Mar-2008 → 09-Oct-2026 (4,558 bars)
- hourly NIFTY: 31-Oct-2023 → 09-Oct-2026 (5,036 bars)
- hourly BANKNIFTY: 31-Oct-2023 → 09-Oct-2026 (5,063 bars)
- m5 NIFTY: 16-Jul-2026 → 09-Oct-2026 (4,498 bars)
- m5 BANKNIFTY: 16-Jul-2026 → 09-Oct-2026 (4,498 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,677 | -5.7 bps (-12.8 pts) | -3.45 | 0.001 | -4.9 bps, p 0.00 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,540 | +3.00 vol pts | +6.97 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,663 | +6.0 bps (+13.4 pts) | +3.25 | 0.001 | -4.5 bps, p 0.99 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,676 | +5.9 bps (+13.3 pts) | +2.99 | 0.003 | -3.8 bps, p 0.98 | ✓ |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,685 | -5.7 bps (-31.7 pts) | -2.82 | 0.005 | -0.8 bps, p 0.37 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,674 | +5.0 bps (+11.3 pts) | +2.73 | 0.006 | -1.4 bps, p 0.77 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,675 | -5.7 bps (-31.7 pts) | -2.66 | 0.008 | -0.4 bps, p 0.43 | ✓ |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 523 | +1.2 bps (+2.6 pts) | +2.66 | 0.008 | +1.7 bps, p 0.03 | · |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,663 | +5.5 bps (+30.5 pts) | +2.59 | 0.009 | -1.0 bps, p 0.66 | ✓ |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,675 | +4.6 bps (+10.3 pts) | +2.58 | 0.010 | -3.8 bps, p 0.98 | ✓ |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,685 | -5.4 bps (-29.9 pts) | -2.53 | 0.011 | -2.9 bps, p 0.12 | · |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,620 | +4.6 bps (+10.3 pts) | +2.46 | 0.014 | +1.4 bps, p 0.24 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 492 | +1.3 bps (+2.8 pts) | +2.46 | 0.014 | +0.9 bps, p 0.19 | ✓ |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,692 | -5.0 bps (-27.5 pts) | -2.42 | 0.016 | -1.4 bps, p 0.27 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,692 | -5.1 bps (-28.2 pts) | -2.41 | 0.016 | -3.2 bps, p 0.11 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,636 | +4.3 bps (+9.7 pts) | +2.31 | 0.021 | -3.9 bps, p 0.98 | ✓ |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 942 | -7.9 bps (-17.9 pts) | -2.28 | 0.023 | -5.1 bps, p 0.13 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,657 | +3.7 bps (+8.3 pts) | +2.04 | 0.042 | -2.4 bps, p 0.92 | ✓ |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,672 | -4.5 bps (-24.7 pts) | -1.95 | 0.051 | -5.7 bps, p 0.01 | · |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,642 | -4.0 bps (-22.0 pts) | -1.93 | 0.054 | -6.0 bps, p 0.01 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 526 | +0.9 bps (+2.1 pts) | +1.89 | 0.059 | +0.8 bps, p 0.22 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 946 | -8.6 bps (-47.6 pts) | -1.83 | 0.068 | +1.0 bps, p 0.56 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,675 | +3.2 bps (+7.2 pts) | +1.82 | 0.069 | +1.2 bps, p 0.26 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,859 | -3.9 bps (-8.7 pts) | -1.77 | 0.077 | -3.5 bps, p 0.12 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 492 | +1.0 bps (+5.8 pts) | +1.73 | 0.084 | +0.4 bps, p 0.39 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +19.0 bps (+42.9 pts) | +1.59 | 0.114 | +34.5 bps, p 0.02 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,690 | -3.3 bps (-18.0 pts) | -1.55 | 0.121 | -4.3 bps, p 0.04 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 216 | -1.3 bps (-7.1 pts) | -1.54 | 0.125 | -0.0 bps, p 0.49 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 275 | -1.2 bps (-6.6 pts) | -1.53 | 0.128 | -0.3 bps, p 0.44 | · |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +0.7 bps (+1.6 pts) | +1.47 | 0.143 | +2.2 bps, p 0.98 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 524 | +0.8 bps (+1.7 pts) | +1.45 | 0.148 | +1.2 bps, p 0.13 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,690 | +3.1 bps (+17.2 pts) | +1.45 | 0.148 | +0.6 bps, p 0.40 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,627 | -2.5 bps (-5.6 pts) | -1.44 | 0.150 | -3.0 bps, p 0.05 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,635 | +3.2 bps (+17.9 pts) | +1.44 | 0.151 | +2.4 bps, p 0.16 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,689 | -2.9 bps (-16.1 pts) | -1.37 | 0.170 | -1.9 bps, p 0.22 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,651 | -2.9 bps (-16.1 pts) | -1.34 | 0.179 | -3.4 bps, p 0.09 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,676 | +2.1 bps (+4.8 pts) | +1.28 | 0.202 | +1.5 bps, p 0.20 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,607 | -2.5 bps (-5.6 pts) | -1.27 | 0.205 | +1.1 bps, p 0.74 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 571 | +0.6 bps (+1.3 pts) | +1.18 | 0.238 | -0.6 bps, p 0.69 | ✓ |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 512 | +0.7 bps (+1.5 pts) | +1.17 | 0.242 | +1.0 bps, p 0.22 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 722 | -2.5 bps (-13.9 pts) | -1.14 | 0.253 | -4.8 bps, p 0.13 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 523 | +0.6 bps (+3.5 pts) | +1.07 | 0.283 | +0.5 bps, p 0.36 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 117 | +1.3 bps (+7.0 pts) | +1.07 | 0.285 | +2.7 bps, p 0.09 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 232 | +0.8 bps (+1.9 pts) | +1.07 | 0.287 | -0.0 bps, p 0.51 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-47.7 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 406 | -0.6 bps (-1.4 pts) | -1.06 | 0.291 | +0.7 bps, p 0.72 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 232 | +0.8 bps (+1.8 pts) | +1.02 | 0.309 | +0.6 bps, p 0.37 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 232 | +0.8 bps (+1.7 pts) | +1.00 | 0.318 | +0.7 bps, p 0.34 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 406 | -0.7 bps (-4.0 pts) | -0.99 | 0.324 | -0.9 bps, p 0.28 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +14.0 bps (+77.3 pts) | +0.95 | 0.342 | +32.3 bps, p 0.02 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 112 | +0.9 bps (+2.1 pts) | +0.92 | 0.360 | -1.4 bps, p 0.74 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,677 | +1.5 bps (+3.4 pts) | +0.90 | 0.369 | -0.4 bps, p 0.59 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,691 | +1.7 bps (+9.3 pts) | +0.77 | 0.440 | +1.1 bps, p 0.33 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 722 | -0.9 bps (-4.9 pts) | -0.77 | 0.442 | -1.1 bps, p 0.29 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 571 | +0.4 bps (+2.5 pts) | +0.74 | 0.460 | -0.9 bps, p 0.74 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,649 | +1.3 bps (+2.8 pts) | +0.73 | 0.464 | -2.0 bps, p 0.88 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 526 | +0.4 bps (+2.1 pts) | +0.68 | 0.495 | +0.0 bps, p 0.49 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,691 | -1.4 bps (-7.9 pts) | -0.66 | 0.509 | -5.3 bps, p 0.98 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 512 | -0.4 bps (-2.1 pts) | -0.58 | 0.561 | -0.5 bps, p 0.38 | · |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 55 | +2.9 bps (+6.6 pts) | +0.56 | 0.579 | +13.2 bps, p 0.86 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 524 | +0.4 bps (+2.0 pts) | +0.55 | 0.580 | +0.1 bps, p 0.46 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 920 | +3.0 bps (+16.6 pts) | +0.53 | 0.594 | +8.2 bps, p 0.11 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,677 | -1.1 bps (-6.3 pts) | -0.52 | 0.600 | -7.3 bps, p 1.00 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 719 | +0.9 bps (+2.0 pts) | +0.51 | 0.607 | +0.5 bps, p 0.44 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,692 | +0.8 bps (+4.7 pts) | +0.43 | 0.671 | -1.2 bps, p 0.70 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 232 | +0.4 bps (+2.1 pts) | +0.40 | 0.693 | -1.0 bps, p 0.70 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 359 | -4.1 bps (-9.3 pts) | -0.38 | 0.702 | +10.0 bps, p 0.86 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 275 | -0.3 bps (-0.6 pts) | -0.38 | 0.703 | +1.4 bps, p 0.87 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 52 | -2.2 bps (-11.9 pts) | -0.38 | 0.706 | +10.3 bps, p 0.80 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | -0.3 bps (-0.7 pts) | -0.35 | 0.725 | +1.8 bps, p 0.89 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 232 | -0.4 bps (-2.0 pts) | -0.33 | 0.744 | -0.2 bps, p 0.46 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,671 | -0.5 bps (-1.2 pts) | -0.31 | 0.754 | -0.8 bps, p 0.31 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 216 | +0.2 bps (+0.4 pts) | +0.30 | 0.761 | +1.4 bps, p 0.84 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,670 | +0.6 bps (+1.2 pts) | +0.30 | 0.765 | -1.5 bps, p 0.80 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 721 | +0.3 bps (+1.6 pts) | +0.25 | 0.801 | +1.6 bps, p 0.76 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,660 | -0.4 bps (-0.8 pts) | -0.21 | 0.833 | +2.1 bps, p 0.88 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 920 | +0.8 bps (+1.8 pts) | +0.21 | 0.834 | +1.9 bps, p 0.32 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,677 | +0.3 bps (+0.8 pts) | +0.19 | 0.848 | -2.2 bps, p 0.90 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,573 | -0.6 bps (-3.2 pts) | -0.18 | 0.860 | -4.0 bps, p 0.83 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,692 | +0.2 bps (+1.3 pts) | +0.12 | 0.902 | +2.1 bps, p 0.81 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | -0.1 bps (-0.6 pts) | -0.12 | 0.906 | +0.1 bps, p 0.51 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 719 | -0.1 bps (-0.2 pts) | -0.10 | 0.923 | -0.3 bps, p 0.57 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 719 | +0.1 bps (+0.2 pts) | +0.09 | 0.926 | -1.1 bps, p 0.74 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | -0.0 bps (-0.2 pts) | -0.07 | 0.947 | +0.8 bps, p 0.73 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,677 | -0.1 bps (-0.2 pts) | -0.05 | 0.957 | +1.5 bps, p 0.79 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 232 | +0.0 bps (+0.2 pts) | +0.04 | 0.972 | +0.2 bps, p 0.54 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,621 | -0.1 bps (-0.4 pts) | -0.03 | 0.972 | -1.3 bps, p 0.70 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.009212729407944724}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.1644359146259317}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.46127655720074107}
- D4 NIFTY:  {"p_discovery": 0.04713602077309866}
- D5 NIFTY:  {"p_discovery": 0.9673061271700512}
- D6 NIFTY:  {"p_discovery": 0.4645149934517705}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.804, "mean_vix": 19.68}
- H1 NIFTY:  {"p_discovery": 0.6270384485803646}
- H2 NIFTY:  {"p_discovery": 0.9954300924076941}
- H3 NIFTY:  {"p_discovery": 0.5240835344790847}
- M1 NIFTY:  {"p_discovery": 0.5373221174711772}
- M2 NIFTY:  {"p_discovery": 0.04185352265231216}
- M3 NIFTY:  {"p_discovery": 0.9806112278566244}
- G-ES NIFTY:  {"p_discovery": 0.0011078822717063086}
- G-NQ NIFTY:  {"p_discovery": 9.673505978644483e-06}
- G-SPX NIFTY:  {"p_discovery": 0.000339477622427646}
- G-NASDAQ NIFTY:  {"p_discovery": 8.791425579948919e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0011459520118631925}
- G-N225 NIFTY:  {"p_discovery": 0.30010116860058295}
- G-HSI NIFTY:  {"p_discovery": 0.31026339504300077}
- G-KOSPI NIFTY:  {"p_discovery": 0.08854217597298326}
- G-SSE NIFTY:  {"p_discovery": 0.7205172895285107}
- G-STOXX NIFTY:  {"p_discovery": 0.5514204900088062}
- G-DAX NIFTY:  {"p_discovery": 0.5200276515836483}
- G-FTSE NIFTY:  {"p_discovery": 0.8763283468486468}
- G-USVIX NIFTY:  {"p_discovery": 0.007792024964475205}
- G-DXY NIFTY:  {"p_discovery": 0.3504587568213906}
- G-USDINR NIFTY:  {"p_discovery": 0.018612829792812563}
- G-BRENT NIFTY:  {"p_discovery": 0.22691134561122533}
- G-GOLD NIFTY:  {"p_discovery": 0.5078003650904216}
- G-UST10 NIFTY:  {"p_discovery": 0.12225755723602673}
- L-ES NIFTY:  {"p_discovery": 0.34570945629499306}
- L-NQ NIFTY:  {"p_discovery": 0.06258467380437248}
- L-N225 NIFTY:  {"p_discovery": 0.16882496969890218}
- L-HSI NIFTY:  {"p_discovery": 0.02857163699562255}
- L-KOSPI NIFTY:  {"p_discovery": 0.5409549512600357}
- L-SSE NIFTY:  {"p_discovery": 0.1643076122346335}
- L-STOXX NIFTY:  {"p_discovery": 0.09501619391626356}
- L-DAX NIFTY:  {"p_discovery": 0.3047150310981098}
- L-FTSE NIFTY:  {"p_discovery": 0.2271626712511059}
- L-DXY NIFTY:  {"p_discovery": 0.07917071456303992}
- L-USDINR NIFTY:  {"p_discovery": 0.01249233481060592}
- L-BRENT NIFTY:  {"p_discovery": 0.011896048199877062}
- L-GOLD NIFTY:  {"p_discovery": 0.34492388559752374}
- D1 BANKNIFTY:  {"p_discovery": 0.017378332701031094}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.7931215911065232}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017924987}
- D4 BANKNIFTY:  {"p_discovery": 0.03452281152140772}
- D5 BANKNIFTY:  {"p_discovery": 0.9555482757913127}
- D6 BANKNIFTY:  {"p_discovery": 0.8117328613562985}
- H1 BANKNIFTY:  {"p_discovery": 0.5898207633517466}
- H2 BANKNIFTY:  {"p_discovery": 0.7637623068017078}
- H3 BANKNIFTY:  {"p_discovery": 0.5684093629364001}
- M1 BANKNIFTY:  {"p_discovery": 0.16790106167638122}
- M2 BANKNIFTY:  {"p_discovery": 0.7053346699887422}
- M3 BANKNIFTY:  {"p_discovery": 0.38776755550070496}
- G-ES BANKNIFTY:  {"p_discovery": 0.3770092470385279}
- G-NQ BANKNIFTY:  {"p_discovery": 0.509297977137182}
- G-SPX BANKNIFTY:  {"p_discovery": 0.3450488931221215}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.8591512085444026}
- G-DJI BANKNIFTY:  {"p_discovery": 0.24480738829984838}
- G-N225 BANKNIFTY:  {"p_discovery": 0.5116111269538935}
- G-HSI BANKNIFTY:  {"p_discovery": 0.5084916944065502}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.14379872169511146}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8018814961537613}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.024416548842532613}
- G-DAX BANKNIFTY:  {"p_discovery": 0.03741405493847932}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.0032422783483484546}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.22601853819421885}
- G-DXY BANKNIFTY:  {"p_discovery": 0.2926782751716642}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.2463203789610397}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.002926054317955097}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.005397705700008298}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8664954257334824}
- L-ES BANKNIFTY:  {"p_discovery": 0.5810617216338799}
- L-NQ BANKNIFTY:  {"p_discovery": 0.34497070945101765}
- L-N225 BANKNIFTY:  {"p_discovery": 0.01999399151681514}
- L-HSI BANKNIFTY:  {"p_discovery": 0.4006623732880123}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.026609066193918885}
- L-SSE BANKNIFTY:  {"p_discovery": 0.8466744458418913}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.3068639651791817}
- L-DAX BANKNIFTY:  {"p_discovery": 0.9632663922960975}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.7157597291251232}
- L-DXY BANKNIFTY:  {"p_discovery": 0.23396183100550869}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.05134705825683625}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.04498609904659962}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.4988544696430692}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,691 | +0.369 | +0.514 | 0.264 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,691 | +0.383 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,691 | +0.307 | +0.487 | 0.237 | +38.2 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,691 | +0.344 | +0.483 | 0.233 | +37.8 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,691 | +0.280 | +0.446 | 0.198 | +34.1 |
| S&P 500 | NIFTY | opening gap | 4,676 | +0.200 | +0.424 | 0.179 | +32.0 |
| Nasdaq Composite | NIFTY | opening gap | 4,676 | +0.175 | +0.421 | 0.177 | +31.8 |
| Dow Jones | NIFTY | opening gap | 4,676 | +0.211 | +0.420 | 0.176 | +31.7 |
| S&P 500 futures | NIFTY | opening gap | 4,676 | +0.185 | +0.394 | 0.155 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,676 | +0.162 | +0.391 | 0.153 | +29.0 |
| CBOE VIX | BANKNIFTY | opening gap | 4,691 | -0.045 | -0.386 | 0.149 | -28.7 |
| CBOE VIX | NIFTY | opening gap | 4,676 | -0.029 | -0.384 | 0.147 | -28.4 |
| DAX | BANKNIFTY | opening gap | 4,691 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,691 | +0.209 | +0.319 | 0.101 | +23.0 |
| FTSE 100 | BANKNIFTY | opening gap | 4,691 | +0.238 | +0.296 | 0.087 | +21.2 |
| DAX | NIFTY | opening gap | 4,676 | +0.130 | +0.294 | 0.087 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,676 | +0.119 | +0.274 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,676 | +0.131 | +0.247 | 0.061 | +17.4 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,254 | +0.552 | +0.197 | 0.039 | +11.4 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,249 | +0.680 | +0.188 | 0.035 | +10.9 |
| US dollar index | NIFTY | opening gap | 4,676 | -0.185 | -0.151 | 0.023 | -10.5 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,458 | +0.261 | +0.166 | 0.028 | +9.9 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,454 | +0.313 | +0.155 | 0.024 | +9.2 |
| US dollar index | BANKNIFTY | opening gap | 4,691 | -0.240 | -0.130 | 0.017 | -8.9 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 2,026 | +0.106 | +0.181 | 0.033 | +8.3 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 2,019 | +0.119 | +0.164 | 0.027 | +7.5 |
| DAX | NIFTY | same 5 minutes | 2,025 | +0.087 | +0.155 | 0.024 | +7.1 |
| US 10-year yield | BANKNIFTY | opening gap | 4,691 | +0.032 | +0.096 | 0.009 | +6.6 |
| FTSE 100 | NIFTY | same 5 minutes | 2,025 | +0.093 | +0.138 | 0.019 | +6.3 |
| Brent crude | NIFTY | opening gap | 4,676 | +0.022 | +0.091 | 0.008 | +6.2 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 2,018 | +0.109 | +0.138 | 0.019 | +6.2 |
| DAX | BANKNIFTY | same 5 minutes | 2,018 | +0.096 | +0.137 | 0.019 | +6.2 |
| Brent crude | BANKNIFTY | opening gap | 4,691 | +0.033 | +0.088 | 0.008 | +6.0 |
| Gold | BANKNIFTY | same 5 minutes | 3,462 | +0.131 | +0.091 | 0.008 | +5.4 |
| Gold | NIFTY | same 5 minutes | 3,464 | +0.097 | +0.087 | 0.008 | +5.2 |
| US 10-year yield | NIFTY | opening gap | 4,676 | +0.015 | +0.066 | 0.004 | +4.5 |
| Brent crude | NIFTY | same 5 minutes | 3,121 | -0.018 | -0.077 | 0.006 | -4.3 |
| Gold | NIFTY | opening gap | 4,676 | +0.030 | +0.059 | 0.004 | +4.1 |
| Hang Seng | NIFTY | same 5 minutes | 2,424 | +0.106 | +0.080 | 0.006 | +4.0 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,119 | -0.021 | -0.069 | 0.005 | -3.9 |
| US dollar index | NIFTY | same 5 minutes | 3,410 | -0.277 | -0.065 | 0.004 | -3.8 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,438 | +0.123 | +0.070 | 0.005 | +3.5 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,406 | -0.287 | -0.052 | 0.003 | -3.0 |
| Kospi | NIFTY | same 5 minutes | 1,450 | +0.026 | +0.072 | 0.005 | +2.7 |
| Nikkei 225 | NIFTY | opening gap | 4,676 | +0.015 | +0.040 | 0.002 | +2.7 |
| USD/INR | NIFTY | same 5 minutes | 3,663 | -0.189 | -0.044 | 0.002 | -2.7 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,312 | +0.025 | +0.073 | 0.005 | +2.6 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,663 | -0.228 | -0.042 | 0.002 | -2.5 |
| Kospi | BANKNIFTY | same 5 minutes | 1,454 | +0.028 | +0.060 | 0.004 | +2.3 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,811 | +0.049 | +0.053 | 0.003 | +2.3 |
| Gold | BANKNIFTY | opening gap | 4,691 | +0.023 | +0.030 | 0.001 | +2.0 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,691 | -0.018 | -0.029 | 0.001 | -2.0 |
| Hang Seng | BANKNIFTY | opening gap | 4,691 | +0.017 | +0.029 | 0.001 | +2.0 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,814 | +0.053 | +0.044 | 0.002 | +1.9 |
| Hang Seng | NIFTY | opening gap | 4,676 | +0.008 | +0.021 | 0.000 | +1.4 |
| USD/INR | BANKNIFTY | opening gap | 4,691 | -0.037 | -0.021 | 0.000 | -1.4 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,320 | +0.007 | +0.017 | 0.000 | +0.6 |
| USD/INR | NIFTY | opening gap | 4,676 | -0.010 | -0.008 | 0.000 | -0.6 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,691 | +0.004 | +0.007 | 0.000 | +0.5 |
| Kospi | BANKNIFTY | opening gap | 4,691 | -0.004 | -0.007 | 0.000 | -0.5 |
| Shanghai Composite | NIFTY | opening gap | 4,676 | -0.003 | -0.006 | 0.000 | -0.4 |
| Kospi | NIFTY | opening gap | 4,676 | -0.002 | -0.005 | 0.000 | -0.3 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 12.8 pts/trade vs 4.2 pts of costs (t -3.45, rolling validation -4.9 bps). Per-trade σ 263 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹363,696; smaller accounts are over-betting it.


Experiment record: 802a9d8be9104fada3e769335a98a2af · 9d675fcd5421f20a0a0f77ed41d87be4e87da81fdae7ff9eac115625c8181e0a
