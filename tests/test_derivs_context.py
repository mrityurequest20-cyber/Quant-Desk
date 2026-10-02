"""Second-order Greeks against finite differences; GEX sign and flip; the options-implied forward."""
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.options.gex import gamma_exposure, gex_at, implied_forward
from quantdesk.options.pricing import bs_price, greeks, second_order_greeks

S, K, T, R, Q, V = 22400.0, 22600.0, 10 / 365, 0.065, 0.012, 0.14


@pytest.mark.parametrize("right", ["CE", "PE"])
def test_second_order_greeks_match_finite_differences(right):
    g2 = second_order_greeks(S, K, T, R, Q, V, right)
    h, dt, ds = 1e-4, 1e-5, 0.5
    g = lambda **kw: greeks(kw.get("S", S), K, kw.get("T", T), R, Q, kw.get("v", V), right)   # noqa: E731
    assert g2["vanna"] == pytest.approx((g(v=V + h)["delta"] - g(v=V - h)["delta"]) / (2 * h) / 100, rel=1e-5)
    assert g2["volga"] == pytest.approx((g(v=V + h)["vega"] - g(v=V - h)["vega"]) / (2 * h) / 100, rel=1e-5)
    assert g2["charm"] == pytest.approx((g(T=T - dt)["delta"] - g(T=T + dt)["delta"]) / (2 * dt) / 365, rel=1e-5)
    assert g2["speed"] == pytest.approx((g(S=S + ds)["gamma"] - g(S=S - ds)["gamma"]) / (2 * ds), rel=1e-4)


def chain(spot=22400.0, call_heavy=True):
    ks = np.arange(21400, 23450, 50.0)
    T_ = 5 / 365
    rows = {}
    for k in ks:
        c, p = bs_price(spot, k, T_, R, Q, 0.13, "CE"), bs_price(spot, k, T_, R, Q, 0.13, "PE")
        rows[k] = {"ce_ltp": c, "pe_ltp": p, "ce_bid": c - 0.5, "ce_ask": c + 0.5, "pe_bid": max(p - 0.5, 0.05),
                   "pe_ask": p + 0.5, "ce_iv": 13.0, "pe_iv": 13.0,
                   "ce_oi": (3e6 if call_heavy else 1e6) * math.exp(-((k - spot) / 400) ** 2),
                   "pe_oi": (1e6 if call_heavy else 3e6) * math.exp(-((k - spot) / 400) ** 2)}
    return pd.DataFrame.from_dict(rows, orient="index"), T_


def test_gex_sign_and_flip():
    df, T_ = chain(call_heavy=True)
    pos = gamma_exposure(df, 22400.0, T_, R, Q)
    assert pos["gex_cr_per_1pct"] > 0 and pos["gex_state"].startswith("positive")
    df2, _ = chain(call_heavy=False)
    neg = gamma_exposure(df2, 22400.0, T_, R, Q)
    assert neg["gex_cr_per_1pct"] < 0 and neg["gex_state"].startswith("negative")
    # a flip, where reported, really is a zero of the curve
    mixed = df.copy()
    mixed.loc[mixed.index < 22300, "pe_oi"] *= 8
    m = gamma_exposure(mixed, 22400.0, T_, R, Q)
    if m["gamma_flip"] == m["gamma_flip"]:
        args = (mixed.index.to_numpy(float), mixed["ce_oi"], mixed["pe_oi"], mixed["ce_iv"] / 100, mixed["pe_iv"] / 100, T_, R, Q)
        lo, hi = gex_at(m["gamma_flip"] - 30, *args), gex_at(m["gamma_flip"] + 30, *args)
        assert np.sign(lo) != np.sign(hi)


def test_implied_forward_recovers_the_carry():
    df, T_ = chain()
    f = implied_forward(df, 22400.0, T_, R)
    assert f["carry_ann"] == pytest.approx(R - Q, abs=0.002)                  # put-call parity: F = S·e^{(r−q)T}
