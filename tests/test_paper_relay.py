"""The relay's paper-order queue (deploy/cloudflare/paper.js and its routes in live.js), run under Node. PAPER MONEY ONLY: the relay holds orders and the account; every rule about
whether a trade happens is the Python risk gate's (tests/test_paper_runner.py). Here: who may call what, the shape of everything that crosses, the queue, and the account that may
only grow."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
I, R = "i" * 32, "r" * 32


def stage(tmp_path):
    for f in ("live.js", "kotak.js", "series.js", "paper.js", "news.js", "candles.js", "routes.js"):
        shutil.copyfile(ROOT / "deploy" / "cloudflare" / f, tmp_path / ("live.mjs" if f == "live.js" else f))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")


HARNESS = r"""
import { handleLive, LiveBoard } from "./live.mjs";
const mem = new Map();
const clone = (v) => JSON.parse(JSON.stringify(v));
let putDelay = 0;                                               // test hook: every storage operation yields this many ms first, as a real one does
const lag = () => (putDelay ? new Promise((r) => setTimeout(r, putDelay)) : null);
let failGetKey = null, failPutKey = null;                       // test hooks: a read of this key throws; a write that includes this key throws
const LIMIT = 131072;                                           // a Durable Object value is limited to 128 KiB: an over-size write throws, as the real one does
const big = (v) => JSON.stringify(v).length > LIMIT;
const state = { storage: {
  get: async (k) => { await lag(); if (failGetKey && (k === failGetKey || (Array.isArray(k) && k.includes(failGetKey)))) throw new Error("storage read failed"); return Array.isArray(k) ? new Map(k.filter((x) => mem.has(x)).map((x) => [x, clone(mem.get(x))])) : (mem.has(k) ? clone(mem.get(k)) : undefined); },
  put: async (k, v) => { await lag(); const kv = typeof k === "object" ? Object.entries(k) : [[k, v]]; for (const [a, b] of kv) { if (a === failPutKey || big(b)) throw new Error("storage write failed: " + a); } for (const [a, b] of kv) mem.set(a, clone(b)); },
  getAlarm: async () => null, setAlarm: async () => {}, deleteAlarm: async () => {} }, blockConcurrencyWhile: async (fn) => fn() };
let board = new LiveBoard(state, {});
let now = 1789000000000;
board.now = () => now;
const LIVE = { idFromName: () => "board", get: () => ({ fetch: (u, init) => board.fetch(new Request(u, init)) }) };
const env = { LIVE, LIVE_INGEST_TOKEN: "%(I)s", LIVE_READ_TOKEN: "%(R)s" };
const call = async (method, path, { token, body, e = env } = {}) => {
  const r = await handleLive(new Request("https://qd.example" + path, { method, headers: token ? { authorization: "Bearer " + token } : {}, ...(body !== undefined ? { body: typeof body === "string" ? body : JSON.stringify(body) } : {}) }), e);
  if (r === null) return null;
  return { status: r.status, body: await r.json() };
};
const READ = env.LIVE_READ_TOKEN, ING = env.LIVE_INGEST_TOKEN;
const order = (id, extra = {}) => ({ id, side: "buy", symbol: "NIFTY12NOV2624500CE", lots: 1, strategy: "breakout", thesis: "range break with rising volume on the thirty minute chart", ...extra });
const row = (i, prev) => ({ seq: i, kind: "buy", hash: (String(i).padStart(4, "0") + "x".repeat(60)).slice(0, 64), prev, pad: "p".repeat(200) });
const account = (n, tag = "") => JSON.stringify({ capital0: 500000, ledger: Array.from({ length: n }, (_, i) => ({ ...row(i + 1, i ? "h" + i : "0"), hash: tag + (String(i + 1).padStart(4, "0") + "x".repeat(60)).slice(0, 64 - tag.length) })) });
const out = {};
%(BODY)s
console.log(JSON.stringify(out));
"""


def run(tmp_path, body: str):
    stage(tmp_path)
    (tmp_path / "t.mjs").write_text(HARNESS % {"I": I, "R": R, "BODY": body}, encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_each_route_takes_exactly_one_key(tmp_path):
    o = run(tmp_path, r"""
