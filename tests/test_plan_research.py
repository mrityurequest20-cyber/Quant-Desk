"""Cost-aware, multi-horizon, plan-level research (quantdesk/autolearn/plans.py, policy.py, research.py) and the gate that
keeps unvalidated reads from creating trades.

Evidence rules under test: only `real_point_in_time` outcomes may qualify. Modelled-chain results are scenario analysis
only, never combined with real ones, and never promotion evidence. Stop first when a bar touches both levels, a gap
through the stop costs the gap, and intrabar order is never inferred. The replay uses the engine's own constraints."""
import datetime as dt
import json
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import plans as P
from quantdesk.autolearn.live import LiveLearner
from quantdesk.autolearn.models import Logit
from quantdesk.autolearn.policy import PLAN_FEATURES, PlanPolicy
from quantdesk.autolearn.registry import PromotionRefused, Registry
from quantdesk.autolearn.research import PlanLock, PlanStudy, one_class, replay
from quantdesk.autolearn.validation import WalkForwardConfig, folds, split
from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.calendar import TradingCalendar
from quantdesk.execution.costs import CostModel
from quantdesk.intraday.chains import COLUMNS, IntradayPricer, time_to_expiry
from quantdesk.intraday.playbook import PlanLeg, StrikePicker, TradePlan
from quantdesk.intraday.quant import to_5m
from quantdesk.options.pricing import bs_price

IST = "Asia/Kolkata"


def ts(x):
    return pd.Timestamp(x, tz=IST)


def make_cfg(tmp_path, research=None, intraday=None, **auto):
    a = {"plan_research": {"bootstrap": {"samples": 100, "block_days": 2, "seed": 7}, **(research or {})}, **auto}
    over = {"runtime": {"dir": str(tmp_path / "runtime")}, "autolearn": a}
    if intraday:
        over["intraday"] = intraday
    return Config.load(DEFAULT_CONFIG, overrides=over)


@pytest.fixture
def cfg(tmp_path):
    return make_cfg(tmp_path)


def days_from(start, n, cal):
    return [d.date() for d in cal.trading_days(start, pd.Timestamp(start) + pd.Timedelta(days=n * 2 + 10))][:n]


def market1m(days, seed=0, start=25000.0, sig=0.0007):
    """1-minute random-walk bars."""
    rng = np.random.default_rng(seed)
    frames, S = [], start
    for d in days:
        c = S * np.exp(np.cumsum(rng.normal(0, sig / math.sqrt(5), 375)))
        o = np.r_[S, c[:-1]]
        idx = pd.date_range(f"{d} 09:15", periods=375, freq="1min", tz=IST)
        frames.append(pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0001, "low": np.minimum(o, c) * 0.9999,
                                    "close": c, "volume": 1000.0}, index=idx))
        S = float(c[-1])
    return pd.concat(frames)


def nearest(cal, d):
    return [e for e in cal.expiries(d, 30, 1, True) if (e - d).days >= 1][0]


def book(m1, days, cal, every=2, iv=0.14, half=0.6, symbol="NIFTY", expiry=None):
    """A 'recorded' Kotak book: snapshots every `every` minutes of `expiry` (default: the nearest ≥ 1 calendar day out)."""
    pr = IntradayPricer()
    out = []
    for d in days:
        exp = expiry or nearest(cal, d)
        day = m1[m1.index.date == d]["close"].iloc[::every]
        for t, S in day.items():
            stamp = t + pd.Timedelta(minutes=1)
            T = time_to_expiry(stamp, exp)
            K = round(S / 50) * 50 + 50 * np.arange(-10, 11)
            r = {"ts": stamp, "underlying": symbol, "expiry": pd.Timestamp(exp), "spot": S, "source": "kotak", "strike": K}
            for side in ("ce", "pe"):
                m = bs_price(S, K, T, pr.r, pr.q, iv, side.upper())
                r.update({f"{side}_ltp": m, f"{side}_bid": np.maximum(0.05, np.round((m - half) / 0.05) * 0.05),
                          f"{side}_ask": np.round((m + half) / 0.05) * 0.05, f"{side}_iv": iv * 100, f"{side}_oi": 1.0,
                          f"{side}_doi": 0.0, f"{side}_vol": 1.0})
            out.append(pd.DataFrame(r))
    return pd.concat(out, ignore_index=True)


# ---- the engine's exit order, stop first, no intrabar ordering --------------------------------------------------------
def test_exit_rules_follow_the_engine_and_stop_comes_first():
    rules = P.PlanRules()
    t0 = ts("2026-09-29 10:00")
    times = pd.DatetimeIndex([t0 + pd.Timedelta(minutes=i) for i in range(1, 41)])
    entry, qty = 100.0, 65
    flat = np.full(40, 100.0)
    # a bar whose close is past the target but whose adverse extreme reached the stop: the stop, flagged intrabar
    mc, ma = flat.copy(), flat.copy()
    mc[5], ma[5] = 170.0, 65.0
    assert P.exit_index(entry, qty, 0.0, mc, ma, times, t0, rules, 30) == (5, "premium_stop", True)
    # the favourable extreme never counts: a target only at an observed close
    mc = flat.copy()
    mc[7] = 161.0
    assert P.exit_index(entry, qty, 0.0, mc, flat, times, t0, rules, None)[:2] == (7, "premium_target")
    # the time stop only exits a plan that hasn't made 10% of its premium (the engine's rule): a winner is held
    k, why, _ = P.exit_index(entry, qty, 0.0, flat + 5.0, flat + 5.0, times, t0, rules, 30)
    assert why == "time_exit" and times[k] - t0 >= pd.Timedelta(minutes=30)
    k, why, _ = P.exit_index(entry, qty, 0.0, flat + 15.0, flat + 15.0, times, t0, rules, 30)
    assert why != "time_exit"
    # breakeven: half the target's open profit given back to ≤ 0
    mc = flat.copy()
    mc[3], mc[4] = 135.0, 99.0
    assert P.exit_index(entry, qty, 0.0, mc, np.minimum(mc, flat), times, t0, rules, None)[:2] == (4, "breakeven_stop")


