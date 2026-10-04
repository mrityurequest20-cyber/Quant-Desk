"""Historical 1-minute option, index and futures candles from Kotak Neo: the intraday option history no free source has.

Kotak's candle endpoint serves about 30 days of 1-minute bars per contract, with volume, using the same consumer key
the desk already uses (no login, no orders). This module pulls them for:
- every strike within `strikes` of the money, both rights, for the nearest `expiries` expiries of each index;
- the index itself;
- the active futures contract.

Run it once to collect the last month. Then run it after every session (live.yml does): each contract's final days
before expiry are kept, which Kotak forgets 30 days later and which expired contracts can't be fetched for at all.

What this data is: **traded** minute bars (OHLC of trades, plus volume). It is not bid/ask quotes. A strike that
didn't trade in a minute has no bar, and an illiquid strike's close can be stale. Evidence class `real_trade_minutes`:
- right for intraday research, move and IV studies, and checking the cost model against the chain tape's real quotes;
- it does not qualify a strategy; only real point-in-time quotes do (autolearn/plans.py).

Output, one set per run (overlapping runs are de-duplicated on load by contract and minute):

  runtime/intraday/backfill/<as of>/options_<UNDERLYING>.parquet   ts, underlying, expiry, strike, right, token, OHLCV
  runtime/intraday/backfill/<as of>/index.parquet, futures.parquet
  runtime/intraday/backfill/<as of>/manifest.json                  contracts asked, served, empty, failed, coverage
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from ..intraday.feeds import IST
from ..intraday.kotak import INDEX, KotakFutures, chain_parts, _f

EVIDENCE = "real_trade_minutes"
COLS = ["ts", "underlying", "expiry", "strike", "right", "token", "open", "high", "low", "close", "volume"]
CHUNK_DAYS = 5


def contracts(client, underlying: str, n_expiries: int, strikes: int, today: dt.date) -> list[dict]:
    """Tokens for every strike within `strikes` of the money, CE and PE, for the nearest `n_expiries` expiries."""
    out = []
    count = max(10, int(round(strikes / 10)) * 10)
    for exp in [e for e in client.expiries(underlying) if e >= today][:n_expiries]:
        _, calls, puts = chain_parts(client.option_chain(underlying, exp, count))
        for right, items in (("CE", calls), ("PE", puts)):
            for item in items:
                ins = item.get("instrument") or item.get("inst") or {}
                k = _f(ins.get("strikePrice", ins.get("strkPrc")))
                tok = str(ins.get("neoSymbol") or "")
                if k > 0 and "|" in tok:
                    out.append({"underlying": underlying, "expiry": exp, "strike": k, "right": right, "token": tok})
    return out


def candles(client, token: str, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, str | None]:
    """The whole window in one call; if Kotak refuses or returns nothing, in CHUNK_DAYS pieces."""
    try:
        df = client.candles(token, "1min", start, end)
        if len(df):
            return df, None
    except Exception as exc:                                  # a long window may be refused: try it in pieces
        first_err = f"{exc!s:.120}"
    else:
        first_err = None
    parts, err = [], first_err
    d = start
    while d <= end:
        e = min(end, d + dt.timedelta(days=CHUNK_DAYS - 1))
        try:
            p = client.candles(token, "1min", d, e)
            if len(p):
                parts.append(p)
        except Exception as exc:
            err = f"{exc!s:.120}"
        d = e + dt.timedelta(days=1)
    if not parts:
        return pd.DataFrame(), err
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index(), None


def _frame(df: pd.DataFrame, meta: dict) -> pd.DataFrame:
    out = df.reset_index().rename(columns={df.index.name or "index": "ts"})
    if "ts" not in out:
        out = out.rename(columns={out.columns[0]: "ts"})
    for k, v in meta.items():
        out[k] = v
    return out[[c for c in COLS if c in out.columns]]


def _write(run: Path, man: dict, idx_parts: list, fut_parts: list) -> None:
    """Index, futures and manifest as they stand: rewritten after every underlying, so a later timeout loses nothing."""
    if idx_parts:
        pd.concat(idx_parts, ignore_index=True).to_parquet(run / "index.parquet", index=False, compression="zstd")
    if fut_parts:
        pd.concat(fut_parts, ignore_index=True).to_parquet(run / "futures.parquet", index=False, compression="zstd")
    (run / "manifest.json").write_text(json.dumps(man, indent=1, default=str))


def backfill(client, out_root: Path, underlyings=("NIFTY", "BANKNIFTY"), days: int = 30, n_expiries: int = 4,
             strikes: int = 20, today: dt.date | None = None, say=print, on_underlying=None) -> dict:
    """`on_underlying(u, run)` is called once an underlying's files and the manifest so far are on disk (the CLI
    uploads them to the release there, so a timeout on a later underlying never loses a finished one)."""
    today = today or pd.Timestamp.now(tz=IST).date()
    start = today - dt.timedelta(days=days)
    run = Path(out_root) / str(today)
    run.mkdir(parents=True, exist_ok=True)
    man = {"evidence": EVIDENCE, "as_of": str(today), "window": [str(start), str(today)], "underlyings": {},
           "note": "traded 1-minute bars (OHLC of trades, volume), not bid/ask quotes; research and cost calibration, "
                   "never strategy qualification"}
    idx_parts, fut_parts = [], []
    fut = KotakFutures(client)
    for u in underlyings:
        rep = {"asked": 0, "served": 0, "empty": 0, "failed": 0, "bars": 0, "errors": {}, "asked_by_expiry": {},
               "failed_by_expiry": {}, "failed_contracts": []}
        try:
            cs = contracts(client, u, n_expiries, strikes, today)
        except Exception as exc:
            rep["errors"]["contracts"] = f"{exc!s:.160}"
            man["underlyings"][u] = rep
            say(f"  {u}: no contracts ({exc!s:.100})")
            continue
        rep["asked"] = len(cs)
        rep["expiries"] = sorted({str(c["expiry"]) for c in cs})
        for c in cs:
            rep["asked_by_expiry"][str(c["expiry"])] = rep["asked_by_expiry"].get(str(c["expiry"]), 0) + 1
        parts = []
        for c in cs:
            df, err = candles(client, c["token"], start, today)
            if err and df.empty:
                rep["failed"] += 1
                rep["errors"][err] = rep["errors"].get(err, 0) + 1
                e = str(c["expiry"])                         # where they fail is the diagnosis: one error string hides it
                rep["failed_by_expiry"][e] = rep["failed_by_expiry"].get(e, 0) + 1
                rep["failed_contracts"].append({"expiry": e, "strike": c["strike"], "right": c["right"], "error": err})
            elif df.empty:
                rep["empty"] += 1
            else:
                rep["served"] += 1
                parts.append(_frame(df, c))
        if parts:
            opt = pd.concat(parts, ignore_index=True)
            opt.to_parquet(run / f"options_{u}.parquet", index=False, compression="zstd")
            rep["bars"] = int(len(opt))
            rep["sessions"] = int(opt["ts"].dt.date.nunique())
            rep["first"], rep["last"] = str(opt["ts"].min()), str(opt["ts"].max())
            rep["bars_by_expiry"] = {str(k): int(v) for k, v in opt.groupby("expiry").size().items()}
        for kind, sym, holder in (("index", f"nse_cm|{INDEX.get(u, u)}", idx_parts), ("futures", None, fut_parts)):
            try:
                tok = sym or fut.active(u, today)["token"]
                df, err = candles(client, tok, start, today)
                if len(df):
                    holder.append(_frame(df, {"underlying": u, "token": tok}))
                    rep[f"{kind}_bars"] = int(len(df))
                elif err:
                    rep["errors"][f"{kind}: {err}"] = 1
            except Exception as exc:
                rep["errors"][f"{kind}: {exc!s:.100}"] = 1
        man["underlyings"][u] = rep
        say(f"  {u}: {rep['served']}/{rep['asked']} contracts with bars ({rep['empty']} empty, {rep['failed']} failed), "
            f"{rep['bars']:,} option bars over {rep.get('sessions', 0)} sessions; index {rep.get('index_bars', 0):,}, "
            f"futures {rep.get('futures_bars', 0):,} bars")
        man["calls"] = dict(getattr(client, "calls", {}) or {})
        _write(run, man, idx_parts, fut_parts)
        if on_underlying:
            on_underlying(u, run)
    man["calls"] = dict(getattr(client, "calls", {}) or {})
    _write(run, man, idx_parts, fut_parts)
    man["path"] = str(run)
    return man


def load(root: Path, kind: str = "options", underlying: str | None = None) -> pd.DataFrame:
    """Every run's files of one kind, de-duplicated by contract and minute (later runs win)."""
    pat = f"options_{underlying}.parquet" if (kind == "options" and underlying) else (
        "options_*.parquet" if kind == "options" else f"{kind}.parquet")
    parts = [pd.read_parquet(p) for p in sorted(Path(root).glob(f"*/{pat}"))]
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts, ignore_index=True)
    return df.drop_duplicates(["token", "ts"], keep="last").sort_values(["token", "ts"]).reset_index(drop=True)


def release_names(run: Path) -> list[str]:
    """Release asset names for a run: <as of>_<file> (Parquet and the manifest)."""
    return [p.name for p in sorted(Path(run).iterdir()) if p.suffix in (".parquet", ".json")]
