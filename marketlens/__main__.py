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
    b.add_argument("--news", type=Path, default=None, help="the news corpus folder (and any briefs): builds the News page")
    fn = sub.add_parser("fetch-news", help="download the news corpus and the situation briefs from their releases (read-only)")
    fn.add_argument("--dest", type=Path, required=True)
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
    nl = sub.add_parser("news-label", help="news P3: the one-time Claude labelling run (estimate, smoke, run, audit)")
    nl.add_argument("--corpus", type=Path, required=True)
    nl.add_argument("--out", type=Path, required=True)
    nl.add_argument("--mode", choices=["estimate", "smoke", "run", "audit", "situations", "briefs"], default="estimate")
    nl.add_argument("--warehouse", type=Path, default=None, help="situations/briefs: the warehouse folder (fetched if empty)")
    nl.add_argument("--cap", type=float, default=0.0, help="dollars this run may spend (run, audit)")
    nl.add_argument("--audit-n", type=int, default=1500)
    nl.add_argument("--release", default="", help="pull the corpus from / push labels to these releases: corpus,labels")
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
    if a.cmd == "fetch-news":
        from quantdesk.data.warehouse import ReleaseStore
        a.dest.mkdir(parents=True, exist_ok=True)
        got = []
        for tag, keep in (("news-corpus", lambda n: n.endswith(".parquet")), ("news-labels", lambda n: n.startswith("brief_"))):
            st = ReleaseStore(tag)
            try:
                names = [n for n in st.assets() if keep(n)]
            except Exception as e:                              # noqa: BLE001 - a release not made yet is no error
                print(f"{tag}: not available ({e!s:.120})")
                continue
            got += st.pull(a.dest, names) if names else []
            print(f"{tag}: {len(names)} files")
        print(f"fetched {len(got)} news files into {a.dest}")
        return 0
    if a.cmd == "news-label":
        return _news_label(a)
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
        ov = build(a.warehouse, a.out, syms, news=a.news)
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




def _news_label(a) -> int:
    import anthropic
    import pandas as pd
    from .news import corpus as NC, label as NL
    stores = {}
    if a.release:
        from quantdesk.data.warehouse import ReleaseStore
        c_tag, l_tag = (a.release.split(",") + ["news-labels"])[:2]
        stores["c"] = ReleaseStore(c_tag)
        stores["l"] = ReleaseStore(l_tag, title="MarketLens news labels",
                                   notes="The one-time Claude labels of the news corpus (marketlens/news/label.py). Not a software release.")
        stores["l"].ensure()
        stores["c"].pull(a.corpus, [n for n in stores["c"].assets() if n.endswith(".parquet")])
        have = stores["l"].assets()
        if have:
            stores["l"].pull(a.out, have)
    df = NC.Corpus(a.corpus).read()
    stories = NL.select(df)
    print(f"{len(df)} rows in the corpus, {len(stories)} stories to label")
    if a.mode in ("situations", "briefs"):
        from .engine.data import Warehouse, fetch
        from .news import brief as NB, situations as NS
        wh_dir = a.warehouse or (a.out / "_warehouse")
        if not any(Path(wh_dir).glob("*.parquet")):
            fetch(Path(wh_dir), tables=("global_daily", "cm_bhav", "nse_index_close"))
        an = NS.analyse(df, *NS.inputs(Warehouse(Path(wh_dir))))
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "situations.json").write_text(json.dumps(an, default=str))
        for sid, sit in an.items():
            print(f"{sid}: {sit['stories']} stories, {len(sit['episodes'])} episodes")
        files = ["situations.json"]
        if a.mode == "briefs":
            reqs = NB.requests_for(an, NS.recent(df))
            st = NB.write(anthropic.Anthropic(), reqs, a.out, NL.total_spent(a.out, but="state_briefs.json"), a.cap or NL.TOTAL_BUDGET)
            print(json.dumps(st))
            files += [p.name for p in a.out.glob("brief_*.json")] + ["state_briefs.json"]
        if "l" in stores:
            stores["l"].push(a.out, [f for f in files if (a.out / f).exists()])
        return 0
    client = anthropic.Anthropic()
    if a.mode == "smoke":
        print(json.dumps(NL.smoke(client, stories.sample(min(6, len(stories)), random_state=1)), indent=1, default=str))
        return 0
    model = NL.OPUS if a.mode == "audit" else NL.HAIKU
    if a.mode == "audit":
        stories = NL.audit_sample(stories, a.audit_n)
    reqs = NL.requests_for(stories, model)
    est = NL.estimate(client, reqs, model)
    print("estimate:", json.dumps(est))
    if a.mode == "estimate":
        return 0
    if a.cap <= 0:
        print("no --cap given: nothing sent")
        return 1
    run = NL.Run(a.out, model)
    other = NL.total_spent(a.out, but=run.state_path.name)
    cap = min(a.cap, NL.TOTAL_BUDGET - other)                 # the owner's $13 covers labels, audit and briefs together
    print(f"cap for this run ${cap:.2f} (the rest of the job has spent ${other:.4f} of ${NL.TOTAL_BUDGET:.2f})")
    try:
        print(json.dumps(NL.label(client, reqs, run, cap), indent=1))
    finally:
        if "l" in stores:
            stores["l"].push(a.out, run.files())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
