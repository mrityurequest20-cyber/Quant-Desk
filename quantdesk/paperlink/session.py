"""The paper runner's session: restore the account, then every few seconds read the board and the queue, run `Runner.step`, save, report. Paper money only."""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

from ..markets import sessions as MK
from ..paper.account import Account
from ..paper.runner import Runner, account_json, choose_state, load_account
from .relay import Relay, RelayError

IST = MK.IST
EXIT_REFUSED = 3             # the saved histories disagree or do not verify: the runner will not start


def restore(cfg, relay: Relay, ledger_path: Path, say=print, sleep=time.sleep, tries: int = 6, wait_s: float = 10.0) -> Account:
    """The account to continue from: the relay's saved account and the ledger branch's file (restored by the workflow), the longer one if it extends the other.
    The relay must answer: without it there are no orders, and a runner that started from the branch alone could later write a shorter history over the relay's."""
    answer = None
    for i in range(tries):
        try:
            answer = relay.get_state() or {}
            break
        except RelayError as e:
            say(f"paper: could not read the relay's saved account ({e}); try {i + 1} of {tries}")
            sleep(wait_s)
    if answer is None:
        raise SystemExit("paper: the relay did not answer: not starting (nothing can be traded without it)")
    branch = ledger_path.read_text(encoding="utf-8") if ledger_path.exists() else None
    try:
        a, b = load_account(answer.get("account")), load_account(branch)
    except ValueError as e:
        raise SystemExit(f"paper: a saved account does not verify ({e}): not starting") from None
    acct, note = choose_state(a, b)
    if acct is None and not (a is None and b is None):
        raise SystemExit(f"paper: {note}")
    if acct is None:
        cap = cfg.get("paper.capital")
        say(f"paper: no saved account; starting a new paper account with {cap:,.0f}")
        return Account(float(cap))
    say(f"paper: {note}; {len(acct.ledger)} ledger rows, {len(acct.positions)} open positions")
    return acct


def run(cfg, relay: Relay, ledger_path: Path, until_ist: dt.time, every_s: float = 3.0, *, clock=None, sleep=time.sleep, say=print, runner: Runner | None = None) -> int:
    """Run until `until_ist` (IST clock time today). Returns a process exit code."""
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    account = runner.account if runner else restore(cfg, relay, ledger_path, say, sleep)
    rn = runner or Runner(cfg, account)
    saved_len, last_state, pending, fails = len(account.ledger), 0.0, [], 0
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    account.save(ledger_path)
    while clock().astimezone(IST).time() < until_ist:
        t0 = time.monotonic()
        try:
            snap, q = relay.snapshot(), relay.queue()
            fails = 0
        except RelayError as e:
            fails += 1
            if fails in (1, 10, 100):
                say(f"paper: relay unreachable ({e}); {fails} cycles in a row")
            sleep(every_s)
            continue
        waiting = {r["id"] for r in pending}                           # an order whose result is still waiting to be posted is not handled again (it would only add a "done")
        orders = [o for o in (q.get("orders") if isinstance(q.get("orders"), list) else []) if not (isinstance(o, dict) and o.get("id") in waiting)]
        rep = rn.step(snap, orders, bool(q.get("kill")), clock())
        if rep["skipped"]:
            say(f"paper: cycle skipped: {rep['skipped']}")
        now = Runner.server_now(snap)
        changed = len(account.ledger) != saved_len
        if changed:
            account.save(ledger_path)                                  # on disk first, then the relay, then the order results: a crash can repeat a report, never a fill
            saved_len = len(account.ledger)
        if now is not None and (changed or time.monotonic() - last_state > 10):
            try:
                relay.put_state(rn.summary(snap, now), account_json(account) if changed or last_state == 0.0 else None)
                last_state = time.monotonic()
            except RelayError as e:
                say(f"paper: could not save the state to the relay ({e}); will retry")
                saved_len = -1                                         # forces a full state upload on the next change check
        pending.extend(rep["results"])
        for res in list(pending):
            if res.get("id") is None:
                pending.remove(res)
                continue
            try:
                relay.post_result(res)
                pending.remove(res)
                if res["status"] in ("filled", "refused", "expired"):
                    say(f"paper: order {res['id']}: {res['status']} {'; '.join(res.get('reasons') or [])}")
            except RelayError as e:
                say(f"paper: could not report order {res['id']} ({e}); will retry")
        sleep(max(0.0, every_s - (time.monotonic() - t0)))
    account.save(ledger_path)
    say(f"paper: session ended; {len(account.ledger)} ledger rows")
    return 0


def parse_hhmm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


if __name__ == "__main__":                                              # pragma: no cover
    sys.exit("use: python -m quantdesk paper run")
