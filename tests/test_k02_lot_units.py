"""Audit K-02 (E-01, CRITICAL): MCX and NSE currency books show sizes in LOTS, the gate compared UNITS, so an MCX future's stop, square-off and the loss-cap flatten
were refused ("100 is more than the 2 bid") and the loss ran with no bound. Now every size is converted to units once, where a quote enters the runner, and a forced exit
(a stop, target or square-off, the expiry sale, the loss-budget trim, the kill switch and the halts' flatten) is never refused for the size shown: it is filled, and the
ledger row says what was shown. PAPER MONEY ONLY."""
from __future__ import annotations

import datetime as dt

import pytest

from quantdesk.paper import runner as R
from quantdesk.paper.account import Account
from quantdesk.paper.risk import Quote
from tests import test_paper_auto2_mcx as M
from tests.test_paper_auto2 import cfg  # noqa: F401 - a fixture

FL2 = "FL1.uaan.2/1.d"                    # a long future with a 2R target (any target works here; this one also meets asymmetric_only_v1)


def held_future(cfg, tmp_path, monkeypatch):
    rn, ap = M.desk(cfg, tmp_path, M.proven(FL2))
    ap.evolved_on = M.EVE.date()
    monkeypatch.setattr(ap, "state", lambda snap, u, ch, now, news: M.futures_state("up"))
    snap = M.crude_board(M.EVE)
    snap["quotes"]["CRUDEOIL-MCX"].update(bid_qty=2, ask_qty=11)              # the live board at 22:55 IST, 20 Nov: 2 lots bid, 11 offered
    mine = ap.decide(snap, rn.account, R.Runner.server_now(snap))
    rep = rn.step(snap, mine, False, M.EVE.astimezone(dt.timezone.utc))
    return rn, ap, mine, rep


def test_sizes_on_a_lot_sized_segment_become_units_and_nse_fo_stays_in_units():
    now = dt.datetime(2026, 11, 20, 17, 25, tzinfo=dt.timezone.utc)
    snap = {"quotes": {"X": {"bid": 10.0, "ask": 10.5, "bid_qty": 2, "ask_qty": 11, "age_s": 1.0}}}
    q1, q100 = R.Runner.quote_from(snap, "X", now), R.Runner.quote_from(snap, "X", now, lot=100)
    assert (q1.bid_qty, q1.ask_qty) == (2, 11) and (q100.bid_qty, q100.ask_qty) == (200, 1100)
    fut = type("I", (), {"lot_size": 100})()
    assert R.Runner.units(fut, "mcx") == 100 and R.Runner.units(fut, "nse_cds") == 100 and R.Runner.units(fut, "nse_fo") == 1
    assert R.Runner.quote_from(snap, "X", now, lot=True).bid_qty == 2 and R.Runner.quote_from(snap, "X", now, lot=0).bid_qty == 2     # never a bad multiplier


def test_a_one_lot_mcx_future_is_bought_against_a_book_shown_in_lots(cfg, tmp_path, monkeypatch):
    rn, ap, mine, rep = held_future(cfg, tmp_path, monkeypatch)
    fut = [o for o in mine if o.get("symbol") == "CRUDEOIL-MCX"]
    assert fut, "AUTO proposed no future"
    res = next(r for r in rep["results"] if r["id"] == fut[0]["id"])
    assert res["status"] == "filled", res["reasons"]                                 # was: "100 is more than the 11 offered"


def test_the_stop_of_an_mcx_future_executes_against_a_book_shown_in_lots(cfg, tmp_path, monkeypatch):
    rn, ap, _, _ = held_future(cfg, tmp_path, monkeypatch)
    pos = rn.account.positions.get("CRUDEOIL-MCX")
    assert pos is not None and pos.stop
    t2 = M.EVE + dt.timedelta(minutes=5)
    snap2 = M.crude_board(t2, F=pos.stop - 20)
    snap2["quotes"]["CRUDEOIL-MCX"].update(bid_qty=2, ask_qty=11)
    rep = rn.step(snap2, [], False, t2.astimezone(dt.timezone.utc))
    assert "CRUDEOIL-MCX" not in rn.account.positions, f"stop not executed: {rep['forced']}"         # was: "100 is more than the 2 bid", and the loss ran


def test_a_forced_exit_is_filled_even_against_less_than_its_size_and_the_ledger_says_so(cfg, tmp_path, monkeypatch):
    rn, ap, _, _ = held_future(cfg, tmp_path, monkeypatch)
    pos = rn.account.positions["CRUDEOIL-MCX"]
    t2 = M.EVE + dt.timedelta(minutes=5)
    snap2 = M.crude_board(t2, F=pos.stop - 20)
    snap2["quotes"]["CRUDEOIL-MCX"].update(bid_qty=0.5, ask_qty=11)                 # thinner than the position, even in units (50 against 100)
    rn.step(snap2, [], False, t2.astimezone(dt.timezone.utc))
    assert "CRUDEOIL-MCX" not in rn.account.positions
    row = rn.account.ledger[-1]
    assert row["kind"] == "sell" and "never refused for size" in row["thesis"] and "against 50 bid" in row["thesis"]
    assert rn.account.verify_ledger()


def test_the_owners_own_sale_still_needs_the_size_in_units(cfg, tmp_path, monkeypatch):
    rn, ap, _, _ = held_future(cfg, tmp_path, monkeypatch)
    t2 = M.EVE + dt.timedelta(minutes=3)
    snap2 = M.crude_board(t2)
    snap2["quotes"]["CRUDEOIL-MCX"].update(bid_qty=0.5, ask_qty=11)                 # 50 units bid against a 100-unit position
    o = {"id": "own-sell-1", "side": "sell", "symbol": "CRUDEOIL-MCX", "lots": "all", "queued_at": int(t2.timestamp() * 1000)}
    rep = rn.step(snap2, [o], False, t2.astimezone(dt.timezone.utc))
    res = next(r for r in rep["results"] if r["id"] == "own-sell-1")
    assert res["status"] == "refused" and any("100 is more than the 50 bid" in x for x in res["reasons"]) and "CRUDEOIL-MCX" in rn.account.positions
    snap2["quotes"]["CRUDEOIL-MCX"].update(bid_qty=2)                                # 200 units: the owner's sale goes
    o2 = dict(o, id="own-sell-2")
    rep = rn.step(snap2, [o2], False, (t2 + dt.timedelta(seconds=3)).astimezone(dt.timezone.utc))
    assert next(r for r in rep["results"] if r["id"] == "own-sell-2")["status"] == "filled" and "CRUDEOIL-MCX" not in rn.account.positions


def test_the_gate_refuses_by_size_only_when_not_forced():
    from quantdesk.config import Config
    from pathlib import Path
    from quantdesk.paper.risk import RiskGate
    from quantdesk.core.types import Instrument
    cfg_ = Config.load(Path(__file__).resolve().parents[1] / "config" / "quantdesk.yaml")
    gate = RiskGate(cfg_)
    a = Account(500_000.0)
    inst = Instrument.option("NIFTY", dt.date(2026, 11, 24), 24500, "CE", 65)
    a.apply_fill("buy", inst, "nse_fo", 130, 100.0, 40.0, "2026-11-20T04:00:00+00:00", "s", "a held call for the size test")
    now = dt.datetime(2026, 11, 20, 5, 0, tzinfo=dt.timezone.utc)
    q = Quote(90.0, 90.5, now, 65.0, 1000.0)
    assert not gate.check_exit(a, inst.symbol, 130, q, now).allowed
    assert gate.check_exit(a, inst.symbol, 130, q, now, forced=True).allowed
