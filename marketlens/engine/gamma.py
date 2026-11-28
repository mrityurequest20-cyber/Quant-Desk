"""Gamma by strike: where option hedging flows are largest, and which way they push.

Gamma of an option (Black-76 on the expiry's own parity forward, the vol read off that expiry's liquid smile at the
strike) times its open interest is how much underlying the holders of that strike must trade for a 1% move. It is
reported in rupees: gamma x OI x F^2 x 1%, summed over expiries, in Rs crore per 1% move.

Two readings, kept apart because only one needs an assumption:

  * gamma concentration, calls and puts separately: no assumption. It is where hedging would be heaviest.
  * the hedging book's NET gamma. Whether a strike's gamma makes the market calmer or wilder depends on who is long
    it. NSE publishes each participant's long and short index (and stock) options, by calls and puts, every day
    (participant_oi). The desks that delta-hedge are the proprietary traders (Pro) and the foreign institutions (FII);
    their net share of the market's call and put open interest gives the sign. Clients are not assumed to hedge.
    A positive net means the hedgers are long gamma: they sell into rises and buy into falls, which damps moves. A
    negative net means they chase moves. The flip is the price where the net changes sign.

The participant file is one figure for all index options (or all stock options) together, not per strike or per
index, so the net is the hedgers' overall share applied to every strike: an estimate, and labelled as one.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

from .vol import R

HEDGERS = ("FII", "Pro")
CRORE = 1e7


def weights(poi: pd.DataFrame, asof, kind: str) -> dict | None:
    """The hedgers' (Pro + FII) net share of the market's call and put open interest, from the last participant file
    on or before asof. kind: 'index' or 'stock'."""
    if poi is None or poi.empty:
        return None
    p = poi[pd.to_datetime(poi["date"]) <= pd.Timestamp(asof)]
    if p.empty:
        return None
    d = pd.to_datetime(p["date"]).max()
    p = p[pd.to_datetime(p["date"]) == d]
    p = p.set_index(p["participant"].astype(str).str.strip())
    pre = "opt_idx" if kind == "index" else "opt_stk"
    if "TOTAL" not in p.index or not set(HEDGERS) <= set(p.index):
        return None
    out = {"date": str(d.date())}
    for side, col in (("calls", "call"), ("puts", "put")):
        tot = float(p.at["TOTAL", f"{pre}_{col}_long"])
        net = sum(float(p.at[h, f"{pre}_{col}_long"] - p.at[h, f"{pre}_{col}_short"]) for h in HEDGERS)
        out[side] = net / tot if tot > 0 else None
    return out if out["calls"] is not None and out["puts"] is not None else None


def weights_history(poi: pd.DataFrame, kind: str) -> pd.DataFrame:
    """weights() for every day of the participant file: columns calls, puts, indexed by date."""
    if poi is None or poi.empty:
        return pd.DataFrame(columns=["calls", "puts"])
    pre = "opt_idx" if kind == "index" else "opt_stk"
    p = poi.copy()
    p["participant"] = p["participant"].astype(str).str.strip()
    out = {}
    for side, col in (("calls", "call"), ("puts", "put")):
        tot = p[p["participant"] == "TOTAL"].groupby("date")[f"{pre}_{col}_long"].sum()
        h = p[p["participant"].isin(HEDGERS)]
        net = (h[f"{pre}_{col}_long"] - h[f"{pre}_{col}_short"]).groupby(h["date"]).sum()
        out[side] = (net / tot.replace(0, np.nan)).reindex(tot.index)
    w = pd.DataFrame(out)
    w.index = pd.to_datetime(w.index)
    return w.sort_index()


def b76_gamma(F, K, T, sig):
    """Black-76 gamma with respect to the forward (both calls and puts)."""
    F, K, T, sig = (np.asarray(x, dtype=float) for x in (F, K, T, sig))
    sq = sig * np.sqrt(T)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(F / K) + 0.5 * sq * sq) / sq
        return np.exp(-R * T) * norm.pdf(d1) / (F * sq)


def smile_points(ivrows: pd.DataFrame) -> pd.DataFrame:
    """The strikes each expiry's IV is read from: liquid traded strikes, plus any traded strike within 3% of the
    forward (as the at-the-money reading itself, and as livecore.readExpiry builds its smile)."""
    if ivrows is None or ivrows.empty:
        return pd.DataFrame(columns=["date", "expiry", "strike", "iv"])
    near = ivrows["traded"] & ((ivrows["strike"] / ivrows["F"] - 1).abs() <= 0.03)
    s = ivrows[ivrows["liquid"] | near]
    return s[["date", "expiry", "strike", "iv"]].sort_values(["date", "expiry", "strike"])


def chain(opt: pd.DataFrame, t: pd.DataFrame, ivrows: pd.DataFrame, days) -> pd.DataFrame:
    """Per (date, expiry, strike): call and put OI, the expiry's F and T, and the vol at the strike. Only expiries
    that passed every curve check that day, strikes 0.6..1.6 of the forward."""
    days = set(pd.to_datetime(list(days)))
    o = opt[opt["kind"].isin(["CE", "PE"]) & opt["date"].isin(days) & (opt["expiry"] > opt["date"])]
    if o.empty or t.empty:
        return pd.DataFrame()
    oi = o.pivot_table(index=["date", "expiry", "strike"], columns="kind", values="oi", aggfunc="sum").fillna(0.0)
    oi = oi.rename(columns={"CE": "oi_c", "PE": "oi_p"}).reset_index()
    for c in ("oi_c", "oi_p"):
        if c not in oi:
            oi[c] = 0.0
    c = oi.merge(t[t["date"].isin(days)][["date", "expiry", "F", "T", "atm_iv"]], on=["date", "expiry"])
    c = c[(c["strike"] / c["F"]).between(0.6, 1.6)]
    sm = {k: g for k, g in smile_points(ivrows[ivrows["date"].isin(days)]).groupby(["date", "expiry"])}
    ivs = []
    for (d, e), g in c.groupby(["date", "expiry"], sort=False):
        s = sm.get((d, e))
        if s is not None and len(s) >= 2:
            ivs.append(pd.Series(np.interp(g["strike"], s["strike"], s["iv"]), index=g.index))
        else:
            ivs.append(g["atm_iv"])
    c["iv"] = pd.concat(ivs) if ivs else np.nan
    return c.dropna(subset=["iv"])


def _gex(c: pd.DataFrame, shift: float = 1.0) -> pd.DataFrame:
    """Rs crore per 1% move, per row, with every forward moved by `shift` (1.0 = as it is)."""
    F = c["F"] * shift
    g = b76_gamma(F, c["strike"], c["T"], c["iv"]) * F * F * 0.01 / CRORE
    return pd.DataFrame({"call": g * c["oi_c"], "put": g * c["oi_p"]}, index=c.index)


def profile(opt: pd.DataFrame, t: pd.DataFrame, ivrows: pd.DataFrame, asof, spot: float, w: dict | None,
            band: float = 0.06, grid: float = 0.05) -> dict | None:
    """The as-of gamma map: by strike (within +-band of spot), the hedgers' net, and the net over a range of prices."""
    c = chain(opt, t, ivrows, [asof])
    if c.empty:
        return None
    x = _gex(c)
    c = c.assign(call=x["call"], put=x["put"])
    by = c.groupby("strike")[["call", "put"]].sum()
    out = {"asof": str(pd.Timestamp(asof).date()), "spot": spot, "expiries": sorted(str(e.date()) for e in c["expiry"].unique()),
           "call_total": float(by["call"].sum()), "put_total": float(by["put"].sum()), "weights": w}
    show = by[(by.index >= spot * (1 - band)) & (by.index <= spot * (1 + band))]
    out["strikes"] = [float(k) for k in show.index]
    out["call"] = show["call"].round(4).tolist()
    out["put"] = show["put"].round(4).tolist()
    if w:
        out["net"] = (w["calls"] * show["call"] + w["puts"] * show["put"]).round(4).tolist()
        steps = np.linspace(1 - grid, 1 + grid, 41)
        tot = []
        for s in steps:
            y = _gex(c, s)
            tot.append(float((w["calls"] * y["call"] + w["puts"] * y["put"]).sum()))
        out["profile"] = {"price": [float(spot * s) for s in steps], "net": [round(v, 4) for v in tot]}
        out["net_total"] = tot[20]
        out["flip"] = flip(out["profile"]["price"], tot, spot)
    return out


