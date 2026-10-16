"""Stock minutes (data/kotak_backfill.py `stock_minutes`): universe, tokens, throttle and budget, partial failures,
de-duplication, release naming, and the live.yml step."""
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from quantdesk.data import kotak_backfill as B
from quantdesk.intraday.feeds import IST
from quantdesk.intraday.kotak import KotakError

TODAY = dt.date(2026, 10, 5)
SYMS = ["AAA", "BBB", "CCC", "DDD"]


class Clock:
    """A fake clock: sleeping advances it, and so does every request (`latency`)."""

    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


class FakeKotak:
    def __init__(self, clock=None, latency=0.0, dead=(), empty=(), no_future=(), flaky=None):
        self.clock, self.latency = clock, latency
        self.dead, self.empty, self.no_future, self.flaky = set(dead), set(empty), set(no_future), dict(flaky or {})
        self.calls = {"candles": 0, "chain": 0}
        self.stamps = []

    def _tick(self):
        if self.clock:
            self.stamps.append(self.clock.t)
            self.clock.t += self.latency

    def _get(self, path, params):                              # KotakFutures.contracts: the chain endpoint, instrument_type=fut
        self._tick()
        self.calls["chain"] += 1
        u = params["underlying"]
        if u in self.no_future:
            return {"future_contracts": []}
        rows = [{"inst": {"neoSymbol": f"nse_fo|F{u}{m}", "exp": e}, "quote": {"ltp": "100.5"}, "oi": {"cur": "5000", "prev": "4800"}}
                for m, e in (("1", "2026-10-27"), ("2", "2026-11-24"))]
        return {"future_contracts": rows}

    def candles(self, token, interval, start, end, raw=False):
        self._tick()
        self.calls["candles"] += 1
        if self.flaky.get(token, 0) > 0:
            self.flaky[token] -= 1
            raise KotakError("historical: HTTP 429: too many requests")
        if token in self.dead:
            raise KotakError("historical: HTTP 200: no data for this instrument")
        if token in self.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        days = list(pd.bdate_range(start, end))
        idx = pd.DatetimeIndex([pd.Timestamp(f"{d.date()} 09:15", tz=IST) + pd.Timedelta(minutes=m) for d in days for m in range(3)])
        n = len(idx)
        return pd.DataFrame({"open": np.ones(n), "high": np.ones(n) * 2, "low": np.ones(n) * 0.5, "close": np.ones(n),
                             "volume": np.arange(n, dtype=float)}, index=idx)


@pytest.fixture(autouse=True)
def masters(monkeypatch):
    """The scrip masters: AAA..CCC have a token in the F&O master (pAssetCode), DDD only in the cash master."""
    fo = pd.DataFrame({"pSymbolName": ["AAA", "BBB", "CCC", "AAA"], "pInstType": ["FUTSTK"] * 3 + ["OPTSTK"],
                       "pAssetCode": [11, 22, 33, 11]})
    cm = pd.DataFrame({"pTrdSymbol": ["DDD-EQ", "AAA-EQ"], "pSymbol": [44, 11]})
    monkeypatch.setattr(B, "scrip_master", lambda client, name="nse_fo": fo if name == "nse_fo" else cm)


_RANKED = object()


def run(tmp_path, client, syms=SYMS, fo_stocks=_RANKED, **kw):
    kw.setdefault("n", len(syms))
    kw.setdefault("days", 3)
    kw.setdefault("today", TODAY)
    kw.setdefault("say", lambda *a: None)
    return B.stock_minutes(client, tmp_path, _ranked(syms) if fo_stocks is _RANKED else fo_stocks, **kw)


def _ranked(syms, d=TODAY - dt.timedelta(days=1)):
    n = len(syms)
    return pd.DataFrame({"date": [d] * n, "symbol": syms, "opt_premium": [(n - i) * 1e8 for i in range(n)],
                         "active_strikes": [20] * n, "opt_contracts": [1e5] * n, "fut_contracts": [1e4] * n,
                         "fut_oi": [1e5] * n, "atm_straddle": [0.03] * n, "lot": [100] * n, "underlying": [1000.0] * n,
                         "strike_step": [10.0] * n})


# ---- the universe --------------------------------------------------------------------------------------------------
def test_universe_is_ranked_on_the_warehouse_and_point_in_time():
    df = _ranked(["AAA", "BBB", "CCC"])
    # today's own row says ZZZ is the most liquid stock of all: using it would be look-ahead
    today_row = _ranked(["ZZZ"], d=TODAY).assign(opt_premium=9e12)
    syms, info = B.universe(pd.concat([df, today_row], ignore_index=True), TODAY, n=2)
    assert syms == ["AAA", "BBB"] and info["source"] == "ranked" and "ZZZ" not in syms
    assert info["ranked_through"] == str(TODAY - dt.timedelta(days=1)) and info["symbols"] == syms