const routes = [["POST", "/paper/order", order("ord-aaaa1")], ["POST", "/paper/kill", { on: true }], ["GET", "/paper/state"],
                ["GET", "/paper/queue"], ["POST", "/paper/result", { id: "ord-aaaa1", status: "refused", reasons: ["x"] }], ["POST", "/paper/state", { summary: { ledger_len: 0 } }], ["GET", "/paper/state?full=1"]];
const m = {};
for (const [method, path, body] of routes) {
  m[method + " " + path] = { none: (await call(method, path, { body })).status, read: (await call(method, path, { token: READ, body })).status, ingest: (await call(method, path, { token: ING, body })).status };
}
out.m = m;
out.other = (await call("GET", "/paper/nothing", { token: READ })).status;
out.put = (await call("PUT", "/paper/order", { token: READ })).status;
out.off = (await call("GET", "/paper/state", { token: READ, e: { LIVE } })).status;
out.live = (await call("GET", "/live/snapshot", { token: READ })).status;
""")
    m = o["m"]
    for k in m:
        assert m[k]["none"] == 401, k                                                            # no key: refused
    read_ok = {"POST /paper/order", "POST /paper/kill", "GET /paper/state"}
    ingest_ok = {"GET /paper/queue", "POST /paper/result", "POST /paper/state", "GET /paper/state?full=1"}
    for k in read_ok:
        assert m[k]["read"] == 200 and m[k]["ingest"] == 401, k                                  # the read key does these; the ingest key does not
    for k in ingest_ok:
        assert m[k]["ingest"] == 200 and m[k]["read"] == 401, k                                  # the ingest key does these; the read key does not
    assert o["other"] == 404 and o["put"] == 405 and o["off"] == 503 and o["live"] == 200


@needs_node
def test_an_order_is_checked_stamped_by_the_relay_and_queued_once(tmp_path):
    o = run(tmp_path, r"""
out.good = await call("POST", "/paper/order", { token: READ, body: order("ord-bbbb1", { queued_at: 5, evil: "x", __proto__: { admin: true } }) });
out.dup = await call("POST", "/paper/order", { token: READ, body: order("ord-bbbb1") });
out.sellall = await call("POST", "/paper/order", { token: READ, body: { id: "ord-bbbb2", side: "sell", symbol: "NIFTY12NOV2624500CE", lots: "all" } });
const bad = {};
for (const [k, v] of Object.entries({ id: order("x"), side: order("ord-cccc1", { side: "short" }), lots0: order("ord-cccc2", { lots: 0 }), lotsF: order("ord-cccc3", { lots: 1.5 }), lotsAll: order("ord-cccc4", { lots: "all" }),
  lotsBig: order("ord-cccc5", { lots: 5000 }), thesis: order("ord-cccc6", { thesis: "buy it" }), strat: order("ord-cccc7", { strategy: "" }), sym: order("ord-cccc8", { symbol: "<script>" }), symlow: order("ord-cccc9", { symbol: "nifty" }),
  limit: order("ord-cccd1", { limit: -1 }), limitS: order("ord-cccd2", { limit: "9" }), group: order("ord-cccd3", { group: "g".repeat(50) }), arr: [order("ord-cccd4")], str: "x" })) bad[k] = (await call("POST", "/paper/order", { token: READ, body: v })).status;
