"""Expired option contracts leave the relay's board (deploy/cloudflare/live.js), so an expiry roll cannot fill it: the review of the stock-chains change found that
200 stocks x 14 names for the old expiry plus the same for the new one, kept 4 days, would refuse new contracts at the roll."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

HEAD = r"""
import { LiveBoard, expiredOption } from "./live.mjs";
const out = {};
const mem = new Map();
const state = { storage: { get: async (k) => (Array.isArray(k) ? new Map() : mem.get(k)), put: async (k, v) => { if (v === undefined && k && typeof k === "object") for (const [a, b] of Object.entries(k)) mem.set(a, b); else mem.set(k, v); }, delete: async () => {}, getAlarm: async () => null, setAlarm: async () => {} }, blockConcurrencyWhile: async (fn) => fn() };
let now = Date.UTC(2026, 10, 12, 4, 30);                      // Thu 12 Nov 2026, 10:00 IST
const mk = () => { const b = new LiveBoard(state, {}); b.now = () => now; return b; };
const push = (b, quotes) => b.fetch(new Request("https://live/push", { method: "POST", body: JSON.stringify({ quotes }) })).then((r) => r.json());
const names = async (b) => Object.keys((await (await b.fetch(new Request("https://live/snapshot"))).json()).quotes).sort();
"""


def run(tmp_path, body: str) -> dict:
    for f in (ROOT / "deploy" / "cloudflare").glob("*.js"):
        shutil.copyfile(f, tmp_path / ("live.mjs" if f.name == "live.js" else f.name))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "t.mjs").write_text(HEAD + body + "\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_only_an_option_whose_expiry_is_before_today_counts_as_expired(tmp_path):
    out = run(tmp_path, r"""
const today = 20261112;
out.v = {
  past: expiredOption("NIFTY05NOV2624500CE", today), today: expiredOption("NIFTY12NOV2624500CE", today), future: expiredOption("NIFTY19NOV2624500CE", today),
  lastYear: expiredOption("BAJAJ-AUTO30DEC2550000PE", today), nextYear: expiredOption("NIFTY07JAN2724500CE", today), decimal: expiredOption("BANKNIFTY29OCT2652000.5PE", today),
  hyphenStock: expiredOption("BAJAJ-AUTO05NOV269000PE", today), digitsFirst: expiredOption("360ONE05NOV261000CE", today), mm: expiredOption("M&M05NOV263100CE", today),
};
out.notOptions = ["NIFTY", "NIFTY-FUT", "RELIANCE", "CRUDEOIL-MCX", "USDINR-CDS", "NIFTY05NOV26", "NIFTY05XXX2624500CE", "NIFTY05NOV2624500XX", "", "05NOV2624500CE"].map((n) => expiredOption(n, today));
""")
    v = out["v"]
    assert v["past"] is True and v["today"] is False and v["future"] is False                  # the expiry day itself is still traded
    assert v["lastYear"] is True and v["nextYear"] is False and v["decimal"] is True
    assert v["hyphenStock"] is True and v["digitsFirst"] is True and v["mm"] is True            # names with hyphens, leading digits and an ampersand parse
    assert out["notOptions"] == [False] * 10                                                    # futures, spots and commodities are never "expired" by name


@needs_node
def test_a_prune_drops_expired_contracts_on_the_day_after_and_keeps_the_expiry_day(tmp_path):
    out = run(tmp_path, r"""
const b = mk(); await b.ready;
await push(b, { NIFTY: { ltp: 24500 }, "NIFTY-FUT": { ltp: 24530 }, NIFTY05NOV2624500CE: { ltp: 1 }, NIFTY12NOV2624500CE: { ltp: 2 }, NIFTY19NOV2624500CE: { ltp: 3 } });
out.expiryDay = await names(b);
now += 5 * 60000 + 1; await push(b, { NIFTY: { ltp: 24501 } });                          // a prune runs (every five minutes on a request)
out.expiryDayAfterPrune = await names(b);
now = Date.UTC(2026, 10, 13, 4, 30);                                                       // the day after the 12 Nov expiry
await push(b, { NIFTY: { ltp: 24502 } });
out.dayAfter = await names(b);
out.pruned = b.health(now).kotak.pruned;
""")
    assert "NIFTY05NOV2624500CE" in out["expiryDay"]                                            # nothing has pruned yet in this request
    assert out["expiryDayAfterPrune"] == ["NIFTY", "NIFTY-FUT", "NIFTY12NOV2624500CE", "NIFTY19NOV2624500CE"]      # the 5 Nov contract is gone, the expiry-day one stays
    assert out["dayAfter"] == ["NIFTY", "NIFTY-FUT", "NIFTY19NOV2624500CE"] and out["pruned"] == 2


@needs_node
def test_an_expiry_roll_cannot_fill_the_board_so_new_contracts_are_still_accepted(tmp_path):
    out = run(tmp_path, r"""
const b = mk(); await b.ready;
// the board is full: 5,900 contracts of an expiry that has passed, and 100 current names
const old = {}; for (let i = 0; i < 5900; i++) old["S" + i + "05NOV2610" + (i % 90) + "CE"] = { ltp: 1 };
for (let k = 0; k < 3; k++) { const part = {}; Object.entries(old).slice(k * 2000, k * 2000 + 2000).forEach(([n, q]) => { part[n] = q; }); await push(b, part); }
const cur = {}; for (let i = 0; i < 100; i++) cur["C" + i] = { ltp: 2 };
await push(b, cur);
out.full = b.quotes.size;
now = Date.UTC(2026, 10, 13, 4, 30);                                                       // the next day: the 5 Nov names are long past their expiry
const r = await push(b, { NEWOPT: { ltp: 5 }, RELIANCE24NOV261300CE: { ltp: 6 } });
out.after = { accepted: r.n, refused: r.refused, size: b.quotes.size, hasNew: b.quotes.has("NEWOPT") };
""")
    assert out["full"] == 6000                                                                  # it really was full
    assert out["after"]["accepted"] == 2 and out["after"]["refused"] == 0 and out["after"]["hasNew"] is True      # the expired names made room
    assert out["after"]["size"] < 200
