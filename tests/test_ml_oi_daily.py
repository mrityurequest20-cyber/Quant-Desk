"""The daily OI grading check (quantdesk/ml/oi_daily.py): every forward weekday is graded or accounted for, and a missing or failing session is loud."""
import json

import pytest

from quantdesk.cli import main
from quantdesk.ml import oi_daily as OD
from tests.test_ml_oi import tape_dir

quiet = lambda *a, **k: None


def test_the_forward_weekdays_start_at_the_first_forward_session_and_skip_weekends():
    assert OD.forward_weekdays("2026-10-25") == []                                           # a Sunday before the start
    assert OD.forward_weekdays("2026-10-26") == ["2026-10-26"]
    assert OD.forward_weekdays("2026-11-02") == ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02"]
    assert OD.forward_weekdays("2026-11-01")[-1] == "2026-10-30"                             # a Sunday ends on the Friday


def fake_grade(days_ok=(), days_bad=()):
    def grade(source, day, out):
        if day in days_bad:
            raise RuntimeError("does not reproduce")
        return {"rows": {"NIFTY": 23, "BANKNIFTY": 23}, "usable60": {"NIFTY": 20, "BANKNIFTY": 20},
                "quarantine": {"NIFTY": {"snapshots": 375, "quarantined": 1}, "BANKNIFTY": {"snapshots": 375, "quarantined": 0}}}
    return grade


def with_tape(tmp_path, days, name="t"):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    for day in days:
        for part in ("morning-1", "afternoon-1"):
            (d / f"{day}_{part}_chains.parquet").write_bytes(b"x")
    return d


def test_every_graded_day_is_reported_with_its_counts(tmp_path):
    tape = with_tape(tmp_path, ["2026-10-26", "2026-10-27"])
    rep = OD.grade_all(tape, tmp_path / "o", "2026-10-27", say=quiet, grade=fake_grade())
    assert rep["ok"] and rep["graded"] == 2 and rep["failed"] == [] and rep["missing"] == []
    assert rep["days"][0] == {"day": "2026-10-26", "status": "graded", "rows": {"NIFTY": 23, "BANKNIFTY": 23}, "usable60": {"NIFTY": 20, "BANKNIFTY": 20},
                              "quarantined": {"NIFTY": 1, "BANKNIFTY": 0}, "snapshots": {"NIFTY": 375, "BANKNIFTY": 375}}


def test_a_trading_day_without_a_tape_is_missing_and_fails_the_run_until_it_is_graded(tmp_path):
    tape = with_tape(tmp_path, ["2026-10-26", "2026-10-28"])
    rep = OD.grade_all(tape, tmp_path / "o", "2026-10-28", say=quiet, grade=fake_grade())
    assert not rep["ok"] and rep["missing"] == ["2026-10-27"] and rep["graded"] == 2
    rep = OD.grade_all(with_tape(tmp_path, ["2026-10-27", "2026-10-28"], "t2"), tmp_path / "o", "2026-10-28", say=quiet, grade=fake_grade())
    assert rep["missing"] == ["2026-10-26"]                                                  # it stays on the list every day, nothing is dropped


def test_a_listed_exchange_holiday_without_a_tape_is_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(OD, "exchange_holidays", lambda: ({"2026-10-27"}, {2026}))
    rep = OD.grade_all(with_tape(tmp_path, ["2026-10-26", "2026-10-28"]), tmp_path / "o", "2026-10-28", say=quiet, grade=fake_grade())
    assert rep["ok"] and [r["status"] for r in rep["days"]] == ["graded", "holiday", "graded"]


def test_a_year_the_holiday_list_does_not_cover_is_unknown_not_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(OD, "exchange_holidays", lambda: (set(), {2025}))
    rep = OD.grade_all(with_tape(tmp_path, []), tmp_path / "o", "2026-10-26", say=quiet, grade=fake_grade())
    assert rep["ok"] and rep["days"] == [{"day": "2026-10-26", "status": "unknown"}]


