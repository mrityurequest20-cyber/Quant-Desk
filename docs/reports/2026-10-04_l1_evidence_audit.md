# L1 evidence audit (4 Oct 2026)

**Scope.** An investigation of law L1 (the expiry-eve short strangle) and L2 (its insured condor). It covers:
- the registered specifications;
- the code that executes them;
- the statistics;
- the holdout;
- the v1 → v2 correction;
- the post-Nov-2024 regime;
- the forward paper pipeline;
- the data defects and the provenance.

**Nothing registered was changed.** No specification, ledger, result, test threshold or risk limit was modified, and no test was re-run in a way that writes evidence. Every number below was recomputed in a scratch area, from:
- the code at commit `3cd4203`;
- the warehouse files with the digests below.

The reproduction scripts and their outputs are in [2026-10-04_l1_audit/](2026-10-04_l1_audit/).

**Inputs** (sha256 over the sorted file list and each file's hash):

| table | files | digest |
|---|---:|---|
| `fo_bhav_*.parquet` | 94 | `d3854e12bc920f10` |
| `bse_fo_bhav_*.parquet` | 34 | `c47fabf348401a54` |
| `nse_index_close_*.parquet` | 8 | `b6fb9e505fa6a77c` |

The audit's rebuilt trades:
- v1: `519b3b7e3679376a`;
- v2: `5c80c5f30f8d98aa`.

The independent statistics use their own Newey–West code, cross-checked with statsmodels 0.15.0, which shares no code with the desk.

**Labels:**
- **[V]** verified here, by inspection or by computation;
- **[A]** rests on outside knowledge (exchange rules, statutory rates) that the repository cannot verify;
- **[U]** could not be verified.

---

## 1. Executive verdict

**Verified**
- **The registered v2 result reproduces exactly** from raw data with independent code [V]: 288 weeks, +9.4754 bps, Newey–West t 4.9772.
  - statsmodels' HAC gives the same t; with its small-sample correction, 4.9685.
- **The holdout was clean in process** [V]:
  - the spec was written at 00:40:42Z and committed byte-identical at 01:59:18Z;
  - the study ran **once** on a runner, at 02:20:44Z;
  - the first held-out number was displayed at 02:22:18Z;
  - no earlier code or session output shows any held-out instrument's performance.
- **L1 stays positive under every reasonable aggregation and dependence treatment tried** [V]. The weakest:
  - weeks with ≥ 2 instruments: +6.58 bps, t 2.96;
  - Newey–West at 52 lags: t 3.66;
  - the block-bootstrap 5th percentile is ≥ +5.66 bps for blocks of 4–26 weeks.
- **The v1 → v2 correction did what its spec says** [V]:
  - 788 trades changed, all before 8 Jul 2024, on NSE instruments only;
  - every NSE v2 trade enters and settles on NSE's official close (0 exceptions).

**Weaker than claimed, or not verified**
1. **Historical fills are bhavcopy closing prices, not executable quotes** [V]. In the UDiFF era the close equals the last trade on only 26.8% of traded NSE option rows (BSE 29.0%). This is the largest approximation in the study, and it is not quantified historically. A one-day estimate is in §6.
2. **"Five held-out instruments" is effectively two** [V]:
   - FINNIFTY carries 51% of the pooled mean's weight, SENSEX 30%;
   - 184 of the 288 weeks contain a single instrument.
3. **L2 is not robust** [V]:
   - weeks with ≥ 2 instruments: t 1.58;
   - without FINNIFTY: t 1.84;
   - after 20 Nov 2024: t 0.84.
4. **L1's "weak current regime" is mostly a composition effect, not decay** [V]:
   - within instruments there is no decline (instrument fixed effects: +3.43 bps, t 0.89);
   - the pre/post difference is not significant (p 0.13);
   - the post-change evidence is **inconclusive**, not negative.
5. **The forward sleeves settle differently from the history** [V]:
   - the registered sleeve settlement (the mean of 15:00–15:29 one-minute closes) misses NSE's official close by 10.5–11.3 bps on average, and up to 35 bps, on 19 recorded days;
   - the history (v2) settles on the official close.
6. **v2 was computed locally** [V]. Its `nse_index_close` input was backfilled on this machine and is still being published to the shared release (Data run 37189406730, in progress). It has not yet been reproduced on a runner.

**Readiness.** L1 is fit to **continue paper validation** (not live trading). Nothing found invalidates the historical result. But paper P&L alone cannot confirm the edge in useful time: about 300 weeks are needed to detect +4.9 bps a week with 80% power. The forward work should first test the two unverified links, the entry price and the settlement. Both are low-variance and resolvable in weeks (§10).

**Corrections to claims made earlier in this project's chat** [V]:
- *"v2 is the same trades re-settled"*: wrong.
  - 74 FINNIFTY and 25 MIDCPNIFTY trades chose different strikes, because the index level feeds the delta calculation;
  - 7 trades are new and 2 dropped;
  - of the +0.60 bps uplift, +0.38 comes from re-settled common trades.
- *"Settlement uses the 15:00–15:29 mean, the same way NSE builds the close"*: wrong. It differs from the official close by about 10 bps (§6).
- *"Weak since Nov 2024" recorded as an L1 caveat*: mis-attributed (§5).

## 2. Strategy implementation: registered rules vs actual code

Spec: [`docs/prereg/expiry_eve_law_v2.json`](../prereg/expiry_eve_law_v2.json) (hash `a3ff6d83a18e`).

The code path:
- `laws.run` (quantdesk/research/laws.py:158);
- then `all_trades` (:135) and `trades` (:61);
- then `warehouse_research.build_trades` (quantdesk/research/warehouse_research.py:97–205).

| # | Rule | What the code does | Status |
|---|---|---|---|
| 1 | Final session before expiry | `settle` = the last calendar day ≤ the nominal expiry (wr.py:115); entry = the trading day before it (`k = 1`, :118–121). For a holiday-shifted expiry this is the actual expiry day. Trades the nearest expiry only (:120). Skips the first 10 days of each series (:120, an rv10 warm-up the strangle doesn't use). | [V] matches |
| 2 | ~20-delta OTM call and put | Black–Scholes IV and delta are recomputed from each strike's **closing price** with the closing index level, r = 6.5%, q = 1.2%, and calendar-day T = days/365 (wr.py:35, :67–68, :136–139). For each side the code takes the OTM strike with \|Δ\| nearest 0.20; the trade is dropped if it is off by more than 0.08 (:161–168). Only strikes with close > 0 **and** contracts > 0 that day qualify (:125). | [V] |
| 3 | Hold to settlement | Settles at the index level on `settle` (wr.py:129); payout = intrinsic (:178). | [V] |
| 4 | Costs | Each leg: 0.05 + max(0.05, 0.2% × close) (wr.py:56–59, :179–180). Statutory fees from `CostModel.fees` (execution/costs.py:26–42) at **2026 rates for every year and both exchanges**: STT on sell 0.15%, exchange 0.03503%, SEBI ₹10/cr, stamp 0.003%, GST 18%, brokerage ₹20 per order (config/quantdesk.yaml:49–59). 0.125% STT on exercised long legs (wr.py:37, :188–189). | [V] code; [A] rates |
| 5 | Lot sizes | One median lot per instrument over rows that carry a lot (laws.py:54–58). The UDiFF era only, since old NSE files have no lot. Affects only per-unit fixed fees. | [V] |
| 6 | Units | bps = P&L points ÷ entry index level × 10⁴ (laws.py:73–74). | [V] |
| 7 | Index level (v2) | NSE official close → bhavcopy underlying → nearest future (laws.py:38–51); official closes from `nse_index_close` (laws.py:146–155). BSE levels come from the file's underlying. SENSEX matches Yahoo's ^BSESN on all 142 entry and settlement days (0.00 bps) [V]; BANKEX was not cross-checked [U]. | [V] |

**Answers to the six questions**

1. **How is 20-delta chosen?** It is calculated retrospectively from end-of-day closing prices: not observed, and not a strike-distance proxy [V].
   - On the 1,098 selected held-out legs, median \|Δ\| is 0.199 (5–95%: 0.163–0.232); 71.9% are within ±0.02 and 3.4% are off by more than 0.05 [V].
   - NIFTYNXT50 is the loosest: 13.5% are off by more than 0.05.
   - The median OTM distance is 0.84% (calls) and −0.82% (puts).
2. **Missing contracts, quotes, liquidity, holidays, re-datings, spec changes** [V]:
   - **untraded strikes are excluded:** history has no quotes;
   - **a side with no strike within 0.08 drops the trade.** Genuine skips: FINNIFTY 11, MIDCPNIFTY 17, NIFTYNXT50 3. MIDCPNIFTY also lost 54 eves in Jan 2022 – mid 2023 that had no traded contracts at all;
   - **holiday-shifted expiries** settle on the true last day;
   - **re-dated contracts** (expiry weekday moves) appear as phantom expiries and are skipped (37). None blocked a real trade: every non-traded expiry was classified, and none had a valid chain;
   - **lot changes** don't affect per-unit P&L.
3. **Was the information available at entry?** Mostly, not exactly [V]:
   - strike selection uses the same closing prices it trades at, and the official index close, which NSE computes from the last 30 minutes **[A]** and publishes after the close;
   - the `contracts > 0` filter uses full-day volume;
   - an executable version would decide at ~15:20 from live quotes, which the forward sleeves do (§6).
   - Severity **Medium**: the bias direction is not known.
4. **Are costs consistent across years and exchanges?** Consistent in form, but at today's rates throughout [V code; A rates]:
   - STT on option sales was 0.0625% before Oct 2024 [A], so pre-2024 costs are overstated;
   - NSE exchange charges were higher before Oct 2024 [A];
   - one rate is applied to BSE too.
   - Total modelled cost is 0.41–0.52 bps a trade against a mean of 9.5. Break-even is **13×** (post-Nov-2024) to **18×** the modelled costs for L1, but only **4.1×** (post) to **6.2×** (v1 full sample) for L2.
   - Under the desk's own live slippage model (1.2% half-spread, ₹0.10 floor), L1 is +9.29 bps (t 4.88). Severity **Low** for L1, **Medium** for L2.
5. **Future information?** No future index closes, no settlement leaks and no retrospectively corrected data were found [V]:
   - v2's levels are the same day's official close;
   - the only same-day hindsight is in (3).
   - The `nse_index_close` file is NSE's original publication, fetched once [V]. Whether NSE ever revises it: [U].
6. **Executable prices?** No [V]. Material approximations, by severity:
   - **(High)** the entry at the bhavcopy close: a computed close, not a trade or quote (26.8% equal the last trade); last-trade times are unknown, so stale closes on thin strikes are possible;
   - **(Medium)** liquidity: 59.6% of NIFTYNXT50 legs traded under 100 contracts that day (0–5% elsewhere). Results on strikes with ≥ 100 contracts stay strong (+8.13 bps, t 4.18, v1 audit);
   - **(Medium)** the weekend carry: "one session before" is 3–4 calendar days for 24% of legs;
   - **(Low)** today's statutory rates for all years;
   - **(Low)** no market impact; 1 lot.

## 3. Statistical audit

**Exact definitions** [V] (laws.py:91–98, edges.py:62–78):
- **Observational unit:** the **ISO year-week of the expiry date**. Weeks with no held-out trade don't exist in the series; they are not zeros.
- **Within a week:** the plain mean of trade P&L (bps) across the held-out trades that week. That is equal weight per *trade*; 9 instrument-weeks hold 2 trades of one instrument.
- **Across weeks:** equal weight. A FINNIFTY-only week counts as much as a five-instrument week. A week with more instruments therefore gets *no more* influence, so each trade in a crowded week gets less.
- **Newey–West:** mean m = x̄. γ_k = (1/n) Σ e_t e_{t−k}. Bartlett weights 1 − k/(L+1). σ² = γ₀ + 2 Σ w_k γ_k. se = √(σ²/n).
  - L = ⌊4 (n/100)^{2/9}⌋ = 5 for n = 288.
  - No finite-sample correction (÷n). The p-value uses t with n−1 df.
  - The registered replication rule is the one-sided t > 1.645 (laws.py:112).
- **Weighting:** P&L is per unit of index, in bps. There is no capital or lot weighting.
- **Dependence:**
  - instruments that share a week are averaged into one observation;
  - serial dependence across weeks: Newey–West;
  - there are no overlapping positions (each trade lives one session or one weekend);
  - common shocks *across* weeks (vol regimes) are only partly covered by L = 5. See the lag and bootstrap sensitivity.

**Reproduced results, v2** [V] (`2026-10-04_l1_audit/b_stats.json`):

| | L1 strangle | L2 insured |
|---|---:|---:|
| weeks / trades | 288 / 549 | 288 / 549 |
| mean (bps a week) | **+9.48** | **+5.48** |
| sd / NW se / iid se | 33.40 / 1.904 / 1.968 | 27.34 / 1.508 / 1.611 |
| NW t (registered; statsmodels) | 4.98; 4.98 (4.97 corrected) | 3.63; 3.63 (3.63) |
| 95% CI (NW, t₂₈₇) | [+5.73, +13.22] | [+2.51, +8.45] |
| median / hit rate | +17.56 / 79.9% | +12.94 / 76.0% |
| worst / best week | −223.8 (2022-W35) / +84.3 | −137.4 (2022-W07) / +71.2 |
| skew / excess kurtosis | −3.26 / 15.1 | −2.46 / 7.3 |
| trade-level mean / median / worst | +7.77 / +19.26 / −417.1 | +3.95 / +14.47 / −337.0 |

Trades by instrument: FINNIFTY 214, SENSEX 142, MIDCPNIFTY 100, BANKEX 67, NIFTYNXT50 26.
- Instruments per week: one in 184 weeks, two in 39, three in 2, four in 43, five in 20.
- Weight in the pooled mean: FINNIFTY 51.3%, SENSEX 30.3%, MIDCPNIFTY 10.6%, BANKEX 5.8%, NIFTYNXT50 2.0%.

**Sensitivity** [V] (mean bps, t):

| alternative | L1 | L2 |
|---|---|---|
| registered | +9.48, 4.98 | +5.48, 3.63 |
| instruments equal within a week | +9.52, 5.01 | +5.52, 3.67 |
| trade-weighted (week-clustered NW) | +7.77, 4.26 | +3.95, 2.59 |
| only weeks with ≥ 2 instruments | +6.58, 2.96 | +2.97, **1.58** |
| calendar-month means | +10.64, 5.41 | +6.38, 4.08 |
| each instrument's mean, equally weighted | +7.88, – | +3.90, – |
| without 2021 | +7.35, 3.95 | +3.90, 2.62 |
| NW lags 0 / 10 / 26 / 52 | t 4.82 / 4.54 / 4.07 / 3.66 | t 3.41 / 3.30 / 2.91 / 2.59 |
| stationary bootstrap 5th pct, blocks 4 / 8 / 16 / 26 weeks | +6.17 / +5.97 / +5.80 / +5.66 | +2.86 / +2.67 / +2.37 / +2.21 |

- **Trimmed and winsorised means** *raise* both means (e.g. trimming 5% from each tail: +13.64), because the P&L is negatively skewed. They are not valid measures for a short-volatility payoff and are shown in the JSON only to flag that.
- **Sign and Wilcoxon tests** ignore dependence and are not decisive.
- **Missing weeks:** 11 of the 299 calendar weeks spanned have no held-out trade. They are left out rather than counted as zero, so Newey–West treats the weeks on either side of a gap as adjacent.
- **Excluded expiries:** genuinely skipped expiries (n = 90) had index moves similar to traded ones (median 0.56% vs 0.51%). No selection bias is evident, but it can't be ruled out for the 54 untraded MIDCPNIFTY eves [V].

**The v1 → v2 correction** [V] (`d_diff.py`):

| strangle trades | identical | different strikes | same strikes, level changed | only v1 | only v2 |
|---|---:|---:|---:|---:|---:|
| FINNIFTY | 43 | 74 | 95 | 0 | 2 |
| MIDCPNIFTY | 42 | 25 | 31 | 1 | 2 |
| NIFTYNXT50 | 24 | 0 | 2 | 0 | 0 |
| SENSEX, BANKEX | 142, 67 | 0 | 0 | 0 | 0 |
| NIFTY, BANKNIFTY (discovery) | 117, 41 | 107, 162 | 169, 123 | 1, 0 | 5, 0 |

- **Affected dates:** expiries from 2019-01-17 to 2024-07-04, plus one trade expiring 2024-07-08 that was entered on the last old-format day. Nothing after the UDiFF switch.
- **v1's index levels against the official close:** at settlement, +0.141% on average (sd 0.211, range −0.73% to +0.88%); at entry, +0.168% (worst −2.02%).
- **The uplift:**
  - on common trades, +8.88 → +9.27 bps;
  - in total, +8.87 → +9.48;
  - the rest comes from 7 added trades (all positive) and 2 dropped.
- **No unrelated rule changed:** the code differs only in `spot()` precedence (laws.py:38–51).
- **Records preserved:** v1's spec, result and audit are unchanged in git [V].
- **Reproducible from source:** yes, exactly [V]. On a runner: not yet (§1, item 6).

## 4. Holdout integrity

**Timeline** [V] (git, and this session's transcript as the access log; the repository keeps no separate data-access logs):

| time (UTC, 4 Oct) | event |
|---|---|
| before 00:40 | No research code references FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX or BANKEX (`git grep` at `c545eef^`). Transcript mentions are data descriptions, parsers, planning notes and synthetic unit-test values; no performance figure. |
| 00:40:42 | Spec `expiry_eve_law_v1.json` written once (no later edits) |
| 01:59:18 | Data, spec and code committed (`0e3676c`, `c545eef`, `eb6dee6`; one author timestamp) |
| 02:20:44 | Study run 37170766466: the only `laws` run ever on a runner (Study has 2 runs in total; the other is `wings`) |
| 02:22:18 | First held-out number displayed |

**Answers**
1. **Untouched in development?** Yes, as far as the record shows [V]:
   - hypothesis, delta, offset, costs, aggregation and tests were all fixed on NIFTY/BANKNIFTY work, or in the spec, before the run;
   - limitation: the researcher's general prior knowledge (option sellers earn a premium in Indian index options) applies to every instrument [A]. That isn't data contamination, but the held-out test is not prior-free.
2. **Results viewed before freezing?** None were found [V].
3. **Registered before evaluation?** Yes: entry day, delta, cost model, weekly aggregation, the test, the replication rule and exclusions (only traded strikes, within 0.08) [V].
   - **Not** pre-specified: the `lot_of` median and the 10-day warm-up. These are code behaviour inherited from `build_trades`, fixed before the run.
4. **Variants before L1:** at least 48 cells on NIFTY/BANKNIFTY [V]:
   - 8 structures × 3 entry offsets × 2 indices (commit `64db924`), plus ±10% perturbations;
   - then the `expiry_wings_v1` variants.
   - The held-out test itself was one run of two structures.
5. **Selection effects:**
   - discovery multiplicity inflates the *discovery* estimates, not the held-out test;
   - the held-out instruments are every other index option market in the warehouse, not a favourable subset (BANKEX, which is weak, is included);
   - BSE starts in 2024 because the BSE archive does (quantdesk/data/bse.py, `BSE_FROM`);
   - post-hoc analyses (the v1 audit, v2, this report) were done *after* seeing v1. Their choices are exposed to hindsight, even though registered before running. The audit's current-regime check was registered after v1 showed a weaker last third.
6. **Classification of the evidence:**

| evidence | class |
|---|---|
| NIFTY, BANKNIFTY (VRP research, expiry_wings_v1) | exploratory discovery, with multiplicity |
| expiry_eve_law_v1 held-out (5 instruments) | **independent replication**: clean holdout, run once |
| expiry_eve_law_v2 | a **correction** of the same replication: same data, not new evidence |
| v1 audit, this report's sensitivities | robustness analysis, partly post hoc |
| expiry_seller_v1–v3 forward sleeves | prospective; **no settled trades yet** |

## 5. Current-regime assessment

**The rule change, from the data** [V]. The last weekly expiries:
- BANKNIFTY 2024-11-13;
- FINNIFTY 2024-11-19;
- MIDCPNIFTY and BANKEX 2024-11-18.

From 20 Nov 2024 those instruments have monthlies only, while NIFTY and SENSEX kept weeklies. The split date (registered in `expiry_eve_law_v1_audit.json`, matching SEBI's effective date [A]) fits the actual change.

| L1 held-out pooled | weeks / trades | span | mean | t | 95% CI |
|---|---|---|---:|---:|---|
| pre | 191 / 362 | 2021-01-14 → 2024-11-19 | +11.16 | 4.91 | [+6.70, +15.62] |
| post | 98 / 187 | 2024-11-22 → 2026-10-01 | **+4.92** | **1.42** | [−1.89, +11.74] |
| pre − post | | | +6.23 (se 4.16) | z 1.50, p 0.13 | |

- **Figures check** [V]:
  - +4.92 / t 1.42 is confirmed;
  - 2024 is +2.02 under v2 (the earlier "+1.5" was v1's +1.51);
  - by year: 2021 +22.7, 2022 +11.4, 2023 +9.8, 2024 +2.0, 2025 +7.4, 2026 +6.2.
- **Composition** [V]:
  - post-change weeks are 69% SENSEX-only (68 of 98);
  - pre-change weeks were dominated by FINNIFTY;
  - SENSEX is the weakest instrument in both periods.
- **Within instrument, no decline** [V] (post − pre, bps): NIFTY +3.4, FINNIFTY +2.9, MIDCPNIFTY +8.3, SENSEX +1.7, BANKNIFTY −0.8, BANKEX −2.3.
  - The fixed-effects shift is **+3.43 bps, t 0.89**.
  - NIFTY (discovery) post-change: +7.82, t 2.62.
- **Costs, post-change** [V]: costs ×2 +4.52, ×3 +4.12, ×5 +3.32; break-even 13.3×; desk cost model +4.72. Costs don't decide it.
- **L2** [V]:
  - leave-one-out over the full sample: −FINNIFTY +3.17 (t 1.84); the others t 3.19–4.02;
  - post-change: every leave-one-out t < 1.6;
  - break-even 4.1× costs post-change.
- **Is the sample enough?** No [V]:
  - post-change weekly sd is 38.3 bps;
  - detecting +4.92 one-sided at 80% power needs about **303 weeks**; detecting +9.48 needs about 82.

**What's supported:**
- L1 earned a positive premium in history across instruments; the evidence is strong and robust to dependence and aggregation;
- no measurable within-instrument change after Nov 2024.

**What's uncertain:**
- the size of the edge today (CI −1.9 to +11.7 bps);
- L2 in any form;
- anything resting on SENSEX alone.

**What would change the assessment:**
- forward entry credits materially below the history's convention (§10);
- a within-instrument decline that becomes significant as post-change data accumulates;
- results on stock options (BACKLOG 1), which would give many more independent markets.

## 6. Paper-trading readiness

Implementation: `quantdesk/intraday/sleeves.py`. The specs are `expiry_seller_v1.json`, `v2.json` and `v3.json`.

1. **Timestamps and records** [V]:
   - snapshot `ts` is the fetch time in IST (kotak.py `chain`);
   - each attempt's fetch latency and errors are in `tape.csv`;
   - events carry `recorded_at` (IST) and the spec hash (sleeves.py:231–236);
   - there is no exchange timestamp per quote [U];
   - partial fills are not modelled: a full 1-lot fill at the touch ± 1 tick, with a `thin` flag when the touch is smaller than the order;
   - skips are appended with a reason (sleeves.py:334, :367, :373), including eves the job never ran (`missed`, :320).
2. **Can hard trades drop out of performance?** Yes [V]. `assess()` (sleeves.py:173) uses settled trades only; skips are reported beside them, not in P&L. If skips cluster on stressed days (no two-sided quote), the forward P&L is optimistic.
3. **Are bid/ask assumptions plausible for 1 lot?** For NIFTY/BANKNIFTY/SENSEX near-expiry OTM strikes, yes [V]:
   - on 29 Sep the real NIFTY half-spread was 0.07 points, and the fill model costs 0.12;
   - NIFTYNXT50 wings: doubtful, since 60% of historical legs were thin.
4. **Settlement** [V]:
   - the registered rule is the mean of 15:00–15:29 one-minute index closes (`settlement_price`, sleeves.py:139; specs' `exit`);
   - against NSE's official close on 19 recorded days: mean absolute error 10.5 bps (NIFTY), 11.3 bps (BANKNIFTY), max 35 bps;
   - the last minute-bar's close equalled the official close on every day;
   - **the registered method is not equivalent to the official settlement** [V]. NSE builds the index close from constituents' last-30-minute prices, not from a time average of index values [A].
5. **Preservation** [V]:
   - the ledger is append-only JSONL on the `journal` git branch (deploy/journal.sh);
   - snapshots (now with touch sizes) are archived to the `chains-YYYY` releases;
   - every decision, fill, fee, STT amount and settlement source is recorded;
   - official settlement values are not recorded with the trade.
6. **Minimum before any conclusion:**
   - *execution realism*: ≥ 40 eves across ≥ 3 instruments over ≥ 12 weeks; skip rate ≤ 10% with every reason logged; flagged legs ≤ 10%;
   - *P&L*: the registered sleeve rules (cost check from 6 trades, consistency from 8) can **reject** the history, but cannot **confirm** an edge inside a year.
7. **Comparing without moving the goalposts:**
   - compare each instrument and expiry type against its own historical distribution (weekly vs monthly);
   - use one settlement definition on both sides (record both);
   - report costs separately;
   - never change rules mid-test: a different rule is a new spec with a new forward clock.

**Indicative entry-price check** [V, one day only]:
- 29 Sep 2026 used the NSE public chain, at 7 and 28 days to expiry, not an eve;
- selling at the 15:20 bid − 0.05 versus the history's close − cost: NIFTY −0.30 bps per leg (sd 2.82, n 23), BANKNIFTY −0.15 (sd 1.80, n 28);
- small against a ~9.5 bps edge, but measured on one day.

## 7. Data defects

| defect | affects L1? | other impact | severity | action |
|---|---|---|---|---|
| Monthly future used as the index on weekly expiries before Jul 2024 (v1) | yes (fixed in v2) | any study using `laws.spot` without official closes | high (resolved) | keep v1 preserved; re-run v2 on a runner once the release has `nse_index_close` |
| Bhavcopy close ≠ an executable price (26.8% equal the last trade) | yes, entry prices | every bhavcopy-priced study | high | the paired prospective test (§10) |
| NSE 2021-03-30 missing | **no**: not an entry or settlement day for any trade [V] | rv10-based filters (not L1) | low | refetch run 37189408232 queued |
| 22 BSE traded closes outside their own high–low, all on 1–2 Jan 2024 (21 SENSEX, 1 BANKEX) | **no**: no L1/L2 leg uses them [V] | any study starting at BSE's first two days | low | flag in the warehouse audit; exclude those two days in new specs |
| BSE expiring-option prices hold the index value | **no**: L1 settles on the index; SENSEX levels match Yahoo on 142/142 days [V] | blanked by the parser, by design | none | none |
| Contract re-datings (FINNIFTY Oct 2021; MIDCPNIFTY 2023; NIFTY/BANKNIFTY Sep 2025) | **no**: phantom expiries skipped; none blocked a real trade [V] | inflated "skip rates" in reports | low | report phantoms separately (done in the warehouse audit) |
| Old NSE files: no lot, expiring settle = 0 in 2019–20 | **no** [V] | fee per unit uses the median lot | low | dated lots in new specs |
| Results carry no data digest or code commit | provenance | all results | **medium** | record both in new results |
| Fingerprint changes when prose is reworded; it holds no code or data hash | the duplicate guard can be evaded [V] | experiment memory | **medium** | fingerprint the executed configuration + code commit |

**How the ledger separates evidence** [V]:
- principles move along *hypothesis → found → replicated → forward → proven* (`docs/principles.json`), with reasons in each principle's `history`;
- evidence rows carry a free-text `class`;
- specs carry no machine-readable type, so discovery / replication / prospective is inferred from prose;
- `test_every_recorded_result_matches_its_spec_as_registered` proves no spec changed after its result. It does not hash the result files themselves; git history is the integrity record.

## 8. Evidence table

| claim | status | evidence | confidence |
|---|---|---|---|
| v2: 288 weeks, +9.48 bps, t 4.98 | **verified** | b_stats.json; results/expiry_eve_law_v2-a3ff6d83a18e.json | high |
| v2 reproducible from source | verified locally; runner: **not yet** | a_trades.py; Data run 37189406730 | medium |
| Holdout clean (spec frozen before results; one run) | **verified** | git `c545eef`; transcript times; Study runs | high |
| L1 positive across aggregations and dependence treatments | **verified** | b_stats.json | high |
| "Five independent held-out instruments" | **overstated**: effectively FINNIFTY + SENSEX (82% of weight) | b_stats.py | high |
| L2 replicates robustly | **not supported** under sensitivity | b_stats.json, e_regime.json | high |
| L1 weaker since Nov 2024 | **not established**: composition; within-instrument +3.4, t 0.89 | e_regime.py | medium |
| History's entry prices are executable | **not verified**; the close is not a trade price on 73% of rows | c_impl.py | high (that it's unverified) |
| Costs don't explain the edge (L1) | verified (break-even 13–18×; desk model +9.29) | e_regime.json | high for modelled costs; [A] for real |
| Forward settlement equals the official close | **false**: ~10 bps MAE | §6 calculation | high |
| v2's NSE levels = the official close | **verified** (0 exceptions) | d_diff.py | high |
| BSE levels correct | SENSEX verified against Yahoo (142/142); BANKEX [U] | §7 | high (SENSEX) |
| Statutory rates per year | **assumption** | config/quantdesk.yaml | – |

## 9. Prioritized actions (smallest reversible fixes; no registered rule changes)

**Critical**
1. **Record NSE's official close next to the registered sleeve settlement** in every settle event. Report the forward P&L both ways and keep the registered one primary. It's a diagnostic field: no rule change, removable. Switching the primary settlement would need a new sleeve spec.

**High**
2. Re-run v2 on a runner once `nse_index_close` is on the release, and record the data digest with the run. Until then, cite v2 as "locally reproduced".
3. Correct the ledger's L1/L2 caveats with a `review` history entry citing this report (no status change; L2 passed its registered test).
   - replace L1's "weak current regime" caveat with: "post-Nov-2024 pooled +4.92 (t 1.42) is a composition effect: within-instrument shift +3.43 (t 0.89)";
   - add "effective held-out evidence ≈ FINNIFTY (51%) + SENSEX (30%)";
   - add to L2: "not robust: t 1.58 on multi-instrument weeks; t 1.84 without FINNIFTY; t 0.84 post-Nov-2024".
4. Put skips in front of the forward results: the skip rate and reasons in every sleeve report. Add a labelled *modelled* settlement of skipped eves from the bhavcopy, to bound skip bias.

**Medium**

5. New results record the data digest and the code commit.
6. The experiment fingerprint should cover the executed configuration and the code commit, not the spec's prose.
7. A dated statutory-rate table for *new* studies.
8. Register the same ten-check audit on v2. It is already the engineer's top proposal.

**Low**

9. Finish the 2021-03-30 refetch (queued).
10. Exclude BSE 1–2 Jan 2024 in new specs.
11. Report phantom expiries separately from skips.
12. Use dated lots for fees.

## 10. Next experiment (pre-register before any forward trade is examined)

**`expiry_eve_entry_v1`: is the history's entry price executable?** A prospective, paired test.

- **Why this one.** The history already holds 288 weeks of the slow, heavy-tailed part (the payout distribution). The links nobody has verified are the **entry price** and the **settlement**. Both can be measured as low-variance *paired* differences on the same strikes on the same day, so they resolve in weeks. A P&L-only forward test would need about 300 weeks.
- **Population.** Every eve from the registration date on every taped instrument (NIFTY, SENSEX weeklies; BANKNIFTY, FINNIFTY, MIDCPNIFTY monthlies), with the registered strike rule applied to the Kotak snapshot nearest 15:20.
- **Per eve, record:**
  - (a) the executable credit: bid − 0.05 per leg, in bps of the 15:20 index;
  - (b) the history-convention credit for the *same strikes*: that day's bhavcopy close − (0.05 + max(0.05, 0.2%)), in bps;
  - (c) the payout at NSE's official close, and at the registered 15:00–15:29 mean.
- **Primary endpoint.** The mean paired shortfall D = (b) − (a). One-sided test of D > 2 bps (about 20% of the historical edge), Newey–West by week.
- **Sample size.**
  - The planning sd is 4 bps per strangle. This is an assumption from the one-day leg estimate (2–3 bps per leg); re-estimate after 10 eves by a pre-stated rule that can only *increase* n.
  - That gives n = 25 trades for 80% power; **register n = 40 eves, at least 12 weeks**.
- **Decision rules (fixed).**
  - D significantly > 2 bps: the historical edge is overstated by an entry-price artifact. Recompute L1 with D subtracted, and register v3 of the law.
  - D within ±2 bps: the history's entry convention is validated; L1 continues to the sleeves' registered consistency tests.
  - Secondary: the settlement gap (c), reported, not tested.
- **Out of scope.** Live trading, any change to the sleeves' registered rules, and promotion of any strategy.
