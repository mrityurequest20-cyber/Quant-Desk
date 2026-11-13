"""The live board survives an eviction or a redeploy (deploy/cloudflare/live.js, 13 Nov 2026). Before, quotes and order books were memory only, so after the close, when
nothing ticks to refill them, a restart left the app with nothing until the next open. Now they are kept in BOARD_SHARDS storage shards, written with the chart series, and
read back on start: re-checked like a push, each with its own arrival time, so the app shows the last prices aged and never as live. Run under Node."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
READ = "r" * 32


def run(tmp_path, body: str) -> dict:
    for f in ("live.js", "kotak.js", "series.js", "paper.js", "news.js", "candles.js", "routes.js"):
        shutil.copyfile(ROOT / "deploy" / "cloudflare" / f, tmp_path / ("live.mjs" if f == "live.js" else f))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "t.mjs").write_text(HEAD + body + "\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


HEAD = r"""
import { LiveBoard, BOARD_SHARDS, boardKeys, boardShard } from "./live.mjs";
const out = {};
const MIN = 60000;
const T0 = Date.UTC(2026, 10, 13, 9, 59);                      // Fri 13 Nov 2026 15:29 IST, a minute before the close
const mkStorage = (mem = new Map()) => ({
  mem,
  get: async (k) => { if (Array.isArray(k)) { const m = new Map(); for (const x of k) if (mem.has(x)) m.set(x, structuredClone(mem.get(x))); return m; } const v = mem.get(k); return v === undefined ? v : structuredClone(v); },
  put: async (k, v) => { if (v === undefined && k && typeof k === "object") { for (const [a, b] of Object.entries(k)) mem.set(a, structuredClone(b)); } else mem.set(k, structuredClone(v)); },
  delete: async (k) => { for (const x of [].concat(k)) mem.delete(x); },
  getAlarm: async () => null, setAlarm: async () => {},
});
const mkBoard = async (storage, now) => { const b = new LiveBoard({ storage, blockConcurrencyWhile: async (fn) => fn() }, {}); b.now = () => now.t; await b.ready; return b; };
const push = (b, quotes, src) => b.fetch(new Request("https://live/push", { method: "POST", body: JSON.stringify(src ? { src, quotes } : { quotes }) }));
const book = { b: [[24500, 75, 3], [24499.5, 150, 4]], a: [[24501, 50, 2], [24501.5, 100, 1]] };
"""


@needs_node
def test_an_eviction_after_the_close_keeps_the_last_prices_and_books_with_their_true_age(tmp_path):
    out = run(tmp_path, r"""
const storage = mkStorage(), now = { t: T0 };
const a = await mkBoard(storage, now);
await push(a, { "NIFTY-FUT": { ltp: 24500.5, bid: 24500, ask: 24501, vol: 12345, oi: 999, s: "fut", d: book }, "NIFTY": { ltp: 24480.1, s: "idx" } });
await push(a, { "CRUDEOIL-MCX": { ltp: 5812, bid: 5811, ask: 5813, s: "mcx" } }, "f");
now.t = T0 + 6 * MIN;                                            // the flush runs on the next request after five minutes
await a.fetch(new Request("https://live/arm", { method: "POST" }));
out.keys = [...storage.mem.keys()].filter((k) => k.startsWith("brd:")).length;
// the object is evicted; the next morning, before the open, the app asks for the board
now.t = T0 + 16 * 60 * MIN;                                      // Sat 07:29 IST
const b = await mkBoard(storage, now);
out.quotes = Object.fromEntries([...b.quotes].map(([n, e]) => [n, Object.fromEntries(Object.entries(e).map(([s, q]) => [s, { ltp: q.ltp, bid: q.bid, oi: q.oi, s: q.s, at: q.at }]))]));
out.depth = b.depth.get("NIFTY-FUT");
out.at0 = T0;
""")
    assert 1 <= out["keys"] <= 32
    q = out["quotes"]
    assert q["NIFTY-FUT"]["z"] == {"ltp": 24500.5, "bid": 24500, "oi": 999, "s": "fut", "at": out["at0"]}          # the arrival time it had, not the restart's
    assert q["NIFTY"]["z"]["ltp"] == 24480.1 and q["CRUDEOIL-MCX"]["f"]["ltp"] == 5812                          # every feed's row, Fyers' too
    assert out["depth"]["src"] == "z" and out["depth"]["b"][0] == [24500, 75, 3] and out["depth"]["at"] == out["at0"]


@needs_node
def test_the_snapshot_after_a_restart_shows_the_prices_aged_not_live(tmp_path):
    out = run(tmp_path, r"""