def flip(prices, net, spot) -> float | None:
    """The price nearest spot where the net changes sign (linear between grid points); None if it never does."""
    best = None
    for i in range(1, len(net)):
        a, b = net[i - 1], net[i]
        if a == 0 or (a < 0) != (b < 0):
            p = prices[i - 1] if a == 0 else prices[i - 1] + (prices[i] - prices[i - 1]) * a / (a - b)
            if best is None or abs(p - spot) < abs(best - spot):
                best = p
    return float(best) if best is not None else None


def history(opt: pd.DataFrame, t: pd.DataFrame, ivrows: pd.DataFrame, wh_hist: pd.DataFrame, days) -> pd.DataFrame:
    """Daily: total call and put gamma and the hedgers' net, at that day's prices (Rs crore per 1%)."""
    c = chain(opt, t, ivrows, days)
    if c.empty:
        return pd.DataFrame(columns=["gamma_call", "gamma_put", "gamma_net"])
    x = _gex(c)
    c = c.assign(call=x["call"], put=x["put"])
    d = c.groupby("date")[["call", "put"]].sum().rename(columns={"call": "gamma_call", "put": "gamma_put"})
    w = wh_hist.reindex(d.index, method="ffill") if len(wh_hist) else pd.DataFrame(index=d.index, columns=["calls", "puts"])
    d["gamma_net"] = w["calls"] * d["gamma_call"] + w["puts"] * d["gamma_put"]
    return d


