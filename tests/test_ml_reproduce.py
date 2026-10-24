"""P0.4: reproducing a pre-registered result (quantdesk/ml/reproduce.py): the field-by-field comparison, the guards that keep a reproduction from
touching the committed results, and an end-to-end round trip on a small synthetic dataset and spec."""
import copy
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.autolearn import volstudy as V
from quantdesk.ml import reproduce as R

IST = "Asia/Kolkata"


# ---- the comparison -------------------------------------------------------------------------------------------------
def doc():
    return {"spec": "x", "ok": True, "n": 3, "label": "C_har", "none": None,
            "cells": {"a": {"t": 4.65, "gain": 12.9, "passed": True, "days": 1023}, "b": {"t": 5.07, "gain": 18.2, "passed": True, "days": 1023}},
            "dev": [0.1, 0.2, 0.3], "lock": {"opened": "2026-10-04T00:58:21+05:30"}}


def test_identical_results_match_and_count_their_numbers():
    c = R.compare_results(doc(), doc())
    assert c.ok and c.numbers == 1 + 3 + 3 + 3 and c.max_abs == 0.0 and c.mismatches == []          # n; cell a (t, gain, days); cell b; dev


def test_rounding_noise_passes_and_a_real_difference_is_named():
    d = doc()
    d["cells"]["a"]["t"] += 1e-12
    c = R.compare_results(doc(), d)
    assert c.ok and 0 < c.max_abs < 2e-12 and c.worst == "/cells/a/t"
    d["cells"]["a"]["t"] += 0.01
    c = R.compare_results(doc(), d)
    assert not c.ok and "/cells/a/t" in c.mismatches[0] and "difference" in c.mismatches[0]
    assert not R.compare_results(doc(), {**doc(), "n": 4}).ok                                    # an integer differs by 1
    tight = copy.deepcopy(doc()); tight["dev"][1] += 1e-13
    assert R.compare_results(doc(), tight, rtol=1e-9).ok and not R.compare_results(doc(), tight, rtol=0, atol=0).ok


def test_nan_and_infinity_match_only_themselves():
    a, b = doc(), doc()
    a["cells"]["a"]["t"], b["cells"]["a"]["t"] = float("nan"), float("nan")
    assert R.compare_results(a, b).ok
    b["cells"]["a"]["t"] = 4.65
    assert not R.compare_results(a, b).ok and not R.compare_results(b, a).ok                      # NaN against a number, both ways
    a["cells"]["a"]["t"], b["cells"]["a"]["t"] = float("inf"), float("inf")
    assert R.compare_results(a, b).ok
    b["cells"]["a"]["t"] = float("-inf")
    assert not R.compare_results(a, b).ok


@pytest.mark.parametrize("change", [
    lambda d: d["cells"]["a"].update(passed=False),                          # a cell's verdict flips
    lambda d: d.update(label="B_seasonal"),                                  # a string
    lambda d: d.update(ok=False),
    lambda d: d.update(none=0),                                              # None is not 0
    lambda d: d.update(n=True),                                              # a bool is not an int
    lambda d: d["dev"].append(0.4),                                          # a list grew
    lambda d: d["cells"].pop("b"),                                           # a key missing
    lambda d: d["cells"].update(c={}),                                       # a key added
    lambda d: d.update(spec=["x"])])                                         # a type changed
def test_everything_that_is_not_a_tolerated_number_must_match_exactly(change):
    d = doc()
    change(d)
    assert not R.compare_results(doc(), d).ok


def test_only_the_declared_path_is_ignored():
    d = doc()
    d["lock"]["opened"] = "another time"                                     # the one timestamp that differs by construction
    assert R.compare_results(doc(), d).ok
    assert R.IGNORED == frozenset({"/lock/opened"})
    for name, edit in (("a path only in the reproduction", lambda e: e.update(path="/tmp/x")),
                       ("opened at the top", lambda e: e.update(opened="x")),
                       ("opened inside a cell", lambda e: e["cells"]["a"].update(opened="x")),
                       ("path inside a cell", lambda e: e["cells"]["a"].update(path="x")),
                       ("opened under another parent", lambda e: e.update(other={"opened": "x"}))):
        e = doc()
        edit(e)
        assert not R.compare_results(doc(), e).ok, name                      # the same key name anywhere else is a real difference
    assert not R.compare_results(doc(), d, ignore=frozenset()).ok            # and only because the caller left the default


