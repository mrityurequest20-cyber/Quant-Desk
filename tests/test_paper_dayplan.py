"""The day plan (quantdesk/paper/auto2.py, owner's order of 13 Nov 2026): from 06:00 to 09:15 the paper desk plans the day from last night's closing books, the overnight markets,
the news and the pre-market brief, and lists the defined-risk strategies with reward to risk of PLAN_MIN_RR or better. The open then takes a planned strategy first, through the very
same proof gate (MIN_TRADES shadow trades, a positive draw) and risk gate. PAPER MONEY ONLY."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from quantdesk.paper import auto2 as A2
from tests.test_paper_auto import T0, board
from tests.test_paper_auto2 import IC, calm, cfg, cycle, desk, proven  # noqa: F401 - cfg is a fixture

IST = A2.IST
PRE = dt.datetime(2026, 11, 10, 7, 30, tzinfo=IST)                    # Tue 07:30, the morning after T0's session
CLOSE_AGE = (PRE - T0).total_seconds() - 6 * 3600                      # the closing board, as old at 07:30 as the 15:30 close is

BRIEF = {"session": "2026-11-10",
         "global": [{"kind": "equity", "change": c, "india_prior": 1} for c in (0.011, 0.009, 0.012, 0.008)] + [{"kind": "fx", "change": -0.02, "india_prior": 1}],
         "results": [], "expiring": [], "macro": [{"name": "US CPI", "time": "19:00", "when": "today"}],
         "watch": [{"symbol": "NIFTY", "why": ["index", "futures OI rose 12% yesterday"]}]}


def test_the_closing_board_is_kept_for_planning_with_its_age_cleared_and_older_quotes_dropped():
    snap = {"now": 0, "quotes": {"A": {"ltp": 1, "age_s": 15 * 3600}, "B": {"ltp": 2, "age_s": 5 * 86400}, "C": {"ltp": 3}}}
    cs = A2.AutoPilotV2.close_snap(snap)
    assert cs["quotes"] == {"A": {"ltp": 1, "age_s": 0.0}} and snap["quotes"]["A"]["age_s"] == 15 * 3600          # the live snapshot is never changed


def test_the_overnight_cue_is_the_median_equity_move_and_needs_three_markets():
    m, why = A2.AutoPilotV2.overnight(BRIEF)
    assert m == pytest.approx(1.0) and "median of 4" in why                            # (0.9 + 1.1) / 2, the currency row left out
    assert A2.AutoPilotV2.overnight({"global": BRIEF["global"][:2]}) == (None, None) and A2.AutoPilotV2.overnight(None) == (None, None)


def test_a_quiet_close_plans_no_trade_a_trade_is_planned_for_a_big_move_or_a_strong_direction_only(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)                                                         # the owner, 14 Nov 2026: "big move or strong direction"; a quiet close is neither
    dp = ap.plan(board(T0, age=CLOSE_AGE), PRE)
    assert dp["from"] == "last close" and dp["built_at"].startswith("2026-11-10T07:30") and dp["states"]["NIFTY"]["view"] == "flat"
    assert dp["items"] == [], dp
    assert any("No candidate is proven yet" in n for n in dp["notes"]) and any("No pre-market brief" in n for n in dp["notes"])


def test_overnight_markets_and_the_closing_book_together_give_a_view_and_the_brief_adds_catalysts(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    ap.brief = BRIEF
    dp = ap.plan(board(T0, age=CLOSE_AGE, cb=3000, ca=500, pb=500, pa=3000, fwd_gap=-0.2), PRE)
    st = dp["states"]["NIFTY"]
    assert st["view"] == "up" and any("overnight markets +1.00%" in w for w in st["why"]), st
    assert dp["overnight_pct"] == 1.0 and dp["brief"] == "2026-11-10"
    for i in dp["items"]:
        assert i["view"] == "up" and "macro: US CPI" in i["catalysts"] and "futures OI rose 12% yesterday" in i["catalysts"]


def test_one_overnight_vote_alone_is_no_view(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    ap.brief = BRIEF
    dp = ap.plan(board(T0, age=CLOSE_AGE), PRE)                                          # overnight up, but nothing on the board agrees
    assert dp["states"]["NIFTY"]["view"] is None and dp["items"] == []


UP = dict(cb=3000, ca=500, pb=500, pa=3000, fwd_gap=-0.2)                                 # the closing book and the options forward both say up


def test_a_strong_direction_is_planned_with_overnight_strategies_and_a_proven_one_first(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    ap.brief = BRIEF
    dp = ap.plan(board(T0, age=CLOSE_AGE, **UP), PRE)                                    # three readings agree: book, forward, overnight markets
    assert dp["states"]["NIFTY"]["view"] == "up" and dp["items"]
    for i in dp["items"]:
        assert A2.BY_SID[i["sid"]].hold == "overnight" and i["view"] == "up" and i["rr"] >= A2.PLAN_MIN_RR and i["risk_lot"] > 0 and i["risk_unit"] > 0
    low = min(dp["items"], key=lambda i: i["rr"])["sid"]
    rn, ap = desk(cfg, tmp_path / "b", stats=proven(sid=low))
    ap.brief = BRIEF
    dp = ap.plan(board(T0, age=CLOSE_AGE, **UP), PRE)
    first, rest = dp["items"][0], dp["items"][1:]
    assert first["sid"] == low and first["proven"] and first["n"] == 20 and first["mean_r"] > 0
    assert not any("No candidate is proven yet" in n for n in dp["notes"])


def test_two_agreeing_readings_are_not_a_strong_direction(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    ap.brief = BRIEF
    dp = ap.plan(board(T0, age=CLOSE_AGE, cb=3000, ca=500, pb=500, pa=3000), PRE)        # the book and the overnight markets agree; the forward is silent
    st = dp["states"]["NIFTY"]
    assert st["view"] is None and dp["items"] == [] and any("a direction needs 3 agreeing" in w for w in st["why"])


def _other_flat_ic():
    s0 = A2.BY_SID[IC]
    return next(s.sid for s in A2.CATALOGUE if s.sid != IC and (s.struct, s.view, s.vol, s.timing, s.expiry, s.hold) == (s0.struct, s0.view, s0.vol, s0.timing, s0.expiry, s0.hold))


def test_at_the_open_a_planned_proven_strategy_is_taken_before_a_better_unplanned_one(cfg, tmp_path):
    other = _other_flat_ic()
    stats = {**proven(), **proven(sid=other, mean=5.0)}                                     # the unplanned one's record is far better: Thompson sampling alone would take it
    rn, ap = desk(cfg, tmp_path, stats=stats)
    ap.day_plan = {"built_at": T0.date().isoformat() + "T07:30", "items": [{"u": "NIFTY", "sid": IC}]}
    t = calm(rn, ap, minutes=5)
    live = [p.strategy for p in rn.account.positions.values()]
    assert live and all(x == f"{A2.TAG} {IC} NIFTY" for x in live), live
    assert "On the day plan built before the open." in next(iter(rn.account.positions.values())).thesis

    rn2, ap2 = desk(cfg, tmp_path / "b", stats=stats)                                       # the same day without a plan: the better record wins
    calm(rn2, ap2, minutes=5)
    assert {p.strategy for p in rn2.account.positions.values()} == {f"{A2.TAG} {other} NIFTY"}


def test_a_planned_strategy_without_a_record_never_trades_and_yesterdays_plan_never_steers_today(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)                                                             # no record at all
    ap.day_plan = {"built_at": T0.date().isoformat() + "T07:30", "items": [{"u": "NIFTY", "sid": IC}]}
    calm(rn, ap, minutes=6)
    assert not rn.account.ledger
    rn, ap = desk(cfg, tmp_path / "b", stats=proven())
    ap.day_plan = {"built_at": "2026-11-06T07:30", "items": [{"u": "NIFTY", "sid": IC}]}
    cycle(rn, ap, board(T0), T0)
    assert ap.day_plan is None


def test_decide_builds_the_plan_before_the_open_and_trades_nothing_then(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path, stats=proven())
    snap = board(T0, age=CLOSE_AGE)
    mine = ap.decide(snap, rn.account, PRE)
    assert ap.day_plan and ap.day_plan["built_at"].startswith("2026-11-10T07:30")
    assert not [o for o in mine if o.get("group") == "auto2"]                              # 07:30: nothing is entered before FIRST_ENTRY
    first = ap.day_plan
    ap.decide(snap, rn.account, PRE + dt.timedelta(minutes=5))
    assert ap.day_plan is first                                                              # rebuilt every PLAN_EVERY_S, not every cycle
    ap.decide(snap, rn.account, PRE + dt.timedelta(minutes=11))
    assert ap.day_plan is not first


def test_the_plan_fits_the_runners_state_on_the_relay(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    ap.brief = BRIEF
    ap.plan(board(T0, age=CLOSE_AGE), PRE)
    assert "plan" in ap.summary() and len(json.dumps(ap.summary())) < 20000


def test_the_session_fetches_only_todays_brief_from_the_public_premarket_branch():
    from quantdesk.paperlink import session as SE
    seen = []

    class R:
        def __init__(self, b):
            self.b = b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return self.b

    def opener(body):
        def o(req, timeout=None):
            seen.append(req.full_url)
            if isinstance(body, Exception):
                raise body
            return R(body)
        return o
    day = dt.date(2026, 11, 10)
    assert SE.fetch_brief("owner/repo", day, opener(json.dumps(BRIEF).encode())) == BRIEF
    assert seen[-1] == "https://raw.githubusercontent.com/owner/repo/premarket/brief.json"
    assert SE.fetch_brief("owner/repo", day, opener(json.dumps({**BRIEF, "session": "2026-11-09"}).encode())) is None      # yesterday's never plans today
    assert SE.fetch_brief("owner/repo", day, opener(b"not json")) is None
    assert SE.fetch_brief("owner/repo", day, opener(OSError("down"))) is None
    n = len(seen)
    assert SE.fetch_brief("owner/repo/../x", day, opener(b"{}")) is None and SE.fetch_brief("", day, opener(b"{}")) is None and len(seen) == n
