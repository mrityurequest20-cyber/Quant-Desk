"""Stock option chains in the Kotak poller (deploy/cloudflare/kotak.js, live.js), run under Node: the call plan keeps the prices and the index chains in every cycle and
rotates the stock chains in the calls that are left; a stock chain keeps only a few strikes around the money; the universe the relay accepts carries the keep-count."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def run(tmp_path, body: str) -> dict:
    for f in (ROOT / "deploy" / "cloudflare").glob("*.js"):                       # every module, so a new import never breaks the staging
        shutil.copyfile(f, tmp_path / ("live.mjs" if f.name == "live.js" else f.name))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "t.mjs").write_text('import * as K from "./kotak.js";\nimport { cleanUniverse } from "./live.mjs";\nconst out = {};\n' + body + "\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


UNIVERSE = r"""
const quotes = (n) => Array.from({ length: n }, (_, i) => ({ n: "Q" + i, s: "eq", g: "nse_cm", t: String(1000 + i) }));
const idx = Array.from({ length: 7 }, (_, i) => ({ n: "IDX" + i, s: "idx", g: "nse_cm", t: "Index " + i, one: true }));
const hot = (n) => Array.from({ length: n }, (_, i) => ({ u: "HOT" + i, x: "nse_fo", e: "2026-11-12" }));
const cold = (n) => Array.from({ length: n }, (_, i) => ({ u: "STK" + i, x: "nse_fo", e: "2026-11-24", n: 3 }));
const ids = (p) => p.calls.map((c) => (c.kind === "q" ? "q:" + c.items[0].n + "+" + c.items.length : "c:" + c.chain.u));
"""


@needs_node
def test_prices_and_index_chains_run_every_cycle_and_the_stock_chains_rotate_in_what_is_left(tmp_path):
    out = run(tmp_path, UNIVERSE + r"""
const u = { quotes: [...idx, ...quotes(600)], chains: [...hot(4), ...cold(200)], count: 10 };      // 7 + 24 quote calls, 4 index chains, 200 stock chains
let cursor = 0, covered = new Set(), always = null, maxCalls = 0, sameEvery = true, cycles = 0;
const first = ids(K.plan(u, 0)).filter((x) => !x.startsWith("c:STK"));
while (covered.size < 200 && cycles < 100) {
  const p = K.plan(u, cursor);
  maxCalls = Math.max(maxCalls, p.calls.length);
  const fixed = ids(p).filter((x) => !x.startsWith("c:STK"));
  if (JSON.stringify(fixed) !== JSON.stringify(first)) sameEvery = false;
  for (const c of p.calls) if (c.kind === "c" && c.chain.n) covered.add(c.chain.u);
  cursor = p.next; cycles++;
}
out.tier = { fixed: first.length, sameEvery, maxCalls, covered: covered.size, cycles, total: K.plan(u, 0).total };
// the prices alone nearly fill a cycle: no tier, everything rotates together as before
const heavy = { quotes: [...idx, ...quotes(1000)], chains: [...hot(4), ...cold(20)], count: 10 };
let seen = new Set(); cursor = 0; maxCalls = 0;
for (let i = 0; i < 20; i++) { const p = K.plan(heavy, cursor); maxCalls = Math.max(maxCalls, p.calls.length); for (const c of p.calls) seen.add(c.kind === "q" ? c.items[0].n : c.chain.u); cursor = p.next; }
out.heavy = { maxCalls, seen: seen.size, wanted: 7 + 40 + 4 + 20 };
// small: everything, once, with no rotation
const small = K.plan({ quotes: idx, chains: [...hot(2), ...cold(3)] }, 5);
out.small = { n: small.calls.length, next: small.next };
""")
    t = out["tier"]
    assert t["fixed"] == 7 + 24 + 4 and t["sameEvery"] is True and t["maxCalls"] <= 40       # the quote calls and the index chains are the same in every cycle
    assert t["covered"] == 200 and t["cycles"] <= 200 / 1 and t["total"] == 7 + 24 + 4 + 200
    assert out["heavy"]["maxCalls"] <= 40 and out["heavy"]["seen"] == out["heavy"]["wanted"]
    assert out["small"] == {"n": 7 + 5, "next": 0}


@needs_node
def test_a_stock_chain_keeps_a_few_strikes_around_the_money_and_an_index_chain_keeps_all(tmp_path):
    out = run(tmp_path, r"""
const mk = (n) => ({ strike: n, side: "CE", ltp: 1 });
const rows = []; for (let k = 100; k <= 300; k += 10) { rows.push({ strike: k, side: "CE", ltp: 1 }, { strike: k, side: "PE", ltp: 2 }); }          // 21 strikes, 42 rows
out.kept = K.nearMoney(rows, 3).map((r) => r.strike + r.side);
out.fewer = K.nearMoney(rows.slice(0, 10), 3).length;                                  // 5 strikes: nothing to cut
out.allStrikes = new Set(K.nearMoney(rows, 3).map((r) => r.strike)).size;
// through a whole cycle
const body = (n) => ({ data: { call: Array.from({ length: 21 }, (_, i) => ({ inst: { strkPrc: String(100 + i * 10), neoSymbol: "nse_fo|" + i }, quote: { ltp: "5", vol: "9" }, oi: { cur: "7" } })),
                                put: Array.from({ length: 21 }, (_, i) => ({ inst: { strkPrc: String(100 + i * 10), neoSymbol: "nse_fo|" + (100 + i) }, quote: { ltp: "4" }, oi: { cur: "6" } })) } });
const poller = { quotes: async () => [], chain: async () => body() };
const r = await K.runCycle(poller, { quotes: [], chains: [{ u: "RELIANCE", x: "nse_fo", e: "2026-11-24", n: 3 }, { u: "NIFTY", x: "nse_fo", e: "2026-11-24" }], count: 10 }, 0);
const names = r.updates.map((u) => u[0]);
out.cycle = { stock: names.filter((n) => n.startsWith("RELIANCE")).length, index: names.filter((n) => n.startsWith("NIFTY")).length, sample: names.find((n) => n.startsWith("RELIANCE")), ok: r.ok, failed: r.failed };
""")
    assert len(out["kept"]) == 14 and out["allStrikes"] == 7 and out["fewer"] == 10
    assert out["kept"][0] == "170CE" and out["kept"][-1] == "230PE"                         # 21 strikes, the middle one is 200: 170..230
    assert out["cycle"]["stock"] == 14 and out["cycle"]["index"] == 42 and out["cycle"]["failed"] == 0
    assert out["cycle"]["sample"].startswith("RELIANCE24NOV26")


@needs_node
def test_the_relay_keeps_the_keep_count_only_when_it_is_a_small_integer_and_takes_four_hundred_chains(tmp_path):
    out = run(tmp_path, r"""
const c = (u, n) => ({ u, x: "nse_fo", e: "2026-11-24", ...(n !== undefined ? { n } : {}) });
const clean = (chains) => cleanUniverse({ asof: "2026-11-09", quotes: [], chains }).chains;
out.n = clean([c("A", 3), c("B", 0), c("C", 11), c("D", 2.5), c("E", "3"), c("F"), c("G", -1), c("H", null)]).map((x) => x.u + ":" + x.n);
out.many = clean(Array.from({ length: 450 }, (_, i) => c("S" + i, 3))).length;
""")
    assert len(out["n"]) == 8                                                                  # all eight chains are kept; only the keep-count is judged
    assert [x for x in out["n"] if x.split(":")[1] != "undefined"] == ["A:3"]           # only 3 survives; 0, 11, 2.5, "3", -1 and null are not keep-counts
    assert out["many"] == 400
