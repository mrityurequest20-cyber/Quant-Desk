"""Plan first, hold overnight, a volatility stop (quantdesk/paper/auto2.py; the owner, 14 Nov 2026). PAPER MONEY ONLY.

The owner: "every day it should analyze the news and everything ... there is a high expectation for the market to move ... prior we are deciding it, not when the market
opens. Then it's fine. Okay, then it takes trade"; "my options, whether buying or selling, must have the overnight holding power"; the stop "based on the market
conditions. How much volatile the market is". And his choices: an underlying-move stop, a big move or a strong direction, both books, held until its exits say so.

What is pinned: with PLAN_ONLY nothing goes live that the day plan did not name before the open, in either book; a planned trade is taken at the open even when the
intraday view does not agree (it was decided before), but not when it has been contradicted, is late, or has become dear; an overnight strategy is held past the close
and across sessions, and closed by the underlying moving 1.5 daily standard deviations against it (times sqrt(sessions)) or on the session before expiry; the shadow
book keeps recording all day."""
from __future__ import annotations

import datetime as dt
import math

import pytest

from quantdesk.paper import auto2 as A2
from tests.test_convex import fat_tails
from tests.test_paper_auto import board
from tests.test_paper_auto2 import IC, cfg, cycle, desk, proven  # noqa: F401  (cfg is a fixture)
from tests.test_paper_dayplan import BRIEF, CLOSE_AGE, UP

IST = A2.IST
PRE = dt.datetime(2026, 11, 9, 7, 30, tzinfo=IST)                       # Monday 07:30: the plan, from Friday's closing books
OPEN = dt.datetime(2026, 11, 9, 9, 25, tzinfo=IST)                      # five minutes after the first entry (Tuesday 10 Nov is a holiday: Diwali Balipratipada)
TAILS = {"NIFTY": fat_tails(daily=0.01)}


def planned_desk(cfg, tmp_path, proven_sid=True):
    """A desk with PLAN_ONLY, a tail model (its daily volatility sets the stop), the up plan built at 07:30 and, if asked, its first item proven."""
    rn, ap = desk(cfg, tmp_path, plan_only=True)
    ap.brief = {**BRIEF, "tails": TAILS}
    dp = ap.plan(board(PRE, age=CLOSE_AGE, **UP), PRE)
    sid = dp["items"][0]["sid"]
    if proven_sid:
        ap.lab = A2.Lab(proven(sid=sid))
        dp = ap.plan(board(PRE, age=CLOSE_AGE, **UP), PRE)
        assert dp["items"][0]["sid"] == sid and dp["items"][0]["proven"]
    return rn, ap, sid


def test_the_stop_is_the_underlying_moving_against_the_trade_by_its_volatility():
    assert A2.VOL_STOP_K == 1.5
    lim = 1.5 * 0.01
    assert A2.vol_stop("up", "BCS", 24500, 0.01, 24500 * math.exp(-lim * 1.01), 1)              # down 1.5 days' sd against an up view
    assert A2.vol_stop("up", "BCS", 24500, 0.01, 24500 * math.exp(-lim * 0.99), 1) is None
    assert A2.vol_stop("up", "BCS", 24500, 0.01, 24500 * math.exp(+lim * 3), 1) is None          # the right way is never a stop
    assert A2.vol_stop("down", "BRP", 24500, 0.01, 24500 * math.exp(lim * 1.01), 1)
    assert A2.vol_stop("flat", "IC", 24500, 0.01, 24500 * math.exp(-lim * 1.01), 1)              # a short-volatility structure: a move either way
    assert A2.vol_stop("flat", "LS", 24500, 0.01, 24500 * math.exp(-lim * 3), 1) is None          # a long straddle wants the move: its premium is its stop
    assert A2.vol_stop("any", "XW", 24500, 0.01, 24500 * math.exp(-lim * 3), 1) is None
    assert A2.vol_stop("up", "BCS", 24500, 0.01, 24500 * math.exp(-lim * 1.2), 2) is None         # two sessions held: sqrt(2) wider
    assert A2.vol_stop("up", "BCS", 24500, 0.02, 24500 * math.exp(-lim * 1.2), 1) is None         # a more volatile market: a wider stop
    assert A2.vol_stop("up", "BCS", None, 0.01, 24000, 1) is None and A2.vol_stop("up", "BCS", 24500, None, 24000, 1) is None


def test_an_unplanned_proven_strategy_never_goes_live_and_the_shadow_book_still_records(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven(), plan_only=True)                               # IC proven: it would trade intraday without PLAN_ONLY
    for i in range(7):
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    assert not rn.account.ledger and ap.shadow                                                   # nothing live; everything still tested in shadow
    rn2, ap2 = desk(cfg, tmp_path / "b", stats=proven(), plan_only=False)
    for i in range(7):
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn2, ap2, board(t), t)
    assert rn2.account.positions                                                                 # the same record trades when the plan is not required


