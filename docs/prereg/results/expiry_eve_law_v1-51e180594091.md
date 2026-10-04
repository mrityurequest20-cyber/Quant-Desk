# Law L1 across instruments · expiry_eve_law_v1 · spec 51e180594091

Selling 20-delta options at the close the night before expiry, held to settlement; real bhavcopy prices. P&L in basis points of the index (instrument-neutral); 'kept' is the share of the premium sold that was kept. Discovery instruments are for reference; the test is on the held-out ones.

## strangle: short_strangle_20d

| instrument | role | n | mean bps | t | win | worst bps | CVaR5 bps | credit bps | kept | first ⅔ / last ⅓ | span |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BANKEX | held out | 67 | +2.98 | 0.59 | 79% | -157 | -133 | 25.1 | 12% | +3.78 / +1.46 | 2024-01-18 → 2026-09-24 |
| BANKNIFTY | discovery | 326 | +10.08 | 2.91 | 81% | -685 | -202 | 32.3 | 31% | +11.51 / +7.21 | 2019-01-16 → 2026-09-29 |
| FINNIFTY | candidate ✅ | 212 | +9.08 | 2.81 | 84% | -397 | -138 | 24.9 | 36% | +13.19 / +0.91 | 2021-01-27 → 2026-09-29 |
| MIDCPNIFTY | candidate ✅ | 99 | +9.22 | 3.00 | 78% | -153 | -95 | 26.1 | 35% | +6.25 / +15.16 | 2023-05-16 → 2026-09-29 |
| NIFTY | discovery | 394 | +4.29 | 1.97 | 77% | -622 | -148 | 22.3 | 19% | +3.65 / +5.56 | 2019-01-30 → 2026-09-29 |
| NIFTYNXT50 | held out | 26 | +11.34 | 2.40 | 81% | -78 | -78 | 26.8 | 42% | +9.95 / +13.95 | 2024-05-30 → 2026-08-25 |
| SENSEX | candidate ✅ | 142 | +4.45 | 1.75 | 78% | -197 | -113 | 20.6 | 22% | +2.76 / +7.76 | 2024-01-18 → 2026-10-01 |

Pooled held-out (weekly mean across instruments): 286 weeks, mean +8.87 bps, t 4.46, first ⅔ +9.95 / last ⅓ +6.74.
Positive mean on 5 of 5 held-out instruments with ≥ 20 trades.
**Verdict: L1 (strangle) REPLICATES** on held-out instruments; tape and forward-sleeve candidates: FINNIFTY, MIDCPNIFTY, SENSEX.

## insured: iron_condor_20_05

| instrument | role | n | mean bps | t | win | worst bps | CVaR5 bps | credit bps | kept | first ⅔ / last ⅓ | span |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| BANKEX | held out | 67 | +0.28 | 0.07 | 76% | -118 | -103 | 19.8 | 1% | +0.81 / -0.73 | 2024-01-18 → 2026-09-24 |
| BANKNIFTY | discovery | 324 | +5.87 | 2.33 | 79% | -263 | -129 | 24.6 | 24% | +6.66 / +4.29 | 2019-01-16 → 2026-09-29 |
| FINNIFTY | held out | 212 | +5.40 | 2.07 | 83% | -352 | -112 | 19.6 | 27% | +9.28 / -2.30 | 2021-01-27 → 2026-09-29 |
| MIDCPNIFTY | held out | 99 | +3.94 | 1.38 | 78% | -116 | -91 | 20.6 | 19% | +0.96 / +9.89 | 2023-05-16 → 2026-09-29 |
| NIFTY | discovery | 394 | +1.61 | 1.05 | 75% | -246 | -100 | 17.3 | 9% | +1.01 / +2.82 | 2019-01-30 → 2026-09-29 |
| NIFTYNXT50 | held out | 26 | +6.31 | 1.32 | 81% | -84 | -84 | 22.1 | 29% | +5.01 / +8.77 | 2024-05-30 → 2026-08-25 |
| SENSEX | held out | 142 | +1.52 | 0.71 | 77% | -112 | -88 | 16.2 | 9% | -0.56 / +5.59 | 2024-01-18 → 2026-10-01 |

Pooled held-out (weekly mean across instruments): 286 weeks, mean +5.07 bps, t 3.28, first ⅔ +6.02 / last ⅓ +3.21.
Positive mean on 5 of 5 held-out instruments with ≥ 20 trades.
**Verdict: L1 (insured) REPLICATES** on held-out instruments; tape and forward-sleeve candidates: none.
