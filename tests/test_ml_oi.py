"""The OI features and their pre-registered test (quantdesk/ml/oi.py, docs/prereg/oi_shadow_v1.json).

A synthetic one-day chain with known walls and known OI changes gives every feature an expected value computed here, independently of the module;
the look-ahead canary runs against `decision_table` itself; the estimator is checked against a plain dummy-variable regression and against a planted slope.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm

from quantdesk.ml import oi, pit

IST = "Asia/Kolkata"
DAY = "2026-10-13"
STRIKES = np.arange(22000.0, 23001.0, 50.0)
SPOT = 22500.0
FAR = pd.Timestamp("2026-11-03")


def gen(day=DAY, spot_fn=None, oi_fn=None, expiry=FAR, drop=(), corrupt=(), underlying="NIFTY", iv=15.0, minutes=range(375), iv_fn=None, vol_fn=None, qty=100.0):
    """One session of snapshots, one a minute at the minute, long format like the archive: strikes 22000 to 23000 step 50. Baseline OI is 1e5 on
    every strike and side; walls of 1e6 sit at 23000 (calls) and 22000 (puts). A mid is intrinsic plus 60 at the money, falling away from it, so the
    ATM straddle is 120. `oi_fn(minute, side, strike, base)` and `spot_fn(minute)` change them; `drop`: minutes with no snapshot; `corrupt`: minutes whose
    puts carry a feed fault. `iv_fn(minute, side, strike)` gives a strike's volatility (points), `vol_fn(minute, side, strike)` its running volume, `qty` the size
    at the touch on both sides."""
    rows = []
    for k in minutes:
        if k in drop:
            continue
        ts = pd.Timestamp(f"{day} 09:15", tz=IST) + pd.Timedelta(minutes=k)
        S = float(spot_fn(k)) if spot_fn else SPOT
        for K in STRIKES:
            base_c = 1e6 if K == 23000 else 1e5
            base_p = 1e6 if K == 22000 else 1e5
            ce_oi = oi_fn(k, "c", K, base_c) if oi_fn else base_c
            pe_oi = oi_fn(k, "p", K, base_p) if oi_fn else base_p
            if k in corrupt:
                pe_oi = 9.0e18
            ce = max(S - K, 0) + 60 * math.exp(-abs(S - K) / 200)
            pe = max(K - S, 0) + 60 * math.exp(-abs(S - K) / 200)
            if oi_fn is not None and getattr(oi_fn, "price", None):
                ce += oi_fn.price(k, "c", K)
                pe += oi_fn.price(k, "p", K)
            civ = iv_fn(k, "c", K) if iv_fn else iv
            piv = iv_fn(k, "p", K) if iv_fn else iv
            rows.append({"ts": ts, "underlying": underlying, "expiry": expiry, "spot": S, "source": "kotak", "strike": K,
                         "ce_ltp": ce, "ce_bid": ce - 0.5, "ce_ask": ce + 0.5, "ce_iv": civ, "ce_oi": ce_oi, "ce_doi": 0.0,
                         "ce_vol": vol_fn(k, "c", K) if vol_fn else 0.0,
                         "pe_ltp": pe, "pe_bid": pe - 0.5, "pe_ask": pe + 0.5, "pe_iv": piv, "pe_oi": pe_oi, "pe_doi": 0.0,
                         "pe_vol": vol_fn(k, "p", K) if vol_fn else 0.0,
                         "ce_bidq": qty, "ce_askq": qty, "pe_bidq": qty, "pe_askq": qty})
    df = pd.DataFrame(rows)
    df["ts"] = df["ts"].astype("datetime64[us, Asia/Kolkata]")
    return df


def row_at(df, m, **kw):
    t = decision(df, m, **kw)
    assert len(t) == 1, f"expected one row for minute {m}, got {len(t)}"
    return t.iloc[0]


def decision(df, m, day=DAY, underlying="NIFTY", labels=True):
    t = oi.decision_table(df, day, underlying, with_labels=labels)
    return t[t["m"] == m]


M0 = 120.0                                              # the ATM straddle of gen(): 60 + 60 (mids at the strike)


# ---- the implied probability -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("a,s", [(1.0, 1.0), (0.5, 1.0), (2.0, 1.0), (0.1, 3.0)])
def test_one_far_barrier_is_the_reflection_formula(a, s):
    assert oi.survival_prob(a, 1e7, s) == pytest.approx(2 * norm.cdf(a / s) - 1, abs=1e-9)
    assert oi.survival_prob(1e7, a, s) == pytest.approx(2 * norm.cdf(a / s) - 1, abs=1e-9)


def test_two_barriers_match_a_random_walk_with_the_discrete_monitoring_correction():
    """A walk monitored n times sees a barrier as if it were pushed out by 0.5826 sigma sqrt(dt) (Broadie, Glasserman, Kou)."""
    rng = np.random.default_rng(0)
    n, N = 1500, 30000
    for a, b, s in [(1.0, 1.0, 1.0), (0.6, 1.4, 1.0), (2.0, 0.8, 1.5)]:
        path = np.cumsum(rng.standard_normal((N, n)) * s / math.sqrt(n), axis=1)
        mc = float(((path.max(1) < a) & (path.min(1) > -b)).mean())
        delta = 0.5826 * s / math.sqrt(n)
        assert mc == pytest.approx(oi.survival_prob(a + delta, b + delta, s), abs=0.012), (a, b, s)


def test_survival_probability_is_monotone_bounded_and_symmetric():
    s = 1.0
    assert oi.survival_prob(1, 1, s) == pytest.approx(oi.survival_prob(1, 1, s))
    assert oi.survival_prob(1.0, 2.0, s) == pytest.approx(oi.survival_prob(2.0, 1.0, s))        # which wall is which does not matter
    p = [oi.survival_prob(1, 1, x) for x in (0.1, 0.5, 1, 2, 5)]
    assert p == sorted(p, reverse=True) and all(0 <= x <= 1 for x in p)                         # wider walls survive more; more vol, less
    assert oi.survival_prob(5, 5, 0.01) == pytest.approx(1.0)
    assert oi.survival_prob(0.01, 0.01, 5) == pytest.approx(0.0, abs=1e-6)
    assert oi.survival_prob(1, 3, 1) > oi.survival_prob(1, 1, 1)
    for bad in [(-1, 1, 1), (1, -1, 1), (0, 1, 1), (1, 1, 0), (1, 1, -2), (float("nan"), 1, 1)]:
        assert math.isnan(oi.survival_prob(*bad)), bad


# ---- quarantine ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("ce,pe,ok", [(1e5, 1e5, True), (0.0, 0.0, True), (np.nan, 5e4, True), (9e18, 1e5, False), (1e5, -1.0, False),
                                      (-9e18, 1e5, False), (np.inf, 1e5, False), (1e5, 1e12 + 1, False), (1e12, 1e12, True)])
def test_valid_oi_quarantines_a_snapshot_with_an_implausible_print(ce, pe, ok):
    g = pd.DataFrame({"ce_oi": [1e5, ce, 1e5], "pe_oi": [1e5, 1e5, pe]})
    assert oi.valid_oi(g) is ok


def test_snapshot_validity_computed_for_all_snapshots_at_once_equals_valid_oi_one_at_a_time():
    rng = np.random.default_rng(5)
    df = gen(minutes=range(60))
    for k in rng.choice(60, 12, replace=False):                                              # corrupt a random mix of snapshots, in different ways
        rows = df.index[df["ts"] == df["ts"].iloc[0] + pd.Timedelta(minutes=int(k))]
        col = rng.choice(["ce_oi", "pe_oi"])
        df.loc[rows[3], col] = rng.choice([9e18, -5.0, np.inf, -np.inf, np.nan, 1e12, 1e12 + 1, 0.0])
    sn = oi.Snapshots(df)
    one_by_one = np.array([oi.valid_oi(sn[k]) for k in sn.keys])
    assert (sn.valid == one_by_one).all() and 0 < sn.valid.sum() < len(sn.valid)
    shuffled = oi.Snapshots(df.sample(frac=1, random_state=1))                                # the input need not be in time order
    assert (shuffled.keys == sn.keys).all() and (shuffled.valid == sn.valid).all()
    assert len(sn[sn.keys[7]]) == len(STRIKES) and (sn[sn.keys[7]]["ts"] == sn[sn.keys[7]]["ts"].iloc[0]).all()


# ---- the features, against values worked out here --------------------------------------------------------------------
def test_walls_distances_and_strength():
    r = row_at(gen(), 90)
    assert (r.spot, r.move, r.iv) == (SPOT, M0, 15.0)
    assert (r.call_wall, r.put_wall) == (23000.0, 22000.0)
    assert r.wall_c_dist == pytest.approx(500 / M0) and r.wall_p_dist == pytest.approx(500 / M0)
    assert r.mult_c == pytest.approx(10.0) and r.mult_p == pytest.approx(10.0)             # 1e6 over the 1e5 median of the band
    assert r.strength == pytest.approx(10.0)
    assert r.pcr_band == pytest.approx(1.0) and r.maxpain_dist == pytest.approx(0.0)
    assert r.com_c == pytest.approx((22700 - SPOT) / M0) and r.com_p == pytest.approx((22300 - SPOT) / M0)


def test_a_wall_beyond_the_band_still_counts_but_is_measured_against_the_band():
    def f(k, side, K, base):
        return 4e5 if (K == 22900 and side == "c") else base                                # a nearer, smaller call wall inside nothing: 22900 > spot
    r = row_at(gen(oi_fn=f), 90)
    assert r.call_wall == 23000.0                                                          # 1e6 still beats 4e5


def test_the_walls_are_on_the_right_side_of_spot():
    r = row_at(gen(spot_fn=lambda k: 22980.0), 90)
    assert r.call_wall == 23000.0 and r.put_wall == 22000.0
    r = row_at(gen(spot_fn=lambda k: 23020.0), 90)                                         # spot above every strike: no call wall at all
    assert math.isnan(r.call_wall) and math.isnan(r.wall_c_dist) and math.isnan(r.strength)


def writing_oi(k, side, K, base):
    """Call OI at 22600 triples after 10:15 and the call there gets cheaper (written); put OI at 22400 falls by 4e4 (unwound)."""
    if side == "c" and K == 22600 and k > 60:
        return 3e5
    if side == "p" and K == 22400 and k > 60:
        return 6e4
    return base


writing_oi.price = lambda k, side, K: -5.0 if (side == "c" and K == 22600 and k > 60) else 0.0


def test_build_up_classification_and_normalisation():
    r = row_at(gen(oi_fn=writing_oi), 90)                      # 10:45; the snapshot 30 minutes earlier is 10:15 (minute 60)
    near_calls_now = 6 * 1e5 + 3e5                             # 22350 to 22650 are the seven strikes within 1.5 x 120 of spot
    assert r.call_write == pytest.approx(2e5 / near_calls_now) and r.call_buy == 0 and r.call_unwind == 0
    near_puts_now = 7 * 1e5 - 4e4
    assert r.put_unwind == pytest.approx(4e4 / near_puts_now) and r.put_write == 0 and r.put_buy == 0
    assert r.band_oi_cover == pytest.approx(1.0)


def test_added_oi_at_a_dearer_option_is_buying():
    f = writing_oi
    g = lambda k, side, K, base: f(k, side, K, base)
    g.price = lambda k, side, K: 5.0 if (side == "c" and K == 22600 and k > 60) else 0.0
    r = row_at(gen(oi_fn=g), 90)
    assert r.call_buy == pytest.approx(2e5 / (6 * 1e5 + 3e5)) and r.call_write == 0


def test_the_centre_of_mass_shift_is_measured_against_the_past_snapshot():
    r = row_at(gen(oi_fn=writing_oi), 90)
    k = np.arange(22550.0, 22851.0, 50.0)
    now, then = np.full(len(k), 1e5), np.full(len(k), 1e5)
    now[list(k).index(22600.0)] = 3e5
    expected = ((k * now).sum() / now.sum() - (k * then).sum() / then.sum()) / M0
    assert r.d_com_c == pytest.approx(expected) and r.d_com_p == pytest.approx(0.0 + (
        (lambda kk, w: ((kk * w).sum() / w.sum()))(np.arange(22150.0, 22451.0, 50.0), np.where(np.arange(22150.0, 22451.0, 50.0) == 22400.0, 6e4, 1e5))
        - 22300.0) / M0)


def test_a_decision_without_a_past_snapshot_has_no_change_features():
    r = row_at(gen(), 15)                                      # 09:30 has no snapshot 30 minutes before
    assert all(math.isnan(r[c]) for c in ("d_com_c", "d_com_p", "call_write", "put_buy", "band_oi_cover"))
    assert r.call_wall == 23000.0                              # the level features need only the snapshot itself


def test_the_expiry_is_the_nearest_with_an_hour_to_run():
    same_day = pd.Timestamp(DAY)
    both = pd.concat([gen(expiry=same_day), gen(expiry=FAR)], ignore_index=True)
    t = oi.decision_table(both, DAY, "NIFTY")
    morning, late = t[t["m"] == 90].iloc[0], t[t["m"] == 300].iloc[0]                       # 10:45 and 14:15 (75 minutes to the close)
    assert morning.expiry == DAY and bool(morning.expiry_day) and morning.to_expiry_min == pytest.approx(285)
    assert late.expiry == DAY
    t2 = t[t["m"] == 330].iloc[0]                                                           # 14:45: only 45 minutes left on the same-day expiry
    assert t2.expiry == str(FAR.date()) and not bool(t2.expiry_day)


# ---- missing and faulty snapshots ------------------------------------------------------------------------------------
def test_a_stale_snapshot_gives_no_decision():
    df = gen(drop=range(80, 91))                               # nothing between 10:35 and 10:45: the last is 6 minutes old
    assert decision(df, 90).empty
    assert len(decision(gen(drop=range(89, 91)), 90)) == 1     # two minutes old is within 150 seconds
    assert decision(gen(drop=range(88, 91)), 90).empty         # three minutes old is not
    assert row_at(gen(drop=[90]), 90).snap_age_s == pytest.approx(60.0)


def test_a_feed_fault_quarantines_the_snapshot_and_the_decision_uses_the_last_valid_one():
    r = row_at(gen(corrupt=[89, 90]), 90)
    assert r.skipped_invalid == 2 and r.snap_age_s == pytest.approx(120.0) and r.strength == pytest.approx(10.0)       # nothing leaks from the fault
    assert decision(gen(corrupt=[88, 89, 90]), 90).empty                                   # 180 s old: too stale, counted nowhere as a row
    clean = row_at(gen(), 90)
    assert clean.skipped_invalid == 0


def test_a_faulty_snapshot_never_reaches_a_feature():
    df = gen(corrupt=[90])
    for c in ("pcr_band", "mult_p", "strength", "maxpain_dist"):
        v = row_at(df, 90)[c]
        assert abs(v) < 1e3, (c, v)                            # a 9e18 print would make PCR about 1e13


# ---- labels ---------------------------------------------------------------------------------------------------------
def test_contained_and_the_implied_probability():
    r = row_at(gen(), 90)
    assert r.contained60 == 1.0 and r.ret60 == pytest.approx(0.0) and r.cover60 == pytest.approx(1.0)
    s = 0.15 * math.sqrt(60 / (252 * 375))
    want = oi.survival_prob(math.log(23000 / SPOT), math.log(SPOT / 22000), s)
    assert r.p_iv60 == pytest.approx(want)
    assert 0.0 < want <= 1.0
    s30 = 0.15 * math.sqrt(30 / (252 * 375))
    assert r.p_iv30 == pytest.approx(oi.survival_prob(math.log(23000 / SPOT), math.log(SPOT / 22000), s30))


def test_a_touch_of_either_wall_breaks_containment_and_only_inside_the_window():
    jump_up = gen(spot_fn=lambda k: 23050.0 if k >= 110 else SPOT)                           # 11:05
    assert row_at(jump_up, 90).contained60 == 0.0                                           # window 10:45 to 11:45 sees it
    assert row_at(jump_up, 60).contained60 == 0.0                                           # window 10:15 to 11:15 also contains 11:05
    assert row_at(jump_up, 45).contained60 == 1.0                                           # window 10:00 to 11:00 ends before it
    dip = gen(spot_fn=lambda k: 21990.0 if k == 100 else SPOT)
    assert row_at(dip, 90).contained60 == 0.0
    late_touch = gen(spot_fn=lambda k: 23050.0 if k >= 160 else SPOT)                       # 11:55: after the 10:45 window ends
    assert row_at(late_touch, 90).contained60 == 1.0
    assert row_at(late_touch, 90).ret60 == pytest.approx(0.0)
    # the touch is strict: spot exactly at the wall is a touch
    assert row_at(gen(spot_fn=lambda k: 23000.0 if k == 100 else SPOT), 90).contained60 == 0.0           # exactly at the wall is a touch
    assert row_at(gen(spot_fn=lambda k: 22999.5 if k == 100 else SPOT), 90).contained60 == 1.0           # half a point inside is not


def test_the_label_needs_coverage_and_a_window_inside_the_session():
    sparse = gen(drop=[k for k in range(91, 151) if k % 3])                                  # a third of the minutes in the window
    assert math.isnan(row_at(sparse, 90).contained60) and math.isnan(row_at(sparse, 90).ret60)
    assert row_at(sparse, 90).p_iv60 != row_at(sparse, 90).p_iv60
    r = decision(gen(), 330)                                                                  # 14:45 + 60 minutes runs past the close
    assert len(r) == 1 and math.isnan(r.iloc[0].contained60) and r.iloc[0].contained30 == 1.0


# ---- no look-ahead --------------------------------------------------------------------------------------------------
def perturb_after(df, key, rng):
    """Everything after the decision, replaced: spot, every OI print, every price."""
    underlying, day, m = key
    t = pd.Timestamp(f"{day} 09:15", tz=IST) + pd.Timedelta(minutes=m)
    out = df.copy()
    late = out["ts"] > t
    n = int(late.sum())
    out.loc[late, "spot"] = out.loc[late, "spot"] * np.exp(rng.normal(0, 0.01, n))
    for c in ("ce_oi", "pe_oi", "ce_ltp", "ce_bid", "ce_ask", "pe_ltp", "pe_bid", "pe_ask", "ce_vol", "pe_vol", "ce_iv", "pe_iv",
              "ce_bidq", "ce_askq", "pe_bidq", "pe_askq"):
        out.loc[late, c] = out.loc[late, c] * rng.uniform(0.5, 2.0, n)
    return out


def walk(k):
    return SPOT + 40 * math.sin(k / 25)


def test_no_feature_uses_anything_after_its_decision():
    vol = lambda k, side, K: 1000.0 + 5.0 * k + (K - 22000) / 10                                  # a running total that grows
    df = pd.concat([gen(spot_fn=walk, oi_fn=writing_oi, vol_fn=vol), gen(spot_fn=walk, oi_fn=writing_oi, vol_fn=vol, expiry=FAR + pd.Timedelta(days=7), iv=16.0)],
                   ignore_index=True)
    keys = [("NIFTY", DAY, m) for m in (30, 90, 150, 210, 270)]
    feats = oi.FEATURES + ["p_iv60", "p_iv30"]
    rep = pit.assert_point_in_time(lambda d: oi.decision_table(d, DAY, "NIFTY"), df, keys, perturb_after, oi.KEY, feats, ["ret60"])
    assert rep.checked == len(keys) and rep.label_moved["ret60"] > 0 and max(rep.max_rel_diff.values()) <= 1e-9


def test_the_canary_catches_a_feature_that_peeks():
    df = gen(spot_fn=walk, oi_fn=writing_oi)

    def leaky(d):
        t = oi.decision_table(d, DAY, "NIFTY")
        return t.assign(strength=t["strength"] * (1 + t["ret60"].fillna(0)))

    with pytest.raises(pit.PointInTimeError, match="leaks"):
        pit.assert_point_in_time(leaky, df, [("NIFTY", DAY, 90)], perturb_after, oi.KEY, oi.FEATURES, ["ret60"])


# ---- the frozen rank map ---------------------------------------------------------------------------------------------
def test_rank_strength_is_monotone_bounded_and_ranked_against_the_development_sessions():
    for u in ("NIFTY", "BANKNIFTY"):
        br = oi.STRENGTH_BREAKS[u]
        assert len(br) == 21 and br == sorted(br)
        x = np.linspace(br[0] - 1, br[-1] + 1, 200)
        r = oi.rank_strength(x, u)
        assert (np.diff(r) >= 0).all() and r.min() == 0.0 and r.max() == 1.0               # clipped, never extrapolated
        assert oi.rank_strength(br[10], u) == pytest.approx(0.5)
    assert oi.rank_strength([4.55], "NIFTY")[0] != oi.rank_strength([4.55], "BANKNIFTY")[0]  # ranked within its own index


# ---- the estimator --------------------------------------------------------------------------------------------------
def planted(G=60, n=14, beta=0.25, gamma=-0.3, seed=1, noise=0.4):
    rng = np.random.default_rng(seed)
    g = np.repeat(np.arange(G), n)
    rk, p = rng.uniform(0, 1, G * n), rng.uniform(0.2, 0.9, G * n)
    y = rng.normal(0, 0.3, G)[g] + beta * rk + gamma * p + rng.normal(0, noise, G * n)
    return y, np.column_stack([rk, p]), g


def test_fit_within_equals_a_dummy_variable_regression_and_its_clustered_errors():
    y, X, g = planted()
    f = oi.fit_within(y, X, g)
    Z = np.column_stack([X, (g[:, None] == np.unique(g)[None, :]).astype(float)])
    b = np.linalg.lstsq(Z, y, rcond=None)[0]
    np.testing.assert_allclose(f["beta"], b[:2], rtol=1e-9)
    e = y - Z @ b
    bread = np.linalg.inv(Z.T @ Z)
    meat = sum(np.outer(Z[g == k].T @ e[g == k], Z[g == k].T @ e[g == k]) for k in np.unique(g))
    G = len(np.unique(g))
    np.testing.assert_allclose(f["se"], np.sqrt(np.diag(bread @ meat @ bread * G / (G - 1)))[:2], rtol=1e-8)
    assert f["G"] == G and f["df"] == G - 1


def test_the_planted_slope_is_recovered_and_a_null_is_not_rejected_more_than_chance():
    y, X, g = planted(G=200, beta=0.25)
    f = oi.fit_within(y, X, g)
    assert abs(f["beta"][0] - 0.25) < 3 * f["se"][0] and abs(f["beta"][1] + 0.3) < 3 * f["se"][1]
    rejects = 0
    for seed in range(200):
        y, X, g = planted(G=40, n=10, beta=0.0, seed=100 + seed)
        f = oi.fit_within(y, X, g)
        rejects += f["beta"][0] / f["se"][0] > 1.686                                         # one-sided 5% at 39 df
    assert rejects / 200 < 0.10                                                              # nominal 5%; 200 runs allow a margin


def test_holm_step_down():
    assert oi.holm({"a": 0.02, "b": 0.06}) == {"a": True, "b": False}
    assert oi.holm({"a": 0.03, "b": 0.04}) == {"a": False, "b": False}                       # 0.03 > 0.025, so nothing after it either
    assert oi.holm({"a": 0.01, "b": 0.04}) == {"a": True, "b": True}
    assert oi.holm({"a": 0.9}) == {"a": False} and oi.holm({}) == {}


def fake_table(sessions, beta, start="2026-10-26", seed=0, u="NIFTY", p_low=0.3):
    rng = np.random.default_rng(seed)
    days = [str(d.date()) for d in pd.bdate_range(start, periods=sessions)]
    rows = []
    for d in days:
        a = rng.normal(0, 0.1)
        for m in oi.DECISIONS[:14]:
            br = oi.STRENGTH_BREAKS[u]
            strength = rng.uniform(br[0], br[-1])
            p = rng.uniform(p_low, 0.85)
            prob = np.clip(p + a + beta * oi.rank_strength(strength, u) + 0.0, 0.01, 0.99)
            rows.append({"underlying": u, "day": d, "m": m, "strength": strength, "p_iv60": p, "contained60": float(rng.random() < prob), "p_iv30": p, "contained30": 1.0})
    return pd.DataFrame(rows)


def test_wall_test_recovers_an_effect_respects_the_restriction_and_the_forward_start():
    t = fake_table(120, beta=0.3)
    r = oi.wall_test(t, "NIFTY")
    assert r["status"] == "ok" and r["sessions"] == 120 and r["beta"] > 0 and r["p_one_sided"] < 0.05 and r["ci90"][0] < r["beta"] < r["ci90"][1]
    only = t.assign(p_iv60=t["p_iv60"].clip(0.9, 0.95))                                      # outside the restriction: nothing left
    assert oi.wall_test(only.assign(p_iv60=0.95), "NIFTY")["status"].startswith("insufficient")
    dev = fake_table(15, beta=0.9, start="2026-10-05", seed=5)                                # development days carry a huge effect: ignored
    assert oi.wall_test(dev, "NIFTY")["status"].startswith("insufficient")
    mixed = pd.concat([dev, fake_table(40, beta=0.0, seed=6)], ignore_index=True)
    assert oi.wall_test(mixed, "NIFTY")["sessions"] == 40
    assert oi.wall_test(t, "BANKNIFTY")["status"].startswith("insufficient")                  # no rows for the other index


def test_the_report_is_confirmatory_only_at_the_final_readout_with_enough_sessions():
    t = pd.concat([fake_table(120, 0.3, seed=1, u="NIFTY"), fake_table(120, 0.0, seed=2, u="BANKNIFTY")], ignore_index=True)
    interim = oi.oi_report(t, "interim")
    assert not interim["confirmatory"] and "not a finding" in interim["note"]
    short = oi.oi_report(pd.concat([fake_table(80, 0.3, seed=1), fake_table(80, 0, seed=2, u="BANKNIFTY")], ignore_index=True), "final")
    assert not short["confirmatory"] and "needs 120" in short["note"]
    final = oi.oi_report(t, "final")
    assert final["confirmatory"] and final["rejected"]["NIFTY"] is True and final["rejected"]["BANKNIFTY"] is False
    assert final["retired"] == {"NIFTY": False, "BANKNIFTY": True} or final["retired"]["NIFTY"] is False


# ---- the code pin ---------------------------------------------------------------------------------------------------
def test_the_code_hash_changes_with_a_definition_a_constant_or_the_rank_map(monkeypatch):
    base = oi.code_sha256()
    assert base == oi.code_sha256() and len(base) == 64
    for name, val in (("BAND", oi.BAND + 0.5), ("OI_MAX", 1e9), ("MAX_AGE_S", 100.0), ("P_IV_RANGE", (0.1, 0.9)), ("FORWARD_START", "2026-10-27"),
                      ("LOOKBACK", 20), ("MIN_COVER", 0.7)):
        monkeypatch.setattr(oi, name, val)
        assert oi.code_sha256() != base, name
        monkeypatch.undo()
    monkeypatch.setattr(oi, "STRENGTH_BREAKS", {**oi.STRENGTH_BREAKS, "NIFTY": [x + 0.001 for x in oi.STRENGTH_BREAKS["NIFTY"]]})
    assert oi.code_sha256() != base


# ---- a session, end to end ------------------------------------------------------------------------------------------
def tape_dir(tmp_path, days=(DAY,)):
    d = tmp_path / "tape"
    d.mkdir()
    for day in days:
        both = pd.concat([gen(day=day, spot_fn=walk, oi_fn=writing_oi, underlying=u) for u in ("NIFTY", "BANKNIFTY")], ignore_index=True)
        half = len(both) // 2
        both.iloc[:half].to_parquet(d / f"{day}_morning-1_chains.parquet")
        both.iloc[half:].to_parquet(d / f"{day}_afternoon-1_chains.parquet")
    return d


def test_run_day_writes_once_pins_its_inputs_and_refuses_a_different_rerun(tmp_path):
    tape, out = tape_dir(tmp_path), tmp_path / "out"
    man = oi.run_day(tape, DAY, out)
    assert man["day"] == DAY and man["forward"] is False and man["code_sha256"] == oi.code_sha256()
    assert set(man["inputs"]) == {f"{DAY}_morning-1_chains.parquet", f"{DAY}_afternoon-1_chains.parquet"}
    assert all(len(v) == 64 for v in man["inputs"].values()) and man["rows"] == {"NIFTY": 23, "BANKNIFTY": 23}
    assert man["quarantine"]["NIFTY"] == {"snapshots": 375, "quarantined": 0}
    again = oi.run_day(tape, DAY, out)                                                       # a faithful rerun is accepted and changes nothing
    assert again == man
    (tape / f"{DAY}_afternoon-1_chains.parquet").write_bytes((tape / f"{DAY}_morning-1_chains.parquet").read_bytes())
    with pytest.raises(RuntimeError, match="does not reproduce"):
        oi.run_day(tape, DAY, out)
    with pytest.raises(FileNotFoundError):
        oi.run_day(tape, "2026-01-02", out)


def test_a_forward_day_is_marked_forward_and_tables_of_other_code_are_refused(tmp_path):
    tape, out = tape_dir(tmp_path, ("2026-10-26",)), tmp_path / "out"
    assert oi.run_day(tape, "2026-10-26", out)["forward"] is True
    assert len(oi.load_tables(out)) == 46
    mp = out / "oi_2026-10-26.json"
    m = json.loads(mp.read_text())
    m["code_sha256"] = "0" * 64
    mp.write_text(json.dumps(m))
    with pytest.raises(RuntimeError, match="other code"):
        oi.load_tables(out)
    with pytest.raises(FileNotFoundError):
        oi.load_tables(tmp_path / "empty")


def test_the_quarantine_is_counted_in_the_manifest(tmp_path):
    d = tmp_path / "tape"
    d.mkdir()
    gen(spot_fn=walk, corrupt=[40, 41, 200]).to_parquet(d / f"{DAY}_morning-1_chains.parquet")
    man = oi.run_day(d, DAY, tmp_path / "out")
    assert man["quarantine"]["NIFTY"] == {"snapshots": 375, "quarantined": 3}


# ---- gaps found by mutation testing the module (each test kills a named mutant) ---------------------------------------
def with_gen(**kw):
    return gen(**kw)


def edit(df, minute, strike=None, **cols):
    """Set columns on the rows of one snapshot (optionally one strike) of a gen() frame."""
    ts = df["ts"].iloc[0] + pd.Timedelta(minutes=minute)
    mask = df["ts"] == ts
    if strike is not None:
        mask &= df["strike"] == strike
    for c, v in cols.items():
        df.loc[mask, c] = v
    return df


def test_the_implied_probability_is_sensitive_to_the_volatility_convention_when_the_walls_are_near():
    """Walls 5.8 sigma away give a probability of 1 under any convention; walls about one sigma away do not. (kills: 252 -> 365 trading days)"""
    near = lambda k, side, K, base: 1e6 if (side == "c" and K == 22600) or (side == "p" and K == 22400) else 1e5
    r = row_at(gen(oi_fn=near), 90)
    s = 0.15 * math.sqrt(60 / (252 * 375))
    want = oi.survival_prob(math.log(22600 / SPOT), math.log(SPOT / 22400), s)
    assert 0.2 < want < 0.8 and r.p_iv60 == pytest.approx(want, rel=1e-9)
    assert abs(want - oi.survival_prob(math.log(22600 / SPOT), math.log(SPOT / 22400), 0.15 * math.sqrt(60 / (365 * 375)))) > 0.05


def test_the_coverage_needed_for_a_label_is_80_percent_of_the_window():
    """54 of 60 minutes sampled (90%) is enough, 47 (78%) is not. (kills: MIN_COVER 0.5 and 0.95)"""
    keep54 = [k for k in range(91, 151)][:54]
    df = gen(drop=[k for k in range(91, 151) if k not in keep54])
    assert row_at(df, 90).contained60 == 1.0
    keep47 = [k for k in range(91, 151)][:47]
    assert math.isnan(row_at(gen(drop=[k for k in range(91, 151) if k not in keep47]), 90).contained60)
    keep48 = [k for k in range(91, 151)][:48]                                                # exactly 80%
    assert row_at(gen(drop=[k for k in range(91, 151) if k not in keep48]), 90).contained60 == 1.0


def test_a_missing_oi_print_is_not_a_feed_fault():
    """A NaN print (nothing reported) is not an implausible number: the snapshot is used. (kills: NaN counted as a fault)"""
    df = edit(gen(), 90, strike=22700.0, ce_oi=np.nan)
    r = row_at(df, 90)
    assert r.snap_age_s == 0.0 and r.skipped_invalid == 0 and r.call_wall == 23000.0
    sn = oi.Snapshots(df)
    assert sn.valid.all() and oi.valid_oi(sn[sn.keys[90]])


def test_a_mid_falls_back_to_the_last_price_and_a_crossed_quote_is_not_a_mid():
    """(kills: no ltp fallback; crossed quotes accepted)"""
    df = edit(gen(), 90, strike=22500.0, ce_bid=np.nan, ce_ask=np.nan)                         # no quote at the money, a last price
    assert row_at(df, 90).move == pytest.approx(M0)                                           # call 60 (last) + put 60 (mid)
    crossed = edit(gen(), 90, strike=22500.0, ce_bid=70.0, ce_ask=60.0, ce_ltp=61.0)           # bid above ask
    assert row_at(crossed, 90).move == pytest.approx(61.0 + 60.0)                             # the last price, not (70 + 60) / 2 = 65
    none = edit(gen(), 90, strike=22500.0, ce_bid=np.nan, ce_ask=np.nan, ce_ltp=np.nan)
    assert math.isnan(row_at(none, 90).move) and math.isnan(row_at(none, 90).call_wall)       # no price at all: no features, not wrong ones


def test_the_strike_at_spot_is_not_a_wall():
    """Spot is exactly a strike here. A huge call OI at the money must not become the wall above spot. (kills: >= for >)"""
    f = lambda k, side, K, base: 5e6 if (side == "c" and K == SPOT) else (5e6 if (side == "p" and K == SPOT) else base)
    r = row_at(gen(oi_fn=f), 90)
    assert r.call_wall == 23000.0 and r.put_wall == 22000.0


def band_mult(values: dict, lo_strike=22200.0, atm=50.0, side="c"):
    """The call wall's multiple for a band profile `values` {strike: OI} in a chain whose implied move is 100 (so the band is 22200 to 22800,
    edges on strikes), the wall being 23000 with 1e6; the expected median is computed here."""
    def f(k, s, K, base):
        if s == side and K in values:
            return values[K]
        if s == side and K == 23000.0:
            return 1e6
        return 1e5 if s == side else 1e5
    df = gen_atm(f, atm)
    return row_at(df, 90)


def gen_atm(oi_fn, atm):
    """gen() with the at-the-money premium changed, so the implied move is 2 x atm."""
    df = gen(oi_fn=oi_fn)
    for side in ("ce", "pe"):
        for col in (f"{side}_ltp", f"{side}_bid", f"{side}_ask"):
            df[col] = df[col] - (60.0 - atm) * np.exp(-np.abs(df["spot"] - df["strike"]) / 200)
    return df


BAND_STRIKES = np.arange(22200.0, 22801.0, 50.0)


def test_the_band_median_includes_both_edges_and_ignores_zero_oi():
    """Implied move 100 puts the band edges exactly on strikes 22200 and 22800. (kills: exclusive edge; zero OI counted)"""
    v = dict(zip(BAND_STRIKES, np.array([9, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 9]) * 1e4))
    r = band_mult(v)
    assert r.move == pytest.approx(100.0)
    assert r.mult_c == pytest.approx(1e6 / np.median(list(v.values())))                         # 1e6 / 2e4 = 50 with the edges, 100 without
    z = dict(zip(BAND_STRIKES, [0.0] * 7 + [4e4] * 6))
    assert band_mult(z).mult_c == pytest.approx(1e6 / 4e4)                                     # the seven empty strikes are not part of the median


def test_the_band_uses_the_median_and_needs_three_strikes():
    """(kills: mean for median; a one-strike band)"""
    spiky = dict(zip(BAND_STRIKES, [1e4] * 12 + [9e5]))                       # below the 1e6 wall, far above the median
    assert band_mult(spiky).mult_c == pytest.approx(1e6 / 1e4)                                  # the mean is 7.8e4, which would give 12.8
    two = dict(zip(BAND_STRIKES, [0.0] * 11 + [3e4, 3e4]))
    assert math.isnan(band_mult(two).mult_c)                                                    # two strikes with OI: not a distribution to compare with
    three = dict(zip(BAND_STRIKES, [0.0] * 10 + [3e4, 3e4, 3e4]))
    assert band_mult(three).mult_c == pytest.approx(1e6 / 3e4)


def test_strength_is_the_geometric_mean_of_the_two_multiples():
    f = lambda k, side, K, base: 4e5 if (side == "p" and K == 22000) else base                    # put wall 4e5 (multiple 4), call wall 1e6 (multiple 10)
    r = row_at(gen(oi_fn=f), 90)
    assert (r.mult_c, r.mult_p) == (pytest.approx(10.0), pytest.approx(4.0))
    assert r.strength == pytest.approx(math.sqrt(40.0)) and abs(r.strength - 7.0) > 0.5


def test_pcr_is_puts_over_calls_inside_the_band():
    f = lambda k, side, K, base: 2e5 if (side == "p" and 22140 <= K <= 22860) else base
    r = row_at(gen(oi_fn=f), 90)
    assert r.pcr_band == pytest.approx(2.0)


def test_oi_added_where_the_price_is_unknown_is_neither_written_nor_bought():
    """The strike's price 30 minutes ago is missing: the OI added there is classified as neither. (kills: counting it as buying)"""
    df = gen(oi_fn=writing_oi)
    df = edit(df, 60, strike=22600.0, ce_bid=np.nan, ce_ask=np.nan, ce_ltp=np.nan)
    r = row_at(df, 90)
    assert r.call_write == 0.0 and r.call_buy == 0.0


