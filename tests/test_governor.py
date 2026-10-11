"""The risk governor (quantdesk/intraday/governor.py): pure functions that can only ever TIGHTEN the intraday risk limits,
inside a hard envelope, shipped in shadow mode (computed and journaled, no effect on trading)."""
import ast
import copy
import datetime as dt
import json
import logging
import math
import random
from pathlib import Path

import pandas as pd
import pytest

import quantdesk.intraday.engine as engine_mod
from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.core.types import Trade
from quantdesk.intraday import governor as gov
from quantdesk.intraday.engine import IntradayEngine, run_live, run_replay
from quantdesk.intraday.feeds import IST, ReplayFeed
from quantdesk.intraday.risk import IntradayRisk
from quantdesk.intraday.sim import IntradayBroker
from quantdesk.intraday.synthetic import simulate_sessions
from quantdesk.journal.journal import Journal

BASE = {"risk_per_trade": 0.025, "max_trades": 4, "max_open": 2, "max_exposure": 0.5, "daily_loss": 0.05}
CEIL = {"risk_per_trade": 0.025, "max_trades_per_day": 4, "max_open": 2, "daily_loss_pct": 0.05, "max_total_outlay": 0.5}
GC = gov.settings({"mode": "tighten", "floor": 0.25, "start_cap": 0.5, "ceilings": CEIL})
T0 = pd.Timestamp("2026-09-28 10:00", tz=IST)
OBS = {"equity": 500000.0, "range_pct": None, "fc_sigma30_pct": None, "vix": None, "feed_events": 0, "stale": False}
FIELDS = list(BASE)


def fresh(gc=GC, now=T0, base=BASE):
    return gov.new_state(now.date(), gc, base)


def tick(st, now=T0, gc=GC, base=BASE, **obs):
    return gov.tick(st, {**OBS, **obs}, base, gc, now)


# ---- config -----------------------------------------------------------------------------------------------
def test_config_ceilings_are_exactly_todays_risk_values(cfg):
    g, r = cfg.get("intraday.governor"), cfg.get("intraday.risk")
    assert g["mode"] == "shadow" and g["floor"] == 0.25 and g["start_cap"] == 0.5
    assert g["ceilings"] == {"risk_per_trade": r["risk_per_trade"], "max_trades_per_day": r["max_trades_per_day"],
                             "max_open": r["max_open"], "daily_loss_pct": r["daily_loss_limit"],
                             "max_total_outlay": r["max_total_outlay"]}
    assert g["ceilings"] == CEIL                                   # 2.5%, 4 trades, 2 open, 5% day, 50% outlay: today's values
    rk = IntradayRisk(cfg)
    assert (rk.risk_per_trade, rk.max_trades, rk.max_open, rk.daily_loss, rk.max_exposure) == (0.025, 4, 2, 0.05, 0.5)


def test_settings_fail_safe():
    assert gov.settings(None)["mode"] == "off" and gov.settings({"mode": "turbo"})["mode"] == "off"
    assert gov.settings({"mode": "tighten", "floor": 7, "start_cap": 9})["floor"] <= 1
    assert gov.settings({"mode": "tighten", "start_cap": 9})["start_cap"] <= 1


# ---- the rules --------------------------------------------------------------------------------------------
def test_s_r_over_the_last_twenty_closed_trades():
    assert gov.s_r([]) == 0.5
    assert gov.s_r([1.0] * 20) == 1.0 and gov.s_r([-1.0] * 20) == 0.25
    assert gov.s_r([1.0, 1.0]) == pytest.approx(0.5 + 2 / 12)
    assert gov.s_r([-5.0] * 30 + [1.0] * 20) == 1.0                    # only the last 20 count
    assert gov.s_r([-1.0, 0.4, 0.3]) == pytest.approx(0.5 - 0.3 / 13)


def test_s_dd_from_peak_to_date_drawdown():
    assert gov.s_dd(500000, 500000) == 1.0 and gov.s_dd(510000, 500000) == 1.0 and gov.s_dd(None, 500000) == 1.0
    assert gov.s_dd(475000, 500000) == pytest.approx(0.5)
    assert gov.s_dd(450000, 500000) == 0.25 and gov.s_dd(300000, 500000) == 0.25


