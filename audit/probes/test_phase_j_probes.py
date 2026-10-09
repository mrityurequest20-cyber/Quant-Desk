"""Phase J forensic probes: UI truthfulness (read-only: static inspection of the app, the API over COPIES of journals,
and journals written by the engine itself in synthetic temp-dir sessions; no browser needed for these probes).

    QD_JOURNAL=<close snapshot>/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_j_probes.py

The rendered-UI evidence (headless Chromium screenshots and visible text) is produced separately by phase_j_site.py +
phase_j_shoot.py / phase_j_focus.py and saved under audit/data/phase_j_screens/.
Each passing probe CONFIRMS the Phase J finding or control it names (audit/QUANTDESK_PHASE_J_UI_TRUTHFULNESS.md).
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = Path(os.environ.get("QD_REPO", str(HERE.parents[1])))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
APP = (REPO / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")


def _journal():
    p = os.environ.get("QD_JOURNAL")
    if not p or not Path(p).exists():
        pytest.skip("QD_JOURNAL not set")
    return Path(p)


def _site_data(src: Path) -> dict:
    """The exact data object the published site serves (export_site.site_data), built from a COPY of src."""
    from quantdesk.config import Config, DEFAULT_CONFIG
    from quantdesk.journal.journal import Journal
    from quantdesk.web.export_site import site_data
    tmp = Path(tempfile.mkdtemp(prefix="j-probe-"))
    acct = tmp / "rt" / "intraday"
    acct.mkdir(parents=True)
    for n in ("journal.db", "memory.json", "broker.json", "data"):
        if (src / n).is_dir():
            shutil.copytree(src / n, acct / n, ignore=lambda d, x: [y for y in x if y == "chains"])
        elif (src / n).exists():
            shutil.copy(src / n, acct / n)
    if not (acct / "journal.db").exists():
        shutil.copy(src / "j.db", acct / "journal.db")
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    j = Journal(acct / "journal.db")
    if j.get_state("intraday_account") is None:                       # as production's ensure_account writes it
        j.set_state("intraday_account", {"capital": float(cfg.get("intraday.capital")), "since": "2026-09-01"})
    j.close()
    return json.loads(json.dumps(site_data(cfg, "live", 3, live=True), default=str))


@pytest.fixture(scope="module")
def crash_sites():
    import phase_h_det_tests as H
    import phase_i_evidence as E
    bars, days = H.world()
    E.entry_crash(bars, days[-1])
    E.exit_crash(bars, days[-1])
    last = lambda pat: sorted(Path(tempfile.gettempdir()).glob(pat), key=lambda p: p.stat().st_mtime)[-1]  # noqa: E731
    return {"8a": _site_data(last("i-8a-*")), "8b": _site_data(last("i-8b-*"))}


# ---- J-01: the zero India VIX is presented as a valid, learned, maximally bullish vote ----------------------------------
def test_zero_vix_is_served_to_the_ui_as_a_normal_factor():
    d = _site_data(_journal())
    ev = [e for v in d["state"]["heartbeat"]["views"].values() for e in v["evidence"] if e["factor"] == "vix"]
    assert ev and all(e["observation"].startswith("India VIX 0.00 (-100.0% today)") and e["direction"] == 1.0 for e in ev)
    assert all(e["learned"] is not None for e in ev)                                     # rendered as "learned ×0.95"
    assert set(ev[0]) == {"factor", "category", "direction", "weight", "observation", "learned"}   # no validity flag


# ---- J-02 / J-03: halts and broker/journal disagreement --------------------------------------------------------------------
def test_halts_fact_omits_safe_mode_and_reconcile():
    m = re.search(r"const hl = \[(.*?)\]\.filter", APP)
    assert m and "kill_switch" in m.group(1) and "safe_mode" not in m.group(1) and "reconcile" not in m.group(1)


def test_a_halted_action_has_no_status_class_and_falls_to_the_generic_headline():
    body = APP[APP.index("function readAction"):APP.index("function stance")]
    assert "halted" not in body.lower()                                                   # → kind "other"
    assert 'else head = "Reading the market every minute"' in APP


def test_entry_crash_shows_a_loss_with_no_position(crash_sites):
    st = crash_sites["8a"]["state"]
    hb = st["heartbeat"]
    assert hb["halts"]["reconcile"] is True and hb["positions"] == []                    # orphan leg not shown
    assert st["equity"] < st["capital"] - 10000 and st["total_trades"] == 0               # −₹16k, "0 trades"


def test_exit_crash_shows_a_phantom_gain_and_no_naked_short(crash_sites):
    st = crash_sites["8b"]["state"]
    hb = st["heartbeat"]
    assert hb["halts"]["reconcile"] is True and hb["positions"] == []                    # −65 short not shown
    assert st["equity"] > st["capital"] + 10000 and st["total_pnl"] < 0                  # +₹13k "today", −₹597 all-time


def test_positions_and_equity_come_from_the_engine_not_the_broker():
    from quantdesk.intraday import engine
    import inspect
    src = inspect.getsource(engine.IntradayEngine._heartbeat)
    assert "for t in self.open_trades" in src and "broker.positions" not in src
    assert "self.broker.positions" not in inspect.getsource(engine.IntradayEngine.equity)


# ---- J-04: news times ------------------------------------------------------------------------------------------------------
def test_feed_shows_publish_time_not_first_seen():
    row = APP[APP.index("function newsRow"):APP.index("async function renderLog")]
    assert "ago(r.ts)" in row and "seen_at" not in APP


# ---- J-05: no-trade reasons ------------------------------------------------------------------------------------------------
def test_rejection_decisions_are_not_served_to_the_ui():
    api = (REPO / "quantdesk/web/intraday_api.py").read_text()
    assert "FROM decisions" not in api and "def decisions" not in api and "decision" not in APP.split("GLOSS")[0].lower()


def test_stand_aside_glossary_omits_the_dominant_production_reasons():
    g = re.search(r'aside: \["Standing aside", "(.*?)"\]', APP).group(1)
    assert "entry window" not in g and "plan model" not in g and "scheduled event" not in g


# ---- J-06: global intelligence --------------------------------------------------------------------------------------------
def test_unvalidated_global_drivers_vote_while_the_ui_says_only_validated_links_do():
    assert "only links the weekly research has validated on real data actually vote in the bias" in APP
    with sqlite3.connect(f"file:{_journal() / 'journal.db'}?mode=ro", uri=True) as c:
        w = [e["weight"] for (ev,) in c.execute("SELECT evidence FROM thoughts") for e in json.loads(ev)
             if e["factor"] == "global_crude"]
        hb = json.loads(c.execute("SELECT value FROM state WHERE key='intraday_live'").fetchone()[0])
    assert sum(x > 0 for x in w) >= 100                                                     # 194 of 501 reads
    crude = [d for d in hb["views"]["NIFTY"]["brain"]["drivers"] if "Crude" in d["name"]]
    assert crude and crude[0]["validated"] is False                                         # shown as "Probation"


# ---- J-07: learning -------------------------------------------------------------------------------------------------------
def test_sessions_graded_counts_bootstrap_and_pre_reset_days():
    m = json.loads((_journal() / "memory.json").read_text())
    days = m.get("days") or []
    assert {"2026-09-24", "2026-09-25", "2026-09-28"} <= set(days)                         # bootstrap replays (D-03)
    assert "len(self.memory.d.get(\"days\")" in (REPO / "quantdesk/intraday/engine.py").read_text()


# ---- J-08: chart levels are recomputed by the API, not the engine's -------------------------------------------------------
def test_chart_prior_day_levels_disagree_with_the_engine_after_an_unrecorded_day():
    from quantdesk.config import Config, DEFAULT_CONFIG
    from quantdesk.web.intraday_api import IntradayAPI
    src = _journal()
    tmp = Path(tempfile.mkdtemp(prefix="j-lv-"))
    shutil.copytree(src, tmp / "rt" / "intraday", ignore=lambda d, n: [x for x in n if x in ("autolearn", "chains")])
    api = IntradayAPI(Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}}))
    lv = api.chart("live", "NIFTY", "2026-10-05", "1m")["levels"]
    with sqlite3.connect(f"file:{tmp / 'rt/intraday/journal.db'}?mode=ro", uri=True) as c:
        eng = json.loads(c.execute("SELECT levels FROM thoughts WHERE symbol='NIFTY' AND substr(ts,1,10)='2026-10-05' "
                                   "ORDER BY id DESC LIMIT 1").fetchone()[0])
    assert abs(lv["pdl"] - eng["pdl"]) > 100                                                # 22,616.60 vs 22,217.65


# ---- J-09 / controls -------------------------------------------------------------------------------------------------------
def test_stale_banner_blames_a_handover_whatever_the_age():
    assert "It hands over to a fresh runner at 12:20, and a restart takes a few minutes" in APP


def test_paper_glossary_claims_real_chains_and_costs_unconditionally():
    g = re.search(r'paper: \["Paper trading", "(.*?)"\]', APP).group(1)
    assert "real option chains" in g and "real costs" in g


def test_model_chain_fallback_is_disclosed_in_the_quant_panel():                           # control V-J2
    assert 'c.source === "model"' in APP and "priced off India VIX" in APP


def test_stress_size_cut_is_described_as_active():
    assert "Above 2σ the desk cuts position size, down to half." in APP
