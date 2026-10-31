"""The scout's read-out (shadow, offline): base rates, where the lift is, and how the desk's own entries compare. docs/ASYMMETRY_SCOUT.md.

EXPLORATORY. It is run on the open sessions only (the module that makes the candidates refuses the sealed ones). Every table is a hypothesis for a
later pre-registered test, never a finding: ~190 feature bins are looked at, so some pass by chance. Lift is against the POOLED EMPIRICAL rate (the
session is finite, so 1 / (k + 1) is an upper bound). Standard errors are clustered by session.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .scout import COST_R, EVIDENCE, FEATURES, KS, NOT_FOR

TRAIN_TO = dt.date(2020, 12, 31)        # index discovery: fit/bin edges on <= 2020, look again on 2021-2022
CATEGORICAL = {"weekday", "n_obst_3r", "open_air", "broke_or", "broke_pd"}
MIN_TRAIN_N, MIN_VALID_N = 2000, 500
LIFT_TRAIN, LIFT_VALID = 1.30, 1.15
DESK_BEFORE_MIN, DESK_AFTER_MIN = 15, 5   # a desk setup counts as 'near' a candidate if it fired this long before or after it


def rate(df: pd.DataFrame, col: str) -> dict:
    """Mean of a 0/1 column with a session-clustered standard error."""
    n = len(df)
    if n == 0:
        return {"n": 0, "sessions": 0, "rate": np.nan, "se": np.nan}
    y = df[col].to_numpy(dtype=float)
    p = y.mean()
    key = df["symbol"].astype(str) + "|" + df["day"].astype(str)
    resid = pd.Series(y - p).groupby(key.to_numpy()).sum()
    return {"n": n, "sessions": int(resid.size), "rate": float(p), "se": float(np.sqrt((resid ** 2).sum()) / n)}


def base_rates(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (sym, kind), g in df.groupby(["symbol", "kind"]):
        for k in KS:
            r = rate(g, f"reach_{k}")
            need = (1 + COST_R) / (k + 1)
            rows.append({"symbol": sym, "kind": kind, "k": k, **r, "random_walk": 1 / (k + 1), "break_even": need,
                         "net_R": r["rate"] * k - (1 - r["rate"]) - COST_R})
    return pd.DataFrame(rows)


def _bins(train: pd.Series, col: str) -> np.ndarray | None:
    if col in CATEGORICAL or train.nunique() <= 6:
        return None
    return np.unique(np.nanquantile(train, [0.2, 0.4, 0.6, 0.8]))


def _label(x: pd.Series, edges: np.ndarray | None) -> pd.Series:
    if edges is None:
        return x.astype("float").round(3).astype(str)
    return pd.Series(np.searchsorted(edges, x.to_numpy(dtype=float), side="right"), index=x.index).map(lambda b: f"q{b + 1}")


def feature_tables(df: pd.DataFrame, k: int) -> pd.DataFrame:
    """Rate of reach_k in each bin of each feature, on <= 2020 and again on 2021-2022, with the lift over the pooled rate of each period."""
    lab = f"reach_{k}"
    tr, va = df[df["day"] <= TRAIN_TO], df[df["day"] > TRAIN_TO]
    base_tr, base_va = tr[lab].mean(), va[lab].mean()
    out = []
    for col in FEATURES:
        edges = _bins(tr[col].dropna(), col)
        for part, base, tag in ((tr, base_tr, "train"), (va, base_va, "valid")):
            sub = part.dropna(subset=[col])
            b = _label(sub[col], edges)
            for name, g in sub.groupby(b):
                r = rate(g, lab)
                out.append({"feature": col, "bin": name, "part": tag, "n": r["n"], "sessions": r["sessions"], "rate": r["rate"],
                            "se": r["se"], "lift": r["rate"] / base if base > 0 else np.nan})
    t = pd.DataFrame(out)
    w = t.pivot_table(index=["feature", "bin"], columns="part", values=["n", "rate", "lift"], aggfunc="first")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    w = w.reset_index()
    w["k"] = k
    w["worth_testing"] = ((w["lift_train"] >= LIFT_TRAIN) & (w["lift_valid"] >= LIFT_VALID)
                          & (w["n_train"] >= MIN_TRAIN_N) & (w["n_valid"] >= MIN_VALID_N))
    return w.sort_values("lift_valid", ascending=False)


def model_check(df: pd.DataFrame, k: int, seed: int = 7) -> dict:
    """A small boosted model fitted on <= 2020 and judged on 2021-2022: does the feature set carry information about reaching k x risk?"""
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score
    lab = f"reach_{k}"
    tr, va = df[df["day"] <= TRAIN_TO], df[df["day"] > TRAIN_TO]
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=150, min_samples_leaf=500, random_state=seed)
    clf.fit(tr[list(FEATURES)], tr[lab])
    p = clf.predict_proba(va[list(FEATURES)])[:, 1]
    y = va[lab].to_numpy()
    out = {"k": k, "auc_valid": float(roc_auc_score(y, p)), "base_valid": float(y.mean()), "n_valid": int(len(va))}
    order = np.argsort(-p)
    for frac in (0.05, 0.10, 0.25):
        top = order[: max(1, int(len(p) * frac))]
        sub = va.iloc[top]
        r = rate(sub, lab)
        out[f"top{int(frac * 100)}"] = {"n": r["n"], "rate": r["rate"], "se": r["se"], "lift": r["rate"] / y.mean(),
                                       "net_R": r["rate"] * k - (1 - r["rate"]) - COST_R}
    sample = va.sample(min(60000, len(va)), random_state=seed)
    imp = permutation_importance(clf, sample[list(FEATURES)], sample[lab], n_repeats=3, random_state=seed, scoring="roc_auc")
    out["importance"] = sorted(({"feature": f, "drop_in_auc": float(m)} for f, m in zip(FEATURES, imp.importances_mean)),
                               key=lambda r: -r["drop_in_auc"])[:8]
    return out


def desk_comparison(df: pd.DataFrame, lab_rows: Path) -> dict:
    """Does a candidate near a desk setup reach k x risk more often than one with none? Uses ONLY the lab rows' day, time, symbol, direction and setup
    (never their outcomes), and only sessions that are in this (open) window."""
    lab = pd.read_parquet(lab_rows, columns=["day", "ts", "symbol", "direction", "setup", "idea_first"])
    lab["day"] = pd.to_datetime(lab["day"]).dt.date
    lab = lab[lab["idea_first"]]
    sessions = set(zip(df["symbol"], df["day"]))
    lab = lab[[(s, d) in sessions for s, d in zip(lab["symbol"], lab["day"])]]
    if lab.empty:
        return {"note": "no lab rows in the open window"}
    lab["ts"] = pd.to_datetime(lab["ts"])
    cand = df[df.set_index(["symbol", "day"]).index.isin(set(zip(lab["symbol"], lab["day"])))].copy()
    near = np.zeros(len(cand), dtype=bool)
    setups = np.full(len(cand), "", dtype=object)
    by = {k: g for k, g in lab.groupby(["symbol", "day", "direction"])}
    for n, (sym, day, d, ts) in enumerate(zip(cand["symbol"], cand["day"], cand["direction"], cand["ts"])):
        g = by.get((sym, day, d))
        if g is None:
            continue
        dm = (g["ts"] - ts).dt.total_seconds().to_numpy() / 60
        hit = (dm >= -DESK_BEFORE_MIN) & (dm <= DESK_AFTER_MIN)
        if hit.any():
            near[n] = True
            setups[n] = g["setup"].to_numpy()[hit][0]
    cand["desk_near"], cand["desk_setup"] = near, setups
    res = {"sessions": int(cand[["symbol", "day"]].drop_duplicates().shape[0]), "candidates": int(len(cand)),
           "share_with_desk_setup": float(near.mean()), "by_k": {}}
    for k in KS:
        lab_k = f"reach_{k}"
        res["by_k"][k] = {"rate_near_desk": rate(cand[cand["desk_near"]], lab_k), "rate_no_desk": rate(cand[~cand["desk_near"]], lab_k),
                          "share_of_reach_with_desk_setup": float(cand[cand[lab_k]]["desk_near"].mean()) if cand[lab_k].any() else np.nan}
    res["by_setup"] = {s: {"n": int(len(g)), "reach_3": float(g["reach_3"].mean()), "reach_4": float(g["reach_4"].mean())}
                       for s, g in cand[cand["desk_near"]].groupby("desk_setup")}
    return res


def _fmt(x, nd=3):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def write_report(out: Path, lab_rows: Path | None = None, say=print) -> Path:
    out = Path(out)
    df = pd.read_parquet(out / "scout_candidates.parquet")
    man = json.loads((out / "manifest.json").read_text())
    idx = df[df["kind"] == "index"]
    stk = df[df["kind"] == "stock"]
    L = [f"# Asymmetry scout read-out (exploratory, {EVIDENCE})", "",
         f"**Not for:** {NOT_FOR}", "",
         f"Window {man['first']} to {man['last']} ({man['sessions']} symbol-sessions, {man['rows']:,} candidates). Sessions from {man['sealed_from']} are sealed. "
         f"Cost assumed {COST_R}R per round trip (an assumption, not measured). Lift is against the pooled empirical rate.", ""]
    br = base_rates(df)
    L += ["## 1. Base rates", "", "| symbol | k | n | sessions | rate | se | random walk | break-even | net R per trade |", "|---|---|---|---|---|---|---|---|---|"]
    for r in br.itertuples():
        L.append(f"| {r.symbol} | {r.k} | {r.n:,} | {r.sessions} | {_fmt(r.rate)} | {_fmt(r.se, 4)} | {_fmt(r.random_walk)} | {_fmt(r.break_even)} | {_fmt(r.net_R)} |")
    tabs = {}
    if len(idx) and (idx["day"] > TRAIN_TO).any() and (idx["day"] <= TRAIN_TO).any():
        for k in (3, 4):
            t = feature_tables(idx, k)
            tabs[k] = t
            t.to_csv(out / f"feature_bins_reach_{k}.csv", index=False)
            top = t[t["worth_testing"]].head(12)
            L += ["", f"## 2.{k}  Feature bins whose lift held up (reach_{k}; index; train <= 2020, valid 2021-2022)", "",
                  "Hypotheses only. A bin is listed if lift >= 1.30 on train and >= 1.15 on valid with enough rows.", "",
                  "| feature | bin | n train | rate train | lift train | n valid | rate valid | lift valid |", "|---|---|---|---|---|---|---|---|"]
            for r in top.itertuples():
                L.append(f"| {r.feature} | {r.bin} | {int(r.n_train):,} | {_fmt(r.rate_train)} | {_fmt(r.lift_train, 2)} | {int(r.n_valid):,} | {_fmt(r.rate_valid)} | {_fmt(r.lift_valid, 2)} |")
            if top.empty:
                L.append("| (no bin passed) | | | | | | | |")
        L += ["", "## 3. Does the feature set carry information? (boosted model, train <= 2020, judged on 2021-2022)", ""]
        try:
            import sklearn  # noqa: F401
            have_sklearn = True
        except ImportError:                                  # scikit-learn is in requirements-ml.txt, not the base install: say so, never skip silently
            have_sklearn = False
            L += ["(skipped: scikit-learn is not installed; `pip install -r requirements-ml.txt`)", ""]
        for k in (3, 4) if have_sklearn else ():
            m = model_check(idx, k)
            L += [f"**reach_{k}**: AUC {m['auc_valid']:.3f} on {m['n_valid']:,} rows, base rate {m['base_valid']:.3f}. "
                  + "; ".join(f"top {p}%: rate {m[f'top{p}']['rate']:.3f} (lift {m[f'top{p}']['lift']:.2f}, net R {m[f'top{p}']['net_R']:+.2f}, n {m[f'top{p}']['n']:,})" for p in (5, 10, 25)),
                  "  Largest features by permutation: " + ", ".join(f"{i['feature']} ({i['drop_in_auc']:.4f})" for i in m["importance"][:6]), ""]
            (out / f"model_reach_{k}.json").write_text(json.dumps(m, indent=1))
    if len(stk):
        L += ["## 4. Stocks (a few sessions: descriptive only, no rule is tuned on them)", "",
              f"{stk['symbol'].nunique()} stocks, {stk[['symbol', 'day']].drop_duplicates().shape[0]} stock-sessions, "
              + ", ".join(f"reach_{k} {stk[f'reach_{k}'].mean():.3f}" for k in KS) + "."]
    if lab_rows is not None and len(idx):
        dc = desk_comparison(idx, Path(lab_rows))
        (out / "desk_comparison.json").write_text(json.dumps(dc, indent=1, default=str))
        L += ["", "## 5. The desk's own entries beside the candidates", ""]
        if "by_k" in dc:
            L += [f"{dc['candidates']:,} candidates in {dc['sessions']} sessions the lab also replayed; {dc['share_with_desk_setup']:.1%} have a desk setup armed within "
                  f"{DESK_BEFORE_MIN} min before or {DESK_AFTER_MIN} after, same direction.", "",
                  "| k | rate near a desk setup | rate with none | share of all reaches that had a desk setup |", "|---|---|---|---|"]
            for k, v in dc["by_k"].items():
                L.append(f"| {k} | {_fmt(v['rate_near_desk']['rate'])} (n {v['rate_near_desk']['n']:,}) | {_fmt(v['rate_no_desk']['rate'])} | {_fmt(v['share_of_reach_with_desk_setup'])} |")
        else:
            L.append(dc["note"])
    p = out / "report.md"
    p.write_text("\n".join(L) + "\n")
    say(f"wrote {p}")
    return p
