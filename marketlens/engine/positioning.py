"""Positioning from open interest: strike walls, put/call ratios, the futures book (basis, carry, build-up, rollover),
and the participant books (FII / DII / Pro / Client).

None of this is read as a direction. Open interest says where positions sit and how they are changing, not who is
right: every contract has a buyer and a seller. What it does say well is where the crowd is concentrated, how
crowded it is against its own history, and how much is being rolled or closed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def pct_rank(x: pd.Series, window: int | None = None) -> pd.Series:
    """Percentile of each value against the values before it (and itself): 0 = lowest ever, 1 = highest."""
    x = x.astype(float)
    if window:
        return x.rolling(window, min_periods=max(20, window // 4)).apply(lambda a: (a[:-1] < a[-1]).mean() if len(a) > 1 else np.nan, raw=True)
    vals = x.values
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if i >= 20 and np.isfinite(vals[i]):
            prev = vals[:i][np.isfinite(vals[:i])]
            out[i] = (prev < vals[i]).mean()
    return pd.Series(out, index=x.index)


def latest_pct(x: pd.Series, window: int | None = None) -> float | None:
    x = x.dropna()
    if len(x) < 21:
        return None
    h = x.iloc[-window - 1:-1] if window else x.iloc[:-1]
    return float((h < x.iat[-1]).mean())


# ---------------- options open interest ----------------

def strike_profile(opt: pd.DataFrame, asof, spot: float, n_expiries: int = 2, band: float = 0.12) -> list[dict]:
    """Calls and puts open interest and its change by strike, for the nearest expiries, within +-band of spot."""
    o = opt[(opt["date"] == asof) & opt["kind"].isin(["CE", "PE"]) & (opt["expiry"] > asof)]   # a contract settling
    exps = sorted(o["expiry"].unique())[:n_expiries]                                              # today has no walls
    out = []
    for e in exps:
        g = o[(o["expiry"] == e) & (o["strike"].between(spot * (1 - band), spot * (1 + band)))]
        pv = g.pivot_table(index="strike", columns="kind", values=["oi", "chg_oi", "contracts"], aggfunc="sum").fillna(0)
        if pv.empty:
            continue
        pv.columns = [f"{a}_{b}" for a, b in pv.columns]
        for c in ("oi_CE", "oi_PE", "chg_oi_CE", "chg_oi_PE", "contracts_CE", "contracts_PE"):
            if c not in pv:
                pv[c] = 0.0
        pv = pv.reset_index()
        calls_above = pv[pv["strike"] >= spot]
        puts_below = pv[pv["strike"] <= spot]
        wall_c = calls_above.loc[calls_above["oi_CE"].idxmax(), "strike"] if len(calls_above) and calls_above["oi_CE"].max() > 0 else None
        wall_p = puts_below.loc[puts_below["oi_PE"].idxmax(), "strike"] if len(puts_below) and puts_below["oi_PE"].max() > 0 else None
        tot_c, tot_p = pv["oi_CE"].sum(), pv["oi_PE"].sum()
        out.append({
            "expiry": str(pd.Timestamp(e).date()),
            "days": int((pd.Timestamp(e) - pd.Timestamp(asof)).days),
            "strikes": pv["strike"].tolist(),
            "call_oi": pv["oi_CE"].tolist(), "put_oi": pv["oi_PE"].tolist(),
            "call_chg": pv["chg_oi_CE"].tolist(), "put_chg": pv["chg_oi_PE"].tolist(),
            "call_wall": wall_c, "put_wall": wall_p,
            "pcr": float(tot_p / tot_c) if tot_c > 0 else None,
            "call_add": float(pv["chg_oi_CE"].sum()), "put_add": float(pv["chg_oi_PE"].sum()),
        })
    return out


def pcr_history(opt: pd.DataFrame) -> pd.DataFrame:
    """Put/call ratio of open interest (all expiries) and of the day's traded contracts, daily."""
    o = opt[opt["kind"].isin(["CE", "PE"])]
    g = o.groupby(["date", "kind"])[["oi", "contracts"]].sum().unstack("kind")
    out = pd.DataFrame(index=g.index)
    out["pcr_oi"] = g[("oi", "PE")] / g[("oi", "CE")]
    out["pcr_vol"] = g[("contracts", "PE")] / g[("contracts", "CE")]
    out["opt_oi"] = g[("oi", "PE")] + g[("oi", "CE")]
    out["opt_contracts"] = g[("contracts", "PE")] + g[("contracts", "CE")]
    return out.replace([np.inf, -np.inf], np.nan)


# ---------------- futures ----------------

