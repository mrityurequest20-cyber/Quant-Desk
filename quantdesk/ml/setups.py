"""The labelled-setup counter (P0.7 of docs/ML_PHASE0.md).

The entry filter (M4) needs about 300 to 500 *labelled setups*: a setup the desk saw whose outcome is now known. Three kinds exist, and the counter says
which is which:

* `paper`: a paper trade the desk took and closed: its label is the trade's R multiple (journal table `trades`, status `closed`, a finite `r_multiple`).
* `replay`: an armed setup the EV gate refused, replayed afterwards on the bars that followed and graded (`intraday/learning.py: grade_armed`; the journal's
  `decisions` rows whose detail says the entry level was reached, and whose key `ts|symbol|strategy` is in the learning memory's graded list). Its label is known
  once its 45-minute window has closed; the value of the label is kept only as an aggregate in the memory, so a replay setup counts but carries no outcome here.
* `shadow`: a setup the engine journals on an instrument in the Shadow stage of the scope ladder. **That stage does not exist yet**; the source is reserved and the
  count of it is zero until the stage is built (a separate, reviewed change).

Counting rules, so the number cannot flatter itself: a setup counts once however many times it was recorded (by `setup_id`); a replay setup that re-arms the same symbol and strategy within
its 45-minute window is the same idea and counts once, and so does one that fired as a paper trade on the same symbol within the window (counted there); a record that fails validation is
not counted and is reported; a setup counts in the week of its **label date** (when its outcome became known); and the unit of statistics stays the session, so the
line also gives the number of distinct sessions the setups come from. Trades on the same day move together, so 300 setups from 40 sessions are not 300 independent
samples; the line shows both.

Everything here is read-only and imports nothing from the desk: `from_journal` opens the journal file read-only with `sqlite3` and reads the memory as JSON.
`line` is what the Saturday digest shows; the site export publishes it in `data.json` (`setups`) and the watchdog's W8 digest reads it from there.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CATEGORY = "setup_labelled"
SOURCES = ("paper", "replay", "shadow")
TARGET = (300, 500)
REPLAY_HORIZON_MIN = 45                                       # learning.grade_armed(horizon=45): the label is known when this window has closed
ARMED_MARK = "reached its level"                              # learning.grade_armed's filter on a decision's detail
IST = timezone(timedelta(hours=5, minutes=30))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/|+-]{0,127}")


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
    """Every reason `rec` is not a labelled setup (empty if none). `outcome` is required except for a `replay` setup, whose value lives in the memory's aggregate."""
    if not isinstance(rec, dict):
        return ["a setup record must be an object"]
    p: list[str] = []
    need = ("setup_id", "source", "symbol", "session", "ts", "labelled_at") + (() if rec.get("source") == "replay" else ("outcome",))
    for k in need:
        if k not in rec or rec[k] in (None, ""):
            p.append(f"missing {k}")
    if p:
        return p
    if not (isinstance(rec["setup_id"], str) and _ID.fullmatch(rec["setup_id"])):
        p.append("setup_id must be a short identifier (letters, digits, _ . : / | + -)")
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
    if rec.get("outcome") is not None and not _finite(rec["outcome"]):
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
        w = str(week_start(_ts(r["labelled_at"]).astimezone(IST).date()))
        by_week.setdefault(w, {s: 0 for s in SOURCES})[r["source"]] += 1
    this = by_week.get(str(wk), {s: 0 for s in SOURCES})
    total = len(good)
    by_source = {s: sum(1 for r in good if r["source"] == s) for s in SOURCES}
    return {"total": total, "by_source": by_source, "this_week": sum(this.values()), "this_week_by_source": this, "week_start": str(wk),
            "by_week": dict(sorted(by_week.items())), "sessions": len({r["session"] for r in good}),
            "session_symbols": len({(r["session"], r["symbol"]) for r in good}), "target": TARGET, "progress_low": total / TARGET[0],
            "progress_high": total / TARGET[1], "invalid": bad, "duplicates_ignored": len(records) - len(good) - len(bad)}


def line(c: dict, notes: list | None = None) -> str:
    """The one line for the Saturday digest, from `count`'s result. A count that could not be read is not shown as zero: the line says it is not available."""
    notes = list(notes or [])
    if notes and c["total"] == 0:
        return f"Labelled setups: not available ({notes[0]})."
    s = c["this_week_by_source"]
    out = (f"Labelled setups: {c['this_week']} this week from the Monday {c['week_start']} (paper {s['paper']}, replay {s['replay']}, shadow {s['shadow']}); {c['total']} counted in total, "
           f"from {c['sessions']} sessions and {c.get('session_symbols', c['sessions'])} session-symbol pairs (setups on one day move together, so they are not independent samples); "
           f"{c['total'] / TARGET[0]:.0%} of the {TARGET[0]} the entry filter needs at least ({TARGET[0]} to {TARGET[1]}).")
    if c["invalid"]:
        out += f" {len(c['invalid'])} record(s) failed validation and are not counted."
    if notes:
        out += " Not fully counted: " + "; ".join(notes) + "."
    return out


def digest_line(records, today: date) -> str:
    return line(count(records, today))


