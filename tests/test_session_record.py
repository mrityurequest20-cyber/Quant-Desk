"""The record-only session (quantdesk/data/session_record.py): it records the bars and chains the desk used to, where the
archive expects them, keeps going through source failures, never records a model chain, and imports nothing that
could trade."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pandas as pd

from quantdesk.config import DEFAULT_CONFIG, Config
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


def test_a_set_kotak_key_that_fails_is_a_warning_not_a_quiet_fallback(monkeypatch):
    msgs = []
    monkeypatch.setenv("KOTAK_CONSUMER_KEY", "set-but-refused")
    monkeypatch.setattr(SR, "kotak_client", lambda: None)
    feed, chains = SR.make_sources(Cfg({}), say=msgs.append)
    assert msgs and msgs[0].startswith("::warning::") and "Kotak" in msgs[0]
    monkeypatch.delenv("KOTAK_CONSUMER_KEY")
    msgs.clear()
    SR.make_sources(Cfg({}), say=msgs.append)
    assert msgs and not msgs[0].startswith("::warning::")


def test_the_recorder_workflow_keeps_no_git_credential_and_holds_only_the_kotak_secret():
    import yaml
    text = (ROOT / ".github" / "workflows" / "record.yml").read_text()
    wf = yaml.load(text, Loader=yaml.BaseLoader)
    assert wf["permissions"] == {"contents": "write"}
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"KOTAK_CONSUMER_KEY"} and "KITE" not in text
    for job in ("morning", "afternoon"):
        assert wf["jobs"][job]["steps"][0]["with"]["persist-credentials"] == "false"


def test_an_nse_holiday_records_nothing_even_though_the_cron_starts_the_job(tmp_path):
    class HolCfg(Cfg):
        def holidays(self):
            return {DAY}
    clock = Clock(dt.time(9, 10))
    cfg = HolCfg({"intraday.underlyings": ["NIFTY", "BANKNIFTY"], "universe.volatility_index": "INDIAVIX"})
    said = []
    s = SR.SessionRecording(cfg, Feed(clock, ()), Chains("kotak", ()), SessionRecorder(tmp_path / "data"), say=said.append, now=clock.now, sleep=clock.sleep)
    out = s.run(dt.time(9, 25))
    assert out["recorded"] is False and not (tmp_path / "data" / str(DAY)).exists() and any("NSE holiday" in m for m in said)
    real = Config.load(DEFAULT_CONFIG)
    assert dt.date(2026, 11, 10) in real.holidays() and dt.date(2026, 11, 24) in real.holidays() and dt.date(2026, 11, 9) not in real.holidays()      # the real calendar: Mon 9 Nov trades, Tue 10 Nov does not


def _step_script(job: str, name_start: str) -> str:
    import yaml
    wf = yaml.safe_load((Path(__file__).resolve().parents[1] / ".github/workflows/record.yml").read_text(encoding="utf-8"))
    return next(s["run"] for s in wf["jobs"][job]["steps"] if s.get("name", "").startswith(name_start))


def _run_step(tmp_path, script: str, tape_exits_first: bool, rc: int) -> int:
    """The workflow's own step script, run with `bash -e` (as Actions does) against stub processes: the chain tape either ends by itself first or is still running, and the recorder ends with `rc`."""
    import os
    import stat
    import subprocess
    bin_ = tmp_path / "bin"
    bin_.mkdir(parents=True)
    stub = bin_ / "python"
    stub.write_text("#!/bin/bash\nif [[ \"$*\" == *' tape'* ]]; then\n  " + ("exit 0" if tape_exits_first else "sleep 30") + "\nfi\nsleep 1\nexit " + str(rc) + "\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "HANDOVER": "12:20"}
    return subprocess.run(["bash", "-e", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60).returncode


def test_the_recorder_step_does_not_fail_just_because_the_chain_tape_ended_before_it_and_still_reports_a_real_failure(tmp_path):
    for job, name in (("morning", "Record to the hand-over"), ("afternoon", "Record to the close")):
        script = _step_script(job, name)
        assert _run_step(tmp_path / f"a{job}", script, tape_exits_first=True, rc=0) == 0       # the first real run (a weekend smoke test) found this red: `kill` of a finished tape failed the step under bash -e
        assert _run_step(tmp_path / f"b{job}", script, tape_exits_first=False, rc=0) == 0      # and the tape still running is stopped, as before
        assert _run_step(tmp_path / f"c{job}", script, tape_exits_first=True, rc=3) == 3       # a recorder that really failed still fails the step, with its own code
