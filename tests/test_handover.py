"""Running unattended: a session split across two runners (each capped at 6 hours) must carry on
exactly where the first left off, and a real option chain that can't be reached (NSE blocks many
cloud IPs) must degrade to the model chain instead of stopping the desk."""
import datetime as dt
import json
from types import SimpleNamespace

import pandas as pd
import pytest

import quantdesk.intraday.engine as engine_mod
from quantdesk.core.calendar import TradingCalendar
from quantdesk.core.types import Instrument
from quantdesk.intraday.engine import IntradayEngine, close_out, run_live, run_replay
from quantdesk.intraday.feeds import IST, ReplayFeed, normalise_bars, session_bounds
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal, _json, trade_to_dict


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


CAPITAL = 500000
HAND_OVER = dt.time(12, 20)


# ---- the book the morning runner leaves behind (C-05) ---------------------------------------------------------------
# These tests used to look for a position the desk had opened by itself, and skipped when there was none; with the plan
# model gate pinned (autolearn.require_approved_model) it never opens one, so they never ran. The position is built
# here instead, deterministically, the way tests/test_trading_path_b.py does, and everything after it (the restore, the
# reconciliation, the hand-over, the after-the-bell close, the kill switch) is the engine's own code. A missing
# position is a failure, never a skip.
def _rec(t):
    """A trade as it round-trips through the journal's JSON (tuples become lists, numpy scalars plain numbers)."""
    return json.loads(_json(trade_to_dict(t)))


def _book(eng):
    r = eng.risk
    return {"open": [_rec(t) for t in eng.open_trades], "closed": [_rec(t) for t in eng.closed],
            "day_start_equity": eng.day_start_equity, "trades_today": r.trades_today, "consec_losses": r.consec_losses,
            "halted": r.halted, "cool_until": r.cool_until}


def _new_engine(cfg, bars, day, tmp_path, clock=None, review_dir=None):
    """A new process on the same journal.db and broker.json (what `deploy/journal.sh restore` hands the next job)."""
    feed = ReplayFeed(bars, day)
    if clock is not None:
        feed.clock = clock
    return IntradayEngine(cfg, feed, "model", Journal(tmp_path / "j.db"),
                          IntradayBroker(cfg, starting_cash=CAPITAL, state_path=tmp_path / "broker.json"),
                          say=None, review_dir=review_dir)


def _hold(eng, feed, u):
    """Open a one-lot long call the way the playbook would (the desk is paused, so it opens nothing of its own)."""
    now = feed.now()
    ch, S = eng.chain_df[u], float(eng.chain_df[u].attrs["spot"])
    plan = eng.playbook._directional("orb", eng.views[u], ch, now, 1, "t", "t", S - 60, S + 400)
    assert plan is not None, f"no {u} plan to open at {now:%H:%M}"
    lots, notes = eng.risk.size(plan, eng.equity(now), eng.broker.cash())
    n = len(eng.open_trades)
    eng._open(plan, max(1, lots), notes, eng.views[u], eng._last_s[u], now)
    assert len(eng.open_trades) == n + 1, f"the {u} position did not open"
    return eng.open_trades[-1]


def _inert(t):
    """No stop, target or time exit can fire, so only the clock (15:15), the operator or the kill switch closes it."""
    t.stop = t.target = None
    t.meta.pop("range", None)
    t.exit_rules.update(premium_stop=1e9, premium_target=1e9, time_stop_min=9999)


