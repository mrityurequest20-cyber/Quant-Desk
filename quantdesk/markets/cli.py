"""python -m quantdesk markets today|plan [--date YYYY-MM-DD] [--trading]

  today  which segments trade on the day, their hours, and whether each calendar is verified
  plan   the chained jobs that cover the day (JSON, for the workflow that starts them)
"""
from __future__ import annotations

import datetime as dt
import json

from . import sessions as S


def add_parser(sub) -> None:
    s = sub.add_parser("markets", help="the market map (quantdesk/markets): which segments trade when, and the day's chained jobs (reads only)")
    s.add_argument("action", choices=["today", "plan"])
    s.add_argument("--date", help="the day (YYYY-MM-DD, IST; default today)")
    s.add_argument("--trading", action="store_true", help="count only segments whose holiday calendar is verified for that year")
    s.set_defaults(fn=run)


def run(cfg, a) -> None:
    day = dt.date.fromisoformat(a.date) if a.date else dt.datetime.now(S.IST).date()
    cal = S.Calendars(cfg)
    if a.action == "plan":
        print(json.dumps(S.plan_jobs(day, cal, trading=a.trading), indent=2))
        return
    print(f"{day:%a %d %b %Y} (US daylight saving {'on' if S.us_dst(day) else 'off'})")
    for key, seg in S.SEGMENTS.items():
        s = S.session(key, day, cal, a.trading)
        verified = "calendar verified" if cal.known(key, day) else "calendar NOT verified (records, does not trade)"
        print(f"  {key:8s} {seg.name:28s} " + (f"{s[0]:%H:%M}-{s[1]:%H:%M}" if s else "closed       ") + f"   {verified}")
