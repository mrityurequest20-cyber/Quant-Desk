"""The quant layer: causal features, a model that must prove itself out of sample, a vol forecast
that scales right, and an EV engine that charges every cost and gives no free lunch."""
import datetime as dt
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.execution.costs import CostModel
from quantdesk.intraday.chains import IntradayPricer, time_to_expiry
from quantdesk.intraday.playbook import PlanLeg, TradePlan
from quantdesk.intraday.quant import (FEATURES, MIN_PER_YEAR, DirectionModel, EVEngine, VolForecaster, features_5m,
                                      to_5m)

IST = "Asia/Kolkata"


def sessions_5m(n_days=40, seed=1, momentum=0.0):
    """Random-walk 5m sessions; `momentum` makes the next 30 minutes follow the last 30 (a planted edge)."""
    rng = np.random.default_rng(seed)
    frames, px = [], 22000.0
    for d in pd.bdate_range("2026-06-01", periods=n_days):
        idx = pd.date_range(pd.Timestamp(d.date(), tz=IST) + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min")
        r = rng.normal(0, 8e-4, 75)
        for i in range(6, 75):
            r[i] += momentum * r[i - 6:i].sum() / 6
        c = px * np.exp(np.cumsum(r))
        o = np.r_[px, c[:-1]]
        frames.append(pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0002, "low": np.minimum(o, c) * 0.9998,
                                    "close": c, "volume": 0.0}, index=idx))
        px = c[-1] * np.exp(rng.normal(0, 3e-3))
    return pd.concat(frames)


def test_features_are_causal():
    df = sessions_5m(3, seed=4)
    full = features_5m(df)
    last_day = df[df.index.date == df.index.date[-1]]
    before = df[df.index.date < df.index.date[-1]]
    for k in (1, 2, 5, 17, 40):
        part = features_5m(pd.concat([before, last_day.iloc[:k]]))
        a, b = part[FEATURES].iloc[-1].to_numpy(), full.loc[part.index[-1], FEATURES].to_numpy()
        assert np.allclose(a, b, atol=1e-9), (k, a - b)          # a row never changes when later bars arrive


def test_model_finds_a_planted_edge_and_refuses_noise():
    edge = DirectionModel()
    d = edge.fit(features_5m(sessions_5m(45, seed=2, momentum=0.6)))
    assert edge.valid and d["auc_oos"] > 0.58, d
    noise = DirectionModel()
    d = noise.fit(features_5m(sessions_5m(45, seed=3, momentum=0.0)))
    assert not noise.valid and d["status"] == "no edge out of sample", d
    few = DirectionModel()
    assert few.fit(features_5m(sessions_5m(5, seed=5)))["status"] == "not enough history"


def test_vol_forecast_scales_and_reacts():
    rng = np.random.default_rng(0)
    idx = pd.date_range(pd.Timestamp("2026-09-28 09:15", tz=IST), periods=375, freq="1min")
    prev = pd.DatetimeIndex([t - pd.Timedelta(days=1) for t in idx])
    calm = np.exp(np.cumsum(rng.normal(0, 3e-4, 750))) * 22000
    bars = pd.DataFrame({"close": calm}, index=prev.append(idx))
    f = VolForecaster().forecast(bars, idx[0].date())
    assert f["sigma_min"] == pytest.approx(3e-4, rel=0.2) and f["sigma_30m"] == pytest.approx(f["sigma_min"] * math.sqrt(30))
    wild = bars.copy()
    wild.iloc[-100:, 0] = wild["close"].iloc[-101] * np.exp(np.cumsum(rng.normal(0, 1.5e-3, 100)))
    assert VolForecaster().forecast(wild, idx[0].date())["sigma_min"] > 1.5 * f["sigma_min"]     # today's burst counts
    with_iv = VolForecaster().forecast(bars, idx[0].date(), atm_iv=30.0)
    assert with_iv["sigma_min"] > f["sigma_min"] and with_iv["source"] == "realised+implied"


@pytest.fixture
def plan_factory(cfg):
    pr = IntradayPricer(0.065, 0.012)
    now = pd.Timestamp("2026-09-29 10:30", tz=IST)
    S, exp = 22780.0, dt.date(2026, 10, 6)
    T = time_to_expiry(now, exp)

    def leg(K, ratio, iv=13.0):
        m = pr.price(K, "CE", S, T, iv / 100)
        half = max(0.5, 0.004 * m)
        return PlanLeg(K, "CE", ratio, m + half if ratio > 0 else m - half, m, iv, pr.greeks(K, "CE", S, T, iv / 100)["delta"])

    def make(legs, hold=45):
        return TradePlan("orb", "NIFTY", 1, "x", exp, legs, 65, "t", "th", 22700, 23050, 0.30, 0.60, hold, "nse", 0.6)
    return pr, now, S, leg, make, EVEngine(cfg, pr, CostModel(cfg), n_paths=4000)


