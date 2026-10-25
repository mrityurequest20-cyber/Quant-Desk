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


def _skeleton() -> dict:
    t = SPEC_TEMPLATE.read_text()
    m = re.search(r"```json\n(.*?)\n```", t, flags=re.S)
    assert m, "the template carries no machine-readable skeleton"
    return json.loads(m.group(1))


def _fill(node, tag):
    """Every `<placeholder>` string becomes a distinct concrete value, every zero a distinct number: a stand-in for an author filling the template in."""
    if isinstance(node, dict):
        return {k: _fill(v, f"{tag}.{k}") for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, f"{tag}.{i}") for i, v in enumerate(node)]
    if isinstance(node, str) and node.startswith("<"):
        return f"probe {tag} 47 minutes 0.137"
    if isinstance(node, (int, float)) and not isinstance(node, bool):
        return node + 1 + (abs(hash(tag)) % 97) / 1000
    return node


def test_the_skeleton_in_the_template_has_a_field_for_each_of_the_seven_sections():
    sk = _skeleton()
    owner = {"question": 1, "decision": 1, "target": 2, "baseline": 2, "data": 3, "split": 4, "model": 5, "variants_tried": 5, "multiple_testing": 5, "evidence": 6, "kill": 7}
    assert {k for k in sk if k not in ("name", "registered")} == set(owner)
    assert set(owner.values()) == {1, 2, 3, 4, 5, 6, 7}
    assert isinstance(sk["kill"]["threshold"], (int, float)) and "threshold" in sk["kill"]               # the number a spec can fail on is a number


def test_a_spec_filled_in_from_the_template_is_new_to_the_research_memory(tmp_path):
    """The draft is the template's own skeleton with its placeholders filled in, not a hand-built dict."""
    draft = _fill(_skeleton(), "t")
    draft["name"], draft["registered"] = "template_probe_v1", "2026-10-24"
    assert "<" not in json.dumps(draft)                                                                    # nothing left unfilled
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
