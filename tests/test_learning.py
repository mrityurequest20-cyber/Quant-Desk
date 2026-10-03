"""The desk learns from its own calls: news tone, each factor's direction, each setup's R and the pre-break entries
the EV gate refused are graded against what the market did next, and the record moves weights within bounds."""
import json

import numpy as np
import pandas as pd
import pytest

from quantdesk.intraday import learning
from quantdesk.intraday.learning import Memory, forward
from quantdesk.journal.journal import Journal

IST = "Asia/Kolkata"


def day_bars(day="2026-10-05", start=25000.0, step=1.0):
    """One session of 1-minute bars rising `step` points a minute."""
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz=IST)
    c = start + step * np.arange(len(idx))
    return pd.DataFrame({"open": c, "high": c + 2, "low": c - 2, "close": c, "volume": 0.0}, index=idx)


def ts(x):
    return pd.Timestamp(x, tz=IST)


def test_memory_shrinks_bounds_and_survives_a_restart(tmp_path):
    m = Memory(tmp_path / "memory.json")
    assert m.reliability("factor", "vwap") == 1.0 and m.setup_mult("orb") == (1.0, None)
    for i in range(10):
        m.bump("factor", "vwap", True, 5.0)
    assert 1.0 < m.reliability("factor", "vwap") < 1.4                  # 10 of 10 right is not yet 2×: shrunk
    for i in range(500):
        m.bump("factor", "pcr", i % 5 == 0, -1.0)                         # right 20% of the time
    assert m.reliability("factor", "pcr") == pytest.approx(0.5, abs=0.03)
    for i in range(200):
        m.bump("news_event", "policy", True, 9.0)
        m.bump("news_source", "ET", True, 9.0)
    assert m.news_trust("policy", "ET") == 1.5                            # bounded however good the record
    for i in range(9):
        m.bump("setup", "orb", False, -1.0)
        m.bump("setup", "orb|trend", False, -1.0)
    mult, why = m.setup_mult("orb", "trend")
    assert mult == 0.0 and "orb has lost" in why and "trend days" in why
    for i in range(12):
        m.bump("setup", "flag", True, 2.0)
    assert m.setup_mult("flag", "balance")[0] == pytest.approx(1.3)      # falls back to the setup's overall record
    m.save()
    again = Memory(tmp_path / "memory.json")
    assert again.reliability("factor", "vwap") == m.reliability("factor", "vwap") and again.setup_mult("orb")[0] == 0.0


def test_forward_stays_in_the_session_and_overnight_news_counts_from_the_open():
    b = pd.concat([day_bars("2026-10-05"), day_bars("2026-10-06", 26000.0)])
    assert forward(b, ts("2026-10-05 10:00")) == pytest.approx(np.log((25045 + 30) / 25045.0))
    assert forward(b, ts("2026-10-05 15:10")) is None                    # 30 minutes later is tomorrow
    assert forward(b, ts("2026-10-05 20:00")) is None
    assert forward(b, ts("2026-10-05 20:00"), from_open=True) == pytest.approx(np.log(26030 / 26000.0))
    assert forward(b, ts("2026-10-06 12:00:30")) is not None


def test_grading_news_factors_trades_and_refused_entries(tmp_path):
    from quantdesk.intraday.news import NewsItem, classify
    j = Journal(tmp_path / "j.db")
    bars = {"NIFTY": day_bars(), "BANKNIFTY": day_bars(start=55000.0, step=-1.0)}
    up = classify(NewsItem(ts("2026-10-05 10:00"), "ET", "RBI cuts repo rate by 25 bps, Nifty and banks rally", id="a"))
    j.news_add([up], ts("2026-10-05 10:01"))
    for k in range(12):                                                  # a read every 5 minutes, plus an extra one
        t = ts("2026-10-05 10:00") + pd.Timedelta(minutes=5 * k)
        ev = [{"factor": "vwap", "direction": 1.0}, {"factor": "pcr", "direction": -0.6}, {"factor": "rsi", "direction": 0.05}]
        for sym in ("NIFTY",) + (("NIFTY",) if k == 3 else ()):
            j._exec("INSERT INTO thoughts (ts, symbol, evidence) VALUES (?,?,?)", (str(t), sym, json.dumps(ev)))
    for i, (r, regime) in enumerate([(1.5, "trend"), (-1.0, "trend"), (-1.0, "balance")]):
        j._exec("INSERT INTO trades (id, strategy, status, r_multiple, context, opened_at) VALUES (?,?,?,?,?,?)",
                (f"T{i}", "orb", "closed", r, json.dumps({"regime": regime}), "2026-10-05 10:30"))
    j.decision(ts("2026-10-05 11:00"), "orb", "NIFTY", "rejected", "orb reached its level 25,105.00 but EV below the floor",
               0, {"armed": {"level": 25105.0, "invalidation": 25085.0, "direction": 1}, "target": 25135.0})
    j.commit()
    m = Memory()
    got = learning.grade_session(m, j, bars, "2026-10-05")
    assert got["news"] >= 2 and got["factors"] == 24 and got["trades"] == 3 and got["armed"] == 1
    assert m.stat("news_reader", "rules")["hits"] == 1                    # NIFTY rose: right; BANKNIFTY fell: wrong
    assert m.stat("news_event", "policy")["n"] == 2
    assert m.stat("factor", "vwap")["hits"] == m.stat("factor", "vwap")["n"] == pytest.approx(12 * 5 / 30)
    assert m.stat("factor", "pcr")["hits"] == 0 and m.stat("factor", "rsi") is None   # too faint to grade
    assert m.stat("setup", "orb")["n"] == 3 and m.stat("setup", "orb|trend")["n"] == 2
    assert m.stat("armed_rejected", "orb")["sum"] == pytest.approx(1.5)                 # target first: +1.5R missed
    again = learning.grade_session(m, j, bars, "2026-10-05")
    assert again == {"news": 0, "factors": 0, "trades": 0, "armed": 0, "rs": 0}        # nothing graded twice
    assert m.reliability("factor", "vwap") > 1 > m.reliability("factor", "pcr")
    lines = learning.summary(m)
    assert any(x.startswith("factor vwap") for x in lines) and any("pre-break orb" in x for x in lines)
    fresh = Memory()
    learning.rebuild(fresh, j, bars)
    assert fresh.d["tables"] == m.d["tables"]


