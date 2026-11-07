"""The manual paper runner: takes the owner's queued paper orders, one at a time, through the risk gate and the paper broker. Paper money only.

The owner places a paper trade by hand in the app (a written thesis, a strategy name, a contract and a number of lots). The order waits in the
relay's queue; this runner drains it every few seconds during the session. It has NO trading logic of its own: every rule that decides whether a
trade happens, at what price, with what fees and whether it is recorded lives in `risk.py`, `broker.py` and `account.py`. This file only

  * checks the shape of an order (strict, fails closed: anything odd is refused with the reason),
  * turns a contract name on the board into an Instrument (the underlying must be on the paper desk's own list),
  * turns the relay's quote (bid, ask, displayed sizes, age) into the gate's Quote, timed by the relay's clock so the age is the relay's age,
  * runs the gate's brakes each cycle (`update`): the kill switch, the daily loss cap, the drawdown halt and the loss-budget trim all FLATTEN or
    TRIM exactly as the gate says,
  * sells at 15:20 IST whatever expires today (no settlement price is guessed),
  * never fills the same order twice (the order id is written into the ledger row; an order older than `max_age_s` is not executed at all),
  * reports what happened to every order, and the account, back to the relay.

No function here sends an order to a broker or touches real money. There is no credential in this file: the relay tokens come from the environment.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path

from ..core.types import OPTION, Instrument
from ..markets import sessions as MK
from .account import Account, is_number, is_whole_positive
from .broker import PaperBroker
from .risk import Order, Quote, RiskGate

IST = MK.IST
ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
OPT_TAIL = re.compile(r"^(\d{2})(" + "|".join(MONTHS) + r")(\d{2})(\d{1,6})(CE|PE)$")
DONE_RE = re.compile(r"(?:\[order ([A-Za-z0-9_-]{6,64})\]|^exit ([A-Za-z0-9_-]{6,64}):)")
MAX_SKEW_S = 120              # the relay's clock and this machine's may differ by this much; more and nothing is done (a wrong clock must not place a trade)
MAX_ORDER_AGE_S = 120         # an order that waited longer than this is not executed: the owner decided at another price
MARK_MAX_AGE_S = 600          # a held position is marked at its bid only if the quote is this fresh; otherwise its mark is unknown and the gate fails closed
FLATTEN_AT = dt.time(15, 20)  # IST: contracts that expire today are sold at the bid from here (a settlement price is never guessed)
MIN_THESIS = 20
MAX_LOTS = 1000               # a sanity bound on the shape of an order; the risk gate is what limits the size
SEGMENT = "nse_fo"            # this version trades the NSE index options only


def _text(x, lo: int, hi: int) -> bool:
    return isinstance(x, str) and lo <= len(x.strip()) <= hi


def parse_contract(symbol, underlyings, lot_sizes: dict) -> tuple[Instrument | None, str | None]:
    """A board option name (NIFTY12NOV2624500CE) to an Instrument, or (None, why). The underlying must be on the paper desk's list and have a known lot."""
    if not isinstance(symbol, str) or symbol != symbol.strip().upper() or not (8 <= len(symbol) <= 40):
        return None, "the contract name is missing or malformed"
    for u in sorted(underlyings, key=len, reverse=True):
        if not symbol.startswith(u):
            continue
        m = OPT_TAIL.match(symbol[len(u):])
        if not m:
            continue
        try:
            expiry = dt.date(2000 + int(m.group(3)), MONTHS.index(m.group(2)) + 1, int(m.group(1)))
        except ValueError:
            return None, f"{symbol}: the expiry date does not exist"
        lot = lot_sizes.get(u)
        if not (isinstance(lot, int) and lot > 0):
            return None, f"{u} has no known lot size"
        inst = Instrument.option(u, expiry, int(m.group(4)), m.group(5), lot)
        if inst.symbol != symbol:
            return None, f"{symbol} is not in the board's naming"
        return inst, None
    return None, f"{symbol} is not an option on an underlying the paper desk trades ({', '.join(sorted(underlyings))})"


