"""Hardening C: the entry-unwind path books and journals what it costs, the lot size is checked against the exchange,
a prior-day open position has an explicit owner-only resolution, and the intraday desk's cross-day drawdown stop is
opt-in. Each test was written to fail on the code before the fix."""
import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.analyst import MarketView
from quantdesk.intraday.engine import IntradayEngine, run_step
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.playbook import PlanLeg, TradePlan
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal
from test_trading_path_b import Stub, desk, open_trade, run_to, sessions  # noqa: F401  (sessions: the fixture)

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


# ---- P2-6: the configured lot against the exchange's (Kotak mktLot) ----------------------------------------------------
class LotStub(Stub):
    """A 'real' chain reporting `lot` as the exchange's (None: unknown, as when Kotak sends no mktLot)."""
    def __init__(self, eng, lot):
        super().__init__(eng)
        self.lot = lot

    def chain(self, u, expiry, spot=None, ts=None):
        ch = super().chain(u, expiry, spot=spot, ts=ts)
        ch.attrs["lot"] = self.lot if u == "NIFTY" else self.eng.lot(u)          # only NIFTY disagrees
        return ch


CALM = SimpleNamespace(vetoes=[])


def _lot_desk(cfg, sessions, lot):
    eng, feed = desk(cfg, sessions, chains=lambda e: LotStub(e, lot))
    eng.paused = False
    return eng, feed


def _why(eng, feed):
    return eng._blocked("NIFTY", CALM, feed.now())


def test_a_lot_the_exchange_revised_blocks_new_entries_with_one_event_naming_both(cfg, sessions):
    eng, feed = _lot_desk(cfg, sessions, 70)                                  # config says NIFTY 65
    assert eng.lot("NIFTY") == 65
    why = _why(eng, feed)
    assert why and why.startswith("halted: NIFTY lot size mismatch") and "65" in why and "70" in why
    assert eng.lot("NIFTY") == 65                                             # never adopted silently
    run_to(eng, feed, 5)                                                      # five more refreshes: still one event
    ev = eng.journal.df("SELECT level, category, message FROM events WHERE message LIKE 'NIFTY lot size mismatch%'")
    assert len(ev) == 1 and ev.level[0] == "ERROR" and ev.category[0] == "data"
    assert "65" in ev.message[0] and "70" in ev.message[0]
    assert "lot size" not in str(eng._blocked("BANKNIFTY", CALM, feed.now()))     # only the index that disagrees


def test_a_lot_mismatch_leaves_an_open_trade_managed_and_exited(cfg, sessions):
    eng, feed = _lot_desk(cfg, sessions, 65)
    t, _ = open_trade(eng, feed)
    eng.chains.lot = 70                                                       # NSE revises the lot mid-session
    t.stop = float(eng.chain_df["NIFTY"].attrs["spot"]) + 500                 # and the trade's invalidation is through
    run_to(eng, feed, 1, run_step)
    assert "lot size mismatch" in _why(eng, feed)
    assert not eng.open_trades and [c.exit_reason for c in eng.closed] == ["invalidation"]


def test_a_matching_or_unknown_lot_changes_nothing(cfg, sessions):
    for lot in (65, None, 0, float("nan")):
        eng, feed = _lot_desk(cfg, sessions, lot)
        assert "lot size" not in str(_why(eng, feed)) and not eng.lot_mismatch
        assert eng.journal.df("SELECT * FROM events WHERE message LIKE '%lot size%'").empty
    eng, feed = desk(cfg, sessions)                                           # the model chain carries no exchange lot
    assert "lot size" not in str(_why(eng, feed)) and not eng.lot_mismatch


def test_the_lot_veto_lifts_when_the_exchange_and_config_agree_again(cfg, sessions):
    eng, feed = _lot_desk(cfg, sessions, 70)
    assert "lot size mismatch" in _why(eng, feed)
    eng.chains.lot = 65
    run_to(eng, feed, 1)
    assert "lot size" not in str(_why(eng, feed))


# ---- refresh gates: a step that starts a few hundred ms early must not skip a whole cycle -----------------------------
def test_refresh_due_forgives_jitter_but_not_a_half_interval():
    from quantdesk.intraday.feeds import REFRESH_JITTER, refresh_due
    t0 = ts("2026-09-29 11:00:00")
    for minutes in (1, 4, 15):
        iv = pd.Timedelta(minutes=minutes)
        assert refresh_due(t0 + iv, t0, minutes) and refresh_due(t0 + iv - pd.Timedelta(seconds=0.5), t0, minutes)
        assert not refresh_due(t0 + iv / 2, t0, minutes)
        assert not refresh_due(t0 + iv - REFRESH_JITTER - pd.Timedelta(seconds=0.5), t0, minutes)   # never sooner than the tolerance
    assert refresh_due(t0, None, 1)                                                                 # never refreshed: due
    assert not refresh_due(t0 + pd.Timedelta(seconds=28), t0, 0.5)                                  # a short interval: 5% (1.5 s), not 2 s


class CountingStub(Stub):
    def __init__(self, eng):
        super().__init__(eng)
        self.calls = 0

    def chain(self, u, expiry, spot=None, ts=None):
        self.calls += 1
        return super().chain(u, expiry, spot=spot, ts=ts)


def test_a_chain_refresh_due_now_is_not_skipped_by_jitter(cfg, sessions):
    eng, feed = desk(cfg, sessions, chains=lambda e: CountingStub(e))
    iv = pd.Timedelta(minutes=eng.refresh_min)
    last = eng.chain_at["NIFTY"]
    calls = eng.chains.calls
    eng._refresh_chain("NIFTY", last + iv / 2)                                 # half the interval: no
    eng._refresh_chain("NIFTY", last + iv - pd.Timedelta(seconds=5))           # more than the tolerance early: no
    assert eng.chains.calls == calls and eng.chain_at["NIFTY"] == last
    due = last + iv - pd.Timedelta(seconds=0.5)
    eng._refresh_chain("NIFTY", due)                                           # 0.5 s early: yes
    assert eng.chains.calls == calls + 1 and eng.chain_at["NIFTY"] == due


def test_a_failed_chain_retry_and_the_pre_open_and_news_gates_forgive_jitter_too(cfg, sessions):
    from quantdesk.intraday.news import NewsDesk
    eng, feed = desk(cfg, sessions, chains=lambda e: CountingStub(e))
    eng.chain_at.pop("NIFTY")
    t = feed.now()
    eng.chain_failed_at["NIFTY"] = t
    calls = eng.chains.calls
    iv = pd.Timedelta(minutes=eng.refresh_min)
    eng._refresh_chain("NIFTY", t + iv / 2)
    assert eng.chains.calls == calls
    eng._refresh_chain("NIFTY", t + iv - pd.Timedelta(seconds=0.5))
    assert eng.chains.calls == calls + 1

    got = []
    eng.gift_source = lambda: got.append(1) or {}
    eng._gift_at = t
    for secs, n in ((120, 0), (239.5, 1)):                                     # the pre-open print: every 4 minutes
        try:
            eng.preopen(t + pd.Timedelta(seconds=secs))
        except Exception:
            pass                                                               # what it does with the print is not under test
        assert len(got) == n

    fetched = []
    news = NewsDesk(cfg, fetch=lambda url: fetched.append(url) or "", sources=[{"name": "x", "url": "u"}])
    news.last_fetch = t
    news.refresh(t + pd.Timedelta(minutes=news.refresh_min) / 2)                # half the cadence: not yet
    assert not fetched
    news.refresh(t + pd.Timedelta(minutes=news.refresh_min) - pd.Timedelta(seconds=0.5))
    assert len(fetched) == 1
