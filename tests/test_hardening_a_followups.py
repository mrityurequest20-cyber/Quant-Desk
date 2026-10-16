"""Hardening A follow-ups (the independent review of #60): one exit attempt per moment, the fallback said on the record,
raw bars kept raw, and the cases #60 left untested (tick square-off, run_step failures, a partial book, the entry cutoff)."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.engine import run_step
from quantdesk.intraday.feeds import IST, normalise_bars
from quantdesk.intraday.recorder import SessionRecorder
from quantdesk.intraday.risk import IntradayRisk
from quantdesk.intraday.synthetic import simulate_sessions
from test_trading_path import Book, _engine, _open, _plan


@pytest.fixture(scope="module")
def sessions():
    days = [d.date() for d in TradingCalendar(Config.load(DEFAULT_CONFIG).holidays()).trading_days("2026-08-31", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days


@pytest.fixture
def cfg(tmp_path):
    return Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp_path / "runtime")},
                                                  "autolearn": {"require_approved_model": False}})


def at(d, hhmm):
    return pd.Timestamp(dt.datetime.combine(d, dt.time(*hhmm)), tz=IST)


def held_trade(eng, feed):
    """One open NIFTY trade that only the clock or a forced stop can close."""
    plan, S, now = _plan(eng, feed)
    _open(eng, plan, now)
    t = eng.open_trades[0]
    t.target = None
    t.exit_rules.update(time_stop_min=9999, premium_stop=50, premium_target=99)
    return t, S


def closes(eng):
    """Count the close orders that reach the broker; none of them fills (the exit stays stuck)."""
    sent = []
    eng.broker.execute = lambda order, ref, ts, atr=None: sent.append(order.instrument.symbol) or None
    return sent


# ---- 1. one exit attempt per moment, whoever reaches for it first ------------------------------------------------------
def test_manage_and_the_wall_clock_send_one_exit_in_the_same_step(cfg, sessions):
    """Past 15:15 with a stop already breached, `_manage` (first) and then `_wallclock_exits` both reached for the exit:
    the fresh exit `_manage` left stuck was sent again at once, because only `_retry_exit` was deduped."""
    eng, feed, d = _engine(cfg, sessions)
    t, S = held_trade(eng, feed)
    t.stop = S * 2                                        # long: the underlying is "through" it, so `_manage` exits
    sent = closes(eng)
    feed.clock = at(d, (15, 16))
    eng.step()
    assert sorted(sent) == sorted(l.instrument.symbol for l in t.legs), sent      # each leg once
    assert t in eng.open_trades and t.meta["exit_pending"][0] == "invalidation"


def test_a_stuck_exit_is_still_retried_on_the_next_moment(cfg, sessions):
    """The once-per-moment rule must not skip an exit that is needed: the next minute tries again and closes it."""
    eng, feed, d = _engine(cfg, sessions)
    t, S = held_trade(eng, feed)
    t.stop = S * 2
    real = eng.broker.execute
    sent = closes(eng)
    feed.clock = at(d, (15, 16))
    eng.step()
    assert len(sent) == len(t.legs) and t in eng.open_trades
    eng.broker.execute = real                             # the broker accepts again
    feed.clock = at(d, (15, 17))
    eng.step()
    assert not eng.open_trades and eng.closed[-1].exit_reason == "invalidation"


def test_tick_does_not_resend_the_exit_the_wall_clock_just_sent(cfg, sessions):
    """`tick` at the square-off ran `_wallclock_exits`, then (the exit still stuck) `_manage` on the same moment."""
    eng, feed, d = _engine(cfg, sessions)
    t, S = held_trade(eng, feed)
    t.stop = None
    sent = closes(eng)
    feed.has_ltp = True
    feed.ltp = lambda want: {u: S for u in want}
    feed.clock = at(d, (15, 15))
    eng.tick()
    assert sorted(sent) == sorted(l.instrument.symbol for l in t.legs), sent      # each leg once
    assert t in eng.open_trades and t.meta["exit_pending"][0] == "square_off"


# ---- 2. the fallback is said, once per outage ----------------------------------------------------------------------------
def test_a_down_real_chain_is_journaled_once_per_outage(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    book = Book(eng)
    eng.chains = book
    eng.refresh_min = 1

    def say():
        ev = eng.journal.events("2000-01-01")
        return [e for e in ev.to_dict("records") if e["category"] == "execution" and "on purpose" in e["message"]]

    real_chain = book.chain
    book.chain = lambda u, *a, **k: (_ for _ in ()).throw(RuntimeError("kotak 503"))   # the real chain is down: model stands in
    for _ in range(6):
        feed.advance()
        eng.step()
    seen = say()
    assert len(seen) == 2 and {e["message"].split(":")[0] for e in seen} == {"NIFTY", "BANKNIFTY"}    # one per index, not per minute
    assert all(e["level"] == "WARN" and "chain is down" in e["message"] and "fallback" in e["message"] for e in seen)
    book.chain = real_chain                               # it comes back (the desk retries a failed real chain every 15 min) ...
    for _ in range(16):
        feed.advance()
        eng.step()
    assert len(say()) == 2
    book.chain = lambda u, *a, **k: (_ for _ in ()).throw(RuntimeError("kotak 503"))   # ... and a second outage is said again
    for _ in range(3):
        feed.advance()
        eng.step()
    assert len(say()) == 4


def test_a_working_real_chain_says_nothing(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    eng.chains = Book(eng)
    eng.refresh_min = 1
    for _ in range(3):
        feed.advance()
        eng.step()
    assert not eng.fallback_since
    ev = eng.journal.events("2000-01-01")
    assert not [e for e in ev.to_dict("records") if "on purpose" in e["message"]]


# ---- 3. the recorder keeps what it recorded ------------------------------------------------------------------------------
def test_a_junk_row_on_disk_survives_a_later_record_bars(sessions, tmp_path):
    bars, days = sessions
    d = days[-1]
    b = bars["NIFTY"]
    day = b[b.index.date == d].iloc[:30]
    rec = SessionRecorder(tmp_path)
    rec.record_bars("NIFTY", day.iloc[:10])
    path = rec.day_dir(d) / "NIFTY_1m.csv"
    raw = pd.read_csv(path, index_col=0, parse_dates=True)
    raw.iloc[3, :4] = np.nan                              # a NaN minute and a zero minute, as Yahoo serves them
    raw.iloc[5, :4] = 0.0
    raw.to_csv(path, index_label="ts")
    rec.record_bars("NIFTY", day.iloc[10:20])
    rec.record_bars("NIFTY", day.iloc[20:30])
    out = pd.read_csv(path, index_col=0, parse_dates=True)
    assert len(out) == 30 and out.iloc[3, :4].isna().all() and (out.iloc[5, :4] == 0).all()
    clean = rec.load_bars(["NIFTY"])["NIFTY"]             # what the engine reads stays normalised
    assert len(clean) == 28 and (clean[["open", "high", "low", "close"]] > 0).all().all()
    assert clean.index.equals(normalise_bars(out).index)


# ---- 4. the cases #60 left untested --------------------------------------------------------------------------------------
def test_tick_squares_off_at_1515_when_the_bars_have_stopped(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    t, S = held_trade(eng, feed)
    t.stop = None
    feed.poll = lambda sym, since: None                   # no bar has come for a long while
    feed.has_ltp = True
    feed.ltp = lambda want: {}
    feed.clock = at(d, (15, 14))
    assert eng.tick() is False and t in eng.open_trades   # a minute early: nothing to do
    feed.clock = at(d, (15, 15))
    assert eng.tick() is True
    assert not eng.open_trades and eng.closed[-1].exit_reason == "square_off"


def test_a_failing_step_is_counted_and_the_third_in_a_row_is_safe_mode(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    t, S = held_trade(eng, feed)
    t.stop = None
    assert eng.max_step_failures == 3
    real = eng.step

    def boom():
        raise RuntimeError("step blew up")
    eng.step = boom
    assert run_step(eng) is False and run_step(eng) is False
    h = eng.health
    assert h["consecutive_failures"] == 2 and h["step_errors"] == 2 and not h["safe_mode"] and eng.open_trades
    eng.step = real
    run_step(eng)                                         # a good minute resets the run
    assert h["consecutive_failures"] == 0 and h["step_errors"] == 2
    eng.step = boom
    run_step(eng), run_step(eng)
    assert not h["safe_mode"]
    assert run_step(eng) is False                         # the third straight failure
    assert h["consecutive_failures"] == 3 and h["step_errors"] == 5 and "3 steps failed" in h["safe_mode"]
    assert not eng.open_trades and eng.closed[-1].exit_reason == "safe_mode"
    ev = eng.journal.events("2000-01-01").to_dict("records")
    assert sum(e["level"] == "ERROR" and e["category"] == "engine" for e in ev) == 5
    assert "halted: safe mode" in eng._blocked("NIFTY", type("V", (), {"vetoes": []})(), feed.now())


def test_run_step_square_off_survives_a_failing_step(cfg, sessions):
    """The failure path still runs the clock's exits: a step that raises at 15:16 must not leave the position open."""
    eng, feed, d = _engine(cfg, sessions)
    t, S = held_trade(eng, feed)
    t.stop = None
    eng.step = lambda: (_ for _ in ()).throw(RuntimeError("step blew up"))
    feed.clock = at(d, (15, 16))
    run_step(eng)
    assert not eng.open_trades and eng.closed[-1].exit_reason == "square_off"


