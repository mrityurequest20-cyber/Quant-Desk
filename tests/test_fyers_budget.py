"""The Fyers feed's day budget (quantdesk/data/fyers_feed.py; docs/FEEDS.md): Fyers' data APIs allow Standard 5 calls a second, 50 a minute and 5,000 a day (Prime 10, 500,
5,00,000) from 16 Oct 2026, and a user who breaks the minute cap more than three times in a day is blocked for the rest of it.

What is pinned: the plans' caps sit under Fyers' own; an unknown plan is Standard; a whole day, split into the workflow's three back-to-back jobs and with a job re-run, stays
under the daily cap and under the minute cap at every moment, and still has quotes in the last hour; on Prime the 5 s floor sets the pace as before; a short budget is shared
between the option chains and the books; a -429 in the answer's body stops the feed like an HTTP 429; the CLI passes the configured plan."""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from itertools import pairwise
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.data import fyers_feed as F
from tests.test_fyers import NAMES, PRICES, FakeAPI, FakePusher

IST = F.IST
ROOT = Path(__file__).resolve().parents[1]
FYERS = {"standard": (5, 50, 5000), "prime": (10, 500, 500000)}                     # Fyers' published data-API caps: a second, a minute, a day
DAY = dt.date(2026, 11, 16)


class Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += dt.timedelta(seconds=max(float(s), 0.5))                         # each round costs at least a little time, as on a real runner


class TimedAPI(FakeAPI):
    def __init__(self, prices, clock):
        super().__init__(prices)
        self.clock, self.at = clock, []

    def get(self, path, params):
        self.at.append((self.clock.now(), path))
        return super().get(path, params)


def _day(monkeypatch, plan, jobs):
    """Run the feed through `jobs` [(start HH:MM, until HH:MM)] of one day on one fake clock; the calls of all of them, with their times."""
    clock = Clock(dt.datetime.combine(DAY, dt.time(8, 59), IST))
    api = TimedAPI(dict(PRICES), clock)
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: NAMES)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    reps = []
    for start, until in jobs:
        h, m = (int(x) for x in start.split(":"))
        clock.t = max(clock.t, dt.datetime.combine(DAY, dt.time(h, m), IST))
        reps.append(F.run(until, "A-100", "t", FakePusher(), watchlist={"commodities": ["CRUDEOIL"], "currencies": ["USDINR"]}, now=clock.now, sleep=clock.sleep,
                          plan=plan))
    return api, reps


def test_the_plans_sit_under_fyers_published_caps_and_an_unknown_plan_is_standard():
    for name, (ps, pm, pd) in FYERS.items():
        c = F.PLANS[name]
        assert c["per_second"] < ps and c["per_minute"] <= 0.8 * pm and c["per_day"] <= 0.9 * pd
    assert F.plan_caps("PRIME")[0] == "prime" and F.plan_caps("gold")[0] == "standard" and F.plan_caps(None)[0] == "standard"
    assert (F.PER_SECOND, F.PER_MINUTE) == (F.PLANS["standard"]["per_second"], F.PLANS["standard"]["per_minute"])
    assert F.FyersData("A-100", "t").limiter.pm == F.PLANS["standard"]["per_minute"]
    assert F.FyersData("A-100", "t", plan="prime").limiter.pm == F.PLANS["prime"]["per_minute"]


def test_the_budget_starts_empty_fills_only_in_the_trading_window_and_holds_a_burst_at_most():
    clock = Clock(dt.datetime.combine(DAY, dt.time(7, 0), IST))
    b = F.DayBudget(5000, 1.0, clock.now, burst=8)
    assert not b.take(1)                                                               # a job starts with nothing: earlier jobs are taken to have spent their share
    clock.t = dt.datetime.combine(DAY, dt.time(8, 58), IST)
    assert not b.take(1)                                                               # nothing accrues before the first open
    clock.t = dt.datetime.combine(DAY, dt.time(12, 0), IST)
    assert b.take(8) and not b.take(1)                                                 # three hours accrue, but the bucket holds eight
    assert b.wait_s(9) == float("inf") and 0 < b.wait_s(1) <= 15


