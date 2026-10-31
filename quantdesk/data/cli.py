"""`quantdesk data …`: the market-data warehouse (quantdesk/data/warehouse.py).

  update   fetch every missing day in a range (default: the last 10 days) and today's API snapshots;
           with --release, pull the files it touches from the GitHub release first and push what changed
  status   what the warehouse holds: rows, first/last day, gaps; NSE's holiday list vs the config's
"""
from __future__ import annotations

import datetime as dt
import os
import json
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
    x = ss.add_parser("kite-token", help="Kite Connect: exchange the owner's one-time request_token (env KITE_REQUEST_TOKEN) with KITE_DATA_KEY / KITE_DATA_SECRET for the day's access "
                                         "token, written to --out (mode 0600) and never printed. Market data only (docs/ml/KITE_TRIAL.md).")
    x.add_argument("--out", required=True)
    x.set_defaults(fn=cmd_kite_token)
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
    x.add_argument("--shard", choices=["year", "quarter"], default="year",
                   help="release per year (default) or per quarter (<prefix>-2026Q4: stays under GitHub's ~1000 assets)")
    x.add_argument("--min-gap", type=float, help="seconds between Kotak calls (default: the client's)")
    x.set_defaults(fn=cmd_kotak_backfill)
    x = ss.add_parser("collect-wide", help="read-only data collection beside the desk (collect-wide.yml): minutes for all "
                                           "five indices, the liquid stocks' chains, and a per-source health check")
    x.add_argument("--step", choices=["minutes", "stocks", "health"], required=True)
    x.add_argument("--day", help="YYYY-MM-DD (default today, IST)")
    x.add_argument("--part", default="local", help="stocks: which run recorded it (the Actions run id)")
    x.add_argument("--force", action="store_true", help="stocks: also outside the session or on a non-trading day")
    x.add_argument("--out", help="default runtime/collect")
    x.add_argument("--push", action="store_true", help="push to the GitHub releases (needs GH_TOKEN)")
    x.set_defaults(fn=cmd_collect_wide)
    x = ss.add_parser("daily-history", help="daily OHLCV since ~2013 for the indices and F&O stocks, with split/bonus "
                                            "adjustment, jump flags, a second-source cross-check and a gap report "
                                            "(daily-history.yml; read-only, no secret, always exits 0)")
    x.add_argument("--out", help="default runtime/daily_history")
    x.add_argument("--symbols", help="only these (comma-separated; indices and stocks), e.g. to test")
    x.add_argument("--sources", default="nse,yahoo", help="in order of preference (nse, yahoo)")
    x.add_argument("--from", dest="start", help="YYYY-MM-DD (default: config daily_history.start)")
    x.add_argument("--push", action="store_true", help="push the shards to the daily-history release (needs GH_TOKEN)")
    x.set_defaults(fn=cmd_daily_history)
    x = ss.add_parser("stock-minutes", help="1-minute candles for the cash series and near-month futures of the most "
                                            "liquid F&O stocks (data collection only; traded bars, not quotes)")
    x.add_argument("--stocks", type=int, default=50, help="how many stocks (ranked on the warehouse's fo_stocks, else a fixed list)")
    x.add_argument("--days", type=int, default=3)
    x.add_argument("--rate", type=float, default=5.0, help="requests a second (Kotak allows 25)")
    x.add_argument("--budget-min", type=float, default=12.0, help="stop after this many minutes and record what is missing")
    x.add_argument("--out", help="default runtime/intraday/backfill")
    x.add_argument("--release-prefix", help="also keep the files on release <prefix>-YYYY (e.g. stock-minutes)")
    x.set_defaults(fn=cmd_stock_minutes)
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
    from .collect_wide import release_tag
    from .kotak_backfill import backfill, release_names
    try:
        client = KotakClient.from_env(**({"min_gap": a.min_gap} if getattr(a, "min_gap", None) else {}))
    except KotakError:
        raise SystemExit("kotak-backfill: no KOTAK_CONSUMER_KEY")
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "intraday" / "backfill"

    def push(run: Path) -> None:
        from .warehouse import ReleaseStore
        stage = out / "_release"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        as_of, names = run.name, []
        for n in release_names(run):
            dst = f"{as_of}_{n}"
            shutil.copyfile(run / n, stage / dst)
            names.append(dst)
        tag = release_tag(a.release_prefix, dt.date.fromisoformat(as_of), getattr(a, "shard", "year"))
        ReleaseStore(tag, title=f"Option minutes {tag.rsplit('-', 1)[-1]}",
                     notes="Kotak 1-minute candles (traded bars, not quotes) for NIFTY/BANKNIFTY options near the money, "
                           "the index and its futures; one set per run (quantdesk/data/kotak_backfill.py). Not a software "
                           "release.").push(stage, names)
        print(f"pushed {len(names)} file(s) to release {tag}", flush=True)

    # each underlying goes to the release as soon as it is done: a timeout on the next one loses nothing
    man = backfill(client, out, [s.strip().upper() for s in a.symbols.split(",") if s.strip()], days=a.days,
                   n_expiries=a.expiries, strikes=a.strikes, say=lambda m: print(m, flush=True),
                   on_underlying=(lambda u, run: push(run)) if a.release_prefix else None)
    run = Path(man["path"])
    print(f"{run}: " + ", ".join(f"{u} {r.get('bars', 0):,} option bars" for u, r in man["underlyings"].items()))
    if a.release_prefix:
        push(run)                                   # the final manifest (calls, index/futures of the last underlying)


