"""Real half-spreads of ~20-delta options in the last 30 minutes before the close, the session before expiry,
from the desk's recorded chains, vs the laws' cost model (0.05 + max(0.05, 0.2% of price) per unit)."""
import sys, glob
import numpy as np, pandas as pd
from scipy.stats import norm
fs = sorted(glob.glob(f"{sys.argv[1]}/*afternoon*_chains.parquet"))
d = pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True)
d["ts"] = pd.to_datetime(d["ts"]); d["day"] = d.ts.dt.tz_convert("Asia/Kolkata").dt.date
d["expiry"] = pd.to_datetime(d["expiry"]).dt.date
t = d.ts.dt.tz_convert("Asia/Kolkata").dt.time
d = d[(t >= pd.Timestamp("15:00").time()) & (t <= pd.Timestamp("15:30").time())]
rows = []
for (u, day, ex), g in d.groupby(["underlying", "day", "expiry"]):
    bd = np.busday_count(day, ex)
    if bd != 1:                      # the session before expiry only
        continue
    T = 1.25 / 365
    for side, sgn in (("ce", 1), ("pe", -1)):
        iv = g[f"{side}_iv"] / 100
        d1 = (np.log(g.spot / g.strike) + 0.5 * iv**2 * T) / (iv * np.sqrt(T))
        delta = pd.Series(norm.cdf(d1) if sgn == 1 else norm.cdf(d1) - 1, index=g.index)
        bid, ask = g[f"{side}_bid"], g[f"{side}_ask"]
        ok = (bid > 0) & (ask > bid) & iv.gt(0) & (delta.abs().between(0.12, 0.30))
        for _, r in g[ok].assign(delta=delta[ok], bid=bid[ok], ask=ask[ok]).iterrows():
            mid = (r.bid + r.ask) / 2
            rows.append({"u": u, "day": day, "side": side, "delta": r.delta, "mid": mid, "half": (r.ask - r.bid) / 2,
                         "model": 0.05 + max(0.05, 0.002 * mid), "half_bps_idx": (r.ask - r.bid) / 2 / r.spot * 1e4})
x = pd.DataFrame(rows)
if x.empty:
    print("no expiry-eve snapshots"); sys.exit()
s = x.groupby(["u", "day"]).agg(n=("mid", "size"), mid=("mid", "median"), half=("half", "median"), model=("model", "median"),
                               half_bps_idx=("half_bps_idx", "median"))
s["half/model"] = s.half / s.model
print(s.round(3).to_string())
