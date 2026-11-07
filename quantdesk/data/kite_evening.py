"""MCX and currency futures candles from Kite's historical API, collected after their sessions (`quantdesk data kite-evening`, kite-evening.yml).

Why: the Kite tick recorder stops at 15:32 IST. MCX trades to 23:30 (23:55 in some months) and currency to 17:00, so their evenings were never recorded, and Kotak cannot fill them
(its candle API answered every MCX and currency request with HTTP 422). Kite can: one pass shortly after midnight IST reads the whole day of 1-minute candles (with open interest) of the
nearest two futures of every MCX commodity and every currency pair, and, on request, their daily history (Kite's continuous series, up to ~2,000 days). A late or missed run heals itself
because each run re-reads the last `days` days (Kite keeps ~60 days of minutes), and a first run with `--days 55` is the backfill.

Licence: Kite's data is licensed to the subscriber and this repository is public, so the candles are written to `<run>/data/` only to be AES-encrypted by the workflow and kept as an
expiring artifact (docs/AUTONOMY.md). What is published is `<run>/manifest.json`: counts, statuses and contract expiries, no price. `publishable()` checks that before it is pushed.

Market data only: no order, position, holding, margin or profile method is called anywhere in this code (a test checks). Fail-soft in every part: an instrument Kite does not serve is
recorded in the manifest and never raises; a run whose first calls are all refused (no historical-data add-on, a dead token) stops early instead of hammering Kite.

Output, per run: <out>/<day>/data/{mcx,cds}_minutes.parquet and {mcx,cds}_daily.parquet (ts or date, segment, underlying, symbol, token, expiry, rank, open, high, low, close, volume, oi)
and <out>/<day>/manifest.json (the shape evening_minutes.py's manifest has, so the data-health check reads either)."""
from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd

from ..intraday.feeds import IST
from .daily_history import OHLC, clean
from .evening_minutes import session_day  # noqa: F401  (the same session rule: before 06:00 IST a run still belongs to the previous day)

EXCHANGES = {"mcx": "MCX", "cds": "CDS"}                    # Kite's exchange names for the two segments
EVIDENCE = "real_trade_minutes"
SOURCE = "kite"
MINUTE_MAX_DAYS = 55                                          # Kite serves about 60 days of 1-minute candles
DAILY_MAX_DAYS = 1900                                         # and 2,000 days of daily ones
PER_NAME = 2                                                  # the nearest two unexpired futures of each underlying (rank 1 = near month)
GIVE_UP_AFTER = 6                                             # this many refusals in a row, before anything is served: stop (no add-on, a dead token), do not hammer
COLS = ["ts", "segment", "underlying", "symbol", "token", "expiry", "rank", "open", "high", "low", "close", "volume", "oi"]
NOTE = ("traded 1-minute bars (and daily bars) of the nearest two futures of every MCX commodity and currency pair, from Kite's historical API, with open interest; "
        "the candles are licensed, encrypted, never published; data collection only, nothing here trades")
PRICE_KEYS = {"open", "high", "low", "close", "ts", "volume", "oi", "ohlc", "price", "ltp", "bid", "ask"}


class Pacer:
    """At most `rate` calls a second and `budget_s` seconds in all."""

    def __init__(self, rate: float = 3.0, budget_s: float = 1200.0, sleep=time.sleep, clock=time.monotonic):
        self.gap, self.budget, self._sleep, self._clock = 1.0 / max(rate, 0.1), budget_s, sleep, clock
        self._t0, self._last = clock(), None

    @property
    def out_of_time(self) -> bool:
        return self._clock() - self._t0 > self.budget

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None and now - self._last < self.gap:
            self._sleep(self.gap - (now - self._last))
        self._last = self._clock()


def pick_futures(instruments: pd.DataFrame, today: dt.date, per_name: int = PER_NAME) -> list[dict]:
    """The nearest `per_name` unexpired futures of every underlying: [{name, token, symbol, expiry, rank}], sorted by name then expiry."""
    need = {"instrument_type", "name", "expiry", "instrument_token"}
    if instruments is None or instruments.empty or not need <= set(instruments.columns):
        return []
    df = instruments.copy()
    df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    f = df[(df["instrument_type"] == "FUT") & df["expiry"].notna() & df["name"].notna() & (df["name"] != "")]
    f = f[f["expiry"] >= today].sort_values(["name", "expiry"])
    out = []
    for name, g in f.groupby("name", sort=True):
        for rank, r in enumerate(g.head(per_name).itertuples(), 1):
            try:
                tok = int(r.instrument_token)
            except (TypeError, ValueError):
                continue
            out.append({"name": str(name), "token": tok, "symbol": str(getattr(r, "tradingsymbol", "") or ""), "expiry": r.expiry, "rank": rank})
    return out


