# P0.6 result: the one counted run of the version 2 check (30 Oct 2026)

Aggregates and hashes only. No Yahoo or NSE row, and no Kaggle or aeron7 data, is in this file. The record itself (`verification.json`) stays beside the dataset, outside the repository; its sha256 is below.
This file records a result; it changes no rule. `docs/ml/P0_6_criteria_v2.md` is untouched.

## Outcome in one line

**`passed: false`. `symbols_verified: []`. The dataset stays `external_unverified`, and nothing was flipped.** One rule failed: **BANKNIFTY check C, month rule, 2020-03: 15 of 19 compared sessions agree (78.9%), 80% needed.** This is the outcome the verifier's `PRIOR_EXPOSURE` text and the criteria's "Prior exposure" section said to expect (BANKNIFTY C, 2020-03, 15 of 19).

## What ran

| | |
|---|---|
| Check | `p06-v2` (`supersedes: "p06-v1 (void)"`, `post_hoc: true`) |
| Code | `main` at `64d56bd` (#147), fresh clone for this run; the record says `dirty: false` |
| Criteria | `docs/ml/P0_6_criteria_v2.md`, sha256 `508534f5657190f3ca57ee1cd8dd76cbc81aedabcced056a421f9ad7a019b51b` (pinned in `intake.VERIFICATION_CRITERIA`) |
| Dataset | `ml-intake-2-feae259bdba6`, digest `47d28d6376ca63af6f435c7a7fab16dc403cc99a7c49ab954ded2c68ed98e9b8` |
| Reference for C | aeron7 `aeron7-2-906fc2378b`, manifest sha256 `d149dc2937d9859b7d6cdb7ab26593ff3fabbb26612d926f2140b47bc60b3708` |
| Record | `verification.json`, sha256 `f6288b06893d100605cdcb859e1e29e297aafff40c4efda4eaddcda25d646957`, written 30 Oct 2026 20:16 IST |
| NSE | 787 archive files read, 51 weekdays with no file (404), reference-file manifest sha256 `5a5311c15e5059a2335925ae45bfac52765379f4f91e4517330af0cfdd7664b7`, closes CSV sha256 `6eb98865f1a4cbb1a2a9265a0036a0f2d2f6863e703a346d06243006b26c4395`. **786 of the 787 file hashes equal those of the pre-run scan (the scan manifest of the criteria, sha256 `044d56ca…9fa8c`, which uses a different manifest format from the record's `files_manifest_sha256`); 2023-10-23 differs (scan `fa74e790…`, run `176c0139…`, the cached file matches the record), cause unknown: the scan's files were not kept. The three swapped files match. B passes at 100% either way.** |
| Yahoo | `^NSEI` 787 rows (sha256 `43b4989a…1883`), `^NSEBANK` 786 rows (sha256 `e4d67f55…40f6`), yfinance 1.7.0, `auto_adjust=False`, fetched 30 Oct 2026; yfinance logged "Crumb fetch rate-limited (HTTP 429), continuing without crumb" (the data were fetched, row counts as stated) |
| Swapped NSE labels accepted (`date_label_swapped`) | exactly the three named files: 2023-04-06 (`04-06-2023`), 2023-04-10 (`04-10-2023`), 2023-04-11 (`04-11-2023`) |

**Void attempts, none of which compared anything.** The version 1 run voided on 30 Oct 2026 at 13:48 IST, while fetching the NSE file dated 2023-04-06 ( log sha256 `d7be976f412fec09fd90ccdb7a7c48e47991c4048b36eee79b079747dbef8533`; the reason version 2 exists). The first attempt of the version 2 check voided at 19:43 IST on a transient network error while fetching the NSE file for 2025-05-13 (`IncompleteRead`, log sha256 `a98a8bae863e3184cee1734d54416a3c173f2325daaf218d6d3b76a9acf8cb47`), with no record written; the record carries only the version 1 log's sha256, so the second void log's is given here only. The check was then run again with the same code, as the criteria's "one run" rule allows after a void ("may be run again with the same rules"). **The rerun used the cache the voided attempt had left (537 of the 787 files, each hashed in the record), not a new empty folder, which departs from the criteria's wording for the first run**; the 51 days with no file are not cached, so they were asked again. No rule or number changed. That second attempt is the counted run recorded here.

## Numbers

| Check | Symbol | Compared | Agree rate | Gross errors | Longest failing run | Worst judged month | Result |
|---|---|---|---|---|---|---|---|
| A (Yahoo daily OHLC, 2023-03 to 2026-05) | NIFTY | 784 of 784 | 100.0% | 0 | 0 | 2023-03: 100% | pass |
| A | BANKNIFTY | 784 of 784 | 99.87% | 0 | 1 | 2023-05: 95.5% | pass |
| B (NSE official close) | NIFTY | 784 of 784 | 100.0% | 0 | | | pass |
| B | BANKNIFTY | 784 of 784 | 100.0% | 0 | | | pass |
| C (aeron7 overlap, to Feb 2023) | NIFTY | 1,993 common | 99.05% | 0 | 2 | 2015-08: 81.0% | pass |
| C | BANKNIFTY | 1,992 common | 96.74% | 0 | 2 | **2020-03: 78.9% (15 of 19)** | **FAIL (month rule)** |
| D (integrity) | both | | | | | | pass |

Check C's minute-return correlation (both symbols): median 0.9996; 98.85% of common sessions at 0.95 or better (90% needed); no undefined correlation. Coverage of aeron7's sessions by the Kaggle data: 99.70% (95% needed). Every other rule of check C held for BANKNIFTY (pass rate 96.74% against 95% needed; no gross error; run rule).

## What this does and does not show

- **Observed in this record (not a claim, and no label):** in the new window (2023-03-01 to 2026-05-15) the Kaggle **daily high, low and close** agree with Yahoo (A) on 100% of 784 compared sessions for NIFTY and 99.87% for BANKNIFTY (one disagreeing session, 2023-05-11, high differs by 0.23%), and, on the close, with NSE's own file (B) on 100% for both, with no gross error in any compared session. Against aeron7, NIFTY passes every rule of C; BANKNIFTY passes every rule of C but the month rule in one month. These observations come from a record that failed and licenses nothing.
- **Not shown:** nothing independent checks the minute path or the minute timestamps after Feb 2023 (scope of the criteria). C checks consistency between two minute-data vendors, not independent accuracy. B is nearly the same quantity as A's close (Yahoo's index data derive from NSE's).
- **The label:** the criteria allow no partial licence. **No symbol is `external_verified`, and nothing may be quoted as verified.** Any quote of this result says: version 2 was written after a void version 1 run, departs from version 1's "rerun with the same rules", is post hoc, and check C had been rehearsed on 25 Oct (BANKNIFTY 2020-03 was already seen to fail then).
- **Not investigated:** the four BANKNIFTY sessions in 2020-03 that disagree with aeron7 have not been examined. Nothing here argues that the failure is benign.
- **Not done by this change:** no status flip, no loader change, no criteria change, no rule loosened.

## What the owner can decide next (nothing below is started)

1. **Accept the result as it stands.** The dataset stays `external_unverified`; studies that use it say so. The A and B observations above are recorded, carry no label, and may not be quoted as verification.
2. **Ask for a version 3 criteria file.** It would be written after this failure, committed alone before any rerun, post hoc by construction, and the old record moved (not overwritten) to `verification_p06-v2.json` first, as the criteria's "After a failure" says. Any result under it could not be quoted as a clean pass.
