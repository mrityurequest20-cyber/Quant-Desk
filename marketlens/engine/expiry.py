"""The expiry in front: where open interest says the price might be held, how the straddle is decaying, and what
past expiries actually did.

Max pain is the settlement price at which option buyers, all of them together, would collect the least: the strike
that minimises the payout on every open call and put of that expiry. The folk claim is that expiries are pulled
towards it ("pinning"). The study here tests that, per expiry, against a fair baseline: from the last close before
expiry, did the settlement land closer to max pain than to the mirror point the same distance on the other side of
the price? With no pull, that is a coin toss (a symmetric move favours neither point), so the share is tested
against one half.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import binomtest


def oi_by_strike(opt: pd.DataFrame, day, expiry) -> pd.DataFrame:
    """Call and put open interest by strike for one expiry on one day."""
    return _pivot(opt[(opt["date"] == day) & (opt["expiry"] == expiry) & opt["kind"].isin(["CE", "PE"])])


def _pivot(o: pd.DataFrame) -> pd.DataFrame:
    if o.empty:
        return pd.DataFrame(columns=["strike", "oi_c", "oi_p"])
    p = o.pivot_table(index="strike", columns="kind", values="oi", aggfunc="sum").fillna(0.0)
    return pd.DataFrame({"strike": p.index.values.astype(float),
                         "oi_c": p["CE"].values if "CE" in p else np.zeros(len(p)),
                         "oi_p": p["PE"].values if "PE" in p else np.zeros(len(p))})


def max_pain(oi: pd.DataFrame) -> float | None:
    """The strike at which the total payout to every open call and put of the expiry is smallest."""
    if oi.empty or (oi["oi_c"].sum() + oi["oi_p"].sum()) <= 0:
        return None
    K, c, p = oi["strike"].values, oi["oi_c"].values, oi["oi_p"].values
    pay = [(c * np.maximum(s - K, 0)).sum() + (p * np.maximum(K - s, 0)).sum() for s in K]
    return float(K[int(np.argmin(pay))])


def payout_curve(oi: pd.DataFrame, lo: float, hi: float) -> dict:
    """Total payout to option buyers (OI units x rupees, in Rs crore) at each strike between lo and hi."""
    K, c, p = oi["strike"].values, oi["oi_c"].values, oi["oi_p"].values
    ks = [k for k in K if lo <= k <= hi]
    pay = [float(((c * np.maximum(s - K, 0)).sum() + (p * np.maximum(K - s, 0)).sum()) / 1e7) for s in ks]
    return {"strike": [float(k) for k in ks], "payout": [round(x, 3) for x in pay]}


def front(opt: pd.DataFrame, t: pd.DataFrame, asof, spot: float) -> dict | None:
    """The nearest expiry after asof: max pain, the biggest call and put strikes, the payout curve, and the
    straddle's path since it was a month out against the square-root-of-time decay a constant vol would give."""
    o = opt[(opt["date"] == asof) & opt["kind"].isin(["CE", "PE"]) & (opt["expiry"] > asof)]
    if o.empty:
        return None
    e = o["expiry"].min()
    oi = oi_by_strike(opt, asof, e)
    mp = max_pain(oi)
    band = oi[(oi["strike"] / spot - 1).abs() <= 0.10]
    wc = band.loc[band["oi_c"].idxmax(), "strike"] if len(band) and band["oi_c"].max() > 0 else None
    wp = band.loc[band["oi_p"].idxmax(), "strike"] if len(band) and band["oi_p"].max() > 0 else None
    out = {"expiry": str(pd.Timestamp(e).date()), "days": int((pd.Timestamp(e) - pd.Timestamp(asof)).days), "spot": spot,
           "max_pain": mp, "call_wall": float(wc) if wc is not None else None, "put_wall": float(wp) if wp is not None else None,
           "payout": payout_curve(oi, spot * 0.94, spot * 1.06)}
    path = t[t["expiry"] == e].sort_values("date")
    path = path[path["days"] <= 35]
    if len(path):
        T0, S0 = float(path["T"].iat[0]), float(path["straddle"].iat[0])
        out["decay"] = {"date": [str(d.date()) for d in path["date"]], "days": path["days"].astype(int).tolist(),
                        "straddle": path["straddle"].round(2).tolist(), "move": path["implied_move"].round(5).tolist(),
                        # what the first reading would be worth later at an unchanged vol and price: S0 x sqrt(T/T0)
                        "sqrt_t": [round(S0 * float(np.sqrt(x / T0)), 2) for x in path["T"]]}
    return out


