"""Audit K-03 (B-02, CRITICAL): a futures stop is a trigger, not a bound. A 2-lot CRUDEOIL long passed the gate at about Rs 11.4k to its stop, then a 10% move lost
Rs 1,20,432 (24% of equity) in one trade; the stop filled on a 590 s old bid; with the feed down the "lower bound" counted the position at its stop. Now:
  * an entry's risk is the larger of its stop's loss and the contract's registered stress move (paper.futures.stress_pct: the exchange's price-limit band), fees in;
  * a future is marked, and its stop, target or square-off filled, only on a quote at most FUT_QUOTE_AGE_S old; older, it counts at its stress loss.
PAPER MONEY ONLY."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.markets import sessions as MK
from quantdesk.paper import runner as R
from quantdesk.paper.account import Account, future_worst
from quantdesk.paper.risk import KillSwitch, RiskGate

ROOT = Path(__file__).resolve().parents[1]
IST = MK.IST
MON = dt.datetime(2026, 11, 16, 11, 0, tzinfo=IST)
THESIS = "crude holding above the overnight range with rising open interest"


@pytest.fixture()
def cfg():
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def board(now, name, bid, ask, age=2.0, e="2026-12-17", lots_shown=20):
    return {"now": int(now.timestamp() * 1000), "quotes": {name: dict(bid=bid, ask=ask, bid_qty=lots_shown, ask_qty=lots_shown, ltp=bid, age_s=age, s="mcx", e=e)}}


def step(rn, snap, orders, now):
    return rn.step(snap, orders, False, now.astimezone(dt.timezone.utc))


def desk(cfg, tmp_path, capital=500_000):
    return R.Runner(cfg, Account(capital), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL")), kill_file=tmp_path / "KILL")


def buy(rn, name, lots, stop, px=5800.0):
    o = dict(id=f"fut-{name[:6]}-{lots}", side="buy", symbol=name, lots=lots, stop=stop, strategy="crude breakout", thesis=THESIS, queued_at=int(MON.timestamp() * 1000) - 2000)
    return step(rn, board(MON, name, px, px + 1.0), [o], MON)["results"][0]


def test_every_contract_has_a_registered_stress_move(cfg):
    g = RiskGate(cfg)
    contracts = cfg.get("paper.futures.contracts")
    assert set(g.fut_stress) == {u.upper() for u in contracts}
    assert all(g.fut_stress[u.upper()] == (0.09 if c["segment"] == "mcx" else 0.03) for u, c in contracts.items())


def test_the_audits_two_lot_crude_long_is_refused_because_a_gap_through_its_stop_could_cost_far_more_than_2_5_percent(cfg, tmp_path):
    rn = desk(cfg, tmp_path)
    res = buy(rn, "CRUDEOIL-MCX", 2, 5750.0)
    assert res["status"] == "refused" and any("9% move through it" in r for r in res["reasons"]), res
    assert not rn.account.positions


def test_a_mini_contract_sized_on_the_stress_move_keeps_a_stress_gap_inside_the_per_trade_cap(cfg, tmp_path):
    rn = desk(cfg, tmp_path)
    res = buy(rn, "CRUDEOILM-MCX", 1, 5750.0)
    assert res["status"] == "filled", res
    eq0 = 500_000
    t1 = MON + dt.timedelta(seconds=3)
    step(rn, board(t1, "CRUDEOILM-MCX", 5800 * 0.91, 5800 * 0.91 + 1), [], t1)          # a 9% gap straight through the stop, inside three seconds
    assert "CRUDEOILM-MCX" not in rn.account.positions
    loss = eq0 - rn.account.cash
    assert 0 < loss <= 0.025 * eq0, loss                                                  # the per-trade cap holds through a stress gap (it did not: 24.1%)


def test_a_stop_is_never_filled_on_a_stale_quote_and_the_position_counts_at_its_stress_loss(cfg, tmp_path):
    rn = desk(cfg, tmp_path)
    assert buy(rn, "CRUDEOILM-MCX", 1, 5750.0)["status"] == "filled"
    t1 = MON + dt.timedelta(seconds=3)
    step(rn, board(t1, "CRUDEOILM-MCX", 5740.0, 5741.0, age=590.0), [], t1)               # the only price is 590 s old
    assert "CRUDEOILM-MCX" in rn.account.positions                                        # not sold at a price ten minutes old (it was)
    p = rn.account.positions["CRUDEOILM-MCX"]
    assert future_worst(p, rn.account.fut_stress) == pytest.approx(-10 * 0.09 * p.avg_price)
    assert rn.account.equity_lower_bound({}) <= rn.account.cash + p.value(p.avg_price * 0.91) + 1e-6   # a floor under a 9% gap, not the stop's loss
    t2 = MON + dt.timedelta(seconds=6)
    step(rn, board(t2, "CRUDEOILM-MCX", 5740.0, 5741.0, age=2.0), [], t2)                  # a fresh price: the stop goes at once
    assert "CRUDEOILM-MCX" not in rn.account.positions


def test_with_the_feed_down_the_lower_bound_is_under_the_true_equity_at_a_stress_gap(cfg, tmp_path):
    rn = desk(cfg, tmp_path)
    assert buy(rn, "CRUDEOILM-MCX", 1, 5750.0)["status"] == "filled"
    t1 = MON + dt.timedelta(minutes=11)
    step(rn, board(t1, "CRUDEOILM-MCX", 5800 * 0.91, 5800 * 0.91 + 1, age=700.0), [], t1)
    p = rn.account.positions["CRUDEOILM-MCX"]
    gap = p.avg_price * 0.91                                                                     # a 9% move from its entry
    assert rn.account.equity_lower_bound({}) <= rn.account.cash + p.value(gap) + 1e-6           # was: above it (the stop's loss only)
    assert rn.account.stress() <= rn.account.cash + p.value(gap) + 1e-6


def test_a_contract_with_no_registered_stress_move_is_not_opened(cfg, tmp_path):
    rn = desk(cfg, tmp_path)
    rn.gate.fut_stress.pop("CRUDEOILM")
    res = buy(rn, "CRUDEOILM-MCX", 1, 5750.0)
    assert res["status"] == "refused" and any("no registered stress move" in r for r in res["reasons"])


def test_an_option_book_is_unchanged():
    from quantdesk.core.types import Instrument
    a = Account(500_000.0)
    a.fut_stress = {"NIFTY": 0.06}
    inst = Instrument.option("NIFTY", dt.date(2026, 11, 24), 24500, "CE", 65)
    a.apply_fill("buy", inst, "nse_fo", 65, 100.0, 20.0, "2026-11-20T04:00:00+00:00", "s", "a held call, no future in the book")
    assert a.stress() == pytest.approx(a.cash) and a.equity_lower_bound({}) == pytest.approx(a.cash)


def test_a_future_is_never_marked_on_a_quote_older_than_two_minutes_but_an_option_still_is(cfg, tmp_path):
    rn = desk(cfg, tmp_path)
    assert buy(rn, "CRUDEOILM-MCX", 1, 5750.0)["status"] == "filled"
    t1 = MON + dt.timedelta(minutes=6)
    assert "CRUDEOILM-MCX" in rn.marks(board(t1, "CRUDEOILM-MCX", 5790.0, 5791.0, age=100.0), t1)
    assert "CRUDEOILM-MCX" not in rn.marks(board(t1, "CRUDEOILM-MCX", 5790.0, 5791.0, age=300.0), t1)   # 5 minutes old: unknown, so it counts at its stress loss
    assert R.FUT_QUOTE_AGE_S == 120 < R.MARK_MAX_AGE_S


def test_with_only_stale_quotes_the_square_off_still_closes_before_the_close_and_says_how_old_its_price_was(cfg, tmp_path):
    """Risk review of K-03: the 120 s rule must not hold a future overnight. The square-off (and a future somehow held past its day) takes the freshest quote within
    FORCED_EXIT_AGE_S and records its age; a stop or a target still needs a fresh one."""
    rn = desk(cfg, tmp_path)
    assert buy(rn, "CRUDEOILM-MCX", 1, 5750.0)["status"] == "filled"
    t1 = MON.replace(hour=23, minute=26)                                                    # inside the 5-minute square-off before MCX's 23:30 close
    step(rn, board(t1, "CRUDEOILM-MCX", 5790.0, 5791.0, age=300.0), [], t1)
    assert "CRUDEOILM-MCX" not in rn.account.positions
    row = rn.account.ledger[-1]
    assert row["kind"] == "sell" and "square-off" in row["thesis"] and "300 s old" in row["thesis"]


def test_a_stale_quote_still_never_fires_a_stop_and_a_future_held_past_its_day_is_listed_as_stuck(cfg, tmp_path):
    rn = desk(cfg, tmp_path)
    assert buy(rn, "CRUDEOILM-MCX", 1, 5750.0)["status"] == "filled"
    t1 = MON + dt.timedelta(minutes=3)
    step(rn, board(t1, "CRUDEOILM-MCX", 5700.0, 5701.0, age=300.0), [], t1)                 # below the stop, but five minutes old
    assert "CRUDEOILM-MCX" in rn.account.positions
    nxt = MON + dt.timedelta(days=1, hours=-1)                                             # the next morning, before any fresh quote
    snap = board(nxt, "CRUDEOILM-MCX", 5700.0, 5701.0, age=900.0)
    assert "CRUDEOILM-MCX" in rn.summary(snap, nxt.astimezone(dt.timezone.utc))["stuck"]
