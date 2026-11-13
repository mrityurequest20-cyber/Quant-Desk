"""The 5-second live push: the Kite recorder's latest prices, sent to the private live relay (deploy/cloudflare/live.js) for the app's Live tab.

DISPLAY ONLY. Nothing here is read by the paper desk or any trading code, and it can place no order: it holds only the latest price fields of a few symbols and
a bearer token that lets the holder write to the relay's display. The recording to Parquet is the record; this is a window onto it, and **a failure here never
touches the recording** (every error is caught and counted, nothing is raised into the websocket thread or the recorder).

It is off unless both `LIVE_URL` (https) and `LIVE_INGEST_TOKEN` are set in the environment. The token is never printed, logged or put in an error.
Only quotes that CHANGED since the last push are sent, so a quiet market (or a closed one) shows on the app as a growing age instead of a repeated price that
looks fresh.

Two things ride along for the app's instrument page. An instrument subscribed in Kite's FULL mode sends its order book (`book_from_tick`: the best bid and offer, and five levels
a side). And when an instrument ticks more than once between two pushes, the push carries the highest and lowest of those ticks (`hi`, `lo`), so the relay's one-minute candle has
the wick of every trade and not only of the price that happened to be last.

`LivePusher` is also the whole contract for another broker's feed: an adapter builds the same quote dicts under the desk's own instrument names and pushes them with its feed code
(`src`). Which feed is then shown for which kind of instrument is `feeds.routes` in the config, not code (docs/LIVE.md, "More than one broker").
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import urllib.error
import urllib.request

INTERVAL_S = 5.0
TIMEOUT_S = 4.0
FIELDS = ("ltp", "bid", "ask", "bid_qty", "ask_qty", "vol", "oi", "chg")
BATCH = 800                                                      # quotes in one POST: a wide universe is sent in several, each far under the relay's size limit
SEGMENTS = ("idx", "eq", "fut", "bfo", "mcx", "cds", "opt", "mopt", "copt")       # mopt, copt: MCX and currency options (their own routes)
SYMBOL = re.compile(r"^[A-Za-z0-9&_.:-]{1,40}$")
EXPIRY = re.compile(r"^\d{4}-\d{2}-\d{2}$")                 # the relay's own rule for a name: one it would refuse is dropped here, so it can never hold up a batch
PUSH_SOURCES = ("z", "u", "d", "a", "f")                         # the feeds the relay takes a push from, by code (deploy/cloudflare/routes.js PUSH_SOURCES; a test compares the two)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def quote_from_tick(row: dict, change=None, seg: str | None = None, expiry=None) -> dict | None:
    """The display fields of one recorded tick row (`kite_record.tick_row`) plus Kite's own percent change; None if there is no last price. `expiry` (a future's
    contract expiry, YYYY-MM-DD) goes as `e`: the board's name for a future moves to the next month at expiry, so a paper position records which contract it holds."""
    q = {"ltp": _num(row.get("last_price")), "bid": _num(row.get("bid")), "ask": _num(row.get("ask")), "bid_qty": _num(row.get("bid_qty")),
         "ask_qty": _num(row.get("ask_qty")), "vol": _num(row.get("volume")), "oi": _num(row.get("oi")), "chg": _num(change)}
    q = {k: v for k, v in q.items() if v is not None}
    if "ltp" not in q:
        return None
    if seg in SEGMENTS:
        q["s"] = seg
    if isinstance(expiry, str) and EXPIRY.match(expiry[:10]):
        q["e"] = expiry[:10]
    ts = row.get("ts_exchange")
    if ts is not None and str(ts) not in ("NaT", "None"):
        q["t"] = str(ts)[:40]
    return q


DEPTH_LEVELS = 5


