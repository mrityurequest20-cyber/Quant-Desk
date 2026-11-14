"""The Convexity desk (quantdesk/paper/convex.py, wired into AUTO v2; owner, 14 Nov 2026: "Direction ... is very hard ... We want to have things of high risk to reward
only ... 100, 200, 300, 400, 500, 1000% return"). PAPER MONEY ONLY.

What is pinned: the four tests measure what they say (the event's own move is split out of the term structure; the tail test integrates the fitted tails); sizing is the
owner's (0.5% of the account a trade, 3% a month, three open); the exits are the owner's thirds (+100%, +300%, the rest trailed) and the event, time and repricing exits;
the shadow book scores a convex trade with its thirds; nothing trades paper money before its family has 20 shadow trades; and a proven convex package goes live as ONE
package through the REAL runner and risk gate, and is sold in thirds there."""
from __future__ import annotations

import datetime as dt
import math
import random
from math import exp, log, sqrt
from statistics import NormalDist

import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper import convex as CX
from quantdesk.paper import runner as R
from quantdesk.paper import tails as TL
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate
from quantdesk.paperlink.cli import auto_v2
from tests.test_paper_auto import T0
from tests.test_paper_auto2 import cfg, cycle  # noqa: F401  (cfg is a fixture)

IST = A2.IST
EXP = dt.date(2026, 11, 12)
STRIKES = list(range(22000, 27001, 50))
N = NormalDist().cdf


def wide_board(t, spot=24500.0, iv=0.10, spread=0.4, expiries=((EXP, None),)):
    """A NIFTY board with strikes from 22,000 to 27,000, Black-Scholes at `iv` (or each expiry's own: [(date, iv or None)])."""
    q = {}
    for e, e_iv in expiries:
        q.update(_chain(t, spot, e_iv or iv, spread, e))
    fwd = spot * exp(A2.RATE * (dt.datetime.combine(EXP, dt.time(15, 30), tzinfo=IST) - t).total_seconds() / (365.25 * 86400))
    q.update({"NIFTY": dict(ltp=spot, age_s=1.0), "NIFTY-FUT": dict(bid=fwd - 0.5, ask=fwd + 0.5, ltp=fwd, age_s=1.0)})
    return {"now": int(t.timestamp() * 1000), "quotes": q}


def _chain(t, spot, iv, spread, e):
    T = (dt.datetime.combine(e, dt.time(15, 30), tzinfo=IST) - t).total_seconds() / (365.25 * 86400)
    r = A2.RATE

    def bs(kind, k):
        d1 = (log(spot / k) + (r + iv * iv / 2) * T) / (iv * sqrt(T))
        d2 = d1 - iv * sqrt(T)
        return spot * N(d1) - k * exp(-r * T) * N(d2) if kind == "CE" else k * exp(-r * T) * N(-d2) - spot * N(-d1)
    q = {}
    for k in STRIKES:
        for kind in ("CE", "PE"):
            m = max(bs(kind, k), 0.2)
            q[f"NIFTY{e:%d%b%y}{k}{kind}".upper()] = dict(bid=max(0.05, round((m - spread / 2) / 0.05) * 0.05), ask=round((m + spread / 2) / 0.05) * 0.05, ltp=m,
                                                         bid_qty=1000, ask_qty=1000, age_s=1.0, oi=100000)
    return q


def fat_tails(daily=0.015, seed=5):
    """A tail model (tails.fit_series) from 1,500 Student-t(4) daily returns of about `daily` standard deviation."""
    rng, px = random.Random(seed), [100.0]
    for _ in range(1500):
        z = rng.gauss(0, 1) / math.sqrt(sum(rng.gauss(0, 1) ** 2 for _ in range(4)) / 4)
        px.append(px[-1] * math.exp(daily / math.sqrt(2) * z))
    return TL.fit_series(px)


