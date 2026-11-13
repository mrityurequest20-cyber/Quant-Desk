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

from .kite_universe import build_wide, deep_symbols
from .live_push import LivePusher, book_from_tick, quote_from_tick

IST = "Asia/Kolkata"
INDEX_NAMES = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "INDIAVIX": "NSE:INDIA VIX"}
FUTURE_UNDERLYINGS = ("NIFTY", "BANKNIFTY")
DEPTH_LEVELS = 5
DEPTH_COLUMNS = [f"{side}_{field}{i}" for side in ("bid", "ask") for i in range(1, DEPTH_LEVELS + 1) for field in ("p", "q", "n")]      # price, quantity, number of orders at each of the five levels
TICK_COLUMNS = ["symbol", "token", "ts_exchange", "ts_recv", "last_price", "last_qty", "volume", "oi", "bid", "ask", "bid_qty", "ask_qty", "buy_qty_total", "sell_qty_total"] + DEPTH_COLUMNS
FLUSH_SECONDS = 60.0
# The wide universe (kite_universe.py) is recorded APART from the pre-registered Kite trial's five instruments: its own slim rows, its own buffer, its own files
# in the `wide/` subfolder. Nothing the trial measures (tokens.json, ticks_*.parquet, the folder's parquet bytes) changes with it: quote-mode ticks carry no
# exchange timestamp, no depth and ~1,000 symbols would be judged against thresholds written for indices and futures (docs/ml/KITE_TRIAL.md).
WIDE_COLUMNS = ["symbol", "token", "ts_exchange", "ts_recv", "last_price", "last_qty", "volume", "oi", "buy_qty_total", "sell_qty_total", "change", "open", "high", "low", "close"]
MAX_WIDE_BUFFER = 300_000                                    # a slim row is about 1 KB in memory; a wide overflow is recorded as an event and never fails the run


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


def wide_row(tick: dict, symbol: str, recv: pd.Timestamp) -> dict:
    """One slim row of a quote-mode tick: price, quantities, the day's open/high/low/close and Kite's percent change. No depth, no open interest (not in the packet)."""
    ohlc = tick.get("ohlc") or {}
    return {"symbol": symbol, "token": int(tick["instrument_token"]), "ts_exchange": _ist(tick.get("exchange_timestamp") or tick.get("last_trade_time")), "ts_recv": recv,
            "last_price": _f(tick.get("last_price")), "last_qty": _f(tick.get("last_traded_quantity")), "volume": _f(tick.get("volume_traded")), "oi": _f(tick.get("oi")),
            "buy_qty_total": _f(tick.get("total_buy_quantity")), "sell_qty_total": _f(tick.get("total_sell_quantity")), "change": _f(tick.get("change")),
            "open": _f(ohlc.get("open")), "high": _f(ohlc.get("high")), "low": _f(ohlc.get("low")), "close": _f(ohlc.get("close"))}


MAX_BUFFER = 1_000_000                                       # ticks held in memory between flushes (a minute is a few thousand)


