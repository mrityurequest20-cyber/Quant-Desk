"""Audit step C: what the code actually executed, leg by leg (v2 held-out strangle), plus skips and their moves."""
import json
from pathlib import Path
import numpy as np, pandas as pd
from quantdesk.research import laws as L, warehouse_research as WR
from quantdesk.options.pricing import implied_vol_vec
HERE = Path(__file__).parent
W = Path("/home/user/quant-desk/runtime/warehouse")
HELD = ["FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"]
spec = L.load_spec(Path("/home/user/quant-desk/docs/prereg/expiry_eve_law_v2.json"))
opts = L.load(W, spec)
off = L.official_closes(W, spec)
tr = pd.read_csv(HERE / "expiry_eve_law_v2_trades.csv.gz")
tr["entry"] = pd.to_datetime(tr.entry).dt.date; tr["expiry"] = pd.to_datetime(tr.expiry).dt.date
st = tr[(tr.strategy == "short_strangle_20d") & tr.symbol.isin(HELD)].copy()
o = opts[opts.kind.isin(["CE", "PE"])].set_index(["symbol", "date", "kind", "expiry", "strike"]).sort_index()
legs = []
for r in st.itertuples():
    ks = sorted(json.loads(r.strikes) if isinstance(r.strikes, str) and r.strikes.startswith("[") else eval(r.strikes))
    for right, K in (("PE", ks[0]), ("CE", ks[-1])):
        row = o.loc[(r.symbol, r.entry, right, r.expiry, K)]
        row = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        T = WR._year_frac(r.entry, r.expiry)
        iv = implied_vol_vec(np.array([row["close"]]), r.S, np.array([K]), T, WR.R, WR.Q, right)[0]
        d = float(WR._delta(r.S, K, T, iv, right)) if iv > 0 else float("nan")
        legs.append({"symbol": r.symbol, "entry": r.entry, "expiry": r.expiry, "right": right, "K": K, "close": row["close"],
                     "contracts": row["contracts"], "settle_col": row.get("settle"), "delta": d, "iv": iv,
                     "otm_pct": (K / r.S - 1) * 100, "dte_days": (r.expiry - r.entry).days})
lg = pd.DataFrame(legs)
lg.to_csv(HERE / "c_legs.csv.gz", index=False)
ad = lg.delta.abs()
print("legs", len(lg), "| |delta| quantiles", ad.quantile([0, .05, .25, .5, .75, .95, 1]).round(3).to_dict())
print("share within ±0.02 of 0.20:", f"{((ad - 0.2).abs() <= 0.02).mean():.1%}", "| share beyond ±0.05:", f"{((ad - 0.2).abs() > 0.05).mean():.1%}")
print("by instrument |delta| median / share off by >0.05:", lg.assign(a=ad).groupby("symbol").apply(lambda g: (round(g.a.median(), 3), round(((g.a - .2).abs() > .05).mean(), 3))).to_dict())
print("calendar days entry->expiry:", lg.dte_days.value_counts().sort_index().to_dict())
print("leg contracts quantiles:", lg.contracts.quantile([0, .05, .1, .25, .5]).to_dict(), "| share <100:", f"{(lg.contracts < 100).mean():.1%}", "<1000:", f"{(lg.contracts < 1000).mean():.1%}")
print("by instrument share of legs <100 contracts:", lg.groupby("symbol").apply(lambda g: round((g.contracts < 100).mean(), 3)).to_dict())
print("OTM distance % median by right:", lg.groupby("right").otm_pct.median().round(2).to_dict())

# is the bhavcopy 'close' a trade price? compare close and last on traded rows
fo = pd.concat([pd.read_parquet(p, columns=["date", "symbol", "kind", "close", "last", "contracts", "src"]) for p in sorted(W.glob("fo_bhav_*.parquet"))])
fo = fo[fo.kind.isin(["CE", "PE"]) & (fo.contracts > 0)]
for src, g in fo.groupby("src"):
    has = g["last"] > 0
    print(f"NSE {src}: traded rows {len(g):,}; 'last' present {has.mean():.1%}; close == last where present {(g.loc[has,'close'] == g.loc[has,'last']).mean():.1%}")
