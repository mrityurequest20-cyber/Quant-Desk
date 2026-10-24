"""Which live ceiling or filter would have blocked each shadow setup, evaluated per day in time order.

It runs the desk's own `IntradayRisk` (gate and size) read-only on the config as it is: max_trades_per_day, max_open,
daily loss, premium outlay, exposure cap, cooldown, entry window. Nothing is changed or loosened; a blocked setup is still
recorded (it is exactly the sample the entry filter must learn from), only flagged. Starting equity is the config's
intraday.capital each day: the shadow has no account of its own. A setup that could not be priced counts 0 P&L."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd

from ..intraday.risk import IntradayRisk

KEYS = (("trades already today", "max_trades_per_day"), ("positions already open", "max_open"),
        ("daily loss limit", "daily_loss_limit"), ("exposure cap", "exposure_cap"), ("cooling off", "cooldown"),
        ("outside entry window", "entry_window"), ("already holding", "holding_same_symbol"),
        ("governor", "governor"), ("equity unknown", "equity"))


def _key(reason: str) -> str:
    for needle, k in KEYS:
        if needle in reason:
            return k
    return "other"


BINDING = {"premium_outlay": "outlay", "risk": "risk_per_trade", "daily_loss": "daily_loss_limit", "max_lots": "max_lots",
           "margin": "margin", "cash": "cash"}


def _binding(reason: str) -> str:
    """risk.size's last note names the cap that took the lots to zero: 'N lot(s), binding: premium_outlay'."""
    return BINDING.get(reason.rpartition("binding: ")[2].strip(), "sizing")


def evaluate(cfg, day: dt.date, items: list[dict]) -> None:
    """items: dicts with decision_time, entry_time, exit_time (or None), symbol, plan, net_pnl (per lot or None).
    Adds in place: would_have_been_refused_by (list of keys), refusal_reasons (list), lots_sized, accepted."""
    risk = IntradayRisk(cfg)
    equity0 = float(cfg.get("intraday.capital", 20000))
    equity = equity0
    risk.reset(day, equity)
    open_trades: list = []
    for it in sorted(items, key=lambda x: (x["decision_time"], x["symbol"], x["setup"])):
        t = it["entry_time"] or it["decision_time"]
        for tr in sorted([x for x in open_trades if x.exit_time <= t], key=lambda x: x.exit_time):
            open_trades.remove(tr)
            equity += tr.pnl
            risk.on_close(tr.pnl, tr.exit_time)
        reasons = risk.gate(t, equity, open_trades, it["symbol"])
        lots = 0
        if it.get("plan") is not None:
            open_risk = sum(getattr(x, "risk", 0.0) for x in open_trades)
            lots, notes = risk.size(it["plan"], equity, None, open_risk)
            if lots < 1:
                reasons.append("sizing: " + notes[-1])
        it["refusal_reasons"] = reasons
        it["would_have_been_refused_by"] = sorted({_key(r) if not r.startswith("sizing") else _binding(r) for r in reasons})
        it["lots_sized"] = int(lots)
        it["accepted"] = not reasons
        if not reasons:
            risk.trades_today += 1
            exit_t = it["exit_time"] or (t + pd.Timedelta(minutes=int(getattr(it["plan"], "time_stop_min", 45))))
            pnl = float(it["net_pnl"] or 0.0) * lots
            open_trades.append(SimpleNamespace(symbol=it["symbol"], entry_cost=abs(it["plan"].net_premium) * lots,
                                               exit_time=exit_t, pnl=pnl,
                                               risk=it["plan"].planned_risk_per_lot() * lots))
