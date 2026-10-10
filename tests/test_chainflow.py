"""How the option chain moved through the session (chainflow.py), the factors it feeds on probation, and the two research
tables the learning loop keeps: factor IC by horizon and the buyer's edge (realised vs implied volatility)."""
import json

import numpy as np
import pandas as pd
import pytest

from quantdesk.intraday import learning
from quantdesk.intraday.chainflow import ChainFlow, chain_step, iv_trend_note, skew_trend_signal, wall_shift_signal
from quantdesk.intraday.learning import Memory

IST = "Asia/Kolkata"


def ts(x):
    return pd.Timestamp(x, tz=IST)


def an(**kw):
    base = {"source": "kotak", "spot": 25600.0, "atm_iv": 12.0, "skew_25d": 2.0, "pcr_oi": 1.0, "pcr_doi": 1.1,
            "call_wall": 25700.0, "put_wall": 25500.0, "straddle": 180.0, "implied_move": 0.007, "dte_days": 4.0}
    return {**base, **kw}


def test_walls_skew_and_iv_trends_from_the_first_read():
    cf = ChainFlow()
    assert cf.update("NIFTY", an(source="model"), ts("2026-10-05 09:20")) == {}          # the model chain says nothing
    first = cf.update("NIFTY", an(), ts("2026-10-05 09:20"), step=50.0)
    assert first["cf_iv"] == 12.0 and "cf_iv_chg30" not in first                          # no 30-minute history yet
    assert wall_shift_signal(first) is None and skew_trend_signal(first) is None
    cf.update("NIFTY", an(atm_iv=12.2, skew_25d=2.1), ts("2026-10-05 09:35"), step=50.0)
    now = cf.update("NIFTY", an(atm_iv=12.8, skew_25d=2.9, pcr_oi=0.9, call_wall=25600.0), ts("2026-10-05 09:55"), step=50.0)
    assert now["cf_iv_chg30"] == pytest.approx(0.8) and now["cf_skew_chg30"] == pytest.approx(0.9)
    assert now["cf_call_wall_open"] == 25700 and now["cf_call_wall_shift"] == -100 and now["cf_put_wall_shift"] == 0
    d, why = wall_shift_signal(now)
    assert d == pytest.approx(-1.0) and "25,700 → 25,600" in why and "pressing price down" in why
    d, why = skew_trend_signal(now)
    assert d == pytest.approx(-0.6) and "put demand rising" in why
    assert "tailwind for bought options" in iv_trend_note(now)
    assert cf.opening("NIFTY")["atm_iv"] == 12.0
    nxt = cf.update("NIFTY", an(), ts("2026-10-06 09:20"), step=50.0)                     # a new session starts over
    assert nxt["cf_since"].startswith("2026-10-06") and "cf_call_wall_shift" in nxt and nxt["cf_call_wall_shift"] == 0


def test_chain_step_is_the_common_strike_gap():
    df = pd.DataFrame(index=[25400.0, 25450.0, 25500.0, 25550.0, 25600.0, 25700.0])
    assert chain_step(df) == 50.0 and chain_step(None) is None


def test_new_chain_evidence_votes_only_after_its_live_record_earns_it(cfg):
    from quantdesk.intraday.analyst import PROBATION, Analyst
    from quantdesk.intraday.features import session_state
    idx = pd.date_range("2026-10-05 09:15", "2026-10-05 11:00", freq="1min", tz=IST)
    c = 25600 + np.arange(len(idx)) * 0.5
    bars = pd.DataFrame({"open": c, "high": c + 2, "low": c - 2, "close": c, "volume": 0.0}, index=idx)
    s = session_state(bars, idx[-1] + pd.Timedelta(minutes=1))
    chain = {"source": "kotak", "pcr_oi": 1.0, "call_wall": 25800.0, "put_wall": 25400.0, "cf_step": 50.0,
             "cf_call_wall_open": 25900.0, "cf_call_wall_shift": -100.0, "cf_put_wall_open": 25400.0, "cf_put_wall_shift": 0.0,
             "cf_skew": 3.0, "cf_skew_chg30": 1.2, "top_call_adds": [25800.0], "top_put_adds": [25450.0]}
    a = Analyst(cfg)
    v = a.assess("NIFTY", s, chain)
    ev = {e.factor: e for e in v.evidence}
    assert ev["oi_shift"].direction < 0 and ev["oi_shift"].weight == 0 and "probation" in ev["oi_shift"].observation
    assert ev["skew_trend"].direction < 0 and ev["skew_trend"].weight == 0
    assert v.levels["call_add"] == 25800 and v.levels["put_add"] == 25450
    a.graduated, a.learned = {"oi_shift"}, {"oi_shift": 1.2}
    a.apply_learned = True              # intraday.learning.apply_factor_weights (off by default, D-01: test_learning)
    ev = {e.factor: e for e in a.assess("NIFTY", s, chain).evidence}
    assert ev["oi_shift"].weight == pytest.approx(PROBATION["oi_shift"] * 1.2) and ev["skew_trend"].weight == 0


