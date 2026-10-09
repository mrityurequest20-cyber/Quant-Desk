"""Phase I: which archived chain snapshot (touch / mid / LTP) reproduces each decision's plan prices?

    python audit/probes/phase_i_snapshot_ident.py JOURNAL_DB CHAINS_DIR > out.json
"""
import sqlite3, json, re, sys, glob, collections
import pandas as pd
J, CH = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"file:{J}?mode=ro", uri=True)
chains = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CH}/*_chains.parquet"))], ignore_index=True)
chains["ts"] = pd.to_datetime(chains["ts"]); chains["expiry"] = pd.to_datetime(chains["expiry"]).dt.date
res = collections.Counter(); lag = []; kinds = collections.Counter()
for i, ts, sym, ctx in c.execute("select id, ts, symbol, context from decisions"):
    cx = json.loads(ctx); plan = cx.get("plan", ""); cat = "armed/trigger" if "armed" in cx else "ev_floor"
    m = re.match(r"(\S+) (\S+) (\d\d-\w{3}):", plan); legs = re.findall(r"([+−-])(\d+)(CE|PE)@([\d.]+)", plan)
    t0 = pd.Timestamp(ts); exp = pd.Timestamp(f"{m.group(3)}-{t0.year}").date()
    g = chains[(chains.underlying == sym) & (chains.expiry == exp) & (chains.ts <= t0) & (chains.ts >= t0 - pd.Timedelta(minutes=15))]
    snaps = sorted(g.ts.unique())
    if not snaps:
        res["no snapshot within 15 min"] += 1; continue
    hits = []
    for s in snaps:
        sn = g[g.ts == s].set_index("strike")
        def match(kind):
            for sgn, k, r, px in legs:
                if float(k) not in sn.index: return False
                row = sn.loc[float(k)]; r = r.lower()
                ref = {"touch": row[f"{r}_ask"] if sgn == "+" else row[f"{r}_bid"], "mid": (row[f"{r}_bid"] + row[f"{r}_ask"]) / 2,
                       "ltp": row[f"{r}_ltp"]}[kind]
                if abs(float(ref) - float(px)) > 0.006: return False
            return True
        for kind in ("touch", "mid", "ltp"):
            if match(kind): hits.append(s); kinds[(cat, kind)] += 1; break
    if not hits: res["no archived snapshot matches the plan prices"] += 1
    elif hits[-1] == snaps[-1] and len(hits) == 1: res["matches only the latest snapshot"] += 1
    elif len(hits) == 1: res["matches exactly one earlier snapshot"] += 1
    else: res["matches several snapshots (ambiguous)"] += 1
    if hits: lag.append((t0 - hits[-1]).total_seconds())
print(json.dumps({"price_basis_matched": {f"{a}:{b}": n for (a, b), n in kinds.items()}, "decisions": sum(res.values()), "outcome": dict(res),
                  "seconds_from_matching_snapshot_to_decision": {"median": float(pd.Series(lag).median()) if lag else None,
                                                                  "max": float(pd.Series(lag).max()) if lag else None}}, indent=1))
