"""Overnight carry of the desk's own positions, the pure parts (intraday/overnight.py, research/overnight_carry.py,
docs/prereg/overnight_carry_v1.json): defined risk, the FULL max loss, the lots that fit, the calendar and expiry rules, the
evidence gate, the 09:20 mark, and the history test's decision rule on a planted effect and on noise."""
import datetime as dt
import json
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.core.types import Instrument, Trade, TradeLeg
from quantdesk.execution.costs import CostModel
from quantdesk.intraday import overnight as OV

IST = "Asia/Kolkata"
SPEC = OV.load_spec()
DAY, EXP = dt.date(2026, 9, 28), dt.date(2026, 10, 13)          # a Monday; an expiry well beyond the next session
LOT = 65


def mk(legs, lots=3, setup="orb", expiry=EXP, fees=60.0, initial_risk=None):
    """A trade: legs = [(per-lot qty, right, strike, entry price)]."""
    t = Trade(id="T1", strategy=setup, family="intraday", symbol="NIFTY", direction=1, kind="options", legs=[], units=lots,
              opened_at=pd.Timestamp(f"{DAY} 11:00", tz=IST), entry_underlying=25000.0,
              initial_risk=initial_risk if initial_risk is not None else 0.3 * lots * LOT * sum(max(q, 0) * p for q, _, _, p in legs),
              fees=fees)
    for q, right, k, px in legs:
        t.legs.append(TradeLeg(Instrument.option("NIFTY", expiry, k, right, LOT), q * lots * LOT, px))
    return t


def facts(**kw):
    return {"equity": 500000.0, "day_start_equity": 500000.0, "peak": 500000.0, "reserved_loss": 0.0, "reserved_margin": 0.0,
            "carries": 0, "halts": [], **kw}


@pytest.fixture
def env(cfg):
    return cfg, TradingCalendar(cfg.holidays()), CostModel(cfg)


LONG_CALL = [(1, "CE", 25000, 100.0)]
DEBIT_SPREAD = [(1, "CE", 25000, 100.0), (-1, "CE", 25200, 40.0)]
IRON_FLY = [(-1, "CE", 25000, 120.0), (-1, "PE", 25000, 120.0), (1, "CE", 25200, 50.0), (1, "PE", 24800, 50.0)]


# ---- the spec and the config ------------------------------------------------------------------------------------------------------------
def test_the_spec_says_what_the_code_enforces():
    assert SPEC["name"] == "overnight_carry_v1" and set(SPEC["what_may_carry"]["setups"]) == set(OV.SETUPS)
    assert "LOSES" in SPEC["prior"] and "L4" in SPEC["prior"]
    g = SPEC["evidence_gate"]
    assert "n >= 100" in g["a_history_test"]["pass"] and "2.33" in g["a_history_test"]["pass"]
    assert (OV.HIST_MIN_N, OV.HIST_T, OV.FWD_MIN_N, OV.FWD_MAX_N, OV.FWD_T, OV.SHADOW_SESSIONS_REQUIRED) == (100, 2.33, 30, 60, 1.645, 5)
    assert "at least 30 marked" in g["b_forward_shadow"]["pass"] and "1.645" in g["b_forward_shadow"]["pass"]
    assert SPEC["mode"]["shipping_default"].startswith("shadow")
    assert "2.5%" in SPEC["carry_rule"]["sizing_full_max_loss"]


def test_the_config_ships_in_shadow_and_unknown_is_shadow():
    cfg = Config.load(DEFAULT_CONFIG)
    assert cfg.get("intraday.overnight_carry.mode") == "shadow" and OV.settings(cfg)["mode"] == "shadow"
    for bad in (None, "", "yes", "APPLYY", 1):
        assert OV.settings(cfg.with_overrides({"intraday": {"overnight_carry": {"mode": bad}}}))["mode"] == "shadow"
    assert OV.settings(cfg.with_overrides({"intraday": {"overnight_carry": {"mode": "Apply"}}}))["mode"] == "apply"
    assert OV.settings(Config({}))["mode"] == "shadow"


