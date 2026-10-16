"""Hardening C: the entry-unwind path books and journals what it costs, the lot size is checked against the exchange,
a prior-day open position has an explicit owner-only resolution, and the intraday desk's cross-day drawdown stop is
opt-in. Each test was written to fail on the code before the fix."""
import datetime as dt

import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.analyst import MarketView
from quantdesk.intraday.engine import IntradayEngine
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.playbook import PlanLeg, TradePlan
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal

IST = "Asia/Kolkata"
DAY = dt.date(2026, 9, 29)
START = 500000.0


def ts(x):
    return pd.Timestamp(x, tz=IST)


@pytest.fixture
def cfg(tmp_path):
    return Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp_path / "runtime")}})


class RejectingBroker(IntradayBroker):
    """Rejects the n-th order of the given purposes (1-based, counted per purpose)."""

    def __init__(self, *a, reject=(), **k):
        super().__init__(*a, **k)
        self.reject, self.count = dict(reject), {}

    def execute(self, order, ref_price, ts, atr=None):
        purpose = order.purpose
        self.count[purpose] = self.count.get(purpose, 0) + 1
        if self.count[purpose] in self.reject.get(purpose, ()):
            order.status = "REJECTED"
            return None
        return super().execute(order, ref_price, ts, atr)


def _engine(cfg, broker=None, journal=None):
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days(DAY - dt.timedelta(days=10), DAY)]
    bars, _ = simulate_sessions(days, seed=11)
    j = journal or Journal()
    eng = IntradayEngine(cfg, ReplayFeed(bars, DAY), "model", j, broker or IntradayBroker(cfg, starting_cash=START), say=None)
    eng.start_session(DAY)
    return eng, j


def _spread(exp):
    legs = [PlanLeg(25000.0, "CE", 1, 100.0, 99.5, 13.0, 0.45), PlanLeg(25200.0, "CE", -1, 40.0, 40.5, 13.0, 0.3)]
    return TradePlan("orb", "NIFTY", 1, "bull_call_spread", exp, legs, 65, "t", "th", None, None, 0.35, 0.60, 45, "model", 0.6)


def _view(now):
    return MarketView("NIFTY", now, 25000.0, "bull", 0.8, 0.9, "trend", "fair", None, None, [], [], {}, "a read")


def _pnl_reconciles(eng):
    """Broker cash equals the starting cash plus every trade's P&L, open trades' entry cost aside."""
    booked = sum(t.pnl for t in eng.closed)
    open_cost = sum(t.entry_cost + t.fees for t in eng.open_trades)       # cash out for open legs, fees included
    return eng.broker.cash() + open_cost, START + booked


def test_a_rejected_second_leg_is_unwound_journalled_and_booked_to_pnl(cfg):
    now = ts(f"{DAY} 11:00")
    eng, j = _engine(cfg, RejectingBroker(cfg, starting_cash=START, reject={"open": {2}}))
    msg = eng._open(_spread(dt.date(2026, 10, 6)), 1, [], _view(now), {}, now)
    assert "rejected" in msg and "unwound" in msg
    assert not eng.open_trades and not eng.broker.positions()                 # flat at the broker
    assert len(eng.closed) == 1
    t = eng.closed[0]
    assert t.exit_reason == "entry_aborted" and t.pnl < 0
    # the opening fill and the unwind fill are both on the record, the trade is a row, and cash reconciles to P&L
    fills = j.db.execute("SELECT symbol, qty, trade_id FROM fills ORDER BY id").fetchall()
    assert [(f[1] > 0) for f in fills] == [True, False] and {f[2] for f in fills} == {t.id}
    row = j.db.execute("SELECT status, pnl FROM trades WHERE id=?", (t.id,)).fetchone()
    assert row[0] == "closed" and row[1] == pytest.approx(t.pnl)
    cash_equiv, expected = _pnl_reconciles(eng)
    assert cash_equiv == pytest.approx(expected, abs=0.01)
    assert eng.broker.cash() == pytest.approx(START + t.pnl, abs=0.01)


def test_a_rejected_unwind_keeps_the_trade_open_and_pending_exit(cfg):
    now = ts(f"{DAY} 11:00")
    eng, j = _engine(cfg, RejectingBroker(cfg, starting_cash=START, reject={"open": {2}, "unwind": {1}}))
    msg = eng._open(_spread(dt.date(2026, 10, 6)), 1, [], _view(now), {}, now)
    assert "incomplete" in msg and len(eng.open_trades) == 1 and not eng.closed
    t = eng.open_trades[0]
    assert t.meta["exit_pending"][0] == "entry_aborted" and len(eng.broker.positions()) == 1
    eng._reconcile(DAY)                                                       # the book still agrees with the journal
    assert eng.health["reconcile"]["ok"]
    eng._close(t, now + pd.Timedelta(minutes=1), *t.meta["exit_pending"])     # the retry (the broker now accepts)
    assert not eng.open_trades and not eng.broker.positions() and eng.closed == [t]
    assert eng.broker.cash() == pytest.approx(START + t.pnl, abs=0.01)


def test_the_first_leg_rejected_books_nothing(cfg):
    now = ts(f"{DAY} 11:00")
    eng, j = _engine(cfg, RejectingBroker(cfg, starting_cash=START, reject={"open": {1}}))
    msg = eng._open(_spread(dt.date(2026, 10, 6)), 1, [], _view(now), {}, now)
    assert "nothing opened" in msg and not eng.closed and not eng.open_trades
    assert eng.broker.cash() == START and j.db.execute("SELECT COUNT(*) FROM fills").fetchone()[0] == 0
