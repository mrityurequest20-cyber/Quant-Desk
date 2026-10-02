"""The strategy scorecard: every number checked by hand on small cases, and the gates and flags on telling ones."""
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.analytics.scorecard import ruin, scorecard, to_markdown


def test_layer1_by_hand():
    pnl = [100, -50, 200, -50, 100, -100, 300, -50, 50, -100] * 3          # 30 trades
    sc = scorecard(pnl)
    wins = [100, 200, 100, 300, 50]
    losses = [50, 50, 100, 50, 100]
    assert sc["win_rate"] == 0.5
    assert sc["expectancy"] == pytest.approx(0.5 * np.mean(wins) - 0.5 * np.mean(losses))
    assert sc["expectancy"] == pytest.approx(np.mean(pnl))                    # the same thing, said two ways
    assert sc["profit_factor"] == pytest.approx(sum(wins) / sum(losses)) == sc["omega"]
    assert sc["sqn"] == pytest.approx(math.sqrt(30) * np.mean(pnl) / np.std(pnl, ddof=1))


def test_tail_and_drawdown_by_hand():
    pnl = [10.0] * 95 + [-500.0] * 5                                            # a short-premium profile
    sc = scorecard(pnl, capital=2000)
    assert sc["skew"] < -3 and sc["excess_kurtosis"] > 3
    assert sc["var99"] == pytest.approx(500) and sc["cvar99"] == pytest.approx(500)
    assert sc["max_dd"] == -2500 and sc["max_dd_pct"] < -0.5                    # the five losses come together
    assert sc["recovery_trades"] is None                                        # never made it back
    assert any("negative skew" in f for f in sc["flags"]) and any("fat tails" in f for f in sc["flags"])
    assert sc["ulcer_index"] > 0


def test_annualising_from_dates_and_calmar():
    idx = pd.bdate_range("2024-01-01", periods=252)
    rng = np.random.default_rng(0)
    pnl = pd.Series(rng.normal(50, 100, 252), index=idx)
    sc = scorecard(pnl, capital=100_000)
    assert sc["per_year"] == pytest.approx(252 / ((idx[-1] - idx[0]).days / 365.25))
    assert sc["sharpe"] == pytest.approx(pnl.mean() / pnl.std() * math.sqrt(sc["per_year"]))
    assert sc["calmar"] == pytest.approx(sc["annual_return_pct"] / abs(sc["max_dd_pct"]))


def test_gates_pass_for_a_real_edge_and_fail_for_noise():
    rng = np.random.default_rng(1)
    good = scorecard(rng.normal(60, 100, 600), capital=50_000, notional=1_000_000)
    assert good["verdict"] == "PASSES every gate" and good["breakeven_cost_bps"] == pytest.approx(good["expectancy"] / 100)
    noise = scorecard(rng.normal(0, 100, 600), capital=50_000, n_trials=40)
    assert not noise["gates"]["DSR ≥ 0.95"] and not noise["gates"]["profit factor > 1.5"]
    few = scorecard(rng.normal(60, 100, 120))
    assert not few["gates"]["N ≥ 300"]


def test_oos_efficiency_catches_a_decaying_edge():
    rng = np.random.default_rng(2)
    decay = np.concatenate([rng.normal(80, 100, 400), rng.normal(5, 100, 200)])
    sc = scorecard(decay)
    assert sc["oos_efficiency"] < 0.5 and not sc["gates"]["OOS efficiency ≥ 0.5"]


def test_ruin_monte_carlo():
    r = ruin(np.array([-1000.0, 100.0]), capital=2000, horizon=50, n_sims=2000)
    assert r["p_ruin"] > 0.5                                                    # a coin flip that loses 10× the win
    safe = ruin(np.array([10.0, 20.0]), capital=1000, horizon=50, n_sims=500)
    assert safe["p_ruin"] == 0 and safe["final_p5"] > 1000


def test_markdown_renders_every_layer():
    md = to_markdown(scorecard(np.random.default_rng(3).normal(20, 100, 320), capital=20_000), "test")
    for word in ("expectancy", "SQN", "Sortino", "Omega", "CVaR", "Ulcer", "break-even", "OOS efficiency", "DSR", "P(ruin)"):
        assert word in md
