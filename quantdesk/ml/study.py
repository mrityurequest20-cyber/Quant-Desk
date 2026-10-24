"""The locked move-size study, rerun through the platform (P0.4 of docs/ML_PHASE0.md).

`reproduce.reproduce` reruns `volstudy.run`, which proves the old study is deterministic and the committed result untampered; it never touches the
new pieces. This does. It reproduces the study's dev selection and its one-shot lock from the pre-registered spec using only:

- `splits.walk_forward` for the yearly dev folds (train on every earlier session, test on the year; a closed-interval purge that removes nothing
  here because every label ends inside its session, and the verifier is run all the same);
- `build.build_tables` to rebuild the table for each fold with the seasonal profile fitted on that fold's training sessions only, so a fold's
  training rows are exactly the rows with `in_profile` and its test rows exactly the rows without it (`splits.check_test_mask` asserts it);
- the study's own fit and score functions (`fit_c`, `predict_c`, `score`, `daily_loss`, `qlike`) on those rows, and the same Diebold-Mariano test.

Its output has the committed result's shape for `sessions`, `dev`, `selected`, `lock/tests` and `lock/profile` (the builder's fitted seasonal profile,
rounded as the file has it), and `reproduce_through_platform` compares every number of the committed file (the lock's `opened` time is a string and is
ignored). It first checks that the dataset's sessions are the ones the result was computed on, and refuses before computing anything if not. A bug in the builder (a profile fitted on the wrong days, a mis-keyed row, a label window off by one) or in the
splits (a training session that is not in the past) changes a number and fails the comparison. It writes nothing.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..autolearn import volstudy as V
from ..autolearn.prereg import nw_t, spec_hash
from . import build as B
from . import splits as S
from .reproduce import Comparison, ReproductionRefused, compare_results

IST = "Asia/Kolkata"
COMPARED = ("sessions", "dev", "selected")                  # whole subtrees of the committed result; "lock" is compared at lock/tests and lock/profile


def _session_times(days) -> tuple[np.ndarray, np.ndarray]:
    """Open and close of each session in nanoseconds UTC: the interval a session's labels live in."""
    d = pd.to_datetime(pd.Series(list(days)))
    ns = lambda x: pd.DatetimeIndex(x).tz_convert("UTC").as_unit("ns").asi8.astype("int64")
    open_ = d.dt.tz_localize(IST) + pd.Timedelta(hours=9, minutes=15)
    return ns(open_), ns(open_ + pd.Timedelta(hours=6, minutes=15))


def _frame(grids: dict, sym: str, profile_end, train_days: list, test_days: set, tier: str):
    """Rebuild the table with the profile fitted up to `profile_end`; fit on the rows of exactly the sessions the split called training, and
    return (test rows with F_C, the fit). The study was run on grids whose leading gaps are back-filled, so the reproduction allows them and
    reports them. The sessions the split gave must be the sessions the profile was fitted on: a split that hands over a different training
    set than the builder's `in_profile` window is a leak or a bug, not a result."""
    table = B.build_tables({sym: grids[sym]}, profile_end, tier, allow_leading_gap=True)
    train = table[table["day"].isin({str(d) for d in train_days})]
    if set(train["day"]) != set(table.loc[table["in_profile"], "day"]):
        raise S.LeakError(f"{sym}: the split's training sessions ({len(train)} rows) are not the sessions the profile was fitted on "
                          f"({int(table['in_profile'].sum())} rows)")
    te = table[table["day"].isin(test_days)].copy()
    S.check_test_mask([S.Fold(np.array([], dtype=int), np.flatnonzero(table["day"].isin(test_days).to_numpy()), "test")], ~table["in_profile"].to_numpy())
    fit = V.fit_c(train)
    te["F_C"] = V.predict_c(te, fit)
    return te, fit


def sessions_of(grids: dict, spec: dict) -> dict:
    """The `sessions` part of a study result: per symbol, the development and lock session counts and the first and last day."""
    dev_end = dt.date.fromisoformat(spec["dev"]["end"])
    lock_start = dt.date.fromisoformat(spec["lock"]["start"])
    out = {}
    for sym in spec["symbols"]:
        days = list(grids[sym][0])
        out[sym] = {"dev": sum(d <= dev_end for d in days), "lock": sum(d >= lock_start for d in days), "first": str(days[0]), "last": str(days[-1])}
    return out


