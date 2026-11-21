"""Audit K-18 (E-02, HIGH): the relay's board was full (6,000 of 6,000 names), so new strikes and contracts were refused in silence, while 1,745 names that no feed
had refreshed all day kept their places. After a large move the new at-the-money strikes (the ones AUTO, the builder and the owner want) could not enter. Now a
full board makes room from names unrefreshed for 6 hours, the oldest first; a refusal is counted and shown in /live/health; and the watchdog's W10 says so.
Display and paper data only."""
from __future__ import annotations

import json
import subprocess

from tests.test_live import GOOD_INGEST, GOOD_READ, needs_node, stage
from tests.test_watchdog import HEAD, LIVE_HEAD, _node

SCRIPT = r"""
import { handleLive, LiveBoard } from "./live.mjs";
const mem = new Map();
const state = { storage: { get: async (k) => mem.get(k), put: async (k, v) => { mem.set(k, JSON.parse(JSON.stringify(v))); } }, blockConcurrencyWhile: async (fn) => fn() };
let T = Date.parse("2026-11-20T09:20:00+05:30");
let board = new LiveBoard(state, {});
board.now = () => T;
const LIVE = { idFromName: () => "board", get: () => ({ fetch: (u, init) => board.fetch(new Request(u, init)) }) };
const env = { LIVE, LIVE_INGEST_TOKEN: "%(I)s", LIVE_READ_TOKEN: "%(R)s" };
const call = async (method, path, { token, body } = {}) => {
  const r = await handleLive(new Request("https://qd.example" + path, { method, headers: token ? { authorization: "Bearer " + token } : {}, ...(body !== undefined ? { body: JSON.stringify(body) } : {}) }), env);
  return { status: r.status, body: await r.json() };
};
const push = (names) => call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: Object.fromEntries(names.map((n) => [n, { ltp: 1 }])) } });
const health = async () => (await call("GET", "/live/health", { token: env.LIVE_READ_TOKEN })).body;
const names = (p, a, b) => Array.from({ length: b - a }, (_, i) => p + (a + i));
const out = {};
await push(names("OLD", 0, 3000)); await push(names("OLD", 3000, 4500));                    // 4,500 names seen this morning, then never again
T += 30 * 60e3;
await push(names("OLD", 0, 300));                                                              // the first 300 refreshed once, half an hour later: younger than the rest
T += 6 * 3600e3;
await push(names("NEW", 0, 1500));                                                             // 1,500 names live now: the board is full
out.full = (await health()).names;
T += 30 * 60e3;                                                                                 // the OLD names are 7 hours old
const r = await push(["SILVER27NOV26140000PE"]);                                               // the audit's missing strike after silver fell 6.1 percent
out.newStrike = r.body;
const h = await health();
out.after = { names: h.names, board: h.board };
const snap = (await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN })).body.quotes;
out.kept = { strike: "SILVER27NOV26140000PE" in snap, fresh: names("NEW", 0, 1500).every((n) => n in snap), oldest_gone: !("OLD300" in snap) && !("OLD599" in snap),
             refreshed_kept: "OLD0" in snap && "OLD299" in snap, newest_old_kept: "OLD4499" in snap };
// a board full of names refreshed in the last 6 hours: nothing can make room, so a new name is refused, counted and shown
board = new LiveBoard(state, {}); board.now = () => T;
await push(names("F", 0, 3000)); await push(names("F", 3000, 6000));
T += 60e3;
out.refusedPush = (await push(["GOLD27NOV26118000PE"])).body;
out.refusedHealth = (await health()).board;
T += 2 * 3600e3;
out.later = (await health()).board.refused_last_hour;                                          // the hour's count rolls off
console.log(JSON.stringify(out));
""" % {"I": GOOD_INGEST, "R": GOOD_READ}


@needs_node
def test_a_full_board_makes_room_from_names_unrefreshed_for_six_hours_and_counts_what_it_refuses(tmp_path):
    stage(tmp_path)
    (tmp_path / "t.mjs").write_text(SCRIPT, encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["full"] == 6000
    assert out["newStrike"]["n"] == 1 and out["newStrike"]["refused"] == 0                      # was: refused (6,000 of 6,000)
    assert out["after"]["board"]["evicted"] == 300 and out["after"]["names"] == 6000 - 300 + 1
    assert out["kept"] == {"strike": True, "fresh": True, "oldest_gone": True, "refreshed_kept": True, "newest_old_kept": True}   # the oldest went first
    assert out["refusedPush"]["refused"] == 1 and out["refusedHealth"]["refused"] == 1 and out["refusedHealth"]["refused_last_hour"] == 1
    assert out["refusedHealth"]["evicted"] == 0 and out["refusedHealth"]["cap"] == 6000 and out["later"] == 0


@needs_node
def test_w10_pushes_a_p2_when_the_board_refused_new_names_in_the_last_hour(tmp_path):
    out = _node(tmp_path, HEAD + LIVE_HEAD + r"""
const D = "2026-11-23";
const w10 = (r) => r.results.filter((x) => x.check === "W10").flatMap((x) => x.alerts.map((a) => `${a.sev} ${a.title}`));
out.full = w10(await at(D + "T11:00:00", live(H({ board: { cap: 6000, names: 6000, refused: 40, evicted: 0, refused_last_hour: 12 } }))));
out.fine = w10(await at(D + "T11:00:00", live(H({ board: { cap: 6000, names: 6000, refused: 40, evicted: 300, refused_last_hour: 0 } }))));
out.old = w10(await at(D + "T11:00:00", live(H())));                                            // a relay from before the board block: nothing
console.log = () => {}; process.stdout.write(JSON.stringify(out) + "\n");
""")
    assert out["full"] == ["P2 Live board full: new names refused"] and out["fine"] == [] and out["old"] == []
