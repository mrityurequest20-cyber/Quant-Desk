"""Audit K-07 (FH-02, HIGH) and K-36 (FH-06, MEDIUM): a part's stop was an IST clock time only, so a part that started early (the one before it ended early) was
killed by its job's 355-minute limit with no last save, and its run ended "cancelled", which the scheduler reads as the owner's stop; and a part that started
after midnight (a run queued behind the day's) ran to its stop time on the wrong day. Now each part stops and saves by its own job's deadline, the day's last
part ends red when that leaves the rest of the day unwatched, a part never runs on past midnight, and a part started before the desk's day does nothing.
PAPER MONEY ONLY."""
from __future__ import annotations

import datetime as dt
import re

import yaml

from quantdesk.paper import runner as R
from quantdesk.paperlink import session as S
from tests.test_paper_session import IST, NAME, Clock, FakeRelay, cfg  # noqa: F401 - cfg is a fixture
from tests.test_paper_workflow import RAW, ROOT

WF = yaml.safe_load(RAW)
PARTS = ("morning", "afternoon", "evening", "night")


def go(cfg, rl, clk, tmp_path, until, lines, **kw):
    return S.run(cfg, rl, tmp_path / "ledger" / "account.json", until, every_s=3.0, clock=clk, sleep=clk.sleep, say=lines.append, new_account=True, **kw)


def paced(monkeypatch, clk):
    t0 = clk.t
    monkeypatch.setattr(S.time, "monotonic", lambda: (clk.t - t0).total_seconds())


def test_a_part_started_three_hours_early_stops_by_its_deadline_saves_and_hands_over(cfg, tmp_path, monkeypatch):
    """The audit's worked case: the morning part ended at 09:00, so the afternoon part (--until 17:40) started at 09:01. It was killed at about 14:56 with no last
    save. Now it stops at its deadline (job start + 345 minutes), with the fill it made saved on the relay, and exits 0: the evening part takes over. (Started
    here at 09:20, after the open, so the queued order fills.)"""
    clk, lines = Clock(dt.datetime(2026, 11, 9, 9, 20, tzinfo=IST)), []
    paced(monkeypatch, clk)
    rl = FakeRelay(clk)
    rl.add()
    deadline = clk() + dt.timedelta(minutes=345)
    code = go(cfg, rl, clk, tmp_path, dt.time(17, 40), lines, deadline=deadline)
    assert code == 0
    stopped = clk.t.astimezone(IST)
    assert dt.datetime(2026, 11, 9, 15, 5, tzinfo=IST) <= stopped < dt.datetime(2026, 11, 9, 15, 6, tzinfo=IST)     # 345 minutes, inside the 355-minute limit
    assert NAME in R.load_account(rl.state["account"]).positions                                                     # what it filled is on the relay
    assert any(m.startswith("::warning::") and "time limit at 15:05" in m and "next part takes over" in m for m in lines)


def test_the_days_last_part_cut_short_by_its_deadline_ends_red(cfg, tmp_path, monkeypatch):
    clk, lines = Clock(dt.datetime(2026, 11, 9, 16, 0, tzinfo=IST)), []
    paced(monkeypatch, clk)
    rl = FakeRelay(clk)
    code = go(cfg, rl, clk, tmp_path, dt.time(23, 59), lines, deadline=clk() + dt.timedelta(minutes=30), final=True)
    assert code == S.EXIT_SHORT
    assert any(m.startswith("::error::") and "last part" in m for m in lines)


def test_a_part_that_reaches_its_hand_over_first_is_unchanged(cfg, tmp_path, monkeypatch):
    clk, lines = Clock(dt.datetime(2026, 11, 9, 11, 40, tzinfo=IST)), []
    paced(monkeypatch, clk)
    rl = FakeRelay(clk)
    code = go(cfg, rl, clk, tmp_path, dt.time(11, 50), lines, deadline=clk() + dt.timedelta(minutes=345), final=True)
    assert code == 0 and clk.t.astimezone(IST).time() >= dt.time(11, 50)
    assert not any("time limit" in m for m in lines)


