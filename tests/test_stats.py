import numpy as np
import pandas as pd
import pytest

from quantdesk.analytics import volatility as V


def test_garch_recovers_parameters():
    rng = np.random.default_rng(11)
    n, w, a, b = 6000, 0.02, 0.08, 0.90
    r = np.zeros(n)
    s2 = w / (1 - a - b)
    for t in range(n):
        r[t] = np.sqrt(s2) * rng.standard_normal()
        s2 = w + a * r[t] ** 2 + b * s2
    p = V.Garch11().fit(r)
    assert p.alpha == pytest.approx(a, abs=0.03)
    assert p.beta == pytest.approx(b, abs=0.04)
    assert p.persistence == pytest.approx(a + b, abs=0.02)


def test_range_estimators_agree_on_gbm():
    rng = np.random.default_rng(4)
    n, steps, sig = 400, 78, 0.20
    dt = 1 / 252 / steps
    path = np.exp(np.cumsum(rng.normal(0, sig * np.sqrt(dt), n * steps))) * 100
    bars = path.reshape(n, steps)
    df = pd.DataFrame({"open": bars[:, 0], "high": bars.max(1), "low": bars.min(1), "close": bars[:, -1]},
                      index=pd.bdate_range("2020-01-01", periods=n))
    for est in (V.parkinson, V.garman_klass, V.rogers_satchell):
        assert est(df, 252).iloc[-1] == pytest.approx(20, rel=0.15)
    assert V.close_to_close(df["close"], 252).iloc[-1] == pytest.approx(20, rel=0.2)