def test_s_vol_range_vs_forecast_or_vix_vs_median():
    exp = gov.RANGE_PER_SIGMA * 0.5                                    # forecast 30-minute range for sigma_30 = 0.5%
    assert gov.s_vol(1.5 * exp * 1.01, 0.5, None, None) == 0.7
    assert gov.s_vol(1.5 * exp * 0.99, 0.5, None, None) == 1.0
    assert gov.s_vol(None, 0.5, 18.1, 12.0) == 0.7 and gov.s_vol(None, None, 18.0, 12.0) == 1.0
    assert gov.s_vol(None, None, None, None) == 1.0 and gov.s_vol(9.9, None, 30.0, None) == 1.0   # unavailable = neutral
    assert gov.s_vol(9.9, 0.0, float("nan"), 0.0) == 1.0
    h = {f"2026-09-{d:02d}": 12.0 + d for d in range(1, 10)}
    assert gov.vix_median(h, dt.date(2026, 9, 28)) is None             # 9 sessions: not a 20-session median yet
    h["2026-09-10"] = 5.0
    assert gov.vix_median(h, dt.date(2026, 9, 28)) == pytest.approx(16.5)
    assert gov.vix_median(h, dt.date(2026, 9, 10)) is None             # today's own entry is not history


def test_scale_is_max_floor_min_cap_sr_x_sdd_svol():
    st = fresh()
    s, parts = gov.scale(st, {**OBS}, GC)
    assert s == 0.5 and parts["binding"] == "s_cap"                    # no record yet: s_R = 0.5, cap 0.5
    st["recent_r"], st["peak_equity"] = [-1.0] * 20, 500000.0            # a bad record and a drawdown: down to the floor
    s, parts = gov.scale(st, {**OBS, "equity": 400000.0}, GC)
    assert s == 0.25 and parts["binding"] == "floor"
    st["recent_r"] = [1.0] * 20
    gc1 = gov.settings({"mode": "tighten", "start_cap": 1.0, "ceilings": CEIL})
    st = fresh(gc1); st["recent_r"] = [1.0] * 20
    assert gov.scale(st, {**OBS}, gc1)[0] == 1.0
    assert gov.scale(st, {**OBS, "vix": 20.0, "vix_med": 12.0}, gc1)[0] == 0.7


def test_the_cap_follows_the_config_down_but_nothing_lifts_it_above_start_cap():
    st = fresh(); st["recent_r"] = [1.0] * 20
    assert gov.scale({**st, "s_cap": 0.3}, OBS, GC)[0] == 0.3            # a persisted lower cap holds
    assert gov.scale({**st, "s_cap": 0.9}, OBS, GC)[0] == 0.5            # earn-up is not built: a higher one is not honoured
    assert gov.scale(st, OBS, gov.settings({"mode": "tighten", "start_cap": 0.3, "ceilings": CEIL}))[0] == 0.3   # lowered in config


def test_the_scale_is_quantised_down_never_up():
    st = fresh(gov.settings({"mode": "tighten", "start_cap": 1.0, "ceilings": CEIL}))
    st["recent_r"], st["peak_equity"] = [1.0] * 20, 500000.0
    for eq in (499000, 497000, 490000, 480000):
        s, _ = gov.scale(st, {**OBS, "equity": float(eq)}, GC)
        raw = gov.s_dd(eq, 500000)
        assert s <= max(raw, 0.25) + 1e-9 and abs(s / gov.STEP - round(s / gov.STEP)) < 1e-9


def test_mapping_of_s_to_limits():
    L = lambda s, unrel=False: gov.limits(BASE, s, unrel, GC)
    assert L(1.0) == BASE
    assert L(0.5) == {"risk_per_trade": 0.0125, "max_trades": 2, "max_open": 2, "max_exposure": 0.25, "daily_loss": 0.025}
    a = L(0.25)
    assert (a["risk_per_trade"], a["max_trades"], a["max_open"], a["max_exposure"], a["daily_loss"]) == (0.00625, 1, 1, 0.125, 0.025)
    assert L(0.45)["max_open"] == 1 and L(0.55)["max_open"] == 2
    assert L(0.7)["daily_loss"] == pytest.approx(0.035) and L(0.7)["max_trades"] == 3     # round(2.8)
    u = L(0.5, True)                                                    # unreliable feed: one position, half size, half exposure
    assert (u["max_open"], u["risk_per_trade"], u["max_exposure"], u["max_trades"]) == (1, 0.00625, 0.125, 2)


