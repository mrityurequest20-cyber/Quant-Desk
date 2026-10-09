"""L1/L2 registered weekly series: autocorrelation, block-bootstrap p, and the effect of the single-instrument weeks."""
import sys
import numpy as np, pandas as pd
tr = pd.read_csv(sys.argv[1])
held = ["FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"]
rng = np.random.default_rng(7)
for st in ("short_strangle_20d", "iron_condor_20_05"):
    g = tr[(tr.strategy == st) & tr.symbol.isin(held)].copy()
    g["wk"] = pd.to_datetime(g.expiry).dt.strftime("%G-%V")
    w = g.groupby("wk")["bps"].mean().sort_index().to_numpy()
    acf = [np.corrcoef(w[:-k], w[k:])[0, 1] for k in (1, 2, 3, 4)]
    # moving block bootstrap of the centred series: P(mean* >= observed)
    c, n, B, L = w - w.mean(), len(w), 20000, 8
    starts = rng.integers(0, n - L + 1, size=(B, n // L + 1))
    idx = (starts[:, :, None] + np.arange(L)).reshape(B, -1)[:, :n]
    p = (c[idx].mean(1) >= w.mean()).mean()
    print(st, "weeks", n, "mean", round(w.mean(), 3), "ACF1-4", np.round(acf, 3), "block-bootstrap one-sided p", p)
    tot = g.groupby("wk")["bps"].mean()
    print("   top-5 weeks contribute", round(tot.nlargest(5).sum() / tot.sum(), 3), "of the total; median week", round(tot.median(), 2))
    print("   by year:", g.assign(y=g.expiry.str[:4]).groupby("y")["bps"].agg(["size", "mean"]).round(2).T.to_dict())
