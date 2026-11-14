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
const STRIKES = [24200, 24250, 24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700, 24750, 24800];      // the money and 6 strikes either side (a broken wing reaches 5)
const names = {}; STRIKES.forEach((k) => names[k] = { CE: "C" + k, PE: "P" + k });
const SPOT = 24500, T = 3 / 365;
const q = {};
STRIKES.forEach((k) => {
  const iv = 0.14, c = QB.bs("CE", SPOT, k, T, iv, 0.07), p = QB.bs("PE", SPOT, k, T, iv, 0.07), w = (x) => Math.max(0.1, x * 0.01);
  q["C" + k] = { ltp: +c.toFixed(2), bid: +(c - w(c)).toFixed(2), ask: +(c + w(c)).toFixed(2), age_s: 2 };
  q["P" + k] = { ltp: +p.toFixed(2), bid: +(p - w(p)).toFixed(2), ask: +(p + w(p)).toFixed(2), age_s: 2 };
});
const run = (id, width, lots) => { const L = QB.legsFor(id, STRIKES, SPOT, names, width); return L.error ? L : QB.analyze({ u: "NIFTY", legs: L.legs, quotes: q, spot: SPOT, spotAge: 2, T, lots: lots || 1 }); };
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
for (const id of Object.keys(QB.TEMPLATES).filter((i) => !QB.TEMPLATES[i].multi)) { const a = run(id, 2, 1); out[id] = a.error ? { error: a.error } : { risk: a.definedRisk, prem: a.premium, maxP: a.maxProfit === Infinity ? "inf" : a.maxProfit, maxL: a.maxLoss, be: a.breakevens, ok: a.ok, unl: a.unlimitedProfit }; }
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
const edge = QB.legsFor("iron_condor", STRIKES, SPOT, names, 4);   // 8 strikes out: off this board
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
const spec = { u: "NIFTY", legs: L, quotes: q, spot: SPOT, spotAge: 2, T };
const best = QB.suggestLots(spec), at = QB.analyze({ ...spec, lots: best }), over = QB.analyze({ ...spec, lots: best + 1 });
const cond = QB.legsFor("iron_condor", STRIKES, SPOT, names, 2).legs, cs = { u: "NIFTY", legs: cond, quotes: q, spot: SPOT, spotAge: 2, T };
const cb = QB.suggestLots(cs);
console.log(JSON.stringify({ lim: c.limits, eq: c.equity, best, atOk: at.checks.filter((x) => ["risk", "outlay", "lots", "margin"].includes(x.id)).every((x) => x.ok), atRisk: at.risk, overRisk: over.checks.find((x) => x.id === "risk").ok,
  maxLoss1: QB.analyze({ ...spec, lots: 1 }).maxLoss, cb, cMargin: QB.analyze({ ...cs, lots: Math.max(cb, 1) }).margin }));
