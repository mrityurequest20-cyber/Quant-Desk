# QuantDesk: Research Validity (Phase E)

Read-only forensic audit, Phase E of the master protocol (`QUANTDESK_FORENSIC_AUDIT.md`). Findings use the register's
format and IDs (`QUANTDESK_FINDINGS_REGISTER.md`).

**Status: Phase E complete, awaiting review.** No production code, strategy logic, model gate, research-selection
rule, trading configuration or execution setting was changed.

---

## E0. Scope, baseline and method

### Scope as defined

**Master protocol, Phase E:** hypothesis generation, preregistration, train/test separation, holdouts,
walk-forward, multiple testing, FDR, selection bias, survivorship bias, lookahead, data snooping,
backtest/paper/live parity, robustness, regime stability, complexity penalty, reproducibility. Each strategy is
placed on the ladder DISCOVERED → REPLICATED → OOS → PAPER → FORWARD → APPROVED, and "backtest success ≠ validation".

**The Phase E request adds eight explicit items:**
1. Provenance and point-in-time (PIT) correctness.
2. Labels, overlap and effective sample size.
3. Multiple testing, confidence intervals and null baselines.
4. Walk-forward, holdout and lockbox handling, and reuse of data.
5. Backtest realism.
6. Reproducibility.
7. Research ↔ autolearn ↔ plan-model ↔ live parity.
8. A reassessment of earlier findings.

**Subphases used here:**

| Subphase | Topic |
|---|---|
| E1 | Data provenance and PIT |
| E2 | Preregistration, memory and integrity |
| E3 | Edge research and live priors |
| E4 | The laws L1/L2, the audits, wings and the entry check |
| E5 | Forward tests (sleeves) and the paper gate |
| E6 | Other studies (autolearn prereg, volstudy, external and TrueData studies) |
| E7 | Statistics and reproducibility |
| E8 | Parity and reassessment |

### Baseline

| Item | Value |
|---|---|
| Starting commit | `97368c11` (audit branch `claude/exciting-galileo-criwur`); `main` = `c96909f` |
| Working tree at start | clean |
| Research tests (15 files under `tests/` that touch `research/`, `prereg`, `laws`, `sleeves`, `memory`) | 81 passed |
| Pre-existing failures | CI: 2 failed / 445 passed / 6 skipped, both in `tests/test_kotak.py`, i.e. A-19 (date bomb). Re-confirmed on CI for this branch's head `97368c1` (job 113740277877). Not caused by the audit (audit files only). |
| Runtime state | `journal` branch snapshot `ecd03156` (2026-10-09 12:20 IST hand-over) |
| Research priors | `research` branch `201028be` |
| Warehouse release | downloaded 2026-10-09: 94 `fo_bhav`, 34 `bse_fo_bhav`, 8 `nse_index_close` parquet files (+ manifests, participant OI/vol) |
| Chain tapes | `chains-2026` assets for 2026-10-05 … 10-08 |

### Evidence classes

Every claim below carries one of these tags:

| Tag | Meaning |
|---|---|
| **[prod]** | Production evidence: the journal snapshot, the research branch, the published results. |
| **[replay]** | Historical rerun of the desk's own code on archived data. |
| **[synth]** | Synthetic test or simulation. |
| **[infer]** | Statistical or arithmetic inference, not directly observed. |
| **[code]** | Code reading. |

---

## E1. Data provenance and point-in-time correctness

| Input | Source | Snapshot kept? | PIT | Finding |
|---|---|---|---|---|
| `fo_bhav`, `bse_fo_bhav` | NSE/BSE end-of-day bhavcopy (warehouse release) | Yes: the release, but rows are overwritten in place (A-14) | End-of-day file. Entry at that day's close is the "known by 15:30" convention, not a live quote (see E4). | E-06 |
| `nse_index_close` | NSE official index OHLC | Same | Official close is published after 15:30. It is used as settlement, which is correct for options. | — |
| Edge research daily/hourly/5m | Yahoo `period=max`, re-downloaded every run | **No.** Only a sha256 and the row count go into `experiment_log.jsonl` | Fine for daily bars. Yahoo minute history is not stable (A-12). | E-06 |
| Global markets (edges) | Yahoo, keyed by the exchange's own date (`_local_daily`) | No | Correct: avoids a same-day leak (V-05 style) | — |
| Recorded 1m index bars / chain tape | Kotak feed (`feed kotak` in every session review since 10-05) | Journal branch / `chains-2026` | **The index freezes from 15:15 to 15:28 every session** (spot frozen, quotes live) | **E-01** |
| External minutes (aeron7, 2010–2023) | Third-party GitHub dataset | Release `external-aeron7` | "external_verified" = 80 random sessions vs Yahoo daily H/L/C | E-09 |
| TrueData study | Private vendor data | Not in the repo or release | Not reproducible by a third party | untested |

