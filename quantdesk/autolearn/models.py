"""Model candidates, probability calibration and the abstention threshold.

Every candidate has the same interface (fit on a training frame, `predict_proba` on any frame, a JSON artifact) and is
evaluated by identical code, so none is favoured by its plumbing:

  baseline     the live DirectionModel exactly as the desk fits it today (L2 = 3, IRLS): the bar to beat
  logit_l2_*   the same logistic model with weaker / stronger L2
  logit_l1     L1 (+ a little L2) by proximal gradient (FISTA): sparse, drops features that don't earn their place
  stumps       gradient-boosted depth-1 trees on quantile bins (numpy only, deterministic): a non-linear check

A fitted `Pipeline` = base model fitted on the older 80% of its training days, a Platt calibration fitted on the
newer 20% (purged by the label horizon), and an abstention threshold τ chosen on that same calibration slice to
maximise net expectancy after costs with a minimum coverage. |p − ½| < τ means no signal: the model abstains. If no τ
pays on the calibration slice, τ is set so it always abstains, which then fails every gate. Nothing is ever chosen on
test data. Artifacts are plain JSON (no pickle), hashed, and verified on load.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ..intraday.quant import DirectionModel
from .features import FEATURE_VERSION, FEATURES, LABEL_VERSION
from .store import canon, sha

SPECS = {
    "baseline": {"kind": "logit", "l2": 3.0, "l1": 0.0},
    "logit_l2_weak": {"kind": "logit", "l2": 0.3, "l1": 0.0},
    "logit_l2_strong": {"kind": "logit", "l2": 30.0, "l1": 0.0},
    "logit_l1": {"kind": "logit", "l2": 0.1, "l1": 8.0},
    "stumps": {"kind": "stumps", "rounds": 80, "lr": 0.08, "bins": 16, "min_leaf": 40, "lam": 5.0},
}
TAU_GRID = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12)
NEVER = 0.5                                        # τ that abstains on everything


class ArtifactError(RuntimeError):
    pass


# ---- base learners ---------------------------------------------------------------------------------------------------
def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -35, 35)))


class Logit:
    """Standardised logistic regression. l1 == 0 → the DirectionModel's own IRLS fit (identical numbers)."""

    def __init__(self, l2: float = 3.0, l1: float = 0.0, **_):
        self.l2, self.l1 = float(l2), float(l1)
        self.w = self.mu = self.sd = None

    def fit(self, X: np.ndarray, y: np.ndarray):
        if self.l1 == 0:
            self.w, self.mu, self.sd = DirectionModel(l2=self.l2)._fit(X, y)
            return self
        mu, sd = X.mean(0), X.std(0) + 1e-9
        Z = np.column_stack([np.ones(len(X)), (X - mu) / sd])
        L = 0.25 * np.linalg.eigvalsh(Z.T @ Z).max() + self.l2
        w = np.zeros(Z.shape[1])
        v, t = w.copy(), 1.0
        pen = np.r_[0.0, np.full(Z.shape[1] - 1, 1.0)]
        for _ in range(500):                                       # FISTA on Σ loss + l2/2‖w‖² + l1‖w‖₁
            g = Z.T @ (_sigmoid(Z @ v) - y) + self.l2 * pen * v
            u = v - g / L
            w_new = np.sign(u) * np.maximum(np.abs(u) - self.l1 * pen / L, 0.0)
            t_new = (1 + math.sqrt(1 + 4 * t * t)) / 2
            v = w_new + (t - 1) / t_new * (w_new - w)
            if np.abs(w_new - w).max() < 1e-8:
                w = w_new
                break
            w, t = w_new, t_new
        self.w, self.mu, self.sd = w, mu, sd
        return self

    def decision(self, X: np.ndarray) -> np.ndarray:
        Z = np.column_stack([np.ones(len(X)), (X - self.mu) / self.sd])
        return Z @ self.w

    def to_dict(self) -> dict:
        return {"w": self.w.tolist(), "mu": self.mu.tolist(), "sd": self.sd.tolist()}

    @classmethod
    def from_dict(cls, params: dict, d: dict) -> "Logit":
        m = cls(**params)
        m.w, m.mu, m.sd = np.array(d["w"]), np.array(d["mu"]), np.array(d["sd"])
        return m


