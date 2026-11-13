"""`quantdesk data …`: the market-data warehouse (quantdesk/data/warehouse.py).

  update   fetch every missing day in a range (default: the last 10 days) and today's API snapshots;
           with --release, pull the files it touches from the GitHub release first and push what changed
  status   what the warehouse holds: rows, first/last day, gaps; NSE's holiday list vs the config's
  health   did each data channel deliver today, and is it sane? (read-only; exit 1 if a critical one is bad or missing)
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


def cmd_health(cfg, a):
    import datetime as _dt
    from . import health as H
    store = H.GitHubStore(a.repo, os.environ.get("GITHUB_TOKEN") or None)
    now = _dt.datetime.now(H.IST)
    day = _dt.date.fromisoformat(a.day) if a.day else now.date()
    rep = H.build_report(store, cfg, day, now)
    if a.json:
        print(json.dumps(rep.to_dict(), indent=1, default=str))
    else:
        print(rep.markdown())
    if a.summary and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(rep.markdown() + "\n")
    if rep.failed():
        raise SystemExit(1)


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


def cmd_record_session(cfg, a):
    from . import session_record as SR
    out = SR.run(cfg, until=a.until, data_dir=Path(a.data) if a.data else None)
    if not out.get("recorded"):
        return
    if not out.get("bars") and not out.get("chains"):
        raise SystemExit("record-session: nothing was recorded this session (every source failed)")


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
    x = ss.add_parser("record-session", help="record the session without a desk: index and futures 1-minute bars and an "
                                             "option-chain snapshot a minute (Kotak, else Yahoo + NSE), to --until (IST); "
                                             "data only, no order of any kind")
    x.add_argument("--until", help="HH:MM IST (default the close, 15:30)")
    x.add_argument("--data", help="recorder folder (default runtime/intraday/data)")
    x.set_defaults(fn=cmd_record_session)
    x = ss.add_parser("archive-session", help="keep the recorded chains and bars as Parquet (chains-YYYY release)")
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
    x = ss.add_parser("kite-record", help="Kite: record websocket ticks (with five-level depth for the futures) to Parquet until --until (IST), market data only; docs/ml/KITE_TRIAL.md")
    x.add_argument("--out", required=True, help="folder for the ticks (never inside a git tree outside runtime/)")
    x.add_argument("--until", required=True, help="HH:MM IST")
    x.add_argument("--with-reference", action="store_true", help="after the close, also fetch Kite's historical minute candles as the reference")
    x.set_defaults(fn=cmd_kite_record)
    x = ss.add_parser("fyers-feed", help="Fyers: MCX and currency near-month futures (price, book, OI) to the private live relay every 5 s until --until (IST), as feed 'f'. "
                                         "Market data only, nothing written to disk; env FYERS_APP_ID, FYERS_DATA_TOKEN, LIVE_URL, LIVE_INGEST_TOKEN (docs/FEEDS.md)")
    x.add_argument("--until", required=True, help="HH:MM IST")
    x.add_argument("--metrics", help="write the run's counts (no price, no token) here as JSON")
    x.set_defaults(fn=cmd_fyers_feed)
    x = ss.add_parser("kite-compare", help="Kite: the session's measures from a recorded folder (counts and ratios only)")
    x.add_argument("--dir", required=True)
    x.add_argument("--day", required=True, help="YYYY-MM-DD")
    x.add_argument("--desk-dir", help="the desk journal's data/<day> folder with <symbol>_1m.csv, for C2")
    x.add_argument("--json-out", help="write the report here")
    x.set_defaults(fn=cmd_kite_compare)
    x = ss.add_parser("external-verify", help="compare random sessions with an independent daily source (Yahoo) and set "
                                              "the dataset's status")
    x.add_argument("--out", help="output root (default runtime/external)")
    x.add_argument("--n", type=int, default=80, help="sessions sampled per symbol")
    x.set_defaults(fn=cmd_external_verify)
    x = ss.add_parser("kotak-universe", help="build the list of instruments the relay's Kotak poller fetches (F&O stocks and futures, indices, index chains) and push it to the relay (env KOTAK_CONSUMER_KEY, LIVE_URL, LIVE_INGEST_TOKEN)")
    x.add_argument("--push", action="store_true", help="send it to the relay; without this only the counts are printed")
    x.add_argument("--out", help="also write the universe JSON to this file (no key, no token in it)")
    x.add_argument("--fut-limit", type=int, help="look up only this many futures (a dry run)")
    x.set_defaults(fn=cmd_kotak_universe)
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
    x.add_argument("--sources", default="nse,yahoo,warehouse", help="in order of preference (nse, yahoo, warehouse: the independent cross-check)")
    x.add_argument("--from", dest="start", help="YYYY-MM-DD (default: config daily_history.start)")
    x.add_argument("--push", action="store_true", help="push the shards to the daily-history release (needs GH_TOKEN)")
    x.add_argument("--warehouse", help="folder holding the warehouse's nse_index_close_*.parquet and fo_stock_opts_*.parquet (the `warehouse` source; default runtime/warehouse)")
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
    x = ss.add_parser("evening-minutes", help="1-minute candles of the near-month future of every MCX commodity and currency pair, collected after their sessions "
                                              "(evening-minutes.yml; Kotak consumer key, data only; never fails on a Kotak problem)")
    x.add_argument("--days", type=int, default=3, help="days back to read (Kotak serves about 30): the overlap heals a missed run")
    x.add_argument("--budget-min", type=float, default=25.0, help="stop after this many minutes and record what is missing")
    x.add_argument("--segments", default="mcx,cds", help="mcx, cds or both")
    x.add_argument("--rate", type=float, default=5.0, help="requests a second (the limit is 25 and the other recorders share the key)")
    x.add_argument("--out", help="default runtime/evening")
    x.add_argument("--release-prefix", help="also keep the files on release <prefix>-YYYY (e.g. evening-minutes)")
    x.set_defaults(fn=cmd_evening_minutes)
    x = ss.add_parser("kite-evening", help="1-minute (and optionally daily) candles of the nearest two futures of every MCX commodity and currency pair from Kite's historical API, after their "
                                           "sessions (kite-evening.yml; data only; the candles stay on disk to be encrypted, never published; never fails the run on a Kite problem)")
    x.add_argument("--days", type=int, default=3, help="days of minutes to read (Kite keeps about 60; 55 is the backfill)")
    x.add_argument("--daily-days", type=int, default=0, help="also the continuous daily series back this many days (up to 1900); 0 = none")
    x.add_argument("--segments", default="mcx,cds", help="mcx, cds or both")
    x.add_argument("--budget-min", type=float, default=20.0, help="stop after this many minutes and record what is missing")
    x.add_argument("--out", help="default runtime/kite_evening")
    x.set_defaults(fn=cmd_kite_evening)
    x = ss.add_parser("stock-tape", help="every-minute option chains (quotes and 5-level order book) of one shard of the F&O stocks until a time or the close (record-stocks.yml; Kotak consumer key, data only)")
    x.add_argument("--shard", type=int, required=True)
    x.add_argument("--shards", type=int, required=True)
    x.add_argument("--part", required=True, help="e.g. morning-<shard>")
    x.add_argument("--until", help="HH:MM IST (default the close)")
    x.add_argument("--every-min", type=float, default=1.0, help="minutes between passes (1 = every minute; a rollback if Kotak's rate limit bites)")
    x.add_argument("--out", default="runtime/stock-chains")
    x.set_defaults(fn=cmd_stock_tape)
    x = ss.add_parser("stock-chains-publish", help="merge a day's stock-chain parts into three Parquet files and a counts-only manifest, and keep them on the stock-chains-YYYYQn release")
    x.add_argument("--parts", required=True, help="folder holding the parts' files")
    x.add_argument("--day", required=True)
    x.add_argument("--out", default="runtime/stock-chains-day")
    x.add_argument("--push", action="store_true")
    x.set_defaults(fn=cmd_stock_chains_publish)
    x = ss.add_parser("agreement", help="turn the relay's per-day Kite-vs-Kotak counts (a /live/health answer saved as JSON) into one small file a day: counts and percentages only (agreement.yml)")
    x.add_argument("--health", required=True)
    x.add_argument("--out", help="default runtime/agreement")
    x.set_defaults(fn=cmd_agreement)
    x = ss.add_parser("agreement-publish", help="push each day's agreement.json to the agreement-YYYY release (a later run of the same day replaces the earlier one)")
    x.add_argument("--dir", required=True)
    x.set_defaults(fn=cmd_agreement_publish)
    x = ss.add_parser("evening-publish", help="push one kite-evening run's manifest (counts and statuses, never a price) to the evening-minutes-YYYY release")
    x.add_argument("--dir", required=True, help="the run folder holding manifest.json")
    x.add_argument("--release-prefix", default="evening-minutes")
    x.set_defaults(fn=cmd_evening_publish)
    x = ss.add_parser("fx-daily", help="daily history of the FX majors and rupee crosses from 2003 (Yahoo), checked against the ECB's reference rates (fx-daily.yml; public sources, no secret, always exits 0)")
    x.add_argument("--pairs", help="only these (comma-separated), e.g. EURUSD,USDINR")
    x.add_argument("--from", dest="start", default="2003-01-01", help="YYYY-MM-DD")
    x.add_argument("--out", help="default runtime/fx_daily")
    x.add_argument("--push", action="store_true", help="push the dataset to the fx-daily release (needs GH_TOKEN; a name already there is never replaced)")
    x.set_defaults(fn=cmd_fx_daily)
    x = ss.add_parser("fx-minutes", help="1-minute FX bars (Yahoo keeps seven days; each run re-reads the last --days) (fx-minutes.yml; public source, no secret, always exits 0)")
    x.add_argument("--pairs", help="only these (comma-separated)")
    x.add_argument("--days", type=int, default=5, help="days back (Yahoo keeps 7): the overlap heals a missed night")
    x.add_argument("--out", help="default runtime/fx_minutes")
    x.add_argument("--release-prefix", help="also keep the files on release <prefix>-YYYY (e.g. fx-minutes)")
    x.set_defaults(fn=cmd_fx_minutes)
    x = ss.add_parser("status", help="coverage, gaps, and NSE's holidays vs the config")
    x.add_argument("--dir")
    x.add_argument("--release", help="pull the manifest and the small tables from this release first")
    x.add_argument("--all", action="store_true", help="with --release: pull every table (large)")
    x.set_defaults(fn=cmd_status)
    x = ss.add_parser("health", help="did each data channel deliver, and is it sane? read-only; exit 1 if a critical channel is bad or missing")
    x.add_argument("--day", help="YYYY-MM-DD (default today, IST)")
    x.add_argument("--repo", default="mrityurequest20-cyber/Quant-Desk", help="the GitHub repository whose releases and branches are read")
    x.add_argument("--json", action="store_true")
    x.add_argument("--summary", action="store_true", help="also append the table to $GITHUB_STEP_SUMMARY")
    x.set_defaults(fn=cmd_health)


def _kite_authority_ended(today=None) -> bool:
    """The owner's data-only Kite exception (docs/AUTONOMY.md) ends on kitelive.AUTHORITY_ENDS: from that day no Kite command does anything, whatever secrets are still set."""
    import pandas as pd
    from ..intraday import kitelive as KL
    return (today or pd.Timestamp.now(tz="Asia/Kolkata").date()) >= KL.AUTHORITY_ENDS