### Were historical warehouse rows revised? [replay]

**Today's digests differ from the recorded ones:**

| Table | Today | Recorded in `v2_audit` provenance |
|---|---|---|
| `fo_bhav` | `57e0ba27ff84e3e5` | `d3854e12bc920f10` |
| `bse_fo_bhav` | `4ff6b906c37e3094` | `c47fabf348401a54` |
| `nse_index_close` | `52fc7f877621e496` | `b6fb9e505fa6a77c` |

The digest is a whole-file hash per year, so daily appends alone change it. It cannot tell an append from a revision.

**Settled by direct reproduction instead:** `expiry_eve_law_v2` was rerun with HEAD's `laws.run` on today's data and
cut at the registered result's last expiry (2026-10-01).
- It reproduces exactly: all 7 instruments' n and mean bps, and the pooled 288 weeks / +9.4754 bps / t 4.9772
  (L1) and 288 / +5.4807 / t 3.6338 (L2), equal to float precision.
- So the rows feeding this result were not revised (V-21).
- `audit/probes/phase_e_repro_v2.py` → `audit/data/phase_e_repro_v2.json`.

### Survivorship and selection [code + prod]

- The held-out instruments are the ones listed in the bhavcopy today, so there is no delisted-index survivorship.
- **But the weekly expiries of FINNIFTY, MIDCPNIFTY and BANKEX ended in Nov 2024** (the SEBI rule). After that,
  held-out weeks are mostly SENSEX alone, and FINNIFTY carries 51% of the pooled weight. This is a composition effect,
  documented by the desk's own L1 evidence audit and accepted as a caveat.

### Lookahead

- No lookahead found in `laws`, `wings`, `edges` or `warehouse_research.build_trades`:
  - entry at the eve's close;
  - strikes chosen from that close;
  - settlement at the expiry-day official close.
- The edge tests split discovery from validation chronologically (`_split`, oldest ⅔).

---

## E2. Preregistration, research memory and result integrity

| Check | Result | Class |
|---|---|---|
| Every result file matches its spec hash | **Yes, 7/7.** Two schemes coexist: raw-bytes sha256 (`laws`, `wings`, `law_audit`, `sleeves`) and canonical-JSON sha256 (`autolearn/prereg.py`: `intraday_direction_v1`, `vol_forecast_v1`). `memory.registry` accepts both. | [code+prod] |
| Spec committed before its result | **Yes, in every case** (git author times). v1 spec 01:59Z → result 02:40Z; v2 08:07Z → 08:35Z; v2_audit 09:25Z → 12:06Z; wings 23:49Z → 00:14Z; N1 18:06Z → 18:08Z (lock opened 18:07Z); vol 19:18Z → 19:29Z (lock opened 19:28Z) | [prod] |
| Specs frozen after their result | Yes: no spec file has a commit after its result's commit | [prod] |
| Results carry provenance (code commit, data digest) | **Only `expiry_eve_law_v2_audit`, and it is `dirty: true`.** v1, v2, wings_v1, N1 and the vol study have none. | E-06 |
| Spec fixes the sample it is evaluated on | **No.** `expiry_eve_law_v2.json` has no end date. Rerunning today gives 289 weeks, +9.27 bps, t 4.82; the "evaluated once" result exists only as the stored file. | E-05 |
| Duplicate-experiment guard (`memory.method_fingerprint`) | Works for exact repeats, including reworded ones. **A one-number variant (v2 with t > 1.5) is a new experiment**: no "identical" hit, nearest = v2 at similarity > 0.9. It is a registry, not a multiplicity control. | E-04 |
| Experiment ledger (`research/experiment_log.jsonl`) | 7 lines: an init line plus 2 runs of `edges`/`warehouse_research` on 2026-10-03. "Earlier research reports predate the ledger and are not reconstructed." The laws, wings, audits, prereg studies and reports never write to it. | E-04 |
| Principles ladder vs registered results (`docs/principles.json`) | L1, L2: "replicated" on v2 (v2 = v1 rerun with corrected spot, same held-out instruments; E-05). L3 "found" on vol_forecast_v1. N1 "rejected". L4 "found" with its own caveat: from an unregistered report. No principle claims more than its results support; the caveats are explicit. | [prod] |
| Can the tests fail? | The research suite (81 tests) checks hashes, history ↔ status, duplicate fingerprints and synthetic planted and null effects. It does **not** re-derive any registered number from data, so it would pass on a wrong stored result. | [code] |

