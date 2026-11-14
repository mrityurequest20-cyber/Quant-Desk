"""Power of evolution_forgetting_v1's test A (revised): D = sum R x (Pd - Pc) / sum |Pd - Pc|, P = Phi(mean / se) the chance a Thompson draw is positive,
session-clustered ratio estimator, t with G-1 df. Stylised book: S strategies in F families, each active in a session with probability p, one trade a session when active
(entry snapshot = the records at the session's start), a common family shock within the session (rho)."""
import math, numpy as np
from math import erf, sqrt
rng = np.random.default_rng(23)
Phi = lambda x: 0.5 * (1 + np.vectorize(erf)(x / sqrt(2)))
def tq(df, q=0.90):                                    # one-sided t quantile, by a few Newton steps on the normal start (scipy-free)
    from statistics import NormalDist
    z = NormalDist().inv_cdf(q); g1 = (z**3 + z) / 4; g2 = (5*z**5 + 16*z**3 + 3*z) / 96
    return z + g1/df + g2/df**2
def run(S=594, F=20, p=0.5, tau=0.15, sessions=120, looks=(60, 80, 100, 120), hl=60, shift=None, rho=0.4, reps=300, margin=-0.05, min_dis=300, min_ses=40, crit_q=0.95):
    lam = 0.5 ** (1 / hl)
    res = []
    for _ in range(reps):
        fam = rng.integers(0, F, S)
        mu_f = rng.normal(0.05, 0.1, F); th = mu_f[fam] + rng.normal(0, tau, S)
        n = np.zeros(S); s = np.zeros(S); ss = np.zeros(S); ne = np.zeros(S); se_ = np.zeros(S)
        num, den, ndis = [], [], []
        verdict = None
        for t in range(sessions):
            if shift is not None and t == shift[0]:
                hit = rng.random(F) < shift[2]                       # these families' edges turn
                th = th + np.where(hit[fam], shift[1], 0.0)
            ne *= lam; se_ *= lam
            act = rng.random(S) < p
            R = th + math.sqrt(rho) * rng.normal(0, 1, F)[fam] + math.sqrt(1 - rho) * rng.normal(0, 1, S)
            R = np.clip(R, -5, 10)
            s2 = np.where(n >= 2, ((n - 1) * np.maximum((ss - s * s / np.maximum(n, 1)) / np.maximum(n - 1, 1), 0) + 4) / (n - 1 + 4), 1.0)
            fm = np.array([s[fam == f].sum() / max(n[fam == f].sum(), 1) for f in range(F)])[fam] * 0.5      # a rough family mean, shrunk
            def post(nn, sm):
                prec = nn / s2 + 1 / tau**2
                m = (sm / s2 + fm / tau**2) / prec
                return m, np.sqrt(1 / prec)
            mc, sc = post(n, s); md, sd = post(ne, se_)
            Pc, Pd = Phi(mc / sc), Phi(md / sd)
            elig = act & (n >= 8)
            if elig.any():
                diff = Pd[elig] - Pc[elig]
                num.append(float((R[elig] * diff).sum())); den.append(float(np.abs(diff).sum())); ndis.append(int((np.abs(diff) >= 0.1).sum()))
            else:
                num.append(0.0); den.append(0.0); ndis.append(0)
            n += act; s += R * act; ss += R * R * act; ne += act; se_ += R * act
            if verdict is None and (t + 1) in looks:
                G = sum(1 for x in den if x > 0)
                if G >= min_ses and sum(ndis) >= min_dis:
                    N, Dn = np.array(num), np.array(den)
                    D = N.sum() / Dn.sum(); z = N - D * Dn
                    se = math.sqrt(G / (G - 1) * (z * z).sum()) / Dn.sum()
                    c = tq(G - 1, crit_q)
                    lo, hi = D - c * se, D + c * se
                    if hi < 0:
                        verdict = ("FAIL", t + 1, D)
                    elif lo > margin:
                        verdict = ("PASS", t + 1, D)
                    elif t + 1 == looks[-1]:
                        verdict = ("INCONCLUSIVE", t + 1, D)
        res.append(verdict or ("NOT ENOUGH", sessions, float("nan")))
    out = {k: sum(1 for r in res if r[0] == k) / reps for k in ("PASS", "FAIL", "INCONCLUSIVE", "NOT ENOUGH")}
    Ds = [r[2] for r in res if r[2] == r[2]]
    return out, (np.mean(Ds) if Ds else float("nan")), np.mean([r[1] for r in res if r[0] in ("PASS", "FAIL")] or [float("nan")])
if __name__ == "__main__":
    print("the forgetting record against the cumulative one, on the trades where they choose differently (D in R a trade; PASS needs the lower 90% bound above -0.05)")
    cases = [("120 sessions: stable market, half-life 60", {}),
             ("120 sessions: a break at 30, a third of families lose 0.4R", {"shift": (30, -0.4, 1 / 3)}),
             ("120 sessions: a break at 30, two thirds lose 0.3R", {"shift": (30, -0.3, 2 / 3)}),
             ("120 sessions: forgetting much too fast (half-life 3)", {"hl": 3}),
             ("120 sessions: forgetting too fast (half-life 8)", {"hl": 8}),
             ("250 sessions: stable", {"sessions": 250, "looks": (180, 215, 250), "reps": 150}),
             ("250 sessions: a break at 150, a third lose 0.4R", {"sessions": 250, "looks": (180, 215, 250), "reps": 150, "shift": (150, -0.4, 1 / 3)}),
             ("250 sessions: a break at 150, two thirds lose 0.4R", {"sessions": 250, "looks": (180, 215, 250), "reps": 150, "shift": (150, -0.4, 2 / 3)}),
             ("250 sessions: a break at 100, half lose 0.5R", {"sessions": 250, "looks": (180, 215, 250), "reps": 150, "shift": (100, -0.5, 0.5)})]
    for label, kw in cases:
        o, D, when = run(**kw)
        print(f"{label:58s} PASS {o['PASS']:.2f} FAIL {o['FAIL']:.2f} INCONCL {o['INCONCLUSIVE']:.2f} short {o['NOT ENOUGH']:.2f} | mean D {D:+.3f} R")
