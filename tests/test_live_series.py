"""The chart series behind the app's per-instrument view (deploy/cloudflare/series.js and its use in live.js), run under Node: one close a minute per instrument,
the last two trading days, bounded memory, stored in shards and read back after the object is evicted, and served only to the read key. Display only."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
READ, INGEST = "r" * 32, "i" * 32


def run(tmp_path, body: str) -> dict:
    for f in ("live.js", "kotak.js", "series.js", "paper.js"):
        shutil.copyfile(ROOT / "deploy" / "cloudflare" / f, tmp_path / ("live.mjs" if f == "live.js" else f))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "t.mjs").write_text((HEAD + body + "\nconsole.log(JSON.stringify(out));\n").replace("__R__", READ).replace("__I__", INGEST), encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


HEAD = r"""
import { handleLive, LiveBoard } from "./live.mjs";
import { Series, MAX_BARS, MAX_BARS_TOTAL, SHARDS, shardOf, shardKeys } from "./series.js";
const out = {};
const MIN = 60000;
const T0 = Date.UTC(2026, 10, 9, 3, 45);                       // Mon 9 Nov 2026 09:15 IST
const mkStorage = (mem = new Map()) => ({
  mem,
  get: async (k) => { if (Array.isArray(k)) { const m = new Map(); for (const x of k) if (mem.has(x)) m.set(x, structuredClone(mem.get(x))); return m; } const v = mem.get(k); return v === undefined ? v : structuredClone(v); },
  put: async (k, v) => { if (v === undefined && k && typeof k === "object") { for (const [a, b] of Object.entries(k)) mem.set(a, structuredClone(b)); } else mem.set(k, structuredClone(v)); },
  delete: async (k) => { for (const x of [].concat(k)) mem.delete(x); },
  getAlarm: async () => null, setAlarm: async () => {},
});
const mkBoard = (storage, now, env = {}) => { const b = new LiveBoard({ storage, blockConcurrencyWhile: async (fn) => fn() }, env); b.now = () => now.t; return b; };
const push = (b, quotes) => b.fetch(new Request("https://live/push", { method: "POST", body: JSON.stringify({ quotes }) }));
const series = async (b, name) => (await b.fetch(new Request("https://live/series?name=" + encodeURIComponent(name)))).json();
"""


@needs_node
def test_one_close_a_minute_the_last_two_days_and_a_clock_that_steps_back(tmp_path):
    out = run(tmp_path, r"""
const s = new Series();
out.first = s.add("A", T0, 100);
s.add("A", T0 + 10000, 101);                                    // same minute: the close moves
s.add("A", T0 + 1 * MIN, 102);
out.stepBack = s.add("A", T0 - 5 * MIN, 99);                     // older than the last point: ignored
out.bad = [s.add("A", T0 + 2 * MIN, NaN), s.add("A", T0 + 2 * MIN, -1), s.add("A", T0 + 2 * MIN, "5"), s.add("A", T0 + 2 * MIN, 0), s.add("A", NaN, 5)];
out.day1 = s.view("A");
// the next trading day (Tue): Monday's closes become the previous day, and Monday's last close is the baseline
s.add("A", T0 + 24 * 60 * MIN, 110);
out.day2 = s.view("A");
// a third day drops the first: only the day before stays
s.add("A", T0 + 48 * 60 * MIN, 120);
out.day3 = { view: s.view("A"), held: s.m.get("A").length / 2, total: s.total };
// a weekend: Friday then Monday keeps Friday as the previous day
const w = new Series(); w.add("F", Date.UTC(2026, 10, 6, 9, 55), 7); w.add("F", T0, 8);
out.weekend = w.view("F");
out.unknown = s.view("NOPE");
// the cap per instrument
const c = new Series(); for (let i = 0; i < MAX_BARS + 50; i++) c.add("C", T0 + i * MIN, 1 + i);
out.cap = { held: c.m.get("C").length / 2, total: c.total, first: c.m.get("C")[0] === Math.floor(T0 / MIN) + 50 };
""")
    assert out["first"] is True and out["stepBack"] is False and out["bad"] == [False] * 5
    assert out["day1"] == {"day": [[out["day1"]["day"][0][0], 101], [out["day1"]["day"][1][0], 102]], "prev_close": None}
    d2 = out["day2"]
    assert [p for _, p in d2["day"]] == [110] and d2["prev_close"] == 102
    d3 = out["day3"]
    assert [p for _, p in d3["view"]["day"]] == [120] and d3["view"]["prev_close"] == 110 and d3["held"] == 2 and d3["total"] == 2
    assert [p for _, p in out["weekend"]["day"]] == [8] and out["weekend"]["prev_close"] == 7
    assert out["unknown"] == {"day": [], "prev_close": None}
    assert out["cap"] == {"held": 960, "total": 960, "first": True}


@needs_node
def test_the_total_is_bounded_and_a_full_board_charts_no_new_name_but_keeps_the_old(tmp_path):
    out = run(tmp_path, r"""
