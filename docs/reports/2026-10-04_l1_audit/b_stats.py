"""Audit step B: an independent statistical trace of the registered L1/L2 result (v2), from the rebuilt trades.
Nothing from quantdesk is used for the statistics; statsmodels is the cross-check."""
import json, math, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
HERE = Path(__file__).parent
sys.path.append(str(HERE.parent / "pylib"))                 # statsmodels, appended last: never shadows numpy/pandas
import statsmodels.api as sm

HELD = ["FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"]
REG = json.load(open("/home/user/quant-desk/docs/prereg/results/expiry_eve_law_v2-a3ff6d83a18e.json"))
tr = pd.read_csv(HERE / "expiry_eve_law_v2_trades.csv.gz", parse_dates=["entry", "expiry"])
tr = tr[tr.symbol.isin(HELD)].copy()
iso = tr.expiry.dt.isocalendar()
tr["wk"] = iso.year.astype(str) + "-" + iso.week.astype(str).str.zfill(2)

def nw(x, L):
    x = np.asarray(x, float); n = len(x); e = x - x.mean()
    s = e @ e / n
    for k in range(1, L + 1):
        s += 2 * (1 - k / (L + 1)) * (e[k:] @ e[:-k]) / n
    return x.mean(), math.sqrt(s / n)

def auto(n): return max(1, math.floor(4 * (n / 100) ** (2 / 9)))

def sboot(x, block, reps=10000, seed=7):
    x = np.asarray(x, float); n = len(x); rng = np.random.default_rng(seed)
    restart = rng.random((reps, n)) < 1 / block; restart[:, 0] = True
    starts = rng.integers(0, n, (reps, n)); pos = np.broadcast_to(np.arange(n), (reps, n))
    last = np.maximum.accumulate(np.where(restart, pos, 0), axis=1)
    return x[(np.take_along_axis(starts, last, 1) + pos - last) % n].mean(1)

