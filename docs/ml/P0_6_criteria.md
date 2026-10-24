# P0.6 criteria: the independent check of the Kaggle index minutes (version 1)

Committed **alone, before any verifier code and before any result**. Edit this file after a result and the check is void: a changed rule is a new file
(`P0_6_criteria_v2.md`) with the reason stated. The rules below were fixed without looking at how the dataset compares with any reference.

## What is checked

- **Dataset:** `ml-intake-2-feae259bdba6`, manifest digest `47d28d6376ca63af6f435c7a7fab16dc403cc99a7c49ab954ded2c68ed98e9b8`, tier T1b, source Kaggle
  `debashis74017/nifty-50-minute-data` (version 18), licence unknown, not redistributable (so it stays out of the repository; only this file, the code and
  an aggregate report are committed).
- **Symbols that can pass or fail:** `NIFTY` and `BANKNIFTY`. `INDIAVIX` is **not** checked and is **not** covered by any verification claim; no study may use it as
  an input until it has its own check (this file does not give it one).
- **Sessions compared:** every session the importer accepted (`accepted` or `accepted_reviewed`). Not a sample, so there is no seed.
- **Window split:** the *new* window is 2023-03-01 to 2026-05-15 (the dataset's last day), the part the earlier verified aeron7 data does not cover. The
  *overlap* window is every accepted session also in aeron7 (`aeron7-2-906fc2378b`, already `external_verified`, ends Feb 2023).

## The four checks, and what each can fail

A session's daily bar from the minutes: high = maximum of the minute highs, low = minimum of the minute lows, close = the last minute's close.
A session **agrees** with a daily reference when `|ours/ref − 1|` is at most **0.2% on high, 0.2% on low and 0.3% on close** (the tolerances the
aeron7 check used).

| # | Reference | Window | Pass rule (per symbol; all must hold) |
|---|---|---|---|
| A | Yahoo Finance daily OHLC (`^NSEI`, `^NSEBANK`) | new window | at least 500 sessions compared; at least **95%** agree; **no calendar month** with fewer than 80% agreeing (a local corruption must not hide in an average); no run of more than 5 consecutive failing sessions |
| B | NSE's official daily index close (NIFTY 50, NIFTY BANK; via the Bhavcopy source), **close only** | new window | at least 500 sessions compared; at least **95%** within 0.3% |
| C | aeron7 minutes, session by session | overlap window | at least 500 sessions in common; at least **95%** agree on daily high/low/close (same tolerances); **and** the correlation of 1-minute log returns on the common minutes is at least 0.95 in at least **90%** of common sessions and at least 0.98 at the median session (a one-minute labelling shift would drive this to about zero, which is the point) |
| D | the dataset against itself | whole dataset | no accepted session missing from the manifest list the importer wrote; the manifest digest recomputes; partitions hash to the manifest (the loader already refuses otherwise) |

A reference day that is missing from the reference is **not compared**, and the number not compared is reported; a symbol whose compared count is below the
minimum **fails** (fail closed). The Yahoo and NSE closes are not fully independent of each other (Yahoo's index data derive from NSE's), so B adds a check on
the close only; it does not add a second vendor. Said plainly.

## Not done, and why

- **The Kotak overlap** (in the Phase 0 plan): the desk's own Kotak tape starts on 5 Oct 2026 and this dataset ends on 15 May 2026; there is no common session.
  It cannot be done and is not claimed.
- **15 May to early Sep 2026 index minutes:** accepted as a hole. The aeron7 repository was looked at on 24 Oct 2026 for later data: its folders end at `2023`
  and it has no release, so it cannot fill the hole. Nothing in Phase 0 needs those months: the HAR one-shot window ends 14 May 2026, and the open-interest
  shadow reads the desk's own tape.
- **Data checked is index minutes only:** they are not option-chain, bid/ask, IV or execution data and cannot qualify an option strategy, a DTE change, the paper
  gate, a promotion or a profitability claim, whatever this check says.

## Outcome

- **All of A, B, C and D hold for both symbols:** `verification.json` is written beside the manifest with `passed: true`, `check: "p06-v1"`, the dataset
  digest, this file's sha256, the reference sources and the numbers, and the manifest status becomes `external_verified`. A rebuild after that is a new table.
- **Anything fails:** `verification.json` is written with `passed: false` and the reasons; the status stays `external_unverified`; nothing is retried with looser
  rules. If a failure looks benign, the next step is a `v2` criteria file that says why, committed before the rerun.
- **One run.** The record names the code commit that produced it and the sha256 of every reference file used (the reference rows stay out of the repository).
