"""Cross-check edges D1 (NIFTY open->close drift, Yahoo ^NSEI) on NSE's official index OHLC (warehouse nse_index_close)."""
import sys, glob, json
import numpy as np, pandas as pd
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[2]))
from quantdesk.research.edges import hac_mean
wh, research = sys.argv[1], sys.argv[2]
d = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f"{wh}/nse_index_close_*.parquet"))])
for sym in ("NIFTY", "BANKNIFTY"):
    x = d[d.symbol == sym].sort_values("date").drop_duplicates("date")
    x = x[(x.open > 0)]
    r = np.log(x.close / x.open).to_numpy()
    flat = (x.open == x.close.shift(1)).mean()
    for lab, sl in (("2019-2026", slice(None)), ("2019-2022", x.date.astype(str) < "2023"), ("2023-2026", x.date.astype(str) >= "2023")):
        rr = r if lab == "2019-2026" else r[np.asarray(sl)]
        m, t, p = hac_mean(rr)
        print(sym, lab, "n", len(rr), "mean bps", round(m * 1e4, 2), "t", round(t, 2), "p", round(p, 4))
    print(sym, "share of days open == prior close:", round(float(flat), 3))
ed = json.load(open(f"{research}/edges.json"))
for e in ed:
    if e["id"] == "D1": print("edges.json D1", e["symbol"], round(e["effect_bps"], 2), "t", round(e["t"], 2), "holdout bps", round(e["effect_holdout_bps"], 2), e["verdict"])
