# P0.6 criteria: the independent check of the Kaggle index minutes (version 1)

Committed **alone, before any verifier code and before any result**. Edit this file after a result and the check is void: a changed rule is a new file
(`P0_6_criteria_v2.md`) written **after a failed v1** and saying why (see "After a failure"). The rules below were fixed without looking at how the dataset
compares with any reference. (Revised once before merge after an independent review; no result existed then or exists now.)

## What is checked

- **Dataset:** `ml-intake-2-feae259bdba6`, manifest digest `47d28d6376ca63af6f435c7a7fab16dc403cc99a7c49ab954ded2c68ed98e9b8`, tier T1b, source Kaggle
  `debashis74017/nifty-50-minute-data` (version 18), licence unknown, not redistributable (so it stays out of the repository; only this file, the code and
  an aggregate report are committed).
- **Symbols that can pass or fail:** `NIFTY` and `BANKNIFTY`. `INDIAVIX` is **not** checked and has no claim.
- **Sessions compared:** every session the importer accepted (`accepted` or `accepted_reviewed`). Not a sample, so there is no seed.
- **New window:** 2023-03-01 to 2026-05-15 (the dataset's last day), the part the already-verified aeron7 data does not cover. **Overlap window:** every
  accepted session also in aeron7 (`aeron7-2-906fc2378b`, `external_verified`, whose manifest ends in Feb 2023).

## Definitions

- **Daily bar from minutes:** high = maximum of the minute highs, low = minimum of the minute lows, close = the last minute's close (the 15:29 bar).
- **Official close is not a last print.** NSE computes an index's closing value from the last 30 minutes, so the 15:29 bar can miss it by 0.3 to 0.6% on some
  days. A **close agrees** if the 15:29 close **or** the mean of the 15:00 to 15:29 minute closes is within 0.3% of the reference close.
- **Agree (daily):** `|ours/ref − 1|` at most 0.2% on high, 0.2% on low, and the close rule above (the tolerances of `external_aeron.TOLERANCE`).
- **Gross error:** a compared session off by more than 1.5% on high or low, or on the close under **both** close definitions (15:29 close and the 15:00 to 15:29 mean).
- **References, pinned:** Yahoo Finance daily bars for `^NSEI` and `^NSEBANK` via `yfinance` with `auto_adjust=False`, retrieved on the day of the run (date
  recorded). NSE: NSE's own daily index file `https://archives.nseindia.com/content/indices/ind_close_all_<DDMMYYYY>.csv`, the rows `Nifty 50` and
  `Nifty Bank`, field `Closing Index Value` (the file also carries open, high and low; only the close is used). One file is fetched per weekday of the window;
  every raw file is saved, and the sha256 of each file, of a manifest listing them and of the `date,symbol,close` CSV built from them is recorded. A weekday
  whose file answers HTTP 404 is a day NSE published no index file (a holiday or a closure) and is not an error; any other HTTP error, a timeout, or a file
  without the two rows is an error and voids the run (see "one run"). Only the sha256 and aggregates are committed, never reference rows.

## The checks (per symbol; every rule must hold)

**Coverage (A and B).** A *phantom* session is an accepted session on a day with no NSE index file; one phantom session fails the symbol. A
session in the window with no Yahoo (or NSE) row is *not compared*, and every one is listed in the record. At least 500 sessions and at least 95% of the accepted
sessions in the window are compared, and more than 1% of accepted sessions uncompared fails the symbol. Accepted sessions must be at least **97% of the NSE
index files' days** in the window (importer rejections must not flatter the pass rate).

**A. Yahoo daily OHLC, new window.** At least **95%** of compared sessions agree; no gross error anywhere (any one fails the symbol); **no calendar month with
fewer than 80% agreeing** (months with fewer than 10 compared sessions are reported, not judged); **no run of more than 5 consecutive failing compared sessions**
(an uncompared session neither breaks nor extends a run).

**B. NSE official close, close only, new window.** At least 95% of compared sessions agree on the close rule; no gross error. **B is nearly the same
quantity as A's close** (Yahoo's index data derive from NSE's), so it adds protection only against a Yahoo-specific error, not a second vendor. Said plainly.

**C. aeron7 overlap, session by session.** Coverage for C: at least 500 sessions in common, and at least 95% of the aeron7-accepted sessions in the overlap are also
Kaggle-accepted (the reverse direction is reported, not gating; aeron7 is not a trading calendar). Daily high, low and close agree to **0.1%** (tighter than A: two minute vendors
should agree to a few basis points; the close rule above is not used here, both sides are last prints); at least **95%** agree; no gross error; the month rule
and the run rule of A apply. And the correlation of 1-minute log returns, **taken only between consecutive minutes present in both series**, is at least 0.95 in
at least **90%** of common sessions and at least 0.98 at the median session; an undefined correlation (fewer than 30 common minutes) counts as a failure. A
one-minute labelling shift would drive this to about zero, which is the point. **C shows consistency with aeron7, not independent accuracy:** the two vendors
may share an upstream feed, and aeron7 was itself checked only on 80-session samples.

**D. Integrity only (not evidence).** The manifest digest recomputes, partitions hash to the manifest and the accepted-session list matches the minutes loaded.
The loader already enforces this; it is listed so a failure is on the record.

**Information only (never gating).** The record lists, per symbol, the sessions in `review` and `rejected` with counts, and runs A and B on them. It reports
`accepted_reviewed` sessions separately: if a reviewer's evidence cited Yahoo or NSE, they are not independent of A and B. Admitting a session after the run
changes the manifest digest and voids the record.

## What the pass means, and does not

- **Scope of the claim:** NIFTY and BANKNIFTY. In the **new window** only the **daily envelope** (high, low, close) is independently checked; nothing independent
  checks minute timestamps or the intraday path after Feb 2023. In the **overlap** the daily envelope and 1-minute returns agree with aeron7. Any study quoting the
  label `external_verified` states this scope. The record carries `symbols_verified` and `scope` fields saying so.
- **The status label is dataset-wide today** (`intake.effective_status`). The record therefore cannot flip the manifest to `external_verified` until the loader
  returns `external_unverified` for any symbol not in `symbols_verified` and checks this file's sha256 (`criteria_sha256`). That loader change is a separate,
  independently reviewed, tighten-only change, merged first. It must also treat a record **without** `symbols_verified` or `criteria_sha256` as unverified for
  every symbol (the manifest status is outside the digest and a hand edit of it must not make a record dataset-wide verified), and it compares
  `criteria_sha256` with the sha256 of this file as merged. Until then a pass writes `verification.json` but leaves the manifest `external_unverified`. After the
  loader change merges, flipping the manifest status is a **status-only step** that copies `passed` from the existing record; it is not a second run and re-compares
  nothing.
- Index minutes are not option-chain, bid/ask, IV or execution data and cannot qualify an option strategy, a DTE change, the paper gate, a promotion or a
  profitability claim, whatever this check says.

## Not done, and why

- **The Kotak overlap** (in the Phase 0 plan): the desk's own Kotak tape starts on 5 Oct 2026 and this dataset ends on 15 May 2026; there is no common session.
  It cannot be done and is not claimed.
- **15 May to early Sep 2026 index minutes:** accepted as a hole. The aeron7 repository was looked at on 24 Oct 2026 for later data: its folders end at `2023`
  and it has no release. Nothing in Phase 0 needs those months: the HAR one-shot window ends 14 May 2026, and the open-interest shadow reads the desk's tape.

## Outcome and "one run"

- **All rules hold for both symbols:** `verification.json` is written beside the manifest with `passed: true`, `check: "p06-v1"`, the dataset digest, this
  file's sha256, `symbols_verified`, `scope`, the reference sources and dates, the sha256 of each reference file, and the numbers.
- **Anything fails:** `verification.json` is written with `passed: false` and the reasons; the status stays `external_unverified`; nothing is retried with looser
  rules.
- **One run** means one run that produced comparisons. A run is void only on an exception or HTTP error raised by the code, logged in `void_run_<time>.json` (the reason) with nothing else written; the check may then be
  run again with the same rules. A void is never the operator's judgment: a reference that returns incomplete data without an error is a counted run.

## After a failure

If a failure looks benign, the next step is a `P0_6_criteria_v2.md` that **states it was written after a failed v1** and why, committed before any rerun. The v1
record is kept as `verification_p06-v1.json` and never overwritten; a later pass records `supersedes: p06-v1` and `post_hoc: true`, and any quote of the
verified label says so.