_KITE_SIDE_MODULES = ("kiteconnect", "requests", "urllib3")


def _kite_side_failure(exc: BaseException) -> bool:
    """A refusal or an outage on Kite's side (a stale token, the API, the network), as against a bug or a fault of ours (a full disk is an OSError too, and is not Kite's).
    By the class's module, so it needs no kiteconnect import."""
    return isinstance(exc, ConnectionError) or any(c.__module__.split(".")[0] in _KITE_SIDE_MODULES for c in type(exc).__mro__)


def cmd_kite_record(cfg, a):
    from . import kite_record as K
    if _kite_authority_ended():
        print("kite-record: the owner's Kite data authority has ended (docs/AUTONOMY.md); nothing recorded")
        return
    if not (os.environ.get("KITE_DATA_KEY") and os.environ.get("KITE_DATA_TOKEN")):
        print("kite-record: no Kite key or no token for today (the 'Kite token' workflow was not run); nothing recorded")
        return
    try:
        watch = cfg.get("desk.watchlist", {}) or {}                 # what the owner trades: those instruments and every option on the board are subscribed with their order book (live view only)
        rep = K.run_session(Path(a.out), a.until, with_reference=a.with_reference, watchlist=watch if isinstance(watch, dict) else {},
                            stock_steps=int(cfg.get("desk.stock_option_steps", 8) or 8))
    except (K.KiteRecordError, ValueError) as exc:
        raise SystemExit(f"kite-record: {exc}") from None
    except ImportError as exc:                                     # the library did not install: that is a broken setup, not a quiet day
        raise SystemExit(f"kite-record: {type(exc).__name__}: {exc}") from None
    except Exception as exc:
        if not _kite_side_failure(exc):                            # our own bug (a changed instruments dump, a bad path): a traceback and a red run, never a quiet pass
            raise
        print(f"::warning::kite-record: no usable session today ({type(exc).__name__}); nothing recorded")      # a token that decrypts but is no longer valid (the daily workflow was not run), an API refusal, the network: a clean exit
        return
    print(f"kite-record: {rep['day']}: {rep['ticks']:,} ticks in {rep['parts']} parts, instruments {sorted(rep['tokens'])}")


