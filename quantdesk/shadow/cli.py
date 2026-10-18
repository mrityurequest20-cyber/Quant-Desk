"""`python -m quantdesk shadow replay | validate | quality`: offline, read-only. Nothing here trades or touches a ceiling."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

import pandas as pd

from .detect import Detector
from . import loaders, quality, registry, replay, report, validate
from .loaders import OptionBook

DEFAULT_DATA = ["runtime/intraday/data", "runtime/intraday/backfill"]


def _roots(a) -> list[Path]:
    return [Path(p) for p in (a.data or DEFAULT_DATA)]


def _pick(reg, arg: str | None) -> list[str]:
    if not arg or arg.lower() == "all":
        return list(reg)
    if arg.lower() in ("indices", "stocks"):
        k = "index" if arg.lower() == "indices" else "stock"
        return [n for n, s in reg.items() if s.kind == k]
    out = [x.strip().upper() for x in arg.split(",") if x.strip()]
    unknown = [x for x in out if x not in reg]
    if unknown:
        raise SystemExit(f"shadow: not in the registry (add it under shadow: / instruments: in the config): {', '.join(unknown)}")
    return out


def _days(cfg, start: str, end: str) -> list[dt.date]:
    return [d.date() for d in registry.calendar(cfg).trading_days(start, end)]


def _load(cfg, reg, names, roots, days, a, say):
    if getattr(a, "pull", None):
        loaders.pull_releases(a.pull, days, roots[0] / "releases", say=say)
        roots = roots + [roots[0] / "releases"]
    bars, books = {}, {}
    for n in names:
        b, src = loaders.index_minutes(roots, n)
        bars[n] = b
        books[n] = OptionBook(loaders.option_minutes(roots, n))
        say(f"  {n}: {len(b):,} underlying minutes ({src}), {len(books[n].df):,} option minutes")
    vix, _ = loaders.index_minutes(roots, "INDIAVIX")
    return bars, books, (vix if len(vix) else None)


def cmd_replay(cfg, a):
    say = print
    reg = registry.load(cfg)
    names = _pick(reg, a.instruments)
    days = _days(cfg, a.start, a.to)
    say(f"shadow replay {a.start} .. {a.to}: {len(days)} trading days, {len(names)} instruments")
    bars, books, vix = _load(cfg, reg, names, _roots(a), days, a, say)
    df, qual = replay.run(cfg, days, names, bars, vix, books, reg, step=a.step, say=say)
    print("\n" + quality.render(list(qual.values())))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "shadow-quality.json").write_text(json.dumps(qual, indent=1, default=str))
    print(report.summary(df, qual, float(cfg.get("shadow.plausibility_ratio", 5))))
    replayed = {n: {str(d) for d in r["usable"]} for n, r in qual.items()}
    store_for = None
    if a.release:
        from ..data.warehouse import ReleaseStore
        store_for = lambda tag: ReleaseStore(tag, title=f"Shadow setups {tag[-6:]}",   # noqa: E731
                                             notes="Labelled shadow-replay setups as Parquet (quantdesk/shadow). Not a software release.")
    report.write_shards(df, out, replayed, store_for, say)


def cmd_quality(cfg, a):
    reg = registry.load(cfg)
    names = _pick(reg, a.instruments)
    days = _days(cfg, a.start, a.to)
    bars, books, _ = _load(cfg, reg, names, _roots(a), days, a, print)
    th = quality.thresholds(cfg)
    reps = [quality.instrument_report(n, bars[n], books[n], th, reg[n].strike_step, days, bool(reg[n].lot_size)) for n in names]
    print("\n" + quality.render(reps))


def cmd_validate(cfg, a):
    st = validate.settings(cfg)
    if a.threshold is not None:
        st["match_threshold"] = a.threshold
    jp = Path(a.journal) if a.journal else Path(cfg.runtime_dir) / "intraday" / "journal.db"
    if not jp.exists():
        raise SystemExit(f"shadow validate: no journal at {jp}. Restore it first (deploy/journal.sh restore, or fetch the `journal` "
                         f"branch) or pass --journal PATH; without the live record there is nothing to compare against. FAIL")
    trades, dec = validate.read_journal(jp)
    reg = registry.load(cfg)
    days = validate.live_days(trades, dec)
    if not days:
        raise SystemExit("shadow validate: the journal holds no trades or decisions. FAIL")
    names = sorted({s for s in trades["symbol"] if s in reg}) or ["NIFTY", "BANKNIFTY"]
    names = [n for n in ["NIFTY", "BANKNIFTY"] if n in names] or names
    print(f"validating {len(trades)} closed live trades on {days[0]} .. {days[-1]} ({len(days)} sessions with live records)")
    class _A: data, pull = a.data, a.pull
    bars, books, vix = _load(cfg, reg, names, _roots(a), days, _A, print)
    df, qual = replay.run(cfg, days, names, bars, vix, books, reg, step=a.step, say=print)
    res = validate.compare(df, trades, dec, st, instruments=set(names))
    con = sqlite3.connect(f"file:{jp}?mode=ro", uri=True)
    try:
        th = pd.read_sql("SELECT ts, symbol, score, conviction, day_type, evidence FROM thoughts", con)
    finally:
        con.close()
    th["ts"] = th["ts"].map(validate._ts)
    cal = registry.calendar(cfg)
    dcfg = registry.derived_config(cfg, reg)
    for r in res["rows"]:
        if r["matched"] or r.get("setup_found"):
            continue
        det = Detector(dcfg, r["instrument"], cal, vix)
        day = r["live_entry"].date()
        exp, _ = det.expiry_for(day, books[r["instrument"]].expiries_on(day))
        r["diagnosis"] = validate.diagnose(r, det.decide(bars[r["instrument"]], r["live_entry"].floor("min"), exp), th)
    print("\n" + validate.render(res))
    if a.json:
        Path(a.json).write_text(validate.to_json(res))
    raise SystemExit(0 if res["passed"] else 1)


def register(sub):
    s = sub.add_parser("shadow", help="shadow setup replay (offline, read-only): find the desk's setups on every instrument and "
                                      "label what would have happened; `validate` checks the replay against the live record")
    ss = s.add_subparsers(dest="scmd", required=True)

    def common(x, dates=True):
        if dates:
            x.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
            x.add_argument("--to", required=True, help="YYYY-MM-DD")
        x.add_argument("--data", action="append", help="folder of minutes (repeatable; default runtime/intraday/data and .../backfill)")
        x.add_argument("--pull", metavar="PREFIX", help="first pull option-minute assets from releases PREFIX-YYYYQn / PREFIX-YYYY "
                                                       "(e.g. option-minutes) into <data>/releases")
    x = ss.add_parser("replay", help="replay the range and write shadow-setups-YYYYQn.parquet shards")
    common(x)
    x.add_argument("--instruments", default="all", help="all | indices | stocks | comma list (names from the registry)")
    x.add_argument("--out", default="_shadow")
    x.add_argument("--step", type=int, help="minutes between decision points (default shadow.decision_step_min)")
    x.add_argument("--release", action="store_true", help="also push each shard to release shadow-setups-YYYYQn (gh, GH_TOKEN)")
    x.set_defaults(fn=cmd_replay)
    x = ss.add_parser("quality", help="the data-quality report only")
    common(x)
    x.add_argument("--instruments", default="all")
    x.set_defaults(fn=cmd_quality)
    x = ss.add_parser("validate", help="replay the sessions the live desk traded or refused and compare; exits 0 PASS / 1 FAIL")
    common(x, dates=False)
    x.add_argument("--journal", help="journal.db (default runtime/intraday/journal.db; restore with deploy/journal.sh restore)")
    x.add_argument("--threshold", type=float, help="match-rate threshold (default shadow.validate.match_threshold)")
    x.add_argument("--step", type=int)
    x.add_argument("--json", help="also write the comparison here")
    x.set_defaults(fn=cmd_validate)