def test_limits_are_never_looser_than_the_desk_or_the_ceilings(cfg):
    lim = OV.limits(cfg)
    assert (lim["risk_per_trade"], lim["max_open"], lim["daily_loss"], lim["max_margin"], lim["dd_halt"]) == (0.025, 2, 0.05, 0.5, 0.10)
    loose = cfg.with_overrides({"intraday": {"risk": {"risk_per_trade": 0.05, "max_open": 6, "daily_loss_limit": 0.3,
                                                     "max_total_outlay": 0.9, "max_margin": 0.9, "cross_day_drawdown_halt": 0.5}}})
    assert OV.limits(loose) == lim
    tight = cfg.with_overrides({"intraday": {"risk": {"risk_per_trade": 0.01, "max_open": 1}}})
    assert OV.limits(tight)["risk_per_trade"] == 0.01 and OV.limits(tight)["max_open"] == 1


# ---- defined risk and the full max loss -----------------------------------------------------------------------------------------------------
def test_a_long_option_is_sized_on_its_full_debit_not_its_stop_distance(env):
    cfg, cal, costs = env
    t = mk(LONG_CALL, lots=3)                                          # 3 lots at 100: debit ₹6,500 a lot; the 30% stop risks ₹1,950
    pl = OV.plan(cfg, cal, t, DAY, facts(), costs)
    stop_lots = int(0.025 * 500000 // (t.initial_risk / 3))
    assert stop_lots >= 3                                              # the intraday rule would have carried all three
    assert pl["reasons"] == [] and pl["lots_fit"] == 1 and pl["lots"] == 3
    assert pl["per_lot"]["gross_loss"] == pytest.approx(100.0 * LOT)   # the whole premium
    assert pl["per_lot"]["stop_distance_risk"] == pytest.approx(0.3 * 100.0 * LOT)
    assert pl["max_loss"] <= 0.025 * 500000 and pl["max_loss"] > 100.0 * LOT      # costs included, never below the debit
    e2 = OV.loss_for(OV.legs_of(t), 2, t.fees, costs, extra_close_lots=1)
    assert e2["max_loss"] > 0.025 * 500000                              # two lots do not fit: never rounded up
    assert pl["margin"] == pytest.approx(t.entry_cost / 3 * 1)          # a debit blocks its premium


def test_a_debit_spread_risks_its_net_debit_and_a_fly_its_wing_less_credit(env):
    cfg, cal, costs = env
    sp = OV.legs_of(mk(DEBIT_SPREAD, lots=1))
    assert OV.worst_payoff(sp) == pytest.approx(-(100.0 - 40.0) * LOT)
    fly = OV.legs_of(mk(IRON_FLY, lots=1))
    credit = 120 + 120 - 50 - 50
    assert OV.worst_payoff(fly) == pytest.approx(-(200.0 - credit) * LOT)       # the wider wing minus the credit
    assert OV.uncovered(sp) == [] and OV.uncovered(fly) == []


def test_the_carried_lots_never_exceed_two_and_a_half_percent_of_equity_in_full_max_loss(env):
    cfg, cal, costs = env
    for legs, lots in ((LONG_CALL, 9), (DEBIT_SPREAD, 12), (IRON_FLY, 8)):
        for eq in (200000.0, 500000.0, 2000000.0):
            t = mk(legs, lots=lots)
            pl = OV.plan(cfg, cal, t, DAY, facts(equity=eq, day_start_equity=eq, peak=eq), costs, lim=OV.limits(cfg) | {"short_from": 0})
            if pl["lots_fit"]:
                assert pl["max_loss"] <= 0.025 * eq
                assert OV.loss_for(OV.legs_of(t), pl["lots_fit"] + 1, t.fees, costs)["max_loss"] > 0.025 * eq or pl["lots_fit"] == lots


def test_not_one_lot_that_fits_carries_nothing(env):
    cfg, cal, costs = env
    t = mk([(1, "CE", 25000, 400.0)], lots=2)                           # one lot's full debit is ₹26,000: over ₹12,500
    pl = OV.plan(cfg, cal, t, DAY, facts(), costs)
    assert pl["lots_fit"] == 0 and any("not one lot fits" in r and "risk" in r for r in pl["reasons"])


def test_the_daily_room_and_the_margin_room_bind_too(env):
    cfg, cal, costs = env
    t = mk(DEBIT_SPREAD, lots=4)
    free = OV.plan(cfg, cal, t, DAY, facts(), costs)["lots_fit"]
    assert free >= 2
    tight_day = OV.plan(cfg, cal, t, DAY, facts(day_start_equity=500000.0 * (1 / 0.95) + 4000, reserved_loss=0.0), costs)
    assert tight_day["lots_fit"] < free                                 # the day has already used its room
    reserved = OV.plan(cfg, cal, t, DAY, facts(reserved_loss=40000.0), costs)
    assert reserved["lots_fit"] < free                                  # other carries reserve loss against the same 5%
    blocked = OV.plan(cfg, cal, t, DAY, facts(reserved_margin=0.5 * 500000 - 1000.0), costs)
    assert blocked["lots_fit"] == 0 and "margin" in blocked["binding"]


# ---- naked shorts are never carried -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("legs", [
    [(-1, "CE", 25000, 100.0)],                                                   # a naked short call
    [(-1, "PE", 24800, 90.0)],
    [(-1, "CE", 25000, 100.0), (1, "PE", 24800, 90.0)],                           # covered by the wrong right
    [(-1, "CE", 25000, 100.0), (-1, "PE", 25000, 100.0)],                         # a short straddle
    [(-2, "CE", 25000, 100.0), (1, "CE", 25200, 40.0)],                           # a ratio: one short uncovered
])
def test_a_naked_short_is_never_a_carry(env, legs):
    cfg, cal, costs = env
    pl = OV.plan(cfg, cal, mk(legs, lots=1), DAY, facts(), costs)
    assert pl["lots_fit"] == 0 and any("not covered" in r for r in pl["reasons"])


