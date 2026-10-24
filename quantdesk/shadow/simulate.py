"""Outcome simulation: what would have happened after a setup, on the minutes that follow the decision.

Entry is on the NEXT bar (the bar that opens at the decision time); exits follow the plan's own rules in the same order the
engine's `_manage` checks them (invalidation, range break, premium stop, premium target, underlying target, breakeven
stop, time exit) plus the square-off, evaluated on each bar's close and filled at the NEXT bar's open. Two labels:

* underlying (u_*): from the index minutes alone: always possible when the minutes exist, real prices only;
* option (net_pnl...): from Kotak's traded option minutes for every leg. Fills are the bar's open worse by the desk's
  option half-spread, its adverse ticks and the shadow's extra haircut; costs are the desk's CostModel. A leg with no
  traded bar is never filled at a made-up price: the setup is `unlabelled` with the reason."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..core.types import Instrument
from ..execution.costs import CostModel

BAR = pd.Timedelta(minutes=1)
STALE_MARK_MIN = 5


@dataclass
class Haircut:
    cost: CostModel
    adverse_ticks: float
    extra_pct: float
    extra_ticks: float

    @classmethod
    def from_cfg(cls, cfg) -> "Haircut":
        sl = cfg.get("shadow.slippage", {}) or {}
        return cls(CostModel(cfg), float(cfg.get("intraday.adverse_ticks", 1)), float(sl.get("extra_pct", 0.01)),
                   float(sl.get("extra_ticks", 1)))

    def per_unit(self, inst: Instrument, price: float) -> float:
        """Adverse move per unit on one fill: the desk's half-spread model + its adverse ticks + the shadow's extra."""
        t = self.cost.tick
        return self.cost.slippage(inst, price) + (self.adverse_ticks + self.extra_ticks) * t + self.extra_pct * price

    def fill(self, inst: Instrument, qty: int, raw: float) -> float:
        px = raw + self.per_unit(inst, raw) if qty > 0 else raw - self.per_unit(inst, raw)
        return max(round(px / self.cost.tick) * self.cost.tick, self.cost.tick)


@dataclass
class Outcome:
    u_status: str = "unlabelled"                 # labelled | unlabelled
    u_reason: str | None = None
    u_entry: float | None = None
    u_exit: float | None = None
    u_exit_time: pd.Timestamp | None = None
    u_exit_reason: str | None = None
    u_r: float | None = None
    u_mae_pts: float | None = None
    u_mfe_pts: float | None = None
    status: str = "unlabelled"
    reason: str | None = None
    entry_time: pd.Timestamp | None = None
    exit_time: pd.Timestamp | None = None
    exit_reason: str | None = None
    entry_prices: list = field(default_factory=list)
    exit_prices: list = field(default_factory=list)
    gross_pnl: float | None = None
    net_pnl: float | None = None
    fees: float | None = None
    slippage_cost: float | None = None
    mae: float | None = None
    mfe: float | None = None
    stale_marks: int = 0
    held_min: int | None = None


def _hm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def _check_exit(plan, d: int, S: float, held: int, gross: float | None, prem: float | None, mfe: float | None,
                t_close: pd.Timestamp, square_off: dt.time, entry_S: float):
    """The engine's _manage rule order. gross/prem are None for the underlying-only label."""
    if plan.invalidation is not None and d and ((d > 0 and S <= plan.invalidation) or (d < 0 and S >= plan.invalidation)):
        return "invalidation"
    rng = (plan.notes or {}).get("range")
    if rng and not (rng[0] <= S <= rng[1]):
        return "range_break"
    if gross is not None:
        if gross <= -prem * plan.premium_stop:
            return "premium_stop"
        if gross >= prem * plan.premium_target:
            return "premium_target"
    if plan.target_underlying is not None and d and ((d > 0 and S >= plan.target_underlying) or (d < 0 and S <= plan.target_underlying)):
        return "underlying_target"
    if gross is not None:
        if mfe is not None and mfe > 0.5 * prem * plan.premium_target and gross <= 0:
            return "breakeven_stop"
        if held >= plan.time_stop_min and gross < 0.1 * prem:
            return "time_exit"
    else:
        risk = abs(entry_S - plan.invalidation) if plan.invalidation is not None else 0.0
        progress = d * (S - entry_S) if d else -abs(S - entry_S)
        if held >= plan.time_stop_min and progress < 0.1 * risk:
            return "time_exit"
    if t_close.time() >= square_off:
        return "square_off"
    return None


def simulate_underlying(plan, d: int, bars: pd.DataFrame, entry_ts: pd.Timestamp, square_off: dt.time,
                        entry_price: float | None = None) -> Outcome:
    """The underlying's path after entry. entry_price: the level an armed order filled at (inside the entry bar); else the
    open of the entry bar."""
    o = Outcome()
    path = bars[bars.index >= entry_ts]
    if path.empty or path.index[0] != entry_ts:
        o.u_reason = "no underlying bar at the entry minute"
        return o
    S0 = float(entry_price if entry_price is not None else path["open"].iloc[0])
    o.u_entry = S0
    hi = lo = S0
    for i, (ts, b) in enumerate(path.iterrows()):
        t_close = ts + BAR
        hi, lo = max(hi, float(b["high"])), min(lo, float(b["low"]))
        S = float(b["close"])
        why = _check_exit(plan, d, S, i + 1, None, None, None, t_close, square_off, S0)
        last = i == len(path) - 1
        if why is None and last:
            why = "data_end"
        if why:
            nxt = path.iloc[i + 1] if i + 1 < len(path) else None
            o.u_exit = float(nxt["open"]) if nxt is not None else S
            o.u_exit_time = path.index[i + 1] if nxt is not None else t_close
            o.u_exit_reason = why
            risk = abs(S0 - plan.invalidation) if plan.invalidation is not None else None
            o.u_r = (d * (o.u_exit - S0) / risk) if (risk and d) else None
            o.u_mae_pts = (S0 - lo) if d > 0 else (hi - S0) if d < 0 else max(S0 - lo, hi - S0)
            o.u_mfe_pts = (hi - S0) if d > 0 else (S0 - lo) if d < 0 else 0.0
            o.u_status = "labelled" if why != "data_end" else "unlabelled"
            if why == "data_end":
                o.u_reason = "the session's minutes end before an exit rule fired"
            return o
    o.u_reason = "no bars after entry"
    return o


