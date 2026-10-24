"""P0.5: the model card (quantdesk/ml/modelcard.py) and the prediction-event schema (quantdesk/ml/events.py).

Exit test of docs/ML_PHASE0.md P0.5: a model card is generated for every run and refuses to build without its provenance. So every required field is removed
in turn and the build must refuse naming it; then each consistency rule (a real commit, a window that ends before the cut-off, an interval that contains
the difference, the owner's switch for applied) is broken on its own.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys

import pytest

from quantdesk.ml import events as EV
from quantdesk.ml import modelcard as MC

SHA = "a" * 64
COMMIT = "b" * 40


def good_run(**over):
    run = {
        "model_id": "har-c", "version": "1",
        "spec": {"file": "docs/prereg/vol_forecast_v1.json", "sha256": SHA},
        "code_commit": COMMIT,
        "data": {"T1": {"manifest": "ml-intake-2-feae259bdba6", "digest": "47d28d6376ca63af", "status": "external_unverified"}},
        "training_window": {"start": "2010-01-04", "end": "2018-12-31", "cutoff": "2018-12-31"},
        "settings": {"params": {"lags": 5}, "seed": 7},
        "variants_tried": 4,
        "baseline": {"name": "A_desk", "version": "1"},
        "oos": {"metric": "QLIKE", "model": 0.155, "baseline": 0.20, "diff": -0.045, "interval": [-0.07, -0.02], "n_sessions": 1000},
        "leakage_tests": ["perturbation canary", "purged walk-forward"],
        "status": "offline",
    }
    run.update(over)
    return run


# ---- the exit test ---------------------------------------------------------------------------------------------------------
def test_a_complete_run_gets_a_card_with_a_digest_and_a_markdown_in_the_templates_layout():
    card = MC.build_card(good_run())
    assert card["card_version"] == 1 and len(card["digest"]) == 64 and MC.verify_card(card) == []
    md = MC.render_markdown(card)
    template = open("docs/ml/MODEL_CARD_TEMPLATE.md").read()
    required = [ln.split("|")[1].replace("(**required**)", "").replace("**", "").strip() for ln in template.splitlines() if "(**required**)" in ln]
    assert len(required) == 11 and len(MC.REQUIRED) == 12                           # "model id and version" is one row, two fields
    rows = [ln.split("|")[1].strip() for ln in md.splitlines() if ln.startswith("| ") and not ln.startswith("| Field")]
    for want in required:                                                           # the card carries each required row under the template's label
        assert any(want.startswith(r) for r in rows), want
    assert COMMIT in md and "47d28d6376ca63af" in md and "[-0.07, -0.02]" in md


@pytest.mark.parametrize("field", MC.REQUIRED)
def test_the_card_refuses_to_build_without_each_required_field(field):
    run = good_run()
    del run[field]
    with pytest.raises(MC.MissingProvenance, match=f"missing required field: {field}"):
        MC.build_card(run)
    empty = good_run(**{field: None})
    with pytest.raises(MC.MissingProvenance, match=field):
        MC.build_card(empty)


def test_every_missing_field_is_named_in_one_refusal():
    run = good_run()
    for k in ("code_commit", "baseline", "leakage_tests"):
        del run[k]
    with pytest.raises(MC.MissingProvenance) as e:
        MC.build_card(run)
    assert len(e.value.problems) == 3 and all(k in str(e.value) for k in ("code_commit", "baseline", "leakage_tests"))


# ---- consistency: provenance that is present but wrong ------------------------------------------------------------------------
@pytest.mark.parametrize("over,why", [
    ({"code_commit": "main"}, "full 40-hex commit"),
    ({"code_commit": "abc1234"}, "full 40-hex commit"),
    ({"code_commit": "b" * 39 + "-dirty"}, "full 40-hex commit"),
    ({"spec": {"file": "x.json", "sha256": "xyz"}}, "64-hex sha256"),
    ({"spec": {"sha256": SHA}}, "a file and a 64-hex sha256"),
    ({"data": {"T1": {"manifest": "m", "digest": "d"}}}, "manifest, digest and status"),
    ({"training_window": {"start": "2010-01-04", "end": "2019-06-30", "cutoff": "2018-12-31"}}, "start <= end <= cutoff"),
    ({"training_window": {"start": "2010-01-04", "end": "2018-12-31"}}, "start, end and cutoff"),
    ({"settings": {"params": {}}}, "params and seed"),
    ({"variants_tried": 0}, ">= 1"),
    ({"variants_tried": True}, ">= 1"),
    ({"variants_tried": 2.0}, ">= 1"),
    ({"baseline": {"name": "A_desk"}}, "a name and a version"),
    ({"leakage_tests": []}, "leakage_tests"),
    ({"leakage_tests": ["", "x"]}, "leakage_tests"),
    ({"status": "live"}, "status must be one of"),
    ({"model_id": "has space"}, "model_id"),
])
def test_provenance_that_is_present_but_wrong_is_refused(over, why):
    with pytest.raises(MC.MissingProvenance, match=why.replace("(", r"\(")):
        MC.build_card(good_run(**over))


@pytest.mark.parametrize("oos,why", [
    ({"interval": [-0.02, -0.07]}, "low <= high"),
    ({"interval": [-0.07]}, "low <= high"),
    ({"interval": [float("nan"), 0.0]}, "finite"),
    ({"diff": 0.5}, "inside oos.interval"),
    ({"model": float("inf")}, "finite numbers"),
    ({"n_sessions": 0}, "n_sessions"),
])
def test_the_out_of_sample_result_must_be_finite_and_its_interval_must_contain_the_difference(oos, why):
    run = good_run()
    run["oos"] = {**run["oos"], **oos}
    with pytest.raises(MC.MissingProvenance, match=why):
        MC.build_card(run)
    broken = good_run()
    del broken["oos"]["interval"]
    with pytest.raises(MC.MissingProvenance, match="oos is missing: interval"):
        MC.build_card(broken)


def test_the_cutoff_equal_to_the_training_end_is_allowed_and_one_day_before_is_not():
    MC.build_card(good_run())
    with pytest.raises(MC.MissingProvenance, match="cutoff"):
        MC.build_card(good_run(training_window={"start": "2010-01-04", "end": "2018-12-31", "cutoff": "2018-12-30"}))


# ---- status: only the owner makes a model applied ------------------------------------------------------------------------------
OWNER = {"by": "owner", "ts": "2026-10-26T09:00:00+05:30", "rule": "docs/prereg/xyz.json"}


def test_applied_needs_the_owners_switch_recorded_on_the_card():
    with pytest.raises(MC.MissingProvenance, match="owner_apply"):
        MC.build_card(good_run(status="applied"))
    with pytest.raises(MC.MissingProvenance, match="owner_apply"):
        MC.build_card(good_run(status="applied", owner_apply={"by": "owner", "ts": "", "rule": "r"}))
    card = MC.build_card(good_run(status="applied", owner_apply=OWNER))
    assert card["status"] == "applied" and "Owner's apply switch" in MC.render_markdown(card)
    assert MC.build_card(good_run(status="shadow"))["status"] == "shadow"          # shadow needs no switch


@pytest.mark.parametrize("old,new,owner,ok", [
    ("offline", "shadow", None, True), ("shadow", "applied", OWNER, True), ("shadow", "applied", None, False),
    ("shadow", "applied", {"by": "x"}, False), ("offline", "applied", OWNER, False),
    ("applied", "shadow", None, True), ("applied", "offline", None, True), ("shadow", "offline", None, True),
    ("shadow", "shadow", None, True), ("offline", "live", None, False), ("nope", "shadow", None, False),
])
def test_status_transitions_only_tighten_without_the_owner(old, new, owner, ok):
    assert MC.can_transition(old, new, owner)[0] is ok


# ---- storage: write once, tamper-evident ----------------------------------------------------------------------------------------
def test_a_card_is_written_once_and_a_changed_model_is_a_new_version(tmp_path):
    card = MC.build_card(good_run())
    jp, mp = MC.write_card(tmp_path, card)
    assert jp.name == "har-c-1.card.json" and mp.read_text().startswith("# Model card: har-c v1")
    MC.write_card(tmp_path, card)                                                   # the same card again: a no-op
    other = MC.build_card(good_run(variants_tried=5))
    with pytest.raises(FileExistsError, match="new version"):
        MC.write_card(tmp_path, other)
    MC.write_card(tmp_path, MC.build_card(good_run(variants_tried=5, version="2")))


def test_an_edited_card_fails_verification_and_is_not_written(tmp_path):
    card = MC.build_card(good_run())
    forged = copy.deepcopy(card)
    forged["oos"]["interval"] = [-0.5, 0.5]
    forged["oos"]["diff"] = -0.4
    assert any("digest does not match" in p for p in MC.verify_card(forged))
    with pytest.raises(MC.MissingProvenance, match="digest does not match"):
        MC.write_card(tmp_path, forged)
    assert not list(tmp_path.iterdir())


# ---- rolling grade and automatic demotion -------------------------------------------------------------------------------------
def test_the_rolling_grade_compares_the_last_window_with_the_baseline_and_leaves_out_non_finite_losses():
    outs = [{"loss": 1.0, "baseline_loss": 2.0}] * 10 + [{"loss": 3.0, "baseline_loss": 2.0}] * 5 + [{"loss": float("nan"), "baseline_loss": 2.0}]
    g = MC.rolling_grade(outs, window=5)
    assert g["n"] == 5 and g["dropped_non_finite"] == 1 and g["gain"] == pytest.approx(-1.0) and g["mean_loss"] == pytest.approx(3.0)
    g_all = MC.rolling_grade(outs, window=60)
    assert g_all["n"] == 15 and g_all["gain"] == pytest.approx((2.0 * 15 - (10 + 15)) / 15)
    assert MC.rolling_grade([], 5)["gain"] is None
    with pytest.raises(ValueError):
        MC.rolling_grade(outs, window=0)


def test_demotion_needs_enough_graded_predictions_and_a_negative_gain():
    worse = MC.rolling_grade([{"loss": 3.0, "baseline_loss": 2.0}] * 40, window=60)
    assert MC.should_demote(worse) is True
    assert MC.should_demote(MC.rolling_grade([{"loss": 3.0, "baseline_loss": 2.0}] * 29, window=60)) is False       # 29 < 30: no verdict yet
    assert MC.should_demote(MC.rolling_grade([{"loss": 1.0, "baseline_loss": 2.0}] * 40, window=60)) is False
    assert MC.should_demote(MC.rolling_grade([{"loss": 2.0, "baseline_loss": 2.0}] * 40, window=60)) is False      # a tie is not worse
    assert MC.should_demote(MC.rolling_grade([], 60)) is False


# ---- the command ------------------------------------------------------------------------------------------------------------------
def _cli(*args):
    return subprocess.run([sys.executable, "-m", "quantdesk", "ml", "card", *args], capture_output=True, text=True)


def test_the_command_builds_a_card_from_a_run_record_and_refuses_without_provenance(tmp_path):
    run = tmp_path / "run.json"
    run.write_text(json.dumps(good_run()))
    ok = _cli("--run", str(run), "--out", str(tmp_path / "cards"))
    assert ok.returncode == 0 and "digest" in ok.stdout and (tmp_path / "cards" / "har-c-1.card.md").exists()
    bad = good_run()
    del bad["code_commit"]
    del bad["variants_tried"]
    run.write_text(json.dumps(bad))
    refused = _cli("--run", str(run), "--out", str(tmp_path / "cards2"))
    assert refused.returncode != 0 and "code_commit" in refused.stderr and "variants_tried" in refused.stderr
    assert not (tmp_path / "cards2").exists()
    assert _cli("--out", str(tmp_path / "x")).returncode != 0                      # --run is required


# ---- prediction events --------------------------------------------------------------------------------------------------------
def good_prediction(**over):
    ev = {"schema_version": 1, "model_id": "har-c", "card_digest": SHA, "status": "shadow", "ts": "2026-10-26T09:30:00+05:30", "symbol": "NIFTY",
          "session": "2026-10-26", "horizon": 60, "target": "log_realised_variance", "prediction": -9.1, "baseline_prediction": -9.3,
          "features_digest": "c" * 64, "feature_ts_max": "2026-10-26T09:29:00+05:30"}
    ev.update(over)
    return ev


def good_outcome(**over):
    ev = {"schema_version": 1, "model_id": "har-c", "ref": {"ts": "2026-10-26T09:30:00+05:30", "symbol": "NIFTY", "horizon": 60},
          "graded_at": "2026-10-26T10:31:00+05:30", "realised": -9.0, "loss_name": "QLIKE", "loss": 0.12, "baseline_loss": 0.15}
    ev.update(over)
    return ev


def test_a_good_prediction_and_outcome_validate_and_map_to_the_journals_event_call():
    assert EV.validate(good_prediction(), EV.PREDICTION)
    level, cat, msg, data = EV.to_journal_args(good_prediction(), EV.PREDICTION)
    assert (level, cat) == ("INFO", "ml_prediction") and "har-c shadow NIFTY" in msg and data["card_digest"] == SHA
    level, cat, msg, data = EV.to_journal_args(good_outcome(), EV.OUTCOME)
    assert cat == "ml_outcome" and "QLIKE" in msg and data["ref"]["symbol"] == "NIFTY"
    assert EV.validate(good_prediction(horizon="close", baseline_prediction=None), EV.PREDICTION)


@pytest.mark.parametrize("over,why", [
    ({"status": "offline"}, "offline model makes no live event"), ({"card_digest": "123"}, "no card, no prediction"),
    ({"ts": "2026-10-26T09:30:00"}, "zone"), ({"feature_ts_max": "2026-10-26T09:31:00+05:30"}, "from the future"),
    ({"prediction": float("nan")}, "finite"), ({"prediction": "1.0"}, "finite"), ({"horizon": 45}, "horizon"),
    ({"session": "26 Oct"}, "session"), ({"features_digest": "zz"}, "features_digest"), ({"schema_version": 2}, "schema_version"),
    ({"baseline_prediction": float("inf")}, "baseline_prediction"), ({"model_id": "a b"}, "model_id"),
])
def test_a_bad_prediction_is_refused_with_the_reason(over, why):
    with pytest.raises(EV.BadEvent, match=why):
        EV.validate(good_prediction(**over), EV.PREDICTION)


@pytest.mark.parametrize("field", ["model_id", "card_digest", "ts", "symbol", "session", "horizon", "target", "prediction", "features_digest", "feature_ts_max"])
def test_every_prediction_field_is_required(field):
    ev = good_prediction()
    del ev[field]
    with pytest.raises(EV.BadEvent, match=f"missing {field}"):
        EV.validate(ev, EV.PREDICTION)


@pytest.mark.parametrize("over,why", [
    ({"graded_at": "2026-10-26T09:30:00+05:30"}, "after the prediction"), ({"graded_at": "2026-10-26T09:00:00+05:30"}, "after the prediction"),
    ({"loss": float("nan")}, "finite"), ({"baseline_loss": None}, "baseline_loss"), ({"ref": {"ts": "2026-10-26T09:30:00+05:30", "symbol": "NIFTY"}}, "ref needs"),
    ({"ref": {"ts": "2026-10-26T09:30:00+05:30", "symbol": "NIFTY", "horizon": 7}}, "horizon"), ({"graded_at": "2026-10-26T10:31:00"}, "zone"),
])
def test_a_bad_outcome_is_refused_with_the_reason(over, why):
    with pytest.raises(EV.BadEvent, match=why):
        EV.validate(good_outcome(**over), EV.OUTCOME)


def test_the_event_modules_import_nothing_from_the_desk():
    code = ("import sys; import quantdesk.ml.modelcard, quantdesk.ml.events; "
            "print(sorted(m for m in sys.modules if m.startswith('quantdesk')))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "['quantdesk', 'quantdesk.ml', 'quantdesk.ml.events', 'quantdesk.ml.modelcard']"


# ---- review fixes: the version is part of a file name; an interrupted write is redone; the command will not write into a tracked folder ----
@pytest.mark.parametrize("version", ["../x", "..", "a/b", "a\\b", ".hidden", "", "  ", "x" * 65, "v 1", "1\n2"])
def test_a_version_that_could_leave_the_folder_is_refused_before_anything_is_written(tmp_path, version):
    with pytest.raises(MC.MissingProvenance, match="version"):                 # "" is caught earlier as a missing field, the rest by the name rule
        MC.build_card(good_run(version=version))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("version", ["1", "2.1", "v3", "2026-10-26", "a_b-c"])
def test_ordinary_versions_are_accepted_and_stay_inside_the_folder(tmp_path, version):
    jp, mp = MC.write_card(tmp_path / "cards", MC.build_card(good_run(version=version)))
    assert jp.parent == mp.parent == tmp_path / "cards" and jp.name == f"har-c-{version}.card.json"


def test_an_interrupted_write_is_redone_not_half_kept(tmp_path):
    card = MC.build_card(good_run())
    (tmp_path / "har-c-1.card.md").write_text("half")                      # the .md was written, the .json (the commit marker) was not
    jp, mp = MC.write_card(tmp_path, card)
    assert jp.exists() and mp.read_text().startswith("# Model card: har-c v1")


def test_the_command_refuses_an_output_folder_inside_a_git_working_tree(tmp_path):
    from pathlib import Path
    probe = Path(__file__).resolve().parents[1] / "docs" / "ml_cards_probe"
    run = tmp_path / "run.json"
    run.write_text(json.dumps(good_run()))
    refused = _cli("--run", str(run), "--out", str(probe))
    assert refused.returncode != 0 and "inside a git working tree" in refused.stderr
    assert not probe.exists()