""")
    lim = o["lim"]
    for k in ("risk_per_trade", "max_premium_outlay", "max_total_outlay", "max_lots", "max_open", "max_spread_pct", "max_margin", "credit_margin_per_lot", "daily_loss_limit"):
        assert lim[k] == pytest.approx(risk[k] if k in risk else risk[{"daily_loss_limit": "daily_loss_limit"}.get(k, k)]), k          # the defaults equal the config the desk runs on
    assert o["eq"] == cfg.get("paper.capital")
    assert 1 <= o["best"] <= lim["max_lots"] and o["atOk"]
    assert o["atRisk"] <= o["eq"] * lim["risk_per_trade"] + 1e-6                                                                 # the suggested size never breaks the per-trade risk limit, fees included
    assert o["cMargin"] == lim["credit_margin_per_lot"] * max(o["cb"], 1)


def test_the_builder_block_places_no_order_and_touches_no_network():
    b = block()
    assert not re.search(r"fetch\(|XMLHttpRequest|place_order|/orders|\.order\(|localStorage", b)
    assert "window.QD_TRADE" in b and "DEFINED RISK ONLY" in b


def test_the_published_page_carries_the_configs_limits_costs_and_lot_sizes_and_the_builders_defaults_equal_them(cfg, tmp_path):
    from quantdesk.web import export_site as E
    tc = E.trade_config(cfg)
    assert tc["equity"] == cfg.get("paper.capital") and tc["r"] == cfg.get("backtest.risk_free")
    assert tc["inst"]["NIFTY"] == {"lot": 65, "step": 50.0} and tc["inst"]["BANKNIFTY"]["lot"] == 30 and "INDIAVIX" not in tc["inst"]
    assert tc["costs"]["options"]["stt_sell"] == cfg.get("costs.segments.options.stt_sell") and tc["slippage"]["option_tick"] == 0.05
    risk = cfg.get("intraday.risk")
    assert tc["limits"] and tc["limits"] == {k: risk[k] for k in tc["limits"]} and set(tc["limits"]) == {"risk_per_trade", "max_premium_outlay", "max_total_outlay", "max_lots", "max_open", "max_spread_pct", "max_margin", "credit_margin_per_lot", "daily_loss_limit"}   # every limit, none dropped
    pu = cfg.get("paper.underlyings")
    assert tc["paper"] == {"risk_per_trade": cfg.get("paper.risk_per_trade"), "max_quote_age_s": cfg.get("paper.max_quote_age_s"),
                           "underlyings": sorted(set(pu["nse_fo"]) | set(pu["mcx"]) | set(pu["nse_cds"])), "allow_short_legs": cfg.get("paper.allow_short_legs") is True}     # MCX and currency options too (13 Nov 2026)
    assert tc["inst"]["CRUDEOIL"] == {"lot": 100, "tick": 0.1, "r": 0.0, "cost": "mcx_options", "prior_day": True, "segment": "mcx"}                   # priced off the future, its own charges and tick
    assert tc["inst"]["USDINR"]["tick"] == 0.0025 and tc["costs"]["cds_options"]["exchange"] == cfg.get("costs.segments.cds_options.exchange")
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
    assert {**o["paper"], "underlyings": sorted(o["paper"]["underlyings"])} == tc["paper"] and o["fromConfig"] is False                                                                    # and the page knows when it is running on them


@needs_node
def test_the_legs_carry_their_bid_and_ask_for_the_table(tmp_path):
    o = node(tmp_path, BOARD + r"""
const a = run("long_straddle", 1, 1);
console.log(JSON.stringify({ legs: a.legs.map((l) => ({ bid: l.bid, ask: l.ask, px: l.px, src: l.src })) }));
""")
    for l in o["legs"]:
        assert l["bid"] > 0 and l["ask"] >= l["bid"] and l["px"] == l["ask"] and l["src"] == "book"                    # a buy is priced at the offer, and the table can show both sides


# ---- the independent review's findings (F1 stale quotes, F2 one-sided and crossed books, F3 the paper gate) --------------------------------------------------------
@needs_node
def test_a_stale_or_ageless_quote_fails_the_freshness_check_and_so_does_a_stale_spot(tmp_path):
    o = node(tmp_path, BOARD + r"""
const legs = QB.legsFor("long_straddle", STRIKES, SPOT, names, 1).legs;
const go = (mut, spotAge) => { const qq = JSON.parse(JSON.stringify(q)); mut(qq); const a = QB.analyze({ u: "NIFTY", legs, quotes: qq, spot: SPOT, spotAge, T, lots: 1, c: { ...QB.conf(), equity: 5000000 } }); return { fresh: a.checks.find((x) => x.id === "fresh"), ok: a.ok, paperOk: a.paperOk, pf: a.paperChecks.find((x) => x.id === "pfresh").ok }; };
console.log(JSON.stringify({ good: go(() => {}, 2), old: go((qq) => { qq.C24500.age_s = 10800; }, 2), edge: go((qq) => { qq.C24500.age_s = 30; }, 30), over: go((qq) => { qq.C24500.age_s = 30.5; }, 2),
  noAge: go((qq) => { delete qq.P24500.age_s; }, 2), spotOld: go(() => {}, 600), spotNone: go(() => {}, undefined) }));
""")
    assert o["good"]["fresh"]["ok"] and o["good"]["ok"] and o["good"]["paperOk"] and o["good"]["pf"]
    assert o["edge"]["fresh"]["ok"]                                                                                    # exactly at the paper gate's limit still passes (30 s), as the gate does
    for k in ("old", "over", "noAge", "spotOld", "spotNone"):
        assert not o[k]["fresh"]["ok"] and not o[k]["ok"] and not o[k]["paperOk"] and not o[k]["pf"], k                 # an old, ageless or spot-less quote never shows green


@needs_node
def test_a_one_sided_or_crossed_book_is_never_green_and_a_guaranteed_profit_is_a_data_error(tmp_path):
    o = node(tmp_path, BOARD + r"""