bse = pd.concat([pd.read_parquet(p, columns=["date", "kind", "close", "last", "contracts"]) for p in sorted(W.glob("bse_fo_bhav_*.parquet"))])
bse = bse[bse.kind.isin(["CE", "PE"]) & (bse.contracts > 0) & (bse["last"] > 0)]
print(f"BSE: traded rows {len(bse):,}; close == last {(bse.close == bse['last']).mean():.1%}")

# skipped expiries: why, and were they different days?
cal = sorted(set().union(*[set(s.index) for s in off.values()]))
skips = []
for sym in HELD:
    os_ = opts[(opts.symbol == sym) & opts.kind.isin(["CE", "PE"])]
    last_seen = os_.groupby("expiry")["date"].max()
    done = set(st[st.symbol == sym].expiry)
    sp = L.spot(opts, sym, off.get(sym))
    days = sorted(sp.index)
    for e, seen in last_seen.items():
        if e > max(days) or e in done:
            continue
        settle = max((d for d in days if d <= e), default=None)
        redated = (pd.Timestamp(e) - pd.Timestamp(seen)).days > 3
        i = days.index(settle) - 1 if settle in days else None
        reason = "re-dated contract (never reached expiry)" if redated else None
        if reason is None:
            if i is None or i < 10: reason = "first 10 days of history"
            else:
                d0 = days[i]
                ch = os_[(os_.date == d0) & (os_.expiry == e) & (os_.close > 0) & (os_.contracts > 0)]
                if ch.empty: reason = "no traded contracts on the eve"
                else:
                    S = sp[d0]; T = WR._year_frac(d0, e); ok = {}
                    for right in ("CE", "PE"):
                        c = ch[ch.kind == right].drop_duplicates("strike")
                        c = c[(c.strike > S) if right == "CE" else (c.strike < S)]
                        if c.empty: ok[right] = "no OTM strike traded"; continue
                        iv = implied_vol_vec(c.close.to_numpy(float), S, c.strike.to_numpy(float), T, WR.R, WR.Q, right)
                        dl = np.array([WR._delta(S, K, T, v, right) if v > 0 else np.nan for K, v in zip(c.strike, iv)])
                        best = np.nanmin(np.abs(np.abs(dl) - 0.20)) if np.isfinite(dl).any() else np.inf
                        if best > 0.08: ok[right] = f"nearest |delta| off by {best:.2f}"
                    both = set(ch[ch.kind == "CE"].strike) & set(ch[ch.kind == "PE"].strike)
                    reason = "; ".join(f"{k}: {v}" for k, v in ok.items()) or ("no strike with both CE and PE" if not both else "other")
        move = abs(sp.get(settle, np.nan) / sp.get(days[i], np.nan) - 1) * 100 if (settle in days and i is not None and i >= 0) else np.nan
        skips.append({"symbol": sym, "expiry": e, "reason": reason, "move_pct": move})
sk = pd.DataFrame(skips)
sk.to_csv(HERE / "c_skips.csv", index=False)
print("\nskipped expiries by reason:"); print(sk.groupby(["symbol", "reason"]).size().to_string())
tm = (st.S_T / st.S - 1).abs() * 100
real = sk[~sk.reason.str.startswith("re-dated")]
print(f"\n|index move| entry->settle: traded median {tm.median():.2f}% mean {tm.mean():.2f}% (n {len(tm)}) | genuinely skipped median "
      f"{real.move_pct.median():.2f}% mean {real.move_pct.mean():.2f}% (n {real.move_pct.notna().sum()})")
for sym in HELD:
    a = (st[st.symbol == sym].S_T / st[st.symbol == sym].S - 1).abs() * 100; b = real[real.symbol == sym].move_pct.dropna()
    print(f"  {sym}: traded {a.median():.2f}% (n {len(a)}) vs skipped {b.median() if len(b) else float('nan'):.2f}% (n {len(b)})")
