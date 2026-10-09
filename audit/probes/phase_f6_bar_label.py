"""Phase F6 / Q-01: are Kotak 1-minute candles labelled by bar START or bar END?
A chain-tape snapshot fetched at second s of minute t0 carries the index spot at that instant. If candles are
labelled by their start, the bar containing the instant is labelled t0; if by their end, t0+1. Compare the snapshot
spot with the open/close of the bars labelled t0-1, t0, t0+1 (snapshots late in the minute, before 15:15)."""
import sys, glob
import numpy as np, pandas as pd
chains, data = sys.argv[1], sys.argv[2]
rows = []
for f in sorted(glob.glob(f"{chains}/*_chains.parquet")):
    try:
        d = pd.read_parquet(f, columns=["ts", "underlying", "spot"])
    except Exception:
        continue
    d = d.drop_duplicates(["ts", "underlying"])
    d["ts"] = pd.to_datetime(d.ts).dt.tz_convert("Asia/Kolkata")
    for u in ("NIFTY", "BANKNIFTY"):
        x = d[d.underlying == u]
        if x.empty:
            continue
        day = str(x.ts.iloc[0].date())
        try:
            b = pd.read_csv(f"{data}/{day}/{u}_1m.csv", index_col=0, parse_dates=True)
        except FileNotFoundError:
            continue
        b.index = pd.DatetimeIndex(b.index).tz_convert("Asia/Kolkata")
        for ts, s in zip(x.ts, x.spot):
            if ts.time() >= pd.Timestamp("15:14").time() or ts.time() < pd.Timestamp("09:20").time():
                continue
            t0 = ts.floor("min")
            r = {"u": u, "sec": ts.second}
            for k, lab in ((-1, "t0-1"), (0, "t0"), (1, "t0+1")):
                t = t0 + pd.Timedelta(minutes=k)
                if t in b.index:
                    r[f"{lab}_close"] = abs(b.loc[t, "close"] - s) / s * 1e4
                    lo, hi = b.loc[t, "low"], b.loc[t, "high"]
                    r[f"{lab}_inrange"] = lo - 1e-9 <= s <= hi + 1e-9
            rows.append(r)
x = pd.DataFrame(rows)
print("snapshots compared:", len(x))
print("median |spot - close| bps:", {c: round(float(x[c].median()), 3) for c in x if c.endswith("_close")})
print("share with spot inside the bar's [low, high]:", {c: round(float(x[c].mean()), 3) for c in x if c.endswith("_inrange")})
