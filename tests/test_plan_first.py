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


def test_a_convex_trade_unplanned_and_not_yet_held_five_minutes_waits_and_a_planned_one_goes(cfg, tmp_path):
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


# ---- the one exception: important news in the session (owner, 14 Nov 2026: "if during the trading time if any news comes up which could be important then also allow
# the system to trade") ----------------------------------------------------------------------------------------------------------------------------------------------
NEWS_T = dt.datetime(2026, 11, 9, 11, 30, tzinfo=IST)                   # mid-session, long after the plan's entry window
UP_BOOK = dict(cb=3000, ca=500, pb=500, pa=3000, fwd_gap=-0.2)          # the live book and the options forward both say up
CUT = "RBI cuts repo rate by 25 bps, signals more easing"


def story(title, t, impact="high", novelty=0.9, recap=False, symbols=("NIFTY",), sid="s1"):
    return {"id": sid, "title": title, "ts": t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "impact": impact, "novelty": novelty, "tone": 0.6,
            "symbols": list(symbols), "recap": recap}


def news_desk(cfg, tmp_path):
    """PLAN_ONLY, a plan built at 07:30 with nothing on it, a tail model, and a proven overnight long call (one strategy a strong up view can take)."""
    sid = "LC0.uaan.3/1.o"
    rn, ap = desk(cfg, tmp_path, stats=proven(sid=sid), plan_only=True)
    ap.brief = {**BRIEF, "tails": TAILS}
    ap.day_plan = {"built_at": "2026-11-09T07:30+05:30", "items": []}
    return rn, ap, sid


def session(rn, ap, news, start=NEWS_T, minutes=6, **kw):
    """Cycles exactly as the session runs them, with the news digest handed in."""
    from quantdesk.paper import runner as RR
    for i in range(minutes):
        t = start + dt.timedelta(minutes=i)
        snap = board(t, **kw)
        rn.step(snap, ap.decide(snap, rn.account, RR.Runner.server_now(snap), news=news), False, t.astimezone(dt.timezone.utc))


def test_important_news_in_the_session_lets_a_strong_direction_trade(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    news = {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2))], "events": []}
    session(rn, ap, news, **UP_BOOK)
    pos = list(rn.account.positions.values())
    assert pos and pos[0].strategy.startswith(f"{A2.TAG} {sid} NIFTY p"), [p.strategy for p in pos]
    assert "Not on the plan: taken on important news in the session (news at" in pos[0].thesis and CUT[:30] in pos[0].thesis


def test_without_important_news_of_todays_session_the_same_readings_open_nothing(cfg, tmp_path):
    for label, news in (("no news", {"items": [], "events": []}),
                        ("before the plan", {"items": [story(CUT, dt.datetime(2026, 11, 9, 7, 0, tzinfo=IST))], "events": []}),
                        ("yesterday", {"items": [story(CUT, dt.datetime(2026, 11, 6, 14, 0, tzinfo=IST))], "events": []}),
                        ("a recap", {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2), recap=True)], "events": []}),
                        ("low impact", {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2), impact="medium")], "events": []}),
                        ("a repeat", {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2), novelty=0.2)], "events": []})):
        rn, ap, sid = news_desk(cfg, tmp_path / label.replace(" ", "_"))
        session(rn, ap, news, **UP_BOOK)
        assert not rn.account.ledger, label


def test_there_is_no_window_news_from_earlier_in_the_session_still_counts_while_the_market_agrees(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    news = {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=80))], "events": []}           # an hour and twenty minutes ago
    session(rn, ap, news, **UP_BOOK)
    assert rn.account.positions                                                                  # the news still votes, the book and the forward agree: taken
    rn, ap, sid = news_desk(cfg, tmp_path / "b")
    session(rn, ap, news)                                                                        # the same story, but the market no longer agrees with it
    assert not rn.account.ledger


def test_one_news_driven_directional_position_per_instrument_at_a_time(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    ap.lab = A2.Lab({**proven(sid=sid), **proven(sid="LC0.uaan.2/1.o")})                       # two proven overnight strategies that could both take it
    news = {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2))], "events": []}
    session(rn, ap, news, minutes=10, **UP_BOOK)
    pk = ap.live_packages(rn.account)
    assert len(pk) == 1, list(pk)


def test_important_news_without_a_strong_direction_takes_no_directional_trade(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    news = {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2))], "events": []}
    assert ap.news_trigger("NIFTY", news, NEWS_T)["why"].startswith("news at")                  # the news counts
    session(rn, ap, news)                                                                        # it says up, but the book and the forward say nothing
    assert not rn.account.ledger                                                                 # one reading is not a strong direction


