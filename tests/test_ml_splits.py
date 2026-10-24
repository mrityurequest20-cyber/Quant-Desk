"""P0.4: purged walk-forward and combinatorial purged CV (quantdesk/ml/splits.py): the purge, the embargo, the CPCV paths, and that the
verifier catches the leaks it exists for (a split that does not purge)."""
import math

import numpy as np
import pandas as pd
import pytest

from quantdesk.ml import splits as S

DAY = 86_400 * 10 ** 9


def daily(n=60, horizon_days=3):
    """n samples a day apart; each label looks `horizon_days` ahead (so labels overlap their neighbours)."""
    t0 = np.arange(n, dtype="int64") * DAY
    return t0, t0 + horizon_days * DAY


# ---- times ----------------------------------------------------------------------------------------------------------
def test_as_ns_accepts_the_time_types_we_use_and_refuses_the_rest():
    ts = pd.date_range("2024-01-01 09:30", periods=3, freq="D", tz="Asia/Kolkata")
    want = ts.tz_convert("UTC").as_unit("ns").asi8
    assert np.array_equal(S.as_ns(ts), want) and np.array_equal(S.as_ns(pd.Series(ts)), want)
    naive = pd.date_range("2024-01-01", periods=3, freq="D")
    assert np.array_equal(S.as_ns(naive.to_numpy()), naive.as_unit("ns").asi8) and np.array_equal(S.as_ns(pd.Series(naive)), naive.as_unit("ns").asi8)
    assert np.array_equal(S.as_ns([1, 2, 3]), np.array([1, 2, 3])) and S.as_ns(naive.to_numpy().astype("datetime64[us]")).dtype == np.int64
    with pytest.raises(TypeError):
        S.as_ns([1.5, 2.5])


def test_overlap_is_closed_and_the_embargo_only_reaches_forward():
    t0, t1 = np.array([0, 10, 20, 30, 40]), np.array([5, 15, 20, 35, 45])
    win = [(20, 30)]
    assert S.overlaps(t0, t1, win).tolist() == [False, False, True, True, False]            # [20,20] and [30,35] touch the window
    assert S.overlaps(t0, t1, win, embargo=10).tolist() == [False, False, True, True, True]   # 40 starts within 10 after 30
    assert S.overlaps(np.array([41]), np.array([45]), win, embargo=10).tolist() == [False]       # 41 is one past the embargo
    assert S.overlaps(t0, t1, win, embargo=10)[1] == False                                    # nothing before the window is embargoed  # noqa: E712
    assert S.overlaps(np.array([5]), np.array([19]), win).tolist() == [False] and S.overlaps(np.array([5]), np.array([20]), win).tolist() == [True]


# ---- walk-forward ---------------------------------------------------------------------------------------------------
def test_walk_forward_purges_the_labels_that_reach_into_the_test_period():
    t0, t1 = daily(60, 3)
    folds = S.walk_forward(t0, t1, [20 * DAY, 30 * DAY, 40 * DAY])
    assert len(folds) == 2
    f = folds[0]
    assert f.test.tolist() == list(range(20, 30))
    assert f.train.tolist() == list(range(0, 17)) and f.purged == 3                           # samples 17, 18, 19 end on or after day 20
    assert folds[1].train.max() == 26 and folds[1].purged == 3 and f.embargoed == 0
    S.check_no_overlap(folds, t0, t1)


def test_walk_forward_gap_and_rolling_window():
    t0, t1 = daily(60, 3)
    gapped = S.walk_forward(t0, t1, [20 * DAY, 30 * DAY], gap=5 * DAY)[0]
    assert gapped.train.max() == 11 and gapped.purged == 8                                     # t1 < 20 - 5 days, so t0 < 12
    rolled = S.walk_forward(t0, t1, [30 * DAY, 40 * DAY], rolling=10 * DAY)[0]
    assert rolled.train.min() == 20 and rolled.train.max() == 26


def test_walk_forward_skips_empty_folds_and_rejects_bad_input():
    t0, t1 = daily(30, 1)
    assert len(S.walk_forward(t0, t1, [0, 10 * DAY, 20 * DAY], min_train=1)) == 1             # the first fold has nothing before it
    assert S.walk_forward(t0, t1, [100 * DAY, 110 * DAY]) == []                                # no samples in the test period
    for bad in ([5 * DAY], [10 * DAY, 10 * DAY], [20 * DAY, 10 * DAY]):
        with pytest.raises(ValueError):
            S.walk_forward(t0, t1, bad)
    with pytest.raises(ValueError, match="gap"):
        S.walk_forward(t0, t1, [10 * DAY, 20 * DAY], gap=-1)
    with pytest.raises(ValueError, match="t1 < t0"):
        S.walk_forward(t0, t0 - 1, [10 * DAY, 20 * DAY])
    with pytest.raises(ValueError):
        S.walk_forward(t0, t1[:-1], [10 * DAY, 20 * DAY])


