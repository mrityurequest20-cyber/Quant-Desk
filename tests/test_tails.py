"""Extreme value theory (quantdesk/paper/tails.py, quantdesk/premarket/tailrisk.py, AUTO v2's tail check; owner, 13 Nov 2026: "Add Extreme value theory: tail-risk
estimates"). Distributions whose tails are known exactly: the generalised Pareto itself, Student's t with 4 degrees of freedom, and GARCH returns with t shocks."""
from __future__ import annotations

import datetime as dt
import json
import math
import random

import pandas as pd
import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper import tails as TL
from quantdesk.premarket import tailrisk as TR

T4_VAR99, T4_ES99 = 3.747, 5.22                     # Student-t(4), unit scale: the 99% quantile and the mean beyond it


def t4(rng):
    return rng.gauss(0, 1) / math.sqrt(sum(rng.gauss(0, 1) ** 2 for _ in range(4)) / 4)


def garch_closes(n=3000, seed=2):
    rng, var, closes = random.Random(seed), 1e-6 / 0.02, [100.0]
    for _ in range(n):
        r = math.sqrt(var) * t4(rng) / math.sqrt(2)
        var = 1e-6 + 0.08 * r * r + 0.9 * var
        closes.append(closes[-1] * math.exp(r))
    return closes


def test_probability_weighted_moments_recover_a_generalised_pareto():
    rng = random.Random(7)
    ys = [1.0 / 0.25 * ((1 - rng.random()) ** -0.25 - 1) for _ in range(3000)]
    xi, beta = TL.fit_gpd(ys)
    assert xi == pytest.approx(0.25, abs=0.07) and beta == pytest.approx(1.0, abs=0.12)
    assert TL.fit_gpd([1.0, 2.0]) is None


def test_fat_tails_are_measured_where_a_normal_model_misses_them():
    rng = random.Random(7)
    tl = TL.Tail.fit([t4(rng) for _ in range(5000)])
    assert tl.var(0.99) == pytest.approx(T4_VAR99, rel=0.06) and tl.es(0.99) == pytest.approx(T4_ES99, rel=0.08)
    assert tl.lo["xi"] + tl.hi["xi"] > 0.1                                                      # a fat (power-law) tail; one side alone is within its sampling error (+-0.09)
    assert tl.var(0.99) > 2.326 * math.sqrt(2) * 1.05 and tl.es(0.99) > 2.665 * math.sqrt(2) * 1.2   # the normal with the same variance says 3.29 and 3.77
    assert tl.es(0.99) > tl.var(0.99) and tl.var(0.995) > tl.var(0.99)
    assert TL.Tail.fit([0.1] * 100) is None                                                     # under a year of data: nothing


def test_the_conditional_model_passes_its_own_out_of_sample_backtest():
    fs = TL.fit_series(garch_closes())
    assert set(fs["h"]) == {"1", "3", "5", "10"} and fs["sigma"] > 0
    bt = fs["backtest"]
    assert bt["days"] == 500 and bt["kupiec_p"] > 0.05                                          # its 1% is about 1%
    m = TL.Model.read(json.loads(json.dumps(fs)))                                               # through the brief's JSON and back
    assert 0 < m.var_pct(0.99, 1) < m.es_pct(0.99, 1) < m.es_pct(0.99, 5)


def test_kupiec_tells_a_right_breach_count_from_a_wrong_one():
    assert TL.kupiec(500, 5, 0.01) > 0.9
    assert TL.kupiec(500, 15, 0.01) < 0.01 and TL.kupiec(500, 0, 0.01) < 0.05


def test_storage_is_not_trusted():
    good = TL.fit_series(garch_closes())
    bad = json.loads(json.dumps(good))
    bad["h"]["1"]["lo"]["beta"] = -1
    bad["h"]["3"]["body"] = list(reversed(bad["h"]["3"]["body"]))
    m = TL.Model.read(bad)
    assert set(m.h) == {5, 10}                                                                  # the broken horizons are dropped, the rest kept
    assert TL.Model.read({"sigma": 0.01, "h": {}}) is None and TL.Model.read({"nonsense": 1}) is None


def test_expected_payoffs_obey_put_call_parity_over_the_fitted_distribution():
    m = TL.Model.read(TL.fit_series(garch_closes()))
    S, K = 100.0, 101.0
    call = m.expected_payoff(lambda x: max(x - K, 0.0), S, 3)
    put = m.expected_payoff(lambda x: max(K - x, 0.0), S, 3)
    fwd = m.expected_payoff(lambda x: x, S, 3)
    assert call - put == pytest.approx(fwd - K, abs=1e-6) and call > 0 and put > 0
    wide = m.expected_payoff(lambda x: max(x - K, 0.0), S, 3, sigma=m.sigma * 3)
    assert wide > call                                                                          # a higher volatility today (never lower than the brief's) prices more tail


