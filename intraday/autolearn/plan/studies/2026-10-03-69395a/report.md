# Plan-level research — 2026-10-03-69395a

Index data: 2026-07-20 → 2026-10-01, 53 sessions (BANKNIFTY, NIFTY). Recorded chain snapshots: 104. Bhavcopy rows: 674,306. Cost model c3-af7dbbfbb8.
Fee model vs paper fills: {'fills': 0, 'note': 'no paper option fills yet: the cost model is unverified against fills'}.

## 1. Real point-in-time results (the only qualifying evidence)

Sessions with recorded chains: 2 ['2026-09-29', '2026-09-30']. Sessions with complete real plans: 1. Completed real plan outcomes: 74.
Exclusions: {'no_fresh_real_snapshot': 99, 'no_bar_at_decision': 132, 'real_entry_but_modelled_marks_or_exit': 190}.
Status: insufficient real point-in-time data: 1 session(s) with complete real plans; the protocol needs 28 (15 training + 5 folds + 8 locked). Descriptive only; nothing fitted.
Lock: no lock yet: 1 real sessions, 28 needed.

Descriptive (development sessions; not a result: too few sessions to mean anything):

| bucket | horizon | side | plans | sessions | mean net R | P(net>0) | cost / premium | replay trades | unaffordable | replay exp. R | 90% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 3-5 | 120m | put | 3 | 1 | -0.524 | 0.33 | 2.7% | 0 | 3 | — | — … — |
| 3-5 | 120m | call | 2 | 1 | -0.199 | 0.50 | 1.3% | 0 | 2 | — | — … — |
| 3-5 | 30m | put | 10 | 1 | -0.221 | 0.20 | 2.8% | 0 | 10 | — | — … — |
| 3-5 | 30m | call | 9 | 1 | +0.055 | 0.56 | 1.8% | 0 | 9 | — | — … — |
| 3-5 | 60m | put | 8 | 1 | -0.145 | 0.50 | 2.5% | 0 | 8 | — | — … — |
| 3-5 | 60m | call | 7 | 1 | -0.147 | 0.29 | 1.4% | 0 | 7 | — | — … — |
| 3-5 | close | put | 1 | 1 | -1.061 | 0.00 | 0.9% | 0 | 1 | — | — … — |
| 6+ | 120m | put | 3 | 1 | -0.385 | 0.00 | 1.3% | 0 | 3 | — | — … — |
| 6+ | 120m | call | 2 | 1 | +0.206 | 1.00 | 1.1% | 0 | 2 | — | — … — |
| 6+ | 30m | put | 7 | 1 | -0.174 | 0.00 | 1.4% | 0 | 7 | — | — … — |
| 6+ | 30m | call | 8 | 1 | +0.095 | 0.88 | 1.1% | 0 | 8 | — | — … — |
| 6+ | 60m | put | 7 | 1 | -0.225 | 0.00 | 2.3% | 0 | 7 | — | — … — |
| 6+ | 60m | call | 7 | 1 | +0.089 | 1.00 | 1.0% | 0 | 7 | — | — … — |

Locked final period: not opened (insufficient real point-in-time data: 1 session(s) with complete real plans; the protocol needs 28 (15 training + 5 folds + 8 locked). Descriptive only; nothing fitted.).
Approved: no.

## 2. Modelled scenario results — SCENARIO ANALYSIS ONLY

Priced by the desk's model from bhavcopy IV / India VIX. Not evidence of an edge; never combined with real results; never used for promotion, a DTE change or the paper gate.

Sessions: 53 (2026-07-20 → 2026-10-01). Completed modelled plan outcomes: 100,320. IV sources: {'bhavcopy': 25080}. Exclusions: {}.

