# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-11-07 16:35 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 06-Nov-2026 (4,696 bars)
- daily BANKNIFTY: 17-Sep-2007 → 06-Nov-2026 (4,711 bars)
- daily INDIAVIX: 03-Mar-2008 → 06-Nov-2026 (4,577 bars)
- hourly NIFTY: 23-Nov-2023 → 06-Nov-2026 (5,057 bars)
- hourly BANKNIFTY: 23-Nov-2023 → 06-Nov-2026 (5,057 bars)
- m5 NIFTY: 12-Aug-2026 → 06-Nov-2026 (4,496 bars)
- m5 BANKNIFTY: 12-Aug-2026 → 06-Nov-2026 (4,496 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,696 | -5.5 bps (-13.8 pts) | -3.34 | 0.001 | -4.4 bps, p 0.00 | ✓ |
| **PAPER CANDIDATE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +1.7 bps (+4.3 pts) | +3.02 | 0.003 | +1.7 bps, p 0.07 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,559 | +2.98 vol pts | +6.93 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,682 | +5.8 bps (+14.6 pts) | +3.20 | 0.001 | -5.0 bps, p 1.00 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,695 | +5.8 bps (+14.5 pts) | +2.96 | 0.003 | -3.9 bps, p 0.99 | ✓ |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,704 | -5.7 bps (-33.7 pts) | -2.81 | 0.005 | -0.2 bps, p 0.46 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,693 | +4.9 bps (+12.4 pts) | +2.70 | 0.007 | -1.7 bps, p 0.80 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,694 | -5.7 bps (-33.7 pts) | -2.64 | 0.008 | -0.1 bps, p 0.48 | ✓ |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,682 | +5.4 bps (+32.1 pts) | +2.56 | 0.011 | -1.3 bps, p 0.71 | ✓ |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,639 | +4.7 bps (+11.8 pts) | +2.54 | 0.011 | +1.4 bps, p 0.24 | · |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,694 | +4.4 bps (+11.1 pts) | +2.52 | 0.012 | -4.1 bps, p 0.99 | ✓ |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,704 | -5.3 bps (-31.5 pts) | -2.51 | 0.012 | -2.5 bps, p 0.15 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,711 | -5.0 bps (-29.7 pts) | -2.39 | 0.017 | -2.9 bps, p 0.12 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,711 | -4.9 bps (-28.8 pts) | -2.38 | 0.017 | -1.6 bps, p 0.25 | · |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 55 | +15.9 bps (+39.9 pts) | +2.38 | 0.021 | +33.5 bps, p 0.00 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,655 | +4.2 bps (+10.5 pts) | +2.26 | 0.024 | -4.2 bps, p 0.99 | ✓ |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 945 | -7.6 bps (-19.1 pts) | -2.19 | 0.028 | -4.0 bps, p 0.19 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 208 | +2.2 bps (+5.5 pts) | +2.10 | 0.037 | +3.1 bps, p 0.09 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 507 | +1.5 bps (+3.8 pts) | +2.01 | 0.045 | +2.9 bps, p 0.04 | · |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,661 | -4.1 bps (-24.2 pts) | -1.98 | 0.047 | -5.1 bps, p 0.02 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,676 | +3.6 bps (+8.9 pts) | +1.98 | 0.048 | -2.8 bps, p 0.95 | ✓ |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,691 | -4.5 bps (-26.4 pts) | -1.96 | 0.050 | -5.0 bps, p 0.02 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 949 | -8.5 bps (-50.5 pts) | -1.82 | 0.070 | +0.8 bps, p 0.55 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,694 | +3.2 bps (+7.9 pts) | +1.79 | 0.073 | +1.0 bps, p 0.29 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,867 | -3.9 bps (-9.7 pts) | -1.78 | 0.074 | -3.0 bps, p 0.15 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 208 | +2.0 bps (+11.7 pts) | +1.76 | 0.080 | +3.5 bps, p 0.08 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 514 | +1.2 bps (+3.1 pts) | +1.73 | 0.084 | +2.2 bps, p 0.07 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +19.0 bps (+47.7 pts) | +1.59 | 0.114 | +34.5 bps, p 0.02 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,709 | -3.3 bps (-19.3 pts) | -1.56 | 0.120 | -3.9 bps, p 0.06 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 208 | +1.6 bps (+4.1 pts) | +1.56 | 0.120 | +1.9 bps, p 0.20 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 208 | +1.4 bps (+3.5 pts) | +1.51 | 0.132 | +1.3 bps, p 0.21 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,646 | -2.6 bps (-6.4 pts) | -1.50 | 0.134 | -3.1 bps, p 0.04 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,654 | +3.3 bps (+19.7 pts) | +1.49 | 0.136 | +2.6 bps, p 0.15 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,709 | +3.2 bps (+18.7 pts) | +1.48 | 0.139 | +0.5 bps, p 0.41 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,708 | -3.0 bps (-17.4 pts) | -1.40 | 0.163 | -1.5 bps, p 0.27 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 52 | +11.5 bps (+67.7 pts) | +1.40 | 0.169 | +37.5 bps, p 0.99 | · |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 509 | +1.0 bps (+2.5 pts) | +1.35 | 0.176 | +0.2 bps, p 0.44 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,670 | -2.9 bps (-17.2 pts) | -1.35 | 0.177 | -3.6 bps, p 0.07 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 513 | +0.9 bps (+2.4 pts) | +1.24 | 0.215 | +0.1 bps, p 0.48 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,626 | -2.4 bps (-5.9 pts) | -1.20 | 0.229 | +1.5 bps, p 0.80 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,695 | +2.0 bps (+5.0 pts) | +1.19 | 0.234 | +1.1 bps, p 0.27 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-51.0 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 220 | -1.2 bps (-6.9 pts) | -1.04 | 0.298 | -0.3 bps, p 0.45 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 722 | -2.2 bps (-13.2 pts) | -1.01 | 0.312 | -2.9 bps, p 0.25 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 582 | -0.7 bps (-4.1 pts) | -0.97 | 0.330 | -3.3 bps, p 0.99 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,696 | +1.6 bps (+4.1 pts) | +0.97 | 0.331 | -0.1 bps, p 0.52 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | +1.1 bps (+6.7 pts) | +0.97 | 0.336 | +2.2 bps, p 0.21 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 513 | +0.8 bps (+4.9 pts) | +0.96 | 0.340 | +0.4 bps, p 0.42 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +14.0 bps (+82.7 pts) | +0.95 | 0.342 | +32.3 bps, p 0.02 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 722 | +1.6 bps (+4.0 pts) | +0.89 | 0.376 | +2.3 bps, p 0.25 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 143 | -1.0 bps (-2.5 pts) | -0.88 | 0.379 | -2.3 bps, p 0.17 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 208 | +1.0 bps (+6.0 pts) | +0.87 | 0.384 | +1.8 bps, p 0.23 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 582 | -0.5 bps (-1.3 pts) | -0.81 | 0.418 | -2.8 bps, p 0.98 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 275 | -0.8 bps (-5.0 pts) | -0.80 | 0.423 | -1.3 bps, p 0.27 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,710 | +1.7 bps (+9.9 pts) | +0.77 | 0.443 | +1.5 bps, p 0.28 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +0.5 bps (+3.1 pts) | +0.76 | 0.445 | +0.9 bps, p 0.27 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 208 | +0.9 bps (+5.1 pts) | +0.76 | 0.450 | +2.0 bps, p 0.16 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 275 | +0.7 bps (+1.8 pts) | +0.73 | 0.464 | +1.1 bps, p 0.33 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,668 | +1.2 bps (+3.0 pts) | +0.69 | 0.487 | -2.2 bps, p 0.89 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,710 | -1.4 bps (-8.1 pts) | -0.64 | 0.521 | -5.3 bps, p 0.98 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 721 | +0.7 bps (+4.2 pts) | +0.63 | 0.527 | +2.7 bps, p 0.88 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 722 | -0.7 bps (-4.3 pts) | -0.63 | 0.532 | -1.7 bps, p 0.19 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 505 | -0.4 bps (-2.6 pts) | -0.62 | 0.539 | -2.9 bps, p 0.98 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | +0.6 bps (+1.4 pts) | +0.59 | 0.556 | -0.3 bps, p 0.54 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 509 | +0.5 bps (+2.9 pts) | +0.58 | 0.562 | +0.6 bps, p 0.37 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 924 | +3.2 bps (+19.1 pts) | +0.57 | 0.566 | +8.5 bps, p 0.10 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 514 | +0.5 bps (+2.7 pts) | +0.55 | 0.584 | +1.5 bps, p 0.81 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,696 | -1.1 bps (-6.4 pts) | -0.50 | 0.616 | -6.9 bps, p 1.00 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,711 | +1.0 bps (+5.7 pts) | +0.49 | 0.624 | -0.8 bps, p 0.64 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 505 | +0.3 bps (+0.7 pts) | +0.45 | 0.649 | -1.5 bps, p 0.87 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 220 | +0.5 bps (+1.2 pts) | +0.45 | 0.651 | +0.7 bps, p 0.41 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 722 | +0.5 bps (+1.2 pts) | +0.45 | 0.656 | +1.7 bps, p 0.80 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 359 | -4.1 bps (-10.4 pts) | -0.38 | 0.702 | +10.0 bps, p 0.86 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 507 | +0.3 bps (+1.8 pts) | +0.36 | 0.718 | +1.6 bps, p 0.82 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 722 | +0.4 bps (+0.9 pts) | +0.36 | 0.719 | -0.6 bps, p 0.63 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 399 | +0.3 bps (+0.7 pts) | +0.34 | 0.731 | +1.0 bps, p 0.73 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 924 | +1.2 bps (+3.1 pts) | +0.33 | 0.740 | +3.4 bps, p 0.22 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,689 | +0.6 bps (+1.4 pts) | +0.31 | 0.757 | -1.3 bps, p 0.77 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,690 | -0.5 bps (-1.1 pts) | -0.27 | 0.787 | -0.4 bps, p 0.40 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,679 | -0.4 bps (-1.1 pts) | -0.25 | 0.800 | +2.0 bps, p 0.88 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,696 | +0.4 bps (+0.9 pts) | +0.21 | 0.833 | -1.9 bps, p 0.86 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,578 | -0.6 bps (-3.7 pts) | -0.19 | 0.849 | -3.4 bps, p 0.80 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,711 | +0.2 bps (+1.3 pts) | +0.11 | 0.909 | +1.7 bps, p 0.76 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 399 | -0.1 bps (-0.6 pts) | -0.11 | 0.910 | +0.7 bps, p 0.66 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,696 | -0.1 bps (-0.4 pts) | -0.09 | 0.932 | +1.3 bps, p 0.75 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,640 | -0.1 bps (-0.6 pts) | -0.04 | 0.967 | -1.7 bps, p 0.75 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 125 | -0.1 bps (-0.3 pts) | -0.03 | 0.972 | -3.8 bps, p 0.89 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.008796411138690313}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.13977695145542793}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.46127655720074107}
- D4 NIFTY:  {"p_discovery": 0.0442445415337794}
- D5 NIFTY:  {"p_discovery": 0.973665910719219}
- D6 NIFTY:  {"p_discovery": 0.4645149934517705}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.801, "mean_vix": 19.67}
- H1 NIFTY:  {"p_discovery": 0.5760193738326678}
- H2 NIFTY:  {"p_discovery": 0.9146779535864289}
- H3 NIFTY:  {"p_discovery": 0.42902923500122037}
- M1 NIFTY:  {"p_discovery": 0.31372157830109354}
- M2 NIFTY:  {"p_discovery": 0.7890408960985223}
- M3 NIFTY:  {"p_discovery": 0.005466520669876816}
- G-ES NIFTY:  {"p_discovery": 0.0010930295603819558}
- G-NQ NIFTY:  {"p_discovery": 8.070040587459628e-06}
- G-SPX NIFTY:  {"p_discovery": 0.0003454650784122512}
- G-NASDAQ NIFTY:  {"p_discovery": 8.768074517683497e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0011034870395457781}
- G-N225 NIFTY:  {"p_discovery": 0.30512080053040247}
- G-HSI NIFTY:  {"p_discovery": 0.30135689630121076}
- G-KOSPI NIFTY:  {"p_discovery": 0.08771230450884408}
- G-SSE NIFTY:  {"p_discovery": 0.7257612266749802}
- G-STOXX NIFTY:  {"p_discovery": 0.568702779835803}
- G-DAX NIFTY:  {"p_discovery": 0.5445962669828607}
- G-FTSE NIFTY:  {"p_discovery": 0.8463617253772349}
- G-USVIX NIFTY:  {"p_discovery": 0.007562290421883826}
- G-DXY NIFTY:  {"p_discovery": 0.3342734444149113}
- G-USDINR NIFTY:  {"p_discovery": 0.014981351531947611}
- G-BRENT NIFTY:  {"p_discovery": 0.22939412858311362}
- G-GOLD NIFTY:  {"p_discovery": 0.4797926587672031}
- G-UST10 NIFTY:  {"p_discovery": 0.1211478163384586}
- L-ES NIFTY:  {"p_discovery": 0.289474348277698}
- L-NQ NIFTY:  {"p_discovery": 0.3303889460839481}
- L-N225 NIFTY:  {"p_discovery": 0.49040472172987193}
- L-HSI NIFTY:  {"p_discovery": 0.8788787458246018}
- L-KOSPI NIFTY:  {"p_discovery": 0.6468099165169118}
- L-SSE NIFTY:  {"p_discovery": 0.293907447914326}
- L-STOXX NIFTY:  {"p_discovery": 0.17475761836339318}
- L-DAX NIFTY:  {"p_discovery": 0.09505227688891336}
- L-FTSE NIFTY:  {"p_discovery": 0.19624865552514814}
- L-DXY NIFTY:  {"p_discovery": 0.0437048220970097}
- L-USDINR NIFTY:  {"p_discovery": 0.3437289334724446}
- L-BRENT NIFTY:  {"p_discovery": 0.10527827828962195}
- L-GOLD NIFTY:  {"p_discovery": 0.08139737383594368}
- D1 BANKNIFTY:  {"p_discovery": 0.021290141064010407}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.8608615706024031}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017924987}
- D4 BANKNIFTY:  {"p_discovery": 0.03635690552711712}
- D5 BANKNIFTY:  {"p_discovery": 0.9356897440335432}
- D6 BANKNIFTY:  {"p_discovery": 0.8117328613562985}
- H1 BANKNIFTY:  {"p_discovery": 0.4677832254155744}
- H2 BANKNIFTY:  {"p_discovery": 0.8233355782793932}
- H3 BANKNIFTY:  {"p_discovery": 0.8695921347053311}
- M1 BANKNIFTY:  {"p_discovery": 0.7552366180642439}
- M2 BANKNIFTY:  {"p_discovery": 0.28324213834335477}
- M3 BANKNIFTY:  {"p_discovery": 0.6404235971223893}
- G-ES BANKNIFTY:  {"p_discovery": 0.3911957720372327}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5319639552292927}
- G-SPX BANKNIFTY:  {"p_discovery": 0.3052875339051955}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.8410044906351295}
- G-DJI BANKNIFTY:  {"p_discovery": 0.21256695374160017}
- G-N225 BANKNIFTY:  {"p_discovery": 0.55605743523473}
- G-HSI BANKNIFTY:  {"p_discovery": 0.5052224188420356}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.13048918417753153}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8566914603547368}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.02228932000115224}
- G-DAX BANKNIFTY:  {"p_discovery": 0.03556825812737546}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.002438669034950856}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.19131086824731974}
- G-DXY BANKNIFTY:  {"p_discovery": 0.2082051028125361}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.23351903277293673}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.0027465405984419206}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.004783616141154462}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8284160492697054}
- L-ES BANKNIFTY:  {"p_discovery": 0.7337807108242049}
- L-NQ BANKNIFTY:  {"p_discovery": 0.9415014532587067}
- L-N225 BANKNIFTY:  {"p_discovery": 0.5874555352223343}
- L-HSI BANKNIFTY:  {"p_discovery": 0.6103146151973109}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.1450517937013821}
- L-SSE BANKNIFTY:  {"p_discovery": 0.5973562339964618}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.6226663045750835}
- L-DAX BANKNIFTY:  {"p_discovery": 0.3057409378350822}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.8326699384352303}
- L-DXY BANKNIFTY:  {"p_discovery": 0.6217889053195036}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.4670390538537187}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.3175746461342616}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.2506318330185595}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,710 | +0.367 | +0.512 | 0.263 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,710 | +0.383 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,710 | +0.305 | +0.485 | 0.235 | +38.0 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,710 | +0.342 | +0.482 | 0.232 | +37.7 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,710 | +0.277 | +0.443 | 0.196 | +33.9 |
| S&P 500 | NIFTY | opening gap | 4,695 | +0.200 | +0.422 | 0.178 | +31.9 |
| Dow Jones | NIFTY | opening gap | 4,695 | +0.211 | +0.420 | 0.177 | +31.8 |
| Nasdaq Composite | NIFTY | opening gap | 4,695 | +0.174 | +0.419 | 0.175 | +31.6 |
| S&P 500 futures | NIFTY | opening gap | 4,695 | +0.184 | +0.393 | 0.154 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,695 | +0.160 | +0.388 | 0.150 | +28.8 |
| CBOE VIX | BANKNIFTY | opening gap | 4,710 | -0.044 | -0.384 | 0.147 | -28.5 |
| CBOE VIX | NIFTY | opening gap | 4,695 | -0.029 | -0.382 | 0.146 | -28.3 |
| DAX | BANKNIFTY | opening gap | 4,710 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,710 | +0.209 | +0.319 | 0.101 | +23.1 |
| FTSE 100 | BANKNIFTY | opening gap | 4,710 | +0.239 | +0.296 | 0.088 | +21.3 |
| DAX | NIFTY | opening gap | 4,695 | +0.130 | +0.294 | 0.087 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,695 | +0.119 | +0.274 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,695 | +0.132 | +0.248 | 0.061 | +17.5 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,237 | +0.713 | +0.205 | 0.042 | +11.9 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,246 | +0.594 | +0.195 | 0.038 | +11.3 |
| US dollar index | NIFTY | opening gap | 4,695 | -0.186 | -0.152 | 0.023 | -10.5 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,387 | +0.337 | +0.173 | 0.030 | +10.2 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,395 | +0.280 | +0.163 | 0.027 | +9.6 |
| US dollar index | BANKNIFTY | opening gap | 4,710 | -0.241 | -0.130 | 0.017 | -9.0 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 1,853 | +0.105 | +0.154 | 0.024 | +6.7 |
| US 10-year yield | BANKNIFTY | opening gap | 4,710 | +0.032 | +0.095 | 0.009 | +6.6 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 1,864 | +0.087 | +0.150 | 0.022 | +6.5 |
| DAX | BANKNIFTY | same 5 minutes | 1,855 | +0.106 | +0.150 | 0.022 | +6.5 |
| DAX | NIFTY | same 5 minutes | 1,866 | +0.089 | +0.147 | 0.022 | +6.4 |
| Brent crude | NIFTY | opening gap | 4,695 | +0.021 | +0.087 | 0.008 | +6.0 |
| Brent crude | BANKNIFTY | opening gap | 4,710 | +0.031 | +0.085 | 0.007 | +5.8 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,264 | -0.033 | -0.091 | 0.008 | -5.2 |
| Gold | BANKNIFTY | same 5 minutes | 3,381 | +0.142 | +0.088 | 0.008 | +5.2 |
| Brent crude | NIFTY | same 5 minutes | 3,271 | -0.029 | -0.089 | 0.008 | -5.1 |
| FTSE 100 | NIFTY | same 5 minutes | 1,861 | +0.072 | +0.109 | 0.012 | +4.7 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 1,851 | +0.078 | +0.108 | 0.012 | +4.7 |
| US 10-year yield | NIFTY | opening gap | 4,695 | +0.014 | +0.065 | 0.004 | +4.5 |
| Gold | NIFTY | same 5 minutes | 3,389 | +0.102 | +0.072 | 0.005 | +4.2 |
| Gold | NIFTY | opening gap | 4,695 | +0.030 | +0.060 | 0.004 | +4.1 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,809 | +0.114 | +0.082 | 0.007 | +3.5 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,351 | -0.326 | -0.057 | 0.003 | -3.3 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,807 | +0.092 | +0.076 | 0.006 | +3.2 |
| US dollar index | NIFTY | same 5 minutes | 3,359 | -0.278 | -0.055 | 0.003 | -3.2 |
| Kospi | BANKNIFTY | same 5 minutes | 1,478 | +0.055 | +0.081 | 0.007 | +3.1 |
| Kospi | NIFTY | same 5 minutes | 1,473 | +0.043 | +0.069 | 0.005 | +2.7 |
| Nikkei 225 | NIFTY | opening gap | 4,695 | +0.015 | +0.038 | 0.001 | +2.6 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,389 | +0.091 | +0.051 | 0.003 | +2.5 |
| Gold | BANKNIFTY | opening gap | 4,710 | +0.024 | +0.031 | 0.001 | +2.2 |
| Hang Seng | BANKNIFTY | opening gap | 4,710 | +0.017 | +0.029 | 0.001 | +2.0 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,710 | -0.017 | -0.028 | 0.001 | -1.9 |
| Hang Seng | NIFTY | same 5 minutes | 2,378 | +0.056 | +0.036 | 0.001 | +1.8 |
| Hang Seng | NIFTY | opening gap | 4,695 | +0.008 | +0.021 | 0.000 | +1.5 |
| USD/INR | BANKNIFTY | opening gap | 4,710 | -0.037 | -0.021 | 0.000 | -1.4 |
| USD/INR | NIFTY | same 5 minutes | 3,672 | -0.052 | -0.012 | 0.000 | -0.7 |
| USD/INR | NIFTY | opening gap | 4,695 | -0.010 | -0.008 | 0.000 | -0.6 |
| Kospi | BANKNIFTY | opening gap | 4,710 | -0.004 | -0.007 | 0.000 | -0.5 |
| Kospi | NIFTY | opening gap | 4,695 | -0.003 | -0.007 | 0.000 | -0.5 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,710 | +0.004 | +0.006 | 0.000 | +0.4 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,666 | -0.035 | -0.007 | 0.000 | -0.4 |
| Shanghai Composite | NIFTY | opening gap | 4,695 | -0.002 | -0.005 | 0.000 | -0.4 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,315 | +0.002 | +0.004 | 0.000 | +0.1 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,309 | -0.000 | -0.000 | 0.000 | -0.0 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 13.8 pts/trade vs 4.2 pts of costs (t -3.34, rolling validation -4.4 bps). Per-trade σ 292 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹403,175; smaller accounts are over-betting it.
- **M3 NIFTY**: 30-minute momentum: trade the last 30 minutes' direction for the next 30. Trade as stated: 4.3 pts/trade vs 4.2 pts of costs (t +3.02, rolling validation +1.7 bps). Per-trade σ 34 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹570,914; smaller accounts are over-betting it.


Experiment record: 4f7426be2d9544e28a974053b5c5a482 · 3f9edf0aaa87039aa8ef9f56d37a5f944e0f0792d7e4cd18de552a598be4216a
