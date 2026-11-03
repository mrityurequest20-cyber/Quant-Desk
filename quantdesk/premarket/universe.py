"""Every F&O underlying, from the bhavcopy: no list to maintain, no cap.

The warehouse's `fo_stock_opts` (every F&O stock's options and futures, daily) and `fo_bhav` (every index's) say
which instruments exist on a session, at what price, with what lot and strike step, and how much their options
traded. A stock that enters or leaves the F&O segment appears or disappears here by itself.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ACTIVE_CONTRACTS = 100            # a strike counts as active when it traded at least this many contracts


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d["expiry"] = pd.to_datetime(d["expiry"])
    return d


def spot(g: pd.DataFrame) -> float:
    """The underlying's price on one symbol-session: the bhavcopy's underlying column, else the nearest future's close."""
    u = pd.to_numeric(g.get("underlying"), errors="coerce").dropna() if "underlying" in g else pd.Series(dtype=float)
    u = u[u > 0]
    if len(u):
        return float(u.iloc[0])
    f = g[(g["kind"] == "FUT") & (g["close"] > 0)].sort_values("expiry")
    return float(f["close"].iloc[0]) if len(f) else float("nan")


def strike_step(strikes, price: float) -> float:
    """The commonest gap between listed strikes within 10% of the price."""
    k = np.unique(np.asarray([s for s in strikes if s == s], dtype=float))
    if price == price and price > 0:
        near = k[np.abs(k / price - 1) <= 0.10]
        k = near if len(near) >= 3 else k
    gaps = np.diff(k)
    gaps = gaps[gaps > 0]
    if not len(gaps):
        return float("nan")
    vals, counts = np.unique(np.round(gaps, 4), return_counts=True)
    return float(vals[np.argmax(counts)])


def _one(sym: str, segment: str, g: pd.DataFrame, day: pd.Timestamp) -> dict:
    price = spot(g)
    fut = g[g["kind"] == "FUT"].sort_values("expiry")
    opt = g[g["kind"].isin(["CE", "PE"]) & (g["expiry"] >= day)]
    near = opt["expiry"].min() if len(opt) else pd.NaT
    o = opt[opt["expiry"] == near]
    lot = pd.to_numeric(g.get("lot"), errors="coerce").dropna()
    lot = float(lot.iloc[0]) if len(lot) else float("nan")
    contracts = pd.to_numeric(o["contracts"], errors="coerce").fillna(0)
    premium = float((o["close"].clip(lower=0) * contracts).sum() * lot) if lot == lot else float("nan")
    active = o[contracts >= ACTIVE_CONTRACTS]["strike"].nunique()
    f0 = fut.iloc[0] if len(fut) else None
    oi = float(f0["oi"]) if f0 is not None and f0["oi"] == f0["oi"] else float("nan")
    chg = float(f0["chg_oi"]) if f0 is not None and f0["chg_oi"] == f0["chg_oi"] else float("nan")
    prev = oi - chg if oi == oi and chg == chg else float("nan")
    return {"symbol": sym, "segment": segment, "date": day.date().isoformat(), "price": price, "lot": lot,
            "strike_step": strike_step(o["strike"] if len(o) else opt["strike"], price),
            "near_expiry": near.date().isoformat() if near == near else None,
            "opt_contracts": float(contracts.sum()), "opt_premium_cr": premium / 1e7 if premium == premium else float("nan"),
            "active_strikes": int(active), "fut_oi": oi, "fut_oi_chg_pct": chg / prev if prev and prev == prev and prev > 0 else float("nan"),
            "fut_close": float(f0["close"]) if f0 is not None else float("nan"),
            "fut_prev_close": float(f0["prev_close"]) if f0 is not None and "prev_close" in f0 else float("nan")}


def fo_universe(stock_opts: pd.DataFrame | None, index_bhav: pd.DataFrame | None = None, day=None) -> pd.DataFrame:
    """One row per F&O underlying on `day` (default: each table's latest session), indices first, then stocks by
    how much option premium traded. `liq_rank` is the percentile of option contracts traded within the segment."""
    rows = []
    for segment, df in (("index", index_bhav), ("stock", stock_opts)):
        if df is None or len(df) == 0:
            continue
        d = _prep(df)
        on = pd.Timestamp(day) if day is not None else d["date"].max()
        d = d[d["date"] == on]
        for sym, g in d.groupby("symbol", sort=True):
            rows.append(_one(str(sym), segment, g, on))
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["liq_rank"] = out.groupby("segment")["opt_contracts"].rank(pct=True)
    out["segment_order"] = out["segment"].map({"index": 0, "stock": 1})
    return (out.sort_values(["segment_order", "opt_contracts"], ascending=[True, False])
               .drop(columns="segment_order").reset_index(drop=True))
