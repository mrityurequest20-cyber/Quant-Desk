"""The ungated plan path, the one that is live today.

Owner decision #36 set `autolearn.require_approved_model: false` on main: a directional plan no longer needs an approved
plan model to trade, so it meets the EV layer and every other gate directly. Commit 86b535e pinned the older tests to the
gated desk, which left this path without a dedicated test. These tests run the REAL config (only the runtime dir is
redirected), a deterministic synthetic session (seed 5, an hour in: a bearish read, so a put is the plan with the read and
a call the plan against it), and pin that nothing but the model gate is off:

  1. an ungated directional plan is evaluated by EV, not refused by a model gate;
  2. the EV floor (min_ev_inr, min_ev_r) and the global-stress size multiplier still apply;
  3. the risk gate (trades a day, open positions, daily loss + the C-06 sizing cap, total outlay, risk per trade) applies;
  4. liquidity and slippage (two-sided quote, the live book moving away) apply;
  5. the armed-order path goes through the same gates;
  6. a plan-registry fault halts entries only when the plan model is required (P2-7).

Every test states what production change would make it fail ("fails if ...")."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from test_trading_path_b import Stub, desk, open_trade

from quantdesk.autolearn.live import LiveLearner
from quantdesk.autolearn.registry import Registry
from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday.engine import IntradayEngine, run_replay
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.playbook import Armed
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal

GATE_WORDS = "no approved plan model"                 # the gated desk's refusal, word for word (live.py / engine.py)


@pytest.fixture(scope="module")
def sessions():
    days = [d.date() for d in TradingCalendar(Config.load(DEFAULT_CONFIG).holidays()).trading_days("2026-08-31", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days


def make_cfg(tmp_path, required=False, over=None):
    """The shipped config, in memory: only the runtime dir moves; `required` is the one switch this file is about."""
    o = {"runtime": {"dir": str(tmp_path / "runtime")}}
    if required is not None:
        o["autolearn"] = {"require_approved_model": required}
    cfg = Config.load(DEFAULT_CONFIG, overrides=o)
    return cfg.with_overrides(over) if over else cfg


@pytest.fixture
def cfg(tmp_path):
    return make_cfg(tmp_path, required=None)           # untouched: whatever main ships


def live_desk(cfg, sessions, chains="model", minutes=60):
    """desk() of test_trading_path_b (an hour into the last synthetic session), with entries switched back on."""
    eng, feed = desk(cfg, sessions, chains=chains, minutes=minutes)
    eng.paused = False
    return eng, feed


def plans(eng, now, direction=-1):
    """A directional orb plan from the live chain: direction -1 is a put (with the bearish read), +1 a call (against it)."""
    S = float(eng.chain_df["NIFTY"].attrs["spot"])
    p = eng.playbook._directional("orb", eng.views["NIFTY"], eng.chain_df["NIFTY"], now, direction, "t", "t",
                                  S + 60 * -direction, S + 400 * direction)
    assert p is not None and p.direction == direction
    return p


def enter(eng, feed, direction=-1, u="NIFTY"):
    """One pass of the real entry path (_maybe_enter: _blocked, gates, EV, sizing, _open) on a scanned plan."""
    now = feed.now()
    plan = plans(eng, now, direction)
    eng.playbook.scan = lambda *a, **k: [plan]
    return eng._maybe_enter(u, eng.views[u], eng._last_s[u], now), plan


def rejected(eng):
    d = eng.journal.decisions()
    return d[d["action"] == "rejected"]


def one_book(eng, ask_mult=1.0, bid_mult=1.0, drop=()):
    """The Stub chain's two-sided book, distorted: asks and bids scaled, some strikes dropped (no quote)."""
    real = eng.chains.live_quotes

    def live_quotes(insts):
        return {s: (b * bid_mult, a * ask_mult) for s, (b, a) in real(insts).items() if not any(d in s for d in drop)}
    eng.chains.live_quotes = live_quotes


