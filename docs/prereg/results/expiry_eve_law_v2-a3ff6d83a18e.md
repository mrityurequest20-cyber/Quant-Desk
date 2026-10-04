# Law L1 across instruments · expiry_eve_law_v2 · spec a3ff6d83a18e

Index levels from NSE's official closes (nse_index_close). Selling 20-delta options at the close the night before expiry, held to settlement; real bhavcopy prices. P&L in basis points of the index (instrument-neutral); 'kept' is the share of the premium sold that was kept. Discovery instruments are for reference; the test is on the held-out ones.

## strangle: short_strangle_20d

| instrument | role | n | mean bps | t | win | worst bps | CVaR5 bps | credit bps | kept | first ⅔ / last ⅓ | span |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BANKEX | held out | 67 | +2.98 | 0.59 | 79% | -157 | -133 | 25.1 | 12% | +3.78 / +1.46 | 2024-01-18 → 2026-09-24 |
| BANKNIFTY | discovery | 326 | +10.84 | 3.22 | 82% | -638 | -197 | 32.2 | 34% | +13.21 / +6.11 | 2019-01-16 → 2026-09-29 |
| FINNIFTY | candidate ✅ | 214 | +9.42 | 2.96 | 84% | -417 | -137 | 24.6 | 38% | +13.59 / +1.21 | 2021-01-13 → 2026-09-29 |
| MIDCPNIFTY | candidate ✅ | 100 | +11.20 | 3.92 | 80% | -153 | -103 | 26.3 | 43% | +8.89 / +15.67 | 2022-01-24 → 2026-09-29 |
| NIFTY | discovery | 398 | +5.30 | 2.60 | 77% | -580 | -139 | 22.2 | 24% | +5.28 / +5.34 | 2019-01-30 → 2026-09-29 |
| NIFTYNXT50 | held out | 26 | +11.34 | 2.40 | 81% | -78 | -78 | 26.8 | 42% | +9.96 / +13.95 | 2024-05-30 → 2026-08-25 |
| SENSEX | candidate ✅ | 142 | +4.45 | 1.75 | 78% | -197 | -113 | 20.6 | 22% | +2.76 / +7.76 | 2024-01-18 → 2026-10-01 |

Pooled held-out (weekly mean across instruments): 288 weeks, mean +9.48 bps, t 4.98, first ⅔ +10.84 / last ⅓ +6.74.
Positive mean on 5 of 5 held-out instruments with ≥ 20 trades.
**Verdict: L1 (strangle) REPLICATES** on held-out instruments; tape and forward-sleeve candidates: FINNIFTY, MIDCPNIFTY, SENSEX.

## insured: iron_condor_20_05

| instrument | role | n | mean bps | t | win | worst bps | CVaR5 bps | credit bps | kept | first ⅔ / last ⅓ | span |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BANKEX | held out | 67 | +0.28 | 0.07 | 76% | -118 | -103 | 19.8 | 1% | +0.81 / -0.73 | 2024-01-18 → 2026-09-24 |
| BANKNIFTY | discovery | 324 | +6.35 | 2.51 | 79% | -263 | -133 | 24.5 | 26% | +7.74 / +3.58 | 2019-01-16 → 2026-09-29 |
| FINNIFTY | held out | 214 | +5.52 | 2.20 | 82% | -337 | -111 | 19.4 | 28% | +9.09 / -1.52 | 2021-01-13 → 2026-09-29 |
| MIDCPNIFTY | candidate ✅ | 100 | +5.89 | 2.25 | 78% | -116 | -96 | 20.8 | 28% | +3.58 / +10.37 | 2022-01-24 → 2026-09-29 |
| NIFTY | discovery | 398 | +2.07 | 1.38 | 76% | -245 | -101 | 17.3 | 12% | +1.87 / +2.47 | 2019-01-30 → 2026-09-29 |
| NIFTYNXT50 | held out | 26 | +6.31 | 1.33 | 81% | -84 | -84 | 22.1 | 29% | +5.02 / +8.77 | 2024-05-30 → 2026-08-25 |
| SENSEX | held out | 142 | +1.52 | 0.71 | 77% | -112 | -88 | 16.2 | 9% | -0.56 / +5.59 | 2024-01-18 → 2026-10-01 |

Pooled held-out (weekly mean across instruments): 288 weeks, mean +5.48 bps, t 3.63, first ⅔ +6.62 / last ⅓ +3.21.
Positive mean on 5 of 5 held-out instruments with ≥ 20 trades.
**Verdict: L1 (insured) REPLICATES** on held-out instruments; tape and forward-sleeve candidates: MIDCPNIFTY.
