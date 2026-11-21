"""Audit K-04 (FH-01, X-3; HIGH): at a part's start AUTO v2 read its strategy record and its open shadow book from the relay once, with no retry. One failed read
left it with an empty record, and the next save overwrote the relay's: the record (4,158 strategies, 236,553 shadow trades), the probation list and the open book.
It happened live on 20 Nov (16,952 open shadow trades lost at the afternoon start). Now each read is tried six times; while either could not be read nothing
is saved over them; and the relay refuses a record with fewer than half the strategies of the one it holds. PAPER MONEY ONLY: research state, not the ledger."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.paper import auto2 as A2
from quantdesk.paperlink import session as S
from quantdesk.paperlink.relay import RelayError
from tests.test_paper_auto2 import desk
from tests.test_shadow_carry import Relay, cfg  # noqa: F401 - cfg is a fixture

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
SIDS = [s.sid for s in A2.CATALOGUE[:300]]


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


def fresh(cfg, tmp_path):
    ap = desk(cfg, tmp_path)[1]
    waits = []
    ap.load_sleep = waits.append
    return ap, waits


def learn_and_save(ap, relay):
    ap.lab.add(SIDS[0], 0.4)                                                              # one scored shadow trade: the record is dirty
    ap.shadow_dirty = True
    return ap.save(relay, 10_000.0, force=True)


def test_the_audits_case_one_failed_read_no_longer_wipes_the_record(cfg, tmp_path):
    relay = Flaky(lab_fails=1, lab=record())
    ap, waits = fresh(cfg, tmp_path)
    msg = ap.load(relay)
    assert "300 strategies" in msg and ap.persist_blocked is None and waits == [1]        # read again a second later, and got it
    learn_and_save(ap, relay)
    assert len(A2.Lab.unpack(relay.lab)["stats"]) == 300                                  # was: 1 (FH-01's reproduction: 300 -> 1)


def test_a_record_that_cannot_be_read_after_every_try_is_never_saved_over(cfg, tmp_path):
    before = record()
    relay = Flaky(lab_fails=99, lab=before, shadow=json.dumps({"v": 1, "seq": 5, "open": []}))
    ap, waits = fresh(cfg, tmp_path)
    msg = ap.load(relay)
    assert relay.reads["lab"] == A2.LOAD_TRIES == 6 and waits[:5] == list(A2.LOAD_WAITS_S)
    assert ap.persist_blocked and "could not be read" in msg and "nothing AUTO v2 learns in this part is saved" in msg
    assert learn_and_save(ap, relay) is False and not ap.save_shadow(relay, 20_000.0, force=True)
    assert relay.lab == before and relay.puts == 0 and relay.shadow_puts == 0               # the relay keeps exactly what it had
    assert ap.shadow_io["blocked"] >= 1


def test_an_open_book_that_cannot_be_read_blocks_the_saves_too(cfg, tmp_path):
    book = json.dumps({"v": 1, "seq": 5, "open": []})
    relay = Flaky(shadow_fails=99, lab=record(), shadow=book)
    ap, _ = fresh(cfg, tmp_path)
    msg = ap.load(relay)
    assert "300 strategies" in msg and "no open shadow trades could be read" in msg and "open shadow book could not be read" in ap.persist_blocked
    learn_and_save(ap, relay)
    assert relay.puts == 0 and relay.shadow_puts == 0 and relay.shadow == book              # 20 Nov: 16,952 open shadow trades were saved over with 3,613


def test_a_book_read_on_a_later_try_is_carried_and_saving_goes_on(cfg, tmp_path):
    relay = Flaky(shadow_fails=2, lab=record(), shadow=json.dumps({"v": 1, "seq": 5, "open": []}))
    ap, waits = fresh(cfg, tmp_path)
    ap.load(relay)
    assert ap.persist_blocked is None and waits == [1, 2]
    assert learn_and_save(ap, relay) and relay.puts == 1


def test_no_record_ever_saved_is_a_true_start_not_a_failed_read(cfg, tmp_path):
    relay = Relay(lab=None, shadow=None)                                                  # the relay has never held one: {"lab": null}, {"shadow": null}
    ap, waits = fresh(cfg, tmp_path)
    ap.load(relay)
    assert ap.persist_blocked is None and waits == []
    assert learn_and_save(ap, relay) and relay.puts == 1


def test_an_answer_that_is_not_a_record_counts_as_a_failed_read(cfg, tmp_path):
    class Odd(Relay):
        def get_lab(self):
            return {"lab": 12}
    relay = Odd(lab=record())
    ap, _ = fresh(cfg, tmp_path)
    ap.load(relay)
    assert ap.persist_blocked and learn_and_save(ap, relay) is False and relay.puts == 0


def test_the_compressed_record_says_how_many_strategies_it_holds():
    big = A2.Lab({s.sid: [1000, 1.0, 1.0, 500] for s in A2.CATALOGUE})
    o = json.loads(big.to_json())
    assert "z" in o and o["n"] == big.last_kept > 300 and o["stats"] == {}
    small = json.loads(A2.Lab({SIDS[0]: [1, 1.0, 1.0, 1]}).to_json())
    assert "z" not in small and len(small["stats"]) == 1                                   # the plain form is counted by its keys


class AutoStub:
    """What the session sees of AUTO v2 here: its record read failed at the start."""
    def __init__(self):
        self.load_sleep, self.persist_blocked = None, None

    def load(self, relay):
        self.persist_blocked = "the strategy record could not be read (RelayError)"
        return "no record could be read (RelayError): starting from zero"

    def decide(self, *a, **k):
        return []

    def drain_events(self):
        return []

    def save(self, *a, **k):
        return False


def test_the_session_gives_its_clock_to_the_retries_and_warns_when_nothing_will_be_saved(cfg, tmp_path, monkeypatch):
    from tests.test_paper_session import IST, Clock, FakeRelay
    clk, lines = Clock(), []
    monkeypatch.setattr(S.time, "monotonic", lambda: (clk.t - Clock().t).total_seconds())
    auto = AutoStub()
    S.run(cfg, FakeRelay(clk), tmp_path / "ledger" / "account.json", (clk.t + dt.timedelta(minutes=1)).astimezone(IST).time(), every_s=3.0, clock=clk,
          sleep=clk.sleep, say=lines.append, new_account=True, auto=auto)
    assert auto.load_sleep == clk.sleep
    assert any(m.startswith("::warning::paper: AUTO v2 the strategy record could not be read") for m in lines)


@needs_node
def test_the_relay_refuses_a_record_with_fewer_than_half_the_strategies_it_holds(tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/paper.js", tmp_path / "paper.js")
    (tmp_path / "package.json").write_text('{"type": "module"}')
    rec = lambda n: A2.Lab({sid: [10, 1.0, 2.0, 6] for sid in SIDS[:n]}).to_json()      # noqa: E731
    big = A2.Lab({s.sid: [1000, 1.0, 1.0, 500] for s in A2.CATALOGUE}).to_json()          # compressed, with n
    n_big = json.loads(big)["n"]
    legacy = json.dumps({"v": 1, "stats": {}, "z": "eJw="})                               # compressed, from before n was written: count not known
    cases = {"r300": rec(300), "r149": rec(149), "r151": rec(151), "r1": rec(1), "big": big, "big_half": json.dumps({**json.loads(big), "n": n_big // 3}),
             "legacy": legacy, "r10": rec(10), "r2": rec(2)}
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    (tmp_path / "t.mjs").write_text("""import { PaperBook, labCount } from './paper.js';
import { readFileSync } from 'fs';
const C = JSON.parse(readFileSync('cases.json', 'utf8'));
const store = new Map();
const state = { storage: {
  get: async (k) => { if (Array.isArray(k)) { const m = new Map(); for (const x of k) if (store.has(x)) m.set(x, store.get(x)); return m; } return store.get(k); },
  put: async (k, v) => { if (typeof k === "object") for (const [a, b] of Object.entries(k)) store.set(a, b); else store.set(k, v); },
  delete: async (k) => { for (const x of (Array.isArray(k) ? k : [k])) store.delete(x); } } };
