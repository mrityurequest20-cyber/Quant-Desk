"""The chain tape: real chains every minute for several expiries, beside the engine (intraday/tape.py)."""
import datetime as dt

import numpy as np
import pandas as pd

from quantdesk.intraday.chains import COLUMNS, load_chain
from quantdesk.intraday.feeds import IST
from quantdesk.intraday.recorder import SessionRecorder
from quantdesk.intraday.tape import ChainTape, completeness, render, targets

DAY = dt.date(2026, 10, 5)
EXPS = {"NIFTY": [dt.date(2026, 10, 6), dt.date(2026, 10, 13), dt.date(2026, 10, 19), dt.date(2026, 10, 27)],
        "BANKNIFTY": [dt.date(2026, 10, 27), dt.date(2026, 11, 23)]}


def t(hhmm):
    return pd.Timestamp(f"{DAY} {hhmm}", tz=IST)


class FakeKotak:
    def __init__(self, clock, broken=()):
        self.clock, self.broken, self.calls = clock, set(broken), []

    def expiries(self, u):
        return EXPS[u]

    def chain(self, u, e, spot=None, ts=None):
        self.calls.append((u, e, self.clock()))
        if (u, e) in self.broken:
            raise RuntimeError("no bid/ask in Kotak's quotes")
        df = pd.DataFrame(np.ones((3, len(COLUMNS))), index=[22300.0, 22400.0, 22500.0], columns=COLUMNS)
        df.index.name = "strike"
        df.attrs.update({"underlying": u, "spot": 22410.0, "expiry": e, "ts": self.clock(), "source": "kotak", "quoted": 6})
        return df


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += pd.Timedelta(seconds=s)


def test_targets_are_the_nearest_live_expiries():
    assert targets(EXPS["NIFTY"], 3, DAY) == EXPS["NIFTY"][:3]
    assert targets(EXPS["NIFTY"], 3, dt.date(2026, 10, 7)) == EXPS["NIFTY"][1:4]     # a passed expiry drops out
    assert targets(EXPS["BANKNIFTY"], 2, DAY) == EXPS["BANKNIFTY"]


def test_records_every_target_every_minute_with_a_log(tmp_path):
    c = Clock(t("09:10"))
    src = FakeKotak(c)
    tape = ChainTape(src, tmp_path, {"NIFTY": 3, "BANKNIFTY": 2}, clock=c, sleep=c.sleep, say=lambda *a: None)
    rep = tape.run(dt.time(9, 25))
    assert all(ts >= t("09:15") for *_, ts in src.calls)                           # nothing before the open
    files = sorted((tmp_path / str(DAY) / "chains").glob("*.csv"))
    assert len(files) == 5 * 10                                                    # 5 series × 09:15 … 09:24
    ch = load_chain(files[0])
    assert ch.attrs["source"] == "kotak" and ch.attrs["underlying"] in ("BANKNIFTY", "NIFTY")
    assert rep["minutes_in_span"] == 10
    assert all(v["minutes"] == 10 and v["coverage"] == 1.0 for v in rep["series"].values())
    assert rep["attempts"] == 50 and rep["failures"] == 0
    assert "NIFTY 2026-10-06: 10 minutes (100%)" in render(rep)
    assert not list((tmp_path / str(DAY) / "chains").glob(".*"))                   # no temporary files left behind


def test_a_failing_series_backs_off_and_the_others_carry_on(tmp_path):
    c = Clock(t("09:15"))
    bad = ("NIFTY", dt.date(2026, 10, 19))
    src = FakeKotak(c, broken=[bad])
    tape = ChainTape(src, tmp_path, {"NIFTY": 3}, clock=c, sleep=c.sleep, say=lambda *a: None)
    rep = tape.run(dt.time(9, 45))
    tries = [ts for u, e, ts in src.calls if (u, e) == bad]
    assert 4 <= len(tries) < 30                                                    # 1, 1, 2, 4, 5, 5 … minutes apart
    assert max(np.diff([x.value for x in tries])) <= 5 * 60e9 + 10e9
    assert rep["series"]["NIFTY 2026-10-06"]["minutes"] == 30
    assert "NIFTY 2026-10-19" not in rep["series"]
    assert rep["failures"] == len(tries) and "no bid/ask" in next(iter(rep["top_errors"]))


def test_engine_recordings_count_and_writes_are_atomic(tmp_path):
    rec = SessionRecorder(tmp_path)
    c = Clock(t("10:00"))
    ch = FakeKotak(c).chain("NIFTY", dt.date(2026, 10, 6))
    rec.record_chain(ch)
    rep = completeness(tmp_path / str(DAY), t("10:00"), t("10:02"))
    assert rep["series"]["NIFTY 2026-10-06"] == {"minutes": 1, "coverage": 0.5}
    assert not list((tmp_path / str(DAY) / "chains").glob(".*"))


def test_the_tape_archives_with_the_session(tmp_path):
    from quantdesk.data.archive import compact_day
    c = Clock(t("09:15"))
    ChainTape(FakeKotak(c), tmp_path, {"NIFTY": 2}, clock=c, sleep=c.sleep, say=lambda *a: None).run(dt.time(9, 18))
    frames = compact_day(tmp_path / str(DAY))
    assert set(frames) >= {"chains", "tape"}
    assert frames["chains"]["expiry"].nunique() == 2 and frames["chains"]["ts"].nunique() == 3
    assert len(frames["tape"]) == 6
