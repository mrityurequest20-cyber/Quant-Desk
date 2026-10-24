"""The baseline comparison (P0.4's deliverable, in the form P0.5's model card needs it).

A model is worth something only against a baseline on the same sessions. `oos_block` takes the per-session loss of the model and of its baseline (lower is
better), keeps the sessions both have a finite loss for, and returns the out-of-sample block of a model card: the two mean losses, their difference (model
minus baseline, so **negative is better**), a Newey-West interval for it, the level and method of that interval, and the number of sessions. The session is
the unit (docs/ML_PHASE0.md, rule 3): losses are per session, never per decision, and the sessions must be ISO dates so that their order is time.

The interval is the desk's own long-run-variance estimate (the same Bartlett-weighted sum as `autolearn.prereg.nw_t`, 5 lags by default) used with a normal
quantile; with fewer than `min_sessions` sessions, or a difference that never varies, there is no honest interval and the function refuses rather than guess.
Pure functions over plain dicts; nothing here reads the journal, the engine or any data.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
from scipy.stats import norm

NW_LAGS = 5
MIN_SESSIONS = 10


def _finite(x) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:
        return False


def newey_west(d, lags: int = NW_LAGS) -> tuple[float, float]:
    """(mean, standard error of the mean) of a series, with Bartlett-weighted autocovariances up to `lags` (the formula of `autolearn.prereg.nw_t`).
    The error is NaN when the long-run variance is not positive."""
    d = np.asarray(d, float)
    n = len(d)
    if n < 2:
        return (float(d.mean()) if n else float("nan")), float("nan")
    e = d - d.mean()
    var = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(d.mean()), (float(np.sqrt(var / n)) if var > 0 else float("nan"))


def _is_day(s) -> bool:
    try:
        date.fromisoformat(s)
        return isinstance(s, str) and len(s) == 10
    except (TypeError, ValueError):
        return False


def oos_block(model: dict, baseline: dict, metric: str, level: float = 0.9, lags: int = NW_LAGS, min_sessions: int = MIN_SESSIONS) -> dict:
    """The out-of-sample block of a model card from `{session: loss}` for the model and for its baseline (lower loss is better). Raises ValueError when
    there is no honest comparison: a bad key, too few sessions, a flat difference, or a level outside (0, 1)."""
    if not (isinstance(metric, str) and metric.strip()):
        raise ValueError("metric must name the loss")
    if not (_finite(level) and 0 < level < 1):
        raise ValueError("level must be between 0 and 1")
    if not (isinstance(lags, int) and not isinstance(lags, bool) and lags >= 0):
        raise ValueError("lags must be an integer >= 0")
    bad = sorted(str(k) for k in set(model) | set(baseline) if not _is_day(k))
    if bad:
        raise ValueError(f"sessions must be ISO dates (YYYY-MM-DD) so that their order is time: {bad[:3]}")
    both = sorted(set(model) & set(baseline))
    pairs = [(s, model[s], baseline[s]) for s in both if _finite(model[s]) and _finite(baseline[s])]
    n = len(pairs)
    if n < min_sessions:
        raise ValueError(f"only {n} sessions with a finite loss on both sides: at least {min_sessions} are needed for an interval")
    m = np.array([p[1] for p in pairs], float)
    b = np.array([p[2] for p in pairs], float)
    _, se = newey_west(m - b, lags)
    if not (se > 0):
        raise ValueError("the loss difference does not vary across sessions: there is no interval to give")
    mean_m, mean_b = float(m.mean()), float(b.mean())
    diff = mean_m - mean_b
    z = float(norm.ppf((1 + level) / 2))
    return {"metric": metric, "model": mean_m, "baseline": mean_b, "diff": diff, "interval": [diff - z * se, diff + z * se], "interval_level": float(level),
            "interval_method": f"Newey-West, {lags} lags, normal", "n_sessions": n, "t": diff / se,
            "sessions_dropped_non_finite": len(both) - n, "sessions_unmatched": len(set(model) ^ set(baseline))}
