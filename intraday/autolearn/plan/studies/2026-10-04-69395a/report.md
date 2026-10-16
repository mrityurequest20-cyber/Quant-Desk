# Plan-level research — 2026-10-04-69395a

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
| 3-5 | 120m | put | 3 | 1 | -0.524 | 0.33 | 2.7% | 1 | 0 | +0.093 | — … — |
| 3-5 | 120m | call | 2 | 1 | -0.199 | 0.50 | 1.3% | 1 | 0 | -0.443 | — … — |
| 3-5 | 30m | put | 10 | 1 | -0.221 | 0.20 | 2.8% | 2 | 0 | -0.098 | — … — |
| 3-5 | 30m | call | 9 | 1 | +0.055 | 0.56 | 1.8% | 2 | 0 | +0.205 | — … — |
| 3-5 | 60m | put | 8 | 1 | -0.145 | 0.50 | 2.5% | 2 | 0 | -0.238 | — … — |
| 3-5 | 60m | call | 7 | 1 | -0.147 | 0.29 | 1.4% | 2 | 0 | -0.033 | — … — |
| 3-5 | close | put | 1 | 1 | -1.061 | 0.00 | 0.9% | 1 | 0 | -1.051 | — … — |
| 6+ | 120m | put | 3 | 1 | -0.385 | 0.00 | 1.3% | 1 | 0 | -0.481 | — … — |
| 6+ | 120m | call | 2 | 1 | +0.206 | 1.00 | 1.1% | 0 | 2 | — | — … — |
| 6+ | 30m | put | 7 | 1 | -0.174 | 0.00 | 1.4% | 2 | 0 | -0.169 | — … — |
| 6+ | 30m | call | 8 | 1 | +0.095 | 0.88 | 1.1% | 0 | 8 | — | — … — |
| 6+ | 60m | put | 7 | 1 | -0.225 | 0.00 | 2.3% | 2 | 0 | -0.216 | — … — |
| 6+ | 60m | call | 7 | 1 | +0.089 | 1.00 | 1.0% | 0 | 7 | — | — … — |

Locked final period: not opened (insufficient real point-in-time data: 1 session(s) with complete real plans; the protocol needs 28 (15 training + 5 folds + 8 locked). Descriptive only; nothing fitted.).
Approved: no.

## 2. Modelled scenario results — SCENARIO ANALYSIS ONLY

Priced by the desk's model from bhavcopy IV / India VIX. Not evidence of an edge; never combined with real results; never used for promotion, a DTE change or the paper gate.

Sessions: 53 (2026-07-20 → 2026-10-01). Completed modelled plan outcomes: 100,320. IV sources: {'bhavcopy': 25080}. Exclusions: {}.