# ---- the injected leaks ---------------------------------------------------------------------------------------------
def test_the_verifier_catches_a_split_that_does_not_purge():
    """The leak the harness exists for: a chronological split with no purge trains on labels that reach into the test period."""
    t0, t1 = daily(60, 5)
    a = 30 * DAY
    naive = S.Fold(np.flatnonzero(t0 < a), np.flatnonzero((t0 >= a) & (t0 < 40 * DAY)), "naive")
    with pytest.raises(S.LeakError, match="overlap a test window"):
        S.check_no_overlap([naive], t0, t1)
    honest = S.walk_forward(t0, t1, [a, 40 * DAY])
    S.check_no_overlap(honest, t0, t1)                                                         # and the same data, purged, passes


def test_the_verifier_catches_overlap_with_the_embargo_and_a_shared_sample():
    t0, t1 = daily(60, 1)
    test = np.arange(20, 30)
    assert S.overlaps(t0[[30]], t1[[30]], [(int(t0[20]), int(t1[29]))]).tolist() == [True]      # sample 30 starts where test sample 29's label ends
    leaky = S.Fold(np.arange(31, 34), test, "starts just after the test window")
    S.check_no_overlap([leaky], t0, t1)                                                        # fine without an embargo...
    with pytest.raises(S.LeakError):
        S.check_no_overlap([leaky], t0, t1, embargo=3 * DAY)                                   # ...a leak with one
    S.check_no_overlap([S.Fold(np.arange(34, 37), test, "clear of the embargo")], t0, t1, embargo=3 * DAY)
    with pytest.raises(S.LeakError, match="both train and test"):
        S.check_no_overlap([S.Fold(np.array([1, 25]), test, "shared")], t0, t1)


def test_cpcv_without_a_purge_is_caught_and_the_real_one_passes():
    t0, t1 = daily(60, 4)
    real = S.cpcv(t0, t1, n_groups=6, n_test=2, embargo=0)
    S.check_no_overlap(real, t0, t1, windows=S.windows_of(real, t0, t1))
    unpurged = [S.Fold(np.setdiff1d(np.arange(60), f.test), f.test, f.label) for f in real]
    with pytest.raises(S.LeakError):
        S.check_no_overlap(unpurged, t0, t1, windows=S.windows_of(unpurged, t0, t1))


def test_a_test_set_of_separated_groups_needs_its_own_windows_not_one_span():
    """Using one span from the first to the last test sample would purge the training samples between the groups for no reason and,
    worse, would hide which windows matter. windows_of gives one window per contiguous run."""
    t0, t1 = daily(60, 2)
    folds = S.cpcv(t0, t1, 6, 2, embargo=0)
    sep = next(k for k, fold in enumerate(folds) if fold.label == "groups 0,3")
    w = S.windows_of(folds, t0, t1)[sep]
    assert len(w) == 2 and w[0][1] < w[1][0]
    S.check_no_overlap([folds[sep]], t0, t1, windows=[w])


# ---- CPCV -----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("n, k", [(6, 2), (5, 1), (8, 3), (4, 3)])
def test_cpcv_counts_folds_groups_and_paths(n, k):
    t0, t1 = daily(96, 2)
    folds = S.cpcv(t0, t1, n, k, embargo=0)
    assert len(folds) == math.comb(n, k)
    for f in folds:
        assert np.intersect1d(f.train, f.test).size == 0 and len(f.test) == pytest.approx(96 * k / n, abs=k)
    paths = S.cpcv_paths(n, k)
    assert len(paths) == math.comb(n - 1, k - 1)
    for p in paths:
        assert sorted(p) == list(range(n))                                                      # every path covers every group once
        for g, c in p.items():
            assert f"{g}" in folds[c].label.removeprefix("groups ").split(",")                  # ...from a combination that tests that group
    for g in range(n):
        used = [p[g] for p in paths]
        assert len(set(used)) == len(used)                                                      # no two paths share a (group, combination)


