"""AUTO's strategy search (quantdesk/paper/structures.py): every structure the building blocks allow is scored on one scale, nothing is named in advance, a naked short call never appears, and a
structure must offer at least twice its maximum loss to be considered. Prices come from Black-Scholes at a flat volatility, with a realistic spread."""
import math

import pytest

from quantdesk.paper import structures as S

SPOT, STEP, T, VOL = 24500.0, 50, 7 / 365.25, 0.14


def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(spot, k, right, t=T, vol=VOL):
    d1 = (math.log(spot / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    return spot * ncdf(d1) - k * ncdf(d2) if right == "CE" else k * ncdf(-d2) - spot * ncdf(-d1)


def board(spread=0.02, vol=VOL):
    chain, quotes = {}, {}
    for k in range(23500, 25500 + 1, STEP):
        chain[k] = {}
        for r in ("CE", "PE"):
            name = f"NIFTY12NOV26{k}{r}"
            m = max(bs(SPOT, k, r, vol=vol), 0.5)
            half = max(0.05, m * spread / 2)
            quotes[name] = {"bid": round(m - half, 2), "ask": round(m + half, 2), "age_s": 1.0}
            chain[k][r] = name
    return chain, quotes


def sigma():
    atm = 24500
    return S.implied_move(SPOT, bs(SPOT, atm, "CE"), bs(SPOT, atm, "PE"))


def test_the_implied_move_is_the_straddles_and_the_distribution_has_the_tilted_mean():
    sg = sigma()
    assert sg == pytest.approx(VOL * math.sqrt(T), rel=0.03)
    for tilt in (-1.0, 0.0, 0.5):
        d = S.distribution(SPOT, sg, tilt)
        assert sum(w for _, w in d) == pytest.approx(1.0) and sum(s * w for s, w in d) == pytest.approx(SPOT * math.exp(tilt * sg), rel=2e-3)
    assert S.implied_move(SPOT, None, 5) is None and S.implied_move(0, 5, 5) is None


def test_prices_are_the_desks_buy_at_the_offer_sell_at_the_bid_one_tick_worse_and_a_one_sided_quote_has_none():
    q = {"bid": 99.0, "ask": 100.0}
    assert S.price(q, "buy") == pytest.approx(100.05) and S.price(q, "sell") == pytest.approx(98.95)
    for bad in (None, {}, {"bid": 0, "ask": 5}, {"bid": 6, "ask": 5}, {"bid": float("nan"), "ask": 5}, {"bid": 5}):
        assert S.price(bad, "buy") is None


def test_the_payoff_and_extremes_of_a_known_vertical():
    legs = [{"strike": 24500.0, "right": "CE", "qty": 1}, {"strike": 24600.0, "right": "CE", "qty": -1}]
    assert [S.payoff(legs, s) for s in (24400, 24500, 24550, 24600, 25000)] == [0, 0, 50, 100, 100]
    ml, mg = S._extremes(legs, 40.0)
    assert ml == pytest.approx(40.0) and mg == pytest.approx(60.0)
    lc = [{"strike": 24500.0, "right": "CE", "qty": 1}]
    assert S._extremes(lc, 80.0) == (80.0, math.inf)
    assert S._extremes([{"strike": 24500.0, "right": "CE", "qty": -1}], -80.0) == (None, None)                 # a naked short call has no extremes: it is never built
    cov = [{"strike": 24500.0, "right": "CE", "qty": -1}, {"strike": 24400.0, "right": "CE", "qty": 1}]
    assert S._extremes(cov, 30.0)[0] is not None


def test_every_building_block_appears_and_no_candidate_is_a_naked_short_call():
    chain, quotes = board()
    cs = S.candidates(chain, quotes, SPOT)
    labels = " | ".join(c["label"] for c in cs)
    assert len(cs) > 500 and "long 24500 CE" in labels and "buy 24500 / sell 24600 CE" in labels and "buy 2x" in labels and "wing" in labels
    for c in cs:
        calls = sum(l["qty"] for l in c["legs"] if l["right"] == "CE")
        assert calls >= 0 and c["max_loss"] > 0 and all(l["symbol"] in quotes for l in c["legs"])
        # the numbers are consistent with an independent evaluation of the payoff at a few prices
        for s in (0.0, 23000.0, 24500.0, 26000.0, 30000.0):
            assert S.payoff(c["legs"], s) - c["cost"] >= -c["max_loss"] - 1e-6
            if math.isfinite(c["max_gain"]):
                assert S.payoff(c["legs"], s) - c["cost"] <= c["max_gain"] + 1e-6


def test_with_no_view_nothing_clears_the_bar_and_a_view_picks_a_structure_in_its_direction():
    chain, quotes = board()
    cs, sg = S.candidates(chain, quotes, SPOT), sigma()
    none, n, passed = S.choose(cs, SPOT, sg, 0.0)
    assert none is None and n == len(cs) and passed > 0                                  # fair prices plus costs: no edge, no trade
    up, _, _ = S.choose(cs, SPOT, sg, 1.0)
    dn, _, _ = S.choose(cs, SPOT, sg, -1.0)
    assert up and dn
    def lean(c):                                                                          # net delta sign at the money, from the payoff slope around spot
        return S.payoff(c["legs"], SPOT + 700) - S.payoff(c["legs"], SPOT - 700)
    assert lean(up) > 0 and lean(dn) < 0
    for c in (up, dn):
        assert c["max_gain"] >= 2 * c["max_loss"] and c["score"] >= S.MIN_SCORE_DEFAULT and c["ev"] > 0


def test_a_stronger_view_never_scores_the_same_structure_lower_and_the_reward_test_is_a_real_filter():
    chain, quotes = board()
    cs, sg = S.candidates(chain, quotes, SPOT), sigma()
    _, _, p2 = S.choose(cs, SPOT, sg, 1.0, min_rr=2.0)
    _, _, p5 = S.choose(cs, SPOT, sg, 1.0, min_rr=5.0)
    _, _, p0 = S.choose(cs, SPOT, sg, 1.0, min_rr=0.0)
    assert p0 == len(cs) and p5 < p2 < p0
    weak, _, _ = S.choose(cs, SPOT, sg, 0.4)
    strong, _, _ = S.choose(cs, SPOT, sg, 1.0)
    assert strong and (weak is None or strong["score"] >= weak["score"])


def test_a_leg_without_a_two_sided_quote_removes_every_structure_that_uses_it():
    chain, quotes = board()
    name = chain[24500]["CE"]
    quotes[name] = {"bid": 0, "ask": 90}
    for c in S.candidates(chain, quotes, SPOT):
        assert all(l["symbol"] != name for l in c["legs"])
    assert S.candidates({}, {}, SPOT) == [] and S.candidates(chain, quotes, 0) == []


def test_the_chosen_structure_pays_what_the_desk_would_pay_not_the_mid():
    chain, quotes = board()
    cs = S.candidates(chain, quotes, SPOT)
    c = next(x for x in cs if x["label"] == "long 24500 CE")
    assert c["cost"] == pytest.approx(quotes[chain[24500]["CE"]]["ask"] + S.TICK)


def test_when_the_index_is_expected_to_move_less_than_the_market_prices_in_the_search_picks_a_hedged_structure_with_sold_legs_and_when_more_a_plain_long():
    chain, quotes = board()
    cs, sg = S.candidates(chain, quotes, SPOT), sigma()
    calm, _, _ = S.choose(cs, SPOT, sg * 0.5, 0.5)
    wild, _, _ = S.choose(cs, SPOT, sg * 1.4, 0.5)
    assert calm and any(l["qty"] < 0 for l in calm["legs"]) and "wing" in calm["label"] and math.isfinite(calm["max_gain"]) and calm["max_gain"] >= 2 * calm["max_loss"]
    assert wild and all(l["qty"] > 0 for l in wild["legs"])
    assert calm["pop"] >= S.MIN_POP_DEFAULT and wild["pop"] >= S.MIN_POP_DEFAULT


def test_a_structure_that_only_wins_in_the_tails_is_refused_by_the_chance_of_profit_test():
    chain, quotes = board()
    cs, sg = S.candidates(chain, quotes, SPOT), sigma()
    tails, _, _ = S.choose(cs, SPOT, sg, 1.0, min_pop=0.0)
    safe, _, _ = S.choose(cs, SPOT, sg, 1.0, min_pop=0.55)
    assert tails and safe and safe["pop"] >= 0.55 and tails["score"] >= safe["score"]
    assert S.choose(cs, SPOT, sg, 1.0, min_pop=0.99)[0] is None