def test_a_session_that_does_not_grade_is_a_finding_with_its_reason_and_does_not_stop_the_others(tmp_path):
    tape = with_tape(tmp_path, ["2026-10-26", "2026-10-27", "2026-10-28"])
    rep = OD.grade_all(tape, tmp_path / "o", "2026-10-28", say=quiet, grade=fake_grade(days_bad={"2026-10-27"}))
    assert not rep["ok"] and rep["failed"] == ["2026-10-27"] and rep["graded"] == 2
    assert "RuntimeError: does not reproduce" in rep["days"][1]["error"]


def test_a_day_with_only_the_morning_part_or_an_empty_index_is_partial_and_fails(tmp_path):
    one = tmp_path / "m"
    one.mkdir()
    (one / "2026-10-26_morning-1_chains.parquet").write_bytes(b"x")
    rep = OD.grade_all(one, tmp_path / "o", "2026-10-26", say=quiet, grade=fake_grade())
    assert not rep["ok"] and rep["partial"] == ["2026-10-26"] and "morning" in rep["days"][0]["why"]
    both = with_tape(tmp_path, [], "b")
    for part in ("morning-1", "afternoon-1"):
        (both / f"2026-10-26_{part}_chains.parquet").write_bytes(b"x")
    assert OD.grade_all(both, tmp_path / "o", "2026-10-26", say=quiet, grade=fake_grade())["ok"]
    def empty_index(source, day, out):
        return {"rows": {"NIFTY": 23, "BANKNIFTY": 0}, "usable60": {"NIFTY": 20, "BANKNIFTY": 0},
                "quarantine": {"NIFTY": {"snapshots": 375, "quarantined": 0}, "BANKNIFTY": {"snapshots": 0, "quarantined": 0}}}
    rep = OD.grade_all(both, tmp_path / "o", "2026-10-26", say=quiet, grade=empty_index)
    assert not rep["ok"] and "BANKNIFTY" in rep["days"][0]["why"]


def test_an_uncovered_year_warns_loudly_but_does_not_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(OD, "exchange_holidays", lambda: (set(), {2026}))
    said = []
    rep = OD.grade_all(with_tape(tmp_path, [], "u"), tmp_path / "o", "2027-01-05", say=said.append, grade=fake_grade())
    assert rep["unknown"] and any(m.startswith("::warning::") for m in said)


def test_the_default_day_is_the_last_session_that_should_be_complete(monkeypatch):
    import datetime as dt
    import quantdesk.cli as cli
    class Fake(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 27, *Fake.t, tzinfo=tz)
    monkeypatch.setattr(dt, "datetime", Fake)
    Fake.t = (16, 59)
    assert str(cli.last_completed_session_day()) == "2026-10-26"
    Fake.t = (17, 0)
    assert str(cli.last_completed_session_day()) == "2026-10-27"
    Fake.t = (0, 5)
    assert str(cli.last_completed_session_day()) == "2026-10-26"                              # a cron that arrives after midnight still means yesterday's session


def test_the_real_grader_runs_end_to_end_on_a_synthetic_tape(tmp_path):
    days = ["2026-10-26", "2026-10-27"]
    tape = tape_dir(tmp_path, days=tuple(days))
    out = tmp_path / "scratch"
    rep = OD.grade_all(tape, out, "2026-10-27", say=quiet)
    assert rep["ok"] and rep["graded"] == 2 and all(r["rows"]["NIFTY"] == 23 for r in rep["days"])
    assert sorted(p.name for p in out.glob("oi_*.json")) == [f"oi_{d}.json" for d in days]


# ---- the command ------------------------------------------------------------------------------------------------------
def test_the_command_lists_the_days_to_fetch(capsys):
    main(["ml", "oi-daily", "--days-only", "--today", "2026-10-28"])
    assert capsys.readouterr().out.split() == ["2026-10-26", "2026-10-27", "2026-10-28"]


