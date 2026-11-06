"""The paper broker: fills against a real two-sided quote, through the risk gate, with costs. Paper money only.

A buy fills at the ask and a sell at the bid: the spread is paid in full, there is no mid-price optimism. An order bigger than the
size shown at the touch is refused rather than filled partly (a refusal is honest; a partial fill model is not built). Fees come
from the configured cost model, and only for segments whose costs are verified (the risk gate checks), so a segment with no
rates can never trade for free.

There is no function here that changes cash or a position except through `Account.apply_fill`.
"""
from __future__ import annotations

import datetime as dt
import math

from ..core.types import OPTION
from ..execution.costs import CostModel
from .account import Account
from .risk import Decision, Order, Quote, RiskGate


class PaperBroker:
    def __init__(self, cfg, account: Account, gate: RiskGate | None = None):
        self.cfg = cfg
        self.account = account
        self.gate = gate or RiskGate(cfg)
        self.costs = CostModel(cfg)

    def buy(self, order: Order, quote: Quote | None, marks: dict[str, float], now: dt.datetime) -> tuple[Decision, dict | None]:
        d = self.gate.check_entry(self.account, order, quote, marks, now)
        if not d.allowed:
            return d, None
        px = quote.ask
        fees, _ = self.costs.fees(order.instrument, order.qty, px)
        row = self.account.apply_fill("buy", order.instrument, order.segment, order.qty, px, fees, now.isoformat(), order.strategy, order.thesis)
        return d, row

    def sell(self, symbol: str, qty: int, quote: Quote | None, now: dt.datetime, why: str = "exit") -> tuple[Decision, dict | None]:
        d = self.gate.check_exit(self.account, symbol, qty, quote, now)
        if not d.allowed:
            return d, None
        pos = self.account.positions[symbol]
        px = quote.bid
        fees, _ = self.costs.fees(pos.instrument, -qty, px)
        row = self.account.apply_fill("sell", pos.instrument, pos.segment, qty, px, fees, now.isoformat(), pos.strategy, f"{why}: {pos.thesis}")
        return d, row

    def flatten(self, quotes: dict[str, Quote], now: dt.datetime, why: str) -> dict[str, Decision]:
        """Sell everything held, at whatever the bid is. A position with no usable quote or a closed market stays held and is reported."""
        out = {}
        for sym in list(self.account.positions):
            d, _ = self.sell(sym, self.account.positions[sym].qty, quotes.get(sym), now, why)
            out[sym] = d
        return out

    def settle_expired(self, day: dt.date, underlying_settle: dict[str, float], now: dt.datetime) -> dict[str, str]:
        """Cash-settle every long option that expired before `day` at its intrinsic value, with the exercise STT on a profit. A
        position whose underlying has no settlement price is left held and named: until it is settled its equity is unknown, so the
        gate refuses new entries. Returns {symbol: what happened}."""
        out = {}
        for sym, pos in list(self.account.positions.items()):
            inst = pos.instrument
            if inst.kind != OPTION or inst.expiry is None or inst.expiry >= day:
                continue
            s = underlying_settle.get(inst.underlying)
            if not (isinstance(s, (int, float)) and math.isfinite(s) and s > 0):
                out[sym] = "no settlement price for the underlying: left held"
                continue
            intrinsic = max(s - inst.strike, 0.0) if inst.right == "CE" else max(inst.strike - s, 0.0)
            fees = self.costs.exercise_stt(inst.expiry) * pos.qty * intrinsic       # STT on the intrinsic value of an exercised long option
            self.account.apply_fill("settle", inst, pos.segment, pos.qty, intrinsic, fees, now.isoformat(), pos.strategy,
                                    f"expired {inst.expiry:%d %b %Y}, settled at {s:g}: {pos.thesis}")
            out[sym] = f"settled at intrinsic {intrinsic:g}"
        return out