---

## E3. Edge research (`research/edges.py`) and the live prior

**Design** [code]:
- 87 fixed hypotheses: daily D1–D6, V1, hourly H1–H3, 5-minute, global links.
- Newey-West t (V-23).
- Benjamini-Hochberg q = 0.10 on **discovery** p-values only (the older ⅔).
- Rolling validation on the newest ⅓: same sign, one-sided p < 0.10. The code says this slice is re-inspected
  weekly and is not a final test.
- A cost hurdle: one lot of a 0.35Δ option round trip in index points.

**Latest run (2026-10-03)** [prod]: 85 NO EDGE, 1 NEEDS MARGIN (V1, the volatility risk premium), and
**1 PAPER CANDIDATE: D1 NIFTY**. D1 is the open → close drift, −5.70 bps/day, t −3.45, validation −4.61 bps.

**Is D1 a Yahoo artifact?** [replay] No. On NSE's official index OHLC (warehouse, 2019–2026):

| Index | Period | n | Mean bps/day | t |
|---|---|---|---|---|
| NIFTY | 2019–2026 | 1,918 | **−6.30** | −3.85 |
| NIFTY | 2019–22 | — | −8.25 | −3.05 |
| NIFTY | 2023–26 | — | −4.23 | −2.27 |
| BANKNIFTY | 2019–2026 | — | −4.87 | −1.95 |

The sign and size replicate on an independent source (V-26). Probe: `phase_e_d1_official.py`.

**How D1 is used live** [code]:
- `load_research()` turns the D1 row of `edges.json` into `drift.per_min`.
- `engine.py:1100` passes it as `base_drift_min` to the EV Monte Carlo for **every** plan, all day.
- No spec in `docs/prereg/` covers it.

**E-03, the cost hurdle** [code + infer]:
- The hurdle assumes fair option prices: "theta is paid for by gamma" (`edges.py` docstring).
- Three of the desk's own results say a short-dated option buyer pays a premium: V1 (VIX above realised), L1
  (sellers are paid on expiry eves) and L4 (buyers overpay).
- Rough size of that premium for a 0.35Δ weekly near expiry: (1 − σ_r²/σ_i²) × theta.
  - With σ_i 14% vs σ_r 11% this is ≈ 9 index points a day per unit.
  - It is several points for an intraday hold.
  - That is comparable to the 0.35 × ~14 pts ≈ 5 pts of D1 an option captures.
- This is **inference, not tested**. The hurdle as coded omits a cost of the same order as the edge.

**Live impact today:** none, because the engine cannot reach a trade (B-02, C-01).

---

## E4. Warehouse research: laws L1/L2, audits, wings, entry check

### Reproduction [replay]

v2 reproduces exactly from today's data (E1, V-21). The two expiries after the registered sample:

| Date | Instrument | Role | bps |
|---|---|---|---|
| 2026-10-06 | NIFTY | discovery | −12.4 |
| 2026-10-08 | SENSEX | held out | −49.9 |

With them the pooled result is 289 weeks, +9.27 bps, t 4.82.

### Statistical robustness of L1 on its own data and convention [replay]

`phase_e_l1_robust.py`, `phase_e_v2_post.py`:

| Check | L1 (strangle) | L2 (insured) |
|---|---|---|
| NW t, lag 0 / auto (5) / 10 | 4.82 / 4.98 / 4.54 | 3.41 / 3.63 / 3.30 |
| ACF of the weekly series, lags 1–4 | −0.05, −0.02, −0.02, +0.05 | −0.06, −0.03, −0.04, +0.03 |
| Moving-block bootstrap (L = 8), one-sided p | < 5·10⁻⁵ | 2·10⁻⁴ |
| Share of the total from the best 5 weeks | 11% | 15% |
| Instruments per pooled week | 1: 184 · 2: 39 · 3: 2 · 4: 43 · 5: 20 | same |
| Held-out mean by expiry year | 2021 +22.7 · 2022 +11.9 · 2023 +9.9 · **2024 +1.4 (n 202)** · 2025 +10.0 · 2026 +8.7 | 2021 +15.3 · … · **2024 −1.6** · 2025 +5.2 · 2026 +5.8 |

