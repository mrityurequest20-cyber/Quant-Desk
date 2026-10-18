"""`shadow validate`: replay the sessions the live desk really traded and compare, trade by trade.

For every closed live trade on an instrument the replay covers: did the replay find the same setup and side, entering within
`time_tol_min` of the live entry; did it exit within the same tolerance; is the net P&L close (`pnl_tol_frac` of the larger
of the live P&L and the trade's planned risk)? A live trade the replay cannot reproduce on all counts is a mismatch with its
reason; so is a P&L that cannot be compared (the replay is unlabelled for want of option minutes): the replay is not trusted
for ML on a comparison it could not make. Replay setups the live desk did not take are listed with the best explanation
available (a live rejection record, or the live ceiling that would have blocked them) and are reported apart: the live desk
filters candidates with things the replay cannot see (EV floor, direction model, live book), so those are expected.

The journal is read with sqlite in read-only mode; nothing in it is touched."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

from ..intraday.feeds import IST


def settings(cfg) -> dict:
    v = cfg.get("shadow.validate", {}) or {}
    return {"match_threshold": float(v.get("match_threshold", 0.9)), "time_tol_min": float(v.get("time_tol_min", 5)),
            "pnl_tol_frac": float(v.get("pnl_tol_frac", 0.25)), "require_pnl": bool(v.get("require_pnl", True))}


def _ts(x) -> pd.Timestamp | None:
    if x is None or x != x or x == "":
        return None
    t = pd.Timestamp(x)
    return t.tz_convert(IST) if t.tzinfo else t.tz_localize(IST)


def read_journal(path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(closed trades, rejection decisions) from a journal.db, read-only."""
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        trades = pd.read_sql("SELECT id, strategy, symbol, direction, units, opened_at, closed_at, entry_underlying, stop, target,"
                             " initial_risk, pnl, fees, exit_reason, status, mae, mfe FROM trades WHERE status='closed'", con)
        dec = pd.read_sql("SELECT ts, strategy, symbol, action, detail FROM decisions", con)
    finally:
        con.close()
    for c in ("opened_at", "closed_at"):
        trades[c] = trades[c].map(_ts)
    dec["ts"] = dec["ts"].map(_ts)
    return trades, dec


def live_days(trades: pd.DataFrame, dec: pd.DataFrame) -> list:
    d = {t.date() for t in trades["opened_at"].dropna()} | {t.date() for t in dec["ts"].dropna()}
    return sorted(d)


