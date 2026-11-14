"""Probation (B), v3: the session's reading is scaled by its own trade count. z = x / (sd * sqrt(1/k + RHO_REG * (1 - 1/k))), x the mean R of the k trades the strategy
closed that session, sd the population sd of its cumulative R before the session (floor 0.5), RHO_REG a registered within-session correlation. One trade: z = R / sd
whatever RHO_REG; many trades: the session mean's spread if they share a market to RHO_REG. g <- max(0, g - z - K), demoted at g > H.

Grid: trades a session m in (1, 2, 5, 10) (1 + Poisson(m - 1)), true within-session correlation rho in (0, 0.3, 0.6), three R shapes (normal; credit-like +0.5/-1;
+2/-1), a strategy closing trades on half the sessions (no closes: no update). Horizons are CALENDAR sessions."""
import numpy as np
from statistics import NormalDist
rng = np.random.default_rng(53)
M = 25
def two_point(N, T, mu, hi, lo, rho):
    cut = NormalDist().inv_cdf((mu - lo) / (hi - lo))
    e = np.sqrt(rho) * rng.normal(0, 1, (N, T, 1)) + np.sqrt(1 - rho) * rng.normal(0, 1, (N, T, M))
    return np.where(e < cut, hi, lo)
def series(N, T, path, kind, m, rho, active=0.5):
    k = np.minimum(1 + rng.poisson(m - 1, (N, T)), M) * (rng.random((N, T)) < active)
    out = np.zeros((N, T, M))
    for (a, b), mu in path:
        if kind == "normal":
            out[:, a:b] = mu + np.sqrt(rho) * rng.normal(0, 1, (N, b - a, 1)) + np.sqrt(1 - rho) * rng.normal(0, 1, (N, b - a, M))
        elif kind == "credit":
            out[:, a:b] = two_point(N, b - a, mu, 0.5, -1.0, rho)
        else:
            out[:, a:b] = two_point(N, b - a, mu, 2.0, -1.0, rho)
    mask = np.arange(M)[None, None, :] < k[:, :, None]
    return out, mask
def cusum(out, mask, K, H, rho_reg, warm_trades=8, floor=0.5):
    N, T, _ = out.shape
    tot = np.where(mask, out, 0).sum(2); cnt = mask.sum(2); sq = np.where(mask, out * out, 0).sum(2)
    cn, cs, css = np.cumsum(cnt, 1), np.cumsum(tot, 1), np.cumsum(sq, 1)
    g = np.zeros(N); hit = np.full(N, -1)
    for t in range(1, T):
        n = cn[:, t - 1]; k = cnt[:, t]
        live = (n >= warm_trades) & (k > 0) & (hit < 0)
        nn = np.maximum(n, 1); mean = cs[:, t - 1] / nn
        sd = np.maximum(np.sqrt(np.maximum(css[:, t - 1] / nn - mean * mean, 0)), floor)
        kk = np.maximum(k, 1)
        z = (tot[:, t] / kk) / (sd * np.sqrt(1 / kk + rho_reg * (1 - 1 / kk)))
        g = np.where(live, np.maximum(0.0, g - z - K), g)
        new = live & (g > H); hit[new] = t
    return hit
def grid(K, H, rho_reg, N=2000):
    worst_fa3, worst_fa15, rows = 0, 0, []
    for kind in ("normal", "credit", "2/-1"):
        for m in (1, 2, 5, 10):
            for rho in (0.0, 0.3, 0.6):
                o, mk = series(N, 250, [((0, 250), 0.3)], kind, m, rho); h = cusum(o, mk, K, H, rho_reg)
                fa3 = ((h >= 0) & (h < 120)).mean(); fa3l = (h >= 0).mean()
                o, mk = series(N, 120, [((0, 120), 0.15)], kind, m, rho); h = cusum(o, mk, K, H, rho_reg)
                fa15 = (h >= 0).mean()
                o, mk = series(N, 200, [((0, 40), 0.3), ((40, 200), -0.3)], kind, m, rho); h = cusum(o, mk, K, H, rho_reg)
                late = h[h >= 40] - 40
                rows.append((kind, m, rho, fa3, fa3l, fa15, len(late) / N, np.median(late) if len(late) else np.nan))
                worst_fa3, worst_fa15 = max(worst_fa3, fa3), max(worst_fa15, fa15)
    return worst_fa3, worst_fa15, rows
REGISTERED = (0.25, 5, 0.45)
if __name__ == "__main__":
    print("v3 per-session CUSUM, z scaled by the session's trade count; horizons in calendar sessions, a strategy closing trades on half of them; N 2,000 a cell")
    for K, H, rr in ((0.25, 4, 0.6), (0.25, 5, 0.6), (0.3, 5, 0.6), (0.25, 6, 0.6), (0.3, 6, 0.6), (0.25, 5, 0.3), REGISTERED):
        w3, w15, rows = grid(K, H, rr)
        caught = [r[6] for r in rows]; med = [r[7] for r in rows]
        tag = "  <- registered" if (K, H, rr) == REGISTERED else ""
        print(f"K={K} H={H} RHO_REG={rr}: worst false demotion at +0.3R within 120 sessions {w3:.2f}, at +0.15R {w15:.2f} | a +0.3 -> -0.3R turn caught "
              f"{min(caught):.2f}-{max(caught):.2f}, median {np.nanmin(med):.0f}-{np.nanmax(med):.0f} sessions after it{tag}")
        if (K, H, rr) == REGISTERED:
            for r in rows:
                print(f"    {r[0]:7s} m={r[1]:2d} rho={r[2]:.1f}: FA +0.3R {r[3]:.2f} (120) {r[4]:.2f} (250), +0.15R {r[5]:.2f} (120) | caught {r[6]:.2f} median {r[7]:.0f}")
