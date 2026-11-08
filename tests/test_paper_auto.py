"""AUTO v1 (quantdesk/paper/auto.py): the paper desk deciding for itself. PAPER MONEY ONLY. Everything here runs through the REAL runner, risk gate and broker; only the board is made up.
What is pinned: it enters only on agreement of the signals, one lot, within its own tight limits; it exits for its stated reasons and ONLY touches its own positions; the owner's kill switch,
the brakes and the session hours apply; and it never trades by itself unless switched on."""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.markets import sessions as MK
from quantdesk.paper import auto as A
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import KillSwitch, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
DAY = dt.date(2026, 11, 9)                                                    # a Monday
EXP = dt.date(2026, 11, 12)
STRIKES = list(range(24300, 24701, 50))
SPOT, FUT = 24500.0, 24510.0
T0 = dt.datetime(2026, 11, 9, 10, 0, tzinfo=IST)


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def ms(t):
    return int(t.timestamp() * 1000)


def board(t=T0, cb=1000, ca=1000, pb=1000, pa=1000, fwd_gap=0.0, spot=SPOT, age=1.0, spread=0.4, under="NIFTY", call_ask_shift=0.0):
    """A consistent NIFTY board: prices from Black-Scholes at 14% vol, with the sizes and the futures price chosen to make the signals."""
    from math import exp, log, sqrt
    from statistics import NormalDist
    N = NormalDist().cdf
    T = (dt.datetime.combine(EXP, dt.time(15, 30), tzinfo=IST) - t).total_seconds() / (365.25 * 86400)
    r, iv = A.RATE, 0.14

    def bs(kind, k):
        d1 = (log(spot / k) + (r + iv * iv / 2) * T) / (iv * sqrt(T)); d2 = d1 - iv * sqrt(T)
        return spot * N(d1) - k * exp(-r * T) * N(d2) if kind == "CE" else k * exp(-r * T) * N(-d2) - spot * N(-d1)
    q = {under: dict(ltp=spot, age_s=age), under + "-FUT": dict(bid=FUT * (1 + fwd_gap / 100) - 0.5, ask=FUT * (1 + fwd_gap / 100) + 0.5, ltp=FUT * (1 + fwd_gap / 100), age_s=age)}
    # make the options' forward equal spot * e^{rT} so a futures price at that level is "no gap"
    fwd = spot * exp(r * T)
    q[under + "-FUT"] = dict(bid=fwd * (1 + fwd_gap / 100) - 0.5, ask=fwd * (1 + fwd_gap / 100) + 0.5, ltp=fwd * (1 + fwd_gap / 100), age_s=age)
    for k in STRIKES:
        for kind, bq, aq in (("CE", cb, ca), ("PE", pb, pa)):
            m = bs(kind, k)
            m = max(m, 0.2)
            bid = max(0.05, round((m - spread / 2) / 0.05) * 0.05); ask = round((m + spread / 2) / 0.05) * 0.05
            q[f"{under}12NOV26{k}{kind}"] = dict(bid=bid, ask=ask, ltp=m, bid_qty=bq, ask_qty=aq, age_s=age, oi=100000)
    return {"now": ms(t), "quotes": q}


def desk(cfg, tmp_path, **kw):
    acct = Account(500_000)
    gate = RiskGate(cfg, kill=KillSwitch(tmp_path / "K"))
    rn = R.Runner(cfg, acct, gate=gate, kill_file=tmp_path / "K")
    lots = {"NIFTY": 65, "BANKNIFTY": 30}
    return rn, A.AutoPilot(("NIFTY",), lots, 500_000.0), MK.Calendars(cfg)


def tick(rn, ap, cal, snap, now, kill=False):
    """One cycle exactly as the session does it: the autopilot proposes, the runner executes through the gate."""
    srv = R.Runner.server_now(snap)
    mine = ap.decide(snap, rn.account, srv, kill=kill, entries_blocked=rn.entries_blocked, cal=cal)
    rep = rn.step(snap, mine, kill, now.astimezone(dt.timezone.utc))
    return mine, rep


