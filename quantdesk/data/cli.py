"""`quantdesk data …`: the market-data warehouse (quantdesk/data/warehouse.py).

  update   fetch every missing day in a range (default: the last 10 days) and today's API snapshots;
           with --release, pull the files it touches from the GitHub release first and push what changed
  status   what the warehouse holds: rows, first/last day, gaps; NSE's holiday list vs the config's
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pandas as pd

IST = "Asia/Kolkata"


def _dir(cfg, a) -> Path:
    return Path(a.dir) if a.dir else Path(cfg.runtime_dir) / "warehouse"


def cmd_update(cfg, a):
    from .nse import NSE
    from .warehouse import TABLES, ReleaseStore, Warehouse, needed_assets, update
    today = pd.Timestamp.now(tz=IST).date()
    end = dt.date.fromisoformat(a.to) if a.to else today
    start = dt.date.fromisoformat(a.start) if a.start else end - dt.timedelta(days=10)
    only = set(a.only.split(",")) if a.only else None
    if only and only - set(TABLES):
        sys.exit(f"unknown table(s): {', '.join(sorted(only - set(TABLES)))}")
    wh = Warehouse(_dir(cfg, a))
    store = ReleaseStore(a.release) if a.release else None
    if store:
        names = needed_assets(start, max(end, today))
        got = store.pull(wh.root, names)
        print(f"pulled {len(got)} file(s) from release '{a.release}'", flush=True)
        wh.dirty.clear()
    print(f"warehouse {wh.root} · {start} → {end}", flush=True)
    def checkpoint():                     # a long backfill keeps what it has fetched even if the job dies later
        if store and wh.dirty:
            store.push(wh.root, sorted(wh.dirty))
            print(f"    pushed {len(wh.dirty)} file(s)", flush=True)
            wh.dirty.clear()
    counts = update(wh, NSE(gap=a.gap), start, end, only, holidays=set(cfg.holidays()),
                    say=lambda m: print(m, flush=True), on_checkpoint=checkpoint, refetch=getattr(a, "refetch", False))
    print("rows added: " + (", ".join(f"{k} {v:,}" for k, v in counts.items()) or "none"), flush=True)
    if store:
        n = len(wh.dirty)
        store.push(wh.root, sorted(wh.dirty))
        print(f"pushed {n} file(s) to release '{a.release}'", flush=True)


def cmd_status(cfg, a):
    from .warehouse import Warehouse, holiday_diff
    wh = Warehouse(_dir(cfg, a))
    if a.release:
        from .warehouse import ReleaseStore
        store = ReleaseStore(a.release)
        small = ("manifest_", "fii_dii_", "gift_nifty_", "corp_events_", "nse_holidays_")
        names = [n for n in store.assets() if n.endswith(".parquet") and (a.all or n.startswith(small))]
        store.pull(wh.root, names)
    cov = wh.coverage()
    print(f"## Data warehouse ({wh.root})\n")
    print("| table | rows | first | last | days | files |\n|---|---:|---|---|---:|---:|")
    for r in cov.itertuples():
        print(f"| {r.table} | {r.rows:,} | {r.first or '—'} | {r.last or '—'} | {r.days:,} | {r.files} |")
    man = wh.read("manifest")
    if not man.empty:
        bad = man[man["status"] == "none"]
        recent = bad[pd.to_datetime(bad["date"]) >= pd.Timestamp.now() - pd.Timedelta(days=30)]
        if len(recent):
            print("\nNot published by NSE in the last 30 days (holidays, or still pending):")
            for t, g in recent.groupby("table"):
                print(f"- {t}: {', '.join(str(pd.Timestamp(d).date()) for d in sorted(g['date']))}")
    year = pd.Timestamp.now(tz=IST).year
    missing, extra = holiday_diff(wh, set(cfg.holidays()), year)
    if missing or extra:
        print(f"\n**Holiday list check ({year}, F&O, weekdays):**")
        for d, desc in missing:
            print(f"- NSE lists {d} ({desc}) as a holiday; config/quantdesk.yaml doesn't")
        for d in extra:
            print(f"- config/quantdesk.yaml has {d} as a holiday; NSE doesn't")
    elif not wh.read("nse_holidays").empty:
        print(f"\nHoliday list check ({year}): config/quantdesk.yaml matches NSE's F&O holidays.")


def cmd_archive(cfg, a):
    from .archive import archive
    from .warehouse import ReleaseStore
    data = Path(a.data) if a.data else Path(cfg.runtime_dir) / "intraday" / "data"
    day = dt.date.fromisoformat(a.day) if a.day else None
    store_for = None
    if a.release_prefix:
        store_for = lambda y: ReleaseStore(f"{a.release_prefix}-{y}", title=f"Option-chain archive {y}",   # noqa: E731
                                           notes="The live desk's recorded option-chain snapshots and 1-minute bars, "
                                                 "one Parquet file per session part (quantdesk/data/archive.py). "
                                                 "Not a software release.")
    names = archive(data, a.part, Path(a.out), day, store_for, say=lambda m: print(m, flush=True))
    print(f"archived {len(names)} file(s) from {data}" if names else f"nothing recorded under {data}"
          + (f" for {day}" if day else ""))


def register(sub):
    s = sub.add_parser("data", help="the market-data warehouse: NSE bhavcopy, participant OI, FII/DII, GIFT Nifty")
    ss = s.add_subparsers(dest="dcmd", required=True)
    x = ss.add_parser("update", help="fetch missing days (default: the last 10) and today's snapshots")
    x.add_argument("--from", dest="start", help="YYYY-MM-DD")
    x.add_argument("--to", help="YYYY-MM-DD (default today)")
    x.add_argument("--only", help="comma-separated tables (fo_bhav, fo_stocks, participant_oi, participant_vol, fii_dii, "
                                  "gift_nifty, corp_events, nse_holidays)")
    x.add_argument("--refetch", action="store_true", help="fetch and parse the range again even if already fetched")
    x.add_argument("--dir", help="warehouse folder (default runtime/warehouse)")
    x.add_argument("--release", help="GitHub release holding the files (e.g. warehouse): pull first, push after")
    x.add_argument("--gap", type=float, default=0.5, help="seconds between NSE requests")
    x.set_defaults(fn=cmd_update)
    x = ss.add_parser("archive-session", help="keep the desk's recorded chains and bars as Parquet (chains-YYYY release)")
    x.add_argument("--part", required=True, help="which job recorded it, e.g. morning-<run id>")
    x.add_argument("--data", help="recorder folder (default runtime/intraday/data)")
    x.add_argument("--day", help="only this day (YYYY-MM-DD)")
    x.add_argument("--out", default="_archive")
    x.add_argument("--release-prefix", default="chains", help="push to <prefix>-<year>; empty to only write files")
    x.set_defaults(fn=cmd_archive)
    x = ss.add_parser("external-import", help="external NIFTY/BANKNIFTY index minutes (github.com/aeron7/"
                                              "nifty-banknifty-intraday-data) → validated, immutable Parquet "
                                              "(external_unverified; underlying research only)")
    x.add_argument("--source", required=True, help="a local clone of the source repository")
    x.add_argument("--out", help="output root (default runtime/external)")
    x.set_defaults(fn=cmd_external_import)
    x = ss.add_parser("external-verify", help="compare random sessions with an independent daily source (Yahoo) and set "
                                              "the dataset's status")
    x.add_argument("--out", help="output root (default runtime/external)")
    x.add_argument("--n", type=int, default=80, help="sessions sampled per symbol")
    x.set_defaults(fn=cmd_external_verify)
    x = ss.add_parser("kotak-backfill", help="1-minute option, index and futures candles from Kotak (~30 days back): "
                                             "the intraday option history no free source has (traded bars, not quotes)")
    x.add_argument("--days", type=int, default=30)
    x.add_argument("--expiries", type=int, default=4, help="nearest expiries per index")
    x.add_argument("--strikes", type=int, default=20, help="strikes each side of the money (rounded to 10s)")
    x.add_argument("--symbols", default="NIFTY,BANKNIFTY")
    x.add_argument("--out", help="default runtime/intraday/backfill")
    x.add_argument("--release-prefix", help="also keep the files on release <prefix>-YYYY (e.g. option-minutes)")
    x.set_defaults(fn=cmd_kotak_backfill)
    x = ss.add_parser("truedata-import", help="TrueData Velocity export → audited, immutable Parquet with provenance "
                                              "(raw files untouched; external_unverified until checked)")
    x.add_argument("--source", required=True, help="the export folder (or a clone of the repo holding it)")
    x.add_argument("--out", help="output root (default runtime/external)")
    x.set_defaults(fn=cmd_truedata_import)
    x = ss.add_parser("truedata-verify", help="every TrueData bar against Yahoo's daily OHLC; sets the batch's status")
    x.add_argument("--out", help="output root (default runtime/external)")
    x.set_defaults(fn=cmd_truedata_verify)
    x = ss.add_parser("truedata-research", help="daily research on the verified TrueData batch: stats, the pre-registered "
                                                "rules, a causal prediction replay, the backtester (report in the batch folder)")
    x.set_defaults(fn=cmd_truedata_research)
    x = ss.add_parser("status", help="coverage, gaps, and NSE's holidays vs the config")
    x.add_argument("--dir")
    x.add_argument("--release", help="pull the manifest and the small tables from this release first")
    x.add_argument("--all", action="store_true", help="with --release: pull every table (large)")
    x.set_defaults(fn=cmd_status)


def cmd_external_import(cfg, a):
    from . import external_aeron as X
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "external"
    man = X.import_dataset(Path(a.source), out)
    ds = X.dataset_dir(out, man["source_commit"])
    print(f"{man['dataset']}: status {man['status']} · {sum(1 for s in man['sessions'] if s['accepted'])} accepted of "
          f"{len(man['sessions'])} sessions · report {ds / 'quality.md'}")


def cmd_kotak_backfill(cfg, a):
    import shutil

    from ..intraday.kotak import KotakClient, KotakError
    from .kotak_backfill import backfill, release_names
    try:
        client = KotakClient.from_env()
    except KotakError:
        raise SystemExit("kotak-backfill: no KOTAK_CONSUMER_KEY")
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "intraday" / "backfill"
    man = backfill(client, out, [s.strip().upper() for s in a.symbols.split(",") if s.strip()], days=a.days,
                   n_expiries=a.expiries, strikes=a.strikes, say=lambda m: print(m, flush=True))
    run = Path(man["path"])
    print(f"{run}: " + ", ".join(f"{u} {r.get('bars', 0):,} option bars" for u, r in man["underlyings"].items()))
    if a.release_prefix:
        from .warehouse import ReleaseStore
        stage = out / "_release"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        names = []
        for n in release_names(run):
            dst = f"{man['as_of']}_{n}"
            shutil.copyfile(run / n, stage / dst)
            names.append(dst)
        year = man["as_of"][:4]
        ReleaseStore(f"{a.release_prefix}-{year}", title=f"Option minutes {year}",
                     notes="Kotak 1-minute candles (traded bars, not quotes) for NIFTY/BANKNIFTY options near the money, "
                           "the index and its futures; one set per run (quantdesk/data/kotak_backfill.py). Not a software "
                           "release.").push(stage, names)
        print(f"pushed {len(names)} file(s) to release {a.release_prefix}-{year}")


def cmd_truedata_import(cfg, a):
    from . import external_truedata as T
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "external"
    man = T.import_export(Path(a.source), out)
    print(f"{man['dataset']}: status {man['status']} · {len(man['files'])} files · "
          f"{sum(f.get('rows_accepted', 0) for f in man['files'])} rows accepted, "
          f"{sum(f.get('rows_rejected', 0) for f in man['files'])} rejected · report {Path(man['path']) / 'quality.md'}")


def cmd_truedata_verify(cfg, a):
    from . import external_truedata as T
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "external"
    ds = T.latest(out)
    if ds is None:
        raise SystemExit("no TrueData import: run `data truedata-import` first")
    r = T.verify(ds)
    print(f"{ds.name}: {'external_verified' if r['passed'] else 'external_unverified'}")


def cmd_truedata_research(cfg, a):
    from ..research import truedata_study as S
    rep = S.run(cfg)
    from . import external_truedata as T
    ds = T.latest(Path(cfg.runtime_dir) / "external")
    (ds / "research.md").write_text(S.render(rep))
    print(ds / "research.md")


def cmd_external_verify(cfg, a):
    from . import external_aeron as X
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "external"
    ds = X.latest(out)
    if ds is None:
        raise SystemExit("no imported external dataset: run `data external-import` first")
    r = X.verify(ds, n=a.n)
    print(f"{ds.name}: {r['status']}")
