"""Audit K-19 (E-04, HIGH): Kite's MCX and currency evening candles collected nothing on 12 and 17-19 Nov, and every run was green. GitHub's cron (meant for 00:05
IST) fired at 06:12-07:32 IST; shifted by six hours that is the NEXT session day, so the late run (which could not log in) was that day's earliest and took the
real evening's login at 00:10. Now a scheduled run outside the evening's window never logs in nor counts, the cron is gone (the Worker starts the job), and an
evening that collected nothing ends red so the watchdog sees it. Market data only."""
from __future__ import annotations

import datetime as dt
import importlib.util
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kite_evening_gate", ROOT / "deploy" / "kite_evening_gate.py")
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)
IST = G.IST
WF = yaml.safe_load((ROOT / ".github" / "workflows" / "kite-evening.yml").read_text(encoding="utf-8"))


def ts(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=IST).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(i, when, event="workflow_dispatch"):
    return {"databaseId": i, "createdAt": ts(when), "event": event}


RECORDER_19 = [{"databaseId": 10, "createdAt": ts("2026-11-19 08:55"), "conclusion": "success"}]
JOBS = lambda i: [{"name": "record-1", "steps": [{"name": "Log in to Kite by itself (data only)", "conclusion": "success"}]}]     # noqa: E731


def gate(own, run_id, now):
    return G.decide(own, run_id, 1, dt.datetime.fromisoformat(now).replace(tzinfo=IST).astimezone(dt.timezone.utc), RECORDER_19, JOBS)


def test_the_audits_19_nov_case_the_late_cron_run_no_longer_takes_the_evenings_login():
    own = [run(44590000000, "2026-11-19 06:12", "schedule"), run(44590230559, "2026-11-20 00:10")]
    late = gate(own, 44590000000, "2026-11-19 06:12")
    assert late[0] is False and late[2] == "late" and "outside the evening" in late[1]
    ok, why, kind = gate(own, 44590230559, "2026-11-20 00:10")                                  # was: "1 earlier run(s) for this session day: only the first one logs in"
    assert ok and kind == "ok", why


def test_the_window_edges_are_pinned():
    """Mutant M22 (the six-hour shift moved) survived every evening test: the boundary is now pinned at both ends."""
    assert G.in_evening(dt.datetime(2026, 11, 19, 23, 56, tzinfo=IST)) and not G.in_evening(dt.datetime(2026, 11, 19, 23, 55, tzinfo=IST))
    assert G.in_evening(dt.datetime(2026, 11, 20, 5, 59, tzinfo=IST)) and not G.in_evening(dt.datetime(2026, 11, 20, 6, 0, tzinfo=IST))
    assert G.session_day(dt.datetime(2026, 11, 20, 0, 10, tzinfo=IST)) == dt.date(2026, 11, 19) == G.session_day(dt.datetime(2026, 11, 19, 23, 58, tzinfo=IST))
    own = [run(2, "2026-11-20 00:10"), run(3, "2026-11-20 05:59", "schedule")]                     # a scheduled run inside the window is a real evening run, so it
    assert gate(own, 2, "2026-11-20 00:10")[2] == "ok" and gate(own, 3, "2026-11-20 05:59")[2] == "dup"   # counts: the second of the evening never logs in


def test_a_run_started_by_hand_still_uses_the_days_login_and_a_second_evening_run_is_still_refused():
    own = [run(25, "2026-11-19 20:00"), run(30, "2026-11-20 00:10")]                                # a hand backfill at 20:00 used the 19 Nov login
    assert gate(own, 30, "2026-11-20 00:10")[:3:2] == (False, "dup")
    own = [run(30, "2026-11-20 00:10"), run(31, "2026-11-20 00:20")]
    assert gate(own, 31, "2026-11-20 00:20")[2] == "dup"
    assert G.decide([run(30, "2026-11-20 00:10")], 30, 2, dt.datetime(2026, 11, 20, 0, 30, tzinfo=IST), RECORDER_19, JOBS)[2] == "dup"    # a re-run


def test_an_unproven_day_is_its_own_kind():
    ok, why, kind = G.decide([run(30, "2026-11-20 00:10")], 30, 1, dt.datetime(2026, 11, 20, 0, 10, tzinfo=IST), [], JOBS)
    assert not ok and kind == "unproven"


def test_the_workflow_has_no_cron_and_writes_the_kind():
    on = WF.get("on", WF.get(True))
    assert "schedule" not in on and "workflow_dispatch" in on
    src = (ROOT / "deploy" / "kite_evening_gate.py").read_text(encoding="utf-8")
    assert "kind={kind}" in src and '"databaseId,createdAt,event"' in src


def red_step():
    return next(s for s in WF["jobs"]["collect"]["steps"] if s.get("name", "").startswith("Red when this evening collected nothing"))


def run_red(tmp_path, kind, day, files):
    d = tmp_path / "runtime" / "kite_evening" / day / "data"
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("x")
    env = {"KIND": kind, "DAY": day, "PATH": "/usr/bin:/bin"}
    return subprocess.run(["bash", "-e", "-c", red_step()["run"]], cwd=tmp_path, env=env, capture_output=True, text=True).returncode


def test_an_evening_that_collected_nothing_is_red_unless_another_run_has_it(tmp_path):
    st = red_step()
    assert st["if"] == "always()" and set(st["env"]) == {"KIND", "DAY"}
    assert run_red(tmp_path / "a", "ok", "2026-11-19", ["MCX.parquet"]) == 0
    assert run_red(tmp_path / "b", "ok", "2026-11-19", []) == 1                               # logged in, nothing came: red (was green)
    assert run_red(tmp_path / "c", "unproven", "2026-11-19", []) == 1                         # the day's credentials not proven: nothing recorded, red
    assert run_red(tmp_path / "d", "other", "2026-11-19", []) == 1
    assert run_red(tmp_path / "e", "dup", "2026-11-19", []) == 0 and run_red(tmp_path / "f", "late", "2026-11-19", []) == 0