| bucket | horizon | side | plans | sessions | mean net R | P(net>0) | cost / premium | replay trades | unaffordable | replay exp. R | 90% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 120m | put | 924 | 11 | -0.034 | 0.32 | 11.0% | 22 | 0 | +1.025 | +0.344 … +1.720 |
| 0 | 120m | call | 924 | 11 | -0.575 | 0.16 | 11.5% | 21 | 0 | -0.911 | -1.250 … -0.583 |
| 0 | 30m | put | 924 | 11 | -0.096 | 0.31 | 10.5% | 22 | 0 | +0.798 | +0.192 … +1.410 |
| 0 | 30m | call | 924 | 11 | -0.506 | 0.18 | 11.2% | 20 | 0 | -0.776 | -1.124 … -0.449 |
| 0 | 60m | put | 924 | 11 | -0.044 | 0.32 | 10.9% | 22 | 0 | +0.989 | +0.311 … +1.691 |
| 0 | 60m | call | 924 | 11 | -0.556 | 0.16 | 11.4% | 21 | 0 | -0.856 | -1.204 … -0.505 |
| 0 | close | put | 924 | 11 | -0.034 | 0.32 | 11.1% | 22 | 0 | +1.025 | +0.344 … +1.720 |
| 0 | close | call | 924 | 11 | -0.575 | 0.16 | 11.5% | 21 | 0 | -0.911 | -1.250 … -0.583 |
| 1 | 120m | put | 924 | 11 | -0.086 | 0.39 | 5.1% | 22 | 0 | +0.466 | +0.062 … +0.866 |
| 1 | 120m | call | 924 | 11 | -0.178 | 0.31 | 5.5% | 22 | 0 | -0.444 | -0.879 … +0.026 |
| 1 | 30m | put | 924 | 11 | -0.048 | 0.40 | 4.6% | 22 | 0 | +0.710 | +0.301 … +1.123 |
| 1 | 30m | call | 924 | 11 | -0.153 | 0.32 | 4.7% | 22 | 0 | -0.506 | -0.788 … -0.222 |
| 1 | 60m | put | 924 | 11 | -0.060 | 0.39 | 4.9% | 22 | 0 | +0.631 | +0.156 … +1.101 |
| 1 | 60m | call | 924 | 11 | -0.165 | 0.34 | 5.1% | 22 | 0 | -0.491 | -0.881 … -0.074 |
| 1 | close | put | 924 | 11 | -0.045 | 0.39 | 5.2% | 22 | 0 | +0.335 | -0.128 … +0.787 |
| 1 | close | call | 924 | 11 | -0.220 | 0.30 | 5.7% | 22 | 0 | -0.511 | -0.933 … -0.013 |
| 2 | 120m | put | 924 | 11 | -0.186 | 0.37 | 3.6% | 22 | 0 | -0.174 | -0.371 … +0.061 |
| 2 | 120m | call | 924 | 11 | -0.012 | 0.38 | 3.6% | 21 | 0 | -0.042 | -0.229 … +0.149 |
| 2 | 30m | put | 924 | 11 | -0.141 | 0.33 | 3.4% | 22 | 0 | -0.170 | -0.288 … -0.067 |
| 2 | 30m | call | 924 | 11 | -0.068 | 0.35 | 3.5% | 21 | 0 | -0.178 | -0.262 … -0.083 |
| 2 | 60m | put | 924 | 11 | -0.167 | 0.35 | 3.5% | 22 | 0 | -0.245 | -0.390 … -0.094 |
| 2 | 60m | call | 924 | 11 | -0.037 | 0.38 | 3.6% | 21 | 0 | -0.150 | -0.207 … -0.074 |
| 2 | close | put | 924 | 11 | -0.242 | 0.38 | 3.7% | 18 | 0 | -0.033 | -0.328 … +0.387 |
| 2 | close | call | 924 | 11 | -0.013 | 0.35 | 3.7% | 16 | 0 | -0.027 | -0.331 … +0.228 |
| 3-5 | 120m | put | 2772 | 33 | +0.069 | 0.45 | 3.4% | 64 | 0 | +0.149 | +0.051 … +0.243 |
| 3-5 | 120m | call | 2772 | 33 | -0.283 | 0.28 | 3.4% | 56 | 373 | -0.406 | -0.487 … -0.319 |
| 3-5 | 30m | put | 2772 | 33 | -0.043 | 0.39 | 3.3% | 64 | 0 | +0.050 | -0.034 … +0.137 |
| 3-5 | 30m | call | 2772 | 33 | -0.173 | 0.28 | 3.3% | 66 | 0 | -0.212 | -0.269 … -0.154 |
| 3-5 | 60m | put | 2772 | 33 | +0.019 | 0.45 | 3.3% | 64 | 0 | +0.126 | +0.027 … +0.227 |
| 3-5 | 60m | call | 2772 | 33 | -0.226 | 0.29 | 3.3% | 66 | 11 | -0.283 | -0.347 … -0.215 |
| 3-5 | close | put | 2772 | 33 | +0.129 | 0.50 | 3.5% | 49 | 0 | +0.368 | +0.199 … +0.528 |
| 3-5 | close | call | 2772 | 33 | -0.338 | 0.25 | 3.6% | 44 | 271 | -0.524 | -0.647 … -0.394 |
| 6+ | 120m | put | 6996 | 53 | -0.062 | 0.38 | 3.0% | 102 | 38 | +0.016 | -0.048 … +0.082 |
| 6+ | 120m | call | 6996 | 53 | -0.119 | 0.32 | 3.0% | 93 | 873 | -0.171 | -0.241 … -0.094 |
| 6+ | 30m | put | 6996 | 53 | -0.085 | 0.29 | 3.0% | 104 | 50 | -0.050 | -0.092 … -0.007 |
| 6+ | 30m | call | 6996 | 53 | -0.107 | 0.26 | 3.0% | 101 | 345 | -0.146 | -0.186 … -0.104 |
| 6+ | 60m | put | 6996 | 53 | -0.076 | 0.36 | 3.0% | 104 | 44 | -0.035 | -0.086 … +0.016 |
| 6+ | 60m | call | 6996 | 53 | -0.117 | 0.30 | 3.0% | 96 | 707 | -0.166 | -0.225 … -0.103 |
| 6+ | close | put | 6996 | 53 | -0.041 | 0.42 | 3.1% | 59 | 18 | +0.029 | -0.077 … +0.130 |
| 6+ | close | call | 6996 | 53 | -0.135 | 0.32 | 3.0% | 66 | 19 | -0.217 | -0.327 … -0.093 |

