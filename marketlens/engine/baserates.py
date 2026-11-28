"""Days like today: what followed past days in the same options state, against what options priced. Descriptive.

The state of a day is read from the options market alone: the 30-day IV's rank against the past year (cheap / normal /
dear), whether options were priced above the vol of the last month (the premium's sign), and whether the curve was
inverted (60-day IV below 30-day). Two ways of finding "days like today":

  * the same bucket: every past day with the same three readings;
  * nearest neighbours: the 40 past days closest to today on the continuous readings (IV rank, premium, curve slope,
    skew rank, the last week's vol against the last quarter's), at most one day from any 10-session stretch so one
    episode cannot fill the list.

What followed is measured against what was priced that day: the realised vol of the next 21 sessions as a share of
the 30-day IV, and whether the price ended those 21 sessions inside the IV's one-sigma range. The same numbers for
every day give the baseline. Uncertainty: a moving-block bootstrap (21-session blocks: overlapping windows are not
independent). Every result is also shown split before and after 2024 (in and out of sample): a pattern that holds in
one half only is reported as such. Nothing here is a signal; the page says so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .breadth import rank_1y

H = 21                       # the horizon: about a month of sessions
SPLIT = pd.Timestamp("2024-01-01")
K = 40
GAP = 10


def frame(df: pd.DataFrame) -> pd.DataFrame:
    """Per day: the state readings and what followed. df: the instrument's daily frame (close, iv30, rv21, rr25,
    term_60_30, rv5, rv63)."""
    d = pd.DataFrame(index=df.index)
    d["iv_rank"] = rank_1y(df["iv30"])
    d["prem"] = df["iv30"] - df["rv21"]
    d["slope"] = df["term_60_30"] if "term_60_30" in df else np.nan
    d["skew_rank"] = rank_1y(df["rr25"]) if "rr25" in df else np.nan
    d["wake"] = np.log(df["rv5"] / df["rv63"]) if {"rv5", "rv63"} <= set(df.columns) else np.nan
    r = np.log(df["close"]).diff()
    fwd_rv = r.rolling(H, min_periods=int(H * 0.8)).std().shift(-H) * np.sqrt(252)
    d["ratio"] = fwd_rv / df["iv30"]
    move = np.log(df["close"].shift(-H) / df["close"]).abs()
    d["inside"] = (move <= df["iv30"] * np.sqrt(H / 252)).where(move.notna())
    d["bucket"] = (pd.cut(d["iv_rank"], [-0.01, 0.2, 0.8, 1.01], labels=["cheap", "normal", "dear"]).astype(str)
                   + "|" + np.where(d["prem"] > 0, "premium", "discount")
                   + "|" + np.where(d["slope"] < 0, "inverted", np.where(d["slope"].notna(), "upward", "n/a")))
    d.loc[d["iv_rank"].isna() | d["prem"].isna(), "bucket"] = None
    return d


def _boot(ratio: np.ndarray, inside: np.ndarray, idx: np.ndarray, n_days: int, B: int = 1000, seed: int = 0):
    """Moving-block bootstrap of the medians of ratio and the mean of inside over the selected days. idx: positions
    of the selected days on the full calendar, so blocks follow time."""
    rng = np.random.default_rng(seed)
    if len(idx) == 0:
        return None
    blocks = idx // H
    ub = np.unique(blocks)
    by = {b: np.where(blocks == b)[0] for b in ub}
    med, ins = [], []
    for _ in range(B):
        pick = np.concatenate([by[b] for b in rng.choice(ub, len(ub), replace=True)])
        med.append(np.median(ratio[pick]))
        ins.append(np.nanmean(inside[pick]))
    return [float(np.percentile(med, 5)), float(np.percentile(med, 95))], [float(np.percentile(ins, 5)), float(np.percentile(ins, 95))]


def summarise(d: pd.DataFrame, sel: pd.Series, B: int = 1000) -> dict | None:
    """Median ratio and inside share over the selected days with known outcomes, with 90% block-bootstrap intervals,
    split before and after SPLIT."""
    ok = d["ratio"].notna() & d["inside"].notna()
    s = sel & ok
    if s.sum() < 15:
        return None
    pos = np.arange(len(d))[s.to_numpy()]
    ratio = d["ratio"].to_numpy()[pos]
    inside = d["inside"].to_numpy(dtype=float)[pos]
    ci = _boot(ratio, inside, pos, len(d), B)
    early, late = s & (d.index < SPLIT), s & (d.index >= SPLIT)
    part = lambda m: ({"n": int(m.sum()), "ratio": float(d.loc[m, "ratio"].median()), "inside": float(d.loc[m, "inside"].mean())}
                      if m.sum() >= 10 else None)
    return {"n": int(s.sum()), "episodes": int(len(np.unique(pos // H))), "ratio": float(np.median(ratio)), "inside": float(np.mean(inside)),
            "ratio_ci": ci[0], "inside_ci": ci[1], "before_2024": part(early), "from_2024": part(late),
            "since": str(d.index[pos[0]].date())}


def neighbours(d: pd.DataFrame, k: int = K, gap: int = GAP) -> pd.Series:
    """The k past days nearest today on the standardised readings, at most one per `gap`-session stretch, outcomes
    known (more than H sessions back). A boolean mask on d's index."""
    cols = [c for c in ("iv_rank", "prem", "slope", "skew_rank", "wake") if d[c].notna().sum() > 100]
    x = d[cols]
    today = x.iloc[-1]
    if today.isna().any():
        cols = [c for c in cols if pd.notna(today[c])]
        x, today = d[cols], d[cols].iloc[-1]
    z = (x - x.mean()) / x.std()
    dist = np.sqrt(((z - z.iloc[-1]) ** 2).sum(axis=1, min_count=len(cols)))
    cand = dist.iloc[:-H - 1].dropna().sort_values()
    taken, mask = [], pd.Series(False, index=d.index)
    loc = {t: i for i, t in enumerate(d.index)}
    for t in cand.index:
        i = loc[t]
        if all(abs(i - j) >= gap for j in taken):
            taken.append(i)
            mask.iloc[i] = True
            if len(taken) >= k:
                break
    return mask


def lab(df: pd.DataFrame, B: int = 1000) -> dict | None:
    need = {"close", "iv30", "rv21"}
    if not need <= set(df.columns) or df["iv30"].notna().sum() < 300:
        return None
    d = frame(df)
    today = d.iloc[-1]
    if not isinstance(today["bucket"], str):
        return None
    base = summarise(d, pd.Series(True, index=d.index), B)
    same = summarise(d, d["bucket"] == today["bucket"], B)
    nn_mask = neighbours(d)
    nn = summarise(d, nn_mask, B)
    iv, prem, slope = today["bucket"].split("|")

    def differs(x):
        if not (x and base):
            return None
        lo, hi = x["ratio_ci"]
        return "higher" if lo > base["ratio"] else "lower" if hi < base["ratio"] else "same"
    return {"state": {"iv": iv, "premium": prem, "curve": slope, "iv_rank": float(today["iv_rank"]), "prem": float(today["prem"]),
                      "slope": None if pd.isna(today["slope"]) else float(today["slope"])},
            "horizon": H, "baseline": base, "same_bucket": same, "neighbours": nn,
            "verdict": {"same_bucket": differs(same), "neighbours": differs(nn)},
            "neighbour_days": [str(t.date()) for t in d.index[nn_mask.to_numpy()]][:40]}
