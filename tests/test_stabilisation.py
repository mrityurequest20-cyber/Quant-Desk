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
