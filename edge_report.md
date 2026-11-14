# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-11-14 17:00 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 13-Nov-2026 (4,700 bars)
- daily BANKNIFTY: 17-Sep-2007 → 13-Nov-2026 (4,715 bars)
- daily INDIAVIX: 03-Mar-2008 → 13-Nov-2026 (4,581 bars)
- hourly NIFTY: 30-Nov-2023 → 13-Nov-2026 (5,057 bars)
- hourly BANKNIFTY: 30-Nov-2023 → 13-Nov-2026 (5,057 bars)
- m5 NIFTY: 18-Aug-2026 → 13-Nov-2026 (4,496 bars)
- m5 BANKNIFTY: 18-Aug-2026 → 13-Nov-2026 (4,496 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,700 | -5.5 bps (-13.9 pts) | -3.35 | 0.001 | -4.3 bps, p 0.01 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,563 | +2.97 vol pts | +6.93 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,686 | +5.9 bps (+14.7 pts) | +3.21 | 0.001 | -4.9 bps, p 1.00 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,699 | +5.8 bps (+14.6 pts) | +2.97 | 0.003 | -3.9 bps, p 0.99 | ✓ |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +1.7 bps (+4.3 pts) | +2.87 | 0.004 | +1.1 bps, p 0.17 | ✓ |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,708 | -5.7 bps (-34.8 pts) | -2.81 | 0.005 | -0.4 bps, p 0.44 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,697 | +5.0 bps (+12.5 pts) | +2.71 | 0.007 | -1.4 bps, p 0.77 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,698 | -5.7 bps (-35.0 pts) | -2.66 | 0.008 | -0.2 bps, p 0.46 | ✓ |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,686 | +5.4 bps (+32.9 pts) | +2.55 | 0.011 | -1.3 bps, p 0.71 | ✓ |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,643 | +4.7 bps (+11.8 pts) | +2.54 | 0.011 | +1.4 bps, p 0.24 | ✓ |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,698 | +4.5 bps (+11.2 pts) | +2.53 | 0.011 | -4.1 bps, p 0.99 | ✓ |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,708 | -5.3 bps (-32.5 pts) | -2.50 | 0.012 | -2.6 bps, p 0.14 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,715 | -5.0 bps (-30.7 pts) | -2.38 | 0.017 | -2.9 bps, p 0.13 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,715 | -4.8 bps (-29.5 pts) | -2.35 | 0.019 | -1.3 bps, p 0.29 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,659 | +4.2 bps (+10.5 pts) | +2.27 | 0.024 | -4.2 bps, p 0.99 | ✓ |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 56 | +14.7 bps (+37.0 pts) | +2.31 | 0.025 | +19.9 bps, p 0.04 | · |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 945 | -7.6 bps (-19.2 pts) | -2.19 | 0.028 | -4.0 bps, p 0.19 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 496 | +1.6 bps (+4.1 pts) | +2.10 | 0.036 | +2.2 bps, p 0.05 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 196 | +2.3 bps (+5.8 pts) | +2.09 | 0.038 | +3.7 bps, p 0.06 | · |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,665 | -4.1 bps (-25.2 pts) | -2.00 | 0.045 | -5.3 bps, p 0.02 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 503 | +1.5 bps (+3.7 pts) | +2.00 | 0.046 | +2.3 bps, p 0.05 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,680 | +3.6 bps (+9.0 pts) | +1.98 | 0.048 | -2.8 bps, p 0.95 | ✓ |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,695 | -4.4 bps (-26.8 pts) | -1.93 | 0.054 | -4.9 bps, p 0.02 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 196 | +2.2 bps (+13.5 pts) | +1.84 | 0.067 | +3.9 bps, p 0.06 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 196 | +1.9 bps (+4.7 pts) | +1.83 | 0.069 | +3.0 bps, p 0.05 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 949 | -8.5 bps (-52.2 pts) | -1.82 | 0.070 | +0.8 bps, p 0.55 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,698 | +3.2 bps (+7.9 pts) | +1.80 | 0.072 | +1.0 bps, p 0.28 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,869 | -3.9 bps (-9.7 pts) | -1.79 | 0.074 | -3.1 bps, p 0.15 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 567 | -1.4 bps (-8.5 pts) | -1.75 | 0.080 | -4.0 bps, p 0.00 | · |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 497 | +1.3 bps (+3.4 pts) | +1.69 | 0.091 | +0.6 bps, p 0.35 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 196 | +1.8 bps (+4.5 pts) | +1.61 | 0.108 | +2.8 bps, p 0.12 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 168 | +18.9 bps (+47.4 pts) | +1.58 | 0.116 | +34.7 bps, p 0.02 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,713 | -3.2 bps (-19.7 pts) | -1.54 | 0.125 | -3.7 bps, p 0.07 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,658 | +3.4 bps (+20.5 pts) | +1.50 | 0.133 | +2.5 bps, p 0.15 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,650 | -2.6 bps (-6.4 pts) | -1.50 | 0.135 | -3.1 bps, p 0.04 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,713 | +3.2 bps (+19.5 pts) | +1.49 | 0.136 | +0.6 bps, p 0.40 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 196 | +1.9 bps (+11.4 pts) | +1.49 | 0.137 | +4.2 bps, p 0.02 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 53 | +9.9 bps (+60.5 pts) | +1.47 | 0.147 | +24.3 bps, p 0.06 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,712 | -2.9 bps (-18.0 pts) | -1.39 | 0.163 | -1.5 bps, p 0.27 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,674 | -2.9 bps (-17.5 pts) | -1.33 | 0.183 | -3.5 bps, p 0.08 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 567 | -0.8 bps (-2.1 pts) | -1.21 | 0.226 | -2.2 bps, p 0.04 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,630 | -2.4 bps (-5.9 pts) | -1.20 | 0.231 | +1.6 bps, p 0.82 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,699 | +2.0 bps (+5.0 pts) | +1.20 | 0.232 | +1.2 bps, p 0.25 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 722 | -2.5 bps (-15.1 pts) | -1.13 | 0.260 | -2.8 bps, p 0.25 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 196 | +1.4 bps (+8.5 pts) | +1.11 | 0.268 | +2.5 bps, p 0.17 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-52.6 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 503 | +0.9 bps (+5.4 pts) | +1.05 | 0.294 | +2.7 bps, p 0.97 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 502 | +0.8 bps (+2.0 pts) | +1.01 | 0.311 | -0.8 bps, p 0.69 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 168 | +14.4 bps (+88.1 pts) | +0.99 | 0.325 | +35.0 bps, p 0.01 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,700 | +1.6 bps (+4.1 pts) | +0.97 | 0.332 | -0.0 bps, p 0.51 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 497 | +0.8 bps (+4.9 pts) | +0.90 | 0.370 | +1.4 bps, p 0.21 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 275 | +0.8 bps (+2.1 pts) | +0.87 | 0.387 | -0.9 bps, p 0.66 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 137 | -1.0 bps (-2.4 pts) | -0.82 | 0.412 | -2.1 bps, p 0.18 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 722 | +1.4 bps (+3.6 pts) | +0.81 | 0.421 | +2.0 bps, p 0.27 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,714 | +1.7 bps (+10.4 pts) | +0.78 | 0.436 | +1.6 bps, p 0.26 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 496 | +0.7 bps (+4.1 pts) | +0.74 | 0.458 | +1.7 bps, p 0.14 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 496 | -0.6 bps (-3.4 pts) | -0.74 | 0.462 | -2.8 bps, p 0.97 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | +0.7 bps (+1.7 pts) | +0.69 | 0.489 | +0.0 bps, p 0.50 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,672 | +1.2 bps (+3.0 pts) | +0.69 | 0.489 | -2.2 bps, p 0.90 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 496 | +0.4 bps (+1.1 pts) | +0.64 | 0.520 | -0.7 bps, p 0.72 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 392 | +0.5 bps (+1.3 pts) | +0.64 | 0.521 | +1.6 bps, p 0.83 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 224 | -0.7 bps (-4.5 pts) | -0.63 | 0.528 | -0.3 bps, p 0.45 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,714 | -1.3 bps (-8.1 pts) | -0.62 | 0.534 | -5.1 bps, p 0.97 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 722 | -0.7 bps (-4.4 pts) | -0.61 | 0.540 | -1.7 bps, p 0.20 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | +0.7 bps (+4.6 pts) | +0.60 | 0.552 | +1.0 bps, p 0.37 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 721 | +0.6 bps (+3.9 pts) | +0.57 | 0.571 | +3.1 bps, p 0.91 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 924 | +2.9 bps (+18.0 pts) | +0.52 | 0.600 | +7.6 bps, p 0.12 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 502 | +0.5 bps (+2.9 pts) | +0.52 | 0.601 | -0.6 bps, p 0.62 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 224 | +0.6 bps (+1.4 pts) | +0.52 | 0.603 | -0.1 bps, p 0.51 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,700 | -1.0 bps (-6.3 pts) | -0.48 | 0.630 | -6.6 bps, p 0.99 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 275 | -0.5 bps (-3.3 pts) | -0.48 | 0.631 | -1.4 bps, p 0.28 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,715 | +0.9 bps (+5.8 pts) | +0.48 | 0.633 | -0.7 bps, p 0.63 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +0.3 bps (+2.0 pts) | +0.45 | 0.650 | +0.4 bps, p 0.39 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 359 | -4.1 bps (-10.4 pts) | -0.38 | 0.702 | +10.0 bps, p 0.86 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 722 | +0.4 bps (+0.9 pts) | +0.34 | 0.735 | +1.8 bps, p 0.82 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 722 | +0.3 bps (+0.8 pts) | +0.33 | 0.741 | -0.8 bps, p 0.67 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,693 | +0.6 bps (+1.4 pts) | +0.31 | 0.758 | -1.3 bps, p 0.78 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 924 | +1.0 bps (+2.5 pts) | +0.27 | 0.788 | +2.7 bps, p 0.27 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,694 | -0.4 bps (-1.1 pts) | -0.26 | 0.792 | -0.2 bps, p 0.44 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 126 | +0.4 bps (+2.6 pts) | +0.25 | 0.800 | -3.7 bps, p 0.86 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,683 | -0.4 bps (-1.1 pts) | -0.25 | 0.804 | +2.1 bps, p 0.88 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,700 | +0.4 bps (+0.9 pts) | +0.21 | 0.834 | -1.8 bps, p 0.85 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,580 | -0.6 bps (-3.6 pts) | -0.18 | 0.857 | -3.2 bps, p 0.78 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 392 | +0.2 bps (+1.0 pts) | +0.18 | 0.857 | +1.1 bps, p 0.72 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,715 | +0.3 bps (+1.5 pts) | +0.13 | 0.900 | +1.9 bps, p 0.78 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,700 | -0.1 bps (-0.4 pts) | -0.08 | 0.935 | +1.3 bps, p 0.77 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,644 | -0.1 bps (-0.8 pts) | -0.06 | 0.951 | -1.6 bps, p 0.74 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.008206156061460381}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.14327157141782346}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.46127655720074107}
- D4 NIFTY:  {"p_discovery": 0.044244541533779456}
- D5 NIFTY:  {"p_discovery": 0.9736659107192189}
- D6 NIFTY:  {"p_discovery": 0.4729498681780356}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.8, "mean_vix": 19.66}
- H1 NIFTY:  {"p_discovery": 0.6078449181501479}
- H2 NIFTY:  {"p_discovery": 0.7683825804182198}
- H3 NIFTY:  {"p_discovery": 0.396972805121436}
- M1 NIFTY:  {"p_discovery": 0.11738502719383834}
- M2 NIFTY:  {"p_discovery": 0.784587237702453}
- M3 NIFTY:  {"p_discovery": 0.0019301253282653441}
- G-ES NIFTY:  {"p_discovery": 0.001064670721070365}
- G-NQ NIFTY:  {"p_discovery": 8.496698022424944e-06}
- G-SPX NIFTY:  {"p_discovery": 0.00034350261129170923}
- G-NASDAQ NIFTY:  {"p_discovery": 8.409296654680171e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0012407080154911508}
- G-N225 NIFTY:  {"p_discovery": 0.31089434373350183}
- G-HSI NIFTY:  {"p_discovery": 0.30668741783474945}
- G-KOSPI NIFTY:  {"p_discovery": 0.0879912253104534}
- G-SSE NIFTY:  {"p_discovery": 0.7173674918233495}
- G-STOXX NIFTY:  {"p_discovery": 0.5595837536466677}
- G-DAX NIFTY:  {"p_discovery": 0.5602396146897125}
- G-FTSE NIFTY:  {"p_discovery": 0.8192451762820516}
- G-USVIX NIFTY:  {"p_discovery": 0.007549772541873372}
- G-DXY NIFTY:  {"p_discovery": 0.3388024976136806}
- G-USDINR NIFTY:  {"p_discovery": 0.014798906643071347}
- G-BRENT NIFTY:  {"p_discovery": 0.2299965529005607}
- G-GOLD NIFTY:  {"p_discovery": 0.47885248060781355}
- G-UST10 NIFTY:  {"p_discovery": 0.11810000483543572}
- L-ES NIFTY:  {"p_discovery": 0.16462372512748547}
- L-NQ NIFTY:  {"p_discovery": 0.24462766829108096}
- L-N225 NIFTY:  {"p_discovery": 0.04717700624933423}
- L-HSI NIFTY:  {"p_discovery": 0.92499448839793}
- L-KOSPI NIFTY:  {"p_discovery": 0.3694049666929546}
- L-SSE NIFTY:  {"p_discovery": 0.2653274091690576}
- L-STOXX NIFTY:  {"p_discovery": 0.27922753954946605}
- L-DAX NIFTY:  {"p_discovery": 0.15716195902808205}
- L-FTSE NIFTY:  {"p_discovery": 0.28484595062908413}
- L-DXY NIFTY:  {"p_discovery": 0.04866857795763217}
- L-USDINR NIFTY:  {"p_discovery": 0.8873866296481595}
- L-BRENT NIFTY:  {"p_discovery": 0.22637894410251622}
- L-GOLD NIFTY:  {"p_discovery": 0.05535398490503847}
- D1 BANKNIFTY:  {"p_discovery": 0.019872883253660725}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.8740134722509024}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017925004}
- D4 BANKNIFTY:  {"p_discovery": 0.03635690552711712}
- D5 BANKNIFTY:  {"p_discovery": 0.9356897440335433}
- D6 BANKNIFTY:  {"p_discovery": 0.834145995342799}
- H1 BANKNIFTY:  {"p_discovery": 0.37910883152084746}
- H2 BANKNIFTY:  {"p_discovery": 0.6183957070185829}
- H3 BANKNIFTY:  {"p_discovery": 0.8627555530505595}
- M1 BANKNIFTY:  {"p_discovery": 0.6893868583551085}
- M2 BANKNIFTY:  {"p_discovery": 0.12516697953661898}
- M3 BANKNIFTY:  {"p_discovery": 0.7181265540572576}
- G-ES BANKNIFTY:  {"p_discovery": 0.38820363493662474}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5544033660263784}
- G-SPX BANKNIFTY:  {"p_discovery": 0.30647567381776464}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.8534240901285286}
- G-DJI BANKNIFTY:  {"p_discovery": 0.2134859911898663}
- G-N225 BANKNIFTY:  {"p_discovery": 0.5663609737664076}
- G-HSI BANKNIFTY:  {"p_discovery": 0.5219797910016257}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.12994345588435913}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8359242809160498}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.023790408207056662}
- G-DAX BANKNIFTY:  {"p_discovery": 0.03557196819414366}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.0026190519613441795}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.1942938324670115}
- G-DXY BANKNIFTY:  {"p_discovery": 0.2122838112824851}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.22528187490502333}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.0028815399087466992}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.004824500365709002}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8513011037755059}
- L-ES BANKNIFTY:  {"p_discovery": 0.8933781889083465}
- L-NQ BANKNIFTY:  {"p_discovery": 0.9911541530394159}
- L-N225 BANKNIFTY:  {"p_discovery": 0.9192109984770114}
- L-HSI BANKNIFTY:  {"p_discovery": 0.745062658385879}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.4118405085252849}
- L-SSE BANKNIFTY:  {"p_discovery": 0.5767618018279006}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.542432222042292}
- L-DAX BANKNIFTY:  {"p_discovery": 0.27965997183292074}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.6360851143941831}
- L-DXY BANKNIFTY:  {"p_discovery": 0.60956657875712}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.906441864609287}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.4941568644424173}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.3045817969052965}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,714 | +0.367 | +0.512 | 0.262 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,714 | +0.383 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,714 | +0.305 | +0.484 | 0.235 | +38.0 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,714 | +0.342 | +0.481 | 0.232 | +37.7 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,714 | +0.277 | +0.443 | 0.196 | +33.9 |
| S&P 500 | NIFTY | opening gap | 4,699 | +0.199 | +0.422 | 0.178 | +31.9 |
| Dow Jones | NIFTY | opening gap | 4,699 | +0.210 | +0.420 | 0.176 | +31.7 |
| Nasdaq Composite | NIFTY | opening gap | 4,699 | +0.174 | +0.418 | 0.175 | +31.6 |
| S&P 500 futures | NIFTY | opening gap | 4,699 | +0.184 | +0.393 | 0.154 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,699 | +0.160 | +0.387 | 0.150 | +28.8 |
| CBOE VIX | BANKNIFTY | opening gap | 4,714 | -0.044 | -0.384 | 0.147 | -28.6 |
| CBOE VIX | NIFTY | opening gap | 4,699 | -0.029 | -0.381 | 0.145 | -28.3 |
| DAX | BANKNIFTY | opening gap | 4,714 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,714 | +0.209 | +0.319 | 0.101 | +23.1 |
| FTSE 100 | BANKNIFTY | opening gap | 4,714 | +0.238 | +0.296 | 0.088 | +21.3 |
| DAX | NIFTY | opening gap | 4,699 | +0.130 | +0.294 | 0.086 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,699 | +0.119 | +0.274 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,699 | +0.132 | +0.247 | 0.061 | +17.5 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,179 | +0.719 | +0.209 | 0.044 | +12.0 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,187 | +0.604 | +0.197 | 0.039 | +11.3 |
| US dollar index | NIFTY | opening gap | 4,699 | -0.185 | -0.151 | 0.023 | -10.5 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,318 | +0.339 | +0.176 | 0.031 | +10.3 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,325 | +0.283 | +0.165 | 0.027 | +9.6 |
| US dollar index | BANKNIFTY | opening gap | 4,714 | -0.240 | -0.130 | 0.017 | -9.0 |
| US 10-year yield | BANKNIFTY | opening gap | 4,714 | +0.032 | +0.096 | 0.009 | +6.6 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 1,771 | +0.098 | +0.145 | 0.021 | +6.2 |
| DAX | BANKNIFTY | same 5 minutes | 1,773 | +0.097 | +0.141 | 0.020 | +6.0 |
| Brent crude | NIFTY | opening gap | 4,699 | +0.021 | +0.087 | 0.008 | +6.0 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 1,783 | +0.082 | +0.140 | 0.020 | +6.0 |
| Brent crude | BANKNIFTY | opening gap | 4,714 | +0.031 | +0.084 | 0.007 | +5.8 |
| DAX | NIFTY | same 5 minutes | 1,785 | +0.081 | +0.136 | 0.018 | +5.8 |
| Gold | BANKNIFTY | same 5 minutes | 3,303 | +0.166 | +0.099 | 0.010 | +5.7 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,217 | -0.033 | -0.087 | 0.007 | -4.9 |
| Gold | NIFTY | same 5 minutes | 3,310 | +0.127 | +0.085 | 0.007 | +4.9 |
| Brent crude | NIFTY | same 5 minutes | 3,223 | -0.029 | -0.084 | 0.007 | -4.8 |
| US 10-year yield | NIFTY | opening gap | 4,699 | +0.014 | +0.066 | 0.004 | +4.5 |
| FTSE 100 | NIFTY | same 5 minutes | 1,782 | +0.068 | +0.102 | 0.010 | +4.3 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 1,770 | +0.072 | +0.099 | 0.010 | +4.2 |
| Gold | NIFTY | opening gap | 4,699 | +0.030 | +0.060 | 0.004 | +4.1 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,809 | +0.115 | +0.081 | 0.006 | +3.4 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,285 | -0.339 | -0.058 | 0.003 | -3.3 |
| Kospi | BANKNIFTY | same 5 minutes | 1,505 | +0.059 | +0.085 | 0.007 | +3.3 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,807 | +0.092 | +0.074 | 0.006 | +3.2 |
| US dollar index | NIFTY | same 5 minutes | 3,292 | -0.280 | -0.054 | 0.003 | -3.1 |
| Kospi | NIFTY | same 5 minutes | 1,500 | +0.048 | +0.074 | 0.006 | +2.9 |
| Nikkei 225 | NIFTY | opening gap | 4,699 | +0.015 | +0.038 | 0.001 | +2.6 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,347 | +0.095 | +0.049 | 0.002 | +2.4 |
| Gold | BANKNIFTY | opening gap | 4,714 | +0.024 | +0.031 | 0.001 | +2.1 |
| Hang Seng | BANKNIFTY | opening gap | 4,714 | +0.017 | +0.029 | 0.001 | +2.0 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,714 | -0.017 | -0.028 | 0.001 | -1.9 |
| Hang Seng | NIFTY | same 5 minutes | 2,337 | +0.058 | +0.035 | 0.001 | +1.7 |
| Hang Seng | NIFTY | opening gap | 4,699 | +0.008 | +0.022 | 0.000 | +1.5 |
| USD/INR | BANKNIFTY | opening gap | 4,714 | -0.037 | -0.021 | 0.000 | -1.4 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,591 | +0.053 | +0.011 | 0.000 | +0.6 |
| USD/INR | NIFTY | opening gap | 4,699 | -0.010 | -0.008 | 0.000 | -0.6 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,714 | +0.004 | +0.007 | 0.000 | +0.5 |
| Kospi | BANKNIFTY | opening gap | 4,714 | -0.004 | -0.006 | 0.000 | -0.4 |
| Kospi | NIFTY | opening gap | 4,699 | -0.002 | -0.006 | 0.000 | -0.4 |
| Shanghai Composite | NIFTY | opening gap | 4,699 | -0.002 | -0.005 | 0.000 | -0.4 |
| USD/INR | NIFTY | same 5 minutes | 3,598 | +0.016 | +0.004 | 0.000 | +0.2 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,309 | -0.001 | -0.003 | 0.000 | -0.1 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,315 | +0.002 | +0.003 | 0.000 | +0.1 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 13.9 pts/trade vs 4.2 pts of costs (t -3.35, rolling validation -4.3 bps). Per-trade σ 293 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹403,535; smaller accounts are over-betting it.


Experiment record: 71cdbb4eaa4d4394b281b437139f46e3 · 3e00b8a1b85cfc772c1e9b8530eada59383488d5cb79ed2c8516c24cd70dd3b3