def test_a_strike_missing_from_the_past_snapshot_is_left_out_of_the_change_features():
    df = gen(oi_fn=writing_oi)
    ts = df["ts"].iloc[0] + pd.Timedelta(minutes=60)
    df = df[~((df["ts"] == ts) & (df["strike"] == 22600.0))]
    r = row_at(df, 90)
    assert r.band_oi_cover == pytest.approx(6 / 7)                                              # six of the seven strikes near spot are in both
    assert r.call_write == 0.0                                                                  # the strike that carried the writing is not comparable


def test_a_past_snapshot_older_than_the_age_limit_gives_no_change_features():
    r = row_at(gen(drop=range(58, 62)), 90)                                                     # nothing within 150 s of 30 minutes before the decision
    assert all(math.isnan(r[c]) for c in ("d_com_c", "call_write", "band_oi_cover")) and r.call_wall == 23000.0
    ok = row_at(gen(drop=range(59, 62)), 90)                                                    # 2 minutes old: within the limit
    assert not math.isnan(ok.band_oi_cover)


def test_only_quarantined_snapshots_between_the_one_used_and_the_decision_are_counted():
    """(kills: counting faults before the used snapshot or after the decision)"""
    r = row_at(gen(corrupt=[80, 95]), 90)
    assert r.skipped_invalid == 0 and r.snap_age_s == 0.0
    assert row_at(gen(corrupt=[80, 90, 95]), 90).skipped_invalid == 1                           # 90 is faulty, 89 is used
    assert row_at(gen(corrupt=[80, 90]), 90).skipped_invalid == 1 and row_at(gen(corrupt=[90, 95]), 90).skipped_invalid == 1


