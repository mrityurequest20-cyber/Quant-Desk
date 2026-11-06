"""The risk gate: the brakes of the paper desk. Built before any entry code, and every rule here fails CLOSED.

The owner's rule (6 Nov 2026): no cap on the number of trades or open positions, "only a loss cap". So the limits are all loss
limits, and there is no `max_trades` or `max_open`:
  * risk per trade    the most a single entry may lose (the whole premium paid, plus fees) as a share of equity
  * daily loss cap    when equity falls this far below the day's starting equity, new entries stop for the day (sticky) and
                      the runner is told to flatten
  * drawdown halt     when equity falls this far below its high-water mark, new entries stop until the OWNER clears it
  * kill switch       a file; while it exists nothing new opens and the runner is told to flatten
Exits (selling what is held) are never blocked by any of these: the brakes must never trap a position.

Fail closed: unknown equity, a missing or stale or crossed quote, a segment whose costs or holiday calendar are not verified, an
instrument kind this version does not model, a missing thesis, or any exception while checking: the entry is refused.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..core.types import OPTION, Instrument
from ..execution.costs import CostModel
from ..markets import sessions as MK
from .account import Account

IST = MK.IST


@dataclass(frozen=True)
class Limits:
    risk_per_trade: float            # share of equity one entry may lose
    daily_loss_limit: float          # share of the day's starting equity
    drawdown_halt: float             # share below the high-water mark
    max_quote_age_s: float           # a data-quality guard, not a strategy knob
    cost_verified: frozenset         # segments whose costs are configured and verified

    @classmethod
    def from_config(cls, cfg) -> "Limits":
        g = lambda k: cfg.get(f"paper.{k}")                                   # noqa: E731
        vals = [g("risk_per_trade"), g("daily_loss_limit"), g("drawdown_halt"), g("max_quote_age_s")]
        if any(v is None for v in vals):
            raise ValueError("paper.risk_per_trade, daily_loss_limit, drawdown_halt and max_quote_age_s must all be set in the config")
        return cls(float(vals[0]), float(vals[1]), float(vals[2]), float(vals[3]), frozenset(g("cost_verified_segments") or []))


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    ts: dt.datetime                 # timezone-aware
    bid_qty: float | None = None    # displayed size at the touch, when the feed has it
    ask_qty: float | None = None


@dataclass(frozen=True)
class Order:
    instrument: Instrument
    segment: str                    # "nse_fo", "bse_fo", "nse_cds", "mcx"
    qty: int                        # units, > 0 (a multiple of the lot size)
    strategy: str
    thesis: str                     # why this trade, now: required for every entry


@dataclass
class Decision:
    allowed: bool
    reasons: list[str] = field(default_factory=list)


class KillSwitch:
    """Active while the file exists. If the file cannot even be checked, it counts as active."""

    def __init__(self, path):
        self.path = Path(path)

    def active(self) -> bool:
        try:
            return self.path.exists()
        except OSError:
            return True


def _fin(x) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


class RiskGate:
    def __init__(self, cfg, limits: Limits | None = None, kill: KillSwitch | None = None):
        self.limits = limits or Limits.from_config(cfg)
        self.cal = MK.Calendars(cfg)
        self.costs = CostModel(cfg)
        self.kill = kill or KillSwitch(cfg.get("paper.kill_switch_file", "runtime/paper/KILL"))
        self.configured_costs = set((cfg.get("costs.segments") or {}).keys())

    # ---- state ---------------------------------------------------------------------------------------------------------------
    def update(self, account: Account, marks: dict[str, float], now: dt.datetime) -> list[str]:
        """Bring the account's day figures, high-water mark and halts up to date from fresh marks. Returns the reasons the desk must
        FLATTEN (empty: carry on). Halts only ever get set here, never cleared (the daily one by a new day, the other by the owner)."""
        eq = account.equity(marks)
        day = now.astimezone(IST).date().isoformat()
        if _fin(eq):
            if account.day != day:
                account.day, account.day_start, account.day_halted = day, eq, False
            account.hwm = max(account.hwm, eq)
            if account.day_start and eq - account.day_start <= -self.limits.daily_loss_limit * account.day_start:
                account.day_halted = True
            if account.halt is None and eq <= account.hwm * (1 - self.limits.drawdown_halt):
                account.halt = {"since": now.isoformat(), "equity": eq, "hwm": account.hwm,
                                "reason": f"equity {eq:,.0f} is {self.limits.drawdown_halt:.0%} or more below its high-water mark {account.hwm:,.0f}"}
        why = []
        if self.kill.active():
            why.append("the kill switch is on")
        if account.day_halted:
            why.append(f"the daily loss cap ({self.limits.daily_loss_limit:.0%} of the day's starting equity) was hit")
        if account.halt:
            why.append("the drawdown halt is on: " + account.halt["reason"])
        return why

    # ---- entries -------------------------------------------------------------------------------------------------------------
    def check_entry(self, account: Account, order: Order, quote: Quote | None, marks: dict[str, float], now: dt.datetime) -> Decision:
        try:
            return self._check_entry(account, order, quote, marks, now)
        except Exception as e:                                                  # noqa: BLE001 - any failure here refuses the trade
            return Decision(False, [f"the check itself failed ({type(e).__name__}): refused"])

    def _check_entry(self, account, order, quote, marks, now) -> Decision:
        why = list(self.update(account, marks, now))
        eq = account.equity(marks)
        if not _fin(eq):
            why.append("equity is unknown (a position has no usable mark)")
        inst, seg = order.instrument, order.segment
        if inst.kind != OPTION or not (isinstance(order.qty, int) and order.qty > 0):
            why.append("this version opens long options only: futures and short options need a margin model that is not built")
        elif order.qty % max(1, inst.lot_size):
            why.append(f"{order.qty} is not a whole number of lots of {inst.lot_size}")
        if seg not in MK.SEGMENTS:
            why.append(f"unknown segment {seg!r}")
        else:
            if seg not in self.limits.cost_verified or "options" not in self.configured_costs:
                why.append(f"the costs for {seg} are not configured and verified: they would be guessed, so nothing trades there")
            day = now.astimezone(IST).date()
            sess = MK.session(seg, day, self.cal, trading=True)
            if sess is None:
                why.append(f"{seg} does not trade today, or its holiday calendar is not verified for {day.year}")
            elif not (sess[0] <= now.astimezone(IST) < sess[1]):
                why.append(f"{seg} is closed at {now.astimezone(IST):%H:%M}")
        if inst.expiry is None or inst.expiry < now.astimezone(IST).date():
            why.append("the option has expired or has no expiry date")
        if not (order.strategy or "").strip() or not (order.thesis or "").strip():
            why.append("every entry needs a strategy name and a written thesis")
        if quote is None or not (_fin(quote.bid) and _fin(quote.ask) and 0 < quote.bid <= quote.ask):
            why.append("no usable two-sided quote")
        else:
            age = (now - quote.ts).total_seconds()
            if not (0 <= age <= self.limits.max_quote_age_s):
                why.append(f"the quote is {age:.0f}s old (limit {self.limits.max_quote_age_s:.0f}s) or from the future")
            if quote.ask_qty is not None and order.qty > quote.ask_qty:
                why.append(f"{order.qty} is more than the {quote.ask_qty:g} on offer")
            if not why and _fin(eq):
                fees, _ = self.costs.fees(inst, order.qty, quote.ask)
                outlay = order.qty * quote.ask + fees
                if outlay > self.limits.risk_per_trade * eq:
                    why.append(f"it would risk {outlay:,.0f} (the whole premium plus fees), over {self.limits.risk_per_trade:.1%} of equity "
                               f"({self.limits.risk_per_trade * eq:,.0f})")
                if outlay > account.cash:
                    why.append(f"it needs {outlay:,.0f} but cash is {account.cash:,.0f}")
        return Decision(not why, why)

    # ---- exits: never blocked by a brake ---------------------------------------------------------------------------------------
    def check_exit(self, account: Account, symbol: str, qty: int, quote: Quote | None, now: dt.datetime) -> Decision:
        try:
            pos = account.positions.get(symbol)
            why = []
            if pos is None or not (isinstance(qty, int) and 0 < qty <= pos.qty):
                why.append(f"cannot sell {qty} of {symbol}: holding {pos.qty if pos else 0}")
            if quote is None or not (_fin(quote.bid) and _fin(quote.ask) and 0 < quote.bid <= quote.ask):
                why.append("no usable two-sided quote")
            elif pos and quote.bid_qty is not None and qty > quote.bid_qty:
                why.append(f"{qty} is more than the {quote.bid_qty:g} bid")
            if pos:
                day = now.astimezone(IST).date()
                sess = MK.session(pos.segment, day, self.cal, trading=False)           # an exit needs only that the market is open
                if sess is None or not (sess[0] <= now.astimezone(IST) < sess[1]):
                    why.append(f"{pos.segment} is closed")
            return Decision(not why, why)
        except Exception as e:                                                  # noqa: BLE001
            return Decision(False, [f"the check itself failed ({type(e).__name__}): not sold"])
