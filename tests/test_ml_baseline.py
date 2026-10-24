"""The baseline comparison (quantdesk/ml/baseline.py): the out-of-sample block of a model card from per-session losses. Expected values are worked out here by hand
or by an independent route, not by calling the code under test."""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest

from quantdesk.autolearn.prereg import nw_t
from quantdesk.ml import baseline as BL
from quantdesk.ml import modelcard as MC

def losses(d, base=1.0):
    """(model, baseline) per-session losses whose difference model - baseline is `d` (a list), the baseline flat."""
    days = [(date(2026, 1, 5) + timedelta(days=i)).isoformat() for i in range(len(d))]
    return {s: base + x for s, x in zip(days, d)}, {s: base for s in days}


def test_a_hand_worked_comparison_with_no_autocovariance():
    d = [0.1] * 5 + [0.3] * 5                                   # mean 0.2, deviations +-0.1, variance 0.01, se(lags=0) = sqrt(0.01 / 10)
    m, b = losses(d)
    r = BL.oos_block(m, b, "QLIKE", level=0.9, lags=0)
    se = math.sqrt(0.01 / 10)
    z = 1.6448536269514722                                       # the 95th percentile of the normal
    assert r["model"] == pytest.approx(1.2) and r["baseline"] == pytest.approx(1.0) and r["diff"] == pytest.approx(0.2)
    assert r["interval"] == pytest.approx([0.2 - z * se, 0.2 + z * se]) and r["t"] == pytest.approx(0.2 / se)
    assert r["n_sessions"] == 10 and r["interval_level"] == 0.9 and "0 lags" in r["interval_method"]


def test_the_t_statistic_is_the_desks_own_newey_west_t():
    rng = np.random.default_rng(3)
    d = list(0.05 + rng.normal(0, 0.1, 60) + 0.5 * np.r_[0, rng.normal(0, 0.1, 59)])
    m, b = losses(d)
    r = BL.oos_block(m, b, "QLIKE")
    assert r["t"] == pytest.approx(nw_t(np.array(d)), rel=1e-9)
    mean, se = BL.newey_west(d, 5)
    assert mean == pytest.approx(np.mean(d)) and se == pytest.approx(np.mean(d) / nw_t(np.array(d)))


def test_negative_is_better_and_the_interval_contains_the_difference():
    rng = np.random.default_rng(1)
    m, b = losses(list(-0.04 + rng.normal(0, 0.02, 40)))
    r = BL.oos_block(m, b, "QLIKE", level=0.95)
    assert r["diff"] < 0 and r["interval"][0] < r["diff"] < r["interval"][1] and r["interval"][1] < 0       # a clear improvement: the whole interval below zero
    wider = BL.oos_block(m, b, "QLIKE", level=0.99)
    assert wider["interval"][0] < r["interval"][0] and wider["interval"][1] > r["interval"][1]


def test_sessions_with_a_non_finite_loss_or_on_one_side_only_are_counted_and_left_out():
    d = [0.1, 0.2] * 10
    m, b = losses(d)
    keys = sorted(m)
    m[keys[0]] = float("nan")
    b[keys[1]] = float("inf")
    m["2026-03-01"] = 1.0                                        # a session only the model has
    r = BL.oos_block(m, b, "QLIKE")
    assert r["n_sessions"] == 18 and r["sessions_dropped_non_finite"] == 2 and r["sessions_unmatched"] == 1
    assert r["diff"] == pytest.approx(np.mean(d[2:]))


def test_insertion_order_does_not_matter_but_the_dates_do():
    rng = np.random.default_rng(2)
    d = list(rng.normal(0.02, 0.05, 30))
    m, b = losses(d)
    shuffled_m = dict(reversed(list(m.items())))
    shuffled_b = dict(reversed(list(b.items())))
    assert BL.oos_block(shuffled_m, shuffled_b, "QLIKE") == BL.oos_block(m, b, "QLIKE")
    days = sorted(m)                                              # swap the losses of two non-adjacent dates: the autocovariances change, the mean does not
    m2 = dict(m)
    m2[days[3]], m2[days[20]] = m[days[20]], m[days[3]]
    r1, r2 = BL.oos_block(m, b, "QLIKE"), BL.oos_block(m2, b, "QLIKE")
    assert r1["diff"] == pytest.approx(r2["diff"]) and r1["t"] != r2["t"]