def test_a_partial_live_book_is_refused(cfg, sessions):
    """A multi-leg plan where the book quotes only some legs (the rest have no two-sided quote) must not open at all."""
    eng, feed, d = _engine(cfg, sessions)
    plan, S, now = _plan(eng, feed)
    assert len(plan.legs) == 2
    eng.chains = Book(eng, lambda insts: {insts[0].symbol: (plan.legs[0].price - 0.05, plan.legs[0].price + 0.05)})   # one leg only
    msg = _open(eng, plan, now)
    missing = f"{plan.legs[1].strike:g}{plan.legs[1].right}"
    assert f"no two-sided quote on {missing} in the live book" in msg
    assert not eng.open_trades and not eng.broker.positions()
    eng.chains = Book(eng, lambda insts: {i.symbol: (l.price - 0.05, l.price + 0.05) for i, l in zip(insts, plan.legs)})
    assert _open(eng, plan, now).startswith("ENTER") and len(eng.open_trades) == 1      # every leg quoted: it opens


def test_nothing_opens_after_the_last_entry_time(cfg, sessions):
    r = IntradayRisk(cfg)
    r.reset(dt.date(2026, 9, 28), 500000.0)
    cut = r.no_after
    assert cut < r.square_off and cut == dt.time(14, 45)
    assert not r.gate(at(dt.date(2026, 9, 28), (14, 45)), 500000.0, [], "NIFTY")
    for hhmm in [(14, 46), (15, 0), (15, 10), (15, 14), (15, 15), (15, 20)]:
        assert any("outside entry window" in w for w in r.gate(at(dt.date(2026, 9, 28), hhmm), 500000.0, [], "NIFTY")), hhmm


def test_a_ready_plan_is_not_opened_in_the_minutes_before_the_square_off(cfg, sessions):
    """End to end: every minute scan hands the engine a valid plan; after 14:45 the engine must still open nothing."""
    eng, feed, d = _engine(cfg, sessions)
    feed.clock = at(d, (14, 45))
    eng.step()
    plan, S, now = _plan(eng, feed)
    eng.paused = False
    eng.playbook.scan = lambda *a, **k: [plan]
    for hhmm in [(14, 46), (14, 50), (15, 0), (15, 10), (15, 14)]:
        feed.clock = at(d, hhmm)
        eng.step()
        assert not eng.open_trades and not eng.closed, hhmm
        assert eng._blocked("NIFTY", eng.views["NIFTY"], feed.now()).startswith("standing aside: outside entry window")
    assert eng.risk.trades_today == 0
