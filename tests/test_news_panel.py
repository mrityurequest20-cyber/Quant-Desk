"""The news join (the NW block in quantdesk/web/static/app/app.js), run under Node: stories annotated with the live board's reaction and ranked. Pure maths: no DOM, no network, nothing here is a signal."""
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
    (tmp_path / "n.js").write_text("\n".join(block(b) for b in ("builder", "analyse", "news")) + "\n" + script, encoding="utf-8")
    r = subprocess.run(["node", "n.js"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


SETUP = r"""
const NOW = Date.parse("2026-11-09T06:00:00Z");
const ago = (m) => new Date(NOW - m * 60000).toISOString().replace(/\.\d+Z$/, "Z");
const story = (id, extra = {}) => ({ id, ts: ago(10), source: "A", sources: ["A"], title: "t " + id, link: "https://e.com/" + id, tone: 0, tone_from: "words", impact: "low", recap: false, event: "general", novelty: 1, symbols: [], ...extra });
const quotes = {
  NIFTY: { ltp: 24500, chg: 0.3, age_s: 2 }, RELIANCE: { ltp: 1400, chg: 2.4, age_s: 2 }, TCS: { ltp: 3500, chg: -0.2, age_s: 2 }, "INFY-FUT": { ltp: 1500, chg: -1.6, age_s: 2 },
  "TCS12NOV263500CE": { ltp: 40, vol: 90000, oi: 100000, chg: 8, age_s: 3 },            // TCS options trading hard
  "HDFCBANK12NOV261700CE": { ltp: 20, vol: 100, oi: 100000, chg: 1, age_s: 3 },
};
const out = {};
"""


@needs_node
def test_a_story_is_annotated_with_what_the_board_did_and_whether_the_market_cared(tmp_path):
    o = node(tmp_path, SETUP + r"""
const d = { items: [story("a", { symbols: ["RELIANCE"] }), story("b", { symbols: ["TCS"] }), story("c", { symbols: ["INFY"] }), story("d", { symbols: ["HDFCBANK"] }), story("e", { symbols: ["NIFTY"] }), story("f", { symbols: ["NOPE"] }), story("g")] };
const r = NW.rank(d, quotes, NOW);
const by = Object.fromEntries(r.map((x) => [x.item.id, x]));
const brief = (x) => ({ chg: x.names.map((n) => n.chg), hot: x.names.map((n) => n.hot), cared: x.care.map((n) => n.sym) });
console.log(JSON.stringify({ a: brief(by.a), b: brief(by.b), c: brief(by.c), d: brief(by.d), e: brief(by.e), f: brief(by.f), g: brief(by.g), tw: [NW.toneWord(0.3), NW.toneWord(-0.3), NW.toneWord(0.1), NW.toneWord(-0.15)] }));
""")
    assert o["a"] == {"chg": [2.4], "hot": [0], "cared": ["RELIANCE"]}                          # moved 2.4%
    assert o["b"] == {"chg": [-0.2], "hot": [1], "cared": ["TCS"]}                              # barely moved, but its options trade hard
    assert o["c"] == {"chg": [-1.6], "hot": [0], "cared": ["INFY"]}                             # only a future on the board: still read, and -1.6% counts
    assert o["d"] == {"chg": [None], "hot": [0], "cared": []}                                   # not on the board, thin options: the market did not visibly care
    assert o["e"] == {"chg": [0.3], "hot": [0], "cared": []}                                    # an index needs 0.5%
    assert o["f"] == {"chg": [None], "hot": [0], "cared": []} and o["g"] == {"chg": [], "hot": [], "cared": []}
    assert o["tw"] == ["leans positive", "leans negative", "neutral", "leans negative"]


@needs_node
def test_ranking_weighs_impact_outlets_recaps_the_markets_reaction_and_age(tmp_path):
    o = node(tmp_path, SETUP + r"""
const rk = (items) => NW.rank({ items }, quotes, NOW).map((x) => x.item.id);
const sc = (it) => NW.rank({ items: [it] }, quotes, NOW)[0].score;
console.log(JSON.stringify({
  impact: rk([story("lo"), story("hi", { impact: "high" })]), outlets: rk([story("one"), story("three", { sources: ["A", "B", "C"] })]),
  recap: sc(story("r", { impact: "high", recap: true })) < sc(story("n", { impact: "low" })), react: rk([story("quiet", { symbols: ["TCS", "NIFTY"].slice(1) }), story("hot", { symbols: ["TCS"] })]),
  age: rk([story("old", { ts: ago(600) }), story("new", { ts: ago(5) })]), half: sc(story("h", { ts: ago(120) })) / sc(story("h", { ts: ago(0) })), novel: sc(story("x", { novelty: 0 })) < sc(story("y", { novelty: 1 })),
  empty: NW.rank(null, quotes, NOW), notarray: NW.rank({ items: "x" }, quotes, NOW), future: NW.rank({ items: [story("z", { ts: ago(-30) })] }, quotes, NOW)[0].ageMin, noquotes: NW.rank({ items: [story("q", { symbols: ["TCS"] })] }, undefined, NOW).length }));
""")
    assert o["impact"][0] == "hi" and o["outlets"][0] == "three" and o["recap"] is True and o["react"][0] == "hot" and o["age"][0] == "new"
    assert o["half"] == pytest.approx(0.5, abs=0.03) and o["novel"] is True                      # a story halves in two hours; a repeat of an earlier story weighs less
    assert o["empty"] == [] and o["notarray"] == [] and o["future"] == 0 and o["noquotes"] == 1


@needs_node
def test_the_stories_for_an_underlying_include_the_market_wide_ones_for_an_index_only(tmp_path):
    o = node(tmp_path, SETUP + r"""
const d = { items: [story("rbi", { impact: "high", event: "policy" }), story("recap", { impact: "high", recap: true }), story("rel", { symbols: ["RELIANCE"] }), story("nifty", { symbols: ["NIFTY"] }), story("tcs", { symbols: ["TCS"], impact: "medium" })] };
const r = NW.rank(d, quotes, NOW);
const ids = (u) => NW.forUnderlying(r, u, 10).map((x) => x.item.id).sort();
console.log(JSON.stringify({ nifty: ids("NIFTY"), bank: ids("BANKNIFTY"), rel: ids("RELIANCE"), none: ids("ZZZ"), cap: NW.forUnderlying(r, "NIFTY", 1).length }));
""")
    assert o["nifty"] == ["nifty", "rbi"] and o["bank"] == ["rbi"]                              # an index also gets the high-impact news that is not a recap of its own move
    assert o["rel"] == ["rel"] and o["none"] == [] and o["cap"] == 1                            # a stock gets only the stories that name it


def test_the_news_block_is_display_only():
    b = block("news")
    assert not re.search(r"fetch\(|XMLHttpRequest|localStorage|document\.|window\.|innerHTML|paperCall|place_order|Math\.random|Date\.now", b)       # no clock of its own: the caller passes `now`


def test_the_panel_shows_headlines_as_text_and_links_only_when_https_and_says_what_the_tone_is():
    panel = APP[APP.index("function bdNews"):APP.index("function bdPayoff")]
    assert "innerHTML" not in panel and "insertAdjacentHTML" not in panel and "eval(" not in panel
    assert '/^https:\\/\\//.test(it.link)' in panel and 'rel: "noopener noreferrer"' in panel and 'target: "_blank"' in panel      # a link only when https, opened without the opener
    assert "a hint, not a view" in panel and "the news job may not be running" in panel and "Loading the news" in panel
    load = APP[APP.index("async function newsLoad"):APP.index("function bdNews")]
    assert load.count("fetch(") == 1 and 'fetch("/news"' in load and "method" not in load                                       # one read of one route; nothing is sent
    chain = APP[APP.index("function liveChainView"):APP.index("function bdSync")]
    assert chain.index("bdRead(ctx)") < chain.index("bdNews(S.bd, data)")                       # under an instrument's option chain: the read, the flow, then the news
    assert 'safe("news panel"' in chain                                                         # a story the panel cannot read never takes the chain down with it
    live = APP[APP.index("async function renderLive()"):APP.index("/* @@builder:start */")]
    assert "newsLoad(key)" in live and "60000" in live                                           # at most once a minute