def cmd_fyers_feed(cfg, a):
    import datetime as _dt
    import json as _json
    import re as _re

    from . import fyers_feed as F
    from .live_push import LivePusher
    if not _re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", a.until or ""):
        raise SystemExit("fyers-feed: --until must be HH:MM")
    if _dt.datetime.now(F.IST).date() >= F.AUTHORITY_ENDS:
        print("fyers-feed: the owner's Fyers data authority has ended (docs/AUTONOMY.md); nothing streamed")
        return
    app_id, token = (os.environ.get("FYERS_APP_ID") or "").strip(), (os.environ.get("FYERS_DATA_TOKEN") or "").strip()
    url, ingest = (os.environ.get("LIVE_URL") or "").strip(), (os.environ.get("LIVE_INGEST_TOKEN") or "").strip()
    if not (app_id and token):
        print("fyers-feed: no Fyers app id or no token for today (the login did not run or failed); nothing streamed")
        return
    if not (url and ingest):
        print("fyers-feed: no live relay configured (LIVE_URL, LIVE_INGEST_TOKEN); the feed is display only, so nothing to do")
        return
    watch = cfg.get("desk.watchlist", {}) or {}
    try:
        rep = F.run(a.until, app_id, token, LivePusher(url, ingest, src="f"), watchlist=watch if isinstance(watch, dict) else {})
    except (OSError, ValueError) as exc:                            # Fyers or the network (urllib's errors are OSErrors), or an answer that is not JSON: a warning, not a red run
        rep = {"stopped": f"Fyers side: {type(exc).__name__}"}
        print(f"::warning::fyers-feed: {rep['stopped']}")
    if a.metrics:
        Path(a.metrics).write_text(_json.dumps(rep, indent=1, default=str))
    for n in rep.get("notes") or []:
        print(f"::warning::fyers-feed: {n}")
    for n in rep.get("shape") or []:
        print(f"::warning::fyers-feed: an answer it could not read: {n}")
    print(f"fyers-feed: {rep.get('contracts', 0)} contracts, {rep.get('cycles', 0)} cycles, {rep.get('pushed', 0)} quotes pushed, "
          f"{rep.get('books', 0)} books, {rep.get('errors', 0)} errors; stopped: {rep.get('stopped')}")
    if str(rep.get("stopped", "")).startswith(("Fyers refused", "blocked")):
        print(f"::warning::fyers-feed: {rep['stopped']}")


