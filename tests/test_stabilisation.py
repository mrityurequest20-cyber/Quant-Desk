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
