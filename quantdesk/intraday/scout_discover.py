"""The scout's leaderboard and rule miner (shadow, offline): which strategy x exit policy has a right tail worth testing, and what new rules does a search
find that nobody wrote down? docs/ASYMMETRY_SCOUT.md.

EXPLORATORY and built to resist fooling itself:
  * R is capped at CAP_R before any average, and the median and the share of the profit that comes from the best 1% of trades are shown;
  * the leaderboard has len(strategies) x len(policies) cells: a cell must clear a Bonferroni z, be positive on both slices, and is only ever a HYPOTHESIS;
  * the miner counts every rule it tries (the trial ledger) and runs the SAME search on the same data with the outcomes circularly shifted inside each session
    (the null): a real finding has to beat what the search finds in noise, not zero.
The null is a circular shift inside each session: it keeps each session's outcomes and breaks their link to WITHIN-session features, so it tests within-session
information only. Day-level features (gap, opening-range width, weekday) stay tied to the session's outcomes in the shifted data, so for a rule built on them the
null is conservative, and its share is not a p-value for that rule. With n nulls the smallest share is 1/(n+1). Sessions are clustered by DAY (NIFTY and BANKNIFTY of one
day are near-duplicates, so clustering by symbol and day would overstate t).
Fitted on the early years, judged on the later years of the OPEN window; the sealed sessions are untouched (scout.SEAL_FROM). Never evidence for a gate, a promotion or a profit claim."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .scout import COST_R, EVIDENCE, FEATURES, NOT_FOR, POLICY_COLUMNS, assert_open

TRAIN_TO = pd.Timestamp("2020-12-31").date()
CAP_R = 10.0
MIN_VALID_N = 500


def net(x: pd.Series) -> pd.Series:
    """R capped at CAP_R, less the assumed all-in cost."""
    return x.clip(upper=CAP_R) - COST_R


def cluster_mean(y: np.ndarray, gid: np.ndarray) -> dict:
    """Mean with a standard error clustered by session."""
    n = len(y)
    if n == 0:
        return {"n": 0, "sessions": 0, "mean": np.nan, "se": np.nan, "t": np.nan}
    m = float(y.mean())
    s = np.bincount(gid, weights=y - m)
    se = float(np.sqrt((s ** 2).sum()) / n)
    return {"n": n, "sessions": int((np.bincount(gid) > 0).sum()), "mean": m, "se": se, "t": m / se if se > 0 else np.nan}


def _gid(df: pd.DataFrame) -> np.ndarray:
    return pd.factorize(df["day"].astype(str))[0]            # by DAY: the two indices of one day are one market, not two samples


def leaderboard(trades: pd.DataFrame, prior_cells: int = 0) -> pd.DataFrame:
    """Every strategy under every exit policy: train and valid mean net R (capped), t, median, the share of the profit from the best 1%, and the Bonferroni test.
    `clears_bar` is a HYPOTHESIS flag, never a finding. It is given for two families: this run's cells, and this run's plus `prior_cells` (the cells of every earlier
    recorded run: the later-years slice has been looked at by all of them, so it is not a holdout any more)."""
    from scipy.stats import norm
    names = sorted(trades["strategy"].unique())
    z_need = float(norm.isf(0.025 / max(1, len(names) * len(POLICY_COLUMNS))))
    z_all = float(norm.isf(0.025 / max(1, len(names) * len(POLICY_COLUMNS) + int(prior_cells))))
    rows = []
    for name in names:
        g = trades[trades["strategy"] == name]
        for pol, col in POLICY_COLUMNS.items():
            r = {}
            for tag, part in (("train", g[g["day"] <= TRAIN_TO]), ("valid", g[g["day"] > TRAIN_TO])):
                y = net(part[col]).to_numpy()
                r[tag] = cluster_mean(y, _gid(part)) if len(part) else cluster_mean(np.array([]), np.array([], dtype=int))
                if tag == "valid":
                    pos = np.sort(y[y > 0])[::-1]
                    r["median_valid"] = float(np.median(y)) if len(y) else np.nan
                    r["top1pct_share"] = float(pos[: max(1, int(0.01 * len(y)))].sum() / pos.sum()) if len(pos) and len(y) else np.nan
                    r["win3_valid"] = float((part[col] >= 3).mean()) if len(part) else np.nan
            base = (r["train"]["mean"] > 0) and (r["valid"]["mean"] > 0) and (r["valid"]["n"] >= MIN_VALID_N)
            ok, ok_all = base and (r["valid"]["t"] >= z_need), base and (r["valid"]["t"] >= z_all)
            rows.append({"strategy": name, "policy": pol, "n_train": r["train"]["n"], "mean_train": r["train"]["mean"], "t_train": r["train"]["t"],
                         "n_valid": r["valid"]["n"], "sessions_valid": r["valid"]["sessions"], "mean_valid": r["valid"]["mean"], "t_valid": r["valid"]["t"],
                         "median_valid": r["median_valid"], "win3_valid": r["win3_valid"], "top1pct_share": r["top1pct_share"],
                         "cells": len(names) * len(POLICY_COLUMNS), "z_needed": z_need, "prior_cells": int(prior_cells), "z_needed_all_runs": z_all,
                         "clears_bar": bool(ok), "clears_bar_all_runs": bool(ok_all)})
    return pd.DataFrame(rows).sort_values("mean_valid", ascending=False)


# ---------------------------------------------------------------------------------------- the miner
CATEGORICAL = {"weekday", "n_obst_3r", "open_air", "broke_or", "broke_pd"}


def _pool(df: pd.DataFrame, train: np.ndarray, features: list[str]) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Named conditions (a feature above/below a train quantile, or equal to a value) as boolean columns, and the feature index of each."""
    names, cols, owner = [], [], []
    for fi, f in enumerate(features):
        x = df[f].to_numpy(dtype=float)
        xt = x[train]
        xt = xt[~np.isnan(xt)]
        if not len(xt):
            continue
        if f in CATEGORICAL or len(np.unique(xt)) <= 6:
            for v in np.unique(xt):
                names.append(f"{f}=={v:g}"), cols.append(x == v), owner.append(fi)
        else:
            for q in (0.2, 0.4, 0.6, 0.8):
                t = float(np.quantile(xt, q))
                names.append(f"{f}>{t:.3g}"), cols.append(x > t), owner.append(fi)
                names.append(f"{f}<={t:.3g}"), cols.append(x <= t), owner.append(fi)
    if "strategy" in df:
        for s in sorted(df["strategy"].unique()):
            names.append(f"strategy=={s}"), cols.append((df["strategy"] == s).to_numpy()), owner.append(len(features))
    return names, np.array(cols, dtype=bool), np.array(owner)