const mk = (id, w, mut, u) => { const qq = JSON.parse(JSON.stringify(q)); mut(qq); const L = QB.legsFor(id, STRIKES, SPOT, names, w); return QB.analyze({ u: u || "NIFTY", legs: L.legs, quotes: qq, spot: SPOT, spotAge: 2, T, lots: 1 }); };
const ch = (a, id) => a.checks.find((x) => x.id === id);
const buyNoBid = mk("long_call", 1, (qq) => { qq.C24500.bid = 0; });
const sellNoAsk = mk("bear_call_spread", 2, (qq) => { qq.C24500.ask = 0; });
const crossed = mk("long_call", 1, (qq) => { qq.C24500.bid = 200; qq.C24500.ask = 100; });
const wing = mk("bear_call_spread", 2, (qq) => { qq.C24600.bid = 0; qq.C24600.ask = 30; qq.C24500.bid = 150; qq.C24500.ask = 160; });
console.log(JSON.stringify({ buyNoBid: { src: buyNoBid.legs[0].src, book: ch(buyNoBid, "book").ok, spread: ch(buyNoBid, "spread").ok, ok: buyNoBid.ok, paperOk: buyNoBid.paperOk },
  sellNoAsk: { src: sellNoAsk.legs[0].src, book: ch(sellNoAsk, "book").ok, ok: sellNoAsk.ok },
  crossed: { err: crossed.errors, ok: crossed.ok }, wing: { err: wing.errors, ok: wing.ok, maxLoss: wing.maxLoss } }));
""")
    b = o["buyNoBid"]
    assert b["src"] == "side" and not b["book"] and not b["spread"] and not b["ok"] and not b["paperOk"]              # bid 0 / ask 900: priced at the ask, but flagged and refused (the gate needs 0 < bid <= ask)
    assert o["sellNoAsk"]["src"] == "side" and not o["sellNoAsk"]["book"] and not o["sellNoAsk"]["ok"]
    assert o["crossed"]["err"] and "Crossed" in o["crossed"]["err"][0] and not o["crossed"]["ok"]
    assert o["wing"]["err"] and "guaranteed profit" in o["wing"]["err"][0]                                           # the credit above the width is a bad quote, not "Worst loss -0.01%"


@needs_node
def test_the_paper_gate_view_matches_the_paper_desk_and_risk_counts_the_entry_fees(tmp_path):
    o = node(tmp_path, BOARD + r"""
const an = (id, w, u, conf) => { const L = QB.legsFor(id, STRIKES, SPOT, names, w); return QB.analyze({ u, legs: L.legs, quotes: q, spot: SPOT, spotAge: 2, T, lots: 1, c: conf }); };
const pc = (a, id) => a.paperChecks.find((x) => x.id === id).ok;
const call = an("long_call", 1, "NIFTY"), spread = an("bull_call_spread", 2, "NIFTY"), sensex = an("long_call", 1, "SENSEX"), strangle = an("long_strangle", 2, "NIFTY");
// the entry fees tip a trade over the limit: set the equity so that the worst loss alone is JUST inside 2.5% and loss plus fees is just outside
const c0 = QB.conf(), eq = (call.maxLoss + 1) / c0.limits.risk_per_trade, tight = an("long_call", 1, "NIFTY", { ...c0, equity: eq });
console.log(JSON.stringify({ call: { paperOk: call.paperOk, long: pc(call, "long"), under: pc(call, "under") }, spread: { paperOk: spread.paperOk, long: pc(spread, "long") }, spreadOff: (() => { const o = an("bull_call_spread", 2, "NIFTY", { ...c0, paper: { ...c0.paper, allow_short_legs: false } }); return { paperOk: o.paperOk, long: pc(o, "long") }; })(), sensex: { paperOk: sensex.paperOk, under: pc(sensex, "under") }, strangle: strangle.paperOk,
  fees: call.entryFees, risk: call.risk, maxLoss: call.maxLoss, tight: { lossAlone: tight.maxLoss <= eq * c0.limits.risk_per_trade, risk: tight.checks.find((x) => x.id === "risk").ok, prisk: pc(tight, "prisk"), paperOk: tight.paperOk } }));
""")
    assert o["call"] == {"paperOk": True, "long": True, "under": True} and o["strangle"] is True                         # long options on the four index families can be opened
    assert o["spread"] == {"paperOk": True, "long": True}                                                            # a spread has a sold leg: with selling on (owner's order) it goes as one package
    assert o["spreadOff"] == {"paperOk": False, "long": False}                                                       # and with the switch off it is a what-if again
    assert o["sensex"] == {"paperOk": False, "under": False}                                                        # SENSEX is not on the paper desk's list
    assert o["fees"] > 0 and o["risk"] == pytest.approx(o["maxLoss"] + o["fees"])
    t = o["tight"]
    assert t["lossAlone"] and not t["risk"] and not t["prisk"] and not t["paperOk"]                                  # fees counted: inside without them, outside with them


@needs_node
def test_a_bad_expiry_key_is_an_error_not_a_silent_intrinsic_only_curve(tmp_path):
    o = node(tmp_path, BOARD + r"""
