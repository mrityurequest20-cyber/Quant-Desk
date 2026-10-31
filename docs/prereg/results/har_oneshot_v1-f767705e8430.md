> The dataset was `external_unverified` when this was run, and nothing here is verification. Its P0.6 check (version 2) failed one rule: BANKNIFTY, comparison with the aeron7 minute data, month 2020-03 (15 of 19 sessions agree, 80% needed); the four disagreeing sessions have not been examined. Version 2 was written after a void version 1 run, departs from version 1's rule of rerunning with the same rules, is post hoc, and its check C had been rehearsed on 25 Oct, when BANKNIFTY 2020-03 was already seen to fail; the record carries `post_hoc: true` and lists three NSE files with swapped date labels (`date_label_swapped`).
Its P0.6 checks A and B passed for both symbols over the window, under their coverage and agreement thresholds: check A compared the daily high, low and close with Yahoo, and check B compared only the daily close with NSE's official close, which is nearly the same quantity as A's close, so A and B are not two independent confirmations.
One NSE reference file (2023-10-23) hashes differently from the pre-run scan for an unknown cause, and the counted rerun reused the cache of a voided attempt (both are in the result file; B passes at 100% either way).
Nothing independent checks its minute-by-minute path after Feb 2023, and this evaluation forecasts and scores realised variance built from squared 1-minute log returns (QLIKE loss). This evaluation was run under amendment 1 to its registration.

# har_oneshot_v1 - one-shot evaluation (external_unverified)

**Outcome: PASS. The dataset was `external_unverified` when this was run, and nothing here is verification. Its P0.6 check (version 2) failed one rule: BANKNIFTY, comparison with the aeron7 minute data, month 2020-03 (15 of 19 sessions agree, 80% needed); the four disagreeing sessions have not been examined. Version 2 was written after a void version 1 run, departs from version 1's rule of rerunning with the same rules, is post hoc, and its check C had been rehearsed on 25 Oct, when BANKNIFTY 2020-03 was already seen to fail; the record carries `post_hoc: true` and lists three NSE files with swapped date labels (`date_label_swapped`).
Its P0.6 checks A and B passed for both symbols over the window, under their coverage and agreement thresholds: check A compared the daily high, low and close with Yahoo, and check B compared only the daily close with NSE's official close, which is nearly the same quantity as A's close, so A and B are not two independent confirmations.
One NSE reference file (2023-10-23) hashes differently from the pre-run scan for an unknown cause, and the counted rerun reused the cache of a voided attempt (both are in the result file; B passes at 100% either way).
Nothing independent checks its minute-by-minute path after Feb 2023, and this evaluation forecasts and scores realised variance built from squared 1-minute log returns (QLIKE loss). This evaluation was run under amendment 1 to its registration.**

**Not for:** no option prices: nothing here qualifies an option strategy, a DTE change, a paper gate, a promotion, a live change or a profitability claim.

**Registered use_if_passed (verbatim from the spec; its last sentence holds for every outcome):** only as an offline research candidate for the desk's realised-volatility input, pending a separate reviewed change; its effect on option plans is judged by plan research on real point-in-time quotes, never by this study. A failure, a mixed result or a kill is final for this model and this window

Evidence label: **external_unverified**. Opened 2026-10-31T01:54:28.767658+05:30. Spec sha256 `f767705e84300419b89ed9d997b465c79b0851410816b4ab4e0b7c4d70cb490e` (autolearn.prereg.spec_hash; file `4b06e3b45dee0b5b58d81c53eb6ca6fb9394995c1903c39a797480def6498700`), code commit `fe57bbf4f3bb704c7147f1e3e949f90329b4bc8e`.
Dataset `ml-intake-2-feae259bdba6` (digest `47d28d6376ca63af6f435c7a7fab16dc403cc99a7c49ab954ded2c68ed98e9b8`, status external_unverified, tier T1b); artifact sha256 `de59c4ab9496e9ae2bc828741686949bf5608a2c4af548ce064afa25b3bef56a`; tables `ml-build-1-17fa4e51f2f9` and `ml-build-1-6d0bba555384`; amendment sha256 `5a20ea8daf64660de8bc48c220aa61d4caf980034c0f9e27feb6cb59ccaba157` (commit `264ba8e39c8f8e65392c6f10fea2686aeb0a3540`); criteria v2 sha256 `508534f5657190f3ca57ee1cd8dd76cbc81aedabcced056a421f9ad7a019b51b` (commit `126e9368f48c3382b521e12ade44573e2f923a07`); record sha256 `f6288b06893d100605cdcb859e1e29e297aafff40c4efda4eaddcda25d646957`; lock result sha256 `815d559a0d41978ecbf4f5bfc15a44751a4ac8b22b473f1c0341ba341b3b45cf`.

