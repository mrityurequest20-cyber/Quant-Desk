# TrueData export audit · batch f94705809b16 (truedata-1)

Source: TrueData Velocity 2.0 export at `/home/user/quantdesk-truedata` (commit b25f54775c). Status **external_verified**. TrueData index candles are not option-chain, bid/ask, IV, trade-by-trade footprint, aggressor volume or order-book data, and never qualify an option strategy, a DTE change, a paper gate, a promotion or a profitability claim.

| file | bytes | sha256 | schema | timeframe | accepted | rejected | first → last | duplicates (identical / conflicting) |
|---|---|---|---|---|---|---|---|---|
| BANKNIFTY.txt | 17,537 | `4a03de386d6c` | date,time,open,high,low,close,extra_1,extra_2,extra_3,extra_4 | 1d | 247 | 0 | 03-10-2025 17:30:00 → 01-10-2026 17:30:00 | 0 / 0 |
| NIFTY.txt | 17,537 | `193a5711ee77` | date,time,open,high,low,close,extra_1,extra_2,extra_3,extra_4 | 1d | 247 | 0 | 03-10-2025 17:30:00 → 01-10-2026 17:30:00 | 0 / 0 |

## Independent check (Yahoo Finance daily (^NSEI, ^NSEBANK), 2026-10-04T02:17): passed

Tolerances: {'open': 0.003, 'high': 0.002, 'low': 0.002, 'close': 0.003} (relative). A weekday absent from both sides is a market holiday.

- 1d/symbol=BANKNIFTY.parquet: 246 dates compared, 100.0% within tolerance; only in TrueData: 2026-02-01; only in the reference: none.
- 1d/symbol=NIFTY.parquet: 246 dates compared, 100.0% within tolerance; only in TrueData: 2026-02-01; only in the reference: none.

## Per file

**BANKNIFTY.txt**
- Layout: {'10': 247} fields per row; header: none; line endings: 247 CRLF, 0 LF; date format `%d-%m-%Y`, time format `%H:%M:%S`.
- Time zone: one bar per date stamped 17:30:00: an end-of-day marker, not a trade time; dates are NSE session dates.
- Not populated (zero in every row, given no meaning): extra_1, extra_2, extra_3, extra_4.
- Weekend sessions kept and flagged: 2026-02-01.

**NIFTY.txt**
- Layout: {'10': 247} fields per row; header: none; line endings: 247 CRLF, 0 LF; date format `%d-%m-%Y`, time format `%H:%M:%S`.
- Time zone: one bar per date stamped 17:30:00: an end-of-day marker, not a trade time; dates are NSE session dates.
- Not populated (zero in every row, given no meaning): extra_1, extra_2, extra_3, extra_4.
- Weekend sessions kept and flagged: 2026-02-01.

