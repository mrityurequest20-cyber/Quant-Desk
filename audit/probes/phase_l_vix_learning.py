"""Phase L: reconcile the India VIX learned weight multiplier (1.020 → 0.954) with the persisted record (read-only).

Inputs: the CLOSE journal snapshot (journal.db, memory.json, data/<date>/*_1m.csv) and, optionally, the PREV memory.json
(10-09 12:20 snapshot: memory after the 10-08 grading).

Method: the memory keeps only aggregate counts, not a per-day history. The production thoughts are re-graded with the
repo's own `learning.grade_factors` rules (5-min spacing, 30-min forward return on the recorded 1-minute bars, weight
READ_EVERY/HORIZON per read), session by session, and only the `vix` factor's increments are kept, split by what the
VIX evidence said: a fabricated read ("India VIX 0.00", the zero series) or a real one. The state before each session is
then the CLOSE state minus the increments of that session and every later one, and the multiplier the engine used that
session is `Memory.reliability` of it (2 × shrunk hit rate, PRIOR = 20, bounded 0.5–1.5). Each is compared with the
multiplier recorded on the session's thoughts (the evidence weight / DEFAULT_WEIGHTS['vix']).

    python audit/probes/phase_l_vix_learning.py CLOSE_JOURNAL_DIR [PREV_MEMORY_JSON] > out.json
"""
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quantdesk.intraday.analyst import DEFAULT_WEIGHTS  # noqa: E402
from quantdesk.intraday.learning import HORIZON, PRIOR, READ_EVERY, forward  # noqa: E402


def rel(n, hits):
    return float(np.clip(2 * (hits + PRIOR / 2) / (n + PRIOR), 0.5, 1.5))


def main(jdir: Path, prev_mem: Path | None):
    c = sqlite3.connect(f"file:{jdir / 'journal.db'}?mode=ro", uri=True)
    th = pd.read_sql("SELECT ts, symbol, evidence FROM thoughts WHERE ts >= '2026-10-05' ORDER BY id", c)
    mem = json.loads((jdir / "memory.json").read_text())
    final = mem["tables"]["factor"]["vix"]
    days = sorted({t[:10] for t in th["ts"]})
    bars = {}
    for d in days:
        for u in ("NIFTY", "BANKNIFTY"):
            p = jdir / "data" / d / f"{u}_1m.csv"
            if p.exists():
                b = pd.read_csv(p, index_col=0, parse_dates=True)
                bars.setdefault(u, []).append(b)
    bars = {u: pd.concat(v).sort_index() for u, v in bars.items()}
    for u, b in bars.items():
        b.index = pd.DatetimeIndex(b.index).tz_convert("Asia/Kolkata") if b.index.tz is not None else b.index.tz_localize("Asia/Kolkata")

    inc = defaultdict(lambda: defaultdict(lambda: {"n": 0.0, "hits": 0.0, "votes": 0, "up_votes": 0}))
    used = defaultdict(list)
    upto = {}
    w = READ_EVERY / HORIZON
    for r in th.itertuples():
        ev = json.loads(r.evidence or "[]")
        for e in ev:
            if e["factor"] == "vix" and e["weight"] > 0:
                used[r.ts[:10]].append(e["weight"] / DEFAULT_WEIGHTS["vix"])
        last = upto.get(r.symbol, "")
        if last and pd.Timestamp(r.ts) - pd.Timestamp(last) < pd.Timedelta(minutes=READ_EVERY - 0.5):
            continue
        fr = forward(bars.get(r.symbol), r.ts)
        if fr is None:
            continue
        for e in ev:
            d = float(e.get("direction") or 0)
            if e.get("factor") != "vix" or abs(d) < 0.1:
                continue
            kind = "fabricated_zero_read" if str(e.get("observation", "")).startswith("India VIX 0.00") else "real_read"
            x = inc[r.ts[:10]][kind]
            x["n"] += w
            x["hits"] += w * (d * fr > 0)
            x["votes"] += 1
            x["up_votes"] += d > 0
        upto[r.symbol] = r.ts
    # back out the state before each session from the CLOSE state
    out = {"final_close_state": final, "reliability_close": round(rel(final["n"], final["hits"]), 4), "sessions": {}}
    n, h = final["n"], final["hits"]
    for d in reversed(days):
        dn = sum(v["n"] for v in inc[d].values())
        dh = sum(v["hits"] for v in inc[d].values())
        n, h = n - dn, h - dh
        out["sessions"][d] = {"state_before": {"n": round(n, 3), "hits": round(h, 3)},
                              "reliability_before_reconstructed": round(rel(n, h), 4),
                              "multiplier_recorded_on_thoughts_median": round(float(np.median(used[d])), 4) if used[d] else None,
                              "multiplier_recorded_distinct": sorted({round(x, 4) for x in used[d]}),
                              "increments_this_session": {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in inc[d].items()}}
    out["sessions"] = dict(sorted(out["sessions"].items()))
    out["state_before_2026_10_05_is_bootstrap_plus_any_pre_reset_sessions"] = out["sessions"][days[0]]["state_before"]
    tot = defaultdict(float)
    for d in days:
        for k, v in inc[d].items():
            tot[k + "_n"] += v["n"]
            tot[k + "_hits"] += v["hits"]
    out["since_reset_totals"] = {k: round(v, 3) for k, v in tot.items()}
    fz = (tot["fabricated_zero_read_hits"]) / tot["fabricated_zero_read_n"] if tot["fabricated_zero_read_n"] else None
    out["fabricated_read_hit_rate"] = round(fz, 4) if fz is not None else None
    # counterfactual: the CLOSE multiplier had the fabricated reads never been graded
    cn, ch = final["n"] - tot["fabricated_zero_read_n"], final["hits"] - tot["fabricated_zero_read_hits"]
    out["close_multiplier_without_fabricated_reads"] = round(rel(cn, ch), 4)
    if prev_mem and prev_mem.exists():
        p = json.loads(prev_mem.read_text())["tables"]["factor"]["vix"]
        s10 = out["sessions"].get("2026-10-09", {}).get("state_before", {})
        out["check_prev_snapshot"] = {"prev_memory_vix": p, "reliability_prev": round(rel(p["n"], p["hits"]), 4),
                                      "reconstructed_before_10_09": s10,
                                      "abs_diff_n": round(abs(p["n"] - s10.get("n", np.nan)), 4),
                                      "abs_diff_hits": round(abs(p["hits"] - s10.get("hits", np.nan)), 4)}
    print(json.dumps(out, indent=1, default=float))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