def test_news_reaches_the_instruments_it_moves(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    crude = {"items": [story("Crude jumps 7% after strikes on Gulf tankers", NEWS_T - dt.timedelta(minutes=1), symbols=(), sid="s2")], "events": []}
    assert ap.news_trigger("USDINR", crude, NEWS_T) and ap.news_trigger("TCS", crude, NEWS_T) is None   # crude reaches the rupee, not an IT exporter
    assert ap.news_trigger("NIFTY", crude, NEWS_T - dt.timedelta(minutes=5)) is None             # not before it was published


def test_important_news_also_lets_a_proven_convex_trade_through_when_its_test_passes(cfg, tmp_path):
    from quantdesk.paper import runner as RR
    from tests.test_convex import XG, desk as cx_desk, proven as cx_proven, wide_board
    news = {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2))], "events": []}
    for label, nw in (("without", {"items": [], "events": []}), ("with", news)):
        rn, ap = cx_desk(cfg, tmp_path / label, stats=cx_proven())
        ap.plan_only = True
        ap.day_plan = {"built_at": "2026-11-09T07:30+05:30", "items": []}
        for i in range(4):
            t = NEWS_T + dt.timedelta(minutes=i)
            snap = wide_board(t)
            rn.step(snap, ap.decide(snap, rn.account, RR.Runner.server_now(snap), news=nw), False, t.astimezone(dt.timezone.utc))
        got = {p.strategy.split()[2] for p in rn.account.positions.values()}
        assert got == ({XG} if label == "with" else set()), (label, got)
        if got:
            assert "taken on important news in the session" in next(iter(rn.account.positions.values())).thesis


# ---- and the data (owner, 14 Nov 2026: "it's not only limited to news, it's also applies to data also ... In a live market, there is a different setup") -----------
def rising(rn, ap, minutes, start=NEWS_T, step=0.0005, **kw):
    """A live market going up: the book and the options forward say up, and the price climbs `step` a minute (a five-minute move of 0.25%)."""
    from quantdesk.paper import runner as RR
    for i in range(minutes):
        t = start + dt.timedelta(minutes=i)
        snap = board(t, spot=24500 * math.exp(step * i), **UP_BOOK, **kw)
        rn.step(snap, ap.decide(snap, rn.account, RR.Runner.server_now(snap), news={"items": [], "events": []}), False, t.astimezone(dt.timezone.utc))


def test_a_change_in_the_live_data_that_holds_is_a_reason_to_trade(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)                                                     # the plan saw no direction for NIFTY
    rising(rn, ap, 13)
    st = ap.state(board(NEWS_T + dt.timedelta(minutes=13), spot=24500 * math.exp(0.0005 * 13), **UP_BOOK), "NIFTY",
                  A2.V1.chains(board(NEWS_T), ap.und, ap.lots), NEWS_T + dt.timedelta(minutes=13), None)
    assert st["agree"] == "up" and {"book", "forward", "move"} <= set(st["sources"])
    pos = list(rn.account.positions.values())
    assert pos and pos[0].strategy.startswith(f"{A2.TAG} {sid} NIFTY p"), [p.strategy for p in pos]
    assert "Not on the plan: taken on a change in the live data (data: the pre-market read was no direction, the live market says up" in pos[0].thesis