def test_a_gap_through_the_stop_costs_the_gap(cfg):
    cal = TradingCalendar(cfg.holidays())
    rules = P.PlanRules.from_cfg(cfg)
    fees = CostModel(cfg)
    pr = IntradayPricer()
    mb = P.ModelBook("NIFTY", cfg.instrument_spec("NIFTY"), rules, vix5=pd.Series([14.0], index=[ts("2026-09-29 09:15")]),
                     calendar=cal, pricer=pr)
    sim = P.Simulator("NIFTY", 65, rules, fees, pr, model=mb)
    t0 = ts("2026-09-29 10:00")
    ch = mb.chain(t0, 25000.0, dt.date(2026, 10, 6), "3-5")
    plan, _ = P.build_plan(sim.picker, ch, 1, t0, rules)
    # the bar's low gaps far through the stop, its close recovers above it
    idx = pd.DatetimeIndex([t0 + pd.Timedelta(minutes=5 * i) for i in range(1, 5)])
    path = pd.DataFrame({"close": [25000.0, 25010, 25020, 25030], "high": [25005.0, 25015, 25025, 25035],
                         "low": [24400.0, 25000, 25010, 25020], "open": 25000.0}, index=idx)
    o = sim.play(plan, t0, dt.date(2026, 10, 6), path, "3-5", real_entry=False, horizons={"close": None})["close"]
    assert o["exit_reason"] == "premium_stop" and o["intrabar_stop"] and o["exit_ts"] == idx[0]
    assert o["exit_px"] <= plan["entry_px"] * (1 - rules.premium_stop)          # never better than the stop level
    assert o["quote_source"] == "modelled"


# ---- labels: the exact plan, ask in / bid out, adverse ticks, every fee ---------------------------------------------------
def test_real_plan_labels_are_exact_and_point_in_time(cfg):
    cal = TradingCalendar(cfg.holidays())
    day = dt.date(2026, 9, 29)
    m1 = market1m([day], seed=3)
    rec = book(m1, [day], cal, every=1)
    rules = P.PlanRules.from_cfg(cfg)
    fees = CostModel(cfg)
    pr = IntradayPricer()
    sim = P.Simulator("NIFTY", 65, rules, fees, pr, real=P.RealBook(rec, "NIFTY"))
    path = m1[["open", "high", "low", "close"]].copy()
    path.index = path.index + pd.Timedelta(minutes=1)
    dec = pd.DataFrame({"ts": [ts("2026-09-29 10:00"), ts("2026-09-29 11:30")], "symbol": "NIFTY"})
    o = P.outcomes(dec, {"NIFTY": path}, {"NIFTY": sim}, cal, "real", buckets=None)
    assert len(o) and set(o["quote_source"]) == {"real_point_in_time"} and set(o["horizon"]) == set(P.HORIZONS)
    r = o.iloc[0]
    snap = sim.real.at(r["expiry"], r["ts"], rules.pit_max_age_min)
    side = "ce" if r["direction"] > 0 else "pe"
    assert r["entry_px"] == pytest.approx(float(snap.at[r["plan_strike"], f"{side}_ask"]) + rules.adverse_ticks * rules.tick)
    nxt = sim.real.after(r["expiry"], r["exit_ts"], rules.pit_max_age_min)
    if not r["intrabar_stop"]:
        assert r["exit_px"] == pytest.approx(float(nxt.at[r["plan_strike"], f"{side}_bid"]) - rules.adverse_ticks * rules.tick)
    from quantdesk.core.types import Instrument
    inst = Instrument.option("NIFTY", r["expiry"], r["plan_strike"], "CE" if r["direction"] > 0 else "PE", 65)
    f = fees.fees(inst, 65, r["entry_px"])[0] + fees.fees(inst, -65, r["exit_px"])[0]
    assert r["fees"] == pytest.approx(f) and r["net"] == pytest.approx((r["exit_px"] - r["entry_px"]) * 65 - f)
    assert r["net_R"] == pytest.approx(r["net"] / (rules.premium_stop * r["entry_px"] * 65))
    assert r["label_end"] == r["exit_ts"] and r["exit_ts"] > r["ts"]
    assert r["mae"] <= 0 <= r["mfe"]


def test_a_real_entry_with_a_gap_in_the_real_quotes_is_modelled_not_real(cfg):
    cal = TradingCalendar(cfg.holidays())
    day = dt.date(2026, 9, 29)
    m1 = market1m([day], seed=4)
    rec = book(m1, [day], cal, every=1)
    rec = rec[(pd.to_datetime(rec["ts"]) < ts("2026-09-29 10:30")) | (pd.to_datetime(rec["ts"]) > ts("2026-09-29 11:00"))]
    rules = P.PlanRules.from_cfg(cfg)
    sim = P.Simulator("NIFTY", 65, rules, CostModel(cfg), IntradayPricer(), real=P.RealBook(rec, "NIFTY"))
    path = m1[["open", "high", "low", "close"]].copy()
    path.index = path.index + pd.Timedelta(minutes=1)
    o = P.outcomes(pd.DataFrame({"ts": [ts("2026-09-29 10:15")], "symbol": "NIFTY"}), {"NIFTY": path}, {"NIFTY": sim}, cal, "real")
    held_through_gap = o[o["exit_ts"] > ts("2026-09-29 10:42")]
    assert len(held_through_gap) and set(held_through_gap["quote_source"]) == {"modelled"}   # stale marks: not real
    with pytest.raises(ValueError, match="never be combined"):
        one_class(o, "real_point_in_time")                                 # the modelled rows can't ride along


