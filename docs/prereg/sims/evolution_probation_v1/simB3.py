"""Probation (B), revised: the CUSUM is updated once per strategy per session, on the session's mean R over the per-trade spread (sd of the strategy's record before the
session, floored at 0.5R): g <- max(0, g - mean_s / sd - K). Trades in a session: 1 + Poisson(m - 1), sharing a common shock (rho). Three R shapes: normal; credit-like
(+0.5 / -1, short volatility); +2 / -1. Reports, per (K, H): the share demoted within 120 and 250 sessions while still holding an edge, and for an edge that turns from
+0.3R to -0.3R after 30 sessions, the share caught and the median sessions to catch."""
import numpy as np
rng = np.random.default_rng(31)
def corr_two_point(N, T, M, mu, hi, lo, rho):
    """Two-point R (hi / lo) with mean mu, trades in a session correlated through a Gaussian copula with correlation rho."""
    from statistics import NormalDist
    q = (mu - lo) / (hi - lo)
    cut = NormalDist().inv_cdf(q)
    common = rng.normal(0, 1, (N, T, 1))
    e = np.sqrt(rho) * common + np.sqrt(1 - rho) * rng.normal(0, 1, (N, T, M))
    return np.where(e < cut, hi, lo)
def series(N, T, mu_path, kind, m, rho):
    M = 25
    k = 1 + rng.poisson(m - 1, (N, T)); k = np.minimum(k, M)
    mask = np.arange(M)[None, None, :] < k[:, :, None]
    out = np.zeros((N, T, M))
    for (a, b), mu in mu_path:
        seg = slice(a, b)
        if kind == "normal":
            common = rng.normal(0, 1, (N, b - a, 1))
            out[:, seg] = mu + np.sqrt(rho) * common + np.sqrt(1 - rho) * rng.normal(0, 1, (N, b - a, M))
        elif kind == "credit":
            out[:, seg] = corr_two_point(N, b - a, M, mu, 0.5, -1.0, rho)
        else:
            out[:, seg] = corr_two_point(N, b - a, M, mu, 2.0, -1.0, rho)
    return out, mask
def cusum(out, mask, K, H, warm=2):
    N, T, M = out.shape
    tot = np.where(mask, out, 0).sum(2); cnt = mask.sum(2); sq = np.where(mask, out * out, 0).sum(2)
    cn, cs, css = np.cumsum(cnt, 1), np.cumsum(tot, 1), np.cumsum(sq, 1)
    g = np.zeros(N); hit = np.full(N, -1)
    for t in range(warm, T):
        n = cn[:, t - 1]; m_ = cs[:, t - 1] / n; sd = np.sqrt(np.maximum(css[:, t - 1] / n - m_ * m_, 0.25))
        x = tot[:, t] / cnt[:, t]
        g = np.maximum(0.0, g - x / sd - K)
        new = (g > H) & (hit < 0); hit[new] = t
    return hit
if __name__ == "__main__":
    N = 3000
    print("per session CUSUM: g <- max(0, g - session mean R / sd - K); 5 trades a session on average, within-session correlation 0.6")
    for kind in ("normal", "credit", "2/-1"):
        for K, H in ((0.25, 3), (0.25, 4), (0.3, 3), (0.3, 4), (0.4, 3)):
            r = {}
            for edge in (0.3, 0.15):
                o, m = series(N, 250, [((0, 250), edge)], kind, 5, 0.6)
                h = cusum(o, m, K, H)
                r[edge] = ((h >= 0) & (h < 120)).mean(), (h >= 0).mean()
            o, m = series(N, 150, [((0, 30), 0.3), ((30, 150), -0.3)], kind, 5, 0.6)
            h = cusum(o, m, K, H)
            caught = h[h >= 30] - 30
            print(f"{kind:7s} K={K} H={H}: false demotion at +0.3R {r[0.3][0]:.2f} (120 sessions) {r[0.3][1]:.2f} (250); at +0.15R {r[0.15][0]:.2f} / {r[0.15][1]:.2f} | "
                  f"+0.3 -> -0.3R caught {len(caught)/N:.2f}, median {np.median(caught):.0f} sessions, p90 {np.percentile(caught, 90):.0f} (early {((h >= 0) & (h < 30)).mean():.2f})")
