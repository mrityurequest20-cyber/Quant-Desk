# Edge research — NIFTY & BANKNIFTY, with global markets

Generated 2026-11-21 18:11 IST. Data: Yahoo Finance.

- daily NIFTY: 17-Sep-2007 → 20-Nov-2026 (4,705 bars)
- daily BANKNIFTY: 17-Sep-2007 → 20-Nov-2026 (4,720 bars)
- daily INDIAVIX: 03-Mar-2008 → 20-Nov-2026 (4,586 bars)
- hourly NIFTY: 07-Dec-2023 → 20-Nov-2026 (5,075 bars)
- hourly BANKNIFTY: 07-Dec-2023 → 20-Nov-2026 (5,075 bars)
- m5 NIFTY: 25-Aug-2026 → 20-Nov-2026 (4,496 bars)
- m5 BANKNIFTY: 25-Aug-2026 → 20-Nov-2026 (4,496 bars)
- global daily: 18 markets
- global m5: 13 markets

87 pre-registered tests · Benjamini–Hochberg q = 0.10 · rolling validation = newest third · cost hurdle NIFTY 4.2 pts, BANKNIFTY 9.5 pts per round trip

**Validation is re-inspected on every report, so it is not an untouched holdout.** A paper candidate is forward-tested by the paper desk; real money waits for the paper gate (`quantdesk intraday paper-gate`).

Effect/trade is for the side the test states; a negative effect means the edge is the *opposite* side.

