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
    assert len(ev) == 1 and ev[0]["ratio"] == 2.0
    assert V.snap_ratio(2.858) == 3.0 and V.snap_ratio(9.9478) == 10.0 and V.snap_ratio(1.53) == 1.5
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


# ---------------- Tier 1 audit regressions ----------------
from marketlens import universe as U
from marketlens.engine import build as B
from marketlens.engine import events as E


def test_stale_untraded_expiry_is_not_read():
    """2020: an expiry whose ATM pair did not trade carries settlement-only prices; it must not reach the curve."""
    day = pd.Timestamp("2026-01-05")
    e1, e2, e3 = pd.Timestamp("2026-01-20"), pd.Timestamp("2026-01-27"), pd.Timestamp("2026-02-24")
    df = pd.DataFrame(_chain(day, 1000.0, {e1: 0.20, e2: 0.45, e3: 0.21}))
    df.loc[(df["expiry"] == e2) & (df["kind"] != "FUT"), "contracts"] = 0.0
    t, _ = V.expiry_table(df)
    assert e2 not in set(t["expiry"])


def test_curve_outlier_dropped_but_real_inversion_kept():
    day = pd.Timestamp("2026-01-05")
    base = dict(date=day, atm_traded=True)
    t = pd.DataFrame([dict(base, expiry=day + pd.Timedelta(days=d), days=d, atm_iv=v)
                      for d, v in [(3, 0.19), (10, 0.186), (17, 0.255), (24, 0.185), (52, 0.163)]])
    kept = V.drop_curve_outliers(t)
    assert 17 not in set(kept["days"]) and len(kept) == 4
    event = pd.DataFrame([dict(base, expiry=day + pd.Timedelta(days=d), days=d, atm_iv=v) for d, v in [(7, 0.45), (35, 0.25), (63, 0.24)]])
    assert len(V.drop_curve_outliers(event)) == 3                # an event front expiry is real, not an outlier
    dip = pd.DataFrame([dict(base, expiry=day + pd.Timedelta(days=d), days=d, atm_iv=v)    # NIFTY 30 Mar 2026
                        for d, v in [(8, 0.295), (14, 0.299), (22, 0.237), (29, 0.162), (57, 0.226)]])
    assert 29 not in set(V.drop_curve_outliers(dip)["days"])
    bump = pd.DataFrame([dict(base, expiry=day + pd.Timedelta(days=d), days=d, atm_iv=v)   # budget inside the 2nd weekly
                         for d, v in [(3, 0.14), (10, 0.17), (17, 0.15), (24, 0.15)]])
    assert len(V.drop_curve_outliers(bump)) == 4


def test_tick_precision_guard_skips_cheap_near_expiry():
    day = pd.Timestamp("2026-01-05")
    e1, e2 = pd.Timestamp("2026-01-08"), pd.Timestamp("2026-02-24")
    df = pd.DataFrame(_chain(day, 30.0, {e1: 0.5, e2: 0.5}))     # a Rs 30 stock
    t, _ = V.expiry_table(df)
    assert e1 not in set(t["expiry"])                             # 3 days: one tick > 1 vol pt
    assert e2 in set(t["expiry"])


def test_constant_maturity_needs_an_expiry_a_week_out():
    day = pd.Timestamp("2026-01-05")
    t = pd.DataFrame({"date": [day], "expiry": [day + pd.Timedelta(days=3)], "days": [3], "atm_iv": [0.4]})
    assert V.constant_maturity(t).empty


def test_results_study_reads_before_and_shows_both_days():
    days = pd.bdate_range("2026-10-26", periods=8)
    close = pd.Series([100, 100, 100, 100, 100, 112, 113, 113.0], index=days)     # results on day 4, reaction day 5
    ivf = pd.Series([.3, .3, .3, .3, .3, .2, .2, .2], index=days)
    t = pd.DataFrame({"date": [days[3], days[3]], "expiry": [days[3] + pd.Timedelta(days=7), days[3] + pd.Timedelta(days=35)],
                      "days": [7, 35], "atm_iv": [0.45, 0.25]})
    ev = pd.DataFrame({"date": [days[4]], "purpose": ["Financial Results"]})
    r = E.results_study(ev, close, t, ivf, days[-1])[0]
    assert r["move_day0"] == pytest.approx(0.0) and r["move_day1"] == pytest.approx(0.12)
    assert r["reaction"] == pytest.approx(0.12) and r["iv_change"] == pytest.approx(-0.1)
    assert r["implied_event_move"] > 0.02                         # read at the close before the results date