def desk(cfg, tmp_path, capital=10_000_000, stats=None, seed=1):
    rn = R.Runner(cfg, Account(capital), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K")), kill_file=tmp_path / "K")
    ap = auto_v2(cfg, ("NIFTY",), {"NIFTY": 65})
    ap.rng = random.Random(seed)
    ap.brief = {"tails": {"NIFTY": fat_tails()}}
    if stats is not None:
        ap.lab = A2.Lab(stats)
    return rn, ap


# ---- the tests, one at a time -------------------------------------------------------------------------------------------------------------------------
def test_the_options_move_is_measured_against_the_forecast_over_the_same_days():
    assert CX.vol_ratio(0.10, 3 / 365.25, 0.015, 3) == pytest.approx(0.10 * sqrt(3 / 365.25) / (0.015 * sqrt(3)))
    assert CX.vol_ratio(0.0, 0.01, 0.015, 3) is None and CX.vol_ratio(0.1, 0.01, None, 3) is None


def test_the_events_own_move_is_split_out_of_the_term_structure():
    vb, E, Tn, Tx = 0.12 ** 2, 0.02, 3 / 365.25, 10 / 365.25                                  # a 12% base and a 2% event jump inside both expiries
    iv_n, iv_x = sqrt((vb * Tn + E * E) / Tn), sqrt((vb * Tx + E * E) / Tx)
    got = CX.event_split(iv_n, Tn, iv_x, Tx)
    assert got[0] == pytest.approx(E, rel=1e-9) and got[1] == pytest.approx(vb, rel=1e-9)
    day = CX.implied_event_abs(*got, Tn, 3)
    assert day == pytest.approx(sqrt(vb * Tn / 3 + E * E) * sqrt(2 / math.pi))
    assert CX.event_split(0.12, Tn, 0.12, Tn) is None and CX.event_split(0.30, Tn, 0.05, Tx)[0] >= 0    # an inverted term structure is not a negative variance
    assert CX.hist_event_abs({"abs_w": 0.012, "n_eff": 4.0}) == (0.012, 4.0) and CX.hist_event_abs({"abs_w": 0.012, "n_eff": 2.0}) is None


def test_a_squeeze_needs_a_quiet_hour_a_fresh_move_and_options_not_rich():
    assert CX.squeeze(0.10, 0.015, "volatility up", 0.9)                                        # 0.10 / sqrt(252) = 0.0063 a day against 0.015: compressed
    assert CX.squeeze(0.10, 0.015, "drift down", 0.9)                                            # a drift either way: the direction is not used
    assert CX.squeeze(0.30, 0.015, "volatility up", 0.9) is None                                 # not quiet
    assert CX.squeeze(0.10, 0.015, None, 0.9) is None and CX.squeeze(0.10, 0.015, "volatility up", 1.1) is None


def test_the_legs_are_bought_both_sides():
    ks = list(range(24000, 25001, 50))
    atm = ks.index(24500)
    assert CX.legs("XS", 0, ks, atm, 24500, None) == [(1, "CE", 24500), (1, "PE", 24500)]
    assert CX.legs("XG", 2, ks, atm, 24500, None) == [(1, "CE", 24600), (1, "PE", 24400)]
    assert CX.legs("XW", 15, ks, atm, 24500, 0.01) == [(1, "CE", 24900), (1, "PE", 24100)]     # the first strikes beyond 24500 e^{+-1.5%}: 24869 and 24135
    assert CX.legs("XW", 25, ks, atm, 24500, 0.03) is None                                       # beyond the board
    assert all(l[0] > 0 for l in CX.legs("XG", 1, ks, atm, 24500, None))


# ---- sizing and the budget (the owner's: 0.5% a trade, 3% a month) ------------------------------------------------------------------------------------
def test_the_stake_and_the_month():
    assert CX.STAKE_PCT == 0.005 and CX.MONTH_BUDGET_PCT == 0.03 and CX.MAX_OPEN == 3
    assert CX.lots_for(2500, 15.0, 65) == 2 and CX.lots_for(2500, 40.0, 65) == 0 and CX.lots_for(-1, 15.0, 65) == 0
    ledger = [{"kind": "buy", "ts": "2026-11-16T10:00:00+05:30", "qty": 130, "price": 9.5, "fees": 40.0, "strategy": "AUTO v2 XW15.avan.3/1.s NIFTY n2"},
              {"kind": "buy", "ts": "2026-11-16T10:00:00+05:30", "qty": 65, "price": 100.0, "fees": 20.0, "strategy": "AUTO v2 IC1.faan.1/0.5.d NIFTY"},
              {"kind": "sell", "ts": "2026-11-16T11:00:00+05:30", "qty": 130, "price": 30.0, "fees": 40.0, "strategy": "AUTO v2 XW15.avan.3/1.s NIFTY n2"},
              {"kind": "buy", "ts": "2026-10-30T10:00:00+05:30", "qty": 65, "price": 9.0, "fees": 20.0, "strategy": "AUTO v2 XS0.avan.3/1.s NIFTY n1"}]
    assert CX.month_spent(ledger, "2026-11") == pytest.approx(130 * 9.5 + 40)                    # this month's convex buys only; a sale does not refill it


# ---- the exits (the owner's: thirds) ------------------------------------------------------------------------------------------------------------------
def test_the_thirds_then_the_trail():
    now = T0
    assert CX.tranches(6) == (2, 2) and CX.tranches(7) == (2, 2) and CX.tranches(2) == (1, 0) and CX.tranches(1) == (0, 0)
    assert CX.exit_action(0.4, 0.4, False, False, now=now) == (None, None)                      # no price stop: the premium is the most it can lose
    assert CX.exit_action(-0.8, 0.0, False, False, now=now) == (None, None)
    assert CX.exit_action(1.1, 1.1, False, False, now=now)[0] == "rung1"
    assert CX.exit_action(3.2, 3.2, True, False, now=now)[0] == "rung2"
    assert CX.exit_action(3.2, 3.2, False, False, now=now)[0] == "rung2"                        # a jump past both rungs: both thirds
    assert CX.exit_action(5.0, 5.5, True, True, now=now) == (None, None)                        # the last third runs
    assert CX.exit_action(3.5, 5.5, True, True, now=now)[0] == "all"                            # gave back more than 35% of its peak gain
    ev = now - dt.timedelta(minutes=20)
    assert "the event has passed" in CX.exit_action(0.2, 0.3, False, False, now=now, event_at=ev)[1]
    assert CX.exit_action(0.2, 0.3, False, False, now=now, event_at=now - dt.timedelta(minutes=5)) == (None, None)
    assert CX.exit_action(0.1, 0.2, False, False, now=now, rich=True)[0] == "all"               # repriced before the move: take the volatility's gain
    assert CX.exit_action(1.5, 1.5, False, False, now=now, rich=True)[0] == "rung1"             # a runner keeps its ladder
    assert CX.exit_action(-0.3, 0.2, False, False, now=now, held_sessions=5)[0] == "all" and CX.exit_action(-0.3, 0.2, False, False, now=now, last_day=True)[0] == "all"


def test_the_shadow_ladder_scores_the_whole_trade():
    lad = CX.ShadowLadder()
    assert lad.step("rung1", 1.0) is None and lad.step("rung2", 3.0) is None
    assert lad.step("all", 4.0) == pytest.approx(1 / 3 + 1 + 4 / 3)
    lad = CX.ShadowLadder()
    assert lad.step("all", -0.9) == pytest.approx(-0.9)
    lad = CX.ShadowLadder()
    lad.step("rung2", 3.5)                                                                       # straight past both
    assert lad.done1 and lad.done2 and lad.step("all", 2.5) == pytest.approx(3.5 * 2 / 3 + 2.5 / 3)


# ---- in AUTO v2 -------------------------------------------------------------------------------------------------------------------------------------
def test_the_catalogue_has_no_view_and_its_ids_say_the_test():
    assert len(A2.CX_CATALOGUE) == (1 + 2 + 2) * 4 * 2 and all(s.view == "any" and A2.BY_SID[s.sid] is s for s in A2.CX_CATALOGUE)
    assert {s.sid.split(".")[1][1] for s in A2.CX_CATALOGUE} == {"v", "k", "t", "q"}
    assert all(len(f"{A2.TAG} {s.sid} BAJAJ-AUTO n999 e2612041000") <= 60 for s in A2.CX_CATALOGUE)
    assert not set(A2.CX_CATALOGUE) & set(A2.CATALOGUE)                                         # the old book is untouched: both books trade


def test_cheap_options_open_convex_trades_in_shadow_and_none_live_without_a_record(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    for i in range(3):
        t = T0 + dt.timedelta(minutes=i)
        cycle(rn, ap, wide_board(t), t)
    cx = ap.last_state["NIFTY"]["cx"]
    assert cx[0] < CX.CHEAP_RATIO and "cheapvol" in cx[1]                                       # 10% implied against a tail model of about 1.5% a day
    opened = {sid for sid, u in ap.shadow if CX.is_convex(CX.sid_struct(sid))}
    assert opened and {A2.BY_SID[sid].vol for sid in opened} <= {"cheapvol", "tail"}
    assert not rn.account.ledger and ap.summary()["convex"]["ready"] == 0


def test_rich_options_pass_no_volatility_test(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    ap.brief = {"tails": {"NIFTY": fat_tails(daily=0.004)}}                                     # a calm instrument: 10% implied is rich against it
    for i in range(3):
        t = T0 + dt.timedelta(minutes=i)
        cycle(rn, ap, wide_board(t), t)
    assert ap.last_state["NIFTY"]["cx"][0] > CX.RICH_RATIO and ap.last_state["NIFTY"]["cx"][1] == []
    assert not {sid for sid, u in ap.shadow if CX.is_convex(CX.sid_struct(sid)) and A2.BY_SID[sid].vol != "tail"}


XG = "XG2.avan.3/1.s"


def proven(sid=XG, n=20):
    return {sid: [n, 0.8 * n, 4.0 * n, n // 5]}                                                  # mean +0.8R from a few large wins


def test_the_proof_gate_is_the_familys_twenty_trades_and_a_positive_mean():
    lab = A2.Lab(proven(n=20))
    assert lab.convex_ready(A2.BY_SID[XG])
    assert not A2.Lab(proven(n=12)).convex_ready(A2.BY_SID[XG])                                # its family has 12, not 20
    assert not A2.Lab({XG: [20, -0.2 * 20, 4.0 * 20, 3]}).convex_ready(A2.BY_SID[XG])          # a negative mean never trades
    two = A2.Lab({XG: [16, 0.8 * 16, 4.0 * 16, 3], "XG1.avan.3/1.s": [4, 2.0, 16.0, 1]})
    assert two.convex_ready(A2.BY_SID[XG]) and not two.convex_ready(A2.BY_SID["XG1.avan.3/1.s"])   # 20 in the family, but 4 of its own
    lab.add(XG, 55.0)
    assert lab.stats[XG][1] == pytest.approx(0.8 * 20 + CX.R_CAP)                               # a bad quote cannot write +55R


def test_a_proven_convex_package_goes_live_sized_by_the_stake_and_is_sold_in_thirds(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven())
    t = T0
    for i in range(2):
        t = T0 + dt.timedelta(minutes=i)
        mine, rep = cycle(rn, ap, wide_board(t), t)
    pos = {s: p for s, p in rn.account.positions.items()}
    assert set(pos) == {"NIFTY12NOV2624600CE", "NIFTY12NOV2624400PE"}, [r for r in rep["results"]]
    lots = pos["NIFTY12NOV2624600CE"].qty // 65
    p = next(iter(pos.values()))
    paid = sum(x.avg_price for x in pos.values()) * 65 * lots
    assert lots >= 3 and paid <= CX.STAKE_PCT * 10_000_000 and p.strategy == f"AUTO v2 {XG} NIFTY n{lots}"
    assert "Convexity" in p.thesis and "a third at +100%" in p.thesis
    t1, t2 = CX.tranches(lots)

    def at(spot, minutes):
        tt = T0 + dt.timedelta(minutes=minutes)
        return cycle(rn, ap, wide_board(tt, spot=spot), tt)

    at(24950, 10)                                                                                 # the move comes: +100% and more
    assert rn.account.positions["NIFTY12NOV2624600CE"].qty == (lots - t1) * 65 and rn.account.positions["NIFTY12NOV2624400PE"].qty == (lots - t1) * 65
    at(25350, 11)                                                                                 # past +300%
    assert rn.account.positions["NIFTY12NOV2624600CE"].qty == (lots - t1 - t2) * 65
    at(25350, 12)
    assert rn.account.positions["NIFTY12NOV2624600CE"].qty == (lots - t1 - t2) * 65              # the last third runs
    at(24950, 13)                                                                                 # gives back most of it: the trail sells the rest
    assert not rn.account.positions
    assert ap.summary()["convex"]["spent"] == pytest.approx(paid + sum(r["fees"] for r in rn.account.ledger if r["kind"] == "buy"), rel=0.01)


def test_the_month_budget_stops_new_convex_trades(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven())
    rn.account.ledger.append({"kind": "buy", "ts": T0.isoformat(), "qty": 65, "price": 4600.0, "fees": 0.0, "strategy": f"AUTO v2 {XG} NIFTY n1"})   # 299,000 of 300,000
    for i in range(2):
        t = T0 + dt.timedelta(minutes=i)
        cycle(rn, ap, wide_board(t), t)
    assert not rn.account.positions and "left of this month's 3%" in ap.summary()["convex"]["note"]


def test_an_event_the_options_price_too_small_is_bought_both_sides_and_sold_after_it(cfg, tmp_path):
    from quantdesk.paper import eventcal as EC
    rn, ap = desk(cfg, tmp_path)
    nxt = dt.date(2026, 11, 19)
    rbi = {"at": "2026-11-10T10:00+05:30", "name": "RBI MPC decision", "kind": "rbi", "impact": "high", "subjects": ["rbi"], "source": "config"}
    assert EC.touches("NIFTY", rbi) >= EC.TOUCH_MIN["high"]
    ap.brief = {"tails": {"NIFTY": fat_tails(daily=0.006)}, "calendar": [rbi],                   # a calm tail model: no cheap-volatility test, only the event's
                "news_analogs": {"rbi": {"NIFTY": {"n": 40, "n_eff": 6.0, "p_up": 0.5, "abs_w": 0.015}}}}
    board = lambda t: wide_board(t, iv=0.10, expiries=((EXP, 0.10), (nxt, 0.10)))                  # noqa: E731 - flat term structure: no event priced
    for i in range(3):
        t = T0 + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    cx = ap.last_state["NIFTY"]["cx"]
    assert "event" in cx[1] and "cheapvol" not in cx[1]
    ev = [k for k in ap.shadow if A2.BY_SID[k[0]].vol == "event"]
    assert ev and all(ap.shadow[k]["event_at"] == "2026-11-10T10:00+05:30" for k in ev)
    before = sum(v[0] for v in ap.lab.stats.values())
    t = dt.datetime(2026, 11, 10, 10, 20, tzinfo=IST)                                             # twenty minutes after the decision
    cycle(rn, ap, board(t), t)
    assert not [k for k in ap.shadow if A2.BY_SID[k[0]].vol == "event"] and sum(v[0] for v in ap.lab.stats.values()) >= before + len(ev)
    ap.brief["news_analogs"]["rbi"]["NIFTY"]["abs_w"] = 0.004                                      # a past of small moves: the options price it fairly
    rn2, ap2 = desk(cfg, tmp_path / "b")
    ap2.brief = ap.brief
    for i in range(2):
        t = T0 + dt.timedelta(minutes=i)
        cycle(rn2, ap2, board(t), t)
    assert "event" not in ap2.last_state["NIFTY"]["cx"][1]
