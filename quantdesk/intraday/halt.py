"""What a session inherits that no open journal trade accounts for, and the owner's halt on it (H-02, H-03).

Owner decision ("flag + manual"): at session start the desk looks for

* an orphan broker leg: a position the paper broker holds that today's open journal trades don't account for
  (an entry cut short after its first fill, a hand-edited broker.json);
* a trade carried over from another day: still open in the journal (or in `intraday_open`) though it was opened
  before today, including one whose exit got stuck (`exit_pending`);
* an expired leg the broker still holds: never settled.

Each one is named exactly (instrument, quantity, since when) in a CRITICAL event and halts new entries. The halt is
kept in the journal's state (`intraday_halt`), so it survives a restart, the hand-over and the next day, until the
owner clears it with `quantdesk intraday clear-halt --reason "…"`. Clearing refuses while the mismatch is still there,
unless `--force` is given; a forced clear accepts exactly the legs and trades outstanding at that moment, so the same
mismatch doesn't halt again but any change to it does. Nothing here closes, adopts or settles anything.
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

HALT_KEY = "intraday_halt"              # the active halt: None/absent when entries are not held by it
CLEARED_KEY = "intraday_halt_cleared"   # every clear: who, why, when, and what a forced clear accepted as is
ACCEPTED_KEY = "intraday_halt_accepted"  # what the last forced clear accepted and is still there (pruned when it goes)
CLEAR_CMD = 'quantdesk intraday clear-halt --reason "…"'


def book_diff(open_trades, positions: dict) -> tuple[dict[str, int], dict[str, int]]:
    """(what the journal's open trades hold, what the broker holds), per instrument, zero quantities left out."""
    want: dict[str, int] = {}
    for t in open_trades:
        for leg in t.legs:
            want[leg.instrument.symbol] = want.get(leg.instrument.symbol, 0) + int(leg.qty)
    have = {sym: int(p.get("qty", 0)) for sym, p in (positions or {}).items() if int(p.get("qty", 0))}
    return {k: v for k, v in want.items() if v}, have


def leg_key(sym: str, journal_qty: int, broker_qty: int) -> str:
    return f"leg:{sym}:{journal_qty:+d}:{broker_qty:+d}"


def accepted(journal) -> dict:
    """The mismatch the owner's last clear accepted as is (forced) and that is still there: {key: who/why/when}."""
    acc = journal.get_state(ACCEPTED_KEY) or {}
    return {k: acc for k in acc.get("keys") or []}


def prune_accepted(journal, present: set) -> None:
    """An accepted leg or trade that has gone stays gone: if it ever came back, it would halt again."""
    acc = journal.get_state(ACCEPTED_KEY)
    if acc and set(acc.get("keys") or []) - present:
        keep = [k for k in acc["keys"] if k in present]
        journal.set_state(ACCEPTED_KEY, {**acc, "keys": keep} if keep else None)


def journal_open(journal, day: dt.date) -> list:
    """Today's open trades as the journal's `intraday_open` state has them (what a restart would restore)."""
    from ..journal.journal import trade_from_dict
    st = journal.get_state("intraday_open") or {}
    return [trade_from_dict(d) for d in st.get("trades") or []] if st.get("day") == str(day) else []


def _carried(journal, day: dt.date) -> dict[str, dict]:
    """Trades opened before `day` that were never closed: the last session's saved open trades, and any trade the
    journal still lists as open from an earlier day (the saved state is overwritten by the next session)."""
    out: dict[str, dict] = {}
    st = journal.get_state("intraday_open") or {}
    if st.get("day") and st.get("day") != str(day):
        for d in st.get("trades") or []:
            out[d["id"]] = {"id": d["id"], "strategy": d.get("strategy"), "symbol": d.get("symbol"),
                            "opened_at": str(d.get("opened_at")), "legs": d.get("legs") or [], "meta": d.get("meta") or {},
                            "from_day": st.get("day")}
    rows = journal.df("SELECT id, strategy, symbol, opened_at, legs, meta FROM trades WHERE status='open' ORDER BY opened_at")
    for r in rows.itertuples():
        if str(r.opened_at)[:10] >= str(day) or r.id in out:
            continue
        out[r.id] = {"id": r.id, "strategy": r.strategy, "symbol": r.symbol, "opened_at": str(r.opened_at),
                     "legs": json.loads(r.legs or "[]"), "meta": json.loads(r.meta or "{}"), "from_day": str(r.opened_at)[:10]}
    return out


def _ts(x) -> str:
    try:
        return f"{pd.Timestamp(x):%Y-%m-%d %H:%M}"
    except (ValueError, TypeError):
        return str(x)


def inherited(journal, positions: dict, day: dt.date, open_trades, first_seen=None) -> list[dict]:
    """Every orphan leg, carried trade and unsettled expired leg the session at `day` inherits, each with a stable
    `key` and a `detail` naming it exactly. Empty when the broker and today's journal agree and nothing is carried."""
    want, have = book_diff(open_trades, positions)
    carried = _carried(journal, day)
    leg_of = {}                                           # instrument → the carried trade it belongs to
    for c in carried.values():
        for l in c["legs"]:
            if l.get("exit_price") is None:
                leg_of[l["instrument"]["symbol"]] = c
    prev = {i["key"]: i for i in ((journal.get_state(HALT_KEY) or {}).get("items") or [])}
    items = []
    for c in carried.values():
        legs = ", ".join(f"{l['instrument']['symbol']} {int(l['qty']):+d}" for l in c["legs"] if l.get("exit_price") is None)
        stuck = (c["meta"] or {}).get("exit_pending")
        items.append({
            "key": f"trade:{c['id']}", "kind": "carried", "trade": c["id"], "symbol": c["symbol"],
            "since": c["opened_at"], "legs": legs, "exit_pending": stuck,
            "detail": (f"carried trade {c['id']} ({c['strategy']} {c['symbol']}; open legs {legs or 'none'}) open since "
                       f"{_ts(c['opened_at'])}, never closed"
                       + (f"; its exit was stuck ({stuck[0]}: {str(stuck[1])[:80]})" if stuck else "")
                       + "; not restored, not closed")})
    for sym in sorted(have):
        h, w = have[sym], want.get(sym, 0)
        inst = (positions[sym] or {}).get("instrument") or {}
        exp = inst.get("expiry")
        expired = bool(exp) and str(exp) < str(day)
        if h == w and not expired:
            continue
        key = leg_key(sym, w, h)
        kind = ", ".join(k for k, on in (("orphan", h != w), ("expired", expired)) if on)
        owner = leg_of.get(sym)
        since = positions[sym].get("since")
        if since:
            since = _ts(since)
        elif owner is not None:
            since = f"{_ts(owner['opened_at'])} (trade {owner['id']})"
        else:
            last = journal.df("SELECT MAX(ts) AS ts FROM fills WHERE symbol=?", (sym,))["ts"].iloc[0]
            if isinstance(last, str) and last:
                since = f"{_ts(last)} (last journal fill)"
            elif key in prev:
                since = prev[key]["since"]
            else:
                since = f"not on record; first seen {_ts(first_seen) if first_seen is not None else day}"
        items.append({
            "key": key, "kind": kind, "symbol": sym, "qty": h, "journal_qty": w, "expiry": exp, "since": since,
            "trade": owner["id"] if owner is not None else None,
            "detail": (f"{kind} leg {sym}: the broker holds {h:+d}, today's open journal trades account for {w:+d}; "
                       f"held since {since}"
                       + (f"; expired {exp}, not settled" if expired else "")
                       + (f"; a leg of carried trade {owner['id']}" if owner is not None else ""))})
    return items


def summary(halt: dict | None) -> str:
    items = (halt or {}).get("items") or []
    if not items:
        return ""
    more = f" (+{len(items) - 1} more)" if len(items) > 1 else ""
    return f"{items[0]['detail'][:160]}{more}"


def clear(journal, positions: dict, day: dt.date, reason: str, by: str, force: bool = False, now=None) -> dict:
    """The owner's one explicit action that lifts the halt. Refuses while anything inherited is still unexplained,
    unless forced; a forced clear accepts exactly what is outstanding now. Recorded as an INFO event and in state."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("a reason is required (--reason \"…\")")
    now = now if now is not None else pd.Timestamp.now(tz="Asia/Kolkata")
    halt = journal.get_state(HALT_KEY)
    if not halt:
        return {"cleared": False, "message": "no halt to clear: entries are not held by an inherited position"}
    items = inherited(journal, positions, day, journal_open(journal, day))
    acc = accepted(journal)
    outstanding = [i for i in items if i["key"] not in acc]
    if outstanding and not force:
        raise ValueError(f"refusing to clear: {len(outstanding)} inherited position(s) still unexplained: "
                         + "; ".join(i["detail"] for i in outstanding)
                         + ". Resolve them first, or add --force to accept them as they are (on the record)")
    keep = [i for i in items if force or i["key"] in acc]
    rec = {"by": by, "reason": reason[:500], "at": str(now), "forced": bool(outstanding),
           "halt": {"raised_at": halt.get("raised_at"), "items": [i["key"] for i in halt.get("items") or []]},
           "accepted": [i["key"] for i in keep], "accepted_items": [i["detail"] for i in keep]}
    msg = f"entry halt cleared by {by}: {reason[:300]}"
    if outstanding:
        msg += f"; forced with {len(outstanding)} still outstanding, accepted as is: " + "; ".join(i["detail"] for i in outstanding)
    journal.event(now, "INFO", "risk", msg[:2000], rec)
    hist = (journal.get_state(CLEARED_KEY) or [])[-49:]
    journal.set_state(CLEARED_KEY, hist + [rec])
    journal.set_state(ACCEPTED_KEY, {"keys": rec["accepted"], "by": by, "reason": rec["reason"], "at": rec["at"]}
                      if rec["accepted"] else None)
    journal.set_state(HALT_KEY, None)
    journal.commit()
    return {"cleared": True, "forced": bool(outstanding), "message": msg, "record": rec}
