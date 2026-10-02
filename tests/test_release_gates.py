import json
from types import SimpleNamespace

import numpy as np
import pandas as pd

from quantdesk.journal.journal import Journal
from quantdesk.research.protocol import (
    FINAL_TEST_END,
    FINAL_TEST_START,
    append_experiment,
    append_warehouse_experiment,
    development_data,
    development_sample,
    evaluate_paper_candidate,
    paper_strategy_fingerprint,
    record_locked_final_result,
    register_locked_candidate,
)


def test_locked_final_window_is_excluded_from_all_routine_inputs():
    idx = pd.date_range("2026-10-01", "2026-10-08", tz="Asia/Kolkata")
    values = pd.Series(np.arange(len(idx)), index=idx)
    sample = development_sample(values)
    assert sample.index.max().tz_localize(None) < FINAL_TEST_START
    data = {
        "daily": {"NIFTY": pd.DataFrame({"close": values}, index=idx)},
        "global": {"daily": {"SPX": pd.DataFrame({"close": values}, index=idx)}},
    }
    locked = development_data(data)
    assert locked["daily"]["NIFTY"].index.max().tz_localize(None) < FINAL_TEST_START
    assert locked["global"]["daily"]["SPX"].index.max().tz_localize(None) < FINAL_TEST_START
    assert FINAL_TEST_END > FINAL_TEST_START


def test_experiment_log_is_append_only_and_json_safe(tmp_path):
    path = tmp_path / "experiment_log.jsonl"
    result = SimpleNamespace(id="D1", symbol="NIFTY", hypothesis="planted", params={"x": np.float64(np.nan)},
                             n=100, effect_bps=1.0, p_holdout=0.04, hurdle_pts=2.0, verdict="PAPER CANDIDATE")
    data = {"daily": {"NIFTY": pd.DataFrame({"close": [1.0, 2.0]}, index=pd.date_range("2026-10-01", periods=2))},
            "global": {"daily": {"SPX": pd.DataFrame({"close": [3.0, 4.0]}, index=pd.date_range("2026-10-01", periods=2))}}}
    one = append_experiment(path, data, [result], "2026-10-02 09:00 IST", "run-one")
    two = append_experiment(path, data, [result], "2026-10-02 09:01 IST", "run-two")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["run_id"] == "run-one" and rows[1]["run_id"] == "run-two"
    assert one["rolling_validation_is_final"] is False and two["experiments"][0]["parameters"]["x"] is None
    assert "global:daily:SPX" in two["datasets"] and "pandas" in two["software"]


def test_warehouse_hypotheses_are_in_the_same_experiment_ledger(tmp_path):
    path = tmp_path / "experiment_log.jsonl"
    source = tmp_path / "fo_bhav_test.parquet"
    source.write_bytes(b"frozen test source")
    data = {"daily": {"NIFTY": pd.DataFrame({"close": [1.0]}, index=pd.date_range("2026-10-01", periods=1))}}
    append_warehouse_experiment(path, data,
        {"vrp": [{"strategy": "condor", "symbol": "NIFTY", "k": 1, "verdict": "PAPER CANDIDATE"}],
         "positioning": [{"id": "P1", "symbol": "NIFTY", "hypothesis": "sample", "verdict": "NO EDGE"}]},
        "2026-10-02 09:00 IST", "run-warehouse", tmp_path)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["event"] == "warehouse_research_completed"
    assert row["hypotheses"]["vrp"][0]["strategy"] == "condor"
    assert row["hypotheses"]["positioning"][0]["id"] == "P1"
    assert row["rolling_validation_is_final"] is False
    assert row["warehouse_files"][source.name]["sha256"]


