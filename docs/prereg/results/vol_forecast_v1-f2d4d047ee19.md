# Pre-registered move-size study: vol_forecast_v1

Spec sha256 `f2d4d047ee19a607b539eda60d187f1b35ad02f1e42f6025a0cfa6b79b74e637` · **evidence: external_verified (underlying only)** · no option prices: nothing here qualifies an option strategy, a DTE change, a paper gate, a promotion or a profitability claim.

- NIFTY: 2013 dev sessions, 1023 lock sessions (2010-01-04 → 2023-02-28)
- BANKNIFTY: 2009 dev sessions, 1023 lock sessions (2010-10-18 → 2023-02-28)

## Selection on dev (mean QLIKE over 2013–2018 folds and both indices; lower is better)

| horizon | A_desk | B_seasonal | C_har | selected |
|---|---|---|---|---|
| 120m | 0.2619 | 0.1910 | 0.1832 | C_har |
| 30m | 0.2624 | 0.2140 | 0.2122 | C_har |
| 60m | 0.2571 | 0.1996 | 0.1950 | C_har |
| close | 0.2046 | 0.1599 | 0.1452 | C_har |

## Locked period (opened once)

| index · horizon | selected | QLIKE A → selected | DM t | gain | verdict | move ratio by time, A | move ratio by time, selected |
|---|---|---|---|---|---|---|---|
| NIFTY 120m | C_har | 0.2053 → 0.1334 | +12.66 | +35.0% | **pass** | 0.73 · 0.76 · 1.05 · 1.23 | 0.98 · 0.94 · 0.97 · 1.04 |
| NIFTY 30m | C_har | 0.1940 → 0.1550 | +11.41 | +20.1% | **pass** | 0.86 · 0.76 · 0.88 · 1.11 | 1.00 · 0.94 · 0.91 · 1.00 |
| NIFTY 60m | C_har | 0.1875 → 0.1370 | +11.72 | +27.0% | **pass** | 0.81 · 0.75 · 0.93 · 1.16 | 1.02 · 0.93 · 0.92 · 1.01 |
| NIFTY close | C_har | 0.1714 → 0.1239 | +10.91 | +27.7% | **pass** | 0.82 · 0.95 · 1.15 · 1.15 | 1.09 · 1.08 · 1.03 · 1.01 |
| BANKNIFTY 120m | C_har | 0.2123 → 0.1590 | +5.69 | +25.1% | **pass** | 0.73 · 0.75 · 1.02 · 1.15 | 0.97 · 0.89 · 0.95 · 1.01 |
| BANKNIFTY 30m | C_har | 0.2128 → 0.1853 | +4.65 | +12.9% | **pass** | 0.85 · 0.75 · 0.86 · 1.03 | 1.01 · 0.90 · 0.88 · 0.95 |
| BANKNIFTY 60m | C_har | 0.2011 → 0.1646 | +5.07 | +18.2% | **pass** | 0.81 · 0.73 · 0.91 · 1.09 | 1.02 · 0.88 · 0.89 · 0.98 |
| BANKNIFTY close | C_har | 0.1624 → 0.1286 | +10.50 | +20.8% | **pass** | 0.79 · 0.90 · 1.07 · 1.06 | 1.03 · 1.02 · 0.98 · 0.95 |

Move ratio = realised mean |move| ÷ the forecast's expected |move| (√(2/π)·σ), by 09:30–10:00 · 10:00–11:30 · 11:30–13:30 · 13:30–15:00. 1.00 is calibrated; above 1 the forecast is too small, below 1 too big.

Opened 2026-10-04T00:58:21.559609+05:30.
