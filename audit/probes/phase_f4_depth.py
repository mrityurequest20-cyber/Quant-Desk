"""Phase F4: top-of-book size near the money on the recorded chains vs the orders the engine would send
(1 and 10 lots; the engine fills the whole order at the best quote + 1 tick and never reads depth)."""
import sys, glob
import numpy as np, pandas as pd
LOT = {"NIFTY": 65, "BANKNIFTY": 30, "SENSEX": 20, "FINNIFTY": 60, "MIDCPNIFTY": 120}
rows = []
for f in sorted(glob.glob(f"{sys.argv[1]}/*_chains.parquet")):
    try:
        d = pd.read_parquet(f)
    except Exception:
        continue
    d["ts"] = pd.to_datetime(d.ts).dt.tz_convert("Asia/Kolkata")
    d = d[(d.ts.dt.minute % 15 == 0) & (d.ts.dt.time < pd.Timestamp("15:15").time())]
    for (u, ts), g in d.groupby(["underlying", "ts"]):
        if u not in ("NIFTY", "BANKNIFTY"):
            continue
        ex = g.expiry.min(); g = g[g.expiry == ex]                   # nearest expiry: what the engine trades
        S = g.spot.iloc[0]; step = 50 if u == "NIFTY" else 100
        near = g[(g.strike - S).abs() <= 4 * step]
        for side in ("ce", "pe"):
            for q in ("bidq", "askq"):
                v = near[f"{side}_{q}"].dropna()
                rows += [{"u": u, "qty": float(x)} for x in v]
x = pd.DataFrame(rows)
for u, g in x.groupby("u"):
    lot = LOT[u]
    print(f"{u}: {len(g)} best-level quotes within ±4 strikes; median size {g.qty.median():.0f} "
          f"(={g.qty.median() / lot:.1f} lots); share < 1 lot {np.mean(g.qty < lot):.1%}; "
          f"share < 10 lots {np.mean(g.qty < 10 * lot):.1%}")