out.bad = bad;
out.notjson = (await call("POST", "/paper/order", { token: READ, body: "{nope" })).status;
out.big = (await call("POST", "/paper/order", { token: READ, body: "x".repeat(1400000) })).status;
const q = (await call("GET", "/paper/queue", { token: ING })).body;
out.queue = q.orders; out.now = q.now;
// the cap
for (let i = 0; i < 25; i++) out["cap" + i] = (await call("POST", "/paper/order", { token: READ, body: order("ord-fill" + String(i).padStart(2, "0")) })).status;
""")
    assert o["good"]["status"] == 200 and o["good"]["body"]["pending"] == 1 and o["dup"]["status"] == 409 and o["sellall"]["status"] == 200
    assert all(v == 400 for v in o["bad"].values()), o["bad"]
    assert o["notjson"] == 400 and o["big"] == 413
    q = o["queue"][0]
    assert q["queued_at"] == o["now"] and q["queued_at"] != 5 and "evil" not in q and "admin" not in q and set(q) == {"id", "side", "symbol", "lots", "strategy", "thesis", "queued_at"}      # the relay's clock, known fields only
    codes = [o[f"cap{i}"] for i in range(25)]
    assert codes.count(200) == 18 and codes.count(429) == 7                                          # 2 already queued + 18 = the cap of 20


@needs_node
def test_a_result_removes_its_order_and_is_kept_and_the_kill_flag_round_trips(tmp_path):
    o = run(tmp_path, r"""
await call("POST", "/paper/order", { token: READ, body: order("ord-dddd1") });
await call("POST", "/paper/order", { token: READ, body: order("ord-dddd2") });
out.res = await call("POST", "/paper/result", { token: ING, body: { id: "ord-dddd1", status: "filled", reasons: [], fill: { seq: 1, kind: "buy", ts: "t", qty: 65, price: 100, fees: 9.5, symbol: "NIFTY12NOV2624500CE", evil: 1 }, at: "now" } });
out.q = (await call("GET", "/paper/queue", { token: ING })).body.orders.map((x) => x.id);
out.badres = [];
for (const b of [{ id: "ord-dddd2", status: "weird" }, { id: "x", status: "filled" }, "s"]) out.badres.push((await call("POST", "/paper/result", { token: ING, body: b })).status);
await call("POST", "/paper/result", { token: ING, body: { id: "ord-dddd1", status: "done", reasons: ["again"] } });         // a repeat replaces, never duplicates
out.reuse = (await call("POST", "/paper/order", { token: READ, body: order("ord-dddd1") })).status;       // a handled id cannot be queued again (while it is among the last 100 results; the runner's own ledger check is what stops a second fill)
for (let i = 0; i < 120; i++) await call("POST", "/paper/result", { token: ING, body: { id: "ord-res" + String(i).padStart(3, "0"), status: "refused", reasons: ["r"] } });
const st = (await call("GET", "/paper/state", { token: READ })).body;
out.results = st.results.length; out.pending = st.pending.map((p) => p.id); out.pendingKeys = Object.keys(st.pending[0] || {});
out.k1 = (await call("POST", "/paper/kill", { token: READ, body: { on: true } })).body;
out.kq = (await call("GET", "/paper/queue", { token: ING })).body.kill;
out.kbad = (await call("POST", "/paper/kill", { token: READ, body: { on: "yes" } })).status;
out.k2 = (await call("POST", "/paper/kill", { token: READ, body: { on: false } })).body;
const one = (await call("POST", "/paper/result", { token: ING, body: { id: "ord-dddd3", status: "filled", fill: { seq: 1, evil: 1, price: 5, symbol: "S" } } }));
out.fillkeys = Object.keys((await call("GET", "/paper/state", { token: READ })).body.results.find((r) => r.id === "ord-dddd3").fill).sort();
""")
    assert o["res"]["status"] == 200 and o["q"] == ["ord-dddd2"] and o["badres"] == [400, 400, 400]
    assert o["results"] == 30 and o["pending"] == ["ord-dddd2"] and "thesis" not in o["pendingKeys"]               # the app sees the last 30 results and no thesis text in the pending list
    assert o["reuse"] == 409 and o["k1"] == {"kill": True} and o["kq"] is True and o["kbad"] == 400 and o["k2"] == {"kill": False}
    assert o["fillkeys"] == ["price", "seq", "symbol"]


@needs_node
def test_the_account_may_only_grow_and_must_extend_what_is_held(tmp_path):
    o = run(tmp_path, r"""