def warm(rn, ap, cal, t0, minutes=6, spot=SPOT, step=60):
    """Feed the autopilot a quiet tape so it has five minutes of history (no entries expected while nothing agrees)."""
    for i in range(minutes * 60 // step + 1):
        t = t0 + dt.timedelta(seconds=i * step)
        tick(rn, ap, cal, board(t, spot=spot), t)


# ---- the pieces ----------------------------------------------------------------------------------------------------------------------------------------------
def test_direction_needs_two_agreeing_signals_and_no_opposite_one():
    assert A.direction(0.3, 0.06, None)[0] == 1 and A.direction(-0.3, -0.06, None)[0] == -1 and A.direction(0.3, None, 0.12)[0] == 1
    assert A.direction(0.3, None, None)[0] == 0 and A.direction(None, None, 0.2)[0] == 0                                   # one signal alone is not enough
    assert A.direction(0.3, -0.06, 0.2)[0] == 0 and A.direction(0.3, -0.06, None)[0] == 0                                  # a signal against vetoes
    assert A.direction(0.24, 0.049, 0.09)[0] == 0 and A.direction(0.0, 0.0, 0.0)[0] == 0                                    # below the thresholds counts for nothing
    d, why = A.direction(0.3, 0.06, 0.12)
    assert d == 1 and len(why) == 3


def test_the_chains_and_readings_come_from_the_board(cfg):
    snap = board(pb=3000, pa=1000, cb=3000, ca=1000)
    ch = A.chains(snap, ("NIFTY",), {"NIFTY": 65})
    assert sorted(ch["NIFTY"][EXP]) == STRIKES and ch["NIFTY"][EXP][24500] == {"CE": "NIFTY12NOV2624500CE", "PE": "NIFTY12NOV2624500PE"}
    rd = A.readings(snap, "NIFTY", EXP, ch["NIFTY"][EXP], T0, SPOT, snap["quotes"]["NIFTY-FUT"]["ltp"])
    assert rd["pressure"] == pytest.approx(0.0) and abs(rd["gap_pct"]) < 0.06 and rd["atm"] == 24500                         # calls and puts both bid-heavy: no net pressure; consistent board: no gap
    bull = board(cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
    rd2 = A.readings(bull, "NIFTY", EXP, A.chains(bull, ("NIFTY",), {})["NIFTY"][EXP], T0, SPOT, bull["quotes"]["NIFTY-FUT"]["ltp"])
    assert rd2["pressure"] == pytest.approx(1.0) and rd2["gap_pct"] > 0.05                                                    # futures cheap against the options' forward = options point up


# ---- entering ------------------------------------------------------------------------------------------------------------------------------------------------
def test_it_buys_one_atm_call_when_the_signals_agree_and_the_gate_fills_it(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    snap = board(t, cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
    mine, rep = tick(rn, ap, cal, snap, t)
    assert len(mine) == 1 and mine[0]["side"] == "buy" and mine[0]["symbol"] == "NIFTY12NOV2624500CE" and mine[0]["lots"] == 1
    assert mine[0]["strategy"].startswith("AUTO v1") and len(mine[0]["thesis"]) >= 20 and "pressure" in mine[0]["thesis"] and mine[0]["limit"] > snap["quotes"][mine[0]["symbol"]]["ask"]
    res = rep["results"][0]
    assert res["status"] == "filled", res
    assert list(rn.account.positions) == ["NIFTY12NOV2624500CE"] and rn.account.positions["NIFTY12NOV2624500CE"].qty == 65
    assert rn.account.verify_ledger()


def test_it_buys_a_put_when_they_agree_down_and_does_nothing_when_they_do_not(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    mine, _ = tick(rn, ap, cal, board(t, cb=1000, ca=3000, pb=3000, pa=1000, fwd_gap=0.1), t)
    assert len(mine) == 1 and mine[0]["symbol"].endswith("24500PE")
    rn2, ap2, cal2 = desk(cfg, tmp_path)
    warm(rn2, ap2, cal2, T0)
    for snap in (board(t), board(t, cb=3000, ca=1000, pb=1000, pa=3000), board(t, cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=0.1)):               # none, one signal, two that disagree
        assert tick(rn2, ap2, cal2, snap, t)[0] == []
    assert not rn2.account.positions


def test_it_refuses_a_stale_a_wide_or_one_sided_market_and_never_trades_outside_the_session_or_the_entry_window(cfg, tmp_path):
    sig = dict(cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
    for bad in (dict(age=20.0), dict(spread=12.0)):
        rn, ap, cal = desk(cfg, tmp_path)
        warm(rn, ap, cal, T0)
        t = T0 + dt.timedelta(minutes=7)
        assert tick(rn, ap, cal, board(t, **sig, **bad), t)[0] == [], bad
    for when, label in ((dt.datetime(2026, 11, 9, 9, 17, tzinfo=IST), "first minutes"), (dt.datetime(2026, 11, 9, 15, 12, tzinfo=IST), "last twenty minutes"), (dt.datetime(2026, 11, 9, 16, 0, tzinfo=IST), "after the close"),
                        (dt.datetime(2026, 11, 8, 14, 40, tzinfo=IST), "a Sunday without a special session in this build")):
        rn, ap, cal = desk(cfg, tmp_path)
        warm(rn, ap, cal, when - dt.timedelta(minutes=7))
        mine, _ = tick(rn, ap, cal, board(when, **sig), when)
        assert [o for o in mine if o["side"] == "buy"] == [] or label == "a Sunday without a special session in this build" and MK.session("nse_fo", dt.date(2026, 11, 8), cal, trading=True) is not None, label


def test_the_kill_switch_and_a_blocked_relay_stop_entries_and_it_is_off_unless_switched_on(cfg, tmp_path):
    sig = dict(cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    srv = R.Runner.server_now(board(t, **sig))
    assert ap.decide(board(t, **sig), rn.account, srv, kill=True, cal=cal) == []
    assert ap.decide(board(t, **sig), rn.account, srv, entries_blocked="the relay could not be given the latest fills", cal=cal) == []
    cli = (ROOT / "quantdesk/paperlink/cli.py").read_text(encoding="utf-8")
    assert 'getattr(a, "auto", False) or os.environ.get("PAPER_AUTO"' in cli and "auto = None" in cli                           # no switch, no autopilot
    wf = (ROOT / ".github/workflows/paper-desk.yml").read_text(encoding="utf-8")
    assert "PAPER_AUTO" in wf


# ---- holding and leaving ------------------------------------------------------------------------------------------------------------------------------------
def open_one(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    tick(rn, ap, cal, board(t, cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1), t)
    assert len(rn.account.positions) == 1
    return rn, ap, cal, t


def reprice(snap, sym, bid, ask=None):
    snap["quotes"][sym] = {**snap["quotes"][sym], "bid": bid, "ask": ask if ask is not None else bid + 0.4}
    return snap


@pytest.mark.parametrize("name,bid_mult,minutes,expect", [("take profit", 1.35, 8, "take profit"), ("stop loss", 0.70, 8, "stop loss")])
def test_it_sells_at_its_profit_target_and_its_stop(cfg, tmp_path, name, bid_mult, minutes, expect):
    rn, ap, cal, t = open_one(cfg, tmp_path)
    sym = next(iter(rn.account.positions)); avg = rn.account.positions[sym].avg_price
    t2 = t + dt.timedelta(minutes=1)
    snap = reprice(board(t2, cb=1000, ca=1000, pb=1000, pa=1000), sym, round(avg * bid_mult, 2))
    mine, rep = tick(rn, ap, cal, snap, t2)
    assert len(mine) == 1 and mine[0]["side"] == "sell" and expect in mine[0]["_why"]
    assert rep["results"][0]["status"] == "filled" and not rn.account.positions


def test_it_sells_after_25_minutes_when_the_signals_turn_and_ten_minutes_before_the_close_and_only_its_own_positions(cfg, tmp_path):
    rn, ap, cal, t = open_one(cfg, tmp_path)
    sym = next(iter(rn.account.positions))
    assert tick(rn, ap, cal, board(t + dt.timedelta(minutes=2)), t + dt.timedelta(minutes=2))[0] == []                              # quiet board: it holds
    t3 = t + dt.timedelta(minutes=26)
    mine, _ = tick(rn, ap, cal, board(t3), t3)
    assert len(mine) == 1 and "25 minutes" in mine[0]["_why"]
    rn, ap, cal, t = open_one(cfg, tmp_path)
    t4 = t + dt.timedelta(minutes=2)
    flip = board(t4, cb=1000, ca=3000, pb=3000, pa=1000, fwd_gap=0.1, spot=SPOT * 0.9985)
    mine, _ = tick(rn, ap, cal, flip, t4)
    assert any(o["side"] == "sell" and "other way" in o["_why"] for o in mine)
    rn, ap, cal, t = open_one(cfg, tmp_path)
    end = dt.datetime(2026, 11, 9, 15, 21, tzinfo=IST)
    mine, rep = tick(rn, ap, cal, board(end), end)
    assert len(mine) == 1 and "close" in mine[0]["_why"] and rep["results"][0]["status"] == "filled"
    # the owner's own position is never touched
    rn2, ap2, cal2 = desk(cfg, tmp_path)
    inst, _ = R.parse_contract("NIFTY12NOV2624600CE", {"NIFTY"}, {"NIFTY": 65})
    rn2.account.apply_fill("buy", inst, "nse_fo", 65, 50.0, 20.0, T0.isoformat(), "owner: breakout", "my own thesis for this trade, kept by hand")
    warm(rn2, ap2, cal2, T0)
    e2 = dt.datetime(2026, 11, 9, 15, 21, tzinfo=IST)
    assert tick(rn2, ap2, cal2, board(e2), e2)[0] == [] and "NIFTY12NOV2624600CE" in rn2.account.positions


# ---- its own limits -----------------------------------------------------------------------------------------------------------------------------------------
def test_cooldown_open_cap_daily_cap_and_the_days_own_stop(cfg, tmp_path):
    sig = dict(cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
    rn, ap, cal, t = open_one(cfg, tmp_path)
    # an entry on the same index inside 20 minutes: nothing (it also still holds one)
    t2 = t + dt.timedelta(minutes=2)
    assert [o for o in tick(rn, ap, cal, board(t2, **sig), t2)[0] if o["side"] == "buy"] == []
    # the day's own stop: lose 1% of capital on its positions and it sells and stops
    sym = next(iter(rn.account.positions))
    t3 = t + dt.timedelta(minutes=3)
    snap = reprice(board(t3, **sig), sym, 0.05, 0.45)                                                                            # the position is nearly worthless: far past -1% of capital
    mine, rep = tick(rn, ap, cal, snap, t3)
    assert any(o["side"] == "sell" for o in mine)
    assert not rn.account.positions
    t4 = t3 + dt.timedelta(minutes=25)
    big = board(t4, **sig)
    assert [o for o in tick(rn, ap, cal, big, t4)[0] if o["side"] == "buy"] == []                                               # stopped for the day (its result is below -1% only if the loss was that big)


def test_the_day_result_counts_fees_and_an_unpriced_position_as_worth_nothing(cfg, tmp_path):
    rn, ap, cal, t = open_one(cfg, tmp_path)
    facts = ap.day_facts(rn.account, DAY, {})                                                                                    # no mark: counts as nothing
    assert facts["entries"] == 1 and facts["result"] < -2000
    sym = next(iter(rn.account.positions))
    priced = ap.day_facts(rn.account, DAY, {sym: rn.account.positions[sym].avg_price})
    assert priced["result"] > facts["result"] and priced["result"] == pytest.approx(-rn.account.fees, abs=1)


def test_ids_are_unique_and_an_order_in_flight_is_not_repeated(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    snap = board(t, cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
    srv = R.Runner.server_now(snap)
    a = ap.decide(snap, rn.account, srv, cal=cal)
    b = ap.decide(snap, rn.account, srv, cal=cal)                                                                                # nothing filled yet: the same signal must not queue it twice
    assert len(a) == 1 and b == []
    ids = {ap._oid(1.0, "b") for _ in range(50)}
    assert len(ids) == 50 and all(R.ID_RE.fullmatch(i) for i in ids)


def test_the_module_is_pure_no_network_no_environment_no_clock():
    src = (ROOT / "quantdesk/paper/auto.py").read_text(encoding="utf-8")
    import re
    assert not re.search(r"import (requests|urllib|socket|http)|os\.environ|time\.time\(|datetime\.now\(|\.now\(\)", src)


def _round_trip(acct, strike, when, strategy="AUTO v1 NIFTY long call"):
    inst, _ = R.parse_contract(f"NIFTY12NOV26{strike}CE", {"NIFTY"}, {"NIFTY": 65})
    acct.apply_fill("buy", inst, "nse_fo", 65, 50.0, 10.0, when.isoformat(), strategy, "AUTO v1: test")
    acct.apply_fill("sell", inst, "nse_fo", 65, 50.5, 10.0, (when + dt.timedelta(minutes=1)).isoformat(), strategy, "exit")


def test_the_daily_entry_cap_and_the_cooldown_come_from_the_ledger_so_a_restart_forgets_nothing(cfg, tmp_path):
    sig = dict(cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
    t = T0 + dt.timedelta(minutes=7)
    # a trade closed five minutes ago: the cooldown holds; closed 25 minutes ago it does not
    for ago, expect_buy in ((5, False), (25, True)):
        rn, ap, cal = desk(cfg, tmp_path)
        _round_trip(rn.account, 24600, t - dt.timedelta(minutes=ago + 1))
        warm(rn, ap, cal, T0)
        buys = [o for o in tick(rn, ap, cal, board(t, **sig), t)[0] if o["side"] == "buy"]
        assert bool(buys) is expect_buy, ago
    # six entries already today: no seventh, however good the signals
    rn, ap, cal = desk(cfg, tmp_path)
    for i in range(6):
        _round_trip(rn.account, 24000 + 50 * i, T0 - dt.timedelta(minutes=35) + dt.timedelta(seconds=10 * i))        # earlier today, outside the cooldown
    warm(rn, ap, cal, T0)
    assert [o for o in tick(rn, ap, cal, board(t, **sig), t)[0] if o["side"] == "buy"] == []
    # yesterday's entries do not count
    rn, ap, cal = desk(cfg, tmp_path)
    for i in range(6):
        _round_trip(rn.account, 24000 + 50 * i, T0 - dt.timedelta(days=1) + dt.timedelta(seconds=10 * i))
    warm(rn, ap, cal, T0)
    assert [o for o in tick(rn, ap, cal, board(t, **sig), t)[0] if o["side"] == "buy"]