def _build_book(cfg, bars, day, tmp_path, halted=True):
    """The morning runner up to 10:50: one trade opened and closed at a loss, one NIFTY call still open, risk state
    that is not the default (2 trades today, a loss streak, a cool-off, optionally the day halted), all on disk."""
    feed = ReplayFeed(bars, day)
    j = Journal(tmp_path / "j.db")
    eng = IntradayEngine(cfg, feed, "model", j, IntradayBroker(cfg, starting_cash=CAPITAL, state_path=tmp_path / "broker.json"),
                         say=None)
    eng.start_session(day)
    eng.paused = True
    for _ in range(90):                                                         # to 10:45
        feed.advance()
        eng.step()
    lost = _hold(eng, feed, "BANKNIFTY")
    eng._close(lost, feed.now(), "manual", "closed at a loss before the hand-over")
    assert lost.status == "closed" and lost.pnl < 0 and eng.risk.consec_losses == 1
    for _ in range(3):
        feed.advance()
        eng.step()
    held = _hold(eng, feed, "NIFTY")
    _inert(held)
    for _ in range(3):                                                          # marked a few minutes: mae/bars_held move
        feed.advance()
        eng.step()
    assert eng.open_trades == [held] and (held.mae, held.mfe) != (0.0, 0.0) and held.bars_held > 0
    eng.risk.halted = halted
    eng.risk.cool_until = pd.Timestamp(dt.datetime.combine(day, dt.time(13, 0)), tz=IST) if halted else None
    eng._persist()
    j.commit()
    assert eng.risk.trades_today == 2
    assert set(eng.broker.positions()) == {l.instrument.symbol for l in held.legs}
    book = _book(eng)
    j.close()
    return book, feed.now()


def _cash_identity(eng):
    """The broker's cash is the capital less every fill's cost and fee: nothing was dropped on the way to disk."""
    f = eng.journal.df("SELECT qty, price, fees FROM fills")
    assert len(f) > 0
    assert eng.broker.cash() == pytest.approx(CAPITAL - float((f["qty"] * f["price"]).sum()) - float(f["fees"].sum()), abs=0.01)


def _assert_restored(eng, want):
    """`eng` (a new process, already started) holds exactly what the previous runner left."""
    assert want["open"] and [t.id for t in eng.open_trades] == [r["id"] for r in want["open"]]
    assert [_rec(t) for t in eng.open_trades] == want["open"]                   # every field, not just the id
    assert [_rec(t) for t in eng.closed] == want["closed"]
    for t, r in zip(eng.open_trades, want["open"]):
        assert [(l.instrument.symbol, l.qty, l.entry_price) for l in t.legs] == \
               [(Instrument.from_dict(l["instrument"]).symbol, l["qty"], l["entry_price"]) for l in r["legs"]]
        assert t.exit_rules == r["exit_rules"] and (t.stop, t.target) == (r["stop"], r["target"])
        assert (t.mfe, t.mae, t.fees, t.units) == (r["mfe"], r["mae"], r["fees"], r["units"])
    assert eng.day_start_equity == pytest.approx(want["day_start_equity"])
    assert eng.risk.trades_today == want["trades_today"]
    assert (eng.risk.consec_losses, eng.risk.halted) == (want["consec_losses"], want["halted"])
    assert eng.risk.cool_until == want["cool_until"]
    assert eng.health["reconcile"] == {"ok": True, "positions": len(eng.broker.positions())}    # journal == broker
    assert {s: p["qty"] for s, p in eng.broker.positions().items()} == \
           {l.instrument.symbol: l.qty for t in eng.open_trades for l in t.legs}
    _cash_identity(eng)


def _check_restore(cfg, bars, day, tmp_path, clock, want):
    """Start a throwaway engine the way the next runner would and check what it picked up (then let go of the file)."""
    eng = _new_engine(cfg, bars, day, tmp_path, clock)
    eng.start_session(day)
    try:
        _assert_restored(eng, want)
    finally:
        eng.journal.close()


def _handover(cfg, bars, day, tmp_path, sim_clock, resume_at, want):
    """The runner that takes the morning's book and carries it to the 12:20 hand-over (run_live's own loop)."""
    _check_restore(cfg, bars, day, tmp_path, resume_at, want)
    a = _new_engine(cfg, bars, day, tmp_path, resume_at)
    sim_clock.append(a.feed)
    msg = run_live(a, HAND_OVER, handover=True)
    assert msg.startswith("handed over") and "1 open" in msg                     # still holding at the hand-over
    held = want["open"][0]["id"]
    assert [t.id for t in a.open_trades] == [held]
    assert not any(t.exit_reason == "square_off" for t in a.closed)             # nothing was squared off early
    assert a.feed.now().time() >= HAND_OVER and a.open_trades[0].bars_held > want["open"][0]["bars_held"]   # it was managed
    book = _book(a)
    a.journal.close()
    return a, book