const s = new Series();
s.m.set("OLD", [Math.floor(T0 / MIN), 5]); s.total = MAX_BARS_TOTAL;          // as if the board were full
out.newName = s.add("NEW", T0, 1);
out.oldName = s.add("OLD", T0 + MIN, 6);
out.newThere = s.m.has("NEW");
out.oldBars = s.m.get("OLD").length / 2;
""")
    assert out["newName"] is False and out["newThere"] is False and out["oldName"] is True and out["oldBars"] == 1          # the old name trades its oldest minute for its newest: the total does not grow


@needs_node
def test_the_series_survives_an_eviction_and_is_written_only_when_changed_and_at_most_every_five_minutes(tmp_path):
    out = run(tmp_path, r"""
const mem = new Map(); const storage = mkStorage(mem); const now = { t: T0 };
let writes = 0; const put = storage.put; storage.put = async (k, v) => { writes += 1; return put(k, v); };
let b = mkBoard(storage, now); await b.ready;
await push(b, { NIFTY: { ltp: 24500 }, RELIANCE: { ltp: 1300 } });
out.writes0 = writes;                                                         // the first flush window has not passed: nothing written yet... (lastFlush starts at 0 so this one flushes)
now.t = T0 + 1 * MIN; await push(b, { NIFTY: { ltp: 24510 } });
out.writes1 = writes;                                                         // inside five minutes: no write
now.t = T0 + 6 * MIN; await push(b, { NIFTY: { ltp: 24520 } });
out.writes2 = writes;                                                         // after five minutes: written
now.t = T0 + 12 * MIN; await push(b, { NIFTY: { ltp: 24520 } });              // nothing new moved the series? the same price in a new minute is still a point
const keys = [...mem.keys()].filter((k) => k.startsWith("bars:"));
out.keys = keys.length;
// a new object on the same storage (an eviction) has the series back
const b2 = mkBoard(storage, { t: now.t + MIN }); await b2.ready;
out.after = (await series(b2, "NIFTY")).day.map((p) => p[1]);
out.rel = (await series(b2, "RELIANCE")).day.map((p) => p[1]);
""")
    assert out["writes1"] == out["writes0"]                                           # inside the window: no write
    assert out["writes2"] > out["writes1"]                                            # past it: the changed shards are written
    assert out["keys"] >= 1
    assert out["after"][:3] == [24500, 24510, 24520] and out["rel"] == [1300]


@needs_node
def test_hostile_or_broken_storage_never_stops_the_board_and_is_not_trusted(tmp_path):
    out = run(tmp_path, r"""
