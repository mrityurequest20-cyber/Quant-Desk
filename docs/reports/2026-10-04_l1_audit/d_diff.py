"""Audit step D: v1 vs v2, trade by trade; and where v2's index levels come from."""
from pathlib import Path
import numpy as np, pandas as pd
from quantdesk.research import laws as L
HERE = Path(__file__).parent
W = Path("/home/user/quant-desk/runtime/warehouse")
HELD = ["FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"]
k = ["symbol", "strategy", "expiry"]
v1 = pd.read_csv(HERE / "expiry_eve_law_v1_trades.csv.gz"); v2 = pd.read_csv(HERE / "expiry_eve_law_v2_trades.csv.gz")
m = v1.merge(v2, on=k, how="outer", suffixes=("_1", "_2"), indicator=True)
m["cat"] = np.select([m._merge == "left_only", m._merge == "right_only",
                      (m.strikes_1 != m.strikes_2), (m.S_1.round(4) != m.S_2.round(4)) | (m.S_T_1.round(4) != m.S_T_2.round(4))],
                     ["only v1", "only v2", "different strikes", "same strikes, index level changed"], "identical")
s = m[m.strategy == "short_strangle_20d"]
print(pd.crosstab(s.symbol, s.cat).to_string())
ch = s[s.cat.isin(["different strikes", "same strikes, index level changed"])].copy()
ch["exp"] = pd.to_datetime(ch.expiry)
print("\nchanged strangle trades: expiry range by instrument:")
print(ch.groupby("symbol").exp.agg(["min", "max", "count"]).to_string())
print("changed after 2024-07-08 (UDiFF era):", int((ch.exp >= "2024-07-08").sum()))
ch["dS_T_pct"] = (ch.S_T_1 / ch.S_T_2 - 1) * 100; ch["dS_pct"] = (ch.S_1 / ch.S_2 - 1) * 100
ch["dbps"] = ch.bps_2 - ch.bps_1
print("\nv1 settlement level vs official close, % (changed trades):", ch.dS_T_pct.describe().round(3).to_dict())
print("v1 entry level vs official close, %:", ch.dS_pct.describe().round(3).to_dict())
print("bps change v2 - v1 on changed trades, by instrument:", ch.groupby("symbol").dbps.agg(["mean", "sum", "count"]).round(2).to_dict("index"))
only = s[s.cat.isin(["only v1", "only v2"])]
print("\nonly-in-one trades:"); print(only[["symbol", "expiry", "cat", "bps_1", "bps_2"]].to_string(index=False))

# provenance of v2's levels: NSE held-out must equal the official close at entry and at settlement
spec = L.load_spec(Path("/home/user/quant-desk/docs/prereg/expiry_eve_law_v2.json"))
off = L.official_closes(W, spec)
opts = L.load(W, spec)
t2 = v2[v2.symbol.isin(HELD + ["NIFTY", "BANKNIFTY"])].copy()
t2["entry"] = pd.to_datetime(t2.entry).dt.date; t2["expiry"] = pd.to_datetime(t2.expiry).dt.date
bad = []
for sym, g in t2.groupby("symbol"):
    if sym in off:
        o = off[sym]; days = sorted(L.spot(opts, sym, o).index)
        for r in g.itertuples():
            settle = max(d for d in days if d <= r.expiry)
            if abs(o.get(r.entry, np.nan) - r.S) > 1e-6 or abs(o.get(settle, np.nan) - r.S_T) > 1e-6:
                bad.append((sym, r.expiry, r.S, o.get(r.entry), r.S_T, o.get(settle)))
    else:
        u = opts[(opts.symbol == sym)].dropna(subset=["underlying"]).groupby("date")["underlying"].median()
        miss = sum(r.entry not in u.index for r in g.itertuples())
        print(f"{sym} (BSE): trades {len(g)}, entry days without the file's underlying: {miss}")
print("NSE v2 trades whose entry or settlement level is not NSE's official close:", len(bad), bad[:5])
