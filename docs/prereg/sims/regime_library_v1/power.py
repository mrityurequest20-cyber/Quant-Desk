"""Power and size of the regime library's two tests (docs/prereg/regime_library_v1.json): S (choosing by the similar past) and A (choosing by a forgetting record),
each against the cumulative record, on the REAL fingerprint path and SYNTHETIC outcomes.

    PYTHONPATH=. python docs/prereg/sims/regime_library_v1/power.py <features csv> [reps, default 200] [grid: also h 0.35 and 0.7]

Why this design: the features are real (every session's fingerprint, 2014-07 to 2026-11, from closes up to that session: library_features.py), so the kernel's weights,
their persistence and the eras they cluster in are the real ones. The outcomes are synthetic: no replay outcome and no option price was read. Each session, each of 16
families (5 up, 5 down, 6 flat: the single-expiry structures the replay registers) on 2 underlyings returns, in R:

    y = mu_f + drift_f(t) + delta * g_f(features at t) + lambda_f * market(t) + noise

* market(t): the session's move (a t(4) draw scaled by the REAL 20-session volatility of that session): up structures load +, down structures -, flat ones on its
  size against the size priced in (long volatility +, short volatility -; options are priced on the expected move, so a volatile market alone pays neither side);
  the two underlyings' moves correlate 0.8. Loadings differ within a group, so the within-group choice still carries the
  market's noise.
* g_f: each family's own smooth response to the market's kind (tanh of a random direction in the six standardized features, scaled to sd 1): the regime effect the
  library should find, of size delta R. delta 0 is the null.
* drift_f(t): a random walk per family (total sd `drift` over the sample): change that no feature describes (an expiry or lot-size rule, a new era). It is what a
  forgetting record can follow and the library should NOT be credited with.
* mu_f: fixed family means (sd `spread`). With spread > 0, a noisier chooser loses against the cumulative record even when nothing changes.

The choosers, at each session's close (the outcome of session d is known at d + 1's close): FLAT, the cumulative mean of all earlier outcomes; SIM, the kernel mean over
the sessions before d - EMBARGO (bandwidth h on the RMS robust-z distance, as library_features.weights), shrunk to FLAT by n_eff / (n_eff + KAPPA); EW, the mean with
weights halving every HALF_LIFE sessions. Each picks the family with the highest estimate in each (underlying, group) cell. D(d) = the mean over the six cells of
y(pick) - y(flat's pick). The test: mean D over the test sessions, Newey-West t with LAGS lags, one-sided at 2.5% (two tests: Bonferroni). Heavy-tailed worlds add
t(3) noise and rare multi-R payoffs to the long-option families; every outcome is clamped to -5 .. +10 R as Lab.add clamps it.
"""
from __future__ import annotations

import math
import sys

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from library_features import (
    EMBARGO,
    FEATURES,
    MIN_POOL,
    POOL_START,
    Z_CLIP,
    robust_z,
)

GROUPS = {"up": 5, "down": 5, "flat": 6}
LONG_VOL_FLAT = 2                     # of the six flat families: the long straddle and strangle
KAPPA = 30
HALF_LIFE = 60
LAGS = 20
LONG_LAGS = 60                        # a check on LAGS: the choices persist for weeks, so D's autocorrelation can outlast 20 sessions
SEED = 5
MIN_DIFFER = 0.10                     # a PASS also needs the choices to differ in at least this share of cell-sessions
H_REG = 0.5                           # the registered bandwidth (0.35 and 0.7 run too with a third argument)


def weight_matrix(X: np.ndarray, lo: int, h: float) -> tuple[np.ndarray, np.ndarray]:
    """W[i, :] = the kernel weights of the pool sessions [lo, i - EMBARGO) for each test session i (zero elsewhere); the test sessions' indices."""
    n = len(X)
    tests = [i for i in range(n) if i - EMBARGO - lo >= MIN_POOL]
    W = np.zeros((len(tests), n))
    for r, i in enumerate(tests):
        pz, xz = robust_z(X[lo:i - EMBARGO], X[i])
        d2 = np.nanmean((pz - xz) ** 2, axis=1)
        W[r, lo:i - EMBARGO] = np.exp(-d2 / (2 * h * h))
    return W, np.array(tests)


