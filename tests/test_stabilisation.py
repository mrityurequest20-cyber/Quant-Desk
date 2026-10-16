"""Stabilisation fixes from the 16 Oct critical-bug audit (C-04, C-10, ...), each reproduced before the fix."""
import json
from types import SimpleNamespace

import pandas as pd

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.journal.journal import Journal


# ---- C-04: the paper gate counts CRITICAL risk and execution events ------------------------------------------------
def _gate_json(tmp_path, capsys, events):
    from quantdesk.intraday.cli import cmd_paper_gate, paths
    cfg = Config.load(DEFAULT_CONFIG).with_overrides({"runtime": {"dir": str(tmp_path)}})
    j = Journal(paths(cfg, "live")["journal"])
    for ts, level, cat, msg in events:
        j.event(ts, level, cat, msg)
    j.commit()
    j.close()
    cmd_paper_gate(cfg, SimpleNamespace(account="live", strategy="orb", since="2026-10-01"))
    return json.loads(capsys.readouterr().out)


def test_the_paper_gate_counts_critical_events(tmp_path, capsys):
    """Safe mode, a failed reconciliation and a stuck exit are filed at CRITICAL; the gate kept WARN/ERROR only, so a
    strategy that tripped all three still read `no_risk_limit_violations: True`."""
    gate = _gate_json(tmp_path, capsys, [
        ("2026-10-12 11:00:00+05:30", "CRITICAL", "risk", "SAFE MODE: 3 steps failed in a row"),
        ("2026-10-12 11:05:00+05:30", "CRITICAL", "execution", "exit of X not filled: stays open, retried each minute"),
    ])
    assert gate["checks"]["no_risk_limit_violations"] is False


def test_the_paper_gate_ignores_other_categories_and_older_events(tmp_path, capsys):
    gate = _gate_json(tmp_path, capsys, [
        ("2026-10-12 15:20:00+05:30", "WARN", "data", "index bars frozen 15:15-15:27"),
        ("2026-09-20 11:00:00+05:30", "CRITICAL", "risk", "before the evidence window"),
    ])
    assert gate["checks"]["no_risk_limit_violations"] is True


def test_the_cycle_and_the_cli_count_the_same_events_in_the_window(tmp_path):
    from quantdesk.autolearn.cycle import Cycle
    from quantdesk.research.protocol import risk_violation_events
    path = tmp_path / "journal.db"
    j = Journal(path)
    for ts, level, cat in [("2026-09-20 10:00:00+05:30", "CRITICAL", "risk"),     # before the window
                           ("2026-10-12 10:00:00+05:30", "CRITICAL", "execution"),
                           ("2026-10-12 10:01:00+05:30", "ERROR", "risk"),
                           ("2026-10-12 10:02:00+05:30", "WARN", "llm")]:
        j.event(ts, level, cat, "x")
    j.commit()
    cli = len(risk_violation_events(j.events("2026-10-01")))
    j.close()
    c = Cycle.__new__(Cycle)
    c.journal_path = path
    assert cli == 2                                              # the window's CRITICAL execution + ERROR risk
    assert c._risk_violations("2026-10-01") == 3                 # + the old rule: any risk ERROR/CRITICAL ever (tighten-only)
    assert c._risk_violations() == 3


