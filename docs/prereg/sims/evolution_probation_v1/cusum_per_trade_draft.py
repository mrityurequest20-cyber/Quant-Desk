"""The simulation behind evolution_forgetting_v1's probation parameters (K, H): how often a CUSUM on 'losing on average' demotes a strategy that
still has an edge, and how fast it catches one whose edge turned. Not part of the desk; run by hand: python docs/prereg/evolution_forgetting_v1_sim.py"""
import numpy as np
rng = np.random.default_rng(11)
def gen(shape, mu, kind):
    if kind == "normal": return rng.normal(mu, 1.0, shape)
    if kind == "twopoint": return np.where(rng.random(shape) < (mu + 1) / 2, 1.0, -1.0)
    # skewed: tp 2R / sl 1R, p chosen for mean mu
    p = (mu + 1) / 3; return np.where(rng.random(shape) < p, 2.0, -1.0)
def run(kind, k, h, pre, post, mu0, mu1, warm=8, N=4000):
    T = warm + pre + post
    x = np.concatenate([gen((N, warm + pre), mu0, kind), gen((N, post), mu1, kind)], axis=1)
    cs, css = np.cumsum(x, 1), np.cumsum(x * x, 1)
    g = np.zeros(N); hit = np.full(N, -1)
    for i in range(warm, T):
        m = cs[:, i - 1] / i; sd = np.sqrt(np.maximum(css[:, i - 1] / i - m * m, 0.25))
        g = np.maximum(0.0, g - x[:, i] / sd - k)
        new = (g > h) & (hit < 0); hit[new] = i - warm
    return hit
print("CUSUM on 'losing on average': g = max(0, g - R/sd - k), alarm g > h")
for kind in ("normal", "twopoint", "skewed"):
    for k, h in ((0.1, 5), (0.15, 5), (0.15, 6), (0.2, 5), (0.2, 6), (0.25, 5)):
        fa3 = (run(kind, k, h, 150, 0, 0.3, 0.3) >= 0).mean()
        fa1 = (run(kind, k, h, 150, 0, 0.15, 0.15) >= 0).mean()
        hh = run(kind, k, h, 30, 120, 0.3, -0.3)
        early = ((hh >= 0) & (hh < 30)).mean(); late = hh[hh >= 30] - 30
        print(f"{kind:8s} k={k} h={h}  FA/150 at +0.3R {fa3:.3f}, at +0.15R {fa1:.3f} | +0.3 -> -0.3R caught {len(late)/len(hh):.2f} median {np.median(late):.0f} p90 {np.percentile(late,90):.0f} (early {early:.2f})")


# ---- the calibration watch (C): the share of time a model is muted ---------------------------------------------------------------------------------------
def watch(p_fore, p_true, alpha=0.01, min_n=100, mute=0.255, unmute=0.25, T=2000, N=2000):
    """Forecasts of p_fore (or 1 - p_fore, at random) for an event of probability p_true when forecast up; T scored forecasts each."""
    up = rng.random((N, T)) < 0.5
    p = np.where(up, p_fore, 1 - p_fore)
    y = np.where(up, rng.random((N, T)) < p_true, rng.random((N, T)) >= p_true).astype(float)
    b = (p - y) ** 2
    ew = np.full(N, 0.25); muted = np.zeros(N, bool); time_muted = np.zeros(N)
    for i in range(T):
        ew = (1 - alpha) * ew + alpha * b[:, i]
        if i + 1 >= min_n:
            muted = np.where(muted, ew >= unmute, ew > mute)
            time_muted += muted
    return (time_muted / (T - min_n + 1)).mean()
print("calibration watch: share of time muted (alpha 0.01, at least 100 scored, mute above 0.255, unmute under 0.25)")
for label, pf, pt in (("skilled, calibrated (Brier 0.24)", 0.6, 0.6), ("slight skill (Brier 0.248)", 0.6, 0.55), ("no skill, says 0.6 (Brier 0.26)", 0.6, 0.5),
                      ("wrong way (Brier 0.28)", 0.6, 0.4), ("no skill, says 0.55 (Brier 0.2525)", 0.55, 0.5)):
    print(f"  {label:36s} {watch(pf, pt):.2f}")
