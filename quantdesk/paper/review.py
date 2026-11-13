"""The session review: what the paper account did on each trading day, worked out from its own hash-chained ledger. PAPER MONEY ONLY.

The runner puts it in the state it already sends the relay every few seconds (`Runner.summary`), so the app's Positions tab shows today's review as the session goes and
the last few sessions after it, and the Cloudflare watchdog pushes today's figures to the owner's phone after the close (deploy/cloudflare/watchdog.js, W18). It is NOT
published to GitHub: this repository is public, and the account (every thesis and result) stays on the private relay unless the owner chooses otherwise.

Every figure comes from the ledger by replaying it: the profit a closing fill made is the change in the account's realized profit across that one row, so the review
can never disagree with the account. Today's whole-day result (realized plus the change in what is still held) is the account's own equity against its day-start equity;
an earlier day's is shown as realized minus fees only, because the ledger does not keep a day's closing marks, and the review says so rather than invent them.
"""
from __future__ import annotations

import datetime as dt
import json

from ..core.types import Instrument
from .account import FILL_KINDS, Account

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
DAYS = 4                       # earlier sessions kept besides today
MAX_FILLS = 25                 # per day, newest kept
THESIS = 160                   # characters of a thesis shown with a fill
MAX_CHARS = 24000              # the reviews' share of the relay's 60,000-character state: older days go first
CLOSING = ("sell", "btc", "settle")
EVENTS = {"daily_cap_hit": "The daily loss limit was hit: entries stopped and the desk flattened", "halt_set": "The drawdown halt was switched on",
          "halt_cleared": "The drawdown halt was cleared"}


def _ist(ts) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(ts))
    except ValueError:
        return None
    return t.astimezone(IST) if t.tzinfo is not None else None             # the ledger's times are UTC: every day and clock time here is IST


def _r(x, d=2):
    return round(float(x), d)


def session_reviews(account: Account, now: dt.datetime, equity: float | None, clean=lambda s: s) -> list[dict]:
    """[{day, today, fills, closes, wins, losses, realized, fees, net, best, worst, events, equity_change?, opened, still_open}] newest first: today (always, even with nothing
    done) and the DAYS sessions before it that have any row. `clean` takes the runner's own markers out of a thesis."""
    s = Account(account.capital0)
    days: dict[str, dict] = {}
    for row in account.ledger:
        at = _ist(row.get("ts"))
        if at is None:
            continue
        day, hhmm = at.date().isoformat(), at.strftime("%H:%M")
        d = days.setdefault(day, {"day": day, "fills": [], "realized": 0.0, "fees": 0.0, "closes": 0, "wins": 0, "losses": 0, "events": [], "opened": []})
        kind = row.get("kind")
        if kind in FILL_KINDS:
            before = s.realized
            s.apply_fill(kind, Instrument.from_dict(row["instrument"]), row["segment"], row["qty"], row["price"], row["fees"], row["ts"], row["strategy"], row["thesis"], row.get("slip"))
            pnl = s.realized - before if kind in CLOSING else None
            d["realized"] += pnl or 0.0
            d["fees"] += float(row.get("fees") or 0.0)
            if kind in CLOSING:
                d["closes"] += 1
                net = pnl - float(row.get("fees") or 0.0)
                d["wins" if net > 0 else "losses"] += 1
            elif row.get("symbol") not in d["opened"]:
                d["opened"].append(row.get("symbol"))
            d["fills"].append({"t": hhmm, "kind": kind, "symbol": row.get("symbol"), "qty": row.get("qty"), "price": _r(row.get("price") or 0.0),
                               "fees": _r(row.get("fees") or 0.0), "pnl": None if pnl is None else _r(pnl), "strategy": row.get("strategy"),
                               "thesis": clean(row.get("thesis") or "")[:THESIS]})
        else:
            s.record_event(kind, row["ts"], **{k: v for k, v in row.items() if k not in ("seq", "ts", "kind", "prev", "hash")})
            if kind in EVENTS:
                d["events"].append(f"{hhmm} {EVENTS[kind]}")
    today = now.astimezone(IST).date().isoformat()
    days.setdefault(today, {"day": today, "fills": [], "realized": 0.0, "fees": 0.0, "closes": 0, "wins": 0, "losses": 0, "events": [], "opened": []})
    out = []
    for day in sorted(days, reverse=True)[:DAYS + 1]:
        d = days[day]
        closes = [f for f in d["fills"] if f["pnl"] is not None]
        nets = [f["pnl"] - f["fees"] for f in closes]
        r = {**d, "today": day == today, "realized": _r(d["realized"]), "fees": _r(d["fees"]), "net": _r(d["realized"] - d["fees"]),
             "best": _r(max(nets)) if nets else None, "worst": _r(min(nets)) if nets else None, "n_fills": len(d["fills"]), "fills": d["fills"][-MAX_FILLS:]}
        if day == today:
            if equity is not None and account.day == today and account.day_start is not None:
                r["equity_change"] = _r(equity - account.day_start)            # realized, fees and the change in what is still held, all together
            r["still_open"] = sorted(account.positions)
        out.append(r)
    while len(out) > 1 and len(json.dumps(out)) > MAX_CHARS:                   # the relay's cap on the whole state is never risked by the review: older days go first
        out.pop()
    return out
