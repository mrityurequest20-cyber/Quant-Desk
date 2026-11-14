"""Open shadow trades outlive a runner job (14 Nov 2026).

The paper desk runs as chained jobs with handovers (paper-desk.yml: 11:50, 17:40, 23:30 IST and the end of the day). A shadow trade still open at a handover was lost and
never scored, so a strategy held overnight could never be held overnight in shadow, and every record was built only from trades that resolved inside one job; under
PLAN_ONLY the overnight strategies are the ones that trade paper money. What is pinned: the open shadow book is kept on the relay (the runner's key only, in pieces) and read
back by the next job, every field checked; a carried trade is closed and scored by its own exits; a day trade from an earlier session, a trade past its expiry, an unknown
strategy or instrument and anything malformed is dropped, not scored, and counted; a book too large keeps its longest-held trades and counts the rest."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper import convex as CX
from tests.test_paper_auto import T0, board
from tests.test_paper_auto2 import FakeRelay, calm, cycle, desk

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


class Relay(FakeRelay):
    def __init__(self, lab=None, shadow=None):
        super().__init__(lab)
        self.shadow, self.shadow_puts = shadow, 0

    def get_shadow(self):
        return {"shadow": self.shadow}

    def put_shadow(self, text):
        self.shadow, self.shadow_puts = text, self.shadow_puts + 1
        return {"saved": True}


@pytest.fixture()
def cfg():
    from quantdesk.config import Config
    return Config.load(ROOT / "config" / "quantdesk.yaml")


def opened(cfg, tmp_path):
    rn, ap = desk(cfg, tmp_path)
    t = calm(rn, ap, minutes=6)
    assert ap.shadow, "the quiet tape opens shadow trades"
    return rn, ap, t


def test_the_open_shadow_book_is_kept_and_read_back_whole(cfg, tmp_path):
    rn, ap, t = opened(cfg, tmp_path)
    relay = Relay()
    assert ap.save(relay, 1000.0) and relay.shadow_puts == 1
    assert not ap.save_shadow(relay, 1060.0)                                                  # nothing changed: nothing sent
    ap2 = desk(cfg, tmp_path)[1]
    msg = ap2.load(relay, now=t + dt.timedelta(minutes=1))
    assert f"{len(ap.shadow)} open shadow trades carried over" in msg and set(ap2.shadow) == set(ap.shadow)
    for k, sh in ap.shadow.items():
        got = ap2.shadow[k]
        assert got["s"] is sh["s"] and got["exp"] == sh["exp"] and got["opened"] == sh["opened"]
        assert got["risk"] == pytest.approx(sh["risk"], rel=1e-5) and got["fees"] == pytest.approx(sh["fees"], abs=1e-4)
        assert [(l["name"], l["side"]) for l in got["legs"]] == [(l["name"], l["side"]) for l in sh["legs"]]
        assert [l["px"] for l in got["legs"]] == pytest.approx([l["px"] for l in sh["legs"]], abs=1e-4)
        assert (got["best_r"] == sh["best_r"]) or got["best_r"] == pytest.approx(sh["best_r"], abs=1e-4)
    assert ap2.summary()["shadow_carry"]["restored"] == len(ap.shadow)


def test_a_carried_trade_is_closed_and_scored_by_its_own_exits(cfg, tmp_path):
    rn, ap, t = opened(cfg, tmp_path)
    relay = Relay()
    ap.save(relay, 1000.0, force=True)
    rn2, ap2 = desk(cfg, tmp_path)                                                           # the next job
    ap2.load(relay, now=t + dt.timedelta(minutes=2))
    n0 = sum(v[0] for v in ap2.lab.stats.values())
    late = dt.datetime.combine(T0.date(), dt.time(15, 20), tzinfo=A2.IST)
    cycle(rn2, ap2, board(late), late)
    scored = sum(v[0] for v in ap2.lab.stats.values()) - n0
    assert scored > 0 and ap2.shadow_dirty                                                    # without the carry, the next job had nothing to close


def test_stale_expired_unknown_and_malformed_trades_are_dropped_and_counted(cfg, tmp_path):
    rn, ap, t = opened(cfg, tmp_path)
    text, _ = ap.shadow_json()
    rows = A2.Lab.unpack(text)["open"]
    day = next(r for r in rows if A2.BY_SID[r[0]].hold == "day")
    bad = [day,
           [*day[:7], "2020-01-02", *day[8:]],                                                  # past its expiry
           ["NOPE.x.y.z", *day[1:]], [day[0], "NOTANUNDERLYING", *day[2:]],
           [day[0], day[1], [["nifty bad name", 1, 10.0]], *day[3:]], [day[0], day[1], [[day[2][0][0], True, 10.0]], *day[3:]],
           [*day[:3], -1.0, *day[4:]], [*day[:3], "x", *day[4:]], [*day[:6], "2026-11-09T10:00:00", *day[7:]],
           "junk", [1, 2], [*day, {"peak": 1}]]
    ap2 = desk(cfg, tmp_path)[1]
    io = ap2.restore_shadow(json.dumps({"v": 1, "open": bad}), t + dt.timedelta(minutes=1))
    assert io["restored"] == 1 and list(ap2.shadow) == [(day[0], day[1])]
    assert io["dropped"] == {"past its expiry": 1, "unknown strategy or instrument": 2, "malformed": 8}
    ap3 = desk(cfg, tmp_path)[1]                                                            # the next morning: yesterday's day trade is not carried into today
    io = ap3.restore_shadow(json.dumps({"v": 1, "open": [day]}), t + dt.timedelta(days=1))
    assert io["restored"] == 0 and io["dropped"] == {"a day trade from an earlier session": 1}
    for junk in (None, "", "not json", json.dumps({"v": 1, "open": "x"}), json.dumps([1])):     # whatever comes back, the book starts empty, the desk runs
        ap4 = desk(cfg, tmp_path)[1]
        try:
            ap4.restore_shadow(junk, t)
        except ValueError:
            pass
        assert ap4.shadow == {}
    ap5 = desk(cfg, tmp_path)[1]
    assert "no open shadow trades could be read" in ap5._load_shadow(Relay(shadow="{broken"), t)


def test_an_overnight_and_a_convex_trade_carry_their_state(cfg, tmp_path):
    rn, ap, t = opened(cfg, tmp_path)
    over = next(s for s in A2.CATALOGUE if s.hold == "overnight" and s.struct in A2.STRUCTURES)
    cx = A2.CX_CATALOGUE[0]
    some = next(iter(ap.shadow.values()))
    ap.shadow[(over.sid, "NIFTY")] = {**some, "s": over, "spot0": 24000.0, "sd0": 0.011}
    lad = CX.ShadowLadder()
    lad.step("rung1", 1.2)
    ap.shadow[(cx.sid, "NIFTY")] = {**some, "s": cx, "best_r": float("inf"), "peak": 1.7, "lad": lad, "event_at": "2026-11-12T14:30:00+05:30"}
    text, left = ap.shadow_json()
    assert left == 0
    ap2 = desk(cfg, tmp_path)[1]
    ap2.restore_shadow(text, t + dt.timedelta(days=1))                                       # the next session: an overnight trade carries, a day trade does not
    o = ap2.shadow[(over.sid, "NIFTY")]
    assert o["spot0"] == 24000.0 and o["sd0"] == 0.011
    c = ap2.shadow[(cx.sid, "NIFTY")]
    assert c["peak"] == 1.7 and c["lad"].done1 and not c["lad"].done2 and c["lad"].left == pytest.approx(2 / 3) and c["lad"].banked == pytest.approx(0.4)
    assert c["event_at"] == "2026-11-12T14:30:00+05:30" and c["best_r"] == float("inf")
    assert all(ap2.shadow[k]["s"].hold != "day" for k in ap2.shadow)


def test_a_book_too_large_keeps_its_longest_held_trades(cfg, tmp_path, monkeypatch):
    rn, ap, t = opened(cfg, tmp_path)
    full, _ = ap.shadow_json()
    monkeypatch.setattr(A2, "SHADOW_MAX_CHARS", int(len(full) * 0.7))
    stamp = 1_800_000_000_000
    monkeypatch.setattr(ap, "next_seq", lambda: stamp)                                       # the stamp the next save will carry
    text, left = ap.shadow_json(stamp)
    assert left >= 1 and len(text) <= A2.SHADOW_MAX_CHARS
    kept = A2.Lab.unpack(text)["open"]
    oldest = sorted(ap.shadow.items(), key=lambda kv: kv[1]["opened"])[:len(kept)]
    assert [(r[0], r[1]) for r in kept] == [k for k, _ in oldest]
    relay = Relay()
    ap.save_shadow(relay, 1000.0, force=True)
    assert ap.summary()["shadow_carry"]["left_out"] == left


def test_the_book_is_saved_at_most_every_two_minutes_and_at_the_end(cfg, tmp_path):
    rn, ap, t = opened(cfg, tmp_path)
    relay = Relay()
    assert ap.save_shadow(relay, 1000.0)
    ap.shadow_dirty = True
    assert not ap.save_shadow(relay, 1100.0) and ap.save_shadow(relay, 1120.0)
    ap.shadow_dirty = True
    assert ap.save(relay, 1121.0, force=True) and relay.shadow_puts == 3                    # the session's last save (force) keeps it whatever the clock
    ap.shadow_dirty = True
    assert not ap.save_shadow(FakeRelay(), 2000.0, force=True)                               # a relay without the route: nothing, no error


class FailingShadow(Relay):
    def put_shadow(self, text):
        raise OSError("the relay is down")


def test_a_trade_is_never_scored_twice_when_the_book_could_not_be_kept(cfg, tmp_path):
    """Risk review, 14 Nov 2026: the record was saved on its own clock, so a record that had scored a trade could sit beside an older book still holding it open, and
    the next job scored it again."""
    rn, ap, t = opened(cfg, tmp_path)
    relay = Relay()
    ap.save(relay, 1000.0, force=True)                                                       # the book with every trade open, and the record
    late = dt.datetime.combine(T0.date(), dt.time(15, 20), tzinfo=A2.IST)
    cycle(rn, ap, board(late), late)                                                         # the day trades close and are scored
    closed = {k for k in json_keys(relay.shadow)} - set(ap.shadow)
    assert closed and ap.lab.dirty and ap.shadow_dirty
    down = FailingShadow(relay.lab, relay.shadow)
    assert not ap.save(down, 2000.0, force=True)                                             # the book cannot be kept: the record waits too
    assert down.lab == relay.lab and ap.lab.dirty and ap.shadow_dirty
    nxt = desk(cfg, tmp_path)[1]
    nxt.load(down, now=late)                                                                 # what the next job would see: the old book with the old record
    before = A2.Lab(json.loads(relay.lab).get("stats"))
    assert all(nxt.lab.stats.get(sid, [0])[0] == before.stats.get(sid, [0])[0] for sid, _ in closed)   # carried open, and not yet scored: once, not twice
    assert ap.save(relay, 2001.0, force=True) and relay.shadow_puts == 2                     # the relay back: the book first, then the record
    assert json_keys(relay.shadow) == set(ap.shadow)


def json_keys(text):
    return {(r[0], r[1]) for r in A2.Lab.unpack(text)["open"]}


def test_the_record_due_first_takes_the_book_with_it(cfg, tmp_path):
    rn, ap, t = opened(cfg, tmp_path)
    relay = Relay()
    ap.save(relay, 1000.0, force=True)
    ap.shadow_saved_at = 1100.0                                                              # the book saved more recently than the record
    ap.shadow_dirty, ap.lab.dirty = True, True
    assert ap.save(relay, 1125.0) and relay.shadow_puts == 2 and not ap.shadow_dirty and not ap.lab.dirty


class NoRoute(Relay):
    def put_shadow(self, text):
        from quantdesk.paperlink.relay import RelayError
        raise RelayError("POST /paper/shadow: HTTP 404")


def test_a_relay_without_the_route_still_keeps_the_record(cfg, tmp_path):
    """Before the Worker with /paper/shadow is deployed, the relay answers 404: it keeps no book, so nothing can be read back stale, and the record saves as before."""
    rn, ap, t = opened(cfg, tmp_path)
    relay = NoRoute()
    assert ap.save(relay, 1000.0, force=True) and relay.puts == 1 and not ap.lab.dirty and not ap.shadow_route
    late = dt.datetime.combine(T0.date(), dt.time(15, 20), tzinfo=A2.IST)
    cycle(rn, ap, board(late), late)
    assert ap.save(relay, 1200.0) and relay.puts == 2                                        # still saving, every two minutes as before
    ok = Relay(relay.lab)
    ap.shadow_dirty = True
    assert ap.save_shadow(ok, 1400.0) and ap.shadow_route                                     # the route deployed: the book is kept again, and the record waits for it again


def test_a_book_older_than_the_record_is_never_read_back(cfg, tmp_path):
    """Risk re-review, 14 Nov 2026: a Worker rolled back answers 404 but its storage still holds the last book; the record then saved with trades scored that the old
    book still holds open, and a redeploy would have carried them again. Each book is stamped; the record names the last stamp before it; an older book is dropped."""
    rn, ap, t = opened(cfg, tmp_path)
    relay = Relay()
    ap.save(relay, 1000.0, force=True)
    stored = relay.shadow                                                                    # the book a rolled-back Worker keeps in storage
    late = dt.datetime.combine(T0.date(), dt.time(15, 20), tzinfo=A2.IST)
    cycle(rn, ap, board(late), late)                                                         # trades close and are scored
    gone = NoRoute(relay.lab)
    assert ap.save(gone, 2000.0, force=True) and gone.lab != relay.lab                       # the route gone: the record saves, stamped past every book
    back = Relay(gone.lab, stored)                                                           # the route redeployed: the old book is still there
    nxt = desk(cfg, tmp_path)[1]
    msg = nxt.load(back, now=late)
    assert nxt.shadow == {} and nxt.shadow_io["dropped"] == {"older than the record": len(A2.Lab.unpack(stored)["open"])} and "dropped" in msg
    assert nxt.shadow_seq >= nxt.lab_shadow_seq > 0
    fresh = desk(cfg, tmp_path)[1]                                                           # the normal order: book then record, both read back
    r2 = Relay()
    ap.shadow_dirty = ap.lab.dirty = True
    ap.save(r2, 3000.0, force=True)
    fresh.load(r2, now=late)
    assert set(fresh.shadow) == set(ap.shadow) and "older than the record" not in fresh.shadow_io["dropped"]
    held = desk(cfg, tmp_path)[1]
    held.shadow, held.shadow_dirty, held.lab.dirty = dict(ap.shadow), True, True
    held.save(FailingShadow(), 4000.0, force=True)
    assert held.summary()["shadow_carry"]["held_back"] == 1                                  # a record held back is counted, never silent


class ReadFails(Relay):
    def get_shadow(self):
        raise OSError("a transient error at the job's start")


class RolledBack(Relay):
    """A Worker rolled back: both shadow routes answer 404, its storage still holds the last book."""
    def get_shadow(self):
        from quantdesk.paperlink.relay import RelayError
        raise RelayError("GET /paper/shadow: HTTP 404")

    def put_shadow(self, text):
        from quantdesk.paperlink.relay import RelayError
        raise RelayError("POST /paper/shadow: HTTP 404")


def test_a_failed_read_at_the_start_never_gets_a_fresh_book_dropped(cfg, tmp_path):
    """Risk re-review S1(a): a job whose read of the book failed stamped its books from zero, below the record's stamp, so the next job dropped them as stale."""
    rn, ap, t = opened(cfg, tmp_path)
    relay = Relay()
    for i in range(3):                                                                       # a job that kept its book a few times before its record
        ap.shadow_dirty = True
        ap.save_shadow(relay, 900.0 + i, force=True)
    ap.shadow_dirty = True
    ap.save(relay, 1000.0, force=True)                                                       # the record and the book, stamped
    b = desk(cfg, tmp_path)[1]
    b.load(ReadFails(relay.lab, relay.shadow), now=t)                                        # the next job: the record read, the book's read fails
    b.shadow = dict(ap.shadow)
    b.shadow_dirty = True
    assert b.save_shadow(relay, 2000.0, force=True)                                          # it keeps its book; its record is unchanged and not saved
    c = desk(cfg, tmp_path)[1]
    c.load(relay, now=t + dt.timedelta(minutes=1))
    assert set(c.shadow) == set(ap.shadow) and "older than the record" not in c.shadow_io["dropped"]