const L = QB.legsFor("long_call", STRIKES, SPOT, names, 1).legs;
console.log(JSON.stringify({ t: QB.yearsTo("NOV-26", Date.now()), a: QB.analyze({ u: "NIFTY", legs: L, quotes: q, spot: SPOT, spotAge: 2, T: QB.yearsTo("NOV-26", Date.now()), lots: 1 }).errors }));
""")
    assert o["t"] is None and o["a"] and "expiry" in o["a"][0]


@needs_node
def test_ages_grow_while_the_board_is_not_refetched_and_the_margin_check_bites_in_the_sizing(tmp_path):
    o = node(tmp_path, BOARD + r"""
const legs = QB.legsFor("long_call", STRIKES, SPOT, names, 1).legs;
const at = (add) => QB.analyze({ u: "NIFTY", legs, quotes: q, spot: SPOT, spotAge: 2, ageAdd: add, T, lots: 1 }).paperChecks.find((x) => x.id === "pfresh").ok;
const cond = QB.legsFor("iron_condor", STRIKES, SPOT, names, 2).legs, c0 = QB.conf();
const cs = (m) => QB.suggestLots({ u: "NIFTY", legs: cond, quotes: q, spot: SPOT, spotAge: 2, T, c: { ...c0, equity: 50000000, limits: { ...c0.limits, risk_per_trade: 1, max_premium_outlay: 1, credit_margin_per_lot: m, max_margin: 0.5 } } });
const qo = JSON.parse(JSON.stringify(q)); qo.C24500.age_s = 10;             // the leg is older than the spot: at +25 s the spot is 27 s (fine) and the leg 35 s (not)
const legOnly = QB.analyze({ u: "NIFTY", legs, quotes: qo, spot: SPOT, spotAge: 2, ageAdd: 25, T, lots: 1 }).paperChecks.find((x) => x.id === "pfresh").ok;
console.log(JSON.stringify({ fresh: at(0), after20: at(20), after40: at(40), legOnly, roomy: cs(1000), tight: cs(1e12) }));
""")
    assert o["fresh"] and o["after20"] and not o["after40"] and not o["legOnly"]                # 2 s + 40 s on screen is over the 30 s limit even though no new fetch happened
    assert o["roomy"] >= 1 and o["tight"] == 0                              # a credit structure whose margin estimate breaks the limit is sized to zero lots


def test_the_published_equity_is_the_paper_accounts_not_the_intraday_desks_and_the_missing_config_warning_exists():
    from quantdesk.web import export_site as E

    class Cfg:
        def __init__(self, base, **over):
            self.base, self.over = base, over

        def get(self, key, default=None):
            return self.over.get(key, self.base.get(key, default))

    base = Config.load(DEFAULT_CONFIG)
    tc = E.trade_config(Cfg(base, **{"paper.capital": 123456, "intraday.capital": 999999}))
    assert tc["equity"] == 123456.0                                          # paper.capital wins when the two differ
    assert "QD_TRADE is missing" in APP and "c.fromConfig" in APP[APP.index("function bdDraw"):APP.index("function legsTable2")]


# ---- custom legs and what-if scenarios ------------------------------------------------------------------------------------------
@needs_node
def test_custom_legs_take_any_number_of_legs_merge_the_same_contract_and_refuse_nonsense(tmp_path):
    o = node(tmp_path, BOARD + r"""
