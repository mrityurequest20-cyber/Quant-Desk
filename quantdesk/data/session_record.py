"""The session recorder without a desk: every minute from the open to the close, the indices' 1-minute bars (and
their futures') and an option-chain snapshot of each index's nearest expiry, written exactly where the desk used to
write them (`runtime/intraday/data/<day>/`), so `data archive-session` and the `chains-YYYY` release keep receiving
the same files. It reads and writes data only: no engine, no journal, no account, no order of any kind.

Sources: Kotak Neo (bars, futures bars, chain with live bid/ask) when KOTAK_CONSUMER_KEY is set; otherwise Yahoo's
bars and NSE's public chain. The Kite feed is never used here: its ticks are licensed to the subscriber and are
recorded, encrypted, by kite-record.yml.

    python -m quantdesk data record-session --until 12:20     # the morning runner
    python -m quantdesk data record-session                   # to the close
"""
from __future__ import annotations

import datetime as dt
import logging
import time as _time
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
IST = "Asia/Kolkata"
OPEN, CLOSE = dt.time(9, 15), dt.time(15, 30)


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz=IST)


def kotak_client():
    """A Kotak Neo data client when KOTAK_CONSUMER_KEY is set, else None (consumer key only: no login, no orders)."""
    from ..intraday.kotak import KotakClient, KotakError
    try:
        return KotakClient.from_env()
    except KotakError:
        return None


def make_sources(cfg, say=print):
    """(feed, chains): Kotak's when its key is set, else Yahoo's bars and NSE's public chain."""
    kotak = kotak_client()
    if kotak is not None:
        from ..intraday.chains import FallbackChain, NSEOptionChain
        from ..intraday.kotak import KotakIntradayFeed, KotakOptionChain
        kc = cfg.get("intraday.kotak", {}) or {}
        chains = FallbackChain(KotakOptionChain(kotak, strikes=kc.get("strikes", 20), refresh_min=kc.get("refresh_min", 1)),
                               NSEOptionChain(), secondary_min=cfg.get("intraday.chain_refresh_min", 3))
        return KotakIntradayFeed(cfg, kotak), chains
    import os
    if os.environ.get("KOTAK_CONSUMER_KEY", "").strip():          # the key is set but Kotak refused it: say so loudly
        say("::warning::record: KOTAK_CONSUMER_KEY is set but the Kotak client could not start; recording Yahoo bars and "
            "NSE's public chain instead (no live bid/ask)")
    else:
        say("record: no KOTAK_CONSUMER_KEY; Yahoo bars and NSE's public chain")
    from ..intraday.chains import NSEOptionChain
    from ..intraday.feeds import YahooIntradayFeed
    return YahooIntradayFeed(cfg), NSEOptionChain()


def nearest_expiry(chains, u: str, today: dt.date, min_days: int = 0) -> dt.date | None:
    try:
        exps = [e for e in chains.expiries(u) if (e - today).days >= min_days]
    except Exception as exc:                                  # no expiry list: no chain for this index today
        log.warning("expiries %s: %s", u, exc)
        return None
    return min(exps) if exps else None


