"""Check the desk's BH, PSR/DSR and NW against independent reference implementations."""
import sys
import numpy as np, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from quantdesk.research.edges import benjamini_hochberg, hac_mean
from quantdesk.risk.metrics import probabilistic_sharpe, deflated_sharpe
rng = np.random.default_rng(1)
bad = 0
for _ in range(2000):
    m = rng.integers(1, 60); p = np.where(rng.random(m) < .3, rng.random(m) * .02, rng.random(m))
    o = np.sort(p); k = np.nonzero(o <= .10 * np.arange(1, m + 1) / m)[0]
    thr = o[k[-1]] if len(k) else -1
    bad += list(p <= thr) != benjamini_hochberg(list(p), .10)
print("BH mismatches vs reference over 2000 random families:", bad)
print("BH with NaN p treated as 1:", benjamini_hochberg([0.001, float('nan')], .10))
# PSR vs closed form (Bailey & Lopez de Prado 2012), non-normal sample
r = pd.Series(rng.standard_t(4, 500) * .01 + .001)
from scipy.stats import norm, skew, kurtosis
sr = r.mean() / r.std(); g3 = skew(r, bias=False); g4 = kurtosis(r, fisher=False, bias=False)
ref = norm.cdf(sr * np.sqrt(len(r) - 1) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
print("PSR desk", round(probabilistic_sharpe(r), 6), "reference", round(ref, 6))
sr0 = .05 * ((1 - .5772156649) * norm.ppf(1 - 1 / 50) + .5772156649 * norm.ppf(1 - 1 / (50 * np.e)))
print("DSR desk", round(deflated_sharpe(r, 50, .05), 6), "reference", round(norm.cdf((sr - sr0) * np.sqrt(len(r) - 1) / np.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr ** 2)), 6))
# NW t size under H0 with AR(1) phi=.5, T=288 (the L1 weekly series length)
rej = 0
for _ in range(4000):
    e = rng.standard_normal(288); x = np.empty(288); x[0] = e[0]
    for i in range(1, 288): x[i] = .5 * x[i - 1] + e[i]
    rej += hac_mean(x)[1] > 1.645
print("NW one-sided size at nominal 5%, AR(1) .5, T=288:", rej / 4000)
rej = sum(hac_mean(rng.standard_t(3, 288))[1] > 1.645 for _ in range(4000))
print("NW one-sided size at nominal 5%, iid t3, T=288:", rej / 4000)
