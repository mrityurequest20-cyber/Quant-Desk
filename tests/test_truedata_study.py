"""TrueData research (research/truedata_study.py): the replay writes every call before its outcome and never looks ahead."""
import numpy as np
import pandas as pd

from quantdesk.research import truedata_study as S


def bars(n=80, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2026-01-01", periods=n)
    c = 24000 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = c * np.exp(rng.normal(0, 0.004, n))
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.004, "low": np.minimum(o, c) * 0.996, "close": c}, index=idx)


def test_every_prediction_is_made_before_its_outcome():
    f = S.replay(bars(), "NIFTY")
    assert (f["as_of"] < f["horizon_end"]).all() and f["outcome"].notna().all()
    assert set(f["source"]) == {"truedata_replay"}
    assert set(f["rule"]) >= {"D1", "B_persist", "B_reverse", "B_coin"}


def test_changing_the_future_never_changes_a_past_call():
    a = bars()
    b = a.copy()
    b.iloc[50:, :] *= 1.2                                          # rewrite everything from day 50 on
    fa, fb = S.replay(a, "NIFTY"), S.replay(b, "NIFTY")
    cut = str(a.index[49].date())
    keep = ["day", "rule", "direction", "rv20"]
    pa = fa[fa["day"] <= cut][keep].reset_index(drop=True)
    pb = fb[fb["day"] <= cut][keep].reset_index(drop=True)
    pd.testing.assert_frame_equal(pa, pb)                          # calls up to day 49 are identical


def test_ledger_refuses_a_prediction_about_the_past():
    led = S.ReplayLedger()
    t = pd.Timestamp("2026-01-05 15:30", tz="Asia/Kolkata")
    try:
        led.predict(t, t - pd.Timedelta(hours=6), "D1", "NIFTY", 1, {})
        raise AssertionError("accepted a horizon that ended before the call")
    except ValueError:
        pass


def test_scores_are_honest_about_one_sided_rules_and_small_samples():
    sc = S.score(S.replay(bars(), "NIFTY"), "NIFTY")
    assert sc["D1"]["always_one_side"] and sc["D1"]["balanced_accuracy"] == 0.5     # always long: BA is 0.5 by definition
    assert sc["D3"]["n"] < S.MIN_N and sc["D3"]["insufficient"]
    lo, hi = sc["D1"]["accuracy_ci95"]
    assert lo < sc["D1"]["accuracy"] < hi