const put = (n, tag, extra = {}) => call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: n, equity: 1, ...extra }, account: account(n, tag) } });
out.first = (await put(3, "")).status;
out.same = (await put(3, "")).status;                         // the same length again (marks moved): fine
out.grow = (await put(5, "")).status;
out.shorter = await put(4, "");                               // a shorter ledger than held
out.different = await put(6, "Z");                            // longer, but not an extension of the held history
out.aheadNoAcct = await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 9 } } });
out.summaryShort = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 3, equity: 1 } } })).status;      // a summary alone may not claim a shorter ledger either
out.summaryOnly = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 5, equity: 7 } } })).status;
out.mismatch = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 6 }, account: account(5) } })).status;
out.nolen = (await call("POST", "/paper/state", { token: ING, body: { summary: { equity: 1 }, account: account(5) } })).status;
out.notjson = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 5 }, account: "{nope" } })).status;
out.hugesummary = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 5, blob: "x".repeat(70000) } } })).status;
out.appview = (await call("GET", "/paper/state", { token: READ })).body;
out.full = (await call("GET", "/paper/state?full=1", { token: ING })).body;
out.fullIsHeld = out.full.account === account(5);
""")
    assert (o["first"], o["same"], o["grow"]) == (200, 200, 200)
    assert o["shorter"]["status"] == 409 and o["shorter"]["body"]["held"] == 5 and o["different"]["status"] == 409 and "different history" in o["different"]["body"]["error"]
    assert o["aheadNoAcct"]["status"] == 409 and o["summaryOnly"] == 200 and o["summaryShort"] == 409
    assert o["mismatch"] == 400 and o["nolen"] == 400 and o["notjson"] == 400 and o["hugesummary"] == 400
    assert "account" not in o["appview"] and o["appview"]["summary"]["equity"] == 7                                 # the app never gets the ledger
    assert o["fullIsHeld"]                                                                                           # the runner gets back exactly what it stored


@needs_node
def test_a_big_account_is_stored_in_pieces_and_comes_back_whole(tmp_path):
    o = run(tmp_path, r"""
const n = 900;                                                    // ~230 characters a row: well over one stored piece
const text = account(n);
out.len = text.length;
out.put = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: n }, account: text } })).status;
out.pieces = [...mem.keys()].filter((k) => k.startsWith("paper:acct:")).length;
out.back = (await call("GET", "/paper/state?full=1", { token: ING })).body.account === text;
out.grow = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: n + 10 }, account: account(n + 10) } })).status;
out.toobig = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 9000 }, account: account(9000) } })).status;
""")
    assert o["len"] > 200000 and o["put"] == 200 and o["pieces"] >= 3 and o["back"] is True and o["grow"] == 200 and o["toobig"] in (400, 413)


@needs_node
def test_everything_survives_a_restart_and_a_corrupt_store_is_cleaned_not_trusted(tmp_path):
    o = run(tmp_path, r"""
