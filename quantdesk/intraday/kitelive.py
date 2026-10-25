"""Kite Connect websocket as the desk's live source of index bars and the live index price, with the existing feeds behind it as the automatic fallback.

Owner decision (24 Oct 2026): the Kite websocket is attached directly to the running desk, not recorded in shadow. What that means, exactly:

- **Bars:** a completed minute built from Kite ticks is served in place of Kotak's or Yahoo's for that minute. Where Kite has no tick for a minute (a drop, a late connect), the
  wrapped feed supplies it and the result has no holes. A Kite minute whose close differs from the fallback's by more than 0.5% is not used (counted, and the fallback served).
- **Live price:** `ltp()` answers from the last Kite tick when it is fresh (under 20 s), else from the wrapped feed.
- **Everything else is the wrapped feed's:** history (Yahoo, what the models were built on), the near-month futures volume put on index bars, the Kotak chain. No tick-level order
  flow yet (`has_ticks` stays False): trades from ticks would change vote inputs, which is a separate reviewed step.
- **Failure is invisible to the desk:** no key, no token, a refused connection, an expired token, a silent socket: every one leaves the wrapped feed exactly as it was.
- **Market data only.** No order method is used anywhere in this module (a test checks), and nothing here reaches the broker, risk or sizing code.
"""
from __future__ import annotations

import logging
import os
import threading
from collections import Counter

import pandas as pd

from .feeds import BAR, IST, ist

log = logging.getLogger(__name__)
INDEX_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "INDIAVIX": "NSE:INDIA VIX"}
STALE_S = 20.0                      # a tick older than this and the socket is not trusted for the live price
MAX_DISAGREE = 0.005                # a Kite minute close this far from the fallback's is not used
COLUMNS = ["open", "high", "low", "close", "volume"]