def test_touching_the_put_wall_is_a_break_and_a_rising_spot_is_a_positive_return():
    assert row_at(gen(spot_fn=lambda k: 22000.0 if k == 100 else SPOT), 90).contained60 == 0.0
    assert row_at(gen(spot_fn=lambda k: 22001.0 if k == 100 else SPOT), 90).contained60 == 1.0
    up = row_at(gen(spot_fn=lambda k: SPOT + max(0, k - 90) * 2.0), 90)                         # +2 points a minute for the whole window
    assert up.ret60 == pytest.approx(math.log((SPOT + 120.0) / SPOT)) and up.ret60 > 0
    assert row_at(gen(spot_fn=lambda k: SPOT - max(0, k - 90) * 2.0), 90).ret60 < 0


def test_only_real_quotes_are_used():
    df = gen()
    other = gen()
    other["source"] = "nse"
    other["ce_oi"] = other["ce_oi"] * 7
    assert decision(other, 90).empty
    mixed = pd.concat([df, other], ignore_index=True)
    assert oi.decision_table(mixed, DAY, "NIFTY").drop(columns="ts").equals(oi.decision_table(df, DAY, "NIFTY").drop(columns="ts"))


def test_the_test_ignores_decisions_whose_implied_probability_is_outside_the_range_and_has_minimum_sizes():
    t = fake_table(60, beta=0.3, seed=11)
    base = oi.wall_test(t, "NIFTY")
    extra = t.sample(300, random_state=1).assign(p_iv60=0.05, contained60=1.0)                  # outside the range, with an extreme outcome
    assert oi.wall_test(pd.concat([t, extra], ignore_index=True), "NIFTY")["beta"] == pytest.approx(base["beta"])
    hi = t.sample(300, random_state=2).assign(p_iv60=0.95, contained60=0.0)
    assert oi.wall_test(pd.concat([t, hi], ignore_index=True), "NIFTY")["beta"] == pytest.approx(base["beta"])
    edge = t.sample(40, random_state=3).assign(p_iv60=0.15)                                      # exactly on the lower edge is inside
    assert oi.wall_test(pd.concat([t, edge], ignore_index=True), "NIFTY")["n"] == base["n"] + 40
    assert oi.wall_test(fake_table(9, beta=0.3, seed=12), "NIFTY")["status"].startswith("insufficient")        # 9 sessions
    assert oi.wall_test(fake_table(10, beta=0.3, seed=12), "NIFTY")["status"] == "ok"                         # 10 sessions
    two = fake_table(15, beta=0.3, seed=13).groupby("day").head(2)                               # 15 sessions x 2 = 30 decisions
    assert oi.wall_test(two, "NIFTY")["status"] == "ok"
    assert oi.wall_test(two.iloc[:-1], "NIFTY")["status"].startswith("insufficient")              # 29 decisions
    one = fake_table(40, beta=0.3, seed=14).groupby("day").head(1)                               # one decision a session: nothing within sessions
    r = oi.wall_test(one, "NIFTY")
    assert r["status"].startswith("insufficient") and r["n"] == 0