await call("POST", "/paper/order", { token: READ, body: order("ord-eeee1") });
await call("POST", "/paper/kill", { token: READ, body: { on: true } });
await call("POST", "/paper/result", { token: ING, body: { id: "ord-gone1", status: "refused", reasons: ["r"] } });
await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 2 }, account: account(2) } });
board = new LiveBoard(state, {}); board.now = () => now;                                   // a restart: new object, same storage
const q = (await call("GET", "/paper/queue", { token: ING })).body;
out.after = { ids: q.orders.map((x) => x.id), kill: q.kill, results: (await call("GET", "/paper/state", { token: READ })).body.results.map((r) => r.id), full: (await call("GET", "/paper/state?full=1", { token: ING })).body.account === account(2) };
mem.set("paper:queue", [{ id: "ord-ok0001", side: "buy", symbol: "NIFTY12NOV2624500CE", lots: 1, strategy: "s", thesis: "t".repeat(30), queued_at: 1 }, { id: "bad" }, "junk", { id: "ord-ok0002", side: "buy", symbol: "NIFTY12NOV2624500CE", lots: 1, strategy: "s", thesis: "t".repeat(30) }]);
mem.set("paper:results", ["x", { id: "ord-r00001", status: "filled" }, { id: "ord-r00002", status: "hacked" }]);
mem.set("paper:kill", "yes");
board = new LiveBoard(state, {}); board.now = () => now;
const c = (await call("GET", "/paper/queue", { token: ING })).body;
out.cleaned = { ids: c.orders.map((x) => x.id), kill: c.kill, results: (await call("GET", "/paper/state", { token: READ })).body.results.map((r) => r.id) };
mem.set("paper:meta", { n: 3, ledger_len: 2 });
out.unreadable = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 3 }, account: account(3) } })).status;      // a held account that cannot be read blocks a replace
""")
    assert o["after"] == {"ids": ["ord-eeee1"], "kill": True, "results": ["ord-gone1"], "full": True}
    assert o["cleaned"] == {"ids": ["ord-ok0001"], "kill": False, "results": ["ord-r00001"]}                       # only well-formed entries survive; a kill that is not exactly true is off
    assert o["unreadable"] == 409


@needs_node
def test_the_live_board_still_works_beside_the_queue(tmp_path):
    o = run(tmp_path, r"""
out.push = (await call("POST", "/live/ingest", { token: ING, body: { quotes: { NIFTY: { ltp: 24500.5 } } } })).status;
await call("POST", "/paper/order", { token: READ, body: order("ord-ffff1") });
out.snap = Object.keys((await call("GET", "/live/snapshot", { token: READ })).body.quotes);
out.health = (await call("GET", "/live/health", { token: READ })).status;
""")
    assert o["push"] == 200 and o["snap"] == ["NIFTY"] and o["health"] == 200


def test_the_relay_paper_module_has_no_broker_secret_or_network_call():
    import re
    src = (ROOT / "deploy" / "cloudflare" / "paper.js").read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", src)
    assert not re.search(r"fetch\(|XMLHttpRequest|WebSocket|env\.|KOTAK|KITE|secret|password|token", code, re.I)


@needs_node
def test_a_failed_storage_read_is_never_cached_as_empty_and_never_saved_over_the_real_state(tmp_path):
    o = run(tmp_path, r"""
await call("POST", "/paper/order", { token: READ, body: order("ord-keep001") });
await call("POST", "/paper/kill", { token: READ, body: { on: true } });
board = new LiveBoard(state, {}); board.now = () => now;                    // a restart
failGetKey = "paper:queue";                                                // the read of the book fails
const down = await call("GET", "/paper/queue", { token: ING });
const downWrite = await call("POST", "/paper/result", { token: ING, body: { id: "ord-other01", status: "done" } });
out.down = [down.status, downWrite.status];
failGetKey = null;
const back = (await call("GET", "/paper/queue", { token: ING })).body;     // storage recovered
out.back = { ids: back.orders.map((x) => x.id), kill: back.kill };
await call("POST", "/paper/result", { token: ING, body: { id: "ord-other01", status: "done" } });
out.after = { ids: (await call("GET", "/paper/queue", { token: ING })).body.orders.map((x) => x.id), kill: (await call("GET", "/paper/queue", { token: ING })).body.kill, stored: mem.get("paper:kill") };
""")
    assert o["down"] == [503, 503] and o["back"] == {"ids": ["ord-keep001"], "kill": True} and o["after"]["kill"] is True and o["after"]["stored"] is True


@needs_node
def test_a_failed_write_changes_nothing_and_a_retry_is_not_told_the_id_was_used(tmp_path):
    o = run(tmp_path, r"""
