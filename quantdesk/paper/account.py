"""The paper account: cash, option positions (bought, and sold inside bounded packages), and an append-only, hash-chained ledger of every fill.

No network, no clock, no secret. Money here is paper money. A bought option can lose what was paid. A SOLD option (`sto`, closed by `btc`) is allowed only as part of a package whose worst case is
bounded (`stress_equity`: verticals, condors, butterflies), and only while `paper.allow_short_legs` is on; the risk gate refuses a naked short call whatever the flag says. Futures need a margin
model that is not built, and the gate refuses them.

Guarantees, each tested:
  * Money moves only through `apply_fill`. It checks every input (a quantity is a positive whole number, a price and a fee are
    finite numbers, a buy has a positive price), works out the new state and the ledger row FIRST, and only then commits both:
    a failure leaves cash, positions and ledger exactly as they were.
  * Cash never goes negative on a buy. An exit is never refused for its fees, so a sale of a near-worthless option can dip cash
    below zero by the fees; the gate then refuses new entries until cash covers them.
  * Equity is NaN when any position has no usable mark. `equity_lower_bound` counts such a position as worth nothing, which for
    a long-only book is a true lower bound, so the loss caps can still be judged when a price is missing.
  * A saved account is replayed through the same code on load: the ledger's hash chain, and cash, positions, realised profit and
    fees, must all come out as saved. Editing the file, dropping or reordering rows, or truncating the tail is refused.
"""
from __future__ import annotations

import hashlib
import json
import math
import numbers
import os
from dataclasses import dataclass
from pathlib import Path

from ..core.types import FUTURE, Instrument

GENESIS = "0" * 64
FILL_KINDS = ("buy", "sell", "settle", "sto", "btc")      # buy = buy to open a long, sell = sell to close a long, sto = sell to open a short, btc = buy to close a short, settle = cash settlement at expiry
SIDE_OF = {"buy": "buy", "btc": "buy", "sell": "sell", "sto": "sell"}   # the side a slippage record must carry for each kind of fill


@dataclass
class Position:
    instrument: Instrument
    segment: str
    qty: int                 # units (lots x lot size): > 0 for a long position, < 0 for a short one (a sold option, only ever as part of a hedged book: see stress_equity)
    avg_price: float
    opened_at: str
    strategy: str
    thesis: str
    stop: float | None = None        # a future's stop (every futures entry has one): the price the runner closes it at, and what its worst case is counted to
    target: float | None = None      # a future's optional target

    @property
    def is_future(self) -> bool:
        return self.instrument.kind == FUTURE

    def to_dict(self) -> dict:
        d = {"instrument": self.instrument.to_dict(), "segment": self.segment, "qty": self.qty, "avg_price": self.avg_price,
             "opened_at": self.opened_at, "strategy": self.strategy, "thesis": self.thesis}
        for k in ("stop", "target"):                                  # only a future has them: an option's saved form is unchanged
            if getattr(self, k) is not None:
                d[k] = getattr(self, k)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(Instrument.from_dict(d["instrument"]), d["segment"], int(d["qty"]), float(d["avg_price"]), d["opened_at"],
                   d["strategy"], d["thesis"], float(d["stop"]) if d.get("stop") is not None else None, float(d["target"]) if d.get("target") is not None else None)

    def value(self, mark: float) -> float:
        """What the position adds to equity at `mark`: an option is worth its price; a future (margined, not paid for) only its profit or loss since it opened."""
        return self.qty * (float(mark) - self.avg_price) if self.is_future else self.qty * float(mark)

    def at_stop(self) -> float:
        """A future's profit or loss if it closes at its stop (negative for a loss); -inf without a stop."""
        if self.stop is None or not is_number(self.stop):
            return float("-inf")
        return self.qty * (self.stop - self.avg_price)


def is_whole_positive(x) -> bool:
    """A real whole number above zero: not a bool, not a float, not NaN (numpy integers count)."""
    return isinstance(x, numbers.Integral) and not isinstance(x, bool) and x > 0


def is_number(x) -> bool:
    """A finite real number that is not a bool."""
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(x)


def _usable(x) -> bool:
    return is_number(x) and x >= 0