| Verdict | ID | Market | Hypothesis | N | Effect/trade | t | p | Rolling validation | BH |
|---|---|---|---|---:|---:|---:|---:|---:|:-:|
| **PAPER CANDIDATE** | D1 | NIFTY | Intraday drift: long from the open to the close, every day | 4,705 | -5.4 bps (-14.1 pts) | -3.30 | 0.001 | -4.1 bps, p 0.01 | ✓ |
| **NEEDS MARGIN** | V1 | NIFTY | Volatility risk premium: India VIX minus the next 21 days' realised vol | 4,568 | +2.97 vol pts | +6.93 | 0.000 | p 0.00 | ✓ |
| **NO EDGE** | G-NQ | NIFTY | Nasdaq 100 futures prior session → trade NIFTY-side with it, open→close | 4,691 | +5.8 bps (+15.1 pts) | +3.20 | 0.001 | -4.9 bps, p 1.00 | ✓ |
| **NO EDGE** | G-NASDAQ | NIFTY | Nasdaq Composite prior session → trade NIFTY-side with it, open→close | 4,704 | +5.8 bps (+14.9 pts) | +2.96 | 0.003 | -3.9 bps, p 0.98 | ✓ |
| **NO EDGE** | M3 | NIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | +1.7 bps (+4.4 pts) | +2.88 | 0.004 | +1.9 bps, p 0.05 | · |
| **NO EDGE** | G-FTSE | BANKNIFTY | FTSE 100 prior session → trade with it, open→close | 4,713 | -5.8 bps (-37.5 pts) | -2.86 | 0.004 | -0.6 bps, p 0.40 | ✓ |
| **NO EDGE** | G-GOLD | BANKNIFTY | Gold prior session → trade with it, open→close | 4,703 | -5.8 bps (-37.8 pts) | -2.72 | 0.007 | -0.7 bps, p 0.38 | ✓ |
| **NO EDGE** | G-DJI | NIFTY | Dow Jones prior session → trade NIFTY-side with it, open→close | 4,702 | +4.9 bps (+12.6 pts) | +2.68 | 0.007 | -1.5 bps, p 0.78 | ✓ |
| **NO EDGE** | G-USDINR | NIFTY | USD/INR prior session → trade NIFTY-side against it, open→close | 4,648 | +4.7 bps (+12.2 pts) | +2.56 | 0.010 | +1.5 bps, p 0.21 | · |
| **NO EDGE** | G-STOXX | BANKNIFTY | Euro Stoxx 50 prior session → trade with it, open→close | 4,713 | -5.4 bps (-35.2 pts) | -2.56 | 0.011 | -2.8 bps, p 0.13 | · |
| **NO EDGE** | G-BRENT | BANKNIFTY | Brent crude prior session → trade against it, open→close | 4,691 | +5.4 bps (+34.8 pts) | +2.54 | 0.011 | -1.5 bps, p 0.74 | ✓ |
| **NO EDGE** | G-SPX | NIFTY | S&P 500 prior session → trade NIFTY-side with it, open→close | 4,703 | +4.4 bps (+11.3 pts) | +2.49 | 0.013 | -4.2 bps, p 0.99 | ✓ |
| **NO EDGE** | G-DAX | BANKNIFTY | DAX prior session → trade with it, open→close | 4,720 | -5.1 bps (-33.3 pts) | -2.44 | 0.015 | -3.4 bps, p 0.09 | · |
| **NO EDGE** | M1 | NIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 57 | +16.9 bps (+43.6 pts) | +2.43 | 0.018 | +20.0 bps, p 0.08 | · |
| **NO EDGE** | D1 | BANKNIFTY | Intraday drift: long from the open to the close, every day | 4,720 | -4.7 bps (-30.4 pts) | -2.28 | 0.022 | -1.1 bps, p 0.33 | · |
| **NO EDGE** | G-ES | NIFTY | S&P 500 futures prior session → trade NIFTY-side with it, open→close | 4,664 | +4.1 bps (+10.6 pts) | +2.22 | 0.026 | -4.5 bps, p 0.99 | ✓ |
| **NO EDGE** | L-USDINR | BANKNIFTY | USD/INR last 30 min → BANKNIFTY next 30 min (against it) | 591 | -1.7 bps (-11.0 pts) | -2.18 | 0.030 | -3.4 bps, p 0.01 | · |
| **NO EDGE** | D4 | NIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 946 | -7.6 bps (-19.5 pts) | -2.18 | 0.030 | -3.9 bps, p 0.20 | · |
| **NO EDGE** | L-ES | NIFTY | S&P 500 futures last 30 min → NIFTY next 30 min (with it) | 499 | +1.6 bps (+4.2 pts) | +2.09 | 0.037 | +1.7 bps, p 0.06 | · |
| **NO EDGE** | G-DXY | BANKNIFTY | US dollar index prior session → trade against it, open→close | 4,670 | -4.3 bps (-27.6 pts) | -2.07 | 0.039 | -6.0 bps, p 0.01 | · |
| **NO EDGE** | L-DXY | NIFTY | US dollar index last 30 min → NIFTY next 30 min (against it) | 500 | +1.6 bps (+4.2 pts) | +2.03 | 0.043 | +1.4 bps, p 0.13 | · |
| **NO EDGE** | L-DAX | NIFTY | DAX last 30 min → NIFTY next 30 min (with it) | 186 | +2.3 bps (+5.9 pts) | +1.98 | 0.049 | +3.7 bps, p 0.07 | · |
| **NO EDGE** | G-USVIX | NIFTY | CBOE VIX prior session → trade NIFTY-side against it, open→close | 4,685 | +3.6 bps (+9.2 pts) | +1.97 | 0.049 | -2.9 bps, p 0.95 | ✓ |
| **NO EDGE** | G-USVIX | BANKNIFTY | CBOE VIX prior session → trade against it, open→close | 4,700 | -4.5 bps (-28.8 pts) | -1.96 | 0.050 | -5.0 bps, p 0.02 | · |
| **NO EDGE** | M1 | BANKNIFTY | Opening-range breakout: first 5m close outside the 30-min range, hold to 15:15 | 54 | +16.4 bps (+106.3 pts) | +1.94 | 0.057 | +31.8 bps, p 0.06 | · |
| **NO EDGE** | D2 | NIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 1,870 | -4.0 bps (-10.2 pts) | -1.83 | 0.068 | -3.4 bps, p 0.13 | · |
| **NO EDGE** | G-KOSPI | NIFTY | Kospi prior session → trade NIFTY-side with it, open→close | 4,703 | +3.2 bps (+8.3 pts) | +1.83 | 0.068 | +1.3 bps, p 0.24 | · |
| **NO EDGE** | D4 | BANKNIFTY | Tuesday (weekly expiry): long open→close on Tuesdays | 950 | -8.4 bps (-54.4 pts) | -1.79 | 0.074 | +1.4 bps, p 0.59 | · |
| **NO EDGE** | L-DAX | BANKNIFTY | DAX last 30 min → BANKNIFTY next 30 min (with it) | 186 | +2.2 bps (+14.2 pts) | +1.74 | 0.083 | +3.5 bps, p 0.09 | · |
| **NO EDGE** | L-NQ | NIFTY | Nasdaq 100 futures last 30 min → NIFTY next 30 min (with it) | 505 | +1.2 bps (+3.1 pts) | +1.61 | 0.108 | +1.3 bps, p 0.12 | · |
| **NO EDGE** | G-SPX | BANKNIFTY | S&P 500 prior session → trade with it, open→close | 4,718 | -3.3 bps (-21.6 pts) | -1.60 | 0.111 | -4.3 bps, p 0.04 | · |
| **NO EDGE** | L-USDINR | NIFTY | USD/INR last 30 min → NIFTY next 30 min (against it) | 591 | -1.1 bps (-2.7 pts) | -1.60 | 0.111 | -1.4 bps, p 0.10 | · |
| **NO EDGE** | D6 | NIFTY | After an India VIX jump > 10%: long the next day open→close | 168 | +18.9 bps (+48.6 pts) | +1.58 | 0.116 | +34.7 bps, p 0.02 | · |
| **NO EDGE** | G-DXY | NIFTY | US dollar index prior session → trade NIFTY-side against it, open→close | 4,655 | -2.6 bps (-6.8 pts) | -1.55 | 0.122 | -3.4 bps, p 0.03 | · |
| **NO EDGE** | G-USDINR | BANKNIFTY | USD/INR prior session → trade against it, open→close | 4,663 | +3.4 bps (+22.1 pts) | +1.53 | 0.127 | +2.4 bps, p 0.16 | · |
| **NO EDGE** | G-KOSPI | BANKNIFTY | Kospi prior session → trade with it, open→close | 4,718 | +3.3 bps (+21.0 pts) | +1.52 | 0.128 | +0.9 bps, p 0.36 | · |
| **NO EDGE** | G-DJI | BANKNIFTY | Dow Jones prior session → trade with it, open→close | 4,717 | -3.0 bps (-19.7 pts) | -1.44 | 0.149 | -2.0 bps, p 0.21 | · |
| **NO EDGE** | L-BRENT | BANKNIFTY | Brent crude last 30 min → BANKNIFTY next 30 min (against it) | 499 | -1.2 bps (-7.4 pts) | -1.43 | 0.152 | -3.1 bps, p 0.02 | · |
| **NO EDGE** | L-FTSE | BANKNIFTY | FTSE 100 last 30 min → BANKNIFTY next 30 min (with it) | 186 | +1.9 bps (+12.1 pts) | +1.43 | 0.156 | +4.7 bps, p 0.01 | · |
| **NO EDGE** | L-STOXX | NIFTY | Euro Stoxx 50 last 30 min → NIFTY next 30 min (with it) | 186 | +1.6 bps (+4.2 pts) | +1.42 | 0.156 | +2.1 bps, p 0.19 | · |
| **NO EDGE** | G-ES | BANKNIFTY | S&P 500 futures prior session → trade with it, open→close | 4,679 | -3.0 bps (-19.4 pts) | -1.39 | 0.165 | -4.2 bps, p 0.05 | · |
| **NO EDGE** | L-DXY | BANKNIFTY | US dollar index last 30 min → BANKNIFTY next 30 min (against it) | 500 | +1.2 bps (+7.7 pts) | +1.29 | 0.197 | +1.3 bps, p 0.22 | · |
| **NO EDGE** | L-FTSE | NIFTY | FTSE 100 last 30 min → NIFTY next 30 min (with it) | 186 | +1.4 bps (+3.5 pts) | +1.28 | 0.203 | +2.3 bps, p 0.12 | · |
| **NO EDGE** | G-N225 | NIFTY | Nikkei 225 prior session → trade NIFTY-side with it, open→close | 4,704 | +2.1 bps (+5.3 pts) | +1.24 | 0.216 | +1.5 bps, p 0.21 | · |
| **NO EDGE** | L-N225 | NIFTY | Nikkei 225 last 30 min → NIFTY next 30 min (with it) | 275 | +1.2 bps (+3.0 pts) | +1.21 | 0.229 | +1.0 bps, p 0.30 | · |
| **NO EDGE** | G-UST10 | NIFTY | US 10-year yield prior session → trade NIFTY-side against it, open→close | 4,635 | -2.3 bps (-5.9 pts) | -1.17 | 0.243 | +1.7 bps, p 0.84 | · |
| **NO EDGE** | H1 | NIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | +2.0 bps (+5.1 pts) | +1.11 | 0.269 | +2.7 bps, p 0.21 | · |
| **NO EDGE** | M2 | NIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 145 | -1.3 bps (-3.4 pts) | -1.09 | 0.277 | -3.3 bps, p 0.08 | · |
| **NO EDGE** | D3 | BANKNIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 578 | -8.6 bps (-55.7 pts) | -1.06 | 0.291 | +5.7 bps, p 0.70 | · |
| **NO EDGE** | L-STOXX | BANKNIFTY | Euro Stoxx 50 last 30 min → BANKNIFTY next 30 min (with it) | 186 | +1.4 bps (+8.9 pts) | +1.05 | 0.295 | +2.2 bps, p 0.20 | · |
| **NO EDGE** | H1 | BANKNIFTY | First-hour momentum: trade the 09:15→10:15 direction from 10:15 to the close | 724 | -2.3 bps (-14.9 pts) | -1.04 | 0.300 | -2.0 bps, p 0.32 | · |
| **NO EDGE** | D6 | BANKNIFTY | After an India VIX jump > 10%: long the next day open→close | 168 | +14.4 bps (+93.3 pts) | +0.99 | 0.325 | +35.0 bps, p 0.01 | · |
| **NO EDGE** | G-HSI | NIFTY | Hang Seng prior session → trade NIFTY-side with it, open→close | 4,705 | +1.6 bps (+4.0 pts) | +0.94 | 0.349 | -0.2 bps, p 0.54 | · |
| **NO EDGE** | L-NQ | BANKNIFTY | Nasdaq 100 futures last 30 min → BANKNIFTY next 30 min (with it) | 505 | +0.8 bps (+5.2 pts) | +0.88 | 0.377 | +2.1 bps, p 0.10 | · |
| **NO EDGE** | L-GOLD | NIFTY | Gold last 30 min → NIFTY next 30 min (with it) | 504 | +0.7 bps (+1.7 pts) | +0.86 | 0.390 | -0.1 bps, p 0.53 | · |
| **NO EDGE** | L-KOSPI | NIFTY | Kospi last 30 min → NIFTY next 30 min (with it) | 224 | +0.9 bps (+2.4 pts) | +0.85 | 0.396 | +0.1 bps, p 0.48 | · |
| **NO EDGE** | G-N225 | BANKNIFTY | Nikkei 225 prior session → trade with it, open→close | 4,719 | +1.8 bps (+11.6 pts) | +0.82 | 0.412 | +1.9 bps, p 0.23 | · |
| **NO EDGE** | L-HSI | NIFTY | Hang Seng last 30 min → NIFTY next 30 min (with it) | 392 | +0.6 bps (+1.6 pts) | +0.80 | 0.424 | +0.2 bps, p 0.42 | · |
| **NO EDGE** | L-ES | BANKNIFTY | S&P 500 futures last 30 min → BANKNIFTY next 30 min (with it) | 499 | +0.7 bps (+4.8 pts) | +0.79 | 0.431 | +1.7 bps, p 0.15 | · |
| **NO EDGE** | G-BRENT | NIFTY | Brent crude prior session → trade NIFTY-side against it, open→close | 4,677 | +1.2 bps (+3.0 pts) | +0.69 | 0.489 | -2.4 bps, p 0.91 | · |
| **NO EDGE** | G-NASDAQ | BANKNIFTY | Nasdaq Composite prior session → trade with it, open→close | 4,719 | -1.4 bps (-9.0 pts) | -0.65 | 0.515 | -5.4 bps, p 0.98 | · |
| **NO EDGE** | D5 | BANKNIFTY | Turn of the month (last day + first 3): long open→close | 924 | +3.3 bps (+21.5 pts) | +0.59 | 0.555 | +8.8 bps, p 0.09 | · |
| **NO EDGE** | H3 | BANKNIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | -0.7 bps (-4.5 pts) | -0.59 | 0.555 | -1.8 bps, p 0.19 | · |
| **NO EDGE** | L-GOLD | BANKNIFTY | Gold last 30 min → BANKNIFTY next 30 min (with it) | 504 | +0.5 bps (+3.5 pts) | +0.57 | 0.569 | +0.3 bps, p 0.43 | · |
| **NO EDGE** | H2 | BANKNIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 723 | +0.6 bps (+3.9 pts) | +0.54 | 0.591 | +3.4 bps, p 0.93 | · |
| **NO EDGE** | G-NQ | BANKNIFTY | Nasdaq 100 futures prior session → trade with it, open→close | 4,705 | -1.1 bps (-7.1 pts) | -0.51 | 0.609 | -6.9 bps, p 1.00 | · |
| **NO EDGE** | G-HSI | BANKNIFTY | Hang Seng prior session → trade with it, open→close | 4,720 | +0.9 bps (+5.6 pts) | +0.44 | 0.663 | -1.2 bps, p 0.70 | · |
| **NO EDGE** | D3 | NIFTY | Rebound: the day after a close-to-close fall > 1.5%, long open→close | 359 | -4.1 bps (-10.7 pts) | -0.38 | 0.702 | +10.0 bps, p 0.86 | · |
| **NO EDGE** | H2 | NIFTY | Intraday momentum (Gao et al.): overnight + first hour predicts the last hour (14:15→close) | 724 | +0.4 bps (+1.0 pts) | +0.36 | 0.719 | +1.8 bps, p 0.83 | · |
| **NO EDGE** | D5 | NIFTY | Turn of the month (last day + first 3): long open→close | 924 | +1.2 bps (+3.1 pts) | +0.32 | 0.746 | +3.3 bps, p 0.23 | · |
| **NO EDGE** | M2 | BANKNIFTY | VWAP reversion: > 2σ from VWAP, fade it for 30 minutes | 135 | -0.6 bps (-4.2 pts) | -0.32 | 0.747 | -8.6 bps, p 0.98 | · |
| **NO EDGE** | L-SSE | NIFTY | Shanghai Composite last 30 min → NIFTY next 30 min (with it) | 165 | +0.3 bps (+0.8 pts) | +0.32 | 0.749 | -1.9 bps, p 0.89 | · |
| **NO EDGE** | L-N225 | BANKNIFTY | Nikkei 225 last 30 min → BANKNIFTY next 30 min (with it) | 275 | +0.4 bps (+2.5 pts) | +0.32 | 0.750 | +1.4 bps, p 0.70 | · |
| **NO EDGE** | G-FTSE | NIFTY | FTSE 100 prior session → trade NIFTY-side with it, open→close | 4,699 | -0.5 bps (-1.3 pts) | -0.30 | 0.766 | -0.4 bps, p 0.41 | · |
| **NO EDGE** | G-GOLD | NIFTY | Gold prior session → trade NIFTY-side with it, open→close | 4,688 | -0.5 bps (-1.3 pts) | -0.29 | 0.770 | +1.9 bps, p 0.86 | · |
| **NO EDGE** | H3 | NIFTY | Late-day trend: trade the open→14:15 direction into the close | 724 | +0.3 bps (+0.7 pts) | +0.28 | 0.779 | -0.8 bps, p 0.66 | · |
| **NO EDGE** | G-STOXX | NIFTY | Euro Stoxx 50 prior session → trade NIFTY-side with it, open→close | 4,698 | +0.5 bps (+1.3 pts) | +0.27 | 0.788 | -1.4 bps, p 0.80 | · |
| **NO EDGE** | D2 | BANKNIFTY | Gap continuation: after a gap > 0.3%, trade in the gap's direction open→close | 2,582 | -0.7 bps (-4.4 pts) | -0.21 | 0.834 | -3.1 bps, p 0.78 | · |
| **NO EDGE** | G-DAX | NIFTY | DAX prior session → trade NIFTY-side with it, open→close | 4,705 | +0.3 bps (+0.8 pts) | +0.17 | 0.866 | -2.0 bps, p 0.87 | · |
| **NO EDGE** | M3 | BANKNIFTY | 30-minute momentum: trade the last 30 minutes' direction for the next 30 | 600 | -0.1 bps (-0.6 pts) | -0.12 | 0.905 | -0.0 bps, p 0.49 | · |
| **NO EDGE** | G-SSE | BANKNIFTY | Shanghai Composite prior session → trade with it, open→close | 4,720 | +0.2 bps (+1.2 pts) | +0.09 | 0.925 | +1.6 bps, p 0.74 | · |
| **NO EDGE** | L-SSE | BANKNIFTY | Shanghai Composite last 30 min → BANKNIFTY next 30 min (with it) | 165 | -0.1 bps (-0.8 pts) | -0.09 | 0.928 | -3.4 bps, p 0.89 | · |
| **NO EDGE** | G-SSE | NIFTY | Shanghai Composite prior session → trade NIFTY-side with it, open→close | 4,705 | -0.2 bps (-0.4 pts) | -0.09 | 0.928 | +1.3 bps, p 0.77 | · |
| **NO EDGE** | L-KOSPI | BANKNIFTY | Kospi last 30 min → BANKNIFTY next 30 min (with it) | 224 | +0.1 bps (+0.6 pts) | +0.08 | 0.938 | -0.2 bps, p 0.53 | · |
| **NO EDGE** | L-BRENT | NIFTY | Brent crude last 30 min → NIFTY next 30 min (against it) | 499 | -0.0 bps (-0.1 pts) | -0.04 | 0.968 | -1.4 bps, p 0.92 | · |
| **NO EDGE** | L-HSI | BANKNIFTY | Hang Seng last 30 min → BANKNIFTY next 30 min (with it) | 392 | +0.0 bps (+0.2 pts) | +0.03 | 0.979 | -0.7 bps, p 0.66 | · |
| **NO EDGE** | G-UST10 | BANKNIFTY | US 10-year yield prior session → trade against it, open→close | 4,649 | -0.0 bps (-0.2 pts) | -0.01 | 0.989 | -1.5 bps, p 0.73 | · |