def test_the_command_exits_one_on_a_missing_day_zero_otherwise_and_never_writes_into_a_tracked_tree(tmp_path, monkeypatch):
    tape = tape_dir(tmp_path, days=("2026-10-26",))
    monkeypatch.setattr(OD, "exchange_holidays", lambda: ({"2026-10-27"}, {2026}))
    main(["ml", "oi-daily", "--source", str(tape), "--out", str(tmp_path / "o"), "--today", "2026-10-27"])
    with pytest.raises(SystemExit) as e:
        main(["ml", "oi-daily", "--source", str(tape), "--out", str(tmp_path / "o2"), "--today", "2026-10-28"])
    assert e.value.code == 1
    with pytest.raises(SystemExit, match="git working tree"):
        main(["ml", "oi-daily", "--source", str(tape), "--out", str(OD.__file__.rsplit("/quantdesk/", 1)[0] + "/docs/probe"), "--today", "2026-10-26"])
    with pytest.raises(SystemExit, match="folder the read-out reads"):
        main(["ml", "oi-daily", "--source", str(tape), "--out", "runtime/ml_oi", "--today", "2026-10-26"])
    with pytest.raises(SystemExit, match="--source"):
        main(["ml", "oi-daily", "--today", "2026-10-26"])


# ---- the scheduled workflow -------------------------------------------------------------------------------------------
def test_the_scheduled_workflow_is_read_only_and_keeps_counts_only():
    import sys
    from pathlib import Path
    import yaml
    root = Path(OD.__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "deploy"))
    import check_workflows
    path = root / ".github" / "workflows" / "oi-daily.yml"
    text = path.read_text()
    wf = yaml.load(text, Loader=yaml.BaseLoader)
    assert wf["permissions"] == {"contents": "read"} and all("permissions" not in j for j in wf["jobs"].values())
    assert set(wf["on"]) == {"schedule", "workflow_dispatch"} and check_workflows.check(path) == []
    lowered = text.lower()
    for forbidden in ("secrets.", "git push", "git commit", "gh release upload", "gh release create", "gh pr", "gh api", "gh issue", "curl ", "--force",
                      "contents: write", "id-token", "pull-requests", "actions: write", "gh run"):
        assert forbidden not in lowered, forbidden
    steps = [s for j in wf["jobs"].values() for s in j["steps"]]
    assert [s["uses"].split("@")[0] for s in steps if "uses" in s] == ["actions/checkout", "actions/setup-python", "actions/upload-artifact"]
    uploads = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    assert [s["with"]["path"] for s in uploads] == ["oi_daily.txt"]                            # a text summary, never the tape or a table
    assert wf["defaults"]["run"]["shell"] == "bash" and all("shell" not in s for s in steps)  # bash -e -o pipefail: `| tee` cannot hide a failure
    assert all("${{" not in s["run"] for s in steps if "run" in s)
    assert "gh release download" in text and "--dir tape" in text
    assert "--out runtime/ml_oi_daily" in text and "runtime/ml_oi " not in text                   # never the folder the read-out reads


def test_a_local_run_without_out_gets_a_fresh_scratch_folder_each_time(tmp_path, monkeypatch):
    """A morning-only run can leave tables whose input hashes the afternoon's tape then changes; a rerun into the same folder would refuse. So the default is a new
    folder per run, under runtime/ml_oi_daily, and an explicit --out is used as given."""
    from pathlib import Path

    from quantdesk.cli import build_parser
    seen = []
    monkeypatch.setattr(OD, "grade_all", lambda source, out, today: seen.append(Path(out)) or {"ok": True})
    cfg = type("Cfg", (), {"runtime_dir": tmp_path / "runtime"})()
    tape = tmp_path / "tape"
    tape.mkdir()
    for argv in (["--source", str(tape), "--today", "2026-10-27"], ["--source", str(tape), "--today", "2026-10-27"],
                 ["--source", str(tape), "--today", "2026-10-27", "--out", str(tmp_path / "given")]):
        a = build_parser().parse_args(["ml", "oi-daily", *argv])
        a.fn(cfg, a)
    assert seen[0] != seen[1] and seen[0].parent == seen[1].parent == tmp_path / "runtime" / "ml_oi_daily"        # fresh each run, under the scratch parent
    assert seen[2] == tmp_path / "given"                                                                        # an explicit --out is used as given
