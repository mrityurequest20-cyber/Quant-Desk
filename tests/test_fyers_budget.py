"""The Fyers feed's day budget (quantdesk/data/fyers_feed.py; docs/FEEDS.md): Fyers' data APIs allow Standard 5 calls a second, 50 a minute and 5,000 a day (Prime 10, 500,
5,00,000) from 16 Oct 2026, and a user who breaks the minute cap more than three times in a day is blocked for the rest of it.

What is pinned: the plans' caps sit under Fyers' own; an unknown plan is Standard; a whole day, split into the workflow's three back-to-back jobs and with a job re-run, stays
under the daily cap and under the minute cap at every moment, and still has quotes in the last hour; on Prime the 5 s floor sets the pace as before; a short budget is shared
between the option chains and the books; a -429 in the answer's body stops the feed like an HTTP 429; the CLI passes the configured plan."""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
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
    gaps = sorted((b - a).total_seconds() for a, b in zip(quotes, quotes[1:]) if a.date() == b.date() and (b - a).total_seconds() < 3600)
    assert 12 <= gaps[len(gaps) // 2] <= 20                                            # a quote round about every 16 s
    assert all(r["plan"] == "standard" and r["per_day"] == 4500 for r in reps)
    assert sum(r["budget_spent"]["quotes"] + r["budget_spent"]["extras"] for r in reps) == len(times)


def test_a_short_budget_is_shared_between_the_option_chains_and_the_books(monkeypatch):
    api, _ = _day(monkeypatch, "standard", [("08:59", "23:58")])
    n = Counter(p for _, p in api.at)
    assert n["/options-chain-v3"] > 100 and n["/depth"] > 100                         # neither starves the other
    assert abs(n["/options-chain-v3"] - n["/depth"]) <= 0.1 * (n["/options-chain-v3"] + n["/depth"])
    assert n["/quotes"] >= 2.5 * (n["/options-chain-v3"] + n["/depth"])                # three quarters of the day for the quotes


def test_on_prime_the_five_second_floor_sets_the_pace_and_chains_and_books_run_each_round(monkeypatch):
    api, reps = _day(monkeypatch, "prime", [("10:00", "10:10")])
    quotes = [t for t, p in api.at if p == "/quotes"]
    gaps = [(b - a).total_seconds() for a, b in zip(quotes, quotes[1:])]
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