def test_a_regressor_that_does_not_vary_within_sessions_is_reported_not_crashed():
    t = fake_table(40, beta=0.3, seed=15)
    t["strength"] = t.groupby("day")["strength"].transform("first")                              # constant within each session
    t["p_iv60"] = t.groupby("day")["p_iv60"].transform("first")
    assert oi.wall_test(t, "NIFTY")["status"] == "insufficient: the regressors do not vary within sessions"


def test_the_p_value_is_one_sided_in_the_direction_of_the_hypothesis():
    neg = oi.wall_test(fake_table(120, beta=-0.3, seed=21), "NIFTY")
    pos = oi.wall_test(fake_table(120, beta=0.3, seed=21), "NIFTY")
    assert neg["beta"] < 0 < pos["beta"] and neg["p_one_sided"] > 0.95 and pos["p_one_sided"] < 0.05


def test_the_interval_is_a_two_sided_90_percent_one():
    r = oi.wall_test(fake_table(120, beta=0.3, seed=22), "NIFTY")
    from scipy.stats import t as student
    half = student.ppf(0.95, 119) * r["se"]
    assert r["ci90"][0] == pytest.approx(r["beta"] - half) and r["ci90"][1] == pytest.approx(r["beta"] + half)


def test_the_report_retires_an_index_when_the_upper_end_of_its_interval_is_below_a_tenth(monkeypatch):
    def fake(table, u, horizon=60):
        ci = {"NIFTY": [-0.30, 0.0999], "BANKNIFTY": [-0.30, 0.1001]}[u]
        return {"underlying": u, "status": "ok", "beta": -0.1, "se": 0.1, "p_one_sided": 0.9, "ci90": ci, "n": 999, "sessions": 120, "horizon": 60}
    monkeypatch.setattr(oi, "wall_test", fake)
    days = pd.DataFrame({"day": [str(d.date()) for d in pd.bdate_range("2026-10-26", periods=120)]})
    rep = oi.oi_report(days, "final")
    assert rep["confirmatory"] and rep["retired"] == {"NIFTY": True, "BANKNIFTY": False}
    assert rep["rejected"] == {"NIFTY": False, "BANKNIFTY": False}


def test_the_final_readout_needs_exactly_120_forward_sessions_and_the_interim_never_confirms(monkeypatch):
    monkeypatch.setattr(oi, "wall_test", lambda table, u, horizon=60: {"underlying": u, "status": "ok", "p_one_sided": 0.001, "ci90": [0.1, 0.5], "beta": 0.3})
    mk = lambda n, start="2026-10-26": pd.DataFrame({"day": [str(d.date()) for d in pd.bdate_range(start, periods=n)]})
    assert not oi.oi_report(mk(119), "final")["confirmatory"]
    full = oi.oi_report(mk(120), "final")
    assert full["confirmatory"] and full["rejected"] == {"NIFTY": True, "BANKNIFTY": True}
    assert not oi.oi_report(mk(120), "interim")["confirmatory"] and "rejected" not in oi.oi_report(mk(120), "interim")
    dev_only = pd.concat([mk(130, "2026-10-26"), mk(5, "2026-10-05")])                           # development sessions do not count
    assert oi.oi_report(dev_only, "final")["forward_sessions"] == 130
    assert oi.oi_report(mk(60), "interim")["forward_sessions"] == 60


