"""A daily check that the OI shadow's tape can be graded (docs/prereg/oi_shadow_v1.json, `deployment`).

The spec has the desk engineer run `ml oi` after each close and leaves a missing session visible, never silently dropped. This module is the same
command run for every forward weekday so far, on a fresh machine, so a session that was not archived, or that no longer grades, shows up the day
it happens and not at the read-out. It adds nothing to the live process and changes no definition, no table the read-out uses and no rule of the test:

- the tables it writes go to a scratch folder and are thrown away with the machine; the tables that count are the ones `ml oi` writes, and they are
  reproducible from the archive by the same command (that is the spec's own rule). Nothing graded here is read by `oi-report` unless someone points it there;
- a weekday without a tape is "holiday" if the NSE list in config/quantdesk.yaml says so, "unknown" if that list does not cover the year, and "missing" otherwise;
  "missing", "partial" (only the morning part archived, or an index with nothing to grade) and "failed" make the run fail; "unknown" prints a warning annotation. Nothing is ever dropped: a missing day stays on the list every day until it is graded.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from . import oi as OI


def forward_weekdays(today) -> list[str]:
    """Every weekday from the first forward session (inclusive) to `today` (inclusive)."""
    end = pd.Timestamp(today).normalize()
    return [str(d.date()) for d in pd.bdate_range(OI.FORWARD_START, end)] if end >= pd.Timestamp(OI.FORWARD_START) else []


def exchange_holidays():
    """The NSE list in config/quantdesk.yaml (one place to replace in a test: `oi.exchange_holidays` is part of the code the spec hashes)."""
    return OI.exchange_holidays()


def _holiday_status(day: str) -> str:
    holidays, years = exchange_holidays()
    if day in holidays:
        return "holiday"
    return "missing" if pd.Timestamp(day).year in years else "unknown"


def grade_all(source: Path, out: Path, today, say=print, grade=OI.run_day) -> dict:
    """Grade every forward weekday up to `today` whose tape is in `source`. Returns `{"days": [{day, status, ...}], "failed", "missing", "partial", "unknown": [...], "ok": bool}`."""
    rows = []
    for day in forward_weekdays(today):
        if not OI.tape_files(Path(source), day):
            rows.append({"day": day, "status": _holiday_status(day)})
            continue
        try:
            man = grade(Path(source), day, Path(out))
        except Exception as exc:                                            # any reason a session does not grade is a finding, not a crash
            rows.append({"day": day, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        names = [f.name for f in OI.tape_files(Path(source), day)]
        morning, afternoon = any("_morning-" in n for n in names), any("_afternoon-" in n for n in names)
        thin = [u for u in OI.INDICES if man["rows"].get(u, 0) == 0 or man["usable60"].get(u, 0) == 0]
        if (morning and not afternoon) or thin:                            # an unarchived afternoon part, or an index with nothing to grade, is not a graded session
            why = ("only the morning part is archived" if morning and not afternoon else "") + (" " if morning and not afternoon and thin else "") \
                  + (f"no gradable decisions for {', '.join(thin)}" if thin else "")
            rows.append({"day": day, "status": "partial", "why": why, "rows": man["rows"], "usable60": man["usable60"]})
            continue
        rows.append({"day": day, "status": "graded", "rows": man["rows"], "usable60": man["usable60"],
                     "quarantined": {u: q["quarantined"] for u, q in man["quarantine"].items()},
                     "snapshots": {u: q["snapshots"] for u, q in man["quarantine"].items()}})
    failed = [r["day"] for r in rows if r["status"] == "failed"]
    missing = [r["day"] for r in rows if r["status"] == "missing"]
    partial = [r["day"] for r in rows if r["status"] == "partial"]
    unknown = [r["day"] for r in rows if r["status"] == "unknown"]
    for r in rows:
        extra = (f" rows {r['rows']} usable at 60 min {r['usable60']} quarantined {r['quarantined']}" if r["status"] == "graded"
                 else f" {r['error']}" if r["status"] == "failed" else f" {r['why']}" if r["status"] == "partial" else "")
        say(f"{r['day']} {r['status']}{extra}")
    graded = sum(1 for r in rows if r["status"] == "graded")
    if unknown:                                                             # a green run must not be a blind one: GitHub shows this as an annotation
        say(f"::warning::{len(unknown)} weekday(s) have no tape and the holiday list in config/quantdesk.yaml does not cover their year, so they cannot be told from holidays: {unknown[0]} ...")
    say(f"{graded} graded, {len(failed)} failed, {len(missing)} missing, {len(partial)} partial, "
        f"{sum(1 for r in rows if r['status'] == 'holiday')} holidays, {sum(1 for r in rows if r['status'] == 'unknown')} not covered by the holiday list")
    return {"days": rows, "failed": failed, "missing": missing, "graded": graded, "partial": partial, "unknown": unknown, "ok": not failed and not missing and not partial,
            "run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
