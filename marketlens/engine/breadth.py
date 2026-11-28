"""The whole F&O market at once: every stock in NSE's F&O list (about 220), not just the app's twenty.

* Vol breadth: each stock's at-the-money straddle implied vol, read from its own option chain, ranked against that
  stock's own past year; then the share of stocks with options unusually dear (80th percentile or more) or cheap
  (20th or less) each day, and the median rank.
* Positioning breadth: each stock's futures day classified by price change x open-interest change on the same
  contracts (positioning.futures_book's rules), and the share of stocks in each class each day. A day a stock's lot
  size changed (a split or bonus: price and OI jump by the ratio) gets no class.
* Sector vol board: realised vol of NSE's sector indices against their own past year.

Read one monthly file at a time (the stock option table is about 24 million rows), so it fits a small machine.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
from scipy.special import ndtri

from . import positioning as P
from .vol import R

MIN_DAYS = 7                 # an expiry closer than this is all gamma: the straddle IV is read from the next one
CLASSES = ("Long build-up", "Short build-up", "Short covering", "Long unwinding")


def straddle_iv(o: pd.DataFrame) -> pd.DataFrame:
    """Per (date, symbol): the at-the-money straddle implied vol of the nearest expiry at least MIN_DAYS out.
    The ATM strike is where call and put, both traded that day, are closest in price; the forward is put-call parity
    there; the vol is the straddle's own, C + P = 2 e^-rT F (2 N(sigma sqrt(T) / 2) - 1), at that forward. Rows: date,
    symbol, expiry, days, F, straddle, iv."""
    o = o[o["kind"].isin(["CE", "PE"]) & (o["contracts"] > 0) & (o["close"] > 0)]
    if o.empty:
        return pd.DataFrame(columns=["date", "symbol", "expiry", "days", "F", "straddle", "iv"])
    days = (o["expiry"] - o["date"]).dt.days
    o = o[days >= MIN_DAYS]
    w = o.pivot_table(index=["date", "symbol", "expiry", "strike"], columns="kind", values="close", aggfunc="last").dropna()
    if w.empty:
        return pd.DataFrame(columns=["date", "symbol", "expiry", "days", "F", "straddle", "iv"])
    w = w.reset_index()
    w["gap"] = (w["CE"] - w["PE"]).abs()
    w = w.sort_values(["date", "symbol", "expiry", "gap"]).drop_duplicates(["date", "symbol", "expiry"])
    w = w.sort_values(["date", "symbol", "expiry"]).drop_duplicates(["date", "symbol"])          # the nearest eligible expiry
    w["days"] = (w["expiry"] - w["date"]).dt.days
    T = w["days"] / 365.0
    w["F"] = w["strike"] + np.exp(R * T) * (w["CE"] - w["PE"])
    w["straddle"] = w["CE"] + w["PE"]
    q = (w["straddle"] / (2 * np.exp(-R * T) * w["F"]) + 1) / 2
    w["iv"] = np.where(q.between(0.5, 0.9999), 2 * ndtri(q.clip(0.5, 0.9999)) / np.sqrt(T), np.nan)
    ok = ((w["strike"] / w["F"] - 1).abs() <= 0.03) & w["iv"].between(0.03, 3.0)
    return w.loc[ok, ["date", "symbol", "expiry", "days", "F", "straddle", "iv"]].reset_index(drop=True)


def buildups(f: pd.DataFrame) -> pd.DataFrame:
    """positioning.futures_book's daily class for every stock at once (the same rules, vectorised; tests check the two
    agree day by day): price change of the near contract against its own close the session before; OI change over the
    contracts listed on both days, the one expiring that day included; a book under MIN_FUT_CONTRACTS lots the day
    before is a thin market; a day the lot size changed (split, bonus) gets no class."""
    f = f.copy()
    f["px"] = np.where(f["close"] > 0, f["close"], f["settle"])
    f_all = f[f["expiry"] >= f["date"]]
    live = f[f["expiry"] > f["date"]]
    near = live.sort_values(["symbol", "date", "expiry"]).drop_duplicates(["symbol", "date"])[["symbol", "date", "expiry", "px"]]
    near = near.sort_values(["symbol", "date"])
    near["prev"] = near.groupby("symbol")["date"].shift()
    near = near.dropna(subset=["prev"])
    px0 = f[["symbol", "date", "expiry", "px"]].rename(columns={"date": "prev", "px": "px0"})
    near = near.merge(px0, on=["symbol", "prev", "expiry"], how="left")
    near["d_price"] = np.where(near["px0"] > 0, near["px"] / near["px0"] - 1, np.nan)
    oi = f_all.groupby(["symbol", "date", "expiry"])["oi"].sum().reset_index()
    pair = near[["symbol", "date", "prev"]].merge(oi, on=["symbol", "date"]).merge(
        oi.rename(columns={"date": "prev", "oi": "oi0"}), on=["symbol", "prev", "expiry"])          # listed on both days
    s_ = pair.groupby(["symbol", "date"])[["oi", "oi0"]].sum().reset_index()
    near = near.merge(s_, on=["symbol", "date"], how="left")
    near["d_oi"] = np.where(near["oi0"] > 0, near["oi"] / near["oi0"] - 1, np.nan)
    lot = f_all.groupby(["symbol", "date"])["lot"].median().rename("lot0").reset_index().rename(columns={"date": "prev"})
    near = near.merge(lot, on=["symbol", "prev"], how="left")
    lot_now = f_all.groupby(["symbol", "date"])["lot"].median().rename("lot1").reset_index()
    near = near.merge(lot_now, on=["symbol", "date"], how="left")
    d_p, d_o = near["d_price"], near["d_oi"]
    near["buildup"] = np.select([(d_p > 0) & (d_o > 0), (d_p < 0) & (d_o > 0), (d_p > 0) & (d_o < 0), (d_p < 0) & (d_o < 0)],
                                list(CLASSES), default="Flat")
    near.loc[d_p.isna() | d_o.isna(), "buildup"] = "No read"
    thin = (near["lot0"] > 0) & (near["oi0"].fillna(0) / near["lot0"] < P.MIN_FUT_CONTRACTS)
    near.loc[thin, "buildup"] = "Thin market"
    split = near["lot0"].notna() & near["lot1"].notna() & (near["lot0"] != near["lot1"])
    near.loc[split, "buildup"] = "Corporate action"
    return near[["date", "symbol", "buildup", "d_price", "d_oi"]].reset_index(drop=True)


def rank_1y(s: pd.Series, n: int = 252, min_n: int = 126) -> pd.Series:
    """Each day's value against the n readings before it: the share below (positioning.latest_pct's convention)."""
    a = s.to_numpy(dtype=float)
    out = np.full(len(a), np.nan)
    if len(a) < 2:
        return pd.Series(out, index=s.index)
    pad = np.concatenate([np.full(n, np.nan), a])
    win = np.lib.stride_tricks.sliding_window_view(pad[:-1], n)          # row i: the n readings before a[i]
    valid = np.isfinite(win)
    cnt = valid.sum(axis=1)
    below = (np.where(valid, win, np.inf) < a[:, None]).sum(axis=1)
    ok = np.isfinite(a) & (cnt >= min_n)
    out[ok] = below[ok] / cnt[ok]
    return pd.Series(out, index=s.index)


def read_monthly(root: Path, table: str = "fo_stock_opts"):
    files = sorted(p for p in Path(root).glob(f"{table}_*.parquet") if p.stem[len(table) + 1:][:1].isdigit())
    cols = ["date", "symbol", "kind", "expiry", "strike", "close", "settle", "contracts", "oi", "lot"]
    for f in files:
        d = ds.dataset(str(f))
        t = d.to_table(columns=[c for c in cols if c in d.schema.names]).to_pandas()
        for c in ("date", "expiry"):
            t[c] = pd.to_datetime(t[c]).dt.normalize()
        yield t


def market(root: Path, asof) -> dict:
    """Vol and positioning breadth over every F&O stock, daily history and today's reading."""
    ivs, futs = [], []
    for t in read_monthly(root):
        ivs.append(straddle_iv(t))
        futs.append(t[t["kind"] == "FUT"][["date", "symbol", "kind", "expiry", "close", "settle", "oi", "contracts", "lot"]])
    if not ivs:
        return {}
    iv = pd.concat(ivs, ignore_index=True)
    iv = iv[iv["date"] <= pd.Timestamp(asof)].sort_values(["symbol", "date"])
    iv["rank"] = iv.groupby("symbol", group_keys=False)["iv"].apply(rank_1y)
    g = iv.dropna(subset=["rank"]).groupby("date")
    vb = pd.DataFrame({"n": g.size(), "dear": g["rank"].apply(lambda r: (r >= 0.8).mean()),
                       "cheap": g["rank"].apply(lambda r: (r <= 0.2).mean()), "median_rank": g["rank"].median(),
                       "median_iv": g.apply(lambda x: x["iv"].median(), include_groups=False)})
    vb = vb[vb["n"] >= 50]                                   # a day with too few readable stocks is not the market's

    f = pd.concat(futs, ignore_index=True)
    f = f[f["date"] <= pd.Timestamp(asof)]
    bu = buildups(f)
    cls = bu[bu["buildup"].isin(CLASSES)]
    pb = cls.groupby(["date", "buildup"]).size().unstack("buildup").reindex(columns=list(CLASSES)).fillna(0)
    pb = pb.div(pb.sum(axis=1), axis=0)
    pb["n"] = cls.groupby("date").size()
    pb = pb[pb["n"] >= 50]

    last = pd.Timestamp(asof)
    today_iv = iv[iv["date"] == last].dropna(subset=["rank"]).sort_values("rank")
    today_bu = bu[bu["date"] == last]
    return {
        "vol": {"date": [str(d.date()) for d in vb.index], "dear": vb["dear"].round(4).tolist(), "cheap": vb["cheap"].round(4).tolist(),
                "median_rank": vb["median_rank"].round(4).tolist(), "median_iv": vb["median_iv"].round(4).tolist(), "n": vb["n"].astype(int).tolist()},
        "positions": {"date": [str(d.date()) for d in pb.index], **{c: pb[c].round(4).tolist() for c in CLASSES}, "n": pb["n"].astype(int).tolist()},
        "today": {
            "dearest": [{"symbol": r.symbol, "iv": r.iv, "rank": r.rank} for r in today_iv.tail(10).iloc[::-1].itertuples()],
            "cheapest": [{"symbol": r.symbol, "iv": r.iv, "rank": r.rank} for r in today_iv.head(10).itertuples()],
            "buildups": {c: sorted(today_bu[today_bu["buildup"] == c]["symbol"].tolist()) for c in CLASSES},
            "n_iv": int(len(today_iv)), "n_fut": int(len(today_bu)),
        },
    }


