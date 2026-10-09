"""Phase H forensic probes (read-only: temp dirs, synthetic sessions, fake providers; no network, no real state).

    QD_JOURNAL=/tmp/qd_journal/intraday python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes

Each passing probe CONFIRMS the Phase H finding or control it names (audit/QUANTDESK_PHASE_H_RELIABILITY.md).
The deterministic tests 8 and 16 run the real engine (IntradayEngine, Journal, IntradayBroker) on a synthetic session
with the model chain: phase_h_det_tests.py; their recorded outcomes are in audit/data/phase_h_det_tests.json.
"""
import datetime as dt
import inspect
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(os.environ.get("QD_REPO", str(Path(__file__).resolve().parents[2])))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
IST = "Asia/Kolkata"


@pytest.fixture(scope="module")
def world():
    import phase_h_det_tests as H
    return H, *H.world()


# ---- §8 test 8: crash between the ledger (broker) write and the journal/state update --------------------------------
def test8_entry_crash_fails_closed_but_orphans_the_position_silently(world):
    H, bars, days = world
    r = H.test8_entry_crash(bars, days[-1])
    assert r["after_crash"]["broker_positions"] and not r["after_crash"]["journal_fills"]   # broker ahead of journal
    assert r["reconcile"]["ok"] is False and "disagree" in r["blocked"]                     # entries halted (control)
    assert r["end_of_day"]["broker_positions"] == r["after_crash"]["broker_positions"]       # never squared off
    assert r["selfreview_findings"] == [] and r["critical_events"]                         # CRITICAL, but no issue filed


def test8_exit_crash_double_exits_into_a_phantom_naked_short(world):
    H, bars, days = world
    r = H.test8_exit_crash(bars, days[-1])
    assert r["reconcile"]["ok"] is False and r["restart_open_trades"]                       # detected, trade restored
    pos = r["end_of_day"]["broker_positions"]
    assert any(q < 0 for q in pos.values()) and len(pos) == 1                               # a leg sold twice: short
    assert dict(r["end_of_day"]["journal_trades"])                                          # journal: trade "closed"
    assert all(s == "closed" for _, s in r["end_of_day"]["journal_trades"])


# ---- §8 test 16: restart recovery ------------------------------------------------------------------------------------
@pytest.mark.parametrize("graceful", [True, False])
def test16_mid_session_restart_restores_positions_and_risk_state(world, graceful):
    H, bars, days = world
    r = H.test16_restart(bars, days[-1], graceful)
    b, a = r["before"], r["after_restart"]
    assert a["open"] == b["open"] and a["trades_today"] == b["trades_today"]
    assert a["day_start_equity"] == b["day_start_equity"] and a["reconcile"]["ok"] is True
    assert a["thoughts_rows"] == b["thoughts_rows"]                                          # every minute is committed
    assert a["chain_cached"] == [] and a["chain_after_one_step"]                             # chain rebuilt next step
    assert a["armed"] == {}                                                                 # armed state not restored
    assert r["end_of_day"]["broker_positions"] == {}                                        # squared off once


def test16_position_left_overnight_is_ignored_and_halts_every_later_day(world):
    H, bars, days = world
    r = H.test16_overnight(bars, days)
    assert r["next_day_open_trades"] == [] and "never squared off; ignored" in " ".join(r["warn"])
    assert r["reconcile"]["ok"] is False and r["broker"]                                    # legs stay at the broker


# ---- H4 kill switch --------------------------------------------------------------------------------------------------
def test_file_kill_switch_works_but_lives_outside_the_saved_journal(world):
    H, bars, days = world
    r = H.test_kill_switch(bars, days[-1])
    assert r["file_kill"]["killed"] and r["file_kill"]["open_after"] == 0 and r["file_kill"]["broker"] == {}
    assert r["restart_same_disk"]["killed_after_restart"] is True
    assert r["kill_file_location"] == "rt/KILL"                                             # runtime/KILL …
    assert 'cd "$rt/intraday"' in r["journal_sh_saves_only"]                                # … journal.sh saves intraday/ only
    assert r["close_out"]["after"]["broker_positions"] == {}                                # the cancel path flattens


def test_the_phone_app_cannot_reach_the_live_engine():
    worker = (REPO / "deploy/cloudflare/worker.js").read_text()
    assert 'request.method !== "GET" && request.method !== "HEAD"' in worker                # read-only edge
    live = (REPO / ".github/workflows/live.yml").read_text()
    assert "if: cancelled()" in live and "--close-out" in live                              # the real kill switch: cancel


