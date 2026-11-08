#!/usr/bin/env python3
"""Start the session recorder (record.yml), and the Kite tick recorder (kite-record.yml, once a day, never retried), when
they should be running and aren't (run by scheduler.yml every few minutes).

Until 6 Nov 2026 this started the live paper desk (live.yml); the owner stopped paper trading and the recorder took
its place, with the same rules.

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
WORKFLOW = "record.yml"                    # the recorder; live.yml (the paper desk) was retired on 6 Nov 2026
# The Kite tick recorder logs in to Zerodha by itself (deploy/kite_autologin.py). It is started once a day and never
# again after a failure: a wrong or changed password retried every few minutes would lock the owner's Zerodha account.
KITE_WORKFLOW, KITE_MAX_STARTS = "kite-record.yml", 1
# The every-minute F&O stock chain recorder (record-stocks.yml, Kotak only): started like the session recorder, retried once if a day's run failed, and a problem listing or starting it never
# holds up the main recorder (it is a separate workflow with its own concurrency group).
STOCK_WORKFLOW, STOCK_MAX_STARTS = "record-stocks.yml", 2
# The manual paper runner (paper-desk.yml): carries out the owner's queued paper orders through the paper risk gate. Like the stock recorder, a problem listing or starting it never holds up the main recorder.
# It is safe to start again after a failure (it restores its account from the relay and the ledger branch, and an order is never filled twice), so it gets three starts a day.
PAPER_WORKFLOW, PAPER_MAX_STARTS = "paper-desk.yml", 3
PAPER_WINDOW = (dt.time(8, 25), dt.time(15, 25))     # later than the recorders': a runner that stopped early in the afternoon is started again until 15:25, so the 15:20 sale and the 15:31 settlement still happen
# The news digest (news.yml): the desk's public RSS feeds read by its news engine and sent to the relay for the app's News panel. Unlike the recorders it is not once a day: it is started on every tick of
# the session (the Worker's cron fires this scheduler every ten minutes) if none is queued or running and the last one is at least eight minutes old. A failure here never matters to anything else.
# News does not keep market hours: it runs around the clock, every day (8 Nov 2026, owner: "nothing is getting missed out"), so a story at night or on a weekend is already in the digest when the market opens.
NEWS_WORKFLOW = "news.yml"
NEWS_EVERY = dt.timedelta(minutes=8)
# The FX minute bars (fx-minutes.yml, public Yahoo data, no login): FX closes Friday 22:00 UTC and reopens Sunday 22:00 UTC, so the last day's bars are complete by 04:00 IST Tue to Sat. GitHub's cron for it
# ("30 22 * * 1-5") is best-effort; this dispatches it too, and unlike a job that logs in it may be started again (up to three times a day) when a run failed, since nothing logs in.
FX_WORKFLOW, FX_MAX_STARTS = "fx-minutes.yml", 3
FX_WINDOW = (dt.time(4, 5), dt.time(11, 0))
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


def decide(now: dt.datetime, runs: list[dict], hols: set[dt.date], max_starts: int = MAX_STARTS, window: tuple[dt.time, dt.time] = WINDOW) -> tuple[str, str]:
    """('start' | 'wait', why). `runs`: the recorder's runs as `gh run list --json status,conclusion,createdAt,event` gives them."""
    now = now.astimezone(IST)
    day = now.date()
    if day.weekday() >= 5 or day in hols:
        return "wait", f"{day} is not an NSE trading day"
    if not (window[0] <= now.time() < window[1]):
        return "wait", f"{now:%H:%M} IST is outside the start window {window[0]:%H:%M}–{window[1]:%H:%M}"
    if any(r.get("status") in ACTIVE for r in runs):
        return "wait", "the desk is already queued or running"
    today = [r for r in runs if _ist(r["createdAt"]).date() == day]
    if any(r.get("conclusion") == "cancelled" for r in today):
        return "wait", "a run today was cancelled: the desk was stopped on purpose, so it stays stopped"
    if any(r.get("conclusion") == "success" for r in today):
        return "wait", "today's session is already covered"
    if len(today) >= max_starts:
        return "wait", f"{len(today)} runs today and none succeeded: not starting again (look at the logs)"
    return "start", "no run today yet" if not today else f"today's run failed ({len(today)} so far): starting again"


