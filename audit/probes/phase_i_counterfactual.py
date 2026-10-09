"""Phase I: can each rejected plan be valued afterwards from its decision text + archived chains (to 15:15, mid to mid)?

    python audit/probes/phase_i_counterfactual.py JOURNAL_DB CHAINS_DIR > out.json
"""
import sqlite3, json, re, sys, glob
import pandas as pd
J, CH = sys.argv[1], sys.argv[2]
c = sqlite3.connect(f"file:{J}?mode=ro", uri=True)
rows = c.execute("select id, ts, symbol, detail, context from decisions order by id").fetchall()
chains = pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CH}/*_chains.parquet"))], ignore_index=True)
chains["ts"] = pd.to_datetime(chains["ts"]); chains["expiry"] = pd.to_datetime(chains["expiry"]).dt.date
out = {"decisions": len(rows), "parsed_plan": 0, "chain_at_decision": 0, "chain_at_1515": 0, "valued": 0, "examples": []}
for i, ts, sym, det, ctx in rows:
    plan = json.loads(ctx).get("plan", "")
    m = re.match(r"(\S+) (\S+) (\d\d-\w{3}): (.*?);", plan)
    legs = re.findall(r"([+−-])(\d+)(CE|PE)@([\d.]+)", plan)
    if not m or not legs:
        continue
    out["parsed_plan"] += 1
    t0 = pd.Timestamp(ts); day = t0.date()
    exp = pd.Timestamp(f"{m.group(3)}-{day.year}").date()
    g = chains[(chains.underlying == sym) & (chains.expiry == exp) & (chains.ts.dt.date == day)]
    a = g[g.ts <= t0]; b = g[g.ts <= pd.Timestamp(f"{day} 15:15", tz=t0.tz)]
    if a.empty:
        continue
    out["chain_at_decision"] += 1
    if b.empty:
        continue
    out["chain_at_1515"] += 1
    sa, sb = a[a.ts == a.ts.max()].set_index("strike"), b[b.ts == b.ts.max()].set_index("strike")
    pnl, entry_diff = 0.0, []
    try:
        for sgn, k, right, px in legs:
            q = 1 if sgn == "+" else -1; k = float(k); s = right.lower()
            e_mid = (sa.loc[k, f"{s}_bid"] + sa.loc[k, f"{s}_ask"]) / 2
            x_mid = (sb.loc[k, f"{s}_bid"] + sb.loc[k, f"{s}_ask"]) / 2
            entry_diff.append(round(float(px) - float(sa.loc[k, f"{s}_ask" if q > 0 else f"{s}_bid"]), 2))
            pnl += q * (x_mid - e_mid)
    except KeyError:
        continue
    out["valued"] += 1
    if len(out["examples"]) < 4:
        out["examples"].append({"id": i, "ts": ts[:16], "plan": plan[:60], "chain_ts_used": str(sa.index.name and a.ts.max())[:19],
                                "plan_px_minus_archived_touch": entry_diff, "mid_to_mid_pnl_per_unit_to_1515": round(float(pnl), 2)})
print(json.dumps(out, indent=1, default=str))
