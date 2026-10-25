"""P0.8: the retrain drill (quantdesk/ml/retrain.py): a refit of every registered model, in a scratch folder, compared with what the desk loads."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from quantdesk.autolearn import volstudy as V
from quantdesk.autolearn.prereg import spec_hash
from quantdesk.cli import main
from quantdesk.data.external_aeron import ForbiddenUse
from quantdesk.intraday.harvol import fit_coefs
from quantdesk.ml import retrain as RT
from tests.test_ml_reproduce import SPEC, synthetic_dataset

quiet = lambda *a, **k: None


def sha_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_manifest(ds: Path, **over) -> dict:
    import pandas as pd

    from quantdesk.data import external_aeron as X
    parts = {f"1m/symbol=NIFTY/{p.name}": X.frame_hash(pd.read_parquet(p)) for p in sorted((ds / "1m" / "symbol=NIFTY").glob("*.parquet"))}
    man = {"status": "external_verified", "dataset": ds.name, "source_url": "https://example.invalid/src", "source_commit": "a" * 40,
           "importer_version": "aeron7-2", "partitions": parts, **over}
    (ds / "manifest.json").write_text(json.dumps(man))
    return man


def committed_file(root: Path, ds: Path, spec: Path) -> Path:
    """What `autolearn vol-har-fit` would have committed for this dataset: the fit, plus a provenance block naming the inputs."""
    spec_d = json.loads(spec.read_text())
    grids = V.prepare(ds, spec_d["symbols"])
    import datetime as dt
    c = fit_coefs(grids, dt.date.fromisoformat(spec_d["dev"]["end"]), spec_d["name"], spec_hash(spec), ds.name)
    man = json.loads((ds / "manifest.json").read_text())
    c["provenance"] = {"spec": spec_d["name"], "inputs": {k: man.get(k) for k in ("source_url", "source_commit", "importer_version")}
                       | {"partitions_1m": {k: v for k, v in man["partitions"].items() if k.startswith("1m/")}},
                       "code_commit": "f" * 40, "created_at": "2026-10-24T00:00:00+00:00", "fit_command": "unit test"}
    f = root / "loaded" / "vol_har_test.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(c, indent=1))
    return f


@pytest.fixture()
def lab(tmp_path_factory):
    root = tmp_path_factory.mktemp("retrain")
    ds = synthetic_dataset(root)
    write_manifest(ds)
    spec = root / "unit_vol.json"
    spec.write_text(json.dumps(SPEC))
    f = committed_file(root, ds, spec)
    return {"root": root, "ds": ds, "spec": spec, "file": f, "models": (RT.Refit("c_har", f, spec, RT._har),)}


def drill(lab, out=None, **kw):
    return RT.drill(lab["ds"], out or lab["root"] / "out", models=lab["models"], say=quiet, **kw)


# ---- the refit itself -------------------------------------------------------------------------------------------------
def test_the_drill_refit_is_what_the_fit_command_makes_so_a_verified_dataset_gives_the_same_numbers(lab):
    d = json.loads(lab["spec"].read_text())
    import datetime as dt
    study = fit_coefs(V.prepare(lab["ds"], d["symbols"]), dt.date.fromisoformat(d["dev"]["end"]), d["name"], spec_hash(lab["spec"]), lab["ds"].name)
    assert RT._har(lab["ds"], lab["spec"]) == study


def test_a_fresh_import_is_read_unverified_where_the_study_refuses_it(lab):
    write_manifest(lab["ds"], status="external_unverified")
    with pytest.raises(ForbiddenUse):
        V.prepare(lab["ds"], ["NIFTY"])
    assert RT._har(lab["ds"], lab["spec"])["symbols"]["NIFTY"]["sessions"] > 100


# ---- the verdict ------------------------------------------------------------------------------------------------------
def test_a_refit_of_the_same_inputs_reproduces_the_committed_numbers_and_replaces_nothing(lab):
    before = sha_of(lab["file"])
    rep = drill(lab)
    row = rep["models"][0]
    assert rep["ok"] and row["verdict"] == "reproduced" and row["numbers"] > 300 and row["max_abs"] == 0.0 and row["input_findings"] == []
    assert sha_of(lab["file"]) == before                                                       # the file the desk loads is untouched
    out = lab["root"] / "out"
    assert sorted(p.name for p in out.iterdir()) == ["c_har.refit.json", RT.REPORT_NAME]
    assert json.loads((out / RT.REPORT_NAME).read_text())["ok"] is True
    assert row["committed_numbers_sha256"] == row["refit_numbers_sha256"]
    assert rep["dataset"]["source_commit"] == "a" * 40 and rep["versions"]["numpy"]


def test_an_unverified_fresh_import_of_the_same_source_still_reproduces(lab):
    write_manifest(lab["ds"], status="external_unverified")
    rep = drill(lab)
    assert rep["ok"] and rep["dataset"]["status"] == "external_unverified"                    # the report says what the data was


@pytest.mark.parametrize("edit,where", [
    (lambda d: d["symbols"]["NIFTY"]["fit"]["close"]["beta"].__setitem__(0, d["symbols"]["NIFTY"]["fit"]["close"]["beta"][0] + 1e-3), "/symbols/NIFTY/fit/close/beta[0]"),
    (lambda d: d["symbols"]["NIFTY"]["profile"].__setitem__(10, d["symbols"]["NIFTY"]["profile"][10] * 1.01), "/symbols/NIFTY/profile[10]"),
    (lambda d: d["symbols"]["NIFTY"]["fit"]["30m"].__setitem__("smear", d["symbols"]["NIFTY"]["fit"]["30m"]["smear"] + 0.01), "/symbols/NIFTY/fit/30m/smear"),
    (lambda d: d["symbols"]["NIFTY"].__setitem__("sessions", d["symbols"]["NIFTY"]["sessions"] + 1), "/symbols/NIFTY/sessions"),
    (lambda d: d["symbols"]["NIFTY"].__setitem__("trained_through", "2013-12-30"), "/symbols/NIFTY/trained_through"),
    (lambda d: d.__setitem__("dev_end", "2014-01-01"), "/dev_end"),
    (lambda d: d.__setitem__("spec_sha256", "0" * 64), "/spec_sha256"),
    (lambda d: d["symbols"].pop("NIFTY"), "/symbols/NIFTY"),
])
def test_an_edited_committed_number_or_identity_is_named(lab, edit, where):
    d = json.loads(lab["file"].read_text())
    edit(d)
    lab["file"].write_text(json.dumps(d))
    rep = drill(lab)
    row = rep["models"][0]
    assert not rep["ok"] and row["verdict"] == "differs" and any(where in m for m in row["mismatches"]), row["mismatches"]


def test_a_spec_edited_after_the_fit_no_longer_reproduces_it(lab):
    s = json.loads(lab["spec"].read_text())
    s["question"] = "a different question"
    lab["spec"].write_text(json.dumps(s))
    rep = drill(lab)
    assert not rep["ok"] and any("/spec_sha256" in m for m in rep["models"][0]["mismatches"])


def test_provenance_is_not_compared_as_numbers_but_the_inputs_it_records_are_checked(lab):
    d = json.loads(lab["file"].read_text())
    d["provenance"]["created_at"], d["provenance"]["code_commit"], d["provenance"]["fit_command"] = "2020-01-01", "e" * 40, "something else"
    lab["file"].write_text(json.dumps(d))
    assert drill(lab)["ok"]                                                                    # who ran it and when never decides the verdict


def test_the_same_numbers_from_different_inputs_are_not_called_reproduced(lab):
    write_manifest(lab["ds"], source_commit="b" * 40)
    rep = drill(lab)
    row = rep["models"][0]
    assert not rep["ok"] and row["verdict"] == "reproduced_on_different_inputs" and any("source_commit" in x for x in row["input_findings"])


def test_a_partition_that_no_longer_hashes_to_the_recorded_one_is_named(lab):
    man = json.loads((lab["ds"] / "manifest.json").read_text())
    k = sorted(man["partitions"])[0]
    man["partitions"][k] = "0" * 64
    (lab["ds"] / "manifest.json").write_text(json.dumps(man))
    rep = drill(lab)
    assert not rep["ok"] and any("do not match the files" in x and k in x for x in rep["models"][0]["input_findings"])


def test_a_committed_file_without_partition_hashes_cannot_vouch_for_its_inputs(lab):
    d = json.loads(lab["file"].read_text())
    del d["provenance"]["inputs"]["partitions_1m"]
    lab["file"].write_text(json.dumps(d))
    rep = drill(lab)
    assert not rep["ok"] and any("cannot be compared" in x for x in rep["models"][0]["input_findings"])


def test_different_numbers_on_different_inputs_say_differs_first(lab):
    write_manifest(lab["ds"], source_commit="b" * 40)
    d = json.loads(lab["file"].read_text())
    d["symbols"]["NIFTY"]["fit"]["close"]["smear"] += 0.5
    lab["file"].write_text(json.dumps(d))
    row = drill(lab)["models"][0]
    assert row["verdict"] == "differs" and row["input_findings"]


# ---- what the drill will not do ---------------------------------------------------------------------------------------
def test_the_output_may_not_sit_in_a_tracked_tree_or_beside_the_file_the_desk_loads(lab):
    before = sha_of(lab["file"])
    for bad in (RT.REPO / "docs" / "ml_retrain_probe", RT.REPO / "quantdesk" / "intraday" / "probe", RT.REPO):
        with pytest.raises(ForbiddenUse, match="git working tree"):
            drill(lab, bad)
        assert not (bad / RT.REPORT_NAME).exists()
    with pytest.raises(RT.RetrainRefused, match="registered model file"):
        drill(lab, lab["file"].parent)
    assert sha_of(lab["file"]) == before and sorted(p.name for p in lab["file"].parent.iterdir()) == [lab["file"].name]


def test_a_report_is_written_once(lab):
    out = lab["root"] / "once"
    drill(lab, out)
    first = (out / RT.REPORT_NAME).read_bytes()
    with pytest.raises(RT.RetrainRefused, match="exists"):
        drill(lab, out)
    assert (out / RT.REPORT_NAME).read_bytes() == first


def test_a_symlinked_report_name_is_refused_too(lab):
    out = lab["root"] / "linked"
    out.mkdir()
    (out / RT.REPORT_NAME).symlink_to(lab["root"] / "nowhere.json")
    with pytest.raises(RT.RetrainRefused, match="exists"):
        drill(lab, out)


@pytest.mark.parametrize("kw", [{"rtol": 1e-5}, {"rtol": -1.0}, {"rtol": float("nan")}, {"atol": 1e-9}, {"atol": 1e-11}, {"atol": -1e-12}, {"atol": float("nan")}])
def test_the_tolerance_cannot_be_widened_past_the_reproduction_cap(lab, kw):
    with pytest.raises(ValueError):
        drill(lab, **kw)
    assert not (lab["root"] / "out").exists()


def test_an_empty_registry_and_a_comparison_of_nothing_are_refused(lab):
    with pytest.raises(RT.RetrainRefused, match="empty registry"):
        RT.drill(lab["ds"], lab["root"] / "e", models=(), say=quiet)
    empty = lab["root"] / "empty.json"
    empty.write_text("{}")
    nothing = (RT.Refit("none", empty, lab["spec"], lambda ds, sp: {}),)
    with pytest.raises(RT.RetrainRefused, match="no number was compared"):
        RT.drill(lab["ds"], lab["root"] / "n", models=nothing, say=quiet)
    assert not (lab["root"] / "n" / RT.REPORT_NAME).exists()


def test_a_planted_symlink_for_the_refit_cannot_make_the_drill_overwrite_the_file_the_desk_loads(lab):
    before = sha_of(lab["file"])
    out = lab["root"] / "planted"
    out.mkdir()
    (out / "c_har.refit.json").symlink_to(lab["file"])
    with pytest.raises(RT.RetrainRefused, match="exists"):
        drill(lab, out)
    assert sha_of(lab["file"]) == before and not (out / RT.REPORT_NAME).exists()


def test_rounding_noise_passes_and_a_real_difference_does_not(lab):
    d = json.loads(lab["file"].read_text())
    d["symbols"]["NIFTY"]["fit"]["close"]["beta"][1] *= 1 + 1e-12
    lab["file"].write_text(json.dumps(d))
    assert drill(lab)["ok"]
    d["symbols"]["NIFTY"]["fit"]["close"]["beta"][1] *= 1 + 1e-4
    lab["file"].write_text(json.dumps(d))
    assert not drill(lab, lab["root"] / "again")["ok"]


# ---- the shipped registry ---------------------------------------------------------------------------------------------
def test_the_constants_repeated_from_the_live_package_equal_the_originals():
    from quantdesk.intraday import harvol
    assert RT.HAR_SCHEMA == harvol.SCHEMA and RT.HAR_FILE.resolve() == Path(harvol.DEFAULT_PATH).resolve()


def test_the_shipped_registry_names_the_file_the_desk_loads_and_the_spec_that_pins_it():
    from quantdesk.intraday.harvol import DEFAULT_PATH
    (m,) = RT.registry()
    assert m.id == "c_har" and m.committed == Path(DEFAULT_PATH) and m.committed.exists() and m.spec.exists()
    committed = json.loads(m.committed.read_text())
    assert committed["spec_sha256"] == spec_hash(m.spec)                                       # the committed fit is the spec on disk today
    inputs = committed["provenance"]["inputs"]
    assert len(inputs["source_commit"]) == 40 and inputs["partitions_1m"] and all(len(v) >= 24 for v in inputs["partitions_1m"].values())


def test_the_committed_files_shape_is_what_the_refit_returns_so_the_drill_can_compare_them():
    (m,) = RT.registry()
    committed = json.loads(m.committed.read_text())
    sample = fit_coefs({}, __import__("datetime").date(2018, 12, 31), "n", "s", "d")
    assert set(sample) <= set(committed) and set(committed) - set(sample) == {"provenance"}


# ---- the command ------------------------------------------------------------------------------------------------------
def test_the_command_exits_zero_on_a_reproduction_and_one_when_it_does_not(lab, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(RT, "registry", lambda: lab["models"])
    main(["ml", "retrain", "--dataset", str(lab["ds"]), "--out", str(tmp_path / "ok")])
    assert "ALL REPRODUCED" in capsys.readouterr().out
    d = json.loads(lab["file"].read_text())
    d["symbols"]["NIFTY"]["fit"]["close"]["smear"] += 1
    lab["file"].write_text(json.dumps(d))
    with pytest.raises(SystemExit) as e:
        main(["ml", "retrain", "--dataset", str(lab["ds"]), "--out", str(tmp_path / "bad")])
    assert e.value.code == 1 and "NOT REPRODUCED" in capsys.readouterr().out


def test_the_command_refuses_a_wide_tolerance_a_missing_dataset_and_a_tracked_output(lab, monkeypatch, tmp_path):
    monkeypatch.setattr(RT, "registry", lambda: lab["models"])
    with pytest.raises(SystemExit, match="outside 0 to"):
        main(["ml", "retrain", "--dataset", str(lab["ds"]), "--out", str(tmp_path / "a"), "--rtol", "0.5"])
    with pytest.raises(SystemExit, match="git working tree"):
        main(["ml", "retrain", "--dataset", str(lab["ds"]), "--out", str(RT.REPO / "docs" / "probe")])
    with pytest.raises(SystemExit, match="ml retrain"):
        main(["ml", "retrain", "--dataset", str(tmp_path / "nope"), "--out", str(tmp_path / "b")])


# ---- the scheduled workflow -------------------------------------------------------------------------------------------
def test_the_scheduled_workflow_is_read_only_secretless_and_changes_nothing():
    """P0.8's contract: no write permission, no secret, no push. A reviewer edits this test with the workflow, never around it."""
    import sys
    import yaml
    sys.path.insert(0, str(RT.REPO / "deploy"))
    import check_workflows
    path = RT.REPO / ".github" / "workflows" / "ml-retrain.yml"
    text = path.read_text()
    wf = yaml.load(text, Loader=yaml.BaseLoader)
    assert wf["permissions"] == {"contents": "read"} and all("permissions" not in j for j in wf["jobs"].values())
    assert set(wf["on"]) == {"schedule", "workflow_dispatch"}                                  # never a pull_request(_target) trigger
    assert check_workflows.check(path) == []                                                   # pinned actions, explicit permissions
    lowered = text.lower()
    for forbidden in ("secrets.", "github.token", "gh_token", "github_token", "git push", "git commit", "git config", "gh release", "gh pr", "gh api",
                      "gh issue", "gh run", "curl ", "--force", "contents: write", "id-token", "pull-requests", "actions: write"):
        assert forbidden not in lowered, forbidden
    steps = [s for j in wf["jobs"].values() for s in j["steps"]]
    assert all(s.get("with", {}).get("persist-credentials", "false") == "false" for s in steps if s.get("uses", "").startswith("actions/checkout"))
    assert [s["uses"].split("@")[0] for s in steps if "uses" in s] == ["actions/checkout", "actions/setup-python", "actions/upload-artifact"]
    runs = "\n".join(s["run"] for s in steps if "run" in s)
    assert "ml retrain" in runs and "external-import" in runs and "vol_har_v1.json" in runs
    assert "--out runtime/ml_retrain" in runs                                                  # the gitignored folder the command accepts
    assert wf["defaults"]["run"]["shell"] == "bash" and all("shell" not in s for s in steps)  # bash -e -o pipefail: `| tee` cannot hide a failure
    assert all("${{" not in s["run"] for s in steps if "run" in s)                             # no expression is interpolated into a shell script