# ---- the end-to-end round trip ---------------------------------------------------------------------------------------
SPEC = {"name": "unit_vol", "registered": "2026-10-24", "dataset": "synthetic", "not_for": "a unit test", "question": "q", "symbols": ["NIFTY"],
        "dev": {"start": "2012-01-01", "end": "2013-12-31"}, "lock": {"start": "2014-01-01", "end": "2099-12-31", "training": "all dev years"}}


def synthetic_dataset(root: Path) -> Path:
    """A small aeron7-format dataset (manifest + 1m partitions) of stochastic-volatility minute bars, 2011-01 to 2014-12 (the first yearly fold needs a 250-session profile)."""
    ds = root / "aeron7-test"
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2011-01-03", "2014-12-31")
    sig = 2.5e-4 * np.exp(np.cumsum(rng.standard_normal(len(days)) * 0.15) * 0.3)
    shape = 1 + 0.6 * np.exp(-np.arange(375) / 40) + 0.3 * np.exp(-(374 - np.arange(375)) / 30)
    r = rng.standard_normal((len(days), 375)) * sig[:, None] * np.sqrt(shape)[None, :]
    close = 5000 * np.exp(np.cumsum(r, axis=None).reshape(r.shape))
    ts = np.concatenate([(pd.Timestamp(d.date()).tz_localize(IST) + pd.Timedelta(hours=9, minutes=15) + pd.to_timedelta(np.arange(375), unit="min")) for d in days])
    open_ = np.r_[close.ravel()[0], close.ravel()[:-1]]
    df = pd.DataFrame({"ts": ts, "open": open_, "high": np.maximum(open_, close.ravel()) + 0.1, "low": np.minimum(open_, close.ravel()) - 0.1,
                       "close": close.ravel(), "volume": 0.0, "oi": 0.0, "source_file": 0, "symbol": "NIFTY"})
    for y, g in df.groupby(df["ts"].dt.year):
        p = ds / "1m" / "symbol=NIFTY" / f"year={y}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        g.reset_index(drop=True).to_parquet(p)
    (ds / "manifest.json").write_text(json.dumps({"status": "external_verified", "dataset": "aeron7-test", "source_commit": None}))
    return ds


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    root = tmp_path_factory.mktemp("repro")
    ds = synthetic_dataset(root)
    spec = root / "unit_vol.json"
    spec.write_text(json.dumps(SPEC))
    first = root / "committed"                                               # the 'original' opening of the lock, in a folder of its own
    rep = V.run(None, ds, spec, first, open_lock=True, say=lambda *a: None)
    return {"root": root, "ds": ds, "spec": spec, "committed": Path(rep["path"]), "rep": rep}


def snapshot(folder: Path):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob("*"))} if folder.exists() else {}


def test_a_reproduction_matches_the_committed_result_and_writes_nothing_under_docs(lab, tmp_path):
    before = snapshot(R.PROTECTED)
    cmp = R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=tmp_path / "scratch", say=lambda *a: None)
    assert cmp.ok and cmp.numbers > 100 and cmp.max_abs < 1e-9
    assert snapshot(R.PROTECTED) == before                                   # the committed results are exactly as they were
    assert (tmp_path / "scratch" / lab["committed"].name).exists() and snapshot(lab["committed"].parent) == snapshot(lab["committed"].parent)
    text = R.render(cmp, json.loads(lab["committed"].read_text()))
    assert "MATCHES" in text and "locked cells" in text and "NIFTY" in text


def test_a_tampered_committed_result_is_detected(lab, tmp_path):
    good = json.loads(lab["committed"].read_text())
    cell = next(iter(good["lock"]["tests"]))
    for what, edit in (("a statistic", lambda d: d["lock"]["tests"][cell].update(scores={**d["lock"]["tests"][cell]["scores"], "A_desk": {**d["lock"]["tests"][cell]["scores"]["A_desk"], "qlike": 9.0}})),
                       ("a selection", lambda d: d["selected"].update({next(iter(d["selected"])): {"candidate": "A_desk", "dev_mean_qlike": {}}})),
                       ("a dev fold", lambda d: d["dev"][next(iter(d["dev"]))]["A_desk"]["2013"].update(qlike=7.0)),
                       ("the session counts", lambda d: d["sessions"]["NIFTY"].update(lock=1))):
        bad = copy.deepcopy(good)
        edit(bad)
        f = tmp_path / what.replace(" ", "_") / lab["committed"].name
        f.parent.mkdir()
        f.write_text(json.dumps(bad))
        cmp = R.reproduce(lab["ds"], lab["spec"], f, results_dir=tmp_path / f"out_{what.replace(' ', '_')}", say=lambda *a: None)
        assert not cmp.ok and cmp.mismatches, what