def simulate_options(plan, d: int, bars: pd.DataFrame, book, day: dt.date, entry_ts: pd.Timestamp, lot: int,
                     hc: Haircut, square_off: dt.time, max_wait_min: int, underlying: str) -> Outcome:
    """The plan's own legs on Kotak's traded option minutes, 1 lot."""
    o = Outcome()
    legs = plan.legs
    if book is None or not len(book.df):
        o.reason = "no option minutes for this instrument"
        return o
    lb = []
    for l in legs:
        b = book.bars(plan.expiry, l.strike, l.right, day)
        if b is None:
            o.reason = f"no option minutes for {l.strike:g}{l.right} {plan.expiry}"
            return o
        lb.append(b)
    # each leg fills at its first traded bar at or after the decision, within max_wait_min: never at a made-up price
    ents = []
    for l, b in zip(legs, lb):
        after = b[(b.index >= entry_ts) & (b.index <= entry_ts + pd.Timedelta(minutes=max_wait_min))]
        if after.empty:
            o.reason = f"{l.strike:g}{l.right} has no traded bar within {max_wait_min} min of the entry"
            return o
        ents.append(after.index[0])
    t_in = max(ents)
    insts = [Instrument.option(underlying, plan.expiry, l.strike, l.right, lot) for l in legs]
    raw_in = [float(b.loc[t_in]["open"]) if t_in in b.index else float(b[b.index <= t_in]["close"].iloc[-1]) for b in lb]
    if not all(p > 0 for p in raw_in):
        o.reason = "a leg's entry bar has a zero price"
        return o
    fill_in = [hc.fill(i, l.ratio * lot, p) for i, l, p in zip(insts, legs, raw_in)]
    entry_value = sum(l.ratio * lot * p for l, p in zip(legs, fill_in))
    prem = abs(entry_value)
    if prem <= 0:
        o.reason = "zero net premium"
        return o
    path = bars[bars.index >= t_in]
    if path.empty or path.index[0] != t_in:
        o.reason = "no underlying bar at the option entry minute"
        return o
    marks, seen = [], []
    for b in lb:
        u = path.index.union(b.index)
        m = b["close"].reindex(u)
        last = pd.Series(np.where(m.notna(), u.asi8, np.nan), index=u).ffill()    # when each mark last really traded
        marks.append(m.ffill().reindex(path.index))
        seen.append(last.reindex(path.index))
    mfe, mae, stale = 0.0, 0.0, 0
    for i, (ts, b) in enumerate(path.iterrows()):
        t_close = ts + BAR
        mk = [float(m.iloc[i]) if m.iloc[i] == m.iloc[i] else None for m in marks]
        if any(x is None for x in mk):
            mk = [x if x is not None else raw_in[j] for j, x in enumerate(mk)]
        for j in range(len(legs)):
            age = (ts.value - seen[j].iloc[i]) / 6e10 if seen[j].iloc[i] == seen[j].iloc[i] else 0
            if age > STALE_MARK_MIN:
                stale += 1
                break
        gross = sum(l.ratio * lot * m for l, m in zip(legs, mk)) - entry_value
        mfe, mae = max(mfe, gross), min(mae, gross)
        why = _check_exit(plan, d, float(b["close"]), i + 1, gross, prem, mfe, t_close, square_off, float(path["open"].iloc[0]))
        last = i == len(path) - 1
        if why is None and last:
            o.reason = "the session's minutes end before an exit rule fired"
            return o
        if why:
            t_out = path.index[i + 1] if i + 1 < len(path) else t_close
            raw_out = []
            for j, (l, bb) in enumerate(zip(legs, lb)):
                nb = bb[bb.index >= t_out]
                raw_out.append(float(nb["open"].iloc[0]) if len(nb) and nb.index[0] <= t_out + pd.Timedelta(minutes=max_wait_min)
                               else mk[j])
            fill_out = [hc.fill(ins, -l.ratio * lot, p) for ins, l, p in zip(insts, legs, raw_out)]
            fees = 0.0
            for ins, l, pi, po in zip(insts, legs, fill_in, fill_out):
                fees += hc.cost.fees(ins, l.ratio * lot, pi)[0] + hc.cost.fees(ins, -l.ratio * lot, po)[0]
            gross_raw = sum(l.ratio * lot * (po - pi_) for l, po, pi_ in zip(legs, raw_out, raw_in))
            net = sum(l.ratio * lot * (po - pi) for l, po, pi in zip(legs, fill_out, fill_in)) - fees
            o.status, o.entry_time, o.exit_time, o.exit_reason = "labelled", t_in, t_out, why
            o.entry_prices, o.exit_prices = fill_in, fill_out
            o.gross_pnl, o.net_pnl, o.fees = gross_raw, net, fees
            o.slippage_cost = gross_raw - (net + fees)
            o.mae, o.mfe, o.stale_marks, o.held_min = mae, mfe, stale, i + 1
            return o
    o.reason = "no bars after entry"
    return o
