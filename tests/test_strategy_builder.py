"""The strategy builder's maths (the QB block in quantdesk/web/static/app/app.js), run under Node: pricing and Greeks, the structures' payoffs and break-evens, the defined-risk rule, the cost formula
against the desk's own CostModel, the limits from the config, and the lot sizing. Pure functions: no DOM, no network."""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.config import DEFAULT_CONFIG, Config
from quantdesk.core.types import Instrument
from quantdesk.execution.costs import CostModel

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "quantdesk/web/static/app/app.js").read_text(encoding="utf-8")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def block() -> str:
    m = re.search(r"/\* @@builder:start \*/.*?/\* @@builder:end \*/", APP, re.S)
    assert m, "the builder block markers are missing from app.js"
    return m.group(0)


def node(tmp_path, script: str):
    (tmp_path / "b.js").write_text(block() + "\n" + script, encoding="utf-8")
    r = subprocess.run(["node", "b.js"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


BOARD = r"""
const STRIKES = [24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700];
const names = {}; STRIKES.forEach((k) => names[k] = { CE: "C" + k, PE: "P" + k });
const SPOT = 24500, T = 3 / 365;
const q = {};
STRIKES.forEach((k) => {
  const iv = 0.14, c = QB.bs("CE", SPOT, k, T, iv, 0.07), p = QB.bs("PE", SPOT, k, T, iv, 0.07), w = (x) => Math.max(0.1, x * 0.01);
  q["C" + k] = { ltp: +c.toFixed(2), bid: +(c - w(c)).toFixed(2), ask: +(c + w(c)).toFixed(2) };
  q["P" + k] = { ltp: +p.toFixed(2), bid: +(p - w(p)).toFixed(2), ask: +(p + w(p)).toFixed(2) };
});
const run = (id, width, lots) => { const L = QB.legsFor(id, STRIKES, SPOT, names, width); return L.error ? L : QB.analyze({ u: "NIFTY", legs: L.legs, quotes: q, spot: SPOT, T, lots: lots || 1 }); };
const out = {};
"""


@needs_node
def test_black_scholes_prices_greeks_and_implied_vol_agree_with_known_values(tmp_path):
    o = node(tmp_path, r"""
const c = QB.bs("CE", 100, 100, 1, 0.2, 0.05), p = QB.bs("PE", 100, 100, 1, 0.2, 0.05);
const g = QB.greeks("CE", 100, 100, 1, 0.2, 0.05), gp = QB.greeks("PE", 100, 100, 1, 0.2, 0.05);
console.log(JSON.stringify({ c, p, parity: c - p - (100 - 100 * Math.exp(-0.05)), delta: g.delta, deltaP: gp.delta, gamma: g.gamma, vega: g.vega, iv: QB.impliedVol("CE", c, 100, 100, 1, 0.05),
  ivBad: QB.impliedVol("CE", 0.0001, 100, 100, 1, 0.05), expired: QB.bs("CE", 105, 100, 0, 0.2, 0.05), now: QB.yearsTo("12NOV26", Date.UTC(2026, 10, 9, 4, 30)) }));
""")
    assert o["c"] == pytest.approx(10.4506, abs=1e-3) and o["p"] == pytest.approx(5.5735, abs=1e-3) and abs(o["parity"]) < 1e-6        # put-call parity
    assert o["delta"] == pytest.approx(0.6368, abs=1e-3) and o["deltaP"] == pytest.approx(-0.3632, abs=1e-3) and o["gamma"] == pytest.approx(0.01876, abs=1e-4) and o["vega"] == pytest.approx(0.3752, abs=1e-3)
    assert o["iv"] == pytest.approx(0.2, abs=1e-4) and o["ivBad"] is None and o["expired"] == 5                               # an impossible price has no IV; an expired option is its intrinsic value
    assert o["now"] == pytest.approx((3 * 86400 + 5.5 * 3600) / 31556952, rel=1e-3)                                               # 9 Nov 10:00 IST to 12 Nov 15:30 IST


@needs_node
def test_each_structure_has_the_payoff_the_textbook_gives_and_defined_risk(tmp_path):
    o = node(tmp_path, BOARD + r"""
for (const id of Object.keys(QB.TEMPLATES)) { const a = run(id, 2, 1); out[id] = a.error ? { error: a.error } : { risk: a.definedRisk, prem: a.premium, maxP: a.maxProfit === Infinity ? "inf" : a.maxProfit, maxL: a.maxLoss, be: a.breakevens, ok: a.ok, unl: a.unlimitedProfit }; }
console.log(JSON.stringify(out));
""")
    lot, step, w = 65, 50, 2
    for id, d in o.items():
        assert "error" not in d, (id, d)
        assert d["risk"] is True
    for id in ("long_call", "long_put", "long_straddle", "long_strangle"):
        assert o[id]["maxL"] == pytest.approx(o[id]["prem"], rel=1e-9)                                  # a long option structure can lose the premium and no more
    assert o["long_call"]["maxP"] == "inf" and o["long_straddle"]["maxP"] == "inf"
    for id in ("bull_call_spread", "bear_put_spread"):                                                   # debit spreads: max profit = width - debit, max loss = debit
        assert o[id]["maxP"] == pytest.approx(w * step * lot - o[id]["prem"], rel=1e-9) and o[id]["maxL"] == pytest.approx(o[id]["prem"], rel=1e-9)
    for id in ("bull_put_spread", "bear_call_spread"):                                                   # credit spreads: max profit = credit, max loss = width - credit
        assert o[id]["prem"] < 0 and o[id]["maxP"] == pytest.approx(-o[id]["prem"], rel=1e-9) and o[id]["maxL"] == pytest.approx(w * step * lot + o[id]["prem"], rel=1e-9)
    for id in ("iron_condor", "iron_butterfly"):
        assert o[id]["prem"] < 0 and o[id]["maxP"] == pytest.approx(-o[id]["prem"], rel=1e-9) and o[id]["maxL"] == pytest.approx(w * step * lot + o[id]["prem"], rel=1e-9)
    assert len(o["long_straddle"]["be"]) == 2 and len(o["iron_condor"]["be"]) == 2 and len(o["bull_call_spread"]["be"]) == 1


@needs_node
def test_a_structure_with_an_uncovered_short_call_is_refused_and_a_missing_price_says_so(tmp_path):
    o = node(tmp_path, BOARD + r"""
const naked = QB.analyze({ u: "NIFTY", legs: [{ side: -1, type: "CE", strike: 24500, name: "C24500" }], quotes: q, spot: SPOT, T, lots: 1 });
const ratio = QB.analyze({ u: "NIFTY", legs: [{ side: 1, type: "CE", strike: 24500, name: "C24500" }, { side: -1, type: "CE", strike: 24600, name: "C24600" }, { side: -1, type: "CE", strike: 24650, name: "C24650" }], quotes: q, spot: SPOT, T, lots: 1 });
const nopx = QB.analyze({ u: "NIFTY", legs: [{ side: 1, type: "CE", strike: 24500, name: "NOPE" }], quotes: q, spot: SPOT, T, lots: 1 });
const edge = QB.legsFor("iron_condor", STRIKES, SPOT, names, 4);
const nakedPut = QB.analyze({ u: "NIFTY", legs: [{ side: -1, type: "PE", strike: 24500, name: "P24500" }], quotes: q, spot: SPOT, T, lots: 1 });
console.log(JSON.stringify({ naked: naked.errors, ratio: ratio.errors, nopx: nopx.errors, edge: edge.error, nakedPutDefined: nakedPut.definedRisk }));
""")
    assert o["naked"] and "uncovered" in o["naked"][0] and o["ratio"] and "uncovered" in o["ratio"][0]            # a 1x2 call ratio leaves a short call uncovered
    assert o["nopx"] == ["A leg has no price on the board yet."] and "not on the board" in o["edge"]
    assert o["nakedPutDefined"] is True                                                                          # a short put's loss is bounded by the strike (still refused by the limits, not by this rule)


@needs_node
def test_the_cost_formula_matches_the_desks_own_cost_model_to_the_paisa(tmp_path):
    cfg = Config.load(DEFAULT_CONFIG)
    cm = CostModel(cfg)
    o = node(tmp_path, r"""
const c = QB.conf();
const cases = [[1, 120.5, 65], [-1, 120.5, 65], [1, 0.35, 650], [-1, 250.0, 30], [1, 18.2, 1200]];
console.log(JSON.stringify({ fees: cases.map(([s, p, u]) => QB.fees(s, p, u, c)), half: [120.5, 0.35, 250, 18.2].map((p) => QB.halfSpread(p, c)) }));
""")
    cases = [(1, 120.5, 65), (-1, 120.5, 65), (1, 0.35, 650), (-1, 250.0, 30), (1, 18.2, 1200)]
    inst = Instrument.option("NIFTY", dt.date(2026, 11, 12), 24500, "CE", 65)
    for (side, px, units), got in zip(cases, o["fees"]):
        assert got == pytest.approx(cm.fees(inst, side * units, px)[0], rel=1e-9, abs=1e-9)
    for px, got in zip((120.5, 0.35, 250, 18.2), o["half"]):
        assert got == pytest.approx(cm.slippage(inst, px), abs=1e-9)


@needs_node
def test_the_limits_come_from_the_config_and_the_lot_sizing_obeys_them(tmp_path):
    cfg = Config.load(DEFAULT_CONFIG)
    risk = cfg.get("intraday.risk")
    o = node(tmp_path, BOARD + r"""
const c = QB.conf(), L = QB.legsFor("bull_call_spread", STRIKES, SPOT, names, 2).legs;
const spec = { u: "NIFTY", legs: L, quotes: q, spot: SPOT, T };
const best = QB.suggestLots(spec), at = QB.analyze({ ...spec, lots: best }), over = QB.analyze({ ...spec, lots: best + 1 });
const cond = QB.legsFor("iron_condor", STRIKES, SPOT, names, 2).legs, cs = { u: "NIFTY", legs: cond, quotes: q, spot: SPOT, T };
const cb = QB.suggestLots(cs);
console.log(JSON.stringify({ lim: c.limits, eq: c.equity, best, atOk: at.checks.filter((x) => x.id !== "spread" && x.id !== "book").every((x) => x.ok), overRisk: over.checks.find((x) => x.id === "risk").ok,
  maxLoss1: QB.analyze({ ...spec, lots: 1 }).maxLoss, cb, cMargin: QB.analyze({ ...cs, lots: Math.max(cb, 1) }).margin }));
""")
    lim = o["lim"]
    for k in ("risk_per_trade", "max_premium_outlay", "max_total_outlay", "max_lots", "max_open", "max_spread_pct", "max_margin", "credit_margin_per_lot", "daily_loss_limit"):
        assert lim[k] == pytest.approx(risk[k] if k in risk else risk[{"daily_loss_limit": "daily_loss_limit"}.get(k, k)]), k          # the defaults equal the config the desk runs on
    assert o["eq"] == 500000
    assert 1 <= o["best"] <= lim["max_lots"] and o["atOk"]
    assert o["best"] * o["maxLoss1"] <= o["eq"] * lim["risk_per_trade"] + 1e-6                                                 # the suggested size never breaks the per-trade risk limit
    assert o["cMargin"] == lim["credit_margin_per_lot"] * max(o["cb"], 1)


def test_the_builder_block_places_no_order_and_touches_no_network():
    b = block()
    assert not re.search(r"fetch\(|XMLHttpRequest|place_order|/orders|\.order\(|localStorage", b)
    assert "window.QD_TRADE" in b and "DEFINED RISK ONLY" in b


def test_the_published_page_carries_the_configs_limits_costs_and_lot_sizes_and_the_builders_defaults_equal_them(cfg, tmp_path):
    from quantdesk.web import export_site as E
    tc = E.trade_config(cfg)
    assert tc["equity"] == cfg.get("intraday.capital") and tc["r"] == cfg.get("backtest.risk_free")
    assert tc["inst"]["NIFTY"] == {"lot": 65, "step": 50.0} and tc["inst"]["BANKNIFTY"]["lot"] == 30 and "INDIAVIX" not in tc["inst"]
    assert tc["costs"]["options"]["stt_sell"] == cfg.get("costs.segments.options.stt_sell") and tc["slippage"]["option_tick"] == 0.05
    script = E._trade_script(cfg)
    assert script.startswith("<script>window.QD_TRADE=") and "</" not in script[len("<script>"):-len("</script>")]
    out = tmp_path / "site"
    E.publish_site(cfg, "live", out)
    page = (out / "index.html").read_text(encoding="utf-8")
    assert "window.QD_TRADE=" in page and page.index("window.QD_TRADE=") < page.index('<script src="app.js">')                      # the config reaches the page before the app runs
    html = tmp_path / "x.html"
    E.export_site(cfg, "live", html)                                                                                                 # the one-file snapshot too
    one = html.read_text(encoding="utf-8")
    assert "window.QD_TRADE=" in one and one.index("window.QD_TRADE=") < one.index("const QB = (() =>")
    # the builder's built-in defaults (used only if the page has no config) are the config's values
    o = node(tmp_path, "console.log(JSON.stringify(QB.conf()));")
    assert o["equity"] == tc["equity"] and o["r"] == tc["r"] and o["inst"]["NIFTY"] == tc["inst"]["NIFTY"] and o["inst"]["SENSEX"] == tc["inst"]["SENSEX"]
    for k, v in tc["limits"].items():
        assert o["limits"][k] == pytest.approx(v), k
    assert o["costs"]["options"] == pytest.approx(tc["costs"]["options"]) and o["slippage"] == pytest.approx(tc["slippage"])


@needs_node
def test_the_legs_carry_their_bid_and_ask_for_the_table(tmp_path):
    o = node(tmp_path, BOARD + r"""
const a = run("long_straddle", 1, 1);
console.log(JSON.stringify({ legs: a.legs.map((l) => ({ bid: l.bid, ask: l.ask, px: l.px, src: l.src })) }));
""")
    for l in o["legs"]:
        assert l["bid"] > 0 and l["ask"] >= l["bid"] and l["px"] == l["ask"] and l["src"] == "book"                    # a buy is priced at the offer, and the table can show both sides
