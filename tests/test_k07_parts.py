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
PARTS = ("morning", "afternoon", "evening", "night", "reserve")


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
        assert ("--final" in runs[0]) == (name == "reserve"), name                     # the day's last part is the reserve
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


def cascade(dead=None, setup=5, first=dt.datetime(2026, 11, 23, 6, 0, 20, tzinfo=IST)):
    """The workflow's day, as the session runs it: each job starts when the one before ends (plus a few seconds), spends `setup` minutes before its runner cycles,
    and the runner stops at the earlier of its stop time and its job's start + PART_LIMIT_MIN. Part `dead` ends `setup` minutes after it starts (a crash at its
    start). Returns the (from, to) IST intervals in which a runner is cycling."""
    limit = int(WF["env"]["PART_LIMIT_MIN"])
    stops = {"morning": "11:50", "afternoon": "17:40", "evening": "23:30", "night": "23:59", "reserve": "23:59"}
    out, start = [], first
    for name in PARTS:
        cyc = start + dt.timedelta(minutes=setup)
        if name == dead:
            end = cyc
        else:
            until = dt.datetime.combine(first.date(), dt.time.fromisoformat(stops[name]), tzinfo=IST)
            end = max(cyc, min(until, start + dt.timedelta(minutes=limit)))
            if cyc.time() >= S.DESK_DAY_FROM and cyc.date() == first.date() and end > cyc:
                out.append((cyc, end))
        start = end + dt.timedelta(seconds=5)
    return out


def watched(iv, a, b):
    return any(f <= a and t >= b for f, t in iv)


def test_with_any_one_part_ending_at_its_start_the_brakes_of_the_day_still_run():
    """Risk review of #279 (BLOCKING 1): with four parts, one part ending at its start left 3 x 345 minutes for an 18-hour day and the night part stopped at about
    23:21, before the MCX square-off (23:25; config: futures intraday, square_off_min 5). The reserve part covers it, whichever part ends early."""
    d = dt.date(2026, 11, 23)
    at = lambda hhmm: dt.datetime.combine(d, dt.time.fromisoformat(hhmm), tzinfo=IST)     # noqa: E731
    for dead in (None,) + PARTS[:-1]:
        for setup in (3, 5):
            iv = cascade(dead, setup)
            assert watched(iv, at("23:27"), at("23:30")), (dead, setup, iv)        # the MCX square-off: runner.py squares off at any cycle from 23:25 to the 23:30
            #                                                                         close; at least its last three minutes are watched (the worst case starts at 23:25:40)
            assert watched(iv, at("15:20"), at("15:21")) and watched(iv, at("15:31"), at("15:32")), (dead, setup)   # the expiry sale and the settlement
    assert cascade(None)[-1][1].time() >= dt.time(23, 30)                                                     # a normal day reaches the close in the night part


def test_without_the_reserve_one_early_end_misses_the_square_off():
    """The review's case, as a check on the cascade itself: four parts, the evening ending at its start, no runner cycles through 23:25."""
    d = dt.date(2026, 11, 23)
    iv = [x for x in cascade("evening") if x[0].time() < dt.time(23, 21)]          # drop what the reserve adds
    assert not watched(iv, dt.datetime.combine(d, dt.time(23, 25), tzinfo=IST), dt.datetime.combine(d, dt.time(23, 30), tzinfo=IST))


def test_a_paper_run_made_before_the_desks_day_is_not_counted_as_todays_session(monkeypatch):
    """Risk review of #279 (BLOCKING 2): a run dispatched by hand at 01:00 IST does nothing (DESK_DAY_FROM) and ends green; the scheduler counted it as today's
    session and never started the desk. Now, for the paper runner, a run made before its start window is not today's, green or cancelled."""
    from tests.test_scheduler import HOLS, at, run, sch
    t = at("2026-11-23 05:55")
    early_ok, early_cx = run("2026-11-23 01:00"), run("2026-11-23 01:00", conclusion="cancelled")
    assert sch.decide(t, [early_ok], HOLS, sch.PAPER_MAX_STARTS, sch.PAPER_WINDOW, day_from=sch.PAPER_WINDOW[0])[0] == "start"
    assert sch.decide(t, [early_cx], HOLS, sch.PAPER_MAX_STARTS, sch.PAPER_WINDOW, day_from=sch.PAPER_WINDOW[0])[0] == "start"
    later = at("2026-11-23 10:00")
    assert sch.decide(later, [run("2026-11-23 06:00")], HOLS, sch.PAPER_MAX_STARTS, sch.PAPER_WINDOW, day_from=sch.PAPER_WINDOW[0])[0] == "wait"    # a real session still counts
    assert sch.decide(later, [run("2026-11-23 06:00", conclusion="cancelled")], HOLS, sch.PAPER_MAX_STARTS, sch.PAPER_WINDOW,
                      day_from=sch.PAPER_WINDOW[0])[0] == "wait"                                                                         # and the owner's stop still holds
    assert sch.decide(t, [early_ok], HOLS)[0] == "wait"                                       # the other workflows are unchanged (outside their window here anyway)
    calls = []
    monkeypatch.setattr(sch.dt, "datetime", type("D", (sch.dt.datetime,), {"now": classmethod(lambda c, tz=None: at("2026-11-23 06:00"))}))
    monkeypatch.setattr(sch, "_runs", lambda wf: [early_ok] if wf == sch.PAPER_WORKFLOW else [])
    monkeypatch.setattr(sch.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    assert sch.main([]) == 0
    assert ["gh", "workflow", "run", "paper-desk.yml", "--ref", "main"] in calls                # main passes the paper runner's day start
