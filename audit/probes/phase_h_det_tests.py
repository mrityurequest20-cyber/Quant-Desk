"""Phase H deterministic tests 8 (crash between ledger write and state update) and 16 (restart recovery).

Isolated: every journal, broker file and runtime dir is in a fresh temp dir; the market is synthetic (ReplayFeed over
simulate_sessions), the chain is the engine's model chain, the broker is the paper IntradayBroker. Nothing touches the
repository's runtime, the journal branch or any network service. A 'crash' is simulated by raising a BaseException
(so the engine's `except Exception` guards cannot swallow it) and then closing the SQLite connection WITHOUT commit,
which is what a killed process leaves behind (uncommitted rows are lost; fsync'd files survive).
"""
import datetime as dt
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from quantdesk.config import Config, DEFAULT_CONFIG  # noqa: E402
from quantdesk.core.calendar import TradingCalendar  # noqa: E402
from quantdesk.intraday.analyst import MarketView  # noqa: E402
from quantdesk.intraday.engine import IntradayEngine  # noqa: E402
from quantdesk.intraday.feeds import ReplayFeed  # noqa: E402
from quantdesk.intraday.playbook import PlanLeg, TradePlan  # noqa: E402
from quantdesk.intraday.sim import IntradayBroker  # noqa: E402
from quantdesk.intraday.synthetic import simulate_sessions  # noqa: E402
from quantdesk.journal.journal import Journal  # noqa: E402

IST = "Asia/Kolkata"


class Crash(BaseException):
    """A process death: not an Exception, so no `except Exception` in the engine catches it."""


def world():
    cfg_base = Config.load(DEFAULT_CONFIG)
    cal = TradingCalendar(cfg_base.holidays())
    days = [d.date() for d in cal.trading_days("2026-08-17", "2026-09-29")]
    bars, _ = simulate_sessions(days, seed=5)
    return bars, days


def make(tmp: Path, bars, day, at: str | None = None) -> IntradayEngine:
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    feed = ReplayFeed(bars, day)
    if at:
        feed.clock = pd.Timestamp(f"{day} {at}", tz=IST)
    return IntradayEngine(cfg, feed, "model", Journal(tmp / "j.db"),
                          IntradayBroker(cfg, starting_cash=500000, state_path=tmp / "broker.json"), say=None)


def advance(eng, until: str):
    end = pd.Timestamp(f"{eng.day} {until}", tz=IST)
    while eng.feed.now() < end and eng.feed.advance():
        eng.step()


def spread_plan(eng, u="NIFTY") -> TradePlan:
    """A two-leg debit call spread from the engine's own (model) chain: long ATM, short two strikes up."""
    ch = eng.chain_df[u]
    S = float(ch.attrs["spot"])
    ks = ch.index.to_numpy(float)
    i = int(np.argmin(np.abs(ks - S)))
    k1, k2 = ks[i], ks[i + 2]
    r1, r2 = ch.loc[k1], ch.loc[k2]
    legs = [PlanLeg(k1, "CE", 1, float(r1.ce_ask), float((r1.ce_bid + r1.ce_ask) / 2), float(r1.ce_iv), 0.5),
            PlanLeg(k2, "CE", -1, float(r2.ce_bid), float((r2.ce_bid + r2.ce_ask) / 2), float(r2.ce_iv), 0.35)]
    return TradePlan("audit_probe", u, 1, "call debit spread", eng.expiry[u], legs, eng.lot(u), "probe", "probe",
                     None, None, 0.99, 50.0, 9999, str(ch.attrs.get("source")), 0.5)


def view(eng, u="NIFTY") -> MarketView:
    S = float(eng.chain_df[u].attrs["spot"])
    return MarketView(u, eng.feed.now(), S, "neutral", 0.0, 0.5, "trend", "fair", None, None, [], [], {}, "probe")


def crash_on_call(eng, n: int):
    """Wrap the broker so that its n-th execute() (1-based) dies BEFORE executing; earlier calls go through and are
    fsync'd to broker.json by the broker itself."""
    orig, calls = eng.broker.execute, {"n": 0}

    def wrapped(order, ref, ts, atr=None):
        calls["n"] += 1
        if calls["n"] == n:
            raise Crash(f"killed before broker call {n}")
        return orig(order, ref, ts, atr)
    eng.broker.execute = wrapped


def die(eng):
    """What a killed process leaves: uncommitted SQLite rows are gone (close without commit)."""
    eng.journal.db.close()