def cmd_collect_wide(cfg, a):
    """Every step is fail-safe: a problem is a ::warning:: and a health line, the exit status is always 0."""
    import argparse

    from . import collect_wide as W
    from .warehouse import ReleaseStore
    now = pd.Timestamp.now(tz=IST)
    day = dt.date.fromisoformat(a.day) if a.day else now.date()
    S = W.settings(cfg)
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "collect"
    from ..core.calendar import TradingCalendar
    if a.step != "minutes" and not a.force and not TradingCalendar(cfg.holidays()).is_trading_day(day):
        print(f"collect-wide {a.step}: {day} is not a trading day; nothing expected")
        return
    try:
        if a.step == "minutes":
            ns = argparse.Namespace(days=S["minute_days"], expiries=S["minute_expiries"], strikes=S["minute_strikes"],
                                    symbols=",".join(S["indices"]), out=str(out / "minutes"),
                                    release_prefix=S["minutes_release"] if a.push else None, shard=S["shard"],
                                    min_gap=S["min_gap_sec"])
            cmd_kotak_backfill(cfg, ns)
            if S["stock_minutes"] and S["stocks"]:
                try:                                       # the indices' result stands whatever happens to the stocks
                    stock_minutes(a, S, out, day)
                except SystemExit as exc:
                    print(f"::warning::stock option minutes: {exc}")
                except Exception as exc:
                    print(f"::warning::stock option minutes failed: {exc!s:.200}")
        elif a.step == "stocks":
            from ..intraday.kotak import KotakClient, KotakError, KotakOptionChain
            from .archive import archive
            if not a.force and not W.in_stock_window(now, S["stock_deadline"]):
                print(f"::warning::stock chains skipped: {now:%H:%M} IST is outside the session (the book is blank); "
                      "nothing recorded today")
                return
            if not S["stocks"]:
                print("::warning::collect_wide.stocks is empty in the config; nothing to capture")
                return
            try:
                client = KotakClient.from_env(min_gap=S["min_gap_sec"])
            except KotakError:
                print("::warning::no KOTAK_CONSUMER_KEY; stock chains not captured")
                return
            src = KotakOptionChain(client, strikes=S["stock_strikes"])
            data = out / "stocks"
            rep = W.snapshot_stocks(src, S["stocks"], data, S["stock_expiries"], now, say=lambda m: print(m, flush=True))
            out.mkdir(parents=True, exist_ok=True)
            (out / "stocks_report.json").write_text(json.dumps({"day": str(day), "stocks": rep}, indent=1))
            bad = [k for k, v in rep.items() if not v["ok"]]
            print(f"stock chains: {len(rep) - len(bad)}/{len(rep)} captured" + (f"; failed: {', '.join(bad)}" if bad else ""))
            if bad:
                print(f"::warning::stock chains failed for {', '.join(bad)}")
            tag = W.release_tag(S["chains_release"], day, S["shard"])
            store_for = None
            if a.push:
                store_for = lambda y: ReleaseStore(tag, title=f"Option-chain archive {tag.rsplit('-', 1)[-1]}",   # noqa: E731
                                                   notes="Option-chain snapshots recorded beside the desk (quantdesk/data/"
                                                         "collect_wide.py, archive.py). Not a software release.")
            archive(data, f"wide-eod-{a.part}", out / "stocks_parquet", day, store_for, say=lambda m: print(m, flush=True))
        else:
            man_path = out / "minutes" / str(day) / "manifest.json"
            man = json.loads(man_path.read_text()) if man_path.exists() else None
            wide = tape = None
            if a.push:
                wide_store = ReleaseStore(W.release_tag(S["chains_release"], day, S["shard"]))
                desk_store = ReleaseStore(f"{S['chains_release']}-{day.year}")
                try:
                    wide = wide_store.assets(strict=True)
                except Exception:
                    wide = None
                try:
                    tape = desk_store.assets(strict=True) + (wide or [])
                except Exception:
                    tape = None
            sm_path = out / "minutes_stocks" / str(day) / "stock_manifest.json"
            sman = json.loads(sm_path.read_text()) if sm_path.exists() else None
            rows = W.health(day, man, wide, tape, S["indices"], len(S["stocks"]), sman,
                            S["stocks"] if S["stock_minutes"] else ())
            for line in W.render(day, rows):
                print(line, flush=True)
            for r in rows:
                if r["status"] != "OK":
                    print(f"::warning::collect-wide {r['source']} {r['status']}: {r['detail']}")
            p = W.write_health(day, rows, out / "health")
            if a.push:
                ReleaseStore(W.release_tag(S["minutes_release"], day, S["shard"])).push(p.parent, [p.name])
    except SystemExit as exc:                    # kotak-backfill's "no key" exit is a skipped step here, not a failed run
        print(f"::warning::collect-wide {a.step}: {exc}")
    except Exception as exc:
        print(f"::warning::collect-wide {a.step} failed: {exc!s:.200}")


