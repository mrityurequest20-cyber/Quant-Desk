"""Phase L: scan every recorded input series for invalid values (read-only).

  - recorded 1-minute bars (journal branch data/<date>/*_1m.csv): non-positive OHLC, high < low, close outside
    [low, high], duplicate stamps, minutes missing from the 09:15–15:29 session, longest run of identical closes;
  - option-chain archives (chains-2026 *.parquet): crossed quotes (bid > ask), one-sided or empty books, non-positive
    spot, missing IV, by underlying;
  - the evidence the desk journaled since the 10-05 reset: observations carrying 'nan' / 'inf' / '0.00 (' by factor.

    python audit/probes/phase_l_series_scan.py JOURNAL_DIR CHAINS_DIR > out.json      (JOURNAL_DIR holds journal.db, data/)
"""
import glob
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pandas as pd


def bars(data: Path) -> dict:
    out = {}
    for f in sorted(data.glob("*/*_1m.csv")):
        b = pd.read_csv(f, index_col=0, parse_dates=True)
        if b.empty:
            continue
        o = b[["open", "high", "low", "close"]]
        mins = pd.Series(b.index).dt.strftime("%H:%M")
        grid = pd.date_range("09:15", "15:29", freq="1min").strftime("%H:%M")
        run = (b["close"] != b["close"].shift()).cumsum()
        out[f"{f.parent.name}/{f.stem}"] = {
            "rows": len(b), "nonpositive_ohlc_rows": int((o <= 0).any(axis=1).sum()),
            "high_lt_low": int((b["high"] < b["low"]).sum()),
            "close_outside_range": int(((b["close"] > b["high"] + 1e-9) | (b["close"] < b["low"] - 1e-9)).sum()),
            "duplicate_stamps": int(b.index.duplicated().sum()),
            "missing_session_minutes": int(len(set(grid) - set(mins))) if len(b) > 30 else None,
            "longest_identical_close_run": int(run.value_counts().max())}
    return out


def chains(cdir: Path) -> dict:
    out = {}
    for p in sorted(glob.glob(f"{cdir}/*_chains.parquet")):
        d = pd.read_parquet(p)
        for u, g in d.groupby("underlying"):
            r = {"rows": len(g), "snapshots": int(g["ts"].nunique()), "nonpositive_spot": int((g["spot"] <= 0).sum())}
            for s in ("ce", "pe"):
                bid, ask = g[f"{s}_bid"], g[f"{s}_ask"]
                r[f"{s}_crossed"] = int((bid > ask).sum())
                r[f"{s}_no_bid_no_ask"] = int(((bid.fillna(0) <= 0) & (ask.fillna(0) <= 0)).sum())
                r[f"{s}_one_sided"] = int(((bid.fillna(0) <= 0) ^ (ask.fillna(0) <= 0)).sum())
                if f"{s}_iv" in g:
                    r[f"{s}_iv_missing_or_nonpositive"] = int((g[f"{s}_iv"].fillna(0) <= 0).sum())
            out[f"{Path(p).name[:-15]}/{u}"] = r
    return out


def evidence(db: Path) -> dict:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    bad = Counter()
    tot = Counter()
    ex = {}
    pat = re.compile(r"\bnan\b|\binf\b|\b0\.00 \(", re.I)
    for ts, ev in c.execute("SELECT ts, evidence FROM thoughts WHERE ts >= '2026-10-05'"):
        for e in json.loads(ev or "[]"):
            tot[e["factor"]] += 1
            if pat.search(str(e.get("observation", ""))):
                bad[e["factor"]] += 1
                ex.setdefault(e["factor"], f"{ts[:16]} {e['observation'][:90]}")
    return {"flagged_by_factor": dict(bad), "reads_by_factor_for_flagged": {f: tot[f] for f in bad}, "examples": ex}


if __name__ == "__main__":
    j, cd = Path(sys.argv[1]), Path(sys.argv[2])
    b = bars(j / "data")
    print(json.dumps({"bars": b, "bars_flagged": {k: v for k, v in b.items()
                                                  if v["nonpositive_ohlc_rows"] or v["high_lt_low"] or v["close_outside_range"]
                                                  or v["duplicate_stamps"] or (v["longest_identical_close_run"] or 0) > 30},
                      "chains": chains(cd), "evidence": evidence(j / "journal.db")}, indent=1))