const row = (side, type, strike, mult = 1) => ({ side, type, strike, mult });
const many = []; for (let i = 0; i < 9; i++) { many.push(row(1, "CE", STRIKES[i])); many.push(row(1, "PE", STRIKES[i])); }
const res = {
  ok: QB.customLegs([row(1, "CE", 24500, 2), row(-1, "CE", 24600)], names), merged: QB.customLegs([row(1, "CE", 24500), row(1, "CE", 24500, 2)], names),
  both: QB.customLegs([row(1, "CE", 24500), row(-1, "CE", 24500)], names), offBoard: QB.customLegs([row(1, "CE", 99999)], names), zero: QB.customLegs([row(1, "CE", 24500, 0)], names),
  frac: QB.customLegs([row(1, "CE", 24500, 1.5)], names), str: QB.customLegs([row(1, "CE", 24500, "2")], names), big: QB.customLegs([row(1, "CE", 24500, 101)], names),
  mergedBig: QB.customLegs([row(1, "CE", 24500, 60), row(1, "CE", 24500, 60)], names), empty: QB.customLegs([], names), nul: QB.customLegs(null, names), junk: QB.customLegs([null], names),
  eighteen: QB.customLegs(many, names), fiftyOne: QB.customLegs(Array.from({ length: 51 }, (_, i) => row(1, "CE", STRIKES[i % 9], 1)).map((r, i) => ({ ...r, type: i % 2 ? "PE" : "CE" })), names),
};
const L = res.ok.legs, a = QB.analyze({ u: "NIFTY", legs: L, quotes: q, spot: SPOT, spotAge: 2, T, lots: 2 });
out.shape = Object.fromEntries(Object.entries(res).map(([k, v]) => [k, v.error ? "ERR" : v.legs.length]));
out.units = a.legs.map((l) => [l.side, l.units, l.lots, l.mult]); out.err = a.errors;
const w = QB.analyze({ u: "NIFTY", legs: res.eighteen.legs, quotes: q, spot: SPOT, spotAge: 2, T, lots: 1 });
out.many = { n: w.legs.length, err: w.errors, maxLoss: w.maxLoss, unlimited: w.unlimitedProfit };
console.log(JSON.stringify(out));
""")
    sh = o["shape"]
    assert sh["ok"] == 2 and sh["merged"] == 1 and sh["eighteen"] == 18                                                         # eighteen legs: no template has more than four
    for bad in ("both", "offBoard", "zero", "frac", "str", "big", "mergedBig", "empty", "nul", "junk"):
        assert sh[bad] == "ERR", bad
    assert sh["fiftyOne"] == "ERR" or sh["fiftyOne"] <= 18                                                                      # (51 rows collapse onto 18 contracts here; the cap is on the rows)
    assert o["units"] == [[1, 260, 4, 2], [-1, 130, 2, 1]] and o["err"] == []                                                   # the size multiple scales units: 2 base lots x 65, the bought leg twice that
    assert o["many"]["n"] == 18 and o["many"]["err"] == [] and o["many"]["unlimited"] is True                                  # the maths takes them: eighteen long legs, a known worst loss, no cap on the upside


@needs_node
def test_the_what_if_equals_the_payoff_at_expiry_and_moves_the_right_way_before_it(tmp_path):
    o = node(tmp_path, BOARD + r"""
const L = QB.legsFor("bull_call_spread", STRIKES, SPOT, names, 2);
const spec = { u: "NIFTY", legs: L.legs, quotes: q, spot: SPOT, spotAge: 2, T, lots: 1 };
const a = QB.analyze(spec), days = T * 365;
const atExpiry = [-0.03, -0.01, 0, 0.01, 0.03].map((m) => [QB.scenario(a, spec, { move: m, dvol: 0, days }), a.legs.reduce((s, l) => s + QB.legPay(l, SPOT * (1 + m)), 0)]);
const now0 = QB.scenario(a, spec, { move: 0, dvol: 0, days: 0 });
out.atExpiry = atExpiry; out.now0 = now0; out.up = QB.scenario(a, spec, { move: 0.02, dvol: 0, days: 0 }); out.down = QB.scenario(a, spec, { move: -0.02, dvol: 0, days: 0 });
out.volUp = QB.scenario(a, spec, { move: 0, dvol: 0.05, days: 0 }) - now0; out.decay = QB.scenario(a, spec, { move: 0, dvol: 0, days: 2 }) - now0; out.premium = a.premium;
const one = QB.legsFor("long_call", STRIKES, SPOT, names, 1), s1 = { ...spec, legs: one.legs }, a1 = QB.analyze(s1);
out.longVolUp = QB.scenario(a1, s1, { move: 0, dvol: 0.05, days: 0 }) - QB.scenario(a1, s1, { move: 0, dvol: 0, days: 0 }); out.longDecay = QB.scenario(a1, s1, { move: 0, dvol: 0, days: 2 }) - QB.scenario(a1, s1, { move: 0, dvol: 0, days: 0 });
console.log(JSON.stringify(out));
""")
    for got, want in o["atExpiry"]:
        assert got == pytest.approx(want, abs=1e-6)                                                                             # at expiry the what-if IS the payoff chart
    assert o["up"] > o["now0"] > o["down"]                                                                                      # a bull call spread gains when spot rises
    assert o["now0"] < 0 and o["now0"] > -abs(o["premium"])                                                                     # right after opening it is down by about the spread, never by the whole premium
    assert o["longVolUp"] > 0 and o["longDecay"] < 0                                                                            # a long option gains from higher volatility and loses to time


# ---- every structure, the advisor and the designer (owner, 13 Nov 2026: "The strategy builder must have access to the every strategy which it can reason it out when to
# use which and create it's own if required") ---------------------------------------------------------------------------------------------------------------------------
@needs_node
def test_the_newer_structures_have_their_textbook_payoffs(tmp_path):
    o = node(tmp_path, BOARD + r"""
