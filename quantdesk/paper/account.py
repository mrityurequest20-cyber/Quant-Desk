"""The paper account: cash, long option positions, and an append-only, hash-chained ledger of every fill.

No network, no clock, no secret. Money here is paper money. M2 of the 24/7 paper desk holds LONG premium positions only: a buy
pays the premium, a sell receives it, so the most a position can lose is what was paid. Futures and short options need a margin
model that is not built, and the risk gate refuses them.

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

from ..core.types import Instrument

GENESIS = "0" * 64
FILL_KINDS = ("buy", "sell", "settle")


@dataclass
class Position:
    instrument: Instrument
    segment: str
    qty: int                 # units (lots x lot size), always > 0 in M2
    avg_price: float
    opened_at: str
    strategy: str
    thesis: str

    def to_dict(self) -> dict:
        return {"instrument": self.instrument.to_dict(), "segment": self.segment, "qty": self.qty, "avg_price": self.avg_price,
                "opened_at": self.opened_at, "strategy": self.strategy, "thesis": self.thesis}

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(Instrument.from_dict(d["instrument"]), d["segment"], int(d["qty"]), float(d["avg_price"]), d["opened_at"],
                   d["strategy"], d["thesis"])


def is_whole_positive(x) -> bool:
    """A real whole number above zero: not a bool, not a float, not NaN (numpy integers count)."""
    return isinstance(x, numbers.Integral) and not isinstance(x, bool) and x > 0


def is_number(x) -> bool:
    """A finite real number that is not a bool."""
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(x)


def _usable(x) -> bool:
    return is_number(x) and x >= 0


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
            total += p.qty * float(m)
        return total

    def equity_lower_bound(self, marks: dict[str, float]) -> float:
        """Equity with every position that has no usable mark counted as worth nothing. For a long-only book that is a floor under
        the true equity, so a loss cap breached by this figure is truly breached."""
        total = self.cash
        for sym, p in self.positions.items():
            m = marks.get(sym)
            total += p.qty * float(m) if _usable(m) else 0.0
        return total

    def open_value(self, marks: dict[str, float]) -> float:
        """What the open positions are worth at their marks (NaN if a mark is missing): the most they can still lose."""
        total = 0.0
        for sym, p in self.positions.items():
            m = marks.get(sym)
            if not _usable(m):
                return float("nan")
            total += p.qty * float(m)
        return total

    def net_pnl(self, marks: dict[str, float]) -> float:
        return self.equity(marks) - self.capital0

    # ---- the one way money moves ---------------------------------------------------------------------------------------------
    def apply_fill(self, kind: str, instrument: Instrument, segment: str, qty: int, price: float, fees: float, ts: str,
                   strategy: str, thesis: str, slip: dict | None = None) -> dict:
        """kind: 'buy' | 'sell' | 'settle'. Raises ValueError, changing nothing, for anything that would leave the account wrong."""
        if kind not in FILL_KINDS:
            raise ValueError(f"bad fill: unknown kind {kind!r}")
        if not is_whole_positive(qty):
            raise ValueError(f"bad fill: the quantity must be a whole number above zero, not {qty!r}")
        if not (_usable(price) and _usable(fees)):
            raise ValueError(f"bad fill: price {price!r} and fees {fees!r} must be finite and not negative")
        if kind == "buy" and price <= 0:
            raise ValueError("bad fill: a buy at a zero price would be a free position")
        if slip is not None:                                    # the slippage record is part of the sealed row: known keys, finite numbers, nothing else
            from .slippage import clean
            if kind == "settle" or clean(slip) != slip or slip.get("side") != kind or slip.get("qty") != qty or not math.isclose(slip.get("fill", -1), price, abs_tol=1e-4):
                raise ValueError("bad fill: the slippage record is not well formed or does not match the fill")
        qty, price, fees = int(qty), float(price), float(fees)
        sym = instrument.symbol
        pos = self.positions.get(sym)
        new_pos: Position | None
        realized = self.realized
        if kind == "buy":
            cost = qty * price + fees
            if cost > self.cash + 1e-9:
                raise ValueError("not enough cash")
            cash = self.cash - cost
            if pos is None:
                new_pos = Position(instrument, segment, qty, price, ts, strategy, thesis)
            else:
                total = pos.qty + qty
                new_pos = Position(pos.instrument, pos.segment, total, (pos.avg_price * pos.qty + price * qty) / total, pos.opened_at,
                                   pos.strategy, pos.thesis)
        else:
            if pos is None or qty > pos.qty:
                raise ValueError(f"cannot {kind} {qty} of {sym}: holding {pos.qty if pos else 0}")
            cash = self.cash + qty * price - fees
            realized += (price - pos.avg_price) * qty
            new_pos = None if pos.qty == qty else Position(pos.instrument, pos.segment, pos.qty - qty, pos.avg_price, pos.opened_at,
                                                           pos.strategy, pos.thesis)
        body = {"seq": len(self.ledger) + 1, "ts": ts, "kind": kind, "symbol": sym, "instrument": instrument.to_dict(),
                "segment": segment, "qty": qty, "price": price, "fees": fees, "strategy": strategy, "thesis": thesis,
                "cash_after": cash}
        if slip is not None:
            body["slip"] = slip
        row = self._seal(body)                                  # raises (e.g. a thesis that cannot be saved) BEFORE anything changes
        self.cash, self.realized, self.fees = cash, realized, self.fees + fees
        if new_pos is None:
            del self.positions[sym]
        else:
            self.positions[sym] = new_pos
        self.ledger.append(row)
        return row

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
                             row["fees"], row["ts"], row["strategy"], row["thesis"], row.get("slip"))
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