**Verdict.** Given the data and the fill convention, L1's held-out result is not a statistical accident.
- It is not autocorrelated, not driven by a few weeks, and robust to the NW lag (V-24).
- L2 is weaker; it was already caveated by the desk (t 1.58 on multi-instrument weeks; negative in 2024).

### Selection before the holdout [prod]

- The desk's own audit counts ≥ 48 discovery cells before L1 was proposed.
- The held-out test was a single pre-registered rule, so discovery multiplicity does not inflate the held-out p.
- **But v2 is not a second holdout** (E-05):
  - it re-tests the same 5 held-out instruments 5½ hours after v1's result was committed;
  - only the spot source differs.
- This was a legitimate correction. Still, "replicated" rests on one exposure of the held-out data.

### Economic realism

- **Spreads** [prod]: real expiry-eve half-spreads on ~0.12–0.30Δ options, 15:00–15:30, from the recorded chain
  tape (`phase_e_eve_spreads.py`):

  | Eve | Strikes | Median half-spread | Model's half-spread | Ratio |
  |---|---|---|---|---|
  | NIFTY 2026-10-05 | 214 | 0.050 | 0.100 | ≈ 0.5× |
  | SENSEX 2026-10-07 | 299 | 0.075 | 0.165 | ≈ 0.45× |

  On the two instruments the desk records, the cost model is conservative.
- **The other held-out instruments** (FINNIFTY, MIDCPNIFTY, BANKEX, NIFTYNXT50) have **no recorded quotes**.
  FINNIFTY carries 51% of the pooled weight. Untested (E-07).
