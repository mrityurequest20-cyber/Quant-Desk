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
    def _seen(ref: dict | None, now: dt.datetime, quote: Quote | None = None):
        """What the trader saw (bid, ask) and the seconds since (None where the order carried nothing usable). The reference is client-supplied and only ever reported, so it must
        look like a price of this contract now: within a factor of two of the mid at the fill, else it is ignored. A time more than an hour back (or ahead) is dropped on its own."""
        if not isinstance(ref, dict):
            return None, None, None
        if quote is not None:
            m = (quote.bid + quote.ask) / 2
            rb, ra = ref.get("bid"), ref.get("ask")
            if not (SL._ok(rb) and SL._ok(ra) and m > 0 and 0.5 * m <= rb and ra <= 2 * m):
                return None, None, None
        at = ref.get("at")
        delay = (now.timestamp() * 1000 - at) / 1000 if SL._ok(at) else None
        if delay is not None and not (0 <= delay <= 3600):                       # a nonsense time costs only the delay figure, never the record
            delay = None
        return ref.get("bid"), ref.get("ask"), delay

    def buy(self, order: Order, quote: Quote | None, marks: dict[str, float], now: dt.datetime, ref: dict | None = None, limit: float | None = None) -> tuple[Decision, dict | None]:
        wide = quote
        impact = 0.0
        if quote is not None and is_number(quote.ask):
            impact = SL.impact_ticks(order.qty, quote.ask_qty) * self.tick
            wide = Quote(quote.bid, quote.ask + impact, quote.ts, quote.bid_qty, quote.ask_qty)      # the gate judges the order at the price it will really pay
        d = self.gate.check_entry(self.account, order, wide, marks, now)
        if not d.allowed:
            return d, None
        px = wide.ask
        if limit is not None and px > limit + 1e-9:                                  # the owner's "at most" is judged on what would really be paid, impact included
            return Decision(False, [f"the offer is {quote.ask:g} and this size is expected to pay {impact:g} more ({px:g}), above your limit {limit:g}: not bought"]), None
        fees, _ = self.costs.fees(order.instrument, order.qty, px)
        sb, sa, delay = self._seen(ref, now, quote)
        slip = SL.clean(SL.split("buy", order.qty, px, quote.bid, quote.ask, impact, sb, sa, delay)) or SL.clean(SL.split("buy", order.qty, px, quote.bid, quote.ask, impact))
        row = self.account.apply_fill("buy", order.instrument, order.segment, order.qty, px, fees, now.isoformat(), order.strategy, order.thesis, slip)
        return d, row

    def sell(self, symbol: str, qty: int, quote: Quote | None, now: dt.datetime, why: str = "exit", ref: dict | None = None, limit: float | None = None) -> tuple[Decision, dict | None]:
        d = self.gate.check_exit(self.account, symbol, qty, quote, now)
        if not d.allowed:
            return d, None
        pos = self.account.positions[symbol]
        impact = SL.impact_ticks(qty, quote.bid_qty) * self.tick
        px = max(quote.bid - impact, 0.0)
        impact = quote.bid - px                                                  # what was really given up (a bid below the impact is sold at nothing, not below)
        if limit is not None and px < limit - 1e-9:
            return Decision(False, [f"the bid is {quote.bid:g} and this size is expected to give up {impact:g} ({px:g}), below your limit {limit:g}: not sold"]), None
        fees, _ = self.costs.fees(pos.instrument, -qty, px)
        sb, sa, delay = self._seen(ref, now, quote)
        slip = SL.clean(SL.split("sell", qty, px, quote.bid, quote.ask, impact, sb, sa, delay)) or SL.clean(SL.split("sell", qty, px, quote.bid, quote.ask, impact))
        row = self.account.apply_fill("sell", pos.instrument, pos.segment, qty, px, fees, now.isoformat(), pos.strategy, f"{why}: {pos.thesis}", slip)
        return d, row

    # ---- sold options: packages, buying back --------------------------------------------------------------------------------------------
    def open_package(self, legs: list[dict], strategy: str, thesis: str, marks: dict[str, float], now: dt.datetime, refs: dict | None = None,
                     max_debit: float | None = None) -> tuple[Decision, list[dict]]:
        """Open several legs at once, bought and sold, or none. Each leg: {"side": "buy"|"sell", "instrument", "segment", "qty", "quote"}. A buy fills at the ask plus the modelled impact and a sale at
        the bid less it; the gate judges the package at those prices (`RiskGate.check_package`: bounded worst case, risk, loss budget); all the fills are made together and if any fails every one is
        undone. `max_debit` is the most the owner will pay in total for the package (a negative number is a credit he insists on). Returns (decision, the ledger rows)."""
        wide, impacts = [], []
        for l in legs:
            q, sell = l.get("quote"), l.get("side") == "sell"
            if q is None or not (is_number(q.bid) and is_number(q.ask)):
                wide.append(l)
                impacts.append(0.0)
                continue
            imp = SL.impact_ticks(l["qty"], q.bid_qty if sell else q.ask_qty) * self.tick
            impacts.append(imp)
            wide.append({**l, "quote": Quote(max(q.bid - imp, 0.0), q.ask, q.ts, q.bid_qty, q.ask_qty) if sell else Quote(q.bid, q.ask + imp, q.ts, q.bid_qty, q.ask_qty)})
        d = self.gate.check_package(self.account, wide, strategy, thesis, marks, now)
        if not d.allowed:
            return d, []
        debit = sum(l["qty"] * (l["quote"].bid if l["side"] == "sell" else l["quote"].ask) * (-1 if l["side"] == "sell" else 1) for l in wide)
        if max_debit is not None and debit > max_debit + 1e-9:
            return Decision(False, [f"the package would cost {debit:,.2f} net, more than your limit of {max_debit:,.2f}: not opened"]), []
        snap, rows = self.account.snapshot(), []
        try:
            for l, w, imp in sorted(zip(legs, wide, impacts), key=lambda x: x[0]["side"] != "sell"):          # the sales first: their cash pays for the purchases
                q, sell, inst = l["quote"], l["side"] == "sell", l["instrument"]
                px = w["quote"].bid if sell else w["quote"].ask
                fees, _ = self.costs.fees(inst, -l["qty"] if sell else l["qty"], px)
                ref = (refs or {}).get(inst.symbol)
                sb, sa, delay = self._seen(ref, now, q)
                side = "sell" if sell else "buy"
                slip = SL.clean(SL.split(side, l["qty"], px, q.bid, q.ask, (q.bid - px) if sell else imp, sb, sa, delay)) or SL.clean(SL.split(side, l["qty"], px, q.bid, q.ask, (q.bid - px) if sell else imp))
                rows.append(self.account.apply_fill("sto" if sell else "buy", inst, l["segment"], l["qty"], px, fees, now.isoformat(), strategy, thesis, slip))
        except Exception as e:                                                   # noqa: BLE001 - all or nothing
            self.account.restore(snap)
            return Decision(False, [f"the package could not be completed ({type(e).__name__}): nothing was opened"]), []
        return d, rows

    def cover(self, symbol: str, qty: int, quote: Quote | None, now: dt.datetime, why: str = "exit", ref: dict | None = None, limit: float | None = None) -> tuple[Decision, dict | None]:
        """Buy back (close) a sold option at the offer plus the modelled impact."""
        d = self.gate.check_cover(self.account, symbol, qty, quote, now)
        if not d.allowed:
            return d, None
        pos = self.account.positions[symbol]
        impact = SL.impact_ticks(qty, quote.ask_qty) * self.tick
        px = quote.ask + impact
        if limit is not None and px > limit + 1e-9:
            return Decision(False, [f"the offer is {quote.ask:g} and this size is expected to pay {impact:g} more ({px:g}), above your limit {limit:g}: not bought back"]), None
        fees, _ = self.costs.fees(pos.instrument, qty, px)
        sb, sa, delay = self._seen(ref, now, quote)
        slip = SL.clean(SL.split("buy", qty, px, quote.bid, quote.ask, impact, sb, sa, delay)) or SL.clean(SL.split("buy", qty, px, quote.bid, quote.ask, impact))
        row = self.account.apply_fill("btc", pos.instrument, pos.segment, qty, px, fees, now.isoformat(), pos.strategy, f"{why}: {pos.thesis}", slip)
        return d, row

    def close(self, symbol: str, qty: int, quote: Quote | None, now: dt.datetime, why: str = "exit", ref: dict | None = None, limit: float | None = None) -> tuple[Decision, dict | None]:
        """Close a position whichever way it is held: sell a long, buy back a short."""
        pos = self.account.positions.get(symbol)
        if pos is not None and pos.qty < 0:
            return self.cover(symbol, qty, quote, now, why, ref, limit)
        return self.sell(symbol, qty, quote, now, why, ref, limit)

    def trim(self, quotes: dict[str, Quote], marks: dict[str, float], now: dt.datetime, why: str = "trim to the loss budget") -> dict[str, Decision]:
        """Sell just enough, biggest positions first, in whole lots, to bring the open premium back inside the loss budget (the gate's
        `trim_excess`). A position with no usable quote or a closed market stays held and is reported."""
        out = {}
        if self.account.has_shorts():                                           # sold options cannot be trimmed piece by piece without risking an uncovered one: the whole book is closed
            return self.flatten(quotes, now, why)
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
        for sym in sorted(self.account.positions, key=lambda k: self.account.positions[k].qty >= 0):       # sold options first: buying them back never leaves anything uncovered
            pos = self.account.positions[sym]
            d, _ = self.close(sym, abs(pos.qty), quotes.get(sym), now, why)
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
            fees = self.costs.exercise_stt(inst.expiry) * pos.qty * intrinsic if pos.qty > 0 else 0.0       # STT on the intrinsic value of an exercised long option (a sold option pays the intrinsic, no STT)
            self.account.apply_fill("settle", inst, pos.segment, abs(pos.qty), intrinsic, fees, now.isoformat(), pos.strategy,
                                    f"expired {inst.expiry:%d %b %Y}, settled at {s:g}: {pos.thesis}")
            out[sym] = f"settled at intrinsic {intrinsic:g}"
        return out