class Stumps:
    """Gradient boosting of depth-1 trees on the logistic loss over per-feature quantile bins."""

    def __init__(self, rounds: int = 80, lr: float = 0.08, bins: int = 16, min_leaf: int = 40, lam: float = 5.0, **_):
        self.rounds, self.lr, self.bins, self.min_leaf, self.lam = int(rounds), float(lr), int(bins), int(min_leaf), float(lam)
        self.f0, self.edges, self.trees = 0.0, [], []

    def fit(self, X: np.ndarray, y: np.ndarray):
        n, k = X.shape
        base = float(np.clip(y.mean(), 1e-3, 1 - 1e-3))
        self.f0 = math.log(base / (1 - base))
        self.edges = [np.unique(np.quantile(X[:, j], np.linspace(0, 1, self.bins + 1)[1:-1])) for j in range(k)]
        B = [np.searchsorted(self.edges[j], X[:, j], side="right") for j in range(k)]
        F = np.full(n, self.f0)
        self.trees = []
        for _ in range(self.rounds):
            p = _sigmoid(F)
            g, h = y - p, p * (1 - p)
            G, H = g.sum(), h.sum()
            best = None
            for j in range(k):
                nb = len(self.edges[j]) + 1
                gl = np.cumsum(np.bincount(B[j], weights=g, minlength=nb))[:-1]
                hl = np.cumsum(np.bincount(B[j], weights=h, minlength=nb))[:-1]
                cl = np.cumsum(np.bincount(B[j], minlength=nb))[:-1]
                ok = (cl >= self.min_leaf) & (n - cl >= self.min_leaf)
                if not ok.any():
                    continue
                gain = gl ** 2 / (hl + self.lam) + (G - gl) ** 2 / (H - hl + self.lam) - G ** 2 / (H + self.lam)
                gain = np.where(ok, gain, -np.inf)
                b = int(np.argmax(gain))
                if best is None or gain[b] > best[0]:
                    best = (float(gain[b]), j, b, float(gl[b] / (hl[b] + self.lam)), float((G - gl[b]) / (H - hl[b] + self.lam)))
            if best is None or best[0] <= 1e-9:
                break
            _, j, b, vl, vr = best
            thr = float(self.edges[j][b])
            self.trees.append((j, thr, self.lr * vl, self.lr * vr))
            F += np.where(X[:, j] < thr, self.lr * vl, self.lr * vr)
        return self

    def decision(self, X: np.ndarray) -> np.ndarray:
        F = np.full(len(X), self.f0)
        for j, thr, vl, vr in self.trees:
            F += np.where(X[:, j] < thr, vl, vr)
        return F

    def to_dict(self) -> dict:
        return {"f0": self.f0, "trees": [list(t) for t in self.trees]}

    @classmethod
    def from_dict(cls, params: dict, d: dict) -> "Stumps":
        m = cls(**params)
        m.f0, m.trees = float(d["f0"]), [(int(t[0]), float(t[1]), float(t[2]), float(t[3])) for t in d["trees"]]
        return m


KINDS = {"logit": Logit, "stumps": Stumps}


# ---- calibration -----------------------------------------------------------------------------------------------------
def fit_platt(z: np.ndarray, y: np.ndarray, l2: float = 1e-3) -> tuple[float, float]:
    """p = σ(a·z + b) on held-out scores z (Newton, tiny ridge). Identity (1, 0) when there's too little data."""
    if len(z) < 30 or y.min() == y.max():
        return 1.0, 0.0
    a, b = 1.0, 0.0
    for _ in range(50):
        p = _sigmoid(a * z + b)
        r = p - y
        w = p * (1 - p) + 1e-9
        ga, gb = float(z @ r) + l2 * (a - 1), float(r.sum())
        haa, hab, hbb = float((w * z * z).sum()) + l2, float((w * z).sum()), float(w.sum())
        det = haa * hbb - hab * hab
        if det <= 1e-12:
            break
        da, db = (hbb * ga - hab * gb) / det, (haa * gb - hab * ga) / det
        a, b = a - da, b - db
        if max(abs(da), abs(db)) < 1e-9:
            break
    if not (math.isfinite(a) and math.isfinite(b)) or a <= 0:      # a negative slope would flip the model: refuse
        return 1.0, 0.0
    return float(a), float(b)


def choose_tau(p: np.ndarray, fwd_ret: np.ndarray, cost_bps: float, min_coverage: float = 0.10,
               min_trades: int = 20, grid=TAU_GRID) -> tuple[float, dict]:
    """The abstention threshold that maximises net bps per opportunity on a calibration slice (overlapping 30-minute
    signals are fine for ranking thresholds; the P&L simulation proper is non-overlapping)."""
    ok = np.isfinite(fwd_ret)
    p, r = p[ok], fwd_ret[ok] * 1e4
    best, table = (NEVER, -np.inf), {}
    for tau in grid:
        take = np.abs(p - 0.5) >= tau
        n = int(take.sum())
        if n < min_trades or n < min_coverage * len(p):
            table[str(tau)] = {"trades": n, "net_bps_per_opportunity": None}
            continue
        net = (np.sign(p[take] - 0.5) * r[take] - cost_bps).sum() / max(len(p), 1)
        table[str(tau)] = {"trades": n, "net_bps_per_opportunity": round(float(net), 4)}
        if net > best[1]:
            best = (float(tau), float(net))
    if best[1] <= 0:                                                # nothing pays after costs: abstain on everything
        return NEVER, table
    return best[0], table