Notes:
- D1 NIFTY:  {"p_discovery": 0.008514841802240807}
- D2 NIFTY:  {"min_gap": 0.003, "p_discovery": 0.14327157141782346}
- D3 NIFTY:  {"fall": -0.015, "p_discovery": 0.46127655720074107}
- D4 NIFTY:  {"p_discovery": 0.0442445415337794}
- D5 NIFTY:  {"p_discovery": 0.973665910719219}
- D6 NIFTY:  {"p_discovery": 0.4729498681780356}
- V1 NIFTY: in vol points ×100, not a return; harvested by selling options (margin) {"share_positive": 0.8, "mean_vix": 19.66}
- H1 NIFTY:  {"p_discovery": 0.4582447796578493}
- H2 NIFTY:  {"p_discovery": 0.7754223180976485}
- H3 NIFTY:  {"p_discovery": 0.45555198757688325}
- M1 NIFTY:  {"p_discovery": 0.061212391325273806}
- M2 NIFTY:  {"p_discovery": 0.8301038435848316}
- M3 NIFTY:  {"p_discovery": 0.018695571506672438}
- G-ES NIFTY:  {"p_discovery": 0.0010449056118642568}
- G-NQ NIFTY:  {"p_discovery": 8.62693677697691e-06}
- G-SPX NIFTY:  {"p_discovery": 0.00035905954402004197}
- G-NASDAQ NIFTY:  {"p_discovery": 9.103362603779507e-05}
- G-DJI NIFTY:  {"p_discovery": 0.0013206299496923714}
- G-N225 NIFTY:  {"p_discovery": 0.3142078252118396}
- G-HSI NIFTY:  {"p_discovery": 0.3085813161056692}
- G-KOSPI NIFTY:  {"p_discovery": 0.09011518597016872}
- G-SSE NIFTY:  {"p_discovery": 0.7083723035506898}
- G-STOXX NIFTY:  {"p_discovery": 0.5740999867453132}
- G-DAX NIFTY:  {"p_discovery": 0.5627450919000361}
- G-FTSE NIFTY:  {"p_discovery": 0.8102531896577089}
- G-USVIX NIFTY:  {"p_discovery": 0.007308360541200711}
- G-DXY NIFTY:  {"p_discovery": 0.33916932423624824}
- G-USDINR NIFTY:  {"p_discovery": 0.015036738579275967}
- G-BRENT NIFTY:  {"p_discovery": 0.21594867886842414}
- G-GOLD NIFTY:  {"p_discovery": 0.47163977373882676}
- G-UST10 NIFTY:  {"p_discovery": 0.11983658178790349}
- L-ES NIFTY:  {"p_discovery": 0.13241097698109952}
- L-NQ NIFTY:  {"p_discovery": 0.23523971530792653}
- L-N225 NIFTY:  {"p_discovery": 0.24919162062249836}
- L-HSI NIFTY:  {"p_discovery": 0.4348766965885757}
- L-KOSPI NIFTY:  {"p_discovery": 0.3382519554611776}
- L-SSE NIFTY:  {"p_discovery": 0.2504093591503258}
- L-STOXX NIFTY:  {"p_discovery": 0.256623123043884}
- L-DAX NIFTY:  {"p_discovery": 0.18071240106602723}
- L-FTSE NIFTY:  {"p_discovery": 0.4578379765850878}
- L-DXY NIFTY:  {"p_discovery": 0.08888957389947896}
- L-USDINR NIFTY:  {"p_discovery": 0.28385552809558173}
- L-BRENT NIFTY:  {"p_discovery": 0.4389235485207687}
- L-GOLD NIFTY:  {"p_discovery": 0.29578313487535335}
- D1 BANKNIFTY:  {"p_discovery": 0.021015886292124315}
- D2 BANKNIFTY:  {"min_gap": 0.003, "p_discovery": 0.9064527272879974}
- D3 BANKNIFTY:  {"fall": -0.015, "p_discovery": 0.14527496017924987}
- D4 BANKNIFTY:  {"p_discovery": 0.034807299726881194}
- D5 BANKNIFTY:  {"p_discovery": 0.9356897440335432}
- D6 BANKNIFTY:  {"p_discovery": 0.834145995342799}
- H1 BANKNIFTY:  {"p_discovery": 0.34195198369580043}
- H2 BANKNIFTY:  {"p_discovery": 0.5257478526536101}
- H3 BANKNIFTY:  {"p_discovery": 0.9148166731618562}
- M1 BANKNIFTY:  {"p_discovery": 0.2567211443059167}
- M2 BANKNIFTY:  {"p_discovery": 0.027759451741985595}
- M3 BANKNIFTY:  {"p_discovery": 0.8770072395935107}
- G-ES BANKNIFTY:  {"p_discovery": 0.42207768098915865}
- G-NQ BANKNIFTY:  {"p_discovery": 0.5431022312105259}
- G-SPX BANKNIFTY:  {"p_discovery": 0.3206382159072498}
- G-NASDAQ BANKNIFTY:  {"p_discovery": 0.8413385279186231}
- G-DJI BANKNIFTY:  {"p_discovery": 0.22450521465571524}
- G-N225 BANKNIFTY:  {"p_discovery": 0.5659550798078399}
- G-HSI BANKNIFTY:  {"p_discovery": 0.5012371991568129}
- G-KOSPI BANKNIFTY:  {"p_discovery": 0.13429851955369076}
- G-SSE BANKNIFTY:  {"p_discovery": 0.8525851012510307}
- G-STOXX BANKNIFTY:  {"p_discovery": 0.02136541022043174}
- G-DAX BANKNIFTY:  {"p_discovery": 0.037121184149934885}
- G-FTSE BANKNIFTY:  {"p_discovery": 0.002514367280656604}
- G-USVIX BANKNIFTY:  {"p_discovery": 0.18934370760281902}
- G-DXY BANKNIFTY:  {"p_discovery": 0.22589004556785505}
- G-USDINR BANKNIFTY:  {"p_discovery": 0.20979313188801368}
- G-BRENT BANKNIFTY:  {"p_discovery": 0.002648206641825814}
- G-GOLD BANKNIFTY:  {"p_discovery": 0.005105531183634565}
- G-UST10 BANKNIFTY:  {"p_discovery": 0.8261393312388453}
- L-ES BANKNIFTY:  {"p_discovery": 0.8269749759317245}
- L-NQ BANKNIFTY:  {"p_discovery": 0.8780079963781346}
- L-N225 BANKNIFTY:  {"p_discovery": 0.911885808889296}
- L-HSI BANKNIFTY:  {"p_discovery": 0.7313707903601929}
- L-KOSPI BANKNIFTY:  {"p_discovery": 0.862726348355501}
- L-SSE BANKNIFTY:  {"p_discovery": 0.32916640930057495}
- L-STOXX BANKNIFTY:  {"p_discovery": 0.5032221634531784}
- L-DAX BANKNIFTY:  {"p_discovery": 0.2449484926757092}
- L-FTSE BANKNIFTY:  {"p_discovery": 0.7683906831566253}
- L-DXY BANKNIFTY:  {"p_discovery": 0.2965146437577326}
- L-USDINR BANKNIFTY:  {"p_discovery": 0.3532249312358731}
- L-BRENT BANKNIFTY:  {"p_discovery": 0.8624132765290464}
- L-GOLD BANKNIFTY:  {"p_discovery": 0.5460745316621742}

