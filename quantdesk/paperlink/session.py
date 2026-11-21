"""The paper runner's session: restore the account, then every few seconds read the board and the queue, run `Runner.step`, save, report. Paper money only."""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
from pathlib import Path

from ..markets import sessions as MK
from ..paper.account import Account
from ..paper.runner import Runner, account_json, choose_state, fingerprint, fit_summary, load_account, state_size
from .relay import Relay, RelayError

IST = MK.IST
EXIT_REFUSED = 3             # the saved histories disagree or do not verify: the runner will not start
EXIT_UNSAVED = 4             # the part ended with ledger rows the relay never got: the next part starts without them, so the run goes red
EXIT_BRAKES_DOWN = 5         # the cycle failed BRAKES_DOWN_AFTER times in a row at some point in the part: the brakes did not run, so the run goes red (audit K-06, FH-05)
BRAKES_DOWN_AFTER = 20       # consecutive failed cycles (about a minute) before an ::error:: is written and the state says brakes_down
UNSAFE_AFTER_S = 30.0        # new entries wait when the relay has not been given the latest fill for this long (exits and the brakes still run)
NEWS_EVERY_S = 60.0          # the autopilot reads the news digest at most this often
FULL_EVERY_S = 60.0          # the whole account goes to the relay at least this often when only the figures the brakes use (high-water mark, day start) have moved
BRIEF_EVERY_S = 900.0        # the pre-market brief is fetched for the day plan this often, 05:50 to 09:20 IST
BRIEF_WINDOW = (dt.time(5, 50), dt.time(9, 20))
BRIEF_MAX_BYTES = 4 << 20


def fetch_brief(repo: str, today: dt.date, opener=None) -> dict | None:
    """Today's pre-market brief (premarket.yml publishes it to the public `premarket` branch), or None: not published yet, not today's, unreadable or the network.
    Public data only (NSE tables, Yahoo, RSS); it holds no secret and needs none."""
    import json
    import re
    import urllib.request
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repo or ""):
        return None
    url = f"https://raw.githubusercontent.com/{repo}/premarket/brief.json"
    try:
        with (opener or urllib.request.urlopen)(urllib.request.Request(url, headers={"User-Agent": "quantdesk-paper"}), timeout=20) as r:
            b = json.loads(r.read(BRIEF_MAX_BYTES))
    except Exception:                                                  # noqa: BLE001 - no brief only means planning without it
        return None
    return b if isinstance(b, dict) and b.get("session") == today.isoformat() else None


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


def _why(e: Exception) -> str:
    """A failed save's reason for the log: a RelayError's own text (a method, a path and an HTTP status or an exception class, by design nothing secret), else the class."""
    return str(e)[:120] if isinstance(e, RelayError) else type(e).__name__


def _unsaved(account, ledger_pushed: int) -> str:
    """How much of the ledger the relay is not known to hold. -1: no save of this part reached it, so the rows restored at the start may be there and the count is unknown."""
    if ledger_pushed < 0:
        return f"no save of this part reached the relay ({len(account.ledger)} ledger rows here)"
    return f"{len(account.ledger) - ledger_pushed} ledger rows NOT on the relay"


def _size(summ) -> str:
    """The state's size for a log line; "?" when there is none (the summary itself failed). Never raises: a log line must never stop the runner or the brakes."""
    if not isinstance(summ, dict):
        return "?"
    try:
        return f"{state_size(fit_summary(summ)):,}"
    except Exception:                                                  # noqa: BLE001 - a log line must never stop the runner
        return "?"