def test_ev_has_no_free_lunch_and_charges_costs(plan_factory):
    pr, now, S, leg, make, ev = plan_factory
    sig = 0.13 / math.sqrt(MIN_PER_YEAR)                          # realised vol = the option's own implied vol
    for legs in ([leg(22950, 1)], [leg(22850, 1), leg(23000, -1)]):
        r = ev.evaluate(make(legs), S, now, sig, 0.5, 240)
        costs = r["fees"] + r["exit_cost"]
        assert -2.2 * costs < r["ev"] < 0                          # no edge → you lose about the costs, not more, not less
    single, spread = make([leg(22950, 1)]), make([leg(22850, 1), leg(23000, -1)])
    evs = [ev.evaluate(single, S, now, sig, p, 240)["ev"] for p in (0.40, 0.50, 0.55, 0.60)]
    assert evs == sorted(evs)                                     # more edge, more EV
    assert ev.evaluate(spread, S, now, sig, 0.5, 240)["fees"] > 1.5 * ev.evaluate(single, S, now, sig, 0.5, 240)["fees"]
    assert ev.evaluate(single, S, now, sig * 1.5, 0.5, 240)["ev"] > ev.evaluate(single, S, now, sig * 0.8, 0.5, 240)["ev"]
    r = ev.evaluate(single, S, now, sig, 0.5, 240)
    assert r["cvar5"] >= -single.net_premium - r["fees"] - 1            # can't lose more than you paid (+ costs)
    assert ev.evaluate(single, S, now, sig, 0.5, 20)["horizon_min"] == 20    # never holds past the square-off