const B = Math.floor(T0 / MIN);
const bad = new Map([
  ["bars:0", { GOOD: [B, 5, B + 1, 6], NAN: [B, NaN], STR: ["1", 2], ODD: [B, 2, 3], NEG: [B, -5], BACK: [B + 10, 1, B + 5, 2, B + 20, 3], ARR: "x" }],
  ["bars:1", [1, 2, 3]],
  ["bars:2", null],
]);
const storage = mkStorage(bad); const now = { t: T0 };
const b = mkBoard(storage, now); await b.ready;
out.good = (await series(b, "GOOD")).day;
out.others = [(await series(b, "NAN")).day, (await series(b, "STR")).day, (await series(b, "ODD")).day, (await series(b, "NEG")).day];
out.back = b.series.m.get("BACK");
// a storage that throws on read: the board still starts and serves
const broken = mkStorage(); broken.get = async (k) => { if (Array.isArray(k)) throw new Error("storage down"); return undefined; };
const b2 = mkBoard(broken, now); await b2.ready;
out.started = (await push(b2, { A: { ltp: 1 } })).status;
// a storage that throws on write: the push is still answered, the shards stay marked for the next try
const nowrite = mkStorage(); nowrite.put = async () => { throw new Error("write failed"); };
const b3 = mkBoard(nowrite, now); await b3.ready;
out.pushed = (await push(b3, { A: { ltp: 1 } })).status;
out.stillDirty = b3.series.dirty.size;
""")
    assert [p[1] for p in out["good"]] == [5, 6] and out["others"] == [[], [], [], []]
    assert [out["back"][1], out["back"][3]] == [1, 3] and len(out["back"]) == 4                                              # a point out of order is dropped, the rest kept
    assert out["started"] == 200 and out["pushed"] == 200 and out["stillDirty"] >= 1


@needs_node
def test_the_series_endpoint_answers_only_to_the_read_key_and_only_for_a_plain_name(tmp_path):
    out = run(tmp_path, r"""
const storage = mkStorage(); const now = { t: T0 };
const board = mkBoard(storage, now); await board.ready;
const env = { LIVE: { idFromName: () => "b", get: () => ({ fetch: (u, init) => board.fetch(new Request(u, init)) }) }, LIVE_INGEST_TOKEN: "__I__", LIVE_READ_TOKEN: "__R__" };
await handleLive(new Request("https://x/live/ingest", { method: "POST", headers: { authorization: "Bearer __I__" }, body: JSON.stringify({ quotes: { NIFTY: { ltp: 24500 } } }) }), env);
const get = async (path, token, method = "GET") => { const r = await handleLive(new Request("https://x" + path, { method, headers: token ? { authorization: "Bearer " + token } : {} }), env); return { status: r.status, body: await r.json() }; };
out.ok = await get("/live/series?name=NIFTY", "__R__");
out.none = await get("/live/series?name=NIFTY");
out.ingestKey = await get("/live/series?name=NIFTY", "__I__");                 // the write key does not read
out.noName = await get("/live/series", "__R__");
out.badName = await get("/live/series?name=" + encodeURIComponent("<script>"), "__R__");
out.long = await get("/live/series?name=" + "A".repeat(41), "__R__");
out.post = await get("/live/series?name=NIFTY", "__R__", "POST");
out.unknown = await get("/live/series?name=NOPE", "__R__");
""")
    assert out["ok"]["status"] == 200 and out["ok"]["body"]["name"] == "NIFTY" and [p[1] for p in out["ok"]["body"]["day"]] == [24500]
    assert out["none"]["status"] == 401 and out["ingestKey"]["status"] == 401
    assert out["noName"]["status"] == 400 and out["badName"]["status"] == 400 and out["long"]["status"] == 400
    assert out["post"]["status"] == 405
    assert out["unknown"]["status"] == 200 and out["unknown"]["body"]["day"] == []


@needs_node
def test_only_a_changed_kotak_price_adds_a_point_and_shards_are_spread(tmp_path):
    out = run(tmp_path, r"""
const storage = mkStorage(); const now = { t: T0 };
const b = mkBoard(storage, now); await b.ready;
b.put("K", "k", { ltp: 10, vol: 1 }, true);
now.t = T0 + MIN; b.put("K", "k", { ltp: 10, vol: 1 }, true);                 // unchanged: no new minute
now.t = T0 + 2 * MIN; b.put("K", "k", { ltp: 11, vol: 2 }, true);             // changed
out.k = (await series(b, "K")).day.map((p) => p[1]);
const names = Array.from({ length: 4000 }, (_, i) => "SYM" + i), hit = new Set(names.map(shardOf));
out.spread = [hit.size, SHARDS, shardKeys().length];
""")
    assert out["k"] == [10, 11]
    assert out["spread"] == [48, 48, 48]


@needs_node
def test_names_already_charted_cannot_grow_the_total_past_its_cap(tmp_path):
    """B1 of the review: the cap was checked only for a NEW name, so 4000 early names ticking every minute for 960 minutes held 3.8 million minutes (over 128 MB)."""
    out = run(tmp_path, r"""
