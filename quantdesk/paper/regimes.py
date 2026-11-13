"""Regimes and change points (owner, 13 Nov 2026: "Add HMM regime detection and CUSUM change points"). PAPER MONEY ONLY; nothing here trades.

HIDDEN MARKOV MODEL. The market is taken to be in one of three hidden states, CALM, ACTIVE and STRESSED, each with its own distribution of one-minute log returns
(Gaussian, its own mean and variance), and to move between them by a Markov chain. The parameters (start, transition matrix, means, variances) are fitted to the underlying's
last MAX_BARS minutes by Baum-Welch (expectation-maximisation, with scaled forward-backward passes so a long series does not underflow); the states are then named by their
variance (the smallest is CALM). Between fits, each new minute updates the filtered probability of each state by one forward step: P(state now | every return so far).
STRESSED above STRESS_P is the regime in which AUTO v2 sells no volatility (as in an event); CALM is where selling it is most at home.

CUSUM (Page's cumulative sum). Two change detectors on each new one-minute return, standardised by a robust scale (the median absolute deviation of the window):
* MEAN: S+ = max(0, S+ + z - k) and S- = max(0, S- - z - k); S+ above h is a change to drifting up, S- above h to drifting down (k = 0.5 sd, h = 5: about one false alarm in
  several hundred minutes of pure noise);
* VOLATILITY: V = max(0, V + ((z - m)^2 - 1) - kv) around an exponentially weighted running mean m (kv = 1, hv = 10: about one false alarm per 500 minutes of noise),
  above hv a change to higher volatility.
An alarm records a change point (the time and its kind) and resets the sums. A fresh mean change (within CHANGE_FRESH_S) is a vote in AUTO v2's view; a fresh volatility
change is, like STRESSED, the event regime.

Standard library only (paper package rules). Every function is deterministic given its input.
"""
from __future__ import annotations

import math

K = 3                                   # calm, active, stressed
NAMES = ("calm", "active", "stressed")
MIN_BARS = 60                           # an hour of minutes before the model says anything
MAX_BARS = 390                          # a session of minutes is what it is fitted to
REFIT_S = 300                           # Baum-Welch every five minutes; one forward step a minute between
EM_ITERS = 25
VAR_FLOOR = 1e-10
STRESS_P = 0.6
SEPARATION = 2.0                        # the stressed state's sd must be at least twice the calm one's, or the series has no distinct regimes (one regime: calm)
CUSUM_EWMA = 0.2                        # the running mean the volatility CUSUM measures deviations from, so a drift is not read as turbulence
CUSUM_K, CUSUM_H = 0.5, 5.0
CUSUM_KV, CUSUM_HV = 1.0, 10.0          # calibrated on pure noise: about one false volatility alarm per 500 minutes, as the mean detector
CUSUM_MIN_RETURNS = 30                  # no change detection before half an hour of returns gives the robust scale something to stand on
CHANGE_FRESH_S = 900


# ---------------------------------------------------------------------------------------------------------------- the hidden Markov model
def _pdf(x: float, mu: float, var: float) -> float:
    return math.exp(-(x - mu) ** 2 / (2 * var)) / math.sqrt(2 * math.pi * var)


def _init(obs: list[float]) -> tuple[list, list, list, list]:
    """Starting values: equal start probabilities, sticky transitions, zero means, variances at the 20th, 60th and 95th percentiles of the squared returns."""
    sq = sorted(x * x for x in obs)
    pick = lambda q: max(sq[min(len(sq) - 1, int(q * len(sq)))], VAR_FLOOR)       # noqa: E731
    var = [pick(0.2), pick(0.6), pick(0.95)]
    if not (var[0] < var[1] < var[2]):
        m = max(sum(sq) / len(sq), VAR_FLOOR)
        var = [m * 0.4, m, m * 4]
    A = [[0.95 if i == j else 0.025 for j in range(K)] for i in range(K)]
    return [1 / K] * K, A, [0.0] * K, var


def _forward_backward(obs, pi, A, mu, var):
    """Scaled forward-backward: (alpha, beta, scales, log-likelihood)."""
    n = len(obs)
    B = [[max(_pdf(x, mu[k], var[k]), 1e-300) for k in range(K)] for x in obs]
    alpha, scale = [[0.0] * K for _ in range(n)], [0.0] * n
    for k in range(K):
        alpha[0][k] = pi[k] * B[0][k]
    scale[0] = sum(alpha[0]) or 1e-300
    alpha[0] = [a / scale[0] for a in alpha[0]]
    for t in range(1, n):
        for j in range(K):
            alpha[t][j] = sum(alpha[t - 1][i] * A[i][j] for i in range(K)) * B[t][j]
        scale[t] = sum(alpha[t]) or 1e-300
        alpha[t] = [a / scale[t] for a in alpha[t]]
    beta = [[1.0] * K for _ in range(n)]
    for t in range(n - 2, -1, -1):
        for i in range(K):
            beta[t][i] = sum(A[i][j] * B[t + 1][j] * beta[t + 1][j] for j in range(K)) / scale[t + 1]
    return alpha, beta, B, sum(math.log(s) for s in scale)