def test_limits_are_clamped_to_min_of_cfg_and_ceiling():
    loose = {"risk_per_trade": 0.05, "max_trades": 9, "max_open": 5, "max_exposure": 0.9, "daily_loss": 0.2}
    assert gov.limits(loose, 1.0, False, GC) == BASE                     # looser cfg than the ceiling: the ceiling wins
    tight = {"risk_per_trade": 0.01, "max_trades": 1, "max_open": 1, "max_exposure": 0.1, "daily_loss": 0.01}
    assert gov.limits(tight, 1.0, False, GC) == tight                    # tighter cfg than the ceiling: cfg wins
    zero = {**BASE, "max_trades": 0}
    assert gov.limits(zero, 0.25, False, GC)["max_trades"] == 0          # max(1, ...) never lifts a cfg of 0
    assert gov.limits({**BASE, "max_exposure": None}, 0.5, False, GC)["max_exposure"] == 0.25      # no cfg cap: bounded by the ceiling
    assert gov.limits({**BASE, "max_exposure": None}, 0.5, False, gov.settings({"mode": "tighten"}))["max_exposure"] is None


# ---- stand-downs -----------------------------------------------------------------------------------------
def test_day_standdown_after_exactly_three_straight_losses():
    st = fresh()
    st = gov.on_close(st, -100.0, -0.5, T0, GC)
    st = gov.on_close(st, -100.0, -0.5, T0 + pd.Timedelta(minutes=10), GC)
    st, dec = tick(st, T0 + pd.Timedelta(minutes=11))
    assert st["standdown_until"] is None and dec["hold"] is None        # two losses: the 30-minute cooldown in risk.py, not ours
    st = gov.on_close(st, 50.0, 0.2, T0 + pd.Timedelta(minutes=12), GC)  # a win resets the streak
    st = gov.on_close(st, -1.0, -0.1, T0 + pd.Timedelta(minutes=20), GC)
    st = gov.on_close(st, -1.0, -0.1, T0 + pd.Timedelta(minutes=30), GC)
    assert st["standdown_until"] is None
    st = gov.on_close(st, -1.0, -0.1, T0 + pd.Timedelta(minutes=40), GC)
    assert pd.Timestamp(st["standdown_until"]) == pd.Timestamp("2026-09-28 23:59:59", tz=IST)
    st, dec = tick(st, T0 + pd.Timedelta(minutes=41))
    assert dec["hold"] and "3 straight losing trades" in dec["hold"]["why"]
    assert any(c["field"] == "standdown_until" and c["rule"] == "day_standdown" for c in dec["changes"])
    st, dec = tick(st, pd.Timestamp("2026-09-29 09:30", tz=IST))        # next session: clean
    assert st["standdown_until"] is None and dec["hold"] is None and st["day"]["consec"] == 0


def test_entry_pause_when_mean_slippage_of_last_three_entries_exceeds_7_5_percent():
    st = fresh()
    for i, slip in enumerate((0.20, 0.08)):
        st = gov.on_open(st, slip, T0 + pd.Timedelta(minutes=i), GC)
    assert st["standdown_until"] is None                                 # two entries: not enough
    st = gov.on_open(st, 0.0, T0 + pd.Timedelta(minutes=2), GC)          # mean 0.0933 > 0.075
    assert pd.Timestamp(st["standdown_until"]) == T0 + pd.Timedelta(minutes=62) and st["standdown_why"].startswith("entry_pause")
    st2 = fresh()
    for i, slip in enumerate((0.075, 0.075, 0.075)):                     # exactly 7.5%: not "exceeds"
        st2 = gov.on_open(st2, slip, T0 + pd.Timedelta(minutes=i), GC)
    assert st2["standdown_until"] is None
    st3 = fresh()
    for i, slip in enumerate((0.225, 0.0, 0.0, 0.2)):                    # the last three average 6.7% (all four, 10.6%): no pause
        st3 = gov.on_open(st3, slip, T0 + pd.Timedelta(minutes=i), GC)
    assert st3["standdown_until"] is None
    st, dec = tick(st, T0 + pd.Timedelta(minutes=61))
    assert dec["hold"] is not None                                       # 61 min after the 3rd entry's minute 2 → still inside
    st, dec = tick(st, T0 + pd.Timedelta(minutes=62))
    assert dec["hold"] is None                                           # exactly at +60: over


def test_unreliable_feed_three_warn_events_or_any_stale_halt_until_the_close():
    st, dec = tick(fresh(), feed_events=2)
    assert not dec["unreliable"] and dec["limits"]["max_open"] == 2
    st, dec = tick(st, T0 + pd.Timedelta(minutes=1), feed_events=3)
    assert dec["unreliable"] and dec["limits"]["max_open"] == 1
    assert dec["limits"]["risk_per_trade"] == pytest.approx(0.0125 * 0.5) and dec["limits"]["max_exposure"] == pytest.approx(0.25 * 0.5)
    st, dec = tick(st, T0 + pd.Timedelta(minutes=2), feed_events=0)      # sticky: until the close
    assert dec["unreliable"]
    assert any(c["field"] == "unreliable_feed" and c["new"] is True and c["rule"] == "unreliable_feed" for c in (
        tick(fresh(), feed_events=5)[1]["changes"]))
    st, dec = tick(fresh(), stale=True)                                  # one stale-feed halt is enough
    assert dec["unreliable"]
    st, dec = tick(st, pd.Timestamp("2026-09-29 09:30", tz=IST))         # the next session starts clean
    assert not dec["unreliable"]


