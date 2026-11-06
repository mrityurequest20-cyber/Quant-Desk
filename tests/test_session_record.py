"""The record-only session (quantdesk/data/session_record.py): it records the bars and chains the desk used to, where the
archive expects them, keeps going through source failures, never records a model chain, and imports nothing that
could trade."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from quantdesk.data import session_record as SR
from quantdesk.intraday.recorder import SessionRecorder

ROOT = Path(__file__).resolve().parents[1]
IST = "Asia/Kolkata"
DAY = dt.date(2026, 11, 3)


class Clock:
    def __init__(self, start):
        self.t = pd.Timestamp(dt.datetime.combine(DAY, start), tz=IST)

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += pd.Timedelta(seconds=s)


class Cfg(dict):
    runtime_dir = Path(".")

    def get(self, k, d=None):
        return super().get(k, d)


class Feed:
    name = "fake"

    def __init__(self, clock, fail=()):
        self.clock, self.fail, self.fut_bars = clock, set(fail), {}

    def _bar(self, ts, px=100.0):
        return pd.DataFrame({"open": [px], "high": [px], "low": [px], "close": [px], "volume": [1.0]}, index=pd.DatetimeIndex([ts]))

    def poll(self, sym, since):
        if sym in self.fail:
            raise RuntimeError("feed down")
        ts = self.clock.now().floor("min") - pd.Timedelta(minutes=1)
        if since is not None and ts <= since:
            return None
        if sym == "NIFTY":
            self.fut_bars[sym] = self._bar(ts, 101.0)
        return self._bar(ts)

    def history(self, sym, days):
        idx = pd.date_range(pd.Timestamp(dt.datetime.combine(DAY, dt.time(9, 15)), tz=IST), periods=3, freq="min")
        return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx)


class Chains:
    name = "fake-chain"

    def __init__(self, source="kotak", fail=()):
        self.source, self.fail, self.calls = source, set(fail), 0

    def expiries(self, u):
        return [DAY + dt.timedelta(days=7), DAY]

    def chain(self, u, expiry, spot=None, ts=None):
        self.calls += 1
        if u in self.fail:
            raise RuntimeError("chain down")
        ch = pd.DataFrame({"strike": [100.0], "kind": ["CE"], "bid": [1.0], "ask": [1.2], "ltp": [1.1], "oi": [10.0], "volume": [5.0]})
        ch.attrs.update({"underlying": u, "expiry": expiry, "ts": ts, "spot": spot, "source": self.source})
        return ch


def _run(tmp_path, start, until, feed_fail=(), chain_fail=(), source="kotak"):
    clock = Clock(start)
    cfg = Cfg({"intraday.underlyings": ["NIFTY", "BANKNIFTY"], "universe.volatility_index": "INDIAVIX"})
    rec = SessionRecorder(tmp_path / "data")
    s = SR.SessionRecording(cfg, Feed(clock, feed_fail), Chains(source, chain_fail), rec, say=lambda *a: None,
                            now=clock.now, sleep=clock.sleep)
    return s.run(until), tmp_path / "data" / str(DAY)


def test_it_records_bars_futures_and_a_chain_a_minute_where_the_archive_reads_them(tmp_path, monkeypatch):
    out, d = _run(tmp_path, dt.time(9, 10), dt.time(9, 25))
    assert out["recorded"] and out["chains"] > 0 and out["bars"] > 0
    assert {p.name for p in d.glob("*_1m.csv")} == {"NIFTY_1m.csv", "BANKNIFTY_1m.csv", "INDIAVIX_1m.csv", "NIFTY-FUT_1m.csv"}
    names = sorted(p.name for p in (d / "chains").glob("*.csv"))
    assert names[0].startswith(f"BANKNIFTY_{DAY}_09") and any(n.startswith(f"NIFTY_{DAY}_0915") for n in names)
    nifty = pd.read_csv(d / "NIFTY_1m.csv", index_col=0)
    assert len(nifty) >= 10                                  # one bar a minute from the open, plus the gap fill
    from quantdesk.data import archive as A
    assert A.day_dirs(tmp_path / "data") == [d]               # data archive-session finds the day


def test_it_waits_for_the_open_and_stops_at_until(tmp_path):
    out, d = _run(tmp_path, dt.time(8, 50), dt.time(9, 20))
    nifty = pd.read_csv(d / "NIFTY_1m.csv", index_col=0, parse_dates=True)
    assert nifty.index.min().time() >= dt.time(9, 14) and nifty.index.max().time() <= dt.time(9, 21)
    assert 5 <= out["minutes"] <= 8


def test_after_until_it_records_nothing(tmp_path):
    out, d = _run(tmp_path, dt.time(15, 40), dt.time(15, 30))
    assert out["recorded"] is False and not d.exists()


def test_a_failing_source_is_counted_and_the_others_carry_on(tmp_path):
    out, d = _run(tmp_path, dt.time(9, 15), dt.time(9, 25), feed_fail=("BANKNIFTY",), chain_fail=("NIFTY",))
    assert out["bar_errors"] > 0 and out["chain_errors"] > 0
    assert (d / "NIFTY_1m.csv").exists() and any(p.name.startswith("BANKNIFTY_") for p in (d / "chains").glob("*.csv"))
    assert not any(p.name.startswith("NIFTY_") for p in (d / "chains").glob("*.csv"))


def test_a_model_chain_is_never_recorded_as_market_data(tmp_path):
    out, d = _run(tmp_path, dt.time(9, 15), dt.time(9, 20), source="model")
    assert out["chains"] == 0 and not (d / "chains").exists()


def test_the_nearest_expiry_respects_the_minimum_days():
    c = Chains()
    assert SR.nearest_expiry(c, "NIFTY", DAY) == DAY
    assert SR.nearest_expiry(c, "NIFTY", DAY, min_days=1) == DAY + dt.timedelta(days=7)


def test_the_recorder_imports_nothing_that_trades():
    src = (ROOT / "quantdesk" / "data" / "session_record.py").read_text()
    for word in ("engine", "broker", "journal", "risk", "sleeves", "kite", "order"):
        assert not re.search(rf"^\s*(from|import)\b[^\n]*\b{word}", src, re.M | re.I), word
