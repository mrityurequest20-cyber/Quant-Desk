"""MarketLens engine tests on synthetic markets with known answers."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from marketlens.engine import narrative as N
from marketlens.engine import positioning as P
from marketlens.engine import vol as V


def test_implied_vol_round_trip():
    F, T = 100.0, 30 / 365
    K = np.array([80, 90, 100, 110, 120.0])
    for sig in (0.08, 0.2, 0.6):
        for call in (True, False):
            px = V._b76(F, K, T, sig, np.full(K.shape, call))
            iv = V.implied_vol(px, np.full(K.shape, F), K, np.full(K.shape, T), np.full(K.shape, call))
            ok = np.isfinite(iv)
            assert ok.sum() >= 3
            assert np.allclose(iv[ok], sig, atol=1e-6)


def test_implied_vol_rejects_below_intrinsic():
    iv = V.implied_vol(np.array([1.0]), np.array([100.0]), np.array([80.0]), np.array([0.1]), np.array([True]))
    assert np.isnan(iv[0])


def _chain(day, spot, vols, smile=0.0):
    """A full synthetic chain: Black-76 prices at the given ATM vols (expiry -> vol), with a linear skew."""
    rows = []
    for exp, sig in vols.items():
        T = (exp - day).days / 365
        F = spot * np.exp(0.05 * T)
        for K in np.arange(spot * 0.8, spot * 1.2 + 1, spot * 0.01):
            s = sig + smile * np.log(K / F)
            for kind, call in (("CE", True), ("PE", False)):
                px = float(V._b76(F, K, T, s, np.array(call)))
                rows.append(dict(date=day, symbol="X", kind=kind, expiry=exp, strike=round(K, 2), open=px, high=px,
                                 low=px, close=px, settle=px, underlying=spot, oi=1000.0, chg_oi=0.0, contracts=10.0, lot=50.0))
        rows.append(dict(date=day, symbol="X", kind="FUT", expiry=exp, strike=np.nan, open=F, high=F, low=F, close=F,
                         settle=F, underlying=spot, oi=5000.0, chg_oi=0.0, contracts=100.0, lot=50.0))
    return rows


def test_expiry_table_recovers_atm_vol_forward_and_skew():
    day = pd.Timestamp("2026-01-05")
    e1, e2 = pd.Timestamp("2026-01-20"), pd.Timestamp("2026-02-24")
    df = pd.DataFrame(_chain(day, 1000.0, {e1: 0.15, e2: 0.18}, smile=-0.10))
    t, _ = V.expiry_table(df)
    assert len(t) == 2
    for exp, sig in ((e1, 0.15), (e2, 0.18)):
        r = t[t["expiry"] == exp].iloc[0]
        T = (exp - day).days / 365
        assert r["F"] == pytest.approx(1000 * np.exp(0.05 * T), rel=1e-3)
        assert r["atm_iv"] == pytest.approx(sig, abs=0.003)
        assert r["rr25"] < 0                                     # negative smile slope -> puts dearer
        assert r["implied_move"] == pytest.approx(0.8 * sig * np.sqrt(T), rel=0.05)


def test_constant_maturity_interpolates_total_variance():
    day = pd.Timestamp("2026-01-05")
    t = pd.DataFrame({"date": [day, day], "expiry": [day + pd.Timedelta(days=10), day + pd.Timedelta(days=50)],
                      "days": [10, 50], "atm_iv": [0.10, 0.20]})
    iv30 = V.constant_maturity(t, 30).iloc[0]
    w = np.interp(30, [10, 50], [0.10 ** 2 * 10, 0.20 ** 2 * 50])
    assert iv30 == pytest.approx(np.sqrt(w / 30))


def test_event_vol_finds_an_inverted_front():
    day = pd.Timestamp("2026-01-05")
    t = pd.DataFrame({"date": [day, day], "expiry": [day + pd.Timedelta(days=7), day + pd.Timedelta(days=35)],
                      "days": [7, 35], "atm_iv": [0.45, 0.25]})
    ev = V.event_vol(t, day)
    assert ev is not None and ev["event_move"] > ev["normal_day_move"] * 2
    flat = t.assign(atm_iv=[0.25, 0.25])
    assert V.event_vol(flat, day) is None


def test_split_is_removed_from_history():
    idx = pd.bdate_range("2026-01-01", periods=40)
    close = pd.Series(np.linspace(2000, 2100, 40), index=idx)
    close.iloc[20:] /= 2                                       # a 1:1 bonus
    spot = pd.DataFrame({"open": np.nan, "high": np.nan, "low": np.nan, "close": close})
    lots = pd.Series(250.0, index=idx)
    lots.iloc[20:] = 500.0
    adj, ev = V.adjust_splits(spot, lots, "stock")
    assert len(ev) == 1 and ev[0]["ratio"] == pytest.approx(2.0, rel=0.03)
    assert np.log(adj["close"]).diff().abs().max() < 0.05


def test_move_scorecard_counts_inside():
    days = pd.bdate_range("2026-01-01", periods=60)
    spot = pd.Series(100.0, index=days)                       # a flat market: every move stays inside
    t = pd.DataFrame({"date": days[:40], "expiry": days[5:45], "days": 7, "implied_move": 0.02})
    sc = V.move_scorecard(t, spot)
    assert sc["inside_all"] == 1.0


def test_buildup_classes():
    days = pd.bdate_range("2026-01-01", periods=5)
    exp = pd.Timestamp("2026-01-29")
    px = [100, 102, 101, 103, 102]
    oi = [1000, 1100, 1200, 1100, 1000]
    rows = [dict(date=d, kind="FUT", expiry=exp, close=p, settle=p, oi=o, contracts=1.0) for d, p, o in zip(days, px, oi)]
    b = P.futures_book(pd.DataFrame(rows), pd.Series(px, index=days, dtype=float) * 0.999)
    assert list(b["buildup"].iloc[1:]) == ["Long build-up", "Short build-up", "Short covering", "Long unwinding"]
    assert (b["carry"].iloc[1:] > 0).all()


def test_latest_pct_and_words():
    s = pd.Series(np.arange(100, dtype=float))
    assert P.latest_pct(s) == pytest.approx(1.0)
    assert N.level(0.05) == "very low" and N.level(0.95) == "very high" and N.level(0.5) == "normal"
    assert N.ordinal(0.21) == "21st" and N.ordinal(0.12) == "12th"


def test_narratives_never_say_buy_or_sell():
    texts = [
        N.iv_card("X", 0.2, 0.9, 0.5, "2019-01-01")["simple"],
        N.vrp_card("X", 0.2, 0.3, 0.05, 0.7, "2019-01-01")["simple"],
        N.skew_card("X", -0.03, 0.2)["simple"],
        N.term_card("X", 0.3, 0.2, 5, 30, None)["simple"],
        N.futures_card("X", {"basis": 10.0, "carry": 0.12}, 0.9, ["Long build-up"])["simple"],
    ]
    for t in texts:
        low = t.lower()
        assert " buy " not in f" {low} " and " sell " not in f" {low} "
