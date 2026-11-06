"""The risk gate: the brakes of the paper desk. Built before any entry code, and every rule here fails CLOSED.

The owner's rule (6 Nov 2026): no cap on the number of trades or open positions, "only a loss cap". So the limits are all loss
limits, and there is no `max_trades` or `max_open`. But a cap that is only checked now and then is a trigger, not a bound, so the
loss caps are enforced as BOUNDS:

  * risk per trade    one entry may lose at most this share of equity (the whole premium paid, plus fees)
  * the loss budget   an entry is refused unless, if every open position AND the new one fell to zero together, equity would still
                      stand above BOTH floors: the day's (starting equity less the daily loss limit) and the drawdown halt's
                      (high-water mark less the drawdown limit). So the day's loss and the drawdown cannot pass their caps by
                      opening more positions. There is still no cap on how many trades are made in a day: closing a position
                      frees its share of the budget, so a hundred trades one after another are all possible.
  * daily loss cap    when equity stands that far below the day's start (the previous close, so an overnight gap counts), new
                      entries stop for the day (sticky) and the runner is told to flatten
  * drawdown halt     when equity stands that far below its high-water mark, new entries stop until the OWNER clears it
  * kill switch       a file; while it exists nothing new opens and the runner is told to flatten
Exits (selling what is held) are never blocked by any of these: the brakes must never trap a position.

Fail closed: unknown equity, a missing, stale, future, crossed or oversized quote, a time or quote time with no timezone, a segment
whose costs or holiday calendar are not verified, an underlying that does not belong to the segment it is labelled with, an
instrument kind this version does not model, a missing thesis, or any exception while checking: the entry is refused. If equity
is unknown (a position has no price), the caps are still judged with that position counted as worth nothing, and if they would be
breached the runner is told to flatten.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..core.types import OPTION, Instrument
from ..execution.costs import CostModel
from ..markets import sessions as MK
from .account import Account, is_number, is_whole_positive

IST = MK.IST
ROOT = Path(__file__).resolve().parents[2]


def _share(x, name: str) -> float:
    if not (is_number(x) and 0 < x <= 1):
        raise ValueError(f"paper.{name} must be a number above 0 and at most 1, not {x!r}")
    return float(x)


@dataclass(frozen=True)
class Limits:
    risk_per_trade: float            # share of equity one entry may lose
    daily_loss_limit: float          # share of the day's starting equity
    drawdown_halt: float             # share below the high-water mark
    max_quote_age_s: float           # a data-quality guard, not a strategy knob
    cost_verified: frozenset         # segments whose costs are configured and verified
    underlyings: dict = field(default_factory=dict)   # segment -> the underlyings that trade in it (a mislabel guard)

    def __post_init__(self):
        for n in ("risk_per_trade", "daily_loss_limit", "drawdown_halt"):
            _share(getattr(self, n), n)
        if not (is_number(self.max_quote_age_s) and self.max_quote_age_s > 0):
            raise ValueError("paper.max_quote_age_s must be a positive number")

    @classmethod
    def from_config(cls, cfg) -> "Limits":
        g = lambda k: cfg.get(f"paper.{k}")                                   # noqa: E731
        vals = [g("risk_per_trade"), g("daily_loss_limit"), g("drawdown_halt"), g("max_quote_age_s")]
        if any(v is None for v in vals):
            raise ValueError("paper.risk_per_trade, daily_loss_limit, drawdown_halt and max_quote_age_s must all be set in the config")
        und = {seg: frozenset(str(u).upper() for u in us) for seg, us in (g("underlyings") or {}).items()}
        return cls(vals[0], vals[1], vals[2], vals[3], frozenset(g("cost_verified_segments") or []), und)


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
    """Active while the file exists. A relative path is taken from the repository root, not from wherever the process happens to
    run. If the file cannot even be checked, it counts as active."""

    def __init__(self, path):
        p = Path(path)
        self.path = p if p.is_absolute() else ROOT / p

    def active(self) -> bool:
        try:
            return self.path.exists()
        except OSError:
            return True


def _aware(t) -> bool:
    return isinstance(t, dt.datetime) and t.tzinfo is not None and t.utcoffset() is not None


def _two_sided(q) -> bool:
    return q is not None and is_number(q.bid) and is_number(q.ask) and 0 < q.bid <= q.ask


def _size_ok(x) -> bool:
    return x is None or (is_number(x) and x > 0)


class RiskGate:
    def __init__(self, cfg, limits: Limits | None = None, kill: KillSwitch | None = None):
        self.limits = limits or Limits.from_config(cfg)
        self.cal = MK.Calendars(cfg)
        self.costs = CostModel(cfg)
        self.kill = kill or KillSwitch(cfg.get("paper.kill_switch_file", "runtime/paper/KILL"))
        self.configured_costs = set((cfg.get("costs.segments") or {}).keys())

    # ---- state ---------------------------------------------------------------------------------------------------------------
    def floors(self, account: Account) -> tuple[float | None, float]:
        """(the day's floor, the drawdown floor): equity must stay above both."""
        day = account.day_start * (1 - self.limits.daily_loss_limit) if account.day_start else None
        return day, account.hwm * (1 - self.limits.drawdown_halt)

    def update(self, account: Account, marks: dict[str, float], now: dt.datetime) -> list[str]:
        """Bring the account's day figures, high-water mark and halts up to date from fresh marks. Returns the reasons the desk must
        FLATTEN (empty: carry on). Halts only ever get set here, never cleared (the daily one by a new day, the other by the owner)."""
        if not _aware(now):
            raise ValueError("the time must carry a timezone")
        eq = account.equity(marks)
        day = now.astimezone(IST).date().isoformat()
        if account.day is not None and day < account.day:        # a clock that runs backwards must never reset the day's cap
            raise ValueError(f"time went backwards: {day} is before {account.day}, which the account has already seen")
        why = []
        if is_number(eq):
            if account.day != day:                              # a new day starts from the last equity seen: an overnight gap counts
                account.day = day
                account.day_start = account.last_equity if is_number(account.last_equity) else eq
                account.day_halted = False
            account.last_equity = eq
            account.hwm = max(account.hwm, eq)
            if account.day_start and not account.day_halted and eq - account.day_start <= -self.limits.daily_loss_limit * account.day_start:
                account.day_halted = True
                account.record_event("daily_cap_hit", now.isoformat(), day=day, equity=eq, day_start=account.day_start)
            if account.halt is None and eq <= account.hwm * (1 - self.limits.drawdown_halt):
                account.halt = {"since": now.isoformat(), "equity": eq, "hwm": account.hwm,
                                "reason": f"equity {eq:,.0f} is {self.limits.drawdown_halt:.0%} or more below its high-water mark {account.hwm:,.0f}"}
                account.record_event("halt_set", now.isoformat(), equity=eq, hwm=account.hwm, reason=account.halt["reason"])
            excess = self.trim_excess(account, marks)
            if excess > 0:                                      # winners carried in can fall back further than the cap allows
                why.append(f"trim: the open positions are worth more than the loss budget allows, by {excess:,.0f}: sell that much")
        else:                                                   # a position has no price: judge the caps on the worst case, do not set sticky flags
            low = account.equity_lower_bound(marks)
            day_floor, dd_floor = self.floors(account)
            if (day_floor is not None and low <= day_floor) or low <= dd_floor:
                why.append("equity is unknown (a position has no price) and, counting it as worth nothing, a loss cap is breached: "
                           "flatten what can be sold")
        if self.kill.active():
            why.append("the kill switch is on")
        if account.day_halted:
            why.append(f"the daily loss cap ({self.limits.daily_loss_limit:.0%} of the day's starting equity) was hit")
        if account.halt is not None:
            why.append("the drawdown halt is on: " + str(account.halt.get("reason", "")))
        return why

    def trim_excess(self, account: Account, marks: dict[str, float]) -> float:
        """How much open premium is more than the loss budget allows: if every open position fell to zero together, equity would end
        below the day's or the drawdown floor by this much. Zero when the book fits the budget (or equity is unknown)."""
        eq = account.equity(marks)
        if not is_number(eq):
            return 0.0
        day_floor, dd_floor = self.floors(account)
        floor = max(dd_floor, day_floor if day_floor is not None else dd_floor)
        ov = account.open_value(marks)
        return max(0.0, ov - max(eq - floor, 0.0))

    # ---- entries -------------------------------------------------------------------------------------------------------------
    def check_entry(self, account: Account, order: Order, quote: Quote | None, marks: dict[str, float], now: dt.datetime) -> Decision:
        try:
            return self._check_entry(account, order, quote, marks, now)
        except Exception as e:                                                  # noqa: BLE001 - any failure here refuses the trade
            return Decision(False, [f"the check itself failed ({type(e).__name__}): refused"])

    def _check_entry(self, account, order, quote, marks, now) -> Decision:
        if not _aware(now) or (quote is not None and not _aware(quote.ts)):
            return Decision(False, ["a time with no timezone cannot be placed in the session: refused"])
        why = list(self.update(account, marks, now))
        eq = account.equity(marks)
        if not is_number(eq):
            why.append("equity is unknown (a position has no usable mark)")
        inst, seg = order.instrument, order.segment
        if inst.kind != OPTION or not is_whole_positive(order.qty):
            why.append("this version opens long options only: futures and short options need a margin model that is not built")
        elif not (isinstance(inst.lot_size, int) and inst.lot_size > 0) or order.qty % inst.lot_size:
            why.append(f"{order.qty} is not a whole number of lots of {inst.lot_size!r}")
        if seg not in MK.SEGMENTS:
            why.append(f"unknown segment {seg!r}")
        else:
            if seg not in self.limits.cost_verified or "options" not in self.configured_costs:
                why.append(f"the costs for {seg} are not configured and verified: they would be guessed, so nothing trades there")
            if not str(inst.symbol or "").upper().startswith(str(inst.underlying or "").upper()):
                why.append(f"the contract {inst.symbol!r} does not belong to its underlying {inst.underlying!r}")
            if (inst.underlying or "").upper() not in self.limits.underlyings.get(seg, frozenset()):
                why.append(f"{inst.underlying!r} is not on the list of underlyings that trade in {seg}: a mislabelled order would be "
                           "charged the wrong costs and hours")
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
        if not _two_sided(quote) or not (_size_ok(quote.ask_qty) and _size_ok(quote.bid_qty)):
            why.append("no usable two-sided quote")
        else:
            age = (now - quote.ts).total_seconds()
            if not (0 <= age <= self.limits.max_quote_age_s):
                why.append(f"the quote is {age:.0f}s old (limit {self.limits.max_quote_age_s:.0f}s) or from the future")
            if quote.ask_qty is not None and order.qty > quote.ask_qty:
                why.append(f"{order.qty} is more than the {quote.ask_qty:g} on offer")
            if not why and is_number(eq):
                fees, _ = self.costs.fees(inst, order.qty, quote.ask)
                outlay = order.qty * quote.ask + fees
                if outlay > self.limits.risk_per_trade * eq:
                    why.append(f"it would risk {outlay:,.0f} (the whole premium plus fees), over {self.limits.risk_per_trade:.1%} of equity "
                               f"({self.limits.risk_per_trade * eq:,.0f})")
                if outlay > account.cash:                                              # a second layer: the loss budget below already implies it
                    why.append(f"it needs {outlay:,.0f} but cash is {account.cash:,.0f}")
                day_floor, dd_floor = self.floors(account)
                floor = max(dd_floor, day_floor if day_floor is not None else dd_floor)
                budget = eq - floor
                at_risk = account.open_value(marks) + outlay
                if at_risk > budget:
                    why.append(f"if every open position and this one fell to zero together, {at_risk:,.0f} would be lost against a loss "
                               f"budget of {max(budget, 0):,.0f} left before the daily or drawdown floor")
        return Decision(not why, why)

    # ---- exits: never blocked by a brake ---------------------------------------------------------------------------------------
    def check_exit(self, account: Account, symbol: str, qty: int, quote: Quote | None, now: dt.datetime) -> Decision:
        try:
            pos = account.positions.get(symbol)
            why = []
            if not _aware(now) or (quote is not None and not _aware(quote.ts)):
                return Decision(False, ["a time with no timezone cannot be placed in the session: not sold"])
            if pos is None or not is_whole_positive(qty) or qty > pos.qty:
                why.append(f"cannot sell {qty!r} of {symbol}: holding {pos.qty if pos else 0}")
            if not _two_sided(quote) or not (_size_ok(quote.ask_qty) and _size_ok(quote.bid_qty)):
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
