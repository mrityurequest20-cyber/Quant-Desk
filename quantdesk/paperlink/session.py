"""The paper runner's session: restore the account, then every few seconds read the board and the queue, run `Runner.step`, save, report. Paper money only."""
from __future__ import annotations

import datetime as dt
import sys
import time
from pathlib import Path

from ..markets import sessions as MK
from ..paper.account import Account
from ..paper.runner import Runner, account_json, choose_state, fingerprint, load_account
from .relay import Relay, RelayError

IST = MK.IST
EXIT_REFUSED = 3             # the saved histories disagree or do not verify: the runner will not start
UNSAFE_AFTER_S = 30.0        # new entries wait when the relay has not been given the latest fill for this long (exits and the brakes still run)
NEWS_EVERY_S = 60.0          # the autopilot reads the news digest at most this often
FULL_EVERY_S = 60.0          # the whole account goes to the relay at least this often when only the figures the brakes use (high-water mark, day start) have moved


def restore(cfg, relay: Relay, ledger_path: Path, say=print, sleep=time.sleep, tries: int = 6, wait_s: float = 10.0, allow_new: bool = False) -> Account:
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
    if acct is None and not allow_new:
        raise SystemExit("paper: no saved account on the relay or the ledger branch. If this is the very first session, start it once by hand with --new-account; "
                         "otherwise the saved state was lost and the owner must look (a new account would start the history over)")
    if acct is None:
        cap = cfg.get("paper.capital")
        say(f"paper: no saved account; starting a new paper account with {cap:,.0f}")
        return Account(float(cap))
    say(f"paper: {note}; {len(acct.ledger)} ledger rows, {len(acct.positions)} open positions")
    return acct


def _clean(x) -> str:
    """Anything that came from outside, made safe for a log line (no new lines, so no workflow command can start one)."""
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in str(x))[:300]


