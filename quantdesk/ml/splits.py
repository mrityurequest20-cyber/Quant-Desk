"""Time-aware train/test splits for labels that look into the future (P0.4 of docs/ML_PHASE0.md).

A sample is known at `t0` (the decision time: its features use data up to then) and its label is known at `t1` (the end of the
horizon). Two samples interact when their [t0, t1] intervals overlap, so a plain random or even a chronological split leaks: a
training sample whose label window reaches into the test period has already seen the test period. The remedy (Lopez de Prado,
Advances in Financial Machine Learning, ch. 7) is to *purge* from the training set every sample whose interval overlaps a test
window, and to *embargo* the samples that start shortly after a test window, whose features may have been built from it.

Intervals are closed: a label that ends exactly where a test window begins touches it and is purged. All times are int64
nanoseconds (use `as_ns`); nothing here looks at the data, only at when it was known.

- `walk_forward`: expanding (or rolling) train windows before each test fold, with an optional gap.
- `cpcv`: combinatorial purged cross-validation: every combination of `n_test` of `n_groups` time-ordered groups is a test set,
  and the out-of-sample predictions are stitched into `cpcv_paths` complete paths, so a metric has a distribution, not a point.
- `check_no_overlap`: the verifier. A split that fails it is leaking; it is what the tests inject leaks against.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


class LeakError(AssertionError):
    """A split lets a training sample's [t0, t1] overlap a test window (or its embargo)."""


@dataclass(frozen=True)
class Fold:
    train: np.ndarray            # sample indices
    test: np.ndarray
    label: str                   # what the fold is (a test period, or the groups of a CPCV combination)
    purged: int = 0              # training samples removed because their interval overlaps a test window
    embargoed: int = 0           # ...and because they start inside the embargo after one


def as_ns(x) -> np.ndarray:
    """int64 nanoseconds since the epoch (UTC) from datetime64, a DatetimeIndex, a datetime Series or integers. A missing time (NaT) is refused:
    it would become the smallest integer and sit in every fold's training set."""
    if isinstance(x, pd.Series):
        x = x.to_numpy() if not isinstance(x.dtype, pd.DatetimeTZDtype) else pd.DatetimeIndex(x)
    if isinstance(x, pd.DatetimeIndex):
        if x.isna().any():
            raise ValueError("a time is missing (NaT)")
        return (x.tz_convert("UTC") if x.tz is not None else x).as_unit("ns").asi8.astype("int64")
    a = np.asarray(x)
    if np.issubdtype(a.dtype, np.datetime64):
        if np.isnat(a).any():
            raise ValueError("a time is missing (NaT)")
        return a.astype("datetime64[ns]").astype("int64")
    if np.issubdtype(a.dtype, np.integer):
        return a.astype("int64")
    raise TypeError(f"times must be datetimes or integers, not {a.dtype}")


def _check_times(t0: np.ndarray, t1: np.ndarray) -> None:
    if t0.shape != t1.shape or t0.ndim != 1:
        raise ValueError("t0 and t1 must be one-dimensional and the same length")
    if (t1 < t0).any():
        raise ValueError("a label ends before its features are known (t1 < t0)")


def overlaps(t0: np.ndarray, t1: np.ndarray, windows: list[tuple[int, int]], embargo: int = 0) -> np.ndarray:
    """Mask of samples whose closed interval [t0, t1] intersects any closed window (a, b), or starts in (b, b + embargo]."""
    if embargo < 0:
        raise ValueError("embargo cannot be negative")
    hit = np.zeros(len(t0), dtype=bool)
    for a, b in windows:
        hit |= (t0 <= b + embargo) & (t1 >= a)
    return hit


def feature_window_hits(t0: np.ndarray, session: np.ndarray, lookback_sessions: int, test: np.ndarray, cand: np.ndarray) -> np.ndarray:
    """Mask over `cand` (training candidates): samples whose features read data from a test sample's session. A sample decided at time t in
    session s has features built from session s up to t and from the `lookback_sessions` sessions before it (for the M1 table, the grid sessions
    `x_prev5` and the A / B priors average), so it is contaminated when a test sample sits in one of those sessions, or in session s itself
    earlier in the day than t. `session` is each sample's ordinal in the feature builder's own calendar, so a holiday cluster or a dropped
    session cannot make five sessions look like nine days."""
    if lookback_sessions < 0:
        raise ValueError("lookback_sessions cannot be negative")
    ts_all = session[test]
    ordered = np.argsort(ts_all, kind="stable")
    ts_sorted = ts_all[ordered]
    first = pd.Series(t0[test][ordered]).groupby(ts_sorted).min()                 # earliest test decision in each test session
    sess, first_t0 = first.index.to_numpy(), first.to_numpy()
    sc, tc = session[cand], t0[cand]
    lo = np.searchsorted(sess, sc - lookback_sessions, side="left")
    hi = np.searchsorted(sess, sc, side="left")
    earlier_session = hi > lo                                                      # some test session in [s - L, s - 1]
    j = np.minimum(hi, len(sess) - 1)
    same_session = (hi < len(sess)) & (sess[j] == sc) & (first_t0[j] < tc)         # a test decision earlier the same day
    return earlier_session | same_session


