"""Audit K-10 (B-06/E-03): a price the two brokers dispute (the relay's `x`, e.g. USDINR 95.005 against 93) was filled, marked and voted on as if it were true.
Now: no entry, no AUTO pricing, mark or spot vote on it, and no mark, stop or target judged on it (the last agreed quote stands while it is fresh, then there is no
price, the stale path every brake already treats as the worst); an exit (the kill switch, a brake, the owner's) still fills on it, and its record says so.
Also the #282 review follow-ups that ship with it."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess

import pytest

from quantdesk.data import tape as T
from quantdesk.paper import auto as V1
from quantdesk.paper import auto2 as A2
from tests.test_k04_record_guard import ROOT, needs_node, record
from tests.test_paper_runner import MON, NAME, cfg, order, rn, run, snap  # noqa: F401 - cfg and rn are fixtures

X = dict(bid=99.0, ask=100.0, bid_qty=5000, ask_qty=5000, ltp=99.5, age_s=2.0, x=40.0)       # disputed by 40%


def test_a_disputed_price_is_no_quote_for_an_entry_and_a_quote_marked_disputed_for_an_exit():
    now = MON.astimezone(dt.timezone.utc)
    assert R().quote_from(snap(**{NAME: X}), NAME, now) is None
    q = R().quote_from(snap(**{NAME: X}), NAME, now, disputed_ok=True)
    assert q is not None and q.disputed == 40.0 and q.bid == 99.0
    assert R().quote_from(snap(), NAME, now).disputed is None                                       # an agreed price carries nothing
    for bad in (0, -3, "junk", None):                                                               # no dispute said: an ordinary quote
        assert R().quote_from(snap(**{NAME: {**X, "x": bad}}), NAME, now) is not None, bad


def R():
    from quantdesk.paper import runner
    return runner.Runner


def test_an_owners_buy_on_a_disputed_price_is_never_filled(rn):
    res = run(rn, [order()], s=snap(**{NAME: X}))["results"][0]
    assert res["status"] == "refused" and "dispute this price by 40%" in res["reasons"][0] and not rn.account.positions and not rn.account.ledger


def test_an_owners_sell_on_a_disputed_price_fills_at_its_worse_side_and_says_so(rn):
    assert run(rn, [order()])["results"][0]["status"] == "filled"
    t1 = MON + dt.timedelta(seconds=10)
    run(rn, [], s=snap(t1), now=t1)                                                                 # an agreed bid of 99 is seen
    t2 = MON + dt.timedelta(seconds=20)
    high = {**X, "bid": 150.0, "ask": 151.0}                                                         # a bogus print 50% over the market
    res = run(rn, [order("ord-0002", now=t2, side="sell", lots="all", strategy=None, thesis=None)], s=snap(t2, **{NAME: high}), now=t2)["results"][0]
    assert res["status"] == "filled" and NAME not in rn.account.positions                         # an exit is never trapped by a dispute
    assert res["fill"]["price"] <= 99.0                                                             # filled at the agreed 99, never at the bogus 150: no fake profit
    assert "dispute by 40%: filled at its worse side" in rn.account.ledger[-1]["thesis"]


def test_with_no_agreed_price_known_an_exit_fills_at_the_disputed_price_moved_against_the_account(rn):
    run(rn, [order()])
    rn._agreed.clear()                                                                              # a restart: no agreed price known
    res = run(rn, [order("ord-0002", side="sell", lots="all", strategy=None, thesis=None)], s=snap(**{NAME: {**X, "x": 10.0}}))["results"][0]
    assert res["status"] == "filled" and res["fill"]["price"] <= 99.0 * 0.9 + 1e-9


def test_the_kill_switch_flattens_on_a_disputed_price_and_the_record_says_so(rn, tmp_path):
    run(rn, [order()])
    rep = run(rn, [], s=snap(**{NAME: X}), kill=True)
    assert rep["forced"] and rep["forced"][0]["action"] == "flatten" and not rn.account.positions
    assert rn.account.ledger[-1]["kind"] == "sell" and "dispute" in rn.account.ledger[-1]["thesis"] and rn.account.verify_ledger()


def test_a_disputed_price_is_never_a_mark_the_last_agreed_one_stands_while_fresh_then_there_is_none(rn, cfg, tmp_path):
    run(rn, [order()])
    t0 = MON.astimezone(dt.timezone.utc)
    assert rn.marks(snap(), t0)[NAME] == 99.0
    crash = {**X, "bid": 1.0, "ask": 2.0}                                                           # a bogus print 99% under the market, flagged
    t1 = t0 + dt.timedelta(minutes=5)
    assert rn.marks(snap(MON + dt.timedelta(minutes=5), **{NAME: crash}), t1)[NAME] == 99.0        # no news: the last agreed bid (its quote 5 min old, within 10)
    rep = run(rn, [], s=snap(MON + dt.timedelta(minutes=5), **{NAME: crash}), now=MON + dt.timedelta(minutes=5))
    assert not rep["forced"] and NAME in rn.account.positions                                       # the bogus print trips no brake and sells nothing
    t2 = t0 + dt.timedelta(minutes=11)
    assert NAME not in rn.marks(snap(MON + dt.timedelta(minutes=11), **{NAME: crash}), t2)          # past the mark's age: no price, the gate's worst-case path (K-03)
    from quantdesk.paper import runner as RR
    from quantdesk.paper.account import Account
    from quantdesk.paper.risk import KillSwitch, RiskGate
    fresh = RR.Runner(cfg, Account(500_000), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "K2")), kill_file=tmp_path / "K2")
    run(fresh, [order()])
    fresh._agreed.clear()                                                                           # a restart: no agreed price known
    assert NAME not in fresh.marks(snap(**{NAME: X}), t0)


def test_auto_takes_no_spot_and_prices_nothing_on_a_disputed_price():
    s = {"quotes": {"USDINR": {"ltp": 95.005, "age_s": 1.0, "x": 2.1}}}
    assert V1._spot(s, "USDINR") is None                                                            # no false momentum vote, no blown-up volatility
    assert V1._spot({"quotes": {"USDINR": {"ltp": 93.0, "age_s": 1.0}}}, "USDINR") == 93.0
    q = {"bid": 99.0, "ask": 100.0, "age_s": 1.0}
    assert A2._book(q) == (99.0, 100.0)
    assert A2._book({**q, "x": 5.0}) is None and A2._book({**q, "x": 0}) == (99.0, 100.0)         # never priced, entered or marked on


def test_auto_v2_never_marks_a_trade_on_a_disputed_price(cfg, tmp_path):
    from tests.test_paper_auto2 import desk
    ap = desk(cfg, tmp_path)[1]
    legs = [{"name": "L", "side": 1, "px": 100.0}, {"name": "S", "side": -1, "px": 50.0}]
    clean = {"quotes": {"L": {"bid": 99.0, "ask": 100.0, "age_s": 1.0}, "S": {"bid": 49.0, "ask": 50.0, "age_s": 1.0}}}
    assert ap.mark(clean, legs) == pytest.approx((99.0 - 100.0) - (50.0 - 50.0))
    bad = {"quotes": {**clean["quotes"], "L": {**clean["quotes"]["L"], "x": 10.0}, "S": {**clean["quotes"]["S"], "x": 10.0}}}
    assert ap.mark(bad, legs) is None and ap.mark({"quotes": {**clean["quotes"], "S": bad["quotes"]["S"]}}, legs) is None   # one disputed leg: the trade waits


# ---- the #282 review follow-ups ------------------------------------------------------------------------------------------------------
def test_a_full_tape_still_tries_the_disk_so_a_recovered_disk_is_used_again_and_a_failing_one_ever_less_often(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "MAX_PENDING", 50)
    tape = T.Tape(tmp_path / "t", "f", flush_rows=10)
    real = T.gzip.open
    tries = {"n": 0}

    def failing(path, *a, **k):
        tries["n"] += 1
        fh = real(path, *a, **k)
        fh.close()
        raise OSError("disk full")
    monkeypatch.setattr(T.gzip, "open", failing)
    for i in range(60):
        tape.record(f"N{i}", {"ltp": i})
    assert len(tape.rows) == 50 and tape.dropped == 10 and tape.files == 0
    n0 = tries["n"]
    for i in range(10 * 2 ** 6):
        tape.record(f"F{i}", {"ltp": i})
    assert tries["n"] - n0 <= 7                                                                     # 640 rows dropped on a disk still failing: tried at 30, 70, 150, 310, 630 dropped
    monkeypatch.setattr(T.gzip, "open", real)                                                       # the disk recovers while the tape is full
    while tape.files == 0 and tape.dropped < 5000:
        tape.record("M", {"ltp": 1})
    assert tape.files == 1 and tape.rows == []                                                      # was: never written again, every later row dropped
    tape.record("after", {"ltp": 1})
    assert tape.rows and tape.rows[-1][1] == "after"
    assert tape._full_gap == 10                                                                     # a working disk: back to the first gap


def test_a_rerun_attempt_keeps_the_runs_reset_id(cfg, tmp_path, monkeypatch):
    """A re-run of failed jobs is the same run with a new attempt number: the id stays the run's, so the re-run never copies the reset data over the kept copy."""
    from tests.test_k04_record_guard import AutoStub, S
    from tests.test_paper_session import IST, Clock, FakeRelay
    clk = Clock()
    monkeypatch.setattr(S.time, "monotonic", lambda: (clk.t - Clock().t).total_seconds())
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    auto = AutoStub("failed")
    auto.reset_id = None
    S.run(cfg, FakeRelay(clk), tmp_path / "l" / "a.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk, sleep=clk.sleep,
          say=lambda *a: None, new_account=True, auto=auto)
    assert auto.reset_id == "12345"