def pin_study(opt: pd.DataFrame, t: pd.DataFrame, close: pd.Series, asof) -> dict | None:
    """Every past expiry with an option chain the session before and a close on the day: did the settlement land
    closer to max pain than to its mirror point? Also: how often the expiry-day move stayed inside the one-day
    straddle priced at the close before."""
    o = opt[opt["kind"].isin(["CE", "PE"])]
    days = list(close.index)
    pos = {d: i for i, d in enumerate(days)}
    exps = sorted(pd.Timestamp(e) for e in o["expiry"].unique() if pd.Timestamp(e) <= pd.Timestamp(asof) and pos.get(pd.Timestamp(e), 0) > 0)
    pairs = {(days[pos[e] - 1], e) for e in exps}
    sub = o[o["date"].isin({p for p, _ in pairs})]
    sub = {k: g for k, g in sub.groupby(["date", "expiry"]) if k in pairs}
    rows = []
    tt = t.set_index(["date", "expiry"]) if len(t) else None
    for e in exps:
        i = pos[e]
        prev = days[i - 1]
        oi = _pivot(sub.get((prev, e), o.iloc[:0]))
        mp = max_pain(oi)
        s0, s1 = float(close.iat[i - 1]), float(close.iat[i])
        if mp is None or not (s0 > 0 and s1 > 0):
            continue
        mirror = 2 * s0 - mp
        tie = np.isclose(mp, s0)
        mv = None
        if tt is not None and (prev, e) in tt.index:
            mv = float(tt.loc[(prev, e), "implied_move"])
        rows.append({"expiry": e, "s0": s0, "s1": s1, "mp": mp, "d0": abs(s0 - mp) / s0,
                     "closer": None if tie else bool(abs(s1 - mp) < abs(s1 - mirror)),
                     "move": abs(s1 / s0 - 1), "priced": mv})
    if not rows:
        return None
    r = pd.DataFrame(rows)
    decided = r.dropna(subset=["closer"])
    # a max pain within a tenth of a percent of the price says nothing about direction: those are not counted
    decided = decided[decided["d0"] >= 0.001]
    if len(decided) < 20:
        return None
    k = int(decided["closer"].sum())
    pr = r.dropna(subset=["priced"])
    # p: one-sided, for a pull towards max pain; p_two: either way (NIFTY settles AWAY from it more often than not)
    out = {"n": int(len(decided)), "closer": k, "share": k / len(decided), "p": float(binomtest(k, len(decided), 0.5, alternative="greater").pvalue),
           "p_two": float(binomtest(k, len(decided), 0.5).pvalue),
           "since": str(r["expiry"].min().date()), "median_gap": float(decided["d0"].median()),
           "inside": float((pr["move"] <= pr["priced"]).mean()) if len(pr) >= 20 else None, "n_priced": int(len(pr)),
           "recent": [{"expiry": str(x.expiry.date()), "close_before": x.s0, "max_pain": x.mp, "settle": x.s1,
                       # an expiry left out of the count (max pain within 0.1% of the price) shows as not counted
                       "closer": x.closer if x.d0 >= 0.001 else None, "move": x.move, "priced": x.priced}
                      for x in r.tail(8).itertuples()]}
    return out
