# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-10-31 15:54 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 30-Oct-2026 (4,691 bars)
- daily BANKNIFTY: 17-Sep-2007 → 30-Oct-2026 (4,706 bars)
- daily INDIAVIX: 03-Mar-2008 → 30-Oct-2026 (4,572 bars)
- hourly NIFTY: 16-Nov-2023 → 30-Oct-2026 (5,075 bars)
- hourly BANKNIFTY: 16-Nov-2023 → 30-Oct-2026 (5,075 bars)
- m5 NIFTY: 05-Aug-2026 → 30-Oct-2026 (4,496 bars)
- m5 BANKNIFTY: 05-Aug-2026 → 30-Oct-2026 (4,496 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,691 | -5.6 bps (-13.0 pts) | -3.43 | 0.001 | -4.7 bps, p 0.00 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,554 | +2.98 vol pts | +6.94 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,677 | +5.9 bps (+13.6 pts) | +3.23 | 0.001 | -4.8 bps, p 1.00 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,690 | +5.9 bps (+13.5 pts) | +2.99 | 0.003 | -3.7 bps, p 0.98 | ✓ |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,699 | -5.7 bps (-31.0 pts) | -2.79 | 0.005 | -0.4 bps, p 0.44 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,688 | +5.0 bps (+11.5 pts) | +2.72 | 0.006 | -1.4 bps, p 0.77 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,689 | -5.8 bps (-31.5 pts) | -2.67 | 0.008 | -0.1 bps, p 0.49 | ✓ |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,677 | +5.4 bps (+29.7 pts) | +2.56 | 0.010 | -1.2 bps, p 0.70 | ✓ |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,689 | +4.5 bps (+10.4 pts) | +2.55 | 0.011 | -3.9 bps, p 0.98 | ✓ |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,634 | +4.6 bps (+10.6 pts) | +2.49 | 0.013 | +1.3 bps, p 0.24 | · |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,699 | -5.3 bps (-29.0 pts) | -2.49 | 0.013 | -2.2 bps, p 0.18 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,706 | -5.0 bps (-27.3 pts) | -2.43 | 0.015 | -1.7 bps, p 0.23 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,706 | -5.0 bps (-27.3 pts) | -2.37 | 0.018 | -2.7 bps, p 0.14 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,650 | +4.2 bps (+9.8 pts) | +2.28 | 0.022 | -4.0 bps, p 0.99 | ✓ |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 944 | -7.7 bps (-17.8 pts) | -2.23 | 0.026 | -4.3 bps, p 0.17 | · |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +1.1 bps (+2.6 pts) | +2.03 | 0.042 | +2.2 bps, p 0.04 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,671 | +3.6 bps (+8.4 pts) | +2.01 | 0.045 | -2.5 bps, p 0.93 | ✓ |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,656 | -4.1 bps (-22.2 pts) | -1.97 | 0.049 | -5.3 bps, p 0.02 | · |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,686 | -4.4 bps (-24.3 pts) | -1.95 | 0.051 | -5.1 bps, p 0.01 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 515 | +1.3 bps (+3.0 pts) | +1.90 | 0.058 | +1.7 bps, p 0.14 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,864 | -4.0 bps (-9.2 pts) | -1.85 | 0.065 | -3.4 bps, p 0.12 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 505 | +1.4 bps (+3.2 pts) | +1.85 | 0.065 | +3.1 bps, p 0.03 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 218 | +1.8 bps (+4.1 pts) | +1.84 | 0.067 | +2.8 bps, p 0.13 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,689 | +3.2 bps (+7.4 pts) | +1.82 | 0.069 | +1.2 bps, p 0.25 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 948 | -8.6 bps (-46.9 pts) | -1.82 | 0.069 | +0.8 bps, p 0.55 | · |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 55 | +11.5 bps (+26.6 pts) | +1.83 | 0.072 | +26.1 bps, p 0.01 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 513 | +1.2 bps (+2.8 pts) | +1.71 | 0.088 | +1.1 bps, p 0.24 | · |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 509 | +1.2 bps (+2.8 pts) | +1.69 | 0.093 | +1.1 bps, p 0.28 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +19.0 bps (+43.9 pts) | +1.59 | 0.114 | +34.5 bps, p 0.02 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,704 | -3.3 bps (-17.8 pts) | -1.55 | 0.121 | -3.7 bps, p 0.07 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,704 | +3.2 bps (+17.6 pts) | +1.50 | 0.134 | +0.9 bps, p 0.35 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,641 | -2.6 bps (-5.9 pts) | -1.50 | 0.135 | -3.0 bps, p 0.05 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,649 | +3.3 bps (+18.0 pts) | +1.47 | 0.142 | +2.3 bps, p 0.17 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 218 | +1.6 bps (+8.5 pts) | +1.46 | 0.147 | +3.5 bps, p 0.08 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 218 | +1.2 bps (+2.8 pts) | +1.43 | 0.154 | +1.5 bps, p 0.21 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,703 | -2.9 bps (-15.9 pts) | -1.38 | 0.168 | -1.2 bps, p 0.31 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 505 | +0.9 bps (+2.0 pts) | +1.35 | 0.177 | +0.2 bps, p 0.45 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,665 | -2.9 bps (-15.9 pts) | -1.34 | 0.179 | -3.7 bps, p 0.07 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,690 | +2.1 bps (+4.9 pts) | +1.26 | 0.207 | +1.5 bps, p 0.20 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,621 | -2.5 bps (-5.7 pts) | -1.24 | 0.214 | +1.4 bps, p 0.78 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 118 | +1.6 bps (+8.9 pts) | +1.16 | 0.247 | +3.4 bps, p 0.11 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 218 | +1.1 bps (+2.6 pts) | +1.15 | 0.252 | +1.6 bps, p 0.26 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | -2.5 bps (-13.6 pts) | -1.13 | 0.257 | -4.0 bps, p 0.17 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-47.2 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 509 | +0.8 bps (+4.3 pts) | +1.01 | 0.311 | +0.8 bps, p 0.31 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 513 | +0.8 bps (+4.3 pts) | +1.00 | 0.319 | +1.2 bps, p 0.23 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 275 | +0.9 bps (+2.1 pts) | +0.99 | 0.325 | +2.2 bps, p 0.16 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +14.0 bps (+76.5 pts) | +0.95 | 0.342 | +32.3 bps, p 0.02 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,691 | +1.5 bps (+3.5 pts) | +0.91 | 0.365 | -0.3 bps, p 0.58 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | -1.0 bps (-5.4 pts) | -0.85 | 0.395 | -1.8 bps, p 0.17 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,705 | +1.8 bps (+9.7 pts) | +0.81 | 0.417 | +2.1 bps, p 0.21 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 51 | +5.5 bps (+30.0 pts) | +0.79 | 0.433 | +25.8 bps, p 1.00 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 220 | +0.8 bps (+1.9 pts) | +0.78 | 0.435 | +2.2 bps, p 0.21 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 220 | -0.8 bps (-4.5 pts) | -0.75 | 0.451 | -0.2 bps, p 0.46 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | +1.3 bps (+3.0 pts) | +0.74 | 0.461 | +1.4 bps, p 0.33 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,663 | +1.2 bps (+2.8 pts) | +0.70 | 0.484 | -2.1 bps, p 0.89 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 505 | +0.4 bps (+2.5 pts) | +0.67 | 0.505 | -0.8 bps, p 0.74 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | +0.7 bps (+3.9 pts) | +0.65 | 0.514 | +2.7 bps, p 0.84 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 515 | +0.5 bps (+2.8 pts) | +0.64 | 0.519 | +0.6 bps, p 0.36 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,705 | -1.4 bps (-7.4 pts) | -0.63 | 0.526 | -5.2 bps, p 0.98 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 576 | -0.4 bps (-0.8 pts) | -0.56 | 0.573 | -2.5 bps, p 0.97 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | +0.5 bps (+1.1 pts) | +0.52 | 0.607 | +1.1 bps, p 0.33 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 576 | -0.4 bps (-1.9 pts) | -0.51 | 0.611 | -1.4 bps, p 0.85 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 920 | +2.9 bps (+15.7 pts) | +0.51 | 0.611 | +7.7 bps, p 0.12 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 218 | +0.5 bps (+2.9 pts) | +0.50 | 0.618 | +2.1 bps, p 0.85 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,691 | -1.1 bps (-5.8 pts) | -0.49 | 0.621 | -6.8 bps, p 0.99 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 275 | -0.5 bps (-2.6 pts) | -0.49 | 0.628 | -0.6 bps, p 0.39 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 218 | +0.5 bps (+2.7 pts) | +0.45 | 0.656 | +1.5 bps, p 0.72 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,706 | +0.9 bps (+4.8 pts) | +0.44 | 0.659 | -0.9 bps, p 0.66 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 359 | -4.1 bps (-9.5 pts) | -0.38 | 0.702 | +10.0 bps, p 0.86 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,684 | +0.6 bps (+1.4 pts) | +0.34 | 0.737 | -1.3 bps, p 0.77 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 723 | +0.3 bps (+1.9 pts) | +0.32 | 0.752 | +1.9 bps, p 0.80 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 399 | -0.3 bps (-1.4 pts) | -0.31 | 0.758 | +0.3 bps, p 0.56 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,674 | -0.5 bps (-1.1 pts) | -0.28 | 0.783 | +1.9 bps, p 0.86 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,685 | -0.4 bps (-1.0 pts) | -0.27 | 0.790 | -0.4 bps, p 0.41 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,691 | +0.4 bps (+1.0 pts) | +0.24 | 0.812 | -1.8 bps, p 0.84 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,576 | -0.7 bps (-3.7 pts) | -0.21 | 0.836 | -3.6 bps, p 0.81 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 920 | +0.7 bps (+1.7 pts) | +0.19 | 0.846 | +1.7 bps, p 0.34 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 134 | -0.2 bps (-0.5 pts) | -0.19 | 0.848 | -0.8 bps, p 0.62 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | -0.1 bps (-0.3 pts) | -0.14 | 0.888 | -1.5 bps, p 0.81 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 505 | +0.1 bps (+0.6 pts) | +0.13 | 0.900 | +1.6 bps, p 0.84 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,691 | -0.2 bps (-0.4 pts) | -0.11 | 0.915 | +1.1 bps, p 0.73 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 724 | +0.1 bps (+0.2 pts) | +0.10 | 0.921 | +0.7 bps, p 0.64 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,706 | +0.2 bps (+0.9 pts) | +0.09 | 0.930 | +1.8 bps, p 0.77 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,635 | -0.2 bps (-0.9 pts) | -0.07 | 0.944 | -1.9 bps, p 0.78 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | -0.0 bps (-0.1 pts) | -0.04 | 0.972 | +0.3 bps, p 0.60 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 399 | +0.0 bps (+0.0 pts) | +0.02 | 0.987 | +1.4 bps, p 0.78 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.008993710649260321}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.13880432235145346}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.46127655720074107}
- D4 NIFTY:  {"p_discovery": 0.044358185554471685}
- D5 NIFTY:  {"p_discovery": 0.9673061271700512}
- D6 NIFTY:  {"p_discovery": 0.4645149934517705}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.801, "mean_vix": 19.67}
- H1 NIFTY:  {"p_discovery": 0.5769875346889045}
- H2 NIFTY:  {"p_discovery": 0.8790943773842976}
- H3 NIFTY:  {"p_discovery": 0.5979945024798884}
- M1 NIFTY:  {"p_discovery": 0.5182240019699615}
- M2 NIFTY:  {"p_discovery": 0.9372670222344723}
- M3 NIFTY:  {"p_discovery": 0.2836681912643492}
- G-ES NIFTY:  {"p_discovery": 0.0011517508606720562}
- G-NQ NIFTY:  {"p_discovery": 8.488893830313798e-06}
- G-SPX NIFTY:  {"p_discovery": 0.0003721473960454358}
- G-NASDAQ NIFTY:  {"p_discovery": 9.448239671298623e-05}
- G-DJI NIFTY:  {"p_discovery": 0.001180933850088978}
- G-N225 NIFTY:  {"p_discovery": 0.3084208637078899}
- G-HSI NIFTY:  {"p_discovery": 0.31094627403162156}
- G-KOSPI NIFTY:  {"p_discovery": 0.08901310312612633}
- G-SSE NIFTY:  {"p_discovery": 0.7311546608742253}
- G-STOXX NIFTY:  {"p_discovery": 0.5490223382042458}
- G-DAX NIFTY:  {"p_discovery": 0.5486688487436983}
- G-FTSE NIFTY:  {"p_discovery": 0.8413393590497233}
- G-USVIX NIFTY:  {"p_discovery": 0.007976074125201217}
- G-DXY NIFTY:  {"p_discovery": 0.3230478555615944}
- G-USDINR NIFTY:  {"p_discovery": 0.01665148240965516}
- G-BRENT NIFTY:  {"p_discovery": 0.23191365511615455}
- G-GOLD NIFTY:  {"p_discovery": 0.48444105677853627}
- G-UST10 NIFTY:  {"p_discovery": 0.11752632830209993}
- L-ES NIFTY:  {"p_discovery": 0.5104862401586926}
- L-NQ NIFTY:  {"p_discovery": 0.0841337183632876}
- L-N225 NIFTY:  {"p_discovery": 0.7242805680019587}
- L-HSI NIFTY:  {"p_discovery": 0.28787253845167493}
- L-KOSPI NIFTY:  {"p_discovery": 0.888773603949145}
- L-SSE NIFTY:  {"p_discovery": 0.8155832646356364}
- L-STOXX NIFTY:  {"p_discovery": 0.2562220181522872}
- L-DAX NIFTY:  {"p_discovery": 0.09076023808963253}
- L-FTSE NIFTY:  {"p_discovery": 0.20044129298791805}
- L-DXY NIFTY:  {"p_discovery": 0.02284836759154274}
- L-USDINR NIFTY:  {"p_discovery": 0.27448255516966114}
- L-BRENT NIFTY:  {"p_discovery": 0.07049750473851871}
- L-GOLD NIFTY:  {"p_discovery": 0.08231831730447782}
- D1 BANKNIFTY:  {"p_discovery": 0.019742543816257747}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.8546576012257696}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017924987}
- D4 BANKNIFTY:  {"p_discovery": 0.03635690552711712}
- D5 BANKNIFTY:  {"p_discovery": 0.9555482757913127}
- D6 BANKNIFTY:  {"p_discovery": 0.8117328613562985}
- H1 BANKNIFTY:  {"p_discovery": 0.5001696894447815}
- H2 BANKNIFTY:  {"p_discovery": 0.735631669737072}
- H3 BANKNIFTY:  {"p_discovery": 0.6901408825935216}
- M1 BANKNIFTY:  {"p_discovery": 0.5331682257049366}
- M2 BANKNIFTY:  {"p_discovery": 0.6715435173767802}
- M3 BANKNIFTY:  {"p_discovery": 0.7596131618912195}
- G-ES BANKNIFTY:  {"p_discovery": 0.40537537676823754}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5452291809610601}
- G-SPX BANKNIFTY:  {"p_discovery": 0.29852727658325}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.8497257066290974}
- G-DJI BANKNIFTY:  {"p_discovery": 0.20116967952670942}
- G-N225 BANKNIFTY:  {"p_discovery": 0.5903584556615169}
- G-HSI BANKNIFTY:  {"p_discovery": 0.529685051000411}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.1428360059145426}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8211583303855375}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.02066060632695984}
- G-DAX BANKNIFTY:  {"p_discovery": 0.0339340091641527}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.0027632624850961137}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.19694794389998374}
- G-DXY BANKNIFTY:  {"p_discovery": 0.22494835908375593}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.22534718464966894}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.0027846591598907505}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.004324799667585157}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8233192803356848}
- L-ES BANKNIFTY:  {"p_discovery": 0.49893963271035874}
- L-NQ BANKNIFTY:  {"p_discovery": 0.5511134068861973}
- L-N225 BANKNIFTY:  {"p_discovery": 0.6617124645801028}
- L-HSI BANKNIFTY:  {"p_discovery": 0.516059643910233}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.3182636455954169}
- L-SSE BANKNIFTY:  {"p_discovery": 0.8071468285260063}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.998054915277508}
- L-DAX BANKNIFTY:  {"p_discovery": 0.5668255164754148}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.8202681485018704}
- L-DXY BANKNIFTY:  {"p_discovery": 0.3249663434559191}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.8117930563060192}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.14909604364629617}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.5065509850845055}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,705 | +0.368 | +0.513 | 0.263 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,705 | +0.383 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,705 | +0.307 | +0.486 | 0.236 | +38.1 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,705 | +0.343 | +0.482 | 0.233 | +37.8 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,705 | +0.279 | +0.445 | 0.198 | +34.1 |
| S&P 500 | NIFTY | opening gap | 4,690 | +0.200 | +0.423 | 0.179 | +32.0 |
| Nasdaq Composite | NIFTY | opening gap | 4,690 | +0.175 | +0.420 | 0.177 | +31.7 |
| Dow Jones | NIFTY | opening gap | 4,690 | +0.211 | +0.420 | 0.176 | +31.7 |
| S&P 500 futures | NIFTY | opening gap | 4,690 | +0.185 | +0.394 | 0.155 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,690 | +0.161 | +0.390 | 0.152 | +29.0 |
| CBOE VIX | BANKNIFTY | opening gap | 4,705 | -0.044 | -0.385 | 0.149 | -28.7 |
| CBOE VIX | NIFTY | opening gap | 4,690 | -0.029 | -0.383 | 0.147 | -28.4 |
| DAX | BANKNIFTY | opening gap | 4,705 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,705 | +0.208 | +0.318 | 0.101 | +23.0 |
| FTSE 100 | BANKNIFTY | opening gap | 4,705 | +0.238 | +0.296 | 0.087 | +21.2 |
| DAX | NIFTY | opening gap | 4,690 | +0.130 | +0.294 | 0.086 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,690 | +0.118 | +0.274 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,690 | +0.131 | +0.247 | 0.061 | +17.5 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,217 | +0.791 | +0.224 | 0.050 | +13.1 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,223 | +0.664 | +0.221 | 0.049 | +12.9 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,382 | +0.386 | +0.191 | 0.037 | +11.3 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,387 | +0.328 | +0.189 | 0.036 | +11.2 |
| US dollar index | NIFTY | opening gap | 4,690 | -0.185 | -0.151 | 0.023 | -10.5 |
| US dollar index | BANKNIFTY | opening gap | 4,705 | -0.240 | -0.130 | 0.017 | -9.0 |
| DAX | BANKNIFTY | same 5 minutes | 1,912 | +0.133 | +0.173 | 0.030 | +7.7 |
| DAX | NIFTY | same 5 minutes | 1,922 | +0.112 | +0.173 | 0.030 | +7.7 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 1,911 | +0.120 | +0.168 | 0.028 | +7.4 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 1,921 | +0.101 | +0.167 | 0.028 | +7.4 |
| US 10-year yield | BANKNIFTY | opening gap | 4,705 | +0.032 | +0.096 | 0.009 | +6.6 |
| Brent crude | NIFTY | opening gap | 4,690 | +0.022 | +0.091 | 0.008 | +6.2 |
| Gold | BANKNIFTY | same 5 minutes | 3,372 | +0.160 | +0.104 | 0.011 | +6.0 |
| Brent crude | BANKNIFTY | opening gap | 4,705 | +0.033 | +0.088 | 0.008 | +6.0 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 1,910 | +0.103 | +0.130 | 0.017 | +5.8 |
| FTSE 100 | NIFTY | same 5 minutes | 1,920 | +0.091 | +0.129 | 0.017 | +5.7 |
| Gold | NIFTY | same 5 minutes | 3,377 | +0.124 | +0.094 | 0.009 | +5.5 |
| Brent crude | NIFTY | same 5 minutes | 3,221 | -0.028 | -0.092 | 0.008 | -5.2 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,217 | -0.030 | -0.089 | 0.008 | -5.1 |
| US 10-year yield | NIFTY | opening gap | 4,690 | +0.014 | +0.066 | 0.004 | +4.5 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,808 | +0.121 | +0.099 | 0.010 | +4.2 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,810 | +0.140 | +0.098 | 0.010 | +4.2 |
| Gold | NIFTY | opening gap | 4,690 | +0.030 | +0.059 | 0.003 | +4.1 |
| Kospi | BANKNIFTY | same 5 minutes | 1,478 | +0.064 | +0.100 | 0.010 | +3.9 |
| Kospi | NIFTY | same 5 minutes | 1,474 | +0.055 | +0.096 | 0.009 | +3.7 |
| US dollar index | NIFTY | same 5 minutes | 3,348 | -0.297 | -0.062 | 0.004 | -3.6 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,343 | -0.305 | -0.055 | 0.003 | -3.2 |
| USD/INR | NIFTY | same 5 minutes | 3,646 | -0.202 | -0.045 | 0.002 | -2.7 |
| Nikkei 225 | NIFTY | opening gap | 4,690 | +0.015 | +0.039 | 0.002 | +2.7 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,390 | +0.088 | +0.049 | 0.002 | +2.4 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,643 | -0.191 | -0.036 | 0.001 | -2.2 |
| Gold | BANKNIFTY | opening gap | 4,705 | +0.023 | +0.030 | 0.001 | +2.1 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,705 | -0.018 | -0.029 | 0.001 | -2.0 |
| Hang Seng | BANKNIFTY | opening gap | 4,705 | +0.017 | +0.029 | 0.001 | +2.0 |
| Hang Seng | NIFTY | same 5 minutes | 2,378 | +0.045 | +0.031 | 0.001 | +1.5 |
| Hang Seng | NIFTY | opening gap | 4,690 | +0.008 | +0.021 | 0.000 | +1.4 |
| USD/INR | BANKNIFTY | opening gap | 4,705 | -0.037 | -0.021 | 0.000 | -1.4 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,316 | +0.012 | +0.019 | 0.000 | +0.7 |
| USD/INR | NIFTY | opening gap | 4,690 | -0.010 | -0.008 | 0.000 | -0.6 |
| Kospi | BANKNIFTY | opening gap | 4,705 | -0.005 | -0.007 | 0.000 | -0.5 |
| Kospi | NIFTY | opening gap | 4,690 | -0.003 | -0.007 | 0.000 | -0.5 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,705 | +0.004 | +0.007 | 0.000 | +0.5 |
| Shanghai Composite | NIFTY | opening gap | 4,690 | -0.003 | -0.006 | 0.000 | -0.4 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,309 | +0.004 | +0.008 | 0.000 | +0.3 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 13.0 pts/trade vs 4.2 pts of costs (t -3.43, rolling validation -4.7 bps). Per-trade σ 269 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹373,470; smaller accounts are over-betting it.


Experiment record: a4e7291d0fc145d49a3aa09c76111cb9 · 59fea3aa807012bda09837ec41465e5dd9f086b40d68327e097343ea866e6483
