"""The earn-in gate (earn_in.py): a learned tilt reaches trading only once its record has held up out of sample."""
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.intraday import earn_in
from quantdesk.intraday.learning import Memory


def _days(k):
    return [str(d.date()) for d in pd.bdate_range("2026-08-03", periods=k)]


def _record(mem, table, key, days, hit_rate, n_per=10, seed=0, sym="NIFTY", bull=0.5, up_bias=None):
    """Calls with skill `hit_rate` (a hit regardless of the day), a bullish share `bull`; with `up_bias` the market
    rises on that share of moves instead and a hit is whether the call matched it (no skill: a biased coin)."""
    rng = np.random.default_rng(seed)
    for d in days:
        for _ in range(n_per):
            pos = rng.random() < bull
            if up_bias is None:
                hit = rng.random() < hit_rate
                up = pos if hit else not pos
            else:
                up = rng.random() < up_bias
                hit = pos == up
            mem.bump(table, key, hit, 1.0 if hit else -1.0, 1.0, f"{d}|{sym}", pos, up)
        if d not in mem.d["days"]:
            mem.d["days"].append(d)


def _cfg(mode="apply", **kw):
    return Config.load(DEFAULT_CONFIG).with_overrides({"intraday": {"learning": {"earn_in": {"mode": mode, **kw}}}})


def _gate_twice(m, cfg, table, key, extra_days, **rec):
    """The gate on two consecutive sessions: earning a place takes two passes in a row."""
    first = earn_in.Gate(m, cfg)
    _record(m, table, key, extra_days, **rec)
    return first, earn_in.Gate(m, cfg)


def test_a_record_that_keeps_calling_it_right_earns_its_place_after_two_sessions():
    m = Memory()
    _record(m, "news_reader", "rules", _days(14), hit_rate=0.75, seed=1)
    first, g = _gate_twice(m, _cfg(), "news_reader", "rules", _days(15)[14:], hit_rate=0.75, seed=11)
    assert first.results["news_reader"]["rules"]["passes"] and not first.earned("news_reader", "rules")
    assert g.earned("news_reader", "rules")
    rel = m.reliability("news_reader", "rules")
    assert g.reliability("news_reader", "rules") == pytest.approx(1 + (rel - 1) / 2) and rel > 1.2   # half the tilt


def test_a_bullish_reader_in_a_rising_market_is_not_skilled():
    """Research review, 16 Oct: against 0.5 a reader that is 90% bullish in a market that rises 75% of the time scores
    ~70% without any skill; against the day's base rate it scores nothing."""
    m = Memory()
    _record(m, "news_reader", "rules", _days(20), hit_rate=None, bull=0.9, up_bias=0.75, n_per=20, seed=3)
    raw = m.d["tables"]["news_reader"]["rules"]
    assert raw["hits"] / raw["n"] > 0.65                                    # looks skilled against a coin
    first, g = _gate_twice(m, _cfg(), "news_reader", "rules", _days(21)[20:], hit_rate=None, bull=0.9, up_bias=0.75,
                           n_per=20, seed=4)
    assert not g.earned("news_reader", "rules") and g.results["news_reader"]["rules"]["p"] > 0.05


def test_a_consistently_wrong_reader_is_earned_downward():
    m = Memory()
    _record(m, "news_reader", "ollama", _days(14), hit_rate=0.25, seed=2)
    _, g = _gate_twice(m, _cfg(), "news_reader", "ollama", _days(15)[14:], hit_rate=0.25, seed=12)
    assert g.earned("news_reader", "ollama") and g.reliability("news_reader", "ollama") < 0.9


def test_noise_does_not_earn_anything_across_many_items():
    """Two hundred sources with no edge: Benjamini-Hochberg over every tested item keeps the chance passes out."""
    m = Memory()
    for i in range(200):
        _record(m, "news_source", f"src{i}", _days(12), hit_rate=0.5, n_per=4, seed=100 + i)
    g = earn_in.Gate(m, _cfg())
    assert sum(g.results["news_source"][f"src{i}"]["passes"] for i in range(200)) == 0
    assert g.news_trust("general", "src7") == 1.0


def test_too_few_sessions_never_earn_however_good():
    m = Memory()
    _record(m, "factor", "orb", _days(6), hit_rate=0.9, seed=3)
    _, g = _gate_twice(m, _cfg(), "factor", "orb", _days(7)[6:], hit_rate=0.9, seed=13)
    assert not g.earned("factor", "orb") and g.factor_weights() == {}


def test_a_record_that_only_fits_its_past_has_no_lift():
    """Right early, wrong late: the walk-forward user would have lost on it."""
    m = Memory()
    days = _days(14)
    _record(m, "news_event", "policy", days[:7], hit_rate=0.85, seed=4)
    _record(m, "news_event", "policy", days[7:], hit_rate=0.15, seed=5)
    g = earn_in.Gate(m, _cfg())
    assert not g.results["news_event"]["policy"]["passes"]


def test_an_earned_item_keeps_its_place_until_it_stops_holding():
    m, cfg = Memory(), _cfg(window_sessions=20)
    _record(m, "factor", "vwap", _days(14), hit_rate=0.8, seed=6)
    _, g = _gate_twice(m, cfg, "factor", "vwap", _days(15)[14:], hit_rate=0.8, seed=16)
    assert g.earned("factor", "vwap")
    for i, d in enumerate(_days(45)[15:]):                                    # it turns into a coin for 30 sessions
        _record(m, "factor", "vwap", [d], hit_rate=0.5, seed=200 + i)
        g = earn_in.Gate(m, cfg)
    assert not g.earned("factor", "vwap")                                     # the strong sessions aged out