@pytest.mark.parametrize("make,why", [
    (lambda: (losses([0.1] * 9), "QLIKE", {}), "only 9 sessions"),
    (lambda: (losses([0.1] * 30), "QLIKE", {}), "does not vary"),                                          # a flat difference has no interval
    (lambda: (losses([0.1, 0.2] * 10), "", {}), "metric"),
    (lambda: (losses([0.1, 0.2] * 10), "QLIKE", {"level": 1.0}), "level"),
    (lambda: (losses([0.1, 0.2] * 10), "QLIKE", {"level": 0}), "level"),
    (lambda: (losses([0.1, 0.2] * 10), "QLIKE", {"level": True}), "level"),
    (lambda: (losses([0.1, 0.2] * 10), "QLIKE", {"lags": -1}), "lags"),
    (lambda: (losses([0.1, 0.2] * 10), "QLIKE", {"lags": True}), "lags"),
])
def test_there_is_no_block_without_an_honest_comparison(make, why):
    (m, b), metric, kw = make()
    with pytest.raises(ValueError, match=why):
        BL.oos_block(m, b, metric, **kw)


def test_sessions_must_be_iso_dates():
    m, b = losses([0.1, 0.2] * 10)
    for bad in ("session-7", "20260105", "2026-1-5", "2026-02-30", 5):
        m2, b2 = dict(m), dict(b)
        m2[bad] = b2[bad] = 1.0
        with pytest.raises(ValueError, match="ISO dates"):
            BL.oos_block(m2, b2, "QLIKE")


def test_the_block_is_what_a_model_card_asks_for():
    rng = np.random.default_rng(5)
    m, b = losses(list(-0.03 + rng.normal(0, 0.02, 50)))
    block = BL.oos_block(m, b, "QLIKE", level=0.9)
    run = {"model_id": "har-c", "version": "1", "spec": {"file": "x.json", "sha256": "a" * 64}, "code_commit": "b" * 40,
           "data": {"T1": {"manifest": "m", "digest": "47d28d6376ca63af", "status": "external_unverified"}},
           "training_window": {"start": "2010-01-04", "end": "2018-12-31", "cutoff": "2018-12-31"}, "settings": {"params": {}, "seed": 7}, "variants_tried": 4,
           "baseline": {"name": "A_desk", "version": "1"}, "oos": block, "leakage_tests": [{"name": "canary", "passed": True}], "status": "offline"}
    assert MC.check_run(run) == []                               # every number consistent: diff = model - baseline, interval around diff, n an integer
    card = MC.build_card(run)
    assert card["oos"]["n_sessions"] == 50 and MC.verify_card(card) == []


def test_a_forged_block_does_not_pass_the_card_but_the_scorers_does():
    m, b = losses([0.1, 0.2] * 10)
    block = BL.oos_block(m, b, "QLIKE")
    bad = dict(block, diff=block["diff"] + 0.5)
    assert any("must equal" in p or "inside" in p for p in MC.check_run({**_min_run(), "oos": bad}))
    assert MC.check_run({**_min_run(), "oos": block}) == []


def _min_run():
    return {"model_id": "m", "version": "1", "spec": {"file": "x.json", "sha256": "a" * 64}, "code_commit": "b" * 40,
            "data": {"T1": {"manifest": "m", "digest": "47d28d6376ca63af", "status": "external_unverified"}},
            "training_window": {"start": "2010-01-04", "end": "2018-12-31", "cutoff": "2018-12-31"}, "settings": {"params": {}, "seed": 1}, "variants_tried": 1,
            "baseline": {"name": "A", "version": "1"}, "oos": {}, "leakage_tests": [{"name": "c", "passed": True}], "status": "offline"}
