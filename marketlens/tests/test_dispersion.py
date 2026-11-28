"""Implied correlation (engine/dispersion.py): weights recovered from returns, and the correlation formula."""
import numpy as np
import pandas as pd
import pytest

from marketlens.engine import dispersion as D


def test_weights_are_recovered_from_returns():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=200)
    true = pd.Series([0.2, 0.18, 0.15, 0.12, 0.1, 0.1, 0.08, 0.07], index=list("ABCDEFGH"))
    common = rng.normal(0, 0.01, 200)
    rm = pd.DataFrame({k: 0.8 * common + rng.normal(0, 0.008, 200) for k in true.index}, index=idx)
    ri = rm @ true
    w, r2 = D.fit_weights(ri, rm)
    assert r2 == pytest.approx(1.0, abs=1e-9) and np.allclose(w[true.index], true, atol=1e-9)
    # a missing member shows in the fit, which is the guard against a wrong list
    w2, r2b = D.fit_weights(ri, rm.drop(columns=["A"]))
    assert r2b < 0.99


def test_correlation_formula_recovers_the_correlation():
    w = pd.Series([0.4, 0.35, 0.25], index=["a", "b", "c"])
    s = pd.Series([0.2, 0.3, 0.25], index=["a", "b", "c"])
    rho_true = 0.55
    cov = np.outer(s, s) * rho_true
    np.fill_diagonal(cov, s ** 2)
    S = float(np.sqrt(w.to_numpy() @ cov @ w.to_numpy()))
    assert D.rho(w, s, S) == pytest.approx(rho_true, rel=1e-12)


def test_members_fall_back_when_the_list_cannot_be_read():
    def broken(u):
        raise ConnectionError("blocked")
    mem, src = D.members("BANKNIFTY", broken)
    assert src == "fallback list" and len(mem) == 14 and "HDFCBANK" in mem
    mem, src = D.members("BANKNIFTY", lambda u: "Company Name,Industry,Symbol,Series,ISIN Code\n" + "\n".join(f"x,y,S{i},EQ,z" for i in range(14)))
    assert src == "niftyindices.com" and mem[0] == "S0"


def test_a_split_nse_did_not_adjust_is_left_out_of_the_returns():
    idx = pd.bdate_range("2024-01-01", periods=5)
    c = pd.DataFrame({"close": [100, 101, 50.5, 51, 52.0], "prev_close": [99, 100, 101, 50.5, 51]}, index=idx)
    r = D.returns({"X": c})["X"]
    assert np.isnan(r.iat[2]) and r.iat[1] == pytest.approx(np.log(1.01))
