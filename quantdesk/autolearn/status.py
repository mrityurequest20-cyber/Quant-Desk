"""The operational status of the learning loop: one place to see whether it is healthy and what it's doing."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .cycle import STAGES, root_of
from .ledger import Ledger
from .registry import Registry
from .store import ChainLog, read_json
from .validation import LockBox

IST = "Asia/Kolkata"


def status(cfg, now: pd.Timestamp | None = None) -> dict:
    root = root_of(cfg)
    now = now or pd.Timestamp.now(tz=IST)
    reg, led = Registry(root), Ledger(root)
    st = reg.state() if (root / "registry").exists() else {}
    champ = st.get("champion")
    card = reg.card(champ) if champ else None
    cycles = sorted((root / "cycles").glob("????-??-??.json")) if (root / "cycles").exists() else []
    last = read_json(cycles[-1]) if cycles else None
    ok_cycles = [c for c in cycles if (read_json(c) or {}).get("status") == "done"]
    last_ok = read_json(ok_cycles[-1]) if ok_cycles else None
    decisions = led.decisions() if (root / "ledger").exists() else []
    last_dec = max((d["ts"] for d in decisions), default=None)
    outs = led.outcomes() if decisions else {}
    store = root / "bars5"
    fresh = {}
    for p in sorted(store.glob("*.parquet")) if store.exists() else []:
        try:
            b = pd.read_parquet(p, columns=["close"])
            fresh[p.stem] = str(b.index[-1]) if len(b) else None
        except (OSError, ValueError):
            fresh[p.stem] = "unreadable"
    jpath = Path(cfg.runtime_dir) / "intraday" / "journal.db"
    risk, paper = {}, None
    if jpath.exists():
        import sqlite3
        try:
            with sqlite3.connect(f"file:{jpath}?mode=ro", uri=True) as db:
                row = db.execute("SELECT value FROM state WHERE key='intraday_live'").fetchone()
                hb = json.loads(row[0]) if row else {}
                risk = {"as_of": hb.get("ts"), "halted": hb.get("halted"), "paused": hb.get("paused"),
                        "trades_today": hb.get("trades_today"), "day_pnl": hb.get("day_pnl"), "halts": hb.get("halts"),
                        "journal_check": db.execute("PRAGMA quick_check").fetchone()[0]}
        except sqlite3.Error as exc:
            risk = {"journal_check": f"unreadable: {exc}"}
    risk["kill_switch"] = (Path(cfg.runtime_dir) / str(cfg.get("intraday.kill_switch_file", "KILL"))).exists()
    trades = ChainLog(root / "paper_trades.jsonl").read() if (root / "paper_trades.jsonl").exists() else []
    if trades:
        t = pd.DataFrame(trades)
        paper = {"closed_trades": int(len(t)), "net_pnl": float(t["pnl"].sum()),
                 "win_rate": float((t["pnl"] > 0).mean()), "by_model": t.groupby(t["model_id"].fillna("none"))["pnl"].agg(["count", "sum"])
                 .round(2).to_dict("index")}
    drift = read_json(root / "drift.json") or {}
    lock = LockBox(root)
    return {
        "as_of": str(now), "root": str(root),
        "champion": {"model_id": champ, "since": ((card or {}).get("approval") or {}).get("at"),
                     "validation": _val(card), "paper": ((card or {}).get("paper") or {}).get("shadow")} if champ else None,
        "rollback_target": st.get("rollback_target"), "challengers": st.get("challengers", []),
        "rejected": len(st.get("rejected", [])),
        "data_freshness": {"bar_store_last_bar": fresh, "last_decision": last_dec, "decisions": len(decisions),
                           "resolved": len(outs)},
        "last_cycle": {"id": (last or {}).get("cycle_id"), "status": (last or {}).get("status"),
                       "stages": {s: ((last or {}).get("stages", {}).get(s) or {}).get("status") for s in STAGES}},
        "last_successful_cycle": {"id": (last_ok or {}).get("cycle_id"), "finished": (last_ok or {}).get("finished")},
        "drift": {"state": drift.get("state", "no champion" if not champ else "not measured yet"),
                  "reasons": drift.get("reasons"), "as_of": drift.get("as_of")},
        "risk": risk, "paper": paper,
        "lockbox": {"days": (lock.get() or {}).get("days"), "peeks": lock.peeks() if lock.log.path.exists() else 0},
        "recovery_point": {"registry_event": st.get("last_event"), "ledger_records": len(decisions),
                           "last_cycle_finished": (last_ok or {}).get("finished"),
                           "integrity": {"ledger": led.verify() if (root / "ledger").exists() else [],
                                         "registry": reg.events.verify() if reg.events.path.exists() else []}},
    }


def _val(card) -> dict | None:
    m = ((card or {}).get("validation") or {}).get("metrics") or {}
    if not m:
        return None
    t, c = m.get("trading") or {}, m.get("classification") or {}
    ci = (m.get("ci") or {}).get("expectancy_bps") or {}
    return {"expectancy_bps": t.get("expectancy_bps"), "ci90": [ci.get("lo"), ci.get("hi")], "trades": t.get("trades"),
            "auc": c.get("auc"), "brier_skill": c.get("brier_skill"), "ece": c.get("ece"), "coverage": c.get("coverage")}


def render(s: dict) -> str:
    def f(x, nd=2):
        return "—" if x is None else (f"{x:+.{nd}f}" if isinstance(x, (int, float)) else str(x))
    L = [f"learning loop status · {s['as_of'][:16]}"]
    ch = s["champion"]
    if ch:
        v = ch.get("validation") or {}
        L.append(f"  champion        {ch['model_id']} since {str(ch.get('since'))[:16]}: walk-forward {f(v.get('expectancy_bps'))} bps/trade "
                 f"(90% CI {f((v.get('ci90') or [None])[0])} … {f((v.get('ci90') or [None, None])[1])}), AUC {f(v.get('auc'), 3)}, "
                 f"ECE {f(v.get('ece'), 3)}")
        p = ch.get("paper") or {}
        if p:
            L.append(f"  champion paper  {p.get('sessions')} sessions, {p.get('trades')} signals, {f(p.get('expectancy_bps'))} bps/trade net")
    else:
        L.append("  champion        none yet: the desk runs on its session-trained DirectionModel and the EV gate")
    L.append(f"  rollback target {s['rollback_target'] or '—'} · challengers {', '.join(s['challengers']) or 'none'} · rejected {s['rejected']}")
    d = s["data_freshness"]
    L.append(f"  data            bars to {', '.join(f'{k} {str(v)[:16]}' for k, v in d['bar_store_last_bar'].items()) or 'none'}; "
             f"{d['decisions']} decisions recorded, {d['resolved']} resolved, last {str(d['last_decision'])[:16]}")
    lc, lo = s["last_cycle"], s["last_successful_cycle"]
    L.append(f"  last cycle      {lc['id'] or 'never'} {lc['status'] or ''} " + " ".join(f"{k}:{v or '-'}" for k, v in lc["stages"].items()))
    L.append(f"  last success    {lo['id'] or 'never'} {str(lo['finished'] or '')[:16]}")
    L.append(f"  drift           {s['drift']['state']}" + (f" ({'; '.join(s['drift']['reasons'])})" if s["drift"].get("reasons") else ""))
    r = s["risk"]
    L.append(f"  risk            kill switch {'ON' if r.get('kill_switch') else 'off'} · halted {r.get('halted')} · paused {r.get('paused')} · "
             f"trades today {r.get('trades_today')} · day P&L {f(r.get('day_pnl'), 0)} · journal {r.get('journal_check', '—')}")
    if s["paper"]:
        p = s["paper"]
        L.append(f"  paper trades    {p['closed_trades']} closed, net ₹{p['net_pnl']:,.0f}, {p['win_rate']:.0%} won")
    L.append(f"  locked test     {len(s['lockbox']['days'] or [])} sessions" + (f" {s['lockbox']['days'][0]} → {s['lockbox']['days'][-1]}" if s["lockbox"]["days"] else "")
             + f", looked at {s['lockbox']['peeks']} time(s)")
    rp = s["recovery_point"]
    bad = rp["integrity"]["ledger"] + rp["integrity"]["registry"]
    L.append(f"  recovery point  registry event #{(rp['registry_event'] or {}).get('seq', 0)}, {rp['ledger_records']} ledger records; "
             f"integrity {'OK' if not bad else 'PROBLEMS: ' + '; '.join(bad[:3])}")
    return "\n".join(L)
