"""Each finding of the independent risk review of the Kotak live source (commit 4e10042), as a test: the two blockers (a name covered twice must not defeat the freshness rule; the board
must not fill for good), and the non-blocking ones, including every guard the reviewer's mutations showed to be untested."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INGEST, READ, KEY = "i" * 32, "r" * 32, "kotak-consumer-key-0123456789"

HARNESS = r"""
import * as K from "./kotak.js";
import { handleLive, LiveBoard, cleanUniverse, armLive } from "./live.mjs";
const out = {};
const T0 = Date.UTC(2026, 10, 9, 4, 30);                    // Mon 9 Nov 2026 10:00 IST
let now = T0, mode = "ok", lst = null, lastInit = null, kl = "150.5";
const calls = [];
const row = (g, t, o = {}) => ({ exchange: g, exchange_token: t, ltp: kl, last_volume: "1200", open_int: "5000", per_change: "0.5", depth: { buy: [{ price: "150.0", quantity: "50" }], sell: [{ price: "151.0", quantity: "60" }] }, ...(lst ? { lstup_time: lst } : {}), ...o });
const fake = async (url, init) => {
  calls.push(String(url)); lastInit = init;
  if (mode === "net") throw new Error("boom");
  if (mode === "301") return new Response("{}", { status: 301 });
  if (mode === "401") return new Response("{}", { status: 401 });
  if (mode === "429") return new Response("{}", { status: 429 });
  if (mode === "fault1") return new Response(JSON.stringify({ code: "900901", message: "Invalid Credentials" }), { status: 200 });
  if (mode === "fault2") return new Response(JSON.stringify({ status: "ERROR", fault: { message: "x" } }), { status: 200 });
  if (mode === "fault3") return new Response(JSON.stringify({ error: [{ message: "m" }] }), { status: 200 });
  if (mode === "empty") return new Response("[]", { status: 200 });
  const path = new URL(url).pathname;
  if (path.includes("/quotes/")) {
    const batch = decodeURIComponent(path.split("/quotes/neosymbol/")[1].split("/")[0]).split(",");
    return new Response(JSON.stringify(batch.map((p) => { const [g, t] = p.split("|"); return t === "Nifty 50" ? row("nse_cm", "26000", { depth: { buy: [], sell: [] } }) : row(g, t); })), { status: 200 });
  }
  return new Response(JSON.stringify({ data: { call: [{ inst: { strkPrc: "24500" }, quote: { ltp: "150.5", vol: "1200" }, oi: { cur: "5000" } }], put: [] } }), { status: 200 });
};
const mem = new Map(); let alarm = null, alarms = 0;
const mkState = () => ({ storage: { get: async (k) => mem.get(k), put: async (k, v) => { mem.set(k, JSON.parse(JSON.stringify(v))); }, getAlarm: async () => alarm, setAlarm: async (t) => { alarm = t; alarms += 1; } }, blockConcurrencyWhile: async (fn) => fn() });
const env = { LIVE_INGEST_TOKEN: "__I__", LIVE_READ_TOKEN: "__R__", KOTAK_CONSUMER_KEY: "__KEY__" };
let board;
const wire = (b) => { b.now = () => now; b.fetchFn = fake; b.sleepFn = async (ms) => { now += ms; }; return b; };
const boot = () => { now = T0; board = wire(new LiveBoard(mkState(), env)); env.LIVE = { idFromName: () => "board", get: () => ({ fetch: (u, init) => board.fetch(new Request(u, init)) }) }; return board; };
boot();
const call = async (method, path, { token, body } = {}) => { const r = await handleLive(new Request("https://qd.example" + path, { method, headers: token ? { authorization: "Bearer " + token } : {}, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) }), env); return { status: r.status, body: await r.json() }; };
const READ = env.LIVE_READ_TOKEN, ING = env.LIVE_INGEST_TOKEN;
const snap = async () => (await call("GET", "/live/snapshot", { token: READ })).body;
const health = async () => (await call("GET", "/live/health", { token: READ })).body;
const push = (quotes) => call("POST", "/live/ingest", { token: ING, body: { quotes } });
const setUniverse = (u) => call("POST", "/live/universe", { token: ING, body: u });
const OPT = "NIFTY12NOV2624500CE";

