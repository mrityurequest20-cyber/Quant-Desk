#!/usr/bin/env python3
"""May this evening run log in to Zerodha? Only after the same session day's Kite recorder logged in successfully, and only once.

The lockout guard behind the evening candle job (kite-evening.yml, docs/AUTONOMY.md). The morning recorder (kite-record.yml) is the one that finds out whether the owner's
credentials work; it is started once a day and never retried. This job is a third login of the day, so it is held to a stricter rule than the recorder's own:

  * its first attempt only (a re-run never logs in again);
  * the earliest run of this workflow for the session day (a hand-started run earlier in the day uses up the day's login);
  * a kite-record.yml run of the same session day that SUCCEEDED and whose first job's login step succeeded (so the credentials are known good today, and this is
    not the first time they are used).

The session day is the IST day shifted by six hours: a run at 00:05 IST belongs to the evening that just ended (the same rule as quantdesk/data/evening_minutes.py).
A run that may not log in does nothing (there is no stored-token fallback here: a stale token would only record an error). If the run lists cannot be read the answer is `false`.

Audit K-19 (E-04): GitHub's cron, meant for 00:05 IST, fired at 06:12-07:32 IST. Shifted by six hours that is the NEXT session day, so the late run (which could not log
in: that day's recorder had not run yet) counted as that day's earliest run and took the real evening's login at 00:10: 12, 17, 18 and 19 Nov collected nothing, and green.
Now a SCHEDULED run created outside the evening's window (EVENING_FROM to EVENING_TO IST) never logs in and never counts as an earlier run. A run started by hand (or by the
Worker, at 00:10) still does: a hand-started run earlier in the day uses up the day's login, as before.

Prints `first=true|false` and `kind=ok|dup|late|unproven|other` to $GITHUB_OUTPUT (the workflow turns a run red when no candles came for any reason but `dup` and `late`).
Standard library plus the `gh` CLI the runner ships; needs `actions: read`."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
LOGIN_STEP = "Log in to Kite by itself"
EVENING_FROM, EVENING_TO = dt.time(23, 56), dt.time(6, 0)       # after every MCX close (23:30, or 23:55 some months) and before any morning job (audit K-19)


def session_day(ts: dt.datetime) -> dt.date:
    return (ts.astimezone(IST) - dt.timedelta(hours=6)).date()


def _created(r: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))


def in_evening(ts: dt.datetime) -> bool:
    t = ts.astimezone(IST).time()
    return t >= EVENING_FROM or t < EVENING_TO


def could_log_in(r: dict) -> bool:
    """A run that this gate could have let log in: anything but a scheduled run created outside the evening's window (K-19). A run with no event is counted."""
    return r.get("event") != "schedule" or in_evening(_created(r))


def login_proven(record_runs: list[dict], jobs_of, day: dt.date) -> tuple[bool, str]:
    """A kite-record.yml run created on `day` (IST) that succeeded, whose first job's login step succeeded. `jobs_of(run_id)` -> the `jobs` list of `gh run view --json jobs`."""
    todays = [r for r in record_runs if _created(r).astimezone(IST).date() == day and r.get("conclusion") == "success"]
    if not todays:
        return False, f"no successful kite-record.yml run on {day}: the credentials are not proven today"
    for r in sorted(todays, key=lambda r: int(r["databaseId"])):
        for job in jobs_of(int(r["databaseId"])) or []:
            for step in job.get("steps") or []:
                if str(step.get("name", "")).startswith(LOGIN_STEP) and step.get("conclusion") == "success":
                    return True, f"the recorder's automatic login succeeded in run {r['databaseId']}"
    return False, f"the recorder's login step did not succeed on {day} (skipped, failed or absent)"


def may_log_in(own_runs: list[dict], run_id: int, attempt: int, now: dt.datetime, record_runs: list[dict], jobs_of) -> tuple[bool, str]:
    ok, why, _ = decide(own_runs, run_id, attempt, now, record_runs, jobs_of)
    return ok, why


def decide(own_runs: list[dict], run_id: int, attempt: int, now: dt.datetime, record_runs: list[dict], jobs_of) -> tuple[bool, str, str]:
    """(may log in, why, kind): kind is ok, dup (another run has this evening's login), late (a scheduled run outside the evening), unproven or other."""
    if attempt > 1:
        return False, f"attempt {attempt} of this run: a re-run never logs in again", "dup"
    mine = [r for r in own_runs if int(r["databaseId"]) == run_id]
    if not mine:
        return False, "this run is not in the run list yet: not logging in (no login is better than an extra one)", "other"
    if not could_log_in(mine[0]):
        return False, (f"a scheduled run created at {_created(mine[0]).astimezone(IST):%H:%M} IST, outside the evening ({EVENING_FROM:%H:%M}-{EVENING_TO:%H:%M}): "
                       f"GitHub's cron ran late; it does not log in and does not use up an evening's login"), "late"
    day = session_day(_created(mine[0]))
    if day != session_day(now):
        return False, "this run was created for another session day: not logging in", "other"
    earlier = [int(r["databaseId"]) for r in own_runs if could_log_in(r) and session_day(_created(r)) == day and int(r["databaseId"]) < run_id]
    if earlier:
        return False, f"{len(earlier)} earlier run(s) for this session day: only the first one logs in", "dup"
    ok, why = login_proven(record_runs, jobs_of, day)
    return ok, why, "ok" if ok else "unproven"


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=60).stdout


def main() -> int:
    run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        own = json.loads(_gh("run", "list", "-R", repo, "--workflow", "kite-evening.yml", "--limit", "30", "--json", "databaseId,createdAt,event") or "[]")
        rec = json.loads(_gh("run", "list", "-R", repo, "--workflow", "kite-record.yml", "--limit", "30", "--json", "databaseId,createdAt,conclusion") or "[]")
        ok, why, kind = decide(own, run_id, attempt, dt.datetime.now(dt.timezone.utc), rec,
                               lambda i: json.loads(_gh("run", "view", str(i), "-R", repo, "--json", "jobs") or "{}").get("jobs"))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
        ok, why, kind = False, f"could not read the run lists ({type(e).__name__}): not logging in", "other"
    print(f"kite evening login gate: {'yes' if ok else 'no'}: {why}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as fh:
        fh.write(f"first={'true' if ok else 'false'}\nkind={kind}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