def futures_book(opt: pd.DataFrame, spot: pd.Series) -> pd.DataFrame:
    """Daily: near-month future price, basis, annualised carry, total futures OI, roll share, and the build-up class.

    Changes are measured on the same contracts across the two days, so an expiry never shows up as a market move:
    the price change is today's near contract against its own price yesterday (not against yesterday's expired near
    month, which would add a month's carry), and the OI change compares the contracts alive on both days (an expiring
    month's OI leaving the total is not unwinding). Every session gets a real read, the day after expiry included."""
    f = opt[opt["kind"] == "FUT"].copy()
    if f.empty:
        return pd.DataFrame()
    f["px"] = np.where(f["close"] > 0, f["close"], f["settle"])
    # OI changes count every contract the file carries, the one expiring that day included: NSE reports its open
    # interest at the close, so positions rolled out of it into the next month net out instead of looking like fresh
    # money (Reliance's expiry day, 23 Nov 2026, showed +14.9% the other way)
    f_all = f[f["expiry"] >= f["date"]]
    f = f[f["expiry"] > f["date"]].sort_values(["date", "expiry"])   # a contract settling today is not tradable next
                                                                        # session, and its 1-day carry is noise
    f["n"] = f.groupby("date").cumcount()
    near = f[f["n"] == 0].set_index("date")
    nxt = f[f["n"] == 1].set_index("date")
    tot = f.groupby("date")["oi"].sum()
    out = pd.DataFrame(index=near.index)
    out["fut"] = near["px"]
    out["fut_expiry"] = near["expiry"]
    out["spot"] = spot.reindex(out.index)
    out["days"] = (near["expiry"] - near.index.to_series()).dt.days
    # basis and carry use NSE's settlement price: like the official spot close, it is an average of the last 30 minutes,
    # so the two are measured at the same moment (a last-traded price can be minutes away from the spot's close).
    # Carry is read from the first contract at least 20 days out: annualising a short basis turns a few points of noise
    # into -40% (Reliance, 20 Nov 2026, 3 days out). Measured on 2025-26: at 20 days NIFTY's carry moves more than
    # 5 points in a day 8 times in 469 sessions, against 50 at 7 days. Near expiry it therefore comes from next month.
    st = f.assign(stl=np.where(f["settle"] > 0, f["settle"], f["px"]))
    st["dte"] = (st["expiry"] - st["date"]).dt.days
    near_stl = st[st["n"] == 0].set_index("date")["stl"]
    cm = st[st["dte"] >= 20].sort_values(["date", "expiry"]).drop_duplicates("date").set_index("date")
    out["basis"] = near_stl.reindex(out.index) - out["spot"]
    out["carry"] = np.log(cm["stl"] / out["spot"].reindex(cm.index)).reindex(out.index) / (cm["dte"].reindex(out.index) / 365)
    out["fut_oi"] = tot
    out["near_oi"] = near["oi"]
    out["next_oi"] = nxt["oi"].reindex(out.index)
    out["roll_share"] = out["next_oi"] / (out["near_oi"] + out["next_oi"])
    out["fut_contracts"] = f.groupby("date")["contracts"].sum()

    px = f.pivot_table(index="date", columns="expiry", values="px", aggfunc="last")
    oi = f_all.pivot_table(index="date", columns="expiry", values="oi", aggfunc="sum")
    days = list(out.index)
    dp, doi = [np.nan], [np.nan]
    for prev, cur in zip(days, days[1:]):
        e = out.at[cur, "fut_expiry"]
        a0 = px.at[prev, e] if e in px.columns else np.nan
        dp.append(out.at[cur, "fut"] / a0 - 1 if np.isfinite(a0) and a0 > 0 else np.nan)
        both = oi.loc[[prev, cur]].dropna(axis=1).columns          # contracts listed on both days
        o0, o1 = oi.loc[prev, both].sum(), oi.loc[cur, both].sum()
        doi.append(o1 / o0 - 1 if o0 > 0 else np.nan)
    out["d_price"] = dp
    out["d_oi"] = doi
    d_p, d_o = out["d_price"], out["d_oi"]
    out["buildup"] = np.select(
        [(d_p > 0) & (d_o > 0), (d_p < 0) & (d_o > 0), (d_p > 0) & (d_o < 0), (d_p < 0) & (d_o < 0)],
        ["Long build-up", "Short build-up", "Short covering", "Long unwinding"], default="Flat")
    out.loc[d_p.isna() | d_o.isna(), "buildup"] = "No read"
    return out


def roll_history(book: pd.DataFrame) -> list[dict]:
    """At each monthly expiry: the roll share on the day before expiry, and the carry paid to roll."""
    if book.empty:
        return []
    b = book.dropna(subset=["roll_share"])
    out = []
    for e, g in b.groupby("fut_expiry"):
        if pd.Timestamp(e) > b.index.max():            # the current month has not reached its roll day yet
            continue
        g = g[g.index < e]
        if g.empty:
            continue
        last = g.iloc[-1]
        out.append({"expiry": str(pd.Timestamp(e).date()), "roll_share": float(last["roll_share"]),
                    "carry": float(last["carry"]) if np.isfinite(last["carry"]) else None})
    return out[-36:]


# ---------------- participants ----------------

PARTS = ("FII", "DII", "Pro", "Client")


def participant_books(poi: pd.DataFrame) -> pd.DataFrame:
    """Wide daily frame of each participant's net positions (contracts) by product, and their long shares."""
    p = poi.copy()
    p["participant"] = p["participant"].astype(str)
    p = p[p["participant"].isin(PARTS)]
    p["idx_fut_net"] = p["fut_idx_long"] - p["fut_idx_short"]
    p["idx_fut_long_share"] = p["fut_idx_long"] / (p["fut_idx_long"] + p["fut_idx_short"])
    p["stk_fut_net"] = p["fut_stk_long"] - p["fut_stk_short"]
    p["idx_call_net"] = p["opt_idx_call_long"] - p["opt_idx_call_short"]
    p["idx_put_net"] = p["opt_idx_put_long"] - p["opt_idx_put_short"]
    # option "delta-ish" stance: long calls and short puts both gain on a rise
    p["idx_opt_stance"] = p["idx_call_net"] - p["idx_put_net"]
    cols = ["idx_fut_net", "idx_fut_long_share", "stk_fut_net", "idx_call_net", "idx_put_net", "idx_opt_stance",
            "fut_idx_long", "fut_idx_short"]
    w = p.pivot_table(index="date", columns="participant", values=cols)
    w.columns = [f"{a}:{b}" for a, b in w.columns]       # (value, participant) -> "metric:who"
    return w.sort_index()