def cmd_daily_history(cfg, a):
    """Fail-safe like collect-wide: any problem is a ::warning:: and the exit status is 0."""
    import shutil

    from . import daily_history as D
    try:
        if a.start:
            cfg.data.setdefault("daily_history", {})["start"] = a.start
        by = {"nse": lambda: D.NseSource(gap=D.settings(cfg)["gap_sec"]), "yahoo": lambda: D.YahooSource(cfg)}
        names = [n.strip() for n in a.sources.split(",") if n.strip()]
        sources = [by[n]() for n in names if n in by]
        S = D.settings(cfg)
        todo = None
        if a.symbols:
            want = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
            todo = [(s, "index" if s in S["indices"] else "equity") for s in want]
        out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "daily_history"
        man = D.run(cfg, out, sources, symbols=todo, say=lambda m: print(m, flush=True))
        for line in D.render(man):
            print(line, flush=True)
        bad = man["unverified_series"]
        if bad:
            print(f"::warning::daily-history: {len(bad)} series not verified (see manifest.json): {', '.join(bad[:12])}")
        if a.push:
            from .warehouse import ReleaseStore
            ds = Path(man["path"])
            stage = out / "_release"
            if stage.exists():
                shutil.rmtree(stage)
            stage.mkdir(parents=True)
            names_out = []
            for n in D.release_names(ds):
                shutil.copyfile(ds / n, stage / f"{man['as_of']}_{n}")
                names_out.append(f"{man['as_of']}_{n}")
            ReleaseStore("daily-history", title="Daily history",
                         notes="Daily OHLCV with split/bonus adjustment, jump flags, cross-check and gap report, one immutable "
                               "dataset per run (quantdesk/data/daily_history.py). Not a software release.").push(
                stage, names_out, clobber=False)                       # immutable: a name already on the release is never replaced
            print(f"pushed {len(names_out)} file(s) to release daily-history", flush=True)
    except Exception as exc:
        print(f"::warning::daily-history failed: {exc!s:.200}")


def stock_minutes(a, S, out: Path, day: dt.date) -> None:
    """Near-the-money stock option minutes beside the indices': grouped assets in the same quarterly release."""
    import shutil

    from ..intraday.kotak import KotakClient, KotakError
    from . import kotak_backfill as K
    from .collect_wide import release_tag
    from .warehouse import ReleaseStore
    try:
        client = KotakClient.from_env(min_gap=S["min_gap_sec"])
    except KotakError:
        raise SystemExit("no KOTAK_CONSUMER_KEY")
    plan = K.asset_plan(len(S["indices"]), len(S["stocks"]), S["stock_group_size"], S["shard_trading_days"], S["asset_cap"])
    print(f"stock option minutes: {len(S['stocks'])} stocks in {plan['groups']} group file(s), about {plan['per_day']} "
          f"assets/day, {plan['per_shard']} per quarterly release (cap {plan['cap']})", flush=True)
    root = out / "minutes_stocks"
    tag = release_tag(S["minutes_release"], day, S["shard"])

    def push(_k, run: Path) -> None:
        if not a.push:
            return
        stage = root / "_release"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        names = []
        for n in K.release_names(run):
            shutil.copyfile(run / n, stage / f"{run.name}_{n}")
            names.append(f"{run.name}_{n}")
        ReleaseStore(tag, title=f"Option minutes {tag.rsplit('-', 1)[-1]}",
                     notes="Kotak 1-minute candles (traded bars, not quotes); see quantdesk/data/kotak_backfill.py. "
                           "Not a software release.").push(stage, names)
        print(f"pushed {len(names)} stock-minute file(s) to release {tag}", flush=True)

    K.backfill_stocks(client, root, K.group_stocks(S["stocks"], plan["group_size"]), days=S["minute_days"],
                      n_expiries=S["stock_minute_expiries"], window=S["stock_minute_strikes"], today=day,
                      say=lambda m: print(m, flush=True), on_group=push)


