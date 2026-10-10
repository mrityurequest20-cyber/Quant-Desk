"""setup_mult has no record to test (0 closed trades in the journal), so: what does it do to noise?
Each simulated setup trades sequentially; after each trade the desk calls learning.Memory.setup_mult. Stand-aside is
absorbing (a stood-aside setup takes no more trades, so its record can't recover)."""
import numpy as np
import pandas as pd

from common import J
from quantdesk.intraday.learning import Memory

rng = np.random.default_rng(3)
plan = pd.read_parquet(f"{J}/autolearn/plan/studies/2026-10-09-89b486/real_outcomes.parquet")
EMP = plan.net_R.clip(-3, 5).to_numpy()
EMP = EMP - EMP.mean()                                    # the desk's own recorded plan outcomes, zero-mean


def draw(kind, mu, n):
    if kind == "plans":
        return rng.choice(EMP, n) + mu
    p = (1 + mu) / 3                                       # bracket: -1R stop or +2R target, mean mu
    return np.where(rng.random(n) < p, 2.0, -1.0)


def path(kind, mu, N):
    m = Memory()
    r = draw(kind, mu, N)
    mults = []
    for k in range(N):
        m.bump("setup", "x", r[k] > 0, float(np.clip(r[k], -3, 5)))
        mult, why = m.setup_mult("x")
        if why:
            return k + 1, mults
        mults.append(mult)
    return None, mults


SIMS = 4000
print("P(stood aside for good within N trades) | true edge per trade")
for kind in ("plans", "bracket"):
    for mu in (-0.3, -0.1, 0.0, 0.1, 0.2, 0.3):
        out = {}
        for N in (20, 50, 100):
            got = [path(kind, mu, N) for _ in range(SIMS if N < 100 else SIMS // 2)]
            out[N] = np.mean([g[0] is not None for g in got])
        print(f"  {kind:7s} mu {mu:+.1f}R: " + ", ".join(f"N={k}: {v:5.1%}" for k, v in out.items()))

print("conviction tilt noise gives a zero-edge setup that is still trading")
for kind in ("plans", "bracket"):
    for N in (8, 20, 50):
        ms = [g[1][-1] for g in (path(kind, 0.0, N) for _ in range(SIMS)) if g[0] is None and len(g[1]) == N]
        ms = np.array(ms)
        print(f"  {kind:7s} after {N:3d} trades: x{np.quantile(ms, .05):.2f} .. x{np.quantile(ms, .95):.2f} (90% band), "
              f"|tilt| >= 10% in {np.mean(np.abs(ms - 1) >= .1):.0%}")

# multiplicity: 5 setups x 5 day types, 25 setup|day-type cells; a cell with 8+ trades decides on its own record
print("P(at least one of the 25 setup|day-type cells of zero-edge setups is stood aside), 20 trades a cell:")
for kind in ("plans", "bracket"):
    one = np.mean([path(kind, 0.0, 20)[0] is not None for _ in range(SIMS)])
    print(f"  {kind:7s}: one cell {one:.1%} -> any of 25 cells {1 - (1 - one) ** 25:.0%}")
