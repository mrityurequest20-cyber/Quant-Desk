#!/usr/bin/env python3
"""Start the live desk when it should be running and isn't (run by scheduler.yml every few minutes).

Why: GitHub's scheduled events are best-effort. On 29 Sep – 1 Oct 2026 live.yml's 08:52 IST cron was
delivered at 15:27, 15:19 and 15:46 IST: the desk traded 11 minutes in three sessions. This check is
itself scheduled (so each firing can be late too), but it fires every few minutes all day, so some
firings land in the morning, and any one of them starting the desk is enough. It starts the desk by
workflow_dispatch, which GitHub runs at once.

Rules, on an NSE trading day between 08:25 and 14:45 IST:
  * a live.yml run is queued or running            → nothing to do
  * a run today was cancelled                      → the operator stopped the desk (the kill switch): stay stopped
  * a run today succeeded                          → the session is covered
  * a run today failed                             → start it again, at most 3 starts a day
  * no run today                                   → start it
Outside that window it arms a waiter instead, because the check itself arrives only a few times a day (scheduler.yml
fired 4 times in 17 hours on 2-3 Oct 2026, never between 08:25 and 14:45). When the next session's wake-up (08:30 IST)
is less than WAITER_MAX away and no waiter is armed yet, it dispatches wake.yml. That job sleeps on its runner until
08:30 IST, then runs this check, which starts the desk. Any one firing in the six hours before the open is then enough.
A public repository's hosted minutes are free, so a sleeping job costs nothing.

Standard library only; reads the holiday list straight from config/quantdesk.yaml."""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
WINDOW = (dt.time(8, 25), dt.time(14, 45))
MAX_STARTS = 3
WAKE = dt.time(8, 30)                       # when an armed waiter starts the desk (inside WINDOW)
WAITER_MAX = dt.timedelta(hours=5, minutes=40)   # a hosted job may run 6 h: sleep at most this long
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}


def holidays(config: Path) -> set[dt.date]:
    out, inside = set(), False
    for line in config.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s*holidays:\s*$", line):
            inside = True
            continue
        if inside:
            m = re.match(r"^\s*-\s*(\d{4}-\d{2}-\d{2})", line)
            if m:
                out.add(dt.date.fromisoformat(m.group(1)))
            elif line.strip() and not line.strip().startswith("#"):
                break
    return out


def decide(now: dt.datetime, runs: list[dict], hols: set[dt.date]) -> tuple[str, str]:
    """('start' | 'wait', why). `runs`: live.yml runs as `gh run list --json status,conclusion,createdAt,event` gives them."""
    now = now.astimezone(IST)
    day = now.date()
    if day.weekday() >= 5 or day in hols:
        return "wait", f"{day} is not an NSE trading day"
    if not (WINDOW[0] <= now.time() < WINDOW[1]):
        return "wait", f"{now:%H:%M} IST is outside the start window {WINDOW[0]:%H:%M}–{WINDOW[1]:%H:%M}"
    if any(r.get("status") in ACTIVE for r in runs):
        return "wait", "the desk is already queued or running"
    today = [r for r in runs if _ist(r["createdAt"]).date() == day]
    if any(r.get("conclusion") == "cancelled" for r in today):
        return "wait", "a run today was cancelled: the desk was stopped on purpose, so it stays stopped"
    if any(r.get("conclusion") == "success" for r in today):
        return "wait", "today's session is already covered"
    if len(today) >= MAX_STARTS:
        return "wait", f"{len(today)} runs today and none succeeded: not starting again (look at the logs)"
    return "start", "no run today yet" if not today else f"today's run failed ({len(today)} so far): starting again"


def next_wake(now: dt.datetime, hols: set[dt.date]) -> dt.datetime:
    """The next trading day's WAKE at or after `now` (IST)."""
    now = now.astimezone(IST)
    day = now.date() if now.time() < WAKE else now.date() + dt.timedelta(days=1)
    while day.weekday() >= 5 or day in hols:
        day += dt.timedelta(days=1)
    return dt.datetime.combine(day, WAKE, tzinfo=IST)


def arm(now: dt.datetime, runs: list[dict], waiters: list[dict], hols: set[dt.date]) -> tuple[str, str, dt.datetime | None]:
    """('arm' | 'wait', why, wake time). `runs`: live.yml runs; `waiters`: wake.yml runs (same shape)."""
    target = next_wake(now, hols)
    left = target - now.astimezone(IST)
    if left > WAITER_MAX:
        return "wait", f"the next wake-up ({target:%a %d-%b %H:%M} IST) is {left} away: too far to arm a waiter", target
    if any(r.get("status") in ACTIVE for r in waiters):
        return "wait", f"a waiter is already armed for {target:%a %H:%M} IST", target
    if any(r.get("status") in ACTIVE for r in runs):
        return "wait", "the desk is already queued or running", target
    return "arm", f"arming a waiter for {target:%a %d-%b %H:%M} IST ({left} from now)", target


def _ist(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)


def _runs(workflow: str) -> list[dict]:
    return json.loads(subprocess.run(["gh", "run", "list", "--workflow", workflow, "--limit", "30", "--json",
                                      "status,conclusion,createdAt,event"], check=True, capture_output=True,
                                     text=True).stdout or "[]")


def sleep_until(target: dt.datetime, say=print) -> bool:
    """Sleep on this runner until `target`; False if it is further away than a hosted job can wait."""
    left = target - dt.datetime.now(IST)
    if left > WAITER_MAX + dt.timedelta(minutes=10):
        say(f"refusing to sleep {left}: a hosted job would time out first")
        return False
    say(f"sleeping until {target:%a %d-%b %H:%M} IST ({max(left, dt.timedelta(0))})")
    while (left := (target - dt.datetime.now(IST)).total_seconds()) > 0:
        time.sleep(min(left, 300))
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    repo_root = Path(__file__).resolve().parent.parent
    hols = holidays(repo_root / "config" / "quantdesk.yaml")
    if argv[:1] == ["--wake"]:                       # wake.yml: the armed waiter
        if not sleep_until(dt.datetime.fromisoformat(argv[1]).astimezone(IST)):
            return 1
    now = dt.datetime.now(IST)
    runs = _runs("live.yml")
    action, why = decide(now, runs, hols)
    print(f"{action}: {why}")
    if action == "start":
        subprocess.run(["gh", "workflow", "run", "live.yml", "--ref", "main"], check=True)
        print("dispatched live.yml")
        return 0
    if argv[:1] == ["--wake"] or WINDOW[0] <= now.time() < WINDOW[1]:
        return 0
    action, why, target = arm(now, runs, _runs("wake.yml"), hols)
    print(f"{action}: {why}")
    if action == "arm":
        subprocess.run(["gh", "workflow", "run", "wake.yml", "--ref", "main", "-f", f"at={target.isoformat()}"], check=True)
        print("dispatched wake.yml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