def run(cfg, relay: Relay, ledger_path: Path, until_ist: dt.time, every_s: float = 3.0, *, clock=None, sleep=time.sleep, say=print, runner: Runner | None = None,
        new_account: bool = False, auto=None) -> int:
    """Run until `until_ist` (IST clock time today). Returns a process exit code."""
    clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
    log = lambda m: say(_clean(m))                                      # noqa: E731
    account = runner.account if runner else restore(cfg, relay, ledger_path, log, sleep, allow_new=new_account)
    rn = runner or Runner(cfg, account)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    fp_disk = fp_pushed = None
    ledger_pushed, last_full, last_sum, pending, fails = -1, 0.0, 0.0, [], 0
    account.save(ledger_path)
    fp_disk = fingerprint(account)
    try:                                                              # the account goes to the relay once before the first cycle, so even a session with no cycles (the very first, by hand, out of hours) leaves it there
        snap0 = relay.snapshot()
        now0 = Runner.server_now(snap0)
        if now0 is not None:
            relay.put_state(rn.summary(snap0, now0), account_json(account))
            ledger_pushed, fp_pushed, last_full, last_sum = len(account.ledger), fingerprint(account), time.monotonic(), time.monotonic()
    except (RelayError, ValueError, OverflowError) as e:
        log(f"paper: could not send the opening state to the relay ({type(e).__name__}); will retry")
    unsafe_since = None
    news, news_at = None, -1e9
    while clock().astimezone(IST).time() < until_ist:
        t0 = time.monotonic()
        try:
            snap, q = relay.snapshot(), relay.queue()
            fails = 0
        except RelayError as e:
            fails += 1
            if fails in (1, 10, 100):
                log(f"paper: relay unreachable ({e}); {fails} cycles in a row")
            sleep(every_s)
            continue
        waiting = {r["id"] for r in pending}                           # an order whose result is still waiting to be posted is not handled again (it would only add a "done")
        raw_orders = q.get("orders") if isinstance(q.get("orders"), list) else []
        orders = [o for o in raw_orders if not (isinstance(o, dict) and isinstance(o.get("id"), str) and o["id"] in waiting)]
        kill = q.get("kill") is not False                              # a missing or odd answer counts as ON: the safe way round
        if auto is not None:                                           # AUTO v1: its orders join the owner's and go through the very same step, gate and brakes
            if time.monotonic() - news_at >= NEWS_EVERY_S:             # the news digest, at most once a minute; a failure just means no news reading (it never blocks anything)
                news_at = time.monotonic()
                try:
                    got = relay.news()
                    news = got.get("digest") if isinstance(got, dict) and isinstance(got.get("digest"), dict) else None
                except (RelayError, AttributeError):
                    news = None
            try:
                srv = Runner.server_now(snap)
                mine = auto.decide(snap, rn.account, srv, kill=kill, entries_blocked=rn.entries_blocked, cal=rn.gate.cal, news=news) if srv is not None else []
                for ev in auto.drain_events():                         # a held position's new peak goes into the ledger, so the trailing stop survives a restart and the night
                    try:
                        account.record_event(ev["kind"], srv.isoformat(), **{k: v for k, v in ev.items() if k != "kind"})
                    except (ValueError, TypeError):
                        pass
            except Exception as e:                                     # noqa: BLE001 - a fault in the autopilot must never stop the runner or the brakes
                mine = []
                log(f"paper: the autopilot failed this cycle ({type(e).__name__}); the owner's orders and the brakes go on")
            for o in mine:
                log(f"paper: auto proposes {o['side']} {o['symbol']}" + (f" ({o['_why']})" if o.get('_why') else ""))
            orders = orders + mine
        try:
            rep = rn.step(snap, orders, kill, clock())
        except Exception as e:                                         # noqa: BLE001 - whatever went wrong, what was filled before it is still saved below
            rep = {"asof": None, "skipped": f"the cycle failed ({type(e).__name__})", "forced": [], "results": []}
        if rep["skipped"]:
            log(f"paper: cycle skipped: {rep['skipped']}")
        now = Runner.server_now(snap)
        fp = fingerprint(account)
        if fp != fp_disk:                                              # on disk first, then the relay, then the order results: a crash can repeat a report, never a fill
            account.save(ledger_path)
            fp_disk = fp
        if now is not None:
            mono = time.monotonic()
            full = fp[0] != ledger_pushed or (fp != fp_pushed and mono - last_full >= FULL_EVERY_S)      # the whole account: at once for a new fill, within a minute for the figures the brakes use
            if full or mono - last_sum > 10:
                try:
                    relay.put_state(rn.summary(snap, now), account_json(account) if full else None)
                    last_sum = mono
                    if full:
                        ledger_pushed, fp_pushed, last_full = fp[0], fp, mono
                except (RelayError, ValueError, OverflowError) as e:
                    log(f"paper: could not save the state to the relay ({type(e).__name__}); will retry")
        if ledger_pushed == len(account.ledger):                       # the relay holds every fill
            unsafe_since, rn.entries_blocked = None, None
        else:
            unsafe_since = unsafe_since if unsafe_since is not None else time.monotonic()
            if time.monotonic() - unsafe_since >= UNSAFE_AFTER_S:
                rn.entries_blocked = "new orders wait: the relay could not be given the latest fills for over 30 seconds (exits still work)"
        pending.extend(rep["results"])
        if ledger_pushed == len(account.ledger):                       # a result is posted only once the fill it reports is safe on the relay
            for res in list(pending):
                if res.get("id") is None:
                    pending.remove(res)
                    continue
                try:
                    relay.post_result(res)
                    pending.remove(res)
                    if res["status"] in ("filled", "refused", "expired"):
                        log(f"paper: order {res['id']}: {res['status']} {'; '.join(res.get('reasons') or [])}")
                except RelayError as e:
                    log(f"paper: could not report order {res['id']} ({e}); will retry")
        sleep(max(0.0, every_s - (time.monotonic() - t0)))
    account.save(ledger_path)
    log(f"paper: session ended; {len(account.ledger)} ledger rows")
    return 0


def parse_hhmm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


if __name__ == "__main__":                                              # pragma: no cover
    sys.exit("use: python -m quantdesk paper run")