def test_a_short_covered_only_by_another_expiry_is_not_defined_risk(env):
    cfg, cal, costs = env
    t = mk([(-1, "CE", 25000, 100.0)], lots=1, expiry=EXP)
    t.legs.append(TradeLeg(Instrument.option("NIFTY", EXP + dt.timedelta(days=28), 25000.0, "CE", LOT), LOT, 150.0))
    pl = OV.plan(cfg, cal, t, DAY, facts(), costs)
    assert pl["lots_fit"] == 0 and any("not covered" in r for r in pl["reasons"])


def test_an_uncovered_short_is_refused_whatever_else_is_true(env):
    cfg, cal, costs = env
    pl = OV.plan(cfg, cal, mk([(-1, "CE", 25000, 5.0)], lots=1), DAY, facts(equity=1e9, day_start_equity=1e9, peak=1e9), costs)
    assert pl["lots_fit"] == 0


# ---- the calendar and the expiry ---------------------------------------------------------------------------------------------------------------
def test_no_carry_over_a_weekend_or_a_holiday(env):
    cfg, cal, costs = env
    fri = dt.date(2026, 9, 25)
    assert fri.weekday() == 4
    pl = OV.plan(cfg, cal, mk(LONG_CALL, lots=1), fri, facts(), costs)
    assert pl["lots_fit"] == 0 and any("weekend or a holiday" in r for r in pl["reasons"])
    hol = next(h for h in sorted(cfg.holidays()) if h.year == 2026 and h.weekday() in (1, 2, 3)
               and cal.is_trading_day(h - dt.timedelta(days=1)) and cal.is_trading_day(h + dt.timedelta(days=1)))
    pl = OV.plan(cfg, cal, mk(LONG_CALL, lots=1, expiry=hol + dt.timedelta(days=20)), hol - dt.timedelta(days=1), facts(), costs)
    assert pl["lots_fit"] == 0 and any("weekend or a holiday" in r for r in pl["reasons"])
    ok = OV.plan(cfg, cal, mk(LONG_CALL, lots=1), DAY, facts(), costs)
    assert ok["reasons"] == [] and ok["lots_fit"] == 1