def regime_study(hist: pd.DataFrame, ret: pd.Series, iv30: pd.Series, n_perm: int = 2000) -> dict | None:
    """Does the sign of the hedgers' net gamma line up with the next day's move, beyond what options already priced?
    Each next-day absolute return is divided by that day's 30-day IV as a daily move (iv / sqrt(252)), so a calm and
    a wild year are on one scale; the medians of the short-gamma and long-gamma days are compared, with a permutation
    p-value (the share of random splits of the same days with a gap at least this large). Raw medians are kept too:
    on NIFTY they differ by a third, almost all of it 2020, when the hedgers were short gamma on a third of days."""
    if hist.empty or "gamma_net" not in hist:
        return None
    d = pd.DataFrame({"net": hist["gamma_net"], "nxt": ret.shift(-1).abs().reindex(hist.index),
                      "iv": iv30.reindex(hist.index) / np.sqrt(252)}).dropna()
    d = d[d["iv"] > 0]
    neg = (d["net"] < 0).to_numpy()
    if neg.sum() < 20 or (~neg).sum() < 20:
        return None
    z = (d["nxt"] / d["iv"]).to_numpy()
    gap = np.median(z[neg]) - np.median(z[~neg])
    rng = np.random.default_rng(0)
    hits = sum(np.median(z[m]) - np.median(z[~m]) >= gap for m in (rng.permutation(neg) for _ in range(n_perm)))
    return {"n_neg": int(neg.sum()), "n_pos": int((~neg).sum()), "since": str(d.index.min().date()),
            "raw_neg": float(np.median(d["nxt"].to_numpy()[neg])), "raw_pos": float(np.median(d["nxt"].to_numpy()[~neg])),
            "z_neg": float(np.median(z[neg])), "z_pos": float(np.median(z[~neg])), "p": hits / n_perm}
