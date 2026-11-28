"""MCX's public side (engine/commodities.py): benchmark vol and the import-parity price in the MCX unit."""
import numpy as np
import pandas as pd
import pytest

from marketlens.engine import commodities as C


def _global(n=300):
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2025-09-01", periods=n)
    rows = []
    for tk, p0, vol in (("CL=F", 70.0, 0.35), ("GC=F", 3500.0, 0.15), ("SI=F", 40.0, 0.3), ("HG=F", 5.0, 0.22), ("NG=F", 3.5, 0.6),
                        ("INR=X", 88.0, 0.04), ("^TNX", 4.5, 0.2), ("DX-Y.NYB", 100.0, 0.07)):
        px = p0 * np.exp(np.cumsum(rng.normal(0, vol / np.sqrt(252), n)))
        rows += [dict(date=d, ticker=tk, close=float(x)) for d, x in zip(idx, px)]
    return pd.DataFrame(rows)


def test_import_parity_is_the_benchmark_in_the_mcx_unit():
    g = _global()
    b = C.board(g, g["date"].max())
    last = g[g["date"] == g["date"].max()].set_index("ticker")["close"]
    usd = last["INR=X"]
    assert b["contracts"]["CRUDEOIL"]["parity"] == pytest.approx(last["CL=F"] * usd)                 # Rs a barrel
    assert b["contracts"]["GOLD"]["parity"] == pytest.approx(last["GC=F"] * usd * 10 / 31.1034768)    # Rs per 10 g
    assert b["contracts"]["SILVERM"]["parity"] == pytest.approx(last["SI=F"] * usd * 1000 / 31.1034768)   # Rs a kg
    assert b["contracts"]["COPPER"]["parity"] == pytest.approx(last["HG=F"] * usd * 2.20462262)       # Rs a kg


def test_benchmark_vol_and_the_yield_in_points():
    g = _global()
    b = C.board(g, g["date"].max())
    s = g[g["ticker"] == "CL=F"].set_index("date")["close"]
    rv = np.log(s).diff().iloc[-21:].std() * np.sqrt(252)
    assert b["contracts"]["CRUDEOIL"]["rv21"] == pytest.approx(rv, rel=1e-9)
    tnx = next(m for m in b["macro"] if m["ticker"] == "^TNX")
    y = g[g["ticker"] == "^TNX"].set_index("date")["close"]
    assert tnx["is_yield"] and tnx["chg"] == pytest.approx(y.iat[-1] - y.iat[-2])                     # points, not percent
    assert C.board(pd.DataFrame(), "2026-11-26") == {}
