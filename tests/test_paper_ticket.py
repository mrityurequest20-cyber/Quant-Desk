"""The app's paper ticket and Paper tab (quantdesk/web/static/app/app.js): the pure ticket helpers run under Node; the page's POST surface is pinned. PAPER MONEY ONLY: the app can queue a
paper order and set the kill flag on the relay, and nothing else; the paper runner and its risk gate decide."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def block() -> str:
    m = re.search(r"/\* @@ticket:start \*/.*?/\* @@ticket:end \*/", APP, re.S)
    assert m, "the ticket block markers are missing from app.js"
    return m.group(0)


def node(tmp_path, script: str):
    (tmp_path / "t.js").write_text(block() + "\n" + script, encoding="utf-8")
    r = subprocess.run(["node", "t.js"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


THESIS = "range break with rising volume on the thirty minute chart"
LEGS = r"""
const ok = (extra = {}) => ({ paperOk: true, lots: 2, legs: [{ side: 1, name: "NIFTY12NOV2624500CE", ask: 100.2 }, { side: 1, name: "NIFTY12NOV2624400PE", ask: 80 }], ...extra });
const T = "range break with rising volume on the thirty minute chart";
"""


@needs_node
def test_ids_are_the_relays_shape_and_unique_and_limits_sit_a_little_above_the_offer(tmp_path):
    o = node(tmp_path, r"""
const ids = new Set(Array.from({ length: 500 }, () => PT.idNow()));
const lim = [0.5, 10, 100.2, 250, 1000, 2.37].map((a) => [a, PT.limitFor(a)]);
console.log(JSON.stringify({ n: ids.size, sample: [...ids][0], lim }));
""")
    assert o["n"] == 500 and re.fullmatch(r"ord-[0-9a-f]{32}", o["sample"]) and re.fullmatch(r"[A-Za-z0-9_-]{6,64}", o["sample"])        # the relay's and the runner's id rule
    for ask, lim in o["lim"]:
        assert lim >= ask + min(0.1, 0.02 * ask) - 1e-9 and lim <= ask + max(0.1, 0.02 * ask) + 0.05 + 1e-9, (ask, lim)              # two ticks or 2%, rounded up to a tick
        assert abs(lim / 0.05 - round(lim / 0.05)) < 1e-6                                                                           # on the tick grid


@needs_node
def test_a_ticket_is_built_only_for_a_structure_the_paper_desk_can_open_with_a_name_and_a_written_thesis(tmp_path):
    o = node(tmp_path, LEGS + r"""