def books(tmp: Path, trade_id: str | None = None) -> dict:
    with sqlite3.connect(tmp / "j.db") as c:
        fills = c.execute("SELECT symbol, qty FROM fills" + (" WHERE trade_id=?" if trade_id else ""),
                          (trade_id,) if trade_id else ()).fetchall()
        trades = c.execute("SELECT id, status FROM trades").fetchall()
        st = c.execute("SELECT value FROM state WHERE key='intraday_open'").fetchone()
    broker = json.loads((tmp / "broker.json").read_text()) if (tmp / "broker.json").exists() else {}
    return {"journal_fills": fills, "journal_trades": trades,
            "state_open_trades": [t["id"] for t in json.loads(st[0])["trades"]] if st else None,
            "broker_positions": {k: v["qty"] for k, v in (broker.get("positions") or {}).items()},
            "broker_cash": round(float(broker.get("cash", float("nan"))), 2)}


def test8_entry_crash(bars, day):
    """Test 8a: crash after leg 1's broker fill is on disk, before the journal commits the fill/trade/state."""
    tmp = Path(tempfile.mkdtemp(prefix="h8a-"))
    a = make(tmp, bars, day)
    a.start_session(day)
    advance(a, "10:30")
    crash_on_call(a, 2)
    try:
        a._open(spread_plan(a), 1, [], view(a), {}, a.feed.now())
    except Crash:
        pass
    die(a)
    after_crash = books(tmp)
    b = make(tmp, bars, day, "10:32")
    b.start_session(day)
    blocked = b._blocked("NIFTY", view(b) if "NIFTY" in b.chain_df else MarketView("NIFTY", None, 0, "", 0, 0, "", "", None, None, [], [], {}, ""), b.feed.now())
    advance(b, "15:29")
    b.end_session()
    b.journal.commit()
    end = books(tmp)
    from quantdesk.ops.selfreview import check_session
    found = [f.key for f in check_session(b.journal, day, True)]
    crit = b.journal.events(level="CRITICAL")
    return {"after_crash": after_crash, "restart_open_trades": [t.id for t in b.open_trades], "reconcile": b.health["reconcile"],
            "blocked": blocked, "end_of_day": end, "selfreview_findings": found,
            "critical_events": crit["message"].str[:90].tolist()}


def test8_exit_crash(bars, day):
    """Test 8b: a trade opened and committed; crash after the first closing leg's broker fill, before the journal
    records the close. Then restart and let the session run to its square-off."""
    tmp = Path(tempfile.mkdtemp(prefix="h8b-"))
    a = make(tmp, bars, day)
    a.start_session(day)
    advance(a, "10:30")
    a._open(spread_plan(a), 1, [], view(a), {}, a.feed.now())
    tid = a.open_trades[0].id
    advance(a, "11:00")
    opened = books(tmp, tid)
    crash_on_call(a, 2)                                  # the 2nd closing leg dies; the 1st closing leg is on disk
    try:
        a._close(a.open_trades[0], a.feed.now(), "manual", "probe close")
    except Crash:
        pass
    die(a)
    after_crash = books(tmp, tid)
    b = make(tmp, bars, day, "11:02")
    b.start_session(day)
    restored = [t.id for t in b.open_trades]
    rec = dict(b.health["reconcile"])
    advance(b, "15:29")
    b.end_session()
    b.journal.commit()
    end = books(tmp, tid)
    return {"opened": opened, "after_crash": after_crash, "restart_open_trades": restored, "reconcile": rec,
            "end_of_day": end}


def test16_restart(bars, day, graceful: bool):
    """Test 16: mid-session restart with an open position and armed setups. graceful = the SIGTERM path
    (run_live's handler: _persist + event + commit); otherwise a hard kill right after a completed minute step."""
    tmp = Path(tempfile.mkdtemp(prefix=f"h16{'g' if graceful else 'h'}-"))
    a = make(tmp, bars, day)
    a.start_session(day)
    advance(a, "10:30")
    a._open(spread_plan(a), 1, [], view(a), {}, a.feed.now())
    advance(a, "11:30")
    before = {"open": [t.id for t in a.open_trades], "closed": [t.id for t in a.closed],
              "armed": {u: len(v) for u, v in a.armed.items()}, "chain_cached": sorted(a.chain_df),
              "trades_today": a.risk.trades_today, "day_start_equity": a.day_start_equity,
              "thoughts_rows": int(a.journal.df("SELECT COUNT(*) n FROM thoughts")["n"].iloc[0]),
              "decision_rows": int(a.journal.df("SELECT COUNT(*) n FROM decisions")["n"].iloc[0])}
    if graceful:
        a._persist()
        a.journal.event(a.feed.now(), "WARN", "session", "runner stopped: state saved")
        a.journal.commit()
        a.journal.db.close()
    else:
        die(a)
    b = make(tmp, bars, day, "11:32")
    b.start_session(day)
    after = {"open": [t.id for t in b.open_trades], "closed": [t.id for t in b.closed],
             "armed": {u: len(v) for u, v in b.armed.items()}, "chain_cached": sorted(b.chain_df),
             "trades_today": b.risk.trades_today, "day_start_equity": b.day_start_equity,
             "reconcile": dict(b.health["reconcile"]),
             "thoughts_rows": int(b.journal.df("SELECT COUNT(*) n FROM thoughts")["n"].iloc[0]),
             "decision_rows": int(b.journal.df("SELECT COUNT(*) n FROM decisions")["n"].iloc[0])}
    b.step()
    after["chain_after_one_step"] = sorted(b.chain_df)
    advance(b, "15:29")
    b.end_session()
    b.journal.commit()
    return {"before": before, "after_restart": after, "end_of_day": books(tmp)}