def _shift_within_sessions(y: np.ndarray, gid: np.ndarray, rng) -> np.ndarray:
    """The null: each session's outcomes rotated by a random offset, so its distribution and any day-level effect stay but the link to the features goes."""
    order = np.argsort(gid, kind="stable")
    g = gid[order]
    starts = np.r_[0, np.flatnonzero(np.diff(g)) + 1]
    sizes = np.diff(np.r_[starts, len(g)])
    shift = np.repeat(rng.integers(1, np.maximum(sizes, 2)), sizes)
    start_row, size_row = np.repeat(starts, sizes), np.repeat(sizes, sizes)
    pos = np.arange(len(g)) - start_row
    out = np.empty_like(y)
    out[order] = y[order][start_row + (pos + shift) % size_row]
    return out


def _search(Mtr, owner, ytr, n_trials, min_support, rng) -> list[tuple[float, tuple, int]]:
    found, seen = [], set()
    nc = Mtr.shape[0]
    for _ in range(n_trials):
        k = int(rng.choice([1, 2, 3], p=[0.15, 0.5, 0.35]))
        combo = tuple(sorted(int(c) for c in rng.choice(nc, size=k, replace=False)))
        if len({owner[c] for c in combo}) < k or combo in seen:      # two conditions on one feature, or this rule again in another order: skip (still a trial)
            continue
        seen.add(combo)
        m = Mtr[combo[0]].copy()
        for c in combo[1:]:
            m &= Mtr[c]
        n = int(m.sum())
        if n >= min_support:
            found.append((float(ytr[m].mean()), combo, n))
    found.sort(key=lambda r: -r[0])
    return found


