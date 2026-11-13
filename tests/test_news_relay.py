"""The relay's news digest (deploy/cloudflare/news.js and its routes in live.js), run under Node: who may call what, the shape of the digest, the size cut, one digest that the newest replaces, and the behaviour
when storage fails. Public headlines only; no price, no account, no secret."""
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
let failGet = false, failPut = false;
const LIMIT = 131072;
const state = { storage: {
  get: async (k) => { if (failGet && (k === "news")) throw new Error("read failed"); return Array.isArray(k) ? new Map(k.filter((x) => mem.has(x)).map((x) => [x, clone(mem.get(x))])) : (mem.has(k) ? clone(mem.get(k)) : undefined); },
  put: async (k, v) => { const kv = typeof k === "object" ? Object.entries(k) : [[k, v]]; for (const [a, b] of kv) if (failPut || JSON.stringify(b).length > LIMIT) throw new Error("write failed"); for (const [a, b] of kv) mem.set(a, clone(b)); },
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
const item = (i, extra = {}) => ({ id: (i + 4096).toString(16).padStart(12, "0"), ts: "2026-11-09T05:%(M)s:00Z".replace("%(M)s", String(10 + (i %% 40)).padStart(2, "0")), source: "Outlet A", sources: ["Outlet A", "Outlet B"], title: "Story " + i + " about Nifty and HDFC Bank",
  link: "https://example.com/" + i, tone: 0.2, tone_from: "words", impact: "medium", recap: false, event: "general", novelty: 0.9, symbols: ["NIFTY", "HDFCBANK"], ...extra });
const digest = (items, extra = {}) => ({ v: 1, asof: "2026-11-09T05:45:00Z", n: items.length, sources: { "Outlet A": "ok 20", "Outlet B": "fail timeout" }, items, ...extra });
const out = {};
%(BODY)s
console.log(JSON.stringify(out));
"""


def run(tmp_path, body: str):
    stage(tmp_path)
    (tmp_path / "t.mjs").write_text(HARNESS % {"I": I, "R": R, "BODY": body, "M": "%(M)s"} if False else HARNESS.replace("%(I)s", I).replace("%(R)s", R).replace("%(BODY)s", body).replace("%%", "%"), encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_each_route_takes_exactly_one_key_and_other_paths_are_not_the_newss(tmp_path):
    o = run(tmp_path, r"""
const d = digest([item(1)]);
out.ingest = { none: (await call("POST", "/news/ingest", { body: d })).status, read: (await call("POST", "/news/ingest", { token: READ, body: d })).status, ingest: (await call("POST", "/news/ingest", { token: ING, body: d })).status };
out.get = { none: (await call("GET", "/news")).status, ingest: (await call("GET", "/news", { token: ING })).status, read: (await call("GET", "/news", { token: READ })).status };
out.methods = [(await call("GET", "/news/ingest", { token: ING })).status, (await call("POST", "/news", { token: READ, body: d })).status, (await call("PUT", "/news", { token: READ })).status];
out.lookalikes = [await call("GET", "/newsletter", { token: READ }), await call("GET", "/news/", { token: READ }), await call("GET", "/news/other", { token: READ })];
out.off = (await call("GET", "/news", { token: READ, e: { LIVE } })).status;
out.live = (await call("GET", "/live/snapshot", { token: READ })).status;
""")
    assert o["ingest"] == {"none": 401, "read": 401, "ingest": 200} and o["get"] == {"none": 401, "ingest": 401, "read": 200}        # the job writes, the app reads, neither can do the other
    assert o["methods"] == [404, 404, 405] and o["lookalikes"] == [None, None, None] and o["off"] == 503 and o["live"] == 200      # /newsletter and /news/ pass through to the site as before


@needs_node
def test_the_digest_is_cleaned_to_known_fields_and_bad_items_are_dropped(tmp_path):
    o = run(tmp_path, r"""
const items = [
  item(1, { evil: "x", __proto__: { admin: true }, title: "  A   spaced\n\ttitle <img src=x onerror=alert(1)>  " }),
  item(2, { link: "http://plain.example/x" }), item(3, { link: "javascript:alert(1)" }), item(4, { link: "https://ok.example/a b" }),
  item(5, { symbols: ["NIFTY", "<script>", "hdfc", "RELIANCE", 7, "A".repeat(30)] }), item(6, { impact: "catastrophic", tone_from: "magic", event: "<b>", novelty: 5 }),
  item(7, { tone: 3 }), item(8, { tone: "0.5" }), item(9, { id: "not-hex" }), item(10, { ts: "yesterday" }), item(11, { title: "   " }), "junk", null, [1], item(12, { sources: ["A".repeat(100), 5, "B"] }),
];
const r = await call("POST", "/paper/nothing", { token: ING }); // (a paper path is untouched by news)
out.post = (await call("POST", "/news/ingest", { token: ING, body: digest(items, { sources: { "Outlet A": "ok 3", ["x".repeat(60)]: "y".repeat(100), "": "z", bad: 5 } }) })).body;
const got = (await call("GET", "/news", { token: READ })).body;
out.n = got.digest.n; out.byId = Object.fromEntries(got.digest.items.map((x) => [x.id, x]));
out.sources = got.digest.sources; out.keys = Object.keys(got.digest.items[0]).sort(); out.top = Object.keys(got.digest).sort();
out.ids = got.digest.items.map((x) => x.id);
out.stored = got.stored_at; out.now = got.now;
""")
    by = o["byId"]
    ids = {i: format(i + 4096, "012x") for i in range(1, 13)}
    assert o["post"] == {"ok": True, "n": o["n"]} and set(o["ids"]) == {ids[i] for i in (1, 2, 3, 4, 5, 6, 12)}                       # tone out of range / a string, a bad id, a bad time and an empty title are dropped
    assert by[ids[1]]["title"] == "A spaced title <img src=x onerror=alert(1)>" and "evil" not in by[ids[1]] and "admin" not in by[ids[1]]    # whitespace flattened; the text itself is data (the app shows it with textContent)
    assert [by[ids[i]]["link"] for i in (2, 3, 4)] == ["", "", ""] and by[ids[1]]["link"].startswith("https://example.com")             # only plain https links
    assert by[ids[5]]["symbols"] == ["NIFTY", "RELIANCE"]
    assert (by[ids[6]]["impact"], by[ids[6]]["tone_from"], by[ids[6]]["event"], by[ids[6]]["novelty"]) == ("low", "words", "general", 1)
    assert by[ids[12]]["sources"] == ["A" * 40, "B"]
    assert o["keys"] == sorted(["id", "ts", "source", "sources", "title", "link", "tone", "tone_from", "impact", "recap", "event", "novelty", "symbols"]) and o["top"] == ["asof", "events", "items", "n", "sources", "v"]
    assert list(o["sources"]) == ["Outlet A", "x" * 40] and len(o["sources"]["x" * 40]) == 60 and o["stored"] == o["now"]


@needs_node
def test_a_bad_digest_is_refused_and_a_big_one_is_cut_to_fit_and_the_newest_replaces_the_last(tmp_path):
    o = run(tmp_path, r"""
const bad = {};
for (const [k, v] of Object.entries({ notobj: "x", arr: [1], v2: { ...digest([item(1)]), v: 2 }, noasof: { ...digest([item(1)]), asof: "now" }, noitems: { v: 1, asof: "2026-11-09T05:45:00Z" }, empty: digest([]), allbad: digest([{ id: "x" }, null]) })) bad[k] = (await call("POST", "/news/ingest", { token: ING, body: typeof v === "string" ? JSON.stringify(v) : v })).status;
out.bad = bad;
out.notjson = (await call("POST", "/news/ingest", { token: ING, body: "{nope" })).status;
out.huge = (await call("POST", "/news/ingest", { token: ING, body: "x".repeat(250000) })).status;
// 300 stories with wide characters: cut to 80 by count and then by size, and stored under the limit
const wide = Array.from({ length: 80 }, (_, i) => item(i, { title: "₹".repeat(200), link: "https://example.com/" + "p".repeat(470), sources: Array.from({ length: 6 }, () => "₹".repeat(40)), source: "₹".repeat(40) }));
out.big = (await call("POST", "/news/ingest", { token: ING, body: digest(wide) })).status;
const g = (await call("GET", "/news", { token: READ })).body.digest;
out.n = g.n; out.chars = JSON.stringify(g).length; out.stored = JSON.stringify(mem.get("news")).length; out.newestFirst = g.items.every((x, i) => i === 0 || g.items[i - 1].ts >= x.ts);
await call("POST", "/news/ingest", { token: ING, body: digest([item(900)]) });
const h = (await call("GET", "/news", { token: READ })).body.digest;
out.after = { n: h.n, titles: h.items.map((x) => x.title) };
""")
    assert all(v == 400 for v in o["bad"].values()), o["bad"] and o["notjson"] == 400 and o["huge"] == 413
    assert o["big"] == 200 and 1 < o["n"] < 80 and o["chars"] <= 60000 and o["stored"] < 131072 and o["newestFirst"]
    assert o["after"] == {"n": 1, "titles": ["Story 900 about Nifty and HDFC Bank"]}                                      # one digest: the newest replaces the last


@needs_node
def test_nothing_held_is_null_and_a_failed_read_is_a_503_and_a_failed_write_changes_nothing(tmp_path):
    o = run(tmp_path, r"""
out.fresh = (await call("GET", "/news", { token: READ })).body;
await call("POST", "/news/ingest", { token: ING, body: digest([item(1)]) });
failPut = true;
out.putFail = (await call("POST", "/news/ingest", { token: ING, body: digest([item(2)]) })).status;
failPut = false;
out.keptAfterFail = (await call("GET", "/news", { token: READ })).body.digest.items.map((x) => x.title);
failGet = true;
out.getFail = (await call("GET", "/news", { token: READ })).status;
failGet = false;
out.back = (await call("GET", "/news", { token: READ })).body.digest.n;
mem.set("news", { digest: { v: 1, asof: "garbage", items: "x" }, stored_at: "soon" });                       // a corrupt store is shown as nothing, not trusted
out.corrupt = (await call("GET", "/news", { token: READ })).body;
""")
    assert o["fresh"]["digest"] is None and o["fresh"]["stored_at"] is None
    assert o["putFail"] == 503 and o["keptAfterFail"] == ["Story 1 about Nifty and HDFC Bank"] and o["getFail"] == 503 and o["back"] == 1
    assert o["corrupt"]["digest"] is None and o["corrupt"]["stored_at"] is None


@needs_node
def test_overlapping_requests_and_the_live_board_and_paper_queue_are_unaffected(tmp_path):
    o = run(tmp_path, r"""
const posts = await Promise.all(Array.from({ length: 10 }, (_, i) => call("POST", "/news/ingest", { token: ING, body: digest([item(i)]) })));
out.codes = posts.map((r) => r.status);
out.n = (await call("GET", "/news", { token: READ })).body.digest.n;
out.push = (await call("POST", "/live/ingest", { token: ING, body: { quotes: { NIFTY: { ltp: 24500.5 } } } })).status;
out.snap = Object.keys((await call("GET", "/live/snapshot", { token: READ })).body.quotes);
out.paper = (await call("POST", "/paper/order", { token: READ, body: { id: "ord-news0001", side: "buy", symbol: "NIFTY12NOV2624500CE", lots: 1, strategy: "s", thesis: "a thesis of more than twenty characters" } })).status;
""")
    assert o["codes"] == [200] * 10 and o["n"] == 1 and o["push"] == 200 and o["snap"] == ["NIFTY"] and o["paper"] == 200


def test_the_news_module_has_no_network_secret_or_broker():
    import re
    src = (ROOT / "deploy" / "cloudflare" / "news.js").read_text(encoding="utf-8")
    code = re.sub(r"//.*", "", src)
    assert not re.search(r"fetch\(|XMLHttpRequest|WebSocket|env\.|KOTAK|KITE|secret|password|token", code, re.I)


@needs_node
def test_values_that_only_look_like_strings_and_links_that_hide_their_host_are_not_kept(tmp_path):
    o = run(tmp_path, r"""
const items = [
  item(1, { id: ["000000001001"] }), item(2, { ts: [["2026-11-09T05:10:00Z"]] }), item(3, { event: ["earnings"] }), item(4, { event: undefined }),
  item(5, { link: "https://trusted.example@evil.example/x" }), item(6, { link: "https://ok.example/a‮b" }), item(7, { title: "pay‮ txt‏ now" }), item(8),
];
const deepText = '{"v":1,"asof":' + "[".repeat(6000) + "]".repeat(6000) + ',"items":[]}';
out.arrAsof = (await call("POST", "/news/ingest", { token: ING, body: digest([item(9)], { asof: ["2026-11-09T05:45:00Z"] }) })).status;
out.deepAsof = (await call("POST", "/news/ingest", { token: ING, body: deepText })).status;
out.post = (await call("POST", "/news/ingest", { token: ING, body: digest(items) })).status;
const got = (await call("GET", "/news", { token: READ })).body;
out.byId = Object.fromEntries(got.digest.items.map((x) => [x.id, x]));
""")
    ids = {i: format(i + 4096, "012x") for i in range(1, 9)}
    assert o["arrAsof"] == 400 and o["deepAsof"] == 400 and o["post"] == 200                                                        # a bad time is a refusal, never a crash
    by = o["byId"]
    assert set(by) == {ids[i] for i in (3, 4, 5, 6, 7, 8)}                                                                         # an array for an id or a time drops the story
    assert by[ids[3]]["event"] == "general" and by[ids[4]]["event"] == "general"                                                   # "undefined" is not an event
    assert by[ids[5]]["link"] == "" and by[ids[6]]["link"] == ""                                                                   # no userinfo, no direction-changing character
    assert by[ids[7]]["title"] == "pay txt now"                                                                                    # direction controls become spaces


@needs_node
def test_the_event_watch_is_kept_field_by_field_and_a_bad_event_is_dropped(tmp_path):
    import shutil as _sh
    import subprocess as _sp
    _sh.copyfile(ROOT / "deploy" / "cloudflare" / "news.js", tmp_path / "news.mjs")
    js = """import { cleanEvents } from './news.mjs';
console.log(JSON.stringify(cleanEvents([
  { type: 'geopolitics', severity: 3.2, level: 'high', tone: -0.6, n: 5, top: ['Missiles hit', 'x'.repeat(300)], kind: 'geopolitics', evil: 1 },
  { type: 'Bad Type!', severity: 1, level: 'high', tone: 0 },
  { type: 'policy', severity: 'big', level: 'watch', tone: 0 },
  { type: 'policy', severity: 1.2, level: 'extreme', tone: 0 },
])));"""
    (tmp_path / "t.mjs").write_text(js)
    out = _sp.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    import json as _json
    ev = _json.loads(out.stdout.strip())
    assert len(ev) == 1 and ev[0]["type"] == "geopolitics" and ev[0]["level"] == "high" and "evil" not in ev[0] and len(ev[0]["top"][1]) == 140
