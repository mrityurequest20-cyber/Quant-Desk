"""Phase D forensic probes (read-only: temp dirs only).

    QD_JOURNAL=/tmp/qd_journal/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Each passing probe CONFIRMS the finding it names (audit/QUANTDESK_FINDINGS_REGISTER.md).
"""
import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(os.environ.get("QD_REPO", str(Path(__file__).resolve().parents[2])))
JOURNAL = Path(os.environ.get("QD_JOURNAL", "/nonexistent"))
sys.path.insert(0, str(REPO))
IST = "Asia/Kolkata"


# ---- D-04: no recency: an old record outweighs a recent reversal ----------------------------------------------------
def test_factor_reliability_has_no_recency():
    from quantdesk.intraday.learning import Memory
    m = Memory(None)
    for i in range(300):                                   # long ago: right 70% of the time
        m.bump("factor", "x", i % 10 < 7, 1.0)
    for i in range(100):                                   # lately: right only 30% of the time
        m.bump("factor", "x", i % 10 < 3, -1.0)
    assert m.reliability("factor", "x") > 1.0              # still up-weighted: the reversal barely registers


# ---- D-04: an anti-predictive factor keeps voting, in its original direction ---------------------------------------
def test_anti_predictive_factor_is_floored_not_removed():
    from quantdesk.intraday.learning import Memory
    m = Memory(None)
    for i in range(1000):
        m.bump("factor", "bad", i % 10 < 2, -1.0)          # wrong 80% of the time over 1,000 graded reads
    assert m.reliability("factor", "bad") == pytest.approx(0.5)   # floor 0.5×: never 0, never flipped


# ---- D-07: self-review never sees a WARN-level learning failure -----------------------------------------------------
def test_self_review_ignores_warn_level_learning_failures(tmp_path):
    import datetime as dt
    from quantdesk.journal.journal import Journal
    from quantdesk.ops.selfreview import check_session
    j = Journal(tmp_path / "j.db")
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-10-05"})
    t = pd.Timestamp("2026-10-08 09:15", tz=IST)
    j.event(t, "INFO", "session", "session start; expiries …")
    for k in range(3):
        j.event(t + pd.Timedelta(hours=3 * k), "WARN", "learning", "grading failed: Cannot losslessly convert units")
    j.commit()
    assert check_session(j, dt.date(2026, 10, 8), True) == []       # no finding filed


# ---- D-08: truncated graded-id lists let old headlines be graded again ----------------------------------------------
def test_truncated_graded_news_ids_are_regraded(tmp_path):
    from quantdesk.intraday.learning import Memory, grade_news
    p = tmp_path / "m.json"
    m = Memory(p)
    m.d["graded"]["news"] = [f"old{i}" for i in range(5000)] + ["n1"]
    m.save()
    m = Memory(p)
    assert "n1" in m.d["graded"]["news"] and "old0" not in m.d["graded"]["news"]   # the oldest ids fell off
    idx = pd.date_range("2026-10-08 09:15", "2026-10-08 15:29", freq="1min", tz=IST)
    bars = {"NIFTY": pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": range(1, len(idx) + 1), "volume": 0.0},
                                  index=idx).astype(float)}
    news = pd.DataFrame([{"id": "old0", "ts": "2026-10-08 10:00:00+05:30", "source": "X", "sentiment": 0.8,
                          "about": json.dumps({"NIFTY": 4}), "nlp": json.dumps({})}])
    assert grade_news(m, news, bars) == 1                  # graded (again) because its id was truncated away


# ---- D-03: the learning record mixes provenance and can't be rebuilt from the journal --------------------------------
def test_memory_mixes_bootstrap_and_live_sessions_without_tags():
    p = JOURNAL / "memory.json"
    if not p.exists():
        pytest.skip("journal snapshot not available")
    m = json.loads(p.read_text())
    boot = set(m["bootstrap"]["days"])
    assert boot and boot < set(m["days"])                  # bootstrap replay days and live days share one record
    assert all(set(r) == {"n", "hits", "sum", "sum2"} for r in m["tables"]["factor"].values())   # sums only, no source
    data_days = {d.name for d in (JOURNAL / "data").iterdir()}
    assert {"2026-09-24", "2026-09-25", "2026-09-28"} <= set(m["days"]) and not ({"2026-09-24", "2026-09-25"} & data_days)