def _frame(candles: list[dict], meta: dict, daily: bool) -> tuple[pd.DataFrame, dict]:
    """Kite candles -> a cleaned frame (impossible bars dropped and counted, never repaired). Minute bars are IST instants; daily bars are the session's date."""
    if not candles:
        return pd.DataFrame(), {}
    df = pd.DataFrame(candles)
    if "date" not in df or not set(OHLC) <= set(df.columns):
        return pd.DataFrame(), {"malformed": len(df)}
    ts = pd.DatetimeIndex(pd.to_datetime(df["date"]))
    if daily:
        ts = (ts.tz_localize(None) if ts.tz is not None else ts).normalize()
    else:
        ts = ts.tz_convert(IST) if ts.tz is not None else ts.tz_localize(IST)
    df = df.drop(columns=["date"])
    df["volume"] = df["volume"] if "volume" in df else 0.0
    df["oi"] = df["oi"] if "oi" in df else float("nan")
    df.index = ts
    ok, rejected = clean(df[OHLC + ["volume"]].copy())
    df = df.loc[df.index.isin(ok.index)]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    out = df.rename_axis("ts").reset_index()
    for k, v in meta.items():
        out[k] = v
    return out[[c for c in COLS if c in out.columns]], rejected


def run(kite, out_root: Path, today: dt.date | None = None, days: int = 3, daily_days: int = 0, segments: tuple[str, ...] = ("mcx", "cds"), rate: float = 3.0,
        budget_s: float = 1200.0, say=print, sleep=None, clock=None, per_name: int = PER_NAME) -> dict:
    """Collect the last `days` days of minutes (and `daily_days` of daily bars, 0 = none) for the nearest futures of each segment. Never raises on a Kite problem."""
    today = today or session_day(pd.Timestamp.now(tz=IST))
    days, daily_days = max(1, min(int(days), MINUTE_MAX_DAYS)), max(0, min(int(daily_days), DAILY_MAX_DAYS))
    run_dir = Path(out_root) / str(today)
    data_dir = run_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    start = today - dt.timedelta(days=days)
    man = {"evidence": EVIDENCE, "source": SOURCE, "as_of": str(today), "window": [str(start), str(today)], "daily_days": daily_days, "note": NOTE, "segments": {}, "stopped": None,
           "totals": {}, "rate_per_s": rate, "budget_s": budget_s}
    pacer = Pacer(rate, budget_s, sleep or time.sleep, clock or time.monotonic)
    refused = {"n": 0, "served": 0}

    def call(token: int, a: dt.datetime, b: dt.datetime, interval: str, **kw):
        pacer.wait()
        try:
            rows = kite.historical_data(token, a, b, interval, oi=True, **kw) or []
        except Exception as exc:                                            # noqa: BLE001 - recorded per instrument; the run goes on
            refused["n"] += 1
            return None, f"{type(exc).__name__}: {exc!s:.110}"
        refused["n"] = 0
        return rows, None

    for seg in segments:
        exchange = EXCHANGES[seg]
        rep = man["segments"][seg] = {"exchange": exchange, "names": {}}
        try:
            futs = pick_futures(pd.DataFrame(kite.instruments(exchange)), today, per_name)
        except Exception as exc:                                            # noqa: BLE001 - one segment's list failing never stops the other
            rep["error"] = f"instruments: {type(exc).__name__}: {exc!s:.110}"
            say(f"  {seg}: {rep['error']}")
            continue
        if not futs:
            rep["error"] = "no unexpired future in Kite's instrument list"
            say(f"  {seg}: {rep['error']}")
            continue
        rep["underlyings_seen"] = sorted({f["name"] for f in futs})
        minutes, daily = [], []
        for f in futs:
            key = f"{f['name']}#{f['rank']}"
            r = rep["names"][key] = {"underlying": f["name"], "rank": f["rank"], "expiry": str(f["expiry"])}
            if man["stopped"] or pacer.out_of_time or (refused["n"] >= GIVE_UP_AFTER and not refused["served"]):
                man["stopped"] = man["stopped"] or ("time budget" if pacer.out_of_time else f"{GIVE_UP_AFTER} requests in a row refused before any was served")
                r.update(status="not_attempted", error=man["stopped"])
                continue
            meta = {"segment": seg, "underlying": f["name"], "symbol": f["symbol"], "token": f["token"], "expiry": str(f["expiry"]), "rank": f["rank"]}
            rows, err = call(f["token"], dt.datetime.combine(start, dt.time(0, 0)), dt.datetime.combine(today, dt.time(23, 59, 59)), "minute")
            if rows is None:
                r.update(status="failed", error=err)
                continue
            df, rejected = _frame(rows, meta, daily=False)
            if df.empty:
                r.update(status="empty", error="no candles", rejected=int(sum(rejected.values())) if rejected else 0)
                continue
            refused["served"] += 1
            r.update(status="served", bars=int(len(df)), sessions=int(pd.DatetimeIndex(df["ts"]).normalize().nunique()), rejected=int(sum(rejected.values())) if rejected else 0)
            minutes.append(df)
            if daily_days and f["rank"] == 1:                              # the continuous series is one chain: ask once per underlying
                rows, err = call(f["token"], dt.datetime.combine(today - dt.timedelta(days=daily_days), dt.time(0, 0)), dt.datetime.combine(today, dt.time(23, 59, 59)),
                                 "day", continuous=True)
                if rows is None:
                    r["daily"] = {"status": "failed", "error": err}
                else:
                    dd, _ = _frame(rows, meta, daily=True)
                    r["daily"] = {"status": "served" if len(dd) else "empty", "bars": int(len(dd))}
                    if len(dd):
                        daily.append(dd)
        if minutes:
            pd.concat(minutes, ignore_index=True).to_parquet(data_dir / f"{seg}_minutes.parquet", index=False, compression="zstd")
        if daily:
            pd.concat(daily, ignore_index=True).to_parquet(data_dir / f"{seg}_daily.parquet", index=False, compression="zstd")
        names = rep["names"].values()
        man["totals"][seg] = {"asked": len(rep["names"]), "served": sum(1 for v in names if v.get("status") == "served"), "failed": sum(1 for v in names if v.get("status") == "failed"),
                              "empty": sum(1 for v in names if v.get("status") == "empty"), "not_attempted": sum(1 for v in names if v.get("status") == "not_attempted")}
        say(f"  {seg}: {man['totals'][seg]['served']} of {man['totals'][seg]['asked']} futures served")
    man["path"] = str(run_dir)
    (run_dir / "manifest.json").write_text(json.dumps(man, indent=2, default=str), encoding="utf-8")
    return man