def test_entry_slippage_is_fill_vs_plan_legs():
    plan = [(24000, "CE", 1, 100.0, 12.0, 0.4)]
    assert gov.entry_slippage(plan, [108.0]) == pytest.approx(0.08)
    assert gov.entry_slippage(plan, [95.0]) == pytest.approx(-0.05)
    spread = [(24000, "CE", -1, 100.0, 12.0, 0.4), (24200, "CE", 1, 40.0, 12.0, 0.2)]     # a credit: sold 100, bought 40
    assert gov.entry_slippage(spread, [95.0, 42.0]) == pytest.approx((-53 + 60) / 60)
    assert gov.entry_slippage(spread, [100.0, 40.0]) == pytest.approx(0.0)
    assert gov.entry_slippage([], []) is None and gov.entry_slippage(plan, [1.0, 2.0]) is None
    assert gov.entry_slippage([(1, "CE", 1, 0.0, 0, 0)], [1.0]) is None


def test_realised_range_pct():
    assert gov.realised_range_pct([101, 105, 103], [99, 100, 98], 100.0) == pytest.approx(7.0)
    assert gov.realised_range_pct([], [], 100.0) is None and gov.realised_range_pct([1], [2], 0.0) is None


# ---- journaling: changes only ----------------------------------------------------------------------------------
def test_tick_reports_changes_only_with_rule_field_old_new_reason_evidence_and_caps_the_log():
    st, dec = tick(fresh())
    ch = {c["field"]: c for c in dec["changes"]}
    assert set(ch) == {"risk_per_trade", "max_trades", "max_exposure", "daily_loss"}      # s = 0.5: max_open stays 2
    c = ch["risk_per_trade"]
    assert (c["old"], c["new"], c["rule"]) == (0.025, 0.0125, "s_cap")
    assert "scale 0.50" in c["reason"] and {"scale", "s_R", "s_DD", "s_vol", "n_R", "dd"} <= set(c["evidence"])
    st2, dec2 = tick(st, T0 + pd.Timedelta(minutes=1))                    # nothing moved: nothing reported
    assert dec2["changes"] == []
    for i in range(150):                                                  # force many changes: alternate heat on and off
        st2, dec2 = tick(st2, T0 + pd.Timedelta(minutes=2 + i), equity=500000.0 - (i % 2) * 40000)
    assert len(st2["log"]) == 100 and st2["last_change"]
    json.dumps(st2)                                                       # the state is plain JSON


def test_state_shape():
    st, _ = tick(fresh())
    assert {"s_cap", "since", "last_change", "standdown_until", "day", "log"} <= set(st)
    assert st["s_cap"] == 0.5 and st["since"] == "2026-09-28"


# ---- the envelope: a property test ------------------------------------------------------------------------------
def _junk(rng, good):
    r = rng.random()
    return good if r > 0.15 else rng.choice([None, float("nan"), float("inf"), -1.0, 0.0, "x"])


