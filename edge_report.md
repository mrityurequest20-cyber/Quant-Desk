# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-10-17 14:05 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 16-Oct-2026 (4,682 bars)
- daily BANKNIFTY: 17-Sep-2007 → 16-Oct-2026 (4,697 bars)
- daily INDIAVIX: 03-Mar-2008 → 16-Oct-2026 (4,563 bars)
- hourly NIFTY: 02-Nov-2023 → 16-Oct-2026 (5,057 bars)
- hourly BANKNIFTY: 02-Nov-2023 → 16-Oct-2026 (5,057 bars)
- m5 NIFTY: 23-Jul-2026 → 16-Oct-2026 (4,496 bars)
- m5 BANKNIFTY: 23-Jul-2026 → 16-Oct-2026 (4,496 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,682 | -5.7 bps (-13.1 pts) | -3.43 | 0.001 | -4.7 bps, p 0.00 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,545 | +3.00 vol pts | +6.97 | 0.000 | p 0.00 | ✓ |
| **REAL BUT BELOW COSTS** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 521 | +1.6 bps (+3.6 pts) | +2.99 | 0.003 | +2.1 bps, p 0.04 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,668 | +5.9 bps (+13.6 pts) | +3.20 | 0.001 | -4.8 bps, p 1.00 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,681 | +5.8 bps (+13.5 pts) | +2.96 | 0.003 | -3.8 bps, p 0.98 | ✓ |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,690 | -5.7 bps (-31.9 pts) | -2.81 | 0.005 | -0.9 bps, p 0.35 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,679 | +5.0 bps (+11.6 pts) | +2.73 | 0.006 | -1.4 bps, p 0.76 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,680 | -5.8 bps (-32.3 pts) | -2.68 | 0.007 | -0.3 bps, p 0.45 | ✓ |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,668 | +5.5 bps (+30.6 pts) | +2.58 | 0.010 | -0.7 bps, p 0.62 | ✓ |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,680 | +4.5 bps (+10.4 pts) | +2.54 | 0.011 | -3.9 bps, p 0.98 | ✓ |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,690 | -5.4 bps (-30.0 pts) | -2.52 | 0.012 | -3.0 bps, p 0.11 | · |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,625 | +4.7 bps (+10.8 pts) | +2.51 | 0.012 | +1.5 bps, p 0.22 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,697 | -5.0 bps (-27.7 pts) | -2.41 | 0.016 | -1.6 bps, p 0.25 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,697 | -5.1 bps (-28.3 pts) | -2.40 | 0.016 | -3.5 bps, p 0.09 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 512 | +1.3 bps (+3.0 pts) | +2.38 | 0.017 | +1.9 bps, p 0.06 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 522 | +1.3 bps (+3.0 pts) | +2.37 | 0.018 | +2.7 bps, p 0.02 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,641 | +4.2 bps (+9.8 pts) | +2.27 | 0.023 | -4.2 bps, p 0.99 | ✓ |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 943 | -7.8 bps (-17.9 pts) | -2.23 | 0.026 | -4.6 bps, p 0.15 | · |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +1.0 bps (+2.4 pts) | +2.03 | 0.043 | +1.8 bps, p 0.05 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,662 | +3.6 bps (+8.4 pts) | +2.00 | 0.046 | -2.6 bps, p 0.93 | ✓ |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,677 | -4.5 bps (-25.2 pts) | -1.98 | 0.048 | -5.2 bps, p 0.01 | · |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,647 | -4.0 bps (-22.4 pts) | -1.94 | 0.052 | -5.5 bps, p 0.02 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 947 | -8.5 bps (-47.5 pts) | -1.80 | 0.072 | +1.6 bps, p 0.60 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,860 | -3.9 bps (-9.0 pts) | -1.80 | 0.072 | -3.6 bps, p 0.12 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,680 | +3.2 bps (+7.3 pts) | +1.80 | 0.073 | +1.2 bps, p 0.26 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +19.0 bps (+44.1 pts) | +1.59 | 0.114 | +34.5 bps, p 0.02 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,695 | -3.3 bps (-18.5 pts) | -1.57 | 0.115 | -4.3 bps, p 0.04 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 220 | -1.3 bps (-7.3 pts) | -1.54 | 0.126 | -0.3 bps, p 0.44 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 512 | +0.9 bps (+5.2 pts) | +1.53 | 0.127 | +0.3 bps, p 0.40 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 526 | +0.8 bps (+1.9 pts) | +1.47 | 0.141 | +0.4 bps, p 0.38 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,632 | -2.5 bps (-5.8 pts) | -1.47 | 0.143 | -2.9 bps, p 0.06 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 113 | +2.1 bps (+11.5 pts) | +1.48 | 0.143 | +4.8 bps, p 0.03 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,640 | +3.3 bps (+18.3 pts) | +1.46 | 0.145 | +2.5 bps, p 0.16 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,695 | +3.1 bps (+17.3 pts) | +1.44 | 0.150 | +0.3 bps, p 0.44 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 232 | +1.1 bps (+2.5 pts) | +1.40 | 0.162 | +1.3 bps, p 0.22 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 232 | +1.1 bps (+2.5 pts) | +1.38 | 0.168 | +0.5 bps, p 0.40 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,694 | -2.9 bps (-16.3 pts) | -1.38 | 0.168 | -1.6 bps, p 0.26 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,656 | -3.0 bps (-16.5 pts) | -1.37 | 0.171 | -3.6 bps, p 0.08 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 522 | +0.9 bps (+4.9 pts) | +1.31 | 0.192 | +1.7 bps, p 0.13 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 511 | +0.8 bps (+1.7 pts) | +1.27 | 0.204 | +1.6 bps, p 0.12 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,681 | +2.1 bps (+4.8 pts) | +1.25 | 0.211 | +1.6 bps, p 0.19 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,612 | -2.4 bps (-5.6 pts) | -1.22 | 0.222 | +1.3 bps, p 0.78 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 722 | -2.6 bps (-14.5 pts) | -1.18 | 0.237 | -4.9 bps, p 0.12 | · |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 55 | +7.2 bps (+16.7 pts) | +1.18 | 0.242 | +14.4 bps, p 0.13 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 406 | -0.8 bps (-4.4 pts) | -1.08 | 0.281 | -0.4 bps, p 0.38 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-48.2 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 275 | -0.8 bps (-4.6 pts) | -0.99 | 0.325 | +0.2 bps, p 0.54 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 521 | +0.6 bps (+3.4 pts) | +0.96 | 0.340 | +0.0 bps, p 0.50 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +14.0 bps (+78.1 pts) | +0.95 | 0.342 | +32.3 bps, p 0.02 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 275 | +0.7 bps (+1.6 pts) | +0.93 | 0.352 | +2.6 bps, p 0.96 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 232 | +0.7 bps (+1.7 pts) | +0.92 | 0.360 | +0.7 bps, p 0.34 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,682 | +1.5 bps (+3.4 pts) | +0.88 | 0.380 | -0.3 bps, p 0.57 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 722 | -1.0 bps (-5.5 pts) | -0.85 | 0.396 | -1.3 bps, p 0.24 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,696 | +1.7 bps (+9.4 pts) | +0.77 | 0.443 | +1.3 bps, p 0.31 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,654 | +1.2 bps (+2.8 pts) | +0.71 | 0.480 | -2.2 bps, p 0.89 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 511 | -0.5 bps (-2.7 pts) | -0.70 | 0.484 | +0.1 bps, p 0.54 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,696 | -1.5 bps (-8.2 pts) | -0.69 | 0.493 | -5.7 bps, p 0.99 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 232 | +0.6 bps (+3.4 pts) | +0.68 | 0.498 | +1.6 bps, p 0.19 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 125 | +0.7 bps (+1.5 pts) | +0.65 | 0.515 | +0.1 bps, p 0.48 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 722 | +1.1 bps (+2.6 pts) | +0.65 | 0.519 | +1.1 bps, p 0.37 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 51 | -3.6 bps (-19.9 pts) | -0.63 | 0.532 | +4.2 bps, p 0.73 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 406 | -0.4 bps (-0.8 pts) | -0.61 | 0.542 | +0.9 bps, p 0.78 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 583 | +0.3 bps (+0.8 pts) | +0.60 | 0.547 | +0.0 bps, p 0.49 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,682 | -1.2 bps (-6.6 pts) | -0.55 | 0.585 | -7.2 bps, p 1.00 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 920 | +2.9 bps (+16.2 pts) | +0.51 | 0.608 | +7.8 bps, p 0.12 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 220 | +0.4 bps (+0.9 pts) | +0.50 | 0.615 | +1.0 bps, p 0.27 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,697 | +0.8 bps (+4.7 pts) | +0.42 | 0.674 | -1.5 bps, p 0.76 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 359 | -4.1 bps (-9.6 pts) | -0.38 | 0.702 | +10.0 bps, p 0.86 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 232 | +0.3 bps (+1.8 pts) | +0.34 | 0.732 | -0.5 bps, p 0.59 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 721 | +0.4 bps (+2.0 pts) | +0.33 | 0.744 | +2.0 bps, p 0.81 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,675 | +0.6 bps (+1.4 pts) | +0.32 | 0.747 | -1.3 bps, p 0.77 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 583 | +0.2 bps (+1.1 pts) | +0.30 | 0.765 | +0.3 bps, p 0.40 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,676 | -0.5 bps (-1.1 pts) | -0.28 | 0.781 | -0.6 bps, p 0.35 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,665 | -0.4 bps (-1.0 pts) | -0.25 | 0.801 | +2.0 bps, p 0.88 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | -0.3 bps (-1.4 pts) | -0.25 | 0.803 | +0.3 bps, p 0.57 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,682 | +0.4 bps (+0.9 pts) | +0.22 | 0.823 | -1.9 bps, p 0.86 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 232 | -0.2 bps (-1.2 pts) | -0.22 | 0.825 | +0.2 bps, p 0.54 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 920 | +0.7 bps (+1.7 pts) | +0.19 | 0.846 | +1.7 bps, p 0.34 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 526 | +0.1 bps (+0.6 pts) | +0.18 | 0.858 | -0.9 bps, p 0.72 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,573 | -0.6 bps (-3.2 pts) | -0.18 | 0.860 | -4.0 bps, p 0.83 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | -0.1 bps (-0.3 pts) | -0.15 | 0.878 | +1.4 bps, p 0.85 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 722 | +0.1 bps (+0.3 pts) | +0.13 | 0.894 | -0.9 bps, p 0.70 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,682 | -0.2 bps (-0.5 pts) | -0.11 | 0.911 | +1.3 bps, p 0.75 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,697 | +0.2 bps (+1.1 pts) | +0.10 | 0.924 | +1.6 bps, p 0.75 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 722 | -0.1 bps (-0.1 pts) | -0.06 | 0.953 | +0.0 bps, p 0.50 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +0.0 bps (+0.1 pts) | +0.03 | 0.976 | +0.5 bps, p 0.66 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,626 | -0.0 bps (-0.2 pts) | -0.01 | 0.989 | -1.4 bps, p 0.72 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.008593314222090073}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.1610916593835373}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.46127655720074107}
- D4 NIFTY:  {"p_discovery": 0.047136020773098704}
- D5 NIFTY:  {"p_discovery": 0.967306127170051}
- D6 NIFTY:  {"p_discovery": 0.4645149934517705}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.803, "mean_vix": 19.68}
- H1 NIFTY:  {"p_discovery": 0.5981375412269906}
- H2 NIFTY:  {"p_discovery": 0.9382390038005444}
- H3 NIFTY:  {"p_discovery": 0.5545681802984175}
- M1 NIFTY:  {"p_discovery": 0.5670592839651102}
- M2 NIFTY:  {"p_discovery": 0.3873242217139931}
- M3 NIFTY:  {"p_discovery": 0.19959127024869164}
- G-ES NIFTY:  {"p_discovery": 0.001044098233700507}
- G-NQ NIFTY:  {"p_discovery": 9.258564247862582e-06}
- G-SPX NIFTY:  {"p_discovery": 0.000392459339662231}
- G-NASDAQ NIFTY:  {"p_discovery": 9.967595167671782e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0011762558104254093}
- G-N225 NIFTY:  {"p_discovery": 0.31872806326459174}
- G-HSI NIFTY:  {"p_discovery": 0.32830144853790527}
- G-KOSPI NIFTY:  {"p_discovery": 0.09281146474093009}
- G-SSE NIFTY:  {"p_discovery": 0.7048667797308908}
- G-STOXX NIFTY:  {"p_discovery": 0.5576570362005746}
- G-DAX NIFTY:  {"p_discovery": 0.5422109629294062}
- G-FTSE NIFTY:  {"p_discovery": 0.8712685681120245}
- G-USVIX NIFTY:  {"p_discovery": 0.008211561605273506}
- G-DXY NIFTY:  {"p_discovery": 0.32787083674203404}
- G-USDINR NIFTY:  {"p_discovery": 0.017487123823860938}
- G-BRENT NIFTY:  {"p_discovery": 0.2241217752306213}
- G-GOLD NIFTY:  {"p_discovery": 0.48476254019870135}
- G-UST10 NIFTY:  {"p_discovery": 0.12397207497916075}
- L-ES NIFTY:  {"p_discovery": 0.5588310418033091}
- L-NQ NIFTY:  {"p_discovery": 0.0507743126068044}
- L-N225 NIFTY:  {"p_discovery": 0.7875227754083082}
- L-HSI NIFTY:  {"p_discovery": 0.12081310163410591}
- L-KOSPI NIFTY:  {"p_discovery": 0.9446081007023369}
- L-SSE NIFTY:  {"p_discovery": 0.3900593680438208}
- L-STOXX NIFTY:  {"p_discovery": 0.04782619312518136}
- L-DAX NIFTY:  {"p_discovery": 0.2036741074901339}
- L-FTSE NIFTY:  {"p_discovery": 0.36688368742103944}
- L-DXY NIFTY:  {"p_discovery": 0.01092190289132451}
- L-USDINR NIFTY:  {"p_discovery": 0.34490241820421336}
- L-BRENT NIFTY:  {"p_discovery": 0.07774159715781755}
- L-GOLD NIFTY:  {"p_discovery": 0.2386924912615012}
- D1 BANKNIFTY:  {"p_discovery": 0.019321388767872334}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.7931215911065235}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017925004}
- D4 BANKNIFTY:  {"p_discovery": 0.032733076954806394}
- D5 BANKNIFTY:  {"p_discovery": 0.9555482757913127}
- D6 BANKNIFTY:  {"p_discovery": 0.8117328613562985}
- H1 BANKNIFTY:  {"p_discovery": 0.5802275468841154}
- H2 BANKNIFTY:  {"p_discovery": 0.7262194060788216}
- H3 BANKNIFTY:  {"p_discovery": 0.5703041000714405}
- M1 BANKNIFTY:  {"p_discovery": 0.33402383067511277}
- M2 BANKNIFTY:  {"p_discovery": 0.6738553188017354}
- M3 BANKNIFTY:  {"p_discovery": 0.6891675253247921}
- G-ES BANKNIFTY:  {"p_discovery": 0.38017040519828393}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5396367603280142}
- G-SPX BANKNIFTY:  {"p_discovery": 0.33015237821171617}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.8309355534417301}
- G-DJI BANKNIFTY:  {"p_discovery": 0.22394428498330046}
- G-N225 BANKNIFTY:  {"p_discovery": 0.5306360788048118}
- G-HSI BANKNIFTY:  {"p_discovery": 0.47099883014366634}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.1332865289642869}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8501486025583481}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.02668647697013532}
- G-DAX BANKNIFTY:  {"p_discovery": 0.0433723714732726}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.0035444012217706235}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.19611847863434317}
- G-DXY BANKNIFTY:  {"p_discovery": 0.2472183807081298}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.24012572340908056}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.0034516053152236054}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.004623037193853899}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8316549352430418}
- L-ES BANKNIFTY:  {"p_discovery": 0.21884021605652076}
- L-NQ BANKNIFTY:  {"p_discovery": 0.30447066448474613}
- L-N225 BANKNIFTY:  {"p_discovery": 0.08336625770936196}
- L-HSI BANKNIFTY:  {"p_discovery": 0.2380667387054479}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.0475204158808861}
- L-SSE BANKNIFTY:  {"p_discovery": 0.6251118224804303}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.43782839572279986}
- L-DAX BANKNIFTY:  {"p_discovery": 0.9242152604434163}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.6901090852587797}
- L-DXY BANKNIFTY:  {"p_discovery": 0.14931024006945967}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.8677953504232809}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.07120775707370716}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.5026853325060576}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,696 | +0.368 | +0.514 | 0.264 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,696 | +0.383 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,696 | +0.307 | +0.487 | 0.237 | +38.2 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,696 | +0.343 | +0.483 | 0.233 | +37.8 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,696 | +0.279 | +0.445 | 0.198 | +34.1 |
| S&P 500 | NIFTY | opening gap | 4,681 | +0.200 | +0.424 | 0.179 | +32.0 |
| Nasdaq Composite | NIFTY | opening gap | 4,681 | +0.175 | +0.421 | 0.177 | +31.8 |
| Dow Jones | NIFTY | opening gap | 4,681 | +0.211 | +0.420 | 0.176 | +31.7 |
| S&P 500 futures | NIFTY | opening gap | 4,681 | +0.185 | +0.394 | 0.155 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,681 | +0.162 | +0.391 | 0.153 | +29.0 |
| CBOE VIX | BANKNIFTY | opening gap | 4,696 | -0.045 | -0.386 | 0.149 | -28.7 |
| CBOE VIX | NIFTY | opening gap | 4,681 | -0.029 | -0.384 | 0.147 | -28.4 |
| DAX | BANKNIFTY | opening gap | 4,696 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,696 | +0.209 | +0.319 | 0.101 | +23.0 |
| FTSE 100 | BANKNIFTY | opening gap | 4,696 | +0.238 | +0.296 | 0.087 | +21.2 |
| DAX | NIFTY | opening gap | 4,681 | +0.130 | +0.294 | 0.087 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,681 | +0.119 | +0.274 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,681 | +0.131 | +0.247 | 0.061 | +17.4 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,268 | +0.567 | +0.206 | 0.043 | +12.1 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,261 | +0.692 | +0.196 | 0.039 | +11.4 |
| US dollar index | NIFTY | opening gap | 4,681 | -0.185 | -0.151 | 0.023 | -10.5 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,454 | +0.269 | +0.173 | 0.030 | +10.3 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,449 | +0.323 | +0.162 | 0.026 | +9.7 |
| US dollar index | BANKNIFTY | opening gap | 4,696 | -0.240 | -0.130 | 0.017 | -8.9 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 2,020 | +0.093 | +0.157 | 0.025 | +7.2 |
| DAX | NIFTY | same 5 minutes | 2,020 | +0.091 | +0.149 | 0.022 | +6.8 |
| US 10-year yield | BANKNIFTY | opening gap | 4,696 | +0.032 | +0.096 | 0.009 | +6.6 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 2,011 | +0.106 | +0.145 | 0.021 | +6.6 |
| Brent crude | NIFTY | opening gap | 4,681 | +0.022 | +0.091 | 0.008 | +6.2 |
| DAX | BANKNIFTY | same 5 minutes | 2,011 | +0.103 | +0.137 | 0.019 | +6.2 |
| Brent crude | BANKNIFTY | opening gap | 4,696 | +0.033 | +0.088 | 0.008 | +6.0 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 2,011 | +0.106 | +0.133 | 0.018 | +6.0 |
| FTSE 100 | NIFTY | same 5 minutes | 2,020 | +0.088 | +0.129 | 0.017 | +5.8 |
| Gold | BANKNIFTY | same 5 minutes | 3,458 | +0.131 | +0.092 | 0.008 | +5.4 |
| Brent crude | NIFTY | same 5 minutes | 3,268 | -0.023 | -0.089 | 0.008 | -5.1 |
| Gold | NIFTY | same 5 minutes | 3,463 | +0.094 | +0.085 | 0.007 | +5.0 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,264 | -0.026 | -0.080 | 0.006 | -4.6 |
| US 10-year yield | NIFTY | opening gap | 4,681 | +0.015 | +0.066 | 0.004 | +4.5 |
| Gold | NIFTY | opening gap | 4,681 | +0.030 | +0.059 | 0.004 | +4.1 |
| US dollar index | NIFTY | same 5 minutes | 3,407 | -0.290 | -0.069 | 0.005 | -4.0 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,402 | -0.313 | -0.058 | 0.003 | -3.4 |
| Kospi | NIFTY | same 5 minutes | 1,471 | +0.032 | +0.084 | 0.007 | +3.2 |
| Hang Seng | NIFTY | same 5 minutes | 2,422 | +0.085 | +0.063 | 0.004 | +3.1 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,435 | +0.105 | +0.061 | 0.004 | +3.0 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,807 | +0.064 | +0.066 | 0.004 | +2.8 |
| Kospi | BANKNIFTY | same 5 minutes | 1,475 | +0.034 | +0.072 | 0.005 | +2.8 |
| Nikkei 225 | NIFTY | opening gap | 4,681 | +0.015 | +0.039 | 0.002 | +2.7 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,810 | +0.070 | +0.056 | 0.003 | +2.4 |
| Gold | BANKNIFTY | opening gap | 4,696 | +0.023 | +0.030 | 0.001 | +2.1 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,696 | -0.018 | -0.029 | 0.001 | -2.0 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,724 | -0.164 | -0.032 | 0.001 | -2.0 |
| Hang Seng | BANKNIFTY | opening gap | 4,696 | +0.017 | +0.029 | 0.001 | +2.0 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,309 | +0.018 | +0.043 | 0.002 | +1.6 |
| Hang Seng | NIFTY | opening gap | 4,681 | +0.008 | +0.021 | 0.000 | +1.4 |
| USD/INR | BANKNIFTY | opening gap | 4,696 | -0.037 | -0.021 | 0.000 | -1.4 |
| USD/INR | NIFTY | same 5 minutes | 3,726 | -0.087 | -0.021 | 0.000 | -1.3 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,316 | +0.010 | +0.019 | 0.000 | +0.7 |
| USD/INR | NIFTY | opening gap | 4,681 | -0.010 | -0.008 | 0.000 | -0.6 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,696 | +0.004 | +0.007 | 0.000 | +0.5 |
| Shanghai Composite | NIFTY | opening gap | 4,681 | -0.003 | -0.006 | 0.000 | -0.4 |
| Kospi | BANKNIFTY | opening gap | 4,696 | -0.004 | -0.006 | 0.000 | -0.4 |
| Kospi | NIFTY | opening gap | 4,681 | -0.002 | -0.005 | 0.000 | -0.4 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 13.1 pts/trade vs 4.2 pts of costs (t -3.43, rolling validation -4.7 bps). Per-trade σ 270 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹373,442; smaller accounts are over-betting it.


Experiment record: a6c489e39b4b424298c285bdb9f44c32 · 5c12ec2ae000e909c5e988b447cd35847bf46b933c7aabc18770356ca348b67f
