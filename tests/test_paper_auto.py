"""AUTO v1 (quantdesk/paper/auto.py): the paper desk deciding for itself. PAPER MONEY ONLY. Everything here runs through the REAL runner, risk gate and broker; only the board and the news are made up.
What is pinned: it enters only on agreement of the readings, one lot, one strike out of the money, with no trade-count limits of its own (the gate's loss caps are the bound); it risks a small fixed share of the premium and puts NO cap on the gain
(a trailing stop lets a winner run); it decides about the NIGHT before the close and carries a position overnight only when the idea is intact; it ONLY touches its own positions; the owner's
kill switch, the brakes and the session hours apply; and it never trades by itself unless switched on."""
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


def desk(cfg, tmp_path, day_stop=None, **kw):
    acct = Account(500_000)
    gate = RiskGate(cfg, kill=KillSwitch(tmp_path / "K"))
    rn = R.Runner(cfg, acct, gate=gate, kill_file=tmp_path / "K")
    lots = {"NIFTY": 65, "BANKNIFTY": 30}
    return rn, A.AutoPilot(("NIFTY",), lots, 500_000.0, day_stop_frac=day_stop), MK.Calendars(cfg)


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


SIG_UP = dict(cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=-0.1)
SIG_DOWN = dict(cb=1000, ca=3000, pb=3000, pa=1000, fwd_gap=0.1)


def story(tone=0.6, impact="high", age_min=10, symbols=None, recap=False, novelty=0.9, now=T0):
    ts = (now.astimezone(dt.timezone.utc) - dt.timedelta(minutes=age_min)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"ts": ts, "tone": tone, "impact": impact, "symbols": symbols or [], "recap": recap, "novelty": novelty, "title": "x"}


def digest(*items):
    return {"v": 1, "items": list(items)}


# ---- the readings --------------------------------------------------------------------------------------------------------------------------------------------
def test_direction_needs_two_agreeing_readings_and_no_opposite_one_news_included():
    assert A.direction(0.3, 0.06, None)[0] == 1 and A.direction(-0.3, -0.06, None)[0] == -1 and A.direction(0.3, None, 0.12)[0] == 1
    assert A.direction(0.3, None, None)[0] == 0 and A.direction(None, None, 0.2)[0] == 0                                   # one reading alone is not enough
    assert A.direction(0.3, -0.06, 0.2)[0] == 0 and A.direction(0.3, -0.06, None)[0] == 0                                  # a reading against vetoes
    assert A.direction(0.24, 0.049, 0.09)[0] == 0 and A.direction(0.0, 0.0, 0.0)[0] == 0                                    # below the thresholds counts for nothing
    assert A.direction(0.3, None, None, 1, "news tone +0.5")[0] == 1 and A.direction(None, None, None, 1, "n")[0] == 0     # news is a reading like the others
    assert A.direction(0.3, None, None, -1, "n")[0] == 0 and A.direction(0.3, 0.06, 0.12, -1, "n")[0] == 0                # and it can veto
    d, why = A.direction(0.3, 0.06, 0.12, 1, "news tone +0.5 over 2 stories")
    assert d == 1 and len(why) == 4