def test_a_rollback_across_two_jobs_never_scores_a_trade_twice(cfg, tmp_path):
    """Risk re-review S1(b): job A keeps a book, the Worker is rolled back, A closes trades and saves its record; job B starts on the rolled-back Worker and saves its
    record; the Worker is redeployed. Job C must not carry A's closed trades again."""
    rn, ap, t = opened(cfg, tmp_path)
    store = Relay()
    ap.save(store, 1000.0, force=True)                                                       # job A: the book with every trade open
    back = RolledBack(store.lab, store.shadow)
    late = dt.datetime.combine(T0.date(), dt.time(15, 20), tzinfo=A2.IST)
    cycle(rn, ap, board(late), late)                                                         # A closes trades and scores them
    closed = json_keys(store.shadow) - set(ap.shadow)
    assert closed and ap.save(back, 2000.0, force=True)                                      # A's record saved on the rolled-back Worker
    b = desk(cfg, tmp_path)[1]
    b.load(back, now=late)                                                                   # job B: its book's read 404s
    b.lab.dirty = True
    assert b.save(back, 3000.0, force=True)                                                  # B's record saved, still rolled back
    redeployed = Relay(back.lab, store.shadow)                                               # the Worker back, its storage still holding A's first book
    c = desk(cfg, tmp_path)[1]
    c.load(redeployed, now=late)
    assert not (set(c.shadow) & closed)                                                      # nothing A scored is carried open again
    assert c.shadow_io["dropped"].get("older than the record") == len(json_keys(store.shadow))


