"""Phase F3: the desk's Black-Scholes, Greeks and IV vs an independent implementation, and IV consistency on the
recorded chains (put-call parity with the desk's fixed r, q vs the chain's own forward)."""
import sys, glob, math
from pathlib import Path
import numpy as np, pandas as pd
from scipy.stats import norm
from scipy.optimize import brentq
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from quantdesk.options.pricing import bs_price, greeks, implied_vol
from quantdesk.intraday.chains import IntradayPricer, time_to_expiry

def ref(S, K, T, r, q, v, right):
    d1 = (math.log(S / K) + (r - q + v * v / 2) * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    if right == "CE":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)

rng = np.random.default_rng(3); worst = {"price": 0, "delta": 0, "gamma": 0, "vega": 0, "theta": 0, "iv": 0}
for _ in range(3000):
    S = 22000; K = S * rng.uniform(.9, 1.1); T = rng.uniform(1 / 365 / 24, .3); v = rng.uniform(.06, .6); right = rng.choice(["CE", "PE"])
    r, q = .065, .012
    p = float(bs_price(S, K, T, r, q, v, right)); worst["price"] = max(worst["price"], abs(p - ref(S, K, T, r, q, v, right)))
    g = greeks(S, K, T, r, q, v, right); h = S * 1e-4
    fd = {"delta": (ref(S + h, K, T, r, q, v, right) - ref(S - h, K, T, r, q, v, right)) / (2 * h),
          "gamma": (ref(S + h, K, T, r, q, v, right) - 2 * ref(S, K, T, r, q, v, right) + ref(S - h, K, T, r, q, v, right)) / h ** 2}
    worst["delta"] = max(worst["delta"], abs(float(g["delta"]) - fd["delta"]))
    worst["gamma"] = max(worst["gamma"], abs(float(g["gamma"]) - fd["gamma"]) / max(fd["gamma"], 1e-9))
    if p > 0.05:
        iv = implied_vol(p, S, K, T, r, q, right); worst["iv"] = max(worst["iv"], abs(iv - v))
print("max |price - ref| (pts):", round(worst["price"], 8), "| max |delta - FD|:", round(worst["delta"], 6),
      "| max rel gamma err:", round(worst["gamma"], 5), "| max |IV - true| (p > 0.05):", round(worst["iv"], 6))
print("greeks keys / units:", {k: round(float(v), 4) for k, v in greeks(22000, 22000, 7 / 365, .065, .012, .14, "CE").items()})

# IV consistency on recorded chains: ATM CE IV vs PE IV with the desk's r, q (and the gap the chain's own forward implies)
pr = IntradayPricer()
rows = []
for f in sorted(glob.glob(f"{sys.argv[1]}/*_chains.parquet")):
    try:
        d = pd.read_parquet(f)
    except Exception:
        continue
    d["ts"] = pd.to_datetime(d.ts)
    for (u, ts, ex), g in d.groupby(["underlying", "ts", "expiry"]):
        if ts.tz_convert("Asia/Kolkata").minute % 30 or not (9 <= ts.tz_convert("Asia/Kolkata").hour < 15):
            continue
        g = g.set_index("strike").sort_index(); S = float(g.spot.iloc[0]); exd = pd.Timestamp(ex).date()
        T = time_to_expiry(ts, exd)
        if T < 1 / 365:
            continue
        k = g.index[np.argmin(abs(g.index - S))]; r = g.loc[k]
        if not (r.ce_bid > 0 and r.ce_ask > r.ce_bid and r.pe_bid > 0 and r.pe_ask > r.pe_bid):
            continue
        c, p = (r.ce_bid + r.ce_ask) / 2, (r.pe_bid + r.pe_ask) / 2
        ivc, ivp = pr.implied(c, k, "CE", S, T), pr.implied(p, k, "PE", S, T)
        F = k + math.exp(pr.r * T) * (c - p)
        q_impl = pr.r - math.log(F / S) / T
        rows.append({"u": u, "dte": T * 365, "ivc": ivc * 100, "ivp": ivp * 100, "gap_vol_pts": (ivp - ivc) * 100,
                     "fwd_basis_bps": (F / (S * math.exp((pr.r - pr.q) * T)) - 1) * 1e4, "q_implied": q_impl,
                     "rec_ce_iv": r.ce_iv, "rec_pe_iv": r.pe_iv})
x = pd.DataFrame(rows)
if len(x):
    x["dte_b"] = pd.cut(x.dte, [0, 2, 7, 15, 40, 400])
    print(x.groupby(["u", "dte_b"], observed=True).agg(n=("ivc", "size"), put_minus_call_iv=("gap_vol_pts", "median"),
          fwd_vs_desk_bps=("fwd_basis_bps", "median"), q_implied=("q_implied", "median")).round(3).to_string())
    print("recorded IV vs desk-recomputed IV (CE, median abs diff, vol pts):", round(float((x.rec_ce_iv - x.ivc).abs().median()), 3))