def test_a_whole_standard_day_in_three_jobs_and_a_rerun_stays_under_the_day_and_minute_caps(monkeypatch):
    jobs = [("08:59", "14:15"), ("14:15", "17:00"), ("17:00", "20:05"), ("20:05", "23:58")]    # the second job failed at 17:00 and was re-run
    api, reps = _day(monkeypatch, "standard", jobs)
    times = [t for t, _ in api.at]
    assert len(times) <= F.PLANS["standard"]["per_day"] < 5000
    per_min = Counter(t.replace(second=0, microsecond=0) for t in times)
    assert max(per_min.values()) <= F.PLANS["standard"]["per_minute"]
    assert any(t.time() >= dt.time(23, 0) for t in times)                             # the budget lasts the day: quotes in the last hour
    quotes = [t for t, p in api.at if p == "/quotes"]
    gaps = sorted((b - a).total_seconds() for a, b in pairwise(quotes) if a.date() == b.date() and (b - a).total_seconds() < 3600)
    assert 15 <= gaps[len(gaps) // 2] <= 24 and gaps[int(0.99 * len(gaps))] < 30     # a quote round about every 20 s, inside the paper desk's 30 s quote age for a fill
    assert sum(r.get("quote_skips", 0) for r in reps) == 0                             # the budget sets the pace: no quote batch is ever skipped for want of budget
    assert all(r["plan"] == "standard" and r["per_day"] == 4500 for r in reps)
    assert sum(r["budget_spent"]["quotes"] + r["budget_spent"]["extras"] for r in reps) == len(times)


def test_a_short_budget_is_shared_three_option_chains_to_one_book(monkeypatch):
    api, _ = _day(monkeypatch, "standard", [("08:59", "23:58")])
    n = Counter(p for _, p in api.at)
    assert n["/depth"] > 100                                                           # the books are not starved
    assert 2.7 <= n["/options-chain-v3"] / n["/depth"] <= 3.3
    extras = n["/options-chain-v3"] + n["/depth"]
    assert abs(extras / sum(n.values()) - F.EXTRAS_SHARE) <= 0.03                     # the extras' share of the day, the quotes the rest


COM = ["CRUDEOIL", "CRUDEOILM", "NATURALGAS", "NATGASMINI", "GOLD", "GOLDM", "SILVER", "SILVERM", "COPPER"]
CUR = ["USDINR", "EURINR", "GBPINR", "JPYINR"]


def test_on_standard_every_watchlist_chain_comes_round_within_the_paper_desks_600_s_mark_age(monkeypatch):
    """Risk review, 15 Nov 2026: at a quarter of the budget shared one to one with the books, a chain came round every 14 to 27 minutes, past the runner's 600 s mark age
    (MARK_MAX_AGE_S) and the 12-minute chain staleness. The desk's real watchlist (9 commodities, 4 currencies) and 32 contracts, a whole day in three jobs."""
    from quantdesk.paper import runner as RN
    names = {f"{c}-MCX": {"seg": "mcx", "ticker": f"MCX:{c}26NOVFUT", "expiry": dt.date(2026, 11, 19)} for c in COM + [f"X{i}" for i in range(15)]}
    names.update({f"{c}-CDS": {"seg": "cds", "ticker": f"NSE:{c}26NOVFUT", "expiry": dt.date(2026, 11, 26)} for c in CUR + ["CHFINR", "AUDINR", "CADINR", "SGDINR"]})
    cfg = Config.load(ROOT / "config" / "quantdesk.yaml")
    assert [n for n in COM + CUR] == [str(x).upper() for x in cfg.get("desk.watchlist.commodities") + cfg.get("desk.watchlist.currencies")]
    clock = Clock(dt.datetime.combine(DAY, dt.time(8, 59), IST))
    api = TimedAPI({c["ticker"]: (100.0, 99.9, 100.1) for c in names.values()}, clock)
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: names)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    for start, until in [("08:59", "14:15"), ("14:15", "20:05"), ("20:05", "23:58")]:
        h, m = (int(x) for x in start.split(":"))
        clock.t = max(clock.t, dt.datetime.combine(DAY, dt.time(h, m), IST))
        F.run(until, "A-100", "t", FakePusher(), watchlist={"commodities": COM, "currencies": CUR}, now=clock.now, sleep=clock.sleep, plan="standard")
    seen: dict[str, list] = {}
    for (t, path), (_, params) in zip(api.at, api.calls):
        if path == "/options-chain-v3":
            seen.setdefault(params["symbol"], []).append(t)
    assert len(seen) == len(COM + CUR)
    for lo, hi in ((dt.time(9, 30), dt.time(17, 5)), (dt.time(17, 30), dt.time(23, 58))):       # by day (13 names) and in the evening (MCX's 9)
        gaps = [(b - a).total_seconds() for ts in seen.values() for a, b in pairwise([x for x in ts if lo <= x.time() <= hi])]
        assert gaps and max(gaps) < RN.MARK_MAX_AGE_S == 600


