# Pre-registered intraday direction tests: intraday_direction_v1

Spec sha256 `5367cc9ae63cc8292914af403c72ef43e71bc349b5b223eb1832b17a6336577c` · dataset aeron7-2-906fc2378b · **evidence: external_verified** · no option prices: nothing here qualifies an option strategy, a DTE change, a paper gate, a promotion or a profitability claim.

- NIFTY: dev 2011 sessions (2010-01-27 → 2018-12-31), lock 1023 (2019-01-01 → 2023-02-28); high-vol cut (rv20, dev top tercile) 16.2%
- BANKNIFTY: dev 2008 sessions (2010-10-18 → 2018-12-31), lock 1023 (2019-01-01 → 2023-02-28); high-vol cut (rv20, dev top tercile) 23.7%

## Development period: every test

| test | days | mean (bps) | t (NW) | BH q | hit rate | cost hurdle (bps) | selected |
|---|---|---|---|---|---|---|---|
| H1_intraday_momentum NIFTY | 1999 | +0.91 | +1.60 | 0.253 | 0.503 | 6.6 | — |
| H2_first_half_hour_ex_gap NIFTY | 2009 | +1.04 | +1.75 | 0.253 | 0.516 | 6.6 | — |
| H3_first_hour_continuation NIFTY | 2011 | +5.09 | +3.28 | 0.007 | 0.549 | 6.6 | — |
| H4_large_gap NIFTY | 510 | +0.28 | +0.07 | 0.947 | 0.527 | 6.8 | — |
| H5_opening_range_breakout NIFTY | 1894 | +3.40 | +2.20 | 0.131 | 0.529 | 6.6 | — |
| H6_momentum_high_vol NIFTY | 662 | +0.09 | +0.07 | 0.947 | 0.471 | 6.9 | — |
| H7_first_hour_high_vol NIFTY | 665 | +1.85 | +0.52 | 0.763 | 0.522 | 6.9 | — |
| H1_intraday_momentum BANKNIFTY | 1999 | -0.52 | -0.66 | 0.763 | 0.501 | 6.6 | — |
| H2_first_half_hour_ex_gap BANKNIFTY | 2008 | +0.14 | +0.20 | 0.947 | 0.504 | 6.6 | — |
| H3_first_hour_continuation BANKNIFTY | 2008 | +3.72 | +1.67 | 0.253 | 0.523 | 6.6 | — |
| H4_large_gap BANKNIFTY | 686 | -2.92 | -0.60 | 0.763 | 0.506 | 6.9 | — |
| H5_opening_range_breakout BANKNIFTY | 1871 | +8.38 | +3.58 | 0.005 | 0.542 | 6.6 | follow |
| H6_momentum_high_vol BANKNIFTY | 662 | -2.06 | -1.15 | 0.500 | 0.470 | 7.1 | — |
| H7_first_hour_high_vol BANKNIFTY | 664 | +3.11 | +0.66 | 0.763 | 0.517 | 7.1 | — |

## Locked period (opened once)

| test | direction | days | mean (bps) | t (NW) | one-sided p | net of hurdle (bps) | verdict |
|---|---|---|---|---|---|---|---|
| H5_opening_range_breakout BANKNIFTY | follow | 952 | +3.55 | +0.96 | 0.1680 | -2.57 | fail |

Opened 2026-10-03T23:37:02.494976+05:30.
