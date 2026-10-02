"""The framework's model layer, as a research library: none of this runs in the live desk's loop.

  ou_fit                Ornstein-Uhlenbeck dX = θ(μ − X)dt + σdW, fitted exactly through its AR(1) discretisation
  hawkes_fit            self-exciting point process λ(t) = μ + Σ α e^{−β(t−tᵢ)}, by maximum likelihood; α/β is the share
                        of events triggered by earlier ones (clustering)
  pca                   principal components of a panel of changes (e.g. an IV surface's daily moves)
  kelly_vector          w* = Σ⁻¹μ, scaled to a Kelly fraction and capped
  heston_price          Heston (1993) European option by numerical Fourier inversion (the "little trap" form)
  heston_calibrate      least-squares fit of (v0, κ, θ, σᵥ, ρ) to a chain's prices
  almgren_chriss        optimal liquidation path and its expected cost / variance
  avellaneda_stoikov    a market maker's reservation price and optimal quote spread
  ofi                   order-flow imbalance from consecutive best quotes (Cont, Kukanov & Stoikov 2014)
  vpin                  volume-synchronised probability of informed trading, with bulk volume classification

Hurst, variance ratio, OU half-life, Kalman hedge ratio, GARCH, HMM and SVI already live in analytics/stats,
analytics/volatility, analytics/regime and options/surface."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import integrate, optimize
from scipy.special import ndtr


# ---- stochastic processes --------------------------------------------------------------------------------------------
def ou_fit(x, dt: float = 1.0) -> dict:
    """Exact OU fit: X_{t+1} = a + b·X_t + ε with b = e^{−θdt}, μ = a/(1−b), σ² = 2θ·var(ε)/(1−b²)."""
    x = np.asarray(pd.Series(x).dropna(), dtype=float)
    if len(x) < 10:
        return {}
    X, Y = x[:-1], x[1:]
    b, a = np.polyfit(X, Y, 1)
    eps = Y - (a + b * X)
    if not 0 < b < 1:
        return {"theta": float("nan"), "mu": float("nan"), "sigma": float("nan"), "half_life": float("inf"), "b": float(b),
                "mean_reverting": False}
    theta = -math.log(b) / dt
    var = eps.var(ddof=2)
    return {"theta": theta, "mu": a / (1 - b), "sigma": math.sqrt(2 * theta * var / (1 - b * b)),
            "half_life": math.log(2) / theta, "b": float(b), "mean_reverting": True}


def hawkes_loglik(params, t: np.ndarray, T: float) -> float:
    mu, alpha, beta = params
    if mu <= 0 or alpha < 0 or beta <= 0 or alpha >= beta:
        return -1e18
    A, ll, prev = 0.0, 0.0, None
    for ti in t:
        if prev is not None:
            A = math.exp(-beta * (ti - prev)) * (1 + A)
        ll += math.log(mu + alpha * A)
        prev = ti
    ll -= mu * T + (alpha / beta) * np.sum(1 - np.exp(-beta * (T - t)))
    return float(ll)


def hawkes_fit(times, T: float | None = None) -> dict:
    """Exponential-kernel Hawkes MLE on event times (any unit). branching = α/β: 0 = Poisson, → 1 = self-feeding."""
    t = np.sort(np.asarray(times, dtype=float))
    if len(t) < 10:
        return {}
    t = t - t[0]
    T = float(T if T is not None else t[-1] * 1.0001 + 1e-9)
    rate = len(t) / T
    best = None
    for a0, b0 in ((0.3, 1.0), (0.5, 2.0), (0.2, 0.5)):
        x0 = [rate * (1 - a0 / b0), a0 * rate * 5, b0 * rate * 5]
        r = optimize.minimize(lambda p: -hawkes_loglik(p, t, T), x0, method="Nelder-Mead",
                              options={"maxiter": 4000, "xatol": 1e-8, "fatol": 1e-8})
        if best is None or r.fun < best.fun:
            best = r
    mu, alpha, beta = best.x
    return {"mu": float(mu), "alpha": float(alpha), "beta": float(beta), "branching": float(alpha / beta),
            "loglik": float(-best.fun), "n": len(t)}


# ---- linear algebra ----------------------------------------------------------------------------------------------------
def pca(panel: pd.DataFrame, k: int = 3) -> dict:
    """PCA of a panel (rows = dates, columns = e.g. moneyness buckets of IV changes), standardised."""
    X = panel.dropna().to_numpy(dtype=float)
    X = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1)
    _, s, vt = np.linalg.svd(X, full_matrices=False)
    var = s ** 2 / np.sum(s ** 2)
    return {"explained": var[:k].tolist(), "loadings": pd.DataFrame(vt[:k].T, index=panel.columns,
                                                                    columns=[f"PC{i + 1}" for i in range(k)])}


def kelly_vector(mu, cov, fraction: float = 0.5, max_gross: float = 1.0, ridge: float = 1e-6) -> np.ndarray:
    """Multi-asset Kelly w* = Σ⁻¹μ (per-period mean returns and covariance), times a Kelly fraction, scaled down so
    the gross exposure Σ|w| stays within `max_gross`."""
    mu, cov = np.asarray(mu, dtype=float), np.asarray(cov, dtype=float)
    w = np.linalg.solve(cov + ridge * np.eye(len(mu)), mu) * fraction
    gross = np.abs(w).sum()
    return w * (max_gross / gross) if gross > max_gross else w


# ---- Heston --------------------------------------------------------------------------------------------------------------
def _heston_cf(u, S, T, r, q, v0, kappa, theta, sigma, rho):
    x = math.log(S)
    d = np.sqrt((rho * sigma * 1j * u - kappa) ** 2 + sigma ** 2 * (1j * u + u ** 2))
    g = (kappa - rho * sigma * 1j * u - d) / (kappa - rho * sigma * 1j * u + d)
    C = (r - q) * 1j * u * T + kappa * theta / sigma ** 2 * (
        (kappa - rho * sigma * 1j * u - d) * T - 2 * np.log((1 - g * np.exp(-d * T)) / (1 - g)))
    D = (kappa - rho * sigma * 1j * u - d) / sigma ** 2 * (1 - np.exp(-d * T)) / (1 - g * np.exp(-d * T))
    return np.exp(C + D * v0 + 1j * u * x)


def heston_price(S, K, T, r, q, v0, kappa, theta, sigma, rho, right: str = "CE") -> float:
    """European option under Heston: P₁/P₂ probabilities by Gil-Pelaez inversion of the characteristic function."""
    lnK = math.log(K)

    def p(j):
        def f(u):
            if j == 1:
                num = _heston_cf(u - 1j, S, T, r, q, v0, kappa, theta, sigma, rho)
                den = _heston_cf(-1j, S, T, r, q, v0, kappa, theta, sigma, rho)
                val = np.exp(-1j * u * lnK) * num / (1j * u * den)
            else:
                val = np.exp(-1j * u * lnK) * _heston_cf(u, S, T, r, q, v0, kappa, theta, sigma, rho) / (1j * u)
            return float(np.real(val))
        return 0.5 + integrate.quad(f, 1e-8, 200, limit=400)[0] / math.pi
    call = S * math.exp(-q * T) * p(1) - K * math.exp(-r * T) * p(2)
    if right.upper().startswith("C"):
        return float(call)
    return float(call - S * math.exp(-q * T) + K * math.exp(-r * T))


def heston_calibrate(S, strikes, T, r, q, prices, rights, x0=(0.02, 2.0, 0.02, 0.5, -0.5)) -> dict:
    """Least squares on prices (vega-free, so near-ATM options dominate). Bounds keep the Feller-ish region sane."""
    strikes, prices = np.asarray(strikes, float), np.asarray(prices, float)

    def resid(p):
        v0, kappa, theta, sig, rho = p
        return np.array([heston_price(S, k, T, r, q, v0, kappa, theta, sig, rho, rt) for k, rt in zip(strikes, rights)]) - prices
    r_ = optimize.least_squares(resid, x0, bounds=([1e-4, 0.1, 1e-4, 0.05, -0.99], [1.0, 15.0, 1.0, 3.0, 0.99]),
                                max_nfev=200)
    v0, kappa, theta, sig, rho = r_.x
    return {"v0": v0, "kappa": kappa, "theta": theta, "sigma_v": sig, "rho": rho,
            "rmse": float(np.sqrt(np.mean(r_.fun ** 2))), "feller": 2 * kappa * theta > sig ** 2}


# ---- execution and market making ------------------------------------------------------------------------------------------
def almgren_chriss(X: float, T: float, N: int, sigma: float, eta: float, gamma: float, lam: float) -> dict:
    """Optimal liquidation of X shares over T in N steps (Almgren & Chriss 2000): holdings x_j = X·sinh(κ(T−t_j))/sinh(κT)
    with κ² ≈ λσ²/η; temporary impact η per unit rate, permanent γ per unit, risk aversion λ."""
    tau = T / N
    k_tilde2 = lam * sigma ** 2 / (eta * (1 - gamma * tau / (2 * eta))) if eta > gamma * tau / 2 else lam * sigma ** 2 / eta
    kappa = math.acosh(1 + 0.5 * k_tilde2 * tau ** 2) / tau if k_tilde2 > 0 else 0.0
    t = np.linspace(0, T, N + 1)
    x = X * np.sinh(kappa * (T - t)) / math.sinh(kappa * T) if kappa > 0 else X * (1 - t / T)
    n = -np.diff(x)
    cost = 0.5 * gamma * X ** 2 + (eta - 0.5 * gamma * tau) / tau * np.sum(n ** 2)
    var = sigma ** 2 * tau * np.sum(x[1:] ** 2)
    return {"holdings": x, "trades": n, "expected_cost": float(cost), "variance": float(var), "kappa": kappa}


def avellaneda_stoikov(s: float, inventory: float, sigma: float, gamma: float, k: float, t_left: float) -> dict:
    """Reservation price r = s − qγσ²(T−t) and the optimal total spread δ = γσ²(T−t) + (2/γ)ln(1 + γ/k)."""
    r = s - inventory * gamma * sigma ** 2 * t_left
    spread = gamma * sigma ** 2 * t_left + (2 / gamma) * math.log(1 + gamma / k)
    return {"reservation": r, "spread": spread, "bid": r - spread / 2, "ask": r + spread / 2}


# ---- microstructure ---------------------------------------------------------------------------------------------------------
def ofi(quotes: pd.DataFrame) -> pd.Series:
    """Order-flow imbalance per update from best bid/ask prices and sizes (columns bid, bid_size, ask, ask_size):
    e_n = 1{b_n ≥ b_{n−1}}q^b_n − 1{b_n ≤ b_{n−1}}q^b_{n−1} − 1{a_n ≤ a_{n−1}}q^a_n + 1{a_n ≥ a_{n−1}}q^a_{n−1}."""
    b, qb, a, qa = (quotes[c].to_numpy(float) for c in ("bid", "bid_size", "ask", "ask_size"))
    e = ((b[1:] >= b[:-1]) * qb[1:] - (b[1:] <= b[:-1]) * qb[:-1]
         - (a[1:] <= a[:-1]) * qa[1:] + (a[1:] >= a[:-1]) * qa[:-1])
    return pd.Series(np.concatenate([[0.0], e]), index=quotes.index)


def vpin(bars: pd.DataFrame, bucket_volume: float, window: int = 50) -> pd.Series:
    """VPIN with bulk volume classification (Easley, López de Prado & O'Hara): each bar's volume is split buy/sell by
    Φ(ΔP/σ_ΔP); bars fill equal-volume buckets; VPIN = mean |V_buy − V_sell| / V over the last `window` buckets."""
    c = bars["close"].to_numpy(float)
    v = bars["volume"].to_numpy(float)
    dp = np.diff(c, prepend=c[0])
    sd = np.std(dp[1:]) if len(dp) > 2 and np.std(dp[1:]) > 0 else 1.0
    buy = v * ndtr(dp / sd)
    imb, cur_b, cur_v, ends = [], 0.0, 0.0, []
    for i in range(len(v)):
        vb, vv = buy[i], v[i]
        while vv > 0:
            take = min(vv, bucket_volume - cur_v)
            frac = take / v[i] if v[i] > 0 else 0
            cur_b += buy[i] * frac
            cur_v += take
            vv -= take
            if cur_v >= bucket_volume - 1e-9:
                imb.append(abs(2 * cur_b - cur_v) / cur_v)
                ends.append(bars.index[i])
                cur_b = cur_v = 0.0
    s = pd.Series(imb, index=ends, dtype=float)
    return s.rolling(window, min_periods=max(5, window // 5)).mean()
