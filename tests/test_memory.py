"""The research memory (research/memory.py): an identical experiment can't be registered twice, every recorded result
matches its spec as registered, every principle's status is explained by its history, and proposals follow the
evidence."""
import copy
import datetime as dt
import json

import pytest

from quantdesk.research import memory as M

SPEC = {"name": "x_v1", "registered": "2026-10-04", "why": "because", "underlyings": ["NIFTY", "BANKNIFTY"],
        "rules": {"entry": "15:20 the session before expiry", "delta": 0.20}, "tests": {"t": 1.645}}


def test_the_fingerprint_is_the_substance_not_the_wording():
    same = {"tests": {"t": 1.645}, "rules": {"delta": 0.20, "entry": "15:20  the session BEFORE expiry"},
            "underlyings": ["NIFTY", "BANKNIFTY"], "name": "x_v2", "registered": "2027-01-01", "why": "other prose"}
    assert M.fingerprint(SPEC) == M.fingerprint(same)                    # renamed, re-dated, re-worded: same experiment
    changed = copy.deepcopy(SPEC)
    changed["rules"]["delta"] = 0.25
    assert M.fingerprint(changed) != M.fingerprint(SPEC)                 # one parameter differs: a new experiment
    assert M.similarity(SPEC, changed) > M.similarity(SPEC, {"tests": {"t": 3.0}})


def test_check_names_the_identical_and_the_nearest(tmp_path):
    (tmp_path / "results").mkdir()
    (tmp_path / "x_v1.json").write_text(json.dumps(SPEC))
    near = dict(SPEC, name="x_v2", rules={"entry": "15:20 the session before expiry", "delta": 0.25})
    (tmp_path / "x_v2.json").write_text(json.dumps(near))
    reg = M.registry(tmp_path)
    again = dict(SPEC, name="x_v3", why="I forgot we did this")
    c = M.check(again, reg)
    assert c["identical"] == ["x_v1"] and c["nearest"][0][1] == "x_v2"
    (tmp_path / "x_v3.json").write_text(json.dumps(again))
    assert M.duplicates(M.registry(tmp_path)) == [["x_v1", "x_v3"]]


def test_no_two_registered_specs_are_the_same_experiment():
    """The guard: CI refuses a pre-registered spec identical in substance to one already registered."""
    assert M.duplicates(M.registry()) == []


def test_every_recorded_result_matches_its_spec_as_registered():
    """A result file is named after its spec's hash: if a spec were edited after its result, the names would no longer
    match. Every result in docs/prereg/results must belong to a spec exactly as it stands."""
    reg = M.registry()
    claimed = {x for r in reg for x in r["results"]}
    found = {p.name for p in (M.PREREG / "results").glob("*.md")}
    assert found <= claimed, f"results whose spec changed or vanished: {sorted(found - claimed)}"


def test_every_principle_is_explained_by_its_history():
    assert M.history_problems(M.load_principles()) == []


def _doc():
    return {"principles": [
        {"id": "A", "status": "replicated", "caveats": ["weak since 2024"], "pending": ["forward sleeves"],
         "applied_in": [], "history": [{"date": "2026-10-01", "from": "hypothesis", "to": "found", "reason": "r", "ref": "x"},
                                       {"date": "2026-10-02", "from": "found", "to": "replicated", "reason": "r", "ref": "y"}]},
        {"id": "B", "status": "found", "pending": ["held-out instruments"], "applied_in": [],
         "history": [{"date": "2026-10-01", "from": "hypothesis", "to": "found", "reason": "r", "ref": "x"}]},
        {"id": "C", "status": "rejected", "pending": [], "applied_in": [],
         "history": [{"date": "2026-10-01", "from": "hypothesis", "to": "rejected", "reason": "r", "ref": "x"}]}]}


def test_proposals_put_a_caveat_on_a_relied_on_principle_first():
    props = M.proposals(_doc(), reg=[])
    assert [(p["principle"], p["kind"]) for p in props][:3] == [("A", "caveat"), ("A", "forward"), ("B", "replicate")]
    assert props[-1]["kind"] == "closed" and props[-1]["principle"] == "C"


def test_a_move_is_recorded_with_its_reason_and_checked():
    doc = _doc()
    e = M.move(doc, "B", "replicated", "held-out pooled t 3.1", "docs/prereg/results/b.md", dt.date(2026, 10, 5),
               caveats_add=["only two instruments"])
    assert e["kind"] == "up" and doc["principles"][1]["status"] == "replicated"
    assert doc["principles"][1]["caveats"] == ["only two instruments"] and M.history_problems(doc) == []
    r = M.move(doc, "A", "replicated", "audit: robust", "audit.md", caveats_clear=["weak since 2024"])
    assert r["kind"] == "review" and doc["principles"][0]["caveats"] == []
    with pytest.raises(ValueError):
        M.move(doc, "A", "certain", "no", "x")
    with pytest.raises(ValueError):
        M.move(doc, "A", "found", "", "x")
    doc["principles"][2]["status"] = "found"                            # a status nobody explained
    assert M.history_problems(doc) == ["C: status 'found' but its history ends at 'rejected'"]
