"""Direction research on the external index minutes (data/external_aeron.py): 30m / 60m / 120m / close.

The question: do the desk's 5-minute features predict the index's direction over each horizon, out of sample? It asks
this over years of sessions instead of Yahoo's 55 days. This is direction research and development-fold testing
only (the dataset's ALLOWED_USES):
- there are no option prices here, so nothing in this report speaks to option profitability;
- nothing here can qualify a strategy, change a DTE or horizon policy, advance the paper gate or promote a model;
- every result carries the dataset's evidence status (`external_unverified` until its independent check passes).

Method: the one baseline (the desk's DirectionModel logistic, Platt calibration and abstention, models.Pipeline("baseline")).
Each horizon gets its own label and its own model, on a day-grouped expanding walk-forward:
- 5 folds after `min_train_days`;
- training rows purged when their label is still open at the block's start;
- an embargo of the horizon.
Reported per horizon and symbol:
- AUC and Brier skill out of sample;
- rank IC of P(up) with the forward return;
- hit rate when the model takes a side, and abstention;
- the mean absolute move (the size any instrument would have to beat);
- the futures-proxy net bps per signal after round-trip costs, for scale (not an option result).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ..data import external_aeron as X
from .evaluate import CostModel
from .features import FEATURES
from .models import Pipeline
from .store import write_json
from .validation import WalkForwardConfig, folds, split

HORIZON_MIN = {"30m": 30, "60m": 60, "120m": 120, "close": 375}


def _auc(y, p) -> float | None:
    y, p = np.asarray(y, float), np.asarray(p, float)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) < 10 or len(neg) < 10:
        return None
    r = pd.Series(np.r_[pos, neg]).rank().to_numpy()
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def study(cfg, ds: Path, symbols=("NIFTY", "BANKNIFTY"), n_folds: int = 5, min_train_days: int = 250, say=print) -> dict:
    hz = X.load(ds, "horizons", symbols, use="direction_research", allow_unverified=True)
    status = hz.attrs.get("status")
    cost = CostModel.from_cfg(cfg)
    out = {"dataset": hz.attrs.get("dataset"), "evidence": status, "use": "direction_research / development_folds",
           "not_for": X.FORBIDDEN_NOTE, "model": "baseline (DirectionModel logistic, L2 3, Platt, abstention)", "results": {}}
    for sym in symbols:
        s = hz[hz["symbol"] == sym].copy()
        if s.empty:
            continue
        s["day"] = s["day"].astype(str)
        s = s[np.isfinite(s[FEATURES].to_numpy(float)).all(1)]
        days = sorted(s["day"].unique())
        out["results"][sym] = {"sessions": len(days), "first_day": days[0], "last_day": days[-1], "horizons": {}}
        for h, mins in HORIZON_MIN.items():
            d = s.rename(columns={f"y_{h}": "y_h", f"fwd_ret_{h}": "fwd_h", f"label_end_{h}": "le_h"})
            d = d.assign(y=d["y_h"], fwd_ret=d["fwd_h"], label_end=d["le_h"]).dropna(subset=["y", "fwd_ret"])
            wf = WalkForwardConfig(folds=n_folds, min_train_days=min_train_days, embargo_min=mins, horizon_min=mins)
            lay = folds(d, wf)
            cb = cost.round_trip_bps(float(d["entry_px"].median()), sym)
            oos = []
            for f in lay:
                tr, te, _ = split(d, f, wf)
                try:
                    pipe = Pipeline("baseline").fit(tr, cb, embargo=pd.Timedelta(minutes=mins))
                except ValueError as exc:
                    say(f"  {sym} {h} fold {f['fold']}: not fitted ({exc!s:.80})")
                    continue
                te = te.copy()
                te["p"] = pipe.predict(te)
                te["signal"] = pipe.signal(te["p"].to_numpy())
                te["fold"] = f["fold"]
                oos.append(te)
            if not oos:
                out["results"][sym]["horizons"][h] = {"status": "insufficient data"}
                continue
            o = pd.concat(oos)
            y, p, r = o["y"].to_numpy(float), o["p"].to_numpy(float), o["fwd_ret"].to_numpy(float)
            base = float(y.mean())
            brier = float(np.mean((p - y) ** 2))
            took = o["signal"].to_numpy() != 0
            hit = float((np.sign(r[took]) == o["signal"].to_numpy()[took]).mean()) if took.any() else None
            ic = float(pd.Series(p).rank().corr(pd.Series(r).rank())) if len(o) > 30 else None
            net = (o["signal"].to_numpy()[took] * r[took] * 1e4 - cb) if took.any() else np.array([])
            by_fold = o.groupby("fold").apply(lambda g: _auc(g["y"], g["p"]), include_groups=False).to_dict()
            out["results"][sym]["horizons"][h] = {
                "oos_rows": int(len(o)), "oos_sessions": int(o["day"].nunique()), "folds": len(lay),
                "auc": _auc(y, p), "auc_by_fold": {str(k): v for k, v in by_fold.items()},
                "brier_skill": float(1 - brier / (base * (1 - base))) if 0 < base < 1 else None, "rank_ic": ic,
                "coverage": float(took.mean()), "hit_rate_when_trading": hit,
                "mean_abs_move_bps": float(np.nanmean(np.abs(r)) * 1e4),
                "futures_proxy": {"round_trip_bps": cb, "signals": int(took.sum()),
                                  "net_bps_per_signal": float(net.mean()) if len(net) else None,
                                  "breakeven_hit_rate": float(0.5 + cb / (2 * np.nanmean(np.abs(r)) * 1e4))}}
            m = out["results"][sym]["horizons"][h]
            say(f"  {sym} {h:>5}: AUC {m['auc'] if m['auc'] is None else round(m['auc'], 4)}, IC "
                f"{None if ic is None else round(ic, 4)}, coverage {m['coverage']:.1%}, mean |move| {m['mean_abs_move_bps']:.1f} bps "
                f"[{status}]")
    write_json(Path(ds) / "direction_study.json", out)
    return out


def render(rep: dict) -> str:
    L = [f"# Direction research on external index minutes ({rep['dataset']})", "",
         f"**Evidence: {rep['evidence']}** · use: {rep['use']} · {rep['not_for']}.", "", f"Model: {rep['model']}.", ""]
    for sym, r in rep["results"].items():
        L += [f"## {sym}: {r['sessions']} sessions ({r['first_day']} → {r['last_day']})", "",
              "| horizon | OOS sessions | AUC | Brier skill | rank IC | coverage | hit rate | mean abs move (bps) | futures-proxy net bps / signal |",
              "|---|---|---|---|---|---|---|---|---|"]
        for h, m in r["horizons"].items():
            if "auc" not in m:
                L.append(f"| {h} | — | {m.get('status')} | | | | | | |")
                continue

            def f(x, d=4):
                return "—" if x is None else f"{x:.{d}f}"
            L.append(f"| {h} | {m['oos_sessions']} | {f(m['auc'])} | {f(m['brier_skill'])} | {f(m['rank_ic'])} | "
                     f"{m['coverage']:.1%} | {f(m['hit_rate_when_trading'], 3)} | {m['mean_abs_move_bps']:.1f} | "
                     f"{f(m['futures_proxy']['net_bps_per_signal'], 2)} |")
        L.append("")
    return "\n".join(L) + "\n"