def test_a_rerun_with_different_input_files_is_refused_even_if_the_table_would_be_the_same(tmp_path):
    tape, out = tape_dir(tmp_path), tmp_path / "out"
    man = oi.run_day(tape, DAY, out)
    f = tape / f"{DAY}_morning-1_chains.parquet"
    pd.read_parquet(f).to_parquet(f, compression="gzip")                                          # same rows, different bytes
    assert oi.sha256_file(f) != man["inputs"][f.name]
    with pytest.raises(RuntimeError, match="does not reproduce"):
        oi.run_day(tape, DAY, out)


def test_the_manifest_counts_the_usable_decisions_and_overlapping_files_change_nothing(tmp_path):
    tape = tape_dir(tmp_path)
    man = oi.run_day(tape, DAY, tmp_path / "out")
    assert man["usable60"] == {"NIFTY": 21, "BANKNIFTY": 21} and man["rows"] == {"NIFTY": 23, "BANKNIFTY": 23}          # 14:45 and 15:00 have no hour left
    both = pd.concat([pd.read_parquet(f) for f in sorted(tape.glob("*.parquet"))])
    dup = tmp_path / "tape2"
    dup.mkdir()
    pd.concat([both, both]).to_parquet(dup / f"{DAY}_all-1_chains.parquet")                       # every row twice
    again = oi.run_day(dup, DAY, tmp_path / "out2")
    a, b = pd.read_parquet(tmp_path / "out" / f"oi_{DAY}.parquet"), pd.read_parquet(tmp_path / "out2" / f"oi_{DAY}.parquet")
    pd.testing.assert_frame_equal(a[oi.FEATURES], b[oi.FEATURES])
    assert again["rows"] == man["rows"]


# ---- the advanced features, each against a value worked out here ---------------------------------------------------------
from scipy.stats import norm as _norm


def bs_gamma(S, K, T, sigma):
    """Black-Scholes gamma, written again here (rate and dividend zero), not imported from the module."""
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma ** 2 * T) / sq
    return _norm.pdf(d1) / (S * sq)


def T_years(minute, expiry=FAR, day=DAY):
    t = pd.Timestamp(f"{day} 09:15", tz=IST) + pd.Timedelta(minutes=minute)
    return max((pd.Timestamp(f"{expiry:%Y-%m-%d} 15:30", tz=IST) - t).total_seconds() / 60 / 525600, 60 / 525600)


def test_crossing_finder_by_hand():
    u = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    assert oi._nearest_crossing(u, np.array([-3.0, -1.0, 1.0, 2.0, 3.0])) == pytest.approx(-0.5)                  # one crossing, interpolated
    assert oi._nearest_crossing(u, np.array([-1.0, 2.0, 2.0, -1.0, -1.0])) == pytest.approx(2 / 3)                 # crossings at -5/3 and 2/3: the nearer to 0 wins
    assert oi._nearest_crossing(u, np.array([1.0, 1.0, 1.0, 1.0, 1.0])) != oi._nearest_crossing(u, np.array([1.0, 1.0, 1.0, 1.0, 1.0]))   # none: NaN
    two = oi._nearest_crossing(u, np.array([1.0, -1.0, -1.0, 1.0, 1.0]))                                         # crossings at -1.5 and 0.5: the nearer to 0
    assert two == pytest.approx(0.5)
    assert oi._nearest_crossing(u, np.array([-1.0, -1.0, 0.0, 1.0, 1.0])) == 0.0                                  # an exact zero is a crossing
    assert oi._nearest_crossing(u, np.array([1.0, 1.0, 1.0, 1.0, 0.0])) == 2.0                                    # and so is one at the end


def test_gamma_is_black_scholes_gamma_and_zero_without_a_volatility():
    ks = np.array([22000.0, 22500.0, 23000.0, 22500.0, 22500.0])
    g = oi._gamma(22500.0, ks, 0.05, np.array([0.15, 0.15, 0.15, np.nan, -0.1]))
    want = [bs_gamma(22500.0, k, 0.05, 0.15) for k in ks[:3]]
    np.testing.assert_allclose(g[:3], want, rtol=1e-12)
    assert g[3] == 0.0 and g[4] == 0.0 and g[1] > g[0] and g[1] > g[2]                                              # peaked at the money
    assert oi._gamma(22500.0, np.array([0.0]), 0.05, np.array([0.15]))[0] == 0.0


def test_the_gamma_ratio_is_independent_of_the_dealer_sign_and_of_the_level():
    calls3 = lambda k, side, K, base: 3e5 if (side == "c" and 22140 <= K <= 22860) else (1e5 if 22140 <= K <= 22860 else base)
    assert row_at(gen(oi_fn=calls3), 90).gex_ratio == pytest.approx((3 - 1) / (3 + 1))                              # calls carry 3x the OI at identical gamma
    puts3 = lambda k, side, K, base: 3e5 if (side == "p" and 22140 <= K <= 22860) else (1e5 if 22140 <= K <= 22860 else base)
    assert row_at(gen(oi_fn=puts3), 90).gex_ratio == pytest.approx(-0.5)
    assert row_at(gen(), 90).gex_ratio == pytest.approx(0.0, abs=1e-12)
    assert abs(row_at(gen(), 90).gex_ratio) <= 1


def test_the_gamma_wall_is_the_strike_with_the_most_gamma_weighted_oi_and_can_differ_from_the_oi_wall():
    r = row_at(gen(), 90)
    T, S = T_years(90), SPOT
    best_c = max((K for K in STRIKES if K > S), key=lambda K: bs_gamma(S, K, T, 0.15) * (1e6 if K == 23000 else 1e5))
    best_p = max((K for K in STRIKES if K < S), key=lambda K: bs_gamma(S, K, T, 0.15) * (1e6 if K == 22000 else 1e5))
    assert (best_c, best_p) == (23000.0, 22000.0)                                                                    # ten times the OI beats the gamma at four sigma
    assert r.gwall_c_dist == pytest.approx(500 / M0) and r.gwall_p_dist == pytest.approx(500 / M0)
    assert r.gwall_c_is_oi_wall == 1.0 and r.gwall_p_is_oi_wall == 1.0
    near = lambda k, side, K, base: 5e5 if (side == "c" and K == 22600) else (5e5 if (side == "p" and K == 22400) else 2e5 if K in (23000, 22000) else 1e5)
    r2 = row_at(gen(oi_fn=near), 90)
    want_c = max((K for K in STRIKES if K > S), key=lambda K: bs_gamma(S, K, T, 0.15) * near(90, "c", K, 1e5))
    want_p = max((K for K in STRIKES if K < S), key=lambda K: bs_gamma(S, K, T, 0.15) * near(90, "p", K, 1e5))
    assert (want_c, want_p) == (22600.0, 22400.0)
    assert r2.gwall_c_dist == pytest.approx((22600 - S) / M0) and r2.gwall_p_dist == pytest.approx((S - 22400) / M0)
    assert r2.call_wall == 22600.0 and r2.gwall_c_is_oi_wall == 1.0 and r2.gwall_p_is_oi_wall == 1.0                   # here the two agree
    split = lambda k, side, K, base: 8e5 if (side == "c" and K == 22600) else (9e5 if (side == "c" and K == 23000) else 1e5)
    gw = max((K for K in STRIKES if K > S), key=lambda K: bs_gamma(S, K, T, 0.15) * split(90, "c", K, 1e5))
    assert gw == 22600.0                                                                                              # by the independent gamma: the nearer strike wins
    r3 = row_at(gen(oi_fn=split), 90)
    assert r3.call_wall == 23000.0 and r3.gwall_c_dist == pytest.approx((22600 - S) / M0) and r3.gwall_c_is_oi_wall == 0.0    # the two walls disagree


def test_the_gamma_flip_is_where_call_heavy_gamma_turns_put_heavy():
    heavy = lambda k, side, K, base: (3e5 if K > 22500 else 1e5) if side == "c" else (3e5 if K < 22500 else 1e5)   # calls above spot, puts below
    r = row_at(gen(oi_fn=heavy), 90)
    T, S = T_years(90), SPOT
    net = lambda x: sum(bs_gamma(S + M0 * x, K, T, 0.15) * ((3e5 if K > 22500 else 1e5) - (3e5 if K < 22500 else 1e5)) * (1 if K != 22500 else 0) for K in STRIKES)
    lo, hi = -0.5, 0.5
    for _ in range(60):                                                                                              # bisection on the true curve
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if net(lo) * net(mid) > 0 else (lo, mid)
    assert not math.isnan(r.gex_flip_dist) and r.gex_flip_dist == pytest.approx((lo + hi) / 2, abs=0.02)             # grid step 0.1: interpolation error under 0.02
    one_sided = lambda k, side, K, base: 3e5 if side == "c" else 1e5
    assert math.isnan(row_at(gen(oi_fn=one_sided), 90).gex_flip_dist)                                                # calls everywhere: no flip inside the range


def test_wall_dynamics_are_measured_against_the_snapshots_30_and_60_minutes_earlier():
    def moving(k, side, K, base):                                                                                    # the call wall moves from 23000 to 22900 after minute 60
        if side == "c" and K == 22900:
            return 2e6 if k > 60 else 1e5
        return base if not (side == "c" and K == 23000 and k > 60) else 1e5
    r = row_at(gen(oi_fn=moving), 90)
    assert r.call_wall == 22900.0
    assert r.wall_c_shift30 == pytest.approx((22900 - 23000) / M0)                                                   # the wall 30 minutes ago was 23000
    assert r.wall_c_oi_growth30 == pytest.approx(2e6 / 1e5 - 1)
    assert r.wall_c_stable == 0.0                                                                                    # neither earlier snapshot had 22900 as the wall
    assert r.wall_p_shift30 == 0.0 and r.wall_p_oi_growth30 == pytest.approx(0.0) and r.wall_p_stable == 2.0           # the put wall did not move
    assert row_at(gen(), 90).wall_c_stable == 2.0 and row_at(gen(), 90).wall_c_shift30 == 0.0
    early = row_at(gen(), 45)                                                                                        # 10:00: 30 minutes ago exists, 60 does not
    assert early.wall_c_shift30 == 0.0 and math.isnan(early.wall_c_stable) and math.isnan(early.net_write_accel)
    first = row_at(gen(), 15)
    assert math.isnan(first.wall_c_shift30) and math.isnan(first.wall_c_oi_growth30) and math.isnan(first.maxpain_shift30)


def test_max_pain_and_its_shift_by_hand():
    ks = np.array([100.0, 110.0, 120.0])
    # settling at 100: puts at 120 pay 20 each; at 110: calls at 100 pay 10 each and puts 10 each; at 120: calls pay 20 each
    assert oi._max_pain(ks, np.array([5.0, 0.0, 0.0]), np.array([0.0, 0.0, 10.0])) == 120.0                        # 200, 150, 100
    assert oi._max_pain(ks, np.array([10.0, 0.0, 0.0]), np.array([0.0, 0.0, 5.0])) == 100.0                        # 100, 150, 200
    assert oi._max_pain(ks, np.array([0.0, 7.0, 0.0]), np.array([0.0, 7.0, 0.0])) == 110.0                          # OI at 110 only: pain is least there
    skew = lambda k, side, K, base: 5e5 if (side == "c" and K == 22800 and k > 60) else base
    r = row_at(gen(oi_fn=skew), 90)
    ks_ = STRIKES
    cenow = np.array([5e5 if K == 22800 else (1e6 if K == 23000 else 1e5) for K in ks_])
    ceold = np.array([1e6 if K == 23000 else 1e5 for K in ks_])
    pe_ = np.array([1e6 if K == 22000 else 1e5 for K in ks_])
    assert r.maxpain_shift30 == pytest.approx((oi._max_pain(ks_, cenow, pe_) - oi._max_pain(ks_, ceold, pe_)) / M0)


