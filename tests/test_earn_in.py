"""The earn-in gate (earn_in.py): a learned tilt reaches trading only after it beats a placebo out of sample."""
import numpy as np
import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.intraday import earn_in
from quantdesk.intraday.learning import Memory


def _days(k):
    return [str(d.date()) for d in pd.bdate_range("2026-08-03", periods=k)]


def _record(mem, table, key, days, hit_rate, n_per=10, seed=0, sym="NIFTY"):
    rng = np.random.default_rng(seed)
    for d in days:
        for _ in range(n_per):
            hit = rng.random() < hit_rate
            mem.bump(table, key, hit, 1.0 if hit else -1.0, 1.0, f"{d}|{sym}")


def _cfg(mode="apply", **kw):
    return Config.load(DEFAULT_CONFIG).with_overrides(
        {"intraday": {"learning": {"earn_in": {"mode": mode, **kw}}}})


def test_a_record_that_keeps_calling_it_right_earns_its_place():
    m = Memory()
    _record(m, "news_reader", "rules", _days(14), hit_rate=0.75, seed=1)
    g = earn_in.Gate(m, _cfg())
    r = g.results["news_reader"]["rules"]
    assert r["lift"] > 0 and r["p"] < 0.01 and g.earned("news_reader", "rules")
    assert g.reliability("news_reader", "rules") == m.reliability("news_reader", "rules") > 1.2


def test_a_consistently_wrong_reader_is_earned_downward():
    m = Memory()
    _record(m, "news_reader", "ollama", _days(14), hit_rate=0.25, seed=2)
    g = earn_in.Gate(m, _cfg())
    assert g.earned("news_reader", "ollama") and g.reliability("news_reader", "ollama") < 0.8


def test_noise_does_not_earn_anything_across_many_items():
    """Two hundred sources with no edge: Benjamini-Hochberg keeps the chance passes out."""
    m = Memory()
    for i in range(200):
        _record(m, "news_source", f"src{i}", _days(12), hit_rate=0.5, n_per=4, seed=100 + i)
    g = earn_in.Gate(m, _cfg())
    assert sum(g.earned("news_source", f"src{i}") for i in range(200)) == 0
    assert g.news_trust("general", "src7") == 1.0


def test_too_few_sessions_never_earn_however_good():
    m = Memory()
    _record(m, "factor", "orb", _days(6), hit_rate=0.9, seed=3)
    g = earn_in.Gate(m, _cfg())
    assert not g.earned("factor", "orb") and g.factor_weights() == {}


def test_a_record_that_only_fits_its_past_has_no_lift():
    """Right early, wrong late: the walk-forward user would have lost on it."""
    m = Memory()
    days = _days(14)
    _record(m, "news_event", "policy", days[:7], hit_rate=0.85, seed=4)
    _record(m, "news_event", "policy", days[7:], hit_rate=0.15, seed=5)
    g = earn_in.Gate(m, _cfg())
    assert not g.earned("news_event", "policy")


def test_an_earned_setup_resizes_but_never_stands_aside():
    m = Memory()
    for i, d in enumerate(_days(14)):
        for _ in range(3):
            m.bump("setup", "trend_break", False, -1.0, 1.0, f"{d}|NIFTY")
    g = earn_in.Gate(m, _cfg())
    assert g.earned("setup", "trend_break")
    mult, why = g.setup_mult("trend_break")
    assert why is None and mult == pytest.approx(0.6)                       # sized down to the floor, still trades
    assert m.setup_mult("trend_break")[0] == 0.0                             # the old rule: stood aside for good


def test_unearned_and_unrecorded_items_are_neutral():
    g = earn_in.Gate(Memory(), _cfg())
    assert g.news_trust("policy", "Reuters") == 1.0 and g.reliability("news_reader", "gemini") == 1.0
    assert g.setup_mult("orb") == (1.0, None) and "0 of 0" in g.summary()


def test_blocks_are_recorded_and_rebuilt_from_the_journal():
    m = Memory()
    m.bump("factor", "vwap", True, 2.0, 1.0, "2026-10-14|NIFTY")
    m.bump("factor", "vwap", False, -1.0, 1.0, "2026-10-14|NIFTY")
    assert m.d["blocks"]["factor"]["vwap"]["2026-10-14|NIFTY"] == [2.0, 1.0, 1.0]
    assert m.stat("factor", "vwap")["n"] == 2.0                               # the totals are unchanged by blocks
    assert "blocks" in Memory().d


def test_the_two_indices_of_a_session_are_one_block():
    """NIFTY and BANKNIFTY share a session's move (+0.71): flipping them separately would overstate the evidence."""
    e, n, days = earn_in._sessions({"2026-10-14|NIFTY": [10, 8, 0], "2026-10-14|BANKNIFTY": [10, 7, 0]})
    assert days == ["2026-10-14"] and n.tolist() == [20] and e.tolist() == [5.0]


def _engine(mode, tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    from quantdesk.journal.journal import Journal
    cfg = _cfg(mode)
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    m = Memory()
    _record(m, "news_source", "Wire", _days(14), hit_rate=0.5, n_per=3, seed=9)   # noise: a raw tilt, never earned
    m.d["tables"]["news_source"]["Wire"].update(n=100.0, hits=70.0)              # raw record says x1.4
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000),
                         say=None, memory=m)
    from types import SimpleNamespace
    eng.news = SimpleNamespace(trust=None, reader_trust=None)          # a replay has no news feed: wire a stand-in
    eng._apply_memory()
    return eng, m


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_off_and_shadow_change_nothing(mode, tmp_path):
    eng, m = _engine(mode, tmp_path)
    assert eng.news.trust("general", "Wire") == m.news_trust("general", "Wire") > 1.0       # the raw record, as before
    assert eng.analyst.apply_learned is False
    ev = eng.journal.events()
    assert (mode == "shadow") == bool((ev["category"] == "learning").any() and ev["message"].str.contains("earn-in").any())


def test_apply_routes_every_tilt_through_the_gate(tmp_path):
    eng, m = _engine("apply", tmp_path)
    assert eng.news.trust("general", "Wire") == 1.0                                        # unearned: neutral
    assert eng.news.reader_trust("rules") == 1.0
    assert eng.analyst.learned == {} and eng.analyst.graduated == set()