def test_a_reproduction_is_refused_where_it_could_replace_or_be_mistaken_for_a_committed_result(lab, tmp_path):
    run = lambda d, committed=None: R.reproduce(lab["ds"], lab["spec"], committed or lab["committed"], results_dir=d, say=lambda *a: None)
    with pytest.raises(R.ReproductionRefused, match="inside"):
        run(R.PROTECTED / "scratch")
    with pytest.raises(R.ReproductionRefused, match="inside"):
        run(R.PROTECTED)
    assert not (R.PROTECTED / "scratch").exists()
    with pytest.raises(R.ReproductionRefused, match="already exists"):
        run(lab["committed"].parent)                                         # would be the committed file itself


@pytest.mark.parametrize("where", ["docs/prereg", "docs", ".", "quantdesk", "docs/prereg/results/../.."])
def test_nothing_inside_the_repository_is_a_valid_scratch_folder(lab, where):
    """The guard is the whole repository, not only the results folder: a result-lookalike with a spent lock must not sit in a tracked tree."""
    before = sorted(p.name for p in (R.REPO / where).resolve().glob("unit_vol-*.json"))
    with pytest.raises(R.ReproductionRefused, match="inside a git working tree"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=R.REPO / where, say=lambda *a: None)
    assert sorted(p.name for p in (R.REPO / where).resolve().glob("unit_vol-*.json")) == before


def test_a_symlink_into_the_repository_is_followed_before_judging(lab, tmp_path):
    link = tmp_path / "link"
    link.symlink_to(R.PROTECTED)
    with pytest.raises(R.ReproductionRefused, match="inside"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=link, say=lambda *a: None)
    with pytest.raises(R.ReproductionRefused, match="inside"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=link / "new", say=lambda *a: None)      # a not-yet-existing subfolder of it


def test_the_output_name_is_the_one_the_study_writes_not_the_committed_copys(lab, tmp_path):
    """A committed copy under another name must not hide a stale file or a dangling link at the name volstudy.run will use."""
    other = tmp_path / "renamed.json"
    other.write_text(lab["committed"].read_text())
    name = lab["committed"].name
    scratch = tmp_path / "s1"
    scratch.mkdir()
    (scratch / name).write_text("{}")
    with pytest.raises(R.ReproductionRefused, match="already exists"):
        R.reproduce(lab["ds"], lab["spec"], other, results_dir=scratch, say=lambda *a: None)
    scratch2 = tmp_path / "s2"
    scratch2.mkdir()
    (scratch2 / name).symlink_to(R.PROTECTED / "does-not-exist.json")      # dangling: exists() is False, writing would follow it
    with pytest.raises(R.ReproductionRefused, match="already exists"):
        R.reproduce(lab["ds"], lab["spec"], other, results_dir=scratch2, say=lambda *a: None)
    assert not (R.PROTECTED / "does-not-exist.json").exists()


@pytest.mark.parametrize("rtol", [1.1e-6, 1e-3, 1.0, 1e9, -1e-12])
def test_the_tolerance_cannot_be_widened_until_everything_matches(lab, tmp_path, rtol):
    with pytest.raises(ValueError, match="not a reproduction"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=tmp_path / "x", rtol=rtol, say=lambda *a: None)
    assert not (tmp_path / "x").exists()
    ok = R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=tmp_path / "y", rtol=R.RTOL_MAX, say=lambda *a: None)
    assert ok.ok and "WIDER" in R.render(ok, json.loads(lab["committed"].read_text()))
    assert "WIDER" not in R.render(R.compare_results(doc(), doc()), json.loads(lab["committed"].read_text()))