def walk_forward(t0, t1, test_edges, gap: int = 0, rolling: int | None = None, min_train: int = 1) -> list[Fold]:
    """Folds whose test set is the samples with t0 in [test_edges[j], test_edges[j+1]) and whose train set is every earlier
    sample whose label ended at least `gap` before the test period began (`gap` 0 is the plain purge: a label that reaches the
    test period is dropped). `rolling` keeps only the train samples that began within that many nanoseconds of the test start."""
    t0, t1 = as_ns(t0), as_ns(t1)
    _check_times(t0, t1)
    edges = as_ns(test_edges)
    if len(edges) < 2 or (np.diff(edges) <= 0).any():
        raise ValueError("test_edges must be at least two strictly increasing times")
    if gap < 0:
        raise ValueError("gap cannot be negative")
    folds = []
    for a, b in zip(edges[:-1], edges[1:]):
        test = np.flatnonzero((t0 >= a) & (t0 < b))
        before = t0 < a
        ok = before & (t1 < a - gap)
        if rolling is not None:
            ok &= t0 >= a - rolling
        train = np.flatnonzero(ok)
        if len(test) == 0 or len(train) < min_train:
            continue
        folds.append(Fold(train, test, f"{pd.Timestamp(a)} to {pd.Timestamp(b)}", purged=int((before & ~ok).sum()), embargoed=0))
    return folds


def group_edges(t0, n_groups: int) -> np.ndarray:
    """Boundaries of `n_groups` contiguous time-ordered groups of (nearly) equal size, as sample positions into the sort by t0."""
    n = len(as_ns(t0))
    if not 2 <= n_groups <= n:
        raise ValueError("need 2 <= n_groups <= number of samples")
    return np.linspace(0, n, n_groups + 1).round().astype(int)


def cpcv(t0, t1, n_groups: int, n_test: int, *, embargo: int, session=None, lookback_sessions: int | None = None,
         samples_independent: bool = False) -> list[Fold]:
    """Combinatorial purged CV. The samples are sorted by t0 and cut into `n_groups` contiguous groups; every combination of
    `n_test` groups is a test set (C(n_groups, n_test) folds). Each fold's training set is everything else minus the samples
    whose interval overlaps a test group's time window, minus those that start within `embargo` after it.

    `embargo` (nanoseconds) has no default and cannot be negative, because the right value is a property of the features, not of the
    split: a sample's features that look back over earlier sessions (the M1 table's reach five) read the test labels of a block that ended
    just before it. A time embargo cannot say "five sessions" (holidays and dropped sessions stretch five sessions over more than nine days, and
    the measured real spans reach 19), so give `session` (each sample's ordinal in the feature builder's calendar, the M1 table's `session`
    column) and `lookback_sessions`: every training sample whose feature window contains a test session is then removed as well
    (`feature_window_hits`). Both or neither. With neither and `embargo == 0` the split assumes the features of one sample never read another's period:
    say so with `samples_independent=True` (it is true of samples whose features are built from data before their own decision and not from
    neighbouring samples' sessions, and false for the M1 table, for which use `build.cpcv_for`). Pooling several symbols through `session=` over-purges
    safely (their ordinals collide) but `cpcv_for` takes one symbol at a time."""
    if embargo < 0:
        raise ValueError("embargo cannot be negative")
    if session is None and embargo == 0 and not samples_independent:
        raise ValueError("embargo=0 without session and lookback_sessions assumes the features never read a neighbouring sample's period: say so with "
                         "samples_independent=True, or give session and lookback_sessions (build.cpcv_for does for the M1 table)")
    if (session is None) != (lookback_sessions is None):
        raise ValueError("session and lookback_sessions go together")
    session = None if session is None else np.asarray(session, dtype="int64")
    if session is not None and session.shape != np.shape(t0):
        raise ValueError("session must have one entry per sample")
    t0, t1 = as_ns(t0), as_ns(t1)
    _check_times(t0, t1)
    if not 1 <= n_test < n_groups:
        raise ValueError("need 1 <= n_test < n_groups")
    order = np.argsort(t0, kind="stable")
    cut = group_edges(t0, n_groups)
    groups = [order[cut[g]:cut[g + 1]] for g in range(n_groups)]
    windows = [(int(t0[g].min()), int(t1[g].max())) for g in groups]
    folds = []
    for combo in itertools.combinations(range(n_groups), n_test):
        test = np.sort(np.concatenate([groups[g] for g in combo]))
        cand = np.setdiff1d(np.arange(len(t0)), test)
        win = [windows[g] for g in combo]
        hit_plain, hit_emb = overlaps(t0[cand], t1[cand], win, 0), overlaps(t0[cand], t1[cand], win, embargo)
        if session is not None:
            hit_emb = hit_emb | feature_window_hits(t0, session, lookback_sessions, test, cand)
        folds.append(Fold(cand[~hit_emb], test, "groups " + ",".join(map(str, combo)),
                          purged=int(hit_plain.sum()), embargoed=int((hit_emb & ~hit_plain).sum())))
    return folds


