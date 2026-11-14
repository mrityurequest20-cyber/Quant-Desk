"""Kalman filtering (owner, 13 Nov 2026: "Kalman filtering: smoothing the futures premium and trend"). PAPER MONEY ONLY; nothing here trades.

THE MODEL: a LOCAL LINEAR TREND, the simplest state-space model with a trend in it.
    observation      y_t     = level_t + e_t                  e_t ~ N(0, r)        (what the board shows: the truth plus noise)
    state            level_t = level_t-1 + slope_t-1 + w_t     w_t ~ N(0, q_level)  (the level moves by the slope, plus shocks)
                     slope_t = slope_t-1 + v_t                 v_t ~ N(0, q_slope)  (the slope itself wanders, slowly)
The Kalman filter gives, after each observation, the best estimate of (level, slope) from everything seen so far and its covariance P. The SLOPE over its standard
error, sqrt(P[1][1]), is a t-statistic: |t| >= TREND_T says the trend is distinguishable from noise. Unlike a raw five-minute change, a single noisy print moves it little.

THE NOISE is not guessed: the three variances are fitted by MAXIMUM LIKELIHOOD from the prediction-error decomposition (each observation's innovation v and its variance S
give log L = -1/2 * sum(log 2 pi S + v^2 / S)). The likelihood is CONCENTRATED over the overall scale (with every variance a multiple of r, r has a closed form), so only the
two ratios q_level / r and q_slope / r are searched, on a grid.

Used twice:
* the TREND of each underlying, on log one-minute closes (regimes.RegimeBook feeds it): the slope's t-statistic is AUTO v2's price vote, in place of the raw five-minute move;
* the FUTURES PREMIUM, (future / spot - 1), read every 30 seconds by the market read: the smoothed premium, not each noisy print, is what its change is read from.

Standard library only (paper package rules).
"""
from __future__ import annotations

import math

LEVEL_RATIOS = (0.01, 0.1, 0.5, 2.0, 10.0)          # q_level / r searched
SLOPE_RATIOS = (1e-6, 1e-5, 1e-4, 1e-3)             # q_slope / r searched: a slope that wanders far slower than the level
DIFFUSE = 1e6                                        # the first observations' prior variance, in units of the data's own scale
BURN_IN = 2                                          # a two-state model's first two innovations carry the diffuse prior, not information
TREND_T = 2.0


class LocalLinearTrend:
    """One local-linear-trend Kalman filter. Variances are absolute (not ratios)."""

    def __init__(self, q_level: float, q_slope: float, r: float, scale: float = 1.0):
        self.ql, self.qs, self.r = q_level, q_slope, r
        self.x = None                                                        # (level, slope)
        self.P = [[DIFFUSE * scale, 0.0], [0.0, DIFFUSE * scale]]
        self.n = 0

    def step(self, y: float) -> tuple[float, float]:
        """Feed one observation; returns (innovation, its variance)."""
        if self.x is None:
            self.x = [y, 0.0]
        l, s = self.x
        a, b, c = self.P[0][0], self.P[0][1], self.P[1][1]
        l, s = l + s, s                                                      # predict: F = [[1, 1], [0, 1]]
        a, b, c = a + 2 * b + c + self.ql, b + c, c + self.qs                # P = F P F' + Q
        S = a + self.r
        v = y - l
        k0, k1 = a / S, b / S
        self.x = [l + k0 * v, s + k1 * v]
        self.P = [[a - k0 * a, b - k0 * b], [b - k1 * a, c - k1 * b]]       # (I - K H) P
        self.P[1][0] = self.P[0][1]
        self.n += 1
        return v, S

    @property
    def level(self) -> float | None:
        return self.x[0] if self.x else None

    @property
    def slope(self) -> float | None:
        return self.x[1] if self.x else None

    @property
    def slope_se(self) -> float:
        return math.sqrt(max(self.P[1][1], 0.0))

    def trend(self) -> dict | None:
        if self.x is None or self.n <= BURN_IN:
            return None
        se = self.slope_se
        t = self.x[1] / se if se > 0 else 0.0
        return {"level": self.x[0], "slope": self.x[1], "se": se, "t": t, "vote": (1 if t > 0 else -1) if abs(t) >= TREND_T else 0}


def _run(obs: list[float], ql: float, qs: float) -> tuple[float, float, int]:
    """With r = 1: (sum of v^2 / S, sum of log S, n) after the burn-in: the pieces of the concentrated likelihood."""
    f = LocalLinearTrend(ql, qs, 1.0)
    ss = sl = 0.0
    n = 0
    for i, y in enumerate(obs):
        v, S = f.step(y)
        if i >= BURN_IN:
            ss += v * v / S
            sl += math.log(S)
            n += 1
    return ss, sl, n


def fit(obs: list[float], min_n: int = 30) -> dict | None:
    """Maximum likelihood (q_level, q_slope, r) for a series, and the filter run through it. None with fewer than `min_n` observations or a flat series.
    The likelihood is concentrated: for ratios (ql, qs) with r = 1, r_hat = (1/n) sum v^2 / S and log L = -n/2 (log 2 pi r_hat + 1) - 1/2 sum log S."""
    obs = [float(y) for y in obs if isinstance(y, (int, float)) and math.isfinite(y)]
    if len(obs) < min_n:
        return None
    d = [b - a for a, b in zip(obs, obs[1:])]
    if not any(d):
        return None
    best = None
    for ql in LEVEL_RATIOS:
        for qs in SLOPE_RATIOS:
            ss, sl, n = _run(obs, ql, qs)
            if n <= 0 or ss <= 0:
                continue
            r = ss / n
            ll = -0.5 * n * (math.log(2 * math.pi * r) + 1) - 0.5 * sl
            if best is None or ll > best[0]:
                best = (ll, ql, qs, r)
    if best is None:
        return None
    ll, ql, qs, r = best
    f = LocalLinearTrend(ql * r, qs * r, r, scale=r)
    for y in obs:
        f.step(y)
    return {"q_level": ql * r, "q_slope": qs * r, "r": r, "loglik": ll, "filter": f, "n": len(obs)}
