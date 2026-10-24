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
            "dev": [0.1, 0.2, 0.3], "opened": "2026-10-04T00:58:21+05:30"}


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


def test_only_the_declared_keys_are_ignored():
    d = doc()
    d["opened"] = "another time"
    assert R.compare_results(doc(), d).ok
    d["cells"]["a"]["opened"] = "x"                                          # ignored at any depth, by name: documented
    assert R.compare_results(doc(), d).ok
    assert not R.compare_results(doc(), d, ignore=frozenset()).ok            # and only because the caller left the default


# ---- the end-to-end round trip ---------------------------------------------------------------------------------------
SPEC = {"name": "unit_vol", "registered": "2026-10-24", "dataset": "synthetic", "not_for": "a unit test", "question": "q", "symbols": ["NIFTY"],
        "dev": {"start": "2012-01-01", "end": "2013-12-31"}, "lock": {"start": "2014-01-01", "end": "2099-12-31", "training": "all dev years"}}


def synthetic_dataset(root: Path) -> Path:
    """A small aeron7-format dataset (manifest + 1m partitions) of stochastic-volatility minute bars, 2012-06 to 2014-12."""
    ds = root / "aeron7-test"
    rng = np.random.default_rng(11)
    days = pd.bdate_range("2012-06-01", "2014-12-31")
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
    with pytest.raises(R.ReproductionRefused, match="inside"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=R.PROTECTED / "scratch", say=lambda *a: None)
    with pytest.raises(R.ReproductionRefused, match="inside"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=R.PROTECTED, say=lambda *a: None)
    assert not (R.PROTECTED / "scratch").exists()
    with pytest.raises(R.ReproductionRefused, match="already exists"):
        R.reproduce(lab["ds"], lab["spec"], lab["committed"], results_dir=lab["committed"].parent, say=lambda *a: None)   # would be the committed file itself


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