# ---- causality ----------------------------------------------------------------------------------------------------------
def test_quotes_are_causal(cfg):
    cal = TradingCalendar(cfg.holidays())
    day = dt.date(2026, 9, 29)
    m1 = market1m([day], seed=5)
    rec = book(m1, [day], cal, every=3)
    rb = P.RealBook(rec, "NIFTY")
    exp = rb.expiries(day)[0]
    t = ts("2026-09-29 10:01:30")
    snap = rb.at(exp, t, 5)
    assert snap.attrs["ts"] <= t and rb.at(exp, ts("2026-09-29 09:10"), 5) is None
    assert rb.at(exp, t, 0.1) is None                                        # older than the point-in-time limit: unused
    # the entry is the same whether or not the future is in the data
    rules = P.PlanRules.from_cfg(cfg)
    path = m1[["open", "high", "low", "close"]].copy()
    path.index = path.index + pd.Timedelta(minutes=1)
    dec = pd.DataFrame({"ts": [ts("2026-09-29 11:00")], "symbol": "NIFTY"})

    def entry(r):
        sim = P.Simulator("NIFTY", 65, rules, CostModel(cfg), IntradayPricer(), real=P.RealBook(r, "NIFTY"))
        o = P.outcomes(dec, {"NIFTY": path}, {"NIFTY": sim}, cal, "real", horizons={"30m": 30})
        return o[["direction", "plan_strike", "entry_px"]].to_numpy().tolist()
    cut = rec[pd.to_datetime(rec["ts"]) <= ts("2026-09-29 11:00")]
    assert entry(rec) and entry(rec) == entry(cut)                          # nothing after the decision touches the entry
    # bhavcopy IV only from earlier sessions; VIX only from completed bars; spreads only from earlier sessions
    ivt = pd.DataFrame({"date": [dt.date(2026, 9, 28), dt.date(2026, 9, 29)], "expiry": [exp, exp], "atm_iv": [0.12, 0.90],
                        "spot": [25000.0, 25000.0]})
    mb = P.ModelBook("NIFTY", cfg.instrument_spec("NIFTY"), rules, ivt, calendar=cal)
    assert mb.atm_iv(ts("2026-09-29 11:00"), exp) == (0.12, "bhavcopy")
    vix = pd.Series([13.0, 99.0], index=[ts("2026-09-29 10:55"), ts("2026-09-29 11:00")])
    mv = P.ModelBook("NIFTY", cfg.instrument_spec("NIFTY"), rules, None, vix5=vix, calendar=cal)
    assert mv.atm_iv(ts("2026-09-29 11:03"), exp)[0] == pytest.approx(0.13)   # the 11:00 bar isn't complete until 11:05
    st = P.SpreadTable.measure(rec, cal, min_obs=5)
    assert st.pct("NIFTY", P.dte_bucket(cal.trading_days_between(day, exp)), 0.0, 0.012, day) == (0.012, "config")
    assert st.pct("NIFTY", P.dte_bucket(cal.trading_days_between(day, exp)), 0.0, 0.012, dt.date(2026, 9, 30))[1] == "measured"


# ---- dynamic, versioned costs -------------------------------------------------------------------------------------------
def test_costs_are_dynamic_and_versioned(cfg, tmp_path):
    cal = TradingCalendar(cfg.holidays())
    fees = CostModel(cfg)
    from quantdesk.core.types import Instrument
    inst = Instrument.option("NIFTY", dt.date(2026, 10, 6), 25000.0, "CE", 65)
    cheap, rich = fees.fees(inst, -65, 20.0)[0], fees.fees(inst, -65, 200.0)[0]
    assert rich > cheap                                                       # STT and exchange charges scale with premium
    day = dt.date(2026, 9, 29)
    rec = book(market1m([day], seed=6), [day], cal, every=1, half=6.0)   # wider than the config's 1.2% of mid
    rules = P.PlanRules.from_cfg(cfg)
    measured = P.ModelBook("NIFTY", cfg.instrument_spec("NIFTY"), rules, vix5=pd.Series([14.0], index=[ts("2026-09-29 09:15")]),
                           calendar=cal, spreads=P.SpreadTable.measure(rec, cal, min_obs=5))
    flat = P.ModelBook("NIFTY", cfg.instrument_spec("NIFTY"), rules, vix5=pd.Series([14.0], index=[ts("2026-09-29 09:15")]),
                       calendar=cal)
    t = ts("2026-09-30 10:00")
    a, b = measured.chain(t, 25000.0, dt.date(2026, 10, 6), "3-5"), flat.chain(t, 25000.0, dt.date(2026, 10, 6), "3-5")
    assert (a["ce_ask"] - a["ce_bid"]).loc[25000.0] > (b["ce_ask"] - b["ce_bid"]).loc[25000.0]
    v1 = P.cost_model_version(cfg, P.SpreadTable(), rules)
    assert v1 != P.cost_model_version(cfg, P.SpreadTable.measure(rec, cal, min_obs=5), rules)
    other = make_cfg(tmp_path, intraday=None)
    other.data["costs"]["brokerage_per_order"] = 25.0
    assert v1 != P.cost_model_version(other, P.SpreadTable(), rules)