def test_engine_prices_every_plan(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    cal = TradingCalendar(cfg.holidays())
    days = [d.date() for d in cal.trading_days("2026-07-15", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    j = Journal(tmp_path / "journal.db")
    # the EV layer's mechanics: past the approved-model gate on purpose (test_plan_research covers the gate itself)
    cfg = cfg.with_overrides({"autolearn": {"require_approved_model": False}})
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", j, IntradayBroker(cfg, starting_cash=20000), say=None)
    run_replay(eng)
    ev = j.events()
    assert ev["message"].str.contains("direction model").sum() == 2          # trained per underlying, result journaled
    th = j.thoughts(str(days[-1]))
    assert th["narrative"].str.contains("Quant: 30-min σ").all()
    hb = j.get_state("intraday_live")["views"]["NIFTY"]["quant"]
    assert hb["sigma_30m_pct"] > 0 and "model_status" in hb
    dec = j.df("SELECT * FROM decisions")
    tr = j.trades()
    assert len(tr) or dec["detail"].str.contains("EV").any()                 # every plan was priced
    for r in tr.itertuples():
        assert "Quant: EV" in r.rationale and "P(up)" in r.rationale


def test_research_priors_only_use_surviving_edges(plan_factory, tmp_path):
    import json
    from quantdesk.intraday.quant import load_research
    pr, now, S, leg, make, ev = plan_factory
    sig = 0.13 / math.sqrt(MIN_PER_YEAR)
    call = make([leg(22950, 1)])
    base = ev.evaluate(call, S, now, sig, 0.5, 240)["ev"]
    assert ev.evaluate(call, S, now, sig, 0.5, 240, base_drift_min=-5.7 / 1e4 / 375)["ev"] < base   # a bearish drift costs a call
    (tmp_path / "edges.json").write_text(json.dumps([
        {"id": "D1", "symbol": "NIFTY", "verdict": "PAPER CANDIDATE", "effect_bps": -5.7, "t": -3.44, "n": 4669,
         "effect_holdout_bps": -4.6},
        {"id": "D1", "symbol": "BANKNIFTY", "verdict": "NO EDGE", "effect_bps": -5.0},
        {"id": "V1", "symbol": "NIFTY", "verdict": "NEEDS MARGIN", "effect_bps": 301}]))
    r = load_research(tmp_path / "edges.json")
    assert set(r) == {"NIFTY"} and r["NIFTY"]["drift"]["per_min"] == pytest.approx(-5.7 / 1e4 / 375)
    assert r["NIFTY"]["drift"]["rolling_validation_bps"] == -4.6
    (tmp_path / "old.json").write_text(json.dumps([{"id": "D1", "symbol": "NIFTY", "verdict": "EDGE", "effect_bps": -5.7}]))
    assert set(load_research(tmp_path / "old.json")) == {"NIFTY"}                  # reports from before the relabel
    assert load_research(tmp_path / "missing.json") == {}


def test_calibration_table():
    import json
    from quantdesk.web.intraday_api import IntradayAPI
    rows = []
    for i in range(20):
        up = i % 4 != 0                                            # the index went up 75% of the time
        rows.append({"direction": 1, "entry_underlying": 100.0, "exit_underlying": 101.0 if up else 99.0, "pnl": 50.0 if up else -60.0,
                     "meta": json.dumps({"quant": {"p_up": 0.55, "p_source": "prior tilt from the analyst's score (unvalidated)"}})})
    rows.append({"direction": 1, "entry_underlying": 100.0, "exit_underlying": float("nan"), "pnl": 0.0, "meta": "{}"})
    cal = IntradayAPI._calibration(pd.DataFrame(rows))
    assert len(cal) == 1 and cal[0]["trades"] == 20 and cal[0]["bucket"] == "53–56%"
    assert cal[0]["realised"] == pytest.approx(0.75) and cal[0]["source"] == "prior tilt from the analyst's score"


def test_quant_failure_degrades_to_standing_aside(cfg, tmp_path):
    """A broken quant layer must not stop the desk thinking; it just won't trade on missing numbers."""
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    cal = TradingCalendar(cfg.holidays())
    days = [d.date() for d in cal.trading_days("2026-08-20", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    j = Journal()
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", j, IntradayBroker(cfg, starting_cash=20000), say=None)
    eng.volf = None

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")
    eng._select_by_ev = boom
    eng._quant_state = boom
    run_replay(eng)
    th = j.thoughts(str(days[-1]))
    assert len(th) > 100 and not len(j.trades())                                    # kept thinking, didn't trade blind
    errs = j.events(level="ERROR")
    assert errs["message"].str.contains("quant state failed").sum() == 2               # once per underlying, not every minute


# ---- A-05: the live path's 5m bars are the training path's clock buckets ---------------------------------------------
def _minutes(day, drop=(), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz=IST)
    c = 22500 * np.exp(np.cumsum(rng.normal(0, 4e-4, len(idx))))
    o = np.r_[22500, c[:-1]]
    df = pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.0002, "low": np.minimum(o, c) * 0.9998, "close": c,
                       "volume": rng.integers(500, 1500, len(idx)).astype(float)}, index=idx)
    return df[~idx.strftime("%H:%M").isin(drop)]


@pytest.mark.parametrize("drop", [(), ("10:02",), ("12:20", "12:21"), ("12:29",), ("13:05", "13:06", "13:07", "13:08", "13:09")])
def test_live_5m_bars_are_the_training_resample(drop):
    """At every minute the live 5m bars, and the model features on them, are exactly the training path's (to_5m, as
    samples_from_bars builds them) for the clock buckets that have ended: a missing minute shifts no later bucket, and a
    bucket whose last minute hasn't arrived is waited for, never used short."""
    from quantdesk.autolearn.features import samples_from_bars
    from quantdesk.intraday.quant import completed_5m, session_sigma
    day = dt.date(2026, 10, 8)
    prior, today = _minutes("2026-10-07", seed=1), _minutes(str(day), drop)
    train5 = to_5m(pd.concat([prior, today]))
    samples = samples_from_bars({"NIFTY": pd.concat([prior, today])})[0].set_index("ts")
    prev_close, prev_sig = float(prior["close"].iloc[-1]), session_sigma(to_5m(prior)["close"].to_numpy(float))
    waited = 0
    for now in pd.date_range(f"{day} 09:16:04", f"{day} 15:30:04", freq="1min", tz=IST):
        seen = today[today.index + pd.Timedelta(minutes=1) <= now]
        live = completed_5m(seen, now)
        want = train5[(train5.index.date == day) & (train5.index + pd.Timedelta(minutes=5) <= now)]
        if list(live.index) != list(want.index):                # only the newest bucket, while its last minute is due
            assert list(live.index) == list(want.index[:-1]) and want.index[-1] + pd.Timedelta(minutes=4) not in seen.index
            waited += 1
        pd.testing.assert_frame_equal(live, train5.loc[live.index], check_freq=False)
        if len(live):
            f = features_5m(live, prev_close, prev_sig).iloc[-1]
            assert np.allclose(f[FEATURES].to_numpy(float), samples.loc[live.index[-1] + pd.Timedelta(minutes=5), FEATURES]
                               .to_numpy(float), equal_nan=True)
    assert waited == (1 if drop == ("12:29",) else 0)


def test_engine_model_reads_the_training_bars(cfg):
    """Through the engine: each minute the direction model sees the last ended clock 5m bucket's features, equal to the
    training resample's, with a missing minute (10:02) and the hand-over hole (12:20-12:21) in today's data."""
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    cal = TradingCalendar(cfg.holidays())
    days = [d.date() for d in cal.trading_days("2026-09-14", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    day, n = days[-1], bars["NIFTY"]
    bars["NIFTY"] = n[~((n.index.date == day) & n.index.strftime("%H:%M").isin(["10:02", "12:20", "12:21"]))]
    eng = IntradayEngine(cfg, ReplayFeed(bars, day), "model", Journal(), IntradayBroker(cfg, starting_cash=20000), say=None)
    eng.start_session(day)
    seen = []

    class Spy:
        w, valid, diag = 1.0, False, {}

        def predict(self, row):
            seen.append((eng.feed.now(), row))
            return 0.5
    eng.models["NIFTY"] = Spy()
    while eng.feed.advance():
        eng.step()
    train = features_5m(to_5m(bars["NIFTY"]))
    train = train[train.index.date == day]
    assert len(seen) == len(train) and not len(eng.journal.events(level="ERROR"))   # once per completed bucket
    for now, row in seen:
        last = train.index[train.index + pd.Timedelta(minutes=5) <= now][-1]       # the newest bucket ended by now
        assert row.name == last and np.allclose(row[FEATURES].to_numpy(float), train.loc[last, FEATURES].to_numpy(float))
