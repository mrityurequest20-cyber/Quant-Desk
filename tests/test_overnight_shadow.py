"""Overnight carry, PHASE 1 (docs/prereg/overnight_carry_v1.json, intraday/overnight.py): SHADOW ONLY. At the 15:15 square-off
every open position records what it WOULD have carried (lots by the full-max-loss rule) and is squared off exactly as before;
the next session's first real quotes from 09:20 mark the record against the actual exit. Nothing in the paper account changes."""
import datetime as dt
import json

import pandas as pd
import pytest

from quantdesk.core.calendar import TradingCalendar
from quantdesk.intraday import overnight as OV
from quantdesk.intraday.engine import IntradayEngine
from quantdesk.intraday.feeds import ReplayFeed
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal
from test_carry_gate import hist_file, seed
from test_intraday_hardening_c import START, _spread, _view, ts

SPEC = OV.load_spec()
EXP = dt.date(2026, 10, 13)
DAY1, DAY2 = dt.date(2026, 9, 29), dt.date(2026, 9, 30)


def cfg_mode(cfg, mode):
    return cfg.with_overrides({"intraday": {"overnight_carry": {"mode": mode}}})


def engine(cfg, day):
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days(day - dt.timedelta(days=10), DAY2)]
    bars, _ = simulate_sessions(days, seed=11)
    eng = IntradayEngine(cfg, ReplayFeed(bars, day), "model", Journal(), IntradayBroker(cfg, starting_cash=START), say=None)
    eng.start_session(day)
    return eng


def open_spread(eng, lots, expiry=EXP, day=DAY1):
    now = ts(f"{day} 11:00")
    eng._open(_spread(expiry), lots, [], _view(now), {}, now)
    return eng.open_trades[-1]


def squared_off(eng):
    eng.feed.clock = ts(f"{eng.day} 15:16")
    eng._wallclock_exits(eng.feed.now())


def candidates(eng):
    return [e for e in eng.ov_ledger.events() if e["event"] == "candidate"]


# ---- shadow records and changes nothing ---------------------------------------------------------------------------------------------------------
def test_shadow_records_the_would_be_carry_and_squares_off_exactly_as_before(cfg):
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    t = open_spread(eng, 5)
    squared_off(eng)
    assert not eng.open_trades and eng.closed[0].exit_reason == "square_off" and not eng.broker.positions()
    cand, ex = candidates(eng)[0], [e for e in eng.ov_ledger.events() if e["event"] == "exit"][0]
    assert cand["id"] == t.id and cand["setup"] == "orb" and cand["lots"] == 5 and 1 <= cand["lots_fit"] < 5
    assert cand["mode"] == "shadow" and cand["effective"] == "shadow" and cand["next_day"] == str(DAY2)
    assert cand["max_loss_fit"] <= 0.025 * START and ex["id"] == t.id and ex["pnl"] == pytest.approx(eng.closed[0].pnl)
    assert len(eng.journal.df("SELECT * FROM fills WHERE trade_id=?", (t.id,))) == 4          # two entry legs, two exit legs: no trim
    assert eng.journal.events(level="CRITICAL").empty and eng.journal.get_state("overnight_carry") is None


def test_the_excess_lots_are_what_does_not_fit_and_are_recorded_not_traded(cfg):
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    t = open_spread(eng, 5)
    legs, fees, costs = OV.legs_of(t), t.fees, eng.broker.costs
    squared_off(eng)
    c = candidates(eng)[0]
    fit = c["lots_fit"]
    assert c["lots"] - fit >= 1 and c["max_loss_fit"] <= 0.025 * START
    assert c["max_loss_fit"] == pytest.approx(OV.loss_for(legs, fit, fees, costs, extra_close_lots=5 - fit)["max_loss"])
    assert OV.loss_for(legs, fit, fees, costs, extra_close_lots=5 - fit)["trim_fees"] > 0           # the excess lots' closing is inside it
    assert OV.loss_for(legs, fit + 1, fees, costs, extra_close_lots=4 - fit)["max_loss"] > 0.025 * START   # one more would break it
    assert c["max_loss_fit"] >= fit * 60.0 * 65                                                       # at least the carried lots' net debit