def test_no_carry_into_an_expiry_day_or_past_it(env):
    cfg, cal, costs = env
    nxt = cal.next_trading_day(DAY)
    for exp in (DAY, nxt, nxt - dt.timedelta(days=1)):
        pl = OV.plan(cfg, cal, mk(LONG_CALL, lots=1, expiry=exp), DAY, facts(), costs)
        assert pl["lots_fit"] == 0 and any("never carried into an expiry" in r for r in pl["reasons"]), exp
    two = cal.next_trading_day(nxt)
    assert OV.plan(cfg, cal, mk(LONG_CALL, lots=1, expiry=two), DAY, facts(), costs)["lots_fit"] == 1     # two sessions out is allowed


def test_a_year_without_a_holiday_list_refuses(env):
    cfg, cal, costs = env
    t = mk(LONG_CALL, lots=1, expiry=dt.date(2027, 12, 30))
    pl = OV.plan(cfg, cal, t, dt.date(2027, 12, 20), facts(), costs)
    assert pl["lots_fit"] == 0 and any("cannot be trusted" in r for r in pl["reasons"])


@pytest.mark.parametrize("halt", ["the kill switch is set", "safe mode", "an inherited-position halt is active",
                                  "the cross-day drawdown halt is active", "the day's loss limit was hit"])
def test_every_halt_refuses(env, halt):
    cfg, cal, costs = env
    pl = OV.plan(cfg, cal, mk(LONG_CALL, lots=1), DAY, facts(halts=[halt]), costs)
    assert pl["lots_fit"] == 0 and halt in pl["reasons"]


def test_equity_state_and_slots_refuse(env):
    cfg, cal, costs = env
    t = mk(DEBIT_SPREAD, lots=1)
    assert "loss limit" in " ".join(OV.plan(cfg, cal, t, DAY, facts(equity=470000.0), costs)["reasons"])
    assert "from its peak" in " ".join(OV.plan(cfg, cal, t, DAY, facts(equity=440000.0, day_start_equity=440000.0), costs)["reasons"])
    assert "would already be open" in " ".join(OV.plan(cfg, cal, t, DAY, facts(carries=2), costs)["reasons"])
    assert OV.plan(cfg, cal, t, DAY, facts(carries=1), costs)["lots_fit"] == 1                 # the second slot is fine
    assert "floor for sold legs" in " ".join(OV.plan(cfg.with_overrides({"intraday": {"short_legs_from_equity": 900000}}), cal,
                                                     mk(IRON_FLY, lots=1), DAY, facts(), costs)["reasons"])
    assert OV.plan(cfg.with_overrides({"intraday": {"short_legs_from_equity": 900000}}), cal, mk(LONG_CALL, lots=1), DAY, facts(),
                   costs)["lots_fit"] == 1                                                      # a pure long needs no margin floor
    assert "not paper" in " ".join(OV.plan(cfg.with_overrides({"account": {"mode": "live"}}), cal, t, DAY, facts(), costs)["reasons"])
    assert "not a setup this spec covers" in " ".join(OV.plan(cfg, cal, mk(LONG_CALL, lots=1, setup="exploration"), DAY, facts(), costs)["reasons"])


# ---- the ledger, the 09:20 mark and the evidence gate -------------------------------------------------------------------------------------------------
def seed(ledger, setup, ds, sessions=None, un=0):
    """Candidates with an exit and a mark: one per d (rupees per lot at 1 lot), spread over `sessions` days."""
    for i, d in enumerate(ds):
        day = dt.date(2026, 6, 1) + dt.timedelta(days=i % (sessions or len(ds)))
        ledger.append({"event": "candidate", "id": f"{setup}-{i}", "setup": setup, "day": str(day), "next_day": str(day + dt.timedelta(days=1)),
                       "lots": 1})
        ledger.append({"event": "exit", "id": f"{setup}-{i}", "pnl": 0.0})
        ledger.append({"event": "mark", "id": f"{setup}-{i}", "carry_pnl": float(d)})
    for j in range(un):
        ledger.append({"event": "unmarked", "id": f"u{j}", "setup": setup})