def fit_hmm(obs: list[float], iters: int = EM_ITERS) -> dict | None:
    """Baum-Welch on the returns `obs`. The fitted model with its states ordered calm to stressed, the log-likelihood and the filtered probabilities of the last
    observation; None with too few observations."""
    if len(obs) < MIN_BARS:
        return None
    pi, A, mu, var = _init(obs)
    ll_old = -math.inf
    n = len(obs)
    for _ in range(iters):
        alpha, beta, B, ll = _forward_backward(obs, pi, A, mu, var)
        gamma = []
        for t in range(n):
            g = [alpha[t][k] * beta[t][k] for k in range(K)]
            s = sum(g) or 1e-300
            gamma.append([x / s for x in g])
        xi_sum = [[0.0] * K for _ in range(K)]
        for t in range(n - 1):
            den = 0.0
            tmp = [[0.0] * K for _ in range(K)]
            for i in range(K):
                for j in range(K):
                    tmp[i][j] = alpha[t][i] * A[i][j] * B[t + 1][j] * beta[t + 1][j]
                    den += tmp[i][j]
            den = den or 1e-300
            for i in range(K):
                for j in range(K):
                    xi_sum[i][j] += tmp[i][j] / den
        pi = gamma[0][:]
        for i in range(K):
            row = sum(xi_sum[i]) or 1e-300
            A[i] = [max(x / row, 1e-6) for x in xi_sum[i]]
            s = sum(A[i])
            A[i] = [x / s for x in A[i]]
        for k in range(K):
            w = sum(g[k] for g in gamma) or 1e-300
            mu[k] = sum(g[k] * x for g, x in zip(gamma, obs)) / w
            var[k] = max(sum(g[k] * (x - mu[k]) ** 2 for g, x in zip(gamma, obs)) / w, VAR_FLOOR)
        if ll - ll_old < 1e-6 * abs(ll or 1):
            break
        ll_old = ll
    order = sorted(range(K), key=lambda k: var[k])                   # name the states by their variance: calm, active, stressed
    alpha, _, _, ll = _forward_backward(obs, pi, A, mu, var)
    last = alpha[-1]
    # MODEL SELECTION: is there more than one regime at all? The Bayesian information criterion of the three-state model (14 free parameters) against one Gaussian (2):
    # BIC = -2 log-likelihood + parameters x log n. Unless the HMM's is lower, the series is one regime, and calling part of it "stressed" would be reading noise.
    m1 = sum(obs) / n
    v1 = max(sum((x - m1) ** 2 for x in obs) / n, VAR_FLOOR)
    ll1 = sum(math.log(max(_pdf(x, m1, v1), 1e-300)) for x in obs)
    bic_hmm, bic_one = -2 * ll + (K - 1 + K * (K - 1) + 2 * K) * math.log(n), -2 * ll1 + 2 * math.log(n)
    return {"pi": [pi[k] for k in order], "A": [[A[i][j] for j in order] for i in order], "mu": [mu[k] for k in order], "var": [var[k] for k in order],
            "ll": ll, "p": [last[k] for k in order], "regimes": bic_hmm < bic_one, "bic": (round(bic_hmm, 1), round(bic_one, 1))}


def filter_step(model: dict, p: list[float], x: float) -> list[float]:
    """One forward step: the filtered state probabilities after one more return."""
    pred = [sum(p[i] * model["A"][i][j] for i in range(K)) for j in range(K)]
    post = [pred[j] * max(_pdf(x, model["mu"][j], model["var"][j]), 1e-300) for j in range(K)]
    s = sum(post) or 1e-300
    return [v / s for v in post]


