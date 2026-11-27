"""Volatility from the option record itself: implied vol, the forward, skew, straddles, realised vol and the premium.

Method (every day, every expiry, from the bhavcopy):
  * Price of an option = its close when it traded that day (contracts > 0), else NSE's settlement price. Untraded
    settlement prices are theoretical, so the forward and the at-the-money numbers use traded strikes only.
  * Forward F from put-call parity at the strike where |C - P| is smallest: F = K + e^{rT}(C - P). No dividend or
    carry assumption is needed; the options' own prices say where the market puts the forward.
  * Implied vol by Black-76 on F, out-of-the-money side only (calls above F, puts below), which is the liquid side.
  * ATM IV interpolated at F. 25-delta strikes from the ATM vol; risk reversal = IV(25d call) - IV(25d put),
    butterfly = mean of the two wings - ATM. A negative risk reversal means puts cost more than calls (normal for
    Indian indices: insurance against falls is in demand).
  * Straddle = C + P at the strike nearest F: what the market charges for the move to expiry. straddle / F is the
    implied move in percent (about 0.8 * IV * sqrt(T) by the usual rule of thumb).
  * Constant-maturity 30-day IV: total variance (sigma^2 T) interpolated in time between the expiries around 30 days,
    so days with different expiry calendars are comparable over years.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.special import ndtr

R = 0.065                 # a flat INR rate; it only discounts the option prices (it barely moves an implied vol)
Z25 = 0.6745              # the normal quantile of a 25-delta strike (approximately, for a forward delta)
MIN_DAYS = 1.0            # an expiry this close is not read for IV (expiry-day prices are all intrinsic and noise)
MAX_EXPIRIES = 6


def _b76(F, K, T, sig, call):
    sq = sig * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sq * sq) / sq
    d2 = d1 - sq
    df = np.exp(-R * T)
    c = df * (F * ndtr(d1) - K * ndtr(d2))
    p = df * (K * ndtr(-d2) - F * ndtr(-d1))
    return np.where(call, c, p)


def implied_vol(price, F, K, T, call, lo=0.005, hi=4.0, iters=60) -> np.ndarray:
    """Vectorised Black-76 implied vol by bisection (robust for every input; 60 halvings reach 1e-17 of the range).
    NaN where the price is outside the no-arbitrage bounds."""
    price, F, K, T = (np.asarray(x, float) for x in (price, F, K, T))
    call = np.asarray(call, bool)
    df = np.exp(-R * T)
    intrinsic = df * np.where(call, np.maximum(F - K, 0), np.maximum(K - F, 0))
    upper = df * np.where(call, F, K)
    ok = (price > intrinsic + 1e-9) & (price < upper) & (T > 0) & (F > 0) & (K > 0)
    a = np.full(price.shape, lo)
    b = np.full(price.shape, hi)
    for _ in range(iters):
        m = 0.5 * (a + b)
        high = _b76(F, K, T, m, call) > price
        b = np.where(high, m, b)
        a = np.where(high, a, m)
    out = 0.5 * (a + b)
    out[~ok] = np.nan
    out[(out <= lo * 1.01) | (out >= hi * 0.99)] = np.nan
    return out


def _prices(opt: pd.DataFrame) -> pd.DataFrame:
    o = opt[opt["kind"].isin(["CE", "PE"])].copy()
    traded = o["contracts"].fillna(0) > 0
    o["px"] = np.where(traded & (o["close"] > 0), o["close"], o["settle"])
    o["traded"] = traded
    o = o[o["px"] > 0]
    o["days"] = (o["expiry"] - o["date"]).dt.days.astype(float)
    return o


def expiry_table(opt: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per (date, expiry): days, forward, ATM IV, 25d RR/fly, straddle. Also returns the per-strike IV rows (for smiles)."""
    o = _prices(opt)
    o = o[o["days"] >= MIN_DAYS]
    if o.empty:
        return pd.DataFrame(), pd.DataFrame()
    # keep the nearest MAX_EXPIRIES expiries each day
    rank = o.groupby("date")["expiry"].rank(method="dense")
    o = o[rank <= MAX_EXPIRIES]

    # forward from parity on traded pairs (fall back to settlement pairs when a day has none traded)
    c = o[o["kind"] == "CE"][["date", "expiry", "strike", "px", "traded"]]
    p = o[o["kind"] == "PE"][["date", "expiry", "strike", "px", "traded"]]
    pair = c.merge(p, on=["date", "expiry", "strike"], suffixes=("_c", "_p"))
    pair["both"] = pair["traded_c"] & pair["traded_p"]
    pair["gap"] = (pair["px_c"] - pair["px_p"]).abs()
    pair = pair.sort_values(["date", "expiry", "both", "gap"], ascending=[True, True, False, True])
    atm = pair.drop_duplicates(["date", "expiry"]).copy()
    atm["T"] = ((atm["expiry"] - atm["date"]).dt.days.clip(lower=0.5)) / 365.0
    atm["F"] = atm["strike"] + np.exp(R * atm["T"]) * (atm["px_c"] - atm["px_p"])
    atm["straddle"] = atm["px_c"] + atm["px_p"]
    atm = atm.rename(columns={"strike": "atm_strike", "both": "atm_traded"})
    fw = atm[["date", "expiry", "T", "F", "atm_strike", "straddle", "atm_traded"]]

    o = o.merge(fw[["date", "expiry", "T", "F"]], on=["date", "expiry"])
    o = o[(o["strike"] / o["F"]).between(0.6, 1.6)]
    otm = ((o["kind"] == "CE") & (o["strike"] >= o["F"])) | ((o["kind"] == "PE") & (o["strike"] < o["F"]))
    o = o[otm].copy()
    o["iv"] = implied_vol(o["px"].values, o["F"].values, o["strike"].values, o["T"].values, (o["kind"] == "CE").values)
    o = o.dropna(subset=["iv"])
    # a settlement-priced strike far from the money is a model value; keep it only within the traded range
    o = o.sort_values(["date", "expiry", "strike"])

    rows = []
    for (d, e), g in o.groupby(["date", "expiry"], sort=False):
        K = g["strike"].values
        iv = g["iv"].values
        tr = g["traded"].values
        if tr.sum() >= 2:
            lo, hi = K[tr].min(), K[tr].max()
            m = (K >= lo) & (K <= hi)
            K, iv = K[m], iv[m]
        if len(K) < 2:
            continue
        F = g["F"].iat[0]
        T = g["T"].iat[0]
        if not (K.min() <= F <= K.max()):
            continue
        a = float(np.interp(F, K, iv))
        sq = a * np.sqrt(T)
        kc = F * np.exp(0.5 * sq * sq + Z25 * sq)
        kp = F * np.exp(0.5 * sq * sq - Z25 * sq)
        rr = fly = np.nan
        if K.min() <= kp and kc <= K.max():
            ivc = float(np.interp(kc, K, iv))
            ivp = float(np.interp(kp, K, iv))
            rr = ivc - ivp
            fly = 0.5 * (ivc + ivp) - a
        rows.append((d, e, a, rr, fly, len(K)))
    t = pd.DataFrame(rows, columns=["date", "expiry", "atm_iv", "rr25", "fly25", "n_strikes"])
    t = t.merge(fw, on=["date", "expiry"], how="left")
    t["days"] = (t["expiry"] - t["date"]).dt.days
    t["implied_move"] = t["straddle"] / t["F"]
    return t.sort_values(["date", "expiry"]).reset_index(drop=True), o