def day_bars(day, rng, sigma_bps=4.0, start=25000.0):
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz=IST)
    c = start * np.exp(np.cumsum(rng.normal(0, sigma_bps / 1e4, len(idx))))
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": 0.0}, index=idx)


def test_factor_ic_by_horizon_finds_the_factor_that_predicts(tmp_path):
    from quantdesk.journal.journal import Journal
    rng = np.random.default_rng(3)
    days = ["2026-10-05", "2026-10-06", "2026-10-07"]
    bars = pd.concat([day_bars(d, rng) for d in days])
    j = Journal(tmp_path / "j.db")
    for d in days:
        b = bars[bars.index.date == pd.Timestamp(d).date()]
        for t in pd.date_range(f"{d} 09:20", f"{d} 14:20", freq="5min", tz=IST):
            fr = learning.forward(b, t, minutes=30)
            ev = [{"factor": "seer", "direction": float(np.clip(np.sign(fr) * 0.8 + rng.normal(0, 0.3), -1, 1))},
                  {"factor": "coin", "direction": float(rng.choice([-0.8, 0.8]))}]
            j._exec("INSERT INTO thoughts (ts, symbol, evidence) VALUES (?,?,?)", (str(t), "NIFTY", json.dumps(ev)))
    j.commit()
    m = Memory()
    th = j.df("SELECT ts, symbol, evidence FROM thoughts ORDER BY ts")
    assert learning.grade_ic(m, th, {"NIFTY": bars}) == len(th)
    assert learning.grade_ic(m, th, {"NIFTY": bars}) == 0                                # nothing counted twice
    tab = {r["factor"]: r["h"] for r in learning.ic_table(m)}
    assert tab["seer"]["30"]["ic"] > 0.5 and tab["seer"]["30"]["t"] > 3
    assert abs(tab["coin"]["30"]["ic"]) < 0.3 and abs(tab["coin"]["30"]["t"]) < 3
    assert tab["seer"]["5"]["n"] > tab["seer"]["60"]["n"]                                 # overlap-adjusted samples
    assert learning.ic_table(m)[0]["factor"] == "seer"
    assert any(x.startswith("IC seer") for x in learning.summary(m))


def test_buyer_edge_sets_realised_against_the_opens_implied_vol():
    rng = np.random.default_rng(7)
    m = Memory()
    rvs = []
    for i, d in enumerate(["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]):
        b = day_bars(d, rng, sigma_bps=4.0)                    # 4 bps a minute ≈ 12.3% annualised
        rec = learning.record_move(m, d, "NIFTY", b, {"ts": ts(f"{d} 09:20"), "atm_iv": 20.0 if i < 3 else 6.0})
        rvs.append(rec["rv"])
        assert rec["rv_iv"] == pytest.approx(rec["rv"] / rec["iv"], abs=1e-3) and rec["exp_move"] > 0
    assert np.mean(rvs) == pytest.approx(12.3, rel=0.2)                                  # one quiet day can't fool it
    e = learning.buyer_edge(m)["NIFTY"]
    assert e["sessions"] == 4 and e["rv_above"] == pytest.approx(0.25)                    # implied 20 3 days, 6 on one
    assert e["rv_iv"] == pytest.approx(np.mean([r / iv for r, iv in zip(rvs, [20, 20, 20, 6])]), abs=1e-3)
    assert learning.record_move(m, "2026-10-09", "NIFTY", None, {"ts": ts("2026-10-09 09:20"), "atm_iv": 12}) is None
    assert any(x.startswith("buyer's edge NIFTY") for x in learning.summary(m))
    keep = dict(m.d["moves"])
    from quantdesk.journal.journal import Journal
    learning.rebuild(m, Journal(), {})
    assert m.d["moves"] == keep                                                           # not re-derivable: kept


def test_the_heartbeat_carries_the_chain_read_and_the_record(cfg, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine, _chain_view, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    assert _chain_view({"atm_iv": float("nan"), "pcr_oi": 1.1, "cf_iv": 12.0, "junk": 1}) == {"pcr_oi": 1.1, "cf_iv": 12.0}
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=11)
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000),
                         say=None, memory=Memory(tmp_path / "memory.json"))
    run_replay(eng)
    hb = eng.journal.get_state("intraday_live")
    assert hb["learning"]["probation"]["oi_shift"]["voting"] is False and "ic" in hb["learning"]
    assert all("chain" in v for v in hb["views"].values())