# ---- 0. the config this file is about -------------------------------------------------------------------------------
def test_main_ships_ungated_and_no_limit_is_looser_than_the_owner_set(tmp_path):
    """Fails if main's require_approved_model flips (this file then tests a path that is no longer the live one) or if a
    risk / EV limit is loosened: the limits are pinned from above, a tightening is fine."""
    shipped = Config.load(DEFAULT_CONFIG)
    assert shipped.get("autolearn.require_approved_model") is False
    eng = IntradayEngine(make_cfg(tmp_path, required=None), ReplayFeed(*_one_day()), "model", Journal(),
                         IntradayBroker(make_cfg(tmp_path, required=None), starting_cash=500000), say=None)
    assert eng.require_model is False and LiveLearner(make_cfg(tmp_path, required=None), root=tmp_path / "al").require_model is False
    r = eng.risk
    assert (r.max_trades, r.max_open, r.daily_loss, r.max_exposure, r.risk_per_trade) == (4, 2, 0.05, 0.5, 0.025)
    assert eng.qc["min_ev_inr"] >= 40 and eng.qc["min_ev_r"] >= 0.05 and eng.max_entry_slip <= 0.15
    assert shipped.get("account.mode") == "paper"                           # live trading stays off


def _one_day():
    cal = TradingCalendar(Config.load(DEFAULT_CONFIG).holidays())
    days = [d.date() for d in cal.trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days[-1]


# ---- 1. an ungated directional plan is judged by EV, not by a model gate --------------------------------------------
def test_an_ungated_plan_with_no_model_and_no_champion_is_decided_by_ev(cfg, sessions):
    """Fails if `_model_gates` drops directional plans although require_approved_model is false (e.g. the
    `if self.require_model:` guard is removed), or if the EV layer is bypassed on this path."""
    eng, feed = live_desk(cfg, sessions)
    assert eng.learner is None and eng.require_model is False
    plan = plans(eng, feed.now())
    kept, why = eng._model_gates("NIFTY", [plan], feed.now())
    assert kept == [plan] and why is None
    msg, _ = enter(eng, feed, -1)
    assert msg.startswith("ENTER") and GATE_WORDS not in msg
    t = eng.open_trades[0]
    assert t.direction == -1 and "plan_model" not in t.meta and t.meta.get("mode") != "exploration"
    assert "Quant: EV" in t.rationale and t.meta["quant"]["ev"] > 0 and "P(up)" in t.meta["quant_text"]   # priced by Monte Carlo
    assert not eng.journal.decisions().astype(str).apply(lambda c: c.str.contains(GATE_WORDS)).any(axis=None)


def test_a_plan_against_the_read_is_refused_by_ev_with_the_ev_reason_not_a_model_reason(cfg, sessions):
    """Fails if the EV layer stops refusing negative-EV plans or if the refusal is worded/recorded by a model gate."""
    eng, feed = live_desk(cfg, sessions)
    msg, _ = enter(eng, feed, +1)                                           # a call into a bearish read
    assert "not worth it after costs" in msg and GATE_WORDS not in msg and not eng.open_trades
    r = rejected(eng)
    assert len(r) == 1 and r["detail"].iloc[0].startswith("EV below the floor") and r["units"].iloc[0] == 0
    assert eng.risk.trades_today == 0


def test_a_learner_with_no_plan_champion_does_not_gate_either(cfg, sessions, tmp_path):
    """The live desk has a LiveLearner and (today) no approved plan model: plan_gate must pass the plan through
    untouched. Fails if plan_gate (or `_model_gates`) gates on `self.plan is None` without checking require_model."""
    eng, feed = live_desk(cfg, sessions)
    eng.learner = LiveLearner(cfg, root=tmp_path / "al", source="replay")
    eng.learner.start(feed.now().date())
    assert eng.learner.plan is None and eng.learner.fault is None and not eng.learner.active
    plan = plans(eng, feed.now())
    assert eng.learner.plan_gate("NIFTY", [plan], feed.now()) == ([plan], None)
    msg, _ = enter(eng, feed, -1)
    assert msg.startswith("ENTER") and len(eng.open_trades) == 1


def test_the_gated_twin_refuses_the_same_plan_at_the_model_gate(tmp_path, sessions):
    """The control for the two tests above: with the switch on, the very same plan is refused at the model gate, so
    they do pass because of the switch. Fails if require_approved_model stops gating."""
    eng, feed = live_desk(make_cfg(tmp_path, required=True), sessions)
    msg, _ = enter(eng, feed, -1)
    assert GATE_WORDS in msg and not eng.open_trades


def test_a_whole_ungated_session_trades_directionally_on_ev_alone(cfg, sessions, tmp_path):
    """Replays the last synthetic session end to end. Fails if directional trades stop happening ungated, if an opened
    trade did not pass the EV layer, or if the ungated desk breaches the 4-trades-a-day cap."""
    bars, days = sessions
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    run_replay(eng)
    tr = eng.journal.trades()
    assert 1 <= len(tr) <= 4
    assert (tr["direction"] != 0).any()
    assert tr["rationale"].str.contains("Quant: EV").all()                    # each went through _select_by_ev
    assert not eng.journal.decisions().astype(str).apply(lambda c: c.str.contains(GATE_WORDS)).any(axis=None)


# ---- 2. the EV floor and the volatility-targeting multiplier still apply --------------------------------------------
def _ev_of_the_pick(sessions, tmp_path, over=None, direction=-1):
    eng, feed = live_desk(make_cfg(tmp_path, required=False, over=over), sessions)
    now = feed.now()
    plan = plans(eng, now, direction)
    return eng, now, plan, eng._select_by_ev("NIFTY", [plan], eng.views["NIFTY"], eng.equity(now), now)


def test_the_rupee_floor_and_the_r_floor_each_refuse_an_otherwise_passing_candidate(sessions, tmp_path):
    """Fails if `_select_by_ev` ignores min_ev_inr or min_ev_r (e.g. the floor is `max(...)` replaced by one arm, or the
    comparison is dropped). The thresholds are set just above the winner's own EV, so only the floor can refuse it."""
    _, _, _, pick = _ev_of_the_pick(sessions, tmp_path / "base")
    assert not isinstance(pick, str)                                        # control: the shipped floors let it through
    ev, ev_r = pick[0].notes["quant"]["ev"], pick[0].notes["quant"]["ev_r"]
    assert ev > 40 and ev_r > 0.05                                          # ...by clearing both shipped floors
    for name, over in (("rupee", {"intraday": {"quant": {"min_ev_inr": ev + 1_000}}}),
                       ("R", {"intraday": {"quant": {"min_ev_r": ev_r + 1.0}}})):
        eng, now, plan, got = _ev_of_the_pick(sessions, tmp_path / name, over)
        assert isinstance(got, str) and "not worth it after costs" in got, name
        row = rejected(eng).iloc[-1]
        assert row["detail"].startswith("EV below the floor") and row["units"] == 0


def test_a_candidate_below_the_floor_never_reaches_the_broker(cfg, sessions):
    """End to end through `_maybe_enter` on the real floor: the refusal comes with the EV figure and nothing is filled.
    Fails if a sub-floor plan is opened (floor bypass) or sizing runs before the floor decides."""
    eng, feed = live_desk(cfg, sessions)
    cash0 = eng.broker.cash()
    msg, _ = enter(eng, feed, +1)
    assert "EV ₹-" in msg and not eng.open_trades and eng.broker.cash() == cash0 and eng.journal.df("SELECT * FROM fills").empty


def test_global_stress_scales_the_size_down_and_can_stand_the_desk_aside(sessions, tmp_path):
    """Volatility targeting (~1453): size x multiplier, rounded; a multiplier that rounds to no lot stands aside. Fails if
    the multiplier is ignored (full size under stress) or if a zero-lot result still opens."""
    _, _, _, base = _ev_of_the_pick(sessions, tmp_path / "a")
    lots0 = base[1]
    assert lots0 >= 2
    eng, now, plan, _ = _ev_of_the_pick(sessions, tmp_path / "b")
    eng.brain_state["NIFTY"] = SimpleNamespace(size_mult=0.5, stress=4.0)
    scaled = eng._select_by_ev("NIFTY", [plans(eng, now)], eng.views["NIFTY"], eng.equity(now), now)
    assert scaled[1] == int(lots0 * 0.5 + 0.49) < lots0 and any("global stress" in n for n in scaled[2])
    eng.brain_state["NIFTY"] = SimpleNamespace(size_mult=0.01, stress=9.0)
    msg = eng._select_by_ev("NIFTY", [plans(eng, now)], eng.views["NIFTY"], eng.equity(now), now)
    assert isinstance(msg, str) and "global stress" in msg and "standing aside" in msg
    assert rejected(eng).iloc[-1]["units"] == 0


# ---- 3. the risk gate still applies ---------------------------------------------------------------------------------
def test_max_trades_per_day_refuses_an_otherwise_good_plan(cfg, sessions):
    """Fails if the trades/day cap is not enforced on the ungated path (RISK gate dropped from `_blocked`, or the cap
    raised above 4)."""
    eng, feed = live_desk(cfg, sessions)
    assert eng.risk.max_trades == 4
    eng.risk.trades_today = 3
    msg, _ = enter(eng, feed, -1)                                            # the 4th is allowed ...
    assert msg.startswith("ENTER") and eng.risk.trades_today == 4
    eng.open_trades.clear()
    msg, _ = enter(eng, feed, -1)                                            # ... the 5th is not (nothing else changed)
    assert "4 trades already today" in msg and not eng.open_trades


def test_max_open_positions_refuses_an_otherwise_good_plan(cfg, sessions):
    """Fails if `max_open` (2) is not enforced: with BANKNIFTY open NIFTY may enter (control); with both open, a further
    entry is refused with the open-positions reason first."""
    eng, feed = live_desk(cfg, sessions)
    assert eng.risk.max_open == 2
    open_trade(eng, feed, "BANKNIFTY")
    msg, _ = enter(eng, feed, -1)
    assert msg.startswith("ENTER") and len(eng.open_trades) == 2
    eng.risk.trades_today = 0                                                # isolate the open-positions cap from the day's count
    why = eng._blocked("NIFTY", eng.views["NIFTY"], feed.now())
    assert why == "standing aside: 2 positions already open"
    assert any("2 positions already open" in w for w in eng.risk.gate(feed.now(), eng.equity(feed.now()), eng.open_trades, "NIFTY"))


def test_the_daily_loss_limit_halts_new_entries_for_the_day(cfg, sessions):
    """Fails if the 5% daily-loss trigger is not applied: equity 6% under the day's start is 'done for the day', and the
    halt sticks even if equity recovers."""
    eng, feed = live_desk(cfg, sessions)
    assert eng.risk.daily_loss == 0.05
    eng.risk.start_equity = eng.equity(feed.now()) / 0.94
    msg, _ = enter(eng, feed, -1)
    assert "daily loss limit hit" in msg and not eng.open_trades and eng.risk.halted
    eng.risk.start_equity = eng.equity(feed.now())                           # recovered: still done for the day
    assert "daily loss limit hit" in enter(eng, feed, -1)[0]


def test_the_daily_loss_ceiling_sizes_a_new_trade_down_to_what_the_open_risk_leaves(cfg, sessions):
    """C-06: the open trades' stop-out risk counts against the day's -5%. Fails if `risk.size`'s daily_loss cap is
    dropped, or if `_select_by_ev` stops passing the open risk (`self._open_risk()`) to it."""
    eng, feed = live_desk(cfg, sessions)
    open_trade(eng, feed, "BANKNIFTY")
    now = feed.now()
    eng.risk.start_equity = eng.equity(now)
    free = eng.risk.start_equity * eng.risk.daily_loss                       # 5% of the day's start: what a day may lose
    per_lot = plans(eng, now).planned_risk_per_lot()
    eng.open_trades[0].initial_risk = free - 2.5 * per_lot                   # the open trade can still lose most of it
    got = eng._select_by_ev("NIFTY", [plans(eng, now)], eng.views["NIFTY"], eng.equity(now), now)
    assert not isinstance(got, str)
    lots, notes = got[1], got[2]
    assert lots * got[0].planned_risk_per_lot() <= free - eng._open_risk() + 1e-6, notes
    assert lots <= 2 and any("binding: daily_loss" in n for n in notes)
    eng.open_trades[0].initial_risk = free + 1                                # no room at all: not even one lot
    msg = eng._select_by_ev("NIFTY", [plans(eng, now)], eng.views["NIFTY"], eng.equity(now), now)
    assert isinstance(msg, str) and "none fits the account" in msg


def test_total_open_premium_over_half_of_equity_refuses_a_new_entry(cfg, sessions):
    """max_total_outlay 0.5: fails if the exposure cap is not enforced in `_blocked` for the ungated path. The open
    BANKNIFTY premium is first the real (small) figure, which the gate allows, then scaled to 50% of equity."""
    eng, feed = live_desk(cfg, sessions)
    t, _ = open_trade(eng, feed, "BANKNIFTY")
    now, eq = feed.now(), eng.equity(feed.now())
    assert not any("exposure cap" in w for w in eng.risk.gate(now, eq, eng.open_trades, "NIFTY"))
    t.legs[0].entry_price = 0.9 * eq / t.legs[0].qty                          # the net premium paid is now ≥ 50% of equity
    assert t.entry_cost >= 0.5 * eq
    msg, _ = enter(eng, feed, -1)
    assert msg.startswith("standing aside: exposure cap") and len(eng.open_trades) == 1


def test_risk_per_trade_bounds_what_a_stop_out_can_cost(cfg, sessions):
    """Sizing: lots x planned risk <= equity x risk_per_trade (2.5%) x the top conviction scale (1.2). Fails if sizing
    stops using risk_per_trade (or it is loosened) on the ungated path."""
    eng, feed = live_desk(cfg, sessions)
    eq = eng.equity(feed.now())
    msg, _ = enter(eng, feed, -1)
    assert msg.startswith("ENTER")
    t = eng.open_trades[0]
    assert 0 < t.initial_risk <= eq * 0.025 * 1.2
    assert 1 <= t.units <= eng.risk.max_lots
    assert t.units < eng.risk.max_lots                                       # the risk budget, not the lot cap, set the size


# ---- 4. liquidity and slippage still apply --------------------------------------------------------------------------
def test_an_empty_live_book_vetoes_the_entry(cfg, sessions):
    """#60: no two-sided quote on a real book, no entry. Fails if the veto in `_open` is removed or skipped ungated."""
    eng, feed = live_desk(cfg, sessions, chains=lambda e: Stub(e))
    eng.chains.live_quotes = lambda insts: {}
    msg, _ = enter(eng, feed, -1)
    assert "no two-sided quote" in msg and not eng.open_trades and eng.broker.cash() == 500000
    assert "no two-sided quote" in rejected(eng)["detail"].iloc[-1]


def test_a_book_missing_one_leg_vetoes_a_spread(cfg, sessions):
    """Every leg needs a two-sided quote. Fails if the check passes when only some legs are quoted."""
    eng, feed = live_desk(cfg, sessions, chains=lambda e: Stub(e))
    sp = plans(eng, feed.now())                                              # orb is a debit spread by config (always_spread)
    assert len(sp.legs) == 2
    short_strike = f"{sp.legs[1].strike:g}"
    one_book(eng, drop=(short_strike,))
    lots, notes = eng.risk.size(sp, eng.equity(feed.now()), eng.broker.cash())
    msg = eng._open(sp, max(lots, 1), notes, eng.views["NIFTY"], eng._last_s["NIFTY"], feed.now())
    assert "no two-sided quote" in msg and short_strike in msg and not eng.open_trades


def test_a_book_that_moved_away_is_not_chased(cfg, sessions):
    """The live-book re-check (~1516): the ask more than max_entry_slip (15%) above the plan's price skips the trade,
    one inside it fills at the live ask, and a book that moved in our favour is fine. Fails if the slippage test is
    dropped, reversed, or its tolerance widened beyond 15%."""
    eng, feed = live_desk(cfg, sessions, chains=lambda e: Stub(e))
    one_book(eng, ask_mult=1.30)                                             # asks 30% above the chain the plan was priced on
    msg, _ = enter(eng, feed, -1)
    assert "the live book moved away" in msg and not eng.open_trades and eng.risk.trades_today == 0
    assert "moved away" in rejected(eng)["detail"].iloc[-1]
    eng.chains = Stub(eng)                                                   # an undistorted book, then 5% worse asks
    one_book(eng, ask_mult=1.05)
    msg, plan = enter(eng, feed, -1)                                         # inside the tolerance: it fills, at the live book
    t = eng.open_trades[0]
    assert msg.startswith("ENTER") and t.meta["fill_quotes"].startswith("live")


def test_a_book_that_moved_in_our_favour_does_not_block(cfg, sessions):
    """Slippage is one-sided: cheaper asks are not a reason to skip. Fails if the check uses abs() of the move."""
    eng, feed = live_desk(cfg, sessions, chains=lambda e: Stub(e))
    one_book(eng, ask_mult=0.80)
    msg, _ = enter(eng, feed, -1)
    assert msg.startswith("ENTER")


def test_wide_quotes_are_flagged_in_the_entry_record(cfg, sessions):
    """`_leg_liquidity` records each leg's book at entry (journal evidence for the paper gate). Fails if the entry stops
    recording the book it filled against."""
    eng, feed = live_desk(cfg, sessions, chains=lambda e: Stub(e))
    msg, _ = enter(eng, feed, -1)
    assert msg.startswith("ENTER")
    legs = eng.open_trades[0].meta["leg_liquidity"]
    assert legs and all(("ok" in x or "wide" in x or "thin" in x or "no quote" in x) for x in legs)


# ---- 5. the armed-order path is gated the same way ------------------------------------------------------------------
def arm(eng, feed, direction=-1, u="NIFTY"):
    """A resting stop order on the live read: a `break` through a level 5 points from the market, stop 80 points the other
    way. Returns it and a price 5 points through the level (where the order fills, repriced off the chain)."""
    now = feed.now()
    S = float(eng.chain_df[u].attrs["spot"])
    level = S + 5 * direction
    a = Armed("orb", u, direction, "break", level, S - 80 * direction, 1.5, 30.0, now, now + pd.Timedelta(minutes=2), "t", "t")
    eng.armed[u] = [a]
    return a, level + 5 * direction


def test_an_armed_order_fires_through_the_ev_layer_ungated(cfg, sessions):
    """Fails if `_fire_armed` applies a model gate ungated, or opens without the EV layer / the quant text."""
    eng, feed = live_desk(cfg, sessions)
    a, px = arm(eng, feed, -1)
    msg = eng._fire_armed("NIFTY", feed.now(), price=px)
    assert msg and msg.startswith("ENTER") and GATE_WORDS not in msg
    t = eng.open_trades[0]
    assert t.direction == -1 and "armed" in t.meta and "Quant: EV" in t.rationale and "plan_model" not in t.meta
    assert eng.armed["NIFTY"] == []                                         # one shot


def test_an_armed_order_below_the_ev_floor_is_refused_and_recorded(cfg, sessions):
    """Fails if the armed path skips `_select_by_ev` (a sub-floor armed plan would open)."""
    eng, feed = live_desk(cfg, sessions)
    a, px = arm(eng, feed, +1)                                              # a call into the bearish read: negative EV
    msg = eng._fire_armed("NIFTY", feed.now(), price=px)
    assert msg and "reached its level" in msg and "not worth it after costs" in msg and not eng.open_trades
    r = rejected(eng)
    assert r["detail"].str.startswith("EV below the floor").any()            # the EV layer's own record ...
    assert "reached its level" in r["detail"].iloc[-1] and "armed" in r["context"].iloc[-1]    # ... and the armed order's


def test_an_armed_order_obeys_the_trade_cap_and_the_daily_loss_limit(cfg, sessions):
    """Fails if `_fire_armed` does not consult `_blocked` (and so the risk gate) before building the trade."""
    eng, feed = live_desk(cfg, sessions)
    eng.risk.trades_today = eng.risk.max_trades
    a, px = arm(eng, feed, -1)
    assert eng._fire_armed("NIFTY", feed.now(), price=px) is None and not eng.open_trades
    eng.risk.trades_today = 0
    eng.risk.start_equity = eng.equity(feed.now()) / 0.9
    a, px = arm(eng, feed, -1)
    assert eng._fire_armed("NIFTY", feed.now(), price=px) is None and not eng.open_trades and eng.risk.halted


def test_an_armed_order_obeys_the_live_book_checks(cfg, sessions):
    """The armed fill goes through `_open`'s liquidity and slippage tests. Fails if an armed order is filled blind."""
    eng, feed = live_desk(cfg, sessions, chains=lambda e: Stub(e))
    eng.chains.live_quotes = lambda insts: {}
    a, px = arm(eng, feed, -1)
    msg = eng._fire_armed("NIFTY", feed.now(), price=px)
    assert "no two-sided quote" in msg and not eng.open_trades
    eng.chains = Stub(eng)
    one_book(eng, ask_mult=1.5)
    a, px = arm(eng, feed, -1)
    assert "moved away" in eng._fire_armed("NIFTY", feed.now(), price=px) and not eng.open_trades


def test_the_gated_twin_refuses_an_armed_order_at_the_model_gate(tmp_path, sessions):
    """The control: gated, the same armed order stops at the model gate (and says so on the decision record)."""
    eng, feed = live_desk(make_cfg(tmp_path, required=True), sessions)
    a, px = arm(eng, feed, -1)
    msg = eng._fire_armed("NIFTY", feed.now(), price=px)
    assert GATE_WORDS in msg and not eng.open_trades


# ---- 6. a plan-registry fault (P2-7) --------------------------------------------------------------------------------
def break_plan_registry(root, how):
    """A plan champion on record that cannot be trusted (returns a fault) ..."""
    from test_plan_research import _policy
    reg = Registry(root / "plan")
    card = {"code_fingerprint": "c", "feature_version": "f", "label_version": "l", "data_fingerprint": "d", "training_window": {},
            "validation": {"passed": True}, "family": "plan", "evidence": "real_point_in_time"}
    mid, _ = reg.register(_policy("3-5"), card)
    reg.promote(mid, "test", {"forward": True})
    if how == "evidence":
        reg.update_card(mid, evidence="modelled")                            # tampered after promotion
    else:
        next((root / "plan").rglob(f"{mid}/artifact.json")).unlink()          # the artifact is gone


@pytest.mark.parametrize("how", ["evidence", "artifact"])
@pytest.mark.parametrize("required", [False, True])
def test_a_plan_registry_fault_halts_entries_only_when_required(tmp_path, sessions, required, how):
    """Through the real engine path (`start_session` -> `_blocked`), not just LiveLearner. Fails if an advisory plan
    registry halts the ungated desk (P2-7), or if a required one stops halting."""
    cfg = make_cfg(tmp_path, required=required)
    root = tmp_path / "al"
    break_plan_registry(root, how)
    bars, days = sessions
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    eng.learner = LiveLearner(cfg, root=root, source="replay")
    eng.start_session(days[-1])
    eng.paused = True                                                        # the test, not the desk, decides what opens
    for _ in range(60):
        eng.feed.advance()
        eng.step()
    eng.paused = False
    assert eng.learner.plan is None and eng.learner.plan_fault
    why = eng._blocked("NIFTY", eng.views["NIFTY"], eng.feed.now())
    if required:
        assert why and why.startswith("halted: ") and eng.learner.plan_fault in why
    else:
        assert why is None, why
        msg, _ = enter(eng, eng.feed, -1)
        assert msg.startswith("ENTER")                                      # and it then trades, on EV


def corrupt_plan_events(root):
    p = root / "plan" / "registry"
    p.mkdir(parents=True, exist_ok=True)
    (p / "events.jsonl").write_text("not json\n")                            # no state.json: rebuilt from this log


def started(cfg, sessions, root, corrupt=None):
    bars, days = sessions
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    eng.learner = LiveLearner(cfg, root=root, source="replay")
    if corrupt:
        corrupt(root)
    eng.start_session(days[-1])
    eng.paused = True                                                        # the test, not the desk, decides what opens
    for _ in range(60):
        eng.feed.advance()
        eng.step()
    eng.paused = False
    return eng


def test_a_raising_plan_registry_halts_entries_when_the_plan_model_is_required(tmp_path, sessions):
    """Required: an unreadable plan registry is fail-closed (any halt is right). Fails if it stops halting."""
    eng = started(make_cfg(tmp_path, required=True), sessions, tmp_path / "al", corrupt_plan_events)
    why = eng._blocked("NIFTY", eng.views["NIFTY"], eng.feed.now())
    assert why and why.startswith("halted: ") and "registry" in why


def test_a_raising_plan_registry_still_halts_the_ungated_desk(tmp_path, sessions):
    """Pinned as is, fail-closed (16 Oct). A plan registry that RAISES (an unreadable events.jsonl, an I/O error) escapes
    LiveLearner.start; start_session records it as 'learning registry unreadable' and entries halt, even with
    require_approved_model false. Only a plan fault that champion() RETURNS is advisory (P2-7). Making the raising case
    advisory too would let the desk trade through a broken registry, a loosening of a fail-closed halt: that is the
    owner's call (remediation log, open items), not a test's. Change this test only with that decision."""
    eng = started(make_cfg(tmp_path, required=False), sessions, tmp_path / "al", corrupt_plan_events)
    assert eng.learner.fault and "unreadable" in eng.learner.fault
    why = eng._blocked("NIFTY", eng.views["NIFTY"], eng.feed.now())
    assert why and why.startswith("halted: ")


def test_a_direction_champion_that_cannot_be_verified_still_halts_ungated(tmp_path, sessions):
    """Not P2-7's concern: the DIRECTION registry stays fail-closed whatever require_approved_model says. Fails if the
    ungated switch were to silence a direction-champion fault too."""
    def bad_direction_champion(root):
        reg = root / "registry"
        reg.mkdir(parents=True, exist_ok=True)
        (reg / "state.json").write_text('{"champion": "ghost-0000000000", "challengers": []}')
    eng = started(make_cfg(tmp_path, required=False), sessions, tmp_path / "al", bad_direction_champion)
    why = eng._blocked("NIFTY", eng.views["NIFTY"], eng.feed.now())
    assert why and why.startswith("halted: ") and "ghost" in why