def constant_maturity(t: pd.DataFrame, days: float = 30.0) -> pd.Series:
    """IV at a fixed horizon, by interpolating total variance between expiries (flat extrapolation at the ends)."""
    out = {}
    for d, g in t.dropna(subset=["atm_iv"]).groupby("date"):
        g = g.sort_values("days")
        x = g["days"].values.astype(float)
        w = (g["atm_iv"].values ** 2) * x
        if len(x) == 1 or days <= x[0]:
            out[d] = g["atm_iv"].iat[0] if days <= x[0] else g["atm_iv"].iat[-1]
            continue
        if days >= x[-1]:
            out[d] = g["atm_iv"].iat[-1]
            continue
        wi = np.interp(days, x, w)
        out[d] = np.sqrt(max(wi, 0) / days)
    return pd.Series(out, name=f"iv{int(days)}").sort_index()


def front(t: pd.DataFrame, min_days: int = 2) -> pd.DataFrame:
    """The nearest expiry each day with at least min_days to go."""
    f = t[t["days"] >= min_days].sort_values(["date", "days"])
    return f.drop_duplicates("date").set_index("date")


def event_vol(t: pd.DataFrame, asof) -> dict | None:
    """The move the front two expiries imply for a single event day between them: the extra variance in the front
    expiry over the forward vol between the two expiries. None when the curve is not inverted enough to show one."""
    g = t[(t["date"] == asof) & (t["days"] >= 1)].sort_values("days").dropna(subset=["atm_iv"])
    if len(g) < 2:
        return None
    a, b = g.iloc[0], g.iloc[1]
    t1, t2 = a["days"] / 365, b["days"] / 365
    w1, w2 = a["atm_iv"] ** 2 * t1, b["atm_iv"] ** 2 * t2
    fwd = (w2 - w1) / (t2 - t1)
    if fwd <= 0:
        return None
    ev = w1 - fwd * (t1 - 1 / 365)
    if ev <= fwd / 365 * 1.2:
        return None
    return {"event_move": float(np.sqrt(ev)), "normal_day_move": float(np.sqrt(fwd / 365)),
            "front_expiry": str(a["expiry"].date()), "fwd_vol": float(np.sqrt(fwd))}


# ---------------- realised ----------------