def test_universe_falls_back_to_the_fixed_list_and_tops_up_a_short_table():
    for empty in (None, pd.DataFrame(), _ranked(["ZZZ"], d=TODAY)):            # nothing before today is no table
        syms, info = B.universe(empty, TODAY, n=50)
        assert info["source"] == "fallback" and syms == list(B.FALLBACK_UNIVERSE) and len(set(syms)) == 50
    syms, info = B.universe(_ranked(["AAA", "BBB"]), TODAY, n=5)
    assert syms[:2] == ["AAA", "BBB"] and len(syms) == 5 and info["source"] == "ranked+fallback"
    assert syms[2:] == list(B.FALLBACK_UNIVERSE[:3])


# ---- tokens --------------------------------------------------------------------------------------------------------
def test_cash_tokens_come_from_the_fo_master_then_the_cash_master_and_a_missing_one_is_recorded(tmp_path):
    k = FakeKotak()
    man = run(tmp_path, k, SYMS + ["EEE"], fo_stocks=_ranked(SYMS + ["EEE"]))
    s = man["stocks"]
    assert s["AAA"]["cash"]["status"] == "served" and s["DDD"]["cash"]["status"] == "served"
    cash = pd.read_parquet(Path(man["path"]) / "stocks_cash.parquet")
    assert dict(zip(cash["symbol"], cash["token"])) == {"AAA": "nse_cm|11", "BBB": "nse_cm|22", "CCC": "nse_cm|33", "DDD": "nse_cm|44"}
    assert s["EEE"]["cash"]["status"] == "failed" and s["EEE"]["cash"]["error"] == "no cash token in the scrip master"
    assert s["EEE"]["futures"]["status"] == "served"                        # the future does not need the cash token


# ---- output --------------------------------------------------------------------------------------------------------
def test_files_and_manifest(tmp_path):
    man = run(tmp_path, FakeKotak())
    r = Path(man["path"])
    cash, fut = pd.read_parquet(r / "stocks_cash.parquet"), pd.read_parquet(r / "stocks_futures.parquet")
    assert list(cash.columns) == ["ts", "symbol", "token", "open", "high", "low", "close", "volume"]
    assert list(fut.columns) == B.STOCK_COLS and set(fut["token"]) == {f"nse_fo|F{s}1" for s in SYMS}
    assert (fut["expiry"].astype(str) == "2026-10-27").all()               # the near month
    m = json.loads((r / "stocks_manifest.json").read_text())
    assert m["evidence"] == "real_trade_minutes" and m["universe"]["source"] == "ranked"
    assert m["totals"]["cash"] == {"asked": 4, "served": 4, "empty": 0, "failed": 0, "not_attempted": 0}
    assert m["totals"]["futures"]["served"] == 4 and m["stopped"] is None
    a = m["stocks"]["AAA"]
    assert a["cash"]["bars"] == len(cash[cash.symbol == "AAA"]) and 0 < a["cash"]["coverage"] <= 1
    assert a["future"]["oi"] == 5000 and a["future"]["oi_prev"] == 4800 and a["future"]["expiry"] == "2026-10-27"
    assert B.release_names(r, stocks=True) == ["stocks_cash.parquet", "stocks_futures.parquet", "stocks_manifest.json"]


def test_partial_failures_are_in_the_manifest_and_do_not_stop_the_run(tmp_path):
    k = FakeKotak(dead={"nse_cm|22"}, empty={"nse_fo|FCCC1"}, no_future={"DDD"})
    man = run(tmp_path, k)
    s, t = man["stocks"], man["totals"]
    assert s["BBB"]["cash"]["status"] == "failed" and "no data" in s["BBB"]["cash"]["error"]
    assert s["CCC"]["futures"]["status"] == "empty" and s["DDD"]["futures"]["status"] == "failed"
    assert "no futures" in s["DDD"]["futures"]["error"] or s["DDD"]["futures"]["error"]
    assert t["cash"] == {"asked": 4, "served": 3, "empty": 0, "failed": 1, "not_attempted": 0}
    assert t["futures"] == {"asked": 4, "served": 2, "empty": 1, "failed": 1, "not_attempted": 0}
    cash = pd.read_parquet(Path(man["path"]) / "stocks_cash.parquet")
    assert set(cash["symbol"]) == {"AAA", "CCC", "DDD"}                     # what was served is kept


def test_a_transient_error_is_retried_with_backoff_a_permanent_one_is_not(tmp_path):
    clock = Clock()
    k = FakeKotak(clock, flaky={"nse_cm|11": 2}, dead={"nse_cm|22"})
    man = run(tmp_path, k, sleep=clock.sleep, clock=clock.now)
    assert man["stocks"]["AAA"]["cash"]["status"] == "served" and man["retried"] == 2
    assert [s for s in clock.sleeps if s in (1.0, 2.0)] == [1.0, 2.0]       # exponential backoff
    assert man["stocks"]["BBB"]["cash"]["status"] == "failed"
    # the dead token was asked for once (+ once more in the chunked fallback), not retried three times
    assert k.calls["candles"] <= 2 + 3 + 3 + 2 + 2 + 2 + 2