def cmd_kite_compare(cfg, a):
    import json as _json

    from . import kite_compare as KC
    rep = KC.session_report(Path(a.dir), a.day, Path(a.desk_dir) if a.desk_dir else None)
    print(KC.render(rep))
    if a.json_out:
        Path(a.json_out).write_text(_json.dumps(rep, indent=1, default=str))


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
        wh = Path(a.warehouse) if a.warehouse else Path(cfg.runtime_dir) / "warehouse"
        by = {"nse": lambda: D.NseSource(gap=D.settings(cfg)["gap_sec"]), "yahoo": lambda: D.YahooSource(cfg), "warehouse": lambda: D.WarehouseSource(wh)}
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


def cmd_evening_minutes(cfg, a):
    """MCX and currency minutes after their sessions; a Kotak problem is a ::warning:: and the exit status stays 0."""
    from ..intraday.feeds import IST as TZ
    from ..intraday.kotak import KotakClient, KotakError
    from . import evening_minutes as E
    from .collect_wide import release_tag
    try:
        client = KotakClient.from_env()
    except KotakError:
        raise SystemExit("evening-minutes: no KOTAK_CONSUMER_KEY")
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "evening"
    segs = tuple(s.strip() for s in a.segments.split(",") if s.strip() in E.EXCHANGES)
    today = E.session_day(pd.Timestamp.now(tz=TZ))
    man = E.run(client, out, today, days=a.days, segments=segs, rate=a.rate, budget_s=a.budget_min * 60, say=lambda m: print(m, flush=True))
    run = Path(man["path"])
    line = ", ".join(f"{k} {t['served']}/{t['asked']}" for k, t in man["totals"].items()) or "nothing collected"
    print(f"{run}: {line}", flush=True)
    bad = [k for k, v in man["segments"].items() if v.get("error")] + [k for k, t in man["totals"].items() if t["served"] * 2 < t["asked"]]
    if bad or man.get("stopped"):
        print(f"::warning::evening-minutes: incomplete run ({line}; problems: {', '.join(sorted(set(bad))) or 'none'}"
              f"{'; stopped: ' + str(man['stopped'])[:60] if man.get('stopped') else ''})", flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Evening minutes {run.name}\n{line}\n")
            for seg, v in man["segments"].items():
                f.write(f"- {seg}: " + (v.get("error") or f"{len(v['names'])} names; instrument types seen: {', '.join(v.get('instrument_types_seen', [])[:10])}") + "\n")
    if a.release_prefix:
        try:
            _push_run(out, run, release_tag(a.release_prefix, dt.date.fromisoformat(run.name), "year"), E.release_names(run), f"Evening minutes {run.name[:4]}",
                      "Kotak 1-minute candles (traded bars, not quotes) of the near-month future of every MCX commodity and currency pair, collected after "
                      "their sessions; one set per run (quantdesk/data/evening_minutes.py). Not a software release.", clobber=False)
        except Exception as exc:
            print(f"::warning::evening-minutes: files kept on disk only, release push failed ({exc!s:.120})", flush=True)


def _fx_pairs(a):
    from . import fx as FX
    want = [p.strip().upper() for p in (a.pairs or "").split(",") if p.strip()]
    return [p for p in want if p in FX.PAIRS] or None


def cmd_kite_evening(cfg, a):
    """MCX and currency candles from Kite after their sessions. A Kite problem is a ::warning:: and the exit status stays 0; the candles never leave the runner unencrypted."""
    from ..intraday.feeds import IST as TZ
    from . import kite_evening as KE
    if _kite_authority_ended():
        print("kite-evening: the owner's Kite data authority has ended (docs/AUTONOMY.md); nothing collected")
        return
    key, token = os.environ.get("KITE_DATA_KEY"), os.environ.get("KITE_DATA_TOKEN")
    if not (key and token):
        print("::warning::kite-evening: no Kite key or no token for today (the login did not run or failed); nothing collected")
        return
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "kite_evening"
    segs = tuple(s.strip() for s in a.segments.split(",") if s.strip() in KE.EXCHANGES)
    try:
        from kiteconnect import KiteConnect
        kite = KiteConnect(api_key=key)
        kite.set_access_token(token)
        man = KE.run(kite, out, KE.session_day(pd.Timestamp.now(tz=TZ)), days=a.days, daily_days=a.daily_days, segments=segs, budget_s=a.budget_min * 60,
                     say=lambda m: print(m, flush=True))
    except ImportError as exc:
        raise SystemExit(f"kite-evening: {type(exc).__name__}: {exc}") from None
    run = Path(man["path"])
    line = ", ".join(f"{k} {t['served']}/{t['asked']}" for k, t in man["totals"].items()) or "nothing collected"
    print(f"{run.name}: {line}", flush=True)
    bad = [k for k, v in man["segments"].items() if v.get("error")] + [k for k, t in man["totals"].items() if t["served"] * 2 < t["asked"]]
    if bad or man.get("stopped"):
        print(f"::warning::kite-evening: incomplete run ({line}; problems: {', '.join(sorted(set(bad))) or 'none'}{'; stopped: ' + str(man['stopped'])[:70] if man.get('stopped') else ''})",
              flush=True)
    leak = KE.publishable(man)
    if leak:
        raise SystemExit(f"kite-evening: the manifest would carry price data ({leak[:3]}); not written for publishing")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Kite evening candles {run.name}\n{line}\n")


def cmd_stock_tape(cfg, a):
    """One shard of the every-minute F&O stock chains. A Kotak problem is a ::warning:: and the exit status stays 0 (the other shards go on)."""
    from ..core.calendar import TradingCalendar
    from ..intraday.feeds import IST as TZ
    from ..intraday.kotak import KotakClient, KotakError
    from . import stock_chains as SC
    if not 1.0 <= a.every_min <= 5.0:
        raise SystemExit("stock-tape: --every-min must be between 1 and 5")
    try:
        until = dt.time.fromisoformat(a.until) if a.until else None
    except ValueError:
        raise SystemExit(f"stock-tape: --until {a.until!r} is not HH:MM") from None
    now = pd.Timestamp.now(tz=TZ)
    if not TradingCalendar(cfg.holidays()).is_trading_day(now.date()):
        print(f"stock-tape: {now.date()} is not an NSE trading day; nothing to record")
        return
    try:
        client = KotakClient.from_env(min_gap=SC.MIN_GAP)                     # paced: at most 2.5 calls a second a shard
    except KotakError:
        print("::warning::stock-tape: no KOTAK_CONSUMER_KEY; nothing recorded")
        return
    try:
        man = SC.run_shard(client, Path(a.out), a.shard, a.shards, a.part, until, every_min=a.every_min, say=lambda m: print(m, flush=True))
    except Exception as exc:                                              # noqa: BLE001 - one shard failing never fails the others
        print(f"::warning::stock-tape shard {a.shard}: {type(exc).__name__}: {exc!s:.200}")
        return
    print(f"stock-tape shard {a.shard}/{a.shards} {a.part}: {man['recorded']} of {man['stocks']} stocks, {man['chain_rows']:,} chain rows, {man['depth_rows']:,} book rows, "
          f"{man.get('failures')} failed attempts of {man.get('attempts')}", flush=True)
    if man["stocks"] and man["recorded"] * 2 < man["stocks"]:
        print(f"::warning::stock-tape shard {a.shard}: fewer than half the stocks recorded ({man['recorded']} of {man['stocks']})", flush=True)


def cmd_stock_chains_publish(cfg, a):
    import shutil

    from . import stock_chains as SC
    from .collect_wide import release_tag
    from .warehouse import ReleaseStore
    try:
        dt.date.fromisoformat(a.day)
    except ValueError:
        raise SystemExit(f"stock-chains-publish: {a.day!r} is not a date") from None
    out = Path(a.out)
    if out.exists():
        if "runtime" not in out.resolve().parts or out.resolve() == Path.cwd().resolve() or any(out.resolve() == p for p in Path.cwd().resolve().parents):
            raise SystemExit(f"stock-chains-publish: refusing to empty {out}: the output folder must be a sub-folder of a runtime/ directory")
        shutil.rmtree(out)
    man = SC.consolidate(Path(a.parts), out, a.day)
    print(f"{a.day}: {man['recorded']} of {man['stocks']} stocks, {man['minutes_total']:,} stock-minutes (coverage {man['coverage']}), rows {man['rows']}, {man['bad_parts']} unreadable part(s)", flush=True)
    leak = SC.publishable(man)
    if leak:
        raise SystemExit(f"stock-chains-publish: the manifest would carry something it should not ({leak[:3]})")
    if not a.push:
        return
    if not man["recorded"] or not man["files"]:                            # a late or empty run must never reach the release, let alone replace a good day
        print("::warning::stock-chains-publish: nothing was recorded; nothing published", flush=True)
        return
    tag = release_tag("stock-chains", dt.date.fromisoformat(a.day), "quarter")
    store = ReleaseStore(tag, title=f"Stock option chains {tag[-6:]}", notes="Every-minute option chains and five-level order books of the F&O stocks (Kotak), one set of files per day. Not a software release.")
    try:
        names = man["files"] + [f"{a.day}_stock_chains_manifest.json"]
        store.push(out, names, clobber=False)                              # one call, so the data and its manifest go together; a day's data is written once: a name already there is never replaced
        print(f"pushed {len(names)} file(s) to release {tag}", flush=True)
    except Exception as exc:                                              # noqa: BLE001 - a failed push (or a day already kept) is a warning; the parts are still artifacts
        print(f"::warning::stock-chains-publish: not published ({exc!s:.150}); the parts are still artifacts", flush=True)


def cmd_agreement(cfg, a):
    import json as _json

    from . import agreement as AG
    try:
        health = _json.loads(Path(a.health).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("::warning::agreement: the relay's health answer could not be read; nothing recorded")
        return
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "agreement"
    made = AG.build(health, out)
    for m in made:
        print(f"{m['day']}: {m['agree_pct']}% of {m['pairs']:,} pairs agree over {m['cycles']:,} cycles" + (" (partial day)" if m["partial"] else ""), flush=True)
    if not made:
        print("::warning::agreement: the relay holds no tally yet (the poller was off, or no session has run since it was switched on)", flush=True)


def cmd_agreement_publish(cfg, a):
    from .collect_wide import release_tag
    root = Path(a.dir)
    for run in sorted(p for p in root.glob("*") if p.is_dir() and (p / "agreement.json").exists()):
        try:
            _push_run(root, run, release_tag("agreement", dt.date.fromisoformat(run.name), "year"), ["agreement.json"], f"Kite vs Kotak agreement {run.name[:4]}",
                      "Per-day counts of how often the two live sources agreed (no price, no name). Not a software release.", clobber=True)
        except Exception as exc:                                              # noqa: BLE001 - a failed push is a warning, never a red run
            print(f"::warning::agreement-publish: {run.name} kept on disk only ({exc!s:.120})", flush=True)


def cmd_evening_publish(cfg, a):
    import json as _json

    from . import kite_evening as KE
    from .collect_wide import release_tag
    run = Path(a.dir)
    f = run / "manifest.json"
    if not f.exists():
        print("evening-publish: no manifest to push")
        return
    man = _json.loads(f.read_text(encoding="utf-8"))
    leak = KE.publishable(man)
    if leak:
        raise SystemExit(f"evening-publish: refused, the manifest carries price-like data ({leak[:3]})")
    try:
        day = dt.date.fromisoformat(run.name)
    except ValueError:
        raise SystemExit(f"evening-publish: the run folder {run.name!r} is not a date") from None
    if str(man.get("as_of")) != run.name:                                                     # the manifest does not choose its own release or file name
        raise SystemExit(f"evening-publish: refused, the manifest says {man.get('as_of')!r} but the run folder is {run.name!r}")
    try:
        _push_run(run.parent, run, release_tag(a.release_prefix, day, "year"), ["manifest.json"], f"Evening minutes {day.year}",
                  "Per-day manifests (counts and statuses) of the MCX and currency evening candles; the candles themselves are licensed and are not published. Not a software release.",
                  clobber=True)
    except Exception as exc:                                              # noqa: BLE001 - a failed push is a warning, the run is not red for it
        print(f"::warning::evening-publish: manifest kept on disk only, release push failed ({exc!s:.120})", flush=True)


def cmd_fx_daily(cfg, a):
    """FX daily history; any problem is a ::warning:: and the exit status stays 0."""
    from . import fx as FX
    try:
        out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "fx_daily"
        accepted = frozenset((str(m["symbol"]), str(m["date"])) for m in (cfg.get("fx.accepted_moves") or []))        # moves a person reviewed and found genuine
        man = FX.run_daily(out, _fx_pairs(a), a.start, say=lambda m: print(m, flush=True), accepted=accepted)
        bad = man["unverified_series"]
        print(f"fx-daily {man['as_of']}: {len(man['series']) - len(bad)} verified, {len(bad)} unverified of {len(man['series'])}", flush=True)
        if bad:
            print(f"::warning::fx-daily: {len(bad)} series not verified (see manifest.json): {', '.join(bad[:12])}", flush=True)
        if a.push:
            run = Path(man["path"])
            _push_run(out, run, "fx-daily", FX.release_names(run), "FX daily history",
                      "Daily FX closes from Yahoo checked against the ECB's reference rates, one immutable dataset per run (quantdesk/data/fx.py). Not a software release.", clobber=False)
    except Exception as exc:
        print(f"::warning::fx-daily failed: {exc!s:.200}", flush=True)


def cmd_fx_minutes(cfg, a):
    """FX 1-minute bars; any problem is a ::warning:: and the exit status stays 0."""
    from . import fx as FX
    from .collect_wide import release_tag
    try:
        out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "fx_minutes"
        man = FX.run_minutes(out, _fx_pairs(a), a.days, say=lambda m: print(m, flush=True))
        t = man["totals"]
        print(f"fx-minutes {man['as_of']}: {t['served']}/{t['asked']} pairs served", flush=True)
        if t["served"] * 2 < t["asked"]:
            print(f"::warning::fx-minutes: incomplete run ({t['served']}/{t['asked']} pairs)", flush=True)
        if a.release_prefix:
            run = Path(man["path"])
            _push_run(out, run, release_tag(a.release_prefix, dt.date.fromisoformat(run.name), "year"), FX.release_names(run), f"FX minutes {run.name[:4]}",
                      "1-minute FX bars from Yahoo (UTC), one set per run (quantdesk/data/fx.py). Not a software release.", clobber=False)
    except Exception as exc:
        print(f"::warning::fx-minutes failed: {exc!s:.200}", flush=True)


def cmd_external_verify(cfg, a):
    from . import external_aeron as X
    out = Path(a.out) if a.out else Path(cfg.runtime_dir) / "external"
    ds = X.latest(out)
    if ds is None:
        raise SystemExit("no imported external dataset: run `data external-import` first")
    r = X.verify(ds, n=a.n)
    print(f"{ds.name}: {r['status']}")


def cmd_kotak_universe(cfg, a):
    import datetime as _dt

    from ..intraday.kotak import KotakClient, KotakError
    from . import kotak_universe as KU
    key = (os.environ.get("KOTAK_CONSUMER_KEY") or "").strip()
    if not key:
        raise SystemExit("kotak-universe: no KOTAK_CONSUMER_KEY")
    try:
        u = KU.build(KotakClient(key), _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30))).date(), fut_limit=a.fut_limit)
    except KotakError as e:
        raise SystemExit(f"kotak-universe: {type(e).__name__}: Kotak refused or could not answer") from None
    if not u["quotes"] and not u["chains"]:
        raise SystemExit("kotak-universe: nothing could be built (" + "; ".join(u["errors"][:5]) + ")")
    for e in u["errors"][:20]:
        print(f"::warning::kotak-universe: {e}")
    if a.out:
        Path(a.out).write_text(json.dumps(u, indent=1))
    if a.push:
        live_url, token = (os.environ.get("LIVE_URL") or "").strip(), (os.environ.get("LIVE_INGEST_TOKEN") or "").strip()
        if not (live_url and token):
            raise SystemExit("kotak-universe: --push needs LIVE_URL and LIVE_INGEST_TOKEN")
        try:
            ans = KU.push(u, live_url, token)
        except (ValueError, RuntimeError) as e:
            raise SystemExit(f"kotak-universe: {e}") from None
        print(f"kotak-universe: pushed to the relay: {ans.get('quotes')} instruments, {ans.get('chains')} chains; poller configured on the relay: {ans.get('kotak')}")


def cmd_kite_token(cfg, a):
    from ..intraday import kitelive as KL
    if _kite_authority_ended():
        raise SystemExit("kite-token: the owner's Kite data authority has ended (docs/AUTONOMY.md); no token is exchanged")
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
