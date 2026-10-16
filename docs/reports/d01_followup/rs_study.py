"""relstrength persistence (and the preference it gates) against a placebo, on every recorded session."""
import math

import numpy as np
import pandas as pd

from common import IST, bars
from quantdesk.intraday import relstrength as RS

rng = np.random.default_rng(11)
A, B = bars("BANKNIFTY"), bars("NIFTY")


def price_grid(lr: pd.Series) -> pd.Series:
    """The ratio at each 5-minute mark (the close of the bar ending there), whatever the bars' resolution."""
    step = (lr.index[1] - lr.index[0]) if len(lr) > 1 else pd.Timedelta(minutes=5)
    p = lr.copy()
    p.index = p.index + (pd.Timedelta(minutes=5) if step >= pd.Timedelta(minutes=5) else pd.Timedelta(minutes=1))
    return p.resample("5min", label="right", closed="right").last().ffill()


lr = RS._ratio(A, B)
rows = []
for d, x in lr.groupby(lr.index.date):
    if len(x) < 70:
        continue
    g = price_grid(x)
    prior = lr[lr.index.date < d]
    s30 = RS._sigma30(prior) if len(prior) else None
    for t in pd.date_range(f"{d} 09:45", f"{d} 14:55", freq="5min", tz=IST):
        a, b, c = t - pd.Timedelta(minutes=30), t, t + pd.Timedelta(minutes=30)
        if a in g.index and c in g.index and b in g.index:
            xx, yy = (g[b] - g[a]) * 1e4, (g[c] - g[b]) * 1e4
            rows.append((d, t, xx, yy, xx / 1e4 / s30 if s30 else np.nan))
P = pd.DataFrame(rows, columns=["day", "t", "x", "y", "z30"])
P["x"], P["y"] = P.x.clip(-150, 150), P.y.clip(-150, 150)
days = sorted(P.day.unique())
di = P.day.map({d: i for i, d in enumerate(days)}).to_numpy()
x, y = P.x.to_numpy(), P.y.to_numpy()
print(f"{len(days)} sessions {days[0]} .. {days[-1]}, {len(P)} points")


def rec(xx, yy, w=1 / 6):
    """relstrength.record's IC and t on the overlap-weighted count (n/6)."""
    W = w * len(xx)
    r = float(np.corrcoef(xx, yy)[0, 1])
    return r, r * math.sqrt(max(W - 2, 0) / (1 - r * r)), W


r, t, W = rec(x, y)
print(f"persistence IC {r:+.4f}, t {t:+.2f} on W={W:.0f} (the record's formula)")

# effective n from the measured autocorrelation (Bartlett: var(r) ~ (1/n) sum_k rho_x(k) rho_y(k) + rho_xy(k) rho_yx(k))
def acf_pairs(u, v, k):
    a, b = [], []
    for i in range(len(days)):
        m = di == i
        uu, vv = u[m], v[m]
        if len(uu) > abs(k):
            a += list(uu[:len(uu) - k] if k >= 0 else uu[-k:])
            b += list(vv[k:] if k >= 0 else vv[:len(vv) + k])
    return float(np.corrcoef(a, b)[0, 1])


xs, ys = (x - x.mean()) / x.std(), (y - y.mean()) / y.std()
K = 12
s = 1.0 + 2 * sum(acf_pairs(xs, xs, k) * acf_pairs(ys, ys, k) for k in range(1, K + 1)) \
    + sum(acf_pairs(xs, ys, k) * acf_pairs(ys, xs, k) for k in range(-K, K + 1))
neff = len(P) / s
print("ACF x: " + ", ".join(f"{acf_pairs(xs, xs, k):+.2f}" for k in range(1, 8)) + f"; Bartlett factor {s:.2f} -> effective n {neff:.0f} "
      f"(the record uses n/6 = {len(P) / 6:.0f}); t on effective n {r * math.sqrt((neff - 2) / (1 - r * r)):+.2f}")

# per-session contributions: the cleanest independent unit (overnight breaks the intraday dependence)
S = np.array([np.sum((x[di == i] - x.mean()) * (y[di == i] - y.mean())) for i in range(len(days))])
print(f"session-level: mean {S.mean():+.0f}, t {S.mean() / (S.std(ddof=1) / math.sqrt(len(S))):+.2f} over {len(S)} sessions, "
      f"positive in {np.mean(S > 0):.0%}")


def flips(n):
    return rng.choice((1, -1), (n, len(days)))


F = flips(20000)
ic_pl = np.array([rec(x, y * f[di])[0] for f in F])
print(f"sign-flip by session: placebo IC 95th {np.quantile(ic_pl, .95):+.4f}, p(one-sided) = {(ic_pl >= r).mean():.3f}, "
      f"p(two-sided) = {(np.abs(ic_pl) >= abs(r)).mean():.3f}")
# block permutation: the next 30 minutes of one session against the last 30 of another (same clock times)
Y = P.pivot_table(index="day", columns="t", values="y", aggfunc="first")
P["clock"] = P.t.dt.strftime("%H:%M")
Yc = P.pivot_table(index="day", columns="clock", values="y")
perm = []
for _ in range(5000):
    sh = rng.permutation(len(days))
    yy = Yc.iloc[sh].to_numpy()[di, P.clock.map({c: j for j, c in enumerate(Yc.columns)}).to_numpy()]
    m = ~np.isnan(yy)
    perm.append(float(np.corrcoef(x[m], yy[m])[0, 1]))
perm = np.array(perm)
print(f"block permutation of sessions: placebo IC 95th {np.quantile(perm, .95):+.4f}, p(one-sided) = {(perm >= r).mean():.3f}")

# noise turns the preference on: the record checked after every session (earned(): n >= 30, ic > 0, t >= 2)
def ever_earned(sign, start=0):
    on = False
    for k in range(start, len(days)):
        m = (di >= start) & (di <= k)
        if m.sum() < 180:                                            # W >= 30
            continue
        rr, tt, _ = rec(x[m], (y * sign[di])[m])
        if rr > 0 and tt >= RS.MIN_T:
            return True
    return False


G = flips(4000)
rate = np.mean([ever_earned(f) for f in G])
print(f"noise switches the preference on at some session close in {rate:.0%} of placebo paths over {len(days)} sessions "
      f"(nominal one-off rate 2.3%)")
print("observed path ever earned:", ever_earned(np.ones(len(days), int)))
tt = []
for k in range(len(days)):
    m = di <= k
    if m.sum() >= 180:
        tt.append((str(days[k]), round(rec(x[m], y[m])[1], 2)))
print("observed running t (every 10th):", tt[::10], tt[-1])

# when the preference would act: |z30| >= 1; does going with the leader pay over the next 30 minutes?
q = P[P.z30.abs() >= 1]
g = np.sign(q.x) * q.y
qi = q.day.map({d: i for i, d in enumerate(days)}).to_numpy()
pl = np.array([np.mean(g * f[qi]) for f in F])
print(f"|z30| >= 1: {len(q)} points on {q.day.nunique()} sessions; leader's next 30 min {g.mean():+.2f} bps "
      f"(with it {np.mean(g > 0):.1%}); sign-flip p(one-sided) = {(pl >= g.mean()).mean():.3f}")