# ---------------------------------------------------------------------------------------------------------------- CUSUM
def _mad(xs: list[float]) -> float:
    if not xs:
        return 0.0
    m = sorted(xs)[len(xs) // 2]
    d = sorted(abs(x - m) for x in xs)
    return 1.4826 * d[len(d) // 2]                                   # a robust standard deviation


class Cusum:
    """Page's two-sided CUSUM on the mean and a one-sided one on the variance of standardised returns."""

    def __init__(self, k=CUSUM_K, h=CUSUM_H, kv=CUSUM_KV, hv=CUSUM_HV):
        self.k, self.h, self.kv, self.hv = k, h, kv, hv
        self.up = self.dn = self.v = 0.0
        self.m = 0.0                                                  # an exponentially weighted running mean of z

    def step(self, z: float) -> str | None:
        """Feed one standardised return; the change it signals ("volatility up", "drift up", "drift down") or None. Volatility is read around the running mean,
        so a steady drift is a drift and not turbulence; it is checked first, so turbulence is never mistaken for a drift."""
        self.up = max(0.0, self.up + z - self.k)
        self.dn = max(0.0, self.dn - z - self.k)
        self.v = max(0.0, self.v + ((z - self.m) ** 2 - 1.0) - self.kv)
        self.m += CUSUM_EWMA * (z - self.m)
        out = None
        if self.v > self.hv:
            out = "volatility up"
        elif self.up > self.h:
            out = "drift up"
        elif self.dn > self.h:
            out = "drift down"
        if out:
            self.up = self.dn = self.v = 0.0
        return out


# ---------------------------------------------------------------------------------------------------------------- per underlying
class RegimeBook:
    """For each underlying: its one-minute closes, the fitted HMM and its filtered state, and its CUSUM change points."""

    def __init__(self):
        self.bars: dict[str, list[tuple[int, float]]] = {}            # (minute, close)
        self.models: dict[str, dict] = {}
        self.p: dict[str, list[float]] = {}
        self.fit_at: dict[str, float] = {}
        self.cusum: dict[str, Cusum] = {}
        self.changes: dict[str, list[tuple[float, str]]] = {}

    def update(self, u: str, t: float, price: float) -> None:
        """Feed the latest price; work happens only when a minute closes."""
        if not (price and price > 0):
            return
        m = int(t // 60)
        b = self.bars.setdefault(u, [])
        if b and b[-1][0] == m:                                        # the same minute: its close moves
            b[-1] = (m, price)
            return
        just, prev = (b[-1] if b else None), (b[-2] if len(b) >= 2 else None)     # a new minute: the bar before it has closed
        b.append((m, price))
        if len(b) > MAX_BARS + 2:
            b.pop(0)
        if just is None or prev is None:
            return
        (m0, c0), (m1, c1) = prev, just
        if c0 <= 0 or m1 - m0 > 30:                                  # a gap (the close, a halt) is not a return
            return
        r = math.log(c1 / c0)
        rets = self.returns(u)
        scale = _mad(rets[-120:]) or (math.sqrt(sum(x * x for x in rets[-120:]) / max(len(rets[-120:]), 1)) if rets else 0.0)
        if scale > 0 and len(rets) >= CUSUM_MIN_RETURNS:
            ch = self.cusum.setdefault(u, Cusum()).step(r / scale)
            if ch:
                lst = self.changes.setdefault(u, [])
                lst.append((t, ch))
                del lst[:-10]
        model = self.models.get(u)
        if t - self.fit_at.get(u, -1e18) >= REFIT_S or model is None:
            self.fit_at[u] = t
            fitted = fit_hmm(rets[-MAX_BARS:])
            if fitted:
                self.models[u], self.p[u] = fitted, fitted["p"]
        elif model is not None:
            self.p[u] = filter_step(model, self.p.get(u, model["p"]), r)

    def returns(self, u: str) -> list[float]:
        b = self.bars.get(u) or []
        out = []
        for (m0, c0), (m1, c1) in zip(b, b[1:-1]):                    # closed minutes only (the last bar is still forming)
            if c0 > 0 and c1 > 0 and m1 - m0 <= 30:
                out.append(math.log(c1 / c0))
        return out

    def state(self, u: str, t: float) -> dict:
        """{"hmm": name or None, "p": {name: probability}, "stress": bool, "change": the freshest change point within CHANGE_FRESH_S or None, "vote": +1/-1/0}"""
        p = self.p.get(u)
        fresh = [(ts, c) for ts, c in (self.changes.get(u) or []) if t - ts <= CHANGE_FRESH_S]
        change = fresh[-1][1] if fresh else None
        out = {"hmm": None, "p": None, "stress": False, "change": change, "vote": 1 if change == "drift up" else -1 if change == "drift down" else 0}
        model = self.models.get(u)
        if p and model and (not model.get("regimes", True) or model["var"][2] < SEPARATION ** 2 * model["var"][0]):
            out.update(hmm="calm", p={"calm": 1.0, "active": 0.0, "stressed": 0.0})        # no distinct regimes: one, and it is not stress
        elif p:
            k = max(range(K), key=lambda i: p[i])
            out.update(hmm=NAMES[k], p={NAMES[i]: round(p[i], 3) for i in range(K)}, stress=p[2] >= STRESS_P)
        if change == "volatility up":
            out["stress"] = True
        return out