def test_an_absurd_row_costs_only_itself(cfg, tmp_path):
    rn, ap, t = opened(cfg, tmp_path)
    rows = A2.Lab.unpack(ap.shadow_json()[0])["open"]
    good = rows[:3]
    bad = [[*good[0][:6], "0001-01-01T00:00:00+14:00", *good[0][7:]], [*good[1][:3], 1e-300, *good[1][4:]], [*good[2][:7], "9999-12-31", *good[2][8:]]]
    ap2 = desk(cfg, tmp_path)[1]
    io = ap2.restore_shadow(json.dumps({"v": 1, "open": [bad[0], *good, bad[1], bad[2]]}), t + dt.timedelta(minutes=1))
    assert io["restored"] == 3 and io["dropped"] == {"malformed": 3}


@needs_node
def test_the_relay_keeps_the_book_in_pieces_for_the_runners_key_only(tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/paper.js", tmp_path / "paper.js")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    (tmp_path / "t.mjs").write_text("""import { PaperBook, MAX_SHADOW, CHUNK } from './paper.js';
const store = new Map();
const state = { storage: {
  get: async (k) => { if (Array.isArray(k)) { const m = new Map(); for (const x of k) if (store.has(x)) m.set(x, store.get(x)); return m; } return store.get(k); },
  put: async (k, v) => { if (typeof k === "object") for (const [a, b] of Object.entries(k)) store.set(a, b); else store.set(k, v); },
  delete: async (k) => { for (const x of (Array.isArray(k) ? k : [k])) store.delete(x); } } };
const b = new PaperBook(state);
const call = async (m, body) => { const r = await b.handle(new Request("https://live/paper/shadow", { method: m, ...(body ? { body: JSON.stringify(body) } : {}) }), new URL("https://live/paper/shadow"), 1); return [r.status, await r.json()]; };
const out = {};
out.empty = await call("GET");
const long = JSON.stringify({ v: 1, open: [], z: "A".repeat(CHUNK * 2 + 5) });
out.long = await call("POST", { shadow: long });
out.pieces_long = [...store.keys()].filter((k) => k.startsWith("paper:shadow:")).length;
out.long_back = (await call("GET"))[1].shadow === long;
const short = JSON.stringify({ v: 1, open: [["IC", "NIFTY"]] });
out.short = await call("POST", { shadow: short });
out.pieces_short = [...store.keys()].filter((k) => k.startsWith("paper:shadow:")).length;
out.short_back = (await call("GET"))[1].shadow === short;
out.big = await call("POST", { shadow: JSON.stringify({ v: 1, open: [], pad: "x".repeat(MAX_SHADOW) }) });
out.wide = await call("POST", { shadow: JSON.stringify({ v: 1, open: ["\\u00e9"] }).replace("\\\\u00e9", "\\u00e9") });
out.shape = await call("POST", { shadow: JSON.stringify({ v: 1, open: {} }) });
out.notjson = await call("POST", { shadow: "{" });
out.after = (await call("GET"))[1].shadow === short;
console.log(JSON.stringify(out));""")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout)
    assert o["empty"] == [200, {"shadow": None, "now": 1}]
    assert o["long"][0] == 200 and o["pieces_long"] == 3 and o["long_back"]
    assert o["short"][0] == 200 and o["pieces_short"] == 1 and o["short_back"]                 # a shorter book leaves no stale pieces behind
    assert o["big"][0] == 400 and o["wide"][0] == 400 and o["shape"][0] == 400 and o["notjson"][0] == 400 and o["after"]
    live = (ROOT / "deploy/cloudflare/live.js").read_text()
    assert '"POST /paper/shadow": "ingest", "GET /paper/shadow": "ingest"' in live             # the runner's key only: the app's key cannot read or write it
