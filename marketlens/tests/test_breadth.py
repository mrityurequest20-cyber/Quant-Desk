"""Market-wide breadth (engine/breadth.py) and a stock's link to the market (engine/linkage.py)."""
import numpy as np
import pandas as pd
import pytest

from marketlens.engine import breadth as B
from marketlens.engine import linkage as LK
from marketlens.engine import positioning as P
from marketlens.engine import vol as V
from marketlens.tests.test_live import _chain


def test_straddle_iv_is_the_engines_straddle_vol_on_the_first_expiry_a_week_out():
    day = pd.Timestamp("2026-11-26")
    df = _chain(day, 1000.0, {pd.Timestamp("2026-11-30"): 0.3, pd.Timestamp("2026-12-29"): 0.2, pd.Timestamp("2027-01-25"): 0.22})
    b = B.straddle_iv(df)
    assert len(b) == 1 and b["expiry"].iat[0] == pd.Timestamp("2026-12-29")          # 30 Nov is 4 days out: skipped
    t, _ = V.expiry_table(df)
    want = t[t["expiry"] == pd.Timestamp("2026-12-29")]["straddle_iv"].iat[0]
    assert b["iv"].iat[0] == pytest.approx(want, rel=1e-12) and b["iv"].iat[0] == pytest.approx(0.2, abs=0.01)


def test_rank_1y_is_the_share_of_the_previous_readings_below():
    s = pd.Series(np.random.default_rng(0).normal(size=600))
    s.iloc[::13] = np.nan
    a = s.to_numpy()
    want = []
    for i in range(len(a)):
        h = a[max(0, i - 252):i]
        h = h[np.isfinite(h)]
        want.append((h < a[i]).mean() if np.isfinite(a[i]) and len(h) >= 126 else np.nan)
    assert np.allclose(B.rank_1y(s).to_numpy(), np.array(want), equal_nan=True)


def _futures(n=40, split_day=25, seed=0):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2026-01-01", periods=n)
    rows, px = [], 100.0
    for i, d in enumerate(days):
        px *= np.exp(rng.normal(0, 0.01))
        lot = 500.0 if i < split_day else 1000.0
        f = 1.0 if i < split_day else 0.5
        for k, e in enumerate([pd.Timestamp("2026-01-29"), pd.Timestamp("2026-02-26"), pd.Timestamp("2026-03-26")]):
            if e < d:
                continue
            rows.append(dict(date=d, symbol="X", kind="FUT", expiry=e, strike=np.nan, close=px * f * (1 + 0.005 * k), settle=px * f * (1 + 0.005 * k),
                             oi=float(rng.integers(400_000, 900_000)) / f, contracts=1000.0, lot=lot))
    return pd.DataFrame(rows)


def test_vectorised_buildups_match_the_instrument_pages_day_by_day():
    f = _futures()
    ref = P.futures_book(f, pd.Series(dtype=float))
    v = B.buildups(f).set_index("date")
    j = ref[["buildup"]].join(v[["buildup"]], rsuffix="_v", how="inner")
    split = j["buildup_v"] == "Corporate action"
    assert split.sum() == 1 and j.index[split][0] == pd.bdate_range("2026-01-01", periods=40)[25]     # the lot changed
    assert (j.loc[~split, "buildup"] == j.loc[~split, "buildup_v"]).all() and len(j) >= 38


def test_own_share_is_one_minus_the_r_squared():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2024-01-01", periods=400)
    n = rng.normal(0, 0.01, 400)
    k = 0.8 * n + rng.normal(0, 0.006, 400)                 # the sector: mostly the market
    own = rng.normal(0, 0.012, 400)
    s = 1.3 * n + 0.5 * (k - 0.8 * n) + own
    px = lambda r: pd.Series(100 * np.exp(np.cumsum(r)), idx)
    out = LK.rolling(px(s), px(n), px(k)).iloc[-1]
    # by direct least squares on the same 63 days
    r = pd.DataFrame({"s": s, "n": n, "k": k}, index=idx).iloc[-63:]
    X = np.column_stack([np.ones(63), r["n"], r["k"]])
    beta, *_ = np.linalg.lstsq(X, r["s"], rcond=None)
    res = r["s"] - X @ beta
    r2 = 1 - (res ** 2).sum() / ((r["s"] - r["s"].mean()) ** 2).sum()
    assert out["r2"] == pytest.approx(r2, rel=1e-9) and out["own"] == pytest.approx(1 - r2, rel=1e-9)
    assert out["beta_n"] == pytest.approx(np.polyfit(r["n"], r["s"], 1)[0], rel=1e-9)