| cell | days | mean A | mean B | mean C | gain % | DM t | p | Holm p | passes |
|---|---|---|---|---|---|---|---|---|---|
| NIFTY 30m | 784 | 0.2234 | 0.1912 | 0.1911 | +14.4 | +7.00 | 1.28e-12 | 8.99e-12 | yes |
| NIFTY 60m | 784 | 0.2038 | 0.1622 | 0.1667 | +18.2 | +6.95 | 1.77e-12 | 1.06e-11 | yes |
| NIFTY 120m | 784 | 0.2126 | 0.1556 | 0.1631 | +23.3 | +7.78 | 3.77e-15 | 3.01e-14 | yes |
| NIFTY close | 784 | 0.1916 | 0.1555 | 0.1628 | +15.0 | +5.47 | 2.23e-08 | 8.93e-08 | yes |
| BANKNIFTY 30m | 784 | 0.2063 | 0.1804 | 0.1857 | +10.0 | +5.29 | 6.15e-08 | 1.85e-07 | yes |
| BANKNIFTY 60m | 784 | 0.1851 | 0.1494 | 0.1621 | +12.4 | +5.10 | 1.66e-07 | 3.32e-07 | yes |
| BANKNIFTY 120m | 784 | 0.1901 | 0.1374 | 0.1561 | +17.9 | +6.60 | 2.02e-11 | 1.01e-10 | yes |
| BANKNIFTY close | 784 | 0.1743 | 0.1391 | 0.1533 | +12.1 | +4.11 | 1.98e-05 | 1.98e-05 | yes |

Pooled C versus B: 784 dates (0 dropped), t -5.44, one-sided p 1: B_seasonal, which needs no fit, is the cheaper alternative; the HAR layer is not said to add.

Control (spent period): passed within 0.015 in every cell.
Leading-gap sessions dropped from scoring (with the next 5 of that symbol): none.
The weekdays without a row, the sessions with missing minutes and the differences from the expected exclusions are in the JSON preflight; the exchange-holiday check is the steward's (docs/EXTERNAL_DATA.md item 13) and is not repeated by this run.

Everything else (the secondary tables, the accounting of sessions and rows by rule, the refit's coefficients and profile, the frozen coefficients) is in the JSON file beside this one.

> The dataset was `external_unverified` when this was run, and nothing here is verification. Its P0.6 check (version 2) failed one rule: BANKNIFTY, comparison with the aeron7 minute data, month 2020-03 (15 of 19 sessions agree, 80% needed); the four disagreeing sessions have not been examined. Version 2 was written after a void version 1 run, departs from version 1's rule of rerunning with the same rules, is post hoc, and its check C had been rehearsed on 25 Oct, when BANKNIFTY 2020-03 was already seen to fail; the record carries `post_hoc: true` and lists three NSE files with swapped date labels (`date_label_swapped`).
Its P0.6 checks A and B passed for both symbols over the window, under their coverage and agreement thresholds: check A compared the daily high, low and close with Yahoo, and check B compared only the daily close with NSE's official close, which is nearly the same quantity as A's close, so A and B are not two independent confirmations.
One NSE reference file (2023-10-23) hashes differently from the pre-run scan for an unknown cause, and the counted rerun reused the cache of a voided attempt (both are in the result file; B passes at 100% either way).
Nothing independent checks its minute-by-minute path after Feb 2023, and this evaluation forecasts and scores realised variance built from squared 1-minute log returns (QLIKE loss). This evaluation was run under amendment 1 to its registration.
