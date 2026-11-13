"""The market read (quantdesk/paper/marketread.py): positioning, flow and expectations from the options, futures and spot together, combined as Bayesian evidence into
P(up), and used by AUTO v2 as one vote in its view (owner, 13 Nov 2026: "Data analyser must be strong")."""
from __future__ import annotations

import math

import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper import marketread as MR


def q(oi=0, vol=0, mid=None):
    d = {"oi": oi, "vol": vol}
    if mid is not None:
        d.update(bid=mid * 0.99, ask=mid * 1.01, ltp=mid)
    return d


def board(rows, extra=None):
    """rows: {strike: (call oi, put oi)}"""
    quotes, chain = {}, {}
    for k, (coi, poi) in rows.items():
        quotes[f"X{k}CE"], quotes[f"X{k}PE"] = q(coi, coi // 10, 50.0), q(poi, poi // 10, 50.0)
        chain[k] = {"CE": f"X{k}CE", "PE": f"X{k}PE"}
    quotes.update(extra or {})
    return {"quotes": quotes}, chain


def test_max_pain_and_the_walls_on_a_chain_worked_by_hand():
    snap, chain = board({100: (10, 500), 105: (50, 200), 110: (100, 100), 115: (300, 40), 120: (800, 5)})
    rows = MR.chain_rows(snap, chain)
    # holders' payout at 110: calls 10*10 + 50*5 = 350; puts 300*5... computed directly instead of by hand:
    pay = {s["k"]: sum(r["coi"] * max(s["k"] - r["k"], 0) + r["poi"] * max(r["k"] - s["k"], 0) for r in rows) for s in rows}
    assert MR.max_pain(rows) == min(pay, key=pay.get)
    assert MR.walls(rows, 108.0) == (120.0, 100.0)                                       # most call OI above the price, most put OI below it


@pytest.mark.parametrize("px, oi, label, sig", [(0.01, 0.02, "long build-up", 1.0), (-0.01, 0.02, "short build-up", -1.0), (0.01, -0.02, "short covering", 0.5),
                                                (-0.01, -0.02, "long unwinding", -0.5), (0.0002, 0.02, None, 0.0), (0.01, 0.001, None, 0.0)])
def test_the_futures_build_up_has_its_four_textbook_cases(px, oi, label, sig):
    assert MR.buildup(px, oi) == (label, sig)


def test_no_evidence_is_a_coin_toss_and_each_signal_pushes_the_right_way():
    assert MR.MarketRead.evidence({"spot": 100.0}, None)["p_up"] == 0.5
    near_support = MR.MarketRead.evidence({"spot": 101.0, "call_wall": 120.0, "put_wall": 100.0, "pcr": 1.5}, None)
    near_resistance = MR.MarketRead.evidence({"spot": 119.0, "call_wall": 120.0, "put_wall": 100.0, "pcr": 0.6}, None)
    assert near_support["p_up"] > 0.6 > 0.4 > near_resistance["p_up"]
    then = {"spot": 100.0, "fut": 100.0, "foi": 1000.0, "pcr": 1.0, "near_coi": 1000.0, "near_poi": 1000.0, "skew": 0.02, "basis": 0.001}
    bull = MR.MarketRead.evidence({**then, "fut": 101.0, "foi": 1100.0, "pcr": 1.2, "near_poi": 1200.0, "skew": 0.01, "basis": 0.003}, then)
    bear = MR.MarketRead.evidence({**then, "fut": 99.0, "foi": 1100.0, "pcr": 0.8, "near_coi": 1200.0, "skew": 0.04, "basis": -0.001}, then)
    assert bull["p_up"] > 0.9 and bull["vote"] == 1 and bull["buildup"] == "long build-up" and any("puts written" in w for w in bull["why"])
    assert bear["p_up"] < 0.1 and bear["vote"] == -1 and bear["buildup"] == "short build-up" and any("calls written" in w for w in bear["why"])
    logit = sum(MR.WEIGHTS[k] * v for k, v in bull["signals"].items())
    assert bull["p_up"] == pytest.approx(1 / (1 + math.exp(-logit)), abs=1e-3)              # the probability is exactly the logistic of the weighted evidence


def test_skew_and_term_structure_are_read_from_implied_volatility():
    from statistics import NormalDist
    N = NormalDist().cdf

    def bs(S, K, T, sig, right):
        d1 = (math.log(S / K) + sig * sig * T / 2) / (sig * math.sqrt(T))
        d2 = d1 - sig * math.sqrt(T)
        return S * N(d1) - K * N(d2) if right == "CE" else K * N(-d2) - S * N(-d1)
    S, T = 100.0, 7 / 365
    quotes, chain = {}, {}
    for k in range(94, 107):
        iv = 0.20 + (0.004 * (100 - k) if k < 100 else 0.0)                                 # puts below the money priced at a higher volatility: positive skew
        for right in ("CE", "PE"):
            p = bs(S, k, T, iv, right)
            quotes[f"X{k}{right}"] = {"bid": p * 0.999, "ask": p * 1.001, "ltp": p, "oi": 100}
        chain[k] = {"CE": f"X{k}CE", "PE": f"X{k}PE"}
    cr = MR.chain_read({"quotes": quotes}, chain, S, T, 0.0, A2.implied_vol)
    assert cr["atm_iv"] == pytest.approx(0.20, abs=0.005) and cr["skew"] == pytest.approx(0.012, abs=0.004) and cr["implied_move"] > 0


def test_auto_v2_uses_the_read_as_one_vote_and_shows_it():
    d, why = A2.AutoPilotV2.with_read(0, [], {"pressure": 0.4, "gap_pct": None}, None, 0, None, {"vote": 1, "p_up": 0.8, "why": ["futures long build-up"]})
    assert d == 1 and "market read P(up) 0.80" in why[-1]                                 # book pressure up + the read up: two agree
    d, _ = A2.AutoPilotV2.with_read(0, [], {"pressure": -0.4, "gap_pct": None}, None, 0, None, {"vote": 1, "p_up": 0.8, "why": []})
    assert d == 0                                                                         # one against: no view
    d, _ = A2.AutoPilotV2.with_read(0, [], {"pressure": None, "gap_pct": None}, None, 0, None, {"vote": 1, "p_up": 0.8, "why": []})
    assert d == 0                                                                         # the read alone is never enough


def test_each_read_is_scored_against_what_happened_next():
    mr = MR.MarketRead(lookback_s=900)
    mr._score("X", 0.0, 100.0, 0.9)                                                         # it said up, strongly
    mr._score("X", 900.0, 101.0, 0.5)                                                       # and the price rose: (0.9 - 1)^2 = 0.01
    assert mr.calibration()["X"] == {"n": 1, "brier": 0.01}
    mr._score("X", 1800.0, 100.0, 0.5)                                                      # the 0.5 read at 900, then a fall: (0.5 - 0)^2
    assert mr.calibration()["all"] == {"n": 2, "brier": round((0.01 + 0.25) / 2, 4)}
