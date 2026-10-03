"""Drift: is the champion still looking at the world it was validated on, and still doing what it did there?

  data drift         PSI of each feature over the recent window against the training reference (quantile bins
                     stored in the model card at registration)
  prediction drift   PSI of the champion's probabilities against those on its validation folds
  calibration drift  ECE on the champion's recent resolved predictions against its validation ECE
  performance        the champion's recent net expectancy (simulated, after costs) against the lower bound of its
                     validation interval; a shortfall over enough trades is deterioration

State: ok / warn / alarm, or "insufficient data". An alarm makes the live champion abstain (no signal) until a cycle
retrains and a challenger replaces it, or the operator rolls back.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .evaluate import ece, ece_noise
from .features import FEATURES

DEFAULT = {"psi_warn": 0.10, "psi_alarm": 0.25, "ece_warn": 0.03, "ece_alarm": 0.06, "min_rows": 150,
           "min_trades": 20, "window_days": 5}


def reference(values: np.ndarray, bins: int = 10) -> dict:
    """Quantile edges and the share of values in each bin (the reference distribution)."""
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if len(v) < bins * 5:
        return {}
    edges = np.unique(np.quantile(v, np.linspace(0, 1, bins + 1)[1:-1]))
    frac = np.bincount(np.searchsorted(edges, v, side="right"), minlength=len(edges) + 1) / len(v)
    return {"edges": edges.tolist(), "frac": frac.tolist()}


def psi(ref: dict, values: np.ndarray) -> float:
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    if not ref or not len(v):
        return float("nan")
    edges = np.array(ref["edges"])
    cur = np.bincount(np.searchsorted(edges, v, side="right"), minlength=len(edges) + 1) / len(v)
    base = np.array(ref["frac"])
    cur, base = np.clip(cur, 1e-4, None), np.clip(base, 1e-4, None)
    return float(np.sum((cur - base) * np.log(cur / base)))


def references(train: pd.DataFrame, p_val: np.ndarray) -> dict:
    """What the card stores for later drift checks."""
    return {"features": {f: reference(train[f].to_numpy(float)) for f in FEATURES}, "p": reference(p_val)}


def report(card: dict, recent: pd.DataFrame, cfg: dict | None = None) -> dict:
    """`recent`: ledger.frame rows for the champion over the window (features as f_<name>, p, y, signal, net bps)."""
    c = {**DEFAULT, **(cfg or {})}
    ref = (card or {}).get("drift_reference") or {}
    val = ((card or {}).get("validation") or {}).get("metrics") or {}
    out = {"state": "insufficient data", "rows": int(len(recent)), "checks": {}}
    if len(recent) < c["min_rows"] or not ref:
        return out
    fpsi = {f: psi(ref["features"].get(f, {}), recent.get(f"f_{f}", pd.Series(dtype=float)).to_numpy(float)) for f in FEATURES}
    fpsi = {k: round(v, 4) for k, v in fpsi.items() if v == v}
    worst = max(fpsi.values()) if fpsi else float("nan")
    ppsi = psi(ref.get("p", {}), recent["p"].to_numpy(float))
    res = recent[recent["resolved"]] if "resolved" in recent else recent
    raw = ece(res["y"].to_numpy(float), res["p"].to_numpy(float)) if len(res) >= c["min_rows"] else float("nan")
    e = raw - ece_noise(res["p"].to_numpy(float)) if raw == raw else float("nan")      # beyond sampling noise
    traded = res[res["signal"] != 0] if len(res) else res
    net = traded["net_bps"].astype(float) if "net_bps" in traded and len(traded) else pd.Series(dtype=float)
    lo = ((val.get("ci") or {}).get("expectancy_bps") or {}).get("lo")
    perf = float(net.mean()) if len(net) >= c["min_trades"] else float("nan")
    out["checks"] = {"feature_psi_max": worst, "feature_psi": fpsi, "prediction_psi": round(ppsi, 4) if ppsi == ppsi else None,
                     "recent_ece": raw, "recent_ece_excess": e, "validation_ece": (val.get("classification") or {}).get("ece"),
                     "recent_expectancy_bps": perf, "validation_expectancy_lo_bps": lo, "recent_trades": int(len(net))}
    alarm, warn = [], []
    for name, x in (("feature drift", worst), ("prediction drift", ppsi)):
        if x == x and x >= c["psi_alarm"]:
            alarm.append(f"{name} PSI {x:.2f}")
        elif x == x and x >= c["psi_warn"]:
            warn.append(f"{name} PSI {x:.2f}")
    if e == e and e >= c["ece_alarm"]:
        alarm.append(f"calibration ECE {raw:.3f} ({e:+.3f} beyond noise)")
    elif e == e and e >= c["ece_warn"]:
        warn.append(f"calibration ECE {raw:.3f} ({e:+.3f} beyond noise)")
    if perf == perf and lo is not None and perf < lo:
        (alarm if perf < 0 else warn).append(f"expectancy {perf:+.1f} bps below its validation range (≥ {lo:+.1f})")
    out["state"] = "alarm" if alarm else "warn" if warn else "ok"
    out["reasons"] = alarm + warn
    return out
