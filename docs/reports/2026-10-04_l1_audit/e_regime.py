"""Audit step E: the regime question, from the data. Read-only."""
import math, json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
HERE = Path(__file__).parent
W = Path("/home/user/quant-desk/runtime/warehouse")
HELD = ["FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"]
def nw(x, L=None):
    x = np.asarray(x, float); n = len(x)
    if n < 3: return (float(x.mean()) if n else float("nan")), float("nan")
    L = L if L is not None else max(1, math.floor(4 * (n / 100) ** (2 / 9)))
    e = x - x.mean(); s = e @ e / n
    for k in range(1, min(L, n - 1) + 1): s += 2 * (1 - k / (L + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean()), math.sqrt(s / n)
def wk(df):
    iso = pd.to_datetime(df.expiry).dt.isocalendar()
    return df.assign(wk=iso.year.astype(str) + "-" + iso.week.astype(str).str.zfill(2))

# 1. when did each instrument's weekly expiries actually stop / change weekday? (from the contracts traded)
for tbl in ("fo_bhav", "bse_fo_bhav"):
    df = pd.concat([pd.read_parquet(p, columns=["date", "symbol", "kind", "expiry", "contracts"]) for p in sorted(W.glob(f"{tbl}_*.parquet"))])
    df = df[df.kind.isin(["CE", "PE"]) & (df.contracts > 0) & (df.date == df.expiry)]          # expiries that actually expired, traded
    for sym, g in df.groupby("symbol"):
        e = pd.Series(sorted(g.expiry.unique()))
        gap = e.diff().dt.days
        weekly = e[(gap <= 8)]
        last_weekly = weekly.max() if len(weekly) else None
        after = e[e > last_weekly] if last_weekly is not None else e
        wd = e.dt.day_name()
        changes = [(str(e[i].date()), wd[i - 1], wd[i]) for i in range(1, len(e)) if wd[i] != wd[i - 1] and gap[i] <= 8]
        print(f"{sym:11s} expiries {len(e):3d} {e.min().date()}..{e.max().date()} | last weekly expiry: "
              f"{last_weekly.date() if last_weekly is not None else '-'} | weekday changes (weekly): {changes[:6]}")

tr = wk(pd.read_csv(HERE / "expiry_eve_law_v2_trades.csv.gz"))
tr = tr[tr.symbol.isin(HELD)]
SPLIT = "2024-11-20"
res = {}
for key, strat in (("L1 strangle", "short_strangle_20d"), ("L2 insured", "iron_condor_20_05")):
    h = tr[tr.strategy == strat]
    out = {}
    for name, part in (("pre", h[h.expiry < SPLIT]), ("post", h[h.expiry >= SPLIT])):
        w = part.groupby("wk").bps.mean().sort_index()
        m, se = nw(w)
        out[name] = {"weeks": len(w), "trades": len(part), "from": part.expiry.min(), "to": part.expiry.max(), "mean": m, "se": se,
                     "t": m / se, "ci95": [m - 1.96 * se, m + 1.96 * se], "sd": float(w.std()),
                     "by_instrument_trades": part.symbol.value_counts().to_dict(),
                     "instruments_per_week": part.groupby("wk").symbol.nunique().value_counts().sort_index().to_dict(),
                     "by_instrument_mean_bps": part.groupby("symbol").bps.mean().round(2).to_dict()}
        out[name]["w"] = w
    d = out["pre"]["mean"] - out["post"]["mean"]; sed = math.hypot(out["pre"]["se"], out["post"]["se"])
    out["diff"] = {"pre_minus_post": d, "se": sed, "z": d / sed, "p_two_sided": 2 * stats.norm.sf(abs(d / sed))}
    # power: weeks needed for a one-sided 5% test with 80% power, using post-regime sd and HAC inflation
    for name in ("post", "pre"):
        o = out[name]; infl = (o["se"] / (o["sd"] / math.sqrt(o["weeks"]))) ** 2
        o["hac_inflation"] = infl
        for target in (o["mean"], 4.0, 9.48 if key.startswith("L1") else 5.48):
            o.setdefault("weeks_needed", {})[round(target, 2)] = math.ceil(((1.645 + 0.8416) * o["sd"] / target) ** 2 * infl) if target > 0 else None
    # by calendar year
    yr = {}
    for y, g in h.groupby(pd.to_datetime(h.expiry).dt.year):
        w = g.groupby("wk").bps.mean(); m, se = nw(w); yr[int(y)] = (len(w), round(m, 2), round(m / se, 2) if se == se else None)
    out["years"] = yr
    # costs in the post regime: x2, x3, x5, break-even
    p = h[h.expiry >= SPLIT]
    cst = {}
    for mult in (1, 2, 3, 5):
        w = p.assign(a=p.bps - (mult - 1) * p.cost_bps).groupby("wk").a.mean().sort_index(); m, se = nw(w)
        cst[mult] = (round(m, 2), round(m / se, 2))
    wc = p.groupby("wk").cost_bps.mean()
    cst["break_even_multiple"] = round(1 + out["post"]["w"].mean() / wc.mean(), 1)
    cst["cost_bps_mean"] = round(float(p.cost_bps.mean()), 3); cst["credit_bps_mean"] = round(float(p.credit_bps.mean()), 2)
    out["post_costs"] = cst
    # leave one out, whole sample and post regime
    loo = {}
    for nm, part in (("all", h), ("post", p)):
        for s in HELD:
            w = part[part.symbol != s].groupby("wk").bps.mean().sort_index(); m, se = nw(w)
            loo.setdefault(nm, {})[f"-{s}"] = (len(w), round(m, 2), round(m / se, 2) if se == se else None)
        w = part[part.symbol == "FINNIFTY"].groupby("wk").bps.mean().sort_index(); m, se = nw(w)
        loo[nm]["FINNIFTY alone"] = (len(w), round(m, 2), round(m / se, 2) if se == se else None)
    out["loo"] = loo
    for nm in ("pre", "post"): out[nm].pop("w")
    res[key] = out
json.dump(res, open(HERE / "e_regime.json", "w"), indent=1, default=str)
for key, o in res.items():
    print(f"\n===== {key}")
    for nm in ("pre", "post"):
        x = o[nm]
        print(f"  {nm}: {x['weeks']} weeks / {x['trades']} trades, {x['from']}..{x['to']}: mean {x['mean']:+.2f} bps, se {x['se']:.2f}, "
              f"t {x['t']:.2f}, CI95 [{x['ci95'][0]:+.2f}, {x['ci95'][1]:+.2f}], sd {x['sd']:.1f}, HAC inflation {x['hac_inflation']:.2f}")
        print(f"       trades {x['by_instrument_trades']} | instruments/week {x['instruments_per_week']} | mean bps by instrument {x['by_instrument_mean_bps']}")
        print(f"       weeks needed (one-sided 5%, 80% power) for true mean: {x['weeks_needed']}")
    print(f"  pre - post: {o['diff']['pre_minus_post']:+.2f} bps, se {o['diff']['se']:.2f}, z {o['diff']['z']:.2f}, p {o['diff']['p_two_sided']:.3f}")
    print(f"  by year (weeks, mean, t): {o['years']}")
    print(f"  post-regime costs (mean, t) by multiple: {o['post_costs']}")
    print(f"  leave-one-out all: {o['loo']['all']}")
    print(f"  leave-one-out post: {o['loo']['post']}")