JS_STORE = """import { PaperBook } from './paper.js';
import { readFileSync } from 'fs';
const C = JSON.parse(readFileSync('cases.json', 'utf8'));
const store = new Map();
let failPut = false;
const state = { storage: {
  get: async (k) => { if (Array.isArray(k)) { const m = new Map(); for (const x of k) if (store.has(x)) m.set(x, store.get(x)); return m; } return store.get(k); },
  put: async (k, v) => { if (failPut) throw new Error("storage down"); if (typeof k === "object") for (const [a, b] of Object.entries(k)) store.set(a, b); else store.set(k, v); },
  delete: async (k) => { for (const x of (Array.isArray(k) ? k : [k])) store.delete(x); } } };
const b = new PaperBook(state);
"""


@needs_node
def test_a_kept_book_is_never_mixed_with_an_older_copy_and_a_failed_copy_loses_nothing(tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/paper.js", tmp_path / "paper.js")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "cases.json").write_text(json.dumps({"r1": record(1)}))
    (tmp_path / "t.mjs").write_text(JS_STORE + """const out = {};
store.set("paper:shadowprevmeta", { n: 3 }); for (const i of [0, 1, 2]) store.set("paper:shadowprev:" + i, "old" + i);   // an older kept copy in three pieces
store.set("paper:shadowmeta", { n: 1 }); store.set("paper:shadow:0", "new0");                                         // the book now: one piece
out.kept = await b.keepPrev("shadow", "run-9");
out.whole = JSON.stringify(store.get("paper:shadowprevmeta")) === '{"n":1}' && store.get("paper:shadowprev:0") === "new0"
  && !store.has("paper:shadowprev:1") && !store.has("paper:shadowprev:2");
store.clear();
store.set("paper:shadowprevmeta", { n: 2 }); store.set("paper:shadowprev:0", "a"); store.set("paper:shadowprev:1", "b");
store.set("paper:shadowmeta", { n: 1 }); store.set("paper:shadow:0", "new0");
failPut = true;
try { await b.keepPrev("shadow", "run-10"); out.threw = false; } catch (e) { out.threw = true; }
out.old_intact = JSON.stringify(store.get("paper:shadowprevmeta")) === '{"n":2}' && store.get("paper:shadowprev:0") === "a" && store.get("paper:shadowprev:1") === "b";
console.log(JSON.stringify(out));""")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    assert json.loads(r.stdout.strip().splitlines()[-1]) == {"kept": True, "whole": True, "threw": True, "old_intact": True}


def test_a_future_is_never_opened_on_a_disputed_price_but_is_always_closed_on_one(cfg, tmp_path):
    from tests import test_paper_futures as F
    from quantdesk.paper import runner as RR
    from quantdesk.paper.account import Account
    from quantdesk.paper.risk import KillSwitch, RiskGate
    rf = RR.Runner(cfg, Account(F.CAP), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL")), kill_file=tmp_path / "KILL")
    disputed = lambda t: F.board(t, **{F.USD: dict(bid=95.005, ask=95.0075, bid_qty=50000, ask_qty=50000, ltp=95.005, age_s=2.0, s="cds", e="2026-12-29", x=2.1)})  # noqa: E731
    o = F.order(symbol=F.USD, stop=84.40, thesis="RBI absent, importer demand into month end")
    r = F.res(F.run(rf, [o], disputed(F.MON)))
    assert r["status"] == "refused" and "dispute this price by 2.1%" in r["reasons"][0] and F.USD not in rf.account.positions
    assert F.res(F.run(rf, [{**o, "id": "fut-0003"}]), "fut-0003")["status"] == "filled"
    t = F.MON + dt.timedelta(minutes=1)
    r = F.res(F.run(rf, [F.order(oid="fut-0002", now=t, symbol=F.USD, side="sell", lots="all")], disputed(t), t), "fut-0002")
    assert r["status"] == "filled" and F.USD not in rf.account.positions and "dispute by 2.1%" in rf.account.ledger[-1]["thesis"]
    assert r["fill"]["price"] <= 84.5                                                               # the long sold at the agreed bid, never the bogus 95.005
    o = F.order(oid="fut-0004", now=t, symbol=F.USD, side="short", stop=84.60, thesis="RBI absent, exporter supply into month end")
    assert F.res(F.run(rf, [o], F.board(t), t), "fut-0004")["status"] == "filled"
    t1 = t + dt.timedelta(seconds=30)
    rep = F.run(rf, [], disputed(t1), t1)                                                          # the bogus 95.005 is far through the short's stop at 84.60
    assert not rep["forced"] and F.USD in rf.account.positions                                     # never stopped out on it (the audit's fake loss)
    t3 = t + dt.timedelta(minutes=3)
    rep = F.run(rf, [], disputed(t3), t3)                                                           # still disputed past two minutes: no price, so no stop either,
    assert not rep["forced"] and F.USD not in rf.marks(disputed(t3), t3)                           # and the book counts it at its stress loss (the stale path, K-03)
    t2 = t3 + dt.timedelta(seconds=1)
    r = F.res(F.run(rf, [F.order(oid="fut-0005", now=t2, symbol=F.USD, side="sell", lots="all")], disputed(t2), t2), "fut-0005")   # the owner's close fills on it
    assert r["status"] == "filled" and r["fill"]["kind"] == "btc" and "dispute by 2.1%" in rf.account.ledger[-1]["thesis"]


def test_a_package_with_one_disputed_leg_opens_nothing_and_says_which(cfg, tmp_path):
    import dataclasses
    from tests import test_paper_shorts as P
    from quantdesk.paper import runner as RR
    from quantdesk.paper.account import Account
    from quantdesk.paper.risk import KillSwitch, RiskGate
    gate = RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL"))
    gate.limits = dataclasses.replace(gate.limits, allow_short_legs=True)
    rp = RR.Runner(cfg, Account(500_000), gate=gate, kill_file=tmp_path / "KILL")
    s = P.snap(quotes={P.opt(24400).symbol: dict(bid=30.0, ask=32.0, bid_qty=5000, ask_qty=5000, ltp=31, age_s=2.0, x=12.5)})
    res = P.go(rp, [P.package()], s)["results"][0]
    assert res["status"] == "refused" and P.opt(24400).symbol in res["reasons"][0] and "dispute" in res["reasons"][0] and not rp.account.ledger
    assert P.go(rp, [P.package("pkg-00002")])["results"][0]["status"] == "filled"


def test_a_future_squared_off_on_a_disputed_price_never_books_the_bogus_gain(cfg, tmp_path):
    """The review's probe: a long USDINR future squared off on a disputed 95.005 booked +10,502 on one lot. Now it fills at the agreed bid."""
    from tests import test_paper_futures as F
    from quantdesk.paper import runner as RR
    from quantdesk.paper.account import Account
    from quantdesk.paper.risk import KillSwitch, RiskGate
    rf = RR.Runner(cfg, Account(F.CAP), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL")), kill_file=tmp_path / "KILL")
    t0 = F.MON.replace(hour=16, minute=0)
    assert F.res(F.run(rf, [F.order(now=t0, symbol=F.USD, stop=84.40, thesis="RBI absent, importer demand into month end")], F.board(t0), t0))["status"] == "filled"
    t1 = F.MON.replace(hour=16, minute=54, second=50)
    F.run(rf, [], F.board(t1), t1)                                                                  # agreed 84.5 seen
    t2 = F.MON.replace(hour=16, minute=55, second=5)
    rep = F.run(rf, [], F.board(t2, **{F.USD: dict(bid=95.005, ask=95.0075, bid_qty=50000, ask_qty=50000, ltp=95.005, age_s=2.0, s="cds", e="2026-12-29", x=12.4)}), t2)
    assert F.USD not in rf.account.positions and any(f["action"] == "futures" for f in rep["forced"])    # the square-off still happens
    row = rf.account.ledger[-1]
    assert row["price"] <= 84.5 and "dispute by 12.4%" in row["thesis"]


def test_a_future_squared_off_on_an_older_disputed_quote_still_fills_at_the_worse_side(cfg, tmp_path):
    """The square-off's fallback (a quote older than two minutes, up to ten) is filled on the worse side too."""
    from tests import test_paper_futures as F
    from quantdesk.paper import runner as RR
    from quantdesk.paper.account import Account
    from quantdesk.paper.risk import KillSwitch, RiskGate
    rf = RR.Runner(cfg, Account(F.CAP), gate=RiskGate(cfg, kill=KillSwitch(tmp_path / "KILL")), kill_file=tmp_path / "KILL")
    t0 = F.MON.replace(hour=16, minute=50)
    F.run(rf, [F.order(now=F.MON, symbol=F.USD, stop=84.40, thesis="RBI absent, importer demand into month end")], F.board(F.MON), F.MON)
    F.run(rf, [], F.board(t0), t0)                                                                  # agreed 84.5 seen at 16:50
    t2 = F.MON.replace(hour=16, minute=55, second=5)
    old = dict(bid=95.005, ask=95.0075, bid_qty=50000, ask_qty=50000, ltp=95.005, age_s=200.0, s="cds", e="2026-12-29", x=12.4)   # 200 s old: only the fallback takes it
    F.run(rf, [], F.board(t2, **{F.USD: old}), t2)
    row = rf.account.ledger[-1]
    assert F.USD not in rf.account.positions and row["price"] <= 84.5 and "dispute by 12.4%" in row["thesis"]


def test_auto_v1_never_stops_trails_or_peaks_on_a_disputed_price(cfg, tmp_path):
    from tests import test_paper_auto as PA
    rn1, ap, cal, t = PA.open_one(cfg, tmp_path)
    sym = next(iter(rn1.account.positions))
    avg = rn1.account.positions[sym].avg_price
    t1 = t + dt.timedelta(minutes=1)
    s = PA.reprice(PA.board(t1, cb=1000, ca=1000, pb=1000, pa=1000), sym, round(avg * 0.3, 2))
    s["quotes"][sym]["x"] = 70.0                                                                    # the review's probe: a flagged print 70% under
    mine, _ = PA.tick(rn1, ap, cal, s, t1)
    assert [o for o in mine if o["side"] == "sell"] == [] and sym in rn1.account.positions          # was: a stop-loss sell filled at the bogus price
    ap.drain_events()
    t2 = t1 + dt.timedelta(minutes=1)
    s = PA.reprice(PA.board(t2, cb=1000, ca=1000, pb=1000, pa=1000), sym, round(avg * 3.5, 2))
    s["quotes"][sym]["x"] = 70.0
    PA.tick(rn1, ap, cal, s, t2)
    assert not [e for e in ap.drain_events() if e.get("kind") == "auto_peak"]                      # was: a 3.5x peak written to the record


def test_auto_v2_closes_a_day_trade_on_time_even_when_a_leg_is_disputed(cfg, tmp_path):
    from tests.test_paper_auto2 import desk
    ap = desk(cfg, tmp_path)[1]
    snap_ = {"quotes": {"L": {"bid": 99.0, "ask": 100.0, "age_s": 1.0, "x": 9.0}}}
    assert A2.AutoPilotV2._disputed(snap_, [{"name": "L"}]) is True
    assert A2.AutoPilotV2._disputed({"quotes": {"L": {"bid": 99.0, "ask": 100.0, "age_s": 1.0}}}, [{"name": "L"}]) is False
    day = next(s for s in A2.BY_SID.values() if s.hold == "day")
    opened = dt.datetime(2026, 11, 9, 10, 0, tzinfo=A2.IST)
    late = opened.replace(hour=15, minute=25)
    assert ap._exit_why(day, 0.0, float("inf"), opened, late, dt.date(2026, 11, 12), "NIFTY")      # at 0R the time exit still fires
    assert ap._exit_why(day, 0.0, float("inf"), opened, opened.replace(hour=11), dt.date(2026, 11, 12), "NIFTY") is None   # and nothing else does


@pytest.mark.parametrize("how", ["kill", "owner", "expiry", "long dispute"])
def test_a_dispute_of_100_percent_or_more_never_traps_a_long(rn, how):
    """Re-review: with no agreed price, a bid moved by x >= 100% became 0 and every exit was refused. The other broker can then only be above: the shown bid stands."""
    exp = "NIFTY09NOV26" + "24500CE" if how == "expiry" else NAME
    big = {**X, "bid": 40.0, "ask": 41.0, "x": 150.0}
    good = dict(bid=99.0, ask=100.0, bid_qty=5000, ask_qty=5000, ltp=99.5, age_s=2.0)
    assert run(rn, [order(symbol=exp)], s=snap(**{exp: good}))["results"][0]["status"] == "filled"
    if how != "long dispute":
        rn._agreed.clear()                                                                          # a restart: no agreed price known
    t = MON.replace(hour=15, minute=21) if how == "expiry" else MON + dt.timedelta(minutes=13 if how == "long dispute" else 1)
    s = snap(t, **{exp: big})
    if how == "owner":
        res = run(rn, [order("ord-0002", now=t, side="sell", lots="all", strategy=None, thesis=None, symbol=exp)], s=s, now=t)["results"][0]
        assert res["status"] == "filled"
    else:
        run(rn, [], s=s, now=t, kill=how in ("kill", "long dispute"))
    assert exp not in rn.account.positions and rn.account.ledger[-1]["price"] <= 40.0 and "dispute by 150%" in rn.account.ledger[-1]["thesis"]