def test_net_write_acceleration_is_this_half_hours_net_writing_minus_the_previous_ones():
    def f(k, side, K, base):                                                                                         # writing in the half hour before minute 60 and again before 90
        if side == "c" and K == 22600:
            return 3e5 if k > 60 else (2e5 if k > 30 else 1e5)
        return base
    price = lambda k, side, K: (-5.0 if k > 60 else -3.0 if k > 30 else 0.0) if (side == "c" and K == 22600) else 0.0
    f.price = price
    r = row_at(gen(oi_fn=f), 90)
    near_now = 6e5 + 3e5                                                                                             # seven strikes near spot, 22600 at 3e5 now
    near_prev = 6e5 + 2e5                                                                                            # and at 2e5 at minute 60
    now_write, prev_write = (3e5 - 2e5) / near_now, (2e5 - 1e5) / near_prev
    assert r.net_write_accel == pytest.approx(now_write - prev_write)


def test_concentration_measures_by_hand():
    h, e, t3 = oi._conc(np.full(13, 1e5))
    assert h == pytest.approx(0.0, abs=1e-12) and e == pytest.approx(1.0) and t3 == pytest.approx(3 / 13)             # perfectly even
    h, e, t3 = oi._conc(np.array([1e6] + [1.0] * 12))
    assert h > 0.99 and e < 0.05 and t3 > 0.999                                                                       # all in one strike
    w = np.array([5.0, 3.0, 1.0, 1.0])
    p = w / w.sum()
    h, e, t3 = oi._conc(w)
    assert h == pytest.approx(((p ** 2).sum() - 0.25) / 0.75) and e == pytest.approx(-(p * np.log(p)).sum() / math.log(4)) and t3 == pytest.approx(0.9)
    assert all(math.isnan(x) for x in oi._conc(np.array([1.0, 2.0, 0.0, 0.0])))                                        # fewer than three strikes with OI
    assert all(math.isnan(x) for x in oi._conc(np.array([np.nan, 1.0, 1.0])))


def test_concentration_and_pin_share_in_the_chain():
    r = row_at(gen(), 90)                                                                                            # 15 strikes in the band, all 1e5 on both sides
    assert r.hhi_c == pytest.approx(0.0, abs=1e-12) and r.entropy_c == pytest.approx(1.0) and r.top3_c == pytest.approx(3 / 15)
    assert r.pin_share == pytest.approx(3 / 15)                                                                       # 22450, 22500, 22550 are within half a move (60) of spot
    spike = lambda k, side, K, base: 9e5 if (side == "c" and K == 22500) else (1e5 if side == "c" else base)
    r2 = row_at(gen(oi_fn=spike), 90)
    p = np.array([9e5] + [1e5] * 14)
    p = p / p.sum()
    assert r2.hhi_c == pytest.approx(((p ** 2).sum() - 1 / 15) / (1 - 1 / 15)) and r2.hhi_c > r.hhi_c and r2.entropy_c < r.entropy_c


def test_pin_share_by_hand():
    spike = lambda k, side, K, base: 9e5 if (side == "c" and K == 22500) else (1e5 if side == "c" else base)
    r = row_at(gen(oi_fn=spike), 90)
    near_calls = 9e5 + 1e5 + 1e5                                                                                      # 22450, 22500, 22550
    near_puts = 3e5
    total_calls = 9e5 + 14 * 1e5
    total_puts = 15 * 1e5
    assert r.pin_share == pytest.approx((near_calls + near_puts) / (total_calls + total_puts))


def test_spreads_and_queue_imbalance_at_the_money_and_at_the_walls():
    r = row_at(gen(), 90)
    assert r.spread_atm_c == pytest.approx(1.0 / 60.0) and r.spread_atm_p == pytest.approx(1.0 / 60.0)
    wall_mid = 60 * math.exp(-500 / 200)
    assert r.spread_wall_c == pytest.approx(1.0 / wall_mid) and r.spread_wall_p == pytest.approx(1.0 / wall_mid)
    assert r.qimb_atm_c == 0.0 and r.qimb_wall_p == 0.0
    df = edit(gen(), 90, strike=22500.0, ce_bidq=300.0, ce_askq=100.0, pe_bidq=10.0, pe_askq=30.0)
    df = edit(df, 90, strike=23000.0, ce_bidq=0.0, ce_askq=50.0)
    r2 = row_at(df, 90)
    assert r2.qimb_atm_c == pytest.approx(0.5) and r2.qimb_atm_p == pytest.approx(-0.5) and r2.qimb_wall_c == pytest.approx(-1.0)
    crossed = edit(gen(), 90, strike=22500.0, ce_bid=70.0, ce_ask=60.0)
    assert math.isnan(row_at(crossed, 90).spread_atm_c)                                                               # a crossed quote has no spread
    noq = gen().drop(columns=["ce_bidq", "ce_askq", "pe_bidq", "pe_askq"])                                            # older archives have no sizes
    r3 = row_at(noq, 90)
    assert math.isnan(r3.qimb_atm_c) and r3.spread_atm_c == pytest.approx(1 / 60)
    assert math.isnan(oi._qimb(0.0, 0.0)) and math.isnan(oi._qimb(np.nan, 5.0)) and math.isnan(oi._spread_pct(0.0, 1.0))


def test_volume_against_open_interest_and_the_last_half_hour():
    vol = lambda k, side, K: (2000.0 if side == "c" else 1000.0) * (1 + 0.25 * (k > 60)) if 22140 <= K <= 22860 else 0.0
    r = row_at(gen(vol_fn=vol), 90)
    assert r.pcr_vol == pytest.approx(0.5)                                                                             # puts traded half as much as calls
    assert r.turnover_c == pytest.approx(15 * 2500.0 / (15 * 1e5)) and r.turnover_p == pytest.approx(15 * 1250.0 / (15 * 1e5))
    assert r.vol30_pcr == pytest.approx(250.0 / 500.0)                                                                 # in the last 30 minutes: +500 a call strike, +250 a put strike
    quiet = row_at(gen(), 90)
    assert math.isnan(quiet.pcr_vol) and quiet.turnover_c == 0.0 and quiet.turnover_p == 0.0                          # nothing traded: no put-call ratio, zero turnover
    reset = lambda k, side, K: 5000.0 if k <= 60 else 100.0                                                            # the running total fell: a reset, no reading
    assert math.isnan(row_at(gen(vol_fn=reset), 90).vol30_pcr)


def test_wall_defense_is_what_traded_at_the_wall_over_its_oi():
    vol = lambda k, side, K: (5000.0 if k > 60 else 1000.0) if (side == "c" and K == 23000) else (400.0 if (side == "p" and K == 22000) else 0.0)
    r = row_at(gen(vol_fn=vol), 90)
    assert r.wall_defense_c == pytest.approx((5000.0 - 1000.0) / 1e6) and r.wall_defense_p == pytest.approx(0.0)
    assert math.isnan(row_at(gen(vol_fn=vol), 15).wall_defense_c)                                                      # no earlier snapshot


def test_forward_basis_and_the_skew_of_the_smile_by_hand():
    df = edit(gen(), 90, strike=22500.0, ce_bid=64.5, ce_ask=65.5, ce_ltp=65.0)                                        # the call 5 dearer than parity
    assert row_at(df, 90).fwd_basis_bps == pytest.approx(5 / 22500 * 1e4)
    assert row_at(gen(), 90).fwd_basis_bps == pytest.approx(0.0, abs=1e-9)
    iv = lambda k, side, K: 15.0 + (0.01 * (22500 - K) if side == "p" else 0.005 * (K - 22500))
    r = row_at(gen(iv_fn=iv), 90)
    assert r.iv == pytest.approx(15.0)
    iv_put, iv_call = 15.0 + 0.01 * (22500 - (SPOT - M0)), 15.0 + 0.005 * ((SPOT + M0) - 22500)
    assert r.rr_1m == pytest.approx(iv_put - iv_call) and r.fly_1m == pytest.approx((iv_put + iv_call) / 2 - 15.0)
    narrow = gen(iv_fn=iv)
    narrow = narrow[(narrow["strike"] >= 22450) & (narrow["strike"] <= 22550)]                                          # strikes do not reach one move away
    assert math.isnan(oi._iv_at(oi._snapshot(narrow[narrow["ts"] == narrow["ts"].iloc[0]]), SPOT - M0, "p"))


def test_the_next_expiry_gives_the_term_spread_and_the_roll_share():
    next_exp = FAR + pd.Timedelta(days=7)
    both = pd.concat([gen(), gen(expiry=next_exp, iv=16.0, oi_fn=lambda k, s, K, b: 5e4)], ignore_index=True)
    t = oi.decision_table(both, DAY, "NIFTY")
    r = t[t["m"] == 90].iloc[0]
    assert r.expiry == str(FAR.date())
    assert r.iv_term == pytest.approx(16.0 - 15.0)
    assert r.oi_roll_share == pytest.approx((15 * 2 * 5e4) / (15 * 2 * 5e4 + 15 * 2e5))                                # next expiry's band OI over both
    alone = row_at(gen(), 90)
    assert math.isnan(alone.iv_term) and math.isnan(alone.oi_roll_share)
    flat = pd.concat([gen(), gen(expiry=next_exp)], ignore_index=True)
    assert oi.decision_table(flat, DAY, "NIFTY").query("m == 90").iloc[0].iv_term == pytest.approx(0.0)


def test_every_advanced_feature_is_listed_exactly_once_and_recorded():
    assert len(oi.ADVANCED) == len(set(oi.ADVANCED)) == 40 and set(oi.ADVANCED) <= set(oi.COLUMNS) and set(oi.ADVANCED) <= set(oi.FEATURES)
    r = row_at(gen(), 90)
    assert set(oi.ADVANCED) <= set(r.index)
    t = oi.decision_table(gen(), DAY, "NIFTY")
    assert list(t.columns) == oi.COLUMNS + oi.LABELS


# ---- gaps found by mutation testing the advanced features -----------------------------------------------------------------
def indep_max_pain(ks, ce, pe):
    """Max pain written out slowly: the settle that costs option writers least."""
    cost = [sum(max(x - K, 0) * c for K, c in zip(ks, ce)) + sum(max(K - x, 0) * q for K, q in zip(ks, pe)) for x in ks]
    return ks[int(np.argmin(cost))]


def test_advanced_a_locked_quote_has_a_zero_spread_and_a_crossed_one_has_none():
    assert oi._spread_pct(10.0, 10.0) == 0.0 and math.isnan(oi._spread_pct(10.0, 9.99)) and math.isnan(oi._spread_pct(-1.0, 2.0))


def test_advanced_the_smile_is_not_extrapolated_on_either_side():
    df = gen(iv_fn=lambda k, side, K: 15.0 + 0.01 * (K - 22500))
    snap = oi._snapshot(df[(df["strike"] >= 22450) & (df["strike"] <= 22550) & (df["ts"] == df["ts"].iloc[0])])
    assert not math.isnan(oi._iv_at(snap, 22500.0, "c")) and not math.isnan(oi._iv_at(snap, 22450.0, "p"))      # the edges are inside
    assert math.isnan(oi._iv_at(snap, 22551.0, "c")) and math.isnan(oi._iv_at(snap, 22449.0, "p"))               # one point beyond either edge is not
    assert oi._iv_at(snap, 22525.0, "c") == pytest.approx(15.0 + 0.01 * 25)