def fx_due(now: dt.datetime, runs: list[dict]) -> tuple[bool, str]:
    """(start?, why) for the FX minute bars: Tue to Sat, 04:05 to 11:00 IST, until one run of today has succeeded (at most three starts)."""
    now = now.astimezone(IST)
    if now.date().weekday() not in (1, 2, 3, 4, 5):
        return False, f"{now.date()}: no FX day has just closed"
    if not (FX_WINDOW[0] <= now.time() < FX_WINDOW[1]):
        return False, f"{now:%H:%M} IST is outside the FX window {FX_WINDOW[0]:%H:%M}-{FX_WINDOW[1]:%H:%M}"
    if any(r.get("status") in ACTIVE for r in runs):
        return False, "an FX run is already queued or running"
    today = [r for r in runs if _ist(r["createdAt"]).date() == now.date()]
    if any(r.get("conclusion") == "success" for r in today):
        return False, "today's FX bars are already collected"
    if len(today) >= FX_MAX_STARTS:
        return False, f"{len(today)} FX runs today and none succeeded: not starting again (look at the logs)"
    return True, "due" if not today else f"today's FX run failed ({len(today)} so far): starting again"


def news_due(now: dt.datetime, runs: list[dict], hols: set[dt.date] | None = None) -> tuple[bool, str]:
    """(start?, why) for the news digest job: around the clock, every day (`hols` is kept for the callers and ignored). `runs`: news.yml's runs as `gh run list --json status,conclusion,createdAt,event` gives them."""
    now = now.astimezone(IST)
    if any(r.get("status") in ACTIVE for r in runs):
        return False, "a digest is already queued or running"
    if runs and now - max(_ist(r["createdAt"]) for r in runs) < NEWS_EVERY:
        return False, "the last digest was started less than eight minutes ago"
    return True, "due"


def next_wake(now: dt.datetime, hols: set[dt.date]) -> dt.datetime:
    """The next trading day's WAKE at or after `now` (IST)."""
    now = now.astimezone(IST)
    day = now.date() if now.time() < WAKE else now.date() + dt.timedelta(days=1)
    while day.weekday() >= 5 or day in hols:
        day += dt.timedelta(days=1)
    return dt.datetime.combine(day, WAKE, tzinfo=IST)


def arm(now: dt.datetime, runs: list[dict], waiters: list[dict], hols: set[dt.date]) -> tuple[str, str, dt.datetime | None]:
    """('arm' | 'wait', why, wake time). `runs`: the recorder's runs; `waiters`: wake.yml runs (same shape)."""
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
                                     text=True, timeout=120).stdout or "[]")


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
    started = False
    for wf, limit in ((KITE_WORKFLOW, KITE_MAX_STARTS), (STOCK_WORKFLOW, STOCK_MAX_STARTS), (PAPER_WORKFLOW, PAPER_MAX_STARTS), (WORKFLOW, MAX_STARTS)):
        try:
            wf_runs = _runs(wf)
        except (subprocess.SubprocessError, OSError, ValueError):                 # a hung or missing gh, a bad answer: for the extra recorders never fatal
            if wf == WORKFLOW and WINDOW[0] <= now.time() < WINDOW[1]:            # (the scheduler now runs around the clock: only a failure inside the start window is worth failing the run)
                raise
            if wf == WORKFLOW:
                runs = []
            print(f"{wf}: could not list its runs; not starting it")          # the Kite recorder never holds up the main one
            continue
        action, why = decide(now, wf_runs, hols, limit, PAPER_WINDOW if wf == PAPER_WORKFLOW else WINDOW)
        print(f"{wf}: {action}: {why}")
        if action == "start":
            try:
                subprocess.run(["gh", "workflow", "run", wf, "--ref", "main"], check=(wf == WORKFLOW), timeout=120)
                print(f"dispatched {wf}")
            except (subprocess.SubprocessError, OSError):
                if wf == WORKFLOW:
                    raise
                print(f"{wf}: could not be dispatched; the main recorder goes on")
            started = started or wf == WORKFLOW
        if wf == WORKFLOW:
            runs = wf_runs
    for extra, due in ((NEWS_WORKFLOW, lambda r: news_due(now, r, hols)), (FX_WORKFLOW, lambda r: fx_due(now, r))):
        try:                                                                 # news (every tick, around the clock) and the FX bars (each morning): nothing here can hold up or fail the desk
            if extra == FX_WORKFLOW and not (FX_WINDOW[0] <= now.time() < FX_WINDOW[1] and now.weekday() in (1, 2, 3, 4, 5)):
                continue
            go, why = due(_runs(extra))
            print(f"{extra}: {'start' if go else 'wait'}: {why}")
            if go:
                subprocess.run(["gh", "workflow", "run", extra, "--ref", "main"], check=True, timeout=120)
                print(f"dispatched {extra}")
        except Exception as e:                                               # noqa: BLE001 - an extra job must never fail the scheduler, whatever goes wrong
            print(f"{extra}: could not be checked or started ({type(e).__name__}); the desk goes on")
    if started:
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