# ---- C-10: a memory file that fails to load is never overwritten --------------------------------------------------
def test_a_corrupt_memory_is_never_saved_over(tmp_path):
    """A truncated memory.json loaded as a blank record and the next save wiped every learned session."""
    from quantdesk.intraday.learning import Memory
    good = Memory(tmp_path / "memory.json")
    good.d["days"] = [f"2026-10-{d:02d}" for d in range(1, 17)]
    good.save()
    raw = (tmp_path / "memory.json").read_text(encoding="utf-8")
    (tmp_path / "memory.json").write_text(raw[: len(raw) // 2], encoding="utf-8")       # cut off mid-write
    cut = (tmp_path / "memory.json").read_bytes()
    m = Memory(tmp_path / "memory.json")
    assert m.corrupt and m.d["days"] == []
    m.d["days"].append("2026-10-19")
    m.save()
    assert (tmp_path / "memory.json").read_bytes() == cut                             # left exactly as it was


def test_learn_refuses_to_bootstrap_over_a_corrupt_memory(tmp_path):
    import pytest
    from quantdesk.intraday.cli import cmd_learn, paths
    cfg = Config.load(DEFAULT_CONFIG).with_overrides({"runtime": {"dir": str(tmp_path)}})
    paths(cfg, "live")["memory"].write_text('{"days": ["2026-10-1', encoding="utf-8")
    with pytest.raises(SystemExit, match="failed to load"):
        cmd_learn(cfg, SimpleNamespace(account="live", bootstrap=True, if_empty=True, rebuild=False))
    assert paths(cfg, "live")["memory"].read_text(encoding="utf-8") == '{"days": ["2026-10-1'


def test_a_session_on_a_corrupt_memory_says_so(tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.learning import Memory
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    cfg = Config.load(DEFAULT_CONFIG)
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    (tmp_path / "memory.json").write_text("{not json", encoding="utf-8")
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", Journal(), IntradayBroker(cfg, starting_cash=500000),
                         say=None, memory=Memory(tmp_path / "memory.json"))
    eng.start_session(days[-1])
    ev = eng.journal.events()
    assert ((ev["level"] == "ERROR") & (ev["category"] == "learning") & ev["message"].str.contains("unreadable")).any()


# ---- C-06: the daily loss limit is a ceiling for new trades, not only a trigger ----------------------------------
def _plan(per_lot_risk=2000.0, conviction=1.0):
    return SimpleNamespace(conviction=conviction, is_credit=False, premium_stop=0.3, net_premium=per_lot_risk / 0.3,
                           planned_risk_per_lot=lambda: per_lot_risk, max_loss_per_lot=lambda: per_lot_risk / 0.3)


def test_a_trade_near_the_daily_limit_is_sized_to_fit_it():
    """At -4.99% on the day a full-size trade was allowed: its stop-out would have ended the day near -7.8%."""
    from quantdesk.intraday.risk import IntradayRisk
    r = IntradayRisk(Config.load(DEFAULT_CONFIG))
    r.reset(None, 500_000)
    eq = 500_000 * (1 - 0.0499)
    assert r.gate(pd.Timestamp("2026-10-19 11:00", tz="Asia/Kolkata"), eq, [], "NIFTY") == []
    lots, notes = r.size(_plan(), eq, cash=eq)
    assert lots == 0 and "binding: daily_loss" in notes[-1]        # ₹50 of room, ₹2,000 a lot: not one lot fits
    worst = eq - lots * 2000
    assert worst >= 500_000 * 0.95


def test_the_open_trades_risk_counts_against_the_day():
    from quantdesk.intraday.risk import IntradayRisk
    r = IntradayRisk(Config.load(DEFAULT_CONFIG))
    r.reset(None, 500_000)
    full, _ = r.size(_plan(), 500_000, cash=500_000)
    near, notes = r.size(_plan(), 490_000, cash=490_000, open_risk=12_000)   # room: 490k - 475k - 12k = 3k
    assert full > near == 1 and "binding: daily_loss" in notes[-1]
    assert r.size(_plan(), 490_000, cash=490_000, open_risk=12_000, daily_loss_cap=False)[0] > 1   # research replay


# ---- C-09: cash is reconciled to the fills ------------------------------------------------------------------------
def test_cash_booked_without_a_fill_is_flagged(tmp_path):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    cfg = Config.load(DEFAULT_CONFIG)
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    j = Journal()
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-09-21"})
    clean = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", j, IntradayBroker(cfg, starting_cash=500000), say=None)
    clean.start_session(days[-1])
    assert clean.health["cash_reconcile"]["ok"]
    j2 = Journal()
    j2.set_state("intraday_account", {"capital": 500000.0, "since": "2026-09-21"})
    drift = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", j2, IntradayBroker(cfg, starting_cash=498765), say=None)
    drift.start_session(days[-1])
    ev = j2.events()
    assert not drift.health["cash_reconcile"]["ok"]
    assert ((ev["level"] == "ERROR") & (ev["category"] == "reconcile") & ev["message"].str.contains("-1,235")).any()


# ---- C-11: the record says which code made it ----------------------------------------------------------------------
def test_the_session_start_and_trades_carry_the_code_commit(monkeypatch):
    from quantdesk.intraday import engine as E
    monkeypatch.setenv("GITHUB_SHA", "0123456789abcdef")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    assert E._provenance() == {"commit": "0123456789ab", "run": "42"}
    monkeypatch.delenv("GITHUB_SHA")
    monkeypatch.delenv("GITHUB_RUN_ID")
    assert E._provenance() == {}


# ---- C-07: news is graded from when the desk could act on it ----------------------------------------------------
def _flat_day_with_a_jump(day="2026-10-14"):
    import numpy as np
    idx = pd.date_range(f"{day} 09:15", f"{day} 15:29", freq="1min", tz="Asia/Kolkata")
    close = np.where(idx < pd.Timestamp(f"{day} 10:05", tz="Asia/Kolkata"), 100.0, 101.0)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close, "volume": 1.0}, index=idx)


