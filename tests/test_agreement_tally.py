"""The per-day Kite-vs-Kotak agreement tally inside the relay (deploy/cloudflare/live.js `tally`, `cleanAgree`), run under Node with a clock the test controls: counts only, per IST day,
persisted across a restart, finished days kept for a week, a malformed stored value dropped."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
import { LiveBoard, cleanAgree } from "./live.mjs";
const out = {};
const MON = Date.UTC(2026, 10, 9, 4, 30);              // Mon 9 Nov 2026 10:00 IST
let now = MON;
const mem = new Map();
const state = () => ({ storage: { get: async (k) => mem.get(k), put: async (k, v) => { mem.set(k, JSON.parse(JSON.stringify(v))); }, getAlarm: async () => null, setAlarm: async () => {} }, blockConcurrencyWhile: async (fn) => fn() });
const mk = async () => { const b = new LiveBoard(state(), { LIVE_INGEST_TOKEN: "i".repeat(32), LIVE_READ_TOKEN: "r".repeat(32), KOTAK_CONSUMER_KEY: "k".repeat(24) }); b.now = () => now; await b.ready; return b; };
const board = await mk();
const both = (name, z, k, s) => { board.put(name, "z", { ltp: z, s }); board.put(name, "k", { ltp: k, s }); };
board.put("FUTONLYK", "k", { ltp: 7, s: "fut" });                                      // fresh at Kotak only
for (let i = 0; i < 30; i++) both("S" + i, 100, i < 3 ? 103 : 100.1, "eq");        // 30 equities, 3 of them 3% apart (limit 0.5%)
for (let i = 0; i < 10; i++) both("O" + i, 50, i < 1 ? 55 : 50.5, "opt");           // 10 options, 1 of them 10% apart (limit 3%)
board.put("ONLYZ", "z", { ltp: 10, s: "eq" });                                       // one source only: not counted
board.tally(now);
out.first = JSON.parse(JSON.stringify(board.agree));
now += 5000; board.tally(now);
out.second = { cycles: board.agree.cycles, both: board.agree.both, disagree: board.agree.disagree, worst: board.agree.worst_cycle_pct };
now += 120000; board.tally(now);                                                      // two minutes on: every quote is older than FRESH_S, so nothing more is counted as a pair
out.stale = { cycles: board.agree.cycles, both: board.agree.both };
board.put("S0", "z", { ltp: 100, s: "eq" });                                          // a handful of pairs: counted, but a cycle that small does not set the worst-cycle figure
board.put("S0", "k", { ltp: 105, s: "eq" });
board.tally(now);
out.small = { both: board.agree.both, worst: board.agree.worst_cycle_pct };
await board.maybeFlush(now + 400000);
out.stored = mem.has("agree");
const health = board.health(now).agreement;
out.health = { today: health.today.day, keys: Object.keys(health.today).sort(), days: Object.keys(health.days) };
out.noName = !JSON.stringify(health).includes("RELIANCE") && !JSON.stringify(health).includes("S0");
const b2 = await mk();                                                                // a restart: the stored tally is back
out.restart = { cycles: b2.agree && b2.agree.cycles, both: b2.agree && b2.agree.both };
now = Date.UTC(2026, 10, 10, 4, 30);                                                  // Tue
b2.tally(now);
out.nextDay = { today: b2.agree.day, cycles: b2.agree.cycles, kept: Object.keys(b2.agreeDays), keptCycles: b2.agreeDays["2026-11-09"] && b2.agreeDays["2026-11-09"].cycles };
for (let d = 0; d < 10; d++) { now += 86400000; b2.agree.cycles = 1; b2.tally(now); }       // ten more days: only the last seven finished days are kept
out.kept = Object.keys(b2.agreeDays).length;
out.clean = [cleanAgree(null), cleanAgree("x"), cleanAgree({ today: { day: "bad" } }), cleanAgree({ today: { day: "2026-11-09", cycles: -4, both: "7", disagree: NaN } }), cleanAgree({ days: { "2026-11-08": { day: "2026-11-09", cycles: 1 } } })];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("agree")
    for f in ("live.js", "kotak.js", "series.js", "paper.js", "news.js"):
        shutil.copyfile(ROOT / "deploy" / "cloudflare" / f, d / ("live.mjs" if f == "live.js" else f))
    (d / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (d / "run.mjs").write_text(HARNESS, encoding="utf-8")
    r = subprocess.run(["node", "run.mjs"], cwd=d, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_a_cycle_counts_the_instruments_both_sources_hold_fresh_and_those_that_differ_by_more_than_a_spread(out):
    a = out["first"]
    assert a["day"] == "2026-11-09" and a["cycles"] == 1 and a["both"] == 40 and a["disagree"] == 4 and a["opt_both"] == 10 and a["opt_disagree"] == 1
    assert a["worst_cycle_pct"] == 10.0                                                                  # 4 of 40
    assert a["peak"] == {"z": {"eq": 31, "opt": 10}, "k": {"fut": 1, "eq": 30, "opt": 10}}               # names each source holds fresh, by segment
    assert out["second"] == {"cycles": 2, "both": 80, "disagree": 8, "worst": 10.0}


def test_stale_quotes_are_not_counted_as_pairs_and_a_tiny_cycle_does_not_set_the_worst_figure(out):
    assert out["stale"] == {"cycles": 3, "both": 80}
    assert out["small"]["both"] == 81 and out["small"]["worst"] == 10.0                                  # the one fresh pair (5% apart) is counted but 1 pair is not a cycle's worth


def test_health_carries_counts_only_and_the_tally_survives_a_restart_and_rolls_over_the_day(out):
    assert out["health"]["today"] == "2026-11-09" and out["noName"] is True
    assert out["health"]["keys"] == sorted(["day", "cycles", "both", "disagree", "opt_both", "opt_disagree", "worst_cycle_pct", "first_at", "last_at", "peak"])
    assert out["stored"] is True and out["restart"] == {"cycles": 4, "both": 81}
    assert out["nextDay"]["today"] == "2026-11-10" and out["nextDay"]["kept"] == ["2026-11-09"] and out["nextDay"]["keptCycles"] == 4
    assert out["kept"] == 7                                                                               # a week of finished days, no more


def test_a_malformed_stored_tally_is_dropped_not_shown(out):
    assert out["clean"][:3] == [None, None, None]
    assert out["clean"][3]["today"] == {"day": "2026-11-09", "cycles": 0, "both": 7, "disagree": 0, "opt_both": 0, "opt_disagree": 0, "worst_cycle_pct": 0, "first_at": 0, "last_at": 0, "peak": {"z": {}, "k": {}}}
    assert out["clean"][4] is None                                                                        # a day filed under another day's key is refused


def test_the_tally_stores_counts_never_a_price_or_an_instrument_name():
    src = (ROOT / "deploy/cloudflare/live.js").read_text(encoding="utf-8")
    body = src[src.index("	tally(now)"):src.index("	snapshot(now)")]
    assert "this.quotes.get" not in body and ".push(" not in body and "[name]" not in body and "for (const [name" not in body       # it only counts: nothing about one instrument is kept
    assert "ltp" in body and "a.ltp" not in body and "a.name" not in body