for (const id of ["call_butterfly", "put_butterfly", "bw_call_butterfly", "bw_put_butterfly", "call_backspread", "put_backspread"]) {
  const L = QB.legsFor(id, STRIKES, SPOT, names, 2), a = run(id, 2, 1);
  out[id] = { legs: L.legs.map((l) => [l.side, l.type, l.strike, l.mult || 1]), prem: a.premium, maxP: a.maxProfit === Infinity ? "inf" : a.maxProfit, maxL: a.maxLoss, risk: a.definedRisk, units: a.legs.map((l) => l.units) };
}
console.log(JSON.stringify(out));
""")
    lot, step, w = 65, 50, 2
    assert o["call_butterfly"]["legs"] == [[1, "CE", 24400, 1], [-1, "CE", 24500, 2], [1, "CE", 24600, 1]] and o["call_butterfly"]["units"] == [65, 130, 65]
    for id in ("call_butterfly", "put_butterfly"):                                                   # a long butterfly: pay a debit, make the wing width less it at the body
        assert o[id]["prem"] > 0 and o[id]["maxL"] == pytest.approx(o[id]["prem"], rel=1e-9) and o[id]["maxP"] == pytest.approx(w * step * lot - o[id]["prem"], rel=1e-9)
    assert o["bw_call_butterfly"]["legs"] == [[1, "CE", 24500, 1], [-1, "CE", 24600, 2], [1, "CE", 24750, 1]]
    assert o["call_backspread"]["maxP"] == "inf" and o["put_backspread"]["maxP"] != "inf"           # unlimited up; down to zero is bounded
    assert all(d["risk"] is True for d in o.values())


@needs_node
def test_the_advisor_reasons_from_the_textbook_and_the_desks_record(tmp_path):
    o = node(tmp_path, r"""
const top = (ctx, n) => QB.advise(ctx).slice(0, n || 3).map((x) => x.id);
const ev = QB.advise({ view: "range", vol: "rich", event: true });
const rec = QB.advise({ view: "range", vol: "rich", record: { CBF: { mu: 0.4, n: 60 }, IC: { mu: -0.3, n: 80 } } });
console.log(JSON.stringify({
  rangeRich: top({ view: "range", vol: "rich" }, 4), upCheapStrong: top({ view: "up", vol: "cheap", pUp: 0.8, trendT: 2.5 }, 2), upMild: top({ view: "up", vol: "mid", pUp: 0.56 }, 3),
  bigCheap: top({ view: "big", vol: "cheap" }, 2), eventIC: ev.find((x) => x.id === "iron_condor"), eventTop: ev[0].id, standAside: QB.verdict(ev).stand_aside,
  fits: QB.verdict(QB.advise({ view: "range", vol: "rich" })).stand_aside, recTop: rec[0].id, recIC: rec.find((x) => x.id === "iron_condor"),
  every: QB.advise({}).length, n: Object.keys(QB.TEMPLATES).length,
  inv: QB.advise({ view: "up", extra: [{ id: "inv:Gabc12", name: "invented: x", dir: "up", vol: "neutral", conv: "mild", code: "Gabc12", rows: [] }], record: { Gabc12: { mu: 0.3, n: 20 } } })[0] }));