def from_events(events) -> list:
    """The setup records inside journal events (dicts with `category` and `data`): the events of category `setup_labelled`, their payloads, in order. The producer
    of such events is the Shadow stage, which does not exist yet."""
    return [ev["data"] for ev in events if isinstance(ev, dict) and ev.get("category") == CATEGORY and isinstance(ev.get("data"), dict)]


# ---- the journal ------------------------------------------------------------------------------------------------------------------------------
def _aware(x):
    """A journal timestamp as an aware datetime; a naive one is the desk's own clock, India Standard Time."""
    try:
        t = datetime.fromisoformat(str(x).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo is not None else t.replace(tzinfo=IST)


def _sid(prefix: str, raw) -> str:
    return re.sub(r"[^A-Za-z0-9_.:/|+-]", "_", f"{prefix}:{raw}")[:128]


def _trade_record(row) -> dict | None:
    tid, opened, closed, r = row
    o, c = _aware(opened), _aware(closed)
    if o is None or c is None or not _finite(r):
        return None
    return {"setup_id": _sid("trade", tid), "source": "paper", "symbol": "", "session": str(o.date()), "ts": o.isoformat(), "labelled_at": c.isoformat(), "outcome": float(r)}


def from_journal(journal_db, memory_json, notes: list | None = None, stats: dict | None = None) -> list[dict]:
    """The labelled setups of one account, read-only: its closed trades (journal) and its graded armed setups (the learning memory's list of graded keys that the
    journal's decisions still hold). `notes` collects what could not be read; nothing here raises on a missing or unreadable file, because a digest must still go out."""
    notes = notes if notes is not None else []
    stats = stats if stats is not None else {}
    out: list[dict] = []
    jp = Path(journal_db)
    if not jp.exists():
        notes.append(f"no journal at {jp.name}")
        return out
    try:
        db = sqlite3.connect(f"file:{jp.resolve()}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        notes.append(f"journal not readable ({type(exc).__name__})")
        return out
    try:
        for tid, symbol, opened, closed, r in db.execute("SELECT id, symbol, opened_at, closed_at, r_multiple FROM trades WHERE status = 'closed'"):
            rec = _trade_record((tid, opened, closed, r))
            if rec is not None:
                rec["symbol"] = str(symbol or "")
                out.append(rec)
            else:
                stats["trades_skipped"] = stats.get("trades_skipped", 0) + 1            # a closed trade without a usable R or dates carries no label
        graded: set = set()
        try:
            graded = set(json.loads(Path(memory_json).read_text(encoding="utf-8"))["graded"]["armed"])
        except (OSError, ValueError, KeyError, TypeError):
            notes.append("the learning memory could not be read, so replay setups are not counted")
        if graded:
            rows = list(db.execute("SELECT ts, symbol, strategy, detail FROM decisions WHERE detail LIKE ?", (f"%{ARMED_MARK}%",)))     # fetched whole: the read lock is released at once
            cands = []
            for ts, symbol, strategy, detail in rows:
                t = _aware(ts)
                if f"{ts}|{symbol}|{strategy}" in graded and t is not None:
                    cands.append((t, str(symbol or ""), str(strategy or "")))
            horizon = timedelta(minutes=REPLAY_HORIZON_MIN)
            opened = {}
            for rec in out:                                                              # paper trades: when each symbol's trades opened
                if rec["source"] == "paper":
                    opened.setdefault(rec["symbol"], []).append(_ts(rec["ts"]))
            last: dict = {}
            collapsed = 0
            for t, symbol, strategy in sorted(cands):
                prev = last.get((symbol, strategy))
                if prev is not None and t - prev < horizon:                              # the engine re-arms the same level every minute: one idea is one setup until its window has closed
                    collapsed += 1
                    continue
                last[(symbol, strategy)] = t
                if any(o is not None and t - horizon <= o <= t + horizon for o in opened.get(symbol, ())):
                    collapsed += 1                                                       # the same idea fired and closed as a paper trade: counted there
                    continue
                out.append({"setup_id": _sid("armed", f"{t.isoformat()}|{symbol}|{strategy}"), "source": "replay", "symbol": symbol, "session": str(t.date()),
                            "ts": t.isoformat(), "labelled_at": (t + horizon).isoformat(), "outcome": None})
            stats["replay_collapsed"] = collapsed
    except sqlite3.Error as exc:
        notes.append(f"journal query failed ({type(exc).__name__})")
    finally:
        db.close()
    return out


def block(journal_db, memory_json, today: date) -> dict:
    """What the site export publishes in `data.json` as `setups`: the digest line, the counts, and what could not be read (fixed phrases only: this goes on a public site)."""
    notes: list = []
    stats: dict = {}
    c = count(from_journal(journal_db, memory_json, notes, stats), today)
    if stats.get("trades_skipped"):
        notes.append(f"{stats['trades_skipped']} closed trade(s) without a usable R multiple are not counted")
    return {"line": line(c, notes), "total": c["total"], "this_week": c["this_week"], "week_start": c["week_start"], "sessions": c["sessions"],
            "session_symbols": c["session_symbols"], "by_source": c["by_source"], "target": list(TARGET), "invalid": len(c["invalid"]), "notes": notes,
            "replay_collapsed": stats.get("replay_collapsed", 0)}