def test_day_change_is_scaled_by_own_history():
    idx = pd.bdate_range("2025-01-01", periods=300)
    rng = np.random.default_rng(0)
    iv = pd.Series(0.15 + np.cumsum(rng.normal(0, 0.002, 300)), index=idx)
    iv.iloc[-1] = iv.iloc[-2] + 0.02                              # a 10-sigma day
    ch = {c["field"]: c for c in B.day_changes(pd.DataFrame({"iv30": iv}))}
    assert ch["iv30"]["chg"] == pytest.approx(2.0) and ch["iv30"]["z"] > 6


def test_rules_detect_listed_lot_revision_and_physical_settlement():
    asof = pd.Timestamp("2026-11-24")
    near, far = pd.Timestamp("2026-11-26"), pd.Timestamp("2027-01-25")
    rows = [dict(date=asof, kind=k, expiry=e, lot=l) for k in ("FUT", "CE") for e, l in ((near, 650.0), (far, 750.0))]
    r = B.rules_block(pd.DataFrame(rows), asof, U.BY_SYMBOL["HDFCBANK"], [])
    assert r["lot_change"] == {"from": 650.0, "to": 750.0, "expiry": "2027-01-25"}
    assert any(n["kind"] == "settlement" for n in r["notes"]) and r["sessions_to_expiry"] == 2


def test_forward_must_agree_with_the_future():
    """A stale parity pair that puts an expiry's forward 10% away from the market is not read (BANKNIFTY 4 Jun 2020)."""
    day = pd.Timestamp("2026-01-05")
    e1, e2 = pd.Timestamp("2026-01-12"), pd.Timestamp("2026-01-27")
    good = pd.DataFrame(_chain(day, 1000.0, {e1: 0.2, e2: 0.2}))            # the futures trade at ~1000
    stale = pd.DataFrame(_chain(day, 900.0, {e1: 0.2})).query("kind != 'FUT'")  # e1's options priced off 900
    df = pd.concat([good[~((good["expiry"] == e1) & (good["kind"] != "FUT"))], stale], ignore_index=True)
    t, _ = V.expiry_table(df)
    assert set(t["expiry"]) == {e2}


def test_atm_iv_agrees_with_straddle_iv_on_clean_chain():
    day = pd.Timestamp("2026-01-05")
    df = pd.DataFrame(_chain(day, 1000.0, {pd.Timestamp("2026-02-04"): 0.22}))
    t, _ = V.expiry_table(df)
    assert t["straddle_iv"].iat[0] == pytest.approx(t["atm_iv"].iat[0], rel=0.02)


def _strike_rows(day, expiry, strikes, lot=500.0):
    return [dict(date=day, kind="CE", expiry=expiry, strike=k, lot=lot) for k in strikes]


def test_corporate_action_needs_rebuilt_strikes_a_calm_market_and_no_lot_change():
    days = pd.bdate_range("2025-01-01", periods=4)
    e = pd.Timestamp("2025-01-30")
    grid_a = [440 + 10 * i for i in range(12)]
    grid_b = [405 + 10 * i for i in range(12)]                    # rebuilt off the old grid after the demerger
    rows = (_strike_rows(days[0], e, grid_a) + _strike_rows(days[1], e, grid_a) + _strike_rows(days[2], e, grid_b)
            + _strike_rows(days[3], e, grid_b))
    opt = pd.DataFrame(rows)
    stock = pd.Series([480, 481, 441, 442.0], index=days)       # -8.7% on day 2
    calm = pd.Series([100, 100.2, 100.1, 100.3], index=days)
    crash = pd.Series([100, 100, 93, 93.5], index=days)
    a = V.corporate_actions(opt, stock, calm)
    assert [x["date"] for x in a] == [str(days[2].date())]
    assert V.corporate_actions(opt, stock, crash) == []            # everything fell: not an action
    split = opt.copy()
    split.loc[split["date"] >= days[2], "lot"] = 1000.0
    assert V.corporate_actions(split, stock, calm) == []           # lot changed: a split/bonus, handled elsewhere
    t = pd.DataFrame({"date": days, "expiry": e, "atm_iv": 0.05})
    assert set(V.drop_action_windows(t, a)["date"]) == set(days[2:])


def test_skew_words_match_size():
    assert "about the same" in N.skew_card("X", 0.005, 0.5)["simple"]
    assert "Protection against a fall" in N.skew_card("X", -0.03, 0.5)["simple"]
    assert "Upside calls cost more" in N.skew_card("X", 0.03, 0.95)["simple"]