failPutKey = "paper:queue";
out.fail = (await call("POST", "/paper/order", { token: READ, body: order("ord-retry01") })).status;
out.queueAfterFail = (await call("GET", "/paper/queue", { token: ING })).body.orders.length;
failPutKey = null;
out.retry = (await call("POST", "/paper/order", { token: READ, body: order("ord-retry01") })).status;
// the kill flag has its own key: a result store that cannot be written does not stop it
failPutKey = "paper:results";
out.resFail = (await call("POST", "/paper/result", { token: ING, body: { id: "ord-retry01", status: "done" } })).status;
out.kill = (await call("POST", "/paper/kill", { token: READ, body: { on: true } })).status;
board = new LiveBoard(state, {}); board.now = () => now; failPutKey = null;
const q = (await call("GET", "/paper/queue", { token: ING })).body;
out.afterRestart = { kill: q.kill, ids: q.orders.map((x) => x.id) };
""")
    assert o["fail"] == 500 and o["queueAfterFail"] == 0 and o["retry"] == 200 and o["resFail"] == 500 and o["kill"] == 200
    assert o["afterRestart"] == {"kill": True, "ids": ["ord-retry01"]}


@needs_node
def test_a_fresh_store_answers_with_a_boolean_kill_and_every_stored_value_stays_under_the_limit(tmp_path):
    o = run(tmp_path, r"""
out.freshQueue = (await call("GET", "/paper/queue", { token: ING })).body;
out.freshState = (await call("GET", "/paper/state", { token: READ })).body;
const worst = Array.from({ length: 5 }, () => "r".repeat(400));            // more and longer than are kept
for (let i = 0; i < 80; i++) await call("POST", "/paper/result", { token: ING, body: { id: "ord-big" + String(i).padStart(4, "0"), status: "refused", reasons: worst, fill: { symbol: "S".repeat(100), kind: "k".repeat(100), ts: "t".repeat(100) }, at: "a".repeat(100) } });
out.sizes = Object.fromEntries([...mem.entries()].map(([k, v]) => [k, JSON.stringify(v).length]));
out.results = (await call("GET", "/paper/state", { token: READ })).body.results.length;
const kept = mem.get("paper:results");
out.kept = kept.length; out.nReasons = Math.max(...kept.map((r) => r.reasons.length)); out.lenReason = Math.max(...kept.flatMap((r) => r.reasons.map((x) => x.length)));
out.reuse = (await call("POST", "/paper/order", { token: READ, body: order("ord-big0000") })).status;      // used 80 results ago, long out of the last 50
""")
    assert o["freshQueue"]["kill"] is False and o["freshQueue"]["orders"] == [] and o["freshState"]["kill"] is False
    assert max(o["sizes"].values()) < 131072 and o["results"] == 30
    assert o["kept"] == 50 and o["nReasons"] == 5 and o["lenReason"] == 200                                              # the caps themselves, not only the sizes they give
    assert o["reuse"] == 409                                                                                            # the used-id list outlives the results list


@needs_node
def test_an_id_with_trailing_junk_an_infinite_limit_and_a_non_ascii_account_are_refused(tmp_path):
    o = run(tmp_path, r"""