## Global links (how markets move together; not trades)

The opening gap happens before the desk can trade, and same-5-minute co-movement isn't a forecast; they explain *why* NIFTY is where it is, which is what the brain uses them for.

| From | To | What | N | β | corr | R² | t |
|---|---|---|---:|---:|---:|---:|---:|
| S&P 500 | BANKNIFTY | opening gap | 4,719 | +0.367 | +0.512 | 0.262 | +41.0 |
| Dow Jones | BANKNIFTY | opening gap | 4,719 | +0.382 | +0.504 | 0.254 | +40.0 |
| Nasdaq Composite | BANKNIFTY | opening gap | 4,719 | +0.305 | +0.484 | 0.235 | +38.0 |
| S&P 500 futures | BANKNIFTY | opening gap | 4,719 | +0.342 | +0.481 | 0.232 | +37.7 |
| Nasdaq 100 futures | BANKNIFTY | opening gap | 4,719 | +0.276 | +0.443 | 0.196 | +33.9 |
| S&P 500 | NIFTY | opening gap | 4,704 | +0.199 | +0.422 | 0.178 | +31.9 |
| Dow Jones | NIFTY | opening gap | 4,704 | +0.210 | +0.420 | 0.177 | +31.8 |
| Nasdaq Composite | NIFTY | opening gap | 4,704 | +0.174 | +0.418 | 0.175 | +31.6 |
| S&P 500 futures | NIFTY | opening gap | 4,704 | +0.184 | +0.393 | 0.154 | +29.3 |
| Nasdaq 100 futures | NIFTY | opening gap | 4,704 | +0.159 | +0.387 | 0.150 | +28.8 |
| CBOE VIX | BANKNIFTY | opening gap | 4,719 | -0.044 | -0.384 | 0.147 | -28.6 |
| CBOE VIX | NIFTY | opening gap | 4,704 | -0.029 | -0.382 | 0.146 | -28.3 |
| DAX | BANKNIFTY | opening gap | 4,719 | +0.225 | +0.335 | 0.112 | +24.4 |
| Euro Stoxx 50 | BANKNIFTY | opening gap | 4,719 | +0.209 | +0.319 | 0.101 | +23.1 |
| FTSE 100 | BANKNIFTY | opening gap | 4,719 | +0.238 | +0.296 | 0.088 | +21.3 |
| DAX | NIFTY | opening gap | 4,704 | +0.130 | +0.294 | 0.087 | +21.1 |
| Euro Stoxx 50 | NIFTY | opening gap | 4,704 | +0.119 | +0.274 | 0.075 | +19.6 |
| FTSE 100 | NIFTY | opening gap | 4,704 | +0.132 | +0.248 | 0.061 | +17.6 |
| S&P 500 futures | BANKNIFTY | same 5 minutes | 3,202 | +0.582 | +0.186 | 0.034 | +10.7 |
| US dollar index | NIFTY | opening gap | 4,704 | -0.185 | -0.151 | 0.023 | -10.5 |
| S&P 500 futures | NIFTY | same 5 minutes | 3,207 | +0.483 | +0.175 | 0.030 | +10.0 |
| US dollar index | BANKNIFTY | opening gap | 4,719 | -0.240 | -0.129 | 0.017 | -9.0 |
| Nasdaq 100 futures | BANKNIFTY | same 5 minutes | 3,332 | +0.274 | +0.153 | 0.023 | +8.9 |
| Nasdaq 100 futures | NIFTY | same 5 minutes | 3,336 | +0.227 | +0.143 | 0.021 | +8.4 |
| US 10-year yield | BANKNIFTY | opening gap | 4,719 | +0.032 | +0.096 | 0.009 | +6.6 |
| Brent crude | NIFTY | opening gap | 4,704 | +0.021 | +0.087 | 0.008 | +6.0 |
| Euro Stoxx 50 | BANKNIFTY | same 5 minutes | 1,713 | +0.092 | +0.141 | 0.020 | +5.9 |
| Brent crude | BANKNIFTY | opening gap | 4,719 | +0.031 | +0.084 | 0.007 | +5.8 |
| DAX | BANKNIFTY | same 5 minutes | 1,715 | +0.090 | +0.136 | 0.018 | +5.7 |
| Euro Stoxx 50 | NIFTY | same 5 minutes | 1,721 | +0.075 | +0.134 | 0.018 | +5.6 |
| DAX | NIFTY | same 5 minutes | 1,723 | +0.073 | +0.128 | 0.016 | +5.4 |
| Gold | BANKNIFTY | same 5 minutes | 3,319 | +0.126 | +0.082 | 0.007 | +4.7 |
| US 10-year yield | NIFTY | opening gap | 4,704 | +0.014 | +0.066 | 0.004 | +4.5 |
| FTSE 100 | NIFTY | same 5 minutes | 1,721 | +0.067 | +0.103 | 0.011 | +4.3 |
| Gold | NIFTY | opening gap | 4,704 | +0.030 | +0.060 | 0.004 | +4.2 |
| Gold | NIFTY | same 5 minutes | 3,323 | +0.097 | +0.071 | 0.005 | +4.1 |
| Brent crude | BANKNIFTY | same 5 minutes | 3,218 | -0.026 | -0.072 | 0.005 | -4.1 |
| FTSE 100 | BANKNIFTY | same 5 minutes | 1,713 | +0.071 | +0.097 | 0.009 | +4.0 |
| Brent crude | NIFTY | same 5 minutes | 3,221 | -0.023 | -0.068 | 0.005 | -3.9 |
| US dollar index | BANKNIFTY | same 5 minutes | 3,292 | -0.340 | -0.055 | 0.003 | -3.2 |
| US dollar index | NIFTY | same 5 minutes | 3,296 | -0.293 | -0.054 | 0.003 | -3.1 |
| Nikkei 225 | BANKNIFTY | same 5 minutes | 1,809 | +0.102 | +0.071 | 0.005 | +3.0 |
| Nikkei 225 | NIFTY | opening gap | 4,704 | +0.015 | +0.038 | 0.001 | +2.6 |
| Nikkei 225 | NIFTY | same 5 minutes | 1,809 | +0.074 | +0.059 | 0.004 | +2.5 |
| Kospi | BANKNIFTY | same 5 minutes | 1,505 | +0.045 | +0.064 | 0.004 | +2.5 |
| Gold | BANKNIFTY | opening gap | 4,719 | +0.024 | +0.031 | 0.001 | +2.1 |
| Kospi | NIFTY | same 5 minutes | 1,501 | +0.035 | +0.055 | 0.003 | +2.1 |
| Hang Seng | BANKNIFTY | opening gap | 4,719 | +0.017 | +0.030 | 0.001 | +2.0 |
| Shanghai Composite | BANKNIFTY | opening gap | 4,719 | -0.017 | -0.028 | 0.001 | -1.9 |
| Hang Seng | BANKNIFTY | same 5 minutes | 2,347 | +0.077 | +0.040 | 0.002 | +1.9 |
| Hang Seng | NIFTY | opening gap | 4,704 | +0.009 | +0.022 | 0.000 | +1.5 |
| USD/INR | BANKNIFTY | opening gap | 4,719 | -0.037 | -0.021 | 0.000 | -1.4 |
| Hang Seng | NIFTY | same 5 minutes | 2,339 | +0.047 | +0.028 | 0.001 | +1.4 |
| USD/INR | BANKNIFTY | same 5 minutes | 3,744 | +0.064 | +0.013 | 0.000 | +0.8 |
| USD/INR | NIFTY | opening gap | 4,704 | -0.009 | -0.008 | 0.000 | -0.5 |
| Shanghai Composite | BANKNIFTY | same 5 minutes | 1,315 | +0.009 | +0.015 | 0.000 | +0.5 |
| Nikkei 225 | BANKNIFTY | opening gap | 4,719 | +0.004 | +0.007 | 0.000 | +0.5 |
| Kospi | BANKNIFTY | opening gap | 4,719 | -0.004 | -0.006 | 0.000 | -0.4 |
| Kospi | NIFTY | opening gap | 4,704 | -0.002 | -0.006 | 0.000 | -0.4 |
| Shanghai Composite | NIFTY | opening gap | 4,704 | -0.002 | -0.005 | 0.000 | -0.4 |
| Shanghai Composite | NIFTY | same 5 minutes | 1,311 | -0.004 | -0.008 | 0.000 | -0.3 |
| USD/INR | NIFTY | same 5 minutes | 3,748 | +0.002 | +0.000 | 0.000 | +0.0 |

## Verdict

Survived discovery, rolling validation, false-discovery control and the cost hurdle; the paper desk forward-tests them:
- **D1 NIFTY**: Intraday drift: long from the open to the close, every day. Trade **the opposite side** (the effect is negative): 14.1 pts/trade vs 4.2 pts of costs (t -3.30, rolling validation -4.1 bps). Per-trade σ 300 pts, so one lot of a 0.35Δ option is a half-Kelly bet only on an account of about ₹417,774; smaller accounts are over-betting it.


Experiment record: 9f509a75829f4c1caf97c2e8d60ea41a · b8fd8d16493c1878812c8fc3d131b42c087bd89071df7c0410182f09760ab669
