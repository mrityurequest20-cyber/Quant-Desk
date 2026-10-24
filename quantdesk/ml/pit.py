"""The point-in-time canary (P0.3/P0.4 of docs/ML_PHASE0.md): does a feature table use anything after its decision time?

A statistical leak scan cannot tell a leak from a good feature (a volatility forecast legitimately correlates with the volatility it
forecasts). A perturbation test can, exactly. For a sample decided at time t, replace *everything that happens after t* with
different data and rebuild the table: the sample's features must not move. Its labels, which are the future by definition, must
move, otherwise the perturbation never reached the future and the test proved nothing, so that is an error too.

The builder and the perturbation are the caller's: this module only runs the experiment and judges it. Features are compared with a
relative tolerance (default 1e-9) because floating-point reductions in numpy can change the last bit with memory alignment; a real
leak moves a feature by orders of magnitude more than that.

What it does not see: a table whose *rows* depend on the future (a filter on how complete the label window is, as in
`volstudy.rows`) is reported as a vanished row only if the perturbation changes it; the caller's perturbation should say, in its
docstring, what it leaves alone (the missing-minute mask, for example).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class PointInTimeError(AssertionError):
    """A feature moved when only the future was changed (or the test could not have detected one)."""


@dataclass
class PitReport:
    checked: int = 0
    max_rel_diff: dict[str, float] = field(default_factory=dict)       # per feature, the largest relative difference seen
    leaks: list[dict] = field(default_factory=list)
    label_moved: dict[str, float] = field(default_factory=dict)        # per label, the largest absolute change (the future did change)

    @property
    def ok(self) -> bool:
        return not self.leaks


def _rel(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Relative difference, 0 where both are NaN, inf where only one is."""
    both_nan, one_nan = np.isnan(a) & np.isnan(b), np.isnan(a) ^ np.isnan(b)
    with np.errstate(invalid="ignore", divide="ignore"):
        d = np.abs(a - b) / np.maximum(np.maximum(np.abs(a), np.abs(b)), np.finfo(float).tiny)
    d = np.where(a == b, 0.0, d)
    return np.where(both_nan, 0.0, np.where(one_nan, np.inf, d))


def _rows(df: pd.DataFrame, key: tuple) -> pd.DataFrame:
    """The rows whose leading index levels equal `key`, in index order."""
    try:
        out = df.xs(key if len(key) > 1 else key[0], level=list(range(len(key))), drop_level=False)
    except KeyError:
        return df.iloc[0:0]
    return out.sort_index()


def check_point_in_time(build, data, keys, perturb, key_cols: list[str], features: list[str], labels: list[str],
                        rtol: float = 1e-9, rng: np.random.Generator | None = None, require_label_move: bool = True) -> PitReport:
    """Run the canary.

    build(data) -> DataFrame holding `key_cols`, `features` and `labels`. keys: the (key tuple) samples to test.
    perturb(data, key, rng) -> a copy of `data` in which everything strictly after the sample `key` is different.
    For each key the table is rebuilt on the perturbed data and the sample's feature values compared with the original table.
    Raises PointInTimeError if no label moved for a key (a vacuous test) when `require_label_move`; returns the report otherwise
    (call `assert_point_in_time` to also raise on leaks)."""
    rng = rng or np.random.default_rng(0)
    base = build(data).set_index(key_cols)
    if base.index.has_duplicates:
        raise ValueError(f"the table has more than one row for the same {key_cols}")
    rep = PitReport(max_rel_diff={f: 0.0 for f in features}, label_moved={l: 0.0 for l in labels})
    for key in keys:
        key = key if isinstance(key, tuple) else (key,)
        # one sample is a (day, decision) and several rows (horizons): compare every row that shares the leading key
        sel_a = _rows(base, key)
        if len(sel_a) == 0:
            raise ValueError(f"no row of the table starts with {key}")
        sel_b = _rows(build(perturb(data, key, rng)).set_index(key_cols), key)
        rep.checked += 1
        if not sel_a.index.equals(sel_b.index):
            rep.leaks.append({"key": key, "feature": "(rows)", "why": "the set of rows for this sample changed when only the future changed",
                              "lost": [i for i in sel_a.index if i not in sel_b.index][:5], "new": [i for i in sel_b.index if i not in sel_a.index][:5]})
            continue
        moved = False
        for l in labels:
            ch = float(np.nanmax(np.abs(sel_a[l].to_numpy(float) - sel_b[l].to_numpy(float)))) if len(sel_a) else 0.0
            rep.label_moved[l] = max(rep.label_moved[l], ch)
            moved |= ch > 0
        if require_label_move and labels and not moved:
            raise PointInTimeError(f"the perturbation after {key} did not change any label: it did not reach the future, so this test proves nothing")
        for f in features:
            d = _rel(sel_a[f].to_numpy(float), sel_b[f].to_numpy(float))
            worst = float(d.max()) if len(d) else 0.0
            rep.max_rel_diff[f] = max(rep.max_rel_diff[f], worst)
            if worst > rtol:
                rep.leaks.append({"key": key, "feature": f, "rel_diff": worst, "why": "the feature moved when only the future changed"})
    return rep


def assert_point_in_time(*args, **kw) -> PitReport:
    """check_point_in_time, raising PointInTimeError with the leaks if there are any."""
    rep = check_point_in_time(*args, **kw)
    if rep.leaks:
        worst = sorted(rep.leaks, key=lambda x: -x.get("rel_diff", float("inf")))[:3]
        raise PointInTimeError(f"{len(rep.leaks)} leaks in {rep.checked} samples, e.g. {worst}")
    return rep


def perturb_minute_grid(grid: dict, key: tuple, rng: np.random.Generator, scale: float = 5e-3) -> dict:
    """For the minute-return grid of `volstudy.grid` ({'days','r','missing','opens'}) and a sample key (day or day index, minute): replace the
    returns from `minute` onward on that day and every return on every later day with random ones, and the later days' opens too.
    The missing-minute mask is left alone (a row's existence legitimately depends on whether its label window was observed)."""
    i = int(key[0]) if isinstance(key[0], (int, np.integer)) else int(grid["days"].get_loc(key[0]))
    m = int(key[1])
    r, opens = grid["r"].copy(), grid["opens"].copy()
    r[i, m:] = rng.standard_normal(r.shape[1] - m) * scale
    r[i + 1:] = rng.standard_normal(r[i + 1:].shape) * scale
    opens[i + 1:] = opens[i + 1:] * np.exp(rng.standard_normal(len(opens) - i - 1) * 0.05)
    return {**grid, "r": r, "opens": opens}