# ---- DTE buckets ---------------------------------------------------------------------------------------------------------
def test_dte_buckets_count_trading_days_and_take_the_nearest_expiry(cfg):
    cal = TradingCalendar(cfg.holidays())
    assert [P.dte_bucket(n) for n in (0, 1, 2, 3, 5, 6, 30)] == ["0", "1", "2", "3-5", "3-5", "6+", "6+"]
    assert cal.trading_days_between(dt.date(2026, 9, 29), dt.date(2026, 10, 6)) == 4   # 2 Oct is a holiday
    rules = P.PlanRules.from_cfg(cfg)
    ivt = pd.DataFrame({"date": [dt.date(2026, 9, 28)] * 3, "expiry": [dt.date(2026, 10, 6), dt.date(2026, 10, 13), dt.date(2026, 10, 27)],
                        "atm_iv": [0.12, 0.13, 0.14], "spot": 25000.0})
    mb = P.ModelBook("NIFTY", cfg.instrument_spec("NIFTY"), rules, ivt, calendar=cal)
    sim = P.Simulator("NIFTY", 65, rules, CostModel(cfg), IntradayPricer(), model=mb)
    m1 = market1m([dt.date(2026, 9, 29)], seed=7)
    path = to_5m(m1)[["open", "high", "low", "close"]]
    path.index = path.index + pd.Timedelta(minutes=5)
    o = P.outcomes(pd.DataFrame({"ts": [ts("2026-09-29 10:00")], "symbol": "NIFTY"}), {"NIFTY": path}, {"NIFTY": sim}, cal, "modelled",
                   horizons={"30m": 30})
    got = o.drop_duplicates("bucket").set_index("bucket")["expiry"].to_dict()
    assert got == {"3-5": dt.date(2026, 10, 6), "6+": dt.date(2026, 10, 13)}   # 27 Oct is also 6+: only the nearest
    assert set(o["quote_source"]) == {"modelled"} and set(o["iv_source"]) == {"bhavcopy"}


# ---- horizons are separate labels; purge and embargo -------------------------------------------------------------------
def test_horizons_are_independent_labels_and_purge_and_embargo_hold(cfg):
    cal = TradingCalendar(cfg.holidays())
    rules = P.PlanRules.from_cfg(cfg)
    mb = P.ModelBook("NIFTY", cfg.instrument_spec("NIFTY"), rules, vix5=pd.Series([14.0], index=[ts("2026-09-29 09:15")]), calendar=cal)
    sim = P.Simulator("NIFTY", 65, rules, CostModel(cfg), IntradayPricer(), model=mb)
    m1 = market1m([dt.date(2026, 9, 29)], seed=8)
    path = to_5m(m1)[["open", "high", "low", "close"]]
    path.index = path.index + pd.Timedelta(minutes=5)
    dec = pd.DataFrame({"ts": pd.date_range("2026-09-29 09:30", "2026-09-29 14:30", freq="30min", tz=IST), "symbol": "NIFTY"})
    o = P.outcomes(dec, {"NIFTY": path}, {"NIFTY": sim}, cal, "modelled", buckets=["3-5"])
    for h, mins in P.HORIZONS.items():
        g = o[o["horizon"] == h]
        te = g[g["exit_reason"] == "time_exit"]
        if mins is None:
            assert te.empty                                                     # close: held to the square-off
        else:
            assert (te["hold_min"] >= mins).all()
    assert (o["exit_ts"].dt.time <= dt.time(15, 15)).all()
    # one horizon's labels never leak into another's training rows
    a, b = o[o["horizon"] == "30m"], o[o["horizon"] == "120m"]
    assert set(a.index).isdisjoint(b.index)
    # purge: a training row whose plan is still open at the test block's start is dropped
    rows = pd.DataFrame({"ts": [ts("2026-09-28 14:00"), ts("2026-09-28 15:00"), ts("2026-09-29 10:00")],
                         "day": ["2026-09-28", "2026-09-28", "2026-09-29"],
                         "label_end": [ts("2026-09-28 14:30"), ts("2026-09-29 10:10"), ts("2026-09-29 10:30")]})
    wf = WalkForwardConfig(folds=1, min_train_days=1, embargo_min=P.horizon_minutes("close"), horizon_min=375)
    f = folds(rows, wf)[0]
    tr, te, info = split(rows, f, wf)
    assert list(tr["ts"]) == [ts("2026-09-28 14:00")] and info["purged"] == 1
    # embargo: training decisions within the horizon before a block's start are dropped too
    tr, _, info = split(rows, {**f, "test_start": ts("2026-09-28 16:00")}, wf)
    assert tr.empty and info["purged"] == 1 and info["embargoed"] == 1
    # and every horizon's embargo is at least the horizon
    st = PlanStudy(cfg, {"bars5": {}, "recorded": None}, root=cfg.runtime_dir / "al", say=None)
    assert {h: st._wf(h).embargo_min for h in P.HORIZONS} == {"30m": 30, "60m": 60, "120m": 120, "close": 375}


