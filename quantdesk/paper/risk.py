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

from ..core.types import FUTURE, OPTION, Instrument
from ..execution.costs import CostModel
from ..markets import sessions as MK
from .account import Account, is_number, is_whole_positive, stress_equity

IST = MK.IST
ROOT = Path(__file__).resolve().parents[2]
STRESS_MARGIN = 0.002   # equity kept in reserve above the loss floors when a package with sold options is judged on its worst case (exercise STT on a long that finishes in the money, exit costs)


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
    allow_short_legs: bool = False   # sell options as part of a HEDGED book (verticals, condors, butterflies...): off unless the config says so; an uncovered short is refused whatever this says

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
        return cls(vals[0], vals[1], vals[2], vals[3], frozenset(g("cost_verified_segments") or []), und, bool(g("allow_short_legs") is True))


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


FUTURES_ONLY = ("mcx", "nse_cds")         # MCX and currency: futures only (paper.futures, owner's order of 13 Nov 2026)


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
        below the day's or the drawdown floor by this much. Zero when the book fits the budget (or equity is unknown). With a short
        position in the book the measure is the worst-case equity (`Account.stress`): how far below the floor it falls."""
        eq = account.equity(marks)
        if not is_number(eq):
            return 0.0
        day_floor, dd_floor = self.floors(account)
        floor = max(dd_floor, day_floor if day_floor is not None else dd_floor)
        if account.has_shorts():
            st = account.stress()
            return float("inf") if st == float("-inf") else max(0.0, floor - st)
        ov = account.open_value(marks)
        return max(0.0, ov - max(eq - floor, 0.0))

    # ---- entries -------------------------------------------------------------------------------------------------------------
    def check_entry(self, account: Account, order: Order, quote: Quote | None, marks: dict[str, float], now: dt.datetime) -> Decision:
        try:
            if account.has_shorts():                                            # with a sold option in the book every entry is judged on the worst-case equity, one leg or many
                return self.check_package(account, [{"side": "buy", "instrument": order.instrument, "segment": order.segment, "qty": order.qty, "quote": quote}],
                                          order.strategy, order.thesis, marks, now)
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
            why.append("this version opens long options only (a sold option only inside a package): futures need a margin model that is not built")
        elif not (isinstance(inst.lot_size, int) and inst.lot_size > 0) or order.qty % inst.lot_size:
            why.append(f"{order.qty} is not a whole number of lots of {inst.lot_size!r}")
        if seg not in MK.SEGMENTS:
            why.append(f"unknown segment {seg!r}")
        elif seg in FUTURES_ONLY:
            why.append(f"{seg} trades futures only on this desk (paper.futures): an option is not opened there")
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

    # ---- MCX and currency futures (owner's order, 13 Nov 2026): long or short, every entry with a stop --------------------------------
    def check_future(self, account: Account, order: Order, short: bool, quote: Quote | None, px: float | None, stop, target, marks: dict[str, float],
                     now: dt.datetime, rules: dict) -> Decision:
        """A futures entry at fill price `px` (the offer for a long, the bid for a short). `rules`: the contract's paper.futures entry (lot, margin, no_entry_days) and the
        section's square_off/entry cutoff and stop_max_pct, plus `margins` {underlying: rate}. The loss to the stop, with a slippage allowance and both sides' fees, is held to
        risk_per_trade, as the whole premium is for an option; the margin to what equity has free; and, with everything else open, to the loss budget."""
        try:
            return self._check_future(account, order, short, quote, px, stop, target, marks, now, rules)
        except Exception as e:                                                  # noqa: BLE001 - a check that fails refuses, never allows
            return Decision(False, [f"the check itself failed ({type(e).__name__}): not opened"])

    def _check_future(self, account, order, short, quote, px, stop, target, marks, now, rules) -> Decision:
        if not _aware(now) or (quote is not None and not _aware(quote.ts)):
            return Decision(False, ["a time with no timezone cannot be placed in the session: refused"])
        why = list(self.update(account, marks, now))
        eq = account.equity(marks)
        if not is_number(eq):
            why.append("equity is unknown (a position has no usable mark)")
        inst, seg = order.instrument, order.segment
        if inst.kind != FUTURE or seg not in FUTURES_ONLY:
            why.append("not an MCX or currency future")
        if not is_whole_positive(order.qty) or not (isinstance(inst.lot_size, int) and inst.lot_size > 0) or order.qty % inst.lot_size:
            why.append(f"{order.qty!r} is not a whole number of lots of {inst.lot_size!r}")
        if seg in FUTURES_ONLY:
            cost_key = "mcx_futures" if seg == "mcx" else "cds_futures"
            if seg not in self.limits.cost_verified or cost_key not in self.configured_costs:
                why.append(f"the costs for {seg} futures are not configured and verified: nothing trades there")
            if (inst.underlying or "").upper() not in self.limits.underlyings.get(seg, frozenset()):
                why.append(f"{inst.underlying!r} is not on the list of underlyings that trade in {seg}")
            ist = now.astimezone(IST)
            sess = MK.session(seg, ist.date(), self.cal, trading=True)
            cutoff = dt.timedelta(minutes=int(rules.get("entry_cutoff_min", 15)))
            if sess is None:
                why.append(f"{seg} does not trade today, or its holiday calendar is not verified for {ist.year}")
            elif not (sess[0] <= ist < sess[1] - cutoff):
                why.append(f"{seg} is closed at {ist:%H:%M}, or within {cutoff.seconds // 60} minutes of its close (futures are closed before it: intraday only)")
            if inst.expiry is None:
                why.append("the board does not say which contract month this is: not opened")
            elif inst.expiry < ist.date():
                why.append("the contract has expired")
            else:
                n, d = 0, ist.date()                                             # this segment's trading days from today to the expiry
                while d < inst.expiry and n < 40:
                    d += dt.timedelta(days=1)
                    if MK.session(seg, d, self.cal) is not None:
                        n += 1
                if n < int(rules.get("no_entry_days", 5)):
                    why.append(f"{inst.expiry:%d %b} is {n} trading day{'s' if n != 1 else ''} away: no new entry in a contract's last {rules.get('no_entry_days')} (delivery or settlement)")
        if not (order.strategy or "").strip() or not (order.thesis or "").strip():
            why.append("every entry needs a strategy name and a written thesis")
        if not _two_sided(quote) or not (_size_ok(quote.ask_qty) and _size_ok(quote.bid_qty)) or not is_number(px) or px <= 0:
            why.append("no usable two-sided quote")
        else:
            age = (now - quote.ts).total_seconds()
            if not (0 <= age <= self.limits.max_quote_age_s):
                why.append(f"the quote is {age:.0f}s old (limit {self.limits.max_quote_age_s:.0f}s) or from the future")
            shown = quote.bid_qty if short else quote.ask_qty
            if shown is not None and order.qty > shown:
                why.append(f"{order.qty} is more than the {shown:g} {'bid' if short else 'offered'}")
            if not (is_number(stop) and stop > 0):
                why.append("every futures entry needs a stop price")
            elif (short and stop <= px) or (not short and stop >= px):
                why.append(f"the stop {stop:g} must be {'above' if short else 'below'} the {'bid' if short else 'offer'} {px:g}")
            elif abs(px - stop) / px > float(rules.get("stop_max_pct", 0.10)):
                why.append(f"the stop is {abs(px - stop) / px:.1%} away: more than {float(rules.get('stop_max_pct', 0.10)):.0%} looks like a typo")
            if target is not None and not (is_number(target) and target > 0 and ((short and target < px) or (not short and target > px))):
                why.append(f"the target must be {'below' if short else 'above'} the entry")
            if not why and is_number(eq):
                fees_in, _ = self.costs.fees(inst, -order.qty if short else order.qty, px)
                fees_out, _ = self.costs.fees(inst, order.qty if short else -order.qty, stop)
                slip = 0.001 * px                                                 # a stop fills worse than its price: a tenth of a percent allowed for it
                risk = order.qty * (abs(px - stop) + slip) + fees_in + fees_out
                if risk > self.limits.risk_per_trade * eq:
                    why.append(f"to the stop it would risk {risk:,.0f} (with a slippage allowance and both sides' fees), over {self.limits.risk_per_trade:.1%} of equity "
                               f"({self.limits.risk_per_trade * eq:,.0f}): a closer stop or fewer lots")
                rates = rules.get("margins") or {}
                margin = order.qty * px * float(rules.get("margin", 1.0))
                used = account.margin_used(marks, rates)
                if used + margin > eq:
                    why.append(f"it needs {margin:,.0f} of margin; {used:,.0f} is in use and equity is {eq:,.0f}")
                if fees_in > account.cash:
                    why.append(f"the fees of {fees_in:,.0f} are more than the cash")
                day_floor, dd_floor = self.floors(account)
                floor = max(dd_floor, day_floor if day_floor is not None else dd_floor)
                at_risk = account.open_value(marks) + risk
                if not (at_risk <= eq - floor):
                    why.append(f"if every open position went to its worst together with this one at its stop, {at_risk:,.0f} would be lost against a loss budget of "
                               f"{max(eq - floor, 0):,.0f} left before the daily or drawdown floor")
        return Decision(not why, why)

    # ---- packages: several legs at once, some of them SOLD, judged together ------------------------------------------------------------
    def check_package(self, account: Account, legs: list[dict], strategy: str, thesis: str, marks: dict[str, float], now: dt.datetime) -> Decision:
        """Open several option legs together, or none. Each leg: {"side": "buy"|"sell", "instrument", "segment", "qty" (units), "quote" (the price it will really get: a buy pays the ask, a sale gets the bid)}.
        A sold leg is only ever allowed inside a book whose WORST CASE is bounded (`stress_equity`): every short call covered by a long call of the same underlying and expiry, so a naked short, a
        ratio spread with too few longs and a calendar (whose cover expires first) are all refused. The package's risk is how much worse the worst case gets (fees included) and must fit the
        per-trade limit; the worst-case equity after it must stay above the day's and the drawdown floor, which is the loss budget generalised to sold options."""
        try:
            return self._check_package(account, legs, strategy, thesis, marks, now)
        except Exception as e:                                                  # noqa: BLE001 - any failure here refuses the trade
            return Decision(False, [f"the check itself failed ({type(e).__name__}): refused"])

    def _check_package(self, account, legs, strategy, thesis, marks, now) -> Decision:
        if not _aware(now) or any(l.get("quote") is not None and not _aware(l["quote"].ts) for l in legs):
            return Decision(False, ["a time with no timezone cannot be placed in the session: refused"])
        why = list(self.update(account, marks, now))
        eq = account.equity(marks)
        if not is_number(eq):
            why.append("equity is unknown (a position has no usable mark)")
        if not legs or not all(l.get("side") in ("buy", "sell") for l in legs):
            return Decision(False, why + ["a package needs at least one leg, each a buy or a sale"])
        if any(l["side"] == "sell" for l in legs) and not self.limits.allow_short_legs:
            why.append("selling options is switched off (paper.allow_short_legs): only bought options can be opened")
        if len({l["instrument"].symbol for l in legs}) != len(legs):
            why.append("a contract appears twice in the package")
        if not (strategy or "").strip() or not (thesis or "").strip():
            why.append("every entry needs a strategy name and a written thesis")
        day = now.astimezone(IST).date()
        for l in legs:
            inst, seg, qty, quote, sell = l["instrument"], l["segment"], l["qty"], l.get("quote"), l["side"] == "sell"
            tag = f"{inst.symbol}: "
            if inst.kind != OPTION or not is_whole_positive(qty):
                why.append(tag + "only options can be opened (futures need a margin model that is not built)")
            elif not (isinstance(inst.lot_size, int) and inst.lot_size > 0) or qty % inst.lot_size:
                why.append(tag + f"{qty} is not a whole number of lots of {inst.lot_size!r}")
            if seg not in MK.SEGMENTS:
                why.append(tag + f"unknown segment {seg!r}")
            else:
                if seg not in self.limits.cost_verified or "options" not in self.configured_costs:
                    why.append(tag + f"the costs for {seg} are not configured and verified: they would be guessed, so nothing trades there")
                if not str(inst.symbol or "").upper().startswith(str(inst.underlying or "").upper()):
                    why.append(tag + f"the contract does not belong to its underlying {inst.underlying!r}")
                if (inst.underlying or "").upper() not in self.limits.underlyings.get(seg, frozenset()):
                    why.append(tag + f"{inst.underlying!r} is not on the list of underlyings that trade in {seg}")
                sess = MK.session(seg, day, self.cal, trading=True)
                if sess is None:
                    why.append(tag + f"{seg} does not trade today, or its holiday calendar is not verified for {day.year}")
                elif not (sess[0] <= now.astimezone(IST) < sess[1]):
                    why.append(tag + f"{seg} is closed at {now.astimezone(IST):%H:%M}")
            if inst.expiry is None or inst.expiry < day:
                why.append(tag + "the option has expired or has no expiry date")
            held = account.positions.get(inst.symbol)
            if held is not None and ((held.qty > 0) == sell):
                why.append(tag + ("it is held long: sell it to close, do not sell it to open" if sell else "it is held short: buy it to close, do not buy it to open"))
            if not _two_sided(quote) or not (_size_ok(quote.ask_qty) and _size_ok(quote.bid_qty)):
                why.append(tag + "no usable two-sided quote")
            else:
                age = (now - quote.ts).total_seconds()
                if not (0 <= age <= self.limits.max_quote_age_s):
                    why.append(tag + f"the quote is {age:.0f}s old (limit {self.limits.max_quote_age_s:.0f}s) or from the future")
                shown = quote.bid_qty if sell else quote.ask_qty
                if shown is not None and qty > shown:
                    why.append(tag + f"{qty} is more than the {shown:g} {'bid' if sell else 'on offer'}")
        if why or not is_number(eq):
            return Decision(False, why)
        cash_after = account.cash
        after = {s: type(p)(p.instrument, p.segment, p.qty, p.avg_price, p.opened_at, p.strategy, p.thesis, p.stop, p.target) for s, p in account.positions.items()}
        for l in legs:
            inst, qty, sell, q = l["instrument"], l["qty"], l["side"] == "sell", l["quote"]
            px = q.bid if sell else q.ask
            fees, _ = self.costs.fees(inst, -qty if sell else qty, px)
            cash_after += (qty * px - fees) if sell else -(qty * px + fees)
            signed = -qty if sell else qty
            if inst.symbol in after:
                after[inst.symbol].qty += signed
                if after[inst.symbol].qty == 0:
                    del after[inst.symbol]
            else:
                from .account import Position
                after[inst.symbol] = Position(inst, l["segment"], signed, px, now.isoformat(), strategy, thesis)
        before, worst = account.stress(), stress_equity(cash_after, after)
        if worst == float("-inf"):
            return Decision(False, ["this would leave a sold option uncovered (a short call without a long call of the same expiry behind it, or a position that cannot be valued): the loss would have no limit"])
        risk = before - worst
        if not (risk <= self.limits.risk_per_trade * eq + 1e-9):
            why.append(f"it would put {risk:,.0f} at risk (its worst possible loss plus fees), over {self.limits.risk_per_trade:.1%} of equity ({self.limits.risk_per_trade * eq:,.0f})")
        if not any(l["side"] == "sell" for l in legs):                          # bought options only: the plain rules apply as they always did (the whole premium plus fees is the risk, and it shares the loss budget with what is open), whatever the worst-case arithmetic says
            outlay = sum(l["qty"] * l["quote"].ask + self.costs.fees(l["instrument"], l["qty"], l["quote"].ask)[0] for l in legs)
            if outlay > self.limits.risk_per_trade * eq + 1e-9:
                why.append(f"it would risk {outlay:,.0f} (the whole premium plus fees), over {self.limits.risk_per_trade:.1%} of equity ({self.limits.risk_per_trade * eq:,.0f})")
            d_floor, f_floor = self.floors(account)
            fl = max(f_floor, d_floor if d_floor is not None else f_floor)
            longs = [(s, p) for s, p in account.positions.items() if p.qty > 0]
            if any(not (is_number(marks.get(s)) and marks[s] >= 0) for s, _ in longs):
                why.append("a held option has no usable price, so the loss budget cannot be checked")
            elif sum(p.qty * marks[s] for s, p in longs) + outlay > eq - fl:
                why.append(f"the premium at risk would exceed the loss budget ({max(eq - fl, 0):,.0f} left before the daily or drawdown floor)")
        if cash_after < -1e-9:
            why.append(f"it needs cash of {account.cash - cash_after:,.0f} but cash is {account.cash:,.0f}")
        day_floor, dd_floor = self.floors(account)
        floor = max(dd_floor, day_floor if day_floor is not None else dd_floor)
        if worst < floor + STRESS_MARGIN * eq:                                  # a small reserve for what the arithmetic leaves out: the exercise STT on a long that finishes in the money, and exit costs
            why.append(f"if everything expired now at the worst price, equity would be {worst:,.0f}, too near the {floor:,.0f} floor (the day's or the drawdown limit; {STRESS_MARGIN:.1%} of equity is kept in reserve)")
        return Decision(not why, why)

    def check_cover(self, account: Account, symbol: str, qty: int, quote: Quote | None, now: dt.datetime) -> Decision:
        """Buy back (close) a sold option. Like every exit it is never blocked by a brake: it only ever reduces the risk."""
        try:
            pos = account.positions.get(symbol)
            why = []
            if not _aware(now) or (quote is not None and not _aware(quote.ts)):
                return Decision(False, ["a time with no timezone cannot be placed in the session: not covered"])
            if pos is None or pos.qty >= 0 or not is_whole_positive(qty) or qty > -pos.qty:
                why.append(f"cannot buy back {qty!r} of {symbol}: short {-pos.qty if pos and pos.qty < 0 else 0}")
            if not _two_sided(quote) or not (_size_ok(quote.ask_qty) and _size_ok(quote.bid_qty)):
                why.append("no usable two-sided quote")
            elif pos and quote.ask_qty is not None and qty > quote.ask_qty:
                why.append(f"{qty} is more than the {quote.ask_qty:g} on offer")
            if pos:
                day = now.astimezone(IST).date()
                sess = MK.exit_session(pos.segment, day, self.cal)
                if sess is None or not (sess[0] <= now.astimezone(IST) < sess[1]):
                    why.append(f"{pos.segment} is closed")
            return Decision(not why, why)
        except Exception as e:                                                  # noqa: BLE001
            return Decision(False, [f"the check itself failed ({type(e).__name__}): not covered"])

    # ---- exits: never blocked by a brake ---------------------------------------------------------------------------------------
    def check_exit(self, account: Account, symbol: str, qty: int, quote: Quote | None, now: dt.datetime) -> Decision:
        try:
            pos = account.positions.get(symbol)
            why = []
            if not _aware(now) or (quote is not None and not _aware(quote.ts)):
                return Decision(False, ["a time with no timezone cannot be placed in the session: not sold"])
            if pos is None or not is_whole_positive(qty) or pos.qty <= 0 or qty > pos.qty:
                why.append(f"cannot sell {qty!r} of {symbol}: holding {pos.qty if pos else 0}")
            elif account.has_shorts():                                                   # selling a long that is the cover of a sold option would leave that option naked: close the short first
                rest = {s: type(p)(p.instrument, p.segment, p.qty, p.avg_price, p.opened_at, p.strategy, p.thesis, p.stop, p.target) for s, p in account.positions.items()}
                rest[symbol].qty -= qty
                if rest[symbol].qty == 0:
                    del rest[symbol]
                worst, before = stress_equity(account.cash, rest), account.stress()
                day_floor, dd_floor = self.floors(account)
                floor = max(dd_floor, day_floor if day_floor is not None else dd_floor)
                if worst == float("-inf") and before != float("-inf"):
                    why.append("selling this would leave a sold option uncovered (no limit on the loss): buy the sold option back first")
                elif worst < before - 1e-6 and worst < floor:                                   # only a sale that LOWERS the worst case can be refused: an unrelated long is always free to go                                                      # a put spread stripped of its long put is "bounded" only by the strike: far past the loss floors
                    why.append(f"selling this would leave a sold option without its cover: the worst case would be equity of {worst:,.0f}, under the {floor:,.0f} floor: buy the sold option back first")
            if not _two_sided(quote) or not (_size_ok(quote.ask_qty) and _size_ok(quote.bid_qty)):
                why.append("no usable two-sided quote")
            elif pos and quote.bid_qty is not None and qty > quote.bid_qty:
                why.append(f"{qty} is more than the {quote.bid_qty:g} bid")
            if pos:
                day = now.astimezone(IST).date()
                sess = MK.exit_session(pos.segment, day, self.cal)                       # an exit needs only that the market is open (or an announced special session)
                if sess is None or not (sess[0] <= now.astimezone(IST) < sess[1]):
                    why.append(f"{pos.segment} is closed")
            return Decision(not why, why)
        except Exception as e:                                                  # noqa: BLE001
            return Decision(False, [f"the check itself failed ({type(e).__name__}): not sold"])
