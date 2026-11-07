"""The index pipeline brought level with the stocks: the five-level order book beside every index chain, the nearest monthly expiry always recorded, both archived, both judged by Data health
(intraday/tape.py `monthly`, intraday/cli.py, data/archive.py, data/health.py `check_index_depth`, config intraday.tape)."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.data import archive as A
from quantdesk.data import health as H
from quantdesk.data import stock_chains as SC
from quantdesk.intraday import kotak as K
from quantdesk.intraday.chains import COLUMNS, DEPTH
from quantdesk.intraday.feeds import IST
from quantdesk.intraday.tape import ChainTape, monthly_expiry

ROOT = Path(__file__).resolve().parents[1]
DAY = dt.date(2026, 11, 9)
NIFTY = [dt.date(2026, 11, 10), dt.date(2026, 11, 17), dt.date(2026, 11, 24), dt.date(2026, 12, 1), dt.date(2026, 12, 29)]


def test_the_nearest_monthly_expiry_is_the_last_one_listed_in_its_month():
    assert monthly_expiry(NIFTY, DAY) == dt.date(2026, 11, 24)                                  # Nov's weeklies end with the 24th
    assert monthly_expiry(NIFTY, dt.date(2026, 11, 25)) == dt.date(2026, 12, 29)                # once the November series has gone, December's
    assert monthly_expiry([dt.date(2026, 11, 24)], DAY) == dt.date(2026, 11, 24) and monthly_expiry([], DAY) is None


class Clock:
    def __init__(self, start="2026-11-09 09:15:00"):
        self.t = pd.Timestamp(start, tz=IST)

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += pd.Timedelta(seconds=max(s, 30.0))


class Src:
    def __init__(self, clk, exps):
        self.clk, self.exps, self.calls = clk, exps, []

    def expiries(self, u):
        return self.exps

    def chain(self, u, e, spot=None, ts=None, **kw):
        self.calls.append((u, e))
        df = pd.DataFrame(np.ones((2, len(COLUMNS) + len(DEPTH))), index=[100.0, 105.0], columns=COLUMNS + DEPTH)
        df.index.name = "strike"
        df.attrs.update({"underlying": u, "spot": 102.0, "expiry": e, "ts": self.clk(), "source": "kotak", "quoted": 4,
                         "depth": [K.depth_row({"depth": {"buy": [{"price": "9", "quantity": "75"}], "sell": [{"price": "9.1", "quantity": "50"}]}}, k, s) for k in (100.0, 105.0) for s in ("ce", "pe")]})
        return df


def test_the_tape_adds_the_monthly_expiry_only_when_asked_and_keeps_the_nearest_ones(tmp_path):
    for monthly, want in ((False, NIFTY[:2]), (True, NIFTY[:2] + [NIFTY[2]])):
        clk = Clock()
        src = Src(clk, NIFTY)
        ChainTape(src, tmp_path / str(monthly), {"NIFTY": 2}, clock=clk, sleep=clk.sleep, say=lambda *a: None, monthly=monthly).run(dt.time(9, 16))
        assert sorted({e for _, e in src.calls}) == want
    clk = Clock()
    src = Src(clk, NIFTY[1:])                                                                   # the nearest 2 already include nothing monthly: still the 24th, and no duplicate when it is among them
    ChainTape(src, tmp_path / "x", {"NIFTY": 3}, clock=clk, sleep=clk.sleep, say=lambda *a: None, monthly=True).run(dt.time(9, 16))
    assert sorted({e for _, e in src.calls}) == [NIFTY[1], NIFTY[2], NIFTY[3]] and len([c for c in src.calls if c[1] == NIFTY[2]]) == len(src.calls) // 3


def test_the_index_tape_keeps_an_order_book_file_beside_each_chain_and_the_archive_publishes_it(tmp_path):
    clk = Clock()
    src = Src(clk, NIFTY)
    data = tmp_path / "data"
    ChainTape(src, data, {"NIFTY": 1, "BANKNIFTY": 1}, clock=clk, sleep=clk.sleep, say=lambda *a: None, extra=SC.depth_writer(data)).run(dt.time(9, 17))
    day = data / str(DAY)
    assert len(list((day / "depth").glob("*.csv"))) == len(list((day / "chains").glob("*.csv"))) > 0
    frames = A.compact_day(day, depth=True)
    assert set(frames) >= {"chains", "depth"} and {"b1p", "a1q", "side", "strike", "underlying"} <= set(frames["depth"].columns) and set(frames["depth"]["underlying"]) == {"NIFTY", "BANKNIFTY"}
    assert "depth" not in A.compact_day(day)                                                    # opt-in: the stock recorder compacts its books itself
    written = A.archive(data, "morning-1", tmp_path / "out", say=lambda *a: None)
    assert f"{DAY}_morning-1_depth.parquet" in written and f"{DAY}_morning-1_chains.parquet" in written


def test_the_shipped_config_turns_on_depth_and_the_monthly_expiry_for_all_five_indices():
    cfg = Config.load(DEFAULT_CONFIG)
    tc = cfg.get("intraday.tape")
    assert tc["depth_levels"] == 5 and tc["monthly"] is True and set(tc["expiries"]) == set(H.CHAIN_UNDERLYINGS)
    src = (ROOT / "quantdesk/intraday/cli.py").read_text(encoding="utf-8")
    assert "depth_levels=levels" in src and "monthly=bool(tc.get(\"monthly\"" in src and "extra=extra" in src


def _books(unds=H.CHAIN_UNDERLYINGS):
    return pd.DataFrame([{"ts": pd.Timestamp(f"{DAY} 09:15", tz=IST), "underlying": u, "expiry": pd.Timestamp(DAY), "strike": 100.0, "side": "ce", "b1p": 9.0} for u in unds])


class Store:
    def __init__(self, df=None):
        import io
        self.b = None
        if df is not None:
            buf = io.BytesIO()
            df.to_parquet(buf)
            self.b = buf.getvalue()

    def tags(self, t): return ["chains-2026"]
    def assets(self, t): return [f"{DAY}_morning-1_depth.parquet"] if self.b else []
    def read(self, t, n): return self.b


def test_data_health_says_whether_the_index_order_books_arrived_for_every_index():
    assert H.check_index_depth(Store(_books()), DAY).status == H.OK
    w = H.check_index_depth(Store(_books(("NIFTY", "BANKNIFTY"))), DAY)
    assert w.status == H.WARN and "SENSEX" in w.detail
    assert H.check_index_depth(Store(), DAY).status == H.MISSING
    assert "check_index_depth(store, day)" in (ROOT / "quantdesk/data/health.py").read_text(encoding="utf-8")


def test_the_session_recorder_workflow_still_starts_the_tape_exactly_as_before():
    rec = (ROOT / ".github/workflows/record.yml").read_text(encoding="utf-8")
    assert 'python -m quantdesk intraday tape --until "$HANDOVER" > tape.log 2>&1 &' in rec and "python -m quantdesk intraday tape > tape.log 2>&1 &" in rec     # the change is config and the tape's own code
    assert "depth" not in rec.replace("depth_levels", "")


def test_a_half_written_order_book_file_never_costs_the_days_chains_and_bars(tmp_path):
    clk = Clock()
    src = Src(clk, NIFTY)
    data = tmp_path / "data"
    ChainTape(src, data, {"NIFTY": 1}, clock=clk, sleep=clk.sleep, say=lambda *a: None, extra=SC.depth_writer(data)).run(dt.time(9, 17))
    day = data / str(DAY)
    books = sorted((day / "depth").glob("*.csv"))
    assert len(books) >= 2
    books[0].write_text("")                                                                       # a tape killed mid-write: an empty file
    books[1].write_text("strike,side\nnot,enough")                                                # and a garbled one
    (day / "NIFTY_1m.csv").write_text("ts,open,high,low,close,volume\n2026-11-09 09:15:00+05:30,1,2,0.5,1,10\n")
    written = A.archive(data, "morning-1", tmp_path / "out", say=lambda *a: None)
    assert f"{DAY}_morning-1_chains.parquet" in written and f"{DAY}_morning-1_bars.parquet" in written     # the chains and bars are archived whatever happened to the books
    assert f"{DAY}_morning-1_depth.parquet" in written                                                      # and the good books still are
    got = pd.read_parquet(tmp_path / "out" / f"{DAY}_morning-1_depth.parquet")
    assert len(got) > 0 and len(pd.read_parquet(tmp_path / "out" / f"{DAY}_morning-1_chains.parquet")) == sum(1 for _ in (day / "chains").glob("*.csv")) * 2


def test_the_book_writer_goes_through_a_temporary_name(tmp_path):
    clk = Clock()
    src = Src(clk, NIFTY)
    data = tmp_path / "data"
    ChainTape(src, data, {"NIFTY": 1}, clock=clk, sleep=clk.sleep, say=lambda *a: None, extra=SC.depth_writer(data)).run(dt.time(9, 16))
    assert not list((data / str(DAY) / "depth").glob(".*.tmp")) and list((data / str(DAY) / "depth").glob("*.csv"))
    assert "os.replace(tmp, out)" in (ROOT / "quantdesk/data/stock_chains.py").read_text(encoding="utf-8")


def test_the_tape_starts_without_books_if_the_book_writer_cannot_be_imported():
    src = (ROOT / "quantdesk/intraday/cli.py").read_text(encoding="utf-8")
    block = src[src.index("levels = max(0, min(5"):src.index("tape = ChainTape(")]
    assert "except Exception" in block and "levels = 0" in block
