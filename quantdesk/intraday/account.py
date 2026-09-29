"""The paper account's identity: its starting capital and when it started. The capital in the
config is only a *request*; the account's real balance lives in broker.json and the journal.

* A new account, or one that hasn't traded yet, simply takes the configured capital.
* Once it has trades, changing the config does nothing on its own (history would stop adding
  up); `quantdesk intraday reset-account` archives the old account and starts a fresh one.
"""
from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pandas as pd

from ..journal.journal import Journal

IST = "Asia/Kolkata"


def ensure_account(cfg, journal: Journal, broker_path: Path, say=print) -> float:
    """Returns the account's starting capital, (re)initialising it when that's safe."""
    cap = float(cfg.get("intraday.capital", 20000))
    acct = journal.get_state("intraday_account")
    n_trades = int(journal.df("SELECT COUNT(*) AS n FROM trades")["n"].iloc[0])
    now = pd.Timestamp.now(tz=IST)
    if n_trades == 0 and (acct is None or float(acct.get("capital", 0)) != cap):
        if Path(broker_path).exists():
            Path(broker_path).unlink()
        journal.set_state("intraday_account", {"capital": cap, "since": str(now.date())})
        if acct is not None:
            journal.event(now, "WARN", "account", f"no trades yet: account reset from ₹{acct['capital']:,.0f} to ₹{cap:,.0f}")
            say(f"account reset to ₹{cap:,.0f} (it had no trades)")
        journal.commit()
        return cap
    if acct is None:                                   # an older account that predates this record
        acct = {"capital": cap, "since": None}
        journal.set_state("intraday_account", acct)
        journal.commit()
    if float(acct["capital"]) != cap:
        say(f"note: config capital ₹{cap:,.0f} but this account started with ₹{acct['capital']:,.0f} and has "
            f"{n_trades} trades; run `quantdesk intraday reset-account` to start over at ₹{cap:,.0f}")
    return float(acct["capital"])


def reset_account(base: Path) -> Path | None:
    """Move journal, broker, reviews and state aside (runtime/intraday/archive/<stamp>/)."""
    base = Path(base)
    items = [base / n for n in ("journal.db", "broker.json", "reviews") if (base / n).exists()]
    if not items:
        return None
    dest = base / "archive" / pd.Timestamp.now(tz=IST).strftime("%Y-%m-%d_%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for it in items:
        shutil.move(str(it), str(dest / it.name))
    return dest
