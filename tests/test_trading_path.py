"""Order-safety guards on the intraday trading path (independent bug hunt, Oct 2026): the 15:15 square-off runs on the
clock when no bars arrive, no entry on a real book without a two-sided quote, no stop on the wrong side of the entry,
risk.gate fails closed on NaN equity, and NaN/zero-priced Yahoo minutes never reach the features."""
import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.analyst import MarketView
from quantdesk.intraday.chains import ChainSource
from quantdesk.intraday.engine import IntradayEngine
from quantdesk.intraday.feeds import IST, ReplayFeed, normalise_bars
from quantdesk.intraday.features import session_state
from quantdesk.intraday.risk import IntradayRisk
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal


@pytest.fixture(scope="module")
def sessions():
    days = [d.date() for d in TradingCalendar(Config.load(DEFAULT_CONFIG).holidays()).trading_days("2026-08-31", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days


@pytest.fixture
def cfg(tmp_path):
    return Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp_path / "runtime")},
                                                  "autolearn": {"require_approved_model": False}})


def _engine(cfg, sessions, minutes=60):
    """A paused engine an hour into the last session, with one long NIFTY plan ready to open."""
    bars, days = sessions
    d = days[-1]
    feed = ReplayFeed(bars, d)
    eng = IntradayEngine(cfg, feed, "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    eng.start_session(d)
    eng.paused = True                                     # no automatic entries
    for _ in range(minutes):
        feed.advance()
        eng.step()
    return eng, feed, d


def _plan(eng, feed, direction=1, inval=None, target=None):
    ch, now = eng.chain_df["NIFTY"], feed.now()
    S = float(ch.attrs["spot"])
    plan = eng.playbook._directional("orb", eng.views["NIFTY"], ch, now, direction, "t", "t",
                                     S - 60 if inval is None else inval, S + 400 if target is None else target)
    return plan, S, now


def _open(eng, plan, now):
    lots, notes = eng.risk.size(plan, eng.equity(now), eng.broker.cash())
    return eng._open(plan, lots, notes, eng.views["NIFTY"], eng._last_s["NIFTY"], now)


# ---- P1-2: the square-off is the clock's, not the next bar's ----------------------------------------------------------
def test_square_off_runs_when_no_bars_arrive(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    plan, S, now = _plan(eng, feed)
    _open(eng, plan, now)
    t = eng.open_trades[0]
    t.stop = t.target = None                              # only the clock can close it
    t.exit_rules.update(time_stop_min=9999, premium_stop=50, premium_target=99)
    cut = pd.Timestamp(dt.datetime.combine(d, dt.time(14, 50)), tz=IST)
    orig = feed.poll
    feed.poll = lambda sym, since: (lambda r: r[r.index < cut] if r is not None else r)(orig(sym, since))   # the polls dry up
    while feed.clock < pd.Timestamp(dt.datetime.combine(d, dt.time(15, 20)), tz=IST):
        feed.advance()
        eng.step()
    assert not eng.open_trades, "still open at 15:20 with no bars: the 15:15 square-off was skipped"
    assert eng.closed[-1].exit_reason == "square_off" and eng.closed[-1].closed_at.time() < dt.time(15, 20)


def test_stuck_exit_is_retried_when_no_bars_arrive(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    plan, S, now = _plan(eng, feed)
    _open(eng, plan, now)
    t = eng.open_trades[0]
    t.meta["exit_pending"] = ["premium_stop", "a stuck exit"]    # an earlier attempt did not fill
    feed.poll = lambda sym, since: None
    feed.advance()
    assert eng.step() is False
    assert not eng.open_trades and eng.closed[-1].exit_reason == "premium_stop"


# ---- P1-3: no two-sided quote on a real book, no entry ----------------------------------------------------------------
class Book(ChainSource):
    """A Kotak-like source over the model chain, whose live book answers with `quotes` (default: nothing)."""
    name, book, refresh_min = "kotak", True, 1

    def __init__(self, eng, quotes=None):
        self.eng, self.quotes = eng, quotes

    def expiries(self, u):
        return self.eng.model_chain.expiries(u, self.eng.day)

    def chain(self, u, expiry, spot=None, ts=None):
        ch = self.eng.model_chain.chain(u, expiry, spot=spot, ts=ts)
        ch.attrs["source"] = "kotak"
        return ch

    def live_quotes(self, insts):
        return {} if self.quotes is None else self.quotes(insts)


def test_empty_live_book_blocks_the_entry(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    plan, S, now = _plan(eng, feed)
    eng.chains = Book(eng)                                # the book answers with nothing
    msg = _open(eng, plan, now)
    assert "no two-sided quote" in msg and not eng.open_trades
    assert eng.journal.df("SELECT * FROM decisions").astype(str).apply(lambda r: r.str.contains("no two-sided quote")).any(axis=1).any()


def test_model_chain_without_a_book_still_enters(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    plan, S, now = _plan(eng, feed)
    assert eng.chains is eng.model_chain                  # no book exists to consult
    assert _open(eng, plan, now).startswith("ENTER") and len(eng.open_trades) == 1


def test_strike_picker_needs_a_two_sided_quote_on_a_real_book(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    ch = eng.chain_df["NIFTY"].copy()
    ch["ce_bid"] = np.nan                                 # LTP only, no bid: not tradable on a real book
    ch.attrs["source"] = "kotak"
    assert eng.playbook.picker.rows(ch, "CE", feed.now()).empty
    assert not eng.playbook.picker.rows(ch, "PE", feed.now()).empty
    ch.attrs["source"] = "model"                          # no book to consult: LTP pricing as before
    assert not eng.playbook.picker.rows(ch, "CE", feed.now()).empty


# ---- P1-6: a stop on the wrong side of the entry ----------------------------------------------------------------------
def test_directional_plan_refuses_a_stop_on_the_wrong_side(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    S = float(eng.chain_df["NIFTY"].attrs["spot"])
    assert _plan(eng, feed, +1, inval=S + 90, target=S + 400)[0] is None      # long, stop above the entry
    assert _plan(eng, feed, -1, inval=S - 90, target=S - 400)[0] is None      # short, stop below it
    assert _plan(eng, feed, +1, inval=float("nan"), target=S + 400)[0] is None
    assert _plan(eng, feed, +1, inval=S - 90, target=S + 400)[0] is not None
    assert _plan(eng, feed, -1, inval=S + 90, target=S - 400)[0] is not None


def test_orb_with_vwap_above_spot_makes_no_plan(cfg, sessions):
    eng, feed, d = _engine(cfg, sessions)
    ch, now = eng.chain_df["NIFTY"], feed.now()
    S = float(ch.attrs["spot"])
    v = MarketView("NIFTY", now, S, "bullish", 0.6, 0.7, "trend", "fair", 13.0, 11.0, [], [], {}, "", {"atr5": 20.0})
    s = {"last": S, "last5_close": S, "or_done": True, "minutes": 60, "or_high": S - 5, "or_low": S - 120, "prev5_high": S - 8,
         "prev5_low": S - 30, "vwap": S + 90, "rel_volume": 1.0, "atr5": 20.0}      # VWAP above spot: max(mid_or, vwap) > entry
    assert eng.playbook.orb(v, s, ch, now) is None


# ---- P2-3: risk.gate on NaN equity -------------------------------------------------------------------------------------
def test_gate_fails_closed_on_nan_equity(cfg):
    r = IntradayRisk(cfg)
    r.reset(dt.date(2026, 10, 12), 500000.0)
    now = pd.Timestamp("2026-10-12 11:00:04", tz=IST)
    assert r.gate(now, 500000.0, [], "NIFTY") == []
    assert r.gate(now, float("nan"), [], "NIFTY") == ["equity unknown"]
    assert r.gate(now, float("inf"), [], "NIFTY") == ["equity unknown"]
    assert any("daily loss" in w for w in r.gate(now, 470000.0, [], "NIFTY")) and r.halted
    r.reset(dt.date(2026, 10, 12), float("nan"))          # an unknown starting equity can't pass the drawdown test either
    assert r.gate(now, 500000.0, [], "NIFTY")


# ---- P2-1: NaN / zero-priced Yahoo minutes -----------------------------------------------------------------------------
def test_normalise_bars_drops_nan_and_zero_priced_minutes(sessions):
    bars, days = sessions
    d = days[-1]
    b = bars["NIFTY"]
    day = b[b.index.date == d].iloc[:120].copy()
    bad = day.copy()
    bad.iloc[30, :4] = np.nan
    bad.iloc[60, :4] = 0.0
    bad.iloc[90, 3] = 0.0                                 # a zero close alone
    out = normalise_bars(bad)
    assert len(out) == len(day) - 3 and (out[["open", "high", "low", "close"]] > 0).all().all()
    now = out.index[-1] + pd.Timedelta(minutes=1)
    s = session_state(pd.concat([b[b.index.date < d], out]), now)
    assert np.isfinite(s["vwap"]) and np.isfinite(s["day_high"]) and np.isfinite(s["day_low"])