def test_off_records_nothing(cfg):
    eng = engine(cfg_mode(cfg, "off"), DAY1)
    open_spread(eng, 3)
    squared_off(eng)
    assert not eng.open_trades and eng.ov_ledger.events() == []


def test_a_failing_record_never_stops_the_square_off(cfg, monkeypatch):
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    open_spread(eng, 3)
    monkeypatch.setattr(OV, "plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    squared_off(eng)
    assert not eng.open_trades and eng.closed[0].exit_reason == "square_off"
    assert eng.journal.events(level="WARN")["message"].str.contains("shadow record failed").any()


def test_apply_is_not_implemented_it_is_shadow_with_a_warning_even_with_the_gate_met(cfg, tmp_path, monkeypatch):
    import numpy as np
    eng = engine(cfg_mode(cfg, "apply"), DAY1)
    folder = tmp_path / "results"
    hist_file(folder, "orb")
    monkeypatch.setattr(OV, "RESULTS", folder)
    seed(eng.ov_ledger, "orb", list(np.random.default_rng(1).normal(400, 300, 30)), sessions=5)
    assert OV.gate(SPEC, eng.ov_ledger, "orb", folder)["met"]                        # the gate itself is met ...
    open_spread(eng, 5)
    squared_off(eng)                                                                  # ... and still nothing is carried
    assert not eng.open_trades and not eng.broker.positions() and eng.closed[0].exit_reason == "square_off"
    c = candidates(eng)[-1]
    assert c["mode"] == "apply" and c["effective"] == "shadow" and "not implemented" in c["note"]
    w = eng.journal.events(level="WARN")
    assert w["message"].str.contains("apply, which is not implemented").sum() == 1       # said once


@pytest.mark.parametrize("what", ["naked_call", "naked_put", "short_straddle", "ratio"])
def test_a_naked_short_is_never_a_candidate(cfg, what):
    from quantdesk.core.types import Instrument, Trade, TradeLeg
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    legs = {"naked_call": [(-1, "CE", 25000, 100.0)], "naked_put": [(-1, "PE", 24800, 90.0)],
            "short_straddle": [(-1, "CE", 25000, 100.0), (-1, "PE", 25000, 100.0)],
            "ratio": [(-2, "CE", 25000, 100.0), (1, "CE", 25200, 40.0)]}[what]
    t = Trade(id="N1", strategy="orb", family="intraday", symbol="NIFTY", direction=-1, kind="options", legs=[], units=1,
              opened_at=ts(f"{DAY1} 11:00"), entry_underlying=25000.0, initial_risk=1000.0)
    for q, right, k, px in legs:
        t.legs.append(TradeLeg(Instrument.option("NIFTY", EXP, k, right, 65), q * 65, px))
    pl = OV.plan(eng.cfg, eng.cal, t, DAY1, eng._overnight_facts(eng.feed.now()), eng.broker.costs)
    assert pl["lots_fit"] == 0 and any("not covered" in r for r in pl["reasons"])


def test_calendar_and_expiry_exclusions_are_in_the_record(cfg):
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    t = open_spread(eng, 1, expiry=DAY2 + dt.timedelta(days=0))                       # expires at the very next session
    squared_off(eng)
    c = candidates(eng)[0]
    assert c["lots_fit"] == 0 and any("never carried into an expiry" in r for r in c["reasons"])
    eng2 = engine(cfg_mode(cfg, "shadow"), DAY1)
    t2 = open_spread(eng2, 1)
    eng2.day = dt.date(2026, 9, 25)                                                    # a Friday: the next session is Monday
    squared_off(eng2)
    assert any("weekend or a holiday" in r for r in candidates(eng2)[-1]["reasons"]), candidates(eng2)[-1]["reasons"]


def test_a_halt_is_recorded_as_a_reason(cfg):
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    open_spread(eng, 2)
    eng.paused = True
    squared_off(eng)
    c = candidates(eng)[0]
    assert c["lots_fit"] == 0 and any("paused" in r for r in c["reasons"])


def test_the_would_be_carries_of_one_evening_share_the_limits(cfg):
    """Two positions open at the square-off: the second sees the first's reserved loss and slot (max_open 2 allows both, a
    third would not), as two real carries would."""
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    eng._ov_virtual.extend([{"max_loss": 1000.0, "margin": 1000.0}, {"max_loss": 1000.0, "margin": 1000.0}])
    open_spread(eng, 1)
    squared_off(eng)
    assert any("would already be open" in r for r in candidates(eng)[0]["reasons"])


# ---- shadow on and off: the same account, trade for trade ---------------------------------------------------------------------------------------------
def replay(cfg, mode, tmp_path, with_overnight_position=True):
    """A whole synthetic session through the engine, with one extra position held to the close; the account's every number."""
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days(DAY1 - dt.timedelta(days=12), DAY1)]
    bars, _ = simulate_sessions(days, seed=21)
    c = cfg_mode(cfg, mode).with_overrides({"runtime": {"dir": str(tmp_path / mode)}})        # each run its own ledger
    eng = IntradayEngine(c, ReplayFeed(bars, DAY1), "model", Journal(), IntradayBroker(c, starting_cash=START), say=None)
    eng.start_session(DAY1)
    while eng.feed.advance():
        eng.step()
        if with_overnight_position and eng.feed.now() == ts(f"{DAY1} 11:00"):
            eng._open(_spread(EXP), 3, [], _view(eng.feed.now()), {}, eng.feed.now())
            eng.open_trades[-1].exit_rules.update(time_stop_min=9999, premium_stop=99.0, premium_target=99.0)
    eng.end_session()
    j = eng.journal
    trades = j.df("SELECT strategy, symbol, units, opened_at, closed_at, pnl, fees, exit_reason, status FROM trades ORDER BY opened_at, strategy")
    fills = j.df("SELECT ts, symbol, qty, price, fees FROM fills ORDER BY id")
    return {"trades": trades.to_dict("records"), "fills": fills.to_dict("records"), "cash": eng.broker.cash(),
            "positions": json.dumps(eng.broker.positions(), sort_keys=True, default=str), "closed": len(eng.closed),
            "open": len(eng.open_trades), "reasons": sorted(t.exit_reason for t in eng.closed), "eng": eng}


