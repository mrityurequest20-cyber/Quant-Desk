"""Phase K: production persisted evidence around each timeline point (open, 12:20 hand-over, close) for each session.
Read-only (journal copy opened mode=ro).

    python audit/probes/phase_k_prod_points.py JOURNAL_DB > out.json
"""
import json
import sqlite3
import sys

c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
out = {}
days = sorted({r[0] for r in c.execute("SELECT DISTINCT substr(ts,1,10) FROM thoughts")})
for d in days:
    q = lambda sql, *p: c.execute(sql, p).fetchall()  # noqa: E731
    th = q("SELECT ts, symbol, bias, action FROM thoughts WHERE substr(ts,1,10)=? ORDER BY id", d)
    win = lambda lo, hi: [(t[11:19], s, b, (a or "")[:70]) for t, s, b, a in th if lo <= t[11:16] <= hi]  # noqa: E731
    out[d] = {
        "events_in_insertion_order": [(i, t[11:19], lv, cat, m[:80]) for i, t, lv, cat, m in
                                      q("SELECT id, ts, level, category, message FROM events WHERE substr(ts,1,10)=? ORDER BY id", d)
                                      if cat != "session_review"],
        "first_thoughts": win("09:15", "09:20"),
        "thoughts_12_15_to_12_30": win("12:15", "12:30"),
        "last_thoughts": win("15:20", "15:31"),
        "equity_first": q("SELECT ts, equity, cash, open_trades FROM equity WHERE substr(ts,1,10)=? ORDER BY ts LIMIT 2", d),
        "equity_12_10_to_12_35": q("SELECT ts, equity, cash, open_trades FROM equity WHERE substr(ts,1,10)=? AND substr(ts,12,5) BETWEEN '12:10' AND '12:35' ORDER BY ts", d),
        "equity_last": q("SELECT ts, equity, cash, open_trades FROM equity WHERE substr(ts,1,10)=? ORDER BY ts DESC LIMIT 1", d),
        "equity_rows": q("SELECT COUNT(*) FROM equity WHERE substr(ts,1,10)=?", d)[0][0],
        "thought_gap_around_handover_min": None,
    }
    hand = [t for t, *_ in th if "12:10" <= t[11:16] <= "12:40"]
    if len(hand) > 1:
        import pandas as pd
        ts = pd.to_datetime(hand)
        out[d]["thought_gap_around_handover_min"] = round(max((ts[1:] - ts[:-1]).total_seconds()) / 60, 1)
print(json.dumps(out, indent=1, default=str))
