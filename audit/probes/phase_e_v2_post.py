"""Phase E: the trades after the registered v2 sample, and an independent Newey-West check of the registered weekly series.

    python audit/probes/phase_e_v2_post.py <warehouse_dir>
"""
import sys, json
from pathlib import Path
import numpy as np, pandas as pd
REPO = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(REPO))
from quantdesk.config import Config, DEFAULT_CONFIG
from quantdesk.research import laws as L
spec = L.load_spec(REPO / "docs/prereg/expiry_eve_law_v2.json")
_, tr = L.run(Path(sys.argv[1]), Config.load(DEFAULT_CONFIG), spec)
post = tr[pd.to_datetime(tr["expiry"]) > "2026-10-01"]
print(post[["symbol","strategy","entry","expiry","bps","credit_bps","cost_bps"]].to_string())
held = spec["held_out"]["instruments"]
# independent NW (Bartlett, lag floor(4(T/100)^(2/9))) on registered weekly series
cut = tr[(pd.to_datetime(tr["expiry"]) <= "2026-10-01") & tr["symbol"].isin(held)]
for st in cut["strategy"].unique():
    g = cut[cut.strategy == st]
    w = g.assign(wk=pd.to_datetime(g["expiry"]).dt.strftime("%G-%V")).groupby("wk")["bps"].mean()
    x = w.to_numpy(); T = len(x); m = x.mean(); e = x - m
    for lag in (0, int(np.floor(4*(T/100)**(2/9))), 10):
        s = e @ e / T + 2*sum((1-l/(lag+1))*(e[l:] @ e[:-l])/T for l in range(1, lag+1))
        print(st, "T", T, "lag", lag, "mean", round(m,4), "t", round(m/np.sqrt(s/T),4))
    # instruments-per-week composition
    k = g.assign(wk=pd.to_datetime(g["expiry"]).dt.strftime("%G-%V")).groupby("wk")["symbol"].nunique()
    print("  instruments/week distribution", k.value_counts().sort_index().to_dict())
    # duplicate expiry ISO week within same symbol (two expiries same week)?
    d = g.assign(wk=pd.to_datetime(g["expiry"]).dt.strftime("%G-%V")).groupby(["symbol","wk"]).size()
    print("  symbol-weeks with >1 trade:", int((d>1).sum()))