def _fake_yahoo(n=900):
    days = pd.bdate_range("2022-01-03", periods=n)
    rng = random.Random(3)
    px, fx, inr = [], [], []
    a, b, c = 80.0, 82.0, 25000.0
    for _ in range(n):
        a *= math.exp(0.02 * t4(rng) / 1.41)
        b *= math.exp(0.003 * rng.gauss(0, 1))
        c *= math.exp(0.01 * t4(rng) / 1.41)
        px.append(a), fx.append(b), inr.append(c)
    px[400] = -5.0                                                                              # a negative print (WTI, April 2020) and a roll step
    px[600] = px[599] * 3
    return days, {"CL=F": pd.Series(px, index=days), "INR=X": pd.Series(fx, index=days), "^NSEI": pd.Series(inr, index=days)}


def test_the_brief_fits_indices_stocks_and_mcx_proxies_in_rupees():
    days, y = _fake_yahoo()
    ic = pd.DataFrame({"date": days, "symbol": "NIFTY", "close": y["^NSEI"].values})
    out = TR.build(["NIFTY", "CRUDEOIL", "USDINR", "RELIANCE"], ic, y)
    assert out["NIFTY"]["src"] == "nse_index_close" and out["CRUDEOIL"]["src"] == "proxy CL=F x INR=X (Yahoo)" and out["USDINR"]["src"].startswith("proxy INR=X")
    assert "RELIANCE" not in out                                                                # no history: no model, and the check is off for it
    s, _ = TR.series_for("CRUDEOIL", None, y)
    assert (s > 0).all() and s.pct_change().abs().max() < 1.0                                   # the bad prints are gone
    assert TR.tickers_for(["CRUDEOIL", "TCS"]) == ["CL=F", "INR=X", "TCS.NS"]
    line = TR.summary_line(out)
    assert line.startswith("Tail risk (EVT, 1-day 99% expected shortfall): NIFTY ")


def test_the_cli_reuses_the_days_models(tmp_path):
    from quantdesk.premarket import cli as PC

    class A:
        tails, offline = str(tmp_path / "tails.json"), True

    class Cfg:
        def get(self, k, d=None):
            return {"nse_fo": ["NIFTY"]} if k == "paper.underlyings" else d
    days, y = _fake_yahoo()
    ic = pd.DataFrame({"date": days, "symbol": "NIFTY", "close": y["^NSEI"].values})
    now, health = pd.Timestamp("2026-11-16 06:00", tz="Asia/Kolkata"), {}
    got = PC.day_tails(Cfg(), A, {"index_close": ic}, now, health)
    assert set(got) == {"NIFTY"} and json.loads((tmp_path / "tails.json").read_text())["built"] == "2026-11-16"
    health = {}
    assert PC.day_tails(Cfg(), A, {"index_close": None}, now, health) == got and "earlier today" in health["tails"]


# ---- AUTO v2's tail check ------------------------------------------------------------------------------------------------------------------------
class Cal:
    def next_trading_day(self, d):
        d += dt.timedelta(days=1)
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        return d

    def prev_trading_day(self, d):
        return d - dt.timedelta(days=1)


def _ap(with_model=True):
    ap = A2.AutoPilotV2(("NIFTY",), {"NIFTY": 65}, lambda *a: 0.0, Cal())
    ap.brief = {"tails": {"NIFTY": TL.fit_series(garch_closes())}} if with_model else {}
    return ap


def _ic(credit_each):
    """A 100-point-wide iron condor 200 points either side of 10,000: short legs at `credit_each`, long legs at a fifth of it."""
    legs = [{"side": -1, "right": "CE", "k": 10200, "px": credit_each}, {"side": 1, "right": "CE", "k": 10300, "px": credit_each / 5},
            {"side": -1, "right": "PE", "k": 9800, "px": credit_each}, {"side": 1, "right": "PE", "k": 9700, "px": credit_each / 5}]
    net = 2 * credit_each * 0.8
    return {"legs": legs, "exp": dt.date(2026, 11, 20), "lot": 65, "risk": 100 - net, "best": net, "fees": 0.0}


def test_an_option_sale_must_pay_for_its_tail():
    ap, s = _ap(), A2.BY_SID["IC1.faan.1/0.5.d"]
    st = {"u": "NIFTY", "spot": 10000.0, "rv": None}
    today = dt.date(2026, 11, 16)
    ok, why, edge = ap.tail_check(s, st, _ic(0.5), today)
    assert not ok and "does not pay for the tail" in why and edge < 0                            # one rupee of credit for 100 points of tail: refused
    ok, why, edge = ap.tail_check(s, st, _ic(30.0), today)
    assert ok and why is None and edge > 0                                                      # a rich premium pays
    lo, _, e_calm = ap.tail_check(s, {**st, "rv": None}, _ic(8.0), today)
    hi, _, e_wild = ap.tail_check(s, {**st, "rv": 0.80}, _ic(8.0), today)
    assert e_wild < e_calm                                                                      # the last hour's volatility, when higher, makes the tail dearer
    long_call = A2.BY_SID["LC0.uaan.1/0.5.d"]
    assert ap.tail_check(long_call, st, _ic(0.5), today) == (True, None, None)                   # a buyer sells no tail: nothing to check
    assert _ap(with_model=False).tail_check(s, st, _ic(0.5), today) == (True, None, None)       # no model in the brief: no check (and the plan says so)
    assert "1-day 99% ES -" in ap.tail_text("NIFTY") and ap.tail_text("BANKNIFTY") == ""