def test_property_no_limit_ever_exceeds_min_cfg_ceiling_and_scale_never_drops_below_the_floor():
    """hypothesis is not in requirements.txt: a seeded loop of 2000 random sequences of trades, drawdowns, slippage,
    VIX and feed events (some of them garbage)."""
    for seed in range(2000):
        rng = random.Random(seed)
        base = {"risk_per_trade": rng.uniform(0.001, 0.06), "max_trades": rng.randint(0, 8), "max_open": rng.randint(0, 4),
                "max_exposure": rng.choice([None, rng.uniform(0.05, 1.0)]), "daily_loss": rng.uniform(0.005, 0.1)}
        ceil = {"risk_per_trade": rng.choice([None, base["risk_per_trade"] * rng.uniform(0.3, 2)]),
                "max_trades_per_day": rng.choice([None, rng.randint(0, 8)]), "max_open": rng.choice([None, rng.randint(0, 4)]),
                "daily_loss_pct": rng.choice([None, rng.uniform(0.005, 0.1)]), "max_total_outlay": rng.choice([None, rng.uniform(0.05, 1)])}
        gc = gov.settings({"mode": "tighten", "floor": rng.choice([0.0, 0.1, 0.25, 0.5, 1.0]), "start_cap": rng.uniform(0, 1.5),
                           "ceilings": {k: v for k, v in ceil.items() if v is not None}})
        cap = {"risk_per_trade": ceil["risk_per_trade"], "max_trades": ceil["max_trades_per_day"], "max_open": ceil["max_open"],
               "max_exposure": ceil["max_total_outlay"], "daily_loss": ceil["daily_loss_pct"]}
        now = T0
        st = gov.new_state(now.date(), gc, base)
        eq, peak = 500000.0, 500000.0
        for _ in range(rng.randint(1, 40)):
            now += pd.Timedelta(minutes=rng.randint(1, 30))
            if now.date() != T0.date() and rng.random() < 0.5:
                now = T0 + pd.Timedelta(minutes=rng.randint(1, 300))
            kind = rng.choice(["tick", "tick", "close", "open"])
            if kind == "close":
                st = gov.on_close(st, _junk(rng, rng.uniform(-5000, 5000)), _junk(rng, rng.uniform(-3, 3)), now, gc)
            elif kind == "open":
                st = gov.on_open(st, _junk(rng, rng.uniform(-0.1, 0.4)), now, gc)
            else:
                eq = max(1.0, eq * rng.uniform(0.97, 1.02))
                obs = {"equity": _junk(rng, eq), "range_pct": _junk(rng, rng.uniform(0, 3)), "fc_sigma30_pct": _junk(rng, rng.uniform(0.05, 1)),
                       "vix": _junk(rng, rng.uniform(8, 40)), "vix_med": _junk(rng, rng.uniform(10, 20)),
                       "feed_events": rng.choice([0, 0, 1, 3, 7]), "stale": rng.random() < 0.05}
                st, dec = gov.tick(st, obs, base, gc, now)
                assert gc["floor"] - 1e-12 <= dec["s"] <= 1.0 + 1e-12, (seed, dec["s"])
                for k, v in dec["limits"].items():
                    bound = min((x for x in (base[k], cap[k]) if x is not None), default=None)      # min(cfg, ceiling)
                    assert (v is None) if bound is None else (v is not None and 0 <= v <= bound + 1e-12), (seed, k, v, bound)
                lim, hold, _ = gov.effective(dec, "tighten", "paper", now)
                assert lim == dec["limits"]
                assert gov.effective(dec, "tighten", "live", now) == (None, None, "")
                assert gov.effective(dec, "shadow", "paper", now) == (None, None, "")
                assert len(st["log"]) <= 100
            json.dumps(st)


def test_a_larger_cfg_value_can_never_be_raised_by_the_governor():
    """there is no code path from any input to a limit above min(cfg, ceiling), including the maximally friendly one"""
    gc = gov.settings({"mode": "tighten", "floor": 1.0, "start_cap": 1.0, "ceilings": CEIL})
    st = fresh(gc); st["recent_r"] = [9.0] * 20
    st, dec = tick(st, gc=gc, equity=900000.0)
    assert dec["s"] == 1.0 and dec["limits"] == BASE
    rk = IntradayRisk(Config.load(DEFAULT_CONFIG))
    base = dict(rk.base_limits)
    rk.apply_limits({k: 10 * v for k, v in base.items()}, None, "")      # even a (buggy) caller cannot loosen the risk engine
    assert {k: getattr(rk, k) for k in base} == base


# ---- the risk engine's side of the hook ---------------------------------------------------------------------------
def test_apply_limits_and_the_hold_gate(cfg):
    rk = IntradayRisk(cfg)
    rk.reset(dt.date(2026, 9, 28), 500000)
    base = dict(rk.base_limits)
    ok = rk.gate(T0, 500000, [], "NIFTY")
    assert ok == []
    rk.apply_limits(gov.limits(BASE, 0.5, False, GC), T0 + pd.Timedelta(minutes=30), "entry_pause")
    assert (rk.risk_per_trade, rk.max_trades, rk.max_open, rk.max_exposure, rk.daily_loss) == (0.0125, 2, 2, 0.25, 0.025)
    assert any("entry_pause" in w for w in rk.gate(T0, 500000, [], "NIFTY"))
    assert not any("entry_pause" in w for w in rk.gate(T0 + pd.Timedelta(minutes=30), 500000, [], "NIFTY"))
    rk.apply_limits(None)
    assert {k: getattr(rk, k) for k in base} == base and rk.hold_until is None and rk.gate(T0, 500000, [], "NIFTY") == []


