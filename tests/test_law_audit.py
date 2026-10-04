"""The robustness audit of a law (research/law_audit.py): weekly pooling, the stationary bootstrap, and the registered
verdict rule (two failed checks downgrade a principle; one is a caveat)."""
import numpy as np
import pandas as pd

from quantdesk.research import law_audit as A

HELD = ["AAA", "BBB", "CCC"]


def _trades(mean_bps, n_weeks=160, seed=1, start="2022-01-04", cost=0.5, credit=25.0):
    rng = np.random.default_rng(seed)
    rows = []
    for w, e in enumerate(pd.date_range(start, periods=n_weeks, freq="7D")):
        for s in HELD:
            rows.append({"symbol": s, "expiry": e.date(), "entry": (e - pd.Timedelta(days=1)).date(),
                         "bps": mean_bps + rng.normal(0, 30), "cost_bps": cost, "credit_bps": credit})
    return pd.DataFrame(rows)


def test_weekly_pooling_counts_a_shared_week_once():
    tr = pd.DataFrame({"symbol": ["AAA", "BBB", "AAA"], "expiry": ["2024-01-02", "2024-01-04", "2024-01-09"],
                       "bps": [10.0, 20.0, -6.0]})
    w = A.weekly(tr)
    assert list(w) == [15.0, -6.0] and len(w) == 2                    # Tue and Thu of one ISO week: one observation


def test_the_bootstrap_is_deterministic_and_centred():
    x = np.random.default_rng(3).normal(5, 20, 300)
    a, b = A.stationary_bootstrap(x, reps=2000), A.stationary_bootstrap(x, reps=2000)
    assert np.array_equal(a, b) and abs(np.median(a) - x.mean()) < 1.0


def test_a_strong_effect_passes_and_a_dead_one_is_downgraded():
    good = _trades(9.0)
    res = A.audit_structure(good, HELD, None, {100: good, 1000: good})
    assert res["fails"] == [] and res["verdict"] == "replicated, robust"
    dead = _trades(0.0, seed=7)
    res = A.audit_structure(dead, HELD, None, {100: dead, 1000: dead})
    assert len(res["fails"]) >= 2 and res["verdict"] == "found (downgraded)"


def test_reproduction_must_match_the_registered_numbers():
    tr = _trades(9.0)
    base = A._mt(A.weekly(tr))
    ok = A.audit_structure(tr, HELD, {"pooled": base}, {100: tr, 1000: tr})
    assert ok["checks"]["0_reproduce"]["pass"]
    off = dict(base, mean_bps=base["mean_bps"] + 1)
    bad = A.audit_structure(tr, HELD, {"pooled": off}, {100: tr, 1000: tr})
    assert not bad["checks"]["0_reproduce"]["pass"] and bad["verdict"] == "found (reproduction failed)"


def test_costs_scale_linearly_and_break_even_is_reported():
    tr = _trades(9.0, cost=3.0)
    c = A.audit_structure(tr, HELD, None, {100: tr, 1000: tr})["checks"]["4_costs"]
    assert c["pass"] and "break-even at" in c["detail"]
    pricey = _trades(4.0, cost=3.0)                                    # ×2 costs: 4 − 3 = +1; ×3: 4 − 6 < 0
    d = A.audit_structure(pricey, HELD, None, {100: pricey, 1000: pricey})["checks"]["4_costs"]["detail"]
    assert "×3: -" in d
