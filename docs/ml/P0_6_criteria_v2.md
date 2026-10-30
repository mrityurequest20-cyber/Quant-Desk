# P0.6 criteria: the independent check of the Kaggle index minutes (version 2)

Committed **alone, before any verifier change and before any A or B result** (check C had been rehearsed on 25 Oct, see "Prior exposure"). This is `P0_6_criteria_v2.md`; `P0_6_criteria.md` (version 1) is untouched and stays as merged.
**Version 2 is identical to version 1 in every rule, number and threshold except one reference-file rule, stated in "The one changed rule" below; "Wording corrected from version 1" separately lists three sentences of version 1 reworded to match the reviewed verifier, none of which changes a gate.** It was written after a **void**
version 1 run, not after a failed one: that run produced no comparison of any kind, so **no result of the dataset against Yahoo or NSE (checks A and B) and no result of the
version 1 run existed when this file was written**. That is not the same as the engineer having no earlier information; see "Prior exposure" below, which says what was known.
Edit this file after a result and the check is void: a changed rule is a new file.

**Version 2 departs from version 1.** Version 1 says a void run "may be run again with the same rules". This file does not rerun with the same rules: it changes one rule, because
with the same rules the check can never complete (see below). That is a post hoc change of the criteria, made by the engineer on the owner's instruction to go the version 2 route (30 Oct); the owner approves this file by merging it, and every quote of the
outcome says so.

## Why version 2

- On 30 Oct 2026 the one version 1 run was started from `main` (commit `8220039`, dataset digest `47d28d63…`, a new empty cache folder). It stopped while fetching NSE's file
  for 2023-04-06 and logged `void_run_20261030T134834279524.json` (`VoidRun: NSE file for 2023-04-06 says Index Date 2023-06-04`). It compared nothing: no dataset value was
  read against any reference, so no result exists. That is a void by the version 1 rule ("a run is void only on an exception or HTTP error raised by the code").
- The cause is a defect **inside NSE's own archive**: that file's `Index Date` field reads `04-06-2023`, the file's date with day and month swapped. Version 1 says such a file
  "is an error", so while the archive stays as it was on 30 Oct 2026 version 1 **cannot complete**: a rerun with the same rules voids at the same file. NSE could correct the file later (version 2 therefore accepts zero swapped files); the engineer does not wait for that, because the run is one counted run and the owner chose version 2.
- **Before writing this file, the engineer scanned the reference files only** (not the dataset): all 838 weekdays from 2023-03-01 to 2026-05-15, comparing each file's `Index Date`
  with its name. 51 answered HTTP 404 (6.1%). Of the other 787, **exactly three files** carry a swapped label, on both index rows each: 2023-04-06 (`04-06-2023`), 2023-04-10
  (`04-10-2023`) and 2023-04-11 (`04-11-2023`); no file has any other date problem, a missing row or a bad format. Nothing about how the dataset compares with any reference
  was looked at. The scan's only content is this paragraph. It was run twice (30 Oct 2026) with the same counts; the second run saved the sha256 of every file that answered 200:
  - the three files: `2023-04-06` = `5ec0d8a41e5494f414df3774648d954ca0160c799759bd538625277dc9011cda`, `2023-04-10` = `575d1b73761842e3150c3e788fef14664ad725055aa5e2fe49e1abfe78bef9f4`,
    `2023-04-11` = `37ede13a06f935aa915f51fb3533c75c9e75dc317114e0eb14e3eacc733b1483`;
  - the scan manifest (787 lines `YYYY-MM-DD <sha256 of that file>`, in date order, newline-terminated): sha256 `044d56ca41c889310478e26a9bc4e0a2ec1c49e4376d7947b5ba811fdbe9fa8c`.