def test_cpcv_embargo_removes_the_samples_that_start_just_after_a_test_group():
    t0, t1 = daily(60, 1)
    plain = S.cpcv(t0, t1, 6, 1, embargo=0)
    emb = S.cpcv(t0, t1, 6, 1, embargo=3 * DAY)
    f0, e0 = plain[2], emb[2]                                                                   # test group 2 = samples 20..29
    assert f0.test.tolist() == list(range(20, 30))
    assert 30 not in e0.train and 31 not in e0.train and 32 not in e0.train and 33 not in e0.train and 34 in e0.train
    assert e0.embargoed == 3 and f0.embargoed == 0 and e0.purged == f0.purged == 2               # 19 (label touches 20) and 30 (starts at 30); and 30 counts
    S.check_no_overlap(emb, t0, t1, embargo=3 * DAY, windows=S.windows_of(emb, t0, t1))


def test_cpcv_rejects_impossible_shapes():
    t0, t1 = daily(10, 1)
    for n, k in ((1, 1), (6, 0), (6, 6), (20, 2)):
        with pytest.raises(ValueError):
            S.cpcv(t0, t1, n, k, embargo=0)


def test_folds_are_deterministic_and_do_not_depend_on_input_order():
    t0, t1 = daily(60, 3)
    a = S.cpcv(t0, t1, 6, 2, embargo=DAY)
    perm = np.random.default_rng(3).permutation(60)
    b = S.cpcv(t0[perm], t1[perm], 6, 2, embargo=DAY)
    assert all(np.array_equal(x.train, y.train) and np.array_equal(x.test, y.test) for x, y in zip(a, S.cpcv(t0, t1, 6, 2, embargo=DAY)))
    for x, y in zip(a, b):                                                                      # the same samples, whatever the row order
        assert np.array_equal(np.sort(perm[y.train]), x.train) and np.array_equal(np.sort(perm[y.test]), x.test)


# ---- randomised: no split of any shape may pass the verifier while leaking ------------------------------------------
@pytest.mark.parametrize("seed", range(8))
def test_random_samples_every_split_is_clean_and_loses_only_what_it_must(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(40, 200))
    t0 = np.sort(rng.integers(0, 400, n)).astype("int64") * DAY
    t1 = t0 + rng.integers(0, 15, n).astype("int64") * DAY
    edges = np.sort(rng.choice(np.arange(20, 380), size=int(rng.integers(3, 7)), replace=False)) * DAY
    wf = S.walk_forward(t0, t1, edges, gap=int(rng.integers(0, 5)) * DAY)
    S.check_no_overlap(wf, t0, t1)
    for f in wf:                                                                                 # nothing is dropped except what overlaps
        assert len(f.train) + f.purged == int((t0 < t0[f.test].min()).sum()) and f.embargoed == 0
    k = int(rng.integers(1, 3))
    cp = S.cpcv(t0, t1, int(rng.integers(k + 1, 8)), k, embargo=int(rng.integers(0, 6)) * DAY)
    S.check_no_overlap(cp, t0, t1, embargo=0, windows=S.windows_of(cp, t0, t1))
    for f in cp:                                                                                  # accounting: train + dropped + test = everyone
        assert len(f.train) + f.purged + f.embargoed + len(f.test) == n


# ---- the guards added after review of the first head ------------------------------------------------------------------
def test_the_embargo_is_required_and_cannot_be_negative():
    t0 = np.arange(40) * DAY
    t1 = t0 + 1
    with pytest.raises(TypeError):
        S.cpcv(t0, t1, 4, 1)                                           # no default: the right value belongs to the features
    with pytest.raises(TypeError):
        S.cpcv(t0, t1, 4, 1, 0)                                        # and it is keyword-only, so it cannot be a stray positional
    with pytest.raises(ValueError, match="negative"):
        S.cpcv(t0, t1, 4, 1, embargo=-DAY)
    with pytest.raises(ValueError, match="negative"):
        S.overlaps(t0, t1, [(0, 1)], embargo=-1)
    with pytest.raises(ValueError, match="negative"):
        S.check_no_overlap(S.cpcv(t0, t1, 4, 1, embargo=0), t0, t1, embargo=-1)


def test_a_missing_time_is_refused_not_turned_into_the_smallest_integer():
    good = pd.date_range("2024-01-01", periods=5, freq="D")
    for bad in (good.insert(2, pd.NaT), np.array(["2024-01-01", "NaT"], dtype="datetime64[ns]"), pd.Series(good.insert(1, pd.NaT)),
                pd.date_range("2024-01-01", periods=3, freq="D", tz="Asia/Kolkata").insert(1, pd.NaT)):
        with pytest.raises(ValueError, match="NaT"):
            S.as_ns(bad)
    assert S.as_ns(good).dtype == np.int64


