"""The Kotak live source inside the relay (deploy/cloudflare/kotak.js and the two-source board in live.js), run under Node with a fake Kotak that answers in the shapes
quantdesk/intraday/kotak.py parses, a fake Durable Object state with an alarm, and a clock the test controls. No network, no real key."""
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
import { handleLive, LiveBoard, cleanUniverse, armLive, needsUniverse } from "./live.mjs";
const out = {};
const MON_10AM = Date.UTC(2026, 10, 9, 4, 30);        // Mon 9 Nov 2026 10:00 IST
const SAT_10AM = Date.UTC(2026, 10, 7, 4, 30);
// ---- pure helpers
out.num = [K.num("166.7500"), K.num(""), K.num("-"), K.num(null), K.num(undefined), K.num("x"), K.num(true), K.num(0)].map((v) => (Number.isNaN(v) ? "nan" : v));
out.optionName = [K.optionName("NIFTY", "2026-11-12", 24500, "CE"), K.optionName("BANKNIFTY", "2026-12-29", 52000.5, "PE")];
out.enc = K.enc("nse_cm|Nifty 50,nse_cm|2885");
out.session = [K.inSession(MON_10AM), K.inSession(SAT_10AM), K.inSession(Date.UTC(2026, 10, 9, 3, 29)), K.inSession(Date.UTC(2026, 10, 9, 3, 30)), K.inSession(Date.UTC(2026, 10, 9, 10, 4)), K.inSession(Date.UTC(2026, 10, 9, 10, 5))];
const q = { ltp: "2900.10", last_volume: "1000", open_int: "250", per_change: "-0.1", depth: { buy: [{ price: "2900.00", quantity: "50", orders: "2" }], sell: [{ price: "2900.20", quantity: "60", orders: "3" }] } };
out.parse = K.parseQuote(q);
out.parseEmptyBook = K.parseQuote({ ltp: "10", depth: { buy: [], sell: [] } });
out.parseCrossed = K.parseQuote({ ltp: "10", depth: { buy: [{ price: "11" }], sell: [{ price: "10" }] } });
out.parseZero = K.parseQuote({ ltp: "0" });
out.parseChangeFallback = K.parseQuote({ ltp: "110", change: "10" }).chg;
out.parseChain = K.parseChain({ data: { call: [{ inst: { strkPrc: "24500", neoSymbol: "nse_fo|1" }, quote: { ltp: "150.5", vol: "1200" }, oi: { cur: "5000", prev: "4000", chg: "3" } }, { inst: { strkPrc: "0" }, quote: { ltp: "1" } }], put: [{ instrument: { strikePrice: "24500" }, quote: { ltp: "140", volume: "900" }, openInterest: { current: "7000" } }, { inst: { strkPrc: "24400" }, quote: { ltp: "-" } }] } });
// ---- the plan
const big = { quotes: [], chains: [{ u: "NIFTY", x: "nse_fo", e: "2026-11-12" }] };
for (let i = 0; i < 6; i++) big.quotes.push({ n: "IDX" + i, s: "idx", g: "nse_cm", t: "Index " + i, one: true });
for (let i = 0; i < 1500; i++) big.quotes.push({ n: "S" + i, s: "eq", g: "nse_cm", t: String(1000 + i) });
const seen = new Set(); let cursor = 0, maxCalls = 0, cycles = 0;
while (seen.size < 6 + 1500 + 1 && cycles < 50) { const p = K.plan(big, cursor); maxCalls = Math.max(maxCalls, p.calls.length); for (const c of p.calls) for (const it of c.kind === "q" ? c.items : [c.chain]) seen.add(it.n || it.u); cursor = p.next; cycles++; }
out.plan = { total: K.plan(big, 0).total, maxCalls, cycles, covered: seen.size, expected: 6 + 1500 + 1 };
const small = K.plan({ quotes: [{ n: "A", s: "eq", g: "nse_cm", t: "1" }], chains: [] }, 7);
out.planSmall = { calls: small.calls.length, next: small.next };
// ---- a fake Kotak
const calls = []; let mode = "ok"; let now = MON_10AM;
const fakeFetch = async (url, init) => {
  calls.push({ url: String(url), auth: init && init.headers && init.headers.Authorization, at: now });
  if (mode === "net") throw new Error("boom https://mis.kotaksecurities.com secret");
  if (mode === "401") return new Response("{}", { status: 401 });
  if (mode === "429") return new Response("{}", { status: 429 });
  if (mode === "html") return new Response("<html>", { status: 200 });
  if (mode === "err") return new Response(JSON.stringify({ Error: "bad key", errMsg: "x" }), { status: 200 });
  const u = new URL(url); const path = u.pathname;
  if (path.includes("/quotes/neosymbol/")) {
    const batch = decodeURIComponent(path.split("/quotes/neosymbol/")[1].split("/")[0]);
    const rows = [];
    for (const part of batch.split(",")) {
      const [g, t] = part.split("|");
      if (t === "Nifty 50") rows.push({ exchange: "nse_cm", exchange_token: "26000", ltp: fakeFetch.nifty || "24500.50", per_change: "0.4", depth: { buy: [], sell: [] } });
      else if (t === "2885") rows.push({ exchange: "nse_cm", exchange_token: "2885", ltp: fakeFetch.rel || "2900.10", last_volume: "1000", open_int: "0", per_change: "-0.1", depth: { buy: [{ price: "2900.00", quantity: "50" }], sell: [{ price: "2900.20", quantity: "60" }] } });
      else if (t === "51000") rows.push({ exchange: "nse_fo", exchange_token: "51000", ltp: "2905.00", last_volume: "5000", open_int: "99000", per_change: "-0.05", depth: { buy: [], sell: [] } });
    }
    return new Response(JSON.stringify(rows), { status: 200 });
  }
  if (path.includes("option-chain")) {
    return new Response(JSON.stringify({ data: { call: [{ inst: { strkPrc: "24500", neoSymbol: "nse_fo|1" }, quote: { ltp: fakeFetch.ce || "150.5", vol: "1200" }, oi: { cur: "5000", prev: "4000", chg: "3" } }], put: [{ inst: { strkPrc: "24500", neoSymbol: "nse_fo|2" }, quote: { ltp: "140", vol: "900" }, oi: { cur: "7000", prev: "6000" } }] } }), { status: 200 });
  }
  return new Response("{}", { status: 404 });
};
const poller = (o) => new K.KotakPoller({ key: KEY, fetchFn: fakeFetch, now: () => now, sleepFn: async (ms) => { now += ms; }, ...o });
const U = { asof: "2026-11-09", count: 5, quotes: [{ n: "RELIANCE", s: "eq", g: "nse_cm", t: "2885" }, { n: "RELIANCE-FUT", s: "fut", g: "nse_fo", t: "51000" }, { n: "NIFTY", s: "idx", g: "nse_cm", t: "Nifty 50", one: true }], chains: [{ u: "NIFTY", x: "nse_fo", e: "2026-11-12" }] };
const KEY = "__KEY__";
// ---- a cycle
let r = await K.runCycle(poller(), U, 0);
out.cycle = { ok: r.ok, failed: r.failed, names: r.updates.map((u) => u[0]).sort(), rel: r.updates.find((u) => u[0] === "RELIANCE")[1], nifty: r.updates.find((u) => u[0] === "NIFTY")[1], ce: r.updates.find((u) => u[0] === "NIFTY12NOV2624500CE")[1] };
out.calls = { n: calls.length, auth: [...new Set(calls.map((c) => c.auth))], paths: [...new Set(calls.map((c) => new URL(c.url).pathname.split("/").slice(0, 4).join("/")))], spaced: calls.every((c, i) => i === 0 || c.at - calls[i - 1].at >= 0), spaceUrl: calls.find((c) => c.url.includes("Nifty")).url.includes("Nifty%2050") };
// the pacing, on the REAL clock (a fake clock jumps for every sleeping worker at once): request starts are at least MIN_GAP_MS apart, 4 workers or not
const realStarts = []; const realFetch = async () => { realStarts.push(performance.now()); return new Response("[]", { status: 200 }); };
const U12 = { quotes: Array.from({ length: 300 }, (_, i) => ({ n: "S" + i, s: "eq", g: "nse_cm", t: String(i) })), chains: [] };
await K.runCycle(new K.KotakPoller({ key: KEY, fetchFn: realFetch }), U12, 0);
out.gaps = realStarts.length === 12 && realStarts.slice(1).every((t, i) => t - realStarts[i] >= K.MIN_GAP_MS - 8);
for (const m of ["net", "401", "429", "html", "err"]) {
  mode = m; calls.length = 0;
  const rr = await K.runCycle(poller(), m === "401" ? big : U, 0);
  out["fail_" + m] = { ok: rr.ok, failed: rr.failed, errors: rr.errors, calls: calls.length, leaks: JSON.stringify(rr).includes(KEY) || JSON.stringify(rr).includes("mis.kotak") };
}
mode = "ok";
// ---- the board: a universe pushed through the relay, an alarm, two sources
const mem = new Map(); let alarm = null;
const state = { storage: { get: async (k) => mem.get(k), put: async (k, v) => { mem.set(k, JSON.parse(JSON.stringify(v))); }, getAlarm: async () => alarm, setAlarm: async (t) => { alarm = t; } }, blockConcurrencyWhile: async (fn) => fn() };
const env = { LIVE_INGEST_TOKEN: "__I__", LIVE_READ_TOKEN: "__R__", KOTAK_CONSUMER_KEY: KEY };
let board = new LiveBoard(state, env);
const wire = (b) => { b.now = () => now; b.fetchFn = fakeFetch; b.sleepFn = async (ms) => { now += ms; }; return b; };
wire(board);
env.LIVE = { idFromName: () => "board", get: () => ({ fetch: (u, init) => board.fetch(new Request(u, init)) }) };
const call = async (method, path, { token, body } = {}) => {
  const rr = await handleLive(new Request("https://qd.example" + path, { method, headers: token ? { authorization: "Bearer " + token } : {}, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) }), env);
  return { status: rr.status, body: await rr.json() };
};
const snap = async () => (await call("GET", "/live/snapshot", { token: READ })).body;
const READ = env.LIVE_READ_TOKEN, ING = env.LIVE_INGEST_TOKEN;
out.universeBad = [(await call("POST", "/live/universe", { token: READ, body: U })).status, (await call("POST", "/live/universe", { token: ING, body: { quotes: [{ n: "bad name", s: "eq", g: "nse_cm", t: "1" }] } })).status];
out.universeOk = await call("POST", "/live/universe", { token: ING, body: { ...U, quotes: [...U.quotes, { n: "EVIL", s: "eq", g: "mcx_fo", t: "1" }, { n: "X Y", s: "eq", g: "nse_cm", t: "1" }] } });
out.cleanUniverse = cleanUniverse({ quotes: [{ n: "A", s: "eq", g: "nse_cm", t: "1" }], chains: [{ u: "NIFTY", x: "nse_fo", e: "2026-11-12" }, { u: "NIFTY", x: "nse_fo", e: "tomorrow" }], count: 999 });
out.alarmArmed = alarm !== null;
// outside the session nothing is called
now = SAT_10AM; calls.length = 0; await board.alarm();
out.saturday = { calls: calls.length, status: board.k.status, rearmed: alarm - now };
now = MON_10AM; calls.length = 0; await board.alarm();
out.monday = { calls: calls.length, status: board.k.status, rearmed: alarm - now };
let s = await snap();
out.kotakOnly = { rel: s.quotes.RELIANCE, ce: s.quotes.NIFTY12NOV2624500CE, n: s.count };
// Kite pushes the same instruments: two sources
now += 2000;
await call("POST", "/live/ingest", { token: ING, body: { quotes: { RELIANCE: { ltp: 2900.15, bid: 2900.05, ask: 2900.25, s: "eq" }, NIFTY: { ltp: 24500.6, s: "idx" }, "RELIANCE-FUT": { ltp: 2990.0, s: "fut" }, NIFTY12NOV2624500CE: { ltp: 160.0, s: "opt" } } } });
s = await snap();
out.two = { rel: s.quotes.RELIANCE, fut: s.quotes["RELIANCE-FUT"], ce: s.quotes.NIFTY12NOV2624500CE, nifty: s.quotes.NIFTY };
const h2 = (await call("GET", "/live/health", { token: READ })).body;
out.healthTwo = { both: h2.both, disagree: h2.disagree, kiteN: h2.kite.n, kotakN: h2.kotak.n };
// the kotak quote does not refresh when nothing changed; kite's does when it ticks
now += 30000; calls.length = 0; await board.alarm();
await call("POST", "/live/ingest", { token: ING, body: { quotes: { RELIANCE: { ltp: 2900.2, s: "eq" } } } });
s = await snap();
out.aged = { rel: s.quotes.RELIANCE, nifty: s.quotes.NIFTY };
// a holiday: the same prices keep coming, so every age grows
const aged = [];
for (let i = 0; i < 3; i++) { now += 20000; await board.alarm(); }
s = await snap();
out.holiday = { niftyAge: s.quotes.NIFTY.age_s, ceAge: s.quotes.NIFTY12NOV2624500CE.age_s };
// a price that moves is refreshed
fakeFetch.nifty = "24510.00"; now += 5000; await board.alarm(); s = await snap();
out.moved = { age: s.quotes.NIFTY.age_s, ltp: s.quotes.NIFTY.ltp };
// health
const h = (await call("GET", "/live/health", { token: READ })).body;
out.health = { kite: h.kite.n > 0, kotakStatus: h.kotak.status, configured: h.kotak.configured, both: h.both, disagree: h.disagree, universe: h.kotak.universe, noKey: !JSON.stringify(h).includes(KEY), cycles: h.kotak.cycles };
out.healthAuth = (await call("GET", "/live/health")).status;
// the alarm survives a dead Kotak and re-arms, and says so
mode = "net"; now += 5000; alarm = null; await board.alarm();
out.down = { status: board.k.status, rearmed: alarm !== null, err: board.k.last_error };
mode = "401"; await board.alarm(); out.auth = { status: board.k.status, err: board.k.last_error };
mode = "ok";
// the universe survives a restart; quotes do not
board = wire(new LiveBoard(state, env));
await board.ready;
out.restart = { universe: board.universe === null ? 0 : board.universe.quotes.length, quotes: board.quotes.size };
// not configured: no alarm, no calls
const idle = new LiveBoard({ ...state, storage: { ...state.storage, getAlarm: async () => null, setAlarm: async () => { throw new Error("no alarm for an unconfigured poller"); } } }, { ...env, KOTAK_CONSUMER_KEY: "" });
await idle.arm(); calls.length = 0; await idle.alarm(); out.unconfigured = { calls: calls.length, status: idle.k.status };
// the relay asks for a rebuild of a stale universe, at most once in 40 minutes, only on a weekday morning, only when the poller is on
const mk = (e) => { const m2 = new Map(); const b = new LiveBoard({ storage: { get: async (k) => m2.get(k), put: async (k, v) => { m2.set(k, v); }, getAlarm: async () => null, setAlarm: async () => {} }, blockConcurrencyWhile: async (fn) => fn() }, e); return b; };
const ask = async (b, t) => { b.now = () => t; const r = await b.fetch(new Request("https://live/needs-universe", { method: "POST" })); return (await r.json()).need; };
const nb = mk(env), MON_0805 = Date.UTC(2026, 10, 9, 2, 35);
out.needs = [await ask(nb, MON_0805), await ask(nb, MON_0805 + 10 * 60000), await ask(nb, MON_0805 + 41 * 60000), await ask(nb, Date.UTC(2026, 10, 9, 1, 30)), await ask(nb, Date.UTC(2026, 10, 7, 3, 0)), await ask(mk({ ...env, KOTAK_CONSUMER_KEY: "" }), MON_0805 + 3600000 * 3)];
const fresh = mk(env); await fresh.fetch(new Request("https://live/universe", { method: "POST", body: JSON.stringify({ asof: "2026-11-09", quotes: [{ n: "A", s: "eq", g: "nse_cm", t: "1" }], chains: [], count: 5 }) }));
out.needsFresh = await ask(fresh, MON_0805);
const stale = mk(env); await stale.fetch(new Request("https://live/universe", { method: "POST", body: JSON.stringify({ asof: "2026-11-06", quotes: [{ n: "A", s: "eq", g: "nse_cm", t: "1" }], chains: [], count: 5 }) }));
out.needsStale = await ask(stale, MON_0805);
out.needsViaWorker = [await needsUniverse({}), await needsUniverse(env)];
// armLive from the cron
out.armLive = [await armLive({}), await armLive({ ...env, KOTAK_CONSUMER_KEY: "" }), await armLive(env)];
console.log(JSON.stringify(out));
""".replace("__KEY__", KEY).replace("__I__", INGEST).replace("__R__", READ)


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("kl")
    for f in ("live.js", "kotak.js", "series.js"):
        shutil.copyfile(ROOT / "deploy" / "cloudflare" / f, d / ("live.mjs" if f == "live.js" else f))
    (d / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (d / "run.mjs").write_text(HARNESS, encoding="utf-8")
    r = subprocess.run(["node", "run.mjs"], cwd=d, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_numbers_names_session_and_encoding(out):
    assert out["num"] == [166.75, "nan", "nan", "nan", "nan", "nan", "nan", 0]
    assert out["optionName"] == ["NIFTY12NOV2624500CE", "BANKNIFTY29DEC2652000.5PE"]
    from quantdesk.data.kite_universe import option_name                                  # the Python side (Kite's universe) names an option exactly as the Worker (Kotak's) does
    assert [option_name("NIFTY", "2026-11-12", 24500.0, "CE"), option_name("BANKNIFTY", "2026-12-29", 52000.5, "PE")] == out["optionName"]
    assert out["enc"] == "nse_cm|Nifty%2050,nse_cm|2885"                                  # spaces encoded, the bar and the comma literal
    assert out["session"] == [True, False, False, True, True, False]                      # 09:00 to 15:35 IST, weekdays: 08:59 out, 09:00 in, 15:34 in, 15:35 out


def test_a_quote_becomes_the_relays_shape(out):
    assert out["parse"] == {"ltp": 2900.1, "bid": 2900.0, "ask": 2900.2, "bid_qty": 50, "ask_qty": 60, "vol": 1000, "oi": 250, "chg": -0.1}
    assert out["parseEmptyBook"] == {"ltp": 10}                                          # an empty book: no bid or ask, not a zero
    assert out["parseCrossed"] == {"ltp": 10}                                            # a crossed book is not shown
    assert out["parseZero"] is None and out["parseChangeFallback"] == pytest.approx(10 / 100 * 100)
    assert out["parseChain"] == [{"strike": 24500, "side": "CE", "ltp": 150.5, "vol": 1200, "oi": 5000}, {"strike": 24500, "side": "PE", "ltp": 140, "vol": 900, "oi": 7000}]


def test_the_plan_never_exceeds_the_subrequest_limit_and_covers_everything(out):
    p = out["plan"]
    assert p["total"] > 40 and p["maxCalls"] <= 40 and p["covered"] == p["expected"] and p["cycles"] <= 3          # rotated, every item reached within a few cycles
    assert out["planSmall"] == {"calls": 1, "next": 0}


def test_a_cycle_maps_quotes_by_token_indices_by_name_and_chains_to_option_names(out):
    c = out["cycle"]
    assert c["ok"] == 3 and c["failed"] == 0 and c["names"] == ["NIFTY", "NIFTY12NOV2624500CE", "NIFTY12NOV2624500PE", "RELIANCE", "RELIANCE-FUT"]
    assert c["rel"]["bid"] == 2900.0 and c["rel"]["s"] == "eq" and c["nifty"]["s"] == "idx" and c["nifty"]["chg"] == 0.4 and c["ce"] == {"ltp": 150.5, "vol": 1200, "oi": 5000, "s": "opt"}


def test_requests_carry_the_key_only_in_the_header_use_the_two_read_endpoints_and_are_paced(out):
    c = out["calls"]
    assert c["auth"] == ["kotak-consumer-key-0123456789"] and c["spaceUrl"] and out["gaps"]
    assert set(c["paths"]) <= {"/script-details/1.0/quotes", "/market-data/1.0/watchlist"}


@pytest.mark.parametrize("mode,kind", [("net", "net"), ("401", "auth"), ("429", "rate"), ("html", "shape"), ("err", "http")])
def test_each_failure_is_counted_by_kind_and_never_leaks_the_key_or_the_url(out, mode, kind):
    f = out["fail_" + mode]
    assert f["ok"] == 0 and f["failed"] >= 1 and f["errors"].get(kind) == f["failed"] and not f["leaks"]
    if mode == "401":
        assert f["calls"] <= 4                                                           # a refused key is refused for every call: of 40 planned, only the 4 already in flight were asked


def test_the_universe_endpoint_needs_the_ingest_key_and_keeps_only_well_formed_entries(out):
    assert out["universeBad"] == [401, 400]
    assert out["universeOk"]["status"] == 200 and out["universeOk"]["body"]["quotes"] == 3 and out["universeOk"]["body"]["chains"] == 1 and out["universeOk"]["body"]["kotak"] is True
    assert out["cleanUniverse"]["chains"] == [{"u": "NIFTY", "x": "nse_fo", "e": "2026-11-12"}] and out["cleanUniverse"]["count"] == 30 and out["cleanUniverse"]["asof"] is None


def test_it_polls_only_in_the_session_and_always_re_arms(out):
    assert out["alarmArmed"] is True
    assert out["saturday"]["calls"] == 0 and out["saturday"]["status"] == "idle" and out["saturday"]["rearmed"] == 60000      # idle: look again in a minute
    assert out["monday"]["calls"] >= 3 and out["monday"]["status"] == "ok" and 500 <= out["monday"]["rearmed"] <= 5000
    assert out["down"]["status"] == "down" and out["down"]["rearmed"] is True and out["down"]["err"]               # a dead Kotak never kills the alarm
    assert out["auth"]["status"] == "auth" and out["auth"]["err"] == "Kotak refused the key"


def test_kotak_alone_fills_the_board_with_its_source(out):
    k = out["kotakOnly"]
    assert k["rel"]["src"] == "k" and k["rel"]["ltp"] == 2900.1 and k["rel"]["bid"] == 2900.0 and "alt" not in k["rel"] and k["n"] == 5
    assert k["ce"]["src"] == "k" and k["ce"]["s"] == "opt"


def test_two_sources_show_the_fresher_flag_disagreement_and_fill_each_others_gaps(out):
    t = out["two"]
    assert t["rel"]["src"] == "z" and t["rel"]["alt"]["src"] == "k" and "x" not in t["rel"]                    # 2900.15 vs 2900.10: within a spread
    assert t["nifty"]["src"] == "z" and "x" not in t["nifty"] and t["nifty"]["alt"]["ltp"] == 24500.5
    assert t["fut"]["x"] > 0.5 and t["fut"]["alt"]["ltp"] == 2905.0                                         # 2990 vs 2905: a future that two brokers disagree on by 2.9% is a fault
    assert t["ce"]["ltp"] == 160.0 and t["ce"]["src"] == "z" and t["ce"]["alt"]["ltp"] == 150.5 and t["ce"]["x"] > 3      # 160 vs 150.5 is 5.9%: past an option's 3% tolerance, so it is flagged (and, flagged, it borrows nothing from the other source)



def test_an_unchanged_kotak_price_does_not_look_fresh_and_a_moved_one_does(out):
    assert out["aged"]["nifty"]["age_s"] >= 29 and out["aged"]["nifty"]["src"] == "z"                           # nothing moved for 30 s: it is 30 s old, not 0
    assert out["aged"]["rel"]["src"] == "z" and out["aged"]["rel"]["age_s"] < 1                                  # Kite ticked
    assert out["holiday"]["niftyAge"] >= 60 and out["holiday"]["ceAge"] >= 60                                  # a holiday: the same prices keep coming, every age grows
    assert out["moved"]["ltp"] == 24510.0 and out["moved"]["age"] < 1


def test_health_reports_both_sources_and_never_the_key(out):
    h = out["health"]
    assert h["kite"] and h["configured"] is True and h["noKey"] and h["cycles"] >= 3 and out["healthTwo"]["both"] == 4 and out["healthTwo"]["disagree"] >= 1 and h["universe"] == {"asof": "2026-11-09", "quotes": 3, "chains": 1}
    assert out["healthAuth"] == 401


def test_the_universe_survives_a_restart_and_an_unconfigured_poller_does_nothing(out):
    assert out["restart"] == {"universe": 3, "quotes": 0}
    assert out["unconfigured"] == {"calls": 0, "status": "off"}
    assert out["armLive"] == [False, False, True]


def test_the_poller_source_can_trade_nothing_and_holds_the_key_only_in_its_header():
    src = (ROOT / "deploy/cloudflare/kotak.js").read_text()
    paths = {p.rstrip("/") for p in re.findall(r'(?:this\.get|get)\(\s*[`"]([a-z\-]+/[0-9.]+/[a-z\-/]+)', src)}
    assert paths == {"script-details/1.0/quotes/neosymbol", "market-data/1.0/watchlist/option-chain"}, paths
    assert not re.search(r"placeOrder|place_order|/orders|/positions|/holdings|/margins|/limits|/profile|/portfolio|quick-trade|trade-api/orders", src, re.I)
    assert len(re.findall(r"this\.key", src)) == 2 and "console." not in src          # assigned once, sent once (the Authorization header)
    live = (ROOT / "deploy/cloudflare/live.js").read_text()
    assert "KOTAK_CONSUMER_KEY" in live and "console." not in live and not re.search(r"JSON\.stringify\([^)]*KOTAK", live)


def test_the_live_tab_shows_each_prices_source_the_disagreement_flag_and_the_sources_health():
    app = (ROOT / "quantdesk/web/static/app/app.js").read_text()
    for needle in ('v.src === "z" ? "Kite"', '"Kotak"', "v.x.toFixed(1)", "the two sources differ", "/live/health", "lv-sources", "disagree", "sources agree"):
        assert needle in app, needle


def test_the_relay_asks_for_a_universe_rebuild_only_when_it_is_stale_and_not_too_often(out):
    # 08:05 Mon: stale -> yes; 10 min later: no (asked); 41 min later: yes again; 07:00 Mon: too early; Saturday: no; poller off: no
    assert out["needs"] == [True, False, True, False, False, False]
    assert out["needsFresh"] is False and out["needsStale"] is True                      # today's universe is not rebuilt; yesterday's is
    assert out["needsViaWorker"][0] is False