def test_scaling_size_does_not_change_the_r_multiple():
    """R = pnl / planned risk of the lots actually traded, so a half-size trade that makes half the money is the same R"""
    mk = lambda lots: Trade(id="x", strategy="s", family="intraday", symbol="NIFTY", direction=1, kind="options", legs=[], units=lots,
                            opened_at=T0, entry_underlying=24000.0, initial_risk=1000.0 * lots, pnl=400.0 * lots)
    assert mk(1).r_multiple == mk(4).r_multiple == pytest.approx(0.4)
    r = [mk(1).r_multiple] * 5 + [mk(4).r_multiple] * 5
    assert gov.s_r(r) == gov.s_r([mk(2).r_multiple] * 10)


# ---- imports ------------------------------------------------------------------------------------------------------
def test_the_module_imports_no_config_writer_kill_switch_account_mode_setter_or_credentials():
    src = Path(gov.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            names.add(("." * n.level) + (n.module or ""))
            names |= {f"{n.module}.{a.name}" for a in n.names}
    allowed = {"__future__", "copy", "datetime", "logging", "math", "statistics", "typing"}
    assert {x.split(".")[0] for x in names} <= allowed, f"unexpected imports: {sorted(names)}"       # stdlib only, nothing from quantdesk
    assert not any(x.startswith(".") or "quantdesk" in x for x in names)
    forbidden = ("config", "kill", "credential", "secret", "token", "kotak", "kite", "keyring", "os", "subprocess", "pathlib", "shutil", "yaml", "journal")
    assert not [x for x in names if any(f == x.split(".")[0] or f in x.lower().split(".") for f in forbidden)]
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not attrs & {"environ", "getenv", "open", "write_text", "unlink", "set_state", "KILL", "exec", "eval", "__import__"}


def test_the_engine_halts_and_gates_do_not_mention_the_governor():
    import inspect
    for fn in (IntradayEngine._blocked, IntradayEngine._kill_switch, IntradayEngine.enter_safe_mode):
        assert "gov" not in inspect.getsource(fn).lower()
    from quantdesk.autolearn.live import LiveLearner
    assert "gov" not in inspect.getsource(LiveLearner.plan_gate).lower()


# ---- the engine ----------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sessions():
    cal = TradingCalendar(Config.load(DEFAULT_CONFIG).holidays())
    days = [d.date() for d in cal.trading_days("2026-08-17", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days


@pytest.fixture
def sim_clock(monkeypatch):
    feeds = []
    monkeypatch.setattr(engine_mod.time, "sleep", lambda s: [f.advance() for f in feeds])
    return feeds


def _cfg(tmp, mode, account="paper", **gov_over):
    return Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "runtime")}, "account": {"mode": account},
                                                  "intraday": {"governor": {"mode": mode, **gov_over}}})


def _engine(cfg, bars, day, journal=None, broker=None):
    return IntradayEngine(cfg, ReplayFeed(bars, day), "model", journal or Journal(), broker or IntradayBroker(cfg, starting_cash=500000),
                          say=None)


def _lims(eng):
    r = eng.risk
    return (r.risk_per_trade, r.max_trades, r.max_open, r.max_exposure, r.daily_loss, r.hold_until)


def _replay(cfg, bars, day):
    """a full replay; every limit the risk gate saw is collected"""
    eng = _engine(cfg, bars, day)
    seen, gate = set(), eng.risk.gate

    def spy(*a, **k):
        seen.add(_lims(eng))
        return gate(*a, **k)
    eng.risk.gate = spy
    run_replay(eng)
    eng.seen = seen
    return eng


def _record(eng):
    j = eng.journal
    tr = j.trades().drop(columns=["id"])
    fl = j.df("SELECT ts, qty, price, fees, breakdown FROM fills ORDER BY id")
    de = j.df("SELECT ts, strategy, symbol, action, units, detail FROM decisions ORDER BY id")
    th = j.thoughts().drop(columns=["id"])
    ev = j.df("SELECT ts, level, category, message FROM events WHERE category != 'governor' ORDER BY id")
    return "|".join(x.to_json() for x in (tr, fl, de, th, ev)) + f"|{eng.broker.cash()!r}|{eng.risk.trades_today}|{eng.risk.halted}"


@pytest.fixture(scope="module")
def runs(sessions, tmp_path_factory):
    bars, days = sessions
    out = {}
    for name, mode, acct in (("off", "off", "paper"), ("shadow", "shadow", "paper"), ("live", "tighten", "live"), ("tighten", "tighten", "paper")):
        tmp = tmp_path_factory.mktemp(name)
        out[name] = _replay(_cfg(tmp, mode, acct), bars, days[-1])
    return out


