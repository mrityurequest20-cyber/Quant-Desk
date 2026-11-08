"""`quantdesk paper …`: the manual paper runner (docs/RECORDING.md, "The paper runner"). Paper money only; nothing here can reach a broker."""
from __future__ import annotations

from pathlib import Path


def cmd_run(cfg, a):
    from .relay import Relay
    from .session import parse_hhmm, run
    try:
        relay = Relay.from_env()
    except ValueError as e:
        raise SystemExit(f"paper run: {e}") from None
    raise SystemExit(run(cfg, relay, Path(a.ledger), parse_hhmm(a.until), every_s=a.every, new_account=a.new_account))


def cmd_verify(cfg, a):
    """Is this saved account intact (hash chain, replay, flags)? Exits 1 if not. The publish job runs this before it puts the file on the ledger branch."""
    from ..paper.runner import load_account
    p = Path(a.file)
    try:
        acct = load_account(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        print(f"paper verify: {e}")
        raise SystemExit(1) from None
    print(f"paper verify: ok; {len(acct.ledger)} ledger rows, {len(acct.positions)} open positions, cash {acct.cash:,.2f}")


def register(sub):
    s = sub.add_parser("paper", help="the manual paper runner: the owner's queued paper orders through the risk gate (paper money only)")
    ss = s.add_subparsers(dest="pcmd", required=True)
    x = ss.add_parser("run", help="run the session loop (env LIVE_URL, LIVE_READ_TOKEN, LIVE_INGEST_TOKEN)")
    x.add_argument("--until", default="15:35", help="IST clock time to stop, HH:MM")
    x.add_argument("--every", type=float, default=3.0, help="seconds between cycles")
    x.add_argument("--new-account", action="store_true", help="the very first session only: start a new paper account when no saved one exists anywhere (otherwise a missing account stops the start)")
    x.add_argument("--ledger", default="runtime/paper/ledger/account.json", help="the local copy of the saved account (restored from, and published to, the ledger branch)")
    x.set_defaults(fn=cmd_run)
    x = ss.add_parser("verify", help="check a saved account file")
    x.add_argument("--file", default="runtime/paper/ledger/account.json")
    x.set_defaults(fn=cmd_verify)