class SessionRecording:
    """One session's recording loop. Every source call is guarded: a failed minute is counted and the loop goes on."""

    def __init__(self, cfg, feed, chains, recorder, underlyings=None, say=print, now=_now, sleep=_time.sleep):
        self.cfg, self.feed, self.chains, self.recorder, self.say, self.now, self.sleep = cfg, feed, chains, recorder, say, now, sleep
        self.underlyings = list(underlyings or cfg.get("intraday.underlyings", ["NIFTY", "BANKNIFTY"]))
        self.vix = cfg.get("universe.volatility_index", "INDIAVIX")
        self.chain_every = int(cfg.get("intraday.chain_refresh_min", 1) or 1)
        self.last_ts: dict[str, pd.Timestamp] = {}
        self.spot: dict[str, float] = {}
        self.expiry: dict[str, dt.date | None] = {}
        self.stats = {"bars": 0, "chains": 0, "bar_errors": 0, "chain_errors": 0, "minutes": 0}

    def start(self, day: dt.date) -> None:
        for u in self.underlyings:
            self.expiry[u] = nearest_expiry(self.chains, u, day, int(self.cfg.get("intraday.expiry_min_days", 0) or 0))
        self.say(f"record: session {day} · " + ", ".join(f"{u} {e}" for u, e in self.expiry.items())
                 + f" · feed {getattr(self.feed, 'name', '?')} · chain {getattr(self.chains, 'name', '?')}")

    def bars(self) -> None:
        for sym in self.underlyings + [self.vix]:
            try:
                new = self.feed.poll(sym, self.last_ts.get(sym))
            except Exception as exc:
                self.stats["bar_errors"] += 1
                log.warning("poll %s: %s", sym, exc)
                continue
            if new is None or new.empty:
                continue
            self.last_ts[sym] = new.index[-1]
            self.spot[sym] = float(new["close"].iloc[-1])
            self.recorder.record_bars(sym, new)
            self.stats["bars"] += len(new)
            fb = getattr(self.feed, "fut_bars", {}).get(sym)
            if fb is not None and len(fb):                        # the futures' own bars, for the chart and replays
                self.recorder.record_bars(f"{sym}-FUT", fb[fb.index.date == fb.index[-1].date()])

    def snapshot(self, ts: pd.Timestamp) -> None:
        for u in self.underlyings:
            e = self.expiry.get(u)
            if e is None:
                continue
            try:
                ch = self.chains.chain(u, e, spot=self.spot.get(u), ts=ts)
            except Exception as exc:
                self.stats["chain_errors"] += 1
                log.warning("chain %s: %s", u, exc)
                continue
            if ch is not None and len(ch) and ch.attrs.get("source") != "model":   # a model chain is not market data
                self.recorder.record_chain(ch)
                self.stats["chains"] += 1

    def fill_gaps(self, day: dt.date) -> int:
        """At the end: the minutes the polls missed, from the feed's own history for today (adds nothing already there)."""
        n = 0
        for sym in self.underlyings + [self.vix]:
            try:
                h = self.feed.history(sym, 2)
                n += self.recorder.fill_bars(sym, h[h.index.date == day]) if h is not None and len(h) else 0
            except Exception as exc:
                log.warning("gap fill %s: %s", sym, exc)
        return n

    def run(self, until: dt.time = CLOSE) -> dict:
        now = self.now()
        day = now.date()
        if now.weekday() >= 5:
            self.say("record: not a weekday; nothing to record")
            return {**self.stats, "day": str(day), "recorded": False}
        open_at = pd.Timestamp(dt.datetime.combine(day, OPEN), tz=IST)
        stop_at = pd.Timestamp(dt.datetime.combine(day, min(until, CLOSE)), tz=IST)
        if now >= stop_at:
            self.say(f"record: {now:%H:%M} is past {stop_at:%H:%M}; nothing to record")
            return {**self.stats, "day": str(day), "recorded": False}
        if now < open_at:
            self.say(f"record: waiting for the open ({open_at:%H:%M} IST)")
            self.sleep((open_at - now).total_seconds())
        self.start(day)
        while True:
            now = self.now()
            if now >= stop_at + pd.Timedelta(minutes=1):
                break
            self.bars()
            if self.stats["minutes"] % self.chain_every == 0:
                self.snapshot(now)
            self.stats["minutes"] += 1
            nxt = now.floor("min") + pd.Timedelta(minutes=1, seconds=5)    # 5 s into the next minute: its bar has closed
            self.sleep(max(1.0, (nxt - self.now()).total_seconds()))
        added = self.fill_gaps(day)
        out = {**self.stats, "gap_filled": added, "day": str(day), "recorded": True}
        self.say("record: " + ", ".join(f"{k} {v}" for k, v in out.items()))
        return out


def run(cfg, until: str | None = None, data_dir: Path | None = None, say=print) -> dict:
    from ..intraday.recorder import SessionRecorder
    feed, chains = make_sources(cfg, say)
    rec = SessionRecorder(Path(data_dir) if data_dir else cfg.runtime_dir / "intraday" / "data")
    stop = dt.time.fromisoformat(until) if until else CLOSE
    return SessionRecording(cfg, feed, chains, rec, say=say).run(stop)