def test_more_than_fifty_contracts_on_standard_is_reported(monkeypatch):
    names = {f"X{i}-MCX": {"seg": "mcx", "ticker": f"MCX:X{i}26NOVFUT", "expiry": dt.date(2026, 11, 19)} for i in range(60)}
    clock = Clock(dt.datetime.combine(DAY, dt.time(10, 0), IST))
    api = TimedAPI({c["ticker"]: (1.0, 0.9, 1.1) for c in names.values()}, clock)
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: names)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    rep = F.run("10:05", "A-100", "t", FakePusher(), now=clock.now, sleep=clock.sleep, plan="standard")
    assert any("60 contracts need 2 quote calls a round" in n for n in rep["notes"])
    assert not any("quote calls a round" in n for n in F.run("10:10", "A-100", "t", FakePusher(), now=clock.now, sleep=clock.sleep, plan="prime")["notes"])


def test_on_prime_the_five_second_floor_sets_the_pace_and_chains_and_books_run_each_round(monkeypatch):
    api, reps = _day(monkeypatch, "prime", [("10:00", "10:10")])
    quotes = [t for t, p in api.at if p == "/quotes"]
    gaps = [(b - a).total_seconds() for a, b in pairwise(quotes)]
    assert gaps and max(gaps[3:]) <= 6                                                 # after the first seconds' fill, a round every 5 s as before
    assert reps[0]["budget_skips"] <= 3
    n = Counter(p for _, p in api.at)
    assert n["/options-chain-v3"] >= 0.8 * len(quotes) and n["/depth"] >= 0.8 * len(quotes)


def test_fyers_rate_limit_code_in_the_answer_body_stops_the_feed_like_an_http_429():
    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return self.body

    api = F.FyersData("A-100", "t", opener=lambda req, timeout=None: Resp(json.dumps({"s": "error", "code": -429, "message": "request limit reached"}).encode()),
                      limiter=F.Limiter(clock=lambda: 0.0, sleep=lambda s: None))
    with pytest.raises(F.Blocked):
        api.get("/quotes", {"symbols": "MCX:A"})
    text = F.FyersData("A-100", "t", opener=lambda req, timeout=None: Resp(b'{"s": "error", "code": "-429"}'), limiter=api.limiter)
    with pytest.raises(F.Blocked):
        text.get("/quotes", {"symbols": "MCX:A"})                                       # the code as text too


def test_fyers_rate_limit_code_in_an_http_error_body_stops_the_feed_too():
    import io
    import urllib.error

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "x", {}, io.BytesIO(json.dumps({"s": "error", "code": -429}).encode()))
    api = F.FyersData("A-100", "t", opener=opener, limiter=F.Limiter(clock=lambda: 0.0, sleep=lambda s: None))
    with pytest.raises(F.Blocked):
        api.get("/quotes", {"symbols": "MCX:A"})

    def other(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "x", {}, io.BytesIO(b"not json"))
    with pytest.raises(urllib.error.HTTPError):                                        # any other error is just an error (one cycle lost, the feed goes on)
        F.FyersData("A-100", "t", opener=other, limiter=api.limiter).get("/quotes", {"symbols": "MCX:A"})


def test_the_desk_says_standard_and_the_cli_passes_the_configured_plan(monkeypatch, tmp_path):
    cfg = Config.load(ROOT / "config" / "quantdesk.yaml")
    assert cfg.get("feeds.fyers_plan") == "standard"
    from quantdesk.data import cli as C
    seen = {}
    monkeypatch.setattr(F, "run", lambda *a, **k: seen.update(k) or {"stopped": "until"})
    for k, v in {"FYERS_APP_ID": "A-100", "FYERS_DATA_TOKEN": "t", "LIVE_URL": "https://x.example", "LIVE_INGEST_TOKEN": "i" * 30}.items():
        monkeypatch.setenv(k, v)

    class Args:
        until, metrics, check = "23:58", None, False
    C.cmd_fyers_feed(cfg, Args())
    assert seen.get("plan") == "standard"