def _story(seen_at, llm_at=None):
    nlp = {"llm": {"readers": {"gemini": {"NIFTY": 0.6, "at": llm_at}}}} if llm_at else {}
    return pd.DataFrame([{"id": "n1", "ts": "2026-10-14 10:00:00+05:30", "seen_at": seen_at, "source": "wire",
                          "sentiment": 0.5, "about": json.dumps({"NIFTY": 3.0}), "nlp": json.dumps(nlp)}])


def test_a_story_seen_after_the_move_takes_no_credit_for_it():
    """Published 10:00, the index jumped at 10:05, the desk saw it at 10:20: graded from publication it was 'right'."""
    from quantdesk.intraday.learning import Memory, grade_news
    m = Memory()
    grade_news(m, _story("2026-10-14 10:20:00+05:30"), {"NIFTY": _flat_day_with_a_jump()})
    r = m.d["tables"]["news_reader"]["rules"]
    assert r["n"] > 0 and r["hits"] == 0


def test_a_story_seen_before_the_move_still_counts():
    from quantdesk.intraday.learning import Memory, grade_news
    m = Memory()
    grade_news(m, _story("2026-10-14 10:01:00+05:30"), {"NIFTY": _flat_day_with_a_jump()})
    assert m.d["tables"]["news_reader"]["rules"]["hits"] > 0


def test_a_language_model_read_is_graded_from_its_own_arrival():
    from quantdesk.intraday.learning import Memory, grade_news
    m = Memory()
    grade_news(m, _story("2026-10-14 10:01:00+05:30", llm_at="2026-10-14 10:30:00+05:30"), {"NIFTY": _flat_day_with_a_jump()})
    t = m.d["tables"]["news_reader"]
    assert t["rules"]["hits"] > 0 and t["gemini"]["n"] > 0 and t["gemini"]["hits"] == 0


# ---- P2-9: the cross-day drawdown halt (owner decision: 10% from the high-water mark) -----------------------------
def _dd_engine(j, cash):
    from quantdesk.core.calendar import TradingCalendar
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.intraday.synthetic import simulate_sessions
    cfg = Config.load(DEFAULT_CONFIG)
    days = [d.date() for d in TradingCalendar(cfg.holidays()).trading_days("2026-09-21", "2026-09-28")]
    bars, _ = simulate_sessions(days, seed=5)
    eng = IntradayEngine(cfg, ReplayFeed(bars, days[-1]), "model", j, IntradayBroker(cfg, starting_cash=cash), say=None)
    eng.start_session(days[-1])
    return eng, cfg


def test_a_drawdown_past_the_limit_halts_entries_across_days_until_cleared(tmp_path, capsys):
    from quantdesk.intraday.cli import cmd_clear_drawdown_halt, paths
    from quantdesk.intraday.engine import DD_KEY
    cfg0 = Config.load(DEFAULT_CONFIG).with_overrides({"runtime": {"dir": str(tmp_path)}})
    jp = paths(cfg0, "live")["journal"]
    j = Journal(jp)
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-09-01"})
    j.snapshot("2026-09-25 11:00:00+05:30", equity=520000.0, cash=520000.0, drawdown=0.0, open_trades=0, gross=0.0,
               net_delta=0.0, vega=0.0, open_risk=0.0, regime="")
    j.commit()
    eng, cfg = _dd_engine(j, 465000)                       # 465k vs a 520k peak: -10.6%
    assert eng.dd_halt and "below its peak" in eng._blocked("NIFTY", SimpleNamespace(vetoes=[]), eng.feed.now())
    j.commit()
    j.close()
    j = Journal(jp)                                        # the next day, a new runner: still halted
    assert j.get_state(DD_KEY)
    j.close()
    cmd_clear_drawdown_halt(cfg0, SimpleNamespace(account="live", reason="reviewed the losses", by="owner"))
    j = Journal(jp)
    eng2, _ = _dd_engine(j, 465000)
    assert not eng2.dd_halt                                # cleared, and the mark restarted: no instant re-halt
    assert "below its peak" not in str(eng2._blocked("NIFTY", SimpleNamespace(vetoes=[]), eng2.feed.now()))


def test_a_drawdown_inside_the_limit_does_not_halt():
    j = Journal()
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-09-01"})
    j.snapshot("2026-09-25 11:00:00+05:30", equity=510418.0, cash=510418.0, drawdown=0.0, open_trades=0, gross=0.0,
               net_delta=0.0, vega=0.0, open_risk=0.0, regime="")
    eng, _ = _dd_engine(j, 485255)                         # today's real figures: -4.9% from the 15 Oct peak
    assert not eng.dd_halt and eng.peak_equity == 510418.0
