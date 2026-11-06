"""The 5-second live push: the Kite recorder's latest prices, sent to the private live relay (deploy/cloudflare/live.js) for the app's Live tab.

DISPLAY ONLY. Nothing here is read by the paper desk or any trading code, and it can place no order: it holds only the latest price fields of a few symbols and
a bearer token that lets the holder write to the relay's display. The recording to Parquet is the record; this is a window onto it, and **a failure here never
touches the recording** (every error is caught and counted, nothing is raised into the websocket thread or the recorder).

It is off unless both `LIVE_URL` (https) and `LIVE_INGEST_TOKEN` are set in the environment. The token is never printed, logged or put in an error.
Only quotes that CHANGED since the last push are sent, so a quiet market (or a closed one) shows on the app as a growing age instead of a repeated price that
looks fresh.
"""
from __future__ import annotations

import json
import math
import os
import threading
import urllib.error
import urllib.request

INTERVAL_S = 5.0
TIMEOUT_S = 4.0
FIELDS = ("ltp", "bid", "ask", "bid_qty", "ask_qty", "vol", "oi", "chg")


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def quote_from_tick(row: dict, change=None) -> dict | None:
    """The display fields of one recorded tick row (`kite_record.tick_row`) plus Kite's own percent change; None if there is no last price."""
    q = {"ltp": _num(row.get("last_price")), "bid": _num(row.get("bid")), "ask": _num(row.get("ask")), "bid_qty": _num(row.get("bid_qty")),
         "ask_qty": _num(row.get("ask_qty")), "vol": _num(row.get("volume")), "oi": _num(row.get("oi")), "chg": _num(change)}
    q = {k: v for k, v in q.items() if v is not None}
    if "ltp" not in q:
        return None
    ts = row.get("ts_exchange")
    if ts is not None and str(ts) not in ("NaT", "None"):
        q["t"] = str(ts)[:40]
    return q


class LivePusher:
    def __init__(self, url: str, token: str, interval: float = INTERVAL_S, timeout: float = TIMEOUT_S, opener=None):
        if not str(url).startswith("https://"):
            raise ValueError("LIVE_URL must be an https URL")
        if not token:
            raise ValueError("no token")
        self.url, self._token, self.interval, self.timeout = url, token, interval, timeout
        self._open = opener or urllib.request.urlopen
        self.dirty: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.ok = self.failed = 0
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
            with self.lock:
                self.dirty[symbol] = quote

    def push_once(self) -> bool:
        """Send what changed since the last push. Returns True if there was nothing to send or the relay accepted it."""
        with self.lock:
            batch, self.dirty = self.dirty, {}
        if not batch:
            return True
        try:
            req = urllib.request.Request(self.url, data=json.dumps({"quotes": batch}).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": "Bearer " + self._token, "User-Agent": "quantdesk-live"})
            with self._open(req, timeout=self.timeout) as r:
                if not 200 <= getattr(r, "status", 200) < 300:
                    raise urllib.error.HTTPError(self.url, r.status, "relay refused", None, None)
            self.ok += 1
            self.last_error = None
            return True
        except Exception as e:                                       # noqa: BLE001 - nothing here may reach the recorder
            with self.lock:                                          # keep what was not sent, unless a newer tick has replaced it
                for k, v in batch.items():
                    self.dirty.setdefault(k, v)
            self.failed += 1
            self.last_error = type(e).__name__ + (f" {e.code}" if isinstance(e, urllib.error.HTTPError) else "")     # the class and status only: never the URL or token
            return False

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
        return {"pushes_ok": self.ok, "pushes_failed": self.failed, "last_error": self.last_error}
