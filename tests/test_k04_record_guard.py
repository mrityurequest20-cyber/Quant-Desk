"""Audit K-04 (FH-01, X-3; HIGH), second version after the risk review of 9a1b593: at a part's start AUTO v2 read its strategy record and its open shadow book once.
One failed read left it empty, and the next save wrote that over the relay's copy (20 Nov: 16,952 open shadow trades). Now, while either cannot be read, AUTO v2
is PAUSED: it runs every exit of what it holds and opens nothing, live or shadow, learns nothing and saves nothing, so the relay keeps exactly what it had and no
tightening is ever made only to be forgotten. A failed read is tried again from the loop; an unreadable store waits for the owner (reset_record); the relay refuses
a record that halves the one it holds. PAPER MONEY ONLY: research state, not the ledger."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paper.account import Account
from quantdesk.paperlink import session as S
from quantdesk.paperlink.relay import RelayError
from tests.test_paper_auto import T0, board
from tests.test_paper_auto2 import desk
from tests.test_shadow_carry import Relay, cfg  # noqa: F401 - cfg is a fixture

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
SIDS = [s.sid for s in A2.CATALOGUE[:300]]
BOOK = json.dumps({"v": 1, "seq": 5, "open": []})


def record(n=300):
    return A2.Lab({sid: [10, 1.0, 2.0, 6] for sid in SIDS[:n]}).to_json()


class Flaky(Relay):
    """Fails the first `lab_fails` record reads and `shadow_fails` book reads, as the relay did (not JSON, a timeout, a dropped connection)."""
    def __init__(self, lab_fails=0, shadow_fails=0, **kw):
        super().__init__(**kw)
        self.lab_fails, self.shadow_fails, self.reads = lab_fails, shadow_fails, {"lab": 0, "shadow": 0}

    def get_lab(self):
        self.reads["lab"] += 1
        if self.reads["lab"] <= self.lab_fails:
            raise RelayError("GET /paper/lab: not JSON")
        return super().get_lab()

    def get_shadow(self):
        self.reads["shadow"] += 1
        if self.reads["shadow"] <= self.shadow_fails:
            raise RelayError("GET /paper/shadow: TimeoutError")
        return super().get_shadow()


def learn(ap):
    ap.lab.add(SIDS[0], 0.4)
    ap.lab.dirty = ap.shadow_dirty = True


def test_the_audits_case_one_failed_read_no_longer_wipes_the_record(cfg, tmp_path):
    relay = Flaky(lab_fails=1, lab=record(), shadow=BOOK)
    ap = desk(cfg, tmp_path)[1]
    assert "300 strategies" in ap.load(relay) and ap.persist_blocked is None                  # read again at once, and got it
    learn(ap)
    assert ap.save(relay, 10_000.0, force=True)
    assert len(A2.Lab.unpack(relay.lab)["stats"]) == 300                                      # was: 1 (FH-01's reproduction: 300 -> 1)


def test_an_unread_record_pauses_auto_v2_and_nothing_is_saved_over_the_relays_copy(cfg, tmp_path):
    before = record()
    relay = Flaky(lab_fails=99, lab=before, shadow=BOOK)
    ap = desk(cfg, tmp_path)[1]
    msg = ap.load(relay)
    assert relay.reads["lab"] == A2.LOAD_TRIES == 2 and relay.reads["shadow"] == 0             # no wait at the start; the book is not read beside an unread record
    assert ap.persist_kind == "failed" and "paused" in msg and "every 3 minutes" in msg
    learn(ap)
    assert not ap.save(relay, 10_000.0, force=True) and not ap.save_shadow(relay, 10_000.0, force=True)
    assert relay.lab == before and relay.puts == 0 and relay.shadow_puts == 0                 # the relay keeps exactly what it had
    assert ap.summary()["persist"]["state"] == "paused"


def test_an_unread_book_pauses_it_too(cfg, tmp_path):
    relay = Flaky(shadow_fails=99, lab=record(), shadow=BOOK)
    ap = desk(cfg, tmp_path)[1]
    msg = ap.load(relay)
    assert "300 strategies" in msg and "open shadow book could not be read" in ap.persist_blocked
    learn(ap)
    ap.save(relay, 10_000.0, force=True)
    assert relay.puts == 0 and relay.shadow_puts == 0 and relay.shadow == BOOK               # 20 Nov: 16,952 open shadow trades were saved over with 3,613


def test_while_paused_it_opens_and_learns_nothing_but_still_runs_the_exits_of_what_it_holds(cfg, tmp_path, monkeypatch):
    ap = desk(cfg, tmp_path)[1]
    ap.load(Flaky(lab_fails=99, lab=record()))
    for name in ("shadow_step", "evolve", "plan"):                                            # what opens or learns: never called while paused
        monkeypatch.setattr(ap, name, lambda *a, _n=name, **k: (_ for _ in ()).throw(AssertionError(f"{_n} ran while paused")))
    sid = next(s.sid for s in A2.CATALOGUE if not A2.CX.is_convex(s.struct))
    ins = SimpleNamespace(lot_size=65, right="CE", strike=24500, expiry=dt.date(2026, 11, 12))
    pos = SimpleNamespace(qty=65, instrument=ins, avg_price=100.0, opened_at=T0.isoformat())
    monkeypatch.setattr(ap, "live_packages", lambda acct: {"pkg": {"sid": sid, "u": "NIFTY", "legs": {"NIFTY12NOV2624500CE": pos}}})
    monkeypatch.setattr(ap, "mark", lambda snap, legs: 60.0)
    monkeypatch.setattr(ap, "_exit_why", lambda *a, **k: "the R stop")
    orders = ap.decide(board(T0), Account(500_000), T0)
    assert [(o["side"], o["symbol"]) for o in orders] == [("sell", "NIFTY12NOV2624500CE")] and "the R stop" in orders[0]["_why"]   # the brake ran; nothing else


def test_a_later_read_resumes_from_the_relays_copy_and_keeps_the_higher_trail_peak(cfg, tmp_path):
    relay = Flaky(lab_fails=2, lab=record(), shadow=BOOK)                                    # down at the start, back later
    ap = desk(cfg, tmp_path)[1]
    ap.load(relay)
    assert ap.persist_blocked
    ap.cx_peak = {"held": 3.5}                                                                # a convex package's peak seen while paused
    assert not ap.save(relay, 100.0)                                                          # too soon to read again
    assert relay.reads["lab"] == 2
    ap.save(relay, 100.0 + A2.LOAD_RETRY_S)                                                   # read again, on its own thread
    ap._retry_thread.join(5)
    ap.save(relay, 101.0 + A2.LOAD_RETRY_S)                                                   # the next cycle applies what it brought
    assert ap.persist_blocked is None and len(ap.lab.stats) == 300 and ap.cx_peak.get("held") == 3.5
    assert "read its record on a later try" in ap.persist_note and ap.summary()["persist"]["state"] == "ok"
    learn(ap)
    assert ap.save(relay, 1000.0, force=True) and len(A2.Lab.unpack(relay.lab)["stats"]) == 300


def test_an_unreadable_stored_record_waits_for_the_owner_and_is_never_tried_again(cfg, tmp_path):
    relay = Flaky(lab="{not json", shadow=BOOK)
    ap = desk(cfg, tmp_path)[1]
    msg = ap.load(relay)
    assert ap.persist_kind == "corrupt" and "the owner must look" in msg and "reset_record" in msg
    for k in range(5):
        ap.save(relay, 1000.0 + k * A2.LOAD_RETRY_S)
    assert relay.reads["lab"] == 1 and relay.puts == 0 and relay.lab == "{not json"         # not read again, never saved over
    assert ap.summary()["persist"]["state"] == "blocked"


def test_the_owners_reset_starts_an_unreadable_record_from_zero_and_tells_the_relay(cfg, tmp_path):
    class Rec(Flaky):
        def put_lab(self, text, reset=False):
            self.reset_flags = getattr(self, "reset_flags", []) + [reset]
            return super().put_lab(text)
    relay = Rec(lab="{not json", shadow=BOOK)
    ap = desk(cfg, tmp_path)[1]
    ap.allow_reset = True
    ap.load(relay)
    assert ap.persist_blocked is None and ap.reset_pending and "reset_record" in ap.persist_note
    learn(ap)
    assert ap.save(relay, 1000.0, force=True) and relay.reset_flags == [True] and not ap.reset_pending
    learn(ap)
    ap.save(relay, 2000.0, force=True)
    assert relay.reset_flags == [True, False]                                                 # the reset once, then ordinary saves


def test_a_record_the_relay_refuses_is_said_and_counted(cfg, tmp_path):
    class Refuses(Relay):
        def put_lab(self, text, reset=False):
            if not reset:
                raise RelayError("POST /paper/lab: HTTP 409")
            return super().put_lab(text)
    relay = Refuses(lab=None, shadow=None)
    ap = desk(cfg, tmp_path)[1]
    ap.load(relay)
    learn(ap)
    assert not ap.save(relay, 1000.0, force=True)
    assert ap.lab_refused == 1 and ap.persist_note.startswith("::error::") and ap.summary()["persist"]["refused"] == 1
    ap.allow_reset = True                                                                     # the owner's reset: the smaller record goes, on purpose
    assert ap.save(relay, 2000.0, force=True) and relay.lab


def test_no_record_ever_saved_is_a_true_start_and_a_relay_without_the_book_route_is_not_a_failed_read(cfg, tmp_path):
    ap = desk(cfg, tmp_path)[1]
    ap.load(Relay(lab=None, shadow=None))
    assert ap.persist_blocked is None

    class NoRoute(Relay):
        def get_shadow(self):
            raise RelayError("GET /paper/shadow: HTTP 404")
    ap2 = desk(cfg, tmp_path)[1]
    assert "no book route" in ap2.load(NoRoute(lab=record())) and ap2.persist_blocked is None


def test_an_answer_that_is_not_a_record_is_a_failed_read(cfg, tmp_path):
    class Odd(Relay):
        def get_lab(self):
            return {"lab": 12}
    ap = desk(cfg, tmp_path)[1]
    ap.load(Odd(lab=record()))
    assert ap.persist_kind == "failed"


def test_an_owner_release_during_a_pause_is_refused_not_lost(cfg, tmp_path):
    ap = desk(cfg, tmp_path)[1]
    ap.load(Flaky(lab_fails=99, lab=record()))
    ok, why = ap.owner_release(SIDS[0], T0)
    assert not ok and "nothing was released" in why


def test_the_compressed_record_says_how_many_strategies_it_holds():
    big = A2.Lab({s.sid: [1000, 1.0, 1.0, 500] for s in A2.CATALOGUE})
    o = json.loads(big.to_json())
    assert "z" in o and o["n"] == big.last_kept > 300 and o["stats"] == {}


class AutoStub:
    def __init__(self, kind):
        self.kind, self.persist_blocked, self.persist_kind, self.allow_reset, self.persist_note = kind, None, None, None, None

    def load(self, relay):
        self.persist_blocked, self.persist_kind = "the strategy record could not be read (RelayError)", self.kind
        return "paused"

    def decide(self, *a, **k):
        return []

    def drain_events(self):
        return []

    def save(self, *a, **k):
        self.persist_note = "paper: a note"
        return False


@pytest.mark.parametrize("kind, prefix", [("failed", "::warning::"), ("corrupt", "::error::")])
def test_the_session_says_so_and_takes_the_owners_reset_only_from_its_input(cfg, tmp_path, monkeypatch, kind, prefix):
    from tests.test_paper_session import IST, Clock, FakeRelay
    clk, lines = Clock(), []
    monkeypatch.setattr(S.time, "monotonic", lambda: (clk.t - Clock().t).total_seconds())
    monkeypatch.setenv("PAPER_RESET_RECORD", "yes" if kind == "corrupt" else "no")
    auto = AutoStub(kind)
    S.run(cfg, FakeRelay(clk), tmp_path / "ledger" / "account.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk,
          sleep=clk.sleep, say=lines.append, new_account=True, auto=auto)
    assert any(m.startswith(prefix + "paper: AUTO v2 the strategy record could not be read") for m in lines)
    assert auto.allow_reset is (kind == "corrupt") and "paper: a note" in lines


def test_the_workflow_input_is_off_by_default_and_reaches_the_runner():
    import yaml
    wf = yaml.safe_load((ROOT / ".github/workflows/paper-desk.yml").read_text(encoding="utf-8"))
    inp = wf[True]["workflow_dispatch"]["inputs"]["reset_record"]
    assert inp["type"] == "boolean" and inp["default"] is False
    assert wf["env"]["PAPER_RESET_RECORD"] == "${{ inputs.reset_record && 'yes' || 'no' }}"


@needs_node
def test_the_relay_refuses_a_record_with_fewer_than_half_the_strategies_it_holds_unless_it_is_the_owners_reset(tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/paper.js", tmp_path / "paper.js")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    big = A2.Lab({s.sid: [1000, 1.0, 1.0, 500] for s in A2.CATALOGUE}).to_json()
    cases = {"r300": record(300), "r149": record(149), "r151": record(151), "r1": record(1), "big": big,
             "big_third": json.dumps({**json.loads(big), "n": json.loads(big)["n"] // 3}), "legacy": json.dumps({"v": 1, "stats": {}, "z": "eJw="})}
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    (tmp_path / "t.mjs").write_text("""import { PaperBook, labCount } from './paper.js';
import { readFileSync } from 'fs';
const C = JSON.parse(readFileSync('cases.json', 'utf8'));
const store = new Map();
const state = { storage: { get: async (k) => store.get(k), put: async (k, v) => { store.set(k, v); }, delete: async () => {} } };
const b = new PaperBook(state);
const put = async (name, reset) => (await b.handle(new Request("https://live/paper/lab", { method: "POST", body: JSON.stringify({ lab: C[name], ...(reset ? { reset: true } : {}) }) }), new URL("https://live/paper/lab"), 1)).status;
const out = {};
out.first = await put("r300");
out.wipe = await put("r1");
out.held = labCount(store.get("paper:lab"));
out.less_than_half = await put("r149");
out.trim = await put("r151");
out.grow = await put("big");
out.big_third = await put("big_third");
out.legacy = await put("legacy");
out.reset = await put("r300") && await put("r1", true);
out.counts = [labCount(C.r300), labCount(C.legacy), labCount("{")];
console.log(JSON.stringify(out));""")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["first"] == 200 and out["wipe"] == 409 and out["held"] == 300 and out["less_than_half"] == 409 and out["trim"] == 200
    assert out["grow"] == 200 and out["big_third"] == 409 and out["legacy"] == 200 and out["reset"] == 200
    assert out["counts"] == [300, None, None]


def test_the_runner_keeps_the_persist_state_when_it_must_shrink_its_summary():
    from quantdesk.paper import runner as R
    assert "persist" in R.LAB_KEEP


@needs_node
def test_w22_pushes_the_pause_the_block_and_a_refused_record(tmp_path):
    from tests.test_k05_paper_watch import PAPER_HEAD
    from tests.test_watchdog import _node
    out = _node(tmp_path, PAPER_HEAD + r"""
