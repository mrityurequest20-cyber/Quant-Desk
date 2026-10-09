"""Phase I: what the persisted record alone can reconstruct after an interrupted entry or exit.

Read-only and isolated: every journal and broker file lives in a fresh temp dir; the market is synthetic
(phase_h_det_tests.world: ReplayFeed over simulate_sessions, model chain, paper IntradayBroker); no network.

Difference from Phase H's harness: the journal is opened exactly as production opens it,
`Journal(path, autocommit_every=1)` (intraday/cli.py:90), so every journal write is committed at once. Phase H used the
library default (200), which loses buffered rows on a crash. The crash itself is the same (phase_h_det_tests.crash_on_call:
the n-th broker call raises before it executes; earlier fills are on disk).

For each scenario the persisted files are then audited WITHOUT the engine, using only journal.db + broker.json:
  derived positions  = Σ fills.qty per symbol                     vs broker.json positions
  derived cash       = starting capital − Σ(qty·price + fees)     vs broker.json cash
  per trade          = Σ fills.qty per (trade, symbol)            vs the trade row's legs (open) or 0 (closed)
  orphan fills       = fills whose trade_id has no trade row
  crash markers      = CRITICAL events and their data

    python audit/probes/phase_i_evidence.py > out.json
"""
import json
import sqlite3
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase_h_det_tests as H  # noqa: E402
from quantdesk.config import Config, DEFAULT_CONFIG  # noqa: E402
from quantdesk.intraday.engine import IntradayEngine  # noqa: E402
from quantdesk.intraday.feeds import ReplayFeed  # noqa: E402
from quantdesk.intraday.sim import IntradayBroker  # noqa: E402
from quantdesk.journal.journal import Journal  # noqa: E402

import pandas as pd  # noqa: E402

CAPITAL = 500000.0


def make_prod(tmp: Path, bars, day, at: str | None = None) -> IntradayEngine:
    """As phase_h_det_tests.make, but with the production journal setting (autocommit_every=1)."""
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    feed = ReplayFeed(bars, day)
    if at:
        feed.clock = pd.Timestamp(f"{day} {at}", tz=H.IST)
    return IntradayEngine(cfg, feed, "model", Journal(tmp / "j.db", autocommit_every=1),
                          IntradayBroker(cfg, starting_cash=CAPITAL, state_path=tmp / "broker.json"), say=None)


def audit(tmp: Path) -> dict:
    """Reconcile from the files alone (no engine)."""
    with sqlite3.connect(f"file:{tmp / 'j.db'}?mode=ro", uri=True) as c:
        fills = c.execute("SELECT trade_id, symbol, qty, price, fees FROM fills ORDER BY id").fetchall()
        trades = {r[0]: (r[1], json.loads(r[2] or "[]")) for r in c.execute("SELECT id, status, legs FROM trades")}
        crit = [(m, json.loads(d or "{}")) for m, d in
                c.execute("SELECT message, data FROM events WHERE level='CRITICAL' ORDER BY id")]
        st = c.execute("SELECT value FROM state WHERE key='intraday_open'").fetchone()
    st = json.loads(st[0]) if st else {}
    br = json.loads((tmp / "broker.json").read_text()) if (tmp / "broker.json").exists() else {"cash": CAPITAL, "positions": {}}
    pos = defaultdict(int)
    cash = CAPITAL
    per_trade = defaultdict(lambda: defaultdict(int))
    for tid, sym, qty, px, fee in fills:
        pos[sym] += qty
        cash -= qty * px + fee
        per_trade[tid][sym] += qty
    derived = {k: v for k, v in pos.items() if v}
    broker = {k: v["qty"] for k, v in br["positions"].items()}
    trade_checks = {}
    for tid, (status, legs) in trades.items():
        want = {l["instrument"]["symbol"]: (int(l["qty"]) if status == "open" else 0) for l in legs}
        got = {s: q for s, q in per_trade.get(tid, {}).items()}
        trade_checks[tid] = {"status": status, "fills_net": got, "expected_net": want,
                             "consistent": all(got.get(s, 0) == q for s, q in want.items()) and set(got) <= set(want)}
    orphan_fills = [f for f in fills if f[0] not in trades]
    return {"fills": [(f[0][-4:], f[1], f[2]) for f in fills],
            "derived_positions": derived, "broker_positions": broker,
            "positions_match": derived == broker,
            "derived_cash": round(cash, 2), "broker_cash": round(float(br["cash"]), 2),
            "cash_match": abs(cash - float(br["cash"])) < 0.01,
            "trade_checks": trade_checks, "orphan_fill_count": len(orphan_fills),
            "state_open_trades": [t["id"][-4:] for t in st.get("trades", [])],
            "critical_events": [m[:90] for m, _ in crit],
            "critical_event_data": [d for _, d in crit][:2]}


def clean(bars, day):
    tmp = Path(tempfile.mkdtemp(prefix="i-clean-"))
    a = make_prod(tmp, bars, day)
    a.start_session(day)
    H.advance(a, "10:30")
    a._open(H.spread_plan(a), 1, [], H.view(a), {}, a.feed.now())
    H.advance(a, "15:29")
    a.end_session()
    a.journal.commit()
    return {"end": audit(tmp)}


def entry_crash(bars, day):
    tmp = Path(tempfile.mkdtemp(prefix="i-8a-"))
    a = make_prod(tmp, bars, day)
    a.start_session(day)
    H.advance(a, "10:30")
    H.crash_on_call(a, 2)
    try:
        a._open(H.spread_plan(a), 1, [], H.view(a), {}, a.feed.now())
    except H.Crash:
        pass
    H.die(a)
    after = audit(tmp)
    b = make_prod(tmp, bars, day, "10:32")
    b.start_session(day)
    H.advance(b, "15:29")
    b.end_session()
    b.journal.commit()
    return {"after_crash": after, "end": audit(tmp)}


def exit_crash(bars, day):
    tmp = Path(tempfile.mkdtemp(prefix="i-8b-"))
    a = make_prod(tmp, bars, day)
    a.start_session(day)
    H.advance(a, "10:30")
    a._open(H.spread_plan(a), 1, [], H.view(a), {}, a.feed.now())
    H.advance(a, "11:00")
    H.crash_on_call(a, 2)
    try:
        a._close(a.open_trades[0], a.feed.now(), "manual", "probe close")
    except H.Crash:
        pass
    H.die(a)
    after = audit(tmp)
    b = make_prod(tmp, bars, day, "11:02")
    b.start_session(day)
    restored = [t.id[-4:] for t in b.open_trades]
    H.advance(b, "15:29")
    b.end_session()
    b.journal.commit()
    return {"after_crash": after, "restart_open_trades": restored, "end": audit(tmp)}


def overnight(bars, days):
    tmp = Path(tempfile.mkdtemp(prefix="i-16c-"))
    d0, d1 = days[-2], days[-1]
    a = make_prod(tmp, bars, d0)
    a.start_session(d0)
    H.advance(a, "10:30")
    a._open(H.spread_plan(a), 1, [], H.view(a), {}, a.feed.now())
    H.advance(a, "11:00")
    H.die(a)
    b = make_prod(tmp, bars, d1)
    b.start_session(d1)
    b.journal.commit()
    return {"next_day_start": audit(tmp)}


if __name__ == "__main__":
    bars, days = H.world()
    day = days[-1]
    print(json.dumps({"clean_round_trip": clean(bars, day), "entry_crash_8a_prod_journal": entry_crash(bars, day),
                      "exit_crash_8b_prod_journal": exit_crash(bars, day),
                      "overnight_16c_prod_journal": overnight(bars, days)}, indent=1, default=str))