def test_a_spec_edited_after_its_result_or_a_result_without_a_lock_is_refused(lab, tmp_path):
    edited = tmp_path / "unit_vol.json"
    edited.write_text(json.dumps({**SPEC, "question": "a different question"}))
    with pytest.raises(R.ReproductionRefused, match="no longer hashes"):
        R.reproduce(lab["ds"], edited, lab["committed"], results_dir=tmp_path / "o1", say=lambda *a: None)
    nolock = json.loads(lab["committed"].read_text())
    nolock["lock"] = None
    f = tmp_path / "nolock" / lab["committed"].name
    f.parent.mkdir()
    f.write_text(json.dumps(nolock))
    with pytest.raises(R.ReproductionRefused, match="no opened lock"):
        R.reproduce(lab["ds"], lab["spec"], f, results_dir=tmp_path / "o2", say=lambda *a: None)


# ---- the real thing, when the data is at hand -------------------------------------------------------------------------
REAL_DS = os.environ.get("QD_AERON7_DS")


@pytest.mark.skipif(not REAL_DS, reason="set QD_AERON7_DS to the extracted aeron7-2-906fc2378b dataset to reproduce the locked HAR result")
def test_the_locked_har_result_is_reproduced_in_all_eight_cells(tmp_path):
    spec = R.REPO / "docs" / "prereg" / "vol_forecast_v1.json"
    committed = next(R.PROTECTED.glob("vol_forecast_v1-*.json"))
    cmp = R.reproduce(Path(REAL_DS), spec, committed, results_dir=tmp_path / "scratch", say=lambda *a: None)
    got = json.loads(committed.read_text())["lock"]["tests"]
    assert len(got) == 8 and all(t["passed"] for t in got.values())
    assert cmp.ok, R.render(cmp, json.loads(committed.read_text()))


# ---- reproduction through the platform (the P0.4 exit test) ---------------------------------------------------------------
from quantdesk.ml import build as B          # noqa: E402
from quantdesk.ml import splits as S         # noqa: E402
from quantdesk.ml import study as ST         # noqa: E402


def test_the_study_rebuilt_through_the_builder_and_the_splits_matches_the_committed_result(lab):
    """The locked study's dev selection and lock, recomputed with build_tables per fold, walk_forward and the study's own fit and scorers: every
    number equals the committed one. This is what exercises the new pieces; reproduce() alone only reruns the old study."""
    cmp = ST.reproduce_through_platform(lab["ds"], lab["spec"], lab["committed"])
    assert cmp.ok, cmp.mismatches[:5]
    assert cmp.numbers > 150 and cmp.max_abs < 1e-9


def test_a_builder_that_fits_the_profile_on_the_wrong_days_is_caught_by_the_reproduction(lab, monkeypatch):
    real = B.build_tables

    def early(grids, pe, tier, **kw):                                            # the profile fitted on 200 days fewer than it should be
        return real(grids, (pd.Timestamp(pe) - pd.Timedelta(days=200)).date(), tier, **kw)

    monkeypatch.setattr(B, "build_tables", early)
    cmp = ST.reproduce_through_platform(lab["ds"], lab["spec"], lab["committed"])
    assert not cmp.ok and cmp.mismatches


def test_a_builder_whose_profile_covers_its_test_rows_is_refused_not_just_wrong(lab, monkeypatch):
    real = B.build_tables
    monkeypatch.setattr(B, "build_tables", lambda grids, pe, tier, **kw: real(grids, "2099-12-31", tier, **kw))      # every row inside the profile window
    with pytest.raises(S.LeakError, match="not allowed to be scored"):
        ST.reproduce_through_platform(lab["ds"], lab["spec"], lab["committed"])


def test_a_split_that_puts_test_sessions_in_training_is_refused(lab, monkeypatch):
    real = S.walk_forward

    def leaky(*a, **k):
        return [S.Fold(np.union1d(f.train, f.test), f.test, f.label) for f in real(*a, **k)]

    monkeypatch.setattr(S, "walk_forward", leaky)
    with pytest.raises(S.LeakError, match="both train and test"):
        ST.reproduce_through_platform(lab["ds"], lab["spec"], lab["committed"])


def test_a_tampered_committed_result_fails_the_platform_reproduction_too(lab, tmp_path):
    bad = json.loads(lab["committed"].read_text())
    key = next(iter(bad["lock"]["tests"]))
    bad["lock"]["tests"][key]["scores"]["A_desk"]["qlike"] += 0.5
    f = tmp_path / lab["committed"].name
    f.write_text(json.dumps(bad))
    cmp = ST.reproduce_through_platform(lab["ds"], lab["spec"], f)
    assert not cmp.ok and any("qlike" in m for m in cmp.mismatches)