def clean_order(raw) -> tuple[dict | None, str | None]:
    """The shape of an order, strictly. Returns (order, None) or (None, why). Unknown fields are dropped, not trusted."""
    if not isinstance(raw, dict):
        return None, "the order is not an object"
    oid = raw.get("id")
    if not (isinstance(oid, str) and ID_RE.match(oid)):
        return None, "the order id is missing or malformed"
    side = raw.get("side")
    if side not in ("buy", "sell"):
        return None, "side must be buy or sell"
    lots = raw.get("lots")
    if side == "sell" and lots == "all":
        pass
    elif not (is_whole_positive(lots) and lots <= MAX_LOTS):
        return None, f"lots must be a whole number from 1 to {MAX_LOTS}" + (' (or "all" for a sell)' if side == "sell" else "")
    strategy, thesis = raw.get("strategy"), raw.get("thesis")
    if side == "buy":
        if not _text(strategy, 1, 60):
            return None, "a buy needs a strategy name (1 to 60 characters)"
        if not _text(thesis, MIN_THESIS, 1000):
            return None, f"a buy needs a written thesis of at least {MIN_THESIS} characters"
    limit = raw.get("limit")
    if limit is not None and not (is_number(limit) and limit > 0):
        return None, "the limit price must be a number above zero"
    group = raw.get("group")
    if group is not None and not _text(group, 1, 40):
        return None, "the group label is malformed"
    q = raw.get("queued_at")
    return {"id": oid, "side": side, "symbol": raw.get("symbol"), "lots": lots, "strategy": strategy.strip() if isinstance(strategy, str) else None,
            "thesis": thesis.strip() if isinstance(thesis, str) else None, "limit": float(limit) if limit is not None else None,
            "group": group, "queued_at": q if is_number(q) else None}, None


def done_ids(account: Account) -> set[str]:
    """Order ids already written into the ledger (a buy carries `[order <id>]` in its thesis, a sell starts `exit <id>:`)."""
    out = set()
    for row in account.ledger:
        m = DONE_RE.search(str(row.get("thesis", "")))
        if m:
            out.add(m.group(1) or m.group(2))
    return out


def choose_state(relay: Account | None, branch: Account | None) -> tuple[Account | None, str]:
    """Which saved account to continue from. Both are already verified (hash chain and replay) by Account.from_dict. The longer chain wins only if
    the shorter one is its exact prefix; two different histories are a conflict and the runner must not start. Returns (account, note); (None, note)
    means refuse."""
    if relay is None and branch is None:
        return None, "no saved account"
    if relay is None:
        return branch, "continued from the ledger branch (the relay had no state)"
    if branch is None:
        return relay, "continued from the relay"
    a, b = relay.ledger, branch.ledger
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if relay.capital0 != branch.capital0 or long_[:len(short)] != short:
        return None, "the relay's account and the ledger branch's are two different histories: not starting until the owner looks"
    return (relay, "continued from the relay") if len(a) >= len(b) else (branch, "continued from the ledger branch (it was ahead of the relay)")