def _judge(found, top_k, Mva, yva, gva) -> list[dict]:
    out = []
    for score, combo, n in found[:top_k]:
        m = Mva[combo[0]].copy()
        for c in combo[1:]:
            m &= Mva[c]
        s = cluster_mean(yva[m], gva[m]) if m.any() else cluster_mean(np.array([]), np.array([], dtype=int))
        out.append({"combo": combo, "mean_train": score, "n_train": n, "n_valid": s["n"], "mean_valid": s["mean"], "t_valid": s["t"]})
    return out


def mine(df: pd.DataFrame, col: str = "r_trail", features: list[str] | None = None, seed: int = 11, n_trials: int = 15000, top_k: int = 25,
         min_support: int = 3000, n_null: int = 8, say=print) -> dict:
    """Search random conjunctions of 1 to 3 conditions for the best mean net R on the early years, judge the best on the later years, and compare the
    best later-years result with what the identical search finds when the outcomes are shifted inside each session (n_null times)."""
    features = list(features or FEATURES)
    df = df.sort_values(["day", "symbol"], kind="stable").reset_index(drop=True)
    tr = (df["day"] <= TRAIN_TO).to_numpy()
    names, M, owner = _pool(df, tr, features)
    y = net(df[col]).to_numpy(dtype=float)
    gid = _gid(df)
    Mtr, Mva = M[:, tr], M[:, ~tr]
    gva = gid[~tr]

    def statistic(yy, rng):
        found = _search(Mtr, owner, yy[tr], n_trials, min_support, rng)
        judged = _judge(found, top_k, Mva, yy[~tr], gva)
        ok = [j for j in judged if j["n_valid"] >= MIN_VALID_N]
        return judged, (max(j["mean_valid"] for j in ok) if ok else np.nan), len(found)

    judged, best, n_ok = statistic(y, np.random.default_rng(seed))
    nulls = []
    for i in range(n_null):
        rng = np.random.default_rng(seed + 1000 + i)
        _, b, _ = statistic(_shift_within_sessions(y, gid, rng), rng)
        nulls.append(b)
        say(f"    null {i + 1}/{n_null}: best later-years mean {b:+.3f}")
    nl = np.array([x for x in nulls if x == x])
    rules = [{**j, "rule": " & ".join(names[c] for c in j["combo"])} for j in judged]
    for r in rules:
        r.pop("combo")
    return {"outcome": col, "ledger": {"trials": n_trials, "conditions": len(names), "max_depth": 3, "min_support": min_support, "top_k": top_k,
                                         "seed": seed, "rules_clearing_support": n_ok, "nulls": n_null, "cap_r": CAP_R, "cost_r": COST_R},
            "best_valid_mean": best, "null_best_valid_means": [float(x) for x in nulls],
            "p_vs_null": float((1 + (nl >= best).sum()) / (1 + len(nl))) if len(nl) and best == best else np.nan, "p_resolution": 1 / (1 + len(nl)),
            "null_note": "a circular shift inside each session: it tests within-session information only; day-level features stay tied to the outcomes, so p_vs_null is "
                         "NOT a p-value for a rule built on them, and its smallest value is p_resolution", "rules": rules}