# ---- no overlapping trades; the engine's limits -------------------------------------------------------------------------
def test_replay_never_overlaps_and_keeps_the_engine_limits(tmp_path):
    cfg = make_cfg(tmp_path, intraday={"capital": 500000})
    rules = P.PlanRules.from_cfg(cfg)
    rows = []
    for d in ("2026-09-29", "2026-09-30"):
        for sym in ("NIFTY", "BANKNIFTY"):
            for t in pd.date_range(f"{d} 09:20", f"{d} 14:45", freq="5min", tz=IST):
                rows.append({"ts": t, "day": d, "symbol": sym, "trade": True, "entry_px": 100.0, "lot": 65, "expiry": dt.date(2026, 10, 6),
                             "plan_strike": 25000.0, "direction": 1, "exit_px": 90.0, "exit_ts": t + pd.Timedelta(minutes=25),
                             "exit_reason": "time_exit", "bucket": "3-5", "horizon": "30m", "quote_source": "real_point_in_time",
                             "hold_min": 25.0, "score": 0.1, "p_win": 0.6})
    tr, counts = replay(pd.DataFrame(rows), cfg, rules, CostModel(cfg))
    assert len(tr)
    for _, g in tr.groupby("day"):
        g = g.sort_values("ts")
        assert (g["ts"].iloc[1:].to_numpy() >= g["exit_ts"].iloc[:-1].to_numpy()).all()   # max_open 1: never two at once
        assert len(g) <= cfg.get("intraday.risk.max_trades_per_day")
    assert counts["blocked"] and counts["free"] >= len(tr)
    # losses → cooldown: after two straight losses the gate cools off for cooldown_min
    assert any("cooling off" in k or "trades already today" in k for k in counts["blocked"])


# ---- evidence classes, the lock, reproducibility ------------------------------------------------------------------------
def test_plan_lock_is_opened_once_and_holds_back_newer_sessions(tmp_path):
    lk = PlanLock(tmp_path)
    days = [f"2026-08-{d:02d}" for d in range(1, 31)]
    c = lk.current(days[:10], 3, 12, "now")
    assert c["lock"] is None and "no lock yet" in c["note"]
    c = lk.current(days[:12], 3, 12, "now")
    assert c["lock"] == days[9:12] and c["dev"] == days[:9]
    lk.open(1, "30m|1|plan_logit", "abc", {"passed": False}, "now")
    with pytest.raises(RuntimeError, match="already opened"):
        lk.open(1, "x", "y", {}, "now")
    c = lk.current(days[:14], 3, 12, "now")
    assert c["lock"] is None and c["reserved"] == days[12:14] and days[12] not in c["dev"]
    c = lk.current(days[:15], 3, 12, "now")
    assert c["lock"] == days[12:15] and c["generation"] == 2 and lk.opens() == 1


def test_modelled_evidence_can_never_register_or_promote(tmp_path):
    reg = Registry(tmp_path / "plan")
    pol = _policy("3-5", ev_up=True)
    card = {"code_fingerprint": "c", "feature_version": "f", "label_version": "l", "data_fingerprint": "d", "training_window": {},
            "validation": {"passed": True}, "family": "plan"}
    with pytest.raises(ValueError, match="real point-in-time"):
        reg.register(pol, {**card, "evidence": "modelled"})
    mid, _ = reg.register(pol, {**card, "evidence": "real_point_in_time"})
    reg.update_card(mid, evidence="modelled")                              # a tampered card fails closed at promotion
    with pytest.raises(PromotionRefused, match="real point-in-time"):
        reg.promote(mid, "test", {"all": True})
    assert reg.state()["champion"] is None


def test_study_tracks_are_separate_reproducible_and_scenarios_never_pass(tmp_path):
    cal = TradingCalendar(Config.load(DEFAULT_CONFIG).holidays())
    days = days_from("2026-07-01", 22, cal)
    m1 = market1m(days, seed=9)
    b5 = to_5m(m1)
    rec = book(m1, days[-2:], cal, every=2)
    buckets = sorted({P.dte_bucket(cal.trading_days_between(d, nearest(cal, d))) for d in days[-2:]})
    research = {"horizons": ["30m", "close"], "buckets": buckets, "folds": 2, "min_train_days": 6, "dev_gates": {"min_trades": 2}}

    def run(root):
        cfg = make_cfg(root, research=research, intraday={"capital": 500000})
        inputs = {"bars5": {"NIFTY": b5}, "bars1": {"NIFTY": m1[pd.Index(m1.index.date).isin(days[-2:])]},
                  "vix5": pd.Series(14.0, index=b5.index), "bhav": None, "recorded": rec, "fills": None}
        return PlanStudy(cfg, inputs, root=root / "al", now=ts(f"{days[-1]} 16:30"), say=None).run(), root / "al"
    rep, root = run(tmp_path / "a")
    rep2, _ = run(tmp_path / "b")
    assert rep["replay_hash"] == rep2["replay_hash"]                       # same inputs, same everything
    real, scen = rep["real"], rep["scenario"]
    assert len(real["pit_sessions"]) <= 2 and "insufficient real point-in-time data" in real["status"]
    assert not real["trials"] and real["lockbox"]["opened"] is False and real["approved"] is False
    assert scen["label"] == "scenario analysis only" and scen["trials"]
    assert all(t["evidence"] == "modelled" and not t["passed"] for t in scen["trials"])
    assert Registry(root / "plan").state().get("challengers", []) == []     # nothing modelled is ever registered
    logged = [json.loads(x) for x in (root / "plan" / "trials.jsonl").read_text().splitlines()]
    assert len(logged) == len(scen["trials"]) and all(x["config_hash"] for x in logged)   # every configuration on record
    md = (next((root / "plan" / "studies").glob("*/report.md"))).read_text()
    assert "SCENARIO ANALYSIS ONLY" in md and "Real point-in-time results" in md
    real_o = pd.read_parquet(next((root / "plan" / "studies").glob("*/real_outcomes.parquet")))
    scen_o = pd.read_parquet(next((root / "plan" / "studies").glob("*/scenario_outcomes.parquet")))
    assert set(real_o["quote_source"]) == {"real_point_in_time"} and set(scen_o["quote_source"]) == {"modelled"}
    assert rep["production_change"]["change"] is None