out.ids = [];
for (const id of ["ord-ok123\n", "ord-ok123<script>", "ord ok123", "ord-o", "ord-oké123"]) out.ids.push((await call("POST", "/paper/order", { token: READ, body: order(id) })).status);
out.limit = (await call("POST", "/paper/order", { token: READ, body: JSON.stringify(order("ord-limit01")).replace(/\}$/, ',"limit":1e400}') })).status;
const acct = JSON.stringify({ capital0: 1, ledger: [{ hash: "a", note: "₹ rupee" }] });
out.nonascii = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 1 }, account: acct } })).status;
const ok = JSON.stringify({ capital0: 1, ledger: [{ hash: "a", note: "\\u20b9 rupee" }] });
out.ascii = (await call("POST", "/paper/state", { token: ING, body: { summary: { ledger_len: 1 }, account: ok } })).status;
""")
    assert o["ids"] == [400] * 5 and o["limit"] == 400 and o["nonascii"] == 400 and o["ascii"] == 200


@needs_node
def test_requests_that_overlap_never_lose_an_acknowledged_order_or_break_the_cap(tmp_path):
    o = run(tmp_path, r"""
putDelay = 3;
const post = (id) => call("POST", "/paper/order", { token: READ, body: order(id) });
board = new LiveBoard(state, {}); board.now = () => now;                                  // cold start: the first requests all arrive before the book is loaded
const first = await Promise.all([post("ord-lr00001"), post("ord-lr00002"), call("GET", "/paper/queue", { token: ING }), post("ord-lr00003")]);
out.firstStatus = first.map((r) => r.status);
out.firstStored = mem.get("paper:queue").map((x) => x.id).sort();
out.same = (await Promise.all([post("ord-same001"), post("ord-same001")])).map((r) => r.status).sort();      // the same id twice at once: one is queued
const many = await Promise.all(Array.from({ length: 30 }, (_, i) => post("ord-many" + String(i).padStart(3, "0"))));
out.codes = many.map((r) => r.status);
out.manyStored = mem.get("paper:queue").length;                                              // every 200 is really stored, and the cap held
for (let i = 0; i < 5; i++) await call("POST", "/paper/result", { token: ING, body: { id: "ord-many" + String(i).padStart(3, "0"), status: "done" } });      // room for 5
const mixed = await Promise.all([call("POST", "/paper/result", { token: ING, body: { id: "ord-lr00002", status: "refused", reasons: ["x"] } }), post("ord-mix0001"), call("POST", "/paper/kill", { token: READ, body: { on: true } })]);
out.mixed = mixed.map((r) => r.status);
out.after = { queue: mem.get("paper:queue").map((x) => x.id), results: mem.get("paper:results").map((x) => x.id), kill: mem.get("paper:kill") };
""")
    assert o["firstStatus"] == [200, 200, 200, 200] and o["firstStored"] == ["ord-lr00001", "ord-lr00002", "ord-lr00003"]
    assert o["same"] == [200, 409]
    assert o["codes"].count(200) == 16 and o["codes"].count(429) == 14 and o["manyStored"] == 20                    # 4 waiting + 16 = the cap of 20
    assert o["mixed"] == [200, 200, 200]
    assert "ord-lr00002" not in o["after"]["queue"] and "ord-mix0001" in o["after"]["queue"] and "ord-lr00002" in o["after"]["results"] and o["after"]["kill"] is True


@needs_node
def test_the_two_keys_of_an_order_move_together_or_not_at_all_and_the_caps_hold(tmp_path):
    o = run(tmp_path, r"""
failPutKey = "paper:seen";
out.fail = (await call("POST", "/paper/order", { token: READ, body: order("ord-pair0001") })).status;
out.queueWritten = mem.get("paper:queue") !== undefined;                                    // a separate put for the queue would have gone through
failPutKey = null;
for (let i = 0; i < 1030; i++) await call("POST", "/paper/result", { token: ING, body: { id: "ord-s" + String(i).padStart(6, "0"), status: "done" } });
out.seen = mem.get("paper:seen").length;
const fat = Array.from({ length: 5 }, () => "x".repeat(200));
for (let i = 0; i < 60; i++) await call("POST", "/paper/result", { token: ING, body: { id: "ord-w" + String(i).padStart(6, "0"), status: "refused", reasons: fat, fill: { symbol: "S".repeat(60), kind: "k".repeat(60), ts: "t".repeat(60) }, at: "a".repeat(40) } });
out.resultsBytes = JSON.stringify(mem.get("paper:results")).length;
""")
    assert o["fail"] == 500 and o["queueWritten"] is False and o["seen"] == 1000 and o["resultsBytes"] <= 100000


@needs_node
def test_a_package_order_is_checked_queued_once_and_its_per_leg_fills_come_back(tmp_path):
    o = run(tmp_path, r"""
