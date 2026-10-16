"""news_trust (and reader_trust) against a sign-flip placebo by session x index."""
import itertools
import math
import sys

import numpy as np
import pandas as pd

PRIOR = 20.0
NDRAW = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
rng = np.random.default_rng(7)
df = pd.read_pickle("news_rows.pkl")
df["blk"] = df["day"].astype(str) + "|" + df["sym"]
R = df[df.reader == "rules"].reset_index(drop=True)
BLK = sorted(R.blk.unique())
DAYS = sorted(R.day.unique())
bi = R.blk.map({b: i for i, b in enumerate(BLK)}).to_numpy()
di = R.day.map({d: i for i, d in enumerate(DAYS)}).to_numpy()
w, s, fr = R.w.to_numpy(), R.s.to_numpy(), R.fr.to_numpy()
ec, sc = pd.factorize(R.event)[0], pd.factorize(R.source)[0]
W = w.sum()


def rel_codes(codes, hit, m):
    K = codes.max() + 1
    h = np.bincount(codes[m], weights=(hit * w)[m], minlength=K)
    n = np.bincount(codes[m], weights=w[m], minlength=K)
    return np.clip(2 * (h + PRIOR / 2) / (n + PRIOR), 0.5, 1.5)[codes]


def trust_of(hit, m=None):
    """learning.Memory.news_trust for every row, learned from the rows in mask `m` (all by default)."""
    m = np.ones(len(R), bool) if m is None else m
    return np.clip(rel_codes(ec, hit, m) * rel_codes(sc, hit, m), 0.5, 1.5)


def stats(sign):
    """sign: +-1 per row (the placebo flip)."""
    f = fr * sign
    hit = (s * f > 0).astype(float)
    lt = np.log(trust_of(hit))
    mu = float(np.sum(w * lt) / W)
    out = {"hit": float((w * hit).sum() / W), "lvl": mu,
           "disp": float(np.sqrt(np.sum(w * (lt - mu) ** 2) / W)), "max": float(np.max(np.abs(lt)))}
    g = 0.0                          # walk-forward: trust learned on earlier sessions, scored on the next session
    for k in range(1, len(DAYS)):
        m = di == k
        tr = trust_of(hit, di < k)[m]
        g += float(np.sum(w[m] * (tr - np.sum(w[m] * tr) / w[m].sum()) * s[m] * f[m]))
    out["oos"] = g * 1e4                                               # >0: trust lifted the calls that came right
    return out


obs = stats(np.ones(len(R)))
print("observed", {k: round(v, 4) for k, v in obs.items()})
P = pd.DataFrame([stats(rng.choice((1, -1), len(BLK))[bi]) for _ in range(NDRAW)])
print(f"placebo by session x index ({NDRAW} random flips of {len(BLK)} blocks)")
for k in obs:
    p = (P[k].abs() >= abs(obs[k]) - 1e-12).mean() if k == "lvl" else (P[k] >= obs[k] - 1e-12).mean()
    print(f"  {k}: obs {obs[k]:+.4f}, placebo median {P[k].median():+.4f}, 95th {P[k].quantile(.95):+.4f}, p = {p:.3f}")
print("  noise moves some headline's trust beyond 0.8x-1.25x in %.0f%% of flips" % (100 * (P["max"] >= math.log(1.25)).mean()))
dd = di
Q = pd.DataFrame([stats(np.array(bits)[dd]) for bits in itertools.product((1, -1), repeat=len(DAYS))])
print(f"placebo by session (exact, {len(Q)} flips, both indices together)")
for k in ("hit", "disp", "oos"):
    print(f"  {k}: p = {(Q[k] >= obs[k] - 1e-12).mean():.3f}")

# effective n: one observation per (index, 30-minute window); autocorrelation across windows and across indices
win = R.assign(h=w * (2 * (s * fr > 0) - 1)).groupby(["sym", "day", "win"]).h.sum().reset_index()
N = len(win)
win["zc"] = (win.h - win.h.mean()) / win.h.std()
rho = {}
for lag in (1, 2, 3):
    a = []
    for _, g in win.sort_values("win").groupby(["sym", "day"]):
        v = g.zc.to_numpy()
        a += list(zip(v[:-lag], v[lag:]))
    a = np.array(a)
    rho[lag] = (float(np.corrcoef(a[:, 0], a[:, 1])[0, 1]), len(a))
pv = win.pivot_table(index=["day", "win"], columns="sym", values="zc").dropna()
rx = float(np.corrcoef(pv.NIFTY, pv.BANKNIFTY)[0, 1])
pairs = 2 * sum(max(r, 0) * n for r, n in rho.values()) + 2 * max(rx, 0) * len(pv)
neff = N / (1 + pairs / N)
print(f"windows {N}; ACF of the per-window call " + ", ".join(f"lag{k} {r:+.2f}" for k, (r, _) in rho.items())
      + f"; NIFTY~BANKNIFTY same window {rx:+.2f} on {len(pv)} pairs -> effective n {neff:.0f}")
hr = obs["hit"]
print(f"hit {hr:.3f}: z on effective n = {(hr - .5) / math.sqrt(.25 / neff):+.2f}; "
      f"on memory's n=263 at 55.1%: {(0.551 - .5) / math.sqrt(.25 / 263):+.2f}")
for rd, g in df.groupby("reader"):
    h = float((g.w * (g.s * g.fr > 0)).sum() / g.w.sum())
    print(f"reader {rd}: {g.w.sum():.0f} windows, hit {h:.3f}, reliability {2 * (h * g.w.sum() + 10) / (g.w.sum() + 20):.2f}")