def test_paper_gate_is_cost_inclusive_and_final_test_required():
    pnl = [100.0] * 30
    trades = pd.DataFrame({"status": ["closed"] * 30, "pnl": pnl})
    gate = evaluate_paper_candidate(trades, observed_sessions=60, risk_violations=0, capital=20_000)
    assert gate["status"] == "PAPER PASS; FINAL TEST REQUIRED"
    assert not gate["eligible"] and not gate["checks"]["locked_final_test_passed"]
    locked = evaluate_paper_candidate(trades, 60, 0, 20_000, final_test_passed=True)
    assert locked["eligible"] and locked["status"] == "ELIGIBLE FOR PROMOTION REVIEW"
    failed = evaluate_paper_candidate(trades, 60, 1, 20_000, final_test_passed=True)
    assert not failed["eligible"] and not failed["checks"]["no_risk_limit_violations"]


def test_locked_candidate_registration_and_final_evaluation_are_sealed_once(tmp_path):
    manifest_path = tmp_path / "candidate.json"
    ledger = tmp_path / "experiments.jsonl"
    manifest = register_locked_candidate(
        manifest_path, strategy="opening_range", account="candidate-a", since="2026-01-01",
        preperiod_gate={"eligible_for_paper_trial": True}, ledger=ledger, today="2026-10-02")
    assert manifest["paper_strategy_sha256"] == paper_strategy_fingerprint()
    assert manifest_path.exists()
    try:
        register_locked_candidate(manifest_path, strategy="opening_range", account="candidate-a",
                                  since="2026-01-01", preperiod_gate={"eligible_for_paper_trial": True},
                                  today="2026-10-02")
        assert False, "manifest replacement must fail"
    except ValueError as exc:
        assert "already exists" in str(exc)
    final_gate = {"eligible_for_paper_trial": True, "locked_final_test_passed": True, "eligible": True}
    row = record_locked_final_result(ledger, manifest, final_gate, today="2027-04-01")
    assert row["result"] == "PASS; promotion review required" and row["promotion_allowed"] is False
    try:
        record_locked_final_result(ledger, manifest, final_gate, today="2027-04-01")
        assert False, "second final evaluation must fail"
    except ValueError as exc:
        assert "lock" in str(exc).lower() or "already recorded" in str(exc).lower()


def test_locked_candidate_cannot_register_after_final_window_starts(tmp_path):
    try:
        register_locked_candidate(tmp_path / "candidate.json", strategy="s", account="isolated",
                                  since="2026-01-01", preperiod_gate={"eligible_for_paper_trial": True},
                                  ledger=tmp_path / "experiments.jsonl", today="2026-10-05")
        assert False, "registration after seal must fail"
    except ValueError as exc:
        assert "sealed" in str(exc)


def test_journal_integrity_check_and_closed_file_recovery(tmp_path):
    path = tmp_path / "journal.db"
    journal = Journal(path)
    journal.event("2026-10-02T09:15:00+05:30", "INFO", "session", "started")
    journal.close()
    resumed = Journal(path)
    assert resumed.events(level="INFO")["category"].tolist() == ["session"]
    resumed.close()
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_workflows_pin_actions_and_declare_permissions():
    from deploy.check_workflows import check
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    assert all(not check(path) for path in root.glob("*.yml"))


def test_mobile_source_labels_network_stale_and_closed_states():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    app = (root / "quantdesk" / "web" / "static" / "app" / "app.js").read_text(encoding="utf-8")
    shim = (root / "quantdesk" / "web" / "export_site.py").read_text(encoding="utf-8")
    worker = (root / "quantdesk" / "web" / "static" / "app" / "sw.js").read_text(encoding="utf-8")
    page = (root / "quantdesk" / "web" / "static" / "app" / "index.html").read_text(encoding="utf-8")
    assert 't: "Offline"' in app and 't: inSession() ? "Offline" : "Closed"' in app
    assert "Network unavailable." in app and "Desk connection failed." in app
    assert "Showing the last saved state" in app and "No current session snapshot is available" in app
    assert 'addEventListener("offline"' in app and 'addEventListener("online"' in app
    assert 'X-QD-Offline-Cache' in shim and 'headers.set("X-QD-Offline-Cache", "1")' in worker
    assert 'name="viewport" content="width=device-width' in page
    # Mobile-specific layout is intentionally tuned below 380 CSS px and becomes a rail only at 1024 px.
    assert "@media (max-width:380px)" in page and "@media (min-width:1024px)" in page