def test_a_planned_trade_is_taken_at_the_open_though_the_open_does_not_agree(cfg, tmp_path):
    rn, ap, sid = planned_desk(cfg, tmp_path)
    for i in range(3):                                                                           # a calm open: the intraday view is flat, not up
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    assert ap.last_state["NIFTY"]["view"] != "up"
    pos = list(rn.account.positions.values())
    assert pos and all(p.strategy.startswith(f"{A2.TAG} {sid} NIFTY p") and " d" in p.strategy for p in pos), [p.strategy for p in pos]
    assert "On the day plan built before the open." in pos[0].thesis


def test_a_planned_trade_is_not_taken_when_contradicted_late_or_dear(cfg, tmp_path):
    rn, ap, sid = planned_desk(cfg, tmp_path)
    late = dt.datetime(2026, 11, 9, 11, 5, tzinfo=IST)                                          # past PLAN_ENTRY_MIN after 09:20
    for i in range(3):
        t = late + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    assert not rn.account.ledger
    rn, ap, sid = planned_desk(cfg, tmp_path / "b")
    for i in range(3):                                                                           # the open says down: the plan is contradicted
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t, cb=500, ca=3000, pb=3000, pa=500, fwd_gap=0.2), t)
    assert ap.last_state["NIFTY"]["view"] == "down" and not rn.account.ledger
    rn, ap, sid = planned_desk(cfg, tmp_path / "c")
    for i in range(3):                                                                           # gapped down through the stop from the planned price
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t, spot=24500 * math.exp(-0.02)), t)
    assert not rn.account.ledger
    rn, ap, sid = planned_desk(cfg, tmp_path / "d")
    for it in ap.day_plan["items"]:
        it["risk_unit"] = it["risk_unit"] / 2                                                    # it now costs twice what the plan priced
    for i in range(3):
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    assert not rn.account.ledger


def test_an_overnight_trade_is_held_past_the_close_and_stopped_by_the_volatility_stop(cfg, tmp_path):
    rn, ap, sid = planned_desk(cfg, tmp_path)
    for i in range(3):
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    held = set(rn.account.positions)
    assert held
    for t in (dt.datetime(2026, 11, 9, 15, 20, tzinfo=IST), dt.datetime(2026, 11, 11, 9, 30, tzinfo=IST)):
        cycle(rn, ap, board(t), t)
        assert set(rn.account.positions) == held                                                 # through the close and into the next session
    sd = A2.AutoPilotV2._cx_meta(next(iter(rn.account.positions.values())).strategy)["d"]
    assert sd == pytest.approx(max(TAILS["NIFTY"]["sigma"], 0.0), rel=0.05)
    t = dt.datetime(2026, 11, 11, 10, 0, tzinfo=IST)
    drop = 24500 * math.exp(-1.6 * sd * math.sqrt(2))                                           # Monday and Wednesday: two sessions held, beyond 1.5 sd x sqrt(2)
    mine, rep = cycle(rn, ap, board(t, spot=drop), t)
    assert not rn.account.positions and any("volatility stop" in o.get("_why", "") for o in mine)


def test_an_overnight_trade_is_out_by_the_close_of_the_session_before_expiry(cfg, tmp_path):
    rn, ap, sid = planned_desk(cfg, tmp_path)
    for i in range(3):
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, board(t), t)
    assert rn.account.positions
    t = dt.datetime(2026, 11, 11, 15, 16, tzinfo=IST)                                            # Wednesday, the session before Thursday's expiry
    mine, rep = cycle(rn, ap, board(t), t)
    assert not rn.account.positions and any("its expiry is next" in o.get("_why", "") for o in mine)


def test_a_convex_trade_also_goes_live_only_when_planned(cfg, tmp_path):
    from tests.test_convex import XG, desk as cx_desk, proven as cx_proven, wide_board
    rn, ap = cx_desk(cfg, tmp_path, stats=cx_proven())                                         # a 1-crore paper account: a strangle lot fits 0.5% of it
    ap.plan_only = True
    for i in range(3):                                                                           # cheap options intraday, a proven convex strategy, but no plan
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, wide_board(t), t)
    assert "cheapvol" in ap.last_state["NIFTY"]["cx"][1] and not rn.account.ledger
    ap.day_plan = {"built_at": "2026-11-09T07:30", "items": [{"u": "NIFTY", "sid": XG, "convex": True, "risk_unit": 1e9, "spot": 24500.0}]}
    for i in range(3, 6):
        t = OPEN + dt.timedelta(minutes=i)
        cycle(rn, ap, wide_board(t), t)
    assert {p.strategy.split()[2] for p in rn.account.positions.values()} == {XG}
