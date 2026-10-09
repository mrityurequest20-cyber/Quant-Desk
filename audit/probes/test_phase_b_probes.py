"""Phase B forensic probes (read-only: temp dirs only, no repo state touched).

    git fetch origin journal && mkdir -p /tmp/qd_journal && git archive FETCH_HEAD | tar -x -C /tmp/qd_journal
    QD_JOURNAL=/tmp/qd_journal/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Each passing probe CONFIRMS the finding it names (audit/QUANTDESK_FINDINGS_REGISTER.md).
"""
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

REPO = Path(os.environ.get("QD_REPO", str(Path(__file__).resolve().parents[2])))
JOURNAL = Path(os.environ.get("QD_JOURNAL", "/nonexistent"))
sys.path.insert(0, str(REPO))
IST = "Asia/Kolkata"


# ---- B-05: max_pain evidence is unreachable ---------------------------------------------------------------------------
def test_expiry_day_is_never_today_so_max_pain_never_fires():
    from quantdesk.intraday.engine import IntradayEngine
    today = dt.date(2026, 10, 13)                                      # a NIFTY weekly expiry (Tuesday)
    stub = SimpleNamespace(chains=SimpleNamespace(expiries=lambda u: [today, today + dt.timedelta(days=7)]),
                           expiry_min_days=1, cal=None, cfg=None, journal=None)
    picked = IntradayEngine.pick_expiry(stub, "NIFTY", today)
    assert picked != today                                              # engine.py:180 drops 0-DTE
    # analyst gets is_expiry_day = (self.expiry[u] == self.day)  (engine.py:296): always False → max_pain never added
    src = (REPO / "quantdesk/intraday/engine.py").read_text()
    assert "self.expiry[u] == self.day" in src


# ---- B-07: a plan-gate rejection of an armed fire is never graded by no-trade learning --------------------------------
def test_armed_rejections_by_plan_gate_are_never_graded():
    from quantdesk.intraday.learning import Memory, grade_armed
    db = JOURNAL / "journal.db"
    if not db.exists():
        pytest.skip("journal snapshot not available")
    from quantdesk.intraday.recorder import SessionRecorder
    bars = SessionRecorder(JOURNAL / "data").load_bars(["NIFTY", "BANKNIFTY"])
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        dec = pd.read_sql("SELECT * FROM decisions", c)
    armed = dec[dec["detail"].str.contains("reached its level", na=False)]
    assert len(armed) >= 20                                             # 21 in the 2026-10-09 snapshot
    assert all("target" not in json.loads(x) for x in armed["context"])  # the gate path omits it (engine.py:481)
    mem = Memory(None)
    assert grade_armed(mem, armed, bars) == 0                           # nothing graded, nothing learned


# ---- B-08: a retelling of an already-known event re-arms the breaking-news stand-aside days later --------------------
def test_retold_rbi_decision_two_days_later_still_vetoes():
    from quantdesk.config import Config, DEFAULT_CONFIG
    from quantdesk.intraday.news import NewsDesk, NewsItem, classify
    cfg = Config.load(DEFAULT_CONFIG)
    nd = NewsDesk(cfg, fetch=lambda url: "", sources=[])
    now = pd.Timestamp("2026-10-09 11:15", tz=IST)                      # the decision was 2026-10-07 10:00
    it = classify(NewsItem(pd.Timestamp("2026-10-09 11:12", tz=IST), "Mint",
                           "RBI hikes repo rate to 5.50%; shifts policy stance to ‘calibrated tightening’", "", "", ["Mint"]))
    nd.add([it])
    st = nd.state("NIFTY", now)
    assert st is not None and st["breaking"] is not None                # a 2-day-old decision blocks entries again


def test_question_style_preview_is_not_recognised_as_a_preview():
    from quantdesk.intraday.news import PREVIEW
    assert PREVIEW.search("Will RBI hike repo rate? MPC begins 3-day meet as surging crude oil, inflation test policy") is None


# ---- B-09: armed setups are built with no regard to the authorization gate -------------------------------------------
def test_arm_does_not_consult_the_plan_gate():
    import inspect
    from quantdesk.intraday import engine as E
    from quantdesk.intraday.playbook import Playbook
    arm_src = inspect.getsource(E.IntradayEngine._arm) + inspect.getsource(Playbook.arm)
    assert "plan_gate" not in arm_src and "_model_gates" not in arm_src
    fire_src = inspect.getsource(E.IntradayEngine._fire_armed)
    assert "_model_gates" in fire_src                                   # authorization happens only after the trigger


# ---- B-10: with a working live price, bar-range firing is switched off ------------------------------------------------
def test_bar_range_firing_disabled_when_live_price_works():
    import inspect
    from quantdesk.intraday import engine as E
    src = inspect.getsource(E.IntradayEngine.step)
    assert "if self.anticipate and not self.live_px" in src            # a level touched between 5 s polls is missed
