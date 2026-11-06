"""The quant layer: causal features, a model that must prove itself out of sample, a vol forecast
that scales right, and an EV engine that charges every cost and gives no free lunch."""
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.execution.costs import CostModel
from quantdesk.intraday.chains import IntradayPricer, time_to_expiry
from quantdesk.intraday.quant import (FEATURES, MIN_PER_YEAR, DirectionModel, EVEngine, VolForecaster, features_5m,
                                      to_5m)

IST = "Asia/Kolkata"


def sessions_5m(n_days=40, seed=1, momentum=0.0):
    """Random-walk 5m sessions; `momentum` makes the next 30 minutes follow the last 30 (a planted edge)."""
    rng = np.random.default_rng(seed)
    frames, px = [], 22000.0
    for d in pd.bdate_range("2026-06-01", periods=n_days):
        idx = pd.date_range(pd.Timestamp(d.date(), tz=IST) + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min")
        r = rng.normal(0, 8e-4, 75)
        for i in range(6, 75):
            r[i] += momentum * r[i - 6:i].sum() / 6
        c = px * np.exp(np.cumsum(r))
        o = np.r_[px, c[:-1]]
        frames.append(pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0002, "low": np.minimum(o, c) * 0.9998,
                                    "close": c, "volume": 0.0}, index=idx))
        px = c[-1] * np.exp(rng.normal(0, 3e-3))
    return pd.concat(frames)


def test_features_are_causal():
    df = sessions_5m(3, seed=4)
    full = features_5m(df)
    last_day = df[df.index.date == df.index.date[-1]]
    before = df[df.index.date < df.index.date[-1]]
    for k in (1, 2, 5, 17, 40):
        part = features_5m(pd.concat([before, last_day.iloc[:k]]))
        a, b = part[FEATURES].iloc[-1].to_numpy(), full.loc[part.index[-1], FEATURES].to_numpy()
        assert np.allclose(a, b, atol=1e-9), (k, a - b)          # a row never changes when later bars arrive


def test_model_finds_a_planted_edge_and_refuses_noise():
    edge = DirectionModel()
    d = edge.fit(features_5m(sessions_5m(45, seed=2, momentum=0.6)))
    assert edge.valid and d["auc_oos"] > 0.58, d
    noise = DirectionModel()
    d = noise.fit(features_5m(sessions_5m(45, seed=3, momentum=0.0)))
    assert not noise.valid and d["status"] == "no edge out of sample", d
    few = DirectionModel()
    assert few.fit(features_5m(sessions_5m(5, seed=5)))["status"] == "not enough history"


def test_vol_forecast_scales_and_reacts():
    rng = np.random.default_rng(0)
    idx = pd.date_range(pd.Timestamp("2026-09-28 09:15", tz=IST), periods=375, freq="1min")
    prev = pd.DatetimeIndex([t - pd.Timedelta(days=1) for t in idx])
    calm = np.exp(np.cumsum(rng.normal(0, 3e-4, 750))) * 22000
    bars = pd.DataFrame({"close": calm}, index=prev.append(idx))
    f = VolForecaster().forecast(bars, idx[0].date())
    assert f["sigma_min"] == pytest.approx(3e-4, rel=0.2) and f["sigma_30m"] == pytest.approx(f["sigma_min"] * math.sqrt(30))
    wild = bars.copy()
    wild.iloc[-100:, 0] = wild["close"].iloc[-101] * np.exp(np.cumsum(rng.normal(0, 1.5e-3, 100)))
    assert VolForecaster().forecast(wild, idx[0].date())["sigma_min"] > 1.5 * f["sigma_min"]     # today's burst counts
    with_iv = VolForecaster().forecast(bars, idx[0].date(), atm_iv=30.0)
    assert with_iv["sigma_min"] > f["sigma_min"] and with_iv["source"] == "realised+implied"


def test_calibration_table():
    import json
    from quantdesk.web.intraday_api import IntradayAPI
    rows = []
    for i in range(20):
        up = i % 4 != 0                                            # the index went up 75% of the time
        rows.append({"direction": 1, "entry_underlying": 100.0, "exit_underlying": 101.0 if up else 99.0, "pnl": 50.0 if up else -60.0,
                     "meta": json.dumps({"quant": {"p_up": 0.55, "p_source": "prior tilt from the analyst's score (unvalidated)"}})})
    rows.append({"direction": 1, "entry_underlying": 100.0, "exit_underlying": float("nan"), "pnl": 0.0, "meta": "{}"})
    cal = IntradayAPI._calibration(pd.DataFrame(rows))
    assert len(cal) == 1 and cal[0]["trades"] == 20 and cal[0]["bucket"] == "53–56%"
    assert cal[0]["realised"] == pytest.approx(0.75) and cal[0]["source"] == "prior tilt from the analyst's score"


