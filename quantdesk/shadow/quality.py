"""Data-quality report, run before any replay. Per instrument and session: minute gaps, stale (frozen) runs, outlier ticks,
zero-volume share, too few bars, and (when option minutes exist) missing strikes near the money. A failing session is
excluded from the replay and listed with the reason; an instrument with too many failing sessions is excluded whole.
Nothing is repaired or interpolated."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from ..intraday.feeds import IST

SESSION_MIN = 375


def thresholds(cfg) -> dict:
    q = cfg.get("shadow.quality", {}) or {}
    return {"min_bars": int(q.get("min_bars", 330)), "max_gap_min": int(q.get("max_gap_min", 5)),
            "max_stale_run": int(q.get("max_stale_run", 20)), "max_abs_return": float(q.get("max_abs_return", 0.03)),
            "max_outliers": int(q.get("max_outliers", 0)), "min_option_strikes": int(q.get("min_option_strikes", 6)),
            "max_bad_session_share": float(q.get("max_bad_session_share", 0.3))}


def _longest_run(mask: np.ndarray) -> int:
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best


def session_report(day_bars: pd.DataFrame, th: dict) -> dict:
    """One session's minute bars -> metrics and the reasons it fails (empty list: usable)."""
    r: dict = {"bars": int(len(day_bars)), "reasons": []}
    if day_bars.empty:
        r["reasons"].append("no bars")
        return r
    idx = day_bars.index
    open_ts = idx[0].normalize() + pd.Timedelta(hours=9, minutes=15)
    full = pd.date_range(open_ts, periods=SESSION_MIN, freq="min")
    missing = ~full.isin(idx)
    r["missing_minutes"] = int(missing.sum())
    r["longest_gap_min"] = _longest_run(missing)
    r["first_bar"] = f"{idx[0]:%H:%M}"
    c = day_bars["close"].to_numpy(dtype=float)
    ret = np.abs(np.diff(np.log(c))) if len(c) > 1 else np.array([])
    r["outlier_ticks"] = int((ret > th["max_abs_return"]).sum())
    same = np.concatenate([[False], c[1:] == c[:-1]]) if len(c) > 1 else np.array([False])
    r["longest_stale_run"] = _longest_run(same)
    vol = day_bars["volume"].to_numpy(dtype=float)
    r["zero_volume_share"] = float((vol <= 0).mean())
    r["volume_present"] = bool(vol.sum() > 0)
    if r["bars"] < th["min_bars"]:
        r["reasons"].append(f"only {r['bars']} bars (< {th['min_bars']})")
    if r["longest_gap_min"] > th["max_gap_min"]:
        r["reasons"].append(f"gap of {r['longest_gap_min']} minutes")
    if idx[0] > open_ts + pd.Timedelta(minutes=1):
        r["reasons"].append(f"opening bars missing (first bar {idx[0]:%H:%M})")
    if r["longest_stale_run"] > th["max_stale_run"]:
        r["reasons"].append(f"stale: {r['longest_stale_run']} equal closes in a row")
    if r["outlier_ticks"] > th["max_outliers"]:
        r["reasons"].append(f"{r['outlier_ticks']} outlier tick(s) beyond {th['max_abs_return']:.1%} in a minute")
    if bool(vol.sum() > 0) and r["zero_volume_share"] > 0.5:
        r["reasons"].append(f"{r['zero_volume_share']:.0%} of bars have zero volume")
    return r


def option_report(book, day: dt.date, spot: float, step: float | None, th: dict) -> dict:
    """Strikes with bars within ±5 steps of the open, per expiry traded that day."""
    out: dict = {"expiries": {}, "ok": False}
    if book is None or not len(book.df):
        out["reason"] = "no option minutes"
        return out
    exps = book.expiries_on(day)
    if not exps:
        out["reason"] = "no option minutes on this day"
        return out
    step = step or 1.0
    atm = round(spot / step) * step
    want = [atm + step * k for k in range(-5, 6)]
    for e in exps[:3]:
        have = 0
        for k in want:
            for right in ("CE", "PE"):
                if book.bars(e, k, right, day) is not None:
                    have += 1
        out["expiries"][str(e)] = {"strike_legs_with_bars": have, "of": 2 * len(want)}
    best = max((v["strike_legs_with_bars"] for v in out["expiries"].values()), default=0)
    out["ok"] = best >= th["min_option_strikes"]
    if not out["ok"]:
        out["reason"] = f"only {best} of {2 * len(want)} near-the-money option legs have bars"
    return out


def instrument_report(name: str, bars: pd.DataFrame, book, th: dict, step: float | None,
                      days: list[dt.date], lot_ok: bool = True) -> dict:
    """{instrument, sessions: {day: report}, usable: [days], excluded: {day: reasons}, excluded_instrument: reason|None}."""
    rep: dict = {"instrument": name, "sessions": {}, "usable": [], "excluded": {}, "instrument_excluded": None, "notes": []}
    if bars is None or bars.empty:
        rep["instrument_excluded"] = "no minute bars for the underlying"
        return rep
    if not lot_ok:
        rep["notes"].append("lot size unknown: setups are found but cannot be priced")
    by_day = {d: g for d, g in bars.groupby(bars.index.date)}
    for d in days:
        sr = session_report(by_day.get(d, bars.iloc[0:0]), th)
        if book is not None and len(book.df) and d in by_day:
            sr["options"] = option_report(book, d, float(by_day[d]["open"].iloc[0]), step, th)
        sr["usable"] = not sr["reasons"]
        rep["sessions"][str(d)] = sr
        if sr["usable"]:
            rep["usable"].append(d)
        else:
            rep["excluded"][str(d)] = sr["reasons"]
    n = len(days)
    bad = len(rep["excluded"]) / n if n else 1.0
    if n and bad > th["max_bad_session_share"]:
        rep["instrument_excluded"] = f"{len(rep['excluded'])} of {n} sessions fail the data checks (> {th['max_bad_session_share']:.0%})"
        rep["usable"] = []
    return rep


def render(reps: list[dict]) -> str:
    L = ["Data quality (before any replay)", ""]
    for r in reps:
        n = len(r["sessions"])
        head = f"  {r['instrument']:<11} sessions {len(r['usable'])}/{n} usable"
        if r["instrument_excluded"]:
            head += f"  EXCLUDED: {r['instrument_excluded']}"
        L.append(head)
        for d, why in r["excluded"].items():
            L.append(f"      excluded {d}: {'; '.join(why)}")
        for note in r["notes"]:
            L.append(f"      note: {note}")
        opt = [(d, s["options"]) for d, s in r["sessions"].items() if "options" in s and not s["options"]["ok"]]
        for d, o in opt:
            L.append(f"      options {d}: {o.get('reason')}  (setups there are unlabelled, not excluded)")
    return "\n".join(L)