def hist_file(folder, setup="orb", **kw):
    row = {"n": 400, "mean": 300.0, "sd": 2000.0, "t": 3.0, "mean_older": 250.0, "mean_newest": 400.0, **kw}
    (folder).mkdir(parents=True, exist_ok=True)
    (folder / f"{SPEC['name']}-{SPEC['_hash']}.json").write_text(json.dumps({"spec": SPEC["_hash"], "setups": {setup: row}}))
    return row


def test_the_history_rule_is_the_specs_and_recomputed_not_trusted(tmp_path):
    for bad in ({"n": 99}, {"t": 2.32}, {"mean": -1.0}, {"mean_older": -1.0}, {"mean_newest": 0.0}):
        hist_file(tmp_path, **bad, **{"passed": True})                  # a result that says passed but whose numbers do not
        assert OV.history(SPEC, "orb", tmp_path)[0] == "failed", bad
    hist_file(tmp_path)
    assert OV.history(SPEC, "orb", tmp_path)[0] == "passed"
    assert OV.history(SPEC, "vwap_trend", tmp_path) == ("absent", None)             # a setup the file does not hold
    assert OV.history(SPEC, "orb", tmp_path / "nowhere") == ("absent", None)        # no file
    f = tmp_path / f"{SPEC['name']}-{SPEC['_hash']}.json"
    f.write_text(json.dumps({"spec": "000000000000", "setups": {"orb": {"n": 400, "mean": 1, "t": 9, "mean_older": 1, "mean_newest": 1}}}))
    assert OV.history(SPEC, "orb", tmp_path) == ("absent", None)                    # another spec's result is nothing
    f.write_text("{not json")
    assert OV.history(SPEC, "orb", tmp_path) == ("absent", None)


def test_the_forward_rule(tmp_path):
    led = OV.Ledger(tmp_path / "l.jsonl", SPEC)
    row = hist_file(tmp_path)
    seed(led, "orb", [100.0] * 10)
    assert OV.forward(led, "orb", row)["status"] == "collecting"                    # n < 30
    led2 = OV.Ledger(tmp_path / "l2.jsonl", SPEC)
    seed(led2, "orb", list(np.random.default_rng(1).normal(400, 300, 30)))
    f = OV.forward(led2, "orb", row)
    assert f["n"] == 30 and f["status"] == "passed" and f["t"] >= 1.645
    led3 = OV.Ledger(tmp_path / "l3.jsonl", SPEC)
    seed(led3, "orb", list(np.random.default_rng(2).normal(-50, 300, 30)))
    assert OV.forward(led3, "orb", row)["status"] == "failed"                        # a mean at or below zero at 30
    led4 = OV.Ledger(tmp_path / "l4.jsonl", SPEC)
    seed(led4, "orb", list(np.random.default_rng(3).normal(5, 300, 60)))
    assert OV.forward(led4, "orb", row)["status"] == "failed"                        # 60 and still not there
    led5 = OV.Ledger(tmp_path / "l5.jsonl", SPEC)
    seed(led5, "orb", list(np.random.default_rng(1).normal(400, 300, 30)), un=20)
    assert OV.forward(led5, "orb", row)["status"] == "failed"                        # 40% unmarked: void
    led6 = OV.Ledger(tmp_path / "l6.jsonl", SPEC)
    seed(led6, "orb", list(np.random.default_rng(1).normal(400, 300, 30)))
    assert OV.forward(led6, "orb", dict(row, mean=9000.0, sd=100.0))["status"] == "collecting"      # inconsistent: not passed ...
    led7 = OV.Ledger(tmp_path / "l7.jsonl", SPEC)
    seed(led7, "orb", list(np.random.default_rng(1).normal(400, 300, 60)))
    assert OV.forward(led7, "orb", dict(row, mean=9000.0, sd=100.0))["status"] == "failed"          # ... and at 60 it is final