def test16_overnight(bars, days):
    """Test 16c: the session dies with a position open and nobody squares it off; the next trading day starts."""
    tmp = Path(tempfile.mkdtemp(prefix="h16n-"))
    d0, d1 = days[-2], days[-1]
    a = make(tmp, bars, d0)
    a.start_session(d0)
    advance(a, "10:30")
    a._open(spread_plan(a), 1, [], view(a), {}, a.feed.now())
    advance(a, "11:00")
    die(a)
    b = make(tmp, bars, d1)
    b.start_session(d1)
    warn = b.journal.events(level="WARN")
    return {"next_day_open_trades": [t.id for t in b.open_trades], "reconcile": dict(b.health["reconcile"]),
            "warn": warn["message"].str[:100].tolist()[-2:], "broker": books(tmp)["broker_positions"]}


if __name__ == "__main__" and len(sys.argv) == 1:
    bars, days = world()
    day = days[-1]
    out = {"test8a_entry_crash": test8_entry_crash(bars, day),
           "test8b_exit_crash": test8_exit_crash(bars, day),
           "test16a_graceful_restart": test16_restart(bars, day, graceful=True),
           "test16b_hard_kill_restart": test16_restart(bars, day, graceful=False),
           "test16c_overnight_orphan": test16_overnight(bars, days)}
    print(json.dumps(out, indent=1, default=str))


def test_kill_switch(bars, day):
    """H4: the file kill switch and the cancel path (close_out) on a synthetic engine and the paper broker."""
    from quantdesk.intraday.engine import close_out
    tmp = Path(tempfile.mkdtemp(prefix="h4-"))
    a = make(tmp, bars, day)
    a.start_session(day)
    advance(a, "10:30")
    a._open(spread_plan(a), 1, [], view(a), {}, a.feed.now())
    a.kill_file.parent.mkdir(parents=True, exist_ok=True)
    a.kill_file.write_text("stop")
    advance(a, "10:32")
    file_path = {"killed": a.killed, "open_after": len(a.open_trades), "broker": books(tmp)["broker_positions"],
                 "blocked": a._blocked("NIFTY", view(a), a.feed.now())}
    a.journal.commit()
    a.journal.db.close()
    b = make(tmp, bars, day, "10:34")                      # restart on the same machine: the file is still there
    b.start_session(day)
    b.step()
    restart_same_disk = {"killed_after_restart": b.killed}
    b.journal.commit(); b.journal.db.close()
    # a runner's restore: journal.sh saves runtime/intraday/** only, so runtime/KILL never reaches the next runner
    import subprocess
    saved = subprocess.run(["bash", "-c", "grep -n \"cd \\\"\\$rt/intraday\\\"\" " + str(REPO / "deploy/journal.sh")],
                           capture_output=True, text=True).stdout.strip()
    # the cancel path: a second trade, state persisted, then `live --close-out` (close_out) from a fresh process
    tmp2 = Path(tempfile.mkdtemp(prefix="h4c-"))
    c = make(tmp2, bars, day)
    c.start_session(day)
    advance(c, "10:30")
    c._open(spread_plan(c), 1, [], view(c), {}, c.feed.now())
    c._persist(); c.journal.commit(); c.journal.db.close()
    d = make(tmp2, bars, day, "10:40")
    msg = close_out(d)
    return {"file_kill": file_path, "restart_same_disk": restart_same_disk, "journal_sh_saves_only": saved,
            "kill_file_location": str(a.kill_file.relative_to(tmp)),
            "close_out": {"msg": msg[:80], "after": books(tmp2)}}


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "kill":
    bars, days = world()
    print(json.dumps(test_kill_switch(bars, days[-1]), indent=1, default=str))