def _minimal(account, now, why: str) -> dict:
    """The smallest view the relay takes with an account (it needs the ledger's length): sent when the full summary cannot be built or is refused, so the record
    never waits for the app's view (audit K-01, K-06). The app shows it as degraded."""
    return {"v": 1, "asof": now.isoformat() if now is not None else None, "ledger_len": len(account.ledger), "degraded": str(why)[:120]}


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
    ledger_pushed, last_full, last_sum, pending, fails, save_fails = -1, 0.0, 0.0, [], 0, 0
    cycle_fails, brakes_down_seen, view_degraded = 0, False, 0          # audit K-06: a failing cycle is counted, and a failing summary never costs the record
    account.save(ledger_path)
    fp_disk = fingerprint(account)
    if auto is not None and hasattr(auto, "load"):                    # AUTO v2: its strategies' shadow record, kept on the relay across sessions
        auto.runner_commit = os.environ.get("GITHUB_SHA") or None      # phase 2's monthly report names the code that produced it (the paper package reads no environment)
        log(f"paper: AUTO v2 strategy record: {auto.load(relay)}")
    try:                                                              # the account goes to the relay once before the first cycle, so even a session with no cycles (the very first, by hand, out of hours) leaves it there
        snap0 = relay.snapshot()
        now0 = Runner.server_now(snap0)
        if now0 is not None:
            relay.put_state(fit_summary(rn.summary(snap0, now0)), account_json(account))
            ledger_pushed, fp_pushed, last_full, last_sum = len(account.ledger), fingerprint(account), time.monotonic(), time.monotonic()
    except (RelayError, ValueError, OverflowError) as e:
        log(f"paper: could not send the opening state to the relay ({_why(e)}); will retry")
    unsafe_since = None
    news, news_at = None, -1e9
    brief_at = -1e9
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
        releases = [o for o in orders if isinstance(o, dict) and o.get("side") == "release"]
        orders = [o for o in orders if not (isinstance(o, dict) and o.get("side") == "release")]
        for o in releases:                                             # the owner releases a strategy from probation (evolution phase 2): no order, no money, never the gate
            if not isinstance(o.get("id"), str):
                continue
            try:
                ok, why = auto.owner_release(o.get("sid"), clock()) if auto is not None and hasattr(auto, "owner_release") else (False, "AUTO v2 is not running in this session")
            except Exception as e:                                     # noqa: BLE001 - a fault here must never stop the runner or the brakes
                ok, why = False, f"the release failed ({type(e).__name__})"
            pending.append({"id": o["id"], "status": "done" if ok else "refused", "reasons": [str(why)[:200]], "at": clock().isoformat()})
            log(f"paper: owner release request {o['id']}: {'done' if ok else 'refused'}")   # no strategy named: per strategy, it stays on the relay (the spec's publication)
        if auto is not None:                                           # AUTO v1: its orders join the owner's and go through the very same step, gate and brakes
            ist_now = clock().astimezone(IST)
            if hasattr(auto, "brief") and BRIEF_WINDOW[0] <= ist_now.time() <= BRIEF_WINDOW[1] and time.monotonic() - brief_at >= BRIEF_EVERY_S:
                brief_at = time.monotonic()                            # the day plan's catalysts: fetched every fifteen minutes before the open; a failure keeps the last one
                got_brief = fetch_brief(os.environ.get("GITHUB_REPOSITORY", ""), ist_now.date())
                if got_brief is not None:
                    auto.brief = got_brief
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
            if hasattr(auto, "save"):
                auto.save(relay, time.monotonic())                     # at most every two minutes, and only when the record changed
            for o in mine:
                log(f"paper: auto proposes {o['side']} {o.get('symbol') or '+'.join(l['symbol'] for l in o.get('legs', []))}" + (f" ({o['_why']})" if o.get('_why') else ""))
            orders = orders + mine
        try:
            rep = rn.step(snap, orders, kill, clock())
            cycle_fails = 0
        except Exception as e:                                         # noqa: BLE001 - whatever went wrong, what was filled before it is still saved below
            rep = {"asof": None, "skipped": f"the cycle failed ({type(e).__name__})", "forced": [], "results": []}
            cycle_fails += 1
            if cycle_fails == BRAKES_DOWN_AFTER:                       # the brakes are in step(): with it failing, nothing is watched (FH-05)
                brakes_down_seen = True
                log(f"::error::paper: {cycle_fails} cycles in a row failed ({type(e).__name__}): the brakes are not running (nothing in the cycle is: no entry, exit, "
                    f"stop or cap); it keeps retrying, and this part will end red")
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
                summ = None                                                # set before the try: the except below logs its size, and must never fail itself
                try:
                    try:                                                   # the app's view, built from everything; ANY error in it (audit K-06, AIJ-05) gives a
                        summ = rn.summary(snap, now)                       # minimal view instead, and never stops the runner or the record
                        if auto is not None and hasattr(auto, "summary"):
                            summ["lab"] = auto.summary()                # the Strategy lab panel in the app
                    except Exception as e:                             # noqa: BLE001 - see above
                        view_degraded += 1
                        if view_degraded == 1 or view_degraded % 100 == 0:
                            log(f"paper: the app's summary could not be built ({type(e).__name__}); a minimal one is sent ({view_degraded} times)")
                        summ = _minimal(account, now, f"summary failed ({type(e).__name__})")
                    summ["brakes_down"] = cycle_fails >= BRAKES_DOWN_AFTER
                    summ["cycle_fails"] = cycle_fails
                    try:
                        relay.put_state(fit_summary(summ), account_json(account) if full else None)
                    except RelayError:
                        if not full:
                            raise
                        relay.put_state(_minimal(account, now, "the full summary was refused"), account_json(account))   # the record never waits for the view (K-01)
                        view_degraded += 1
                    last_sum = mono
                    if save_fails:
                        log(f"paper: the relay took the state again after {save_fails} failed saves")
                    save_fails = 0
                    if full:
                        ledger_pushed, fp_pushed, last_full = fp[0], fp, mono
                except (RelayError, ValueError, OverflowError) as e:
                    save_fails += 1
                    if save_fails == 1 or save_fails % 20 == 0:                # the first, then about once a minute: the reason, not a wall of the same line
                        log(f"paper: could not save the state to the relay ({_why(e)}); {save_fails} in a row; {_unsaved(account, ledger_pushed)}; "
                            f"state {_size(summ)} characters; will retry")
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
    if auto is not None and hasattr(auto, "save"):
        auto.save(relay, time.monotonic(), force=True)
    if len(account.ledger) > max(ledger_pushed, 0):                    # a last try: the next part of the day starts from the relay's copy, so a fill it never got is lost there
        try:
            snap = relay.snapshot()
            now = Runner.server_now(snap)
            if now is not None:
                relay.put_state(fit_summary(rn.summary(snap, now)), account_json(account))
                ledger_pushed = len(account.ledger)
        except (RelayError, ValueError, OverflowError) as e:
            log(f"paper: the last save to the relay failed too ({_why(e)})")
    log(f"paper: session ended; {len(account.ledger)} ledger rows")
    if len(account.ledger) > max(ledger_pushed, 0):                    # red, so it is seen: the relay does not hold this part's whole ledger and the next part will start without it
        log(f"paper: {_unsaved(account, ledger_pushed)}: the next part of the day starts from the relay's copy without them. The owner must look.")
        return EXIT_UNSAVED
    if brakes_down_seen:
        log(f"::error::paper: at some point {BRAKES_DOWN_AFTER} or more cycles in a row failed and the brakes did not run. The owner must look.")
        return EXIT_BRAKES_DOWN
    return 0


def parse_hhmm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


if __name__ == "__main__":                                              # pragma: no cover
    sys.exit("use: python -m quantdesk paper run")