class Runner:
    def __init__(self, cfg, account: Account, *, gate: RiskGate | None = None, kill_file: str | Path | None = None):
        self.cfg = cfg
        self.account = account
        self.gate = gate or RiskGate(cfg)
        self.broker = PaperBroker(cfg, account, self.gate)
        self.und = frozenset(self.gate.limits.underlyings.get(SEGMENT, ()))
        self.lots = {str(u).upper(): int(v["lot_size"]) for u, v in (cfg.get("instruments") or {}).items() if isinstance(v, dict) and isinstance(v.get("lot_size"), int)}
        self.kill_file = Path(kill_file or cfg.get("paper.kill_switch_file", "runtime/paper/KILL"))
        self.seen: set[str] = set(done_ids(account))
        self.results: list[dict] = []

    # ---- the board ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def server_now(snap) -> dt.datetime | None:
        ms = snap.get("now") if isinstance(snap, dict) else None
        return dt.datetime.fromtimestamp(ms / 1000, tz=dt.timezone.utc) if is_number(ms) and ms > 0 else None

    @staticmethod
    def quote_from(snap, name, now) -> Quote | None:
        q = (snap.get("quotes") or {}).get(name) if isinstance(snap, dict) else None
        if not isinstance(q, dict) or not (is_number(q.get("age_s")) and q["age_s"] >= 0):
            return None
        if not (is_number(q.get("bid")) and is_number(q.get("ask"))):
            return None
        sz = lambda k: float(q[k]) if is_number(q.get(k)) else None          # noqa: E731
        return Quote(float(q["bid"]), float(q["ask"]), now - dt.timedelta(seconds=float(q["age_s"])), sz("bid_qty"), sz("ask_qty"))

    def marks(self, snap, now) -> dict[str, float]:
        out = {}
        for sym in self.account.positions:
            q = self.quote_from(snap, sym, now)
            if q is not None and q.bid > 0 and (now - q.ts).total_seconds() <= MARK_MAX_AGE_S:
                out[sym] = q.bid                                              # what it could be sold for now: never the mid, never the last trade
        return out

    # ---- the kill switch file mirrors the relay's flag ---------------------------------------------------------------------------
    def sync_kill(self, on: bool) -> None:
        if on and not self.kill_file.exists():
            self.kill_file.parent.mkdir(parents=True, exist_ok=True)
            self.kill_file.write_text("set from the relay\n", encoding="utf-8")
        elif not on and self.kill_file.exists():
            self.kill_file.unlink()

    # ---- one cycle -------------------------------------------------------------------------------------------------------------
    def step(self, snap, orders, kill: bool, local_now: dt.datetime) -> dict:
        """One cycle. Returns {"asof", "skipped": why|None, "forced": [...], "results": [one per order]}. Never raises for a bad order or quote."""
        now = self.server_now(snap)
        rep = {"asof": None, "skipped": None, "forced": [], "results": []}
        if now is None or local_now.tzinfo is None:
            rep["skipped"] = "no usable time on the snapshot"
            return rep
        rep["asof"] = now.isoformat()
        if abs((now - local_now).total_seconds()) > MAX_SKEW_S:
            rep["skipped"] = f"the relay's clock and this machine's differ by more than {MAX_SKEW_S}s: nothing is done"
            return rep
        self.sync_kill(bool(kill))
        marks = self.marks(snap, now)
        quotes = {s: self.quote_from(snap, s, now) for s in self.account.positions}
        try:
            reasons = self.gate.update(self.account, marks, now)
        except ValueError as e:                                              # a clock that ran backwards: refuse the cycle, change nothing
            rep["skipped"] = str(e)
            return rep
        trim = [r for r in reasons if r.startswith("trim:")]
        stop = [r for r in reasons if not r.startswith("trim:")]
        if stop and self.account.positions:
            ds = self.broker.flatten(quotes, now, "flatten: " + "; ".join(stop)[:120])
            rep["forced"].append({"action": "flatten", "why": stop, "decisions": {k: v.reasons or ["sold"] for k, v in ds.items()}})
        elif trim:
            ds = self.broker.trim(quotes, marks, now)
            rep["forced"].append({"action": "trim", "why": trim, "decisions": {k: v.reasons or ["sold"] for k, v in ds.items()}})
        ist = now.astimezone(IST)
        if ist.time() >= FLATTEN_AT:
            today = [s for s, p in self.account.positions.items() if p.instrument.expiry == ist.date()]
            if today:
                ds = {s: self.broker.sell(s, self.account.positions[s].qty, quotes.get(s), now, "flatten: expires today")[0] for s in today}
                rep["forced"].append({"action": "sell expiring", "why": ["expires today"], "decisions": {k: v.reasons or ["sold"] for k, v in ds.items()}})
        for raw in orders or []:
            rep["results"].append(self.handle(raw, snap, now))
        return rep

    def handle(self, raw, snap, now) -> dict:
        o, why = clean_order(raw)
        oid = raw.get("id") if isinstance(raw, dict) and isinstance(raw.get("id"), str) else None
        res = {"id": oid, "status": "invalid", "reasons": [], "fill": None, "at": now.isoformat()}
        if o is None:
            res["reasons"] = [why]
            return res
        if o["id"] in self.seen:
            res.update(status="done", reasons=["this order id was already handled: nothing is done twice"])
            return res
        self.seen.add(o["id"])
        age = (now.timestamp() * 1000 - o["queued_at"]) / 1000 if o["queued_at"] is not None else None
        if age is None or age > MAX_ORDER_AGE_S or age < -MAX_SKEW_S:
            res.update(status="expired", reasons=[f"the order waited {age:.0f}s (limit {MAX_ORDER_AGE_S}s): it was not executed at a price the owner did not see"
                                                  if age is not None else "the order has no queue time: not executed"])
            return res
        inst, why = parse_contract(o["symbol"], self.und, self.lots)
        if inst is None:
            res.update(status="refused", reasons=[why])
            return res
        quote = self.quote_from(snap, inst.symbol, now)
        if o["side"] == "buy":
            if quote is not None and o["limit"] is not None and quote.ask > o["limit"]:
                res.update(status="refused", reasons=[f"the offer is {quote.ask:g}, above your limit {o['limit']:g}: not bought"])
                return res
            order = Order(inst, SEGMENT, o["lots"] * inst.lot_size, o["strategy"], f"{o['thesis']} [order {o['id']}]")
            marks = self.marks(snap, now)
            d, row = self.broker.buy(order, quote, marks, now)
        else:
            pos = self.account.positions.get(inst.symbol)
            qty = pos.qty if (pos and o["lots"] == "all") else (o["lots"] * inst.lot_size if pos else 0)
            if quote is not None and o["limit"] is not None and quote.bid < o["limit"]:
                res.update(status="refused", reasons=[f"the bid is {quote.bid:g}, below your limit {o['limit']:g}: not sold"])
                return res
            d, row = self.broker.sell(inst.symbol, qty, quote, now, f"exit {o['id']}")
        if row is None:
            res.update(status="refused", reasons=d.reasons or ["refused"])
        else:
            res.update(status="filled", reasons=[], fill={k: row[k] for k in ("seq", "kind", "ts", "qty", "price", "fees") if k in row} | {"symbol": inst.symbol})
        return res

    # ---- what the app shows ------------------------------------------------------------------------------------------------------
    def summary(self, snap, now) -> dict:
        a, marks = self.account, self.marks(snap, now)
        fin = lambda x: float(x) if is_number(x) else None                    # noqa: E731 - JSON has no NaN
        eq = a.equity(marks)
        pos = []
        for s, p in sorted(a.positions.items()):
            m = marks.get(s)
            pos.append({"symbol": s, "lots": p.qty // max(1, p.instrument.lot_size), "qty": p.qty, "avg": p.avg_price, "mark": fin(m), "pnl": fin((m - p.avg_price) * p.qty) if m is not None else None,
                        "strategy": p.strategy, "thesis": p.thesis, "opened_at": p.opened_at, "expiry": p.instrument.expiry.isoformat() if p.instrument.expiry else None})
        day_floor, dd_floor = self.gate.floors(a)
        return {"v": 1, "asof": now.isoformat(), "equity": fin(eq), "cash": a.cash, "capital0": a.capital0, "net_pnl": fin(eq - a.capital0) if is_number(eq) else None,
                "realized": a.realized, "fees": a.fees, "hwm": a.hwm, "day": a.day, "day_start": a.day_start, "day_halted": a.day_halted, "halt": a.halt,
                "kill": self.kill_file.exists(), "day_floor": fin(day_floor), "dd_floor": fin(dd_floor), "positions": pos,
                "ledger_tail": [_tail(r) for r in a.ledger[-40:]],
                "ledger_len": len(a.ledger), "ledger_ok": a.verify_ledger()}


def _tail(r: dict) -> dict:
    out = {k: r.get(k) for k in ("seq", "ts", "kind", "qty", "price", "fees", "strategy", "thesis") if k in r}
    if isinstance(r.get("instrument"), dict):
        out["symbol"] = r["instrument"].get("symbol")
    return out


def account_json(account: Account) -> str:
    """The saved account as the exact text the relay and the ledger branch hold."""
    return json.dumps(account.to_dict(), sort_keys=True)


def load_account(text: str | None) -> Account | None:
    """A saved account, verified (hash chain, replay, flags). None for no text; raises ValueError for text that does not verify."""
    if not text:
        return None
    return Account.from_dict(json.loads(text))
