"""HMM regime detection and CUSUM change points (quantdesk/paper/regimes.py, owner, 13 Nov 2026). Synthetic series with known regimes and known change points: the
model must find them, and pure noise must stay quiet."""
from __future__ import annotations

import math
import random

import pytest

from quantdesk.paper import regimes as RG


def series(segments, seed=7):
    """segments: [(n, mean, sd)] of one-minute log returns."""
    rng = random.Random(seed)
    return [rng.gauss(mu, sd) for n, mu, sd in segments for _ in range(n)]


def test_baum_welch_finds_three_volatility_levels_and_names_them_calm_to_stressed():
    obs = series([(120, 0, 0.0005), (120, 0, 0.0015), (120, 0, 0.005), (60, 0, 0.0005)])
    m = RG.fit_hmm(obs)
    sds = [math.sqrt(v) for v in m["var"]]
    assert sds[0] < sds[1] < sds[2]
    assert sds[0] == pytest.approx(0.0005, rel=0.35) and sds[2] == pytest.approx(0.005, rel=0.35)
    assert m["p"][0] > 0.8                                                                  # it ended calm
    assert all(abs(sum(row) - 1) < 1e-9 for row in m["A"]) and all(m["A"][i][i] > 0.8 for i in range(3))    # sticky regimes, rows sum to one
    assert RG.fit_hmm(obs[:30]) is None                                                     # too little to say
    assert m["regimes"] is True                                                             # the information criterion prefers three regimes here...
    assert RG.fit_hmm(series([(300, 0, 0.0005)], seed=9))["regimes"] is False               # ...and one when there is one


def test_the_filter_moves_to_stressed_when_the_returns_turn_violent():
    obs = series([(200, 0, 0.0005), (100, 0, 0.004)], seed=3)
    m = RG.fit_hmm(obs)
    p = m["p"]
    for x in series([(15, 0, 0.006)], seed=11):
        p = RG.filter_step(m, p, x)
    assert p[2] > 0.8 and abs(sum(p) - 1) < 1e-9
    for x in series([(40, 0, 0.0004)], seed=12):
        p = RG.filter_step(m, p, x)
    assert p[2] < 0.2                                                                       # and out of stress when it calms


def test_cusum_is_quiet_on_noise_and_catches_a_drift_and_a_volatility_jump():
    rng = random.Random(1)
    c = RG.Cusum()
    false = sum(1 for _ in range(5000) if c.step(rng.gauss(0, 1)))
    assert false <= 25                                                                      # all three detectors together: about one false alarm per 200 minutes of pure noise or fewer
    c = RG.Cusum()
    hits = [(i, c.step(rng.gauss(1.0, 1))) for i in range(40)]
    first = next(i for i, h in hits if h)
    assert first <= 15 and next(h for _, h in hits if h) == "drift up"                     # a one-sd drift is caught within about ten minutes
    c = RG.Cusum()
    hits = [(i, c.step(rng.gauss(0, 3))) for i in range(40)]
    assert next(h for _, h in hits if h) == "volatility up"


def test_the_book_turns_prices_into_a_state_and_fresh_change_points():
    rng = random.Random(5)
    book, t, px = RG.RegimeBook(), 1_700_000_000.0, 100.0
    for i in range(150):                                                                    # calm: tiny moves
        px *= math.exp(rng.gauss(0, 0.0004))
        book.update("NIFTY", t + 60 * i, px)
    st = book.state("NIFTY", t + 60 * 150)
    assert st["hmm"] == "calm" and not st["stress"] and st["vote"] == 0
    for i in range(150, 175):                                                               # then a steady climb, a move every minute
        px *= math.exp(0.003 + rng.gauss(0, 0.0004))
        book.update("NIFTY", t + 60 * i, px)
    st = book.state("NIFTY", t + 60 * 175)
    assert st["change"] in ("drift up", "volatility up") and (st["vote"] == 1 or st["stress"])
    assert book.state("NIFTY", t + 60 * 175 + RG.CHANGE_FRESH_S + 60)["change"] is None     # a change point is news for a quarter of an hour, then it is the regime


def test_auto_v2_reads_stress_as_the_event_regime_and_a_drift_as_one_vote():
    from quantdesk.paper import auto2 as A2
    ap = A2.AutoPilotV2(("NIFTY",), {"NIFTY": 65}, lambda *a: 20.0, None)
    assert ap.regime("NIFTY", None, None, {"stress": True, "change": None, "p": {"stressed": 0.83}}) == ("event", "event regime: the HMM puts NIFTY in its stressed state (P 0.83)")
    assert "CUSUM change point to higher volatility" in ap.regime("NIFTY", None, None, {"stress": True, "change": "volatility up"})[1]
    assert ap.regime("NIFTY", None, None, {"stress": False, "change": "drift up"})[0] == "normal"
    d, why = A2.AutoPilotV2.with_read(0, [], {"pressure": 0.4, "gap_pct": None}, None, 0, None, None, (1, "CUSUM change point: drift up"))
    assert d == 1 and why[-1] == "CUSUM change point: drift up"                               # book pressure and the change point agree
    assert A2.AutoPilotV2.with_read(0, [], {"pressure": None, "gap_pct": None}, None, 0, None, None, (1, "x"))[0] == 0     # a change point alone is never a view
