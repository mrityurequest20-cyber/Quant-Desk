"""The replay: per instrument and session, find the desk's setups with only past data, simulate what followed, label it.

One shadow position per instrument at a time (the live gate's "already holding"): after a setup, the next one for that
instrument is looked for from its exit. Every row records its source (`source: shadow-replay`), the setup's own parameters,
and why it is unlabelled when it is. Nothing is tuned: the detectors, their config and the exit rules are the desk's."""
from __future__ import annotations

import datetime as dt
import hashlib

import pandas as pd

from ..intraday.feeds import IST
from . import ceilings, quality, registry
from .detect import BAR, Detector
from .loaders import OptionBook
from .simulate import Haircut, _hm, simulate_options, simulate_underlying

SOURCE = "shadow-replay"
FIRST_DECISION = dt.time(9, 30)
LAST_DECISION = dt.time(15, 0)


def setup_id(instrument: str, day, decision_time, setup: str, direction: int) -> str:
    return hashlib.sha1(f"{instrument}|{day}|{decision_time}|{setup}|{direction}".encode()).hexdigest()[:16]


def _row(spec, day, d, plan, kind, armed, fill_S, expiry, exp_src, uo, oo, view, s, lot_ok) -> dict:
    t_dec = d.now
    r = {
        "setup_id": setup_id(spec.name, day, t_dec, plan.setup, plan.direction),
        "source": SOURCE, "instrument": spec.name, "session": str(day), "decision_time": t_dec,
        "setup": plan.setup, "trigger_kind": kind, "side": "long" if plan.direction > 0 else "short" if plan.direction < 0 else "neutral",
        "direction": int(plan.direction), "structure": plan.structure, "expiry": expiry, "expiry_source": exp_src,
        "legs": ";".join(f"{l.ratio:+d}x{l.strike:g}{l.right}" for l in plan.legs),
        "underlying_entry": uo.u_entry, "stop": plan.invalidation, "target": plan.target_underlying,
        "premium_stop": plan.premium_stop, "premium_target": plan.premium_target, "time_stop_min": plan.time_stop_min,
        "conviction": float(plan.conviction), "armed_level": getattr(armed, "level", None),
        "lot_size": spec.lot_size, "lot_unverified": bool(spec.unverified),
        "u_status": uo.u_status, "u_reason": uo.u_reason, "u_exit_time": uo.u_exit_time, "u_exit_reason": uo.u_exit_reason,
        "u_exit": uo.u_exit, "u_r": uo.u_r, "u_mae_pts": uo.u_mae_pts, "u_mfe_pts": uo.u_mfe_pts,
        "status": oo.status, "unlabelled_reason": oo.reason, "entry_time": oo.entry_time, "exit_time": oo.exit_time,
        "exit_reason": oo.exit_reason, "gross_pnl": oo.gross_pnl, "net_pnl": oo.net_pnl, "fees": oo.fees,
        "slippage_cost": oo.slippage_cost, "mae": oo.mae, "mfe": oo.mfe, "stale_marks": oo.stale_marks,
        "held_min": oo.held_min, "entry_prices": ",".join(f"{p:.2f}" for p in oo.entry_prices),
        "exit_prices": ",".join(f"{p:.2f}" for p in oo.exit_prices),
        "day_type": view.day_type, "vol_view": view.vol_view, "bias": view.bias, "score": float(view.score),
        "view_conviction": float(view.conviction), "phase": s.get("phase"), "minutes": float(s.get("minutes", 0)),
        "rv_intraday": s.get("rv_intraday"), "atr5": s.get("atr5"), "adx5": s.get("adx5"), "gap": s.get("gap"),
        "range_vs_avg": s.get("range_vs_avg"), "atm_iv": d.iv, "iv_source": d.iv_source, "chain_source": "model",
        "view_inputs": "underlying-only (no chain analytics, flow, news, brain, direction model)",
    }
    if not lot_ok and oo.status == "labelled":     # cannot happen (guarded), kept explicit
        r["status"], r["unlabelled_reason"] = "unlabelled", "lot size unknown"
    return r


