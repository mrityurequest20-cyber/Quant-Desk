"""Kalman filtering (quantdesk/paper/kalman.py, owner, 13 Nov 2026: "Kalman filtering: smoothing the futures premium and trend"). Synthetic series with a known trend, known
noise and none: the filter must find the first, ignore the second, and say nothing about a random walk more often than its own 5% says it will."""
from __future__ import annotations

import math
import random

from quantdesk.paper import auto2 as A2
from quantdesk.paper import kalman as KF
from quantdesk.paper import marketread as MR
from quantdesk.paper import regimes as RG


def walk(n, drift, sd, noise, seed):
    rng, lvl, out = random.Random(seed), 10.0, []
    for _ in range(n):
        lvl += drift + rng.gauss(0, sd)
        out.append(lvl + rng.gauss(0, noise))
    return out


def test_it_recovers_a_known_trend_and_its_significance():
    f = KF.fit(walk(390, 2e-4, 3e-4, 2e-4, 1))
    tr = f["filter"].trend()
    assert abs(tr["slope"] - 2e-4) < 6e-5 and tr["t"] > 4 and tr["vote"] == 1
    tr = KF.fit(walk(390, -2e-4, 3e-4, 2e-4, 2))["filter"].trend()
    assert tr["vote"] == -1


def test_a_driftless_random_walk_votes_about_as_often_as_a_two_sigma_test_should():
    votes = sum(KF.fit(walk(390, 0.0, 3e-4, 1e-4, s))["filter"].trend()["vote"] != 0 for s in range(120))
    assert votes / 120 <= 0.09                                                               # measured 3.5% over 200 seeds; nominal 4.6%


def test_maximum_likelihood_separates_noise_from_movement():
    noisy = KF.fit(walk(300, 0.0, 1e-4, 1e-3, 3))                                            # mostly measurement noise
    moving = KF.fit(walk(300, 0.0, 1e-3, 1e-5, 3))                                           # mostly genuine movement
    assert noisy["r"] > noisy["q_level"] and moving["q_level"] > moving["r"]
    assert KF.fit([1.0] * 50) is None and KF.fit([1.0, 2.0]) is None                         # flat or too short: nothing to fit


def test_the_smoothed_premium_is_closer_to_the_truth_than_each_print():
    rng = random.Random(4)
    mr, truth, err_raw, err_kf = MR.MarketRead(), 0.0060, [], []
    for i in range(200):
        truth -= 0.000002                                                                    # a premium decaying slowly towards expiry
        raw = truth + rng.gauss(0, 0.0004)                                                   # a future and an index that do not tick together
        sm, _ = mr.smooth_basis("NIFTY", raw)
        if i < MR.BASIS_MIN - 1:
            assert sm == raw                                                                 # the raw reading until there are enough to fit
        elif i >= 60:
            err_raw.append(abs(raw - truth))
            err_kf.append(abs(sm - truth))
    assert sum(err_kf) < 0.5 * sum(err_raw)


def test_the_regime_book_carries_the_trend_and_price_is_one_vote():
    rng, book, t, px = random.Random(6), RG.RegimeBook(), 1_700_000_000.0, 100.0
    for i in range(80):
        px *= math.exp(0.0008 + rng.gauss(0, 0.0003))
        book.update("NIFTY", t + 60 * i, px)
    st = book.state("NIFTY", t + 60 * 80)
    assert st["trend"]["vote"] == 1 and st["trend"]["t"] > 2
    # the Kalman trend replaces the raw five-minute move; a CUSUM drift votes only when neither does
    mom, extra = A2.AutoPilotV2.price_vote(0.5, {"trend": {"vote": 1, "t": 3.0, "slope_pct": 0.01}, "vote": 1, "change": "drift up"})
    assert mom is None and extra[0] == 1 and "Kalman trend" in extra[1]
    mom, extra = A2.AutoPilotV2.price_vote(0.5, {"trend": {"vote": 0, "t": 0.4, "slope_pct": 0.0}, "vote": 1, "change": "drift up"})
    assert mom is None and extra == (1, "CUSUM change point: drift up")
    mom, extra = A2.AutoPilotV2.price_vote(0.5, {"trend": None, "vote": 1, "change": "drift up"})
    assert mom == 0.5 and extra is None                                                      # before the filter is fitted: the raw move, and the change point is not counted again
    d, _ = A2.AutoPilotV2.with_read(0, [], {"pressure": None, "gap_pct": None}, None, 0, None, None, (1, "Kalman trend"))
    assert d == 0                                                                            # price alone is never a view
