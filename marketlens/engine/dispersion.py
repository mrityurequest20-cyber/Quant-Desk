"""Implied against realised correlation of an index's members: what the options say about how together the members
will move, against how together they did.

Weights. NSE's index-weight sources do not answer from the build machine (its API is refused; the factsheets are
PDFs), so the weights are read from the market itself: a price index's daily return is the weighted sum of its
members' returns, so a non-negative least-squares fit of the index's returns on the members' over the last 126
sessions recovers the weights. The fit's R-squared is reported beside them (a good fit is above 0.99); a bad fit
means the member list is wrong or a member is missing, and then no correlation is shown.

Correlation, with weights w, member vols s_i and the index vol S:
    rho = (S^2 - sum w_i^2 s_i^2) / ((sum w_i s_i)^2 - sum w_i^2 s_i^2)
Implied: the vols are each one's at-the-money straddle IV (breadth.straddle_iv: the nearest expiry at least a week
out, the same method for the index and every member). Realised: 21-session close-to-close vols, and the realised
correlation of the NEXT 21 sessions, to see whether implied correlation was rich or cheap.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from .breadth import rank_1y

WIN = 126
# Members when niftyindices.com's list cannot be read (it answers from GitHub's runners, not from every machine)
FALLBACK = {
    # 14 members since SEBI's 2025 rules for indices with derivatives (at least 14 stocks, no stock over 20%, the top
    # three at most 45%); the fit on Nov 2026 data finds exactly these, top three 42.7%, R^2 0.998
    "BANKNIFTY": ["HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "BANKBARODA", "PNB", "AUBANK",
                  "IDFCFIRSTB", "FEDERALBNK", "CANBK", "YESBANK", "UNIONBANK"],
}
LISTS = {"BANKNIFTY": "ind_niftybanklist.csv", "NIFTY": "ind_nifty50list.csv", "FINNIFTY": "ind_niftyfinancelist.csv"}
INDEX_NAME = {"BANKNIFTY": "Nifty Bank", "NIFTY": "Nifty 50", "FINNIFTY": "Nifty Financial Services"}


def members(index: str, get=None) -> tuple[list[str], str]:
    """(symbols, source): niftyindices.com's constituent list, else the fallback."""
    try:
        if get is None:
            import requests

            def get(u):
                r = requests.get(u, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
                r.raise_for_status()
                return r.text
        import io
        txt = get(f"https://www.niftyindices.com/IndexConstituent/{LISTS[index]}")
        df = pd.read_csv(io.StringIO(txt))
        syms = [str(s).strip().upper() for s in df["Symbol"] if str(s).strip()]
        if len(syms) >= 5:
            return syms, "niftyindices.com"
    except Exception:                                                    # noqa: BLE001 - a list that will not load falls back
        pass
    return FALLBACK.get(index, []), "fallback list"


def returns(cash: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Daily log returns of each member from the cash bhavcopy, close against NSE's own previous close. A move beyond
    25% in a day is a split or bonus NSE did not adjust (its previous close is not adjusted): left out."""
    out = {}
    for s, c in cash.items():
        if c is None or c.empty:
            continue
        r = np.log(c["close"] / c["prev_close"])
        out[s] = r.where(r.abs() < np.log(1.25))
    return pd.DataFrame(out).sort_index()


def fit_weights(ri: pd.Series, rm: pd.DataFrame) -> tuple[pd.Series, float]:
    """Non-negative least squares of the index's returns on the members' (no intercept). Returns (weights, R^2)."""
    d = pd.concat([ri.rename("_i"), rm], axis=1).dropna()
    if len(d) < 60:
        return pd.Series(dtype=float), np.nan
    A, b = d.drop(columns="_i").to_numpy(), d["_i"].to_numpy()
    w, _ = nnls(A, b)
    res = b - A @ w
    r2 = 1 - (res ** 2).sum() / ((b - b.mean()) ** 2).sum()
    return pd.Series(w, index=d.columns.drop("_i")), float(r2)


def rho(w: pd.Series, s_members: pd.Series, s_index: float) -> float | None:
    """Average pairwise correlation implied by an index vol and its members' vols."""
    s = s_members.reindex(w.index)
    ok = s.notna() & (w > 0)
    if ok.sum() < 3 or not np.isfinite(s_index):
        return None
    w_, s_ = w[ok] / w[ok].sum(), s[ok]                     # renormalised over the members with a vol that day
    a = (w_ * s_).sum() ** 2
    b = (w_ ** 2 * s_ ** 2).sum()
    if a - b <= 0:
        return None
    return float((s_index ** 2 - b) / (a - b))


def study(index: str, ri: pd.Series, rm: pd.DataFrame, iv_index: pd.Series, iv_members: pd.DataFrame, asof) -> dict | None:
    """Weights refitted at each month end on the trailing WIN sessions; implied, realised and next-month realised
    correlation daily; today's reading, its rank against the year, and how implied compared with what followed."""
    rm = rm.copy()
    rm.index = pd.to_datetime(rm.index).astype("datetime64[ns]")
    ri = ri.copy()
    ri.index = pd.to_datetime(ri.index).astype("datetime64[ns]")
    for x in (iv_index, iv_members):
        x.index = pd.to_datetime(x.index).astype("datetime64[ns]")
    rm = rm.loc[:pd.Timestamp(asof)]
    ri = ri.loc[:pd.Timestamp(asof)]
    days = ri.dropna().index.intersection(rm.dropna(how="all").index)          # sessions both the index and its members have
    if len(days) < WIN + 60:
        return None
    month_ends = pd.Series(days, index=days).groupby(days.to_period("M")).max().tolist()
    weights, fits = {}, {}
    for m in month_ends:
        win = days[(days <= m)][-WIN:]
        if len(win) < WIN:
            continue
        w, r2 = fit_weights(ri.loc[win], rm.loc[win].dropna(axis=1, thresh=int(WIN * 0.8)))
        if len(w):
            weights[m], fits[m] = w, r2
    if not weights:
        return None
    keys = sorted(weights)
    rv_m = rm.rolling(21, min_periods=17).std() * np.sqrt(252)
    rv_i = ri.rolling(21, min_periods=17).std() * np.sqrt(252)
    rows = []
    for d in days:
        k = [m for m in keys if m < d]
        if not k:
            continue
        m = k[-1]
        if fits[m] < 0.95:
            continue
        w = weights[m]
        imp = rho(w, iv_members.loc[d] if d in iv_members.index else pd.Series(dtype=float), iv_index.get(d, np.nan))
        rea = rho(w, rv_m.loc[d], rv_i.get(d, np.nan))
        rows.append((d, imp, rea))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["date", "implied", "realised"]).set_index("date")
    df["realised_next"] = df["realised"].shift(-21)
    df["gap"] = df["implied"] - df["realised_next"]
    last_m = keys[-1]
    w = weights[last_m].sort_values(ascending=False)
    imp_now = df["implied"].dropna()
    g = df["gap"].dropna()
    return {
        "index": index, "asof": str(pd.Timestamp(asof).date()), "fit_r2": fits[last_m], "fit_month": str(last_m.date()),
        "weights": [{"symbol": s, "w": float(x)} for s, x in w[w > 0.001].items()], "weight_sum": float(w.sum()),
        "implied": float(imp_now.iat[-1]) if len(imp_now) and imp_now.index[-1] == days[-1] else None,
        "implied_rank": float(rank_1y(df["implied"]).iat[-1]) if len(imp_now) > 130 and pd.notna(rank_1y(df["implied"]).iat[-1]) else None,
        "realised": float(df["realised"].dropna().iat[-1]) if df["realised"].notna().any() else None,
        "gap_median": float(g.median()) if len(g) > 60 else None, "gap_share_positive": float((g > 0).mean()) if len(g) > 60 else None,
        "n_gap": int(len(g)), "since": str(df.index[0].date()),
        "series": {"date": [str(x.date()) for x in df.index[-500:]],
                   **{c: [None if not np.isfinite(v) else round(float(v), 4) for v in df[c].iloc[-500:]] for c in ("implied", "realised", "realised_next")}},
    }