def cpcv_paths(n_groups: int, n_test: int) -> list[dict[int, int]]:
    """The backtest paths of a CPCV. Group g is in the test set of C(n_groups-1, n_test-1) combinations; path p takes, for every
    group, its p-th such combination, so every path covers every group exactly once. -> a list of {group: combination index}."""
    combos = list(itertools.combinations(range(n_groups), n_test))
    per_group = {g: [i for i, c in enumerate(combos) if g in c] for g in range(n_groups)}
    n_paths = math.comb(n_groups - 1, n_test - 1)
    return [{g: per_group[g][p] for g in range(n_groups)} for p in range(n_paths)]


def check_test_mask(folds: list[Fold], allowed: np.ndarray) -> None:
    """Raise LeakError if any fold tests on a sample the mask does not allow (for the M1 table: rows with `in_profile` True, whose seasonal
    features were fitted on days after them, must never be scored)."""
    allowed = np.asarray(allowed, dtype=bool)
    for k, f in enumerate(folds):
        bad = ~allowed[f.test]
        if bad.any():
            raise LeakError(f"fold {k} ({f.label}): {int(bad.sum())} test samples are not allowed to be scored")


def check_no_overlap(folds: list[Fold], t0, t1, embargo: int = 0, windows: list[list[tuple[int, int]]] | None = None,
                     session=None, lookback_sessions: int | None = None) -> None:
    """Raise LeakError unless every fold's training samples are clear of its test windows (and embargo), and train and test are
    disjoint. A fold's test window defaults to the single span from its first t0 to its last t1; pass `windows` (one list per
    fold) when the test set is several separated groups, as in CPCV. With `session` and `lookback_sessions` it also raises if any training sample's
    feature window contains a test session (`feature_window_hits`): the check a time embargo cannot make."""
    if (session is None) != (lookback_sessions is None):
        raise ValueError("session and lookback_sessions go together")
    t0, t1 = as_ns(t0), as_ns(t1)
    for k, f in enumerate(folds):
        if np.intersect1d(f.train, f.test).size:
            raise LeakError(f"fold {k} ({f.label}): a sample is in both train and test")
        if len(f.train) == 0 or len(f.test) == 0:
            continue
        w = windows[k] if windows is not None else [(int(t0[f.test].min()), int(t1[f.test].max()))]
        bad = overlaps(t0[f.train], t1[f.train], w, embargo)
        if bad.any():
            raise LeakError(f"fold {k} ({f.label}): {int(bad.sum())} training samples overlap a test window")
        if session is not None:
            hit = feature_window_hits(t0, np.asarray(session, dtype="int64"), lookback_sessions, f.test, f.train)
            if hit.any():
                raise LeakError(f"fold {k} ({f.label}): {int(hit.sum())} training samples have a test session inside their feature window")


def windows_of(folds: list[Fold], t0, t1) -> list[list[tuple[int, int]]]:
    """Per fold, the closed time windows of its test samples' contiguous runs in time order (what a CPCV test set covers)."""
    t0, t1 = as_ns(t0), as_ns(t1)
    out = []
    for f in folds:
        idx = f.test[np.argsort(t0[f.test], kind="stable")]
        runs, start = [], 0
        pos = np.argsort(np.argsort(t0, kind="stable"), kind="stable")[idx]          # rank of each test sample in the full time order
        for i in range(1, len(idx) + 1):
            if i == len(idx) or pos[i] != pos[i - 1] + 1:
                runs.append((int(t0[idx[start:i]].min()), int(t1[idx[start:i]].max())))
                start = i
        out.append(runs)
    return out