def test_safe_mode_is_not_carried_across_the_handover(world):
    H, bars, days = world
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="hsafe-"))
    a = H.make(tmp, bars, days[-1])
    a.start_session(days[-1])
    H.advance(a, "10:00")
    a.enter_safe_mode(a.feed.now(), "3 steps failed in a row, last: ReadTimeout")       # "no entries for the session"
    assert "safe mode" in a._blocked("NIFTY", H.view(a), a.feed.now())
    a._persist()                                                                            # run_live's hand-over path
    a.journal.commit()
    a.journal.db.close()
    b = H.make(tmp, bars, days[-1], "12:21")                                               # the afternoon job
    b.start_session(days[-1])
    b.step()
    assert b.health["safe_mode"] is None                                                    # forgotten by the new process
    assert "safe mode" not in (b._blocked("NIFTY", H.view(b), b.feed.now()) or "")


# ---- H1 scheduler and self-review timing --------------------------------------------------------------------------
def test_self_review_judges_a_session_before_it_has_happened(tmp_path):
    from quantdesk.journal.journal import Journal
    from quantdesk.ops.selfreview import check_session
    j = Journal(tmp_path / "j.db")
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-10-05"})
    j.event(pd.Timestamp("2026-10-05 09:15", tz=IST), "INFO", "session", "session start; expiries …")
    j.commit()
    # a 17:10 IST cron for 10-05 delivered at 01:14 IST on 10-06 defaults to "today" = 10-06
    found = check_session(j, dt.date(2026, 10, 6), True)
    assert [f.key for f in found] == ["session-missing"]                                    # issue #4, a false alarm
    assert "now" not in inspect.signature(check_session).parameters                        # no "has it happened yet"


def test_self_review_escalates_error_but_not_critical(tmp_path):
    from quantdesk.journal.journal import Journal
    from quantdesk.ops.selfreview import check_session
    j = Journal(tmp_path / "j.db")
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-10-05"})
    t = pd.Timestamp("2026-10-08 09:15", tz=IST)
    j.event(t, "INFO", "session", "session start; …")
    j.event(t, "CRITICAL", "risk", "reconciliation failed, entries halted: X: journal +0 vs broker +65")
    j.event(t, "CRITICAL", "risk", "safe mode: 3 steps failed in a row; 0 position(s) squared off, entries halted")
    j.commit()
    assert check_session(j, dt.date(2026, 10, 8), True) == []


def test_soft_failed_steps_keep_the_live_job_green():
    live = (REPO / ".github/workflows/live.yml").read_text()
    assert live.count("::warning::") >= 7
    from quantdesk.ops.selfreview import check_workflows
    src = inspect.getsource(check_workflows)
    assert '("failure", "timed_out", "startup_failure")' in src                            # success and cancelled pass silently


def test_worker_dispatch_failure_is_only_logged():
    worker = (REPO / "deploy/cloudflare/worker.js").read_text()
    assert "console.log(`desk scheduler ${r.ok ? \"dispatched\" : \"not dispatched\"}" in worker
    assert "fetch(" in worker and "issues" not in worker                                    # no alert path


def test_afternoon_job_runs_the_branch_tip_not_the_mornings_code():
    live = (REPO / ".github/workflows/live.yml").read_text()
    assert "ref: ${{ github.ref }}   # the branch tip" in live


# ---- H6 provider failures that become plausible values ----------------------------------------------------------
def test_missing_india_vix_becomes_a_silent_14(world):
    H, bars, days = world
    import tempfile
    eng = H.make(Path(tempfile.mkdtemp()), {k: v for k, v in bars.items() if k != "INDIAVIX"}, days[-1])
    eng.start_session(days[-1])
    H.advance(eng, "09:30")
    S, iv = eng.model_state("NIFTY", eng.feed.now())
    beta = eng.cfg.instrument_spec("NIFTY").get("iv_beta", 1.0)
    assert iv == pytest.approx(0.14 * beta)                                                 # no VIX → IV 14% × β
    src = inspect.getsource(type(eng).model_state)
    assert "else 14.0" in src and "Timedelta" not in src                                    # nor any freshness check


def test_gift_print_has_no_age_check():
    from quantdesk.data.nse import parse_gift
    old = {"giftnifty": {"LASTPRICE": "22500", "TIMESTMP": "07-Oct-2026 23:59", "EXPIRYDATE": "27-Oct-2026",
                         "PERCHANGE": "0.3", "DAYCHANGE": "60", "CONTRACTSTRADED": "1"},
           "indicativenifty50": {"finalClosingValue": 22400}}
    g = parse_gift(old, fetched=pd.Timestamp("2026-10-09 08:30", tz=IST))
    assert len(g) == 1                                                                       # a 2-day-old print accepted
    from quantdesk.intraday.engine import IntradayEngine
    assert "ts" not in inspect.getsource(IntradayEngine.preopen).split("gift_implied_gap(")[1].split(")")[0]


# ---- H9 storage ------------------------------------------------------------------------------------------------------
def test_plan_studies_are_outside_autolearn_retention():
    from quantdesk.autolearn import cycle
    src = inspect.getsource(cycle.Cycle._retention)
    assert '("datasets"' in src and '"runs"' in src and '"cycles"' in src and "studies" not in src