def nw_t(x: np.ndarray, lags: int) -> float:
    n = len(x)
    e = x - x.mean()
    s = e @ e / n
    for k in range(1, lags + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(x.mean() / math.sqrt(max(s, 1e-30) / n))


def outcomes(rng, X: np.ndarray, vol: np.ndarray, delta: float, drift: float, spread: float, tails: bool = False) -> np.ndarray:
    """y[t, u, f]: 2 underlyings, 16 families (group order: up, down, flat)."""
    n = len(X)
    nf = sum(GROUPS.values())
    z = np.clip((X - np.nanmedian(X, 0)) / (np.nanmedian(np.abs(X - np.nanmedian(X, 0)), 0) * 1.4826), -Z_CLIP, Z_CLIP)
    z = np.nan_to_num(z)
    a = rng.normal(size=(nf, X.shape[1]))
    g = np.tanh(z @ a.T / math.sqrt(X.shape[1]))
    g = (g - g.mean(0)) / (g.std(0) + 1e-12)                                     # [t, f], sd 1
    common = stats.t.rvs(4, size=(n, 1), random_state=rng) / math.sqrt(2)
    own = stats.t.rvs(4, size=(n, 2), random_state=rng) / math.sqrt(2)
    shape = math.sqrt(0.8) * common + math.sqrt(0.2) * own                       # [t, u], before the session's scale
    scale = vol[:, None] / np.nanmedian(vol)
    move = shape * scale
    size = (np.abs(shape) - np.abs(shape).mean()) * scale                       # the size of the move against the size the market priced: options are priced on the
                                                                                # expected move, so a large move in a volatile market is no gain by itself
    lam = np.concatenate([rng.uniform(0.15, 0.45, 5), -rng.uniform(0.15, 0.45, 5),
                          np.r_[rng.uniform(0.15, 0.35, LONG_VOL_FLAT), -rng.uniform(0.1, 0.3, 6 - LONG_VOL_FLAT)]])
    is_flat = np.r_[np.zeros(10, bool), np.ones(6, bool)]
    mkt = np.where(is_flat[None, None, :], size[:, :, None], move[:, :, None]) * lam[None, None, :]
    mu = rng.normal(0, spread, nf) - 0.02
    dr = np.cumsum(rng.normal(0, drift / math.sqrt(n), (n, nf)), axis=0)
    noise = (stats.t.rvs(3, size=(n, 2, nf), random_state=rng) * 0.2 / math.sqrt(3)) if tails else rng.normal(0, 0.2, (n, 2, nf))
    if tails:                                                                   # now and then a long option pays several R (the replay clamps R to -5 .. +10)
        noise += (rng.random((n, 2, nf)) < 0.01) * rng.exponential(2.0, (n, 2, nf)) * np.r_[1, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 0][None, None, :]
    return mu[None, None, :] + dr[:, None, :] + delta * g[:, None, :] + mkt + noise


def run(rng, X, vol, lo, W, tests, delta, drift, spread, tails=False):
    y = np.clip(outcomes(rng, X, vol, delta, drift, spread, tails), -5, 10)
    n = len(X)
    Yp = y.reshape(n, -1)
    cs = np.cumsum(np.where(np.arange(n)[:, None] >= lo, Yp, 0.0), axis=0)
    cnt = np.cumsum(np.arange(n) >= lo)
    flat = np.stack([cs[i - 1] / cnt[i - 1] for i in tests])                    # outcomes of sessions [lo, i - 1]
    sw = W.sum(1, keepdims=True)
    neff = sw[:, 0] ** 2 / (W ** 2).sum(1)
    km = (W @ Yp) / sw
    sim = (neff[:, None] * km + KAPPA * flat) / (neff[:, None] + KAPPA)
    lam = 0.5 ** (1 / HALF_LIFE)
    ew = np.empty_like(flat)
    acc, wt = np.zeros(Yp.shape[1]), 0.0
    k = 0
    for i in range(lo, n):
        if k < len(tests) and tests[k] == i:
            ew[k] = acc / wt
            k += 1
        acc, wt = acc * lam + Yp[i], wt * lam + 1.0                            # after session i's close, its outcome (known at i + 1) joins
    real = Yp[tests]
    out = {}
    cells = []
    for u in range(2):
        off = 0
        for m in GROUPS.values():
            cells.append(slice(u * 16 + off, u * 16 + off + m))
            off += m
    for name, est in (("S", sim), ("A", ew)):
        d = np.zeros(len(tests))
        differ = 0
        for c in cells:
            pe, pf = est[:, c].argmax(1), flat[:, c].argmax(1)
            rr = real[:, c]
            d += rr[np.arange(len(tests)), pe] - rr[np.arange(len(tests)), pf]
            differ += (pe != pf).sum()
        d /= len(cells)
        out[name] = (d.mean(), nw_t(d, LAGS), differ / (len(cells) * len(tests)), nw_t(d, LONG_LAGS))
    return out


def main():
    fe = pd.read_csv(sys.argv[1], index_col=0, parse_dates=True)
    reps = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    X = fe[list(FEATURES)].astype(float).values
    vol = fe["vol20"].astype(float).values                                     # each session's real 20-session volatility scales its synthetic move
    lo = int(np.searchsorted(fe.index.values, POOL_START.to_datetime64()))
    crit = stats.norm.ppf(0.975)                                               # two registered tests, each one-sided at 2.5% (Bonferroni)
    worlds = [("null: nothing differs", 0.0, 0.0, 0.0), ("null: fixed family means", 0.0, 0.0, 0.05), ("null: drift only", 0.0, 0.15, 0.05),
              ("regime 0.03", 0.03, 0.0, 0.05), ("regime 0.05", 0.05, 0.0, 0.05), ("regime 0.08", 0.08, 0.0, 0.05), ("regime 0.05 + drift", 0.05, 0.15, 0.05),
              ("null: heavy tails", 0.0, 0.0, 0.0, True), ("regime 0.05, heavy tails", 0.05, 0.0, 0.05, True)]
    for h in (H_REG,) + tuple(x for x in (0.35, 0.7) if len(sys.argv) > 3):
        W, tests = weight_matrix(X, lo, h)
        print(f"h {h}: {len(tests)} test sessions from {fe.index[tests[0]].date()}")
        for label, delta, drift, spread, *tails in worlds:
            rng = np.random.default_rng(SEED)
            res = [run(rng, X, vol, lo, W, tests, delta, drift, spread, bool(tails and tails[0])) for _ in range(reps)]
            for k in ("S", "A"):
                m = np.array([r[k][0] for r in res]); t = np.array([r[k][1] for r in res]); dif = np.array([r[k][2] for r in res])
                t60 = np.array([r[k][3] for r in res])
                reg = (t >= crit) & (t60 >= crit) & (dif >= MIN_DIFFER)                  # the registered PASS: both lag counts and enough differing choices
                print(f"  {label:28s} {k}: mean D {m.mean():+.4f} R (sd over worlds {m.std():.4f}); PASS (registered rule) {reg.mean():.3f}; t >= 1.96 at {LAGS} lags "
                      f"{np.mean(t >= crit):.2f}, at {LONG_LAGS} {np.mean(t60 >= crit):.2f}; picks differ {dif.mean():.2f}")


if __name__ == "__main__":
    main()