def replay_session(cfg, spec, day: dt.date, bars: pd.DataFrame, vix, book: OptionBook | None, cal, step: int,
                   hc: Haircut) -> list[dict]:
    """All setups for one instrument-session (plan objects kept under `_plan`, for the ceiling pass)."""
    det = Detector(cfg, spec.name, cal, vix)
    sq = _hm(str(cfg.get("intraday.risk.square_off", "15:15")))
    wait = int(cfg.get("shadow.max_leg_wait_min", 2))
    lot = spec.lot_size
    day_bars = bars[bars.index.date == day]
    if day_bars.empty:
        return []
    open_ts = pd.Timestamp(dt.datetime.combine(day, dt.time(9, 15)), tz=IST)
    expiry, exp_src = det.expiry_for(day, book.expiries_on(day) if book else [])
    exp_day = det.is_expiry_day(day)
    rows: list[dict] = []
    blocked_until = None
    t = pd.Timestamp(dt.datetime.combine(day, FIRST_DECISION), tz=IST)
    end = pd.Timestamp(dt.datetime.combine(day, LAST_DECISION), tz=IST)
    history = bars[bars.index <= day_bars.index[-1]]          # decide() filters to what had closed by `now`
    while t <= end:
        if blocked_until is not None and t < blocked_until:
            t += pd.Timedelta(minutes=step)
            continue
        d = det.decide(history, t, expiry, exp_day)
        t += pd.Timedelta(minutes=step)
        if d is None:
            continue
        cands = [(p, "scan", None, None) for p in d.plans]
        nb = day_bars[day_bars.index == d.now]                    # the next bar: where an anticipated order may fill
        for a in d.armed:
            if len(nb):
                S = a.bar_fill(float(nb["open"].iloc[0]), float(nb["high"].iloc[0]), float(nb["low"].iloc[0]))
                if S is not None:
                    p = det.fire(a, d, S)
                    if p is not None:
                        cands.append((p, "armed", a, S))
        if not cands:
            continue
        plan, kind, armed, fill_S = cands[0]
        lot_ok = bool(lot)
        uo = simulate_underlying(plan, plan.direction, day_bars, d.now, sq, entry_price=fill_S)
        if lot_ok:
            oo = simulate_options(plan, plan.direction, day_bars, book, day, d.now, int(lot), hc, sq, wait, spec.name)
        else:
            from .simulate import Outcome
            oo = Outcome(reason="lot size unknown: nothing is priced for this instrument")
        row = _row(spec, day, d, plan, kind, armed, fill_S, expiry, exp_src, uo, oo, d.view, d.state, lot_ok)
        row["_plan"] = plan
        rows.append(row)
        blocked_until = (oo.exit_time or uo.u_exit_time or d.now + pd.Timedelta(minutes=int(plan.time_stop_min)))
    return rows


def run(cfg, days: list[dt.date], instruments: list[str], bars_by: dict[str, pd.DataFrame], vix: pd.DataFrame | None,
        books: dict[str, OptionBook], reg: dict, step: int | None = None, say=print) -> tuple[pd.DataFrame, dict]:
    """Quality gate first, then the replay over the sessions that pass. Returns (setups frame, quality reports)."""
    th = quality.thresholds(cfg)
    dcfg = registry.derived_config(cfg, reg)
    cal = registry.calendar(cfg)
    step = int(step or cfg.get("shadow.decision_step_min", 1))
    hc = Haircut.from_cfg(cfg)
    min_prior = int(cfg.get("shadow.min_prior_days", 2))
    reports = {}
    rows_by_day: dict[dt.date, list[dict]] = {}
    for name in instruments:
        spec = reg[name]
        bars = bars_by.get(name)
        rep = quality.instrument_report(name, bars, books.get(name), th, spec.strike_step, days, lot_ok=bool(spec.lot_size))
        # a session needs history before it: the detectors' levels, value area and 5-minute indicators come from prior days
        if bars is not None and len(bars):
            have = sorted(set(bars.index.date))
            for dd in list(rep["usable"]):
                if sum(1 for h in have if h < dd) < min_prior:
                    rep["usable"].remove(dd)
                    rep["excluded"][str(dd)] = [f"fewer than {min_prior} prior sessions of history"]
        reports[name] = rep
        say(f"  {name}: {len(rep['usable'])}/{len(days)} sessions pass the data checks"
            + (f" (instrument excluded: {rep['instrument_excluded']})" if rep["instrument_excluded"] else ""))
        for dd in rep["usable"]:
            rows = replay_session(dcfg, spec, dd, bars, vix, books.get(name), cal, step, hc)
            rows_by_day.setdefault(dd, []).extend(rows)
    out = []
    for dd in sorted(rows_by_day):
        items = [{"decision_time": r["decision_time"], "entry_time": r["entry_time"] if r["status"] == "labelled" else r["decision_time"],
                  "exit_time": r["exit_time"] if r["status"] == "labelled" else r["u_exit_time"], "symbol": r["instrument"],
                  "setup": r["setup"], "plan": r["_plan"], "net_pnl": r["net_pnl"], "row": r} for r in rows_by_day[dd]]
        ceilings.evaluate(cfg, dd, items)
        for it in items:
            r = it["row"]
            r["would_have_been_refused_by"] = ",".join(it["would_have_been_refused_by"])
            r["refusal_reasons"] = " | ".join(it["refusal_reasons"])
            r["live_lots_sized"] = it["lots_sized"]
            r["accepted_by_live_ceilings"] = bool(it["accepted"])
            out.append(r)
    for r in out:
        r.pop("_plan", None)
    df = pd.DataFrame(out)
    if len(df):
        df = df.sort_values(["session", "decision_time", "instrument", "setup"]).reset_index(drop=True)
    return df, reports