| bucket | horizon | side | plans | sessions | mean net R | P(net>0) | cost / premium | replay trades | unaffordable | replay exp. R | 90% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 120m | put | 924 | 11 | -0.034 | 0.32 | 11.0% | 22 | 0 | +1.007 | +0.327 … +1.704 |
| 0 | 120m | call | 924 | 11 | -0.575 | 0.16 | 11.5% | 21 | 36 | -0.903 | -1.180 … -0.619 |
| 0 | 30m | put | 924 | 11 | -0.096 | 0.31 | 10.5% | 22 | 0 | +0.777 | +0.168 … +1.388 |
| 0 | 30m | call | 924 | 11 | -0.506 | 0.18 | 11.2% | 21 | 34 | -0.835 | -1.110 … -0.552 |
| 0 | 60m | put | 924 | 11 | -0.044 | 0.32 | 10.9% | 22 | 0 | +0.968 | +0.287 … +1.673 |
| 0 | 60m | call | 924 | 11 | -0.556 | 0.16 | 11.4% | 21 | 36 | -0.903 | -1.180 … -0.619 |
| 0 | close | put | 924 | 11 | -0.034 | 0.32 | 11.1% | 22 | 0 | +1.007 | +0.327 … +1.704 |
| 0 | close | call | 924 | 11 | -0.575 | 0.16 | 11.5% | 21 | 36 | -0.903 | -1.180 … -0.619 |
| 1 | 120m | put | 924 | 11 | -0.086 | 0.39 | 5.1% | 22 | 2 | +0.301 | -0.165 … +0.757 |
| 1 | 120m | call | 924 | 11 | -0.178 | 0.31 | 5.5% | 20 | 74 | -0.477 | -0.948 … +0.029 |
| 1 | 30m | put | 924 | 11 | -0.048 | 0.40 | 4.6% | 22 | 3 | +0.532 | -0.003 … +1.035 |
| 1 | 30m | call | 924 | 11 | -0.153 | 0.32 | 4.7% | 20 | 76 | -0.572 | -0.880 … -0.236 |
| 1 | 60m | put | 924 | 11 | -0.060 | 0.39 | 4.9% | 22 | 2 | +0.472 | -0.088 … +0.998 |
| 1 | 60m | call | 924 | 11 | -0.165 | 0.34 | 5.1% | 20 | 85 | -0.583 | -0.964 … -0.164 |
| 1 | close | put | 924 | 11 | -0.045 | 0.39 | 5.2% | 22 | 13 | +0.221 | -0.302 … +0.715 |
| 1 | close | call | 924 | 11 | -0.220 | 0.30 | 5.7% | 20 | 75 | -0.527 | -0.947 … -0.046 |
| 2 | 120m | put | 924 | 11 | -0.186 | 0.37 | 3.6% | 4 | 760 | -0.281 | -0.451 … -0.112 |
| 2 | 120m | call | 924 | 11 | -0.012 | 0.38 | 3.6% | 5 | 714 | -0.049 | -0.116 … +0.220 |
| 2 | 30m | put | 924 | 11 | -0.141 | 0.33 | 3.4% | 3 | 798 | -0.451 | -0.454 … -0.446 |
| 2 | 30m | call | 924 | 11 | -0.068 | 0.35 | 3.5% | 5 | 719 | -0.091 | -0.197 … +0.239 |
| 2 | 60m | put | 924 | 11 | -0.167 | 0.35 | 3.5% | 4 | 778 | -0.211 | -0.496 … +0.074 |
| 2 | 60m | call | 924 | 11 | -0.037 | 0.38 | 3.6% | 5 | 720 | -0.130 | -0.223 … +0.239 |
| 2 | close | put | 924 | 11 | -0.242 | 0.38 | 3.7% | 2 | 765 | -0.635 | -1.070 … -0.200 |
| 2 | close | call | 924 | 11 | -0.013 | 0.35 | 3.7% | 3 | 702 | -0.078 | -0.338 … +0.052 |
| 3-5 | 120m | put | 2772 | 33 | +0.069 | 0.45 | 3.4% | 0 | 2772 | — | — … — |
| 3-5 | 120m | call | 2772 | 33 | -0.283 | 0.28 | 3.4% | 2 | 2674 | -0.581 | -0.581 … -0.581 |
| 3-5 | 30m | put | 2772 | 33 | -0.043 | 0.39 | 3.3% | 0 | 2772 | — | — … — |
| 3-5 | 30m | call | 2772 | 33 | -0.173 | 0.28 | 3.3% | 2 | 2660 | +0.016 | +0.016 … +0.016 |
| 3-5 | 60m | put | 2772 | 33 | +0.019 | 0.45 | 3.3% | 0 | 2772 | — | — … — |
| 3-5 | 60m | call | 2772 | 33 | -0.226 | 0.29 | 3.3% | 2 | 2648 | -0.392 | -0.392 … -0.392 |
| 3-5 | close | put | 2772 | 33 | +0.129 | 0.50 | 3.5% | 0 | 2772 | — | — … — |
| 3-5 | close | call | 2772 | 33 | -0.338 | 0.25 | 3.6% | 1 | 2695 | -1.071 | -1.071 … -1.071 |
| 6+ | 120m | put | 6996 | 53 | -0.062 | 0.38 | 3.0% | 0 | 6996 | — | — … — |
| 6+ | 120m | call | 6996 | 53 | -0.119 | 0.32 | 3.0% | 0 | 6996 | — | — … — |
| 6+ | 30m | put | 6996 | 53 | -0.085 | 0.29 | 3.0% | 0 | 6996 | — | — … — |
| 6+ | 30m | call | 6996 | 53 | -0.107 | 0.26 | 3.0% | 0 | 6996 | — | — … — |
| 6+ | 60m | put | 6996 | 53 | -0.076 | 0.36 | 3.0% | 0 | 6996 | — | — … — |
| 6+ | 60m | call | 6996 | 53 | -0.117 | 0.30 | 3.0% | 0 | 6996 | — | — … — |
| 6+ | close | put | 6996 | 53 | -0.041 | 0.42 | 3.1% | 0 | 6996 | — | — … — |
| 6+ | close | call | 6996 | 53 | -0.135 | 0.32 | 3.0% | 0 | 6996 | — | — … — |

