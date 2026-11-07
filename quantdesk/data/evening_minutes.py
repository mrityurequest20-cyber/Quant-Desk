"""MCX and currency 1-minute candles, collected after their sessions (`quantdesk data evening-minutes`, evening-minutes.yml).

Why: the Kite recorder stops at 15:32 IST. MCX trades to 23:30 (23:55 in some months) and currency to 17:00, so their evenings were never recorded. Kotak serves a traded 1-minute
candle history for about 30 days, so one pass shortly after midnight IST collects the whole day of every MCX commodity's and every currency pair's near-month future; nothing has to
be subscribed through the evening, no Kite login is involved, and a late or missed run heals itself because each run re-reads the last `days` days.

Market data only, through the Kotak consumer key that the other recorders already use (no order method is called anywhere in this code: a test checks). Fail-soft in every part: a name
Kotak does not serve, a segment whose scrip master has no futures, or a run that hits its time budget is recorded in the manifest and never raises. The first real run is the discovery of
what Kotak serves for these two segments, so the manifest records every instrument type and name it saw, not only what it kept.

Output, per run: <out>/<day>/mcx_minutes.parquet, cds_minutes.parquet (ts, segment, underlying, symbol, token, expiry, open, high, low, close, volume) and manifest.json."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from ..intraday.feeds import IST
from ..intraday.kotak import KotakFutures, scrip_master
from .kotak_backfill import Paced, candles

EXCHANGES = {"mcx": "mcx_fo", "cds": "cde_fo"}              # Kotak's segment names for MCX and currency derivatives
COLS = ["ts", "segment", "underlying", "symbol", "token", "expiry", "open", "high", "low", "close", "volume"]
EVIDENCE = "real_trade_minutes"
NOTE = ("traded 1-minute bars (OHLC of trades, volume), not bid/ask quotes; the near-month future of every MCX commodity and every currency pair, "
        "collected after the close; data collection only, nothing here trades")


def future_underlyings(master: pd.DataFrame) -> tuple[list[str], list[str]]:
    """(names that have a future, every instrument type seen) from one scrip-master frame (pSymbolName / pInstType, as for the NSE F&O master)."""
    cols = {str(c).lower(): c for c in master.columns}
    sym, typ = cols.get("psymbolname"), cols.get("pinsttype")
    if not (sym and typ):
        return [], []
    kinds = sorted({str(t).strip().upper() for t in master[typ] if str(t).strip()})
    f = master[master[typ].astype(str).str.upper().str.startswith("FUT")]
    return sorted({str(s).strip().upper() for s in f[sym] if str(s).strip()}), kinds


def _frame(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    out = df.reset_index().rename(columns={df.index.name or "index": "ts"})
    if "ts" not in out:
        out = out.rename(columns={out.columns[0]: "ts"})
    for k, v in meta.items():
        out[k] = v
    return out[[c for c in COLS if c in out.columns]]


def run(client, out_root: Path, today: dt.date | None = None, days: int = 3, segments: tuple[str, ...] = ("mcx", "cds"), rate: float = 5.0,
        budget_s: float = 1500.0, say=print, sleep=None, clock=None, max_names: int = 120) -> dict:
    """Collect the last `days` days of minutes for every near-month future of the segments. Never raises on a Kotak problem."""
    import time
    today = today or pd.Timestamp.now(tz=IST).date()
    start = today - dt.timedelta(days=days)
    run_dir = Path(out_root) / str(today)
    run_dir.mkdir(parents=True, exist_ok=True)
    man = {"evidence": EVIDENCE, "as_of": str(today), "window": [str(start), str(today)], "note": NOTE, "segments": {}, "stopped": None,
           "totals": {}, "rate_per_s": rate, "budget_s": budget_s}
    paced = Paced(client, rate=rate, budget_s=budget_s, sleep=sleep or time.sleep, clock=clock or time.monotonic)
    for seg in segments:
        exchange = EXCHANGES[seg]
        rep = man["segments"][seg] = {"exchange": exchange, "names": {}}
        try:
            names, kinds = future_underlyings(scrip_master(paced, exchange))
        except Exception as exc:                                       # the segment's master could not be read: recorded, the other segment still runs
            rep["error"] = f"scrip master: {exc!s:.160}"
            say(f"  {seg}: {rep['error']}")
            continue
        rep["instrument_types_seen"], rep["underlyings_seen"] = kinds, names
        if not names:
            rep["error"] = "no future found in the scrip master (instrument types seen: " + ", ".join(kinds[:12]) + ")"
            say(f"  {seg}: {rep['error']}")
            continue
        fut, parts = KotakFutures(paced, exchange=exchange), []
        for name in names[:max_names]:
            r = rep["names"][name] = {}
            if paced.out_of_time:
                r.update(status="not_attempted", error="time budget")
                continue
            try:
                a = fut.active(name, today)
            except Exception as exc:
                r.update(status="failed", error=f"contracts: {exc!s:.120}")
                continue
            df, err = candles(paced, a["token"], start, today)
            if df.empty:
                r.update(status="failed" if err else "empty", error=err or "no candles")
                continue
            r.update(status="served", bars=int(len(df)), sessions=int(df.index.normalize().nunique()), expiry=str(a["expiry"]), token=a["token"])
            parts.append(_frame(df, {"segment": seg, "underlying": name, "symbol": a.get("symbol", ""), "token": a["token"], "expiry": str(a["expiry"])}))
        if parts:
            pd.concat(parts, ignore_index=True).to_parquet(run_dir / f"{seg}_minutes.parquet", index=False, compression="zstd")
        asked = len(rep["names"])
        served = sum(1 for v in rep["names"].values() if v.get("status") == "served")
        man["totals"][seg] = {"asked": asked, "served": served, "failed": sum(1 for v in rep["names"].values() if v.get("status") == "failed"),
                              "empty": sum(1 for v in rep["names"].values() if v.get("status") == "empty"),
                              "not_attempted": sum(1 for v in rep["names"].values() if v.get("status") == "not_attempted")}
        say(f"  {seg}: {served} of {asked} futures served")
    if paced.out_of_time:
        man["stopped"] = "time budget"
    man["path"] = str(run_dir)
    import json
    (run_dir / "manifest.json").write_text(json.dumps(man, indent=2, default=str), encoding="utf-8")
    return man


def release_names(run_dir: Path) -> list[str]:
    """The files of one run, named for the release: <day>_<file>."""
    return sorted(p.name for p in Path(run_dir).glob("*") if p.suffix in (".parquet", ".json"))
