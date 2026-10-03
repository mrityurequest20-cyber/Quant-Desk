"""`python -m quantdesk autolearn …`: the paper-learning cycle and its controls."""
from __future__ import annotations

import json
import sys

from .cycle import STAGES, Cycle, CycleBusy, default_loader, root_of


def register(sub):
    s = sub.add_parser("autolearn", help="the self-learning paper loop: cycle, status, verify, recover, rollback")
    ss = s.add_subparsers(dest="acmd", required=True)
    x = ss.add_parser("cycle", help="run the cycle (all stages, or --stages ingest,dataset,…); idempotent and resumable")
    x.add_argument("--stages", help=f"comma-separated subset of {','.join(STAGES)}")
    x.add_argument("--force", action="store_true", help="rerun stages even if their inputs are unchanged")
    x.add_argument("--offline", action="store_true", help="no Yahoo: learn from the stored and recorded bars only")
    x.set_defaults(fn=cmd_cycle)
    for stage, help_ in (("ingest", "validate and store bars, resolve outcomes, ingest closed paper trades"),
                         ("dataset", "build the versioned dataset"), ("train", "train challengers (walk-forward)"),
                         ("validate", "costs, metrics, intervals, gates, the locked final test"),
                         ("register", "register qualified challengers"), ("paper", "shadow paper results and drift"),
                         ("promote", "promote or reject, with the reasons on record")):
        x = ss.add_parser(stage, help=help_)
        x.add_argument("--force", action="store_true")
        x.add_argument("--offline", action="store_true")
        x.set_defaults(fn=cmd_cycle, stages=stage)
    x = ss.add_parser("status", help="champion, freshness, last cycle, drift, risk, paper results, recovery point")
    x.add_argument("--json", action="store_true")
    x.set_defaults(fn=cmd_status)
    x = ss.add_parser("verify", help="integrity of the ledger, the registry and the journal (exit 1 on any problem)")
    x.set_defaults(fn=cmd_verify)
    x = ss.add_parser("recover", help="move torn ledger lines aside, rebuild registry state, clear a stale lock, reset "
                                      "unfinished stages")
    x.set_defaults(fn=cmd_recover)
    x = ss.add_parser("rollback", help="make the previous champion the champion again")
    x.add_argument("--reason", required=True)
    x.set_defaults(fn=cmd_rollback)


def cmd_cycle(cfg, a):
    stages = [s.strip() for s in (a.stages or "").split(",") if s.strip()] or None
    bad = [s for s in stages or [] if s not in STAGES]
    if bad:
        sys.exit(f"unknown stage(s): {', '.join(bad)}")
    c = Cycle(cfg, loader=default_loader(cfg, offline=getattr(a, "offline", False)))
    try:
        st = c.run(stages, force=getattr(a, "force", False))
    except CycleBusy as exc:
        sys.exit(str(exc))
    print(f"cycle {st['cycle_id']}: {st.get('status')}")
    if st.get("status") == "failed":
        sys.exit(1)


def cmd_status(cfg, a):
    from .status import render, status
    s = status(cfg)
    print(json.dumps(s, indent=1, default=str) if a.json else render(s))


def cmd_verify(cfg, a):
    from pathlib import Path

    from .ledger import Ledger
    from .registry import Registry
    root = root_of(cfg)
    bad = Ledger(root).verify() + Registry(root).verify()
    j = Path(cfg.runtime_dir) / "intraday" / "journal.db"
    if j.exists():
        import sqlite3
        with sqlite3.connect(f"file:{j}?mode=ro", uri=True) as db:
            r = db.execute("PRAGMA integrity_check").fetchone()[0]
        if r != "ok":
            bad.append(f"journal: {r}")
    print("\n".join(bad) if bad else "learning ledger, registry and journal: intact")
    if bad:
        sys.exit(1)


def cmd_recover(cfg, a):
    from .ledger import Ledger
    from .registry import Registry
    from .store import read_json, write_json
    root = root_of(cfg)
    n = Ledger(root).recover()
    st = Registry(root).rebuild_state()
    lock = root / "cycle.lock"
    had_lock = lock.exists()
    if had_lock:
        lock.unlink()
    reset = 0
    for p in sorted((root / "cycles").glob("????-??-??.json")) if (root / "cycles").exists() else []:
        c = read_json(p) or {}
        for name, rec in (c.get("stages") or {}).items():
            if rec.get("status") in ("running", "failed"):
                rec["status"] = "reset"
                reset += 1
        write_json(p, c)
    print(f"recovered: {n} torn ledger line(s) moved to .corrupt files; registry state rebuilt "
          f"(champion {st.get('champion') or 'none'}); {'stale lock cleared; ' if had_lock else ''}{reset} unfinished stage(s) "
          f"will rerun on the next cycle")


def cmd_rollback(cfg, a):
    from .registry import PromotionRefused, Registry
    try:
        e = Registry(root_of(cfg)).rollback(a.reason)
    except (PromotionRefused, Exception) as exc:
        sys.exit(f"rollback refused: {exc}")
    print(f"rolled back: champion is now {e.get('to')} (was {e.get('model_id')})")
