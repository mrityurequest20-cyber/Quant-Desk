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
    assert tc["paper"] == {"risk_per_trade": cfg.get("paper.risk_per_trade"), "max_quote_age_s": cfg.get("paper.max_quote_age_s"), "underlyings": sorted(cfg.get("paper.underlyings")["nse_fo"]), "allow_short_legs": cfg.get("paper.allow_short_legs") is True}
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
console.log(JSON.stringify({ call: { paperOk: call.paperOk, long: pc(call, "long"), under: pc(call, "under") }, spread: { paperOk: spread.paperOk, long: pc(spread, "long") }, sensex: { paperOk: sensex.paperOk, under: pc(sensex, "under") }, strangle: strangle.paperOk,
  fees: call.entryFees, risk: call.risk, maxLoss: call.maxLoss, tight: { lossAlone: tight.maxLoss <= eq * c0.limits.risk_per_trade, risk: tight.checks.find((x) => x.id === "risk").ok, prisk: pc(tight, "prisk"), paperOk: tight.paperOk } }));
""")
    assert o["call"] == {"paperOk": True, "long": True, "under": True} and o["strangle"] is True                         # long options on the four index families can be opened
    assert o["spread"] == {"paperOk": False, "long": False}                                                          # a spread has a short leg: the gate opens long options only
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
