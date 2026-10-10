"""Running unattended: a session split across two runners (each capped at 6 hours) must carry on
exactly where the first left off, and a real option chain that can't be reached (NSE blocks many
cloud IPs) must degrade to the model chain instead of stopping the desk."""
import datetime as dt

import pandas as pd
import pytest

import quantdesk.intraday.engine as engine_mod
from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.engine import IntradayEngine, close_out, run_live, run_replay
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal


@pytest.fixture(scope="module")
def sessions():
    from quantdesk.config import DEFAULT_CONFIG, Config
    cal = TradingCalendar(Config.load(DEFAULT_CONFIG).holidays())
    days = [d.date() for d in cal.trading_days("2026-08-17", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days


@pytest.fixture
def sim_clock(monkeypatch):
    """run_live sleeps on the wall clock; in tests each sleep advances the replay clock a minute."""
    feeds = []
    monkeypatch.setattr(engine_mod.time, "sleep", lambda s: [f.advance() for f in feeds])
    return feeds


def _find_handover(cfg, bars, days, tmp_path):
    """A day and a minute at which the desk holds an open position (so the hand-over matters)."""
    for d in days[-8:]:
        eng = IntradayEngine(cfg, ReplayFeed(bars, d), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
        eng.start_session(d)
        while eng.feed.advance():
            eng.step()
            now = eng.feed.now()
            if eng.open_trades and dt.time(10, 30) <= now.time() <= dt.time(14, 30):
                return d, now.time()
    pytest.skip("no open position mid-session in the sample")


def test_handover_resumes_the_session(cfg, sessions, tmp_path, sim_clock):
    bars, days = sessions
    day, t_hand = _find_handover(cfg, bars, days, tmp_path)
    j = Journal(tmp_path / "j.db")
    bstate = tmp_path / "broker.json"

    feed_a = ReplayFeed(bars, day)
    sim_clock.append(feed_a)
    a = IntradayEngine(cfg, feed_a, "model", j, IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    msg = run_live(a, t_hand, handover=True)
    assert msg.startswith("handed over") and a.open_trades                      # still holding at the hand-over
    assert not any(t.exit_reason == "square_off" for t in a.closed)             # nothing was squared off early
    held = {t.id for t in a.open_trades}
    done = {t.id for t in a.closed}

    # the second runner: new process, same journal and broker state, starts a couple of minutes later
    feed_b = ReplayFeed(bars, day)
    feed_b.clock = feed_a.clock + pd.Timedelta(minutes=2)
    sim_clock[:] = [feed_b]
    b = IntradayEngine(cfg, feed_b, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None, review_dir=tmp_path / "rev")
    review = run_live(b)
    assert {t.id for t in b.closed} >= held | done                              # both halves are in the day
    assert b.day_start_equity == pytest.approx(a.day_start_equity)
    assert not b.open_trades
    tr = Journal(tmp_path / "j.db").trades()
    day_tr = tr[tr["opened_at"].str.startswith(str(day))]
    assert (day_tr["status"] == "closed").all() and len(day_tr) == len(b.closed)
    assert len(day_tr) <= cfg.get("intraday.risk.max_trades_per_day")
    for tid in held | done:
        assert tid in review                                                    # the review covers the whole day
    assert (tmp_path / "rev" / f"{day}.md").exists()


def test_handover_nobody_picked_up_is_closed_after_the_bell(cfg, sessions, tmp_path, sim_clock):
    bars, days = sessions
    day, t_hand = _find_handover(cfg, bars, days, tmp_path)
    bstate = tmp_path / "broker.json"
    feed_a = ReplayFeed(bars, day)
    sim_clock.append(feed_a)
    a = IntradayEngine(cfg, feed_a, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    run_live(a, t_hand, handover=True)
    assert a.open_trades
    late = ReplayFeed(bars, day)
    late.clock = late.close_ts + pd.Timedelta(minutes=20)
    b = IntradayEngine(cfg, late, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    review = run_live(b)
    assert "session review" in review and not b.open_trades
    assert (Journal(tmp_path / "j.db").trades()["status"] == "closed").all()
    # and once it's closed, a later run has nothing to do
    assert "is over" in run_live(IntradayEngine(cfg, late, "model", Journal(tmp_path / "j.db"),
                                                IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None))


def test_kill_switch_squares_off_at_current_prices(cfg, sessions, tmp_path, sim_clock):
    bars, days = sessions
    day, t_hand = _find_handover(cfg, bars, days, tmp_path)
    bstate = tmp_path / "broker.json"
    feed_a = ReplayFeed(bars, day)
    sim_clock.append(feed_a)
    a = IntradayEngine(cfg, feed_a, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    run_live(a, t_hand, handover=True)                                          # cancelled mid-run
    held = {t.id for t in a.open_trades}
    stop = ReplayFeed(bars, day)
    stop.clock = feed_a.clock
    b = IntradayEngine(cfg, stop, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    close_out(b)
    tr = Journal(tmp_path / "j.db").trades().set_index("id")
    assert (tr.loc[list(held), "exit_reason"] == "manual").all() and (tr["status"] == "closed").all()
    assert b.chain_df                                                           # exits used a calibrated chain
    assert close_out(b) == "nothing open to close"
    # the operator changes their mind and restarts: the day resumes with its trades counted
    again = ReplayFeed(bars, day)
    again.clock = feed_a.clock + pd.Timedelta(minutes=30)
    sim_clock[:] = [again]
    c = IntradayEngine(cfg, again, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    run_live(c)
    assert c.day_start_equity == pytest.approx(a.day_start_equity) and held <= {t.id for t in c.closed}


def test_not_a_trading_day_and_late_handover(cfg, sessions, sim_clock):
    bars, days = sessions
    sunday = ReplayFeed(bars, days[-1])
    sunday.clock = pd.Timestamp("2026-09-27 10:00", tz="Asia/Kolkata")
    eng = IntradayEngine(cfg, sunday, "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    assert "not an NSE trading day" in run_live(eng)
    f = ReplayFeed(bars, days[-1])
    f.clock = f.open_ts + pd.Timedelta(hours=4)
    eng = IntradayEngine(cfg, f, "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    assert "nothing to do" in run_live(eng, dt.time(12, 0), handover=True)


class BrokenChain:
    """Stands in for NSE when it refuses the connection."""
    name = "nse"

    def __init__(self):
        self.calls = 0

    def expiries(self, u):
        raise ConnectionError("403 Forbidden")

    def chain(self, u, expiry, spot=None, ts=None):
        self.calls += 1
        raise ConnectionError("403 Forbidden")


def test_unreachable_chain_falls_back_to_the_model(cfg, sessions):
    bars, days = sessions
    broken = BrokenChain()
    j = Journal()
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), broken, j, IntradayBroker(cfg, starting_cash=500000), say=None)
    run_replay(eng)
    th = j.thoughts(str(days[-1]))
    assert not th["action"].str.contains("no option chain").any()               # it kept thinking with prices
    assert eng.chain_name() == "model (no nse)"
    warn = j.events(level="WARN")
    msgs = warn[warn["message"].str.contains("pricing off the model chain")]
    assert 1 <= len(msgs) <= 8                                                  # said so, without spamming
    # backs off: ~2×125 refreshes in a session, but only 3 quick tries then one every 15 min per underlying
    assert broken.calls <= 2 * (3 + 26)
    assert all(t.meta.get("quote_source") == "model" for t in eng.closed)


# ---- exits never sell more than the broker holds (H-01) -----------------------------------------------------------
def _spread_engine(cfg, bars, day, tmp_path):
    """An engine at 10:30 holding one two-leg call debit spread opened by the test itself (the desk is paused, so it
    opens nothing of its own); journal and broker state on disk, as a restarted runner would find them."""
    import numpy as np
    from quantdesk.intraday.analyst import MarketView
    from quantdesk.intraday.playbook import PlanLeg, TradePlan
    feed = ReplayFeed(bars, day)
    eng = IntradayEngine(cfg, feed, "model", Journal(tmp_path / "j.db"),
                         IntradayBroker(cfg, starting_cash=500000, state_path=tmp_path / "broker.json"), say=None)
    eng.start_session(day)
    eng.paused = True
    feed.clock = feed.open_ts + pd.Timedelta(minutes=75)
    eng.step()
    ch = eng.chain_df["NIFTY"]
    S, ks = float(ch.attrs["spot"]), ch.index.to_numpy(float)
    k1, k2 = ks[int(np.argmin(np.abs(ks - S)))], ks[int(np.argmin(np.abs(ks - S))) + 2]
    legs = [PlanLeg(k1, "CE", 1, float(ch.loc[k1].ce_ask), float(ch.loc[k1].ce_ask), float(ch.loc[k1].ce_iv), 0.5),
            PlanLeg(k2, "CE", -1, float(ch.loc[k2].ce_bid), float(ch.loc[k2].ce_bid), float(ch.loc[k2].ce_iv), 0.35)]
    plan = TradePlan("probe", "NIFTY", 1, "call debit spread", eng.expiry["NIFTY"], legs, eng.lot("NIFTY"), "probe",
                     "probe", None, None, 0.99, 50.0, 9999, "model", 0.5)
    view = MarketView("NIFTY", feed.now(), S, "neutral", 0.0, 0.5, "trend", "fair", None, None, [], [], {}, "probe")
    eng._open(plan, 1, [], view, {}, feed.now())
    eng.journal.commit()
    assert len(eng.open_trades) == 1 and len(eng.broker.positions()) == 2
    return eng, view


def _criticals(j, text):
    ev = j.events(level="CRITICAL")
    return ev[ev["message"].str.contains(text, regex=False)]


def test_exit_after_a_restart_closes_only_what_the_broker_holds(cfg, sessions, tmp_path):
    """Scenario 8b: the long leg was closed at the broker (an exit cut short before the journal heard of it). After a
    restart the journal still holds both legs; the exit must not sell the long leg again into a naked short."""
    from quantdesk.core.types import Order
    bars, days = sessions
    day = days[-1]
    a, _ = _spread_engine(cfg, bars, day, tmp_path)
    t = a.open_trades[0]
    long_leg, short_leg = t.legs
    a.broker.execute(Order(long_leg.instrument, -long_leg.qty, t.id, "close"), long_leg.entry_price, a.feed.now())
    assert a.broker.positions() == {short_leg.instrument.symbol: a.broker.positions()[short_leg.instrument.symbol]}

    feed = ReplayFeed(bars, day)
    feed.clock = a.feed.now() + pd.Timedelta(minutes=2)
    b = IntradayEngine(cfg, feed, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=500000, state_path=tmp_path / "broker.json"), say=None)
    b.start_session(day)
    assert [x.id for x in b.open_trades] == [t.id] and not b.health["reconcile"]["ok"]
    b._close(b.open_trades[0], feed.now(), "manual", "closed after the restart")
    assert {s: p["qty"] for s, p in b.broker.positions().items()} == {}        # flat: no naked short on the long leg
    assert not b.open_trades and b.closed[-1].status == "closed"
    sym = long_leg.instrument.symbol
    assert len(_criticals(b.journal, f"exit of {sym} skipped: the broker holds 0")) == 1
    fills = b.journal.df("SELECT symbol, qty FROM fills WHERE trade_id=?", (t.id,))
    assert sorted(fills["qty"].tolist()) == sorted([long_leg.qty, short_leg.qty, -short_leg.qty])   # no 2nd sale
    assert b.closed[-1].legs[0].exit_price is not None                          # marked at the estimated exit price


def test_rejected_exit_leg_leaves_the_trade_open_and_is_retried(cfg, sessions, tmp_path):
    bars, days = sessions
    eng, view = _spread_engine(cfg, bars, days[-1], tmp_path)
    t = eng.open_trades[0]
    short_sym = t.legs[1].instrument.symbol
    real = eng.broker.execute
    eng.broker.execute = lambda o, *a, **k: None if o.instrument.symbol == short_sym else real(o, *a, **k)
    eng._close(t, eng.feed.now(), "manual", "probe")
    assert eng.open_trades == [t] and t.status == "open" and not eng.closed     # not marked closed
    for _ in range(2):                                                          # rejected minute after minute
        eng.feed.advance()
        eng._close(t, eng.feed.now(), "manual", "probe")
    assert set(eng.broker.positions()) == {short_sym}                           # the long leg went once, never again
    assert len(_criticals(eng.journal, "stays open")) == 1                      # said once, not every minute
    saved = eng.journal.get_state("intraday_open")["trades"]
    assert [x["id"] for x in saved] == [t.id] and saved[0]["meta"]["exit_pending"][0] == "manual"
    eng.broker.execute = real                                                   # the broker takes orders again
    eng._manage("NIFTY", view, eng.feed.now())                                  # the next minute finishes the exit
    assert not eng.open_trades and eng.broker.positions() == {}
    assert eng.closed[-1].exit_reason == "manual" and "exit_pending" not in eng.closed[-1].meta
    assert len(eng.journal.events(level="CRITICAL")) == 1


def test_safe_mode_does_not_count_a_stuck_exit_as_squared_off(cfg, sessions, tmp_path):
    """H-01 review: safe mode said "1 position(s) squared off" while a rejected leg kept the trade open."""
    bars, days = sessions
    eng, _ = _spread_engine(cfg, bars, days[-1], tmp_path)
    short_sym = eng.open_trades[0].legs[1].instrument.symbol
    real = eng.broker.execute
    eng.broker.execute = lambda o, *a, **k: None if o.instrument.symbol == short_sym else real(o, *a, **k)
    eng.enter_safe_mode(eng.feed.now(), "probe")
    msg = _criticals(eng.journal, "safe mode: probe")["message"].iloc[0]
    assert "0 position(s) squared off, 1 still open" in msg and len(eng.open_trades) == 1


def test_normal_exit_is_unchanged(cfg, sessions, tmp_path):
    bars, days = sessions
    eng, _ = _spread_engine(cfg, bars, days[-1], tmp_path)
    t = eng.open_trades[0]
    cash0, fees0 = eng.broker.cash(), t.fees
    eng._close(t, eng.feed.now(), "manual", "probe")
    assert not eng.open_trades and eng.broker.positions() == {} and t.status == "closed"
    fills = eng.journal.df("SELECT symbol, qty, price, fees FROM fills WHERE trade_id=? ORDER BY id", (t.id,))
    assert fills["qty"].tolist() == [l.qty for l in t.legs] + [-l.qty for l in t.legs]
    exits = fills.iloc[2:]
    assert [l.exit_price for l in t.legs] == exits["price"].tolist()
    assert t.fees == pytest.approx(fees0 + exits["fees"].sum())
    assert t.pnl == pytest.approx(sum(l.qty * (l.exit_price - l.entry_price) for l in t.legs) - t.fees)
    assert eng.broker.cash() == pytest.approx(cash0 + sum(-q * p for q, p in zip(exits["qty"], exits["price"]))
                                              - exits["fees"].sum())
    assert eng.journal.events(level="CRITICAL").empty
