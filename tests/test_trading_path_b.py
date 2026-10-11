"""Trading-path hardening B: four defects from the independent bug hunt (P1-4, P1-5, P2-2, P2-4), each reproduced
on an engine replaying synthetic sessions. Written before the first real Kotak session of the desk."""
import logging
from types import SimpleNamespace

import pandas as pd
import pytest

import quantdesk.intraday.engine as E
from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday import learning
from quantdesk.intraday.chains import ChainSource, ModelOptionChain
from quantdesk.intraday.engine import IntradayEngine, run_step
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.learning import Memory
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal


@pytest.fixture(scope="module")
def sessions():
    from quantdesk.config import DEFAULT_CONFIG, Config
    days = [d.date() for d in TradingCalendar(Config.load(DEFAULT_CONFIG).holidays()).trading_days("2026-08-31", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days


def desk(cfg, sessions, chains="model", minutes=60, memory=None):
    """An engine an hour into the last synthetic session, entries paused (the tests open what they need)."""
    bars, days = sessions
    feed = ReplayFeed(bars, days[-1])
    eng = IntradayEngine(cfg, feed, "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None, memory=memory)
    if chains != "model":
        eng.chains = chains(eng)
    eng.start_session(days[-1])
    eng.paused = True
    run_to(eng, feed, minutes)
    return eng, feed


def run_to(eng, feed, minutes, step=lambda e: e.step()):
    for _ in range(minutes):
        feed.advance()
        step(eng)


def a_plan(eng, feed, u="NIFTY", setup="orb", below=60):
    ch, S = eng.chain_df[u], float(eng.chain_df[u].attrs["spot"])
    return eng.playbook._directional(setup, eng.views[u], ch, feed.now(), 1, "t", "t", S - below, S + 400)


def open_trade(eng, feed, u="NIFTY", setup="orb", below=60):
    now, plan = feed.now(), a_plan(eng, feed, u, setup, below)
    lots, notes = eng.risk.size(plan, eng.equity(now), eng.broker.cash())
    eng._open(plan, lots, notes, eng.views[u], eng._last_s[u], now)
    t = eng.open_trades[-1]
    t.exit_rules.update(time_stop_min=9999)
    return t, plan


class Stub(ChainSource):
    """A 'real' chain (source kotak) built off the model chain; `fail` makes it raise."""
    name, refresh_min = "kotak", 1

    def __init__(self, eng, iv_scale=1.0):
        self.eng, self.fail, self.iv_scale = eng, False, iv_scale

    def expiries(self, u):
        return self.eng.model_chain.expiries(u, self.eng.day)

    def chain(self, u, expiry, spot=None, ts=None):
        if self.fail:
            raise RuntimeError("kotak 503")
        e = self.eng
        m = ModelOptionChain(e.cfg, e.cal, lambda uu, tt: (e.model_state(uu, tt)[0], e.model_state(uu, tt)[1] * self.iv_scale), e.pricer)
        ch = m.chain(u, expiry, spot=spot, ts=ts)
        ch.attrs["source"] = "kotak"
        return ch

    def live_quotes(self, insts):
        return {}


# ---- P1-4: the stale-chain guard ----------------------------------------------------------------------------------
def test_the_stale_chain_guard_fires_when_every_refresh_fails(cfg, sessions, monkeypatch):
    """chain_stale_min: 12 compared now with the time of the last ATTEMPT, so a chain whose refresh raised every
    minute for 25 minutes (data 27 minutes old) never vetoed an entry."""
    eng, feed = desk(cfg, sessions, chains=lambda e: Stub(e))
    assert eng.chain_df["NIFTY"].attrs["source"] == "kotak"
    eng.paused = False
    calm = SimpleNamespace(vetoes=[])
    assert "option chain" not in str(eng._blocked("NIFTY", calm, feed.now()))
    monkeypatch.setattr(E, "fill_iv", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad chain")))
    run_to(eng, feed, 25)
    data_age = feed.now() - eng.chain_df["NIFTY"].attrs["ts"]
    assert data_age > pd.Timedelta(minutes=eng.stale_min)
    why = eng._blocked("NIFTY", calm, feed.now())
    assert why and why.startswith("standing aside: option chain") and "min old" in why


def test_the_marks_are_calibrated_before_the_optional_analytics(cfg, sessions, monkeypatch):
    """An error in the chain analytics left the marker on the previous chain's IV although chain_df was the new one."""
    eng, feed = desk(cfg, sessions, chains=lambda e: Stub(e))
    seen = []
    real = eng.marker.calibrate
    monkeypatch.setattr(eng.marker, "calibrate", lambda ch, lot: (seen.append(ch.attrs["ts"]), real(ch, lot))[1])
    monkeypatch.setattr(E, "chain_analytics", lambda *a, **k: (_ for _ in ()).throw(ValueError("analytics broke")))
    run_to(eng, feed, 1)
    assert seen and seen[-1] == eng.chain_df["NIFTY"].attrs["ts"]


# ---- P1-5: the setup stand-aside rule ------------------------------------------------------------------------------
def losing_record():
    m = Memory()
    for _ in range(10):                                                  # ten losses of 1R: the old rule stands it aside
        m.bump("setup", "orb", False, -1.0)
    return m


def test_a_losing_setup_record_is_recorded_not_applied_by_default(cfg, sessions):
    """The stand-aside rule was an absorbing state (no trades, so no way to recover). D-01: the setup record follows
    the factor record: shown, not applied, unless intraday.learning.apply_factor_weights."""
    eng, feed = desk(cfg, sessions, memory=losing_record())
    assert not eng.analyst.apply_learned
    plan = a_plan(eng, feed)
    conv = plan.conviction
    kept, stop = eng._by_record("NIFTY", [plan], eng.views["NIFTY"], feed.now())
    assert kept == [plan] and stop is None and plan.conviction == conv
    assert eng.memory.setup_mult("orb", "trend", applied=False) == (1.0, None)
    assert eng.memory.setup_mult("orb", "trend")[0] == 0.0               # the record itself still says so
    good = Memory()
    for _ in range(12):
        good.bump("setup", "orb", True, 2.0)
    assert good.setup_mult("orb", None, applied=False) == (1.0, None)    # and no multiplier either way


def test_a_losing_setup_record_still_stands_it_aside_with_the_switch_on(cfg, sessions):
    on = cfg.with_overrides({"intraday": {"learning": {"apply_factor_weights": True}}})
    eng, feed = desk(on, sessions, memory=losing_record())
    assert eng.analyst.apply_learned
    plan = a_plan(eng, feed)
    kept, stop = eng._by_record("NIFTY", [plan], eng.views["NIFTY"], feed.now())
    assert kept == [] and "its record says no" in stop


def test_the_review_marks_the_setup_record_recorded_not_applied():
    lines = learning.summary(losing_record())
    s = [x for x in lines if x.startswith("setup orb")]
    assert s and "stand aside" in s[0] and s[0].endswith("(recorded, not applied)")
    lines = learning.summary(losing_record(), factor_weights_applied=True)
    assert not any("not applied" in x for x in lines if x.startswith("setup "))


# ---- P2-2: one index's failure, and exits behind network I/O --------------------------------------------------------
def breached(eng, feed, u="BANKNIFTY"):
    t, _ = open_trade(eng, feed, u)
    S = float(eng.chain_df[u].attrs["spot"])
    t.stop = S + 500                                                      # the invalidation is already through
    return t


def test_one_indexs_failure_does_not_leave_the_others_stop_unmanaged(cfg, sessions, monkeypatch):
    logging.disable(logging.CRITICAL)
    try:
        eng, feed = desk(cfg, sessions)
        breached(eng, feed)
        real = eng.analyst.assess

        def bad(sym, *a, **k):
            if sym == "NIFTY":
                raise ZeroDivisionError("float division by zero")
            return real(sym, *a, **k)
        monkeypatch.setattr(eng.analyst, "assess", bad)
        run_to(eng, feed, 1, run_step)
        assert not eng.open_trades and [c.exit_reason for c in eng.closed] == ["invalidation"]
        assert not eng.health["safe_mode"] and eng.health["consecutive_failures"] == 1     # counted, not swallowed
        warn = eng.journal.df("SELECT * FROM events WHERE level='WARN' AND message LIKE 'NIFTY: this minute%'")
        assert len(warn) == 1
    finally:
        logging.disable(logging.NOTSET)


def test_the_other_index_still_thinks_and_the_square_off_still_runs_when_one_fails(cfg, sessions, monkeypatch):
    logging.disable(logging.CRITICAL)
    try:
        eng, feed = desk(cfg, sessions)
        real = eng.analyst.assess
        monkeypatch.setattr(eng.analyst, "assess", lambda sym, *a, **k: (_ for _ in ()).throw(KeyError(sym)) if sym == "NIFTY"
                            else real(sym, *a, **k))
        before = eng.views["BANKNIFTY"].ts
        t, _ = open_trade(eng, feed, "BANKNIFTY")
        feed.advance()
        monkeypatch.setattr(eng.risk, "square_off", feed.now().time())    # the day ends this minute
        with pytest.raises(KeyError):                                     # the failure is still raised for run_step to count
            eng.step()
        assert eng.views["BANKNIFTY"].ts > before                         # BANKNIFTY was assessed after NIFTY failed
        assert not eng.open_trades and eng.closed[-1].exit_reason == "square_off"
    finally:
        logging.disable(logging.NOTSET)


def test_the_square_off_runs_even_when_the_optional_refreshes_raise(cfg, sessions, monkeypatch):
    logging.disable(logging.CRITICAL)
    try:
        eng, feed = desk(cfg, sessions)
        open_trade(eng, feed, "BANKNIFTY")
        feed.advance()
        monkeypatch.setattr(eng.risk, "square_off", feed.now().time())
        monkeypatch.setattr(eng, "_short_legs", lambda now: 1 / 0)       # whatever raises between the exits and the loop
        with pytest.raises(ZeroDivisionError):
            eng.step()
        assert not eng.open_trades and eng.closed[-1].exit_reason == "square_off"
    finally:
        logging.disable(logging.NOTSET)


def test_a_persistent_failure_still_ends_in_safe_mode(cfg, sessions, monkeypatch):
    logging.disable(logging.CRITICAL)
    try:
        eng, feed = desk(cfg, sessions)
        monkeypatch.setattr(eng.analyst, "assess", lambda *a, **k: (_ for _ in ()).throw(ZeroDivisionError("x")))
        run_to(eng, feed, eng.max_step_failures - 1, run_step)
        assert not eng.health["safe_mode"]
        run_to(eng, feed, 1, run_step)
        assert eng.health["safe_mode"] and eng.health["consecutive_failures"] == eng.max_step_failures
    finally:
        logging.disable(logging.NOTSET)


def test_exits_run_before_the_optional_network_refreshes(cfg, sessions, monkeypatch):
    """Steps of 51 s and 65 s were logged: news, global, heavyweights and breadth refreshed before `_manage`."""
    eng, feed = desk(cfg, sessions)
    breached(eng, feed, "NIFTY")
    order = []
    real = eng._refresh_news
    monkeypatch.setattr(eng, "_refresh_news", lambda now: (order.append(("news", len(eng.open_trades))), real(now))[1])
    run_to(eng, feed, 1)
    assert order == [("news", 0)] and eng.closed[-1].exit_reason == "invalidation"
    assert "invalidation" in eng.last_action["NIFTY"]                    # the exit is still narrated by the loop


# ---- P2-4: the model-chain fallback and the marks ------------------------------------------------------------------
def test_the_model_chain_fallback_does_not_recalibrate_open_marks(cfg, sessions):
    """A Kotak failure moved a held option's mark by ~4% of premium in a minute: the model chain's (India VIX) IV
    replaced the quote-implied IV the position was marked on."""
    eng, feed = desk(cfg, sessions, chains=lambda e: Stub(e, iv_scale=0.75))
    t, _ = open_trade(eng, feed)
    syms = [l.instrument.symbol for l in t.legs]
    run_to(eng, feed, 1)
    assert eng.chain_df["NIFTY"].attrs["source"] == "kotak"
    iv_real = {s: eng.marker.iv[s] for s in syms}
    eng.chains.fail = True
    run_to(eng, feed, 3)
    assert eng.chain_df["NIFTY"].attrs["source"] == "model"
    assert {s: eng.marker.iv[s] for s in syms} == iv_real                # marks stay on the last real quotes' IV


def test_a_replay_on_the_model_chain_still_calibrates_its_marks(cfg, sessions):
    eng, feed = desk(cfg, sessions, minutes=2)
    assert eng.chains is eng.model_chain and eng.marker.iv                # the replay's model chain is the market
