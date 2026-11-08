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
    assert 'const PAPER_PATHS = new Set(["/paper/order", "/paper/kill", "/paper/state"]);' in APP and "not a paper route" in APP
    assert len(re.findall(r"fetch\(", APP[APP.index("async function paperCall"):APP.index("// ---- the ticket in the Build tab")])) == 1      # one fetch, in paperCall
    ticket = APP[APP.index("function bdTicket"):APP.index("// ---- the Paper tab")]
    assert ticket.count('paperCall("POST", "/paper/order", o)') == 1 and ticket.index('if (tk.stage === "review" && built.orders)') < ticket.index('paperCall("POST", "/paper/order", o)')      # the send exists only on the review step
    assert 'if (r.status !== 200) break;' in ticket                                                                              # a refused first leg stops the rest
    tab = APP[APP.index("// ---- the Paper tab"):APP.index("// refresh loop, pull to refresh, boot")]
    assert 'P.confirm = "kill"' in tab and 'P.confirm = "sell:" + p.symbol' in tab                                                # kill and sell are two taps
    assert tab.count('paperCall("POST"') == 2 and "innerHTML" not in APP


def test_the_ticket_is_not_offered_where_the_paper_desk_would_refuse_and_the_tab_says_when_the_runner_is_silent():
    ticket = APP[APP.index("function bdTicket"):APP.index("// ---- the Paper tab")]
    assert "if (!a.paperOk) return" in ticket and ticket.index("if (!a.paperOk) return") < ticket.index("Review order")
    tab = APP[APP.index("function ppDraw"):APP.index("async function renderPaper")]
    assert "The paper runner has not reported yet" in tab and "last reported" in tab and "Held past expiry with no price" in tab
    assert "github\\.io" in APP[APP.index("async function renderPaper"):APP.index("// refresh loop, pull to refresh, boot")]           # not on the public copy
