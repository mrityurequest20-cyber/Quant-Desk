"""Phase B4 instrumented funnel replay (read-only; temp dirs only).

Replays recorded sessions through the current IntradayEngine with the inputs the live desk had where available:
recorded 1m bars, the recorded real option chains (chains-2026 release), the learning memory as of the journal
snapshot (a copy), news visible from `seen_at`, and the live gating (LiveLearner with an empty registry, as in
production). Differences from live, stated: no brain/global feed, no breadth, no 5-second LTP (armed setups fire
on each 1m bar's range), Yahoo history for prior sessions.

Counts, per minute and underlying, the outcome of the entry path, every setup the playbook raised, every armed
setup, and scores each opportunity the gates removed against the underlying bars that followed (target or
invalidation first within the plan's time stop; stop first when a bar touches both).

usage: python replay_funnel.py <journal_intraday_dir> <chains_dl_dir> <out_dir> 2026-10-05 [2026-10-06 ...]
"""
from __future__ import annotations

import collections
import copy
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "deploy"))

from quantdesk.config import DEFAULT_CONFIG, Config  # noqa: E402
from quantdesk.intraday import engine as E  # noqa: E402
from quantdesk.intraday.chains import COLUMNS, DEPTH, RecordedChains  # noqa: E402
from quantdesk.intraday.feeds import ReplayFeed, normalise_bars  # noqa: E402
from quantdesk.intraday.learning import Memory  # noqa: E402
from quantdesk.intraday.recorder import SessionRecorder  # noqa: E402
from quantdesk.intraday.sim import IntradayBroker  # noqa: E402
from quantdesk.journal.journal import Journal  # noqa: E402
from quantdesk.autolearn.live import LiveLearner  # noqa: E402
import whatif  # noqa: E402

IST = "Asia/Kolkata"


def chains_for(dl: Path, day: dt.date) -> RecordedChains:
    parts = [pd.read_parquet(p) for p in sorted(dl.glob(f"{day}_*_chains.parquet"))]
    df = pd.concat(parts, ignore_index=True)
    snaps = collections.defaultdict(list)
    cols = [c for c in COLUMNS + DEPTH if c in df.columns]
    for (u, e, ts), g in df.groupby(["underlying", "expiry", "ts"], sort=True):
        ch = g.set_index("strike")[cols].astype(float).sort_index()
        for c in COLUMNS + DEPTH:
            if c not in ch.columns:
                ch[c] = np.nan
        ch = ch[COLUMNS + DEPTH]
        ch.index.name = "strike"
        ch.attrs.update({"underlying": u, "spot": float(g["spot"].iloc[0]), "expiry": pd.Timestamp(e).date(),
                         "ts": pd.Timestamp(ts).tz_convert(IST), "source": str(g["source"].iloc[0])})
        snaps[u].append(ch)
    return RecordedChains(dict(snaps))


def classify(a: str) -> str:
    a = a or ""
    for k, p in [("enter", r"^ENTER"), ("no_setup", r"^watching: no setup"),
                 ("plan_model_gate", r"no approved plan model|plan model"),
                 ("ev_floor", r"not worth it after costs"), ("sized_zero", r"sized to 0"),
                 ("record", r"record says no|track record"), ("champion_gate", r"champion model"),
                 ("outside_window", r"outside entry window"), ("first5", r"first 5 minutes"),
                 ("event", r"scheduled event"), ("breaking_news", r"breaking news"), ("rsi_veto", r"too stretched"),
                 ("spread_veto", r"spread .* too wide"), ("stale_chain", r"option chain .* old|no option chain"),
                 ("stale_feed", r"feed stale"), ("risk_gate", r"daily|max .*trades|cooldown|open positions|loss"),
                 ("global_stress", r"global stress"), ("halted", r"^halted"), ("quant_fail", r"quant layer failed"),
                 ("no_vol", r"no volatility forecast")]:
        if re.search(p, a):
            return k
    return "other:" + re.sub(r"[\d,.:₹+\-]+", "#", a)[:60]


def first_touch(bars: pd.DataFrame, t0: pd.Timestamp, d: int, stop: float, target: float, minutes: int):
    w = bars[(bars.index >= t0.floor("min") + pd.Timedelta(minutes=1)) & (bars.index < t0 + pd.Timedelta(minutes=minutes))]
    for ts, b in w.iterrows():
        hit_s = (b["low"] <= stop) if d > 0 else (b["high"] >= stop)
        hit_t = (b["high"] >= target) if d > 0 else (b["low"] <= target)
        if hit_s:
            return "stop", ts
        if hit_t:
            return "target", ts
    return "time", (w.index[-1] if len(w) else None)