def test_advanced_a_snapshot_is_used_for_exactly_150_seconds():
    sn = oi.Snapshots(gen(minutes=[0]))                                               # one snapshot, so the age is the distance from it
    t0 = int(sn.keys[0])
    got = oi._asof(sn, sn.keys, t0 + 150 * 10 ** 9)
    assert got is not None and got[2] == pytest.approx(150.0) and got[1] == SPOT
    assert oi._asof(sn, sn.keys, t0 + 151 * 10 ** 9) is None and oi._asof(sn, sn.keys, t0 - 1) is None


def test_advanced_gamma_is_not_evaluated_closer_than_an_hour_to_expiry():
    """30 minutes before expiry, gamma is taken at one hour. The OI ratio below sits between what 30 minutes and 60 minutes of gamma would prefer."""
    S = SPOT
    g60 = bs_gamma(S, 22600.0, 60 / 525600, 0.15) / bs_gamma(S, 22800.0, 60 / 525600, 0.15)
    g30 = bs_gamma(S, 22600.0, 30 / 525600, 0.15) / bs_gamma(S, 22800.0, 30 / 525600, 0.15)
    assert g60 != pytest.approx(g30, rel=0.05)
    ratio = math.sqrt(g60 * g30)                                                     # OI(22800) / OI(22600): between the two preferences
    f = lambda k, side, K, base: 1e5 * ratio if (side == "c" and K == 22800) else (1e5 if side == "c" else base)
    df = gen(oi_fn=f, minutes=[90])
    snap = oi._snapshot(df)
    base = oi.snapshot_features(snap, None, S, 30.0)
    out = oi.advanced_features(snap, S, base["move"], 30.0, base)
    want = 22600.0 if g60 > ratio else 22800.0                                       # gamma(22600) x OI vs gamma(22800) x OI at one hour
    other = 22800.0 if want == 22600.0 else 22600.0
    assert (22600.0 if g30 > ratio else 22800.0) == other                            # and the unfloored half hour would choose the other
    assert out["gwall_c_dist"] == pytest.approx((want - S) / base["move"])


def test_advanced_the_gamma_flip_far_from_spot_is_found_at_its_true_place():
    """Same-day expiry, so gamma is narrow and the flip sits near the strike where call-heavy OI turns put-heavy. Written out by brute force on a
    fine grid, independent of the module's 61-step grid and its interpolation."""
    exp = pd.Timestamp(DAY)
    for thr, want_sign in ((22350, -1), (22650, 1)):
        sk = lambda k, side, K, base, thr=thr: (3e5 if K >= thr else 1e5) if side == "c" else (3e5 if K < thr else 1e5)
        r = row_at(gen(oi_fn=sk, expiry=exp), 90)
        T = T_years(90, expiry=exp)
        net = lambda x: sum(bs_gamma(SPOT + M0 * x, K, T, 0.15) * (sk(0, "c", K, 0) - sk(0, "p", K, 0)) for K in STRIKES)
        us = np.linspace(-3, 3, 6001)
        v = np.array([net(u) for u in us])
        cross = [us[i] for i in range(len(us) - 1) if v[i] * v[i + 1] < 0]
        assert len(cross) == 1 and np.sign(cross[0]) == want_sign and abs(cross[0]) > 1.0
        assert r.gex_flip_dist == pytest.approx(cross[0], abs=0.01)


def test_advanced_the_put_wall_and_the_past_wall_are_measured_on_their_own_terms():
    def moves(k, side, K, base):                                                      # the put wall moves up from 22000 to 22100 after minute 60
        if side == "p" and K == 22100:
            return 2e6 if k > 60 else 1e5
        if side == "p" and K == 22000 and k > 60:
            return 1e5
        return base
    r = row_at(gen(oi_fn=moves), 90)
    assert r.put_wall == 22100.0 and r.wall_p_shift30 == pytest.approx((22100 - 22000) / M0)
    assert r.wall_p_oi_growth30 == pytest.approx(2e6 / 1e5 - 1) and r.wall_p_stable == 0.0 and r.wall_c_shift30 == 0.0
    # the past wall is the wall as it stood against the spot of the time: spot was 22300, the 22350 call OI above it was the wall
    def spot_fn(k):
        return 22300.0 if k <= 60 else 22500.0
    big = lambda k, side, K, base: 5e6 if (side == "c" and K == 22350) else base
    r2 = row_at(gen(spot_fn=spot_fn, oi_fn=big), 90)
    assert r2.call_wall == 23000.0 and r2.wall_c_shift30 == pytest.approx((23000 - 22350) / M0)                    # not 0: against 22500 the old wall would have been 23000 too


def test_advanced_max_pain_shift_has_the_sign_of_the_move_of_max_pain():
    f = lambda k, side, K, base: 5e6 if (side == "p" and K == 22800 and k > 60) else base
    r = row_at(gen(oi_fn=f), 90)
    ce = [1e6 if K == 23000 else 1e5 for K in STRIKES]
    pe_old = [1e6 if K == 22000 else 1e5 for K in STRIKES]
    pe_new = [5e6 if K == 22800 else (1e6 if K == 22000 else 1e5) for K in STRIKES]
    want = (indep_max_pain(list(STRIKES), ce, pe_new) - indep_max_pain(list(STRIKES), ce, pe_old)) / M0
    assert want != 0.0 and r.maxpain_shift30 == pytest.approx(want)


def test_advanced_wall_stability_counts_the_older_snapshot_separately():
    def f(k, side, K, base):                                                          # the wall moved from 23000 to 22900 at minute 45 and stayed
        if side == "c" and K == 22900:
            return 2e6 if k > 45 else 1e5
        if side == "c" and K == 23000 and k > 45:
            return 1e5
        return base
    r = row_at(gen(oi_fn=f), 90)
    assert r.call_wall == 22900.0 and r.wall_c_stable == 1.0 and r.wall_p_stable == 2.0       # 30 minutes ago it was already 22900, 60 minutes ago it was not


def test_advanced_acceleration_nets_call_writing_against_put_writing():
    def both(k, side, K, base):
        if K == (22600 if side == "c" else 22400) and k > 60:
            return 3e5
        return base
    both.price = lambda k, side, K: -5.0 if (k > 60 and K == (22600 if side == "c" else 22400)) else 0.0
    assert row_at(gen(oi_fn=both), 90).net_write_accel == pytest.approx(0.0, abs=1e-12)              # calls and puts written alike: no net writing
    def puts(k, side, K, base):
        return 3e5 if (side == "p" and K == 22400 and k > 60) else base
    puts.price = lambda k, side, K: -5.0 if (side == "p" and K == 22400 and k > 60) else 0.0
    assert row_at(gen(oi_fn=puts), 90).net_write_accel == pytest.approx(-2e5 / 9e5)                  # net put writing is negative


def test_advanced_a_single_strikes_volume_counter_that_fell_voids_the_reading():
    def vol(k, side, K):
        if side == "c" and K == 22500:
            return 5000.0 if k <= 60 else 100.0                                       # this strike's running total was reset
        return 1000.0 if k <= 60 else 1500.0 if 22140 <= K <= 22860 else 1000.0       # every other strike in the band traded 500
    r = row_at(gen(vol_fn=vol), 90)
    assert math.isnan(r.vol30_pcr)
    ok = row_at(gen(vol_fn=lambda k, side, K: 1000.0 if k <= 60 else 1500.0), 90)
    assert ok.vol30_pcr == pytest.approx(1.0)


def test_advanced_a_wall_whose_volume_counter_fell_has_no_defense_reading():
    vol = lambda k, side, K: (5000.0 if k <= 60 else 100.0) if (side == "c" and K == 23000) else 0.0
    assert math.isnan(row_at(gen(vol_fn=vol), 90).wall_defense_c)
    grow = lambda k, side, K: (100.0 if k <= 60 else 5000.0) if (side == "c" and K == 23000) else 0.0
    assert row_at(gen(vol_fn=grow), 90).wall_defense_c == pytest.approx(4900.0 / 1e6)


def test_the_report_says_what_kind_of_read_out_it_is_and_marks_a_short_test_insufficient():
    rep = {"spec": oi.SPEC, "readout": "interim", "forward_sessions": 12, "confirmatory": False, "note": "interim, descriptive: an estimate and its interval, not a finding",
           "tests": {"NIFTY": {"status": "ok", "underlying": "NIFTY", "n": 400, "sessions": 12, "beta": 0.123, "se": 0.05, "t": 2.46, "p_one_sided": 0.016,
                               "ci90": [0.03, 0.21], "controls": {"p_iv": -0.4, "p_iv_sq": 0.1, "time": 0.0, "time_sq": 0.0}},
                     "BANKNIFTY": {"status": "insufficient: needs at least 10 sessions and 30 decisions", "n": 12, "sessions": 3}}}
    out = oi.render_report(rep).splitlines()
    assert "interim" in out[0] and "not a finding" in out[1]
    assert "beta +0.123" in out[2] and "[+0.030, +0.210]" in out[2] and "12 sessions, 400 decisions" in out[2]
    assert out[3].startswith("  BANKNIFTY: insufficient") and "3 sessions, 12 decisions" in out[3]
    fin = {**rep, "readout": "final", "confirmatory": True, "rejected": {"NIFTY": True}, "retired": {"NIFTY": False, "BANKNIFTY": False}}
    fin.pop("note")
    assert "rejected at the family level: True; retired by the kill rule: False" in oi.render_report(fin)


def test_the_spec_pins_the_code_that_makes_the_tables():
    """Change a definition and this fails: the spec then names other code than the module, and the sessions graded so far are a different experiment."""
    spec = json.loads((Path(__file__).resolve().parents[1] / "docs" / "prereg" / "oi_shadow_v1.json").read_text())
    assert spec["name"] == oi.SPEC and spec["code"]["run"] == oi.RUN_VERSION and spec["code"]["module"] == "quantdesk/ml/oi.py"
    assert spec["code"]["code_sha256"] == oi.code_sha256()


# ---- the command line -----------------------------------------------------------------------------------------------------
def _tape(tmp_path, day=DAY, **kw):
    folder = tmp_path / "tape"
    folder.mkdir(exist_ok=True)
    gen(day=day, minutes=range(0, 375, 5), **kw).to_parquet(folder / f"{day}_0_chains.parquet", index=False)
    return folder


def test_cli_grades_a_session_once_and_reports_without_a_claim(tmp_path, capsys):
    from quantdesk.cli import main
    tape, out = _tape(tmp_path), tmp_path / "tables"
    main(["ml", "oi", "--source", str(tape), "--day", DAY, "--out", str(out)])
    line = capsys.readouterr().out
    assert DAY in line and "NIFTY" in line and "code " + oi.code_sha256()[:12] in line
    assert (out / f"oi_{DAY}.parquet").exists() and (out / f"oi_{DAY}.json").exists()
    main(["ml", "oi", "--source", str(tape), "--day", DAY, "--out", str(out)])                       # a rerun reproduces it and changes nothing
    capsys.readouterr()
    main(["ml", "oi-report", "--out", str(out)])
    rep = capsys.readouterr().out
    assert "interim read-out" in rep and "not a finding" in rep and "insufficient" in rep               # one development session: nothing to estimate


