"""Edge research must find a planted edge, refuse noise, and control false discoveries."""
import numpy as np
import pandas as pd

from quantdesk.research.edges import benjamini_hochberg, daily_tests, hac_mean, hourly_tests, m5_tests, run


def test_hac_and_bh():
    rng = np.random.default_rng(0)
    m, t, p = hac_mean(rng.normal(0.001, 0.01, 4000))
    assert m > 0 and t > 3 and p < 0.01
    ma = np.convolve(rng.normal(0.1, 1, 20002), [1, 1, 1], "valid")         # MA(2): long-run variance 3× the variance
    m2, t2, _ = hac_mean(ma, lags=8)
    naive_se = ma.std() / np.sqrt(len(ma))
    assert 1.5 < (m2 / t2) / naive_se < 1.9                                 # HAC widens the SE by ≈ √3
    ps = [0.001, 0.004, 0.03, 0.2, 0.5, 0.9]
    assert benjamini_hochberg(ps, 0.10) == [True, True, True, False, False, False]
    assert benjamini_hochberg([0.2, 0.4], 0.10) == [False, False]


def _daily(n=2500, seed=1, gap_follow=0.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-01", periods=n, tz="Asia/Kolkata")
    gap = rng.normal(0, 0.005, n)
    r_oc = rng.normal(0, 0.009, n) + gap_follow * gap
    close = 10000 * np.exp(np.cumsum(gap + r_oc))
    open_ = close / np.exp(r_oc)
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.003, "low": np.minimum(open_, close) * 0.997,
                         "close": close}, index=idx)


def test_finds_a_planted_edge_and_refuses_noise():
    noise = daily_tests("NIFTY", _daily(seed=2), None)
    edge = daily_tests("NIFTY", _daily(seed=2, gap_follow=0.8), None)
    d2_noise = next(r for r in noise if r.id == "D2")
    d2_edge = next(r for r in edge if r.id == "D2")
    assert d2_edge.t > 5 and d2_edge.p < 1e-4 and d2_edge.effect_bps > 0 and d2_edge.p_holdout < 0.05
    assert abs(d2_noise.t) < 3
    data = {"daily": {"NIFTY": _daily(seed=2, gap_follow=0.8)}, "hourly": {}, "m5": {}}
    res = {r.id: r for r in run(data, symbols=("NIFTY",))}
    assert res["D2"].verdict == "EDGE" and res["D2"].bh_pass
    assert res["D4"].verdict == "NO EDGE"                                    # Tuesdays: nothing planted, nothing found


def test_hourly_and_5m_shapes_run():
    rng = np.random.default_rng(3)
    days = pd.bdate_range("2025-01-01", periods=120, tz="Asia/Kolkata")
    rows_h, rows_m = [], []
    for d in days:
        t0 = d + pd.Timedelta(hours=9, minutes=15)
        px = 20000 * np.exp(rng.normal(0, 0.01))
        for k, freq, n in ((rows_h, "60min", 7), (rows_m, "5min", 75)):
            idx = pd.date_range(t0, periods=n, freq=freq)
            c = px * np.exp(np.cumsum(rng.normal(0, 0.002 if n == 7 else 0.0008, n)))
            o = np.r_[px, c[:-1]]
            k.append(pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c), "close": c}, index=idx))
    h, m = pd.concat(rows_h), pd.concat(rows_m)
    daily = h.groupby(h.index.date).agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    daily.index = pd.DatetimeIndex(pd.to_datetime(daily.index)).tz_localize("Asia/Kolkata")
    hr, mr = hourly_tests("NIFTY", h, daily), m5_tests("NIFTY", m)
    assert [r.id for r in hr] == ["H1", "H2", "H3"] and all(r.n > 50 for r in hr)
    assert [r.id for r in mr] == ["M1", "M2", "M3"] and mr[2].n > 500
