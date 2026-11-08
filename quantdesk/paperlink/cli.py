"""`quantdesk paper …`: the manual paper runner (docs/RECORDING.md, "The paper runner"). Paper money only; nothing here can reach a broker."""
from __future__ import annotations

import os
from pathlib import Path


def cmd_run(cfg, a):
    from .relay import Relay
    from .session import parse_hhmm, run
    try:
        relay = Relay.from_env()
    except ValueError as e:
        raise SystemExit(f"paper run: {e}") from None
    auto = None
    if getattr(a, "auto", False) or os.environ.get("PAPER_AUTO", "").strip().lower() in ("1", "yes", "on", "true"):
        from ..paper.auto import AutoPilot
        from ..paper.risk import RiskGate
        und = sorted(RiskGate(cfg).limits.underlyings.get("nse_fo", ()))
        lots = {str(u).upper(): int(v["lot_size"]) for u, v in (cfg.get("instruments") or {}).items() if isinstance(v, dict) and isinstance(v.get("lot_size"), int)}
        auto = AutoPilot(tuple(u for u in und if u in lots), lots, float(cfg.get("paper.capital")))
        print(f"paper: AUTO v1 is ON for {', '.join(auto.und)} (one lot a trade, no cap on how many, through the same gate and its loss caps)", flush=True)
    raise SystemExit(run(cfg, relay, Path(a.ledger), parse_hhmm(a.until), every_s=a.every, new_account=a.new_account, auto=auto))


def cmd_verify(cfg, a):
    """Is this saved account intact (hash chain, replay, flags)? With --extends OLD: and does it continue OLD (OLD's ledger is its exact prefix)? Exits 1 if not.
    The publish job runs this before it adds the file to the ledger branch, so the branch can only ever gain rows."""
    from ..paper.runner import choose_state, load_account
    p = Path(a.file)
    try:
        acct = load_account(p.read_text(encoding="utf-8"))
        old = None
        if getattr(a, "extends", None) and Path(a.extends).exists():
            old = load_account(Path(a.extends).read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        print(f"paper verify: {e}")
        raise SystemExit(1) from None
    if old is not None:
        chosen, note = choose_state(acct, old)
        if chosen is not acct:
            print(f"paper verify: this does not continue the branch's account ({note})")
            raise SystemExit(1)
    print(f"paper verify: ok; {len(acct.ledger)} ledger rows, {len(acct.positions)} open positions, cash {acct.cash:,.2f}" + ("; continues the branch's account" if old is not None else ""))


def register(sub):
    s = sub.add_parser("paper", help="the manual paper runner: the owner's queued paper orders through the risk gate (paper money only)")
    ss = s.add_subparsers(dest="pcmd", required=True)
    x = ss.add_parser("run", help="run the session loop (env LIVE_URL, LIVE_READ_TOKEN, LIVE_INGEST_TOKEN)")
    x.add_argument("--until", default="15:35", help="IST clock time to stop, HH:MM")
    x.add_argument("--every", type=float, default=3.0, help="seconds between cycles")
    x.add_argument("--new-account", action="store_true", help="the very first session only: start a new paper account when no saved one exists anywhere (otherwise a missing account stops the start)")
    x.add_argument("--auto", action="store_true", help="switch AUTO v1 on (the paper desk deciding for itself, one lot, tight limits, through the same gate); also on when env PAPER_AUTO is yes")
    x.add_argument("--ledger", default="runtime/paper/ledger/account.json", help="the local copy of the saved account (restored from, and published to, the ledger branch)")
    x.set_defaults(fn=cmd_run)
    x = ss.add_parser("verify", help="check a saved account file")
    x.add_argument("--file", default="runtime/paper/ledger/account.json")
    x.add_argument("--extends", help="a saved account that this one must continue (its ledger must be a prefix of this one's); skipped if the file does not exist")
    x.set_defaults(fn=cmd_verify)