# ---- throttle and budget -------------------------------------------------------------------------------------------
def test_requests_are_spaced_at_the_configured_rate(tmp_path):
    clock = Clock()
    k = FakeKotak(clock, latency=0.01)
    run(tmp_path, k, sleep=clock.sleep, clock=clock.now, rate=5.0, budget_s=10_000)
    gaps = np.diff(k.stamps)
    assert len(gaps) > 10 and gaps.min() >= 0.2 - 1e-9                     # never more than 5 a second


def test_time_budget_stops_cleanly_and_records_what_is_missing(tmp_path):
    clock = Clock()
    k = FakeKotak(clock, latency=0.05)
    man = run(tmp_path, k, sleep=clock.sleep, clock=clock.now, rate=5.0, budget_s=1.5)
    assert man["stopped"] and "time budget" in man["stopped"]
    t = man["totals"]
    assert t["cash"]["not_attempted"] >= 1 and t["cash"]["served"] >= 1      # some done, the rest listed
    assert t["cash"]["served"] + t["cash"]["not_attempted"] + t["cash"]["failed"] + t["cash"]["empty"] == 4
    assert t["cash"]["failed"] == 0 and t["futures"]["failed"] == 0         # running out of time is not a Kotak failure
    left = [s for s, r in man["stocks"].items() if r["cash"]["status"] == "not_attempted"]
    assert all(s in man["stopped"] for s in left)
    r = Path(man["path"])
    assert (r / "stocks_manifest.json").exists() and (r / "stocks_cash.parquet").exists()      # finished symbols are kept
    assert k.calls["candles"] + k.calls["chain"] <= int(1.5 * 5) + 3        # and it really stopped asking


def test_a_dead_scrip_master_is_recorded_not_raised(tmp_path, monkeypatch):
    def boom(client, name="nse_fo"):
        raise KotakError("scrip master: HTTP 500")
    monkeypatch.setattr(B, "scrip_master", boom)
    man = run(tmp_path, FakeKotak())
    assert "scrip master" in man["tokens_error"]
    assert man["totals"]["cash"]["failed"] == 4 and man["totals"]["futures"]["served"] == 4


# ---- load and release naming ---------------------------------------------------------------------------------------
def test_overlapping_runs_deduplicate_on_load(tmp_path):
    for d in (TODAY, TODAY + dt.timedelta(days=1)):
        B.stock_minutes(FakeKotak(), tmp_path, _ranked(SYMS, d - dt.timedelta(days=1)), n=4, days=3, today=d, say=lambda *a: None)
    one = pd.read_parquet(tmp_path / str(TODAY) / "stocks_cash.parquet")
    both = B.load(tmp_path, kind="stocks_cash")
    assert len(both) > len(one) and not both.duplicated(["token", "ts"]).any()
    assert list(both.columns) == ["ts", "symbol", "token", "open", "high", "low", "close", "volume"]
    assert not B.load(tmp_path, kind="stocks_futures").duplicated(["token", "ts"]).any()
    assert list(B.load(tmp_path / "nothing", kind="stocks_cash").columns) == B.STOCK_COLS


def test_release_naming_and_the_two_kinds_of_files_stay_apart(tmp_path):
    assert B.release_tag("stock-minutes", "2026-10-05") == "stock-minutes-2026"
    assert B.release_tag("option-minutes", "2027-01-02") == "option-minutes-2027"
    run_dir = tmp_path / "2026-10-05"
    run_dir.mkdir()
    for n in ("options_NIFTY.parquet", "index.parquet", "manifest.json", "stocks_cash.parquet", "stocks_manifest.json", "x.txt"):
        (run_dir / n).write_text("x")
    assert B.release_names(run_dir) == ["index.parquet", "manifest.json", "options_NIFTY.parquet"]
    assert B.release_names(run_dir, stocks=True) == ["stocks_cash.parquet", "stocks_manifest.json"]


# ---- live.yml ------------------------------------------------------------------------------------------------------
def test_live_yml_stock_step_is_always_warn_only_and_adds_no_secret_or_permission():
    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    text = (root / "live.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    steps = wf["jobs"]["afternoon"]["steps"]
    i = next(i for i, s in enumerate(steps) if "stock-minutes" in s.get("run", ""))
    j = next(i for i, s in enumerate(steps) if "option-minutes" in s.get("run", ""))
    step = steps[i]
    assert i == j + 1                                                       # right after the option-minutes step
    assert step["if"] == "always()" and 0 < step["timeout-minutes"] <= 30
    assert '|| echo "::warning::' in step["run"] and "--live" not in step["run"]
    assert step["env"] == steps[j]["env"] == {"GH_TOKEN": "${{ github.token }}"}          # no secret, same as its neighbour
    assert set(step) <= {"name", "if", "timeout-minutes", "env", "run"} and "secrets." not in json.dumps(step)
    assert "permissions" not in wf["jobs"]["afternoon"] and wf["permissions"] == {"contents": "write"}
    assert "KOTAK_CONSUMER_KEY" in wf["env"]                                # the key is the workflow's own, already there
    manual = yaml.safe_load((root / "kotak-backfill.yml").read_text(encoding="utf-8"))
    assert manual[True]["workflow_dispatch"]["inputs"]["stocks"]["default"] == "50"
    assert manual["permissions"] == {"contents": "write"}