Every configuration tried (20), scenario analysis only:

| config | hash | status | trades | days | exp. R | 90% CI R | P(win) | PF | net ₹ | DSR | abstain | unaffordable | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 30m|0|plan_logit | 9fdb9124 | ok | 8 | 5 | +0.049 | -1.010 … +1.637 | +0.38 | +1.49 | 11,624 | — | +0.98 | 0 | no |
| 30m|1|plan_logit | 3d5236ee | ok | 6 | 3 | +0.108 | -0.361 … +0.892 | +0.50 | +1.23 | 3,084 | — | +0.98 | 0 | no |
| 30m|2|plan_logit | d62b9a74 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +1.00 | 0 | no |
| 30m|3-5|plan_logit | 3f966b1c | ok | 10 | 5 | +0.011 | -0.220 … +0.160 | +0.70 | +1.12 | 762 | +0.00 | +0.99 | 0 | no |
| 30m|6+|plan_logit | 67670508 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +1.00 | 0 | no |
| 60m|0|plan_logit | 4cd81b2f | ok | 6 | 3 | +0.784 | -1.046 … +2.872 | +0.50 | +2.73 | 32,543 | — | +0.97 | 0 | no |
| 60m|1|plan_logit | 9fa531e3 | ok | 10 | 5 | +0.085 | -0.587 … +0.743 | +0.40 | +1.12 | 3,860 | +0.00 | +0.94 | 0 | no |
| 60m|2|plan_logit | e2eb04b4 | ok | 6 | 3 | -0.250 | -0.328 … -0.160 | +0.33 | +0.14 | -9,116 | — | +0.97 | 0 | no |
| 60m|3-5|plan_logit | eec0dca1 | ok | 12 | 7 | +0.074 | -0.161 … +0.373 | +0.50 | +1.35 | 3,477 | +0.00 | +0.99 | 0 | no |
| 60m|6+|plan_logit | 4ab53191 | ok | 0 | 0 | — | — … — | — | — | 0 | — | +1.00 | 0 | no |
| 120m|0|plan_logit | 53667351 | ok | 7 | 4 | +0.541 | -1.018 … +2.097 | +0.43 | +1.84 | 21,044 | — | +0.96 | 0 | no |
| 120m|1|plan_logit | 37432987 | ok | 10 | 5 | -0.480 | -0.984 … +0.229 | +0.20 | +0.26 | -30,753 | +0.00 | +0.93 | 0 | no |
| 120m|2|plan_logit | 758d0986 | ok | 8 | 4 | +0.192 | -0.299 … +0.848 | +0.38 | +1.77 | 6,183 | — | +0.89 | 0 | no |
| 120m|3-5|plan_logit | 61439976 | ok | 11 | 6 | +0.060 | -0.226 … +0.376 | +0.45 | +1.23 | 2,399 | +0.00 | +0.99 | 0 | no |
| 120m|6+|plan_logit | 9a385937 | ok | 24 | 14 | -0.053 | -0.235 … +0.084 | +0.46 | +0.72 | -5,388 | +0.00 | +0.99 | 1 | no |
| close|0|plan_logit | 5b05904b | ok | 5 | 3 | -0.391 | -1.046 … +0.550 | +0.20 | +0.46 | -13,688 | — | +0.98 | 0 | no |
| close|1|plan_logit | 57b0b06f | ok | 6 | 3 | -0.908 | -1.049 … -0.626 | +0.00 | +0.00 | -31,856 | — | +0.98 | 0 | no |
| close|2|plan_logit | 5bb29c11 | ok | 2 | 2 | -0.579 | -1.075 … -0.083 | +0.00 | +0.00 | -7,210 | — | +0.99 | 0 | no |
| close|3-5|plan_logit | 79d6be89 | ok | 17 | 9 | +0.175 | -0.162 … +0.517 | +0.47 | +1.49 | 16,802 | +0.00 | +0.99 | 0 | no |
| close|6+|plan_logit | df0b0fe5 | ok | 17 | 15 | -0.261 | -0.583 … +0.108 | +0.41 | +0.34 | -22,712 | +0.00 | +0.99 | 3 | no |

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

Replay hash: 49927d172a471df7.
