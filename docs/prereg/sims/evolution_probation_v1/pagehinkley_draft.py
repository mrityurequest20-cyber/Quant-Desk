"""The draft (evolution_forgetting_v1, never committed): Page-Hinkley against the running record, per trade. Superseded; kept as the evidence that it caught too little."""
import numpy as np
rng = np.random.default_rng(7)
def gen(shape, mu, kind):
    if kind == "normal": return rng.normal(mu, 1.0, shape)
    p = (mu + 1) / 2                                     # +1 / -1 two-point, sd ~1
    return np.where(rng.random(shape) < p, 1.0, -1.0)
def run(kind, delta, lam, pre, post, mu0, mu1, warm=8, N=4000):
    T = warm + pre + post
    x = np.concatenate([gen((N, warm + pre), mu0, kind), gen((N, post), mu1, kind)], axis=1)
    cs, css = np.cumsum(x, 1), np.cumsum(x * x, 1)
    g = np.zeros(N); hit = np.full(N, -1)
    for i in range(warm, T):
        n = i; m = cs[:, i - 1] / n; sd = np.sqrt(np.maximum(css[:, i - 1] / n - m * m, 0.09))
        g = np.maximum(0.0, g + (m - x[:, i]) / sd - delta)
        new = (g > lam) & (hit < 0); hit[new] = i - warm
    return hit
for kind in ("normal", "twopoint"):
    for delta in (0.5, 0.75):
        for lam in (6, 8, 10):
            fa = (run(kind, delta, lam, 150, 0, 0.3, 0.3) >= 0).mean()
            h = run(kind, delta, lam, 30, 120, 0.3, -0.3)
            early = ((h >= 0) & (h < 30)).mean(); late = h[h >= 30] - 30
            print(f"{kind:8s} d={delta} lam={lam:2d}  false alarm/150 trades {fa:.3f} | caught {len(late)/len(h):.2f} median {np.median(late) if len(late) else 'na'} p90 {np.percentile(late,90) if len(late) else 'na'}")