def test_shadow_on_and_off_leave_the_same_trades_fills_cash_and_square_offs(cfg, tmp_path):
    off, on = replay(cfg, "off", tmp_path), replay(cfg, "shadow", tmp_path)
    for k in ("trades", "fills", "cash", "positions", "closed", "open", "reasons"):
        assert off[k] == on[k], k
    assert off["open"] == 0 and off["positions"] == "{}" and "square_off" in on["reasons"]        # the position was squared off ...
    assert off["eng"].ov_ledger.events() == []                                                     # ... off recorded nothing ...
    ev = on["eng"].ov_ledger.events()
    assert [e["event"] for e in ev if e["event"] in ("candidate", "exit")] == ["candidate", "exit"]     # ... shadow recorded it
    assert ev[0]["lots"] == 3 and ev[1]["pnl"] == pytest.approx([t for t in on["eng"].closed if t.exit_reason == "square_off"][0].pnl)


# ---- the next morning's mark ------------------------------------------------------------------------------------------------------------------------
def chain(source="kotak", at="09:21", expiry=EXP):
    ch = pd.DataFrame({"ce_bid": [95.0, 38.0], "ce_ask": [96.0, 39.0], "pe_bid": [1.0, 1.0], "pe_ask": [2.0, 2.0]}, index=[25000.0, 25200.0])
    ch.attrs.update(source=source, ts=pd.Timestamp(f"{DAY2} {at}", tz="Asia/Kolkata"), expiry=expiry, underlying="NIFTY")
    return ch


def shadow_day(cfg):
    eng = engine(cfg_mode(cfg, "shadow"), DAY1)
    t = open_spread(eng, 3)
    squared_off(eng)
    return eng, t