def compare(setups: pd.DataFrame, trades: pd.DataFrame, dec: pd.DataFrame, st: dict, instruments=None) -> dict:
    tol = pd.Timedelta(minutes=st["time_tol_min"])
    rows, used = [], set()
    for _, t in trades.sort_values("opened_at").iterrows():
        if instruments is not None and t["symbol"] not in instruments:
            continue
        day, t0 = str(t["opened_at"].date()), t["opened_at"].floor("min")
        c = setups[(setups["instrument"] == t["symbol"]) & (setups["session"] == day) & (setups["setup"] == t["strategy"])
                   & (setups["direction"] == int(t["direction"])) & ~setups["setup_id"].isin(used)] if len(setups) else setups
        c = c[(c["decision_time"] - t0).abs() <= tol] if len(c) else c
        rec = {"trade": t["id"], "session": day, "instrument": t["symbol"], "setup": t["strategy"], "side": int(t["direction"]),
               "live_entry": t["opened_at"], "live_exit": t["closed_at"], "live_exit_reason": t["exit_reason"],
               "live_net_pnl": float(t["pnl"]), "reasons": []}
        if c.empty:
            near = setups[(setups["instrument"] == t["symbol"]) & (setups["session"] == day)] if len(setups) else setups
            other = near[(near["decision_time"] - t0).abs() <= tol] if len(near) else near
            why = ("the replay found a different setup there: " + ", ".join(sorted(set(other["setup"] + "/" + other["side"])))
                   if len(other) else "the replay found no setup within the time tolerance (live uses inputs the replay lacks, "
                   "or the live trade came from a different read)")
            rec.update(matched=False, reasons=[why])
            rows.append(rec)
            continue
        r = c.iloc[(c["decision_time"] - t0).abs().argsort()].iloc[0]
        used.add(r["setup_id"])
        rec.update(replay_entry=r["decision_time"], replay_setup_id=r["setup_id"], replay_exit_reason=r["exit_reason"]
                   if r["status"] == "labelled" else r["u_exit_reason"])
        rx = r["exit_time"] if r["status"] == "labelled" else r["u_exit_time"]
        rec["replay_exit"] = rx
        if rx is None or rx != rx:
            rec["reasons"].append("replay has no exit time")
        elif t["closed_at"] is not None and abs(rx - t["closed_at"]) > tol:
            rec["reasons"].append(f"exit time differs: live {t['closed_at']:%H:%M} ({t['exit_reason']}) vs replay {rx:%H:%M} "
                                  f"({rec['replay_exit_reason']})")
        if r["status"] == "labelled":
            lots = max(int(t["units"] or 1), 1)
            rp = float(r["net_pnl"]) * lots
            rec["replay_net_pnl"] = rp
            scale = max(abs(float(t["pnl"])), float(t["initial_risk"] or 0.0), 1.0)
            if abs(rp - float(t["pnl"])) > st["pnl_tol_frac"] * scale:
                rec["reasons"].append(f"net P&L differs: live {t['pnl']:+,.0f} vs replay {rp:+,.0f} ({lots} lot)")
        else:
            rec["replay_net_pnl"] = None
            if st["require_pnl"]:
                rec["reasons"].append(f"P&L not comparable: replay unlabelled ({r['unlabelled_reason']})")
        rec["matched"] = not rec["reasons"]
        rows.append(rec)
    n = len(rows)
    ok = sum(1 for r in rows if r["matched"])
    found = sum(1 for r in rows if "replay_setup_id" in r)
    rate = ok / n if n else 0.0
    # replay setups the live desk did not take, in the sessions it ran
    extra = []
    if len(setups):
        live_sessions = {str(t.date()) for t in trades["opened_at"].dropna()} | {str(t.date()) for t in dec["ts"].dropna()}
        for _, r in setups[setups["session"].isin(live_sessions) & ~setups["setup_id"].isin(used)].iterrows():
            rej = dec[(dec["symbol"] == r["instrument"]) & (dec["strategy"] == r["setup"]) & ((dec["ts"] - r["decision_time"]).abs() <= tol)]
            if len(rej):
                why = "live rejected it: " + str(rej["detail"].iloc[0])[:120]
            elif r["would_have_been_refused_by"]:
                why = "live ceiling would have blocked it: " + r["would_have_been_refused_by"]
            else:
                why = "unexplained (live inputs the replay lacks, or no live record)"
            extra.append({"session": r["session"], "instrument": r["instrument"], "setup": r["setup"], "decision_time": r["decision_time"],
                          "explained_by": why})
    return {"live_trades": n, "setup_found": found, "matched": ok, "match_rate": rate, "rows": rows, "replay_only": extra,
            "threshold": st["match_threshold"], "passed": bool(n > 0 and rate >= st["match_threshold"])}


def render(res: dict) -> str:
    L = ["Shadow validate: replay vs what the live desk did", "",
         f"  live trades compared    {res['live_trades']}",
         f"  setup found (time tol)  {res['setup_found']}",
         f"  fully matched           {res['matched']}   match rate {res['match_rate']:.0%} (threshold {res['threshold']:.0%})", ""]
    for r in res["rows"]:
        L.append(f"  {'MATCH   ' if r['matched'] else 'MISMATCH'} {r['session']} {r['instrument']:<9} {r['setup']:<12} {r['trade']}")
        for why in r["reasons"]:
            L.append(f"      - {why}")
    if res["replay_only"]:
        n_un = sum(1 for e in res["replay_only"] if e["explained_by"].startswith("unexplained"))
        L += ["", f"  replay setups the live desk did not take: {len(res['replay_only'])} ({n_un} unexplained); first 15:"]
        for e in res["replay_only"][:15]:
            L.append(f"      {e['session']} {e['decision_time']:%H:%M} {e['instrument']:<9} {e['setup']:<12} {e['explained_by']}")
    L += ["", ("PASS" if res["passed"] else "FAIL") + f": match rate {res['match_rate']:.0%} vs threshold {res['threshold']:.0%}"
          + ("" if res["passed"] else ". The replay is NOT trusted for ML until this passes and the mismatches are explained.")]
    return "\n".join(L)


def to_json(res: dict) -> str:
    return json.dumps(res, indent=1, default=str)
