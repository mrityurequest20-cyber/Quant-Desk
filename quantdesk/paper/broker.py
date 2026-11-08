"""The paper broker: fills against a real two-sided quote, through the risk gate, with costs. Paper money only.

A buy fills at the ask and a sell at the bid: the spread is paid in full, there is no mid-price optimism. On top of the touch a fill pays a
modelled impact that grows with the share of the displayed size it takes (`slippage.IMPACT_TABLE`); the gate judges the order at that
dearer price, so the risk caps hold on what is really paid. An order bigger than the size shown at the touch is refused rather than filled
partly (a refusal is honest; a partial fill model is not built). Every fill carries its slippage record (spread, delay since the trader looked, impact). Fees come
from the configured cost model, and only for segments whose costs are verified (the risk gate checks), so a segment with no
rates can never trade for free.

There is no function here that changes cash or a position except through `Account.apply_fill`.
"""
from __future__ import annotations

import datetime as dt
import math

from ..core.types import OPTION
from ..execution.costs import CostModel
from . import slippage as SL
from .account import Account, is_number
from .risk import Decision, Order, Quote, RiskGate


class PaperBroker:
    def __init__(self, cfg, account: Account, gate: RiskGate | None = None):
        self.cfg = cfg
        self.account = account
        self.gate = gate or RiskGate(cfg)
        self.costs = CostModel(cfg)
        self.tick = SL.TICK

    @staticmethod
    def _seen(ref: dict | None, now: dt.datetime):
        """What the trader saw (bid, ask) and the seconds since (None where the order carried nothing usable)."""
        if not isinstance(ref, dict):
            return None, None, None
        at = ref.get("at")
        delay = (now.timestamp() * 1000 - at) / 1000 if SL._ok(at) else None
        return ref.get("bid"), ref.get("ask"), delay

    def buy(self, order: Order, quote: Quote | None, marks: dict[str, float], now: dt.datetime, ref: dict | None = None) -> tuple[Decision, dict | None]:
        wide = quote
        impact = 0.0
        if quote is not None and is_number(quote.ask):
            impact = SL.impact_ticks(order.qty, quote.ask_qty) * self.tick
            wide = Quote(quote.bid, quote.ask + impact, quote.ts, quote.bid_qty, quote.ask_qty)      # the gate judges the order at the price it will really pay
        d = self.gate.check_entry(self.account, order, wide, marks, now)
        if not d.allowed:
            return d, None
        px = wide.ask
        fees, _ = self.costs.fees(order.instrument, order.qty, px)
        sb, sa, delay = self._seen(ref, now)
        slip = SL.clean(SL.split("buy", order.qty, px, quote.bid, quote.ask, impact, sb, sa, delay))
        row = self.account.apply_fill("buy", order.instrument, order.segment, order.qty, px, fees, now.isoformat(), order.strategy, order.thesis, slip)
        return d, row

    def sell(self, symbol: str, qty: int, quote: Quote | None, now: dt.datetime, why: str = "exit", ref: dict | None = None) -> tuple[Decision, dict | None]:
        d = self.gate.check_exit(self.account, symbol, qty, quote, now)
        if not d.allowed:
            return d, None
        pos = self.account.positions[symbol]
        impact = SL.impact_ticks(qty, quote.bid_qty) * self.tick
        px = max(quote.bid - impact, 0.0)
        impact = quote.bid - px                                                  # what was really given up (a bid below the impact is sold at nothing, not below)
        fees, _ = self.costs.fees(pos.instrument, -qty, px)
        sb, sa, delay = self._seen(ref, now)
        slip = SL.clean(SL.split("sell", qty, px, quote.bid, quote.ask, impact, sb, sa, delay))
        row = self.account.apply_fill("sell", pos.instrument, pos.segment, qty, px, fees, now.isoformat(), pos.strategy, f"{why}: {pos.thesis}", slip)
        return d, row

    def trim(self, quotes: dict[str, Quote], marks: dict[str, float], now: dt.datetime, why: str = "trim to the loss budget") -> dict[str, Decision]:
        """Sell just enough, biggest positions first, in whole lots, to bring the open premium back inside the loss budget (the gate's
        `trim_excess`). A position with no usable quote or a closed market stays held and is reported."""
        out = {}
        excess = self.gate.trim_excess(self.account, marks)
        for sym in sorted(self.account.positions, key=lambda k: -self.account.positions[k].qty * float(marks.get(k, 0.0) or 0.0)):
            if excess <= 0:
                break
            pos = self.account.positions[sym]
            mark = marks.get(sym)
            if not is_number(mark) or mark <= 0:
                continue
            lot = max(1, pos.instrument.lot_size)
            qty = min(pos.qty, -(-int(math.ceil(excess / mark)) // lot) * lot)
            d, row = self.sell(sym, qty, quotes.get(sym), now, why)
            out[sym] = d
            if row is not None:
                excess -= qty * mark
        return out

    def flatten(self, quotes: dict[str, Quote], now: dt.datetime, why: str) -> dict[str, Decision]:
        """Sell everything held, at whatever the bid is. A position with no usable quote or a closed market stays held and is reported."""
        out = {}
        for sym in list(self.account.positions):
            d, _ = self.sell(sym, self.account.positions[sym].qty, quotes.get(sym), now, why)
            out[sym] = d
        return out

    def settle_expired(self, day: dt.date, underlying_settle: dict[str, float], now: dt.datetime, only: set[str] | None = None) -> dict[str, str]:
        """Cash-settle every long option that expired before `day` at its intrinsic value, with the exercise STT on a profit. A
        position whose underlying has no settlement price is left held and named: until it is settled its equity is unknown, so the
        gate refuses new entries. `only` limits it to those symbols (the runner settles only what expires today, at today's index price). Returns {symbol: what happened}."""
        out = {}
        for sym, pos in list(self.account.positions.items()):
            inst = pos.instrument
            if inst.kind != OPTION or inst.expiry is None or inst.expiry >= day or (only is not None and sym not in only):
                continue
            if not (is_number(inst.strike) and inst.right in ("CE", "PE")):
                out[sym] = "no strike or right on the contract: left held"
                continue
            s = underlying_settle.get(inst.underlying)
            if not (is_number(s) and s > 0):
                out[sym] = "no settlement price for the underlying: left held"
                continue
            intrinsic = max(s - inst.strike, 0.0) if inst.right == "CE" else max(inst.strike - s, 0.0)
            fees = self.costs.exercise_stt(inst.expiry) * pos.qty * intrinsic       # STT on the intrinsic value of an exercised long option
            self.account.apply_fill("settle", inst, pos.segment, pos.qty, intrinsic, fees, now.isoformat(), pos.strategy,
                                    f"expired {inst.expiry:%d %b %Y}, settled at {s:g}: {pos.thesis}")
            out[sym] = f"settled at intrinsic {intrinsic:g}"
        return out