def test_handover_resumes_the_session(cfg, sessions, tmp_path, sim_clock):
    bars, days = sessions
    day = days[-1]
    want, t_built = _build_book(cfg, bars, day, tmp_path)
    held = want["open"][0]["id"]
    done = {r["id"] for r in want["closed"]}
    a, mid = _handover(cfg, bars, day, tmp_path, sim_clock, t_built + pd.Timedelta(minutes=2), want)
    assert mid["trades_today"] == 2 and mid["halted"] and mid["cool_until"] == want["cool_until"]

    # the second runner: new process, same journal and broker state, starts a couple of minutes later
    _check_restore(cfg, bars, day, tmp_path, a.feed.now() + pd.Timedelta(minutes=2), mid)   # the hand-over itself restores
    feed_b = ReplayFeed(bars, day)
    feed_b.clock = a.feed.now() + pd.Timedelta(minutes=2)
    sim_clock[:] = [feed_b]
    b = IntradayEngine(cfg, feed_b, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=CAPITAL, state_path=tmp_path / "broker.json"), say=None,
                       review_dir=tmp_path / "rev")
    review = run_live(b)
    assert {t.id for t in b.closed} == {held} | done                            # both halves are in the day
    assert b.day_start_equity == pytest.approx(want["day_start_equity"])
    assert not b.open_trades and b.broker.positions() == {}
    t = next(x for x in b.closed if x.id == held)
    assert t.exit_reason == "square_off" and t.closed_at.time() >= dt.time(15, 15)   # managed to the 15:15 square-off
    assert t.mae <= mid["open"][0]["mae"] and t.mfe >= mid["open"][0]["mfe"]
    assert all(l.exit_price is not None for l in t.legs)
    assert b.risk.trades_today == 2 and b.risk.halted                           # the risk state carried through the day
    tr = Journal(tmp_path / "j.db").trades()
    day_tr = tr[tr["opened_at"].str.startswith(str(day))]
    assert (day_tr["status"] == "closed").all() and len(day_tr) == len(b.closed) == 2
    assert len(day_tr) <= cfg.get("intraday.risk.max_trades_per_day")
    for tid in {held} | done:
        assert tid in review                                                    # the review covers the whole day
    assert (tmp_path / "rev" / f"{day}.md").exists()
    assert b.broker.cash() == pytest.approx(CAPITAL + sum(x.pnl for x in b.closed), abs=0.01)   # fills, fees, P&L agree
    _cash_identity(b)


def test_handover_nobody_picked_up_is_closed_after_the_bell(cfg, sessions, tmp_path, sim_clock):
    bars, days = sessions
    day = days[-1]
    want, t_built = _build_book(cfg, bars, day, tmp_path)
    a, mid = _handover(cfg, bars, day, tmp_path, sim_clock, t_built + pd.Timedelta(minutes=2), want)
    held = mid["open"][0]["id"]
    late = session_bounds(day)[1] + pd.Timedelta(minutes=20)                    # nobody picked it up: the next job is late
    _check_restore(cfg, bars, day, tmp_path, late, mid)                         # the position is still there to find
    b = _new_engine(cfg, bars, day, tmp_path, late)
    review = run_live(b)
    assert "session review" in review and not b.open_trades
    t = next(x for x in b.closed if x.id == held)
    assert t.exit_reason == "square_off" and t.closed_at >= late and all(l.exit_price is not None for l in t.legs)
    assert b.broker.positions() == {}
    _cash_identity(b)
    assert b.broker.cash() == pytest.approx(CAPITAL + sum(x.pnl for x in b.closed), abs=0.01)
    tr = Journal(tmp_path / "j.db").trades()
    assert (tr["status"] == "closed").all() and set(tr["id"]) == {held} | {r["id"] for r in want["closed"]}
    assert Journal(tmp_path / "j.db").get_state("intraday_open")["ended"] is True
    # and once it's closed, a later run has nothing to do
    assert "is over" in run_live(_new_engine(cfg, bars, day, tmp_path, late))


