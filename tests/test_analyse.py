"""The market read (the AN block in quantdesk/web/static/app/app.js), run under Node: implied volatility, the move the straddle prices, skew, term structure, put/call balance, max pain, open-interest walls,
unusual activity and the model chance of profit, each against a known answer. Pure maths on a board: no DOM, no network, and nothing here is a forecast."""
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


def block(name: str) -> str:
    m = re.search(rf"/\* @@{name}:start \*/.*?/\* @@{name}:end \*/", APP, re.S)
    assert m, f"the {name} block markers are missing from app.js"
    return m.group(0)


def node(tmp_path, script: str):
    (tmp_path / "a.js").write_text(block("builder") + "\n" + block("analyse") + "\n" + script, encoding="utf-8")
    r = subprocess.run(["node", "a.js"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


BOARD = r"""
const STRIKES = [24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700];
const SPOT = 24500, T = 7 / 365, R = 0.07;
const names = {}; STRIKES.forEach((k) => names[k] = { CE: "C" + k, PE: "P" + k });
// put/call volatilities by strike so skew is known; open interest and volume set per test
const board = (ivc = () => 0.14, ivp = () => 0.14, oic = () => 1000, oip = () => 1000) => {
  const q = {};
  STRIKES.forEach((k) => {
    const c = QB.bs("CE", SPOT, k, T, ivc(k), R), p = QB.bs("PE", SPOT, k, T, ivp(k), R);
    q["C" + k] = { ltp: c, bid: c * 0.995, ask: c * 1.005, oi: oic(k), vol: 100, age_s: 2 };
    q["P" + k] = { ltp: p, bid: p * 0.995, ask: p * 1.005, oi: oip(k), vol: 100, age_s: 2 };
  });
  return q;
};
const rowsOf = (q, t = T) => AN.chainRows(names, q, SPOT, t, R);
const out = {};
"""


@needs_node
def test_the_atm_volatility_and_the_move_the_straddle_prices_are_recovered_from_prices(tmp_path):
    o = node(tmp_path, BOARD + r"""
const rows = rowsOf(board());
const a = AN.atm(rows, SPOT, T, -0.45);
console.log(JSON.stringify({ k: a.k, iv: a.iv, straddle: a.straddle, em: a.expiryMovePct, dm: a.dayMovePct, today: a.todayPct, ratio: a.todayVsImplied, ivs: rows.map((r) => [r.ce.iv, r.pe.iv]) }));
""")
    assert o["k"] == 24500 and o["iv"] == pytest.approx(0.14, abs=0.003)                                # the volatility the prices were made with comes back
    assert o["em"] == pytest.approx(o["straddle"] / 24500 * 100, rel=1e-9) and 1.5 < o["em"] < 2.5      # a week at 14% prices roughly 1.7-2% either way
    assert o["dm"] == pytest.approx(0.14 / 252 ** 0.5 * 100, abs=0.02) and o["today"] == -0.45 and o["ratio"] == pytest.approx(0.45 / o["dm"], rel=1e-9)
    assert all(abs(c - 0.14) < 0.02 and abs(p - 0.14) < 0.02 for c, p in o["ivs"] if c is not None and p is not None)


@needs_node
def test_skew_is_the_put_wings_volatility_minus_the_call_wings_and_signed_right(tmp_path):
    o = node(tmp_path, BOARD + r"""
const rich = rowsOf(board((k) => 0.14, (k) => 0.14 + (24500 - k) * 0.0001));         // lower strikes' puts dearer: puts +2 vol points at 24300
const flat = rowsOf(board());
const calls = rowsOf(board((k) => 0.14 + (k - 24500) * 0.0001, (k) => 0.14));          // calls dearer in the wings: negative skew number
console.log(JSON.stringify({ rich: AN.skew(rich, SPOT, 3), flat: AN.skew(flat, SPOT, 3), calls: AN.skew(calls, SPOT, 3), tooWide: AN.skew(flat, SPOT, 6) }));
""")
    assert o["rich"]["points"] == pytest.approx(1.5 * 100 * 0.01 * 1.0, abs=0.35) and o["rich"]["points"] > 0.8        # 3 strikes down = 150 points x 0.0001 = 1.5 vol points
    assert abs(o["flat"]["points"]) < 0.3 and o["calls"]["points"] < -0.8 and o["tooWide"] is None                   # no wing that far out on the board: no answer, not a guess


@needs_node
def test_put_call_ratio_max_pain_and_the_open_interest_walls_match_hand_calculations(tmp_path):
    o = node(tmp_path, BOARD + r"""
const big = (k) => (k === 24500 ? 9000 : 1000);
const rows = rowsOf(board(() => 0.14, () => 0.14, big, big));
const pc = AN.pcr(rows);
const skewed = rowsOf(board(() => 0.14, () => 0.14, () => 1000, () => 2000));
// walls: call OI peaks at 24600 (above spot), put OI peaks at 24400 (below spot)
const w = AN.walls(rowsOf(board(() => 0.14, () => 0.14, (k) => (k === 24600 ? 8000 : k === 24650 ? 5000 : 1000), (k) => (k === 24400 ? 7000 : 1000))), SPOT, 2);
// max pain with all the open interest at 24500 is 24500; with calls only at 24400 and puts only at 24600 it sits between them
const pain1 = AN.maxPain(rows);
const pain2 = AN.maxPain(rowsOf(board(() => 0.14, () => 0.14, (k) => (k === 24400 ? 5000 : 0), (k) => (k === 24600 ? 5000 : 0))));
const none = AN.maxPain(rowsOf(board(() => 0.14, () => 0.14, () => 0, () => 0)));
console.log(JSON.stringify({ pc, pcr2: AN.pcr(skewed).oi, w, pain1, pain2, none }));
""")
    assert o["pc"]["oi"] == pytest.approx(1.0) and o["pcr2"] == pytest.approx(2.0) and o["pc"]["callOi"] == 17000
    assert [x["k"] for x in o["w"]["resistance"]] == [24600, 24650] and [x["k"] for x in o["w"]["support"]][-1:] == [24400]
    assert o["pain1"] == 24500 and 24400 <= o["pain2"] <= 24600 and o["none"] is None                                # no open interest: no max pain, not a made-up strike


@needs_node
def test_term_structure_and_unusual_activity(tmp_path):
    o = node(tmp_path, BOARD + r"""
const front = rowsOf(board(() => 0.16, () => 0.16), 7 / 365), back = rowsOf(board(() => 0.14, () => 0.14), 7 / 365);
const tm = AN.term(front, back, SPOT, 7 / 365, 14 / 365);
const quotes = {
  "NIFTY12NOV2624500CE": { ltp: 100, chg: 5, vol: 90000, oi: 100000, age_s: 3 },     // ratio 0.9: hard traded
  "NIFTY12NOV2624600CE": { ltp: 60, chg: 1, vol: 30000, oi: 100000, age_s: 3 },      // 0.3: ordinary
  "RELIANCE30NOV261500PE": { ltp: 12, chg: 40, vol: 50000, oi: 20000, age_s: 5 },    // 2.5: very hard
  "NIFTY12NOV2624700CE": { ltp: 30, vol: 99999, oi: 100000, age_s: 900 },            // stale: ignored
  "NIFTY12NOV2624800CE": { ltp: 20, vol: 600, oi: 100, age_s: 2 },                   // too little volume: ignored
  "NIFTY": { ltp: 24500, age_s: 1 }, "__proto__12NOV2624500CE": { ltp: 5, vol: 1000, oi: 1000, age_s: 1 },                 // a hostile name is only data
};
const u = AN.unusual(quotes, 5, 120);
console.log(JSON.stringify({ tm, u: u.map((x) => [x.name, x.u, x.k, x.t, +x.ratio.toFixed(2)]) }));
""")
    assert o["tm"]["points"] == pytest.approx(2.0, abs=0.4) and o["tm"]["front"] > o["tm"]["back"]                    # the front expiry is dearer: the market prices something near
    names = [x[0] for x in o["u"]]
    assert names[0] == "RELIANCE30NOV261500PE" and "NIFTY12NOV2624500CE" in names and "NIFTY12NOV2624600CE" not in names and "NIFTY12NOV2624700CE" not in names and "NIFTY12NOV2624800CE" not in names
    assert o["u"][0][1:] == ["RELIANCE", 1500, "PE", 2.5] and "__proto__12NOV2624500CE" in names


@needs_node
def test_the_model_chance_matches_the_closed_form_for_a_long_call_and_the_structures_order_sensibly(tmp_path):
    o = node(tmp_path, BOARD + r"""
const sig = 0.14, K = 24500;
const q = board(() => sig, () => sig);
const L = (id, w) => QB.legsFor(id, STRIKES, SPOT, names, w).legs;
const an = (id, w) => QB.analyze({ u: "NIFTY", legs: L(id, w), quotes: q.constructor === Object ? Object.fromEntries(Object.entries(q).map(([n, v]) => [n, { ...v, age_s: 2 }])) : q, spot: SPOT, spotAge: 2, T, lots: 1 });
const call = an("long_call", 1);
const be = call.breakevens[0];
const d2 = (Math.log(SPOT / be) + (R - sig * sig / 2) * T) / (sig * Math.sqrt(T));
const cond = an("iron_condor", 2), strad = an("long_straddle", 1);
const p = (a) => AN.pop(a.legs, SPOT, T, sig, R);
const [b1, b2] = strad.breakevens;
const cdf = (b) => QB.ncdf((Math.log(b / SPOT) - (R - sig * sig / 2) * T) / (sig * Math.sqrt(T)));
const closedStrad = cdf(b1) + (1 - cdf(b2));                                           // wins when it ends below the lower or above the upper break-even
console.log(JSON.stringify({ call: p(call), closed: QB.ncdf(d2), strad: p(strad), closedStrad, cond: p(cond), none: AN.pop([], SPOT, T, sig, R), bad: AN.pop(call.legs, SPOT, 0, sig, R) }));
""")
    assert o["call"] == pytest.approx(o["closed"], abs=0.01) and o["strad"] == pytest.approx(o["closedStrad"], abs=0.01)   # the integral agrees with the formula, for a one-sided and a two-sided structure
    assert 0.3 < o["call"] < 0.5 and 0 < o["cond"] < 1 and 0.2 < o["strad"] < 0.5                                       # a long option wins less than half the time: you pay for the move
    assert o["none"] is None and o["bad"] is None


@needs_node
def test_ideas_are_every_structure_that_fits_the_view_and_the_ranking_is_by_what_you_asked(tmp_path):
    o = node(tmp_path, BOARD + r"""
const q = board();
const an = (id, w) => QB.analyze({ u: "NIFTY", legs: (QB.legsFor(id, STRIKES, SPOT, names, w).legs || []), quotes: q, spot: SPOT, spotAge: 2, T, lots: 1 });
const ctx = { spot: SPOT, T, sigma: 0.14, r: R };
const up = AN.ideas("up", an, ctx), big = AN.ideas("big", an, ctx), none = AN.ideas("sideways", an, ctx);
const byRR = AN.rank(up, "rr"), byPop = AN.rank(up, "pop"), byCheap = AN.rank(up, "cheap");
console.log(JSON.stringify({ upIds: [...new Set(up.map((x) => x.id))].sort(), bigIds: [...new Set(big.map((x) => x.id))].sort(), none, n: up.length,
  rrOrder: byRR.map((x) => x.rr === Infinity ? 1e9 : x.rr), popOrder: byPop.map((x) => x.pop), cheapOrder: byCheap.map((x) => Math.abs(x.premium)),
  flags: up.map((x) => [x.id, x.paperOk]), fields: Object.keys(up[0]).sort() }));
""")
    assert o["upIds"] == ["bull_call_spread", "bull_put_spread", "long_call"] and o["bigIds"] == ["long_straddle", "long_strangle"] and o["none"] == []
    assert o["rrOrder"] == sorted(o["rrOrder"], reverse=True) and o["popOrder"] == sorted(o["popOrder"], reverse=True) and o["cheapOrder"] == sorted(o["cheapOrder"])
    assert all(ok is False for id, ok in o["flags"] if id != "long_call")                                                  # a spread has a short leg: the paper desk cannot open it (the long call depends on size and price)
    assert {"id", "width", "name", "premium", "maxLoss", "maxProfit", "rr", "breakevens", "paperOk", "fits", "pop"} <= set(o["fields"])


def test_the_market_read_block_places_no_order_and_touches_no_network_or_page():
    b = block("analyse")
    assert not re.search(r"fetch\(|XMLHttpRequest|localStorage|document\.|window\.|innerHTML|paperCall|place_order", b)


def test_the_build_tab_shows_the_read_and_the_ideas_above_the_builder_and_says_what_they_are_not():
    draw = APP[APP.index("function bdDraw"):APP.index("function legsTable2")]
    assert "bdRead({" in draw and "bdIdeas({" in draw and draw.index("bdRead({") < draw.index("QB.legsFor(B.tpl")        # the read comes before the structure being built
    read = APP[APP.index("function bdRead"):APP.index("function bdIdeas")]
    ideas = APP[APP.index("function bdIdeas"):APP.index("function bdPayoff")].split("// ---- news and the board")[0]
    assert "not forecasts" in read and "this read may be stale" in read and "fair bet" in ideas and "Your edge is your view" in ideas
    assert "innerHTML" not in read + ideas and "paperCall" not in read + ideas and "fetch(" not in read + ideas              # read and ideas are display only
    assert 'onclick: () => { B.tpl = x.id; B.width = x.width; bdDraw();' in ideas                                           # 'Build this' only fills the builder; nothing is sent