def test_a_feature_lookback_longer_than_the_embargo_is_caught_by_the_verifier_and_closed_by_the_embargo():
    """Features that read the last five sessions: a sample just after a test block has the block's labels in its inputs."""
    days = np.repeat(np.arange(60), 4)                                          # 60 sessions, four decisions each
    t0 = days * DAY + np.tile(np.arange(4), 60) * (DAY // 8)
    t1 = t0 + DAY // 8                                                           # a label ends within the session
    lookback = 5 * DAY
    leaky = S.cpcv(t0, t1, 6, 2, embargo=0)
    S.check_no_overlap(leaky, t0, t1, embargo=0, windows=S.windows_of(leaky, t0, t1))               # the plain verifier is satisfied...
    with pytest.raises(S.LeakError):
        S.check_no_overlap(leaky, t0, t1, embargo=lookback, windows=S.windows_of(leaky, t0, t1))    # ...the lookback-aware one is not
    safe = S.cpcv(t0, t1, 6, 2, embargo=lookback)
    S.check_no_overlap(safe, t0, t1, embargo=lookback, windows=S.windows_of(safe, t0, t1))
    assert sum(f.embargoed for f in safe) > 0 and all(len(f.train) < len(g.train) for f, g in zip(safe, leaky) if f.embargoed)


def test_check_test_mask_refuses_a_fold_that_scores_a_flagged_sample():
    t0 = np.arange(30) * DAY
    folds = S.walk_forward(t0, t0 + 1, [10 * DAY, 20 * DAY, 30 * DAY])
    allowed = np.ones(30, dtype=bool)
    S.check_test_mask(folds, allowed)
    allowed[15] = False                                                          # a sample in the second fold's test set
    with pytest.raises(S.LeakError, match="1 test samples"):
        S.check_test_mask(folds, allowed)
    allowed[15], allowed[3] = True, False                                        # a training-only sample being flagged is not a test leak
    S.check_test_mask(folds, allowed)


# ---- the feature-window purge ---------------------------------------------------------------------------------------------
def test_feature_window_hits_by_hand():
    """Sessions 0 to 9, two decisions a session; test = both decisions of session 4 and the second decision of session 7; look back 2 sessions."""
    session = np.repeat(np.arange(10), 2)
    t0 = np.arange(20) * 10
    test = np.array([8, 9, 15])                                                    # session 4 (both) and session 7's second decision
    cand = np.setdiff1d(np.arange(20), test)
    hit = dict(zip(map(int, cand), map(bool, S.feature_window_hits(t0, session, 2, test, cand))))
    contaminated = {10, 11, 12, 13,                                                # sessions 5 and 6 look back to session 4
                    16, 17, 18, 19}                                                # sessions 8 and 9 look back to session 7 (7's first decision, 14, does not)
    assert {i for i, h in hit.items() if h} == contaminated
    assert not hit[14]                                                             # same session as the test decision but earlier in the day
    assert not any(hit[i] for i in (0, 1, 2, 3, 4, 5, 6, 7))                       # sessions 0 to 3 are before the test session
    assert not S.feature_window_hits(t0, session, 0, test, cand)[list(cand).index(10)]      # with no lookback the next session is clean


def test_a_test_decision_earlier_the_same_day_contaminates_a_later_training_decision_only():
    session = np.array([3, 3, 3])
    t0 = np.array([100, 200, 300])
    test, cand = np.array([1]), np.array([0, 2])
    hit = S.feature_window_hits(t0, session, 5, test, cand)
    assert list(hit) == [False, True]


def test_feature_window_hits_agrees_with_the_definition_on_random_input():
    rng = np.random.default_rng(3)
    for _ in range(60):
        n = int(rng.integers(5, 60))
        session = np.sort(rng.integers(0, 20, n))
        t0 = rng.permutation(n) * 7 + session * 1000
        order = np.argsort(t0, kind="stable")
        session, t0 = session[order], t0[order]
        test = np.flatnonzero(rng.random(n) < 0.3)
        if not len(test):
            continue
        cand = np.setdiff1d(np.arange(n), test)
        L = int(rng.integers(0, 6))
        want = np.array([((session[test] >= session[i] - L) & (session[test] < session[i])).any() or ((session[test] == session[i]) & (t0[test] < t0[i])).any() for i in cand])
        assert (S.feature_window_hits(t0, session, L, test, cand) == want).all()
    with pytest.raises(ValueError, match="negative"):
        S.feature_window_hits(t0, session, -1, test, cand)
