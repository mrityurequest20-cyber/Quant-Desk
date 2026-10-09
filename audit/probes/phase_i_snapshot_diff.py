"""Phase I: row-level diff of two journal snapshots (rows missing or changed in the later one).

    python audit/probes/phase_i_snapshot_diff.py OLD_JOURNAL_DB NEW_JOURNAL_DB > out.json
"""
import sqlite3, sys, json
old, new = sys.argv[1], sys.argv[2]
a = sqlite3.connect(f"file:{old}?mode=ro", uri=True); b = sqlite3.connect(f"file:{new}?mode=ro", uri=True)
out = {}
for t, key in [("events","id"),("decisions","id"),("thoughts","id"),("fills","id"),("equity","ts"),("news","id"),("trades","id"),("state","key"),("checks","id")]:
    ra = {r[0]: r for r in a.execute(f"select {key}, * from {t}")}
    rb = {r[0]: r for r in b.execute(f"select {key}, * from {t}")}
    missing = [k for k in ra if k not in rb]
    changed = [k for k in ra if k in rb and ra[k] != rb[k]]
    eg = None
    if changed:
        k = changed[0]
        cols = [d[1] for d in a.execute(f"pragma table_info({t})")]
        eg = {"key": str(k)[:60], "columns_changed": [c for c, x, y in zip(cols, ra[k][1:], rb[k][1:]) if x != y]}
    out[t] = {"old_rows": len(ra), "new_rows": len(rb), "missing_in_new": len(missing), "changed_in_new": len(changed), "example": eg}
print(json.dumps(out, indent=1))