class KiteLive:
    """Tick → completed 1-minute bars per symbol, from the websocket. Thread-safe; `ticker_factory()` returns a KiteTicker-like object."""

    def __init__(self, tokens: dict[str, int], ticker_factory, now=None):
        self.tokens = dict(tokens)
        self.by_token = {v: k for k, v in self.tokens.items()}
        self.now = now or (lambda: pd.Timestamp.now(tz=IST))
        self.lock = threading.Lock()
        self.cur: dict[str, dict] = {}
        self.done: dict[str, dict[pd.Timestamp, dict]] = {s: {} for s in self.tokens}
        self.last_tick: dict[str, pd.Timestamp] = {}
        self.last_price: dict[str, float] = {}
        self.connected = False
        self.ws = ticker_factory()
        self.ws.on_ticks = self._on_ticks
        self.ws.on_connect = self._on_connect
        self.ws.on_close = lambda ws, code, reason: self._set_connected(False)
        self.ws.on_noreconnect = lambda ws: self._set_connected(False)
        self.ws.on_reconnect = lambda ws, n: None

    def start(self) -> None:
        self.ws.connect(threaded=True)

    def stop(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def _set_connected(self, v: bool) -> None:
        self.connected = v

    def _on_connect(self, ws, response) -> None:
        toks = list(self.tokens.values())
        ws.subscribe(toks)
        ws.set_mode(ws.MODE_FULL, toks)
        self.connected = True

    def _on_ticks(self, ws, ticks) -> None:
        recv = self.now()
        with self.lock:
            for t in ticks:
                sym = self.by_token.get(t.get("instrument_token"))
                try:
                    px = float(t.get("last_price"))
                except (TypeError, ValueError):
                    continue
                if sym is None or not px == px or px <= 0:
                    continue
                ts = ist(t.get("exchange_timestamp") or t.get("last_trade_time") or recv)
                if abs((ts - recv).total_seconds()) > 120:        # a stamp far from our clock is not a live tick
                    ts = recv
                m = ts.floor("min")
                c = self.cur.get(sym)
                if c is not None and m < c["t"]:
                    continue                                      # a late tick for a minute already closed
                if c is not None and m > c["t"]:
                    self.done[sym][c["t"]] = {k: c[k] for k in COLUMNS}
                    c = None
                if c is None:
                    c = self.cur[sym] = {"t": m, "open": px, "high": px, "low": px, "close": px, "volume": 0.0}
                c["high"], c["low"], c["close"] = max(c["high"], px), min(c["low"], px), px
                self.last_tick[sym] = recv
                self.last_price[sym] = px

    def healthy(self, symbol: str | None = None) -> bool:
        """A tick for the symbol (or for any symbol) in the last STALE_S seconds."""
        now = self.now()
        ts = [self.last_tick[symbol]] if symbol in self.last_tick else ([] if symbol else list(self.last_tick.values()))
        return bool(ts) and (now - max(ts)).total_seconds() <= STALE_S

    def ltp(self, symbol: str) -> float | None:
        return self.last_price.get(symbol) if self.healthy(symbol) else None

    def bars(self, symbol: str) -> pd.DataFrame:
        """Completed minutes (before the minute now forming) since the connection."""
        with self.lock:
            cur = self.cur.get(symbol)
            if cur is not None and self.now().floor("min") > cur["t"]:
                self.done[symbol][cur["t"]] = {k: cur[k] for k in COLUMNS}
                self.cur.pop(symbol)
            rows = dict(self.done.get(symbol, {}))
        if not rows:
            return pd.DataFrame(columns=COLUMNS)
        df = pd.DataFrame.from_dict(rows, orient="index")[COLUMNS].sort_index()
        df.index = pd.DatetimeIndex(df.index).as_unit("ns")
        return df


def make_live(cfg, symbols: list[str], say=print) -> KiteLive | None:
    """Start the websocket if KITE_API_KEY and KITE_ACCESS_TOKEN are in the environment; None (and one line) in every other case. Never raises."""
    key, token = os.environ.get("KITE_API_KEY"), os.environ.get("KITE_ACCESS_TOKEN")
    if not key or not token:
        say("kite live: no KITE_API_KEY / KITE_ACCESS_TOKEN; bars and prices from the existing feeds")
        return None
    try:
        from kiteconnect import KiteConnect, KiteTicker
        kite = KiteConnect(api_key=key)
        kite.set_access_token(token)
        wanted = {s: INDEX_KEYS[s] for s in symbols if s in INDEX_KEYS}
        ltp = kite.ltp(list(wanted.values()))
        tokens = {s: int(ltp[k]["instrument_token"]) for s, k in wanted.items() if k in ltp}
        if not tokens:
            say("kite live: Kite knows none of the desk's indices; existing feeds")
            return None
        live = KiteLive(tokens, lambda: KiteTicker(key, token))
        live.start()
        say(f"kite live: websocket started for {', '.join(sorted(tokens))}")
        return live
    except Exception as exc:                                         # an expired token, no network, the library missing: the desk goes on as it was
        say(f"kite live: not started ({type(exc).__name__}); existing feeds")
        log.warning("kite live not started: %r", exc)
        return None


class KiteBackedFeed:
    """Wraps the desk's feed. Index bars and the live price come from `live` when it is healthy and complete; every other attribute is the wrapped feed's."""

    def __init__(self, inner, live: KiteLive):
        self._inner = inner
        self.live = live
        self.served: Counter = Counter()
        self.last_error = ""
        self._last_close: dict[str, float] = {}

    def __getattr__(self, name):                                      # history, history_bars, completed, now, realtime_age, has_ticks, trades, fut_bars, ...
        return getattr(self._inner, name)

    @property
    def has_ltp(self) -> bool:
        """A live price between minutes exists if the wrapped feed has one, or the websocket is delivering ticks right now."""
        return bool(getattr(self._inner, "has_ltp", False)) or self.live.healthy()

    @property
    def name(self) -> str:
        """What served the bars, for the session review and the site: Kite's minutes and polls, rejected minutes, and the wrapped feed's own account of the rest."""
        k, m, rej = self.served["kite"], self.served["minutes"], self.served["rejected"]
        base = getattr(self._inner, "name", "feed")
        if not (k or rej):
            return f"{base} (kite websocket silent)"
        return f"kite ({m} minutes in {k} polls" + (f", {rej} minute(s) rejected" if rej else "") + f") over {base}"

    def poll(self, symbol, since):
        out = self._poll(symbol, since)
        if out is not None and len(out):
            self._last_close[symbol] = float(out["close"].iloc[-1])
        return out

    def _poll(self, symbol, since):
        live_df = self.live.bars(symbol) if symbol in self.live.tokens else None
        now = self._inner.now()
        last_done = now.floor("min") - BAR
        if live_df is not None and len(live_df):
            need_from = (since + BAR) if since is not None else None
            sl = live_df[live_df.index > since] if since is not None else live_df
            if len(sl):
                expected = pd.date_range(need_from if need_from is not None else sl.index[0], last_done, freq="min", tz=IST)
                if (len(expected) and sl.index.isin(expected).all() and expected.isin(sl.index).all() and since is not None and self.live.healthy(symbol)
                        and not self._jumps(symbol, sl)):
                    self.served["kite"] += 1                           # complete and fresh: no other source is asked
                    self.served["minutes"] += len(sl)
                    return self._with_volume(symbol, sl, now)
        try:
            fb = self._inner.poll(symbol, since)                       # the fallback fills what Kite lacks (and is asked for the whole day on the first poll)
        except Exception as exc:                                       # Yahoo returning nothing (F-19-1) or Kotak down: Kite's unbroken minutes, if there are any, still count
            self.last_error = f"{exc!s:.200}"
            run = self._contiguous(live_df, since, last_done) if live_df is not None and since is not None and self.live.healthy(symbol) else None
            if run is None or not len(run):
                raise
            self.served["kite"] += 1
            self.served["minutes"] += len(run)
            return self._with_volume(symbol, run, now)
        if live_df is None or not len(live_df) or fb is None:
            return fb
        merged = fb.copy() if len(fb) else pd.DataFrame(columns=COLUMNS)
        used = 0
        for ts, row in live_df.iterrows():
            if since is not None and ts <= since:
                continue
            if ts in merged.index:
                ref = float(merged.at[ts, "close"])
                if ref > 0 and abs(float(row["close"]) - ref) / ref > MAX_DISAGREE:
                    self.served["rejected"] += 1
                    continue
                for c in ("open", "high", "low", "close"):
                    merged.at[ts, c] = row[c]                          # the fallback's volume (futures volume for an index) stays
                used += 1
            else:
                merged.loc[ts] = row[COLUMNS].to_numpy()
                used += 1
        if used:
            self.served["kite"] += 1
            self.served["minutes"] += used
        merged = merged.sort_index()
        merged.index = pd.DatetimeIndex(merged.index).as_unit("ns")
        return merged

    def _jumps(self, symbol: str, sl: pd.DataFrame) -> bool:
        """A minute that closes more than MAX_DISAGREE from the one before it (or from the last close this feed served) cannot be served unchecked: the fallback is asked
        and the two must agree. A real spike passes that check; a bad stream does not."""
        prev = self._last_close.get(symbol)
        for c in sl["close"]:
            if prev is not None and prev > 0 and abs(float(c) - prev) / prev > MAX_DISAGREE:
                return True
            prev = float(c)
        return False

    @staticmethod
    def _contiguous(live_df: pd.DataFrame, since, last_done) -> pd.DataFrame:
        """Kite's minutes after `since`, up to the first missing one (a hole must never be papered over)."""
        sl = live_df[live_df.index > since]
        if not len(sl):
            return sl
        want = pd.date_range(since + BAR, last_done, freq="min", tz=IST)
        n = 0
        for ts in want:
            if ts not in sl.index:
                break
            n += 1
        return sl.loc[want[:n]] if n else sl.iloc[0:0]

    def _with_volume(self, symbol, df, now):
        """The index bars with the futures' volume, as the wrapped Kotak feed does; any failure leaves the bars as they are."""
        f = getattr(self._inner, "_with_futures", None)
        if f is None or df.empty:
            return df
        try:
            return f(symbol, df, now.date(), now.date())
        except Exception:
            return df

    def status(self) -> dict:
        """For the app's Data panel: is the websocket delivering, what it served, and each index's last Kite price and its age. Display only."""
        now = self._inner.now()
        syms = {}
        for sym in self.live.tokens:
            ts = self.live.last_tick.get(sym)
            syms[sym] = {"ltp": self.live.last_price.get(sym), "age_s": round((now - ts).total_seconds(), 1) if ts is not None else None}
        return {"attached": True, "connected": bool(self.live.connected), "live": bool(self.live.healthy()), "polls": int(self.served["kite"]),
                "minutes": int(self.served["minutes"]), "rejected": int(self.served["rejected"]), "symbols": syms, "last_error": self.last_error[:160]}

    def ltp(self, symbols):
        out = {}
        for s in symbols:
            p = self.live.ltp(s)
            if p is not None:
                out[s] = p
        missing = [s for s in symbols if s not in out]
        if missing and hasattr(self._inner, "ltp"):
            out.update(self._inner.ltp(missing) or {})
        return out
