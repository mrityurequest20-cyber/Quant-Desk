# Robustness audit of L1 and L2 · expiry_eve_law_v1_audit · spec 363b1c53b623

Audits expiry_eve_law_v1 (51e180594091): the same trades, rebuilt from the raw warehouse, put through ten checks fixed before the audit ran. Every check can only weaken the claim.

## L1 · strangle (short_strangle_20d): **replicated, robust**

Pooled held-out series: 286 weeks, +8.87 bps a week, t 4.46. Trading costs are 2% of the premium sold.

| check | result | detail |
|---|---|---|
| 0_reproduce | ✅ pass | rebuilt 286 weeks, +8.87 bps, t 4.46; registered 286 weeks, +8.87 bps, t 4.46 |
| 1_hac_lags | ✅ pass | lag 0: t 4.43, lag auto=5: t 4.46, lag 10: t 4.07, lag 20: t 3.80 |
| 2_block_bootstrap | ✅ pass | 10,000 resamples, mean block 8 weeks: 5th pct +5.41 bps, median +8.85, share ≤ 0: 0.00% |
| 3_leave_one_out | ✅ pass | −FINNIFTY: +5.55 bps t 2.83, −MIDCPNIFTY: +8.61 bps t 4.09, −NIFTYNXT50: +8.82 bps t 4.43, −SENSEX: +10.23 bps t 4.61, −BANKEX: +8.91 bps t 4.46 |
| 4_costs | ✅ pass | costs 0.52 bps a week on average; ×2: +8.35 bps (t 4.21); ×3: +7.83 bps (t 3.96); break-even at 18.0× costs |
| 5_liquidity | ✅ pass | ≥100 contracts: 267 weeks, +8.13 bps, t 4.18; ≥1,000 contracts: 241 weeks, +7.14 bps, t 3.49 |
| 6_years | ✅ pass | positive in 6 of 6 years: 2021 +22.33 (38w, t 4.50), 2022 +10.13 (52w, t 1.63), 2023 +9.04 (52w, t 4.36), 2024 +1.51 (53w, t 0.57), 2025 +7.42 (53w, t 1.98), 2026 +6.19 (40w, t 1.11) |
| 7_current_regime | ✅ pass | since 2024-11-20: 98 weeks, +4.92 bps, t 1.42; before: 189 weeks, +10.27 bps, t 4.24 |
| 8_trim_best_weeks | ✅ pass | best 14 weeks removed: +6.85 bps (from +8.87) |
| 9_multiple_testing | ✅ pass | pooled t 4.46 vs Bonferroni bar 1.96 |

Failed: none.

## L2 · insured (iron_condor_20_05): **replicated, robust**

Pooled held-out series: 286 weeks, +5.07 bps a week, t 3.28. Trading costs are 5% of the premium sold.

| check | result | detail |
|---|---|---|
| 0_reproduce | ✅ pass | rebuilt 286 weeks, +5.07 bps, t 3.28; registered 286 weeks, +5.07 bps, t 3.28 |
| 1_hac_lags | ✅ pass | lag 0: t 3.15, lag auto=5: t 3.28, lag 10: t 2.99, lag 20: t 2.75 |
| 2_block_bootstrap | ✅ pass | 10,000 resamples, mean block 8 weeks: 5th pct +2.29 bps, median +5.04, share ≤ 0: 0.10% |
| 3_leave_one_out | ✅ pass | −FINNIFTY: +1.91 bps t 1.11, −MIDCPNIFTY: +5.10 bps t 3.11, −NIFTYNXT50: +5.03 bps t 3.26, −SENSEX: +6.11 bps t 3.57, −BANKEX: +5.10 bps t 3.29 |
| 4_costs | ✅ pass | costs 0.98 bps a week on average; ×2: +4.09 bps (t 2.67); ×3: +3.11 bps (t 2.04); break-even at 6.2× costs |
| 5_liquidity | ✅ pass | ≥100 contracts: 267 weeks, +4.54 bps, t 2.99; ≥1,000 contracts: 240 weeks, +3.55 bps, t 2.29 |
| 6_years | ✅ pass | positive in 5 of 6 years: 2021 +14.92 (38w, t 3.37), 2022 +7.72 (52w, t 1.90), 2023 +5.45 (52w, t 3.03), 2024 -1.92 (53w, t -0.80), 2025 +3.02 (53w, t 0.82), 2026 +4.03 (40w, t 0.98) |
| 7_current_regime | ✅ pass | since 2024-11-20: 98 weeks, +2.30 bps, t 0.84; before: 189 weeks, +6.22 bps, t 3.36 |
| 8_trim_best_weeks | ✅ pass | best 14 weeks removed: +3.40 bps (from +5.07) |
| 9_multiple_testing | ✅ pass | pooled t 3.28 vs Bonferroni bar 1.96 |

Failed: none.

## Coverage (informational)

| instrument | expiries in data | traded | skipped | settled on the index itself |
|---|---:|---:|---:|---:|
| FINNIFTY | 237 | 212 | 11% | 20% |
| MIDCPNIFTY | 185 | 99 | 46% | 43% |
| NIFTYNXT50 | 32 | 26 | 19% | 92% |
| SENSEX | 151 | 142 | 6% | 100% |
| BANKEX | 72 | 67 | 7% | 99% |

The rest settled on the nearest index future's settle price, which on expiry day is the index's own final settlement value.
