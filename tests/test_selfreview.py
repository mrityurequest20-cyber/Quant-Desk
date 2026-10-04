"""The desk's self-review (ops/selfreview.py): what it finds after a session, and the issue lifecycle it keeps on GitHub
(one issue per finding, one comment a day on a recurring problem, closed when a transient problem clears)."""
import datetime as dt

import pandas as pd

from quantdesk.core.calendar import TradingCalendar
from quantdesk.journal.journal import Journal
from quantdesk.ops import selfreview as SR

IST = "Asia/Kolkata"


class FakeGitHub:
    def __init__(self, runs=()):
        self.issues, self.comments, self.labels, self._runs, self.n = {}, [], set(), list(runs), 0
        self.today = "2026-10-05"

    def runs(self, since):
        return self._runs

    def open_issues(self):
        return [i for i in self.issues.values() if i["state"] == "open"]

    def ensure_label(self, name, color):
        self.labels.add(name)

    def create(self, title, body, labels):
        self.n += 1
        self.issues[self.n] = {"number": self.n, "title": title, "body": body, "labels": [{"name": x} for x in labels],
                               "state": "open", "updated_at": self.today + "T10:00:00Z"}
        return self.issues[self.n]

    def comment(self, number, body):
        self.comments.append((number, body))
        self.issues[number]["updated_at"] = self.today + "T10:00:00Z"

    def close(self, number):
        self.issues[number]["state"] = "closed"


def test_issue_lifecycle():
    gh = FakeGitHub()
    flaky = SR.Finding("tape-gaps", "data", "Tape gaps", "NIFTY 70%", "fix it")
    ask = SR.Finding("tape-milestone:10", "research", "10 tape sessions", "run plan research", "do it", transient=False)
    SR.sync(gh, [flaky, ask], dt.date(2026, 10, 5), say=lambda *a: None)
    assert len(gh.issues) == 2 and {"desk-request", "desk:data", "desk:research", "auto-clears"} <= gh.labels
    t = next(i for i in gh.issues.values() if "Tape gaps" in i["title"])
    assert "<!-- desk-key: tape-gaps -->" in t["body"] and {"name": "auto-clears"} in t["labels"]
    SR.sync(gh, [flaky, ask], dt.date(2026, 10, 5), say=lambda *a: None)          # same day: nothing new
    assert not gh.comments and len(gh.issues) == 2
    gh.today = "2026-10-06"
    SR.sync(gh, [flaky, ask], dt.date(2026, 10, 6), say=lambda *a: None)          # next day: the problem recurs
    assert [n for n, _ in gh.comments] == [t["number"]]                           # a request is not nagged about
    gh.today = "2026-10-07"
    done = SR.sync(gh, [ask], dt.date(2026, 10, 7), say=lambda *a: None)          # the gaps cleared
    assert done["closed"] == [t["number"]] and t["state"] == "closed"
    assert sum(i["state"] == "open" for i in gh.issues.values()) == 1             # the research request stays open


def _journal(path, day, start=True, errors=0):
    j = Journal(path)
    j.set_state("intraday_account", {"capital": 500000.0, "since": "2026-10-01"})
    t0 = pd.Timestamp(f"{day} 09:15", tz=IST)
    if start:
        j.event(t0, "INFO", "session", "session start; expiries …; chain kotak")
    for k in range(errors):
        j.event(t0 + pd.Timedelta(minutes=k + 1), "ERROR", "engine", "step: KeyError('spot')", {"where": "engine.py:500"})
    j.commit()
    return j


def test_session_checks(tmp_path):
    day = dt.date(2026, 10, 5)
    j = _journal(tmp_path / "a.db", day, start=True, errors=3)
    f = SR.check_session(j, day, True)
    assert [x.key for x in f] == ["engine-errors"] and "3× `step: KeyError('spot')`" in f[0].detail
    j2 = _journal(tmp_path / "b.db", day, start=False)
    assert [x.key for x in SR.check_session(j2, day, True)] == ["session-missing"]
    assert SR.check_session(j2, dt.date(2026, 9, 30), True) == []                 # before the account existed
    assert SR.check_session(j2, day, False) == []                                 # not a trading day


def test_no_trades_streak(cfg, tmp_path):
    cal = TradingCalendar(cfg.holidays())
    j = Journal(tmp_path / "j.db")
    day = dt.date(2026, 10, 9)
    d, n = day, 0
    while n < 5:
        if cal.is_trading_day(d):
            j.event(pd.Timestamp(f"{d} 09:15", tz=IST), "INFO", "session", "session start; …")
            n += 1
        d -= dt.timedelta(days=1)
    j.commit()
    assert [x.key for x in SR.check_trading(j, cal, day)] == ["no-trades"]


def _tape_log(day_dir, minutes, series=(("NIFTY", "2026-10-06"),)):
    day_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"ts": f"{pd.Timestamp(f'{day_dir.name} 09:15') + pd.Timedelta(minutes=m):%Y-%m-%d %H:%M:%S}+05:30",
             "underlying": u, "expiry": e, "ok": True, "strikes": 41, "quoted": 82, "spot": 25000, "secs": 1.2, "error": ""}
            for m in range(minutes) for u, e in series]
    pd.DataFrame(rows).to_csv(day_dir / "tape.csv", index=False)


def test_tape_coverage_from_the_log_and_milestones(tmp_path):
    day = dt.date(2026, 10, 5)
    _tape_log(tmp_path / str(day), 200)
    f = SR.check_tape(tmp_path, day, True)
    assert [x.key for x in f] == ["tape-gaps"] and "NIFTY 2026-10-06: 53%" in f[0].detail
    _tape_log(tmp_path / "2026-10-06", 370)
    assert SR.check_tape(tmp_path, dt.date(2026, 10, 6), True) == []
    assert [x.key for x in SR.check_tape(tmp_path, dt.date(2026, 10, 7), True)] == ["tape-missing"]
    for k in range(10):
        _tape_log(tmp_path / f"2026-11-{k + 1:02d}", 310)
    assert [x.key for x in SR.check_milestones(tmp_path)] == ["tape-milestone:10"]


def test_failed_workflows_are_findings():
    runs = [{"name": "Live paper desk", "conclusion": "failure", "run_number": 7, "html_url": "u", "updated_at": "t",
             "head_branch": "main", "event": "workflow_dispatch"},
            {"name": "Live paper desk", "conclusion": "failure", "run_number": 6},
            {"name": "CI", "conclusion": "success"}, {"name": "Study", "conclusion": "cancelled"}]
    f = SR.check_workflows(FakeGitHub(runs), pd.Timestamp("2026-10-05 17:00", tz=IST))
    assert [x.key for x in f] == ["workflow-failed:Live paper desk"] and "#7" in f[0].detail
