"""python -m quantdesk premarket history|brief

  history  build every F&O company's results history from the warehouse folder (slow: run once a day)
  brief    build today's brief (brief.json, brief.md); builds the history itself when none is given
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from ..intraday import events as EV
from . import brief as B
from . import history as H
from . import sources as SRC


def add_parser(sub) -> None:
    s = sub.add_parser("premarket", help="the pre-market brief (docs/PREMARKET.md): today's events, every F&O company's results "
                                         "against its own history, global cues, headlines and a ranked watch-list (reads only)")
    s.add_argument("action", choices=["history", "brief"])
    s.add_argument("--warehouse", default="runtime/warehouse", help="folder of warehouse assets (fo_stock_opts_*, fo_bhav_*, "
                                                                    "corp_events_*, nse_index_close_*)")
    s.add_argument("--history", help="brief: a results history built by `premarket history` (default: build it now)")
    s.add_argument("--out", default="runtime/premarket", help="history: the history file (.parquet); brief: the output folder")
    s.add_argument("--now", help="brief: the moment to brief for (ISO, IST; default now)")
    s.add_argument("--offline", action="store_true", help="brief: skip Yahoo and the RSS feeds")
    s.set_defaults(fn=run)


def build_history(wh: dict) -> pd.DataFrame:
    so = wh["stock_opts"]
    if so is None or so.empty:
        return pd.DataFrame()
    implied = H.atm_implied(so)
    sessions = H.sessions_of(implied)
    cal = H.results_calendar(wh["corp_events"], sessions, symbols=set(implied["symbol"]))
    return H.results_history(so, implied, cal, H.inferred_results(implied))


def run(cfg, a) -> None:
    t0 = time.monotonic()
    wh = SRC.load_warehouse(Path(a.warehouse))
    if a.action == "history":
        hist = build_history(wh)
        out = Path(a.out if a.out.endswith(".parquet") else Path(a.out) / "results_history.parquet")
        out.parent.mkdir(parents=True, exist_ok=True)
        hist.to_parquet(out, index=False)
        n = hist["source"].value_counts().to_dict() if len(hist) else {}
        print(f"results history: {len(hist)} events {n} -> {out} ({time.monotonic() - t0:.0f}s)")
        return
    now = pd.Timestamp(a.now) if a.now else pd.Timestamp.now(tz=B.IST)
    now = now.tz_localize(B.IST) if now.tzinfo is None else now.tz_convert(B.IST)
    health: dict = {}
    hist = pd.read_parquet(a.history) if a.history and Path(a.history).exists() else None
    recent = SRC.latest_month(wh["stock_opts"], months=3)      # today's implied moves and the normal IV before them
    if hist is None:
        hist = build_history({**wh, "stock_opts": recent})
        health["history"] = "built now from the last three months only (run `premarket history` for the full record)"
    else:
        health["history"] = f"ok {len(hist)} events"
    inp = B.Inputs(now=now, stock_opts=recent, index_bhav=SRC.latest_month(wh["index_bhav"], 2), corp_events=wh["corp_events"],
                   index_close=wh["index_close"], history=hist, macro_events=EV.from_config(cfg),
                   holidays=tuple(cfg.get("calendar.holidays", []) or []), health=health)
    if not a.offline:
        inp.globals_ = SRC.fetch_globals(health)
        inp.headlines = SRC.fetch_headlines(health, now)
    brief = B.jsonable(B.build(inp))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "brief.json.tmp"
    tmp.write_text(json.dumps(brief, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out / "brief.json")
    (out / "brief.md").write_text(B.to_markdown(brief), encoding="utf-8")
    print("\n".join(brief["summary"]))
    print(f"-> {out / 'brief.json'} ({time.monotonic() - t0:.0f}s)")
