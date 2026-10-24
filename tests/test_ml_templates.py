"""P0.1's exit test (docs/ML_PHASE0.md): a spec written from the template passes `experiments --check`, and that check still refuses what has been run."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC_TEMPLATE = REPO / "docs" / "ml" / "SPEC_TEMPLATE.md"


def check(spec: dict, tmp_path):
    p = tmp_path / "draft.json"
    p.write_text(json.dumps(spec))
    return subprocess.run([sys.executable, "-m", "quantdesk", "experiments", "--check", str(p)], cwd=REPO, capture_output=True, text=True)


def test_the_template_has_its_seven_sections_in_order_and_says_to_commit_before_any_result():
    t = SPEC_TEMPLATE.read_text()
    heads = re.findall(r"^## (\d)\. (.+)$", t, flags=re.M)
    assert [h[0] for h in heads] == ["1", "2", "3", "4", "5", "6", "7"]
    assert [h[1] for h in heads] == ["Question and decision", "Target and baseline", "Data", "Split in time (fixed now)", "Model and variants", "Evidence needed",
                                     "What would stop us"]
    assert "before any result exists" in t and "experiments --check" in t


def test_a_spec_written_from_the_template_is_new_to_the_research_memory(tmp_path):
    """A draft whose keys are the template's fields, with a method nobody has registered."""
    draft = {"name": "template_probe_v1", "registered": "2026-10-24",
             "question": "does a made-up probe feature predict the 47 minute move better than the desk's forecaster",
             "decision": {"may_change": "shrink a size only", "component": "M1"},
             "target": {"definition": "realised variance over the next 47 minutes", "horizon_minutes": 47},
             "baseline": {"name": "A_desk", "metric": "QLIKE", "decision_rule": "fails if the 90% interval for the difference contains 0.137"},
             "data": {"tiers": ["T1"], "features": ["probe_feature_47"], "excluded": ["anything after the decision time"]},
             "split": {"train": ["2013-01-01", "2018-12-31"], "validation": ["2019-01-01", "2019-12-31"], "locked_test": ["2020-01-01", "2020-12-31"], "purge_sessions": 3,
                       "cutoff": "2019-12-31"},
             "model": {"family": "ridge", "alpha_grid": [0.0731, 0.731, 7.31]}, "variants_tried": 3, "multiple_testing": "Holm",
             "evidence": {"power_sessions": 211, "cost_stress": 2.0, "shadow_sessions": 37},
             "kill": {"rule": "the 90% interval for the QLIKE difference includes 0.137"}}
    r = check(draft, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "new: no registered spec has this method" in r.stdout and "fingerprint" in r.stdout


def test_a_reworded_copy_of_a_registered_spec_is_refused_as_the_same_experiment(tmp_path):
    spec = json.loads((REPO / "docs" / "prereg" / "oi_shadow_v1.json").read_text())
    spec["name"] = "oi_shadow_reworded"
    spec["question"] = "a completely different way of asking the same thing"
    spec["why"] = "the wording is not the experiment"
    r = check(spec, tmp_path)
    assert r.returncode == 1 and "IDENTICAL to: oi_shadow_v1" in r.stdout


def test_changing_the_method_makes_it_a_different_experiment_again(tmp_path):
    spec = json.loads((REPO / "docs" / "prereg" / "oi_shadow_v1.json").read_text())
    spec["name"] = "oi_shadow_other"
    spec["forward_rule"] = spec["forward_rule"].replace("2026-10-26", "2026-12-01")        # a different start date is a different method
    r = check(spec, tmp_path)
    assert r.returncode == 0 and "IDENTICAL" not in r.stdout
