"""Kite Connect websocket as the desk's live source of index bars and the live index price, with the existing feeds behind it as the automatic fallback.

Owner decision (25 Oct 2026): the Kite websocket is attached directly to the running desk, not recorded in shadow. What that means, exactly:

- **Bars:** a completed minute built from Kite ticks is served in place of Kotak's or Yahoo's for that minute. Where Kite has no tick for a minute (a drop, a late connect), the
  wrapped feed supplies it and the result has no holes. A Kite minute whose close differs from the fallback's by more than 0.5% is not used (counted, and the fallback served).
- **Live price:** `ltp()` answers from the last Kite tick when it is fresh (under 20 s) and within 0.5% of the last served close (a bigger jump must agree with the wrapped feed's price),
  else from the wrapped feed. It is asked only where the wrapped feed already has a live price: the websocket never switches the engine to deciding on single ticks.
- **Everything else is the wrapped feed's:** history (Yahoo, what the models were built on), the near-month futures volume put on index bars, the Kotak chain. No tick-level order
  flow yet (`has_ticks` stays False): trades from ticks would change vote inputs, which is a separate reviewed step.
- **Failure is invisible to the desk:** no key, no token, a refused connection, an expired token, a silent socket: every one leaves the wrapped feed exactly as it was.
- **Licence.** Kite's market data is the subscriber's: the minutes this module serves are not written to the recorder (`unrecorded`), so they never reach the public run artifacts or
  the `chains-YYYY` release. The app shows only how old the last tick is, never a Kite price.
- **Market data only.** No order method is used anywhere in this module (a test checks), and nothing here reaches the broker, risk or sizing code.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from collections import Counter

import pandas as pd

from .feeds import BAR, IST, ist

log = logging.getLogger(__name__)
INDEX_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "INDIAVIX": "NSE:INDIA VIX"}
STALE_TICK_S = 30.0                # an exchange stamp older than this is not a live tick
STALE_S = 20.0                      # a tick older than this and the socket is not trusted for the live price
MAX_DISAGREE = 0.005                # a Kite minute close this far from the fallback's is not used
COLUMNS = ["open", "high", "low", "close", "volume"]
TOKEN_RE = re.compile(r"[A-Za-z0-9]{16,64}")      # the shape of a Kite access token; anything else (a bad decrypt, a newline) is never exported
FIRST_TICK_S = 15.0                 # a minute whose first tick came later than this after the minute began is partial (late connect, reconnect) and is not served from Kite
FUTURE_S = 5.0                      # a tick stamped this far ahead of our clock is dropped
SAMPLE_EVERY = 10                   # every Nth otherwise-Kite-only poll per symbol also asks the fallback, so the disagreement rule (E4) has a denominator


class _Passthrough(Exception):
    """The wrapped feed's own failure: it goes on to the engine exactly as it was (the engine counts it), never swallowed and never mistaken for a Kite fault."""

    def __init__(self, exc):
        super().__init__(repr(exc))
        self.exc = exc


def exchange_token(api_key: str, api_secret: str, request_token: str, connect=None) -> str:
    """The day's access token from the one-time request_token of the owner's morning login. The API secret is used here and in the workflow's encryption step, nowhere else."""
    if connect is None:
        from kiteconnect import KiteConnect as connect
    data = connect(api_key=api_key).generate_session(request_token, api_secret=api_secret)
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        raise ValueError("Kite did not return an access token for that request token")
    return token


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
        self.dropped: Counter = Counter()                             # ticks not used, by reason
        self.closed_to: dict[str, pd.Timestamp] = {}                 # the last minute finished per symbol: a straggler for it can never reopen it
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

    def _close(self, sym: str, c: dict) -> None:
        """A finished minute is kept only if Kite saw it from (nearly) its start; a partial one would stand in for a bar whose open, high and low it never saw."""
        self.closed_to[sym] = max(c["t"], self.closed_to.get(sym, c["t"]))
        if (c["first"] - c["t"]).total_seconds() > FIRST_TICK_S:
            self.dropped["partial_minute"] += 1
            return
        self.done[sym][c["t"]] = {k: c[k] for k in COLUMNS}

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
                stamp = t.get("exchange_timestamp") or t.get("last_trade_time")
                ts = ist(stamp) if stamp else recv
                if ts > recv + pd.Timedelta(seconds=FUTURE_S) or recv - ts > pd.Timedelta(seconds=STALE_TICK_S):
                    self.dropped["stamp"] += 1                      # a stamp that disagrees with our clock is not a live tick: dropped, never re-stamped as now
                    continue
                m = ts.floor("min")
                c = self.cur.get(sym)
                if m <= self.closed_to.get(sym, m - pd.Timedelta(minutes=1)) or (c is not None and m < c["t"]):
                    self.dropped["late"] += 1
                    continue                                      # a late tick for a minute already closed
                if c is not None and m > c["t"]:
                    self._close(sym, c)
                    c = None
                if c is None:
                    c = self.cur[sym] = {"t": m, "first": ts, "open": px, "high": px, "low": px, "close": px, "volume": 0.0}
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
                self._close(symbol, cur)
                self.cur.pop(symbol)
            rows = dict(self.done.get(symbol, {}))
        if not rows:
            return pd.DataFrame(columns=COLUMNS)
        df = pd.DataFrame.from_dict(rows, orient="index")[COLUMNS].sort_index()
        df.index = pd.DatetimeIndex(df.index).as_unit("ns")
        minute = df.index.hour * 60 + df.index.minute
        return df[(minute >= 9 * 60 + 15) & (minute < 15 * 60 + 30)]          # the cash session only, as every other feed (feeds.normalise_bars)


