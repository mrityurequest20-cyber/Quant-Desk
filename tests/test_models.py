"""The research model library, each on a case with a known answer."""
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.analytics import models as M
from quantdesk.options.pricing import bs_price


def test_ou_fit_recovers_its_parameters():
    rng = np.random.default_rng(0)
    theta, mu, sigma, dt, n = 0.5, 2.0, 0.3, 1.0, 20000
    x = np.empty(n)
    x[0] = mu
    b = math.exp(-theta * dt)
    sd = sigma * math.sqrt((1 - b * b) / (2 * theta))
    for i in range(1, n):
        x[i] = mu + (x[i - 1] - mu) * b + sd * rng.normal()
    f = M.ou_fit(x, dt)
    assert f["theta"] == pytest.approx(theta, rel=0.05) and f["mu"] == pytest.approx(mu, abs=0.02)
    assert f["sigma"] == pytest.approx(sigma, rel=0.05) and f["half_life"] == pytest.approx(math.log(2) / theta, rel=0.05)
    assert not M.ou_fit(np.cumsum(rng.normal(size=5000)))["mean_reverting"] or M.ou_fit(np.cumsum(rng.normal(size=5000)))["half_life"] > 200


def test_hawkes_finds_clustering_and_poisson_doesnt():
    rng = np.random.default_rng(1)
    mu, alpha, beta, T = 0.5, 0.8, 1.6, 2000.0                                  # branching 0.5
    t, events, lam_bar = 0.0, [], mu
    while t < T:                                                                # Ogata thinning
        lam_bar = mu + alpha * sum(math.exp(-beta * (t - s)) for s in events[-200:]) + alpha
        t += rng.exponential(1 / lam_bar)
        lam = mu + alpha * sum(math.exp(-beta * (t - s)) for s in events[-200:])
        if t < T and rng.uniform() <= lam / lam_bar:
            events.append(t)
    fit = M.hawkes_fit(events, T)
    assert 0.3 < fit["branching"] < 0.7
    poisson = np.cumsum(rng.exponential(2.0, 800))
    assert M.hawkes_fit(poisson)["branching"] < 0.15


def test_pca_and_kelly():
    rng = np.random.default_rng(2)
    level = rng.normal(size=(500, 1))
    panel = pd.DataFrame(level @ np.ones((1, 6)) + 0.1 * rng.normal(size=(500, 6)))
    assert M.pca(panel)["explained"][0] > 0.9                                  # one common factor
    w = M.kelly_vector([0.01, 0.0], [[0.04, 0.0], [0.0, 0.04]], fraction=1.0, max_gross=10)
    assert w[0] == pytest.approx(0.25, rel=1e-4) and w[1] == pytest.approx(0, abs=1e-6)
    capped = M.kelly_vector([0.05, 0.05], [[0.01, 0], [0, 0.01]], fraction=0.5, max_gross=1.0)
    assert abs(capped).sum() == pytest.approx(1.0)


def test_heston_collapses_to_black_scholes_and_calibrates():
    S, T, r, q, v = 22400.0, 30 / 365, 0.065, 0.012, 0.15 ** 2
    for K in (21500.0, 22400.0, 23200.0):                                      # σᵥ → 0: constant variance = BSM
        h = M.heston_price(S, K, T, r, q, v, 2.0, v, 1e-3, 0.0, "CE")
        assert h == pytest.approx(bs_price(S, K, T, r, q, 0.15, "CE"), rel=2e-3)
    ks = [21800.0, 22100.0, 22400.0, 22700.0, 23000.0]
    true = (0.025, 3.0, 0.03, 0.6, -0.6)
    px = [M.heston_price(S, k, T, r, q, *true, "CE" if k >= S else "PE") for k in ks]
    cal = M.heston_calibrate(S, ks, T, r, q, px, ["CE" if k >= S else "PE" for k in ks])
    assert cal["rmse"] < 0.5 and cal["rho"] < 0                                 # recovers the skew's sign


def test_execution_and_market_making_formulas():
    ac = M.almgren_chriss(X=10000, T=1.0, N=10, sigma=0.3, eta=0.01, gamma=0.001, lam=1e-4)
    assert ac["holdings"][0] == 10000 and ac["holdings"][-1] == pytest.approx(0, abs=1e-9)
    assert (np.diff(ac["holdings"]) <= 0).all() and ac["trades"].sum() == pytest.approx(10000)
    risk_neutral = M.almgren_chriss(X=10000, T=1.0, N=10, sigma=0.3, eta=0.01, gamma=0.001, lam=0)
    assert np.allclose(risk_neutral["trades"], 1000)                            # λ = 0: sell evenly (TWAP)
    a = M.avellaneda_stoikov(100.0, inventory=5, sigma=2.0, gamma=0.1, k=1.5, t_left=0.5)
    assert a["reservation"] == pytest.approx(100 - 5 * 0.1 * 4 * 0.5) and a["ask"] - a["bid"] == pytest.approx(a["spread"])


def test_ofi_and_vpin():
    q = pd.DataFrame({"bid": [100, 100.5, 100.5, 100], "bid_size": [10, 12, 20, 5],
                      "ask": [101, 101, 101.5, 101], "ask_size": [8, 8, 6, 9]})
    e = M.ofi(q)
    assert list(e) == [0, 12 - 0 - 8 + 8, 20 - 12 - 0 + 8, 0 - 20 - 9 + 0]   # last: bid and ask both fell
    rng = np.random.default_rng(3)
    idx = pd.date_range("2026-10-05 09:15", periods=600, freq="1min")
    calm = pd.DataFrame({"close": 100 + np.cumsum(rng.normal(0, 0.05, 600)), "volume": 1000.0}, index=idx)
    trend = pd.DataFrame({"close": 100 + np.cumsum(np.abs(rng.normal(0, 0.05, 600))), "volume": 1000.0}, index=idx)
    assert M.vpin(trend, 5000, 30).iloc[-1] > M.vpin(calm, 5000, 30).iloc[-1]   # one-sided flow → toxic
