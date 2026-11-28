# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-11-28 18:31 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 27-Nov-2026 (4,709 bars)
- daily BANKNIFTY: 17-Sep-2007 → 27-Nov-2026 (4,724 bars)
- daily INDIAVIX: 03-Mar-2008 → 27-Nov-2026 (4,590 bars)
- hourly NIFTY: 13-Dec-2023 → 27-Nov-2026 (5,075 bars)
- hourly BANKNIFTY: 13-Dec-2023 → 27-Nov-2026 (5,075 bars)
- m5 NIFTY: 31-Aug-2026 → 27-Nov-2026 (4,496 bars)
- m5 BANKNIFTY: 31-Aug-2026 → 27-Nov-2026 (4,496 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,709 | -5.5 bps (-14.1 pts) | -3.33 | 0.001 | -4.2 bps, p 0.01 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,572 | +2.97 vol pts | +6.93 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,695 | +5.9 bps (+15.1 pts) | +3.23 | 0.001 | -4.9 bps, p 1.00 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,708 | +5.8 bps (+15.0 pts) | +2.99 | 0.003 | -3.8 bps, p 0.98 | ✓ |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +1.8 bps (+4.6 pts) | +2.95 | 0.003 | +3.1 bps, p 0.00 | · |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,717 | -5.7 bps (-36.1 pts) | -2.83 | 0.005 | -0.2 bps, p 0.47 | ✓ |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 57 | +20.2 bps (+51.6 pts) | +2.88 | 0.006 | +25.5 bps, p 0.04 | · |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,706 | +4.9 bps (+12.6 pts) | +2.70 | 0.007 | -1.4 bps, p 0.77 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,707 | -5.7 bps (-36.2 pts) | -2.68 | 0.007 | -0.5 bps, p 0.41 | ✓ |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,695 | +5.5 bps (+34.4 pts) | +2.58 | 0.010 | -1.2 bps, p 0.70 | ✓ |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,717 | -5.4 bps (-33.8 pts) | -2.53 | 0.012 | -2.7 bps, p 0.14 | · |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,707 | +4.4 bps (+11.3 pts) | +2.52 | 0.012 | -4.1 bps, p 0.99 | ✓ |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,652 | +4.7 bps (+11.9 pts) | +2.52 | 0.012 | +1.3 bps, p 0.25 | · |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,724 | -5.1 bps (-32.0 pts) | -2.41 | 0.016 | -2.9 bps, p 0.12 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,724 | -4.8 bps (-30.2 pts) | -2.33 | 0.020 | -1.0 bps, p 0.35 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,668 | +4.2 bps (+10.7 pts) | +2.25 | 0.024 | -4.3 bps, p 0.99 | ✓ |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 946 | -7.6 bps (-19.4 pts) | -2.18 | 0.030 | -3.9 bps, p 0.20 | · |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,674 | -4.4 bps (-27.5 pts) | -2.11 | 0.035 | -6.4 bps, p 0.01 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 490 | +1.7 bps (+4.3 pts) | +2.06 | 0.040 | +1.1 bps, p 0.19 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,689 | +3.6 bps (+9.2 pts) | +1.99 | 0.046 | -2.7 bps, p 0.94 | ✓ |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,704 | -4.4 bps (-27.5 pts) | -1.92 | 0.055 | -4.7 bps, p 0.02 | · |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 584 | -1.6 bps (-10.2 pts) | -1.91 | 0.056 | -2.6 bps, p 0.06 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,872 | -4.0 bps (-10.3 pts) | -1.87 | 0.062 | -3.6 bps, p 0.11 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,707 | +3.3 bps (+8.3 pts) | +1.85 | 0.064 | +1.5 bps, p 0.20 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 950 | -8.4 bps (-53.1 pts) | -1.79 | 0.074 | +1.4 bps, p 0.59 | · |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 491 | +1.3 bps (+3.4 pts) | +1.59 | 0.113 | +1.5 bps, p 0.14 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,659 | -2.7 bps (-6.9 pts) | -1.58 | 0.115 | -3.4 bps, p 0.03 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 168 | +18.9 bps (+48.3 pts) | +1.58 | 0.116 | +34.7 bps, p 0.02 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,722 | +3.3 bps (+21.1 pts) | +1.56 | 0.118 | +1.1 bps, p 0.33 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,722 | -3.3 bps (-20.5 pts) | -1.55 | 0.120 | -3.9 bps, p 0.06 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,667 | +3.3 bps (+20.8 pts) | +1.48 | 0.140 | +2.1 bps, p 0.20 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 495 | +1.1 bps (+2.9 pts) | +1.47 | 0.141 | +1.0 bps, p 0.22 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 174 | +1.8 bps (+4.6 pts) | +1.42 | 0.156 | +2.6 bps, p 0.18 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,721 | -3.0 bps (-18.8 pts) | -1.41 | 0.158 | -1.4 bps, p 0.28 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 584 | -1.0 bps (-2.5 pts) | -1.39 | 0.167 | -0.7 bps, p 0.28 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 56 | +12.7 bps (+79.9 pts) | +1.38 | 0.175 | +14.3 bps, p 0.28 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,683 | -2.9 bps (-18.3 pts) | -1.35 | 0.178 | -3.8 bps, p 0.06 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 492 | -1.1 bps (-7.0 pts) | -1.32 | 0.186 | -1.9 bps, p 0.14 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 150 | -1.5 bps (-3.9 pts) | -1.30 | 0.197 | -2.9 bps, p 0.10 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,708 | +2.1 bps (+5.4 pts) | +1.26 | 0.208 | +1.6 bps, p 0.19 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 174 | +1.4 bps (+3.7 pts) | +1.22 | 0.226 | +2.0 bps, p 0.18 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,639 | -2.4 bps (-6.0 pts) | -1.20 | 0.232 | +1.5 bps, p 0.80 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 491 | +1.1 bps (+7.2 pts) | +1.18 | 0.238 | +1.7 bps, p 0.17 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 174 | +1.6 bps (+10.2 pts) | +1.11 | 0.268 | +3.3 bps, p 0.10 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | +2.0 bps (+5.0 pts) | +1.08 | 0.279 | +3.1 bps, p 0.18 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 579 | -8.5 bps (-53.8 pts) | -1.05 | 0.296 | +6.0 bps, p 0.70 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | -2.3 bps (-14.2 pts) | -1.00 | 0.319 | -1.5 bps, p 0.37 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 168 | +14.4 bps (+91.0 pts) | +0.99 | 0.325 | +35.0 bps, p 0.01 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 494 | +0.8 bps (+2.0 pts) | +0.96 | 0.337 | +0.4 bps, p 0.39 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,709 | +1.6 bps (+4.0 pts) | +0.95 | 0.344 | -0.1 bps, p 0.52 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 174 | +1.1 bps (+2.9 pts) | +0.89 | 0.376 | +1.2 bps, p 0.32 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 174 | +1.2 bps (+7.7 pts) | +0.88 | 0.378 | +1.0 bps, p 0.37 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,723 | +1.9 bps (+11.8 pts) | +0.86 | 0.390 | +2.2 bps, p 0.20 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 495 | +0.7 bps (+4.6 pts) | +0.76 | 0.447 | +1.3 bps, p 0.23 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,681 | +1.2 bps (+3.2 pts) | +0.72 | 0.470 | -2.1 bps, p 0.88 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 138 | -1.4 bps (-8.5 pts) | -0.67 | 0.505 | -10.0 bps, p 0.99 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 385 | +0.5 bps (+1.4 pts) | +0.66 | 0.510 | +0.7 bps, p 0.24 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,723 | -1.3 bps (-8.2 pts) | -0.61 | 0.543 | -5.1 bps, p 0.97 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 490 | +0.6 bps (+3.7 pts) | +0.60 | 0.551 | +0.5 bps, p 0.39 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | -0.6 bps (-4.1 pts) | -0.55 | 0.582 | -1.0 bps, p 0.31 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 723 | +0.6 bps (+3.8 pts) | +0.54 | 0.590 | +3.7 bps, p 0.95 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 924 | +2.9 bps (+18.6 pts) | +0.52 | 0.600 | +7.6 bps, p 0.12 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,724 | +0.9 bps (+5.9 pts) | +0.47 | 0.636 | -0.9 bps, p 0.65 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,709 | -1.0 bps (-6.3 pts) | -0.47 | 0.639 | -6.5 bps, p 0.99 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 220 | -0.6 bps (-4.1 pts) | -0.43 | 0.665 | -2.1 bps, p 0.75 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 494 | +0.4 bps (+2.8 pts) | +0.42 | 0.672 | +0.3 bps, p 0.45 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 270 | -0.5 bps (-3.4 pts) | -0.41 | 0.686 | -2.0 bps, p 0.76 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 724 | +0.4 bps (+1.1 pts) | +0.40 | 0.691 | +2.3 bps, p 0.89 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 360 | -4.0 bps (-10.1 pts) | -0.37 | 0.714 | +10.4 bps, p 0.86 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | +0.3 bps (+0.9 pts) | +0.34 | 0.731 | -0.5 bps, p 0.60 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | +0.4 bps (+1.0 pts) | +0.34 | 0.736 | -1.2 bps, p 0.71 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 220 | +0.4 bps (+0.9 pts) | +0.30 | 0.764 | -2.2 bps, p 0.86 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 174 | +0.4 bps (+2.7 pts) | +0.29 | 0.771 | +0.9 bps, p 0.38 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,703 | -0.5 bps (-1.2 pts) | -0.29 | 0.772 | -0.2 bps, p 0.45 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 270 | +0.3 bps (+0.8 pts) | +0.28 | 0.778 | -2.5 bps, p 0.91 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,702 | +0.5 bps (+1.3 pts) | +0.28 | 0.782 | -1.4 bps, p 0.79 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,692 | -0.4 bps (-1.1 pts) | -0.26 | 0.794 | +2.1 bps, p 0.88 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 924 | +0.9 bps (+2.4 pts) | +0.25 | 0.803 | +2.4 bps, p 0.28 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | -0.4 bps (-2.5 pts) | -0.25 | 0.803 | -3.5 bps, p 0.86 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,585 | -0.8 bps (-5.0 pts) | -0.24 | 0.807 | -3.5 bps, p 0.80 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +0.2 bps (+1.0 pts) | +0.20 | 0.841 | +1.0 bps, p 0.71 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 385 | -0.2 bps (-1.1 pts) | -0.18 | 0.856 | -0.0 bps, p 0.50 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,709 | +0.3 bps (+0.8 pts) | +0.18 | 0.859 | -1.9 bps, p 0.86 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 492 | -0.1 bps (-0.3 pts) | -0.15 | 0.881 | -0.7 bps, p 0.74 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,724 | +0.3 bps (+1.8 pts) | +0.14 | 0.888 | +1.9 bps, p 0.79 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,709 | -0.1 bps (-0.3 pts) | -0.07 | 0.947 | +1.5 bps, p 0.79 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,653 | -0.1 bps (-0.8 pts) | -0.05 | 0.956 | -1.7 bps, p 0.76 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.008395328200614218}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.14128437898029914}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.4643983304910692}
- D4 NIFTY:  {"p_discovery": 0.044244541533779456}
- D5 NIFTY:  {"p_discovery": 0.9736659107192189}
- D6 NIFTY:  {"p_discovery": 0.4729498681780356}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.8, "mean_vix": 19.66}
- H1 NIFTY:  {"p_discovery": 0.5328519272930371}
- H2 NIFTY:  {"p_discovery": 0.6539796247594343}
- H3 NIFTY:  {"p_discovery": 0.4853648881736708}
- M1 NIFTY:  {"p_discovery": 0.03964791552782766}
- M2 NIFTY:  {"p_discovery": 0.5294247433788258}
- M3 NIFTY:  {"p_discovery": 0.11101402322342913}
- G-ES NIFTY:  {"p_discovery": 0.00105006898299885}
- G-NQ NIFTY:  {"p_discovery": 7.334072366484291e-06}
- G-SPX NIFTY:  {"p_discovery": 0.00035633660055339706}
- G-NASDAQ NIFTY:  {"p_discovery": 8.576397425956473e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0013122515381738596}
- G-N225 NIFTY:  {"p_discovery": 0.3179311039212872}
- G-HSI NIFTY:  {"p_discovery": 0.3150881842477098}
- G-KOSPI NIFTY:  {"p_discovery": 0.09511614980609091}
- G-SSE NIFTY:  {"p_discovery": 0.7049531682524501}
- G-STOXX NIFTY:  {"p_discovery": 0.5768510923253515}
- G-DAX NIFTY:  {"p_discovery": 0.5657672145029823}
- G-FTSE NIFTY:  {"p_discovery": 0.7902691495647501}
- G-USVIX NIFTY:  {"p_discovery": 0.007548242885283596}
- G-DXY NIFTY:  {"p_discovery": 0.32697388975544417}
- G-USDINR NIFTY:  {"p_discovery": 0.015266713792543168}
- G-BRENT NIFTY:  {"p_discovery": 0.2256985264852706}
- G-GOLD NIFTY:  {"p_discovery": 0.4730040354355952}
- G-UST10 NIFTY:  {"p_discovery": 0.12300236995421554}
- L-ES NIFTY:  {"p_discovery": 0.06304982026711271}
- L-NQ NIFTY:  {"p_discovery": 0.2139935189303723}
- L-N225 NIFTY:  {"p_discovery": 0.17345379534953506}
- L-HSI NIFTY:  {"p_discovery": 0.699481229673311}
- L-KOSPI NIFTY:  {"p_discovery": 0.2406407609420376}
- L-SSE NIFTY:  {"p_discovery": 0.3578270781703546}
- L-STOXX NIFTY:  {"p_discovery": 0.43190139847094783}
- L-DAX NIFTY:  {"p_discovery": 0.2679763027826688}
- L-FTSE NIFTY:  {"p_discovery": 0.39378543236544666}
- L-DXY NIFTY:  {"p_discovery": 0.2312167014674995}
- L-USDINR NIFTY:  {"p_discovery": 0.19503105510546145}
- L-BRENT NIFTY:  {"p_discovery": 0.8121161480717533}
- L-GOLD NIFTY:  {"p_discovery": 0.3275291734053925}
- D1 BANKNIFTY:  {"p_discovery": 0.017679862770759957}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.8997611983861157}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.1450243389725967}
- D4 BANKNIFTY:  {"p_discovery": 0.034807299726881194}
- D5 BANKNIFTY:  {"p_discovery": 0.9356897440335433}
- D6 BANKNIFTY:  {"p_discovery": 0.834145995342799}
- H1 BANKNIFTY:  {"p_discovery": 0.3133112777700425}
- H2 BANKNIFTY:  {"p_discovery": 0.4391120824195636}
- H3 BANKNIFTY:  {"p_discovery": 0.7350985608155419}
- M1 BANKNIFTY:  {"p_discovery": 0.13954318763225443}
- M2 BANKNIFTY:  {"p_discovery": 0.04786873371205331}
- M3 BANKNIFTY:  {"p_discovery": 0.7853482668563544}
- G-ES BANKNIFTY:  {"p_discovery": 0.41107509521699825}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5500671149570507}
- G-SPX BANKNIFTY:  {"p_discovery": 0.31267166729468304}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.8421947431494732}
- G-DJI BANKNIFTY:  {"p_discovery": 0.20090930540187898}
- G-N225 BANKNIFTY:  {"p_discovery": 0.5652811794977926}
- G-HSI BANKNIFTY:  {"p_discovery": 0.5109011833310414}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.13027851064318838}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8404965715926951}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.02259927321751034}
- G-DAX BANKNIFTY:  {"p_discovery": 0.034158521594706476}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.0022100830172042058}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.1885509615996325}
- G-DXY BANKNIFTY:  {"p_discovery": 0.23750370885465485}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.2088434948105319}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.0025894846497941113}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.0053888160710381}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8292225925996735}
- L-ES BANKNIFTY:  {"p_discovery": 0.5902528718756972}
- L-NQ BANKNIFTY:  {"p_discovery": 0.7066899154183729}
- L-N225 BANKNIFTY:  {"p_discovery": 0.8973244827541544}
- L-HSI BANKNIFTY:  {"p_discovery": 0.8270237087413578}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.9440235576113871}
- L-SSE BANKNIFTY:  {"p_discovery": 0.4476455725173287}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.9122909777653813}
- L-DAX BANKNIFTY:  {"p_discovery": 0.3180616517229246}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.6368984320058663}
- L-DXY BANKNIFTY:  {"p_discovery": 0.44640412398183776}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.23823896447544313}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.429460816702392}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.6436633444825212}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,723 | +0.366 | +0.511 | 0.261 | +40.9 |
| Dow Jones | BANKNIFTY | opening gap | 4,723 | +0.382 | +0.503 | 0.253 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,723 | +0.303 | +0.483 | 0.233 | +37.9 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,723 | +0.341 | +0.480 | 0.231 | +37.6 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,723 | +0.275 | +0.441 | 0.194 | +33.7 |
| S&P 500 | NIFTY | opening gap | 4,708 | +0.199 | +0.421 | 0.177 | +31.8 |
| Dow Jones | NIFTY | opening gap | 4,708 | +0.210 | +0.420 | 0.176 | +31.8 |
| Nasdaq Composite | NIFTY | opening gap | 4,708 | +0.173 | +0.416 | 0.173 | +31.4 |
| S&P 500 futures | NIFTY | opening gap | 4,708 | +0.183 | +0.392 | 0.153 | +29.2 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,708 | +0.158 | +0.385 | 0.148 | +28.6 |
| CBOE VIX | BANKNIFTY | opening gap | 4,723 | -0.044 | -0.383 | 0.147 | -28.5 |
| CBOE VIX | NIFTY | opening gap | 4,708 | -0.029 | -0.380 | 0.145 | -28.2 |
| DAX | BANKNIFTY | opening gap | 4,723 | +0.224 | +0.334 | 0.111 | +24.3 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,723 | +0.208 | +0.317 | 0.101 | +23.0 |
| FTSE 100 | BANKNIFTY | opening gap | 4,723 | +0.238 | +0.295 | 0.087 | +21.3 |
| DAX | NIFTY | opening gap | 4,708 | +0.130 | +0.293 | 0.086 | +21.0 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,708 | +0.118 | +0.273 | 0.075 | +19.5 |
| FTSE 100 | NIFTY | opening gap | 4,708 | +0.131 | +0.247 | 0.061 | +17.5 |
| US dollar index | NIFTY | opening gap | 4,708 | -0.186 | -0.152 | 0.023 | -10.5 |
| US dollar index | BANKNIFTY | opening gap | 4,723 | -0.241 | -0.130 | 0.017 | -9.0 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,152 | +0.495 | +0.156 | 0.024 | +8.9 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,157 | +0.396 | +0.146 | 0.021 | +8.3 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,272 | +0.238 | +0.130 | 0.017 | +7.5 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,276 | +0.189 | +0.121 | 0.015 | +7.0 |
| US 10-year yield | BANKNIFTY | opening gap | 4,723 | +0.032 | +0.095 | 0.009 | +6.6 |
| Brent crude | NIFTY | opening gap | 4,708 | +0.021 | +0.087 | 0.008 | +6.0 |
| Brent crude | BANKNIFTY | opening gap | 4,723 | +0.031 | +0.084 | 0.007 | +5.8 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 1,630 | +0.080 | +0.136 | 0.019 | +5.5 |
| DAX | BANKNIFTY | same 5 minutes | 1,632 | +0.082 | +0.135 | 0.018 | +5.5 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 1,638 | +0.063 | +0.120 | 0.014 | +4.9 |
| DAX | NIFTY | same 5 minutes | 1,640 | +0.064 | +0.119 | 0.014 | +4.8 |
| US 10-year yield | NIFTY | opening gap | 4,708 | +0.014 | +0.065 | 0.004 | +4.5 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,158 | -0.030 | -0.072 | 0.005 | -4.1 |
| Gold | NIFTY | opening gap | 4,708 | +0.030 | +0.059 | 0.003 | +4.0 |
| Gold | BANKNIFTY | same 5 minutes | 3,257 | +0.112 | +0.071 | 0.005 | +4.0 |
| FTSE 100 | NIFTY | same 5 minutes | 1,638 | +0.062 | +0.096 | 0.009 | +3.9 |
| Brent crude | NIFTY | same 5 minutes | 3,161 | -0.025 | -0.069 | 0.005 | -3.9 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 1,630 | +0.066 | +0.092 | 0.008 | +3.7 |
| Gold | NIFTY | same 5 minutes | 3,261 | +0.082 | +0.061 | 0.004 | +3.5 |
| US dollar index | NIFTY | same 5 minutes | 3,237 | -0.274 | -0.051 | 0.003 | -2.9 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,234 | -0.319 | -0.051 | 0.003 | -2.9 |
| Nikkei 225 | NIFTY | opening gap | 4,708 | +0.015 | +0.039 | 0.001 | +2.7 |
| Gold | BANKNIFTY | opening gap | 4,723 | +0.023 | +0.030 | 0.001 | +2.1 |
| Hang Seng | BANKNIFTY | opening gap | 4,723 | +0.017 | +0.029 | 0.001 | +2.0 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,776 | +0.071 | +0.047 | 0.002 | +2.0 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,723 | -0.017 | -0.028 | 0.001 | -1.9 |
| Kospi | BANKNIFTY | same 5 minutes | 1,479 | +0.037 | +0.047 | 0.002 | +1.8 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,776 | +0.054 | +0.042 | 0.002 | +1.8 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,305 | +0.062 | +0.033 | 0.001 | +1.6 |
| Kospi | NIFTY | same 5 minutes | 1,475 | +0.027 | +0.039 | 0.002 | +1.5 |
| Hang Seng | NIFTY | opening gap | 4,708 | +0.008 | +0.022 | 0.000 | +1.5 |
| USD/INR | BANKNIFTY | opening gap | 4,723 | -0.037 | -0.020 | 0.000 | -1.4 |
| USD/INR | NIFTY | same 5 minutes | 3,709 | -0.068 | -0.016 | 0.000 | -1.0 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,311 | -0.011 | -0.024 | 0.001 | -0.8 |
| Hang Seng | NIFTY | same 5 minutes | 2,297 | +0.028 | +0.018 | 0.000 | +0.8 |
| USD/INR | NIFTY | opening gap | 4,708 | -0.009 | -0.008 | 0.000 | -0.5 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,706 | -0.041 | -0.008 | 0.000 | -0.5 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,723 | +0.004 | +0.007 | 0.000 | +0.5 |
| Kospi | BANKNIFTY | opening gap | 4,723 | -0.003 | -0.006 | 0.000 | -0.4 |
| Shanghai Composite | NIFTY | opening gap | 4,708 | -0.002 | -0.005 | 0.000 | -0.4 |
| Kospi | NIFTY | opening gap | 4,708 | -0.002 | -0.005 | 0.000 | -0.3 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,315 | +0.004 | +0.008 | 0.000 | +0.3 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 14.1 pts/trade vs 4.2 pts of costs (t -3.33, rolling validation -4.2 bps). Per-trade σ 298 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹410,805; smaller accounts are over-betting it.


Experiment record: 4da23bed1a7740b5925088b9b5b3d09f · 2a579f6e00db950cc650ad582758590815e48a9a0b1eb399a64a25ea2686184e