def test_the_workflow_reads_the_pinned_commit_from_the_committed_coefficients():
    (m,) = RT.registry()
    commit = json.loads(m.committed.read_text())["provenance"]["inputs"]["source_commit"]
    assert len(commit) == 40 and set(commit) <= set("0123456789abcdef")


# ---- the audit's follow-ups ----------------------------------------------------------------------------------------
def test_a_partition_changed_after_the_manifest_was_written_is_caught_from_the_files_not_the_manifest(lab):
    import pandas as pd
    part = sorted((lab["ds"] / "1m" / "symbol=NIFTY").glob("year=2014.parquet"))[0]            # after the fit's training window: the numbers would not move
    df = pd.read_parquet(part)
    df["close"] = df["close"] * 1.5
    df.to_parquet(part)
    rep = drill(lab)
    row = rep["models"][0]
    assert not rep["ok"] and row["verdict"] == "reproduced_on_different_inputs"
    assert any("do not match the files" in x and "year=2014" in x for x in row["input_findings"]), row["input_findings"]


def test_an_extra_partition_file_or_manifest_entry_is_named(lab):
    import shutil
    extra = lab["ds"] / "1m" / "symbol=NIFTY" / "year=2099.parquet"
    shutil.copy(lab["ds"] / "1m" / "symbol=NIFTY" / "year=2014.parquet", extra)
    f = drill(lab)["models"][0]["input_findings"]
    assert any("not in the manifest" in x and "year=2099" in x for x in f), f
    extra.unlink()
    man = json.loads((lab["ds"] / "manifest.json").read_text())
    man["partitions"]["1m/symbol=NIFTY/year=2098.parquet"] = "f" * 24                            # in the manifest, not on disk
    (lab["ds"] / "manifest.json").write_text(json.dumps(man))
    f = drill(lab, lab["root"] / "again")["models"][0]["input_findings"]
    assert any("could not be read" in x for x in f), f