def _push_run(out: Path, run: Path, tag: str, names: list[str], title: str, notes: str, clobber: bool = True) -> None:
    """A run's files to release `tag`, named <as of>_<file>."""
    import shutil

    from .warehouse import ReleaseStore
    stage = out / "_release"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    as_of, staged = run.name, []
    for n in names:
        dst = f"{as_of}_{n}"
        shutil.copyfile(run / n, stage / dst)
        staged.append(dst)
    ReleaseStore(tag, title=title, notes=notes).push(stage, staged, clobber=clobber)
    print(f"pushed {len(staged)} file(s) to release {tag}", flush=True)


def cmd_stock_minutes(cfg, a):
    """1-minute candles for the top F&O stocks' cash series and near-month futures; never fails on a Kotak problem."""
    from ..intraday.feeds import IST as TZ
    from ..intraday.kotak import KotakClient, KotakError
    from .collect_wide import release_tag
    from .kotak_backfill import release_names, stock_minutes
    from .warehouse import ReleaseStore, Warehouse
    try:
        client = KotakClient.from_env()
    except KotakError:
        raise SystemExit("stock-minutes: no KOTAK_CONSUMER_KEY")
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "intraday" / "backfill"
    today = pd.Timestamp.now(tz=TZ).date()
    root = Path(cfg.runtime_dir) / "warehouse"
    fo = None
    try:                                  # the universe is ranked on the warehouse's fo_stocks (two months is plenty)
        root.mkdir(parents=True, exist_ok=True)
        ReleaseStore("warehouse").pull(root, [f"fo_stocks_{p}.parquet" for p in pd.period_range(end=pd.Timestamp(today), periods=2, freq="M")])
        fo = Warehouse(root).read("fo_stocks", start=today - dt.timedelta(days=45), end=today)
    except Exception as exc:
        print(f"stock-minutes: no fo_stocks to rank on ({exc!s:.100}); using the fixed list", flush=True)
    man = stock_minutes(client, out, fo, n=a.stocks, days=a.days, today=today, rate=a.rate, budget_s=a.budget_min * 60,
                        say=lambda m: print(m, flush=True))
    run = Path(man["path"])
    line = ", ".join(f"{k} {t['served']}/{t['asked']}" for k, t in man["totals"].items())
    print(f"{run}: {line}", flush=True)
    short = [k for k, t in man["totals"].items() if t["served"] * 2 < t["asked"]]
    if short or man.get("stopped"):                 # a Kotak outage or a cut-short run is a warning, not a green step
        print(f"::warning::stock-minutes: incomplete run ({line}"
              f"{'; stopped: ' + str(man['stopped'])[:80] if man.get('stopped') else ''})", flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Stock minutes {run.name}\n{line}{' (stopped: ' + str(man['stopped'])[:80] + ')' if man.get('stopped') else ''}\n")
    if a.release_prefix:
        try:                                        # never overwrite a run already on the release (a same-day re-run)
            _push_run(out, run, release_tag(a.release_prefix, dt.date.fromisoformat(run.name), "year"),
                      release_names(run, stocks=True), f"Stock minutes {run.name[:4]}",
                      "Kotak 1-minute candles (traded bars, not quotes) for the cash series and near-month futures of the "
                      "most liquid F&O stocks; one set per run (quantdesk/data/kotak_backfill.py). Not a software release.",
                      clobber=False)
        except Exception as exc:
            print(f"::warning::stock-minutes: files kept on disk only, release push failed ({exc!s:.120})", flush=True)


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


def cmd_kite_token(cfg, a):
    from ..intraday import kitelive as KL
    key, secret, req = os.environ.get("KITE_DATA_KEY"), os.environ.get("KITE_DATA_SECRET"), os.environ.get("KITE_REQUEST_TOKEN")
    if not (key and secret and req):
        raise SystemExit("kite-token: KITE_DATA_KEY, KITE_DATA_SECRET and KITE_REQUEST_TOKEN must be set in the environment")
    try:
        token = KL.exchange_token(key, secret, req.strip())
    except Exception as exc:                                              # never echo the library's message: it can carry request details
        raise SystemExit(f"kite-token: {type(exc).__name__}: could not exchange the request token (expired, already used, or wrong key/secret)") from None
    if not KL.TOKEN_RE.fullmatch(token):
        raise SystemExit("kite-token: Kite returned a token of an unexpected shape; nothing written")
    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(token)
    print("kite-token: access token written (not shown)")