def test_a_few_minutes_early_is_said_plainly_not_as_a_warning(cfg, tmp_path, monkeypatch):
    """The usual day: the morning part starts at 06:00 and its hand-over is 350 minutes later, so it stops five minutes early. That is no fault."""
    clk, lines = Clock(dt.datetime(2026, 11, 9, 11, 40, tzinfo=IST)), []
    paced(monkeypatch, clk)
    rl = FakeRelay(clk)
    code = go(cfg, rl, clk, tmp_path, dt.time(11, 50), lines, deadline=clk() + dt.timedelta(minutes=5))
    assert code == 0
    assert any("time limit at 11:45" in m for m in lines) and not any("::warning::" in m for m in lines)


def test_a_part_started_after_midnight_does_nothing(cfg, tmp_path):
    """K-36's falsifier: run() started at 00:00:30 IST with --until 23:59 returns at once (it ran 20,000 cycles, 16.7 hours)."""
    clk, lines = Clock(dt.datetime(2026, 11, 10, 0, 0, 30, tzinfo=IST)), []
    rl = FakeRelay(clk)
    assert go(cfg, rl, clk, tmp_path, dt.time(23, 59), lines) == 0
    assert clk.t == dt.datetime(2026, 11, 10, 0, 0, 30, tzinfo=IST) and rl.state == {}          # no cycle, and nothing sent to the relay
    assert any("before the desk's day" in m for m in lines)


class Slow(Clock):
    """A cycle that takes 90 seconds (a slow relay): one of them can step over midnight while the clock time is still before the stop time."""
    def sleep(self, s):
        self.t += dt.timedelta(seconds=90)
        if self.t.astimezone(IST) > dt.datetime(2026, 11, 10, 0, 5, tzinfo=IST):
            raise AssertionError("the part ran on past midnight")                         # fails fast (it would run the whole next day)


def test_a_part_never_runs_on_past_midnight(cfg, tmp_path, monkeypatch):
    clk, lines = Slow(dt.datetime(2026, 11, 9, 23, 57, tzinfo=IST)), []
    paced(monkeypatch, clk)
    rl = FakeRelay(clk)
    assert go(cfg, rl, clk, tmp_path, dt.time(23, 59), lines) == 0
    assert clk.t.astimezone(IST) <= dt.datetime(2026, 11, 10, 0, 1, 30, tzinfo=IST)            # was: on through the next day to 23:59


def test_every_part_sets_its_deadline_first_and_stops_ten_minutes_inside_its_limit():
    limit = int(WF["env"]["PART_LIMIT_MIN"])
    for name in PARTS:
        job = WF["jobs"][name]
        first = job["steps"][0]
        assert "PART_DEADLINE=" in first["run"] and "date +%s" in first["run"] and "PART_LIMIT_MIN * 60" in first["run"], name
        assert job["timeout-minutes"] - limit >= 10, name                                  # the last save and the artifact upload fit inside the limit
        runs = [s["run"] for s in job["steps"] if "quantdesk paper run" in str(s.get("run", ""))]
        assert len(runs) == 1 and '--deadline-epoch "$PART_DEADLINE"' in runs[0], name
        assert ("--final" in runs[0]) == (name == "night"), name
    assert 4 * limit >= (24 * 60 - 6 * 60) + 3 * 15                                         # four parts cover the 06:00-midnight day with one early end
    assert re.search(r"^\s*PART_LIMIT_MIN: \"\d+\"", RAW, re.M)


def test_the_cli_takes_the_deadline_and_final(monkeypatch):
    import argparse
    from quantdesk.paperlink import cli as C
    p = argparse.ArgumentParser()
    C.register(p.add_subparsers(dest="cmd"))
    a = p.parse_args(["paper", "run", "--until", "23:59", "--deadline-epoch", "1763700000", "--final"])
    seen = {}
    monkeypatch.setattr("quantdesk.paperlink.relay.Relay.from_env", classmethod(lambda cls: object()))
    monkeypatch.setattr(S, "run", lambda *x, **k: seen.update(k) or 0)
    monkeypatch.delenv("PAPER_AUTO", raising=False)
    try:
        C.cmd_run(None, a)
    except SystemExit as e:
        assert e.code == 0
    assert seen["deadline"] == dt.datetime.fromtimestamp(1763700000, tz=dt.timezone.utc) and seen["final"] is True
    assert (ROOT / ".github" / "workflows" / "paper-desk.yml").exists()
