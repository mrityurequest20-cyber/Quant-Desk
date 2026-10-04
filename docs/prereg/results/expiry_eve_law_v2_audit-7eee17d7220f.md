# Robustness audit of L1 and L2 · expiry_eve_law_v2_audit · spec 7eee17d7220f

Audits expiry_eve_law_v2 (a3ff6d83a18e): the same trades, rebuilt from the raw warehouse, put through ten checks fixed before the audit ran. Every check can only weaken the claim.

## L1 · strangle (short_strangle_20d): **replicated, robust**

Pooled held-out series: 288 weeks, +9.48 bps a week, t 4.98. Trading costs are 2% of the premium sold.

| check | result | detail |
|---|---|---|
| 0_reproduce | ✅ pass | rebuilt 288 weeks, +9.48 bps, t 4.98; registered 288 weeks, +9.48 bps, t 4.98 |
| 1_hac_lags | ✅ pass | lag 0: t 4.82, lag auto=5: t 4.98, lag 10: t 4.54, lag 20: t 4.18 |
| 2_block_bootstrap | ✅ pass | 10,000 resamples, mean block 8 weeks: 5th pct +6.11 bps, median +9.46, share ≤ 0: 0.01% |
| 3_leave_one_out | ✅ pass | −FINNIFTY: +6.87 bps t 3.47, −MIDCPNIFTY: +8.86 bps t 4.40, −NIFTYNXT50: +9.42 bps t 4.94, −SENSEX: +11.02 bps t 5.24, −BANKEX: +9.51 bps t 4.96 |
| 4_costs | ✅ pass | costs 0.52 bps a week on average; ×2: +8.95 bps (t 4.72); ×3: +8.43 bps (t 4.46); break-even at 19.1× costs |
| 5_liquidity | ✅ pass | ≥100 contracts: 270 weeks, +8.64 bps, t 4.60; ≥1,000 contracts: 243 weeks, +8.05 bps, t 4.01 |
| 6_years | ✅ pass | positive in 6 of 6 years: 2021 +22.67 (40w, t 5.09), 2022 +11.37 (52w, t 1.98), 2023 +9.83 (52w, t 4.55), 2024 +2.02 (53w, t 0.72), 2025 +7.42 (53w, t 1.98), 2026 +6.19 (40w, t 1.11) |
| 7_current_regime | ✅ pass | since 2024-11-20: 98 weeks, +4.92 bps, t 1.42; before: 191 weeks, +11.16 bps, t 4.91 |
| 8_trim_best_weeks | ✅ pass | best 14 weeks removed: +7.46 bps (from +9.48) |
| 9_multiple_testing | ✅ pass | pooled t 4.98 vs Bonferroni bar 1.96 |

Failed: none.

## L2 · insured (iron_condor_20_05): **replicated, robust**

Pooled held-out series: 288 weeks, +5.48 bps a week, t 3.63. Trading costs are 5% of the premium sold.

| check | result | detail |
|---|---|---|
| 0_reproduce | ✅ pass | rebuilt 288 weeks, +5.48 bps, t 3.63; registered 288 weeks, +5.48 bps, t 3.63 |
| 1_hac_lags | ✅ pass | lag 0: t 3.41, lag auto=5: t 3.63, lag 10: t 3.30, lag 20: t 3.01 |
| 2_block_bootstrap | ✅ pass | 10,000 resamples, mean block 8 weeks: 5th pct +2.74 bps, median +5.47, share ≤ 0: 0.03% |
| 3_leave_one_out | ✅ pass | −FINNIFTY: +3.17 bps t 1.84, −MIDCPNIFTY: +5.11 bps t 3.19, −NIFTYNXT50: +5.44 bps t 3.60, −SENSEX: +6.65 bps t 4.02, −BANKEX: +5.51 bps t 3.65 |
| 4_costs | ✅ pass | costs 0.99 bps a week on average; ×2: +4.49 bps (t 3.00); ×3: +3.51 bps (t 2.36); break-even at 6.6× costs |
| 5_liquidity | ✅ pass | ≥100 contracts: 270 weeks, +4.85 bps, t 3.22; ≥1,000 contracts: 242 weeks, +4.22 bps, t 2.71 |
| 6_years | ✅ pass | positive in 5 of 6 years: 2021 +15.30 (40w, t 3.82), 2022 +8.10 (52w, t 2.01), 2023 +5.95 (52w, t 3.08), 2024 -1.23 (53w, t -0.50), 2025 +3.02 (53w, t 0.82), 2026 +4.03 (40w, t 0.98) |
| 7_current_regime | ✅ pass | since 2024-11-20: 98 weeks, +2.30 bps, t 0.84; before: 191 weeks, +6.82 bps, t 3.82 |
| 8_trim_best_weeks | ✅ pass | best 14 weeks removed: +3.79 bps (from +5.48) |
| 9_multiple_testing | ✅ pass | pooled t 3.63 vs Bonferroni bar 1.96 |

Failed: none.

## Coverage (informational)

| instrument | expiries that reached expiry | re-dated by the exchange | traded | skipped | settled on: official close / file's underlying / nearest future |
|---|---:|---:|---:|---:|---|
| FINNIFTY | 225 | 12 | 214 | 5% | 100% / 0% / 0% |
| MIDCPNIFTY | 171 | 14 | 100 | 42% | 100% / 0% / 0% |
| NIFTYNXT50 | 29 | 3 | 26 | 10% | 100% / 0% / 0% |
| SENSEX | 145 | 6 | 142 | 2% | 0% / 100% / 0% |
| BANKEX | 70 | 2 | 67 | 4% | 0% / 100% / 0% |

A nearest future is the index itself only when it expires that day; on a weekly expiry it is the monthly future, basis and all (the flaw expiry_eve_law_v2 corrects).