def run_through_platform(grids: dict, spec: dict, tier: str = "T1") -> dict:
    """The study's `sessions`, `dev`, `selected` and `lock/tests` and `lock/profile`, computed through the platform. `grids`: {symbol:
    volstudy.grid(...)}."""
    from scipy.stats import norm
    dev_end = dt.date.fromisoformat(spec["dev"]["end"])
    lock_start = dt.date.fromisoformat(spec["lock"]["start"])
    rep = {"sessions": sessions_of(grids, spec), "dev": {}, "selected": {}, "lock": {"tests": {}, "profile": {}}}
    dev_scores: dict[str, dict] = {}
    for sym in spec["symbols"]:
        days = list(grids[sym][0])
        dev_days = [d for d in days if d <= dev_end]
        t0, t1 = _session_times(dev_days)
        edges = pd.to_datetime([f"{y}-01-01" for y in range(2013, dev_end.year + 2)]).tz_localize(IST)
        folds = S.walk_forward(t0, t1, edges)
        S.check_no_overlap(folds, t0, t1)
        for f in folds:
            train_days, test_days = [dev_days[i] for i in f.train], {str(dev_days[i]) for i in f.test}
            y = dev_days[int(f.test[0])].year                                   # the fold's year, from its own sessions (its label is in UTC)
            te, _ = _frame(grids, sym, max(train_days), train_days, test_days, tier)
            for hz, g in te.groupby("horizon"):
                sc = V.score(g)
                for c in V.CANDIDATES:
                    dev_scores.setdefault(hz, {}).setdefault(c, []).append(sc[c]["qlike"])
                    rep["dev"].setdefault(f"{sym} {hz}", {}).setdefault(c, {})[str(y)] = sc[c]
    for hz, per in dev_scores.items():
        means = {c: float(np.mean(v)) for c, v in per.items()}
        best = min(V.CANDIDATES, key=lambda c: (round(means[c], 12), V.CANDIDATES.index(c)))
        rep["selected"][hz] = {"candidate": best, "dev_mean_qlike": means}
    for sym in spec["symbols"]:
        days = list(grids[sym][0])
        train_days = [d for d in days if d <= dev_end]
        test_days = {str(d) for d in days if d >= lock_start}
        te, _ = _frame(grids, sym, dev_end, train_days, test_days, tier)
        for hz, g in te.groupby("horizon"):
            sel = rep["selected"][hz]["candidate"]
            sc = V.score(g)
            row = {"selected": sel, "scores": sc}
            if sel != "A_desk":
                diff = (V.daily_loss(g, "A_desk") - V.daily_loss(g, sel)).to_numpy()
                t = nw_t(diff)
                row.update({"dm_t": t, "p_one": float(norm.sf(t)), "days": int(len(diff)),
                            "qlike_gain_pct": float(100 * diff.mean() / V.daily_loss(g, "A_desk").mean())})
                row["passed"] = bool(row["p_one"] < 0.05)
            rep["lock"]["tests"][f"{sym} {hz}"] = row
        s = B.fit_profile(grids[sym], dev_end)                                  # the builder's fit itself, in the committed file's format
        rep["lock"]["profile"][sym] = {f"{9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}": round(float(v), 3)
                                       for i, v in enumerate(s) if i % 15 == 0 or i < 5 or i > 365}
    return rep


def _compared(result: dict) -> dict:
    """The parts of a study result the platform recomputes."""
    return {**{k: result[k] for k in COMPARED}, "lock": {"tests": result["lock"]["tests"], "profile": result["lock"]["profile"]}}


def reproduce_through_platform(dataset: Path, spec_path: Path, committed_path: Path, rtol: float = 1e-9, tier: str = "T1") -> Comparison:
    """Recompute the locked study through the platform and compare it with the committed result, number by number. Read-only: nothing is
    written, the lock is not opened (it is a recomputation, not a second evaluation: the spec fixed the data and the rule, and the committed file
    holds the one read)."""
    spec_path, committed_path = Path(spec_path), Path(committed_path)
    committed = json.loads(committed_path.read_text())
    h = spec_hash(spec_path)
    if h != committed.get("spec_sha256"):
        raise ReproductionRefused(f"{spec_path.name} no longer hashes to the spec the result was produced from ({h[:12]} ≠ {str(committed.get('spec_sha256'))[:12]})")
    if not committed.get("lock"):
        raise ReproductionRefused(f"{committed_path.name} has no opened lock to reproduce")
    if not 0 <= rtol <= 1e-6:
        raise ValueError(f"rtol {rtol:g} is outside 0 to 1e-06: a reproduction that needs a wider tolerance is not a reproduction")
    spec = json.loads(spec_path.read_text())
    grids = V.prepare(Path(dataset), spec["symbols"])
    mine = sessions_of(grids, spec)
    if mine != committed.get("sessions"):
        raise ReproductionRefused(f"{Path(dataset).name} is not the dataset the result was computed on: its sessions are {mine}, the result's are "
                                  f"{committed.get('sessions')} (nothing was computed, so no number from another dataset is printed)")
    fresh = run_through_platform(grids, spec, tier)
    cmp = compare_results(_compared(committed), _compared(fresh), rtol=rtol)
    gaps = B.leading_gap_sessions({s: grids[s] for s in spec["symbols"]})
    cmp.notes = [f"{sym}: {len(d)} sessions have no bar at the open and were back-filled from a later close, as in the locked run"
                 + (f" (first {d[0]}, last {d[-1]})" if d else "") for sym, d in gaps.items() if d]
    return cmp
