"""The desk scheduler: starts the desk when it should be running and isn't, never against the kill switch."""
import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("scheduler", ROOT / "deploy" / "scheduler.py")
sch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sch)
IST = sch.IST


def at(s):
    return dt.datetime.fromisoformat(s).replace(tzinfo=IST)


def run(created_ist, status="completed", conclusion="success"):
    utc = at(created_ist).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"createdAt": utc, "status": status, "conclusion": conclusion, "event": "schedule"}


HOLS = sch.holidays(ROOT / "config" / "quantdesk.yaml")


def test_reads_the_holidays_from_the_config():
    assert dt.date(2026, 10, 2) in HOLS and dt.date(2026, 10, 20) in HOLS and dt.date(2026, 10, 1) not in HOLS
    assert dt.date(2026, 10, 7) not in HOLS                     # an RBI event day is a trading day


def test_starts_a_missing_session_and_only_in_the_window():
    yday = [run("2026-09-30 15:19")]                             # 1 Oct 2026: the cron hadn't arrived yet
    assert sch.decide(at("2026-10-01 08:40"), yday, HOLS)[0] == "start"
    assert sch.decide(at("2026-10-01 13:30"), yday, HOLS)[0] == "start"      # late is better than never
    assert sch.decide(at("2026-10-01 08:00"), yday, HOLS)[0] == "wait"       # too early: the job would time out
    assert sch.decide(at("2026-10-01 15:00"), yday, HOLS)[0] == "wait"       # too late to trade
    assert sch.decide(at("2026-10-02 10:00"), [], HOLS)[0] == "wait"         # Gandhi Jayanti
    assert sch.decide(at("2026-10-03 10:00"), [], HOLS)[0] == "wait"         # Saturday


def test_never_doubles_up_and_respects_the_kill_switch():
    t = at("2026-10-05 10:00")
    assert sch.decide(t, [run("2026-10-05 08:40", status="in_progress", conclusion=None)], HOLS)[0] == "wait"
    assert sch.decide(t, [run("2026-10-05 08:40", status="queued", conclusion=None)], HOLS)[0] == "wait"
    act, why = sch.decide(t, [run("2026-10-05 08:40", conclusion="cancelled")], HOLS)
    assert act == "wait" and "stopped on purpose" in why
    assert sch.decide(t, [run("2026-10-05 08:40", conclusion="success")], HOLS)[0] == "wait"


def test_retries_a_failed_day_a_few_times_then_stops():
    t = at("2026-10-05 11:00")
    assert sch.decide(t, [run("2026-10-05 08:40", conclusion="failure")], HOLS)[0] == "start"
    three = [run(f"2026-10-05 0{h}:40", conclusion="failure") for h in (8, 9)] + [run("2026-10-05 10:10", conclusion="failure")]
    assert sch.decide(t, three, HOLS)[0] == "wait"


def test_arms_an_overnight_waiter_within_reach_of_the_open():
    # 2-3 Oct 2026: the scheduler fired at 01:46, 05:18 and 07:51 IST. Each one in the six hours before 08:30 arms a waiter.
    act, why, target = sch.arm(at("2026-10-05 05:18"), [], [], HOLS)
    assert act == "arm" and target == at("2026-10-05 08:30")
    assert sch.arm(at("2026-10-05 02:30"), [], [], HOLS)[0] == "wait"        # 6 h away: a hosted job would time out
    assert sch.arm(at("2026-10-05 02:55"), [], [], HOLS)[0] == "arm"
    # Friday evening: the next session is Monday, far beyond reach; Sunday night is close enough
    assert sch.arm(at("2026-10-02 21:46"), [], [], HOLS)[0] == "wait"
    assert sch.arm(at("2026-10-05 04:00"), [], [], HOLS)[2] == at("2026-10-05 08:30")
    # after today's wake-up the target is the next trading day (19 Oct → 21 Oct: Dussehra, 20 Oct)
    assert sch.next_wake(at("2026-10-19 16:00"), HOLS) == at("2026-10-21 08:30")


def test_never_arms_twice_or_over_a_running_desk():
    t = at("2026-10-05 05:18")
    assert sch.arm(t, [], [run("2026-10-05 03:00", status="in_progress", conclusion=None)], HOLS)[0] == "wait"
    assert sch.arm(t, [], [run("2026-10-05 03:00", status="pending", conclusion=None)], HOLS)[0] == "wait"
    assert sch.arm(t, [run("2026-10-05 05:00", status="queued", conclusion=None)], [], HOLS)[0] == "wait"
    assert sch.arm(t, [], [run("2026-10-04 03:00")], HOLS)[0] == "arm"         # yesterday's finished waiter


def test_the_waiter_refuses_a_sleep_longer_than_a_job_can_run():
    far = dt.datetime.now(IST) + dt.timedelta(hours=7)
    assert sch.sleep_until(far, say=lambda *a: None) is False
    assert sch.sleep_until(dt.datetime.now(IST) - dt.timedelta(minutes=1), say=lambda *a: None) is True


def test_the_waiter_workflow_is_dispatchable_and_bounded():
    import yaml
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "wake.yml").read_text())
    on = wf.get("on", wf.get(True))
    assert "workflow_dispatch" in on and "at" in on["workflow_dispatch"]["inputs"]
    job = wf["jobs"]["wait"]
    assert job["timeout-minutes"] <= 360
    assert "--wake" in job["steps"][-1]["run"] and "${{" not in job["steps"][-1]["run"]   # input via env, not inlined