def stress_equity(cash: float, positions: dict) -> float:
    """The WORST-CASE equity if every option expired now: the cash plus, for each underlying and expiry, the lowest value the group's legs can have at expiry over every spot price (each leg at its
    intrinsic value; time value is ignored, which is conservative for the longs). It is -infinity when some group could lose without limit (a short call not covered by a long call) or when a position is
    not a plain option. For a book of long options only it is at least the cash; for a hedged book of spreads, condors and butterflies it is exactly cash less the worst possible loss; for a naked short it
    is -inf, which is how the risk gate refuses one. Groups settle at different times, so their worst cases are added (the safe way round)."""
    groups: dict[tuple, list] = {}
    futures = 0.0
    for p in positions.values():
        i = p.instrument
        if getattr(p, "is_future", False):
            futures += p.at_stop()                               # a future counts at its stop (-inf without one); it moves no cash of its own, so this is all it can cost
            continue
        if not is_number(i.strike) or i.strike <= 0 or i.right not in ("CE", "PE") or i.expiry is None or not is_number(p.qty) or not p.qty:
            return float("-inf")                                 # anything that is not a plain option with a real strike and quantity cannot be valued: treated as unbounded (and a NaN can never slip past a comparison)
        groups.setdefault((i.underlying, i.expiry), []).append((float(i.strike), i.right, p.qty))
    total = float(cash) + futures
    if not math.isfinite(total):
        return float("-inf")
    for legs in groups.values():
        if sum(q for _k, r, q in legs if r == "CE") < 0:
            return float("-inf")                                  # more calls sold than bought: the loss grows with the price without limit
        pts = sorted({0.0} | {k for k, _r, _q in legs})
        total += min(sum(q * (max(s - k, 0.0) if r == "CE" else max(k - s, 0.0)) for k, r, q in legs) for s in pts)
    return total


