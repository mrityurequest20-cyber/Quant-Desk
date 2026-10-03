"""The chain tape: real option-chain snapshots every minute, for several expiries, beside the engine.

Why: plan research qualifies a candidate only on real point-in-time quotes (autolearn/plans.py), and by 3 Oct 2026
the desk had recorded two sessions of them, for the one expiry the engine was trading. The tape records what the
research needs and the engine does not:
- every minute of the session;
- the nearest few expiries of each index (0 / 1 / 2 / 3-5 / 6+ trading days to expiry);
- whichever expiry the engine happens to be using.

It is its own process (deploy/run-session.sh starts it next to the engine). A slow or failing Kotak call costs the tape
a snapshot, never the engine a decision. It writes into the recorder's folder, under the recorder's file names, so the
session archive (data/archive.py) keeps it like any other recorded chain:

  runtime/intraday/data/<day>/chains/<UNDERLYING>_<expiry>_<HHMM>.csv
  runtime/intraday/data/<day>/tape.csv      one row per attempt: completeness, quotes, latency, errors

Kotak only: NSE's public chain throttles and blocks cloud IPs, and the model chain is not data. Without a Kotak key the
tape says so and exits."""
from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import pandas as pd

from .chains import save_chain
from .feeds import IST, session_bounds

DEFAULT_EXPIRIES = {"NIFTY": 3, "BANKNIFTY": 2}
LOG_COLUMNS = ["ts", "underlying", "expiry", "ok", "strikes", "quoted", "spot", "secs", "error"]


def targets(expiries: list[dt.date], n: int, today: dt.date) -> list[dt.date]:
    """The nearest `n` expiries on or after today."""
    return sorted(e for e in expiries if e >= today)[:n]


def save_atomic(chain: pd.DataFrame, path: Path) -> None:
    """save_chain, through a temporary file and a rename, so a reader never sees half a snapshot (the engine's
    recorder may write the same minute's file for its own expiry)."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    save_chain(chain, tmp)
    os.replace(tmp, path)


class ChainTape:
    def __init__(self, source, data_dir: Path, expiries: dict[str, int] | None = None, every_min: float = 1.0,
                 max_backoff_min: float = 5.0, say=print, clock=None, sleep=time.sleep):
        self.src = source
        self.data = Path(data_dir)
        self.want = dict(expiries or DEFAULT_EXPIRIES)
        self.every = float(every_min)
        self.max_backoff = float(max_backoff_min)
        self.say = say
        self.clock = clock or (lambda: pd.Timestamp.now(tz=IST))
        self.sleep = sleep
        self.fails: dict[tuple, int] = {}
        self.next_try: dict[tuple, pd.Timestamp] = {}
        self.log: list[dict] = []

    def _log(self, row: dict, day: dt.date) -> None:
        self.log.append(row)
        path = self.data / str(day) / "tape.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([row], columns=LOG_COLUMNS).to_csv(path, mode="a", header=not path.exists(), index=False)

    def tick(self, now: pd.Timestamp) -> int:
        """One pass over every target; returns the snapshots written."""
        wrote = 0
        for u, n in self.want.items():
            try:
                exps = targets(self.src.expiries(u), n, now.date())
            except Exception as exc:
                self._log({"ts": now, "underlying": u, "expiry": None, "ok": False, "error": f"expiries: {exc!s:.200}"},
                          now.date())
                continue
            for e in exps:
                key = (u, e)
                if key in self.next_try and now < self.next_try[key]:
                    continue
                t0 = time.monotonic()
                try:
                    ch = self.src.chain(u, e, ts=now)
                    ts = pd.Timestamp(ch.attrs["ts"])
                    path = self.data / str(ts.date()) / "chains" / f"{u}_{e}_{ts:%H%M}.csv"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    save_atomic(ch, path)
                    self.fails.pop(key, None)
                    self.next_try.pop(key, None)
                    wrote += 1
                    self._log({"ts": ts, "underlying": u, "expiry": e, "ok": True, "strikes": len(ch),
                               "quoted": ch.attrs.get("quoted"), "spot": ch.attrs.get("spot"),
                               "secs": round(time.monotonic() - t0, 2), "error": None}, now.date())
                except Exception as exc:
                    k = self.fails[key] = self.fails.get(key, 0) + 1
                    wait = min(self.max_backoff, self.every * 2 ** (k - 1)) if k > 1 else 0.0
                    if wait:
                        self.next_try[key] = now + pd.Timedelta(minutes=wait)
                    self._log({"ts": now, "underlying": u, "expiry": e, "ok": False, "secs": round(time.monotonic() - t0, 2),
                               "error": f"{exc!s:.200}"}, now.date())
                    if k in (1, 5) or k % 30 == 0:
                        self.say(f"tape {now:%H:%M} {u} {e}: {exc!s:.120} ({k} in a row)")
        return wrote

    def run(self, until: dt.time | None = None) -> dict:
        """Tick once a minute (a few seconds after the minute) from the open to `until` or the close."""
        now = self.clock()
        open_, close = session_bounds(now.date())
        stop = min(close, pd.Timestamp.combine(now.date(), until).tz_localize(IST)) if until else close
        while (now := self.clock()) < stop:
            if now < open_:
                self.sleep(min(60.0, (open_ - now).total_seconds()))
                continue
            self.tick(now)
            nxt = now.floor("min") + pd.Timedelta(minutes=self.every, seconds=5)
            self.sleep(max(1.0, (nxt - self.clock()).total_seconds()))
        rep = completeness(self.data / str(now.date()), open_, min(stop, close))
        self.say(render(rep))
        return rep


def completeness(day_dir: Path, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> dict:
    """Per underlying and expiry: minutes with a snapshot, of the minutes in [start, end); from the files themselves,
    so the engine's recordings count too."""
    files = sorted((Path(day_dir) / "chains").glob("*.csv"))
    seen: dict[tuple[str, str], set] = {}
    for p in files:
        u, e, hhmm = p.stem.rsplit("_", 2)
        seen.setdefault((u, e), set()).add(hhmm)
    span = None
    if start is not None and end is not None:
        span = max(0, int((end - start).total_seconds() // 60))
    out = {"day": Path(day_dir).name, "minutes_in_span": span, "series": {}}
    for (u, e), mins in sorted(seen.items()):
        out["series"][f"{u} {e}"] = {"minutes": len(mins), "coverage": (len(mins) / span) if span else None}
    log = Path(day_dir) / "tape.csv"
    if log.exists():
        lg = pd.read_csv(log)
        ok = lg["ok"].astype(str).str.lower() == "true"
        out["attempts"], out["failures"] = int(len(lg)), int((~ok).sum())
        out["median_secs"] = float(lg.loc[ok, "secs"].median()) if ok.any() else None
        if (~ok).any():
            out["top_errors"] = lg.loc[~ok, "error"].astype(str).str[:80].value_counts().head(3).to_dict()
    return out


def render(rep: dict) -> str:
    L = [f"chain tape {rep['day']}: " + (f"{rep['minutes_in_span']} session minutes" if rep.get("minutes_in_span") else "")]
    for k, v in rep["series"].items():
        cov = f" ({v['coverage']:.0%})" if v.get("coverage") is not None else ""
        L.append(f"  {k}: {v['minutes']} minutes{cov}")
    if "attempts" in rep:
        L.append(f"  {rep['attempts']} attempts, {rep['failures']} failed, median {rep.get('median_secs')} s per chain")
        for err, n in (rep.get("top_errors") or {}).items():
            L.append(f"    {n}× {err}")
    return "\n".join(L)