Every configuration tried (20), scenario analysis only:

| config | hash | status | trades | days | exp. R | 90% CI R | P(win) | PF | net ₹ | DSR | abstain | unaffordable | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 30m|0|plan_logit | 7fd2b1a2 | ok | 8 | 5 | +0.020 | -1.026 … +1.601 | +0.38 | +1.03 | 201 | — | +0.98 | 0 | no |
| 30m|1|plan_logit | 9b989b4a | ok | 6 | 3 | -0.020 | -0.681 … +0.861 | +0.33 | +0.69 | -1,110 | — | +0.95 | 13 | no |
| 30m|2|plan_logit | bca712d7 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +1.00 | 0 | no |
| 30m|3-5|plan_logit | 3598b58a | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.85 | 294 | no |
| 30m|6+|plan_logit | 46481c4e | ok | 0 | 0 | — | — … — | — | — | 0 | — | +1.00 | 0 | no |
| 60m|0|plan_logit | 7d827953 | ok | 6 | 3 | +0.741 | -1.085 … +2.826 | +0.50 | +2.31 | 4,155 | — | +0.97 | 0 | no |
| 60m|1|plan_logit | 2a2a7008 | ok | 10 | 5 | +0.035 | -0.653 … +0.703 | +0.40 | +0.93 | -470 | +0.00 | +0.93 | 1 | no |
| 60m|2|plan_logit | 8490184c | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.68 | 127 | no |
| 60m|3-5|plan_logit | 743320ef | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.83 | 336 | no |
| 60m|6+|plan_logit | 632f7735 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +1.00 | 0 | no |
| 120m|0|plan_logit | 4cf98c61 | ok | 7 | 4 | +0.500 | -1.053 … +2.052 | +0.43 | +1.64 | 2,861 | — | +0.96 | 0 | no |
| 120m|1|plan_logit | 49afd2a6 | ok | 8 | 4 | -0.462 | -1.096 … +0.503 | +0.25 | +0.44 | -3,186 | — | +0.69 | 56 | no |
| 120m|2|plan_logit | 41c90308 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.20 | 317 | no |
| 120m|3-5|plan_logit | f39b27a2 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.79 | 410 | no |
| 120m|6+|plan_logit | 98b50497 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.90 | 496 | no |
| close|0|plan_logit | cc4a562e | ok | 5 | 3 | -0.430 | -1.085 … +0.505 | +0.20 | +0.50 | -2,215 | — | +0.98 | 0 | no |
| close|1|plan_logit | 1420e68c | ok | 6 | 3 | -0.954 | -1.101 … -0.672 | +0.00 | +0.00 | -4,898 | — | +0.98 | 0 | no |
| close|2|plan_logit | c09d7726 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.82 | 73 | no |
| close|3-5|plan_logit | a4792cad | ok | 1 | 1 | -0.036 | -0.036 … -0.036 | +0.00 | +0.00 | -48 | — | +0.63 | 719 | no |
| close|6+|plan_logit | 22d9df54 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +0.75 | 1234 | no |