def test_cli_refuses_a_rerun_that_does_not_reproduce_and_missing_arguments(tmp_path):
    from quantdesk.cli import main
    tape, out = _tape(tmp_path), tmp_path / "tables"
    main(["ml", "oi", "--source", str(tape), "--day", DAY, "--out", str(out)])
    changed = tmp_path / "tape2"
    changed.mkdir()
    gen(day=DAY, minutes=range(0, 375, 5), oi_fn=lambda k, side, K, base: base * 2).to_parquet(changed / f"{DAY}_0_chains.parquet", index=False)
    with pytest.raises(SystemExit, match="does not reproduce"):
        main(["ml", "oi", "--source", str(changed), "--day", DAY, "--out", str(out)])
    with pytest.raises(SystemExit, match="--source"):
        main(["ml", "oi", "--day", DAY, "--out", str(out)])
    with pytest.raises(SystemExit, match="no chain files"):
        main(["ml", "oi", "--source", str(tape), "--day", "2026-10-14", "--out", str(out)])


def test_cli_report_refuses_sessions_made_by_other_code(tmp_path):
    from quantdesk.cli import main
    tape, out = _tape(tmp_path), tmp_path / "tables"
    main(["ml", "oi", "--source", str(tape), "--day", DAY, "--out", str(out)])
    mp = out / f"oi_{DAY}.json"
    m = json.loads(mp.read_text())
    m["code_sha256"] = "0" * 64
    mp.write_text(json.dumps(m))
    with pytest.raises(SystemExit, match="other code"):
        main(["ml", "oi-report", "--out", str(out)])


def test_cli_refuses_an_output_folder_inside_a_git_working_tree(tmp_path):
    from quantdesk.cli import main
    repo = Path(oi.__file__).resolve().parents[2]
    with pytest.raises(SystemExit, match="ml oi: .*inside a git working tree"):
        main(["ml", "oi", "--source", str(_tape(tmp_path)), "--day", DAY, "--out", str(repo / "docs" / "oi_tables_probe")])
    assert not (repo / "docs" / "oi_tables_probe").exists()


# ---- changes made at the research review: a fixed Holm family, the first 120 sessions, and the time-of-day and nonlinear controls ----------------
def _ok(p):
    return {"status": "ok", "p_one_sided": p, "ci90": [0.0, 0.5], "beta": 0.3}


def test_holm_is_a_family_of_two_even_when_one_index_has_no_test(monkeypatch):
    days = pd.DataFrame({"day": [str(d.date()) for d in pd.bdate_range("2026-10-26", periods=120)]})
    monkeypatch.setattr(oi, "wall_test", lambda table, u, horizon=60: _ok(0.03) if u == "NIFTY" else {"status": "insufficient: needs at least 10 sessions and 30 decisions", "n": 0, "sessions": 0})
    rep = oi.oi_report(days, "final")
    assert rep["rejected"] == {"NIFTY": False, "BANKNIFTY": False}                  # 0.03 > 0.05 / 2: it would pass only as a family of one
    assert rep["retired"] == {"NIFTY": False, "BANKNIFTY": False}
    monkeypatch.setattr(oi, "wall_test", lambda table, u, horizon=60: _ok(0.02) if u == "NIFTY" else {"status": "insufficient: x", "n": 0, "sessions": 0})
    assert oi.oi_report(days, "final")["rejected"] == {"NIFTY": True, "BANKNIFTY": False}


def test_the_final_readout_uses_the_first_120_forward_sessions_only(monkeypatch):
    seen = {}
    def spy(table, u, horizon=60):
        seen[u] = sorted(table.loc[table["day"] >= oi.FORWARD_START, "day"].unique())
        return _ok(0.001)
    monkeypatch.setattr(oi, "wall_test", spy)
    days = [str(d.date()) for d in pd.bdate_range("2026-10-26", periods=130)]
    rep = oi.oi_report(pd.DataFrame({"day": days + ["2026-10-05"]}), "final")
    assert seen["NIFTY"] == days[:120] and seen["BANKNIFTY"] == days[:120]
    assert rep["forward_sessions"] == 130 and rep["sessions_used"] == 120 and rep["confirmatory"]
    seen.clear()
    oi.oi_report(pd.DataFrame({"day": days}), "interim")
    assert seen["NIFTY"] == days                                                    # the interim look is on everything so far


def _confounded(sessions, seed, strength_tracks_time, curve):
    """Containment depends on the time of day (a U) and/or a quadratic in p_iv; wall strength has no effect at all, but tracks the time of day."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in [str(x.date()) for x in pd.bdate_range("2026-10-26", periods=sessions)]:
        a = rng.normal(0, 0.05)
        for m in oi.DECISIONS:
            br = oi.STRENGTH_BREAKS["NIFTY"]
            frac = rng.uniform(0, 1) if not strength_tracks_time else float(np.clip(((m - 180) / 180) ** 2 + rng.normal(0, 0.15), 0, 1))
            strength = br[0] + frac * (br[-1] - br[0])
            p = rng.uniform(0.3, 0.8)
            prob = np.clip(p + a + curve(m, p), 0.01, 0.99)
            rows.append({"underlying": "NIFTY", "day": d, "m": m, "strength": strength, "p_iv60": p, "contained60": float(rng.random() < prob), "p_iv30": p, "contained30": 1.0})
    return pd.DataFrame(rows)


def test_a_time_of_day_pattern_that_wall_strength_merely_tracks_is_not_credited_to_the_wall():
    curve = lambda m, p: 0.25 * (((m - 180) / 180) ** 2 - 0.33)                       # more containment at the ends of the day, none from the wall
    t = _confounded(150, 31, True, curve)
    r = oi.wall_test(t, "NIFTY")
    assert r["status"] == "ok" and abs(r["beta"]) < 2.5 * r["se"] and abs(r["controls"]["time_sq"] - 0.25) < 0.08
    d = t[(t["p_iv60"] >= 0.15) & (t["p_iv60"] <= 0.90)]
    y = (d["contained60"] - d["p_iv60"]).to_numpy(float)
    naive = oi.fit_within(y, np.column_stack([oi.rank_strength(d["strength"], "NIFTY"), d["p_iv60"].to_numpy(float)]), d["day"].to_numpy())
    assert naive["beta"][0] > 4 * naive["se"][0]                                       # without the time controls the same data would "confirm" the wall


def test_a_quadratic_dependence_on_the_implied_probability_is_absorbed():
    curve = lambda m, p: 0.5 * (p - 0.55) ** 2 - 0.02
    r = oi.wall_test(_confounded(200, 32, False, curve), "NIFTY")
    assert r["status"] == "ok" and abs(r["controls"]["p_iv_sq"] - 0.5) < 0.2 and abs(r["beta"]) < 2.5 * r["se"]


def test_the_report_lists_the_weekdays_that_have_no_table(monkeypatch):
    monkeypatch.setattr(oi, "wall_test", lambda table, u, horizon=60: {"status": "insufficient: x", "n": 0, "sessions": 0})
    days = [str(d.date()) for d in pd.bdate_range("2026-10-26", periods=6)]
    days.remove("2026-10-28")
    rep = oi.oi_report(pd.DataFrame({"day": days + ["2026-10-05"]}), "interim")                  # a development day is not a gap
    assert rep["weekdays_without_tables"] == ["2026-10-28"]
    assert oi.oi_report(pd.DataFrame({"day": ["2026-10-05"]}), "interim")["weekdays_without_tables"] == []
    assert "1 weekday(s)" in oi.render_report({**rep, "tests": {}})


def test_a_table_edited_after_it_was_written_does_not_load_and_an_interrupted_write_is_replaced(tmp_path):
    tape, out = _tape(tmp_path), tmp_path / "tables"
    oi.run_day(tape, DAY, out)
    assert len(oi.load_tables(out)) > 0
    tp = out / f"oi_{DAY}.parquet"
    t = pd.read_parquet(tp)
    t.loc[t.index[0], "contained60"] = 1.0 - (0.0 if pd.isna(t.loc[t.index[0], "contained60"]) else t.loc[t.index[0], "contained60"])
    t.to_parquet(tp, index=False)                                                                 # edited by hand
    with pytest.raises(RuntimeError, match="not the table that was written"):
        oi.load_tables(out)
    other = tmp_path / "tables2"
    oi.run_day(tape, DAY, other)
    (other / f"oi_{DAY}.json").unlink()                                                           # a crash after the parquet, before the manifest
    (other / f"oi_{DAY}.parquet").write_bytes(b"partial")
    man = oi.run_day(tape, DAY, other)
    assert len(oi.load_tables(other)) > 0 and man["table_sha256"] == oi.sha256_file(other / f"oi_{DAY}.parquet")
    (other / f"oi_{DAY}.parquet").unlink()
    with pytest.raises(RuntimeError, match="table was removed"):
        oi.run_day(tape, DAY, other)


def test_a_rerun_must_reproduce_labels_and_keys_not_only_features(tmp_path):
    tape, out = _tape(tmp_path), tmp_path / "tables"
    oi.run_day(tape, DAY, out)
    tp = out / f"oi_{DAY}.parquet"
    t = pd.read_parquet(tp)
    t["contained60"] = 1.0 - t["contained60"].fillna(0.5)                                          # features intact, labels changed
    t.to_parquet(tp, index=False)
    with pytest.raises(RuntimeError, match="does not reproduce"):
        oi.run_day(tape, DAY, out)


def test_tables_are_refused_when_the_code_is_not_the_code_the_spec_pins(tmp_path, monkeypatch):
    tape, out = _tape(tmp_path), tmp_path / "tables"
    oi.run_day(tape, DAY, out)
    monkeypatch.setattr(oi, "pinned_code_sha256", lambda: "f" * 64)
    with pytest.raises(RuntimeError, match="not the code the registered spec pins"):
        oi.load_tables(out)


def test_the_code_hash_covers_the_analysis_and_the_gamma_constants(monkeypatch):
    base = oi.code_sha256()
    for name in ("MIN_T_YEARS", "FLIP_STEPS"):
        monkeypatch.setattr(oi, name, getattr(oi, name) * 2)
        assert oi.code_sha256() != base
        monkeypatch.undo()
    src = oi.inspect.getsource(oi.code_sha256)
    for fn in ("wall_test", "fit_within", "holm", "oi_report", "_spot_path", "tape_files", "quarantine_report", "run_day"):
        assert fn in src


def test_a_row_of_another_source_never_displaces_a_kotak_row(tmp_path):
    clean = gen(minutes=range(0, 375, 5))
    other = clean.copy()
    other["source"] = "yfinance"
    other["ce_oi"] = 7.0                                                             # same keys, different content, listed first
    folder = tmp_path / "tape"
    folder.mkdir()
    pd.concat([other, clean], ignore_index=True).to_parquet(folder / f"{DAY}_0_chains.parquet", index=False)
    mixed = oi.run_day(folder, DAY, tmp_path / "a")
    ref_dir = tmp_path / "tape2"
    ref_dir.mkdir()
    clean.to_parquet(ref_dir / f"{DAY}_0_chains.parquet", index=False)
    oi.run_day(ref_dir, DAY, tmp_path / "b")
    a, b = pd.read_parquet(tmp_path / "a" / f"oi_{DAY}.parquet"), pd.read_parquet(tmp_path / "b" / f"oi_{DAY}.parquet")
    assert len(a) > 0 and a.drop(columns="ts").equals(b.drop(columns="ts")) and mixed["rows"] == oi.run_day(ref_dir, DAY, tmp_path / "b")["rows"]


def test_a_missing_spec_makes_the_pin_check_an_error_not_a_skip(monkeypatch, tmp_path):
    tape, out = _tape(tmp_path), tmp_path / "tables"
    oi.run_day(tape, DAY, out)
    monkeypatch.setattr(oi, "__file__", str(tmp_path / "a" / "b" / "oi.py"))
    with pytest.raises(FileNotFoundError, match="pin cannot be checked"):
        oi.load_tables(out)
