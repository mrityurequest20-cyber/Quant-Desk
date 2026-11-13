"""Flow and signals (the FL block in quantdesk/web/static/app/app.js): the futures basis, the forward the options imply, resting-size pressure, a dealer-gamma proxy, the written-down rules,
and the log that grades every firing against what the price did next. Run under Node. Pure maths: display only, no network, no page."""
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
    (tmp_path / "f.js").write_text("\n".join(block(b) for b in ("builder", "analyse", "flow")) + "\n" + script, encoding="utf-8")
    r = subprocess.run(["node", "f.js"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


BOARD = r"""
const STRIKES = [24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700];
const names = {}; STRIKES.forEach((k) => names[k] = { CE: "C" + k, PE: "P" + k });
const SPOT = 24500, T = 5 / 365, R = 0.065, LOT = 65;
const mk = (iv, o = {}) => { const q = {}; STRIKES.forEach((k) => {
  const c = QB.bs("CE", SPOT, k, T, iv, R), p = QB.bs("PE", SPOT, k, T, iv, R);
  q["C" + k] = { ltp: c, bid: c - 0.1, ask: c + 0.1, bid_qty: o.cb ?? 1000, ask_qty: o.ca ?? 1000, oi: o.coi ?? 100000, vol: 1, age_s: 2 };
  q["P" + k] = { ltp: p, bid: p - 0.1, ask: p + 0.1, bid_qty: o.pb ?? 1000, ask_qty: o.pa ?? 1000, oi: o.poi ?? 100000, vol: 1, age_s: 2 };
}); return q; };
const rowsOf = (q) => AN.chainRows(names, q, SPOT, T, R);
const out = {};
"""


@needs_node
def test_the_forward_the_options_imply_equals_the_futures_price_when_the_board_is_consistent_and_shows_a_gap_when_it_is_not(tmp_path):
    o = node(tmp_path, BOARD + r"""
const q = mk(0.14), rows = rowsOf(q), fwd = SPOT * Math.exp(R * T);
const same = FL.parity(rows, SPOT, T, R, fwd), rich = FL.parity(rows, SPOT, T, R, fwd * 0.998), none = FL.parity(rows, SPOT, T, R, null);
out.same = same.gapPct; out.rich = rich.gapPct; out.none = none.gapPct; out.fwd = same.fwd; out.expect = fwd;
out.empty = FL.parity([], SPOT, T, R, fwd); out.expired = FL.parity(rows, SPOT, 0, R, fwd);
console.log(JSON.stringify(out));
""")
    assert abs(o["same"]) < 0.05 and o["fwd"] == pytest.approx(o["expect"], rel=2e-4)                                       # put-call parity recovers the forward
    assert o["rich"] == pytest.approx(0.2, abs=0.06) and o["none"] is None and o["empty"] is None and o["expired"] is None


@needs_node
def test_pressure_leans_the_right_way_and_needs_fresh_sized_two_sided_quotes(tmp_path):
    o = node(tmp_path, BOARD + r"""
const bull = FL.pressure(names, mk(0.14, { cb: 3000, ca: 1000, pb: 1000, pa: 3000 }), SPOT, 3, 60);
const bear = FL.pressure(names, mk(0.14, { cb: 1000, ca: 3000, pb: 3000, pa: 1000 }), SPOT, 3, 60);
const flat = FL.pressure(names, mk(0.14), SPOT, 3, 60);
const stale = mk(0.14); Object.values(stale).forEach((x) => { x.age_s = 500; });
const nosize = mk(0.14); Object.values(nosize).forEach((x) => { delete x.bid_qty; });
const oneSided = mk(0.14); Object.values(oneSided).forEach((x) => { x.bid = 0; });
console.log(JSON.stringify({ bull: bull.score, bear: bear.score, flat: flat.score, stale: FL.pressure(names, stale, SPOT, 3, 60), nosize: FL.pressure(names, nosize, SPOT, 3, 60), one: FL.pressure(names, oneSided, SPOT, 3, 60), used: bull.used }));
""")
    assert o["bull"] == pytest.approx(1.0) and o["bear"] == pytest.approx(-1.0) and o["flat"] == pytest.approx(0.0) and o["used"] == 14
    assert o["stale"] is None and o["nosize"] is None and o["one"] is None                                                   # no fresh, sized, two-sided quote: no reading rather than a made-up one


@needs_node
def test_the_gamma_proxy_is_positive_when_calls_dominate_negative_when_puts_do_and_finds_the_flip(tmp_path):
    o = node(tmp_path, BOARD + r"""
const calls = FL.gamma(rowsOf(mk(0.14, { coi: 300000, poi: 10000 })), SPOT, T, R, LOT);
const puts = FL.gamma(rowsOf(mk(0.14, { coi: 10000, poi: 300000 })), SPOT, T, R, LOT);
const q = mk(0.14); STRIKES.forEach((k) => { q["C" + k].oi = k >= SPOT ? 400000 : 1000; q["P" + k].oi = k < SPOT ? 400000 : 1000; });
const mixed = FL.gamma(rowsOf(q), SPOT, T, R, LOT);
const noOi = FL.gamma(rowsOf(mk(0.14, { coi: 0, poi: 0 })), SPOT, T, R, LOT);
console.log(JSON.stringify({ calls, puts, mixed, noOi, bad: FL.gamma(rowsOf(mk(0.14)), 0, T, R, LOT) }));
""")
    assert o["calls"]["net"] > 0 and o["puts"]["net"] < 0 and o["noOi"] is None and o["bad"] is None
    assert o["mixed"]["flip"] in (24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700) or o["mixed"]["flip"] is None


@needs_node
def test_each_rule_fires_on_its_condition_and_not_otherwise(tmp_path):
    o = node(tmp_path, r"""
const out = {};
const S = (t, o = {}) => ({ t, spot: 24500, fut: 24520, basis: 20, atmIv: 0.14, straddle: 200, fwd: 24520, gapPct: 0, pressure: 0, gexNet: 1, flip: 24400, ...o });
const names = (h) => FL.fire(h).map((f) => f.rule + ":" + f.dir).sort();
const t0 = 1_000_000_000_000;
out.quiet = names([S(t0)]);
out.pressureUp = names([S(t0, { pressure: 0.3 })]); out.pressureDn = names([S(t0, { pressure: -0.3 })]); out.pressureBelow = names([S(t0, { pressure: 0.24 })]);
out.parityUp = names([S(t0, { gapPct: 0.06 })]); out.parityDn = names([S(t0, { gapPct: -0.06 })]); out.parityBelow = names([S(t0, { gapPct: 0.04 })]);
out.gammaDn = names([S(t0, { gexNet: -5, flip: 24600 })]); out.gammaUp = names([S(t0, { gexNet: -5, flip: 24400 })]); out.gammaPositive = names([S(t0, { gexNet: 5, flip: 24600 })]); out.gammaNoFlip = names([S(t0, { gexNet: -5, flip: null })]);
const old = S(t0 - 650000, { straddle: 200 });
out.straddleUp = names([old, S(t0, { straddle: 212 })]); out.straddleSmall = names([old, S(t0, { straddle: 204 })]); out.straddleMoved = names([old, S(t0, { straddle: 212, spot: 24560 })]); out.straddleNoPast = names([S(t0 - 100000), S(t0, { straddle: 212 })]);
out.empty = FL.fire([]);
console.log(JSON.stringify(out));
""")
    assert o["quiet"] == [] and o["empty"] == []
    assert o["pressureUp"] == ["pressure_v1:1"] and o["pressureDn"] == ["pressure_v1:-1"] and o["pressureBelow"] == []
    assert o["parityUp"] == ["parity_v1:1"] and o["parityDn"] == ["parity_v1:-1"] and o["parityBelow"] == []
    assert o["gammaDn"] == ["gamma_v1:-1"] and o["gammaUp"] == ["gamma_v1:1"] and o["gammaPositive"] == [] and o["gammaNoFlip"] == []
    assert o["straddleUp"] == ["straddle_v1:0"] and o["straddleSmall"] == [] and o["straddleMoved"] == [] and o["straddleNoPast"] == []


@needs_node
def test_firings_are_logged_once_per_window_graded_against_the_tape_and_a_record_needs_thirty_and_a_clear_edge(tmp_path):
    o = node(tmp_path, r"""
const out = {};
const t0 = 1_000_000_000_000, MIN = 60000;
const S = (t, spot) => ({ t, spot, straddle: 200 });
const fire = [{ rule: "pressure_v1", dir: 1, why: "x" }];
let log = FL.update([], [S(t0, 24500)], fire, t0);
log = FL.update(log, [S(t0, 24500), S(t0 + 5 * MIN, 24510)], fire, t0 + 5 * MIN);              // the same rule again inside 15 minutes: not logged twice
out.dedup = log.length;
const tape = [S(t0, 24500), S(t0 + 15 * MIN, 24520)];                                           // +0.08%: a hit for a call up
log = FL.update(log, tape, [], t0 + 16 * MIN); out.hit = log[0].res; out.mv = log[0].mv;
const down = FL.update([], [S(t0, 24500)], fire, t0); const flat = FL.update(down, [S(t0, 24500), S(t0 + 15 * MIN, 24501)], [], t0 + 16 * MIN); out.flat = flat[0].res;   // flat counts against it
const wrong = FL.update(down, [S(t0, 24500), S(t0 + 15 * MIN, 24400)], [], t0 + 16 * MIN); out.wrong = wrong[0].res;
const vol = FL.update([], [S(t0, 24500)], [{ rule: "straddle_v1", dir: 0, why: "x" }], t0); out.volHit = FL.update(vol, [S(t0, 24500), S(t0 + 15 * MIN, 24400)], [], t0 + 16 * MIN)[0].res; out.volMiss = FL.update(vol, [S(t0, 24500), S(t0 + 15 * MIN, 24510)], [], t0 + 16 * MIN)[0].res;
const open = FL.update(down, [S(t0, 24500)], [], t0 + 16 * MIN); out.open = open[0].res;       // no sample near the horizon: stays open
const stale = FL.update(down, [S(t0, 24500)], [], t0 + 60 * MIN); out.stale = stale[0].res;      // and is given up on later
const mkLog = (n, hits) => Array.from({ length: n }, (_, i) => ({ t: i, rule: "pressure_v1", dir: 1, spot: 1, res: i < hits ? "hit" : "miss" }));
out.r10 = FL.record(mkLog(10, 10)).pressure_v1; out.r40_20 = FL.record(mkLog(40, 20)).pressure_v1; out.r40_30 = FL.record(mkLog(40, 30)).pressure_v1; out.r29 = FL.record(mkLog(29, 29)).pressure_v1; out.none = FL.record([]).parity_v1;
console.log(JSON.stringify(out));
""")
    assert o["dedup"] == 1 and o["hit"] == "hit" and o["flat"] == "miss" and o["wrong"] == "miss" and o["volHit"] == "hit" and o["volMiss"] == "miss"
    assert o["open"] is None and o["stale"] == "ungraded"
    assert o["r10"]["proven"] is False and o["r29"]["proven"] is False                                                        # a perfect record on too few firings is still unproven
    assert o["r40_20"]["proven"] is False and o["r40_30"]["proven"] is True and o["r40_30"]["z"] == pytest.approx(3.16, abs=0.01) and o["none"]["n"] == 0


def test_the_flow_block_places_no_order_and_touches_no_network_or_page_and_the_panel_says_what_it_is_not():
    b = block("flow")
    assert not re.search(r"fetch\(|XMLHttpRequest|localStorage|document\.|window\.|innerHTML|paperCall|place_order", b)
    panel = APP[APP.index("function bdFlow"):APP.index("// ---- custom legs")]
    assert "innerHTML" not in panel and "paperCall" not in panel and "fetch(" not in panel
    assert "not forecasts" in panel and "UNPROVEN" in panel and "kept in this browser only" in panel
    chain = APP[APP.index("function liveChainView"):APP.index("function bdSync")]
    assert chain.index("bdFlow(ctx)") < chain.index("if (Date.now() - (L.extraAt || 0) < 14000) return;")      # the session's tape is read on every refresh, even while the panel is folded or not redrawn
    assert chain.index("bdRead(ctx)") < chain.index('fold("flow"') < chain.index("bdNews(S.bd, data)")