def test_the_platform_reproduction_writes_nothing_and_refuses_what_the_study_rerun_refuses(lab, tmp_path):
    before = sorted(p.name for p in lab["root"].rglob("*"))
    ST.reproduce_through_platform(lab["ds"], lab["spec"], lab["committed"])
    assert sorted(p.name for p in lab["root"].rglob("*")) == before            # not a file, not even a scratch folder
    edited = tmp_path / "unit_vol.json"
    edited.write_text(json.dumps({**SPEC, "question": "another"}))
    with pytest.raises(R.ReproductionRefused, match="no longer hashes"):
        ST.reproduce_through_platform(lab["ds"], edited, lab["committed"])
    nolock = tmp_path / "nolock.json"
    nolock.write_text(json.dumps({**json.loads(lab["committed"].read_text()), "lock": None}))
    with pytest.raises(R.ReproductionRefused, match="no opened lock"):
        ST.reproduce_through_platform(lab["ds"], lab["spec"], nolock)
    for rtol in (1.1e-6, 1.0, -1e-9):
        with pytest.raises(ValueError, match="not a reproduction"):
            ST.reproduce_through_platform(lab["ds"], lab["spec"], lab["committed"], rtol=rtol)


@pytest.mark.skipif(not REAL_DS, reason="set QD_AERON7_DS to the extracted aeron7-2-906fc2378b dataset to reproduce the locked HAR result through the platform")
def test_the_locked_har_result_is_reproduced_through_the_platform_in_all_eight_cells():
    committed = next(R.PROTECTED.glob("vol_forecast_v1-*.json"))
    spec = R.REPO / "docs" / "prereg" / "vol_forecast_v1.json"
    cmp = ST.reproduce_through_platform(Path(REAL_DS), spec, committed)
    assert cmp.ok, cmp.mismatches[:5]
    cells = json.loads(committed.read_text())["lock"]["tests"]
    assert len(cells) == 8 and all(c["selected"] == "C_har" and c["passed"] for c in cells.values())
    assert cmp.numbers > 1000 and cmp.max_abs < 1e-9


def test_the_command_reproduces_through_the_platform_by_default_and_prints_what_it_ran_on(lab, capsys):
    from quantdesk.cli import main
    main(["ml", "reproduce", "--dataset", str(lab["ds"]), "--spec", str(lab["spec"]), "--committed", str(lab["committed"])])
    out = capsys.readouterr().out
    assert "MATCHES" in out and "ran on dataset aeron7-test" in out and "numpy " in out and "pandas " in out and "python " in out
    with pytest.raises(SystemExit, match="outside 0 to 1e-06|not a reproduction"):
        main(["ml", "reproduce", "--dataset", str(lab["ds"]), "--spec", str(lab["spec"]), "--committed", str(lab["committed"]), "--rtol", "0.5"])


def test_the_command_exits_nonzero_on_a_mismatch(lab, tmp_path, capsys):
    from quantdesk.cli import main
    bad = json.loads(lab["committed"].read_text())
    bad["selected"][next(iter(bad["selected"]))]["candidate"] = "A_desk"
    f = tmp_path / lab["committed"].name
    f.write_text(json.dumps(bad))
    with pytest.raises(SystemExit) as e:
        main(["ml", "reproduce", "--dataset", str(lab["ds"]), "--spec", str(lab["spec"]), "--committed", str(f)])
    assert e.value.code == 1 and "DOES NOT MATCH" in capsys.readouterr().out


def test_a_scratch_folder_inside_any_git_working_tree_is_refused_not_only_this_checkout(lab, tmp_path):
    other = tmp_path / "another_clone"
    (other / ".git").mkdir(parents=True)
    with pytest.raises(R.ReproductionRefused, match="inside a git working tree"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=other / "scratch", say=lambda *a: None)
    with pytest.raises(R.ReproductionRefused, match="inside a git working tree"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=other, say=lambda *a: None)
    (tmp_path / "worktree").mkdir()
    (tmp_path / "worktree" / ".git").write_text("gitdir: /elsewhere")                         # a worktree has a .git file, not a folder
    with pytest.raises(R.ReproductionRefused, match="inside a git working tree"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=tmp_path / "worktree" / "x", say=lambda *a: None)