def main():
    jdir, dl, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    days = [dt.date.fromisoformat(x) for x in sys.argv[4:]]
    out.mkdir(parents=True, exist_ok=True)
    cfg = Config.load(DEFAULT_CONFIG)
    syms = cfg.get("intraday.underlyings") + [cfg.get("universe.volatility_index")]
    rec = SessionRecorder(jdir / "data").load_bars(syms)
    report = {}
    for day in days:
        work = Path(tempfile.mkdtemp(prefix=f"funnel-{day}-"))
        hist = whatif.yahoo_history(cfg, syms, day)
        bars = {}
        for s in syms:
            t = rec.get(s)
            t = t[t.index.date == day] if t is not None else None
            parts = [x for x in (hist.get(s), t) if x is not None and len(x)]
            if parts:
                b = pd.concat(parts).sort_index()
                bars[s] = b[~b.index.duplicated(keep="last")]
        mem_path = work / "memory.json"
        shutil.copy(jdir / "memory.json", mem_path)
        j = Journal(work / "j.db")
        br = IntradayBroker(cfg, starting_cash=cfg.get("intraday.capital"), state_path=work / "b.json",
                            adverse_ticks=cfg.get("intraday.adverse_ticks", 1))
        news = whatif.ReplayNews(cfg, jdir / "journal.db", day)
        eng = E.IntradayEngine(cfg, ReplayFeed(bars, day), chains_for(dl, day), j, br, None, lambda *a, **k: None, None,
                               work / "reviews", news=news, memory=Memory(mem_path))
        eng.learner = LiveLearner(cfg, root=work / "autolearn")          # empty registry: as in production
        stats = collections.Counter()
        setups = collections.Counter()
        gated = []                                                          # opportunities the gates removed
        orig_enter, orig_scan, orig_arm = eng._maybe_enter, eng.playbook.scan, eng.playbook.arm
        cur = {}

        def scan(view, s, chain, now, skip=()):
            pl = orig_scan(view, s, chain, now, skip=skip)
            cur["plans"] = pl
            for p in pl:
                setups[(view.symbol, p.setup, "scan")] += 1
            return pl

        def maybe_enter(u, view, s, now):
            cur["plans"] = []
            a = orig_enter(u, view, s, now)
            c = classify(a)
            stats[(u, c)] += 1
            if c in ("plan_model_gate", "ev_floor", "record", "sized_zero"):
                for p in cur["plans"]:
                    if p.direction != 0 and p.invalidation is not None and p.target_underlying is not None:
                        gated.append({"day": str(day), "ts": str(now), "symbol": u, "setup": p.setup, "path": "confirm",
                                      "gate": c, "d": p.direction, "spot": view.spot, "stop": p.invalidation,
                                      "target": p.target_underlying, "time_stop": p.time_stop_min})
            return a

        def arm(view, s, now, **k):
            got = orig_arm(view, s, now, **k)
            for a in got:
                setups[(view.symbol, a.setup, "armed")] += 1
            return got

        eng._maybe_enter, eng.playbook.scan, eng.playbook.arm = maybe_enter, scan, arm
        E.run_replay(eng)
        j.commit()
        dec = j.df("SELECT ts, symbol, strategy, action, detail, context FROM decisions")
        for r in dec.itertuples():
            ctx = json.loads(r.context or "{}")
            a = ctx.get("armed")
            if a and "reached its level" in (r.detail or ""):
                lvl, inv = float(a["level"]), float(a["invalidation"])
                risk = abs(lvl - inv)
                rr = {"orb": 1.5}.get(a["setup"], 2.0)
                tgt = lvl + a["direction"] * rr * risk
                gated.append({"day": str(day), "ts": r.ts, "symbol": r.symbol, "setup": a["setup"], "path": "armed",
                              "gate": classify(r.detail), "d": a["direction"], "spot": lvl, "stop": inv, "target": tgt,
                              "time_stop": int((cfg.get(f"intraday.setups.{a['setup']}", {}) or {}).get("time_stop_min", 45))})
        trades = j.df("SELECT symbol, strategy, opened_at, pnl FROM trades")
        for g in gated:
            b = bars[g["symbol"]]
            res, at = first_touch(b, pd.Timestamp(g["ts"]), g["d"], g["stop"], g["target"], g["time_stop"])
            g["outcome"] = res
            end_px = float(b[b.index <= at]["close"].iloc[-1]) if at is not None else g["spot"]
            risk = abs(g["spot"] - g["stop"]) or 1e-9
            g["r_underlying"] = {"target": abs(g["target"] - g["spot"]) / risk, "stop": -1.0}.get(res, g["d"] * (end_px - g["spot"]) / risk)
        report[str(day)] = {"entry_path": {f"{u}|{c}": n for (u, c), n in sorted(stats.items())},
                            "setups": {f"{u}|{s}|{k}": n for (u, s, k), n in sorted(setups.items())},
                            "decisions": int(len(dec)), "trades": int(len(trades)),
                            "trade_list": trades.astype(str).to_dict("records"), "gated": gated}
        print(day, "decisions", len(dec), "trades", len(trades), "gated", len(gated), flush=True)
    (out / "funnel.json").write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    main()