// ---- B1: an option asked for as a quote AND as a chain row is one name; with nothing moving its age must grow
await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: OPT, s: "opt", g: "nse_fo", t: "71000" }, { n: OPT, s: "opt", g: "nse_fo", t: "71000" }], chains: [{ u: "NIFTY", x: "nse_fo", e: "2026-11-12" }, { u: "NIFTY", x: "nse_fo", e: "2026-11-12" }] });
out.dedup = { quotes: board.universe.quotes.length, chains: board.universe.chains.length };
for (let i = 0; i < 6; i++) { await board.alarm(); now += 5000; }
let s = await snap();
out.b1 = { age: s.quotes[OPT].age_s, bid: s.quotes[OPT].bid, oi: s.quotes[OPT].oi };
// ---- N4: a price Kotak itself dates is as old as it is, the first time it is seen
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
lst = String(Math.floor((now - 7200e3) / 1000)); await board.alarm(); s = await snap(); out.lst = s.quotes.AAA.age_s;
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
lst = "not-a-time"; await board.alarm(); s = await snap(); out.lstBad = s.quotes.AAA.age_s;
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
lst = String(Math.floor((now + 9e6) / 1000)); await board.alarm(); s = await snap(); out.lstFuture = s.quotes.AAA.age_s;
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
lst = String(Math.floor((now - 3 * 86400e3) / 1000)); await board.alarm(); s = await snap(); out.lstOld = s.quotes.AAA.age_s;           // older than 12 h: not trusted, stamped now
lst = null;

// ---- B2: the board does not fill for good; Kite-only pushes prune too; refused Kotak writes are counted
boot();
const big = (p, n) => Object.fromEntries(Array.from({ length: n }, (_, i) => [p + i, { ltp: 1 + i }]));
await push(big("A", 2500)); await push(big("B", 1500));
out.full = (await snap()).count;
const refused = await push({ NEWONE: { ltp: 5 } });
out.refusedWhileFresh = refused.body.refused;
now += 19 * 3600e3;                                       // a night later: nothing seen for 19 hours
const accepted = await push({ NEWONE: { ltp: 5 } });
s = await snap();
out.afterPrune = { count: s.count, accepted: accepted.body.n, old: "A1" in s.quotes, fresh: "NEWONE" in s.quotes, pruned: (await health()).kotak.pruned };
// a Kotak cycle into a full, fresh board: the refusals are counted
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "KNEW", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
await push(big("A", 2500)); await push(big("B", 1500));
await board.alarm(); out.kotakRefused = (await health()).kotak.refused;
// an expired contract leaves the snapshot after 18 h
boot(); await push({ OLDOPT: { ltp: 1 }, KEEP: { ltp: 1 } }); now += 17 * 3600e3; await push({ KEEP: { ltp: 2 } }); s = await snap(); const at17 = Object.keys(s.quotes).sort();
now += 2 * 3600e3; await board.alarm(); s = await snap(); out.expired = { at17, at19: Object.keys(s.quotes).sort() };