def test_yesterdays_record_is_marked_at_the_first_real_quotes_from_0920(cfg):
    eng1, t = shadow_day(cfg)
    eng = engine(cfg_mode(cfg, "shadow"), DAY2)
    eng.ov_ledger = eng1.ov_ledger
    eng.chain_df["NIFTY"] = chain(at="09:19")                            # before the window
    eng._overnight_mark(ts(f"{DAY2} 09:19"))
    eng.chain_df["NIFTY"] = chain(source="model")                        # a model chain is not a quote
    eng._overnight_mark(ts(f"{DAY2} 09:22"))
    assert [e for e in eng.ov_ledger.events() if e["event"] == "mark"] == []
    eng.chain_df["NIFTY"] = chain()
    eng._overnight_mark(ts(f"{DAY2} 09:22"))
    mk = [e for e in eng.ov_ledger.events() if e["event"] == "mark"]
    assert len(mk) == 1 and mk[0]["id"] == t.id and mk[0]["source"] == "kotak"
    rec = candidates(eng)[0]
    assert mk[0]["carry_pnl"] == pytest.approx(OV.mark_pnl(rec, chain(), eng.broker.costs, float(eng.broker.costs.opt_half_ticks)))
    eng._overnight_mark(ts(f"{DAY2} 09:23"))
    assert len([e for e in eng.ov_ledger.events() if e["event"] == "mark"]) == 1          # once
    pair = eng.ov_ledger.pairs("orb")[0]
    assert pair["d"] == pytest.approx((mk[0]["carry_pnl"] - eng1.closed[0].pnl) / 3)       # carry minus the actual close, per lot
    rep = OV.report(SPEC, eng.ov_ledger)
    orb = next(r for r in rep["rows"] if r["setup"] == "orb")
    assert orb["n"] == 1 and orb["mean"] == pytest.approx(pair["d"]) and orb["candidates"] == 1
    assert "orb |" in OV.render(rep) and "nothing is carried" in OV.render(rep)


def test_an_unpriceable_or_late_record_is_unmarked_never_filled_in(cfg):
    eng1, t = shadow_day(cfg)
    eng = engine(cfg_mode(cfg, "shadow"), DAY2)
    eng.ov_ledger = eng1.ov_ledger
    eng.chain_df["NIFTY"] = chain()
    eng.chain_df["NIFTY"].loc[25200.0, "ce_ask"] = 0.0                    # the short leg has no ask
    eng._overnight_mark(ts(f"{DAY2} 09:22"))
    assert [e for e in eng.ov_ledger.events() if e["event"] == "mark"] == []
    eng._overnight_mark(ts(f"{DAY2} 09:31"))                              # past 09:30: given up
    assert [e["id"] for e in eng.ov_ledger.events() if e["event"] == "unmarked"] == [t.id]
    assert eng.ov_ledger.pairs() == [] and OV.forward(eng.ov_ledger, "orb", None)["unmarked"] == 1
    eng3 = engine(cfg_mode(cfg, "shadow"), dt.date(2026, 10, 1))          # a record whose marking day passed unseen
    eng3.ov_ledger = eng1.ov_ledger
    eng3.ov_ledger.append({"event": "candidate", "id": "old", "setup": "orb", "day": "2026-09-01", "next_day": "2026-09-02", "lots": 1})
    eng3._overnight_finalize(dt.date(2026, 10, 1))
    assert "old" in [e["id"] for e in eng3.ov_ledger.events() if e["event"] == "unmarked"]


def test_marking_uses_only_the_expiry_the_position_holds(cfg):
    eng1, t = shadow_day(cfg)
    eng = engine(cfg_mode(cfg, "shadow"), DAY2)
    eng.ov_ledger = eng1.ov_ledger
    eng.chain_df["NIFTY"] = chain(expiry=EXP + dt.timedelta(days=7))      # a different expiry's chain: its quotes are not this position's
    eng._overnight_mark(ts(f"{DAY2} 09:22"))
    assert [e for e in eng.ov_ledger.events() if e["event"] == "mark"] == []


def test_the_docs_and_config_say_shadow_only():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    backlog = (root / "docs" / "BACKLOG.md").read_text(encoding="utf-8")
    cfg_yaml = (root / "config" / "quantdesk.yaml").read_text(encoding="utf-8")
    assert "Overnight holding: shadow only (phase 1)" in readme and "full max loss" in readme and "intraday overnight" in readme
    assert "shadow only" in backlog and "overnight_carry_v1.json" in backlog and "allocator_v1.json" in backlog
    assert "allocator: {mode: shadow}" in cfg_yaml and "overnight_carry: {mode: shadow}" in cfg_yaml


def test_the_command_prints_the_running_paired_difference(cfg, capsys):
    from quantdesk.cli import build_parser
    a = build_parser().parse_args(["intraday", "overnight"])
    a.fn(cfg, a)
    out = capsys.readouterr().out
    assert "Overnight carry (shadow)" in out and "overnight_carry_v1" in out and "mean carry - close" in out
