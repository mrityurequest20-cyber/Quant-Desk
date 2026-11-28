"""python -m marketlens fetch --dest DIR | build --warehouse DIR --out DIR [--symbols A,B] | site --data DIR --out DIR"""
from __future__ import annotations

import argparse
import json
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
    nc = sub.add_parser("news-corpus", help="news P1: collect the historical news corpus (NSE filings, Google News) into a folder")
    nc.add_argument("--dest", type=Path, required=True)
    nc.add_argument("--from", dest="start", default="2019-01-01")
    nc.add_argument("--to", dest="end", default="")
    nc.add_argument("--sources", default="nse,gnews")
    nc.add_argument("--budget-min", type=float, default=320)
    nc.add_argument("--release", default="", help="pull from / push to this GitHub release (news-corpus)")
    sub.add_parser("news-probe", help="news P0: which news sources answer from here, how far back, and whether the Anthropic key works")
    s = sub.add_parser("site", help="assemble the static site: the web app plus a data folder")
    s.add_argument("--data", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "news-corpus":
        import datetime as _dt
        from .news import corpus as NC
        store = None
        if a.release:
            from quantdesk.data.warehouse import ReleaseStore
            store = ReleaseStore(a.release, title="MarketLens news corpus",
                                 notes="Historical news for MarketLens (marketlens/news/corpus.py): NSE filings and Google News headlines. Not a software release.")
            store.ensure()
            have = store.assets()
            if have:
                store.pull(a.dest, have)
        c = NC.Corpus(a.dest)
        end = _dt.date.fromisoformat(a.end) if a.end else _dt.date.today() + _dt.timedelta(days=1)
        print(NC.collect(c, _dt.date.fromisoformat(a.start), end, sources=tuple(a.sources.split(",")), budget_s=a.budget_min * 60))
        print(json.dumps(NC.stats(c), indent=1))
        if store:
            store.push(a.dest, c.files())
        return 0
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