const s = new Series();
const names = Array.from({ length: 4000 }, (_, i) => "N" + i);
let maxSeen = 0;
for (let m = 0; m < MAX_BARS; m++) {
  for (const n of names) s.add(n, T0 + m * MIN, 1 + (m % 7));
  if (s.total > maxSeen) maxSeen = s.total;
}
let real = 0; for (const a of s.m.values()) real += a.length / 2;
out.r = { maxSeen, total: s.total, real, cap: MAX_BARS_TOTAL, names: s.m.size, newestKept: [...s.m.values()].every((a) => a[a.length - 2] === Math.floor(T0 / MIN) + MAX_BARS - 1) };
""")
    r = out["r"]
    assert r["maxSeen"] <= r["cap"] and r["total"] == r["real"] and r["names"] == 4000      # bounded at every step, and the counter is the truth
    assert r["newestKept"] is True                                                          # a name gives up its oldest minute, never its newest


@needs_node
def test_a_failed_flush_is_retried_a_pruned_name_leaves_storage_and_the_alarm_flushes(tmp_path):
    out = run(tmp_path, r"""
const mem = new Map(); const storage = mkStorage(mem); const now = { t: T0 };
let fail = true; const put = storage.put; storage.put = async (k, v) => { if (fail) throw new Error("storage fault"); return put(k, v); };
const b = mkBoard(storage, now); await b.ready;
b.series.add("A", T0, 5);
now.t = T0 + 6 * MIN;
await b.maybeFlush(now.t);                                                    // fails: the shard stays marked
out.afterFail = { dirty: b.series.dirty.size, stored: [...mem.keys()].filter((k) => k.startsWith("bars:")).length };
fail = false; now.t = T0 + 12 * MIN;
await b.maybeFlush(now.t);                                                    // nothing else changed: only the retained mark can make this write
out.afterRetry = { dirty: b.series.dirty.size, stored: [...mem.keys()].filter((k) => k.startsWith("bars:")).length };
b.series.prune(T0 + 5 * 86400e3);                                             // a name unseen for 5 days is pruned and its shard emptied
now.t = T0 + 20 * MIN; await b.maybeFlush(now.t);
out.afterPrune = { has: b.series.m.has("A"), stored: [...mem.keys()].filter((k) => k.startsWith("bars:")).length };
const mem2 = new Map(); const st2 = mkStorage(mem2); const now2 = { t: T0 };   // the alarm flushes too (the Kotak poller's clock), whatever state the poller is in
const b2 = mkBoard(st2, now2, { KOTAK_CONSUMER_KEY: "k".repeat(20) }); await b2.ready;
b2.series.add("B", T0, 7); now2.t = T0 + 6 * MIN;
await b2.alarm();
out.alarm = [...mem2.keys()].filter((k) => k.startsWith("bars:")).length;
""")
    assert out["afterFail"] == {"dirty": 1, "stored": 0} and out["afterRetry"] == {"dirty": 0, "stored": 1}
    assert out["afterPrune"] == {"has": False, "stored": 0} and out["alarm"] == 1


@needs_node
def test_one_shard_that_cannot_be_written_does_not_stop_the_others(tmp_path):
    out = run(tmp_path, r"""
const mem = new Map(); const storage = mkStorage(mem);
const s = new Series();
let a = "A", b = "B", k = 0; while (shardOf(b) === shardOf(a)) b = "B" + k++;
s.add(a, T0, 1); s.add(b, T0, 2);
const put = storage.put; storage.put = async (key, v) => { if (key === "bars:" + shardOf(a)) throw new Error("too big"); return put(key, v); };
const done = await s.flush(storage);
out.r = { done, stored: [...mem.keys()], bad: shardOf(a), good: "bars:" + shardOf(b), dirty: [...s.dirty] };
""")
    r = out["r"]
    assert r["done"] == 1 and r["stored"] == [r["good"]] and r["dirty"] == [r["bad"]]