def test_kill_switch_squares_off_at_current_prices(cfg, sessions, tmp_path, sim_clock):
    """The operator cancels the day's run (close_out): what is open is squared off now and the session is closed."""
    bars, days = sessions
    day = days[-1]
    want, t_built = _build_book(cfg, bars, day, tmp_path)
    a, mid = _handover(cfg, bars, day, tmp_path, sim_clock, t_built + pd.Timedelta(minutes=2), want)   # cancelled mid-run
    held = {r["id"] for r in mid["open"]}
    assert held
    b = _new_engine(cfg, bars, day, tmp_path, a.feed.now())
    close_out(b)
    tr = Journal(tmp_path / "j.db").trades().set_index("id")
    assert (tr.loc[list(held), "exit_reason"] == "manual").all() and (tr["status"] == "closed").all()
    assert b.chain_df                                                           # exits used a calibrated chain
    assert b.broker.positions() == {} and not b.open_trades
    _cash_identity(b)
    assert b.broker.cash() == pytest.approx(CAPITAL + sum(x.pnl for x in b.closed), abs=0.01)
    assert close_out(b) == "nothing open to close"
    # the operator changes their mind and restarts: the day resumes with its trades counted
    again = ReplayFeed(bars, day)
    again.clock = a.feed.now() + pd.Timedelta(minutes=30)
    sim_clock[:] = [again]
    c = IntradayEngine(cfg, again, "model", Journal(tmp_path / "j.db"),
                       IntradayBroker(cfg, starting_cash=CAPITAL, state_path=tmp_path / "broker.json"), say=None)
    run_live(c)
    assert c.day_start_equity == pytest.approx(want["day_start_equity"]) and held <= {t.id for t in c.closed}
    assert c.risk.trades_today == 2 and not c.open_trades


def test_kill_file_flattens_a_restored_position_and_stops_entries(cfg, sessions, tmp_path):
    """The KILL file dropped into the runtime directory while the afternoon runner holds the morning's position: it is
    flattened once, at the price of the last completed bar, and nothing new is opened while the file stays."""
    bars, days = sessions
    day = days[-1]
    want, t_built = _build_book(cfg, bars, day, tmp_path, halted=False)
    held = want["open"][0]["id"]
    b = _new_engine(cfg, bars, day, tmp_path, t_built + pd.Timedelta(minutes=2))
    b.start_session(day)
    _assert_restored(b, want)
    b.step()                                                                    # the afternoon runner's first minute
    assert [t.id for t in b.open_trades] == [held] and not b.killed
    b.kill_file.parent.mkdir(parents=True, exist_ok=True)
    b.kill_file.write_text("stop")
    b.feed.advance()
    b.step()
    assert b.killed and not b.open_trades and b.broker.positions() == {}
    t = next(x for x in b.closed if x.id == held)
    assert t.exit_reason == "kill_switch" and all(l.exit_price is not None for l in t.legs)
    # at today's price, not yesterday's close from the history: the last bar the engine had seen when the switch fired
    # (the switch is read at the top of the step, before the minute's new bar is polled) or the one just completed
    px = normalise_bars(bars["NIFTY"])["close"]
    seen = [float(px.loc[b.feed.now() - pd.Timedelta(minutes=m)]) for m in (1, 2)]
    assert t.exit_underlying == pytest.approx(seen[0]) or t.exit_underlying == pytest.approx(seen[1])
    assert t.closed_at == b.feed.now()
    _cash_identity(b)
    assert b.broker.cash() == pytest.approx(CAPITAL + sum(x.pnl for x in b.closed), abs=0.01)
    ev = b.journal.events(level="CRITICAL")
    assert ev["message"].str.contains("kill switch").sum() == 1                 # said once
    n_trades, n_today = len(b.journal.trades()), b.risk.trades_today
    calm = SimpleNamespace(vetoes=[])
    for _ in range(6):                                                          # the file stays: no entries, no second flatten
        b.feed.advance()
        b.step()
        assert "kill switch" in str(b._blocked("NIFTY", calm, b.feed.now()))
    assert not b.open_trades and len(b.journal.trades()) == n_trades and b.risk.trades_today == n_today
    assert b.journal.events(level="CRITICAL")["message"].str.contains("kill switch").sum() == 1
    b.kill_file.unlink()                                                        # cleared: said so, entries allowed again
    b.feed.advance()
    b.step()
    assert not b.killed and "kill switch" not in str(b._blocked("NIFTY", calm, b.feed.now()))
    assert b.journal.events(level="WARN")["message"].str.contains("kill switch cleared").any()


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