- **The void log** `void_run_20261030T134834279524.json` has sha256 `d7be976f412fec09fd90ccdb7a7c48e47991c4048b36eee79b079747dbef8533`. It is not committed (it names a path of the
  engineer's cache); the counted record carries its sha256.

## Prior exposure (said plainly)

- On 25 Oct 2026, after the version 1 criteria were merged and before the counted run, the engineer rehearsed the verifier on a copy of the real dataset with **synthetic** Yahoo and NSE references. That rehearsal
  exercised **check C** (dataset against aeron7) on the real data: **NIFTY passed** (worst month 2015-08 at 81% agreeing, above the 80% floor); **BANKNIFTY failed the month rule only**
  (2020-03: 15 of 19 compared sessions agree, 16 would pass). Checks A and B had no real reference then and no result.
- No rule or number was changed because of that rehearsal, and none is changed in version 2 other than the date rule. The verifier already says, in its `PRIOR_EXPOSURE` text,
  that its record is **expected to be `passed: false` with no symbol licensed**, and version 2 carries that text unchanged into its record.
- So version 2 is **not** a blind rerun: a BANKNIFTY failure of C is expected, and a **version 3 (written after that failure) is likely**. Neither the label `external_verified` nor any
  claim from this check can be made on the strength of version 2 alone, and any version 3 is post hoc as well.

## The one changed rule

- **Version 1:** the file's `Index Date` must equal the date in its name, otherwise it is an error (the run is void).
- **Version 2:** the file's `Index Date` must equal the date in its name, **or** be the **swapped label of that date**, defined once here: the verifier first reads the label as
  `DD-MM-YYYY` (NSE's format); a label is *swapped* if, read as `MM-DD-YYYY` instead, it equals the date in the file's name (name 2023-04-06, label `04-06-2023`: read as
  `DD-MM-YYYY` it is 4 June, read as `MM-DD-YYYY` it is 6 April, the name's date). The swapped reading must be a valid calendar date different from the one read as `DD-MM-YYYY`.
  **The exception is pinned to the three files named above (name dates 2023-04-06, 2023-04-10, 2023-04-11).** A swapped label in any other file, or a fourth file, is an error and voids
  the run, exactly as a mismatch of any other kind does; zero swapped files among the three is acceptable (NSE may have corrected them). Every file accepted by the swap is **listed in
  the record** (`date_label_swapped`: the date in the name and the label text) and counted. The closing values in such a file are used as they are: nothing is corrected, re-dated or
  dropped. If a swapped file's values were in fact another day's, the comparison fails visibly, as it would for any wrong reference.

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
  `Nifty Bank`, field `Closing Index Value` (the file also carries open, high and low; only the close is used). One file is fetched per weekday of the window, and also for the date of every accepted session that falls on a weekend (a Budget or Muhurat special session);
  every raw file is saved, and the sha256 of each file, of a manifest listing them and of the `date,symbol,close` CSV built from them is recorded. A weekday
  whose file answers HTTP 404 is a day NSE published no index file (a holiday or a closure) and is not an error; any other HTTP error, a timeout, or a file
  without the two rows is an error and voids the run (see "one run"). The file's `Index Date` must equal the date in its name, or be the swapped label of one of the three pinned files (version 2, see "The one changed rule"), otherwise it is an error. If more than 10% of the weekdays answer 404 the run is void (the archive layout changed; holidays are about 6% of weekdays). Requests carry a browser `User-Agent`, because the archive may refuse requests without one (a 403 voids the run). Only the sha256 and aggregates are committed, never reference rows.

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
at least **90%** of common sessions and at least 0.98 at the median session; an undefined correlation (fewer than 30 one-minute return pairs from consecutive common minutes; see "Wording corrected from version 1") counts as a failure. A
one-minute labelling shift would drive this to about zero, which is the point. **C shows consistency with aeron7, not independent accuracy:** the two vendors
may share an upstream feed, and aeron7 was itself checked only on 80-session samples.

**D. Integrity only (not evidence).** The manifest digest recomputes, partitions hash to the manifest and the accepted-session list matches the minutes loaded.
The loader already enforces this; it is listed so a failure is on the record.

**Information only (never gating).** The record lists, per symbol, the sessions in `review` and `rejected` with counts, and does not run A and B on them (see "Wording corrected from version 1"). It reports
`accepted_reviewed` sessions separately: if a reviewer's evidence cited Yahoo or NSE, they are not independent of A and B. Admitting a session after the run
changes the manifest digest and voids the record.

## What the pass means, and does not

- **Scope of the claim:** NIFTY and BANKNIFTY. In the **new window** only the **daily envelope** (high, low, close) is independently checked; nothing independent
  checks minute timestamps or the intraday path after Feb 2023. In the **overlap** the daily envelope and 1-minute returns agree with aeron7. Any study quoting the
  label `external_verified` states this scope. The record carries `symbols_verified` and `scope` fields saying so.
- **The status label and the loader.** The manifest `status` is dataset-wide and sits outside the digest, so it is not evidence by itself. `intake.effective_status` (merged before the
  version 1 verifier) already returns `external_unverified` for any symbol not in the record's `symbols_verified`, treats a record **without** `symbols_verified` or `criteria_sha256`
  as unverified for every symbol, and accepts a record only when its `check` is registered in `intake.VERIFICATION_CRITERIA` and its `criteria_sha256` equals the pinned hash. No new
  loader logic is needed. What remains for version 2 is a separate, independently reviewed, tighten-only change that registers `p06-v2` in `VERIFICATION_CRITERIA` with the sha256 of this
  file **as merged**, and updates the verifier (the pinned-criteria check, `date_label_swapped`, `supersedes`, `post_hoc`, the void-log sha256, `PRIOR_EXPOSURE` carried verbatim) and the
  status-only flip to emit and accept a `p06-v2` record. Until then a pass writes `verification.json` but leaves the manifest `external_unverified`. After that change merges, flipping the
  manifest status is a **status-only step** that copies `passed` from the existing record; it is not a second run and re-compares nothing.
- Index minutes are not option-chain, bid/ask, IV or execution data and cannot qualify an option strategy, a DTE change, the paper gate, a promotion or a
  profitability claim, whatever this check says.

## Wording corrected from version 1

Three sentences of version 1 do not describe what the merged verifier (`quantdesk/ml/verify.py` at `8220039`) does, and version 2 states what it does. None changes a gate number or loosens a rule; the
verifier is not changed by this file. Two more passages are rewritten, and neither changes a gate: the sentence in "Why version 2" on why version 1 cannot complete (now date-qualified), and the
paragraph on the status label and the loader in "What the pass means" (now describing the loader as merged).

- **Minute-return correlation, undefined.** Version 1 says "fewer than 30 common minutes". The verifier computes the correlation only between consecutive minutes present in both series and calls it
  undefined (a failure) when it has **fewer than 30 such return pairs** (`MIN_COMMON_MINUTES = 30`, counted in pairs). The verifier is never looser than version 1's words: it is stricter whenever the common minutes are not
  consecutive (100 common minutes in alternating positions give no pair at all), and it treats a flat series (zero variance) as undefined, which version 1 does not mention. Both differences count as a failure.
- **Information only.** Version 1 says the record "runs A and B on" the `review` and `rejected` sessions. The verifier **lists** them (`info_only`: counts and days, per symbol) and does not compare them:
  the importer builds the partitions from `accepted` and `accepted_reviewed` sessions only. Nothing gated on that run, so no pass or fail changes; the information version 1 promised is simply not produced.
- **The record file name.** Version 1 and the verifier write `verification.json` and refuse to run while it, or `verification_<check>.json`, exists. Version 1's phrase "kept as `verification_p06-v1.json`"
  means the record is moved to that name before a later criteria file runs; version 2 says so in "After a failure".

## Not done, and why

- **The Kotak overlap** (in the Phase 0 plan): the desk's own Kotak tape starts on 5 Oct 2026 and this dataset ends on 15 May 2026; there is no common session.
  It cannot be done and is not claimed.
- **15 May to early Sep 2026 index minutes:** accepted as a hole. The aeron7 repository was looked at on 24 Oct 2026 for later data: its folders end at `2023`
  and it has no release. Nothing in Phase 0 needs those months: the HAR one-shot window ends 14 May 2026, and the open-interest shadow reads the desk's tape.

## Outcome and "one run"

- **All rules hold for both symbols:** `verification.json` is written beside the manifest with `passed: true`, `check: "p06-v2"`, the dataset digest, this
  file's sha256, `symbols_verified`, `scope`, the reference sources and dates, the sha256 of each reference file, and the numbers. It also carries `supersedes: "p06-v1 (void)"`, the sha256 of the void log
  (`d7be976f…`, above), `post_hoc: true`, `date_label_swapped`, and the verifier's `PRIOR_EXPOSURE` text.
- **Anything fails:** `verification.json` is written with `passed: false` and the reasons; the status stays `external_unverified`; nothing is retried with looser
  rules.
- **One run** means one run that produced comparisons. A run is void only on an exception or HTTP error raised by the code, logged in `void_run_<time>.json` (the reason) with nothing else written; the check may then be
  run again with the same rules. Version 2 itself is run **once**, from a fresh clone of `main` with a new empty cache folder outside any git tree. A void is never the operator's judgment: a reference that returns incomplete data without an error is a counted run.

## After a failure

If a failure looks benign, the next step is a new criteria file written after it, committed before any rerun. The record of this run is `verification.json` (see "Outcome and one run"). Before any later
criteria file is run, that record is **moved, not overwritten,** to `verification_p06-v2.json` (the verifier refuses to run while either file exists), and a later pass records
`supersedes: p06-v2`. Any quote of the verified label states that version 2 was written after a void version 1 run, before any comparison of A or B, for the one reason given above, that it
departs from version 1's rule of rerunning with the same rules, that check C had been exercised on 25 Oct ("Prior exposure"), and that the record carries `date_label_swapped` and `post_hoc: true`.
