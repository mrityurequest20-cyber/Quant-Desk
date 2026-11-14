"""Extreme value theory: tail-risk estimates (owner, 13 Nov 2026: "Add Extreme value theory: tail-risk estimates"). PAPER MONEY ONLY; nothing here trades.

WHY. A normal distribution says a 5-sigma day happens once in 14,000 years; markets have several a decade. The shadow record cannot see this either: a few weeks of trades
rarely contain the day that costs most. EVT models only the TAIL, where it matters, by the one theorem that holds there for nearly any distribution (Pickands-Balkema-de Haan):
losses beyond a high threshold u follow a GENERALISED PARETO DISTRIBUTION
        P(X - u > y | X > u) = (1 + xi y / beta) ^ (-1 / xi)
with a SHAPE xi (xi > 0: a fat, power-law tail, as equity returns have, typically 0.1 to 0.4; xi = 0: exponential; xi < 0: a hard end) and a SCALE beta.

HOW (McNeil and Frey, 2000: conditional EVT). Volatility clusters, so raw history mixes calm and wild years. Each day's return is first STANDARDISED by the volatility
known the evening before (an exponentially weighted moving average, RiskMetrics' lambda = 0.94): z = r / sigma_t. The z's are close to independent and identically distributed,
and it is their tails that are fitted, separately for losses and gains:
* the threshold is the TAIL_Q (95th) percentile of each side (the 90th for a short history), with at least MIN_EXCEED exceedances;
* xi and beta by PROBABILITY-WEIGHTED MOMENTS (Hosking and Wallis, 1987): closed form and steadier than maximum likelihood in samples of a hundred;
* the body between the thresholds is the empirical distribution (a table of quantiles).
Today's distribution is then sigma_now x sqrt(h) x z: today's volatility, history's shape. Horizons of h = 1, 3, 5 and 10 sessions are fitted on their own (overlapping) h-day
returns, standardised by sigma_t sqrt(h): the shape of a 5-day move is measured, not assumed from the 1-day one.

WHAT IT GIVES. Value at risk (VaR_p: the loss exceeded with probability 1 - p) and expected shortfall (ES_p: the average loss beyond it), and a quantile function, so any payoff
can be averaged over the whole distribution (expected_payoff). AUTO v2 uses that to ask whether an option sale's premium pays for the tail it sells (auto2.tail_check).

BACKTEST. A model of the 1% tail must be wrong about 1% of the time: kupiec() is Kupiec's (1995) proportion-of-failures likelihood-ratio test of the exceedance count.

Standard library only (paper package rules): the premarket brief fits the models (fit_series) and ships them as compact JSON (to_json); AUTO v2 reads them back (from_json).
"""
from __future__ import annotations

import math
from statistics import NormalDist

EWMA_LAMBDA = 0.94
EWMA_SEED = 30                        # the first sigma: the plain variance of the first 30 returns (they are not themselves standardised)
TAIL_Q = 0.95                         # each side's threshold: the 95th percentile of its losses (gains) when that leaves TAIL_K_MIN exceedances,
TAIL_K_MIN, TAIL_Q_SHORT = 50, 0.90   # else down to the 90th (a short history: a stock with two years of sessions)
MIN_EXCEED = 25                       # a tail fitted from fewer exceedances is left to the empirical table
# MEASURED (tests/test_tails.py and the study in the commit): on Student-t(4) returns, whose true shape is 0.25, the fit gives 0.16 to 0.18 at these thresholds by moments
# AND by maximum likelihood alike: the t's tail approaches its power law slowly, so a finite threshold sees a thinner one. The 99% VaR and ES come out unbiased (5.24 against
# 5.22 for ES); the 99.9% VaR about 17% too low. The desk therefore works at 99%, and the 99.9% figures are not used for any decision.
MIN_OBS = 250                         # about a year of sessions before anything is fitted
HORIZONS = (1, 3, 5, 10)
XI_CLIP = (-0.5, 0.9)                 # a shape outside this is noise; above 1 the mean itself would not exist
BODY = tuple(round(0.05 * i, 2) for i in range(1, 20))     # the quantiles of z kept for the body: 5%, 10%, ..., 95%
QUAD_N = 401                          # expected_payoff integrates over normal scores from -QUAD_T to QUAD_T (beyond: below 1 in 290,000)
QUAD_T = 4.5
_N = NormalDist()


