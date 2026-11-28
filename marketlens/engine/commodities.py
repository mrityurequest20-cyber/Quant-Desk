"""MCX commodities, from what can be published.

MCX's own files refuse automated reads (403 from GitHub's runners too), and the live MCX prices the desk receives are
licensed broker data that must not be published. So the public side reads the international benchmark each MCX
contract tracks (global_daily: WTI, Henry Hub, COMEX gold, silver and copper, with USDINR), and the live side, in the
browser with the owner's key only, reads the MCX futures and options the relay carries (web/live-ui.js).

For each commodity: the benchmark's realised vol (21 days) and its rank against the past year, the volatility cone,
and the benchmark converted into the MCX contract's own unit in rupees (the import-parity price, before duties and
local premiums). The live page sets the MCX future against it: MCX over parity is the local premium.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .breadth import rank_1y

OZ_G = 31.1034768
# MCX contract: (benchmark ticker, benchmark unit, MCX unit, factor from one benchmark unit, in USD, to one MCX unit)
CONTRACTS = {
    "CRUDEOIL": ("CL=F", "$/barrel", "Rs/barrel", 1.0),
    "CRUDEOILM": ("CL=F", "$/barrel", "Rs/barrel", 1.0),
    "NATURALGAS": ("NG=F", "$/mmBtu", "Rs/mmBtu", 1.0),
    "NATGASMINI": ("NG=F", "$/mmBtu", "Rs/mmBtu", 1.0),
    "GOLD": ("GC=F", "$/troy oz", "Rs/10 g", 10 / OZ_G),
    "GOLDM": ("GC=F", "$/troy oz", "Rs/10 g", 10 / OZ_G),
    "SILVER": ("SI=F", "$/troy oz", "Rs/kg", 1000 / OZ_G),
    "SILVERM": ("SI=F", "$/troy oz", "Rs/kg", 1000 / OZ_G),
    "COPPER": ("HG=F", "$/lb", "Rs/kg", 2.20462262),
}
MACRO = {"INR=X": "USDINR", "DX-Y.NYB": "Dollar index", "^TNX": "US 10-year yield", "^VIX": "CBOE VIX", "ES=F": "S&P 500 futures",
         "BZ=F": "Brent crude"}


def closes(g: pd.DataFrame) -> pd.DataFrame:
    """date x ticker closes from global_daily."""
    if g is None or g.empty:
        return pd.DataFrame()
    c = g.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index()
    c.index = pd.to_datetime(c.index)
    return c


def board(g: pd.DataFrame, asof) -> dict:
    """The public commodities block: per MCX contract, its benchmark's vol, cone and import parity; plus the macro board."""
    c = closes(g)
    if c.empty:
        return {}
    c = c[c.index <= pd.Timestamp(asof)]
    usd = c["INR=X"].ffill() if "INR=X" in c else None
    out = {"asof": str(c.index[-1].date()), "contracts": {}, "macro": [], "source": "Yahoo Finance (global_daily)"}
    seen = {}
    for mcx, (tk, bu, mu, f) in CONTRACTS.items():
        if tk not in c:
            continue
        if tk not in seen:
            s = c[tk].dropna()
            r = np.log(s).diff()
            rv = {w: r.rolling(w, min_periods=int(w * 0.8)).std() * np.sqrt(252) for w in (5, 10, 21, 63, 126, 252)}
            cone = []
            for w, x in rv.items():
                x = x.dropna()
                if len(x) > 60:
                    cone.append({"window": w, "p10": float(x.quantile(.1)), "p50": float(x.median()), "p90": float(x.quantile(.9)),
                                 "now": float(x.iat[-1]), "pct": float((x < x.iat[-1]).mean())})
            rk = rank_1y(rv[21])
            seen[tk] = {"ticker": tk, "close": float(s.iat[-1]), "date": str(s.index[-1].date()), "chg": float(np.expm1(r.iat[-1])),
                        "rv21": float(rv[21].iat[-1]), "rv21_rank": None if pd.isna(rk.iat[-1]) else float(rk.iat[-1]), "cone": cone,
                        "since": str(s.index[0].date()),
                        "rv21_1y": {"date": [str(d.date()) for d in rv[21].index[-252:]], "v": [None if not np.isfinite(v) else round(float(v), 4) for v in rv[21].iloc[-252:]]}}
        b = seen[tk]
        parity = None
        if usd is not None and pd.notna(usd.iloc[-1]):
            parity = b["close"] * f * float(usd.iloc[-1])
        out["contracts"][mcx] = {**{k: v for k, v in b.items() if k not in ("cone", "rv21_1y")}, "benchmark_unit": bu, "mcx_unit": mu,
                                 "factor": f, "usdinr": float(usd.iloc[-1]) if usd is not None else None, "parity": parity,
                                 "cone": b["cone"], "rv21_1y": b["rv21_1y"]}
    for tk, name in MACRO.items():
        if tk not in c:
            continue
        s = c[tk].dropna()
        if len(s) < 30:
            continue
        r = np.log(s).diff() if tk != "^TNX" else s.diff() / 100              # a yield moves in points, not percent
        rv = r.rolling(21, min_periods=17).std() * np.sqrt(252)
        rk = rank_1y(rv)
        out["macro"].append({"ticker": tk, "name": name, "close": float(s.iat[-1]), "date": str(s.index[-1].date()),
                             "chg": float(s.iat[-1] - s.iat[-2]) if tk == "^TNX" else float(s.iat[-1] / s.iat[-2] - 1),
                             "rv21": float(rv.iat[-1]) if pd.notna(rv.iat[-1]) else None,
                             "rv21_rank": None if pd.isna(rk.iat[-1]) else float(rk.iat[-1]), "is_yield": tk == "^TNX"})
    return out