const runs = { "paper-desk": [paper(D + "T05:55:00")] };
const S = (lab) => env({ ...secrets, LIVE: relay({ received_at: IST(D + "T13:30:00") - 5000, lab }) });
const w = async (lab) => fmt(await at(D + "T13:30:00", S(lab), { runs }), "W22");
out.blocked = await w({ persist: { state: "blocked", why: "x", refused: 0 } });
out.refused = await w({ persist: { state: "ok", why: "", refused: 2 } });
out.paused = await w({ persist: { state: "paused", why: "x", refused: 0 } });
out.ok = await w({ persist: { state: "ok", why: "", refused: 0 } });
out.old = await w({});
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["blocked"] == ["P1 AUTO v2 cannot read its strategy record"] and out["refused"] == ["P1 The relay refused AUTO v2's record"]
    assert out["paused"] == ["P2 AUTO v2 is paused: its record was not read"] and out["ok"] == [] and out["old"] == []


def test_a_proven_strategy_never_goes_live_while_the_book_is_unread(cfg, tmp_path):
    """The record read (a proven strategy), the book not: no live entry at all until the book reads (the planted bug: the entries gate without the pause)."""
    from tests.test_paper_auto2 import IC, calm, cycle, proven
    rn, ap = desk(cfg, tmp_path, stats=proven())
    t = calm(rn, ap, minutes=4)
    ap.persist_blocked, ap.persist_kind = "the open shadow book could not be read (RelayError)", "failed"     # paused now, with its proven record in memory
    t = t + dt.timedelta(minutes=1)
    mine, _ = cycle(rn, ap, board(t), t)
    assert not [o for o in mine if o.get("group") == "auto2"] and not rn.account.positions     # the same cycle went live in test_paper_auto2 without the pause
    assert A2.BY_SID[IC]