def test_real_track_selects_on_development_and_opens_the_lock_once(tmp_path):
    cal = TradingCalendar(Config.load(DEFAULT_CONFIG).holidays())
    days = days_from("2026-07-01", 12, cal)
    m1 = market1m(days, seed=10, sig=0.0012)
    b5 = to_5m(m1)
    exp = dt.date(2026, 7, 28)                                              # one monthly expiry: one DTE bucket ("6+")
    rec = book(m1, days, cal, every=2, iv=0.05, expiry=exp)                 # cheap options: some plans pay
    research = {"horizons": ["30m"], "buckets": ["6+"], "folds": 2, "min_train_days": 5, "final_test_days": 3,
                "min_real_sessions": 10, "dev_gates": {"min_trades": 1}}
    cfg = make_cfg(tmp_path, research=research, intraday={"capital": 500000})
    inputs = {"bars5": {"NIFTY": b5}, "bars1": {"NIFTY": m1}, "vix5": None, "bhav": None, "recorded": rec, "fills": None}
    root = tmp_path / "al"
    rep = PlanStudy(cfg, inputs, root=root, now=ts(f"{days[-1]} 16:30"), say=None).run()
    real = rep["real"]
    lockdays = [str(d) for d in days[-3:]]
    assert real["lock"]["lock"] == lockdays and set(real["lock"]["dev"]).isdisjoint(lockdays)
    assert real["trials"] and all(t["evidence"] == "real_point_in_time" for t in real["trials"])
    assert real["selected"] and real["lockbox"]["opened"] and real["lockbox"]["config_hash"] == real["selected_hash"]
    assert real["lockbox"]["refit_on"][1] < lockdays[0]                     # refitted only on sessions before the lock
    opened = [json.loads(x) for x in (root / "plan" / "lock_access.jsonl").read_text().splitlines() if '"opened"' in x]
    assert len(opened) == 1 and opened[0]["config_hash"] == real["selected_hash"]
    rep2 = PlanStudy(cfg, inputs, root=root, now=ts(f"{days[-1]} 17:00"), say=None).run()   # a rerun never reopens it
    assert sum(1 for x in (root / "plan" / "lock_access.jsonl").read_text().splitlines() if '"opened"' in x) == 1
    assert rep2["real"]["lockbox"]["opened"] is False and "was opened" in rep2["real"]["lock"]["note"]
    if not (real["selected_passed_dev"] and real["lockbox"]["passed"]):
        assert Registry(root / "plan").state().get("challengers", []) == []   # nothing that failed is registered


# ---- the gate: unvalidated reads never create a directional trade --------------------------------------------------------
def _policy(bucket, ev_up=True, horizon="30m", tau=0.05):
    n = len(PLAN_FEATURES)
    pol = PlanPolicy("plan_logit", None, horizon, bucket)
    up = Logit.from_dict({"l2": 3.0}, {"w": [3.0 if ev_up else -3.0] + [0.0] * n, "mu": [0.0] * n, "sd": [1.0] * n})
    dn = Logit.from_dict({"l2": 3.0}, {"w": [-3.0] + [0.0] * n, "mu": [0.0] * n, "sd": [1.0] * n})
    pol.models, pol.platt, pol.avg, pol.tau = {1: up, -1: dn}, {1: (1.0, 0.0), -1: (1.0, 0.0)}, {1: (2.0, 1.0), -1: (2.0, 1.0)}, tau
    return pol


def _plan(exp, direction=1, ratio_legs=None):
    legs = ratio_legs or [PlanLeg(25000.0, "CE" if direction > 0 else "PE", 1, 100.0, 99.5, 13.0, 0.45 * direction)]
    return TradePlan("orb", "NIFTY", direction, "long_call" if direction > 0 else "long_put", exp, legs, 65, "t", "th", None, None,
                     0.35, 0.60, 45, "kotak", 0.6)


def _engine(cfg, day):
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days(day - dt.timedelta(days=10), day)]
    bars, _ = simulate_sessions(days, seed=11)
    eng = IntradayEngine(cfg, ReplayFeed(bars, day), "model", Journal(), IntradayBroker(cfg, starting_cash=500000), say=None)
    eng.start_session(day)
    eng.chain_df.setdefault("NIFTY", pd.DataFrame())                    # the playbook is stubbed in these tests
    return eng


def test_no_directional_trade_without_an_approved_plan_model(tmp_path):
    from quantdesk.intraday.analyst import MarketView
    cfg = make_cfg(tmp_path)
    day, now = dt.date(2026, 9, 29), ts("2026-09-29 11:00")
    eng = _engine(cfg, day)
    view = MarketView("NIFTY", now, 25000.0, "bull", 0.8, 0.9, "trend", "fair", None, None, [], [], {}, "a strong read")
    eng._blocked = lambda u, v, n: None
    eng._by_record = lambda u, plans, view, now: (plans, None)
    eng.playbook.scan = lambda *a, **k: [_plan(dt.date(2026, 10, 6))]
    # learning loop off: the analyst's strong read is advisory, nothing opens
    assert "no approved plan model" in eng._maybe_enter("NIFTY", view, {}, now) and not eng.open_trades
    # learning loop on, no plan champion (only unvalidated direction models): still nothing
    eng.learner = LiveLearner(cfg, root=tmp_path / "al", source="replay")
    eng.learner.start(day)
    assert "no approved plan model" in eng._maybe_enter("NIFTY", view, {}, now) and not eng.open_trades
    # the legacy path (tests only) would have reached the EV layer: the gate is what stops it
    eng.require_model = eng.learner.require_model = False
    assert "no approved plan model" not in eng._maybe_enter("NIFTY", view, {}, now)