def write_lab_report(out: Path, trades: pd.DataFrame, grid: pd.DataFrame | None, run_mining: bool = True, say=print, prior_cells: int = 0, **mine_kw) -> Path:
    out = Path(out)
    assert_open(trades, "the trades")                         # the sealed sessions are refused wherever a table comes from
    assert_open(grid, "the grid")
    L = [f"# Scout strategy library and rule miner (exploratory, {EVIDENCE})", "", f"**Not for:** {NOT_FOR}", "",
         f"{len(trades):,} trades from {trades['strategy'].nunique()} strategies over {trades[['symbol', 'day']].drop_duplicates().shape[0]} symbol-sessions "
         f"({trades['day'].min()} to {trades['day'].max()}). Net R is capped at {CAP_R:g} and less {COST_R} per trade (assumed). Fitted to {TRAIN_TO}, judged after it.", ""]
    idx = trades[trades["kind"] == "index"]
    if len(idx) and (idx["day"] > TRAIN_TO).any() and (idx["day"] <= TRAIN_TO).any():
        lb = leaderboard(idx, prior_cells)
        lb.to_csv(out / "leaderboard.csv", index=False)
        L += ["## 1. Strategy x exit policy (index)", "",
              f"{lb['cells'].iloc[0]} cells in this run, so a cell clears the bar at t >= {lb['z_needed'].iloc[0]:.2f} on the later years (and "
              + (f"t >= {lb['z_needed_all_runs'].iloc[0]:.2f} counting the {int(lb['prior_cells'].iloc[0])} cells of earlier recorded runs)" if int(lb['prior_cells'].iloc[0]) else "the all-runs family is THIS RUN ONLY: no earlier recorded run was counted)")
              + f", a positive mean on both slices and {MIN_VALID_N}+ trades. "
              f"Cells clearing the bar: **{int(lb['clears_bar'].sum())}** (this run's family), **{int(lb['clears_bar_all_runs'].sum())}** (all runs' family). "
              "Each one is a HYPOTHESIS for a pre-registered test on sealed data, not a finding: the later-years slice has been looked at by every table here. Best by later-years mean:", "",
              "| strategy | policy | n valid | mean valid | t valid | median valid | R>=3 share | best 1% share of profit | mean train | clears bar (hypothesis) |", "|---|---|---|---|---|---|---|---|---|---|"]
        for r in lb.head(12).itertuples():
            L.append(f"| {r.strategy} | {r.policy} | {r.n_valid:,} | {r.mean_valid:+.3f} | {r.t_valid:.2f} | {r.median_valid:+.2f} | {r.win3_valid:.3f} | {r.top1pct_share:.2f} | {r.mean_train:+.3f} | {'yes' if r.clears_bar else 'no'} |")
        by_pol = lb.groupby("policy")[["mean_valid"]].mean().round(3)
        L += ["", "Mean of the later-years means over all strategies, by exit policy: " + ", ".join(f"{k} {v:+.3f}" for k, v in by_pol["mean_valid"].items()) + "."]
    stk = trades[trades["kind"] == "stock"]
    if len(stk):
        L += ["", "## 2. Stocks (a few sessions: descriptive only)", "",
              f"{stk['symbol'].nunique()} stocks, {len(stk):,} trades; mean net R by exit policy: "
              + ", ".join(f"{p} {net(stk[c]).mean():+.3f}" for p, c in POLICY_COLUMNS.items()) + "."]
    if run_mining:
        for label, frame in (("grid (any minute, any direction, one uniform stop)", grid), ("library trades (strategy flags included)", idx)):
            if frame is None or not len(frame) or not (frame["day"] > TRAIN_TO).any():
                continue
            say(f"mining on {label}")
            res = mine(frame[frame["kind"] == "index"], say=say, **mine_kw)
            tag = "grid" if frame is grid else "library"
            (out / f"mined_{tag}.json").write_text(json.dumps(res, indent=1, default=str))
            lg = res["ledger"]
            L += ["", f"## 3. New rules found by search on the {label}", "",
                  f"Outcome `{res['outcome']}`. **Trials: {lg['trials']:,}** random conjunctions of 1 to 3 of {lg['conditions']} conditions; {lg['rules_clearing_support']:,} had "
                  f"{lg['min_support']:,}+ early-years rows; the best {lg['top_k']} by early-years mean were judged on the later years. Best later-years mean: "
                  f"**{res['best_valid_mean']:+.3f}**. The same search on outcomes shifted inside each session ({lg['nulls']} times) found best means of "
                  + ", ".join(f"{x:+.3f}" for x in res["null_best_valid_means"]) + f". Share of nulls at least as good: **{res['p_vs_null']:.2f}** (smallest possible "
                  f"{res['p_resolution']:.2f}; the shift tests within-session information only, so this is not a p-value for a rule built on day-level features). "
                  "Every rule below is a hypothesis for a pre-registered test, not a finding.", "",
                  "| rule | n train | mean train | n valid | mean valid | t valid |", "|---|---|---|---|---|---|"]
            for r in res["rules"][:8]:
                L.append(f"| {r['rule']} | {r['n_train']:,} | {r['mean_train']:+.3f} | {r['n_valid']:,} | {r['mean_valid']:+.3f} | {r['t_valid']:.2f} |")
    p = out / "report_lab.md"
    p.write_text("\n".join(L) + "\n")
    say(f"wrote {p}")
    return p
