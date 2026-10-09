"""Phase K forensic probes: real-session forensics and timeline UI checks (read-only).

    QD_JOURNAL=<close snapshot>/intraday QD_CHAINS=<chains-2026 parquet dir> \
      python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_k_probes.py

Re-executing probes replay a recorded session from copies (exact persisted inputs, the repo's replay wiring) or run a
synthetic session; the rest check recorded artifacts in audit/data (outputs of phase_k_*.py) against the code.
Each passing probe CONFIRMS the Phase K finding or control it names (audit/QUANTDESK_PHASE_K_SESSION_FORENSICS.md).
"""
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "audit" / "data"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
APP = (REPO / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")


def _need(var):
    p = os.environ.get(var)
    if not p or not Path(p).exists():
        pytest.skip(f"{var} not set")
    return Path(p)


def _json(name):
    return json.loads((DATA / name).read_text())


# ---- K-01: a trigger rejected by the gate is re-armed at the same level in the same minute ("Waiting at the level") ----
def test_rejected_trigger_is_rearmed_in_the_same_minute_exact_replay():
    """Re-executes the exact 10-05 replay (persisted bars + chains-2026 + memory copy) up to 10:56."""
    jdir, cdir = _need("QD_JOURNAL"), _need("QD_CHAINS")
    from phase_i_replay import snapshots
    from quantdesk.config import Config, DEFAULT_CONFIG
    from quantdesk.intraday.chains import RecordedChains
    from quantdesk.intraday.engine import IntradayEngine
    from quantdesk.intraday.feeds import ReplayFeed
    from quantdesk.intraday.learning import Memory
    from quantdesk.intraday.recorder import SessionRecorder
    from quantdesk.intraday.sim import IntradayBroker
    from quantdesk.journal.journal import Journal
    day = dt.date(2026, 10, 5)
    tmp = Path(tempfile.mkdtemp(prefix="k-probe-"))
    acct = tmp / "rt" / "intraday"
    shutil.copytree(jdir / "data", acct / "data", ignore=lambda d, n: [x for x in n if x == "chains"])
    shutil.copy(jdir / "memory.json", acct / "memory.json")
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    u = cfg.get("intraday.underlyings")
    bars = SessionRecorder(acct / "data").load_bars(u + [cfg.get("universe.volatility_index")], upto=day)
    eng = IntradayEngine(cfg, ReplayFeed(bars, day), RecordedChains(snapshots(cdir, day, u)), Journal(acct / "j.db", autocommit_every=1),
                         IntradayBroker(cfg, starting_cash=500000, state_path=acct / "broker.json"), None, None, None, acct / "reviews",
                         memory=Memory(acct / "memory.json"))
    eng.start_session(day)
    while eng.feed.advance() and f"{eng.feed.now():%H:%M}" <= "10:56":
        eng.step()
    eng.journal.commit()
    rej = eng.journal.df("SELECT detail FROM decisions WHERE substr(ts,12,5)='10:56'")["detail"].tolist()
    hb = eng.journal.get_state("intraday_live")
    assert any(d.startswith("trend_break reached its level 22,465.46") and "no approved plan model" in d for d in rej)
    assert hb["views"]["NIFTY"]["action"].startswith("armed: trend_break: sell on a trade through 22,465.46")
    assert any(a["level"] == 22465.46 for a in hb["armed"])                       # the UI's "Waiting at the level"


def test_rearm_rendered_as_waiting_at_the_level():
    t = _json("phase_k_screens/k1005_03_armed_trigger_rejected_105630_text.json")["desk"]
    assert "Armed · Trend break put on NIFTY at 22,465.46" in t and "Waiting at the level" in t
    assert "no approved plan model" not in t.lower()                                # the real outcome isn't shown


# ---- K-02: a trigger that fired and was rejected is shown as "no setup has triggered" -------------------------------------
def test_fired_and_rejected_trigger_shown_as_no_setup_triggered():
    r = next(x for x in _json("phase_k_timeline_2026-10-08_vix_substituted.json")["records"] if x["label"] == "03_armed_trigger_rejected")
    assert any("reached its level" in d["detail"] for d in r["rows_this_minute"]["decisions"])
    assert r["heartbeat_actions"]["NIFTY"] == "watching: no setup has triggered"
    t = _json("phase_k_screens/k1008_03_armed_trigger_rejected_094430_text.json")["desk"]
    assert "NIFTY Watching: No setup has triggered" in t


# ---- K-03: the published site shows "Stale" at every session open -----------------------------------------------------------
def test_open_shows_stale_until_the_first_fresh_publish():
    assert re.search(r"every=\$\{PUBLISH_EVERY_MIN:-6\}", (REPO / "deploy/run-session.sh").read_text())
    assert "st.age_sec <= (pub ? 900 : 180)" in APP
    d = _json("phase_k_screens/prod_open_1012_091700_text.json")
    assert d["status_pill"].startswith("Stale") and "hands over to a fresh runner at 12:20" in d["desk"]


# ---- K-04: "Live" after the session has ended -----------------------------------------------------------------------------
def test_status_reads_live_after_the_close_on_production_data():
    d = _json("phase_k_screens/prod_close_1544_text.json")
    assert " ".join(d["status_pill"].split()) == "Live 15:30"                                 # 14 min after the close


# ---- K-05: trade detail made on modelled quotes is not labelled --------------------------------------------------------------
def test_trade_on_model_quotes_is_not_labelled_in_the_trade_sheet():
    t = _json("phase_k_trade_fixture.json")["trades"][0]
    m = json.loads(t["meta"])
    assert m["quote_source"] == "model" and m["fill_quotes"] == "option chain"      # the label itself says "option chain"
    sheet = _json("phase_k_screens/trade_orb_text.json")["sheet"]
    assert "NET P&L, AFTER COSTS" in sheet and not any(w in sheet for w in ("model chain", "modelled", "priced off India VIX"))
    assert t["rationale"][:200] in sheet                                              # control: rationale shown verbatim


# ---- controls: handover continuity and outage recovery -------------------------------------------------------------------------
def test_handover_keeps_account_figures_continuous_and_status_live():
    recs = {r["label"]: r for r in _json("phase_k_timeline_2026-10-05.json")["records"]}
    a, b, c = recs["05_handover_morning_last"], recs["06_handover_afternoon_restored"], recs["07_handover_afternoon_first_step"]
    assert a["heartbeat_equity"] == b["heartbeat_equity"] == c["heartbeat_equity"]
    assert b["heartbeat_ts"] == a["heartbeat_ts"] and b["engine_armed"] == {}          # armed state not carried (B-04)


def test_outage_is_flagged_and_recovers():
    log = {x["step"]: x for x in _json("phase_k_screens/outage_k1005_log.json")}
    assert log["outage_2_failing_70s"]["status_pill"].startswith("Offline") and "may be stale" in log["outage_2_failing_70s"]["banner"]
    assert log["outage_4_recovered"]["status_pill"].startswith("Live 12:21") and log["outage_4_recovered"]["banner"] == ""
    assert log["stuck_2_16min"]["status_pill"].startswith("Stale") and "hands over" in log["stuck_2_16min"]["banner"]


# ---- K-06 / session forensics -----------------------------------------------------------------------------------------------
def test_every_session_grades_zero_armed_setups():
    s = _json("phase_k_sessions.json")
    graded = [l for d in s.values() for l in d["learning"] if l.startswith("graded:")]
    assert len(graded) == 5 and all(", 0 armed," in l for l in graded)
    assert sum(len(d["decisions"]["armed_triggers"]) for d in s.values()) == 22


def test_vix_learned_multiplier_drifts_on_fabricated_input():
    s = _json("phase_k_sessions.json")
    m = [s[d]["subsequent_use_learned_multipliers_median"]["vix"] for d in sorted(s)]
    assert m[0] > 1.0 and m[-1] < 0.96                                                 # 1.02 → 0.954 across 10-05 … 10-09