def test_the_reread_never_holds_up_the_cycle_or_its_brakes(cfg, tmp_path):
    """Risk review of K-04 v2, finding 1: a re-read inside save() could wait up to a minute on the relay's timeouts, before rn.step, so no stop or halt ran."""
    import threading
    import time
    gate = threading.Event()

    class Slow(Flaky):
        def get_lab(self):
            if self.reads["lab"] >= 2:                                                        # the start's two tries fail at once; the re-read hangs on the relay
                self.reads["lab"] += 1
                gate.wait(10)
            return super().get_lab()
    relay = Slow(lab_fails=2, lab=record(), shadow=BOOK)
    ap = desk(cfg, tmp_path)[1]
    ap.load(relay)
    t0 = time.monotonic()
    for k in range(5):
        ap.save(relay, 1000.0 + k * A2.LOAD_RETRY_S)
    assert time.monotonic() - t0 < 1.0 and ap.persist_blocked                                 # five cycles, none waited
    assert sum(1 for th in threading.enumerate() if th.name == "auto2-reread") == 1           # one re-read at a time
    gate.set()
    ap._retry_thread.join(5)
    ap.save(relay, 9000.0)
    assert ap.persist_blocked is None and len(ap.lab.stats) == 300


def test_a_failing_retry_costs_the_retry_never_the_part(cfg, tmp_path, monkeypatch):
    ap = desk(cfg, tmp_path)[1]
    ap.load(Flaky(lab_fails=99, lab=record()))
    monkeypatch.setattr(ap, "_retry", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    assert ap.save(Flaky(lab=record()), 1000.0) is False and ap.shadow_io["retry_errors"] == 1


def test_an_unknown_convex_peak_never_trails_below_a_rung_already_sold(cfg, tmp_path, monkeypatch):
    """Risk review of K-04 v2, finding 2: with the record unread a package's peak was unknown, so one that had sold its first third at +RUNG1_R trailed from where
    it is now. A rung sold proves the package reached it."""
    ap = desk(cfg, tmp_path)[1]
    s = A2.CX_CATALOGUE[0]
    seen = {}
    monkeypatch.setattr(ap, "_cx_meta", lambda text: {"n": 3})
    monkeypatch.setattr(ap, "_cx_exit", lambda s_, r, peak, d1, d2, *a, **k: seen.update(peak=peak, d1=d1, d2=d2) or (None, ""))
    ins = SimpleNamespace(lot_size=65)

    def pkg(lots):
        return {"sid": s.sid, "u": "NIFTY", "legs": {"L": SimpleNamespace(qty=65 * lots, instrument=ins)}}
    t1, t2 = A2.CX.tranches(3)
    ap._cx_live_exit("pkgA", pkg(3 - t1), s, 0.4, T0, T0, dt.date(2026, 11, 26), 0.0, {})      # rung 1 sold, peak unknown, now +0.4R
    assert seen["d1"] and seen["peak"] == A2.CX.RUNG1_R and ap.cx_peak["pkgA"] == A2.CX.RUNG1_R
    ap._cx_live_exit("pkgB", pkg(3 - t1 - t2), s, 0.4, T0, T0, dt.date(2026, 11, 26), 0.0, {})     # both rungs sold
    assert seen["peak"] == A2.CX.RUNG2_R
    ap._cx_live_exit("pkgC", pkg(3), s, 0.4, T0, T0, dt.date(2026, 11, 26), 0.0, {})               # nothing sold: the peak is what it is
    assert seen["peak"] == 0.4
    ap.cx_peak["pkgD"] = 5.0
    ap._cx_live_exit("pkgD", pkg(3 - t1), s, 0.4, T0, T0, dt.date(2026, 11, 26), 0.0, {})          # a known higher peak is kept
    assert seen["peak"] == 5.0
    ap.cx_peak["pkgE"] = 0.5                                                                       # a known peak below a rung already sold (one stored under the old ladder)
    ap._cx_live_exit("pkgE", pkg(3 - t1), s, 0.4, T0, T0, dt.date(2026, 11, 26), 0.0, {})
    assert seen["peak"] == A2.CX.RUNG1_R