out = {}
for key, strat in (("strangle", "short_strangle_20d"), ("insured", "iron_condor_20_05")):
    h = tr[tr.strategy == strat]
    w = h.groupby("wk")["bps"].mean().sort_index()
    n, L = len(w), auto(len(w))
    m, se = nw(w, L)
    res = sm.OLS(w.values, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": L, "use_correction": False})
    res_c = sm.OLS(w.values, np.ones(n)).fit(cov_type="HAC", cov_kwds={"maxlags": L, "use_correction": True})
    reg = REG["structures"][key]["pooled"]
    per_wk = h.groupby("wk").agg(trades=("bps", "size"), instruments=("symbol", "nunique"))
    dup = h.groupby(["wk", "symbol"]).size()
    tcrit = stats.t.ppf(0.975, n - 1)
    r = {"registered": reg,
         "independent": {"weeks": n, "lag": L, "mean": m, "se_nw": se, "t_nw": m / se,
                         "statsmodels_t": float(res.tvalues[0]), "statsmodels_t_small_sample": float(res_c.tvalues[0]),
                         "sd": float(w.std(ddof=1)), "se_iid": float(w.std(ddof=1) / math.sqrt(n)),
                         "ci95_nw": [m - tcrit * se, m + tcrit * se], "median": float(w.median()),
                         "hit_rate": float((w > 0).mean()), "worst": [w.idxmin(), float(w.min())],
                         "best": [w.idxmax(), float(w.max())], "skew": float(stats.skew(w)), "kurtosis": float(stats.kurtosis(w)),
                         "first": w.index[0], "last": w.index[-1]},
         "trades": int(len(h)), "trades_by_instrument": h.symbol.value_counts().to_dict(),
         "instruments_per_week": per_wk.instruments.value_counts().sort_index().to_dict(),
         "weeks_with_two_trades_of_one_instrument": int((dup > 1).sum()),
         "trade_level": {"mean": float(h.bps.mean()), "median": float(h.bps.median()), "sd": float(h.bps.std()),
                         "hit": float((h.bps > 0).mean()), "worst": float(h.bps.min())}}
    # aggregation alternatives
    alt = {}
    inst_eq = h.groupby(["wk", "symbol"])["bps"].mean().groupby("wk").mean()
    alt["instrument-equal within week"] = nw(inst_eq.sort_index(), auto(len(inst_eq)))
    wsum = h.groupby("wk")["bps"].agg(["sum", "size"]).sort_index()
    mu = wsum["sum"].sum() / wsum["size"].sum()                        # trade-weighted: weeks with more instruments count more
    z = (wsum["sum"] - mu * wsum["size"]).values
    def nwz(z, L):
        s = z @ z
        for k in range(1, L + 1): s += 2 * (1 - k / (L + 1)) * (z[k:] @ z[:-k])
        return math.sqrt(s) / wsum["size"].sum()
    alt["trade-weighted, week-clustered + NW"] = (mu, nwz(z, auto(len(z))))
    multi = per_wk[per_wk.instruments >= 2].index
    alt["only weeks with >= 2 instruments"] = nw(w[w.index.isin(multi)], auto(int(w.index.isin(multi).sum())))
    mon = h.groupby(h.expiry.dt.to_period("M"))["bps"].mean().sort_index()
    alt["calendar-month means"] = nw(mon, auto(len(mon)))
    inst_means = h.groupby("symbol")["bps"].mean()
    alt["each instrument equal (mean of instrument means; no SE)"] = (float(inst_means.mean()), float("nan"))
    for lo in (0.05, 0.10):
        k = int(round(lo * n)); s = w.sort_values()
        alt[f"trimmed {int(lo*100)}% each tail"] = nw(s.iloc[k:n - k].sort_index(), auto(n - 2 * k))
    for q in (0.01, 0.05):
        lo_, hi_ = w.quantile(q), w.quantile(1 - q)
        alt[f"winsorised {int(q*100)}%"] = nw(w.clip(lo_, hi_), L)
    alt["without 2021"] = nw(w[~w.index.str.startswith("2021")], auto(int((~w.index.str.startswith("2021")).sum())))
    r["alternatives"] = {k: {"mean": v[0], "se": v[1], "t": v[0] / v[1] if v[1] == v[1] and v[1] > 0 else None} for k, v in alt.items()}
    r["lags"] = {L_: nw(w, L_)[0] / nw(w, L_)[1] for L_ in (0, 2, 5, 10, 13, 20, 26, 52)}
    r["bootstrap_p5"] = {b: float(np.percentile(sboot(w.values, b), 5)) for b in (4, 8, 16, 26)}
    r["bootstrap_share_le0"] = {b: float((sboot(w.values, b) <= 0).mean()) for b in (4, 8, 16, 26)}
    r["wilcoxon_p_one_sided"] = float(stats.wilcoxon(w.values, alternative="greater").pvalue)
    r["sign_test_p_one_sided"] = float(stats.binomtest(int((w > 0).sum()), n, 0.5, alternative="greater").pvalue)
    out[key] = r
json.dump(out, open(HERE / "b_stats.json", "w"), indent=1, default=str)
for key, r in out.items():
    i, g = r["independent"], r["registered"]
    print(f"== {key}: registered weeks {g['weeks']} mean {g['mean_bps']:.4f} t {g['t']:.4f} | independent weeks {i['weeks']} "
          f"mean {i['mean']:.4f} t {i['t_nw']:.4f} | statsmodels t {i['statsmodels_t']:.4f} (small-sample corr {i['statsmodels_t_small_sample']:.4f})")
    print(f"   lag {i['lag']} sd {i['sd']:.2f} se_nw {i['se_nw']:.3f} se_iid {i['se_iid']:.3f} CI95 [{i['ci95_nw'][0]:.2f}, {i['ci95_nw'][1]:.2f}] "
          f"median {i['median']:.2f} hit {i['hit_rate']:.1%} worst {i['worst']} best {i['best']} skew {i['skew']:.2f} kurt {i['kurtosis']:.1f} span {i['first']}..{i['last']}")
    print(f"   trades {r['trades']} {r['trades_by_instrument']} | instruments/week {r['instruments_per_week']} | dup instr-weeks {r['weeks_with_two_trades_of_one_instrument']}")
    print(f"   trade-level: {r['trade_level']}")
    for k, v in r["alternatives"].items():
        print(f"   {k:55s} mean {v['mean']:+.2f}  t {v['t'] if v['t'] is None else round(v['t'], 2)}")
    print("   t by lag:", {k: round(v, 2) for k, v in r["lags"].items()})
    print("   bootstrap 5th pct by block:", {k: round(v, 2) for k, v in r["bootstrap_p5"].items()}, "share<=0", r["bootstrap_share_le0"])
    print(f"   Wilcoxon p {r['wilcoxon_p_one_sided']:.2e}  sign-test p {r['sign_test_p_one_sided']:.2e}")