- **Entry price:** the bhavcopy close (last trade on only 26.8% of rows, per the desk's audit). That is not an
  executable quote. `expiry_eve_entry_v1` is properly pre-registered to measure the difference: power analysis,
  40–120 eves, a decision table. It is collecting: 0 decided.
- **Statutory rates:** 2026 rates are applied to all years. This is conservative only where rates rose.

### Wings (L2) and law_audit [prod + code]

- `expiry_wings_v1` selected BANKNIFTY W5. Its NIFTY result (best wing t 1.99 against a 2.0 bar) is reported
  honestly.
- `law_audit`'s 10 checks pass on v2. They are sensitivity reports run once, not new held-out tests.

---

## E5. Forward tests: the sleeves and the paper gate

**What exists** [prod]:
- `expiry_seller_v1` (sleeves A/B on NIFTY and BANKNIFTY), `v2` (BANKNIFTY far-wing condor) and `v3` (D/E on
  FINNIFTY, MIDCPNIFTY and SENSEX).
- In the snapshot: **4 settled trades**:
  - A/B NIFTY, expiry 2026-10-06;
  - D/E SENSEX, expiry 2026-10-08.
- These are the only paper trades the desk has made.

**The design is good in several ways** [code] (V-25):
- Real quotes only, at the 15:20 snapshot.
- Fills at bid − 0.05 / ask + 0.05.
- A logged cost gap against the history's convention.
- An append-only ledger.
- Retirement rules fixed in advance.
- An explicit `no_profit_claim`: "26 trades give an expected t of about 0.27".

### E-01: the forward ledger settles on a frozen index

**The settlement rule** is the mean of the 15:00–15:29 one-minute index closes.

**On every recorded session the Kotak index freezes:**
- O = H = L = C, the same value for 12–14 consecutive minutes from 15:15 to ~15:28;
- volume keeps changing during the freeze;
- then the bar jumps to the official close at 15:29 (NIFTY) or never does (SENSEX).

**The chain tape shows the same freeze:**
- the spot is frozen from 15:15;
- yet every strike's bid/ask keeps updating minute by minute.

So the quotes are live and the index is not. `phase_e_frozen_minutes.py`:

| Day | NIFTY: mean 15:00–15:29 vs 15:29 bar | BANKNIFTY |
|---|---|---|
| 09-29 | −14.2 bps | +15.6 |
| 10-05 | −10.5 | −6.0 |
| **10-06 (expiry)** | **−26.9** | −23.3 |
| 10-07 | −0.3 | +1.1 |
| 10-08 | −10.4 | −7.9 |

**Effect on the four settled trades** [prod + infer]:

| Trade | Registered settle | Official | P&L in ledger (rules use this) | P&L at official |
|---|---|---|---|---|
| A-NIFTY 10-06 | 22,714.88 | 22,776.10 (NSE) | **+₹560** | **−₹3,419** |
| B-NIFTY 10-06 | 22,714.88 | 22,776.10 | **+₹2,142** | **−₹1,838** |
| D-SENSEX 10-08 | 71,438.50 | 71,593.24 (BSE bhavcopy underlying) | −₹10,438 | ≈ −₹7,343 [infer: 154.74 pts × 20] |
| E-SENSEX 10-08 | 71,438.50 | 71,593.24 | −₹11,040 | ≈ −₹7,945 [infer] |

- **`sleeves.assess` uses `pnl_rs`**, the registered settlement. The cost check, consistency z, tail rule and
  eligibility all run on it.
- The official P&L is a diagnostic event (`official`). It was not yet written for SENSEX in the snapshot.
- The history that the consistency z compares against settles on the official close. So the comparison mixes two
  settlement conventions, and one of them is computed half on frozen data.
- **Secondary:** at the 15:20 entry, deltas, and therefore strikes, are computed from a spot that is 5 minutes stale
  while the quotes are live.

### E-02: "eligible for the paper account" means "not rejected"

**The rule:**
- ≥ 10 settled trades;
- the cost check passed;
- consistency not rejected (z > −1.645 against the history's mean and sd).

**Simulation** [synth] (`test_paper_gate_admits_a_zero_edge_sleeve`): with A_NIFTY's history (mean ₹118, sd
₹2,232), a sleeve whose **true edge is zero** is declared eligible after 10 trades in **≈ 93%** of 2,000
simulations.

**Analytical** [infer]: zero-edge survival is 93% for A_NIFTY and 90% for A_BANKNIFTY at n = 10.

**A_NIFTY's own history** is not significant: t 1.05 over 391 expiries.

**Mitigations:**
- the spec states that the forward test cannot show profitability;
- eligibility is "reported, never applied automatically";
- real money stays the owner's decision.

Hence P2, not P1.

---

## E6. Other studies

| Study | Design | Integrity | Finding |
|---|---|---|---|
| `intraday_direction_v1` (N1 rejected) | 7 rules; dev 2010–2018, lock 2019–2023-02, opened once (18:07Z, after the spec at 18:06Z) | Spec hash matches; the lock is single-use | A clean negative. It is consistent with C-02 and D-01: the desk's direction features carry no detectable signal. |
| `vol_forecast_v1` (L3 found) | A_desk vs seasonal vs HAR; dev selection, lock opened once | Clean | **E-08:** A_desk = "the desk's forecaster **without IV**"; production blends 30% ATM IV (`VolForecaster.iv_weight = 0.3`). The live engine still runs the old forecaster: no HAR or seasonal model is in `intraday/quant.py`. |
| `external_study` | direction research on aeron7 minutes; purged and embargoed walk-forward | Uses `allow_unverified=True`; restricted uses respected | E-09 (shallow verification) |
| `truedata_study` | private data | Cannot be rerun | **Untested** |
| L4 ("buyers overpay") | an unregistered report | Its caveat says so | No new finding |

---

## E7. Statistics implementation and reproducibility

Reference checks [synth] (`phase_e_stats_check.py`, V-23):

| Implementation | Check | Result |
|---|---|---|
| `edges.benjamini_hochberg` | vs a reference step-up, 2,000 random families | **0 mismatches**; NaN p treated as 1 |
| `risk.metrics.probabilistic_sharpe` | vs Bailey & López de Prado (2012), t₄ sample | equal to 10⁻⁶ |
| `risk.metrics.deflated_sharpe` | vs the closed form, 50 trials | equal to 10⁻⁶ |
| `edges.hac_mean` (NW) | vs an independent Bartlett implementation on the L1 series | equal (t 4.9772) |
| NW one-sided size, nominal 5%, T = 288 | iid t₃ / AR(1) φ = .5 | 5.4% / **8.1%** |

The 8.1% under strong positive autocorrelation is a known small-sample property. It does not affect L1, whose ACF is
≈ 0.

**Reproducibility:**

| Result | Reproducible? | Notes |
|---|---|---|
| L1/L2 v2 | **Yes**, bit-exact | Needs the cutoff, which is not recorded (E-05). |
| `edges.json` | **No** | Yahoo data is not archived; drift is detectable through the sha256 but not recoverable (E-06). |
| N1 and the vol study | Not rerun here | ~13 years of external minutes; code-level review only. |
| TrueData | No | Private data. |
| Daily-desk backtester (`backtest/runner`, `walkforward`, `montecarlo`) | — | Used by the CLI, `demo.py` and `truedata_study` only. **No production path consumes it.** Reviewed at code level: DSR counts the grid size in `walkforward.py:78`. |

---

## E8. Parity: research ↔ autolearn ↔ plan model ↔ live

| Research says | Production does | Gap |
|---|---|---|
| N1: index direction is not predictable from the desk's features | The architecture still trains a direction model each session (C-02) and gates plans on a plan model (C-01) | The research and the engine disagree on the premise. Live effect: nothing trades (B-02). |
| L3: the desk's vol forecaster is mis-scaled by time of day (move ratio 0.73–1.23) and loses to HAR by 13–35% QLIKE | The EV Monte Carlo still uses `VolForecaster` (with IV, which the study did not test) | E-08 |
| D1: intraday drift, a "paper candidate" | Applied as a base drift to every EV, with no registered spec | E-03 |
| L1: the expiry-eve premium | Traded only by the sleeves (outside the engine), with forward rules | E-01, E-02 |
| Autolearn costs | Futures STT 2 bps vs the desk's 5 bps | C-04 (unchanged) |
| L1 history settles on the official close | Sleeves settle on the 15:00–15:29 mean of a frozen feed | E-01 |

---

## Coverage matrix

| # | Requirement (Phase E request / master protocol) | Covered in | Status |
|---|---|---|---|
| 1 | Data provenance, missing or revised data, source consistency | E1, V-21, E-06 | Covered |
| 1b | PIT of research inputs | E1 | Covered: no lookahead found |
| 2 | Labels, overlap, leakage, contamination | E3 (signed returns), E4 (one trade per expiry; weekly pooling) | Covered. Same-week duplicates: 9 symbol-weeks hold 2 trades, averaged within the week. |
| 2b | Effective sample size | E4: 184 of 288 weeks hold a single instrument; FINNIFTY 51% / SENSEX 30% | Covered |
| 3 | Multiple testing, parameter search, selection bias | E2, E3, E4, E-04 | Covered; the program-wide count is unknowable before the ledger (Q-09) |
| 3b | Confidence intervals and null baselines | E4 (block bootstrap), E5 (zero-edge gate simulation), V-23 | Covered |
| 4 | Walk-forward, purge, embargo, lockbox, repeated inspection, reuse | E2 (lock timings), E3 (rolling validation re-inspected weekly), E4 (v2 reuse, E-05); autolearn lockbox C-07 | Covered |
| 5 | Backtest realism: costs, spreads, slippage, liquidity, sizing, fills | E4 (spreads measured on 2 instruments; entry convention), E5 | Partly. Illiquid held-out instruments untested (E-07, Q-10). |
| 6 | Reproducibility: fingerprints, versions, seeds, artifacts, reruns | E2, E7, V-21 | Covered |
| 7 | Research vs autolearn vs plan model vs live | E8 | Covered |
| 8 | Reassess A–D findings | the section below | Covered |
| M | Hypothesis generation, preregistration | E2 | Covered |
| M | Survivorship bias | E1 | Covered |
| M | Regime stability | E4 (by year; 2024) | Covered |
| M | Complexity penalty | E3 (fixed hypothesis list), E7 (DSR in walk-forward) | Covered at code level |
| M | Paper and live parity, the strategy ladder | E5, E8, the ladder table below | Covered |
| — | TrueData study | — | **Untested:** private data |
| — | Full reruns of N1 and the vol study | — | **Untested:** code review and the published result only |

### Strategy ladder (master protocol)

| Strategy | Discovered | Replicated | OOS | Paper | Forward | Approved |
|---|---|---|---|---|---|---|
| L1 expiry-eve strangle | ✅ NIFTY/BANKNIFTY | ✅ held-out v1/v2 (one exposure) | ✅ held-out instruments | ⚠️ sleeves B/E (4 trades; settled on a frozen index, E-01) | ❌ | ❌ |
| L2 insured condor | ✅ | ⚠️ passed, not robust | ⚠️ | ⚠️ sleeves A/D (as above) | ❌ | ❌ |
| D1 intraday drift | ✅ (87-test screen + BH) | ✅ on NSE official data (V-26) | ⚠️ rolling slice, re-inspected | ❌ no registered paper test | ❌ | ❌ but used in the live EV (E-03) |
| L3 HAR vol forecast | ✅ | ✅ lock | ✅ 2019–23 | ❌ not deployed | ❌ | ❌ |
| Engine directional setups | ❌ (N1 rejected) | — | — | ❌ (B-02) | — | — |

---

## Findings (proposed for the register)

| ID | Title | Sev | Status | Class |
|---|---|---|---|---|
| E-01 | The sleeves' forward ledger settles on a frozen index: Kotak bars freeze 15:15–15:28 every session; the settlement gap reached −27 bps and flipped both NIFTY trades' sign; the rules use that P&L | **P1** | MISLEADING | prod |
| E-02 | Paper-account eligibility = "not rejected": a zero-edge sleeve qualifies ≈ 93% of the time after 10 trades | P2 | VERIFIED | synth + infer |
| E-03 | D1 drift enters every live EV without a registered study; its cost hurdle assumes fair option prices, which the desk's own results contradict | P3 | PARTIAL | code + replay + infer |
| E-04 | No program-wide multiplicity accounting: the ledger covers 2 runs; the duplicate guard admits one-number variants | P2 | PARTIAL | code + prod |
| E-05 | v2 is a re-test of the same held-out instruments, not a second holdout; the spec has no frozen sample end | P3 | PARTIAL | prod |
| E-06 | Result provenance gaps: 1 of 7 results stamped (and dirty); the digest cannot tell appends from revisions; edge data not archived | P3 | PARTIAL | prod + code |
| E-07 | L1's economics are untested where most of its held-out weight sits (no quotes for FINNIFTY/MIDCPNIFTY/BANKEX/NIFTYNXT50; entry at the close) | P3 | UNVERIFIED | prod |
| E-08 | L3 parity: the vol study's "desk" baseline omits the live IV blend, and the better model is not deployed | P3 | PARTIAL | code |
| E-09 | External minutes are "verified" against Yahoo daily H/L/C on 80 sessions only | P4 | PARTIAL | code |

Full entries are in `QUANTDESK_FINDINGS_REGISTER.md`.

### Proven vs suggestive vs untested

**Proven** (production or replay evidence, reproducible here):
- E-01's freeze and its P&L effect on the two NIFTY trades.
- E-02's gate behaviour (synthetic, on the production `assess` function).
- E-04, E-05, E-06 and E-08 as code and record facts.
- The exact reproduction of v2 (V-21).
- D1's sign on official data (V-26).
- L1's statistical robustness on its own convention (V-24).
- The correctness of the stats implementations (V-23).

**Suggestive** (inference):
- E-03's claim that the VRP drag is the same order as D1 (back-of-envelope Greeks).
- E-01's SENSEX official P&L (arithmetic on the BSE bhavcopy underlying, not a desk-written `official` event).
- That the freeze originates at the vendor (seen in both the 1m bars and the tape's spot, while quotes are live)
  rather than in the recorder (Q-08).

**Untested:**
- L1 on illiquid instruments' real quotes (E-07).
- The entry-price artifact (waiting on `expiry_eve_entry_v1`).
- The TrueData study.
- Full reruns of N1 and the vol study.
- Whether the frozen minutes also bias the autolearn "close" labels and the factor grading windows that end after
  15:15 (likely, not measured).

---

## Reassessment of earlier findings

| Finding | Phase E evidence | Change |
|---|---|---|
| A-12 (Yahoo history unstable) | Edge research re-downloads Yahoo `period=max` weekly with no archive | Extends to research: E-06 |
| A-14 (warehouse rows overwritten) | v2's rows reproduce exactly | Risk unrealised for v2's sample; no change to A-14 (the mechanism remains) |
| A-06 (12:20 hole) | — | The freeze (E-01) is a second, systematic recording defect, at 15:15–15:28 |
| B-02 / C-01 (no trade path) | N1 says the premise (predictable direction) is false | Strengthened: research and engine disagree |
| C-02 (session model passes on noise) | N1 lock: 7 rules fail out of sample | Consistent |
| C-04 (two cost models) | Edge hurdle ≠ autolearn costs ≠ desk costs ≠ law spreads | Same pattern; E-03 |
| D-01 (learning is noise) | N1, independently | Consistent |
| D-06 (no baseline) | The sleeves do have a history baseline, but use a different settlement (E-01) | Partial counter-example |

## Verified-working controls added

| ID | Control |
|---|---|
| V-21 | `expiry_eve_law_v2` reproduces bit-exactly from today's warehouse with HEAD code (cutoff 2026-10-01) |
| V-22 | All 7 registered results match their spec hashes; every spec was committed before its result and never edited after; locks opened once, after the spec |
| V-23 | BH, PSR, DSR and NW match reference implementations |
| V-24 | L1's held-out result is robust on its own data: ACF ≈ 0, block-bootstrap p < 5·10⁻⁵, best 5 weeks = 11%, NW lag 0–10 gives t 4.5–5.0 |
| V-25 | The sleeve and entry-check specs are honest about power, use real quotes, log the cost gap, are append-only and fix their retirement rules in advance |
| V-26 | D1's sign and size replicate on NSE's official OHLC (−6.3 bps, t −3.85), so it is not a Yahoo artifact |

## Open questions

| ID | Question |
|---|---|
| Q-08 | Root cause of the 15:15 freeze: the Kotak index LTP, or the desk's polling and aggregation? Needs raw Kotak responses around 15:15. |
| Q-09 | How many hypotheses has the program tested since inception? The ledger starts 2026-10-03 and earlier reports are not reconstructed. |
| Q-10 | Real expiry-eve spreads for FINNIFTY, MIDCPNIFTY, BANKEX and NIFTYNXT50 (no quotes recorded) |
| Q-11 | Do the frozen minutes bias autolearn's "close" labels and plan research's settlement? (Not measured.) |

---

## Remediation plan (prioritized; not implemented: awaiting review)

| Priority | Fix | Addresses | Notes |
|---|---|---|---|
| 1 | Settle sleeves on the exchange's official close (NSE file / BSE bhavcopy underlying), or keep the registered mean but exclude stale minutes. Either is a **new spec** (`expiry_seller_v4`), per the desk's own "changes" rule. Re-derive the 4 trades on both conventions and keep the old ledger frozen. | E-01 | Also detect flat-bar runs at record time (O = H = L = C and unchanged ≥ 3 minutes → flag) |
| 2 | Make paper eligibility require positive evidence (e.g. a sequential test or a one-sided lower bound > 0 on a pooled forward sample), or rename it "not rejected" in the reports. New spec. | E-02 | — |
| 3 | Register D1 as a study before it steers EV; add a VRP / IV-premium term to the edge hurdle, or switch the drift prior off until registered | E-03 | — |
| 4 | Append every registered run (laws, wings, audits, prereg, sleeves' decisions) to `experiment_log.jsonl`; report a running family count; reconstruct the pre-ledger reports as far as possible | E-04 | — |
| 5 | Stamp provenance on every result (`stamp()` already exists); refuse a dirty tree; store a frozen sample end in each spec; per-row or per-day digests | E-05, E-06 | — |
| 6 | Archive the edge research inputs (Parquet) with each run | E-06 | — |
| 7 | Record expiry-eve quotes for every held-out instrument (the tape already exists for NIFTY and SENSEX) | E-07 | — |
| 8 | Re-run vol_forecast with the live forecaster (IV blend) as baseline; then decide on deploying HAR | E-08 | — |
| 9 | Minute-level spot checks of external data against NSE (`nse_index_close` OHLC for 2019–2023) | E-09 | — |

## Probes and reproduction

All scripts are read-only; inputs are copies in a scratch directory.

```
# pytest probes (Phases A–E): 33 pass
QD_JOURNAL=<journal copy>/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

python audit/probes/phase_e_repro_v2.py      <warehouse> 2026-10-01 <out.csv>   # → audit/data/phase_e_repro_v2.json
python audit/probes/phase_e_v2_post.py       <warehouse>                        # post-sample trades, NW lag check
python audit/probes/phase_e_l1_robust.py     <out.csv>                          # ACF, block bootstrap, by year
python audit/probes/phase_e_d1_official.py   <warehouse> <research branch>      # D1 on NSE official OHLC
python audit/probes/phase_e_eve_spreads.py   <chains-2026 assets>               # real expiry-eve half-spreads
python audit/probes/phase_e_frozen_minutes.py <journal>/intraday/data           # the 15:15 freeze, settlement gaps
python audit/probes/phase_e_stats_check.py                                      # BH / PSR / DSR / NW vs references
```

## Files created or changed in Phase E

**Created:**
- `audit/QUANTDESK_RESEARCH_VALIDITY.md`
- `audit/probes/test_phase_e_probes.py`
- `audit/probes/phase_e_*.py` (7 scripts)
- `audit/data/phase_e_*` (outputs)

**Changed:** `audit/QUANTDESK_FINDINGS_REGISTER.md` (E-01 … E-09, V-21 … V-26, Q-08 … Q-11, change log) and
`audit/QUANTDESK_FORENSIC_AUDIT.md` (Phase E section, tracker).

**No other file in the repository was touched.**