class Recorder:
    """Collects ticks and writes them in parts. `now` is injectable so tests control time; the websocket object is whatever `ticker_factory` returns (KiteTicker's interface)."""

    def __init__(self, out_dir: Path, tokens: dict[str, int], ticker_factory, now=None, flush_seconds: float = FLUSH_SECONDS, live=None, core=None, meta=None, deep=None):
        self.out = Path(out_dir)
        self.tokens = dict(tokens)
        self.by_token = {v: k for k, v in self.tokens.items()}
        self.now = now or (lambda: pd.Timestamp.now(tz=IST))
        self.flush_seconds = flush_seconds
        self.core = set(tokens) if core is None else set(core)       # symbols recorded in FULL mode (five levels of depth); the rest in QUOTE mode (price, volume, quantities, no depth)
        self.deep = (set(deep or ()) & set(tokens)) - self.core      # wide symbols also SUBSCRIBED in FULL mode, for the live view's order book (options, the watchlist). They are still written as slim wide rows: the recorded layout does not change
        self.meta = dict(meta or {})                                 # symbol -> {'s': segment, ...}: what each instrument is, for the live view
        self.live = live                                             # the display-only 5-second push (live_push.py), or None; it never affects the recording
        self.rows: list[dict] = []
        self.wide_rows: list[dict] = []                              # the wide universe's slim rows (see WIDE_COLUMNS)
        self.wide_overflow = self.wide_dropped = self.wide_ticks = self.wide_part = 0
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
        full = [t for s_, t in self.tokens.items() if s_ in self.core]
        deep = [t for s_, t in self.tokens.items() if s_ in self.deep]
        wide = [t for s_, t in self.tokens.items() if s_ not in self.core and s_ not in self.deep]
        for i in range(0, len(full) + len(deep) + len(wide), 500):     # subscribe in chunks: one oversized message is the easiest way to lose a subscription
            ws.subscribe((full + deep + wide)[i:i + 500])
        if full:
            ws.set_mode(ws.MODE_FULL, full)
        for i in range(0, len(deep), 500):                              # after the core five, so a refusal here can never cost them their mode
            ws.set_mode(ws.MODE_FULL, deep[i:i + 500])
        for i in range(0, len(wide), 500):                              # QUOTE is the default mode of a subscription: this only makes it explicit, in messages of a size the socket takes
            ws.set_mode(getattr(ws, "MODE_QUOTE", "quote"), wide[i:i + 500])
        self._event("connect", n=len(full) + len(deep) + len(wide), full=len(full), deep=len(deep), quote=len(wide))

    def _on_ticks(self, ws, ticks) -> None:
        recv = self.now()
        with self.lock:
            for t in ticks:
                sym = self.by_token.get(t.get("instrument_token"))
                if sym is None:
                    continue
                if sym not in self.core:                            # the wide universe: its own slim row and buffer, never mixed into the trial's data
                    if len(self.wide_rows) >= MAX_WIDE_BUFFER:
                        self.wide_overflow += 1
                        continue
                    row = wide_row(t, sym, recv)
                    self.wide_rows.append(row)
                    self.wide_ticks += 1
                    if self.live is not None:
                        try:
                            m = self.meta.get(sym) or {}
                            q = quote_from_tick(row, t.get("change"), m.get("s"), m.get("expiry") if m.get("kind") == "future" else None)
                            if q and sym in self.deep:                # FULL mode: the tick carries the book
                                q.update(book_from_tick(t))
                            self.live.update(sym, q)
                        except Exception:                           # noqa: BLE001
                            pass
                    continue
                if len(self.rows) >= MAX_BUFFER:                    # writes keep failing: stop growing without bound and say so once per flush
                    self.overflow += 1
                    continue
                row = tick_row(t, sym, recv)
                self.rows.append(row)
                self.ticks += 1
                if self.live is not None:
                    try:
                        m = self.meta.get(sym) or {}
                        q = quote_from_tick(row, t.get("change"), m.get("s"), m.get("expiry") if m.get("kind") == "future" else None)
                        if q:
                            q.update({k: v for k, v in book_from_tick(t).items() if k == "d"})      # the five levels; the best bid and offer are already on the row
                        self.live.update(sym, q)
                    except Exception:                               # noqa: BLE001 - the display must never cost a recorded tick
                        pass

    def _flush_wide(self) -> None:
        """Write the wide universe's rows to wide/wide_<tag>_<part>.parquet. Best effort: a failed write keeps the rows for the next flush; it never raises and never counts against the run."""
        with self.lock:
            rows, self.wide_rows = self.wide_rows, []
            lost, self.wide_overflow = self.wide_overflow, 0
        self.wide_dropped += lost
        if lost:
            self._event("wide_overflow", dropped_ticks=lost)
        if not rows:
            return
        part = self.wide_part + 1
        try:
            d = self.out / "wide"
            d.mkdir(exist_ok=True)
            path = d / f"wide_{self.tag}_{part:04d}.parquet"
            tmp = path.with_name(path.name + ".part")
            pd.DataFrame(rows, columns=WIDE_COLUMNS).to_parquet(tmp, index=False)
            tmp.replace(path)
            self.wide_part = part
        except Exception:                                          # noqa: BLE001
            with self.lock:
                kept = rows + self.wide_rows
                self.wide_dropped += max(0, len(kept) - MAX_WIDE_BUFFER)      # the oldest rows are dropped to stay bounded: counted, never silent
                self.wide_rows = kept[-MAX_WIDE_BUFFER:]

    def flush(self) -> Path | None:
        try:
            self._flush_wide()
        except Exception:                                          # noqa: BLE001 - the wide universe is best effort: a freak error there must never skip the core flush below
            pass
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
        if self.live is not None:
            try:
                self.live.start()
            except Exception:                                       # noqa: BLE001 - no display, same recording
                self.live = None
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
        self.flush()                                                # the recording first: the display's last push (which can wait on the network) must never delay the last part
        self._event("wide", ticks=self.wide_ticks, parts=self.wide_part, dropped=self.wide_dropped, unwritten=len(self.wide_rows))
        if self.live is not None:
            try:
                self.live.stop()
                self._event("live", **self.live.stats())
            except Exception:                                       # noqa: BLE001
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


