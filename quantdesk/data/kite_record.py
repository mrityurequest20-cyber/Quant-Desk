"""Kite Connect market-data trial recorder (docs/ml/KITE_TRIAL.md): ticks from the websocket, written to Parquet, and Kite's own historical candles as the reference.

A separate process. It reads market data only: **it never calls an order method** (a test greps this file for them), imports nothing from the engine, the journal or the risk
code, and a failure in it reaches nobody else. The credential comes from the environment (`KITE_DATA_KEY`, `KITE_DATA_TOKEN`: not the broker adapter's names); nothing is printed or logged with it. The data
is licensed to the subscriber: it is written to a folder the caller chooses and never into the repository (`refuse_tracked_tree`).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from pathlib import Path

import pandas as pd

IST = "Asia/Kolkata"
INDEX_NAMES = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "INDIAVIX": "NSE:INDIA VIX"}
FUTURE_UNDERLYINGS = ("NIFTY", "BANKNIFTY")
DEPTH_LEVELS = 5
DEPTH_COLUMNS = [f"{side}_{field}{i}" for side in ("bid", "ask") for i in range(1, DEPTH_LEVELS + 1) for field in ("p", "q", "n")]      # price, quantity, number of orders at each of the five levels
TICK_COLUMNS = ["symbol", "token", "ts_exchange", "ts_recv", "last_price", "last_qty", "volume", "oi", "bid", "ask", "bid_qty", "ask_qty", "buy_qty_total", "sell_qty_total"] + DEPTH_COLUMNS
FLUSH_SECONDS = 60.0


class KiteRecordError(RuntimeError):
    pass


def _ist(ts) -> pd.Timestamp | None:
    if ts is None:
        return None
    t = pd.Timestamp(ts)
    return t.tz_localize(IST) if t.tzinfo is None else t.tz_convert(IST)


def resolve_tokens(kite, today: dt.date) -> dict[str, int]:
    """symbol -> instrument token: the three indices, and the near-month future of NIFTY and BANKNIFTY (nearest expiry on or after today)."""
    ltp = kite.ltp(list(INDEX_NAMES.values()))
    out = {name: int(ltp[key]["instrument_token"]) for name, key in INDEX_NAMES.items() if key in ltp}
    missing = [n for n in INDEX_NAMES if n not in out]
    if missing:
        raise KiteRecordError(f"Kite does not know the index instruments {missing}")
    futs = pd.DataFrame(kite.instruments("NFO"))
    if futs.empty:
        raise KiteRecordError("Kite returned no NFO instruments")
    futs = futs[(futs["instrument_type"] == "FUT") & futs["name"].isin(FUTURE_UNDERLYINGS)].copy()
    futs["expiry"] = pd.to_datetime(futs["expiry"]).dt.date
    for name in FUTURE_UNDERLYINGS:
        c = futs[(futs["name"] == name) & (futs["expiry"] >= today)].sort_values("expiry")
        if c.empty:
            raise KiteRecordError(f"no live future for {name}")
        out[f"{name}-FUT"] = int(c.iloc[0]["instrument_token"])
    return out


def tick_row(tick: dict, symbol: str, recv: pd.Timestamp) -> dict:
    """One row from a Kite full-mode tick. Futures carry five levels of depth on each side (price, quantity, orders), indices carry none: their depth columns stay empty."""
    depth = tick.get("depth") or {}
    buys, sells = depth.get("buy") or [], depth.get("sell") or []
    buy, sell = (buys or [{}])[0], (sells or [{}])[0]
    row = {"symbol": symbol, "token": int(tick["instrument_token"]), "ts_exchange": _ist(tick.get("exchange_timestamp") or tick.get("last_trade_time")), "ts_recv": recv,
           "last_price": _f(tick.get("last_price")), "last_qty": _f(tick.get("last_traded_quantity")), "volume": _f(tick.get("volume_traded")), "oi": _f(tick.get("oi")),
           "bid": _f(buy.get("price")), "ask": _f(sell.get("price")), "bid_qty": _f(buy.get("quantity")), "ask_qty": _f(sell.get("quantity")),
           "buy_qty_total": _f(tick.get("total_buy_quantity")), "sell_qty_total": _f(tick.get("total_sell_quantity"))}
    for side, levels in (("bid", buys), ("ask", sells)):
        for i in range(1, DEPTH_LEVELS + 1):
            lv = levels[i - 1] if i <= len(levels) and isinstance(levels[i - 1], dict) else {}
            row[f"{side}_p{i}"], row[f"{side}_q{i}"], row[f"{side}_n{i}"] = _f(lv.get("price")), _f(lv.get("quantity")), _f(lv.get("orders"))
    return row


def _f(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


MAX_BUFFER = 1_000_000                                       # ticks held in memory between flushes (a minute is a few thousand)


class Recorder:
    """Collects ticks and writes them in parts. `now` is injectable so tests control time; the websocket object is whatever `ticker_factory` returns (KiteTicker's interface)."""

    def __init__(self, out_dir: Path, tokens: dict[str, int], ticker_factory, now=None, flush_seconds: float = FLUSH_SECONDS):
        self.out = Path(out_dir)
        self.tokens = dict(tokens)
        self.by_token = {v: k for k, v in self.tokens.items()}
        self.now = now or (lambda: pd.Timestamp.now(tz=IST))
        self.flush_seconds = flush_seconds
        self.rows: list[dict] = []
        self.overflow = 0                                            # dropped since the last flush
        self.dropped = 0                                             # dropped in the whole session: a later good flush does not make them come back
        self.lock = threading.Lock()
        self.part = 0
        self.tag = self.now().strftime("%H%M%S")                    # parts of two jobs on one day never collide
        self.ticks = 0
        self.events: list[dict] = []
        self.out.mkdir(parents=True, exist_ok=True)
        self.ws = ticker_factory()
        self.ws.on_ticks = self._on_ticks
        self.ws.on_connect = self._on_connect
        self.ws.on_close = lambda ws, code, reason: self._event("close", code=code, reason=str(reason)[:200])
        self.ws.on_error = lambda ws, code, reason: self._event("error", code=code, reason=str(reason)[:200])
        self.ws.on_reconnect = lambda ws, n: self._event("reconnect", attempt=n)
        self.ws.on_noreconnect = lambda ws: self._event("noreconnect")

    def _event(self, kind: str, **kw) -> None:
        with self.lock:
            self.events.append({"ts": str(self.now()), "kind": kind, **kw})

    def _on_connect(self, ws, response) -> None:
        toks = list(self.tokens.values())
        ws.subscribe(toks)
        ws.set_mode(ws.MODE_FULL, toks)
        self._event("connect", n=len(toks))

    def _on_ticks(self, ws, ticks) -> None:
        recv = self.now()
        with self.lock:
            for t in ticks:
                sym = self.by_token.get(t.get("instrument_token"))
                if sym is None:
                    continue
                if len(self.rows) >= MAX_BUFFER:                    # writes keep failing: stop growing without bound and say so once per flush
                    self.overflow += 1
                    continue
                self.rows.append(tick_row(t, sym, recv))
                self.ticks += 1

    def flush(self) -> Path | None:
        with self.lock:
            rows, self.rows = self.rows, []
            events, self.events = self.events, []
            lost, self.overflow = self.overflow, 0
        self.dropped += lost
        if lost:
            events.append({"kind": "overflow", "dropped_ticks": lost, "at": str(self.now())})
        if events:
            try:
                with open(self.out / "events.jsonl", "a") as fh:
                    fh.write("".join(json.dumps(e) + "\n" for e in events))
            except Exception:                                      # put back for the next flush, never lost
                with self.lock:
                    self.events = events + self.events
        if not rows:
            return None
        part = self.part + 1
        path = self.out / f"ticks_{self.tag}_{part:04d}.parquet"
        try:
            df = pd.DataFrame(rows, columns=TICK_COLUMNS)
            tmp = path.with_name(path.name + ".part")
            df.to_parquet(tmp, index=False)
            tmp.replace(path)
        except Exception:                                          # a failed write keeps the rows for the next flush instead of dropping them
            with self.lock:
                self.rows = rows + self.rows
            return None
        self.part = part
        return path

    def run(self, until: pd.Timestamp, sleep=time.sleep) -> dict:
        """Connect and record until `until` (IST), flushing every `flush_seconds`. Never raises on a dropped connection: the library reconnects and the gap is in the data."""
        self.ws.connect(threaded=True)
        last = self.now()
        while self.now() < until:
            sleep(min(1.0, self.flush_seconds))
            if (self.now() - last).total_seconds() >= self.flush_seconds:
                self.flush()
                last = self.now()
        try:
            self.ws.close()
        except Exception:
            pass
        self.flush()
        return {"parts": self.part, "ticks": self.ticks, "unwritten": len(self.rows), "dropped": self.dropped}


def fetch_reference(kite, tokens: dict[str, int], day: dt.date, out_dir: Path) -> Path:
    """Kite's own historical minute candles for the day, per instrument: the yardstick the tick-built bars are measured against."""
    rows = []
    start = dt.datetime.combine(day, dt.time(9, 0))
    end = dt.datetime.combine(day, dt.time(15, 40))
    for sym, tok in tokens.items():
        try:
            candles = kite.historical_data(tok, start, end, "minute", oi=sym.endswith("-FUT")) or []
        except Exception:                                          # one instrument's reference failing (rate limit, no add-on) must not cost the session its other measures
            continue
        for c in candles:
            rows.append({"symbol": sym, "ts": _ist(c["date"]), "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": c.get("volume"), "oi": c.get("oi")})
    df = pd.DataFrame(rows, columns=["symbol", "ts", "open", "high", "low", "close", "volume", "oi"])
    path = Path(out_dir) / "reference_minutes.parquet"
    df.to_parquet(path, index=False)
    return path


def run_session(out_dir: Path, until_hhmm: str, day: dt.date | None = None, kite=None, ticker_factory=None, now=None, sleep=time.sleep, with_reference: bool = False) -> dict:
    """Record from now until `until_hhmm` IST today. Credentials from the environment. Writes to `out_dir`; refuses a folder inside a git tree outside runtime/."""
    from ..ml.build import refuse_tracked_tree
    refuse_tracked_tree(Path(out_dir), "the Kite trial folder")
    key, token = os.environ.get("KITE_DATA_KEY"), os.environ.get("KITE_DATA_TOKEN")
    if kite is None or ticker_factory is None:
        if not key or not token:
            raise KiteRecordError("KITE_DATA_KEY and KITE_DATA_TOKEN must be set in the environment")
        from kiteconnect import KiteConnect, KiteTicker
        kite = kite or KiteConnect(api_key=key)
        if hasattr(kite, "set_access_token"):
            kite.set_access_token(token)
        ticker_factory = ticker_factory or (lambda: KiteTicker(key, token))
    clock = now or (lambda: pd.Timestamp.now(tz=IST))
    today = day or clock().date()
    tokens = resolve_tokens(kite, today)
    (Path(out_dir)).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / "tokens.json").write_text(json.dumps(tokens, indent=1))
    h, m = (int(x) for x in until_hhmm.split(":"))
    until = pd.Timestamp.combine(pd.Timestamp(today), dt.time(h, m)).tz_localize(IST)
    rec = Recorder(Path(out_dir), tokens, ticker_factory, now=clock)
    stats = rec.run(until, sleep=sleep)
    if with_reference:
        fetch_reference(kite, tokens, today, Path(out_dir))
    if stats["unwritten"] or stats["dropped"]:                     # ticks are gone (the last write failed, or the buffer overflowed while writes were failing): the run must not look clean
        raise KiteRecordError(f"{stats['unwritten']:,} ticks could not be written to {out_dir} and {stats['dropped']:,} were dropped from a full buffer; they are lost, the parts already written are kept")
    return {"day": str(today), "tokens": tokens, **stats}