def test_the_analyst_and_the_news_desk_use_the_record(cfg):
    from quantdesk.intraday.analyst import Analyst
    from quantdesk.intraday.features import session_state
    from quantdesk.intraday.news import NewsDesk, NewsItem, classify
    b = day_bars()
    now = ts("2026-10-05 11:00")
    s = session_state(b[b.index + pd.Timedelta(minutes=1) <= now], now)
    a = Analyst(cfg)
    plain = a.assess("NIFTY", s, {"spot": s["last"]})
    other = next(e.factor for e in plain.evidence if e.factor != "vwap")
    a.learned = {"vwap": 1.5, other: 0.5}
    v = a.assess("NIFTY", s, {"spot": s["last"]})
    w0, w1 = ({e.factor: e.weight for e in x.evidence} for x in (plain, v))
    assert w1["vwap"] == pytest.approx(1.5 * w0["vwap"]) and w1[other] == pytest.approx(0.5 * w0[other])
    track = v.narrative.split("Track record: ")[1]
    assert "vwap ×1.50" in track and f"{other} ×0.50" in track and "Track record" not in plain.narrative

    desk = NewsDesk(cfg, fetch=lambda url: "", sources=[])
    desk.add([classify(NewsItem(now - pd.Timedelta(minutes=10), "ET", "RBI cuts repo rate by 25 bps, Nifty in focus", id="x"))])
    tone = desk.state("NIFTY", now)["tone"]
    desk.trust = lambda event, source: 0.5 if event == "policy" else 1.0
    assert desk.state("NIFTY", now)["tone"] == pytest.approx(tone * 0.5)


@pytest.fixture(scope="module")
def synthetic():
    from quantdesk.config import DEFAULT_CONFIG, Config
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.synthetic import simulate_sessions
    c = Config.load(DEFAULT_CONFIG)
    days = [d.date() for d in TradingCalendar(c.holidays()).trading_days("2026-08-24", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    return c, bars, days


def test_the_engine_grades_each_session_and_stands_aside_on_a_losing_record(synthetic, tmp_path):
    from quantdesk.intraday.engine import IntradayEngine, run_replay
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    cfg, bars, days = synthetic
    j, broker = Journal(), IntradayBroker(cfg, starting_cash=500000)
    mem = Memory(tmp_path / "memory.json")
    for d in days[-3:]:
        eng = IntradayEngine(cfg, ReplayFeed(bars, d), "model", j, broker, say=None, memory=mem)
        review = run_replay(eng)
    assert "## What the desk learned" in review and "factor " in review
    saved = json.loads((tmp_path / "memory.json").read_text())
    assert saved["tables"]["factor"] and len(saved["days"]) == 3
    assert eng.analyst.learned and all(0.5 <= x <= 1.5 for x in eng.analyst.learned.values())

    bad = Memory()                                                       # every setup has lost 1R a trade, 10 times
    for setup in cfg.get("intraday.setups"):
        for _ in range(10):
            bad.bump("setup", setup, False, -1.0)
    run = lambda m: run_replay(e := IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(),
                                                   IntradayBroker(cfg, starting_cash=500000), say=None, memory=m)) and e
    plain, e2 = run(None), run(bad)
    dec = e2.journal.df("SELECT * FROM decisions WHERE detail LIKE 'track record:%'")
    assert e2.closed == [] and (dec.empty or dec["detail"].str.contains("has lost").all())
    assert not plain.closed or not dec.empty                             # what it would have traded, it refused by record


def test_a_night_of_headlines_is_one_observation_not_forty(tmp_path):
    from quantdesk.intraday.news import NewsItem, classify
    j = Journal(tmp_path / "j.db")
    night = [classify(NewsItem(ts("2026-10-04 21:00") + pd.Timedelta(minutes=10 * i), "ET",
                               f"Nifty, banks set to rally as FII buying returns, story {i}", id=f"n{i}")) for i in range(40)]
    j.news_add(night, ts("2026-10-05 08:00"))
    j.commit()
    m = Memory()
    graded = learning.grade_news(m, j.news(n=1000), {"NIFTY": day_bars(), "BANKNIFTY": day_bars(start=55000.0)})
    assert graded == 80                                                  # 40 stories × 2 indices were read...
    assert m.stat("news_reader", "rules")["n"] == pytest.approx(2.0)     # ...but they are one opening move per index
    assert m.reliability("news_reader", "rules") < 1.1                   # one good morning is not a record


def test_bootstrap_seeds_the_record_from_real_sessions(synthetic, tmp_path):
    cfg, bars, days = synthetic
    window = {s: df[df.index.date >= days[-3]] for s, df in bars.items()}
    m = Memory(tmp_path / "memory.json")
    got = learning.bootstrap(cfg, m, window, journal=None, say=lambda *_: None)
    assert got["sessions"] == 3 and got["factors"] > 300 and m.d["bootstrap"]["days"][-1] == str(days[-1])
    assert m.stat("setup", "orb") is None                                # replay fills don't build a setup record
    assert all(0.5 <= w <= 1.5 for w in m.factor_weights().values()) and len(m.d["days"]) == 3