""")
    assert set(o["rangeRich"]) == {"iron_condor", "iron_butterfly", "call_butterfly", "put_butterfly"}       # a range and dear options: sell them, in a defined-risk shape
    assert set(o["upCheapStrong"]) == {"long_call", "call_backspread"}                                         # a strong view up and cheap options: buy the move
    assert o["upMild"][0] in ("bull_call_spread", "bull_put_spread", "bw_call_butterfly")                    # a mild view: capped
    assert set(o["bigCheap"]) <= {"long_straddle", "long_strangle"}
    assert o["eventIC"]["score"] < 1 and any("no volatility is sold" in a for a in o["eventIC"]["against"])
    assert o["standAside"] is True and o["fits"] is False                                                       # a range view in an event: nothing fits, and it says so
    assert o["recTop"] == "call_butterfly" and any("shadow record" in a for a in o["recIC"]["against"])       # the desk's own record moves the ranking
    assert o["every"] == o["n"] == 20                                                                     # 16 single-expiry structures and 4 calendars or diagonals
    assert o["inv"]["id"] == "inv:Gabc12" and o["inv"]["invented"] is True                                   # the desk's inventions are on the list, judged the same way


@needs_node
def test_the_desks_read_becomes_the_advisors_context(tmp_path):
    o = node(tmp_path, r"""
const lab = { state: { NIFTY: ["flat", "rich", 1.31, true, 0.52, "", "", "calm", "", 0.4, "", 0.5, ""], CRUDEOIL: [null, "mid", 1.0, false, null, "", "event regime: oil", "stressed", "volatility up", null, "", 0.71, ""] },
  families: [{ struct: "IC", mu_r: 0.08, se: 0.1, trades: 120 }], inventions: [{ code: "Gabc12", name: "invented: buy 1 call", view: "flat", legs: [[1, "CE", 1], [-2, "CE", 2], [1, "CE", 3]], mu_r: 0.1, trades: 14 }] };
const n = QB.deskContext(lab, "NIFTY"), cr = QB.deskContext(lab, "CRUDEOIL"), none = QB.deskContext(null, "X");
console.log(JSON.stringify({ n: n.ctx, seen: n.seen, cr: cr.ctx, none: none.ctx, noneSeen: none.seen }));
""")
    assert o["n"]["view"] == "range" and o["n"]["vol"] == "rich" and o["n"]["eve"] is True and o["n"]["pUp"] == 0.52 and o["n"]["record"]["IC"]["n"] == 120
    assert "volatility rich (1.31x realized)" in o["seen"] and "expiry tomorrow" in o["seen"]
    assert o["cr"]["view"] == "big" and o["cr"]["event"] is True and o["cr"]["pUp"] == 0.71                  # no view but an event: a big move; the news model's P(up)
    inv = o["n"]["extra"][0]
    assert inv["dir"] == "range" and inv["rows"][1] == {"side": -1, "type": "CE", "off": 2, "mult": 2} and o["n"]["record"]["Gabc12"]["n"] == 14
    assert "view" not in o["none"] and o["noneSeen"] == []                                                  # no read: the advisor reasons from the view you pick


@needs_node
def test_the_designer_builds_defined_risk_structures_that_pay_if_the_view_is_right(tmp_path):
    o = node(tmp_path, BOARD + r"""
