# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-10-03 15:23 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 01-Oct-2026 (4,672 bars)
- daily BANKNIFTY: 17-Sep-2007 → 01-Oct-2026 (4,687 bars)
- daily INDIAVIX: 03-Mar-2008 → 01-Oct-2026 (4,553 bars)
- hourly NIFTY: 26-Oct-2023 → 01-Oct-2026 (5,043 bars)
- hourly BANKNIFTY: 26-Oct-2023 → 01-Oct-2026 (5,043 bars)
- m5 NIFTY: 13-Jul-2026 → 01-Oct-2026 (4,348 bars)
- m5 BANKNIFTY: 13-Jul-2026 → 01-Oct-2026 (4,348 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,672 | -5.7 bps (-12.8 pts) | -3.45 | 0.001 | -4.6 bps, p 0.00 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,535 | +3.01 vol pts | +6.98 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,658 | +5.9 bps (+13.3 pts) | +3.23 | 0.001 | -4.7 bps, p 0.99 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,671 | +5.9 bps (+13.2 pts) | +2.98 | 0.003 | -3.7 bps, p 0.98 | ✓ |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 523 | +1.2 bps (+2.7 pts) | +2.84 | 0.005 | +2.2 bps, p 0.00 | · |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,680 | -5.8 bps (-31.3 pts) | -2.82 | 0.005 | -1.3 bps, p 0.30 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,669 | +5.0 bps (+11.1 pts) | +2.70 | 0.007 | -1.8 bps, p 0.82 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,670 | -5.8 bps (-31.5 pts) | -2.68 | 0.007 | +0.2 bps, p 0.53 | ✓ |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,658 | +5.6 bps (+30.3 pts) | +2.61 | 0.009 | -0.8 bps, p 0.62 | ✓ |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,670 | +4.5 bps (+10.2 pts) | +2.57 | 0.010 | -3.7 bps, p 0.98 | ✓ |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,680 | -5.4 bps (-29.5 pts) | -2.54 | 0.011 | -3.0 bps, p 0.11 | · |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,615 | +4.6 bps (+10.3 pts) | +2.46 | 0.014 | +1.5 bps, p 0.22 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,687 | -5.0 bps (-27.2 pts) | -2.42 | 0.015 | -1.4 bps, p 0.29 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,687 | -5.1 bps (-27.8 pts) | -2.41 | 0.016 | -3.3 bps, p 0.10 | · |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 941 | -8.0 bps (-18.0 pts) | -2.31 | 0.021 | -5.0 bps, p 0.13 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,631 | +4.3 bps (+9.6 pts) | +2.30 | 0.022 | -3.9 bps, p 0.98 | ✓ |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 485 | +1.2 bps (+2.7 pts) | +2.26 | 0.025 | +1.6 bps, p 0.08 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,652 | +3.7 bps (+8.3 pts) | +2.04 | 0.041 | -2.2 bps, p 0.90 | ✓ |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 485 | +1.3 bps (+7.0 pts) | +1.97 | 0.049 | +1.6 bps, p 0.11 | · |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,667 | -4.5 bps (-24.3 pts) | -1.95 | 0.051 | -5.7 bps, p 0.01 | · |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,637 | -4.0 bps (-21.9 pts) | -1.94 | 0.052 | -6.0 bps, p 0.01 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 945 | -8.7 bps (-47.2 pts) | -1.83 | 0.067 | +0.8 bps, p 0.55 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 523 | +1.0 bps (+5.2 pts) | +1.82 | 0.070 | +1.3 bps, p 0.14 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,856 | -3.9 bps (-8.8 pts) | -1.81 | 0.070 | -3.2 bps, p 0.14 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,670 | +3.2 bps (+7.1 pts) | +1.80 | 0.073 | +0.9 bps, p 0.31 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +19.0 bps (+42.7 pts) | +1.59 | 0.114 | +34.5 bps, p 0.02 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,685 | -3.3 bps (-17.8 pts) | -1.55 | 0.120 | -4.7 bps, p 0.03 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 232 | +1.2 bps (+2.8 pts) | +1.52 | 0.131 | +1.7 bps, p 0.16 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 228 | +1.3 bps (+3.0 pts) | +1.50 | 0.134 | +2.5 bps, p 0.09 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,622 | -2.5 bps (-5.6 pts) | -1.46 | 0.144 | -3.4 bps, p 0.04 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,685 | +3.1 bps (+16.9 pts) | +1.45 | 0.148 | +0.2 bps, p 0.46 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,630 | +3.2 bps (+17.7 pts) | +1.44 | 0.150 | +2.4 bps, p 0.17 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 232 | +1.2 bps (+2.6 pts) | +1.42 | 0.156 | +2.3 bps, p 0.09 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,684 | -3.0 bps (-16.2 pts) | -1.40 | 0.163 | -2.5 bps, p 0.17 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,646 | -2.9 bps (-15.9 pts) | -1.35 | 0.178 | -3.6 bps, p 0.08 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 720 | -2.8 bps (-15.5 pts) | -1.29 | 0.197 | -5.6 bps, p 0.09 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,602 | -2.5 bps (-5.7 pts) | -1.28 | 0.200 | +1.1 bps, p 0.74 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 108 | +1.3 bps (+2.9 pts) | +1.27 | 0.206 | -0.5 bps, p 0.59 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,671 | +2.1 bps (+4.7 pts) | +1.26 | 0.206 | +1.3 bps, p 0.24 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 265 | -0.9 bps (-5.1 pts) | -1.22 | 0.223 | +1.3 bps, p 0.80 | ✓ |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 216 | -1.0 bps (-5.6 pts) | -1.18 | 0.239 | +0.5 bps, p 0.62 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 399 | -0.7 bps (-1.5 pts) | -1.16 | 0.245 | -0.1 bps, p 0.45 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 526 | +0.6 bps (+1.2 pts) | +1.14 | 0.255 | +1.5 bps, p 0.07 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 572 | +0.5 bps (+1.2 pts) | +1.13 | 0.259 | +0.1 bps, p 0.46 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 113 | +1.4 bps (+7.4 pts) | +1.12 | 0.265 | +1.6 bps, p 0.23 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-47.0 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 509 | -0.6 bps (-3.4 pts) | -0.98 | 0.329 | -0.5 bps, p 0.37 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 572 | +0.6 bps (+3.3 pts) | +0.97 | 0.331 | -0.4 bps, p 0.63 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +14.0 bps (+76.2 pts) | +0.95 | 0.342 | +32.3 bps, p 0.02 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,672 | +1.5 bps (+3.3 pts) | +0.89 | 0.376 | -0.4 bps, p 0.61 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 509 | +0.5 bps (+1.1 pts) | +0.86 | 0.392 | +0.9 bps, p 0.25 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 168 | -0.9 bps (-5.1 pts) | -0.84 | 0.402 | +0.3 bps, p 0.55 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 168 | -0.7 bps (-1.6 pts) | -0.82 | 0.413 | +1.5 bps, p 0.83 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 232 | +0.8 bps (+4.4 pts) | +0.78 | 0.434 | +1.0 bps, p 0.32 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 524 | +0.4 bps (+0.9 pts) | +0.77 | 0.442 | +0.9 bps, p 0.23 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,686 | +1.7 bps (+9.1 pts) | +0.76 | 0.445 | +0.7 bps, p 0.39 | · |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 580 | +0.4 bps (+0.8 pts) | +0.76 | 0.450 | +1.0 bps, p 0.16 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,644 | +1.3 bps (+2.9 pts) | +0.75 | 0.454 | -1.9 bps, p 0.86 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 720 | -0.9 bps (-4.7 pts) | -0.74 | 0.459 | -1.3 bps, p 0.25 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,686 | -1.4 bps (-7.8 pts) | -0.66 | 0.506 | -6.0 bps, p 0.99 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 399 | -0.5 bps (-2.5 pts) | -0.66 | 0.512 | -0.2 bps, p 0.44 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 50 | -3.1 bps (-17.0 pts) | -0.55 | 0.584 | +5.3 bps, p 0.69 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,672 | -1.1 bps (-6.2 pts) | -0.53 | 0.597 | -6.9 bps, p 0.99 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 917 | +2.9 bps (+15.8 pts) | +0.51 | 0.608 | +8.8 bps, p 0.91 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 580 | -0.2 bps (-1.2 pts) | -0.43 | 0.665 | -0.0 bps, p 0.50 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,687 | +0.8 bps (+4.5 pts) | +0.42 | 0.677 | -1.1 bps, p 0.70 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 719 | +0.5 bps (+2.5 pts) | +0.42 | 0.677 | +2.2 bps, p 0.84 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 358 | -4.4 bps (-9.9 pts) | -0.41 | 0.685 | +9.8 bps, p 0.85 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 216 | +0.3 bps (+0.6 pts) | +0.38 | 0.701 | +1.3 bps, p 0.83 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 228 | +0.4 bps (+2.3 pts) | +0.37 | 0.709 | +1.5 bps, p 0.75 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 720 | +0.6 bps (+1.4 pts) | +0.36 | 0.717 | -0.7 bps, p 0.59 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,666 | -0.6 bps (-1.2 pts) | -0.33 | 0.743 | -1.2 bps, p 0.24 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 232 | +0.3 bps (+1.8 pts) | +0.32 | 0.746 | +1.8 bps, p 0.83 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 265 | -0.2 bps (-0.5 pts) | -0.32 | 0.752 | +1.7 bps, p 0.93 | · |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 53 | +1.4 bps (+3.1 pts) | +0.29 | 0.775 | +10.4 bps, p 0.83 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,665 | +0.5 bps (+1.2 pts) | +0.29 | 0.775 | -1.8 bps, p 0.85 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,655 | -0.4 bps (-0.9 pts) | -0.23 | 0.820 | +2.0 bps, p 0.87 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,570 | -0.6 bps (-3.4 pts) | -0.19 | 0.850 | -4.7 bps, p 0.86 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 524 | +0.1 bps (+0.6 pts) | +0.18 | 0.857 | -0.1 bps, p 0.53 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,672 | +0.3 bps (+0.7 pts) | +0.18 | 0.859 | -2.3 bps, p 0.90 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 917 | +0.6 bps (+1.3 pts) | +0.16 | 0.874 | +2.2 bps, p 0.70 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 720 | +0.1 bps (+0.3 pts) | +0.14 | 0.888 | -1.0 bps, p 0.72 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,687 | +0.3 bps (+1.5 pts) | +0.14 | 0.889 | +2.3 bps, p 0.83 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 526 | -0.1 bps (-0.3 pts) | -0.11 | 0.915 | +0.6 bps, p 0.70 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 720 | -0.1 bps (-0.2 pts) | -0.09 | 0.932 | -0.4 bps, p 0.59 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,616 | -0.1 bps (-0.6 pts) | -0.05 | 0.958 | -0.8 bps, p 0.62 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,672 | -0.0 bps (-0.1 pts) | -0.03 | 0.978 | +1.7 bps, p 0.84 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.007521489276128289}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.13627385573713446}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.4498319762377186}
- D4 NIFTY:  {"p_discovery": 0.043130702830444616}
- D5 NIFTY:  {"p_discovery": 0.9651281336324894}
- D6 NIFTY:  {"p_discovery": 0.4645149934517705}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.805, "mean_vix": 19.69}
- H1 NIFTY:  {"p_discovery": 0.5625971869336857}
- H2 NIFTY:  {"p_discovery": 0.956278327353503}
- H3 NIFTY:  {"p_discovery": 0.5277181990787198}
- M1 NIFTY:  {"p_discovery": 0.41777449835482977}
- M2 NIFTY:  {"p_discovery": 0.04507859986375381}
- M3 NIFTY:  {"p_discovery": 0.9425316992809665}
- G-ES NIFTY:  {"p_discovery": 0.0011761472449433469}
- G-NQ NIFTY:  {"p_discovery": 9.389605925164126e-06}
- G-SPX NIFTY:  {"p_discovery": 0.00039095151709936794}
- G-NASDAQ NIFTY:  {"p_discovery": 9.873881335087465e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0010204322497047939}
- G-N225 NIFTY:  {"p_discovery": 0.28366774505739406}
- G-HSI NIFTY:  {"p_discovery": 0.30900286924719084}
- G-KOSPI NIFTY:  {"p_discovery": 0.08264922336402745}
- G-SSE NIFTY:  {"p_discovery": 0.6981565237980015}
- G-STOXX NIFTY:  {"p_discovery": 0.5198041967464913}
- G-DAX NIFTY:  {"p_discovery": 0.5183621619630072}
- G-FTSE NIFTY:  {"p_discovery": 0.9260684334383941}
- G-USVIX NIFTY:  {"p_discovery": 0.008990769037268757}
- G-DXY NIFTY:  {"p_discovery": 0.3805318218790329}
- G-USDINR NIFTY:  {"p_discovery": 0.01967413683888197}
- G-BRENT NIFTY:  {"p_discovery": 0.23082428415259817}
- G-GOLD NIFTY:  {"p_discovery": 0.5089812850026957}
- G-UST10 NIFTY:  {"p_discovery": 0.119159861576565}
- L-ES NIFTY:  {"p_discovery": 0.5897540282687262}
- L-NQ NIFTY:  {"p_discovery": 0.8661271450044535}
- L-N225 NIFTY:  {"p_discovery": 0.13510148159437063}
- L-HSI NIFTY:  {"p_discovery": 0.13921288758185785}
- L-KOSPI NIFTY:  {"p_discovery": 0.686139724087325}
- L-SSE NIFTY:  {"p_discovery": 0.06786498840276765}
- L-STOXX NIFTY:  {"p_discovery": 0.2242581553677718}
- L-DAX NIFTY:  {"p_discovery": 0.4810951023996568}
- L-FTSE NIFTY:  {"p_discovery": 0.40341541372102585}
- L-DXY NIFTY:  {"p_discovery": 0.1544261039205501}
- L-USDINR NIFTY:  {"p_discovery": 0.1239122922708894}
- L-BRENT NIFTY:  {"p_discovery": 0.08345694674177555}
- L-GOLD NIFTY:  {"p_discovery": 0.7515554795785312}
- D1 BANKNIFTY:  {"p_discovery": 0.016450456735701516}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.7506268703756827}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017925004}
- D4 BANKNIFTY:  {"p_discovery": 0.03452281152140772}
- D5 BANKNIFTY:  {"p_discovery": 0.9948436189695389}
- D6 BANKNIFTY:  {"p_discovery": 0.8117328613562985}
- H1 BANKNIFTY:  {"p_discovery": 0.5727639671208665}
- H2 BANKNIFTY:  {"p_discovery": 0.7343907761869739}
- H3 BANKNIFTY:  {"p_discovery": 0.6481370809132377}
- M1 BANKNIFTY:  {"p_discovery": 0.243312362113954}
- M2 BANKNIFTY:  {"p_discovery": 0.40280470375746086}
- M3 BANKNIFTY:  {"p_discovery": 0.502539129141491}
- G-ES BANKNIFTY:  {"p_discovery": 0.3863282111063746}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5606976388636078}
- G-SPX BANKNIFTY:  {"p_discovery": 0.37509715338895433}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.7644031508626173}
- G-DJI BANKNIFTY:  {"p_discovery": 0.272916151067625}
- G-N225 BANKNIFTY:  {"p_discovery": 0.4718899245049464}
- G-HSI BANKNIFTY:  {"p_discovery": 0.5189939763856142}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.1268867305555621}
- G-SSE BANKNIFTY:  {"p_discovery": 0.7894252062852666}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.02523575715184206}
- G-DAX BANKNIFTY:  {"p_discovery": 0.039127063156930784}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.004122659845229542}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.22973592008127547}
- G-DXY BANKNIFTY:  {"p_discovery": 0.28212722918965405}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.2422415051021761}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.0030199461877079884}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.0034109951110296113}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.9418679513194286}
- L-ES BANKNIFTY:  {"p_discovery": 0.240749444922363}
- L-NQ BANKNIFTY:  {"p_discovery": 0.5356961492014087}
- L-N225 BANKNIFTY:  {"p_discovery": 0.010265164965885197}
- L-HSI BANKNIFTY:  {"p_discovery": 0.4672742566273894}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.059320158235309575}
- L-SSE BANKNIFTY:  {"p_discovery": 0.23716880440732965}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.5254492380501617}
- L-DAX BANKNIFTY:  {"p_discovery": 0.7585127291774809}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.9181144550468383}
- L-DXY BANKNIFTY:  {"p_discovery": 0.14870584009567128}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.08311300668586558}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.13714931791090434}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.7320553054276422}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,686 | +0.369 | +0.514 | 0.264 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,686 | +0.383 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,686 | +0.308 | +0.487 | 0.237 | +38.1 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,686 | +0.344 | +0.483 | 0.233 | +37.7 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,686 | +0.280 | +0.446 | 0.199 | +34.1 |
| S&P 500 | NIFTY | opening gap | 4,671 | +0.200 | +0.424 | 0.180 | +32.0 |
| Nasdaq Composite | NIFTY | opening gap | 4,671 | +0.176 | +0.421 | 0.178 | +31.8 |
| Dow Jones | NIFTY | opening gap | 4,671 | +0.211 | +0.420 | 0.177 | +31.6 |
| S&P 500 futures | NIFTY | opening gap | 4,671 | +0.185 | +0.394 | 0.155 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,671 | +0.162 | +0.391 | 0.153 | +29.0 |
| CBOE VIX | BANKNIFTY | opening gap | 4,686 | -0.045 | -0.386 | 0.149 | -28.7 |
| CBOE VIX | NIFTY | opening gap | 4,671 | -0.029 | -0.384 | 0.147 | -28.4 |
| DAX | BANKNIFTY | opening gap | 4,686 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,686 | +0.209 | +0.319 | 0.102 | +23.0 |
| FTSE 100 | BANKNIFTY | opening gap | 4,686 | +0.238 | +0.296 | 0.087 | +21.2 |
| DAX | NIFTY | opening gap | 4,671 | +0.130 | +0.295 | 0.087 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,671 | +0.119 | +0.275 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,671 | +0.131 | +0.247 | 0.061 | +17.4 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,251 | +0.491 | +0.192 | 0.037 | +11.2 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,251 | +0.610 | +0.186 | 0.035 | +10.8 |
| US dollar index | NIFTY | opening gap | 4,671 | -0.185 | -0.151 | 0.023 | -10.5 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,460 | +0.220 | +0.157 | 0.025 | +9.3 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,461 | +0.274 | +0.153 | 0.023 | +9.1 |
| US dollar index | BANKNIFTY | opening gap | 4,686 | -0.241 | -0.130 | 0.017 | -8.9 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 2,030 | +0.106 | +0.178 | 0.032 | +8.1 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 2,026 | +0.123 | +0.163 | 0.027 | +7.4 |
| DAX | NIFTY | same 5 minutes | 2,029 | +0.088 | +0.157 | 0.025 | +7.1 |
| FTSE 100 | NIFTY | same 5 minutes | 1,994 | +0.103 | +0.149 | 0.022 | +6.7 |
| US 10-year yield | BANKNIFTY | opening gap | 4,686 | +0.032 | +0.096 | 0.009 | +6.6 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 1,990 | +0.118 | +0.143 | 0.021 | +6.5 |
| Brent crude | NIFTY | opening gap | 4,671 | +0.022 | +0.091 | 0.008 | +6.2 |
| Brent crude | BANKNIFTY | opening gap | 4,686 | +0.033 | +0.088 | 0.008 | +6.0 |
| DAX | BANKNIFTY | same 5 minutes | 2,025 | +0.094 | +0.132 | 0.017 | +6.0 |
| Gold | NIFTY | same 5 minutes | 3,473 | +0.088 | +0.087 | 0.008 | +5.2 |
| Gold | BANKNIFTY | same 5 minutes | 3,476 | +0.107 | +0.083 | 0.007 | +4.9 |
| US 10-year yield | NIFTY | opening gap | 4,671 | +0.015 | +0.066 | 0.004 | +4.5 |
| Hang Seng | NIFTY | same 5 minutes | 2,382 | +0.106 | +0.088 | 0.008 | +4.3 |
| US dollar index | NIFTY | same 5 minutes | 3,411 | -0.315 | -0.073 | 0.005 | -4.3 |
| Gold | NIFTY | opening gap | 4,671 | +0.030 | +0.059 | 0.004 | +4.1 |
| Brent crude | NIFTY | same 5 minutes | 3,061 | -0.014 | -0.068 | 0.005 | -3.8 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,412 | -0.342 | -0.062 | 0.004 | -3.6 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,395 | +0.118 | +0.073 | 0.005 | +3.6 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,064 | -0.016 | -0.063 | 0.004 | -3.5 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,691 | -0.306 | -0.057 | 0.003 | -3.5 |
| USD/INR | NIFTY | same 5 minutes | 3,687 | -0.218 | -0.052 | 0.003 | -3.2 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,336 | +0.027 | +0.085 | 0.007 | +3.1 |
| Nikkei 225 | NIFTY | opening gap | 4,671 | +0.016 | +0.040 | 0.002 | +2.7 |
| Kospi | NIFTY | same 5 minutes | 1,445 | +0.024 | +0.071 | 0.005 | +2.7 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,745 | +0.046 | +0.053 | 0.003 | +2.2 |
| Kospi | BANKNIFTY | same 5 minutes | 1,448 | +0.026 | +0.057 | 0.003 | +2.2 |
| Gold | BANKNIFTY | opening gap | 4,686 | +0.023 | +0.030 | 0.001 | +2.1 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,686 | -0.018 | -0.029 | 0.001 | -2.0 |
| Hang Seng | BANKNIFTY | opening gap | 4,686 | +0.017 | +0.029 | 0.001 | +2.0 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,747 | +0.053 | +0.047 | 0.002 | +2.0 |
| Hang Seng | NIFTY | opening gap | 4,671 | +0.008 | +0.021 | 0.000 | +1.5 |
| USD/INR | BANKNIFTY | opening gap | 4,686 | -0.038 | -0.021 | 0.000 | -1.4 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,344 | +0.015 | +0.036 | 0.001 | +1.3 |
| USD/INR | NIFTY | opening gap | 4,671 | -0.010 | -0.008 | 0.000 | -0.6 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,686 | +0.004 | +0.007 | 0.000 | +0.5 |
| Kospi | BANKNIFTY | opening gap | 4,686 | -0.004 | -0.007 | 0.000 | -0.5 |
| Shanghai Composite | NIFTY | opening gap | 4,671 | -0.003 | -0.006 | 0.000 | -0.4 |
| Kospi | NIFTY | opening gap | 4,671 | -0.002 | -0.005 | 0.000 | -0.4 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 12.8 pts/trade vs 4.2 pts of costs (t -3.45, rolling validation -4.6 bps). Per-trade σ 261 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹362,943; smaller accounts are over-betting it.


Experiment record: f83da0cbc5784d7da6f2dc82cbef8f78 · e77e4c2f2f7a55b4ec3a81df26cd857755908aaf03cdeba98d2d9ef796d99ff4