def run_session(out_dir: Path, until_hhmm: str, day: dt.date | None = None, kite=None, ticker_factory=None, now=None, sleep=time.sleep, with_reference: bool = False,
                watchlist: dict | None = None, stock_steps: int = 8) -> dict:
    """Record from now until `until_hhmm` IST today. Credentials from the environment. Writes to `out_dir`; refuses a folder inside a git tree outside runtime/.
    `watchlist` (config `desk.watchlist`) names what the owner trades: those instruments and every option are subscribed with their order book, for the live view only."""
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
    core = set(tokens)
    meta = {k: {"s": "idx" if k in INDEX_NAMES else "fut", "kind": "index" if k in INDEX_NAMES else "future", "name": k.split("-")[0]} for k in tokens}
    wide_errors: list[str] = []
    if os.environ.get("KITE_WIDE", "1") != "0":                    # everything else the desk watches; fail-soft: the core five are recorded whatever happens here
        try:
            wide_tokens, wide_meta, wide_errors = build_wide(kite, today, tokens, stock_options=(watchlist or {}).get("stocks") or (), stock_steps=stock_steps)
            tokens.update(wide_tokens)
            meta.update(wide_meta)
        except Exception as e:                                     # noqa: BLE001
            wide_errors = [f"wide universe: {type(e).__name__}"]
    deep: list[str] = []
    if os.environ.get("KITE_DEEP", "1") != "0":                    # the order books for the live view; KITE_DEEP=0 puts every wide instrument back in QUOTE mode
        try:
            deep = deep_symbols(meta, watchlist)
        except Exception as e:                                     # noqa: BLE001 - the live view's books never cost the recording
            wide_errors = [*wide_errors, f"deep list: {type(e).__name__}"]
    (Path(out_dir)).mkdir(parents=True, exist_ok=True)
    all_tokens = dict(tokens)
    tokens = {k: v for k, v in all_tokens.items() if k in core}      # tokens.json is what the pre-registered trial measures: the five core instruments only
    (Path(out_dir) / "tokens.json").write_text(json.dumps(tokens, indent=1))
    (Path(out_dir) / "universe.json").write_text(json.dumps({"meta": meta, "errors": wide_errors, "core": sorted(core), "deep": sorted(deep), "wide_tokens": {k: v for k, v in all_tokens.items() if k not in core}}, indent=1))
    h, m = (int(x) for x in until_hhmm.split(":"))
    until = pd.Timestamp.combine(pd.Timestamp(today), dt.time(h, m)).tz_localize(IST)
    rec = Recorder(Path(out_dir), all_tokens, ticker_factory, now=clock, live=LivePusher.from_env(), core=core, meta=meta, deep=deep)
    stats = rec.run(until, sleep=sleep)
    if with_reference:
        fetch_reference(kite, tokens, today, Path(out_dir))
    if stats["unwritten"] or stats["dropped"]:                     # ticks are gone (the last write failed, or the buffer overflowed while writes were failing): the run must not look clean
        raise KiteRecordError(f"{stats['unwritten']:,} ticks could not be written to {out_dir} and {stats['dropped']:,} were dropped from a full buffer; they are lost, the parts already written are kept")
    return {"day": str(today), "tokens": tokens, "wide_n": len(all_tokens) - len(tokens), "deep_n": len(deep), "wide_errors": wide_errors, **stats}