# What a published manifest may contain: every key and its type. A key outside this list, a float where a count belongs, or a long string is refused, so a price cannot ride in a field
# nobody thought to name.
_TOP = {"evidence": str, "source": str, "as_of": str, "window": list, "daily_days": int, "note": str, "segments": dict, "stopped": (str, type(None)), "totals": dict,
        "rate_per_s": (int, float), "budget_s": (int, float), "path": str}
_SEG = {"exchange": str, "names": dict, "underlyings_seen": list, "error": str}
_NAME = {"underlying": str, "rank": int, "expiry": str, "status": str, "bars": int, "sessions": int, "rejected": int, "error": str, "daily": dict}
_DAILY = {"status": str, "bars": int, "error": str}
_TOTAL = {"asked": int, "served": int, "failed": int, "empty": int, "not_attempted": int}
MAX_STR = 400
MAX_ITEMS = 400


def publishable(manifest: dict) -> list[str]:
    """Reasons a manifest must NOT be published (empty = it may be): Kite's data is licensed, so a published file carries counts, statuses and names, never a price."""
    bad: list[str] = []

    def shape(o, allowed: dict, path: str) -> None:
        if not isinstance(o, dict):
            bad.append(f"{path}: not an object")
            return
        for k, v in o.items():
            want = allowed.get(k)
            if str(k).lower() in PRICE_KEYS or want is None:
                bad.append(f"{path}/{k}: not an allowed field")
            elif not isinstance(v, want) or (want is int and isinstance(v, bool)):
                bad.append(f"{path}/{k}: wrong type {type(v).__name__}")
            elif isinstance(v, str) and len(v) > MAX_STR:
                bad.append(f"{path}/{k}: a string of {len(v)} characters")
            elif isinstance(v, (list, dict)) and len(v) > MAX_ITEMS:
                bad.append(f"{path}/{k}: {len(v)} items")

    shape(manifest, _TOP, "")
    for sym, seg in (manifest.get("segments") or {}).items():
        shape(seg, _SEG, f"/segments/{sym}")
        for u in (seg.get("names") or {}) if isinstance(seg, dict) else {}:
            row = seg["names"][u]
            shape(row, _NAME, f"/segments/{sym}/names/{u}")
            if isinstance(row, dict) and "daily" in row:
                shape(row["daily"], _DAILY, f"/segments/{sym}/names/{u}/daily")
        if isinstance(seg, dict) and any(not isinstance(x, str) or len(x) > 40 for x in seg.get("underlyings_seen") or []):
            bad.append(f"/segments/{sym}/underlyings_seen: a long or non-string name")
    for sym, t in (manifest.get("totals") or {}).items():
        shape(t, _TOTAL, f"/totals/{sym}")
    if any(not isinstance(x, str) or len(x) > 12 for x in manifest.get("window") or []):
        bad.append("/window: not dates")
    return bad


def data_files(run_dir: Path) -> list[Path]:
    return sorted((Path(run_dir) / "data").glob("*.parquet"))