# ---------------------------------------------------------------------------------------------------------------- volatility and returns
def ewma_sigma(rets: list[float], lam: float = EWMA_LAMBDA) -> list[float]:
    """sigma[t]: the volatility known BEFORE return t (so return t standardised by it is a forecast error); one longer than rets: the last is tomorrow's."""
    if len(rets) < EWMA_SEED + 1:
        return []
    seed = rets[:EWMA_SEED]
    var = sum(r * r for r in seed) / len(seed)
    out = [math.sqrt(var)] * EWMA_SEED
    for r in rets[EWMA_SEED:]:
        out.append(math.sqrt(var))
        var = lam * var + (1 - lam) * r * r
    out.append(math.sqrt(var))
    return out


def log_returns(closes: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(closes, closes[1:]) if a and b and a > 0 and b > 0]


# ---------------------------------------------------------------------------------------------------------------- the generalised Pareto tail
def fit_gpd(exceed: list[float]) -> tuple[float, float] | None:
    """(xi, beta) of a GPD by probability-weighted moments: with the exceedances y sorted ascending and plotting positions p_i = (i - 0.35) / n,
    a0 = mean(y), a1 = mean((1 - p_i) y_i); xi = 2 - a0 / (a0 - 2 a1), beta = 2 a0 a1 / (a0 - 2 a1). None when the sample cannot carry it."""
    y = sorted(x for x in exceed if x >= 0 and math.isfinite(x))
    n = len(y)
    if n < 5:
        return None
    a0 = sum(y) / n
    a1 = sum((1 - (i + 1 - 0.35) / n) * v for i, v in enumerate(y)) / n
    den = a0 - 2 * a1
    if den <= 0 or a0 <= 0:
        return None
    xi = 2 - a0 / den
    beta = 2 * a0 * a1 / den
    if not (math.isfinite(xi) and math.isfinite(beta)) or beta <= 0:
        return None
    xi = min(max(xi, XI_CLIP[0]), XI_CLIP[1])
    return xi, beta


def _gpd_q(xi: float, beta: float, s: float) -> float:
    """The excess y with P(Y > y) = s under GPD(xi, beta)."""
    if abs(xi) < 1e-6:
        return -beta * math.log(s)
    return beta / xi * (s ** (-xi) - 1)


def _gpd_mean_beyond(xi: float, beta: float, y: float) -> float:
    """E[Y | Y > y] for a GPD: (y + beta) / (1 - xi) when xi < 1 (mean excess is linear in y: the GPD's signature)."""
    return (y + beta) / (1 - xi)


