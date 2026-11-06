"""The paper account: cash, long option positions, and an append-only, hash-chained ledger of every fill.

No network, no clock, no secret. Money here is paper money. M2 of the 24/7 paper desk holds LONG premium positions only: a buy
pays the premium, a sell receives it, so the most a position can lose is what was paid. Futures and short options need a margin
model that is not built, and the risk gate refuses them.

Equity is cash plus every position at its mark. If any position has no usable mark the equity is NaN, and the risk gate
treats unknown equity as a reason to refuse entries (a NaN passes every `x > 0` and `x <= -y` test, so it is never compared).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from ..core.types import Instrument

GENESIS = "0" * 64


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


def _usable(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x) and x >= 0


class Account:
    def __init__(self, capital: float):
        if not (math.isfinite(capital) and capital > 0):
            raise ValueError("the starting capital must be a positive number")
        self.capital0 = float(capital)
        self.cash = float(capital)
        self.positions: dict[str, Position] = {}
        self.realized = 0.0          # gross profit on closed quantity, before fees
        self.fees = 0.0              # every fee paid, on buys and sells
        self.hwm = float(capital)    # high-water mark of equity
        self.day: str | None = None  # the IST date the day figures below belong to
        self.day_start: float | None = None
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

    def net_pnl(self, marks: dict[str, float]) -> float:
        return self.equity(marks) - self.capital0

    # ---- the one way money moves ---------------------------------------------------------------------------------------------
    def apply_fill(self, kind: str, instrument: Instrument, segment: str, qty: int, price: float, fees: float, ts: str,
                   strategy: str, thesis: str) -> dict:
        """kind: 'buy' | 'sell' | 'settle'. qty > 0. Raises ValueError rather than ever letting cash or a position go wrong."""
        if kind not in ("buy", "sell", "settle") or qty <= 0 or not (_usable(price) and _usable(fees)):
            raise ValueError(f"bad fill: {kind} {qty} @ {price} fees {fees}")
        sym = instrument.symbol
        pos = self.positions.get(sym)
        if kind == "buy":
            cost = qty * price + fees
            if cost > self.cash + 1e-9:
                raise ValueError("not enough cash")
            self.cash -= cost
            if pos is None:
                self.positions[sym] = Position(instrument, segment, qty, price, ts, strategy, thesis)
            else:
                new = pos.qty + qty
                pos.avg_price = (pos.avg_price * pos.qty + price * qty) / new
                pos.qty = new
        else:
            if pos is None or qty > pos.qty:
                raise ValueError(f"cannot {kind} {qty} of {sym}: holding {pos.qty if pos else 0}")
            self.cash += qty * price - fees
            self.realized += (price - pos.avg_price) * qty
            pos.qty -= qty
            if pos.qty == 0:
                del self.positions[sym]
        self.fees += fees
        return self._record(kind, sym, segment, qty, price, fees, ts, strategy, thesis)

    def _record(self, kind, sym, segment, qty, price, fees, ts, strategy, thesis) -> dict:
        body = {"seq": len(self.ledger) + 1, "ts": ts, "kind": kind, "symbol": sym, "segment": segment, "qty": qty, "price": price,
                "fees": fees, "strategy": strategy, "thesis": thesis, "cash_after": self.cash}
        prev = self.ledger[-1]["hash"] if self.ledger else GENESIS
        row = {**body, "prev": prev, "hash": self._hash(body, prev)}
        self.ledger.append(row)
        return row

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
    def clear_halt(self, who: str, reason: str, equity: float) -> None:
        """The owner's act. Records who and why, and restarts the high-water mark at the current equity so the same drawdown
        does not halt again at once."""
        if not (who and reason and math.isfinite(equity) and equity > 0):
            raise ValueError("clearing the halt needs who, why and a known equity")
        self.halt = None
        self.hwm = float(equity)

    # ---- persistence ---------------------------------------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"capital0": self.capital0, "cash": self.cash, "positions": {k: p.to_dict() for k, p in self.positions.items()},
                "realized": self.realized, "fees": self.fees, "hwm": self.hwm, "day": self.day, "day_start": self.day_start,
                "day_halted": self.day_halted, "halt": self.halt, "ledger": self.ledger}

    @classmethod
    def from_dict(cls, d: dict) -> "Account":
        a = cls(d["capital0"])
        a.cash, a.realized, a.fees, a.hwm = float(d["cash"]), float(d["realized"]), float(d["fees"]), float(d["hwm"])
        a.positions = {k: Position.from_dict(v) for k, v in d["positions"].items()}
        a.day, a.day_start, a.day_halted, a.halt, a.ledger = d["day"], d["day_start"], bool(d["day_halted"]), d["halt"], list(d["ledger"])
        if not a.verify_ledger():
            raise ValueError("the ledger's hash chain does not verify: the saved account was changed")
        return a

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)                                  # atomic: a crash never leaves half an account

    @classmethod
    def load(cls, path: Path) -> "Account":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