const em = SPOT * 0.14 * Math.sqrt(T), base = { u: "NIFTY", strikes: STRIKES, names, quotes: q, spot: SPOT, spotAge: 2, T, em, seed: 3, top: 4 };
for (const v of ["up", "down", "range", "big"]) out[v] = QB.design({ ...base, view: v });
out.again = QB.design({ ...base, view: "up" });
out.tight = QB.design({ ...base, view: "up", budget: 1500 });
out.bad = QB.design({ ...base, view: "sideways" });
out.check = out.up.designs.map((d) => { const a = QB.analyze({ u: "NIFTY", legs: d.rows.map((r) => ({ ...r, name: names[r.strike][r.type] })), quotes: q, spot: SPOT, spotAge: 2, T, lots: 1 }); return [a.definedRisk, a.maxLoss]; });
console.log(JSON.stringify(out));
""")
    for v in ("up", "down", "range", "big"):
        ds = o[v]["designs"]
        assert ds and all(d["avgRight"] > 0 and d["maxLoss"] > 0 for d in ds), v
        assert [d["score"] for d in ds] == sorted((d["score"] for d in ds), reverse=True)
        for d in ds:
            calls = sum((1 if r["side"] > 0 else -1) * r["mult"] for r in d["rows"] if r["type"] == "CE")
            assert calls >= 0 and len(d["rows"]) <= 4 and sum(r["mult"] for r in d["rows"]) <= 6           # defined risk, at most 4 legs and 6 lots
    assert all(d["avgRight"] > d["avgWrong"] for d in o["up"]["designs"])                                # it pays more where the view is right than where it is wrong
    assert any(d["known"] and d["known"]["id"] == "bull_call_spread" for d in o["up"]["designs"])            # it says when its answer already has a name
    assert any(d["known"] is None for v in ("up", "range", "big") for d in o[v]["designs"])                   # and it finds structures of its own
    assert all(any(r["type"] == "CE" and r["side"] > 0 for r in d["rows"]) and any(r["type"] == "PE" and r["side"] > 0 for r in d["rows"]) for d in o["big"]["designs"][:2])   # either way: both sides
    assert o["again"] == o["up"]                                                                          # the same board and seed, the same designs
    assert all(d["maxLoss"] <= 1500 for d in o["tight"]["designs"])
    assert all(m[0] is True and m[1] > 0 for m in o["check"]) and "error" in o["bad"]


def test_the_builder_finds_an_mcx_or_currency_underlying_and_uses_only_its_own_names():
    """Two bugs found by driving the page (14 Nov 2026): the builder priced an option's underlying from NAME or NAME-FUT only, so an MCX (-MCX) or currency (-CDS)
    option had "no price on the board"; and it read a variable `u` that does not exist in its scope, so the Strategy tab stopped drawing."""
    draw = APP[APP.index("function bdDraw"):APP.index("function legsTable2")]
    flow = APP[APP.index("function bdFlow"):APP.index("function bdFlow") + 4000]
    assert 'data.quotes[B.u + "-FUT"]' not in draw + flow and "liveNames(B.u, data.quotes).fut" in draw + flow
    for body in (draw, flow, APP[APP.index("function bdIdeas"):APP.index("function bdPayoff")]):
        assert not re.search(r"rateOf\(u\b", body) and "B.u || u" not in body


@needs_node
def test_a_calendar_is_valued_at_the_near_expiry_with_its_worst_case_at_the_floor(tmp_path):
    """Owner, 14 Nov 2026: "Build Calendar and diagonal spreads". The builder places a calendar's later leg on the next expiry's chain and judges it as the paper gate does."""
    o = node(tmp_path, BOARD + r"""
const T2 = T + 7 / 365, names2 = {};
STRIKES.forEach((k) => { names2[k] = { CE: "X" + k + "CE", PE: "X" + k + "PE" };
  for (const t of ["CE", "PE"]) { const v = QB.bs(t, SPOT, k, T2, 0.14, 0.07); q["X" + k + t] = { ltp: +v.toFixed(2), bid: +(v * 0.995).toFixed(2), ask: +(v * 1.005).toFixed(2), age_s: 2 }; } });
const next = { strikes: STRIKES, names: names2, T: T2 };
for (const id of ["call_calendar", "put_calendar", "call_diagonal", "put_diagonal"]) {
  const L = QB.legsFor(id, STRIKES, SPOT, names, 2, next);
  const a = QB.analyze({ u: "NIFTY", legs: L.legs, quotes: q, spot: SPOT, spotAge: 2, T, lots: 1 });
  out[id] = { legs: L.legs.map((l) => [l.side, l.type, l.strike, l.name[0]]), err: a.errors, multi: a.multi, prem: a.premium, maxL: a.maxLoss, maxP: a.maxProfit, be: a.breakevens, risk: a.definedRisk };
}
out.none = QB.legsFor("call_calendar", STRIKES, SPOT, names, 1, null).error;
const rev = QB.analyze({ u: "NIFTY", legs: [{ side: 1, type: "CE", strike: 24500, name: "C24500" }, { side: -1, type: "CE", strike: 24500, name: "X24500CE", T: T2 }], quotes: q, spot: SPOT, spotAge: 2, T, lots: 1 });
out.rev = rev.errors;
console.log(JSON.stringify(out));
""")
    cal = o["call_calendar"]
    assert cal["err"] == [] and cal["multi"] is True and cal["risk"] is True and cal["legs"] == [[-1, "CE", 24500, "C"], [1, "CE", 24500, "X"]]
    assert cal["prem"] > 0 and cal["maxL"] == pytest.approx(cal["prem"] + 0.02 * 7 / 365 * 3 * 24500 * 65, rel=1e-6)   # the debit, plus the floor's allowance at three times its strike (as the gate)
    assert 0 < cal["maxP"] < 1e6 and len(cal["be"]) == 2                                                     # the tent: two break-evens either side of the strike
    assert o["put_calendar"]["maxL"] > o["put_calendar"]["prem"] and o["put_calendar"]["err"] == []
    assert o["call_diagonal"]["legs"] == [[-1, "CE", 24600, "C"], [1, "CE", 24500, "X"]] and o["call_diagonal"]["err"] == []
    assert "next expiry" in o["none"] and o["rev"] and "near expiry" in o["rev"][0]