def test_the_same_session_is_counted_once():
    m = Memory()
    _record(m, "factor", "vwap", _days(14), hit_rate=0.8, seed=6)
    for _ in range(3):                                                      # the engine applies memory several times a day
        g = earn_in.Gate(m, _cfg())
    assert not g.earned("factor", "vwap") and m.d[earn_in.STATE_KEY]["factor|vwap"]["streak"] == 1


def test_an_earned_setup_resizes_but_never_stands_aside():
    m = Memory()
    days = _days(15)
    for d in days[:14]:
        for _ in range(3):
            m.bump("setup", "trend_break", False, -1.0, 1.0, f"{d}|NIFTY")
        m.d["days"].append(d)
    earn_in.Gate(m, _cfg())
    for _ in range(3):
        m.bump("setup", "trend_break", False, -1.0, 1.0, f"{days[14]}|NIFTY")
    m.d["days"].append(days[14])
    g = earn_in.Gate(m, _cfg())
    assert g.earned("setup", "trend_break")
    mult, why = g.setup_mult("trend_break")
    assert why is None and mult == pytest.approx(1 + 0.25 * (-45 / 53)) and mult >= 0.75   # sized down, still trades
    assert m.setup_mult("trend_break")[0] == 0.0                            # the old rule: stood aside for good


def test_unearned_and_unrecorded_items_are_neutral():
    g = earn_in.Gate(Memory(), _cfg())
    assert g.news_trust("policy", "Reuters") == 1.0 and g.reliability("news_reader", "gemini") == 1.0
    assert g.setup_mult("orb") == (1.0, None) and "0 of 0" in g.summary()


def test_blocks_carry_the_call_and_the_move():
    m = Memory()
    m.bump("factor", "vwap", True, 2.0, 1.0, "2026-10-14|NIFTY", True, True)
    m.bump("factor", "vwap", False, -1.0, 1.0, "2026-10-14|NIFTY", True, False)
    assert m.d["blocks"]["factor"]["vwap"]["2026-10-14|NIFTY"] == [2.0, 1.0, 1.0, 2.0, 1.0]
    assert m.stat("factor", "vwap")["n"] == 2.0                              # the totals are unchanged by blocks
    assert "blocks" in Memory().d


def test_a_block_without_the_base_rate_is_left_out():
    e, n, days = earn_in._sessions({"2026-10-13|NIFTY": [10, 8, 0], "2026-10-14|NIFTY": [10, 8, 0, 5, 5]})
    assert days == ["2026-10-14"] and e.tolist() == [3.0]                    # 8 - 10 x 0.5


def test_the_two_indices_of_a_session_are_one_block():
    e, n, days = earn_in._sessions({"2026-10-14|NIFTY": [10, 8, 0, 5, 5], "2026-10-14|BANKNIFTY": [10, 7, 0, 5, 5]})
    assert days == ["2026-10-14"] and n.tolist() == [20] and e.tolist() == [5.0]


def _engine(mode):
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
    _record(m, "news_source", "Wire", _days(14), hit_rate=0.5, n_per=3, seed=9)   # noise: never earned
    m.d["tables"]["news_source"]["Wire"].update(n=100.0, hits=70.0)              # the raw record says x1.4
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000),
                         say=None, memory=m)
    eng.news = SimpleNamespace(trust=None, reader_trust=None)                   # a replay has no news feed: a stand-in
    eng._apply_memory()
    return eng, m


@pytest.mark.parametrize("mode", ["off", "shadow"])
def test_off_and_shadow_change_nothing(mode):
    eng, m = _engine(mode)
    assert eng.news.trust("general", "Wire") == m.news_trust("general", "Wire") > 1.0          # the raw record, as before
    assert eng.analyst.apply_learned is False
    ev = eng.journal.events()
    assert (mode == "shadow") == bool(((ev["category"] == "learning") & ev["message"].str.contains("earn-in")).any())


def test_apply_routes_every_tilt_through_the_gate():
    eng, m = _engine("apply")
    assert eng.news.trust("general", "Wire") == 1.0 and eng.news.reader_trust("rules") == 1.0   # unearned: neutral
    assert eng.analyst.learned == {} and eng.analyst.graduated == set()


def test_a_gate_that_fails_after_working_does_not_leave_the_raw_record_applied(monkeypatch):
    """Risk review, 16 Oct: apply mode, the gate works at start, then raises on the post-close re-grade. The fallback
    restored the raw record but left apply_learned on, so unearned weights and the stand-aside reached trading."""
    eng, m = _engine("apply")
    m.d["tables"].setdefault("factor", {})["vwap"] = {"n": 400.0, "hits": 296.0, "sum": 0.0, "sum2": 0.0}
    for _ in range(10):
        m.bump("setup", "orb", False, -1.0)
    assert eng.analyst.apply_learned is True                                     # apply mode, the gate working
    monkeypatch.setattr(earn_in.Gate, "__init__", lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    eng._apply_memory()
    assert eng.earn_gate is None and eng.analyst.apply_learned is False
    assert eng.memory.setup_mult("orb", None, eng.analyst.apply_learned) == (1.0, None)   # no stand-aside comes back