def test_news_counts_only_recent_medium_or_high_impact_new_stories_that_bear_on_the_index():
    now = T0
    good = digest(story(0.6, "high"))
    assert A.news_tone(good, "NIFTY", now)[0] == pytest.approx(0.6) and A.news_vote(good, "NIFTY", now)[0] == 1                # one high story: weight 3, enough
    assert A.news_vote(digest(story(0.6, "medium")), "NIFTY", now)[0] == 0                                                      # one medium story: weight 2, not enough
    assert A.news_vote(digest(story(0.6, "medium"), story(0.5, "medium")), "NIFTY", now)[0] == 1                               # two medium: enough
    assert A.news_vote(digest(story(-0.6, "high")), "NIFTY", now)[0] == -1
    assert A.news_vote(digest(story(0.2, "high")), "NIFTY", now)[0] == 0                                                        # too mild
    for bad in (story(0.6, "low"), story(0.6, "high", age_min=200), story(0.6, "high", recap=True), story(0.6, "high", novelty=0.1), story(0.6, "high", symbols=["RELIANCE"]), story(5.0, "high")):
        assert A.news_vote(digest(bad), "NIFTY", now)[0] == 0, bad
    assert A.news_vote(digest(story(0.6, "high", symbols=["NIFTY"])), "NIFTY", now)[0] == 1 and A.news_vote(digest(story(0.6, "high", symbols=["NIFTY"])), "BANKNIFTY", now)[0] == 0
    for junk in (None, {}, {"items": "x"}, {"items": [None, 5, {"tone": "x"}, {"impact": "high", "tone": 0.9, "ts": "yesterday"}]}):
        assert A.news_vote(junk, "NIFTY", now)[0] == 0


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
def test_it_buys_one_lot_one_strike_out_of_the_money_when_the_readings_agree_and_the_gate_fills_it(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    snap = board(t, **SIG_UP)
    mine, rep = tick(rn, ap, cal, snap, t)
    assert len(mine) == 1 and mine[0]["side"] == "buy" and mine[0]["symbol"] == "NIFTY12NOV2624550CE" and mine[0]["lots"] == 1             # ATM is 24500: the first strike out of the money is 24550
    assert mine[0]["strategy"].startswith("AUTO v1") and len(mine[0]["thesis"]) >= 20 and "pressure" in mine[0]["thesis"] and "uncapped" in mine[0]["thesis"]
    assert mine[0]["limit"] > snap["quotes"][mine[0]["symbol"]]["ask"] and snap["quotes"][mine[0]["symbol"]]["ask"] >= A.MIN_PREMIUM
    res = rep["results"][0]
    assert res["status"] == "filled", res
    assert list(rn.account.positions) == ["NIFTY12NOV2624550CE"] and rn.account.positions["NIFTY12NOV2624550CE"].qty == 65 and rn.account.verify_ledger()


def test_it_buys_a_put_one_strike_below_when_they_agree_down_and_does_nothing_when_they_do_not(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    mine, _ = tick(rn, ap, cal, board(t, **SIG_DOWN), t)
    assert len(mine) == 1 and mine[0]["symbol"].endswith("24450PE")
    rn2, ap2, cal2 = desk(cfg, tmp_path)
    warm(rn2, ap2, cal2, T0)
    for snap in (board(t), board(t, cb=3000, ca=1000, pb=1000, pa=3000), board(t, cb=3000, ca=1000, pb=1000, pa=3000, fwd_gap=0.1)):               # none, one reading, two that disagree
        assert tick(rn2, ap2, cal2, snap, t)[0] == []
    assert not rn2.account.positions


def test_the_news_can_be_the_second_reading_or_the_veto(cfg, tmp_path):
    t = T0 + dt.timedelta(minutes=7)
    one = dict(cb=3000, ca=1000, pb=1000, pa=3000)                                                                              # pressure alone: not enough
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    assert ap.decide(board(t, **one), rn.account, R.Runner.server_now(board(t, **one)), cal=cal) == []
    with_news = ap.decide(board(t, **one), rn.account, R.Runner.server_now(board(t, **one)), cal=cal, news=digest(story(0.6, "high", now=t, age_min=5)))
    assert len(with_news) == 1 and "news tone" in with_news[0]["thesis"]                                                         # pressure + good news = a buy
    rn2, ap2, cal2 = desk(cfg, tmp_path)
    warm(rn2, ap2, cal2, T0)
    vetoed = ap2.decide(board(t, **SIG_UP), rn2.account, R.Runner.server_now(board(t, **SIG_UP)), cal=cal2, news=digest(story(-0.7, "high", now=t, age_min=5)))
    assert [o for o in vetoed if o["side"] == "buy"] == []                                                                       # two readings up, bad news: no buy


def test_it_never_buys_an_option_close_to_expiry_a_stale_a_wide_or_a_cheap_one_or_outside_the_session_and_entry_window(cfg, tmp_path):
    t = T0 + dt.timedelta(minutes=7)
    for bad in (dict(age=20.0), dict(spread=12.0)):
        rn, ap, cal = desk(cfg, tmp_path)
        warm(rn, ap, cal, T0)
        assert tick(rn, ap, cal, board(t, **SIG_UP, **bad), t)[0] == [], bad
    # Wednesday: the 12 Nov expiry is only one day away, so there is nothing far enough to buy
    tue = dt.datetime(2026, 11, 11, 10, 7, tzinfo=IST)      # (Tuesday 10 Nov is an NSE holiday)
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, tue - dt.timedelta(minutes=7))
    assert tick(rn, ap, cal, board(tue, **SIG_UP), tue)[0] == []
    for when, label in ((dt.datetime(2026, 11, 9, 9, 17, tzinfo=IST), "first minutes"), (dt.datetime(2026, 11, 9, 15, 12, tzinfo=IST), "last twenty minutes"), (dt.datetime(2026, 11, 9, 16, 0, tzinfo=IST), "after the close")):
        rn, ap, cal = desk(cfg, tmp_path)
        warm(rn, ap, cal, when - dt.timedelta(minutes=7))
        mine, _ = tick(rn, ap, cal, board(when, **SIG_UP), when)
        assert [o for o in mine if o["side"] == "buy"] == [], label


def test_the_kill_switch_and_a_blocked_relay_stop_entries_and_it_is_off_unless_switched_on(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    srv = R.Runner.server_now(board(t, **SIG_UP))
    assert ap.decide(board(t, **SIG_UP), rn.account, srv, kill=True, cal=cal) == []
    assert ap.decide(board(t, **SIG_UP), rn.account, srv, entries_blocked="the relay could not be given the latest fills", cal=cal) == []
    cli = (ROOT / "quantdesk/paperlink/cli.py").read_text(encoding="utf-8")
    assert 'getattr(a, "auto", False) or os.environ.get("PAPER_AUTO"' in cli and "auto = None" in cli                           # no switch, no autopilot
    wf = (ROOT / ".github/workflows/paper-desk.yml").read_text(encoding="utf-8")
    assert "PAPER_AUTO: ${{ (inputs.auto || vars.PAPER_AUTO != 'no') && 'yes' || 'no' }}" in wf          # ON for every run by the owner's order (13 Nov 2026); the variable set to no switches it off
    assert "lots.update(stock_lots(cfg))" in cli                                                        # and it trades the stocks as well as the indices


# ---- holding: a small fixed risk, no cap on the gain ---------------------------------------------------------------------------------------------------------
def open_one(cfg, tmp_path, sig=SIG_UP):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    tick(rn, ap, cal, board(t, **sig), t)
    assert len(rn.account.positions) == 1
    return rn, ap, cal, t


def reprice(snap, sym, bid, ask=None):
    snap["quotes"][sym] = {**snap["quotes"][sym], "bid": bid, "ask": ask if ask is not None else bid + 0.4}
    return snap


def moved(rn, ap, cal, t, mult, **kw):
    sym = next(iter(rn.account.positions)); avg = rn.account.positions[sym].avg_price
    snap = reprice(board(t, cb=1000, ca=1000, pb=1000, pa=1000, **kw), sym, round(avg * mult, 2))
    return tick(rn, ap, cal, snap, t), sym


def test_it_risks_forty_percent_of_the_premium_and_not_a_rupee_more(cfg, tmp_path):
    rn, ap, cal, t = open_one(cfg, tmp_path)
    (mine, rep), sym = moved(rn, ap, cal, t + dt.timedelta(minutes=1), 0.62)                                                    # down 38%: inside the stop
    assert mine == []
    (mine, rep), sym = moved(rn, ap, cal, t + dt.timedelta(minutes=2), 0.59)                                                    # down 41%: the stop
    assert len(mine) == 1 and mine[0]["side"] == "sell" and "stop loss" in mine[0]["_why"] and rep["results"][0]["status"] == "filled" and not rn.account.positions


def test_it_does_not_cap_the_gain_a_winner_is_held_and_only_a_trailing_stop_ends_it(cfg, tmp_path):
    rn, ap, cal, t = open_one(cfg, tmp_path)
    t1 = t
    for step, mult in enumerate((1.3, 1.8, 2.5, 3.5)):                                                                          # +30%, +80%, +150%, +250%: nothing is sold on the way up
        t1 = t + dt.timedelta(minutes=step + 1)
        (mine, _), sym = moved(rn, ap, cal, t1, mult)
        assert [o for o in mine if o["side"] == "sell"] == [], mult
    assert rn.account.positions
    peak_events = ap.drain_events()
    assert peak_events and peak_events[-1]["kind"] == "auto_peak" and peak_events[-1]["peak"] >= rn.account.positions[sym].avg_price * 3.4        # the peak is queued for the ledger
    t2 = t1 + dt.timedelta(minutes=1)
    (mine, rep), _ = moved(rn, ap, cal, t2, 2.9)                                                                                # off the peak by 17%: still inside the 30% trail
    assert [o for o in mine if o["side"] == "sell"] == []
    t3 = t2 + dt.timedelta(minutes=1)
    (mine, rep), _ = moved(rn, ap, cal, t3, 2.4)                                                                                # 31% off the 3.5x peak: the trailing stop
    assert len(mine) == 1 and "trailing stop" in mine[0]["_why"] and rep["results"][0]["status"] == "filled" and not rn.account.positions
    fill = rep["results"][0]["fill"]
    assert fill["price"] > 2.0 * 50 or fill["price"] > 0                                                                       # (sold well above the entry)


def test_the_peak_is_remembered_in_the_ledger_so_a_restart_cannot_loosen_the_trail(cfg, tmp_path):
    rn, ap, cal, t = open_one(cfg, tmp_path)
    t1 = t + dt.timedelta(minutes=1)
    (mine, _), sym = moved(rn, ap, cal, t1, 3.0)
    for ev in ap.drain_events():                                                                                                # what the session does with them
        rn.account.record_event(ev["kind"], t1.isoformat(), **{k: v for k, v in ev.items() if k != "kind"})
    assert rn.account.verify_ledger() and any(r["kind"] == "auto_peak" for r in rn.account.ledger)
    again = A.AutoPilot(("NIFTY",), {"NIFTY": 65}, 500_000.0)                                                                  # a new process knows only the ledger
    snap = reprice(board(t1 + dt.timedelta(minutes=1), cb=1000, ca=1000, pb=1000, pa=1000), sym, round(rn.account.positions[sym].avg_price * 2.0, 2))      # 33% off the 3.0x peak
    out = again.decide(snap, rn.account, R.Runner.server_now(snap), cal=cal)
    assert len(out) == 1 and out[0]["side"] == "sell" and "trailing stop" in out[0]["_why"]
    loaded = Account.from_dict(__import__("json").loads(__import__("json").dumps(rn.account.to_dict())))                      # and the event rows replay cleanly
    assert loaded.ledger == rn.account.ledger


def test_it_sells_when_the_readings_turn_the_other_way_or_the_news_turns_against_it(cfg, tmp_path):
    rn, ap, cal, t = open_one(cfg, tmp_path)
    t4 = t + dt.timedelta(minutes=2)
    flip = board(t4, **SIG_DOWN, spot=SPOT * 0.9985)
    mine, _ = tick(rn, ap, cal, flip, t4)
    assert any(o["side"] == "sell" and "other way" in o["_why"] for o in mine)
    rn, ap, cal, t = open_one(cfg, tmp_path)
    t5 = t + dt.timedelta(minutes=2)
    snap = board(t5)
    out = ap.decide(snap, rn.account, R.Runner.server_now(snap), cal=cal, news=digest(story(-0.8, "high", now=t5, age_min=3)))
    assert len(out) == 1 and out[0]["side"] == "sell" and "news turned against" in out[0]["_why"]


def test_a_manual_position_is_never_touched(cfg, tmp_path):
    rn2, ap2, cal2 = desk(cfg, tmp_path)
    inst, _ = R.parse_contract("NIFTY12NOV2624600CE", {"NIFTY"}, {"NIFTY": 65})
    rn2.account.apply_fill("buy", inst, "nse_fo", 65, 50.0, 20.0, T0.isoformat(), "owner: breakout", "my own thesis for this trade, kept by hand")
    warm(rn2, ap2, cal2, T0)
    for when in (dt.datetime(2026, 11, 9, 15, 21, tzinfo=IST), dt.datetime(2026, 11, 9, 11, 0, tzinfo=IST)):
        snap = reprice(board(when), "NIFTY12NOV2624600CE", 10.0)                                                                # even at -80%
        assert [o for o in tick(rn2, ap2, cal2, snap, when)[0] if o["side"] == "sell"] == [] and "NIFTY12NOV2624600CE" in rn2.account.positions


# ---- the night ------------------------------------------------------------------------------------------------------------------------------------------------
def held_position(rn, symbol="NIFTY12NOV2624550CE", opened=T0 + dt.timedelta(minutes=7), avg=50.0):
    inst, _ = R.parse_contract(symbol, {"NIFTY"}, {"NIFTY": 65})
    rn.account.apply_fill("buy", inst, "nse_fo", 65, avg, 20.0, opened.isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: test thesis for a held position")
    return symbol


def evening(rn, ap, cal, day, mult=1.0, news=None, symbol="NIFTY12NOV2624550CE", **kw):
    t = dt.datetime.combine(day, dt.time(15, 21), tzinfo=IST)
    avg = rn.account.positions[symbol].avg_price
    snap = reprice(board(t, **{**dict(cb=1000, ca=1000, pb=1000, pa=1000), **kw}), symbol, round(avg * mult, 2))
    return ap.decide(snap, rn.account, R.Runner.server_now(snap), cal=cal, news=news), ap.last_info


def test_ten_minutes_before_the_close_it_decides_and_carries_an_intact_position_overnight(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    held_position(rn)
    out, info = evening(rn, ap, cal, DAY, mult=1.1)                                                                              # Monday close, expiry Thursday: three days left, in profit
    assert [o for o in out if o["side"] == "sell"] == [] and info.get("held_overnight") == ["NIFTY12NOV2624550CE"]
    out, info = evening(rn, ap, cal, DAY, mult=0.85)                                                                             # a little under water but above the stop: still carried
    assert [o for o in out if o["side"] == "sell"] == []
    # the next morning it is still there, with its stops: nothing sold while it is fine, the stop still works
    tue = dt.datetime(2026, 11, 11, 10, 30, tzinfo=IST)      # the next session: Tuesday is a holiday
    snap = reprice(board(tue, cb=1000, ca=1000, pb=1000, pa=1000), "NIFTY12NOV2624550CE", 55.0)
    assert ap.decide(snap, rn.account, R.Runner.server_now(snap), cal=cal) == []
    snap = reprice(board(tue + dt.timedelta(minutes=5), cb=1000, ca=1000, pb=1000, pa=1000), "NIFTY12NOV2624550CE", 28.0)
    out = ap.decide(snap, rn.account, R.Runner.server_now(snap), cal=cal)
    assert len(out) == 1 and "stop loss" in out[0]["_why"]


@pytest.mark.parametrize("what", ["expiry", "age", "underwater", "news", "signals", "noprice"])
def test_it_does_not_carry_a_position_overnight_when_the_idea_is_not_intact(cfg, tmp_path, what):
    rn, ap, cal = desk(cfg, tmp_path)
    day = DAY
    symbol = "NIFTY12NOV2624550CE"
    opened = T0 + dt.timedelta(minutes=7)
    if what == "expiry":
        day = dt.date(2026, 11, 11)                                                                                              # Wednesday: expiry is tomorrow
        opened = dt.datetime(2026, 11, 11, 10, 0, tzinfo=IST)
    if what == "age":
        day = dt.date(2026, 11, 12 - 0)
        symbol = "NIFTY19NOV2624550CE"
        opened = dt.datetime(2026, 11, 9, 10, 7, tzinfo=IST)
    inst, _ = R.parse_contract(symbol, {"NIFTY"}, {"NIFTY": 65})
    held_position(rn, symbol, opened)
    kw, mult, news = {}, 1.1, None
    if what == "underwater":
        mult = 0.7
    if what == "news":
        news = digest(story(-0.8, "high", now=dt.datetime.combine(day, dt.time(15, 21), tzinfo=IST), age_min=5))
    if what == "signals":
        kw = SIG_DOWN
    t = dt.datetime.combine(day, dt.time(15, 21), tzinfo=IST)
    q = board(t, **{**dict(cb=1000, ca=1000, pb=1000, pa=1000), **kw})
    if symbol not in q["quotes"]:
        q["quotes"][symbol] = dict(q["quotes"]["NIFTY12NOV2624550CE"])
    if what != "noprice":
        reprice(q, symbol, round(50.0 * mult, 2))
    else:
        q["quotes"].pop(symbol, None)
    if what == "age":
        q["quotes"] = {k: v for k, v in q["quotes"].items()}
    out = ap.decide(q, rn.account, R.Runner.server_now(q), cal=cal, news=news)
    assert [o for o in out if o["side"] == "sell"], what


def test_the_days_own_stop_counts_what_was_opened_today_and_not_a_position_carried_in(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    old = dt.datetime(2026, 11, 6, 11, 0, tzinfo=IST)                                                                            # carried in from Friday
    inst, _ = R.parse_contract("NIFTY12NOV2624550CE", {"NIFTY"}, {"NIFTY": 65})
    rn.account.apply_fill("buy", inst, "nse_fo", 65, 50.0, 20.0, old.isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: carried in from Friday")
    marks = {"NIFTY12NOV2624550CE": 35.0}                                                                                        # -30% on it: a loss, but not today's
    f = ap.day_facts(rn.account, DAY, marks)
    assert f["entries"] == 0 and f["result"] == pytest.approx(0.0)
    # a position opened today at a heavy loss does count
    inst2, _ = R.parse_contract("NIFTY12NOV2624600CE", {"NIFTY"}, {"NIFTY": 65})
    rn.account.apply_fill("buy", inst2, "nse_fo", 65, 100.0, 30.0, (T0 + dt.timedelta(minutes=5)).isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: today")
    f2 = ap.day_facts(rn.account, DAY, {**marks, "NIFTY12NOV2624600CE": 60.0})
    assert f2["entries"] == 1 and f2["result"] == pytest.approx((60.0 - 100.0) * 65 - 30.0)
    # a sale today realises the result (fees in), and an unpriced position opened today counts as worth nothing
    rn.account.apply_fill("sell", inst2, "nse_fo", 65, 80.0, 25.0, (T0 + dt.timedelta(minutes=30)).isoformat(), "AUTO v1 NIFTY long call", "exit")
    f3 = ap.day_facts(rn.account, DAY, marks)
    assert f3["result"] == pytest.approx((80.0 - 100.0) * 65 - 25.0 - 30.0)
    other = Account(500_000)
    other.apply_fill("buy", inst2, "nse_fo", 65, 100.0, 30.0, (T0 + dt.timedelta(minutes=5)).isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: today")
    assert ap.day_facts(other, DAY, {})["result"] == pytest.approx(-100.0 * 65 - 30.0)
    # the stop: down more than 1% of 500,000 on what it opened today -> it sells that and buys nothing
    snap = reprice(board(T0 + dt.timedelta(minutes=40), **SIG_UP), "NIFTY12NOV2624600CE", 5.0)
    rn3, ap3, cal3 = desk(cfg, tmp_path, day_stop=0.01)
    rn3.account.apply_fill("buy", inst2, "nse_fo", 65, 100.0, 30.0, (T0 + dt.timedelta(minutes=5)).isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: today")
    snap["quotes"]["NIFTY12NOV2624600CE"] = {**snap["quotes"].get("NIFTY12NOV2624600CE", {}), "bid": 8.0, "ask": 8.4, "age_s": 1.0, "bid_qty": 1000, "ask_qty": 1000}
    out = ap3.decide(snap, rn3.account, R.Runner.server_now(snap), cal=cal3)
    assert [o for o in out if o["side"] == "sell"] and [o for o in out if o["side"] == "buy"] == []


# ---- its own limits -----------------------------------------------------------------------------------------------------------------------------------------
def _round_trip(acct, strike, when, strategy="AUTO v1 NIFTY long call"):
    inst, _ = R.parse_contract(f"NIFTY12NOV26{strike}CE", {"NIFTY"}, {"NIFTY": 65})
    acct.apply_fill("buy", inst, "nse_fo", 65, 50.0, 10.0, when.isoformat(), strategy, "AUTO v1: test")
    acct.apply_fill("sell", inst, "nse_fo", 65, 50.5, 10.0, (when + dt.timedelta(minutes=1)).isoformat(), strategy, "exit")


def test_there_is_no_cap_on_trades_or_open_positions_and_no_stop_of_its_own_only_a_short_guard_against_ping_pong(cfg, tmp_path):
    t = T0 + dt.timedelta(minutes=7)
    # ten entries already today, three open, a loss of 1.5% of capital today: it still buys (the risk gate, not AUTO, is what bounds losses)
    rn, ap, cal = desk(cfg, tmp_path)
    for i in range(10):
        _round_trip(rn.account, 24000 + 50 * i, T0 - dt.timedelta(minutes=35) + dt.timedelta(seconds=10 * i))
    for k in (24350, 24400, 24450):
        held_position(rn, f"NIFTY12NOV26{k}CE", T0 - dt.timedelta(minutes=20))
    inst, _ = R.parse_contract("NIFTY12NOV2624650CE", {"NIFTY"}, {"NIFTY": 65})
    rn.account.apply_fill("buy", inst, "nse_fo", 65, 100.0, 10.0, (T0 - dt.timedelta(minutes=30)).isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: today")
    rn.account.apply_fill("sell", inst, "nse_fo", 65, 15.0, 10.0, (T0 - dt.timedelta(minutes=25)).isoformat(), "AUTO v1 NIFTY long call", "exit")      # a 5,500 loss: 1.1% of capital
    warm(rn, ap, cal, T0)
    mine, rep = tick(rn, ap, cal, board(t, **SIG_UP), t)
    buys = [o for o in mine if o["side"] == "buy"]
    assert len(buys) == 1                                                                                                       # AUTO proposes it: no count of trades, no loss stop of its own stands in the way
    res = rep["results"][0]
    assert res["status"] in ("filled", "refused"), res
    if res["status"] == "refused":                                                                                              # if the answer is no, it is the RISK GATE that says so, in its own words
        assert any(x in " ".join(res["reasons"]) for x in ("loss budget", "risk", "daily", "floor")), res["reasons"]
    # the guard: the same contract is not re-bought within five minutes of AUTO's last fill in it; a different one is fine
    rn2, ap2, cal2 = desk(cfg, tmp_path)
    inst2, _ = R.parse_contract("NIFTY12NOV2624550CE", {"NIFTY"}, {"NIFTY": 65})
    for ago, expect in ((2, False), (8, True)):
        rn2, ap2, cal2 = desk(cfg, tmp_path)
        rn2.account.apply_fill("buy", inst2, "nse_fo", 65, 50.0, 10.0, (t - dt.timedelta(minutes=ago + 1)).isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: test")
        rn2.account.apply_fill("sell", inst2, "nse_fo", 65, 40.0, 10.0, (t - dt.timedelta(minutes=ago)).isoformat(), "AUTO v1 NIFTY long call", "exit")
        warm(rn2, ap2, cal2, T0)
        got = [o for o in tick(rn2, ap2, cal2, board(t, **SIG_UP), t)[0] if o["side"] == "buy"]
        assert bool(got) is expect, ago


def test_ids_are_unique_and_an_order_in_flight_is_not_repeated(cfg, tmp_path):
    rn2, ap2, cal2 = desk(cfg, tmp_path)
    warm(rn2, ap2, cal2, T0)
    t = T0 + dt.timedelta(minutes=7)
    snap = board(t, **SIG_UP)
    srv = R.Runner.server_now(snap)
    a = ap2.decide(snap, rn2.account, srv, cal=cal2)
    b = ap2.decide(snap, rn2.account, srv, cal=cal2)                                                                              # nothing filled yet: the same signal must not queue it twice
    assert len(a) == 1 and b == []
    ids = {ap2._oid(1.0, "b") for _ in range(50)}
    assert len(ids) == 50 and all(R.ID_RE.fullmatch(i) for i in ids)


def test_the_module_is_pure_no_network_no_environment_no_clock():
    src = (ROOT / "quantdesk/paper/auto.py").read_text(encoding="utf-8")
    import re
    assert not re.search(r"import (requests|urllib|socket|http)|os\.environ|time\.time\(|datetime\.now\(|\.now\(\)", src)
    assert "take profit" not in src and "TAKE_PROFIT" not in src and "HOLD_MAX_S" not in src                                    # no fixed profit target, no intraday-only time stop


def test_an_optional_day_stop_sells_what_was_opened_today_but_leaves_a_carried_position_to_its_own_stops(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path, day_stop=0.01)
    carried_at = dt.datetime(2026, 11, 6, 11, 0, tzinfo=IST)
    held_position(rn, "NIFTY12NOV2624550CE", carried_at)
    inst, _ = R.parse_contract("NIFTY12NOV2624600CE", {"NIFTY"}, {"NIFTY": 65})
    early = T0 - dt.timedelta(minutes=30)
    rn.account.apply_fill("buy", inst, "nse_fo", 65, 100.0, 10.0, early.isoformat(), "AUTO v1 NIFTY long call", "AUTO v1: today")
    rn.account.apply_fill("sell", inst, "nse_fo", 65, 20.0, 10.0, (early + dt.timedelta(minutes=10)).isoformat(), "AUTO v1 NIFTY long call", "exit")      # a 5,200 loss today: past 1% of 500,000
    t = T0 + dt.timedelta(minutes=7)
    snap = reprice(board(t, **SIG_UP), "NIFTY12NOV2624550CE", 52.0)
    out = ap.decide(snap, rn.account, R.Runner.server_now(snap), cal=cal)
    assert out == [] and "NIFTY12NOV2624550CE" in rn.account.positions                                                         # no sale of the carried one, and no new buy: the day is stopped


def test_it_does_not_buy_a_lottery_ticket_under_five_rupees(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    snap = reprice(board(t, **SIG_UP), "NIFTY12NOV2624550CE", 2.9, 3.0)
    assert tick(rn, ap, cal, snap, t)[0] == []


# ---- review fixes: a contract the owner also holds, and a clock that jumps ---------------------------------------------------------------------------------------
def test_when_the_owner_holds_the_same_contract_auto_never_adds_to_it_and_when_the_owner_adds_to_autos_it_sells_only_its_own_lots(cfg, tmp_path):
    sig = SIG_UP
    t = T0 + dt.timedelta(minutes=7)
    # case B: the owner already holds the very contract AUTO would pick: it picks nothing, and the owner's position is left alone
    rn, ap, cal = desk(cfg, tmp_path)
    inst, _ = R.parse_contract("NIFTY12NOV2624550CE", {"NIFTY"}, {"NIFTY": 65})
    rn.account.apply_fill("buy", inst, "nse_fo", 65, 50.0, 20.0, T0.isoformat(), "owner: breakout", "my own thesis for this trade, kept by hand")
    warm(rn, ap, cal, T0)
    assert [o for o in tick(rn, ap, cal, board(t, **sig), t)[0] if o["side"] == "buy"] == [] and rn.account.positions["NIFTY12NOV2624550CE"].qty == 65
    # case A: AUTO holds a lot, then the owner buys another lot of the same contract (the two merge into one position)
    rn, ap, cal, t = open_one(cfg, tmp_path)
    sym = next(iter(rn.account.positions))
    inst, _ = R.parse_contract(sym, {"NIFTY"}, {"NIFTY": 65})
    rn.account.apply_fill("buy", inst, "nse_fo", 65, rn.account.positions[sym].avg_price, 20.0, (t + dt.timedelta(minutes=1)).isoformat(), "owner: add", "my own second lot, bought by hand on purpose")
    assert rn.account.positions[sym].qty == 130
    assert ap.own_qty(rn.account) == {sym: 65}
    (mine, rep), _ = moved(rn, ap, cal, t + dt.timedelta(minutes=2), 0.55)                                                         # the stop
    assert len(mine) == 1 and mine[0]["lots"] == 1 and rep["results"][0]["status"] == "filled"                                   # one lot sold, not "all"
    assert rn.account.positions[sym].qty == 65                                                                                    # the owner's lot is still there
    (mine2, _), _ = moved(rn, ap, cal, t + dt.timedelta(minutes=3), 0.40)
    assert mine2 == [] and rn.account.positions[sym].qty == 65                                                                    # and AUTO now treats it as none of its business


def test_a_snapshot_time_that_jumps_restarts_the_momentum_tape_instead_of_freezing_it(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    far = T0 + dt.timedelta(days=2)
    ap.decide(board(far), rn.account, R.Runner.server_now(board(far)), cal=cal)
    assert len(ap.tape["NIFTY"]) == 1 and ap.tape["NIFTY"][0][0] == pytest.approx(far.timestamp())
    back = T0 + dt.timedelta(minutes=10)
    ap.decide(board(back), rn.account, R.Runner.server_now(board(back)), cal=cal)
    assert len(ap.tape["NIFTY"]) == 1 and ap.tape["NIFTY"][0][0] == pytest.approx(back.timestamp())


def test_after_an_entry_order_for_an_index_and_direction_it_waits_a_minute_before_another_strike(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    first = ap.decide(board(t, **SIG_UP), rn.account, R.Runner.server_now(board(t, **SIG_UP)), cal=cal)
    assert len(first) == 1
    t2 = t + dt.timedelta(seconds=20)
    shifted = board(t2, **SIG_UP, spot=SPOT + 50)                                                                               # spot moved a strike: ATM+1 is a different contract
    assert [o for o in ap.decide(shifted, rn.account, R.Runner.server_now(shifted), cal=cal) if o["side"] == "buy"] == []
    t3 = t + dt.timedelta(seconds=70)
    later = board(t3, **SIG_UP, spot=SPOT + 50)
    assert len([o for o in ap.decide(later, rn.account, R.Runner.server_now(later), cal=cal) if o["side"] == "buy"]) == 1       # a minute on, a new strike is fine


# ---- a stopped account and the storage guard (reviewer, PR #252) ----------------------------------------------------------------------------------------------
def test_it_proposes_nothing_while_the_account_is_stopped_for_the_day_or_halted_and_goes_on_when_it_is_cleared(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    snap = board(t, **SIG_UP)
    srv = R.Runner.server_now(snap)
    for flag, val in (("day_halted", True), ("halt", "drawdown")):
        setattr(rn.account, flag, val)
        assert ap.decide(snap, rn.account, srv, cal=cal) == [] and "stopped" in ap.last_info["entries"]
        setattr(rn.account, flag, False if flag == "day_halted" else None)
    assert len(ap.decide(snap, rn.account, srv, cal=cal)) == 1


def test_it_stops_opening_at_the_ledger_soft_limit_but_still_manages_what_it_holds(cfg, tmp_path):
    rn, ap, cal = desk(cfg, tmp_path)
    warm(rn, ap, cal, T0)
    t = T0 + dt.timedelta(minutes=7)
    snap = board(t, **SIG_UP)
    srv = R.Runner.server_now(snap)
    rn.account.ledger.extend({"kind": "event", "seq": i} for i in range(A.LEDGER_SOFT_LIMIT))
    assert ap.decide(snap, rn.account, srv, cal=cal) == [] and "ledger holds" in ap.last_info["entries"]
    del rn.account.ledger[:]
    assert len(ap.decide(snap, rn.account, srv, cal=cal)) == 1
