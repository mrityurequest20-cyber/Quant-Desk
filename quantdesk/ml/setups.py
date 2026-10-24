"""The labelled-setup counter (P0.7 of docs/ML_PHASE0.md). **Design level: nothing produces these records yet.**

The entry filter (M4) needs about 300 to 500 *labelled setups*: a setup the desk saw (live in the Shadow stage, or replayed offline) whose outcome is now
known. This module defines the record of one such setup, validates it, and counts them per week and toward that target, in one line for the Saturday
digest. A record is the `data` of a journal event of category `setup_labelled`; this module does not import the journal and no emitter exists: the Shadow
stage of the scope ladder, and the replay that labels past setups, are later, separately reviewed changes. Until then the line honestly reads zero.

Counting rules, so the number cannot flatter itself: a setup counts once however many times it was recorded (by `setup_id`); a record that fails validation
is not counted and is reported; a setup counts in the week of its **label date** (when its outcome became known), because that is when it became usable;
and the unit of statistics stays the session, so the line also gives the number of distinct sessions the setups come from.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

CATEGORY = "setup_labelled"
SOURCES = ("shadow", "replay")
TARGET = (300, 500)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,95}")


class BadSetup(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


def _ts(x):
    try:
        t = datetime.fromisoformat(str(x))
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _finite(x) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:
        return False


def check_setup(rec) -> list[str]:
    """Every reason `rec` is not a labelled setup (empty if none)."""
    if not isinstance(rec, dict):
        return ["a setup record must be an object"]
    p: list[str] = []
    for k in ("setup_id", "source", "symbol", "session", "ts", "labelled_at", "outcome"):
        if k not in rec or rec[k] in (None, ""):
            p.append(f"missing {k}")
    if p:
        return p
    if not (isinstance(rec["setup_id"], str) and _ID.fullmatch(rec["setup_id"])):
        p.append("setup_id must be a short identifier (letters, digits, _ . : / -)")
    if rec["source"] not in SOURCES:
        p.append(f"source must be one of {SOURCES}")
    if not (isinstance(rec["symbol"], str) and rec["symbol"].strip()):
        p.append("symbol must be non-blank text")
    ts, lt = _ts(rec["ts"]), _ts(rec["labelled_at"])
    if ts is None or lt is None:
        p.append("ts and labelled_at must be ISO timestamps with a zone")
    elif lt <= ts:
        p.append("labelled_at must be after ts: an outcome cannot be known before the setup")
    try:
        sd = date.fromisoformat(rec["session"]) if isinstance(rec["session"], str) and len(rec["session"]) == 10 else None
    except ValueError:
        sd = None
    if sd is None:
        p.append("session must be a real YYYY-MM-DD date")
    elif ts is not None and sd != ts.date():
        p.append("session must be the date of ts (in ts's own zone)")
    if not _finite(rec["outcome"]):
        p.append("outcome must be a finite number (the label)")
    return p


def validate(rec) -> dict:
    problems = check_setup(rec)
    if problems:
        raise BadSetup(problems)
    return rec


def week_start(d: date) -> date:
    """The Monday of the week containing `d`."""
    return d - timedelta(days=d.weekday())


def count(records, today: date) -> dict:
    """The counts the digest needs. Records are validated one by one; duplicates by `setup_id` count once (the first); invalid ones are listed, not counted."""
    seen, good, bad = set(), [], []
    for i, r in enumerate(records):
        problems = check_setup(r)
        if problems:
            bad.append({"index": i, "problems": problems})
            continue
        if r["setup_id"] in seen:
            continue
        seen.add(r["setup_id"])
        good.append(r)
    wk = week_start(today)
    by_week: dict[str, dict[str, int]] = {}
    for r in good:
        w = str(week_start(_ts(r["labelled_at"]).date()))
        by_week.setdefault(w, {s: 0 for s in SOURCES})[r["source"]] += 1
    this = by_week.get(str(wk), {s: 0 for s in SOURCES})
    total = len(good)
    return {"total": total, "this_week": sum(this.values()), "this_week_by_source": this, "week_start": str(wk), "by_week": dict(sorted(by_week.items())),
            "sessions": len({r["session"] for r in good}), "target": TARGET, "progress_low": total / TARGET[0], "progress_high": total / TARGET[1],
            "invalid": bad, "duplicates_ignored": len(records) - len(good) - len(bad)}


def digest_line(records, today: date) -> str:
    """One line for the Saturday digest."""
    c = count(records, today)
    s = c["this_week_by_source"]
    line = (f"Labelled setups: {c['this_week']} this week (shadow {s['shadow']}, replay {s['replay']}); {c['total']} in total from {c['sessions']} sessions, "
            f"{c['total'] / TARGET[0]:.0%} of the {TARGET[0]} the entry filter needs at least ({TARGET[0]} to {TARGET[1]}).")
    if c["invalid"]:
        line += f" {len(c['invalid'])} record(s) failed validation and are not counted."
    return line


def from_events(events) -> list:
    """The setup records inside journal events (dicts with `category` and `data`): the events of category `setup_labelled`, their payloads, in order."""
    out = []
    for ev in events:
        if isinstance(ev, dict) and ev.get("category") == CATEGORY and isinstance(ev.get("data"), dict):
            out.append(ev["data"])
    return out