def test_an_approved_real_evidence_plan_model_opens_only_positive_ev_plans(tmp_path):
    from quantdesk.intraday.analyst import MarketView
    cfg = make_cfg(tmp_path)
    day, now = dt.date(2026, 9, 29), ts("2026-09-29 11:00")
    cal = TradingCalendar(cfg.holidays())
    exp = dt.date(2026, 10, 6)
    bucket = P.dte_bucket(cal.trading_days_between(day, exp))
    root = tmp_path / "al"
    reg = Registry(root / "plan")
    card = {"code_fingerprint": "c", "feature_version": "f", "label_version": "l", "data_fingerprint": "d", "training_window": {},
            "validation": {"passed": True}, "family": "plan", "evidence": "real_point_in_time"}
    mid, _ = reg.register(_policy(bucket), card)
    reg.promote(mid, "test", {"forward": True})
    eng = _engine(cfg, day)
    eng.learner = LiveLearner(cfg, root=root, source="replay")
    eng.learner.start(day)
    assert eng.learner.plan and eng.learner.fault is None
    from quantdesk.autolearn.features import FEATURES
    eng.learner.feats["NIFTY"] = (now, {k: 0.0 for k in FEATURES})
    view = MarketView("NIFTY", now, 25000.0, "bear", -0.8, 0.9, "trend", "fair", None, None, [], [], {}, "bearish read")
    eng._blocked = lambda u, v, n: None
    eng._by_record = lambda u, plans, view, now: (plans, None)
    # the model expects the put to lose: the analyst's bearish read can't make it trade
    eng.playbook.scan = lambda *a, **k: [_plan(exp, -1)]
    assert "plan model expects" in eng._maybe_enter("NIFTY", view, {}, now) and not eng.open_trades
    # a plan outside the model's DTE bucket, or a spread, is not covered
    eng.playbook.scan = lambda *a, **k: [_plan(dt.date(2026, 10, 27), 1)]
    assert "covers DTE" in eng._maybe_enter("NIFTY", view, {}, now)
    spread = [PlanLeg(25000.0, "CE", 1, 100.0, 99.5, 13.0, 0.45), PlanLeg(25200.0, "CE", -1, 40.0, 40.5, 13.0, 0.3)]
    eng.playbook.scan = lambda *a, **k: [_plan(exp, 1, spread)]
    assert "single long options only" in eng._maybe_enter("NIFTY", view, {}, now)
    # the call it expects to pay opens, on the model's horizon
    eng.playbook.scan = lambda *a, **k: [_plan(exp, 1)]
    msg = eng._maybe_enter("NIFTY", view, {}, now)
    assert msg.startswith("ENTER") and len(eng.open_trades) == 1
    t = eng.open_trades[0]
    assert t.exit_rules["time_stop_min"] == 30 and t.meta["plan_model"]["model_id"] == mid
    assert t.meta["plan_model"]["evidence"] == "real_point_in_time" and t.exit_rules["premium_stop"] == 0.30


def test_a_plan_champion_without_real_evidence_halts_entries(tmp_path):
    cfg = make_cfg(tmp_path)
    root = tmp_path / "al"
    reg = Registry(root / "plan")
    card = {"code_fingerprint": "c", "feature_version": "f", "label_version": "l", "data_fingerprint": "d", "training_window": {},
            "validation": {"passed": True}, "family": "plan", "evidence": "real_point_in_time"}
    mid, _ = reg.register(_policy("3-5"), card)
    reg.promote(mid, "test", {"forward": True})
    reg.update_card(mid, evidence="modelled")                               # tampered after promotion
    lr = LiveLearner(cfg, root=root, source="replay")
    lr.start(dt.date(2026, 9, 29))
    assert lr.fault and "real point-in-time" in lr.fault and lr.plan is None


# ---- the paper gate counts only real fills ------------------------------------------------------------------------------
def test_paper_gate_counts_only_trades_filled_at_the_live_book():
    from quantdesk.research.protocol import real_quote_trades
    t = pd.DataFrame({"pnl": [100.0, -50.0, 80.0, 30.0], "meta": [
        json.dumps({"quote_source": "kotak", "fill_quotes": "live kotak book", "exit_quotes": "live kotak book"}),
        json.dumps({"quote_source": "model", "fill_quotes": "option chain", "exit_quotes": "marked"}),
        json.dumps({"quote_source": "kotak", "fill_quotes": "live kotak book", "exit_quotes": "marked"}),
        "not json"]})
    kept, excluded = real_quote_trades(t)
    assert list(kept["pnl"]) == [100.0] and excluded == 3