class Tail:
    """One distribution of standardised returns z: the empirical body and a GPD on each side. Losses are -z."""

    def __init__(self, body: list[float], lo: dict | None, hi: dict | None, n: int):
        self.body = body                    # z quantiles at BODY
        self.lo, self.hi = lo, hi           # {"u": threshold (positive, in loss units for lo), "xi", "beta", "zeta": share of the sample beyond u, "n": exceedances}
        self.n = n

    @classmethod
    def fit(cls, z: list[float]) -> "Tail | None":
        z = sorted(x for x in z if math.isfinite(x))
        n = len(z)
        if n < MIN_OBS:
            return None
        body = [_empirical_q(z, p) for p in BODY]
        sides = []
        for side in (-1, 1):
            vals = sorted((side * x for x in z), reverse=True)           # the side's extremes first, as positive numbers on the loss (or gain) axis
            k = int(round(n * (1 - TAIL_Q)))
            if k < TAIL_K_MIN:
                k = min(TAIL_K_MIN, int(round(n * (1 - TAIL_Q_SHORT))))
            if k < MIN_EXCEED:
                sides.append(None)
                continue
            u = vals[k]
            got = fit_gpd([v - u for v in vals[:k]])
            sides.append(None if got is None else {"u": u, "xi": got[0], "beta": got[1], "zeta": k / n, "n": k})
        return cls(body, sides[0], sides[1], n)

    # -- the distribution of z
    def quantile(self, p: float) -> float:
        """z with P(Z <= z) = p: the GPD beyond each side's threshold, the body's table between them (linear), and the thresholds' own probabilities to join them."""
        p = min(max(p, 1e-12), 1 - 1e-12)
        if self.lo and p < self.lo["zeta"]:
            return -(self.lo["u"] + _gpd_q(self.lo["xi"], self.lo["beta"], p / self.lo["zeta"]))
        if self.hi and p > 1 - self.hi["zeta"]:
            return self.hi["u"] + _gpd_q(self.hi["xi"], self.hi["beta"], (1 - p) / self.hi["zeta"])
        xs = list(BODY)
        ys = list(self.body)
        if self.lo:
            xs, ys = [self.lo["zeta"]] + xs, [-self.lo["u"]] + ys
        if self.hi:
            xs, ys = xs + [1 - self.hi["zeta"]], ys + [self.hi["u"]]
        pts = sorted(zip(xs, ys))
        if p <= pts[0][0]:
            return pts[0][1] + (pts[1][1] - pts[0][1]) / (pts[1][0] - pts[0][0]) * (p - pts[0][0])      # the table's ends, extended (no GPD on that side)
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if p <= x1:
                return y0 + (y1 - y0) * (p - x0) / (x1 - x0) if x1 > x0 else y1
        (x0, y0), (x1, y1) = pts[-2], pts[-1]
        return y1 + (y1 - y0) / (x1 - x0) * (p - x1)

    def var(self, p: float = 0.99, side: str = "loss") -> float:
        """Value at risk in z units, as a positive number: the loss (or gain) exceeded with probability 1 - p."""
        return -self.quantile(1 - p) if side == "loss" else self.quantile(p)

    def es(self, p: float = 0.99, side: str = "loss") -> float:
        """Expected shortfall in z units, positive: the average loss (gain) beyond VaR_p. Closed form in the GPD tail: ES = VaR + E[excess beyond VaR] =
        (VaR + beta - xi u) / (1 - xi); numerically over the table where there is no GPD."""
        t = self.lo if side == "loss" else self.hi
        v = self.var(p, side)
        if t and v >= t["u"] and t["xi"] < 1:
            return v + _gpd_mean_beyond(t["xi"], t["beta"], v - t["u"]) - (v - t["u"])
        k = 200
        qs = [self.var(1 - (1 - p) * (i + 0.5) / k, side) for i in range(k)]
        return sum(qs) / k

    # -- compact form for the brief
    def to_json(self) -> dict:
        r = lambda x: round(x, 4)                                          # noqa: E731
        side = lambda t: None if t is None else {"u": r(t["u"]), "xi": r(t["xi"]), "beta": r(t["beta"]), "zeta": r(t["zeta"]), "n": t["n"]}   # noqa: E731
        return {"body": [r(x) for x in self.body], "lo": side(self.lo), "hi": side(self.hi), "n": self.n}

    @classmethod
    def from_json(cls, d) -> "Tail | None":
        try:
            body = [float(x) for x in d["body"]]
            if len(body) != len(BODY) or any(not math.isfinite(x) for x in body) or body != sorted(body):
                return None
            sides = []
            for k in ("lo", "hi"):
                t = d.get(k)
                if t is None:
                    sides.append(None)
                    continue
                t = {"u": float(t["u"]), "xi": float(t["xi"]), "beta": float(t["beta"]), "zeta": float(t["zeta"]), "n": int(t["n"])}
                if not (t["beta"] > 0 and 0 < t["zeta"] < 0.5 and XI_CLIP[0] <= t["xi"] <= XI_CLIP[1] and all(math.isfinite(v) for v in t.values())):
                    return None
                sides.append(t)
            return cls(body, sides[0], sides[1], int(d.get("n", 0)))
        except (KeyError, TypeError, ValueError):
            return None


def _empirical_q(sorted_z: list[float], p: float) -> float:
    n = len(sorted_z)
    x = p * (n - 1)
    i = int(x)
    return sorted_z[i] + (sorted_z[min(i + 1, n - 1)] - sorted_z[i]) * (x - i)


# ---------------------------------------------------------------------------------------------------------------- a series, all horizons
def fit_series(closes: list[float]) -> dict | None:
    """From daily closes (oldest first): {"sigma": today's EWMA daily volatility, "n": returns, "h": {h: Tail json}, "backtest": the 1-day 99% VaR's out-of-sample record}."""
    rets = log_returns(closes)
    sig = ewma_sigma(rets)
    if len(rets) < MIN_OBS or not sig:
        return None
    lp = [0.0]
    for r in rets:
        lp.append(lp[-1] + r)
    mean = sum(rets) / len(rets)                                            # history's drift is no forecast: it is taken out
    out = {"sigma": round(sig[-1], 6), "n": len(rets), "h": {}}
    for h in HORIZONS:
        z = []
        for t in range(EWMA_SEED, len(rets) - h + 1):                       # the h-day return from day t, standardised by the volatility known before it
            if sig[t] > 0:
                z.append((lp[t + h] - lp[t] - h * mean) / (sig[t] * math.sqrt(h)))
        tl = Tail.fit(z)
        if tl is not None:
            out["h"][str(h)] = tl.to_json()
    if not out["h"]:
        return None
    out["backtest"] = backtest(rets, sig, mean)
    return out


