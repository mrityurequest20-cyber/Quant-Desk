# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-10-24 14:24 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 23-Oct-2026 (4,686 bars)
- daily BANKNIFTY: 17-Sep-2007 → 23-Oct-2026 (4,701 bars)
- daily INDIAVIX: 03-Mar-2008 → 23-Oct-2026 (4,567 bars)
- hourly NIFTY: 08-Nov-2023 → 23-Oct-2026 (5,075 bars)
- hourly BANKNIFTY: 08-Nov-2023 → 23-Oct-2026 (5,075 bars)
- m5 NIFTY: 29-Jul-2026 → 23-Oct-2026 (4,496 bars)
- m5 BANKNIFTY: 29-Jul-2026 → 23-Oct-2026 (4,496 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,686 | -5.7 bps (-12.9 pts) | -3.46 | 0.001 | -4.9 bps, p 0.00 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,549 | +2.99 vol pts | +6.95 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,672 | +5.9 bps (+13.4 pts) | +3.23 | 0.001 | -4.7 bps, p 1.00 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,685 | +5.9 bps (+13.3 pts) | +2.99 | 0.003 | -3.6 bps, p 0.98 | ✓ |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 512 | +1.8 bps (+4.2 pts) | +2.89 | 0.004 | +3.5 bps, p 0.01 | · |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,694 | -5.7 bps (-30.7 pts) | -2.78 | 0.005 | -0.4 bps, p 0.43 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,683 | +5.0 bps (+11.3 pts) | +2.73 | 0.006 | -1.4 bps, p 0.76 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,684 | -5.7 bps (-31.1 pts) | -2.66 | 0.008 | -0.3 bps, p 0.44 | ✓ |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 510 | +1.8 bps (+4.0 pts) | +2.63 | 0.009 | +2.2 bps, p 0.11 | ✓ |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,672 | +5.5 bps (+29.8 pts) | +2.58 | 0.010 | -0.8 bps, p 0.63 | ✓ |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,684 | +4.5 bps (+10.2 pts) | +2.55 | 0.011 | -3.8 bps, p 0.98 | ✓ |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,629 | +4.6 bps (+10.5 pts) | +2.50 | 0.012 | +1.5 bps, p 0.22 | · |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,694 | -5.3 bps (-28.9 pts) | -2.49 | 0.013 | -2.4 bps, p 0.17 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,701 | -5.0 bps (-27.2 pts) | -2.44 | 0.015 | -2.1 bps, p 0.19 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,701 | -5.0 bps (-27.3 pts) | -2.38 | 0.018 | -3.1 bps, p 0.11 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,645 | +4.2 bps (+9.6 pts) | +2.28 | 0.022 | -4.1 bps, p 0.99 | ✓ |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 943 | -7.8 bps (-17.5 pts) | -2.23 | 0.026 | -4.6 bps, p 0.15 | · |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 55 | +12.8 bps (+28.9 pts) | +2.14 | 0.037 | +21.8 bps, p 0.06 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,666 | +3.6 bps (+8.2 pts) | +2.01 | 0.045 | -2.5 bps, p 0.93 | ✓ |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,651 | -4.1 bps (-22.2 pts) | -1.98 | 0.048 | -5.8 bps, p 0.01 | · |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,681 | -4.5 bps (-24.4 pts) | -1.97 | 0.049 | -5.6 bps, p 0.01 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 515 | +1.3 bps (+2.8 pts) | +1.88 | 0.060 | +1.4 bps, p 0.20 | · |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +1.0 bps (+2.2 pts) | +1.83 | 0.067 | +2.0 bps, p 0.05 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,862 | -4.0 bps (-8.9 pts) | -1.82 | 0.069 | -3.4 bps, p 0.12 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 947 | -8.5 bps (-46.1 pts) | -1.80 | 0.072 | +1.6 bps, p 0.60 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,684 | +3.2 bps (+7.2 pts) | +1.80 | 0.072 | +1.1 bps, p 0.28 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 512 | +1.3 bps (+7.1 pts) | +1.73 | 0.084 | +2.7 bps, p 0.05 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 503 | +1.2 bps (+2.8 pts) | +1.68 | 0.094 | +3.2 bps, p 0.04 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 109 | +2.4 bps (+13.0 pts) | +1.69 | 0.094 | +5.3 bps, p 0.03 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +19.0 bps (+43.0 pts) | +1.59 | 0.114 | +34.5 bps, p 0.02 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,699 | -3.3 bps (-17.9 pts) | -1.57 | 0.117 | -4.3 bps, p 0.05 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,636 | -2.6 bps (-5.8 pts) | -1.50 | 0.134 | -3.0 bps, p 0.05 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,699 | +3.1 bps (+17.0 pts) | +1.46 | 0.143 | +0.5 bps, p 0.41 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,644 | +3.3 bps (+17.7 pts) | +1.46 | 0.145 | +2.4 bps, p 0.17 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,698 | -3.0 bps (-16.0 pts) | -1.39 | 0.163 | -1.5 bps, p 0.28 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,660 | -2.9 bps (-15.9 pts) | -1.36 | 0.174 | -3.7 bps, p 0.07 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 502 | +0.8 bps (+1.8 pts) | +1.31 | 0.190 | +1.4 bps, p 0.18 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 510 | +1.0 bps (+5.3 pts) | +1.27 | 0.205 | +0.9 bps, p 0.32 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,685 | +2.1 bps (+4.7 pts) | +1.26 | 0.209 | +1.5 bps, p 0.21 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 275 | -1.1 bps (-6.2 pts) | -1.24 | 0.218 | -1.2 bps, p 0.29 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,616 | -2.4 bps (-5.5 pts) | -1.22 | 0.221 | +1.4 bps, p 0.79 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | -2.5 bps (-13.3 pts) | -1.12 | 0.263 | -4.7 bps, p 0.13 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 228 | +1.0 bps (+2.3 pts) | +1.11 | 0.270 | +1.6 bps, p 0.24 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 228 | +0.9 bps (+2.0 pts) | +1.10 | 0.271 | +1.6 bps, p 0.18 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-46.8 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 228 | +0.9 bps (+2.1 pts) | +0.99 | 0.321 | +0.9 bps, p 0.35 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 167 | +14.0 bps (+76.0 pts) | +0.95 | 0.342 | +32.3 bps, p 0.02 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,686 | +1.5 bps (+3.3 pts) | +0.88 | 0.378 | -0.4 bps, p 0.59 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | -1.0 bps (-5.6 pts) | -0.88 | 0.379 | -1.6 bps, p 0.20 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | +0.9 bps (+5.1 pts) | +0.87 | 0.388 | +3.3 bps, p 0.90 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 220 | -0.9 bps (-5.0 pts) | -0.85 | 0.394 | +0.8 bps, p 0.62 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,700 | +1.7 bps (+9.4 pts) | +0.79 | 0.430 | +1.6 bps, p 0.27 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | +0.7 bps (+1.6 pts) | +0.75 | 0.456 | +2.3 bps, p 0.85 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | +1.3 bps (+2.9 pts) | +0.73 | 0.469 | +1.5 bps, p 0.33 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,658 | +1.2 bps (+2.8 pts) | +0.72 | 0.473 | -2.1 bps, p 0.88 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,700 | -1.4 bps (-7.6 pts) | -0.65 | 0.516 | -5.7 bps, p 0.99 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 515 | +0.5 bps (+2.5 pts) | +0.61 | 0.543 | +0.7 bps, p 0.37 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 228 | +0.6 bps (+3.4 pts) | +0.59 | 0.553 | +2.7 bps, p 0.87 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,686 | -1.1 bps (-6.0 pts) | -0.51 | 0.610 | -6.8 bps, p 0.99 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 920 | +2.8 bps (+15.1 pts) | +0.49 | 0.623 | +7.5 bps, p 0.13 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 502 | +0.3 bps (+1.7 pts) | +0.46 | 0.646 | -0.5 bps, p 0.63 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,701 | +0.9 bps (+4.7 pts) | +0.44 | 0.661 | -1.3 bps, p 0.72 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | -0.3 bps (-1.4 pts) | -0.42 | 0.677 | -0.0 bps, p 0.49 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 359 | -4.1 bps (-9.4 pts) | -0.38 | 0.702 | +10.0 bps, p 0.86 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,679 | +0.6 bps (+1.4 pts) | +0.33 | 0.743 | -1.3 bps, p 0.77 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 50 | +2.2 bps (+11.7 pts) | +0.32 | 0.753 | +14.9 bps, p 0.90 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,680 | -0.5 bps (-1.0 pts) | -0.27 | 0.785 | -0.5 bps, p 0.39 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,669 | -0.4 bps (-0.9 pts) | -0.25 | 0.804 | +2.0 bps, p 0.88 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,686 | +0.4 bps (+0.9 pts) | +0.23 | 0.819 | -1.9 bps, p 0.85 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,575 | -0.6 bps (-3.5 pts) | -0.20 | 0.845 | -3.9 bps, p 0.83 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 723 | +0.2 bps (+1.1 pts) | +0.18 | 0.857 | +1.6 bps, p 0.75 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 228 | +0.2 bps (+1.0 pts) | +0.17 | 0.863 | +2.0 bps, p 0.84 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 920 | +0.6 bps (+1.4 pts) | +0.17 | 0.869 | +1.4 bps, p 0.37 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 573 | -0.1 bps (-0.5 pts) | -0.14 | 0.889 | -1.2 bps, p 0.79 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,686 | -0.2 bps (-0.5 pts) | -0.13 | 0.897 | +1.0 bps, p 0.72 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 399 | -0.1 bps (-0.2 pts) | -0.12 | 0.906 | +0.8 bps, p 0.68 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 275 | -0.1 bps (-0.2 pts) | -0.11 | 0.915 | +0.8 bps, p 0.65 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 220 | +0.1 bps (+0.2 pts) | +0.10 | 0.917 | +0.8 bps, p 0.62 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 724 | -0.1 bps (-0.2 pts) | -0.09 | 0.932 | +0.1 bps, p 0.53 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,701 | +0.2 bps (+0.9 pts) | +0.08 | 0.933 | +1.5 bps, p 0.73 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 399 | -0.1 bps (-0.3 pts) | -0.08 | 0.938 | +0.1 bps, p 0.52 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | -0.1 bps (-0.2 pts) | -0.08 | 0.940 | -1.6 bps, p 0.82 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 228 | +0.1 bps (+0.4 pts) | +0.07 | 0.941 | +0.7 bps, p 0.61 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 131 | +0.1 bps (+0.2 pts) | +0.06 | 0.950 | -0.2 bps, p 0.54 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,630 | -0.1 bps (-0.4 pts) | -0.04 | 0.971 | -1.8 bps, p 0.77 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 573 | -0.0 bps (-0.0 pts) | -0.04 | 0.972 | -1.2 bps, p 0.80 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 503 | +0.0 bps (+0.0 pts) | +0.01 | 0.992 | +2.5 bps, p 0.91 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.008679577771228979}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.14850950711094998}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.46127655720074107}
- D4 NIFTY:  {"p_discovery": 0.04713602077309866}
- D5 NIFTY:  {"p_discovery": 0.9673061271700512}
- D6 NIFTY:  {"p_discovery": 0.4645149934517705}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.802, "mean_vix": 19.67}
- H1 NIFTY:  {"p_discovery": 0.5882172708501375}
- H2 NIFTY:  {"p_discovery": 0.8748909634796245}
- H3 NIFTY:  {"p_discovery": 0.5278176837631019}
- M1 NIFTY:  {"p_discovery": 0.09053039511693937}
- M2 NIFTY:  {"p_discovery": 0.832094085153382}
- M3 NIFTY:  {"p_discovery": 0.37100998290138354}
- G-ES NIFTY:  {"p_discovery": 0.0010644157461134475}
- G-NQ NIFTY:  {"p_discovery": 9.073012288229268e-06}
- G-SPX NIFTY:  {"p_discovery": 0.00038798768530252513}
- G-NASDAQ NIFTY:  {"p_discovery": 9.852548572925568e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0011951476065886802}
- G-N225 NIFTY:  {"p_discovery": 0.306737004726227}
- G-HSI NIFTY:  {"p_discovery": 0.3163881770071637}
- G-KOSPI NIFTY:  {"p_discovery": 0.08832038581405206}
- G-SSE NIFTY:  {"p_discovery": 0.7226313824914071}
- G-STOXX NIFTY:  {"p_discovery": 0.5543297362866111}
- G-DAX NIFTY:  {"p_discovery": 0.5401903379769807}
- G-FTSE NIFTY:  {"p_discovery": 0.8463125297769362}
- G-USVIX NIFTY:  {"p_discovery": 0.008201214706882731}
- G-DXY NIFTY:  {"p_discovery": 0.3215676588913065}
- G-USDINR NIFTY:  {"p_discovery": 0.01743481495181219}
- G-BRENT NIFTY:  {"p_discovery": 0.2316523422479936}
- G-GOLD NIFTY:  {"p_discovery": 0.4868770628835865}
- G-UST10 NIFTY:  {"p_discovery": 0.11927520138322378}
- L-ES NIFTY:  {"p_discovery": 0.6527382773630678}
- L-NQ NIFTY:  {"p_discovery": 0.030593686303047082}
- L-N225 NIFTY:  {"p_discovery": 0.5089831716799853}
- L-HSI NIFTY:  {"p_discovery": 0.4257660549614683}
- L-KOSPI NIFTY:  {"p_discovery": 0.7561818612771288}
- L-SSE NIFTY:  {"p_discovery": 0.8591346068318554}
- L-STOXX NIFTY:  {"p_discovery": 0.2083197170459009}
- L-DAX NIFTY:  {"p_discovery": 0.34645009901499707}
- L-FTSE NIFTY:  {"p_discovery": 0.499845521243251}
- L-DXY NIFTY:  {"p_discovery": 0.0017128047078220025}
- L-USDINR NIFTY:  {"p_discovery": 0.2811661431528692}
- L-BRENT NIFTY:  {"p_discovery": 0.3612618679809353}
- L-GOLD NIFTY:  {"p_discovery": 0.10230017521950092}
- D1 BANKNIFTY:  {"p_discovery": 0.022581114141305987}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.8189538420944457}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017924987}
- D4 BANKNIFTY:  {"p_discovery": 0.032733076954806394}
- D5 BANKNIFTY:  {"p_discovery": 0.9555482757913127}
- D6 BANKNIFTY:  {"p_discovery": 0.8117328613562985}
- H1 BANKNIFTY:  {"p_discovery": 0.6091084429140151}
- H2 BANKNIFTY:  {"p_discovery": 0.7005767913361537}
- H3 BANKNIFTY:  {"p_discovery": 0.5996275083497232}
- M1 BANKNIFTY:  {"p_discovery": 0.5701872624930516}
- M2 BANKNIFTY:  {"p_discovery": 0.5746532885697312}
- M3 BANKNIFTY:  {"p_discovery": 0.547841282736819}
- G-ES BANKNIFTY:  {"p_discovery": 0.393088105976504}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5520607911765159}
- G-SPX BANKNIFTY:  {"p_discovery": 0.334676754544773}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.7925560685318569}
- G-DJI BANKNIFTY:  {"p_discovery": 0.2093705141768486}
- G-N225 BANKNIFTY:  {"p_discovery": 0.5493501810075747}
- G-HSI BANKNIFTY:  {"p_discovery": 0.48889109169538425}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.1355955650990099}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8585334573124911}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.021574831563691426}
- G-DAX BANKNIFTY:  {"p_discovery": 0.04035910753129187}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.002919244750881449}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.21598477867108865}
- G-DXY BANKNIFTY:  {"p_discovery": 0.2546164471687227}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.2364025451134596}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.0033208061909233}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.005094715813251369}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8084478782567874}
- L-ES BANKNIFTY:  {"p_discovery": 0.0652974035470893}
- L-NQ BANKNIFTY:  {"p_discovery": 0.5542591739509498}
- L-N225 BANKNIFTY:  {"p_discovery": 0.19854228802833762}
- L-HSI BANKNIFTY:  {"p_discovery": 0.8606097013874603}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.06032280524709901}
- L-SSE BANKNIFTY:  {"p_discovery": 0.7865418546673844}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.8227575849169372}
- L-DAX BANKNIFTY:  {"p_discovery": 0.6853325192094395}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.5245343148777392}
- L-DXY BANKNIFTY:  {"p_discovery": 0.12240825030106603}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.49295119101943713}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.32919210998126425}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.44478260140189996}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,700 | +0.368 | +0.513 | 0.264 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,700 | +0.383 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,700 | +0.307 | +0.486 | 0.236 | +38.1 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,700 | +0.343 | +0.482 | 0.233 | +37.8 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,700 | +0.279 | +0.445 | 0.198 | +34.1 |
| S&P 500 | NIFTY | opening gap | 4,685 | +0.200 | +0.423 | 0.179 | +32.0 |
| Nasdaq Composite | NIFTY | opening gap | 4,685 | +0.175 | +0.421 | 0.177 | +31.7 |
| Dow Jones | NIFTY | opening gap | 4,685 | +0.211 | +0.420 | 0.176 | +31.7 |
| S&P 500 futures | NIFTY | opening gap | 4,685 | +0.185 | +0.394 | 0.155 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,685 | +0.161 | +0.390 | 0.152 | +29.0 |
| CBOE VIX | BANKNIFTY | opening gap | 4,700 | -0.044 | -0.386 | 0.149 | -28.6 |
| CBOE VIX | NIFTY | opening gap | 4,685 | -0.029 | -0.383 | 0.147 | -28.4 |
| DAX | BANKNIFTY | opening gap | 4,700 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,700 | +0.209 | +0.318 | 0.101 | +23.0 |
| FTSE 100 | BANKNIFTY | opening gap | 4,700 | +0.238 | +0.296 | 0.087 | +21.2 |
| DAX | NIFTY | opening gap | 4,685 | +0.130 | +0.294 | 0.086 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,685 | +0.118 | +0.274 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,685 | +0.131 | +0.247 | 0.061 | +17.4 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,209 | +0.621 | +0.211 | 0.045 | +12.2 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,205 | +0.751 | +0.211 | 0.045 | +12.2 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,380 | +0.310 | +0.185 | 0.034 | +10.9 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,378 | +0.366 | +0.182 | 0.033 | +10.8 |
| US dollar index | NIFTY | opening gap | 4,685 | -0.185 | -0.151 | 0.023 | -10.5 |
| US dollar index | BANKNIFTY | opening gap | 4,700 | -0.240 | -0.130 | 0.017 | -9.0 |
| DAX | NIFTY | same 5 minutes | 1,982 | +0.101 | +0.149 | 0.022 | +6.7 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 1,981 | +0.094 | +0.147 | 0.022 | +6.6 |
| US 10-year yield | BANKNIFTY | opening gap | 4,700 | +0.032 | +0.096 | 0.009 | +6.6 |
| DAX | BANKNIFTY | same 5 minutes | 1,972 | +0.115 | +0.144 | 0.021 | +6.5 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 1,971 | +0.108 | +0.142 | 0.020 | +6.3 |
| Brent crude | NIFTY | opening gap | 4,685 | +0.022 | +0.091 | 0.008 | +6.2 |
| Brent crude | BANKNIFTY | opening gap | 4,700 | +0.033 | +0.088 | 0.008 | +6.0 |
| Gold | BANKNIFTY | same 5 minutes | 3,377 | +0.151 | +0.101 | 0.010 | +5.9 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 1,971 | +0.099 | +0.117 | 0.014 | +5.2 |
| Gold | NIFTY | same 5 minutes | 3,378 | +0.109 | +0.088 | 0.008 | +5.1 |
| FTSE 100 | NIFTY | same 5 minutes | 1,981 | +0.084 | +0.111 | 0.012 | +5.0 |
| Brent crude | NIFTY | same 5 minutes | 3,196 | -0.025 | -0.087 | 0.008 | -5.0 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,195 | -0.028 | -0.084 | 0.007 | -4.8 |
| US 10-year yield | NIFTY | opening gap | 4,685 | +0.015 | +0.066 | 0.004 | +4.5 |
| US dollar index | NIFTY | same 5 minutes | 3,343 | -0.326 | -0.072 | 0.005 | -4.2 |
| Gold | NIFTY | opening gap | 4,685 | +0.030 | +0.059 | 0.003 | +4.0 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,808 | +0.093 | +0.089 | 0.008 | +3.8 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,341 | -0.338 | -0.061 | 0.004 | -3.6 |
| Kospi | NIFTY | same 5 minutes | 1,472 | +0.036 | +0.086 | 0.007 | +3.3 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,810 | +0.098 | +0.077 | 0.006 | +3.3 |
| Kospi | BANKNIFTY | same 5 minutes | 1,476 | +0.037 | +0.076 | 0.006 | +2.9 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,392 | +0.099 | +0.058 | 0.003 | +2.8 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,639 | -0.242 | -0.046 | 0.002 | -2.8 |
| USD/INR | NIFTY | same 5 minutes | 3,642 | -0.199 | -0.045 | 0.002 | -2.7 |
| Nikkei 225 | NIFTY | opening gap | 4,685 | +0.015 | +0.039 | 0.002 | +2.7 |
| Hang Seng | NIFTY | same 5 minutes | 2,380 | +0.070 | +0.050 | 0.003 | +2.5 |
| Gold | BANKNIFTY | opening gap | 4,700 | +0.023 | +0.030 | 0.001 | +2.0 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,700 | -0.018 | -0.029 | 0.001 | -2.0 |
| Hang Seng | BANKNIFTY | opening gap | 4,700 | +0.017 | +0.029 | 0.001 | +2.0 |
| Hang Seng | NIFTY | opening gap | 4,685 | +0.008 | +0.021 | 0.000 | +1.4 |
| USD/INR | BANKNIFTY | opening gap | 4,700 | -0.037 | -0.021 | 0.000 | -1.4 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,316 | +0.014 | +0.024 | 0.001 | +0.9 |
| USD/INR | NIFTY | opening gap | 4,685 | -0.009 | -0.008 | 0.000 | -0.6 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,700 | +0.004 | +0.007 | 0.000 | +0.5 |
| Kospi | BANKNIFTY | opening gap | 4,700 | -0.004 | -0.007 | 0.000 | -0.5 |
| Kospi | NIFTY | opening gap | 4,685 | -0.003 | -0.007 | 0.000 | -0.5 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,309 | +0.006 | +0.012 | 0.000 | +0.5 |
| Shanghai Composite | NIFTY | opening gap | 4,685 | -0.003 | -0.006 | 0.000 | -0.4 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 12.9 pts/trade vs 4.2 pts of costs (t -3.46, rolling validation -4.9 bps). Per-trade σ 263 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹363,699; smaller accounts are over-betting it.


Experiment record: 0af4f05329704346a50a11e8abb0cca8 · 3f2b2adc51eb68a0d74847a9b8a55fb879f981b116182262310e0ee987313ed6