# ---- the end-of-day approximation is real but never point in time -------------------------------------------------------
def test_eod_approximation_is_labelled_and_pessimistic(cfg):
    cal = TradingCalendar(cfg.holidays())
    rules = P.PlanRules.from_cfg(cfg)
    pr = IntradayPricer()
    rows = []
    for d, S in ((dt.date(2026, 9, 28), 25000.0), (dt.date(2026, 9, 29), 25000.0)):
        for K in np.arange(24500, 25550, 50.0):
            for kind in ("CE", "PE"):
                T = time_to_expiry(ts(f"{d} 15:30"), dt.date(2026, 10, 6))
                c = float(bs_price(S, K, T, pr.r, pr.q, 0.13, kind))
                # on the 29th every contract opens at its value, trades down 50% and up 80% (both levels touched), closes flat
                rows.append({"date": d, "symbol": "NIFTY", "kind": kind, "expiry": dt.date(2026, 10, 6), "strike": K, "open": c,
                             "high": c * 1.8, "low": c * 0.5, "close": c, "underlying": S, "contracts": 100})
    bhav = pd.DataFrame(rows)
    e = P.eod_outcomes(bhav, "NIFTY", cfg.instrument_spec("NIFTY"), rules, CostModel(cfg), cal, pr)
    assert len(e) and set(e["quote_source"]) == {"real_eod_approximation"} and set(e["horizon"]) == {"close"}
    assert set(e["exit_reason"]) == {"premium_stop"}                                     # stop first, always
    assert (e["exit_px"] <= e["entry_px"] * (1 - rules.premium_stop)).all()


# ---- the engine's strike picker: vectorised, same answers ---------------------------------------------------------------
def _old_rows(picker, chain, right, now):
    from quantdesk.intraday.chains import mid
    S, T = float(chain.attrs["spot"]), time_to_expiry(now, chain.attrs["expiry"])
    side = right.lower()
    near = chain[np.abs(chain.index.to_numpy(dtype=float) / S - 1) <= 0.08]
    mids = np.array([mid(row, side) for _, row in near.iterrows()], dtype=float)
    implied = picker.pricer.implied_many(np.where(mids > 0.05, mids, np.nan), near.index.to_numpy(dtype=float), right, S, T) \
        if len(near) else np.array([])
    out = []
    for (K, row), m, iv in zip(near.iterrows(), mids, implied):
        bid, ask, quoted = row.get(f"{side}_bid"), row.get(f"{side}_ask"), row.get(f"{side}_iv")
        if not (m == m and m > 0.05):
            continue
        if not (iv == iv and iv > 0):
            iv = quoted / 100 if quoted == quoted and quoted and quoted > 0 else float("nan")
        if not (iv == iv and iv > 0):
            continue
        d = picker.pricer.greeks(float(K), right, S, T, iv)["delta"]
        spread = (ask - bid) / m if bid == bid and ask == ask and ask >= bid > 0 else np.nan
        out.append({"strike": float(K), "bid": bid, "ask": ask, "mid": m, "iv": iv * 100, "delta": d, "spread": spread})
    return pd.DataFrame(out)


def test_vectorised_strike_picker_matches_the_row_loop():
    rng = np.random.default_rng(1)
    picker = StrikePicker(IntradayPricer())
    now = ts("2026-09-29 10:00")
    for _ in range(60):
        S = 25000 + rng.normal(0, 200)
        K = np.round(S / 50) * 50 + 50 * np.arange(-40, 41)
        df = pd.DataFrame({c: rng.uniform(0.0, 400, len(K)) for c in COLUMNS}, index=K.astype(float))
        for side in ("ce", "pe"):
            df[f"{side}_ask"] = df[f"{side}_bid"] + rng.choice([-1, 0.5, 2, np.nan], len(K))
            df.loc[rng.random(len(K)) < 0.2, f"{side}_bid"] = np.nan
            df.loc[rng.random(len(K)) < 0.2, f"{side}_ltp"] = np.nan
            df.loc[rng.random(len(K)) < 0.3, f"{side}_iv"] = rng.choice([0, np.nan, 15.0])
        df.attrs.update({"spot": S, "expiry": dt.date(2026, 10, 6), "ts": now})
        for right in ("CE", "PE"):
            a, b = _old_rows(picker, df, right, now), picker.rows(df, right, now)
            assert len(a) == len(b)
            if len(a):
                assert np.allclose(a.to_numpy(float), b[a.columns].to_numpy(float), equal_nan=True)


def test_armed_orders_pass_the_same_gate(tmp_path):
    from quantdesk.intraday.analyst import MarketView
    from quantdesk.intraday.playbook import Armed
    cfg = make_cfg(tmp_path)
    day, now = dt.date(2026, 9, 29), ts("2026-09-29 11:00")
    eng = _engine(cfg, day)
    view = MarketView("NIFTY", now, 25000.0, "bull", 0.8, 0.9, "trend", "fair", None, None, [], [], {}, "a strong read")
    eng.views["NIFTY"], eng._last_s["NIFTY"] = view, {}
    eng._blocked = lambda u, v, n: None
    eng._by_record = lambda u, plans, view, now: (plans, None)
    eng._chain_at = lambda u, S, now: None
    eng.playbook.fire = lambda a, view, chain, now, S: _plan(dt.date(2026, 10, 6))
    eng.armed["NIFTY"] = [Armed("orb", "NIFTY", 1, "break", 25010.0, 24960.0, 1.5, 30.0, now, now + pd.Timedelta(minutes=2), "t", "t")]
    msg = eng._fire_armed("NIFTY", now, price=25012.0)                   # the resting order's level is reached
    assert "no approved plan model" in msg and not eng.open_trades
    d = eng.journal.df("SELECT * FROM decisions")
    assert d.astype(str).apply(lambda r: r.str.contains("no approved plan model")).any(axis=None)   # advisory record kept