def book_from_tick(tick: dict) -> dict:
    """The order book of a Kite FULL-mode tick, for the display: the best bid and offer with their sizes, and up to five levels a side as `d` = {"b": [[price, quantity, orders], ...],
    "a": [...]}. Empty when the tick carries no book (an index, or a QUOTE-mode tick). A level with no price or no size is left out; a side with nothing is left out."""
    depth = tick.get("depth") or {}
    out: dict = {}
    book: dict = {}
    for key, side, px, qty in (("b", "buy", "bid", "bid_qty"), ("a", "sell", "ask", "ask_qty")):
        levels = []
        for lv in (depth.get(side) or [])[:DEPTH_LEVELS]:
            if not isinstance(lv, dict):
                continue
            p_, q_, n_ = _num(lv.get("price")), _num(lv.get("quantity")), _num(lv.get("orders"))
            if p_ is not None and p_ > 0 and q_ is not None and q_ > 0:
                levels.append([p_, q_, n_ if n_ is not None and n_ >= 0 else 0])
        if levels:
            book[key] = levels
            out[px], out[qty] = levels[0][0], levels[0][1]
    if "bid" in out and "ask" in out and out["bid"] > out["ask"]:      # a crossed book is a bad quote: nothing of it is sent
        return {}
    if book:
        out["d"] = book
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would make urllib send the Authorization header to another host: refuse it (the relay never redirects)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LivePusher:
    def __init__(self, url: str, token: str, interval: float = INTERVAL_S, timeout: float = TIMEOUT_S, opener=None, src: str = "z"):
        if not str(url).startswith("https://"):
            raise ValueError("LIVE_URL must be an https URL")
        if not token:
            raise ValueError("no token")
        if src not in PUSH_SOURCES:
            raise ValueError("not a feed code the relay takes a push from")
        self.url, self._token, self.interval, self.timeout = url, token, interval, timeout
        self.src = src                                               # which feed this is, by the relay's one-letter code (deploy/cloudflare/routes.js); "z" (Kite) is the relay's default and is not sent
        self._open = opener or urllib.request.build_opener(_NoRedirect).open
        self.dirty: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.ok = self.failed = self.skipped = self.refused = 0
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def from_env(cls) -> "LivePusher | None":
        url, token = (os.environ.get("LIVE_URL") or "").strip(), (os.environ.get("LIVE_INGEST_TOKEN") or "").strip()
        if not url or not token:
            return None
        try:
            return cls(url, token)
        except ValueError:
            return None

    def update(self, symbol: str, quote: dict | None) -> None:
        """Called from the websocket thread for each tick: remember the newest quote of the symbol until the next push."""
        if quote:
            if not SYMBOL.match(str(symbol)):
                self.skipped += 1
                return
            with self.lock:
                prev = self.dirty.get(symbol)
                if prev is not None and "ltp" in quote:              # a second tick before the push: remember the highest and lowest of the window, so the relay's one-minute candle has the true wick
                    quote = {**quote, "hi": max(prev.get("hi", prev["ltp"]), quote["ltp"]), "lo": min(prev.get("lo", prev["ltp"]), quote["ltp"])}
                self.dirty[symbol] = quote

    def push_once(self) -> bool:
        """Send what changed since the last push, in batches. Returns True if there was nothing to send or the relay accepted all of it."""
        with self.lock:
            pending, self.dirty = self.dirty, {}
        if not pending:
            return True
        items = list(pending.items())
        allok = True
        for i in range(0, len(items), BATCH):
            batch = dict(items[i:i + BATCH])
            try:
                body = {"quotes": batch} if self.src == "z" else {"src": self.src, "quotes": batch}
                req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                             headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._token, "User-Agent": "quantdesk-live"})
                with self._open(req, timeout=self.timeout) as r:
                    if not 200 <= getattr(r, "status", 200) < 300:
                        raise urllib.error.HTTPError(self.url, r.status, "relay refused", None, None)
                    try:                                             # read INSIDE the connection: the relay says how many it could not take (its board is full), counted and never retried
                        answer = r.read(65536)
                    except Exception:                                # noqa: BLE001 - a body we cannot read changes nothing
                        answer = b""
                self.ok += 1
                self.last_error = None
                try:
                    self.refused += int(json.loads(answer or b"{}").get("refused") or 0)
                except Exception:                                    # noqa: BLE001
                    pass
            except Exception as e:                                   # noqa: BLE001 - nothing here may reach the recorder
                allok = False
                with self.lock:                                      # keep this batch and every later one, unless a newer tick has replaced it
                    for k, v in items[i:]:
                        self.dirty.setdefault(k, v)
                self.failed += 1
                self.last_error = type(e).__name__ + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else "")     # the class and status only: never the URL or token
                break                                                # the relay or the network is down: one timeout per cycle, not one per batch
        return allok

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.push_once()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="live-push", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.timeout + 1)
        self.push_once()                                             # the last quotes

    def stats(self) -> dict:
        return {"pushes_ok": self.ok, "pushes_failed": self.failed, "skipped_names": self.skipped, "refused_by_relay": self.refused, "last_error": self.last_error}