SECTORS = {"Nifty Bank": "Banks", "Nifty IT": "IT", "Nifty Pharma": "Pharma", "Nifty Auto": "Autos", "Nifty FMCG": "FMCG",
           "Nifty Metal": "Metals", "Nifty Energy": "Energy", "Nifty Realty": "Realty", "Nifty Financial Services": "Financials",
           "Nifty PSU Bank": "PSU banks", "Nifty Private Bank": "Private banks", "Nifty Media": "Media", "Nifty Infrastructure": "Infrastructure",
           "Nifty Oil & Gas": "Oil & gas", "Nifty Healthcare Index": "Healthcare", "Nifty Consumer Durables": "Consumer durables",
           "Nifty Capital Markets": "Capital markets", "Nifty Commodities": "Commodities", "Nifty Financial Services Ex-Bank": "NBFCs",
           "Nifty Capital Goods": "Capital goods", "Nifty India Digital": "Digital"}


def sector_board(idx: pd.DataFrame, asof) -> list[dict]:
    """Realised vol of each sector index (21 days, annualised), its rank against the index's own past year, and its
    5-day against 63-day vol (above 1: the sector has woken up)."""
    out = []
    for name, label in SECTORS.items():
        s = idx[idx["index"] == name].drop_duplicates("date", keep="last").set_index("date")["close"].sort_index()
        s = s[s.index <= pd.Timestamp(asof)]
        r = np.log(s).diff()
        if r.notna().sum() < 300:
            continue
        rv21, rv5, rv63 = (r.rolling(n).std() * np.sqrt(252) for n in (21, 5, 63))
        rk = rank_1y(rv21.iloc[-260:]).iloc[-1]
        out.append({"sector": label, "index": name, "rv21": float(rv21.iat[-1]), "rank": None if not np.isfinite(rk) else float(rk),
                    "wake": float(rv5.iat[-1] / rv63.iat[-1]) if rv63.iat[-1] > 0 else None, "since": str(s.index[0].date()),
                    "rv21_1y": [None if not np.isfinite(x) else round(float(x), 4) for x in rv21.iloc[-252:]]})
    return sorted(out, key=lambda x: -(x["rank"] if x["rank"] is not None else -1))