const good = PT.ordersFor(ok(), "  Breakout   long ", T);
const bad = {
  notOk: PT.ordersFor(ok({ paperOk: false }), "s", T), undef: PT.ordersFor(ok({ paperOk: undefined }), "s", T), truthy: PT.ordersFor(ok({ paperOk: 1 }), "s", T), nolegs: PT.ordersFor(ok({ legs: [] }), "s", T), nul: PT.ordersFor(null, "s", T),
  noThesis: PT.ordersFor(ok(), "s", ""), short: PT.ordersFor(ok(), "s", "buy it now"), spaces: PT.ordersFor(ok(), "s", " ".repeat(40)), long: PT.ordersFor(ok(), "s", "x".repeat(1001)),
  noName: PT.ordersFor(ok(), "   ", T), longName: PT.ordersFor(ok(), "n".repeat(61), T),
  sellLeg: PT.ordersFor(ok({ legs: [{ side: -1, name: "NIFTY12NOV2624500CE", ask: 10 }] }), "s", T), noAsk: PT.ordersFor(ok({ legs: [{ side: 1, name: "NIFTY12NOV2624500CE", ask: 0 }] }), "s", T), noName2: PT.ordersFor(ok({ legs: [{ side: 1, ask: 5 }] }), "s", T),
};
console.log(JSON.stringify({ good, errors: Object.fromEntries(Object.entries(bad).map(([k, v]) => [k, v.error || null])), sell: PT.sellFor("NIFTY12NOV2624500CE") }));
""")
    g = o["good"]["orders"]
    assert [x["symbol"] for x in g] == ["NIFTY12NOV2624500CE", "NIFTY12NOV2624400PE"] and all(x["side"] == "buy" and x["lots"] == 2 for x in g)
    assert g[0]["strategy"] == "Breakout long" and g[0]["thesis"] == THESIS and g[0]["limit"] >= 100.2 and len({x["id"] for x in g}) == 2 and len({x["group"] for x in g}) == 1      # whitespace flattened, one group, one id per leg
    assert all(re.fullmatch(r"[A-Za-z0-9_-]{6,64}", x["id"]) and len(x["group"]) <= 40 for x in g)
    assert all(v for v in o["errors"].values()), o["errors"]                                                                         # every bad case says why
    assert o["sell"]["side"] == "sell" and o["sell"]["lots"] == "all" and "thesis" not in o["sell"]


@needs_node
def test_the_tickets_orders_pass_the_runners_own_shape_check(tmp_path):
    o = node(tmp_path, LEGS + r"""console.log(JSON.stringify({ orders: PT.ordersFor(ok(), "Breakout", T).orders, sell: PT.sellFor("NIFTY12NOV2624500CE") }));""")
    R = pytest.importorskip("quantdesk.paper.runner")                                                                                # (the runner lands in its own change)
    for x in o["orders"] + [o["sell"]]:
        cleaned, why = R.clean_order({**x, "queued_at": 1})
        assert why is None, (x, why)
        inst, why = R.parse_contract(cleaned["symbol"], {"NIFTY"}, {"NIFTY": 65})
        assert why is None and inst.symbol == cleaned["symbol"]


def test_the_page_posts_to_exactly_two_relay_routes_and_only_after_a_review_step():
    posts = re.findall(r'paperCall\("POST", "([^"]+)"', APP)
    assert sorted(set(posts)) == ["/paper/kill", "/paper/order"]                                                                  # nothing else is ever sent
    assert 'const PAPER_ROUTES = { "/paper/order": "POST", "/paper/kill": "POST", "/paper/state": "GET" };' in APP and "not a paper route" in APP
    assert len(re.findall(r"fetch\(", APP[APP.index("async function paperCall"):APP.index("// ---- the ticket in the Build tab")])) == 1      # one fetch, in paperCall
    ticket = APP[APP.index("function bdTicket"):APP.index("// ---- the Paper tab")]
    assert ticket.count('paperCall("POST", "/paper/order", o)') == 1 and ticket.index('if (tk.stage === "review" && built.orders)') < ticket.index('paperCall("POST", "/paper/order", o)')      # the send exists only on the review step
    assert 'if (r.status !== 200) break;' in ticket                                                                              # a refused first leg stops the rest
    tab = APP[APP.index("// ---- the Paper tab"):APP.index("// refresh loop, pull to refresh, boot")]
    assert 'P.confirm = killOn ? "kill:off" : "kill:on"' in tab and 'P.confirm = "sell:" + p.symbol' in tab                          # kill and sell are two taps, and the kill tap names its direction
    assert 'P.confirm === (killOn ? "kill:off" : "kill:on")' in tab                                                              # the second tap only counts for the direction that was asked about
    assert tab.count('paperCall("POST"') == 2 and "innerHTML" not in APP


def test_the_ticket_is_not_offered_where_the_paper_desk_would_refuse_and_the_tab_says_when_the_runner_is_silent():
    ticket = APP[APP.index("function bdTicket"):APP.index("// ---- the Paper tab")]
    assert "if (!a.paperOk) return" in ticket and ticket.index("if (!a.paperOk) return") < ticket.index("Review order")
    tab = APP[APP.index("function ppDraw"):APP.index("async function renderPaper")]
    assert "The paper runner has not reported yet" in tab and "last reported" in tab and "Held past expiry with no price" in tab
    assert "github\\.io" in APP[APP.index("async function renderPaper"):APP.index("// refresh loop, pull to refresh, boot")]           # not on the public copy


@needs_node
def test_the_page_can_call_only_its_three_routes_each_with_its_one_method_on_its_own_origin(tmp_path):
    o = node(tmp_path, r"""
(async () => {
	const calls = [];
	const fk = async (u, init) => { calls.push({ u, m: init.method, auth: init.headers.Authorization, signal: !!init.signal }); return { status: 200, json: async () => ({ ok: true }) }; };
	const res = {};
	for (const [m, p] of [["POST", "/paper/order"], ["POST", "/paper/kill"], ["GET", "/paper/state"], ["GET", "/paper/order"], ["POST", "/paper/state"], ["GET", "/paper/kill"], ["POST", "/live/ingest"], ["POST", "https://example.com/paper/order"], ["POST", "//example.com/paper/order"], ["POST", "/paper/order?x=1"], ["POST", "/paper/../paper/order"], ["POST", "constructor"], ["POST", "__proto__"], ["POST", "toString"]]) res[m + " " + p] = (await paperSend(fk, "k", m, p, m === "POST" ? { a: 1 } : null)).status;
	const nokey = await paperSend(fk, "", "GET", "/paper/state");
	console.log(JSON.stringify({ res, calls, nokey: nokey.status, n: calls.length }));
})();
""")
    allowed = {"POST /paper/order", "POST /paper/kill", "GET /paper/state"}
    assert {k for k, v in o["res"].items() if v == 200} == allowed, o["res"]                                                       # everything else is refused before any request
    assert o["n"] == 3 and [c["u"] for c in o["calls"]] == ["/paper/order", "/paper/kill", "/paper/state"]                         # the request goes to the relative path itself
    assert all(c["auth"] == "Bearer k" and c["signal"] for c in o["calls"]) and o["nokey"] == 0                                    # with a timeout; nothing without a key


@needs_node
def test_a_hung_request_gives_up_and_is_reported_not_left_sending_forever(tmp_path):
    o = node(tmp_path, r"""
