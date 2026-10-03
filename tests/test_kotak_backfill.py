"""Kotak minute backfill (data/kotak_backfill.py): contract selection, chunked fallback, output, de-duplication."""
import datetime as dt
import json

import numpy as np
import pandas as pd

from quantdesk.data import kotak_backfill as B
from quantdesk.intraday.feeds import IST

TODAY = dt.date(2026, 10, 5)
EXPS = [dt.date(2026, 9, 29), dt.date(2026, 10, 6), dt.date(2026, 10, 13), dt.date(2026, 10, 27)]


class FakeKotak:
    def __init__(self, refuse_long=False, dead=()):
        self.refuse_long, self.dead, self.calls = refuse_long, set(dead), {"candles": 0}

    def expiries(self, u):
        return EXPS

    def option_chain(self, u, exp, count):
        legs = lambda r: [{"inst": {"strkPrc": str(22000 + 50 * i), "neoSymbol": f"nse_fo|{u}{exp:%m%d}{r}{i}"}}
                          for i in range(-2, 3)]
        return {"data": {"call": legs("C"), "put": legs("P")}}

    def _get(self, path, params):                      # KotakFutures.contracts
        return {"future_contracts": [{"inst": {"neoSymbol": "nse_fo|FUT1", "exp": "2026-10-27"}, "quote": {}, "oi": {}}]}

    def candles(self, token, interval, start, end):
        self.calls["candles"] += 1
        if token in self.dead:
            raise RuntimeError("no data for this instrument")
        if self.refuse_long and (end - start).days > B.CHUNK_DAYS:
            raise RuntimeError("date range too long")
        days = [d for d in pd.bdate_range(start, end)]
        idx = pd.DatetimeIndex([pd.Timestamp(f"{d.date()} 09:15", tz=IST) + pd.Timedelta(minutes=m) for d in days for m in range(3)])
        n = len(idx)
        return pd.DataFrame({"open": np.ones(n), "high": np.ones(n) * 2, "low": np.ones(n) * 0.5, "close": np.ones(n),
                             "volume": np.arange(n, dtype=float)}, index=idx)


def test_contracts_are_the_nearest_live_expiries_both_rights():
    cs = B.contracts(FakeKotak(), "NIFTY", 2, 20, TODAY)
    assert {c["expiry"] for c in cs} == {dt.date(2026, 10, 6), dt.date(2026, 10, 13)}       # 29 Sep has expired
    assert {c["right"] for c in cs} == {"CE", "PE"} and len(cs) == 2 * 2 * 5
    assert all("|" in c["token"] and c["strike"] > 0 for c in cs)


def test_a_refused_long_window_is_fetched_in_pieces():
    df, err = B.candles(FakeKotak(refuse_long=True), "nse_fo|X", TODAY - dt.timedelta(days=30), TODAY)
    assert err is None and len(df) > 0 and df.index.is_unique and df.index.is_monotonic_increasing
    assert df.index.min().date() <= TODAY - dt.timedelta(days=28)


def test_backfill_writes_options_index_futures_and_an_honest_manifest(tmp_path):
    k = FakeKotak(dead={"nse_fo|NIFTY1006C0"})
    man = B.backfill(k, tmp_path, ["NIFTY"], days=10, n_expiries=2, strikes=20, today=TODAY, say=lambda *a: None)
    rep = man["underlyings"]["NIFTY"]
    assert rep["asked"] == 20 and rep["served"] == 19 and rep["failed"] == 1
    assert man["evidence"] == "real_trade_minutes" and "not bid/ask" in man["note"]
    run = tmp_path / str(TODAY)
    opt = pd.read_parquet(run / "options_NIFTY.parquet")
    assert list(opt.columns) == B.COLS and opt["right"].isin(["CE", "PE"]).all()
    assert (run / "index.parquet").exists() and (run / "futures.parquet").exists()
    assert json.loads((run / "manifest.json").read_text())["underlyings"]["NIFTY"]["bars"] == len(opt)
    assert sorted(B.release_names(run)) == ["futures.parquet", "index.parquet", "manifest.json", "options_NIFTY.parquet"]


def test_overlapping_runs_deduplicate_on_load(tmp_path):
    k = FakeKotak()
    B.backfill(k, tmp_path, ["NIFTY"], days=10, n_expiries=1, strikes=20, today=TODAY, say=lambda *a: None)
    B.backfill(k, tmp_path, ["NIFTY"], days=10, n_expiries=1, strikes=20, today=TODAY + dt.timedelta(days=1), say=lambda *a: None)
    one = pd.read_parquet(tmp_path / str(TODAY) / "options_NIFTY.parquet")
    both = B.load(tmp_path, "options", "NIFTY")
    assert len(both) >= len(one) and not both.duplicated(["token", "ts"]).any()