def test_the_mark_prices_the_exit_side_of_real_quotes():
    costs = CostModel(Config.load(DEFAULT_CONFIG))
    ch = pd.DataFrame({"ce_bid": [95.0, 38.0], "ce_ask": [96.0, 39.0], "pe_bid": [0.0, 0.0], "pe_ask": [0.0, 0.0]}, index=[25000.0, 25200.0])
    ch.attrs.update(source="kotak", ts=pd.Timestamp("2026-09-29 09:21", tz=IST))
    rec = {"lots": 2, "lot": LOT, "underlying": "NIFTY", "entry_fees": 100.0,
           "legs": [{"right": "CE", "strike": 25000.0, "qty": LOT, "entry": 100.0, "expiry": str(EXP)},
                    {"right": "CE", "strike": 25200.0, "qty": -LOT, "entry": 40.0, "expiry": str(EXP)}]}
    pnl = OV.mark_pnl(rec, ch, costs, ticks=1.0)
    sell, buy = 95.0 - costs.tick, 39.0 + costs.tick                     # long sold at the bid, short bought at the ask, a tick worse
    gross = 2 * LOT * ((sell - 100.0) - (buy - 40.0))
    fees = costs.fees(Instrument.option("NIFTY", EXP, 25000.0, "CE", LOT), -2 * LOT, sell)[0] \
        + costs.fees(Instrument.option("NIFTY", EXP, 25200.0, "CE", LOT), 2 * LOT, buy)[0]
    assert pnl == pytest.approx(gross - 100.0 - fees)
    ch.loc[25200.0, "ce_ask"] = 0.0                                       # an unpriced leg: no mark, never filled in
    assert OV.mark_pnl(rec, ch, costs) is None
    now = pd.Timestamp("2026-09-29 09:21", tz=IST)
    assert OV.usable_chain(ch, now)
    assert not OV.usable_chain(ch, pd.Timestamp("2026-09-29 09:31", tz=IST))
    ch.attrs["source"] = "model"
    assert not OV.usable_chain(ch, now)


# ---- the history test (research/overnight_carry.py) -----------------------------------------------------------------------------------------------------------








def test_the_gate_is_computed_and_shown_but_apply_is_not_implemented_in_phase_1(tmp_path):
    led = OV.Ledger(tmp_path / "l.jsonl", SPEC)
    hist_file(tmp_path)
    assert OV.effective("shadow", SPEC, led, "orb", tmp_path) == ("shadow", "")
    assert OV.effective("off", SPEC, led, "orb", tmp_path) == ("off", "")
    mode, why = OV.effective("apply", SPEC, led, "orb", tmp_path)
    assert mode == "shadow" and "not implemented" in why and "history passed" in why
    seed(led, "orb", list(np.random.default_rng(1).normal(400, 300, 30)), sessions=4)       # forward passes, but only 4 sessions
    g = OV.gate(SPEC, led, "orb", tmp_path)
    assert g["history"] == "passed" and g["forward"] == "passed" and g["sessions"] == 4 and not g["met"]
    led2 = OV.Ledger(tmp_path / "l2.jsonl", SPEC)
    seed(led2, "orb", list(np.random.default_rng(1).normal(400, 300, 30)), sessions=5)
    assert OV.gate(SPEC, led2, "orb", tmp_path)["met"]                                       # met is a fact about the record ...
    assert OV.effective("apply", SPEC, led2, "orb", tmp_path)[0] == "shadow"                  # ... and still nothing carries
    assert not OV.gate(SPEC, led2, "vwap_trend", tmp_path)["met"]                            # the gate is per setup


def test_a_chain_stamped_on_another_date_is_not_usable():
    ch = pd.DataFrame({"ce_bid": [95.0]}, index=[25000.0])
    now = pd.Timestamp("2026-09-29 09:21", tz=IST)
    ch.attrs.update(source="kotak", ts=pd.Timestamp("2026-09-28 09:21", tz=IST))
    assert not OV.usable_chain(ch, now)
    ch.attrs["ts"] = pd.Timestamp("2026-09-29 09:21", tz=IST)
    assert OV.usable_chain(ch, now)


def test_duplicate_candidate_rows_count_once(tmp_path):
    led = OV.Ledger(tmp_path / "overnight_carry_v1.jsonl")
    seed(led, "orb", [5.0, 7.0])
    led.append({"event": "candidate", "id": "orb-0", "setup": "orb", "day": "2026-06-01", "next_day": "2026-06-02", "lots": 1})
    rows = led.pairs("orb")
    assert [r["id"] for r in rows] == ["orb-0", "orb-1"]