(async () => {
	const hang = (u, init) => new Promise((_, rej) => init.signal.addEventListener("abort", () => rej(new Error("aborted"))));
	const t0 = Date.now(); const r = await paperSend(hang, "k", "POST", "/paper/order", { a: 1 }, 50);
	console.log(JSON.stringify({ status: r.status, err: r.body.error, ms: Date.now() - t0 }));
})();
""")
    assert o["status"] == 0 and "timed out" in o["err"] and o["ms"] < 5000


@needs_node
def test_numbers_the_page_cannot_trust_never_become_an_order(tmp_path):
    o = node(tmp_path, LEGS + r"""
const run = (a) => { const r = PT.ordersFor(a, "S", T); return r.error ? "ERR" : r.orders.map((x) => x.limit); };
const leg = (ask) => ({ side: 1, name: "NIFTY12NOV2624500CE", ask });
console.log(JSON.stringify({
  inf: run(ok({ legs: [leg(Infinity)] })), nan: run(ok({ legs: [leg(NaN)] })), str: run(ok({ legs: [leg("5")] })), neg: run(ok({ legs: [leg(-1)] })),
  lots0: run(ok({ lots: 0 })), lotsf: run(ok({ lots: 1.5 })), lotss: run(ok({ lots: "2" })), lotsbig: run(ok({ lots: 1001 })), lotsinf: run(ok({ lots: Infinity })), lots1000: run(ok({ lots: 1000 })), fine: run(ok()),
}));
""")
    for k in ("inf", "nan", "str", "neg", "lots0", "lotsf", "lotss", "lotsbig", "lotsinf"):
        assert o[k] == "ERR", (k, o[k])
    assert o["lots1000"] != "ERR" and o["fine"] != "ERR" and all(isinstance(x, (int, float)) for x in o["fine"])


@needs_node
def test_a_review_belongs_to_one_structure_and_the_page_resets_it_when_the_structure_changes(tmp_path):
    o = node(tmp_path, LEGS + r"""
const a = ok(), same = ok({ legs: [{ side: 1, name: "NIFTY12NOV2624500CE", ask: 90 }, { side: 1, name: "NIFTY12NOV2624400PE", ask: 70 }] });
console.log(JSON.stringify({ same: PT.sigOf(a) === PT.sigOf(same), lots: PT.sigOf(a) !== PT.sigOf(ok({ lots: 3 })), strike: PT.sigOf(a) !== PT.sigOf(ok({ legs: [{ side: 1, name: "NIFTY12NOV2624600CE", ask: 100 }, a.legs[1]] })), none: PT.sigOf({ paperOk: false, legs: a.legs, lots: 2 }) }));
""")
    assert o["same"] is True and o["lots"] is True and o["strike"] is True and o["none"] == ""                                    # prices move, the structure does not
    ticket = APP[APP.index("function bdTicket"):APP.index("// ---- the Paper tab")]
    assert 'if (tk.sig !== sig) { if (!tk.busy) { tk.sig = sig; tk.stage = "edit";' in ticket                                       # a changed structure voids the review and the "sent" screen
    assert "`Strategy: ${PT.flat(strategy)}`" in ticket                                                                            # the review shows what is sent
    assert "if (tk.busy) return;" in ticket and "ev.currentTarget.disabled = true" in ticket                                        # one tap, one send


def test_double_taps_on_sell_and_kill_do_nothing_and_a_half_made_confirm_expires():
    tab = APP[APP.index("// ---- the Paper tab"):APP.index("// refresh loop, pull to refresh, boot")]
    assert tab.count("if (P.acting) return; P.acting = true;") == 2 and tab.count("P.acting = false;") >= 2
    assert "Date.now() - P.confirmAt < 30000" in tab and "S.pp.confirm = null" in APP[APP.index("function show(tab"):APP.index("function show(tab") + 600]
    assert "it sends no order" not in APP and "sends no order" not in (ROOT / "docs/RECORDING.md").read_text(encoding="utf-8")        # the old "sends nothing" texts are gone


@needs_node
def test_each_order_carries_the_prices_the_trader_saw_only_when_they_are_sane(tmp_path):
    o = node(tmp_path, LEGS + r"""
const withBook = (extra) => ok({ legs: [{ side: 1, name: "NIFTY12NOV2624500CE", ask: 100.2, bid: 99.4, age: 2, ...extra }] });
const ref = (a, now) => PT.ordersFor(a, "S", T, undefined, now).orders[0].ref;
console.log(JSON.stringify({
  good: ref(withBook({}), 1789000010000), noNow: ref(withBook({}), NaN), crossed: ref(withBook({ bid: 101 }), 1789000010000) || null, zero: ref(withBook({ bid: 0 }), 1789000010000) || null,
  str: ref(withBook({ bid: "99" }), 1789000010000) || null, noBook: ref(ok(), 1789000010000) || null, negAge: ref(withBook({ age: -5 }), 1789000010000),
}));
""")
    assert o["good"] == {"bid": 99.4, "ask": 100.2, "at": 1789000008000}                                                          # the quote's own time: the snapshot's less its age
    assert o["noNow"] == {"bid": 99.4, "ask": 100.2} and o["negAge"] == {"bid": 99.4, "ask": 100.2}                                 # no time rather than a made-up one
    assert o["crossed"] is None and o["zero"] is None and o["str"] is None and o["noBook"] is None                                  # a bad book sends no reference; the order still goes