const storage = mkStorage(), now = { t: T0 };
const a = await mkBoard(storage, now);
await push(a, { "NIFTY": { ltp: 24480.1, s: "idx" } });
now.t = T0 + 6 * MIN;
await a.fetch(new Request("https://live/arm", { method: "POST" }));
now.t = T0 + 16 * 60 * MIN;
const b = await mkBoard(storage, now);
const snap = b.snapshot(now.t);
const row = snap && (snap.quotes ? snap.quotes["NIFTY"] : null);
out.row = row ? { ltp: row.ltp, age: row.age_s } : null;
""")
    assert out["row"]["ltp"] == 24480.1 and out["row"]["age"] >= 16 * 3600 - 60


@needs_node
def test_storage_is_not_trusted_on_the_way_back(tmp_path):
    out = run(tmp_path, r"""
const storage = mkStorage(), now = { t: T0 };
const k = boardKeys()[boardShard("GOOD")];
storage.mem.set(k, { q: {
    "GOOD": { z: { ltp: 10, at: T0 - MIN, s: "eq" } },
    "BAD NAME!": { z: { ltp: 10, at: T0 - MIN } },
    "NOLTP": { z: { bid: 5, at: T0 - MIN } },
    "FUTURE": { z: { ltp: 10, at: T0 + 3600 * 1000 } },
    "UNKNOWN_SRC": { x: { ltp: 10, at: T0 - MIN } },
    "OLD": { z: { ltp: 10, at: T0 - 5 * 86400 * 1000 } },
    "EXTRA": { z: { ltp: 10, at: T0 - MIN, evil: "<script>", hi: 11 } },
  }, d: {
    "GOOD": { src: "z", at: T0 - MIN, b: [[11, 5, 1]], a: [[10, 5, 1]] },        // crossed: refused
  } });
storage.mem.set("brd:999", "junk");
const b = await mkBoard(storage, now);
out.names = [...b.quotes.keys()].sort();
out.extra = b.quotes.get("EXTRA") ? Object.keys(b.quotes.get("EXTRA").z).sort() : null;
out.depth = b.depth.size;
""")
    assert out["names"] == ["EXTRA", "GOOD"]
    assert out["extra"] == ["at", "ltp"]                                                    # only the fields a push may carry; the candle window (hi) is never stored on a quote
    assert out["depth"] == 0


@needs_node
def test_only_changed_shards_are_written_and_a_pruned_name_leaves_storage(tmp_path):
    out = run(tmp_path, r"""
const storage = mkStorage(), now = { t: T0 };
const a = await mkBoard(storage, now);
await push(a, { "A": { ltp: 1, s: "eq" }, "B": { ltp: 2, s: "eq" } });
out.first = await a.flushBoard(storage);
out.again = await a.flushBoard(storage);                         // nothing changed: nothing written
await push(a, { "A": { ltp: 1.5, s: "eq" } });
out.one = await a.flushBoard(storage);
now.t = T0 + 5 * 86400 * 1000;                                  // five days on: both are stale and pruned
a.prune(now.t);
await a.flushBoard(storage);
out.left = [...storage.mem.keys()].filter((k) => k.startsWith("brd:")).length;
out.shards = BOARD_SHARDS;
""")
    assert out["first"] in (1, 2) and out["again"] == 0 and out["one"] == 1 and out["left"] == 0 and out["shards"] == 32
