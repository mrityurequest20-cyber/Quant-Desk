#!/usr/bin/env python3
"""May this Kite recorder run log in to Zerodha? Only the first run of the IST day, on its first attempt.

The lockout guard behind the automatic Kite login (deploy/kite_autologin.py, docs/AUTONOMY.md): a wrong or changed
password must cost at most one failed Zerodha login a day. Two starters exist (the scheduler and its overnight
waiter), a job can be re-run by hand, and two starters can race; every run but the earliest one created today, and
every re-run attempt, is refused the login. A refused run still records with the stored token, if there is one.

Prints `first=true|false` to $GITHUB_OUTPUT. Standard library plus the `gh` CLI the runner ships; needs
`actions: read`. If the run list cannot be read, the answer is `false`: no login is better than a second one.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
# Which workflow's runs to count: the Kite recorder by default; the Fyers and Angel One feeds set GATE_WORKFLOW, so its login has the same one-a-day guard.
WORKFLOW = os.environ.get("GATE_WORKFLOW") or "kite-record.yml"
if WORKFLOW not in ("kite-record.yml", "fyers-feed.yml", "angel-feed.yml"):
    WORKFLOW = "kite-record.yml"


def may_log_in(runs: list[dict], run_id: int, attempt: int, today: dt.date) -> tuple[bool, str]:
    if attempt > 1:
        return False, f"attempt {attempt} of this run: a re-run never logs in again"
    mine = [r for r in runs if int(r["databaseId"]) == run_id]
    if not mine:
        return False, "this run is not in the run list yet: not logging in (no login is better than a second one)"
    def day(r):
        return dt.datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00")).astimezone(IST).date()
    if day(mine[0]) != today:                     # created yesterday, gated after midnight: it would not see today's runs
        return False, "this run was created on another IST day: not logging in"
    todays = [int(r["databaseId"]) for r in runs if day(r) == today]
    earlier = [i for i in todays if i < run_id]
    if earlier:
        return False, f"{len(earlier)} earlier run(s) today: only the first run of the day logs in"
    return True, "the first run today, first attempt"


def main() -> int:
    run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    try:
        out = subprocess.run(["gh", "run", "list", "-R", os.environ["GITHUB_REPOSITORY"], "--workflow", WORKFLOW,
                              "--limit", "30", "--json", "databaseId,createdAt"], check=True, capture_output=True, text=True,
                             timeout=60).stdout
        runs = json.loads(out or "[]")
    except (subprocess.SubprocessError, OSError, ValueError, KeyError) as e:
        ok, why = False, f"could not read this workflow's runs ({type(e).__name__}): not logging in"
    else:
        ok, why = may_log_in(runs, run_id, attempt, dt.datetime.now(IST).date())
    print(f"login gate ({WORKFLOW}): {'yes' if ok else 'no'}: {why}")
    with open(os.environ.get("GITHUB_OUTPUT", os.devnull), "a") as fh:
        fh.write(f"first={'true' if ok else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