def test_shadow_mode_leaves_trading_byte_identical_and_only_journals(runs):
    off, sh = runs["off"], runs["shadow"]
    assert _record(sh) == _record(off)                                   # trades, fills, decisions, thoughts, events, cash
    assert sh.seen == off.seen == {(0.025, 4, 2, 0.5, 0.05, None)}       # the limits the gate used: today's, every minute
    gev = sh.journal.df("SELECT * FROM events WHERE category='governor'")
    assert len(gev) >= 4 and (gev["level"] == "INFO").all()
    d = json.loads(gev.iloc[0]["data"])
    assert {"rule", "field", "old", "new", "reason", "evidence", "applied", "mode"} <= set(d) and d["applied"] is False and d["mode"] == "shadow"
    assert off.journal.get_state("risk_governor") is None and off.journal.df("SELECT * FROM events WHERE category='governor'").empty
    st = sh.journal.get_state("risk_governor")
    assert {"s_cap", "since", "last_change", "standdown_until", "day", "log"} <= set(st) and 1 <= len(st["log"]) <= 100


def test_live_mode_is_a_noop_that_only_journals_proposals(runs):
    off, live = runs["off"], runs["live"]
    assert _record(live) == _record(off) and live.seen == off.seen
    gev = live.journal.df("SELECT * FROM events WHERE category='governor'")
    assert len(gev) >= 4 and not any(json.loads(x)["applied"] for x in gev["data"])
    assert gov.effective({"limits": BASE, "hold": {"until": "2099-01-01T00:00:00+05:30", "why": "x"}}, "tighten", "live", T0) == (None, None, "")
    assert gov.effective({"limits": BASE, "hold": None}, "tighten", None, T0) == (None, None, "")      # no account.mode: not paper


def test_tighten_mode_uses_the_effective_limits_and_only_tighter_ones(runs):
    t = runs["tighten"]
    base = (0.025, 4, 2, 0.5, 0.05)
    assert t.seen and all(all(a <= b + 1e-12 for a, b in zip(lim[:5], base)) for lim in t.seen)       # never above today's
    assert min(x[0] for x in t.seen) <= 0.0125 + 1e-12 and min(x[1] for x in t.seen) <= 2     # the start cap of 0.5 is in force
    assert not any(x[:5] == base for x in t.seen)                        # ... from the first gate call of the day


def test_any_exception_in_the_governor_means_identity_limits_and_one_log_line(sessions, tmp_path, monkeypatch, caplog):
    bars, days = sessions
    eng = _engine(_cfg(tmp_path, "tighten"), bars, days[-1])
    eng.start_session(days[-1])
    for _ in range(3):
        eng.feed.advance(); eng.step()
    assert _lims(eng)[:5] != (0.025, 4, 2, 0.5, 0.05)                    # tightened...
    monkeypatch.setattr(gov, "_logged", False)
    monkeypatch.setattr(gov, "tick", lambda *a, **k: 1 / 0)
    caplog.set_level(logging.WARNING, logger=gov.log.name)
    for _ in range(6):
        eng.feed.advance(); eng.step()                                    # never raises into step()
        assert _lims(eng) == (0.025, 4, 2, 0.5, 0.05, None)               # ...and identity as soon as the governor fails
    assert len([r for r in caplog.records if r.name == gov.log.name]) == 1
    eng.end_session()                                                     # nor into end_session
    assert len([r for r in caplog.records if r.name == gov.log.name]) == 1


def test_exceptions_in_the_open_close_and_save_hooks_never_reach_the_engine(sessions, tmp_path, monkeypatch):
    bars, days = sessions
    eng = _engine(_cfg(tmp_path, "tighten"), bars, days[-1])
    for fn in ("on_open", "on_close", "entry_slippage"):
        monkeypatch.setattr(gov, fn, lambda *a, **k: 1 / 0)
    run_replay(eng)                                                       # trades open and close regardless
    real = eng.journal.set_state
    monkeypatch.setattr(eng.journal, "set_state", lambda k, v: (_ for _ in ()).throw(OSError("disk")) if k == "risk_governor" else real(k, v))
    eng._persist(ended=True)                                              # a failing governor save never fails the engine's