def make_live(cfg, symbols: list[str], say=print) -> KiteLive | None:
    """Start the websocket if KITE_DATA_KEY and KITE_DATA_TOKEN are in the environment; None (and one line) in every other case. Never raises. These are deliberately not the names the
    broker adapter (execution/kite.py) reads, so the day's token can never switch that adapter's credentials on."""
    key, token = os.environ.get("KITE_DATA_KEY"), os.environ.get("KITE_DATA_TOKEN")
    if not key or not token:
        say("kite live: no KITE_DATA_KEY / KITE_DATA_TOKEN; bars and prices from the existing feeds")
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
        self._kite_ts: dict[str, set] = {}                            # minutes whose numbers came from Kite (kept out of the recorder)
        self._fast: Counter = Counter()
        self._late_seen: dict[str, set] = {}                          # 15:15 to 15:28 index minutes already counted (E3)

    def __getattr__(self, name):                                      # history, history_bars, completed, now, realtime_age, has_ticks, trades, fut_bars, ...
        return getattr(self._inner, name)

    @property
    def has_ltp(self) -> bool:
        """The wrapped feed's own: a live price between minutes decides armed orders on single ticks, and the websocket must not switch that on for a desk that did not have it."""
        return bool(getattr(self._inner, "has_ltp", False))

    @property
    def name(self) -> str:
        """What served the bars, for the session review and the site: Kite's minutes and polls, rejected minutes, and the wrapped feed's own account of the rest."""
        k, m, rej = self.served["kite"], self.served["minutes"], self.served["rejected"]
        base = getattr(self._inner, "name", "feed")
        if not (k or rej):
            return f"{base} (kite websocket silent)"
        return f"kite ({m} minutes in {k} polls" + (f", {rej} minute(s) rejected" if rej else "") + f") over {base}"

    def poll(self, symbol, since):
        self.served["polls"] += 1
        try:
            out = self._poll(symbol, since)
        except _Passthrough as p:
            raise p.exc
        except Exception as exc:                                       # a fault in the Kite logic itself: the wrapped feed answers, as if Kite were not there
            self.last_error = type(exc).__name__
            self.served["kite_faults"] += 1
            self.served["fallback"] += 1
            out = self._inner.poll(symbol, since)
        if out is not None and len(out):
            self._last_close[symbol] = float(out["close"].iloc[-1])
            self._count_late(symbol, out)
        return out

    def _count_late(self, symbol, out) -> None:
        """E3 of docs/ml/KITE_TRIAL.md: of the Kite-served index minutes from 15:15 to 15:28 (where Kotak's index series is frozen), how many are flat (open = high = low = close)."""
        if symbol not in ("NIFTY", "BANKNIFTY"):
            return
        mine, seen = self._kite_ts.get(symbol, ()), self._late_seen.setdefault(symbol, set())
        for ts in out.index:
            if ts in mine and ts not in seen and ts.hour == 15 and 15 <= ts.minute <= 28:
                seen.add(ts)
                r = out.loc[ts]
                self.served["late_minutes"] += 1
                if float(r["open"]) == float(r["high"]) == float(r["low"]) == float(r["close"]):
                    self.served["late_flat"] += 1

    def unrecorded(self, symbol) -> set:
        """Minutes of `symbol` served from Kite: the engine keeps them out of the recorder (Kite's licence; they would reach public run artifacts and a public release)."""
        return set(self._kite_ts.get(symbol, ()))

    def _mark(self, symbol, index) -> None:
        self._kite_ts.setdefault(symbol, set()).update(index)

    def _fallback(self, symbol, since):
        self.served["fallback"] += 1
        try:
            return self._inner.poll(symbol, since)
        except Exception as exc:
            self.last_error = type(exc).__name__
            raise _Passthrough(exc)

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
                    self._fast[symbol] += 1
                    if not self._fast[symbol] % SAMPLE_EVERY:
                        self.served["sampled"] += 1                    # asked on purpose, not because Kite could not serve: counted apart so the fallback's real use is readable
                    if self._fast[symbol] % SAMPLE_EVERY:              # complete and fresh: no other source is asked, except every Nth time (below)
                        self.served["kite"] += 1
                        self.served["minutes"] += len(sl)
                        self._mark(symbol, sl.index)
                        return self._with_volume(symbol, sl, now)
        try:
            fb = self._fallback(symbol, since)                         # the fallback fills what Kite lacks (and is asked for the whole day on the first poll)
        except _Passthrough:                                           # Yahoo returning nothing (F-19-1) or Kotak down: Kite's unbroken, unjumping minutes, if there are any, still count
            run = self._contiguous(live_df, since, last_done) if live_df is not None and since is not None and self.live.healthy(symbol) else None
            if run is None or not len(run) or self._jumps(symbol, run):
                raise
            self.served["kite"] += 1
            self.served["minutes"] += len(run)
            self._mark(symbol, run.index)
            return self._with_volume(symbol, run, now)
        if live_df is None or not len(live_df) or fb is None:
            return fb
        merged = fb.copy() if len(fb) else pd.DataFrame(columns=COLUMNS)
        used, kite_only = 0, []
        for ts, row in live_df.iterrows():
            if since is not None and ts <= since:
                continue
            if ts in merged.index:
                ref = float(merged.at[ts, "close"])
                self.served["compared"] += 1
                if ref > 0 and abs(float(row["close"]) - ref) / ref > MAX_DISAGREE:
                    self.served["rejected"] += 1
                    continue
                for c in ("open", "high", "low", "close"):
                    merged.at[ts, c] = row[c]                          # the fallback's volume (futures volume for an index) stays
                used += 1
                self._mark(symbol, [ts])
            else:
                before = merged.loc[merged.index < ts, "close"]        # a minute the fallback lacks is added only if it continues, without a hole, from the minute before it
                prev_ts = ts - BAR
                adjacent = prev_ts in merged.index or (since is not None and prev_ts == since)
                prev = float(merged.at[prev_ts, "close"]) if prev_ts in merged.index else (float(before.iloc[-1]) if len(before) else self._last_close.get(symbol))
                if not adjacent or (prev is not None and prev > 0 and abs(float(row["close"]) - prev) / prev > MAX_DISAGREE):
                    self.served["rejected" if adjacent else "holes"] += 1
                    continue
                merged = pd.concat([merged, pd.DataFrame([row[COLUMNS].to_numpy()], index=pd.DatetimeIndex([ts]), columns=COLUMNS)]).sort_index()
                kite_only.append(ts)
                used += 1
                self._mark(symbol, [ts])
        if used:
            self.served["kite"] += 1
            self.served["minutes"] += used
        merged = merged.sort_index()
        merged.index = pd.DatetimeIndex(merged.index).as_unit("ns")
        if kite_only:                                                   # the futures' volume the wrapped feed puts on index bars, for the minutes it did not have
            sub = self._with_volume(symbol, merged.loc[kite_only], now)
            if sub is not None and len(sub) == len(kite_only) and "volume" in sub:
                merged.loc[kite_only, "volume"] = sub["volume"].to_numpy()
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
        """For the app's Data panel: is the websocket delivering, what it served, and how old each index's last Kite tick is. Display only, and never a Kite price: that data is not published."""
        now = self._inner.now()
        syms = {}
        for sym in self.live.tokens:
            ts = self.live.last_tick.get(sym)
            syms[sym] = {"age_s": round((now - ts).total_seconds(), 1) if ts is not None else None}
        c = self.served
        return {"attached": True, "connected": bool(self.live.connected), "live": bool(self.live.healthy()), "polls": int(c["polls"]), "kite_polls": int(c["kite"]),
                "fallback_polls": int(c["fallback"]), "sampled_polls": int(c["sampled"]), "late_minutes": int(c["late_minutes"]), "late_flat": int(c["late_flat"]), "minutes": int(c["minutes"]), "compared": int(c["compared"]), "rejected": int(c["rejected"]), "faults": int(c["kite_faults"]),
                "dropped": dict(self.live.dropped), "symbols": syms, "last_error": self.last_error[:60]}

    def ltp(self, symbols):
        try:
            return self._ltp(symbols)
        except Exception as exc:
            self.last_error = type(exc).__name__
            self.served["kite_faults"] += 1
            return self._inner.ltp(symbols) if hasattr(self._inner, "ltp") else {}

    def _ltp(self, symbols):
        out = {}
        for s in symbols:
            p = self.live.ltp(s)
            if p is None:
                continue
            last = self._last_close.get(s)
            if last and abs(p - last) / last > MAX_DISAGREE:           # a jump from the last served close: believed only if the wrapped feed's price agrees
                fb = (self._inner.ltp([s]) or {}).get(s) if hasattr(self._inner, "ltp") else None
                if not fb or abs(p - fb) / fb > MAX_DISAGREE:
                    self.served["rejected"] += 1
                    continue
            out[s] = p
        missing = [s for s in symbols if s not in out]
        if missing and hasattr(self._inner, "ltp"):
            out.update(self._inner.ltp(missing) or {})
        return out
