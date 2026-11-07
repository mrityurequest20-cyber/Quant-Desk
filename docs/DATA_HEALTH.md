# Data health

One command, one workflow: did each data channel deliver today, and is what arrived sane?

```
python -m quantdesk data health [--day YYYY-MM-DD] [--json] [--summary]
```

`.github/workflows/data-health.yml` runs it at 19:00 and 22:15 IST on weekdays. It only **reads** (public release assets, the `premarket` branch, the Actions API), writes only the run summary, holds no secret, and installs only `requirements.txt`. The run goes **red** when a critical channel is bad or missing. A non-trading day (weekend or NSE holiday) has nothing due and passes.

## What each channel is judged on

| Channel | Critical | OK when | WARN | BAD / MISSING |
|---|---|---|---|---|
| Session bars (5 symbols) | yes | every symbol has 98% or more of the 375 session minutes, prices possible, no flat run, the morning and afternoon jobs agree | below 98%, an impossible bar, a flat run outside the closing auction, two jobs disagree | below 90% for any symbol, or no file |
| Option chains (5 indices) | yes | every index has a snapshot in 98% or more of the minutes and nothing to quarantine | rows to quarantine, duplicated rows, below 98% | below 90% for any index, or no file |
| Fetch tape | no | 95% or more of fetch attempts succeeded | 80 to 95% | below 80%, or no file |
| GIFT Nifty pre-open | no | 3 or more prints | fewer | no file |
| Option and stock minutes | no | every contract / stock asked for was served | a failure or a stale last bar | below 90% served, or no manifest |
| NSE warehouse (6 daily tables) | yes | newest day is the expected one (today after 21:00 IST, else the last trading day) | one trading day behind, or a file with under half its usual rows | two or more days behind, or a table with nothing |
| Pre-market brief | no | the `premarket` branch holds today's brief | | missing, stale, or not JSON |
| Stock option minutes | no | every stock's contracts asked for were served and the newest bar is the day's | one or more stocks below 98% | any stock below 90%, or no manifest |
| MCX/currency minutes (the previous evening's) | no | every future asked for was served in both segments | a segment below 98%, or the run was cut short | a segment below 90% or unreadable, or no manifest |
| Daily history | no | a dataset on the `daily-history` release, under 45 days old, every series verified | older, or some series unverified | no dataset |
| Kite ticks | no | an encrypted tick artifact of real size exists | | none (arrival is all that can be checked: the content is encrypted) |

Before a channel's due time (`DUE` in `health.py`) it is **pending**, not missing. A check that cannot run is reported as such (critical: BAD), never skipped.

## Why these thresholds

They come from looking at the real healthy days of 4 to 6 Nov 2026, not from guesses: 375 bars a symbol, a chain snapshot about every minute for each index, a tape that succeeds about 99.9% of the time. The 98% completeness line is the exit criterion in `docs/RENAISSANCE.md`. NIFTY and BANKNIFTY sit flat for the closing auction (from about 15:14, with volume still printing): that is the exchange, so flat runs that start at or after 15:10 are ignored.

## Quarantine: the corrupt open interest

On 4, 5 and 6 Nov the Kotak chain feed produced open interest of about -9.08e18 (an integer overflow) on BANKNIFTY strikes of the 23 Nov expiry, 38, 92 and 58 rows a day. `chain_fault_mask(chains)` marks every row that must not be used: open interest below zero or above 1e12, a bid above the ask, a non-positive spot or strike. **Any code that reads recorded chains for a decision or a study should drop the rows it marks.** The report counts them each day, so the fault is visible rather than silently averaged in. The recorded files are not edited.

## Not covered yet

* The Kite tick content (it is encrypted; `kite-compare` measures it).
* The Kite wide universe's MCX and currency ticks (they are encrypted with the rest); the MCX/currency minutes above are the checkable record of those two segments.
* Wiring `chain_fault_mask` into `archive.load_archive` (the ML OI module already quarantines on its own).