const b = new PaperBook(state);
const put = async (name) => { const r = await b.handle(new Request("https://live/paper/lab", { method: "POST", body: JSON.stringify({ lab: C[name] }) }), new URL("https://live/paper/lab"), 1); return r.status; };
const out = {};
out.first = await put("r300");
out.wipe = await put("r1");                 // the audit's case: 300 strategies -> 1
out.held_after_wipe = labCount(store.get("paper:lab"));
out.less_than_half = await put("r149");
out.trim = await put("r151");               // a trim at the size bound: allowed
out.grow = await put("big");
out.big_wipe = await put("big_half");       // compressed, a third of the count
out.legacy = await put("legacy");           // a count not known: allowed (the guard needs both counts)
out.small_store = new PaperBook({ storage: { get: async () => C.r10, put: async () => {} } });
out.small = (await out.small_store.handle(new Request("https://live/paper/lab", { method: "POST", body: JSON.stringify({ lab: C.r2 }) }), new URL("https://live/paper/lab"), 1)).status;
delete out.small_store;
out.counts = [labCount(C.r300), labCount(C.big), labCount(C.legacy), labCount("{")];
console.log(JSON.stringify(out));""")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["first"] == 200 and out["wipe"] == 409 and out["held_after_wipe"] == 300          # refused: the record held is kept
    assert out["less_than_half"] == 409 and out["trim"] == 200 and out["grow"] == 200 and out["big_wipe"] == 409
    assert out["legacy"] == 200 and out["small"] == 200                                          # unknown count; a record held below 20 strategies is not guarded
    assert out["counts"][0] == 300 and out["counts"][1] == n_big and out["counts"][2] is None and out["counts"][3] is None


def test_a_relay_without_the_book_route_is_not_a_failed_read_and_is_not_retried(cfg, tmp_path):
    """A Worker rolled back answers 404 for /paper/shadow: no book can be read or saved over there, and the record's stamp drops the stale book later
    (test_shadow_carry's rollback test), so this is no reason to stop saving, nor to wait 30 s."""
    class NoRoute(Relay):
        def get_shadow(self):
            raise RelayError("GET /paper/shadow: HTTP 404")
    relay = NoRoute(lab=record())
    ap, waits = fresh(cfg, tmp_path)
    msg = ap.load(relay)
    assert ap.persist_blocked is None and waits == [] and "no book route" in msg