class Account:
    def __init__(self, capital: float):
        if not (is_number(capital) and capital > 0):
            raise ValueError("the starting capital must be a positive number")
        self.capital0 = float(capital)
        self.cash = float(capital)
        self.positions: dict[str, Position] = {}
        self.realized = 0.0          # gross profit on closed quantity, before fees
        self.fees = 0.0              # every fee paid, on buys and sells
        self.hwm = float(capital)    # high-water mark of equity
        self.day: str | None = None  # the IST date the day figures below belong to
        self.day_start: float | None = None
        self.last_equity: float | None = None   # the last finite equity seen: the next day starts from it, so an overnight gap counts
        self.day_halted = False      # sticky for the day once the daily loss cap is hit
        self.halt: dict | None = None  # the multi-day drawdown halt: cleared only by the owner (clear_halt)
        self.ledger: list[dict] = []

    # ---- reads ---------------------------------------------------------------------------------------------------------------
    def equity(self, marks: dict[str, float]) -> float:
        total = self.cash
        for sym, p in self.positions.items():
            m = marks.get(sym)
            if not _usable(m):
                return float("nan")
            total += p.value(m)
        return total

    def has_shorts(self) -> bool:
        return any(p.qty < 0 for p in self.positions.values())

    def stress(self) -> float:
        """The worst-case equity if everything expired now (see `stress_equity`)."""
        return stress_equity(self.cash, self.positions)

    def equity_lower_bound(self, marks: dict[str, float]) -> float:
        """Equity with every position that has no usable mark counted as worth nothing. For a long-only book that is a floor under
        the true equity, so a loss cap breached by this figure is truly breached. With a short position that has no price, the true
        figure could be far lower, so the worst-case equity (`stress`) is used instead."""
        if any(p.qty < 0 and not p.is_future and not _usable(marks.get(sym)) for sym, p in self.positions.items()):
            return self.stress()
        total = self.cash
        for sym, p in self.positions.items():
            m = marks.get(sym)
            if p.is_future:
                total += p.value(m) if _usable(m) else min(p.at_stop(), 0.0)          # a future with no price: counted at its stop, the loss it was opened to bear
            else:
                total += p.qty * float(m) if _usable(m) else 0.0
        return total

    def open_value(self, marks: dict[str, float]) -> float:
        """The most the open positions can still lose (NaN if a mark is missing): an option's value at its mark; a future's distance from its mark to its stop."""
        total = 0.0
        for sym, p in self.positions.items():
            m = marks.get(sym)
            if not _usable(m):
                return float("nan")
            if p.is_future:
                total += max(0.0, p.value(m) - p.at_stop()) if math.isfinite(p.at_stop()) else float("inf")
            else:
                total += p.qty * float(m)
        return total

    def margin_used(self, marks: dict[str, float], rates: dict[str, float]) -> float:
        """The margin the open futures hold: lots x price x the contract's rate (`rates` by underlying), at the mark or, without one, the price paid."""
        total = 0.0
        for sym, p in self.positions.items():
            if p.is_future:
                m = marks.get(sym)
                total += abs(p.qty) * (float(m) if _usable(m) else p.avg_price) * float(rates.get(p.instrument.underlying, 1.0))
        return total

    def net_pnl(self, marks: dict[str, float]) -> float:
        return self.equity(marks) - self.capital0

    # ---- the one way money moves ---------------------------------------------------------------------------------------------
    def apply_fill(self, kind: str, instrument: Instrument, segment: str, qty: int, price: float, fees: float, ts: str,
                   strategy: str, thesis: str, slip: dict | None = None, stop: float | None = None, target: float | None = None) -> dict:
        """kind: 'buy' (open a long) | 'sell' (close a long) | 'sto' (sell to open a short) | 'btc' (buy to close a short) | 'settle' (cash settlement of either). Raises ValueError, changing nothing,
        for anything that would leave the account wrong."""
        if kind not in FILL_KINDS:
            raise ValueError(f"bad fill: unknown kind {kind!r}")
        if not is_whole_positive(qty):
            raise ValueError(f"bad fill: the quantity must be a whole number above zero, not {qty!r}")
        if not (_usable(price) and _usable(fees)):
            raise ValueError(f"bad fill: price {price!r} and fees {fees!r} must be finite and not negative")
        if kind == "buy" and price <= 0:
            raise ValueError("bad fill: a buy at a zero price would be a free position")
        if kind == "sto" and price <= 0:
            raise ValueError("bad fill: a sale to open at a zero price is not a trade")
        if slip is not None:                                    # the slippage record is part of the sealed row: known keys, finite numbers, nothing else
            from .slippage import clean
            if kind == "settle" or clean(slip) != slip or slip.get("side") != SIDE_OF[kind] or slip.get("qty") != qty or not math.isclose(slip.get("fill", -1), price, abs_tol=1e-4):
                raise ValueError("bad fill: the slippage record is not well formed or does not match the fill")
        qty, price, fees = int(qty), float(price), float(fees)
        sym = instrument.symbol
        pos = self.positions.get(sym)
        fut = instrument.kind == FUTURE
        if fut:                                                 # a future: margined, so a fill moves cash only by its fees and, on a close, its profit; every opening has a stop
            if kind == "settle":
                raise ValueError("bad fill: a future is closed in the session (intraday), never settled")
            if kind in ("buy", "sto"):
                if not (_usable(stop) and stop > 0) or (target is not None and not (_usable(target) and target > 0)):
                    raise ValueError("bad fill: a futures entry needs a stop (and a target, if any) that is a positive price")
                if pos is not None:
                    raise ValueError(f"bad fill: {sym} is already held; one futures position per contract")
        elif stop is not None or target is not None:
            raise ValueError("bad fill: a stop or a target belongs to a future only")
        new_pos: Position | None
        realized = self.realized
        if kind == "sto":
            if pos is not None and pos.qty > 0:
                raise ValueError(f"cannot sell to open {sym}: it is held long (sell it to close)")
            cash = self.cash - fees if fut else self.cash + qty * price - fees
            if pos is None:
                new_pos = Position(instrument, segment, -qty, price, ts, strategy, thesis, stop if fut else None, target if fut else None)
            else:
                held = -pos.qty
                new_pos = Position(pos.instrument, pos.segment, -(held + qty), (pos.avg_price * held + price * qty) / (held + qty), pos.opened_at, pos.strategy, pos.thesis)
        elif kind == "btc" or (kind == "settle" and pos is not None and pos.qty < 0):
            if pos is None or pos.qty >= 0 or qty > -pos.qty:
                raise ValueError(f"cannot {kind} {qty} of {sym}: short {-pos.qty if pos and pos.qty < 0 else 0}")
            cash = self.cash + (pos.avg_price - price) * qty - fees if fut else self.cash - (qty * price + fees)      # closing a short is never refused for cash or fees: it only ever reduces the risk
            realized += (pos.avg_price - price) * qty
            new_pos = None if -pos.qty == qty else Position(pos.instrument, pos.segment, pos.qty + qty, pos.avg_price, pos.opened_at, pos.strategy, pos.thesis, pos.stop, pos.target)
        elif kind == "buy":
            if pos is not None and pos.qty < 0:
                raise ValueError(f"cannot buy to open {sym}: it is held short (buy it to close)")
            cost = fees if fut else qty * price + fees
            if cost > self.cash + 1e-9:
                raise ValueError("not enough cash")
            cash = self.cash - cost
            if pos is None:
                new_pos = Position(instrument, segment, qty, price, ts, strategy, thesis, stop if fut else None, target if fut else None)
            else:
                total = pos.qty + qty
                new_pos = Position(pos.instrument, pos.segment, total, (pos.avg_price * pos.qty + price * qty) / total, pos.opened_at,
                                   pos.strategy, pos.thesis)
        else:
            if pos is None or pos.qty <= 0 or qty > pos.qty:
                raise ValueError(f"cannot {kind} {qty} of {sym}: holding {pos.qty if pos else 0}")
            cash = self.cash + (price - pos.avg_price) * qty - fees if fut else self.cash + qty * price - fees
            realized += (price - pos.avg_price) * qty
            new_pos = None if pos.qty == qty else Position(pos.instrument, pos.segment, pos.qty - qty, pos.avg_price, pos.opened_at,
                                                           pos.strategy, pos.thesis, pos.stop, pos.target)
        body = {"seq": len(self.ledger) + 1, "ts": ts, "kind": kind, "symbol": sym, "instrument": instrument.to_dict(),
                "segment": segment, "qty": qty, "price": price, "fees": fees, "strategy": strategy, "thesis": thesis,
                "cash_after": cash}
        if slip is not None:
            body["slip"] = slip
        if fut and kind in ("buy", "sto"):
            body["stop"] = float(stop)
            if target is not None:
                body["target"] = float(target)
        row = self._seal(body)                                  # raises (e.g. a thesis that cannot be saved) BEFORE anything changes
        self.cash, self.realized, self.fees = cash, realized, self.fees + fees
        if new_pos is None:
            del self.positions[sym]
        else:
            self.positions[sym] = new_pos
        self.ledger.append(row)
        return row

    def snapshot(self) -> dict:
        """Everything a package of fills may change, so a failure half way can put it all back (`restore`)."""
        return {"cash": self.cash, "realized": self.realized, "fees": self.fees, "positions": {k: Position.from_dict(p.to_dict()) for k, p in self.positions.items()}, "n": len(self.ledger)}

    def restore(self, snap: dict) -> None:
        self.cash, self.realized, self.fees, self.positions = snap["cash"], snap["realized"], snap["fees"], snap["positions"]
        del self.ledger[snap["n"]:]

    def record_event(self, kind: str, ts: str, **fields) -> dict:
        """A non-money row in the same chain (the owner clearing a halt). Kinds that move money are not allowed here."""
        if kind in FILL_KINDS:
            raise ValueError("a fill is recorded by apply_fill")
        row = self._seal({"seq": len(self.ledger) + 1, "ts": ts, "kind": kind, **fields})
        self.ledger.append(row)
        return row

    def _seal(self, body: dict) -> dict:
        prev = self.ledger[-1]["hash"] if self.ledger else GENESIS
        json.dumps(body, sort_keys=True)                        # must be saveable
        return {**body, "prev": prev, "hash": self._hash(body, prev)}

    @staticmethod
    def _hash(body: dict, prev: str) -> str:
        return hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()

    def verify_ledger(self) -> bool:
        """Every row's hash covers its own content and the row before it: change, drop or reorder one and this is False."""
        prev = GENESIS
        for i, row in enumerate(self.ledger, 1):
            body = {k: v for k, v in row.items() if k not in ("prev", "hash")}
            if row.get("seq") != i or row.get("prev") != prev or row.get("hash") != self._hash(body, prev):
                return False
            prev = row["hash"]
        return True

    # ---- the owner's halt ----------------------------------------------------------------------------------------------------
    def clear_halt(self, who: str, reason: str, equity: float, ts: str) -> None:
        """The owner's act. Appends a row to the ledger (who, why, when, the equity) and restarts the high-water mark at the current
        equity so the same drawdown does not halt again at once."""
        if not (who and reason and ts and is_number(equity) and equity > 0):
            raise ValueError("clearing the halt needs who, why, when and a known equity")
        self.record_event("halt_cleared", ts, who=who, reason=reason, equity=float(equity), was=self.halt)
        self.halt = None
        self.hwm = float(equity)

    # ---- persistence ---------------------------------------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"capital0": self.capital0, "cash": self.cash, "positions": {k: p.to_dict() for k, p in self.positions.items()},
                "realized": self.realized, "fees": self.fees, "hwm": self.hwm, "day": self.day, "day_start": self.day_start,
                "last_equity": self.last_equity, "day_halted": self.day_halted, "halt": self.halt, "ledger": self.ledger}

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        a = cls(d["capital0"])
        a.cash, a.realized, a.fees, a.hwm = float(d["cash"]), float(d["realized"]), float(d["fees"]), float(d["hwm"])
        a.positions = {k: Position.from_dict(v) for k, v in d["positions"].items()}
        a.day, a.day_start, a.last_equity = d["day"], d["day_start"], d.get("last_equity")
        a.day_halted, a.halt, a.ledger = bool(d["day_halted"]), d["halt"], list(d["ledger"])
        if not a.verify_ledger():
            raise ValueError("the ledger's hash chain does not verify: the saved account was changed")
        a._check_against_replay()
        return a

    def _check_against_replay(self) -> None:
        """Rebuild the account from its ledger through the same code and compare: a file whose cash, positions, profit or fees were
        edited, or whose ledger was cut short, no longer matches its own history."""
        s = Account(self.capital0)
        for row in self.ledger:
            if row["kind"] in FILL_KINDS:
                s.apply_fill(row["kind"], Instrument.from_dict(row["instrument"]), row["segment"], row["qty"], row["price"],
                             row["fees"], row["ts"], row["strategy"], row["thesis"], row.get("slip"), row.get("stop"), row.get("target"))
            else:
                s.record_event(row["kind"], row["ts"], **{k: v for k, v in row.items() if k not in ("seq", "ts", "kind", "prev", "hash")})
        same = (s.ledger == self.ledger and math.isclose(s.cash, self.cash, abs_tol=1e-6) and math.isclose(s.realized, self.realized, abs_tol=1e-6)
                and math.isclose(s.fees, self.fees, abs_tol=1e-6) and set(s.positions) == set(self.positions)
                and all(self._same_position(s.positions[k], p) for k, p in self.positions.items()))
        if not same:
            raise ValueError("the saved cash, positions, profit or fees do not match the ledger: the saved account was changed")
        self._check_flags_against_ledger()

    @staticmethod
    def _same_position(a: "Position", b: "Position") -> bool:
        """Every field of the position, the contract included: a changed strike, expiry, right, lot size or segment changes what the
        position is worth and which brakes apply to it."""
        da, db = a.to_dict(), b.to_dict()
        return math.isclose(da.pop("avg_price"), db.pop("avg_price"), abs_tol=1e-9) and da == db

    def _check_flags_against_ledger(self) -> None:
        """The halt and the day's cap are written to the ledger when they are set, so the saved flags must agree with it."""
        last = next((r for r in reversed(self.ledger) if r["kind"] in ("halt_set", "halt_cleared")), None)
        if (self.halt is not None) != (last is not None and last["kind"] == "halt_set"):
            raise ValueError("the saved drawdown halt does not match the ledger: the saved account was changed")
        if self.day is not None:
            hit = any(r["kind"] == "daily_cap_hit" and r.get("day") == self.day for r in self.ledger)
            if bool(self.day_halted) != hit:
                raise ValueError("the saved daily loss cap flag does not match the ledger: the saved account was changed")
        elif self.day_halted:
            raise ValueError("a daily loss cap flag without a day: the saved account was changed")

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(self.to_dict(), sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())                               # on disk before the rename: a crash never leaves half an account
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> "Account":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