# ---- the pipeline ----------------------------------------------------------------------------------------------------
class Pipeline:
    def __init__(self, name: str, spec: dict | None = None):
        self.name = name
        self.spec = dict(spec or SPECS[name])
        self.base = None
        self.platt = (1.0, 0.0)
        self.tau = NEVER
        self.fit_info: dict = {}

    def _X(self, df: pd.DataFrame) -> np.ndarray:
        X = df[FEATURES].to_numpy(float)
        if not np.isfinite(X).all():
            raise ValueError("non-finite features")
        return X

    def fit(self, train: pd.DataFrame, cost_bps: float, cal_frac: float = 0.2, embargo: pd.Timedelta | None = None,
            min_coverage: float = 0.10) -> "Pipeline":
        """Base model on the older days, calibration + τ on the newer days (purged so no fit row's label reaches into
        the calibration slice)."""
        d = train.dropna(subset=["y"])
        days = sorted(d["day"].unique())
        if len(days) < 5 or len(d) < 200:
            raise ValueError(f"too little training data ({len(d)} rows over {len(days)} days)")
        cut = days[max(1, int(round(len(days) * (1 - cal_frac))))] if len(days) > 2 else days[-1]
        cal = d[d["day"] >= cut]
        cal_start = cal["ts"].min() - BAR_BEFORE
        fit = d[(d["day"] < cut) & (pd.to_datetime(d["label_end"]) <= cal_start - (embargo or pd.Timedelta(0)))]
        if len(fit) < 150 or len(cal) < 50:
            raise ValueError(f"too little data to fit and calibrate ({len(fit)} fit rows, {len(cal)} calibration rows)")
        kind = KINDS[self.spec["kind"]]
        self.base = kind(**{k: v for k, v in self.spec.items() if k != "kind"}).fit(self._X(fit), fit["y"].to_numpy(float))
        z = self.base.decision(self._X(cal))
        self.platt = fit_platt(z, cal["y"].to_numpy(float))
        p_cal = _sigmoid(self.platt[0] * z + self.platt[1])
        self.tau, tau_table = choose_tau(p_cal, cal["fwd_ret"].to_numpy(float), cost_bps, min_coverage)
        self.fit_info = {"fit_rows": int(len(fit)), "cal_rows": int(len(cal)), "fit_days": [days[0], str(fit["day"].max())],
                         "cal_days": [str(cut), days[-1]], "platt": list(self.platt), "tau": self.tau, "tau_table": tau_table}
        return self

    def predict_raw(self, df: pd.DataFrame) -> np.ndarray:
        return _sigmoid(self.base.decision(self._X(df)))

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Calibrated P(up in 30 minutes)."""
        return _sigmoid(self.platt[0] * self.base.decision(self._X(df)) + self.platt[1])

    def signal(self, p: np.ndarray) -> np.ndarray:
        """+1 / −1, or 0 where the model abstains."""
        p = np.asarray(p, dtype=float)
        return np.where(np.abs(p - 0.5) >= self.tau, np.sign(p - 0.5), 0.0).astype(int) if self.tau < NEVER else np.zeros(len(p), int)

    # ---- artifacts -----------------------------------------------------------------------------------------------
    def artifact(self) -> dict:
        body = {"name": self.name, "spec": self.spec, "base": self.base.to_dict(), "platt": list(self.platt), "tau": self.tau,
                "features": FEATURES, "feature_version": FEATURE_VERSION, "label_version": LABEL_VERSION}
        return {**body, "sha256": sha(canon(body))}

    @classmethod
    def from_artifact(cls, art: dict, expect_sha: str | None = None) -> "Pipeline":
        body = {k: v for k, v in art.items() if k != "sha256"}
        digest = sha(canon(body))
        if art.get("sha256") != digest or (expect_sha and expect_sha != digest):
            raise ArtifactError(f"model artifact {art.get('name')} failed its integrity check")
        if body.get("feature_version") != FEATURE_VERSION or body.get("features") != FEATURES:
            raise ArtifactError(f"model artifact {art.get('name')} was built for features {body.get('feature_version')}, "
                                f"this code computes {FEATURE_VERSION}")
        m = cls(body["name"], body["spec"])
        kind = KINDS[m.spec["kind"]]
        m.base = kind.from_dict({k: v for k, v in m.spec.items() if k != "kind"}, body["base"])
        m.platt, m.tau = (float(body["platt"][0]), float(body["platt"][1])), float(body["tau"])
        return m


BAR_BEFORE = pd.Timedelta(minutes=5)              # a decision at ts used the bar that started 5 minutes earlier
