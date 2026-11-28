"""python -m marketlens fetch --dest DIR | build --warehouse DIR --out DIR [--symbols A,B] | site --data DIR --out DIR"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="marketlens")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download the public warehouse tables")
    f.add_argument("--dest", type=Path, required=True)
    b = sub.add_parser("build", help="build the app's JSON data from a warehouse folder")
    b.add_argument("--warehouse", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--symbols", default="")
    r = sub.add_parser("fetch-rules", help="download NSE's ban list and MWPL files for recent sessions")
    r.add_argument("--dest", type=Path, required=True)
    r.add_argument("--days", type=int, default=60, help="calendar weekdays back from today")
    r.add_argument("--strict", action="store_true", help="fail on any file that arrived but did not parse")
    r.add_argument("--show", action="store_true", help="print what was read (the live probe)")
    sub.add_parser("probe-sources", help="check which Tier 3 data sources answer from this machine (read-only)")
    sub.add_parser("news-probe", help="news P0: which news sources answer from here, how far back, and whether the Anthropic key works")
    s = sub.add_parser("site", help="assemble the static site: the web app plus a data folder")
    s.add_argument("--data", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "news-probe":
        from .news.probe import main as news_probe_main
        return news_probe_main()
    if a.cmd == "probe-sources":
        from .probe import main as probe_main
        return probe_main()
    if a.cmd == "fetch":
        from .engine.data import fetch
        print(f"fetched {fetch(a.dest)} files into {a.dest}")
    elif a.cmd == "build":
        from .engine.build import build
        syms = [x.strip() for x in a.symbols.split(",") if x.strip()] or None
        ov = build(a.warehouse, a.out, syms)
        print(f"built {len(ov['screener'])} instruments, as of {ov['asof']}")
    elif a.cmd == "fetch-rules":
        import datetime as dt
        import pandas as pd
        from .engine import rules as R
        today = dt.date.today()
        # the next session's ban list is published the evening before, under that session's date
        nxt = (pd.Timestamp(today) + pd.offsets.BDay(1)).date()
        days = [d.date() for d in pd.bdate_range(end=nxt, periods=a.days + 1)][::-1]
        rep = R.fetch(a.dest, days, strict=a.strict)
        if a.show:
            ban, mw = R.load(a.dest)
            print("sources:", rep["urls"])
            print("errors:", rep["errors"] or "none")
            if len(ban):
                last = ban.loc[ban["symbol"] == "", "date"].max()
                print(f"ban list for {pd.Timestamp(last).date()}:", sorted(ban.loc[(ban["date"] == last) & (ban["symbol"] != ""), "symbol"]))
            if len(mw):
                last = mw["date"].max()
                m = mw[mw["date"] == last].sort_values("util", ascending=False)
                print(f"MWPL {pd.Timestamp(last).date()}: {len(m)} stocks; fullest:")
                print(m.head(12)[["symbol", "mwpl", "oi", "util", "limit_text"]].to_string(index=False))
        if a.strict and (rep["ban_days"] == 0 or rep["mwpl_days"] == 0):
            print("strict: no ban list or no MWPL file was read")
            return 1
    elif a.cmd == "site":
        web = Path(__file__).parent / "web"
        if a.out.exists():
            shutil.rmtree(a.out)
        shutil.copytree(web, a.out)
        shutil.copytree(a.data, a.out / "data")
        print(f"site in {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
