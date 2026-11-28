"""The expiry in front (engine/expiry.py): max pain, and the study of whether expiries settle near it."""
import numpy as np
import pandas as pd
import pytest

from marketlens.engine import expiry as X


def test_max_pain_by_hand():
    oi = pd.DataFrame({"strike": [90.0, 100.0, 110.0], "oi_c": [0.0, 10.0, 50.0], "oi_p": [40.0, 10.0, 0.0]})
    # settle 90: calls pay 0, puts pay 10*10 = 100 ... settle 100: calls 0, puts 0 -> 0 ... settle 110: calls 10*10 = 100
    assert X.max_pain(oi) == 100.0
    assert X.max_pain(oi.assign(oi_c=0.0, oi_p=0.0)) is None


def _market(pull: float, n: int = 300, seed: int = 0):
    """n weekly expiries: OI piled at a strike near the price the day before; the settle moves randomly, plus `pull`
    of the way towards that strike."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2020-01-01", periods=2 * n)
    close = pd.Series(1000.0, index=days)
    rows = []
    for i in range(n):
        prev, e = days[2 * i], days[2 * i + 1]
        s0 = 1000.0 * np.exp(rng.normal(0, 0.05))
        mp = round(s0 * (1 + rng.choice([-1, 1]) * rng.uniform(0.003, 0.01)) / 5) * 5
        s1 = s0 * np.exp(rng.normal(0, 0.008))
        s1 += pull * (mp - s1)
        close[prev], close[e] = s0, s1
        for k in np.arange(mp - 50, mp + 51, 5):
            w = 1000.0 if k == mp else 10.0
            rows += [dict(date=prev, expiry=e, kind="CE", strike=float(k), oi=w), dict(date=prev, expiry=e, kind="PE", strike=float(k), oi=w)]
    return pd.DataFrame(rows), close


def test_pin_study_is_a_coin_toss_without_a_pull_and_finds_a_real_one():
    opt, close = _market(0.0)
    s = X.pin_study(opt, pd.DataFrame(), close, close.index[-1])
    assert s["n"] > 250 and 0.42 < s["share"] < 0.58 and s["p"] > 0.05
    opt, close = _market(0.6)
    s = X.pin_study(opt, pd.DataFrame(), close, close.index[-1])
    assert s["share"] > 0.8 and s["p"] < 1e-6