def backtest(rets: list[float], sig: list[float], mean: float = 0.0, test: int = 500, p: float = 0.99) -> dict | None:
    """Out of sample: the 1-day tail fitted on everything before the last `test` days, then each of those days' loss against that day's VaR_p (the model's sigma that morning).
    {"days", "breaches", "expected", "kupiec_p"}: a p-value under 0.05 says the model's 1% is not 1%."""
    if len(rets) < MIN_OBS + test or len(sig) < len(rets):
        return None
    z = [(rets[t] - mean) / sig[t] for t in range(EWMA_SEED, len(rets) - test) if sig[t] > 0]
    tl = Tail.fit(z)
    if tl is None:
        return None
    v = tl.var(p, "loss")
    x = sum(1 for t in range(len(rets) - test, len(rets)) if -(rets[t] - mean) > v * sig[t])
    return {"days": test, "breaches": x, "expected": round(test * (1 - p), 1), "kupiec_p": round(kupiec(test, x, 1 - p), 3)}


def kupiec(n: int, x: int, p: float) -> float:
    """Kupiec's proportion-of-failures test: LR = -2 ln[(1 - p)^(n - x) p^x / ((1 - x/n)^(n - x) (x/n)^x)], chi-squared with one degree of freedom under the model; returns
    its p-value (high: the breach count is what the model promised)."""
    if n <= 0:
        return 1.0
    f = x / n

    def ll(q):
        return (n - x) * (math.log(1 - q) if q < 1 else -math.inf) + (x * math.log(q) if x else 0.0)
    lr = -2 * (ll(p) - (ll(f) if 0 < f < 1 else (0.0 if f == 0 and x == 0 else ll(min(max(f, 1e-12), 1 - 1e-12)))))
    lr = max(lr, 0.0)
    return math.erfc(math.sqrt(lr / 2))                                     # P(chi2_1 > lr)


# ---------------------------------------------------------------------------------------------------------------- what AUTO v2 asks
class Model:
    """One underlying's fitted tails (fit_series' output, read back from the brief)."""

    def __init__(self, d: dict):
        self.sigma = float(d["sigma"])
        self.h = {int(k): t for k, v in (d.get("h") or {}).items() if (t := Tail.from_json(v)) is not None}
        if not (self.sigma > 0 and math.isfinite(self.sigma) and self.h):
            raise ValueError("no usable tail")
        self.backtest = d.get("backtest")

    @classmethod
    def read(cls, d) -> "Model | None":
        try:
            return cls(d)
        except (KeyError, TypeError, ValueError):
            return None

    def horizon(self, days: int) -> tuple[Tail, float]:
        """(the Tail of the smallest fitted horizon >= days, sqrt(days)): z at horizon h is the h-day return over sigma sqrt(h), so a `days`-day return is
        sigma sqrt(days) z, its shape taken from the nearest horizon at or above (beyond the longest, the longest's shape)."""
        hs = sorted(self.h)
        h = next((x for x in hs if x >= days), hs[-1])
        return self.h[h], math.sqrt(max(days, 1))

    def dist(self, days: int, sigma: float | None = None) -> tuple[Tail, float]:
        """(Tail, scale): the log return over `days` sessions is scale * z. sigma: today's daily volatility if it is known better than the brief's (never lower)."""
        tl, root_h = self.horizon(days)
        return tl, max(self.sigma, sigma or 0.0) * root_h

    def var_pct(self, p: float = 0.99, days: int = 1, side: str = "loss") -> float:
        tl, sc = self.dist(days)
        x = tl.var(p, side) * sc
        return (1 - math.exp(-x)) * 100 if side == "loss" else (math.exp(x) - 1) * 100

    def es_pct(self, p: float = 0.99, days: int = 1, side: str = "loss") -> float:
        tl, sc = self.dist(days)
        x = tl.es(p, side) * sc
        return (1 - math.exp(-x)) * 100 if side == "loss" else (math.exp(x) - 1) * 100

    def expected_payoff(self, payoff, spot: float, days: int, sigma: float | None = None) -> float:
        """E[payoff(S_T)] with S_T = spot * exp(scale * Z), integrated over the whole fitted distribution of Z by quadrature in normal scores: for t on a grid over
        [-QUAD_T, QUAD_T], u = Phi(t) and the weight is phi(t) dt, so the tails get as many points as the body."""
        tl, sc = self.dist(days, sigma)
        dt = 2 * QUAD_T / (QUAD_N - 1)
        tot = wsum = 0.0
        for i in range(QUAD_N):
            t = -QUAD_T + i * dt
            w = _N.pdf(t) * dt
            tot += w * payoff(spot * math.exp(sc * tl.quantile(_N.cdf(t))))
            wsum += w
        return tot / wsum
