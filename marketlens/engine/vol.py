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
TICK_ERR = 0.0625         # see expiry_table: the IV error of half a tick on each leg of an ATM straddle, times F sqrt(T)
MIN_STRADDLE = 1.0        # rupees/points: below this the tick size, not the market, sets the implied vol
MIN_STRIKE_SHARE = 0.005  # a strike trading under 0.5% of its expiry's busiest strike is not read for the smile or wings
MIN_LIQ_SHARE = 0.002     # an expiry trading under 0.2% of the day's busiest expiry near the money is not read
EVENT_MIN_RATIO = 4.0     # an "event": the priced day's variance at least 4x a normal day's (a move at least 2x normal)
EVENT_MIN_DAYS = 3        # and the front expiry at least 3 days out: expiry-week gamma premium is not an event
EVENT_MIN_EXCESS = 0.10   # and front vol at least 10% above the forward vol: a gentle slope over a long month is not one


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


def near_future(opt: pd.DataFrame) -> pd.Series:
    """The near-month future's price each day (close when it traded, else settlement)."""
    f = opt[opt["kind"] == "FUT"]
    if f.empty:
        return pd.Series(dtype=float)
    f = f.assign(px=np.where(f["close"] > 0, f["close"], f["settle"]))
    f = f[(f["expiry"] > f["date"]) & (f["px"] > 0)].sort_values(["date", "expiry"])
    return f.drop_duplicates("date").set_index("date")["px"]


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

    # liquidity of each expiry near the money: an expiry that barely traded (314 contracts against 37 million in the
    # front, BANKNIFTY 7 Feb 2022) prints stale prices and must not set the curve
    near = o.merge(fw[["date", "expiry", "F"]], on=["date", "expiry"])
    near = near[(near["strike"] / near["F"] - 1).abs() <= 0.03]
    liq = near.groupby(["date", "expiry"])["contracts"].sum().rename("atm_contracts").reset_index()
    fw = fw.merge(liq, on=["date", "expiry"], how="left")

    o = o.merge(fw[["date", "expiry", "T", "F"]], on=["date", "expiry"])
    o = o[(o["strike"] / o["F"]).between(0.6, 1.6)]
    otm = ((o["kind"] == "CE") & (o["strike"] >= o["F"])) | ((o["kind"] == "PE") & (o["strike"] < o["F"]))
    o = o[otm].copy()
    o["iv"] = implied_vol(o["px"].values, o["F"].values, o["strike"].values, o["T"].values, (o["kind"] == "CE").values)
    o = o.dropna(subset=["iv"])
    # a settlement-priced strike far from the money is a model value; keep it only within the traded range
    o = o.sort_values(["date", "expiry", "strike"])
    ex_max = o.groupby(["date", "expiry"])["contracts"].transform("max")
    o["liquid"] = o["traded"] & (o["contracts"] >= np.maximum(1.0, MIN_STRIKE_SHARE * ex_max))

    rows = []
    for (d, e), g in o.groupby(["date", "expiry"], sort=False):
        K = g["strike"].values
        iv = g["iv"].values
        tr = g["traded"].values
        if tr.sum() >= 2:
            # the smile and the wings use liquid traded strikes only: a strike that printed a handful of contracts
            # (0.5% of the expiry's busiest strike) carries a stale price, which is what made BANKNIFTY's 25-delta
            # risk reversal jump by 10 vol points in a day
            c = g["contracts"].values
            liq = tr & (c >= max(1.0, MIN_STRIKE_SHARE * c.max()))
            liq |= np.isclose(K, g["F"].iat[0], rtol=0.03) & tr        # the money itself always counts if it traded
            K, iv = K[liq], iv[liq]
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
    # two independent reads of the same thing must agree: the smile's ATM vol, and the vol the straddle itself implies
    # (at the forward, C + P = 2 e^{-rT} F (2N(sigma sqrt(T) / 2) - 1)). A broken at-the-money print shows as a split
    # (BANKNIFTY 4 Jun 2020: smile 8.7% while every liquid strike around it was above 15%)
    from scipy.special import ndtri
    q = (t["straddle"] / (2 * np.exp(-R * t["T"]) * t["F"]) + 1) / 2
    t["straddle_iv"] = np.where(q.between(0.5, 0.9999), 2 * ndtri(q.clip(0.5, 0.9999)) / np.sqrt(t["T"]), np.nan)
    # an expiry is read only when its at-the-money pair really traded and the parity strike sits near the forward:
    # in thin years (2019-2021 weeklies) the other expiries carry only stale settlement prices, which gave a 2020
    # crash curve of 75% beside a traded monthly at 47%
    good = t["atm_traded"].fillna(False).astype(bool) & ((t["atm_strike"] / t["F"] - 1).abs() <= 0.03)
    # anchor to the market: each expiry's parity forward must sit within 3% of the day's near-month future, the most
    # liquid contract there is (carry over a few months is well under 3%). A stale pair once put BANKNIFTY's weekly
    # forward at 18,301 with the index near 20,400 (4 Jun 2020), and every IV of that expiry with it.
    anchor = near_future(opt)
    a = t["date"].map(anchor)
    good &= ((t["F"] / a - 1).abs() <= 0.03) | a.isna()
    # a straddle of a few ticks (a Rs 20 stock near expiry) is all rounding; an IV outside 3%..300% is a broken print
    # (Reliance's Jio Financial demerger day showed 1.4%)
    good &= (t["straddle"] >= MIN_STRADDLE) & t["atm_iv"].between(0.03, 3.0)
    good &= ((t["atm_iv"] / t["straddle_iv"] - 1).abs() <= 0.25).fillna(False)
    # precision: half a tick (0.025) on each leg moves a straddle's IV by about 0.0625 / (F sqrt(T)); skip an expiry
    # where that exceeds one vol point (a Rs 35 stock a week from expiry), where rounding, not the market, sets the IV
    good &= (TICK_ERR / (t["F"] * np.sqrt(t["T"]))) <= 0.01
    day_max = t.groupby("date")["atm_contracts"].transform("max")
    is_front = t.groupby("date")["expiry"].transform("min") == t["expiry"]
    good &= is_front | (t["atm_contracts"].fillna(0) >= MIN_LIQ_SHARE * day_max)
    t = t[good].copy()
    t["days"] = (t["expiry"] - t["date"]).dt.days
    t = drop_curve_outliers(t)
    t["implied_move"] = t["straddle"] / t["F"]
    return t.sort_values(["date", "expiry"]).reset_index(drop=True), o


