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
            rec.update(matched=False, reasons=[why], categories=["setup_not_found"], setup_found=False)
            rows.append(rec)
            continue
        r = c.iloc[(c["decision_time"] - t0).abs().argsort()].iloc[0]
        used.add(r["setup_id"])
        rec.update(setup_found=True, categories=[], replay_entry=r["decision_time"], replay_setup_id=r["setup_id"], replay_exit_reason=r["exit_reason"]
                   if r["status"] == "labelled" else r["u_exit_reason"])
        rx = r["exit_time"] if r["status"] == "labelled" else r["u_exit_time"]
        rec["replay_exit"] = rx
        if rx is None or rx != rx:
            rec["reasons"].append("replay has no exit time")
            rec["categories"].append("exit_time")
        elif t["closed_at"] is not None and abs(rx - t["closed_at"]) > tol:
            rec["categories"].append("exit_time")
            rec["reasons"].append(f"exit time differs: live {t['closed_at']:%H:%M} ({t['exit_reason']}) vs replay {rx:%H:%M} "
                                  f"({rec['replay_exit_reason']})")
        if r["status"] == "labelled":
            lots = max(int(t["units"] or 1), 1)
            rp = float(r["net_pnl"]) * lots
            rec["replay_net_pnl"] = rp
            scale = max(abs(float(t["pnl"])), float(t["initial_risk"] or 0.0), 1.0)
            if abs(rp - float(t["pnl"])) > st["pnl_tol_frac"] * scale:
                rec["categories"].append("pnl_differs")
                rec["reasons"].append(f"net P&L differs: live {t['pnl']:+,.0f} vs replay {rp:+,.0f} ({lots} lot)")
        else:
            rec["replay_net_pnl"] = None
            if st["require_pnl"]:
                rec["categories"].append("pnl_not_comparable")
                rec["reasons"].append(f"P&L not comparable: replay unlabelled ({r['unlabelled_reason']})")
        rec["matched"] = not rec["reasons"]
        rows.append(rec)
    n = len(rows)
    ok = sum(1 for r in rows if r["matched"])
    found = sum(1 for r in rows if r.get("setup_found"))
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
    rej = reject_classes(dec)
    return {"live_trades": n, "setup_found": found, "setup_only_rate": (found / n if n else 0.0), "live_rejections": rej,
            "rejections_replay_cannot_see": rej["total"] - rej["other"], "matched": ok, "match_rate": rate, "rows": rows, "replay_only": extra,
            "threshold": st["match_threshold"], "passed": bool(n > 0 and rate >= st["match_threshold"])}


def reject_class(detail: str) -> str:
    d = (detail or "").lower()
    if "ev below the floor" in d:
        return "ev_floor"
    if "plan model" in d or "approved" in d:
        return "model_gate"
    if "veto" in d or "stand" in d or "blackout" in d or "news" in d:
        return "veto_or_stand_aside"
    return "other"


def reject_classes(dec: pd.DataFrame) -> dict:
    out = {"total": 0, "ev_floor": 0, "model_gate": 0, "veto_or_stand_aside": 0, "other": 0}
    for d in (dec[dec["action"] == "rejected"]["detail"] if len(dec) else []):
        out["total"] += 1
        out[reject_class(d)] += 1
    return out


EVIDENCE_REPLAY_LACKS = {"pcr", "oi_walls", "max_pain", "iv_move", "flow", "divergence", "news", "model", "research", "fut_oi", "basis",
                         "vix", "oi_shift", "skew_trend", "breadth", "breadth_div"}


def diagnose(rec: dict, decision, thoughts: pd.DataFrame) -> list[str]:
    """Why the replay did not find a live trade's setup: compare the replay's view at the live minute with the live desk's own
    recorded read (its `thoughts` row). `decision` is detect.Decision at that minute (or None)."""
    cats = []
    th = thoughts[(thoughts["symbol"] == rec["instrument"]) & (thoughts["ts"] <= rec["live_entry"])]
    live = th.iloc[-1] if len(th) else None
    if decision is None:
        return ["replay_no_state"]
    same = [p for p in list(decision.plans) + list(decision.armed) if p.setup == rec["setup"]]
    if same and not any(p.direction == rec["side"] for p in same):
        cats.append("replay_found_opposite_side")
    if live is not None:
        ds, dc = abs(float(live["score"]) - decision.view.score), abs(float(live["conviction"]) - decision.view.conviction)
        if ds > 0.15 or dc > 0.15 or live["day_type"] != decision.view.day_type:
            try:
                ev = json.loads(live["evidence"] or "[]")
            except ValueError:
                ev = []
            lacking = sum(abs(e["direction"] * e["weight"]) for e in ev if e["factor"] in EVIDENCE_REPLAY_LACKS)
            cats.append("analyst_view_differs_chain_flow_news_evidence" if lacking > 0.5 else "analyst_view_differs_other")
            rec["view_diff"] = {"live_score": float(live["score"]), "replay_score": decision.view.score,
                                "live_conviction": float(live["conviction"]), "replay_conviction": decision.view.conviction,
                                "live_day_type": live["day_type"], "replay_day_type": decision.view.day_type,
                                "live_evidence_replay_lacks": round(lacking, 2)}
    if not cats:
        cats.append("view_close_but_setup_conditions_differ")
    return cats


def top_reasons(res: dict) -> list:
    from collections import Counter
    c = Counter()
    for r in res["rows"]:
        if not r["matched"]:
            for k in (r.get("diagnosis") or []) + r.get("categories", []):
                c[k] += 1
    return c.most_common()


def render(res: dict) -> str:
    L = ["Shadow validate: replay vs what the live desk did", "",
         f"  live trades compared    {res['live_trades']}",
         f"  SETUP-ONLY match        {res['setup_found']}/{res['live_trades']} = {res['setup_only_rate']:.0%}   (right setup and side within the time tolerance)",
         f"  FULL match              {res['matched']}/{res['live_trades']} = {res['match_rate']:.0%}   (threshold {res['threshold']:.0%}; also entry/exit times and net P&L)",
         f"  live rejections         {res['live_rejections']['total']} records; {res['rejections_replay_cannot_see']} for reasons the replay cannot see "
         f"(EV floor {res['live_rejections']['ev_floor']}, model gate {res['live_rejections']['model_gate']}, "
         f"veto/stand-aside {res['live_rejections']['veto_or_stand_aside']})", ""]
    for r in res["rows"]:
        L.append(f"  {'MATCH   ' if r['matched'] else 'MISMATCH'} {r['session']} {r['instrument']:<9} {r['setup']:<12} {r['trade']}")
        for why in r["reasons"]:
            L.append(f"      - {why}")
    tr = top_reasons(res)
    if tr:
        L += ["", "  Top mismatch reasons (counted per live trade; a trade can have several):"] + [f"      {n:>3}  {k}" for k, n in tr]
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