def test_a_stale_feed_and_three_warn_events_make_the_feed_unreliable_in_the_engine(sessions, tmp_path, monkeypatch):
    bars, days = sessions
    eng = _engine(_cfg(tmp_path, "tighten"), bars, days[-1])
    eng.start_session(days[-1])
    for _ in range(2):
        eng.feed.advance()
    eng.step()
    assert not eng._gov["day"]["unreliable"] and eng.risk.max_open == 2
    now = eng.feed.now()
    for cat, lvl in (("data", "WARN"), ("quotes", "ERROR"), ("chain", "WARN"), ("engine", "INFO")):    # only two count
        eng.journal.event(now, lvl, cat, "x")
    eng._gov_step(now)
    assert not eng._gov["day"]["unreliable"]
    eng.journal.event(now, "CRITICAL", "engine", "x")
    eng._gov_step(now)
    assert eng._gov["day"]["unreliable"] and eng.risk.max_open == 1
    eng2 = _engine(_cfg(tmp_path / "b", "tighten"), bars, days[-1])
    eng2.start_session(days[-1])
    eng2.feed.advance(); eng2.step()
    monkeypatch.setattr(eng2.feed, "realtime_age", lambda now, last: 99.0)                   # a stale-feed halt
    eng2._gov_step(eng2.feed.now())
    assert eng2._gov["day"]["unreliable"] and eng2._gov["day"]["stale"] and eng2.risk.max_open == 1


def test_state_survives_a_restart_and_the_1220_handover(sessions, tmp_path, sim_clock):
    bars, days = sessions
    day = days[-1]
    cfg = _cfg(tmp_path, "tighten")
    j, bstate = Journal(tmp_path / "j.db"), tmp_path / "broker.json"
    t_open = pd.Timestamp(f"{day} 09:30", tz=IST)
    seed = gov.new_state(day, GC, BASE)                           # three straight losses already today: stood down for the day
    for i in range(3):
        seed = gov.on_close(seed, -500.0, -0.5, t_open + pd.Timedelta(minutes=5 * i), GC)
    seed["peak_equity"], seed["s_cap"] = 512345.0, 0.4
    j.set_state("risk_governor", seed)

    feed_a = ReplayFeed(bars, day)
    sim_clock.append(feed_a)
    a = IntradayEngine(cfg, feed_a, "model", j, IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    assert run_live(a, dt.time(12, 20), handover=True).startswith("handed over")
    assert a._gov["s_cap"] == 0.4 and a._gov["peak_equity"] >= 512345.0 and a._gov["standdown_until"] == seed["standdown_until"]
    assert not a.closed and not a.open_trades                             # stood down: nothing traded
    saved = Journal(tmp_path / "j.db").get_state("risk_governor")
    assert saved == json.loads(json.dumps(a._gov))                        # what the second runner will read is what the first held

    feed_b = ReplayFeed(bars, day)
    feed_b.clock = feed_a.clock + pd.Timedelta(minutes=2)
    b = IntradayEngine(cfg, feed_b, "model", Journal(tmp_path / "j.db"), IntradayBroker(cfg, starting_cash=500000, state_path=bstate), say=None)
    b.start_session(day)
    for k in ("s_cap", "since", "standdown_until", "standdown_why", "recent_r", "peak_equity"):
        assert b._gov[k] == saved[k], k
    assert b._gov["log"][:len(saved["log"])] == saved["log"] and b._gov["day"]["consec"] == 3
    assert pd.Timestamp(b.risk.hold_until) == pd.Timestamp(seed["standdown_until"])          # in force before the first step
    assert (b.risk.max_trades, b.risk.max_open) == (1, 1)                # s = 0.35: the three losses in the R record, under the 0.4 cap
    while b.feed.advance():
        b.step()
    b.end_session()
    assert not b.closed and not b.open_trades                             # the stand-down held through the hand-over, to the close
    assert b._gov["since"] == a._gov["since"] and b._gov["s_cap"] == 0.4


def test_a_fresh_engine_restores_nothing_from_a_previous_day(sessions, tmp_path):
    bars, days = sessions
    j = Journal()
    old = gov.new_state(days[-2], GC, BASE)
    for i in range(3):
        old = gov.on_close(old, -1.0, -0.5, pd.Timestamp(f"{days[-2]} 10:0{i}", tz=IST), GC)
    j.set_state("risk_governor", old)
    eng = _engine(_cfg(tmp_path, "tighten"), bars, days[-1], journal=j)
    eng.start_session(days[-1])
    assert eng._gov["standdown_until"] is None and eng._gov["day"]["consec"] == 0 and eng.risk.hold_until is None
    assert eng._gov["recent_r"] == old["recent_r"] and eng._gov["since"] == old["since"]     # the record carries over, the day does not