def drop_curve_outliers(t: pd.DataFrame) -> pd.DataFrame:
    """Remove an expiry whose ATM vol breaks from its own curve that day: a thinly traded pair printing at a stale
    price (NIFTY 5 Aug 2024: one far weekly at 25.5% between neighbours at 18.6% and 16.3%). An interior expiry is
    compared with the total-variance interpolation of its two neighbours. The end expiries are never removed: the
    front is the most liquid and is where an event shows (45% before results with 25% behind it is the signal, not
    noise). One point is removed at a time, the worst first, and the rest re-judged, so a bad print never takes an
    honest neighbour down with it."""
    drop = []
    for _, g in t.groupby("date", sort=False):
        g = g.sort_values("days")
        idx = list(g.index)
        x = g["days"].astype(float).to_dict()
        v = g["atm_iv"].to_dict()

        def excesses(keys):
            out = {}
            for i in range(1, len(keys) - 1):
                k, a, b = keys[i], keys[i - 1], keys[i + 1]
                wi = np.interp(x[k], [x[a], x[b]], [v[a] ** 2 * x[a], v[b] ** 2 * x[b]])
                ref = np.sqrt(max(wi, 1e-12) / x[k])
                # below its neighbours = total variance falling with maturity, which a clean market cannot show:
                # tight tolerance. Above them can be a real event inside that expiry: wide tolerance.
                tol = max(0.03, 0.15 * ref) if v[k] < ref else max(0.05, 0.3 * ref)
                out[k] = abs(v[k] - ref) / tol
            return out

        budget = max(1, len(idx) // 3)          # never more than a third of a day's curve: no cascades
        while len(idx) >= 3 and budget > 0:
            budget -= 1
            ex = excesses(idx)
            if not ex or max(ex.values()) <= 1:
                break
            # leave-one-out: remove the expiry whose absence leaves the cleanest curve (a bad print makes its honest
            # neighbour look bad too, so the worst-looking point is not always the culprit)
            best = min((k for k, e in ex.items() if e > 1),
                       key=lambda k: (max(excesses([j for j in idx if j != k]).values(), default=0), -ex[k]))
            drop.append(best)
            idx.remove(best)
    return t.drop(index=drop)


def constant_maturity(t: pd.DataFrame, days: float = 30.0) -> pd.Series:
    """IV at a fixed horizon, by interpolating total variance between expiries (flat extrapolation at the ends)."""
    out = {}
    for d, g in t[t["days"] >= 2].dropna(subset=["atm_iv"]).groupby("date"):
        g = g.sort_values("days")
        if g["days"].max() < 7:          # only an expiry this week: stretching it to 30 days amplifies its noise
            continue
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
    if a["days"] < EVENT_MIN_DAYS:
        return None
    ev = w1 - fwd * (t1 - 1 / 365)
    if ev < fwd / 365 * EVENT_MIN_RATIO or a["atm_iv"] < np.sqrt(fwd) * (1 + EVENT_MIN_EXCESS):
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
            raw = float(np.exp(-x))                      # old price / new price on the day
            ratio = snap_ratio(raw)                      # the corporate action's own ratio (a bonus 2:1 is exactly 3)
            # divide history by the action's ratio only, so the day's real market move stays in the series
            s.loc[s.index < d, ["open", "high", "low", "close"]] /= ratio
            events.append({"date": str(d.date()), "ratio": round(ratio, 4), "raw": round(raw, 4)})
    return s, events


def corporate_actions(opt: pd.DataFrame, close: pd.Series, market: pd.Series) -> list[dict]:
    """Days the exchange rebuilt a stock's option strikes for a corporate action that is not a split or bonus
    (demergers such as Jio Financial from Reliance on 20 Jul 2023 or ITC Hotels on 6 Jan 2025, rights issues, special
    dividends). Before such a day the options price the adjusted contract, so their implied vol is not comparable with
    any other day's (ITC printed 5% a year). Conditions: more than half of an expiry's strikes replaced overnight; the
    stock moved more than 5% beyond the market; the market itself calm (under 2%) or the new strikes visibly adjusted
    (non-round), since crash days rebuild strikes too; and the lot size unchanged (a split or bonus is handled by
    adjust_splits)."""
    c = opt[opt["kind"] == "CE"]
    if c.empty:
        return []
    sets = c.groupby(["date", "expiry"])["strike"].apply(lambda x: set(np.round(x.values, 2)))
    lots = opt.groupby("date")["lot"].median()
    rs = np.log(close).diff()
    rm = np.log(market.reindex(close.index)).diff()
    days = sorted(c["date"].unique())
    out = []
    for a, b in zip(days, days[1:]):
        for e in c.loc[c["date"] == b, "expiry"].unique():
            if (a, e) in sets.index and (b, e) in sets.index:
                A, B = sets[(a, e)], sets[(b, e)]
                if len(A) > 5 and len(A & B) / len(A) < 0.5:
                    resid = abs(rs.get(b, np.nan) - (rm.get(b, 0) if np.isfinite(rm.get(b, np.nan)) else 0))
                    la, lb = lots.get(a, np.nan), lots.get(b, np.nan)
                    if np.isfinite(la) and np.isfinite(lb):
                        lot_same = abs(lb / la - 1) < 0.05
                    else:                    # old bhavcopy: no lot sizes; a split/bonus is at least 5:4 (a 20%+ drop)
                        lot_same = abs(rs.get(b, 0)) < np.log(1.2)
                    new = B - A
                    odd = np.mean([abs(k * 2 - round(k * 2)) > 1e-6 for k in new]) if new else 0.0
                    calm = abs(rm.get(b, 0)) < 0.02 if np.isfinite(rm.get(b, np.nan)) else True
                    # crash days rebuild strikes too (the warehouse keeps +-30%): require a calm market that day, or
                    # strikes the exchange visibly adjusted to non-round values
                    if np.isfinite(resid) and resid > 0.05 and lot_same and (calm or odd >= 0.5):
                        out.append({"date": str(pd.Timestamp(b).date()), "move": float(rs.get(b))})
                    break
    return out


def drop_action_windows(t: pd.DataFrame, actions: list[dict], sessions: int = 25) -> pd.DataFrame:
    """Remove, from the vol table, every expiry that spans a corporate-action day, for the sessions before it."""
    if not actions or t.empty:
        return t
    days = np.array(sorted(t["date"].unique()))
    keep = np.ones(len(t), bool)
    for a in actions:
        d = pd.Timestamp(a["date"])
        i = days.searchsorted(d)
        start = days[max(0, i - sessions)]
        keep &= ~((t["date"] >= start) & (t["date"] < d) & (t["expiry"] >= d)).values
    return t[keep]


def snap_ratio(raw: float, tol: float = 0.06) -> float:
    """The corporate action's own ratio behind a one-day price jump. Bonus and split ratios are simple (1:1 bonus = 2,
    2:1 bonus = 3, 1:5 split = 5, 1:2 split + 4:1 bonus = 10, 1:2 bonus = 1.5), and the jump also carries that day's
    market move, so the simplest ratio within tol wins over a closer but unlikely one (BSE May 2025: 2.86 -> 3)."""
    for q in (1, 2, 4, 3, 5):                    # whole numbers first, then halves, quarters, thirds, fifths
        for p in range(q + 1, 100 * q + 1):
            if abs(p / q / raw - 1) <= tol:
                return p / q
    return raw


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