def test_a_different_importer_version_is_an_input_finding(lab):
    write_manifest(lab["ds"], importer_version="aeron7-3")
    row = drill(lab)["models"][0]
    assert row["verdict"] == "reproduced_on_different_inputs" and any("importer_version" in x for x in row["input_findings"])


def test_the_report_records_the_spec_the_code_state_and_what_reproduced_means(lab):
    rep = drill(lab)
    row = rep["models"][0]
    assert row["spec_sha256"] == spec_hash(lab["spec"]) and "code_has_uncommitted_changes" in rep and len(rep["dataset"]["manifest_sha256"]) == 64
    assert "repeatability, not correctness" in rep["meaning"]


def test_the_drill_refit_is_what_the_real_fit_command_writes(lab, tmp_path):
    """Pins `_har` to `autolearn vol-har-fit` itself (the committed numbers come from that command): run the command on the same dataset and compare every number."""
    import shutil
    root = tmp_path / "ext"
    shutil.copytree(lab["ds"], root / "aeron7" / "aeron7-2-lab")
    out = tmp_path / "from_command.json"
    main(["autolearn", "vol-har-fit", "--out", str(root), "--spec", str(lab["spec"]), "--to", str(out)])
    command = json.loads(out.read_text())
    mine = RT._har(root / "aeron7" / "aeron7-2-lab", lab["spec"])
    assert {k: v for k, v in command.items() if k != "provenance"} == mine