def adjust_splits(spot: pd.DataFrame, lots: pd.Series | None, kind: str) -> tuple[pd.DataFrame, list]:
    """Remove corporate-action jumps from a stock's price history (bonus/split days show up as a one-day jump with a lot
    size change). Prices before the event are divided by the jump. Returns the adjusted frame and the events found."""
    if kind != "stock" or spot.empty:
        return spot, []
    s = spot.copy()
    r = np.log(s["close"]).diff()
    lot_chg = None
    if lots is not None and len(lots):
        lot_chg = lots.reindex(s.index).ffill().pct_change().abs()
    events = []
    for d, x in r.items():
        if not np.isfinite(x):
            continue
        big = abs(x) > 0.4 or (abs(x) > 0.15 and lot_chg is not None and (lot_chg.get(d, 0) or 0) > 0.2)
        if big:
            f = np.exp(x)
            s.loc[s.index < d, ["open", "high", "low", "close"]] *= f
            events.append({"date": str(d.date()), "ratio": round(float(1 / f), 4)})
    return s, events


def realised(spot: pd.DataFrame) -> pd.DataFrame:
    """Annualised realised vol, close-to-close and Parkinson (high-low) where highs and lows exist."""
    s = spot.sort_index()
    r = np.log(s["close"]).diff()
    out = pd.DataFrame(index=s.index)
    out["ret"] = r
    for w in (5, 10, 21, 63, 126, 252):
        out[f"rv{w}"] = r.rolling(w, min_periods=int(w * 0.8)).std() * np.sqrt(252)
    hl = np.log(s["high"] / s["low"])
    if hl.notna().sum() > 50:
        pk = (hl ** 2) / (4 * np.log(2))
        out["pk21"] = np.sqrt(pk.rolling(21, min_periods=15).mean() * 252)
    out["fwd_rv21"] = out["rv21"].shift(-21)
    return out


def cone(rv: pd.DataFrame, windows=(5, 10, 21, 63, 126, 252)) -> list[dict]:
    """The volatility cone: for each window, the distribution of realised vol over history and where today sits."""
    rows = []
    for w in windows:
        x = rv[f"rv{w}"].dropna()
        if len(x) < 30:
            continue
        rows.append({"window": w, "min": x.min(), "p10": x.quantile(.1), "p25": x.quantile(.25),
                     "p50": x.median(), "p75": x.quantile(.75), "p90": x.quantile(.9), "max": x.max(),
                     "now": x.iat[-1], "pct": float((x < x.iat[-1]).mean())})
    return rows


def move_scorecard(t: pd.DataFrame, spot: pd.Series) -> dict:
    """How the options market's implied move compared with what happened, over history.

    For every day and its front expiry, implied = straddle / F, realised = |S(expiry) - S(day)| / S(day) using the
    official close on the expiry date. The share of days the move stayed inside the implied range, and the ratio,
    by days-to-expiry bucket. Overlapping windows: the counts are of days, not of independent trials."""
    f = t[(t["days"] >= 1) & t["implied_move"].notna()].sort_values(["date", "days"]).drop_duplicates("date")
    s = spot.sort_index()
    idx = s.index
    pos = idx.searchsorted(f["expiry"].values, side="right") - 1
    ok = pos >= 0
    f = f[ok].copy()
    pos = pos[ok]
    f["s_exp"] = s.values[pos]
    f["s_exp_date"] = idx[pos]
    f = f[f["s_exp_date"] >= f["expiry"] - pd.Timedelta(days=4)]     # an expiry the spot history reaches
    s0 = s.reindex(f["date"]).values
    f["realised"] = np.abs(f["s_exp"].values - s0) / s0
    f = f.dropna(subset=["realised"])
    f = f[f["expiry"] <= idx.max()]
    if f.empty:
        return {}
    f["inside"] = f["realised"] <= f["implied_move"]
    f["ratio"] = f["realised"] / f["implied_move"]
    buckets = [(1, 3, "1-3 days"), (4, 8, "4-8 days"), (9, 20, "9-20 days"), (21, 45, "21-45 days")]
    out = []
    for lo, hi, lab in buckets:
        g = f[f["days"].between(lo, hi)]
        if len(g) >= 15:
            out.append({"bucket": lab, "n": int(len(g)), "inside": float(g["inside"].mean()),
                        "median_ratio": float(g["ratio"].median()), "p90_ratio": float(g["ratio"].quantile(.9)),
                        "avg_implied": float(g["implied_move"].mean()), "avg_realised": float(g["realised"].mean())})
    recent = f.tail(260)
    return {"buckets": out, "n": int(len(f)), "since": str(f["date"].min().date()),
            "inside_all": float(f["inside"].mean()), "inside_1y": float(recent["inside"].mean()),
            "ratio_1y": float(recent["ratio"].median()),
            "series": f[["date", "implied_move", "realised"]].tail(400)}