def test_a_flicker_is_not_a_change(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    rising(rn, ap, 8)                                                                            # the five-minute move exists from minute 5: three minutes of agreement
    assert ap.agree_since["NIFTY"] and not rn.account.ledger


def test_what_the_plan_already_expected_is_not_a_change(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    ap.day_plan["states"] = {"NIFTY": {"view": "up"}}                                          # the pre-market read already said up (and nothing was proven to take it)
    rising(rn, ap, 13)
    assert ap.agree_since["NIFTY"][0] == 1                                                       # the live market does agree, strongly and for long enough
    assert not rn.account.ledger                                                                 # but no change in the read since the open, no change point: not a new reason


def test_a_big_move_test_that_holds_on_the_live_board_is_a_reason_too(cfg, tmp_path):
    from quantdesk.paper import runner as RR
    from tests.test_convex import XG, desk as cx_desk, proven as cx_proven, wide_board
    rn, ap = cx_desk(cfg, tmp_path, stats=cx_proven())
    ap.plan_only = True
    ap.day_plan = {"built_at": "2026-11-09T07:30+05:30", "items": []}
    for i in range(8):                                                                           # cheap options all along: the test holds past LIVE_PERSIST_S
        t = NEWS_T + dt.timedelta(minutes=i)
        snap = wide_board(t)
        rn.step(snap, ap.decide(snap, rn.account, RR.Runner.server_now(snap), news={"items": [], "events": []}), False, t.astimezone(dt.timezone.utc))
        if i < 5:
            assert not rn.account.ledger, i
    pos = list(rn.account.positions.values())
    assert {p.strategy.split()[2] for p in pos} == {XG} and "taken on a change in the live data (data: its test has held" in pos[0].thesis


# ---- the risk review of 14 Nov 2026 (findings 1, 2, 4, 5): each pinned so it cannot come back -------------------------------------------------------------
def test_a_tail_test_must_itself_hold_five_minutes_not_just_be_looked_at(cfg, tmp_path):
    from quantdesk.paper import runner as RR
    from tests.test_convex import desk as cx_desk, wide_board
    tail = "XG2.atan.3/1.s"                                                                      # passes the EVT test on cheap options, fails it on rich ones
    rn, ap = cx_desk(cfg, tmp_path, stats={tail: [20, 16.0, 80.0, 4]})
    ap.plan_only = True
    ap.day_plan = {"built_at": "2026-11-09T07:30+05:30", "items": []}

    def at(i, iv):
        t = NEWS_T + dt.timedelta(minutes=i)
        snap = wide_board(t, iv=iv)
        rn.step(snap, ap.decide(snap, rn.account, RR.Runner.server_now(snap), news={"items": [], "events": []}), False, t.astimezone(dt.timezone.utc))
    for i in range(7):
        at(i, 0.40)                                                                              # rich: the tail test fails, whatever matches() says
    at(7, 0.10)                                                                                  # one cheap cycle: a flicker
    assert not rn.account.ledger
    for i in range(8, 12):
        at(i, 0.10)
    assert not rn.account.ledger                                                                 # four minutes held: not yet
    for i in range(12, 14):
        at(i, 0.10)
    assert {p.strategy.split()[2] for p in rn.account.positions.values()} == {tail}             # five minutes of the test itself holding


def test_a_hold_with_a_gap_starts_again():
    ap = A2.AutoPilotV2(("NIFTY",), {"NIFTY": 65}, lambda *a: 0.0, None)
    ap.cx_first = {}
    k = ("NIFTY", "XS0.avan.3/1.s")
    assert not ap._held(k, 0.0) and not ap._held(k, 60.0) and not ap._held(k, 240.0)            # 240 - 60 > LIVE_GAP_S: the clock restarted at 240
    assert not ap._held(k, 480.0) and ap._held(k, 540.0) is False and ap._held(k, 600.0) is False   # 480 - 240 > gap again
    for t in range(600, 960, 60):
        held = ap._held(k, float(t))
    assert held                                                                                  # sighted every minute for five: held
    st = {"agree": "up", "sources": ["book", "forward", "move"], "votes": 3, "read": None, "hmm": {}}
    ap.agree_since = {"NIFTY": (1, NEWS_T.timestamp() - 3600, NEWS_T.timestamp() - 1800)}       # held an hour, but last seen half an hour ago
    assert ap.live_trigger("NIFTY", st, {"items": []}, NEWS_T) is None
    ap.agree_since = {"NIFTY": (1, NEWS_T.timestamp() - 600, NEWS_T.timestamp())}
    assert ap.live_trigger("NIFTY", st, {"items": []}, NEWS_T)["kind"] == "data"


def test_a_planned_strategy_refused_by_the_plan_does_not_come_back_through_a_trigger(cfg, tmp_path):
    rn, ap, sid = news_desk(cfg, tmp_path)
    ap.day_plan["items"] = [{"u": "NIFTY", "sid": sid, "risk_unit": 1e9, "spot": 24500.0}]     # planned, but 11:30 is past its entry window
    news = {"items": [story(CUT, NEWS_T - dt.timedelta(minutes=2))], "events": []}
    session(rn, ap, news, **UP_BOOK)
    assert not rn.account.ledger
    rn, ap, sid = news_desk(cfg, tmp_path / "b")                                               # the same news with it unplanned: taken, and labelled as news
    session(rn, ap, news, **UP_BOOK)
    th = next(iter(rn.account.positions.values())).thesis
    assert "taken on important news" in th and "On the day plan" not in th


def test_the_convex_stake_holds_at_the_orders_own_limit_price(cfg, tmp_path):
    from quantdesk.paper import convex as CX
    from tests.test_convex import XG, desk as cx_desk, proven as cx_proven, wide_board
    from quantdesk.paper import runner as RR
    rn, ap = cx_desk(cfg, tmp_path, stats=cx_proven())
    for i in range(2):
        t = OPEN + dt.timedelta(minutes=i)
        snap = wide_board(t)
        mine = ap.decide(snap, rn.account, RR.Runner.server_now(snap))
        rn.step(snap, mine, False, t.astimezone(dt.timezone.utc))
        for o in mine:
            if o.get("side") == "package":
                assert o["net_limit"] <= CX.STAKE_PCT * 10_000_000                              # the most a fill may cost is inside the 0.5% stake
    paid = sum(r["qty"] * r["price"] + r["fees"] for r in rn.account.ledger if r["kind"] == "buy")
    assert 0 < paid <= CX.STAKE_PCT * 10_000_000 and {p.strategy.split()[2] for p in rn.account.positions.values()} == {XG}