Best by the selection rule (scenario analysis only, not selected for anything): none

## 3. Real end-of-day approximation (bhavcopy open → close) — not point in time, cannot qualify

Sessions: 246 (2025-10-03 → 2026-10-01). Plan outcomes: 1,741. Exclusions: {'eod_untraded_strike': 3}.

| symbol | bucket | side | plans | sessions | mean net R | P(net>0) | cost / premium | stops | 90% CI R |
|---|---|---|---|---|---|---|---|---|---|
| BANKNIFTY | 0 | put | 12 | 12 | -1.201 | 0.17 | 3.1% | 10 | -2.295 … +0.069 |
| BANKNIFTY | 0 | call | 12 | 12 | -2.782 | 0.00 | 3.0% | 12 | -3.230 … -2.292 |
| BANKNIFTY | 1 | put | 12 | 12 | +0.700 | 0.33 | 3.8% | 8 | -0.479 … +1.957 |
| BANKNIFTY | 1 | call | 12 | 12 | -0.964 | 0.17 | 2.8% | 10 | -1.840 … -0.188 |
| BANKNIFTY | 2 | put | 12 | 12 | -0.739 | 0.25 | 2.9% | 9 | -1.561 … +0.209 |
| BANKNIFTY | 2 | call | 12 | 12 | +0.161 | 0.42 | 3.3% | 5 | -0.834 … +1.168 |
| BANKNIFTY | 3-5 | put | 34 | 34 | +0.028 | 0.32 | 3.1% | 15 | -0.358 … +0.469 |
| BANKNIFTY | 3-5 | call | 34 | 34 | -0.669 | 0.21 | 2.9% | 20 | -1.001 … -0.300 |
| BANKNIFTY | 6+ | put | 245 | 245 | -0.204 | 0.38 | 2.8% | 63 | -0.291 … -0.120 |
| BANKNIFTY | 6+ | call | 246 | 246 | -0.129 | 0.39 | 2.8% | 45 | -0.205 … -0.048 |
| NIFTY | 0 | put | 52 | 52 | -0.562 | 0.23 | 4.2% | 40 | -1.311 … +0.249 |
| NIFTY | 0 | call | 52 | 52 | -2.653 | 0.00 | 3.7% | 51 | -2.906 … -2.369 |
| NIFTY | 1 | put | 52 | 52 | -0.657 | 0.23 | 3.5% | 38 | -1.173 … -0.115 |
| NIFTY | 1 | call | 52 | 52 | -0.478 | 0.27 | 3.5% | 37 | -1.033 … +0.071 |
| NIFTY | 2 | put | 53 | 53 | -0.776 | 0.23 | 3.2% | 39 | -1.040 … -0.501 |
| NIFTY | 2 | call | 53 | 53 | -0.456 | 0.21 | 3.3% | 34 | -0.783 … -0.115 |
| NIFTY | 3-5 | put | 153 | 153 | -0.196 | 0.36 | 3.2% | 86 | -0.406 … +0.037 |
| NIFTY | 3-5 | call | 153 | 153 | -0.576 | 0.27 | 3.0% | 87 | -0.721 … -0.433 |
| NIFTY | 6+ | put | 244 | 244 | -0.117 | 0.40 | 3.1% | 89 | -0.228 … -0.006 |
| NIFTY | 6+ | call | 246 | 246 | -0.209 | 0.38 | 3.0% | 78 | -0.323 … -0.098 |

## Production change: none. no configuration has passed on real point-in-time evidence (development gates and the locked test): no basis for a DTE or horizon change. Modelled and EOD results cannot supply one.

Replay hash: 35988ff66e317279.
