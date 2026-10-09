"""Phase I: how news rows changed between two snapshots of the journal branch (read-only).

    python audit/probes/phase_i_news_mutation.py OLD_JOURNAL_DB NEW_JOURNAL_DB > out.json
"""
import collections
import json
import sqlite3
import sys

import pandas as pd

a = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
b = sqlite3.connect(f"file:{sys.argv[2]}?mode=ro", uri=True)
A = {r[0]: r for r in a.execute("select id, ts, seen_at, source, title, nlp from news")}
B = {r[0]: r for r in b.execute("select id, ts, seen_at, source, title, nlp from news")}
ch = [k for k in A if k in B and A[k] != B[k]]
stats, eg, dseen, dts = collections.Counter(), [], [], []
for k in ch:
    o, n = A[k], B[k]
    so, sn, to, tn = (pd.Timestamp(x) for x in (o[2], n[2], o[1], n[1]))
    stats["seen_at later"] += sn > so; stats["seen_at earlier"] += sn < so; stats["seen_at same"] += sn == so
    stats["ts later"] += tn > to; stats["ts earlier"] += tn < to; stats["ts same"] += tn == to
    no, nn = json.loads(o[5] or "{}"), json.loads(n[5] or "{}")
    ro = set(((no.get("llm") or {}).get("readers") or {})); rn = set(((nn.get("llm") or {}).get("readers") or {}))
    stats["llm readers lost"] += bool(ro - rn); stats["llm readers gained"] += bool(rn - ro); stats["nlp identical"] += no == nn
    dseen.append((sn - so).total_seconds() / 3600); dts.append((tn - to).total_seconds() / 3600)
    if len(eg) < 3:
        eg.append({"id": k, "title": o[4][:70], "old_ts": o[1], "new_ts": n[1], "old_seen": o[2], "new_seen": n[2]})
s, t = pd.Series(dseen, dtype=float), pd.Series(dts, dtype=float)
print(json.dumps({"rows_old": len(A), "rows_new": len(B), "missing_in_new": sum(k not in B for k in A), "changed_rows": len(ch),
                  "counts": dict(stats),
                  "seen_at_shift_hours": {"min": round(s.min(), 2), "median": round(s.median(), 2), "max": round(s.max(), 2)},
                  "ts_shift_hours": {"min": round(t.min(), 2), "median": round(t.median(), 2), "max": round(t.max(), 2)},
                  "examples": eg}, indent=1, default=str))
