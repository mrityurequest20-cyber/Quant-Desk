"""The plan policy: the one simple baseline, kept deliberately simple until something beats it after costs.

For one (horizon, DTE bucket), at a decision point, for each side (long call / long put) of the plan the engine would
buy:

  P(net > 0)      a logistic model (L2) on the decision's features and the plan's own numbers (implied vol, quoted
                  spread, days to expiry), calibrated by Platt scaling on held-out sessions
  expected net R  P × (average win R) − (1 − P) × (average loss R), both averaged on the fit sessions; R = net P&L ÷ the
                  premium at risk to the stop, so ₹ = R × that risk
  abstain         buy the side with the higher expected net R only when it clears τ. τ is chosen on the calibration
                  sessions to maximise net R per decision point. If no τ pays there, τ = ∞ and the policy never
                  trades

The fit never sees test data:
  - the logistic fits the older 80% of the training sessions;
  - Platt and τ fit the newer 20%, purged so that no fit plan's exit reaches into them.
Another candidate is added only when it improves out-of-sample plan-level net results after costs (see
docs/PLAN_RESEARCH.md). Artifacts are plain JSON, hashed, and verified on load.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import FEATURES
from .models import ArtifactError, Logit, _sigmoid, fit_platt
from .store import canon, sha

PLAN_FEATURES = FEATURES + ["plan_iv", "plan_spread_pct", "dte"]
CANDIDATES = {"plan_logit": {"kind": "plan_logit", "l2": 3.0}}
TAU_GRID = (0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50)
NEVER = float("inf")
R_CLIP = 4.0                                     # one gap-through-the-stop outlier shouldn't set the average loss
POLICY_VERSION = "p2"


def _X(df: pd.DataFrame) -> np.ndarray:
    X = df[PLAN_FEATURES].to_numpy(float)
    if not np.isfinite(X).all():
        raise ValueError("non-finite plan features")
    return X


def choose(rows: pd.DataFrame, score: np.ndarray) -> pd.DataFrame:
    """One row per decision point (ts, symbol): the side with the higher score."""
    d = rows.assign(score=score).sort_values(["ts", "symbol", "score"], ascending=[True, True, False], kind="stable")
    return d.drop_duplicates(["ts", "symbol"], keep="first").reset_index(drop=True)


def tau_table(best: pd.DataFrame, grid=TAU_GRID, min_trades: int = 10) -> tuple[float, dict]:
    """τ maximising net R per decision point on the calibration sessions (overlapping plans are fine for ranking
    thresholds; the evaluation proper is the engine-constrained replay). ∞ when nothing pays."""
    n = max(len(best), 1)
    out, pick = {}, (NEVER, 0.0)
    for tau in grid:
        take = best["score"].to_numpy(float) >= tau
        k = int(take.sum())
        if k < min_trades:
            out[str(tau)] = {"trades": k, "net_R_per_point": None}
            continue
        v = float(np.clip(best["net_R"].to_numpy(float)[take], -R_CLIP, None).sum() / n)
        out[str(tau)] = {"trades": k, "net_R_per_point": round(v, 5)}
        if v > pick[1]:
            pick = (float(tau), v)
    return pick[0], out


class PlanPolicy:
    family = "plan"

    def __init__(self, name: str, spec: dict | None, horizon: str, bucket: str):
        self.name, self.spec = name, dict(spec or CANDIDATES[name])
        self.horizon, self.bucket = horizon, bucket
        self.models: dict[int, Logit] = {}
        self.platt: dict[int, tuple[float, float]] = {}
        self.avg: dict[int, tuple[float, float]] = {}
        self.tau = NEVER
        self.fit_info: dict = {}

    @property
    def kind(self) -> str:
        return self.spec["kind"]

    def fit(self, rows: pd.DataFrame, embargo: pd.Timedelta, cal_frac: float = 0.2, min_trades: int = 10) -> "PlanPolicy":
        """`rows`: plan outcomes of one evidence class for this horizon and bucket (both sides), with the features."""
        d = rows.dropna(subset=PLAN_FEATURES + ["net_R"])
        days = sorted(d["day"].unique())
        if len(days) < 5 or len(d) < 120:
            raise ValueError(f"too little data ({len(d)} plan rows over {len(days)} sessions)")
        cut = days[max(1, int(round(len(days) * (1 - cal_frac))))]
        cal = d[d["day"] >= cut]
        cal_start = pd.Timestamp(cal["ts"].min()) - pd.Timedelta(minutes=5)
        fit = d[(d["day"] < cut) & (pd.to_datetime(d["label_end"]) <= cal_start - embargo)]
        if fit["ts"].nunique() < 60 or cal["ts"].nunique() < 20:
            raise ValueError(f"too little data to fit and calibrate ({fit['ts'].nunique()} / {cal['ts'].nunique()} points)")
        params = {k: v for k, v in self.spec.items() if k != "kind"}
        for side in (1, -1):
            f, c = fit[fit["direction"] == side], cal[cal["direction"] == side]
            if len(f) < 60 or len(c) < 20:
                raise ValueError(f"too few {('call', 'put')[side < 0]} plans to fit ({len(f)}) or calibrate ({len(c)})")
            y = (f["net"] > 0).to_numpy(float)
            if y.min() == y.max():
                raise ValueError(f"every {('call', 'put')[side < 0]} plan in the fit sessions had the same outcome")
            self.models[side] = Logit(**params).fit(_X(f), y)
            self.platt[side] = fit_platt(self.models[side].decision(_X(c)), (c["net"] > 0).to_numpy(float))
            r = f["net_R"].to_numpy(float)
            w, lo = r[r > 0], r[r <= 0]
            self.avg[side] = (float(np.clip(w, None, R_CLIP).mean()) if len(w) else 0.0,
                              float(-np.clip(lo, -R_CLIP, None).mean()) if len(lo) else 1.0)
        best = choose(cal, self.score(cal))
        self.tau, table = tau_table(best, TAU_GRID, min_trades)
        self.fit_info = {"fit_rows": int(len(fit)), "fit_points": int(fit["ts"].nunique()), "cal_points": int(len(best)),
                         "fit_days": [days[0], str(fit["day"].max())], "cal_days": [str(cut), days[-1]],
                         "tau": None if self.tau == NEVER else self.tau, "tau_table": table,
                         "avg_win_loss_R": {str(k): v for k, v in self.avg.items()}}
        return self

    def p_win(self, rows: pd.DataFrame) -> np.ndarray:
        """Calibrated P(net > 0) per row, for the row's own side."""
        side = rows["direction"].to_numpy(int)
        out = np.full(len(rows), np.nan)
        for s in (1, -1):
            m = side == s
            if m.any():
                a, b = self.platt[s]
                out[m] = _sigmoid(a * self.models[s].decision(_X(rows[m])) + b)
        return out

    def score(self, rows: pd.DataFrame) -> np.ndarray:
        """Expected net R per row, for the row's own side."""
        p = self.p_win(rows)
        side = rows["direction"].to_numpy(int)
        w = np.where(side > 0, self.avg[1][0], self.avg[-1][0])
        lo = np.where(side > 0, self.avg[1][1], self.avg[-1][1])
        return p * w - (1 - p) * lo

    def decide(self, rows: pd.DataFrame) -> pd.DataFrame:
        """One row per decision point: the better side's plan, its expected net R (`score`), P(win), and `trade`."""
        best = choose(rows, self.score(rows))
        best["p_win"] = self.p_win(best)
        best["trade"] = best["score"].to_numpy(float) >= self.tau
        return best

    def artifact(self) -> dict:
        body = {"family": "plan", "policy_version": POLICY_VERSION, "name": self.name, "spec": self.spec,
                "horizon": self.horizon, "bucket": self.bucket, "features": PLAN_FEATURES,
                "models": {str(k): m.to_dict() for k, m in self.models.items()},
                "platt": {str(k): list(v) for k, v in self.platt.items()},
                "avg": {str(k): list(v) for k, v in self.avg.items()},
                "tau": None if self.tau == NEVER else self.tau}
        return {**body, "sha256": sha(canon(body))}

    @classmethod
    def from_artifact(cls, art: dict, expect_sha: str | None = None) -> "PlanPolicy":
        body = {k: v for k, v in art.items() if k != "sha256"}
        digest = sha(canon(body))
        if art.get("sha256") != digest or (expect_sha and expect_sha != digest):
            raise ArtifactError(f"plan policy {art.get('name')} failed its integrity check")
        if body.get("features") != PLAN_FEATURES:
            raise ArtifactError(f"plan policy {body.get('name')} was built for other features than this code computes")
        m = cls(body["name"], body["spec"], body["horizon"], body["bucket"])
        params = {k: v for k, v in m.spec.items() if k != "kind"}
        m.models = {int(k): Logit.from_dict(params, v) for k, v in body["models"].items()}
        m.platt = {int(k): (float(v[0]), float(v[1])) for k, v in body["platt"].items()}
        m.avg = {int(k): (float(v[0]), float(v[1])) for k, v in body["avg"].items()}
        m.tau = NEVER if body.get("tau") is None else float(body["tau"])
        return m