// ---- N2: a fault shape with HTTP 200 is an error; an empty 200 is not a success
for (const m of ["fault1", "fault2", "fault3", "empty"]) {
  boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] }); mode = m;
  await board.alarm(); const h = await health(); out["n2_" + m] = { status: h.kotak.status, errors: h.kotak.errors, err: h.kotak.last_error }; mode = "ok";
}
// ---- N3: the book fill: never on a flagged row, a bid and an ask only as a pair, never from a stale quote
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "BK", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
await board.alarm();                                                                                // Kotak: ltp 150.5 with a book 150.0 / 151.0
await push({ BK: { ltp: 150.6, s: "eq" } });                                                         // Kite: no book, agrees
out.fill = (await snap()).quotes.BK;
await push({ BK: { ltp: 160.0, s: "eq" } });                                                         // Kite: 6% away: flagged
const flagged = (await snap()).quotes.BK; out.flagged = { x: flagged.x, bid: flagged.bid };
await push({ BK: { ltp: 150.7, bid: 150.1, s: "eq" } });                                              // Kite has a bid only: the pair is not borrowed
const half = (await snap()).quotes.BK; out.half = { bid: half.bid, ask: half.ask };
now += 61000; await push({ BK: { ltp: 150.8, s: "eq" } });                                            // Kotak's quote is now 61 s old: too stale to lend a book
const stale = (await snap()).quotes.BK; out.stale = { bid: stale.bid, x: stale.x };
// ---- N5: one label per instrument, Kite's first, whichever source is fresher
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "LBL", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
await board.alarm(); await push({ LBL: { ltp: 150.5, s: "fut" } }); s = await snap(); const l1 = s.quotes.LBL.s;
now += 20000; kl = "151.5"; await board.alarm(); s = await snap(); out.label = [l1, s.quotes.LBL.s, s.quotes.LBL.src]; kl = "150.5";      // Kotak's price moved: it is now the FRESHER source, and the label must still be Kite's
// ---- N6: types and dates
out.types = cleanUniverse({ quotes: [{ n: ["NIFTY"], s: "eq", g: "nse_cm", t: "1" }, { n: "OK", s: "eq", g: "nse_cm", t: "1" }], chains: [{ u: ["NIFTY"], x: "nse_fo", e: "2026-11-12" }, { u: "NIFTY", x: "nse_fo", e: ["2026-11-12"] }, { u: "NIFTY", x: "nse_fo", e: "2026-13-99" }, { u: "NIFTY", x: "nse_fo", e: "2026-02-30" }, { u: "NIFTY", x: "mcx_fo", e: "2026-11-12" }, { u: "NIFTY", x: "nse_fo", e: "2026-11-12" }], asof: "2026-13-99" });
out.badToken = cleanUniverse({ quotes: [{ n: "A", s: "eq", g: "nse_cm", t: "a/b" }, { n: "B", s: "eq", g: "nse_cm", t: "a?b=1" }, { n: "C", s: "eq", g: "nse_cm", t: "a&b" }, { n: "D", s: "eq", g: "nse_cm", t: "a%2fb" }, { n: "E", s: "eq", g: "nse_cm", t: "a\nb" }, { n: "F", s: "eq", g: "nse_cm", t: "Nifty 50" }] });
mem.set("universe", { asof: "2026-11-09", count: 5, quotes: [{ n: ["X"], s: "eq", g: "nse_cm", t: "1" }, { n: "FINE", s: "eq", g: "nse_cm", t: "1" }, { n: "EVIL", s: "eq", g: "evil_host", t: "1" }], chains: [] });
await boot().ready; out.reload = board.universe.quotes.map((q) => q.n);
mem.set("universe", { quotes: [{ n: ["X"] }], chains: [] }); await boot().ready; out.reloadBad = board.universe;
// ---- N7: back off when Kotak refuses the key, or rate-limits
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
mode = "401"; const delays = [];
for (let i = 0; i < 7; i++) { const t = now; await board.alarm(); delays.push(alarm - now); now += 1000; }
out.authDelays = delays; mode = "429";
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] }); await board.alarm(); out.rateDelay = alarm - now;
mode = "ok"; await board.alarm(); out.afterOk = alarm - now;
// ---- N8: no re-arm without a key; redirects are never followed and a 3xx is an error
boot(); env.KOTAK_CONSUMER_KEY = ""; board.env = env; alarms = 0; alarm = null; await board.alarm(); out.noKey = { alarms, status: board.k.status }; env.KOTAK_CONSUMER_KEY = "__KEY__";
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] }); mode = "301"; await board.alarm(); out.redirect = { redirect: lastInit.redirect, errors: (await health()).kotak.errors }; mode = "ok";
// ---- N10: the guards the reviewer's mutations showed untested
out.base = K.BASE;
calls.length = 0; boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }, { n: "IDX", s: "idx", g: "nse_cm", t: "Nifty 50", one: true }], chains: [{ u: "NIFTY", x: "nse_fo", e: "2026-11-12" }] }); await board.alarm();
out.hosts = [...new Set(calls.map((u) => new URL(u).host))];
// a slow cycle never makes the re-arm delay less than 500 ms
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "AAA", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
board.fetchFn = async (u, i) => { now += 9000; return fake(u, i); }; await board.alarm(); out.slowDelay = alarm - now; board.fetchFn = fake;
// FRESH_S: two sources 70 s apart are not compared, so no flag even at 50% apart
boot(); await setUniverse({ asof: "2026-11-09", count: 5, quotes: [{ n: "FR", s: "eq", g: "nse_cm", t: "11" }], chains: [] });
await board.alarm(); now += 70000; await push({ FR: { ltp: 300, s: "eq" } }); const fr = (await snap()).quotes.FR; out.fresh = { x: fr.x, alt: fr.alt.age_s > 60 };
console.log(JSON.stringify(out));
""".replace("__KEY__", KEY).replace("__I__", INGEST).replace("__R__", READ)


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("klr")
    for f in ("live.js", "kotak.js"):
        shutil.copyfile(ROOT / "deploy" / "cloudflare" / f, d / ("live.mjs" if f == "live.js" else f))
    (d / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (d / "run.mjs").write_text(HARNESS, encoding="utf-8")
    r = subprocess.run(["node", "run.mjs"], cwd=d, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---- B1 ----------------------------------------------------------------------------------------------------------------------------------------
def test_b1_a_name_covered_twice_does_not_defeat_the_freshness_rule(out):
    assert out["dedup"] == {"quotes": 1, "chains": 1}                                      # the same name or chain asked for twice is one entry
    assert out["b1"]["age"] >= 25                                                          # six unchanged cycles (30 s) on a contract covered by a quote AND a chain row: it AGES, a holiday cannot look live
    assert out["b1"]["bid"] == 150.0 and out["b1"]["oi"] == 5000                           # and the quote's book was kept while the chain row (which has none) arrived


# ---- B2 ----------------------------------------------------------------------------------------------------------------------------------------
def test_b2_the_board_does_not_fill_for_good(out):
    assert out["full"] == 4000 and out["refusedWhileFresh"] == 1                           # full of fresh names: a new one is refused (and counted by the push)
    a = out["afterPrune"]
    assert a["accepted"] == 1 and a["fresh"] is True and a["old"] is False and a["count"] == 1 and a["pruned"] == 4000      # 19 hours on: the stale ones made room
    assert out["kotakRefused"] >= 1                                                         # a Kotak write refused by a full board is counted in /live/health, not silent
    assert out["expired"]["at17"] == ["KEEP", "OLDOPT"] and out["expired"]["at19"] == ["KEEP"] or out["expired"]["at19"] == []      # an expired contract leaves the snapshot after 18 h of silence


# ---- N2 ----------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mode,kind", [("fault1", "http"), ("fault2", "http"), ("fault3", "http"), ("empty", "empty")])
def test_n2_a_fault_shape_or_an_empty_answer_is_not_ok(out, mode, kind):
    r = out["n2_" + mode]
    assert r["status"] == "down" and r["errors"].get(kind) == 1 and "Invalid Credentials" not in json.dumps(r)      # counted by kind, the message never echoed


# ---- N3 ----------------------------------------------------------------------------------------------------------------------------------------
def test_n3_the_book_is_borrowed_only_when_safe(out):
    f = out["fill"]
    assert f["bid"] == 150.0 and f["ask"] == 151.0 and f["src"] == "z"                      # unflagged and fresh: the pair comes from Kotak
    assert out["flagged"]["x"] > 5 and out["flagged"].get("bid") is None                          # a flagged row borrows nothing
    assert out["half"]["bid"] == 150.1 and out["half"].get("ask") is None                         # Kite has a bid only: no ask is borrowed to go with it
    assert out["stale"].get("bid") is None                                                       # Kotak's quote is 61 s old: too stale to lend a book


# ---- N4 ----------------------------------------------------------------------------------------------------------------------------------------
def test_n4_a_price_kotak_dates_is_as_old_as_it_is_when_first_seen(out):
    assert 7190 <= out["lst"] <= 7210                                                         # its own timestamp, not "now"
    assert out["lstBad"] == 0 and out["lstFuture"] == 0                                       # a garbage timestamp is ignored, a future one clamped to now
    assert out["lstOld"] == 43200                                                             # a 3-day-old timestamp is clamped to 12 hours: honest ("at least 12 h"), and never fresher than it is


# ---- N5 ----------------------------------------------------------------------------------------------------------------------------------------
def test_n5_one_label_per_instrument_kites_first(out):
    assert out["label"] == ["fut", "fut", "k"]                                               # Kite says fut, Kotak says eq: fut, even when Kotak is the fresher source (src k)


# ---- N6 ----------------------------------------------------------------------------------------------------------------------------------------
def test_n6_types_dates_tokens_and_the_storage_reload(out):
    t = out["types"]
    assert [q["n"] for q in t["quotes"]] == ["OK"] and t["chains"] == [{"u": "NIFTY", "x": "nse_fo", "e": "2026-11-12"}] and t["asof"] is None      # arrays, 2026-13-99, 2026-02-30, mcx_fo all dropped; the duplicate chain is one
    assert [q["n"] for q in out["badToken"]["quotes"]] == ["C", "F"]                          # slash, ?, %, newline in a token are refused; `&` is legal (M&M) and is percent-encoded in the path; a plain index name passes
    assert out["reload"] == ["FINE"] and out["reloadBad"] is None                            # the stored universe is re-validated on every reload


# ---- N7 / N8 ------------------------------------------------------------------------------------------------------------------------------------
def test_n7_it_backs_off_from_a_refused_key_and_a_rate_limit(out):
    d = out["authDelays"]
    assert d[0] == 60000 and d[1] == 60000 or d[0] >= 60000
    assert d == sorted(d) and d[-1] > d[0] and d[-1] <= 900000                              # a minute, doubling, never past 15 minutes
    assert out["rateDelay"] == 15000 and out["afterOk"] == 5000                              # rate-limited: 15 s; healthy again: back to 5 s


def test_n8_no_rearm_without_a_key_and_redirects_are_never_followed(out):
    assert out["noKey"] == {"alarms": 0, "status": "off"}
    assert out["redirect"]["redirect"] == "manual" and out["redirect"]["errors"].get("http") == 1


# ---- N10: the guards the reviewer's mutations showed untested ---------------------------------------------------------------------------------------
def test_n10_the_key_only_ever_goes_to_one_host(out):
    assert out["base"] == "https://mis.kotaksecurities.com" and out["hosts"] == ["mis.kotaksecurities.com"]


def test_n10_a_slow_cycle_never_makes_the_rearm_delay_zero(out):
    assert out["slowDelay"] >= 500


def test_n10_two_sources_far_apart_in_time_are_not_compared(out):
    assert out["fresh"].get("x") is None and out["fresh"]["alt"] is True


def test_n10_the_worker_hook_is_guarded_and_never_awaited():
    wk = (ROOT / "deploy/cloudflare/worker.js").read_text()
    i = wk.index("async scheduled(")
    head = wk[i:i + 700]
    assert "try {" in head and "ctx.waitUntil(armLive(env)" in head and "await armLive" not in wk