const leg = (symbol, side, lots = 1, extra = {}) => ({ symbol, side, lots, ...extra });
const pkg = (id, extra = {}) => ({ id, side: "package", legs: [leg("NIFTY12NOV2624500PE", "sell"), leg("NIFTY12NOV2624400PE", "buy", 1, { ref: { bid: 30, ask: 32, at: 5, evil: 1 } })], strategy: "bull put spread", thesis: "support held at 24400 for an hour with falling put volume", ...extra });
out.good = await call("POST", "/paper/order", { token: READ, body: pkg("pkg-aaaa1", { net_limit: -1500, evil: "x" }) });
const bad = {};
for (const [k, v] of Object.entries({ none: pkg("pkg-bbbb1", { legs: [] }), many: pkg("pkg-bbbb2", { legs: Array.from({ length: 51 }, (_, i) => leg("NIFTY12NOV26" + (20000 + i * 50) + "PE", "buy")) }),
  side: pkg("pkg-bbbb3", { legs: [leg("NIFTY12NOV2624500PE", "short")] }), lots: pkg("pkg-bbbb4", { legs: [leg("NIFTY12NOV2624500PE", "buy", 0)] }), dup: pkg("pkg-bbbb5", { legs: [leg("NIFTY12NOV2624500PE", "buy"), leg("NIFTY12NOV2624500PE", "sell")] }),
  sym: pkg("pkg-bbbb6", { legs: [leg("<script>", "buy")] }), strat: pkg("pkg-bbbb7", { strategy: "" }), thesis: pkg("pkg-bbbb8", { thesis: "short" }), net: pkg("pkg-bbbb9", { net_limit: "x" }) })) bad[k] = (await call("POST", "/paper/order", { token: READ, body: v })).status;
out.bad = bad;
const q = (await call("GET", "/paper/queue", { token: ING })).body;
out.queue = q.orders;
out.pending = (await call("GET", "/paper/state", { token: READ })).body?.pending;
const fill = (symbol, kind) => ({ symbol, kind, qty: 65, price: 60, fees: 20, seq: 1, ts: "t", slip: { total_inr: 5, junk: 9 } });
out.post = await call("POST", "/paper/result", { token: ING, body: { id: "pkg-aaaa1", status: "filled", reasons: [], fill: fill("NIFTY12NOV2624500PE", "sto"), fills: [fill("NIFTY12NOV2624500PE", "sto"), fill("NIFTY12NOV2624400PE", "buy"), "junk"], at: "x" } });
out.state = (await call("GET", "/paper/state", { token: READ })).body;
""")
    assert o["good"]["status"] == 200 and all(v == 400 for v in o["bad"].values()), o["bad"]
    q = o["queue"][0]
    assert q["side"] == "package" and set(q) == {"id", "side", "legs", "strategy", "thesis", "net_limit", "queued_at"} and q["net_limit"] == -1500        # known fields only
    assert q["legs"][1]["ref"] == {"bid": 30, "ask": 32, "at": 5} and set(q["legs"][0]) == {"symbol", "side", "lots"}
    assert o["post"]["status"] == 200
    res = [r for r in o["state"]["results"] if r["id"] == "pkg-aaaa1"][0]
    assert len(res["fills"]) == 2 and res["fills"][1]["symbol"] == "NIFTY12NOV2624400PE" and "junk" not in res["fills"][0].get("slip", {}) and res["fills"][0]["slip"] == {"total_inr": 5}
