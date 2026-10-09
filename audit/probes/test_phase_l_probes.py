"""Phase L forensic probes: final adversarial audit (read-only).

    QD_JOURNAL=<close snapshot dir holding intraday/> QD_CHAINS=<chains-2026 parquet dir> \
      python -m pytest -o addopts="" -q -p no:cacheprovider audit/probes/test_phase_l_probes.py

Re-executing probes replay a recorded session from copies, or check the repo's code; the rest check the recorded
artifacts in audit/data (outputs of phase_l_*.py) against the code. Each passing probe CONFIRMS the Phase L finding,
update or control it names (audit/QUANTDESK_PHASE_L_FINAL_AUDIT.md). After a fix, the probes marked "flips" fail.
"""
import datetime as dt
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATA = REPO / "audit" / "data"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))
APP = (REPO / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")
ENGINE = (REPO / "quantdesk/intraday/engine.py").read_text(encoding="utf-8")


def _need(var):
    p = os.environ.get(var)
    if not p or not Path(p).exists():
        pytest.skip(f"{var} not set")
    return Path(p)


def _json(name):
    return json.loads((DATA / name).read_text())


def _tot(mode, key):
    return _json("phase_l_consistency_summary.json")["totals_by_mode"][f"{mode}:{key}"]


# ---- the UI port used for every-minute counting -----------------------------------------------------------------------
def test_ui_port_matches_every_phase_k_chromium_render():
    r = _json("phase_l_ui_port_check.json")
    assert r["compared"] == 10 and r["all_match"]


# ---- L-01: an armed trigger's outcome never reaches the screen ------------------------------------------------------------
def test_every_replayed_trigger_rejection_is_hidden_from_the_screen():            # flips after the fix
    for mode in ("bar", "tick"):
        assert _tot(mode, "denominators")["stepped_minutes"] == 1870
        assert _tot(mode, "fire_outcomes") == {"rejected_model_gate": 60}
        v = _tot(mode, "outcome_visibility")
        assert v["decision_row_written"] == 60 and v["outcome_in_heartbeat_action"] == 0 and v["outcome_in_thought"] == 0


def test_bar_replay_screen_after_rejection_matches_k01_and_k02():
    s = _tot("bar", "screen_after_fire")
    assert s == {"rearmed_same_setup_same_level": 8, "rearmed_other": 6, "watching_no_setup_has_triggered": 41,
                 "standing_aside_other_reason": 5}


def test_tick_path_rejection_shows_waiting_with_nothing_armed():
    assert _tot("tick", "screen_after_fire")["stale_armed_action_empty_armed_list"] == 60
    t = _json("phase_l_screens/l1005_tick_rejected_105540_text.json")["desk"]
    assert "Watching · no setup has triggered" in t and "NIFTY Waiting at the level: Trend_break" in t


def test_fire_result_is_discarded_and_model_gate_rejection_is_decision_only():
    assert re.search(r"\n\s+self\._fire_armed\(sym, now, bar=", ENGINE)               # step(): return value unused
    assert "on the decision record only: this minute's read isn't formed yet" in ENGINE
    assert not re.search(r"decisions", " ".join(p.read_text(errors="ignore") for p in (REPO / "quantdesk/web").rglob("*.py")))
    assert "decisions" not in APP                                                      # no endpoint, no view (J-08)


def test_tick_path_rejection_reexecuted_on_the_exact_replay():
    jdir, cdir = _need("QD_JOURNAL"), _need("QD_CHAINS")
    from phase_l_consistency import main
    out = Path(tempfile.mkdtemp(prefix="l-probe-")) / "c.json"
    main(jdir, cdir, dt.date(2026, 10, 5), "tick", out, False)
    r = json.loads(out.read_text())
    assert r["outcomes"] == {"rejected_model_gate": 9}
    t = r["tick_heartbeats"][0]
    assert t["hb_actions"]["NIFTY"].startswith("armed: trend_break") and t["hb_armed"] == []


def test_production_rejections_came_from_the_live_tick_path_and_are_unrecorded_in_thoughts():
    p = _json("phase_l_prod_consistency.json")
    assert p["path"]["ev_rejection_second_of_minute"] == {"4": 51}                     # the minute step runs at :04
    assert p["path"]["armed_off_step_cadence"] == 22
    a = p["armed"]
    assert a["outcome_recorded_in_any_thought"] == 0
    f5 = a["first_sampled_thought_within_5min"]
    assert f5["rearmed_same_setup_same_level"] + f5["rearmed_same_setup_new_level"] == 7 and f5["watching_no_setup_has_triggered"] == 6


# ---- L-02: a hit while halted leaves no record ---------------------------------------------------------------------------
def test_halted_trigger_hit_leaves_no_record():                                    # flips after the fix
    r = _json("phase_l_blocked_silent.json")
    assert len(r["control_no_halt"]["decisions_1056"]) == 1
    assert r["halted"]["decisions_1056"] == [] and r["halted"]["thoughts_1056"] == []
    assert r["halted"]["heartbeat_action_NIFTY"].startswith("halted: safe mode")


# ---- L-03: published armed cards outlive their expiry -------------------------------------------------------------------
def test_published_armed_card_outlives_its_expiry():                               # flips after the fix
    cfg = (REPO / "config/quantdesk.yaml").read_text()
    assert re.search(r"ttl_min: 2\b", cfg)
    assert re.search(r"every=\$\{PUBLISH_EVERY_MIN:-6\}", (REPO / "deploy/run-session.sh").read_text())
    lines = [l for l in APP.splitlines() if "expires" in l]
    assert len(lines) == 1 and '"until " + ist(x.expires)' in lines[0]               # displayed, never compared with now
    g = _json("phase_l_published_armed.json")
    assert g["armed"] and g["armed"][0]["expires"] < "2026-10-09 12:52"                # next publish ≈ 6 min after 12:46
    assert g["replay_publish_points"]["with_armed_card"] == 138


# ---- I-07 update: the EV text's P(up) ------------------------------------------------------------------------------------
def test_ev_rows_print_a_p_up_the_evaluator_did_not_use():
    p = _json("phase_l_prod_consistency.json")["ev"]
    assert p["structures"] == {"iron_fly": 51} and p["message_p_up_not_0.50_while_nondirectional_evaluated_at_0.50"] == 33
    assert "p_up if v.direction != 0 else 0.5" in ENGINE
    assert 'fact("P(up) used", q.valid && fin(q.p_model) ? pct(q.p_model, 0)' in APP and "coin flip + prior" in APP
    e = _tot("bar", "ev_pup")
    assert e["ev_rejections"] == 41 and e["message_p_differs_from_p_used"] == 14 and e["ui_p_used_shows_coin_flip_while_message_has_number"] == 41


# ---- L2: India VIX propagation -------------------------------------------------------------------------------------------
def test_vix_multiplier_reconciles_exactly_with_the_record():
    v = _json("phase_l_vix_learning.json")
    for d, s in v["sessions"].items():
        assert abs(s["reliability_before_reconstructed"] - s["multiplier_recorded_on_thoughts_median"]) < 1e-4, d
    assert v["check_prev_snapshot"]["abs_diff_n"] < 1e-3 and v["check_prev_snapshot"]["abs_diff_hits"] < 1e-3
    assert v["since_reset_totals"]["fabricated_zero_read_n"] > 100 and v["since_reset_totals"]["real_read_n"] < 0.2
    assert v["close_multiplier_without_fabricated_reads"] > 1.0 > v["reliability_close"]


def test_vix_ic_is_ranked_on_a_near_constant_regressor():                          # L-06; flips after the fix
    r = _json("phase_l_vix_ic.json")
    assert r["rank_of_vix"] < 12 and all(s["var_d"] < 0.001 for s in r["vix_direction_stats"].values())
    assert "vx <= 1e-12" in (REPO / "quantdesk/intraday/learning.py").read_text()


def test_vix_vote_changes_the_replayed_decision_stream_but_no_trade():
    a, b = _json("phase_l_vix_counterfactual_2026-10-05.json"), _json("phase_l_vix_counterfactual_2026-10-08_subst.json")
    assert a["diff"]["vix_vote_+1_as_recorded"] == 750 and a["diff"]["bias_differs"] == 29 and len(a["decisions_only_without_vote"]) == 2
    assert b["diff"]["bias_differs"] == 6 and len(b["decisions_only_without_vote"]) == 1
    assert all("reached its level" in x and "standing aside" in x for x in a["decisions_only_without_vote"] + b["decisions_only_without_vote"])


def test_vix_is_the_only_invalid_recorded_bar_series():
    s = _json("phase_l_series_scan.json")
    assert sorted(s["bars_flagged"]) == [f"2026-10-0{d}/INDIAVIX_1m" for d in range(5, 10)]
    assert s["evidence"]["flagged_by_factor"] == {"vix": 742}


def test_candle_path_has_no_positive_guard_and_the_validation_exemption_is_off_path():
    k = (REPO / "quantdesk/intraday/kotak.py").read_text()
    candles = k[k.index("def candles"):k.index("# ---- the option chain")]
    assert "> 0" not in candles and "p == p and p > 0" in k                              # ltp() guards, candles don't
    users = [p for p in REPO.joinpath("quantdesk").rglob("*.py") if "from ..data.validation import audit" in p.read_text(errors="ignore")]
    assert [p.relative_to(REPO).as_posix() for p in users] == ["quantdesk/ops/checks.py"]


# ---- L3: scheduler attribution, post-close backup runs ---------------------------------------------------------------------
def test_i10_scheduler_attribution_matches_run_metadata():
    s = _json("phase_l_scheduler_runs.json")
    by_day = {}
    for r in s["runs"]:
        by_day.setdefault(r["created_at"][:10], []).append(r)
    assert [(r["event"], r["created_at"]) for r in by_day["2026-09-30"]] == [("schedule", "2026-09-30T09:49:30Z")]
    assert [(r["event"], r["created_at"]) for r in by_day["2026-10-01"]] == [("schedule", "2026-10-01T10:16:38Z")]
    assert s["scheduler_added"]["date"] < "2026-10-05" and s["scheduler_added"]["date"] > "2026-10-01T10:17"
    assert all(any(r["event"] == "workflow_dispatch" and r["created_at"][11:13] == "03" for r in by_day[d]) for d in
               ("2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"))


def test_post_close_backup_run_uploads_duplicate_mislabelled_assets():              # L-05; flips after the fix
    a = {x["name"]: x for x in _json("phase_l_release_assets.json")["assets"]}
    for day, late in (("2026-10-05", "37297771333"), ("2026-10-09", "37919282668")):
        m, f = a[f"{day}_morning-{late}_bars.parquet"], a[f"{day}_afternoon-{late}_bars.parquet"]
        assert m["size"] == f["size"] and m["created_at"][11:13] == "10"                # "morning" = the full day, after the close
        assert f"{day}_morning-{late}_chains.parquet" not in a


# ---- L4: Pages ---------------------------------------------------------------------------------------------------------------
def test_pages_deploy_time_is_measured_and_no_deployment_after_10_08():
    p = _json("phase_l_pages_latency.json")
    assert p["runs_listed"] == p["runs_total_reported"] == 389
    assert p["last"] < "2026-10-09" and p["build_deploy_seconds"]["median"] < 60
    assert all(v["first_ist"] >= "09:19" for d, v in p["session_cadence_by_day"].items() if d >= "2026-10-05")


def test_served_site_returned_404_after_the_session():                              # L-04 (an observation, not re-fetched)
    t = (DATA / "phase_l_pages_get_20261009T1835Z.txt").read_text()
    assert "HTTP/2 404" in t and "server: GitHub.com" in t


# ---- integrity of the audit itself --------------------------------------------------------------------------------------------
def test_canonical_register_is_unchanged():
    h = hashlib.sha256((REPO / "audit/QUANTDESK_FINDINGS_REGISTER.md").read_bytes()).hexdigest()
    assert h.startswith("e49341c0")
    assert _json("phase_l_consolidated_findings.json")["canonical_register_sha256"] == h


def test_consolidated_register_covers_a_to_l_and_marks_itself_proposed():
    c = _json("phase_l_consolidated_findings.json")
    assert c["status"].startswith("PROPOSED") and c["counts"]["findings"] == 115
    assert all(c["counts"]["by_phase"][p] > 0 for p in "ABCDEFGHIJKL")
    j01 = next(r for r in c["findings"] if r["id"] == "J-01")
    assert j01["severity"] == "P2" and j01["owner_decision"]["severity_proposed"] == "P1"   # carried, not applied
