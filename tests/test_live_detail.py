"""The Live tab's instrument view (quantdesk/web/static/app/app.js): the pure parts run under Node (an option's name into underlying, expiry, strike and side; the chains
grouped from the names on the board), and the wiring that must hold (the series is read with the key, rows open the view, nothing here can trade)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "quantdesk/web/static/app/app.js").read_text()
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def pure_part() -> str:
    i, j = APP.index("const LIVE_MONTHS"), APP.index("function liveHHMM")
    return APP[i:j]


def run(tmp_path, body: str) -> dict:
    (tmp_path / "t.mjs").write_text(pure_part() + "\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_option_names_parse_to_underlying_expiry_strike_and_side_and_nothing_else_does(tmp_path):
    out = run(tmp_path, r"""
out.opts = ["NIFTY12NOV2624500CE", "BANKNIFTY29DEC2652000.5PE", "BAJAJ-AUTO24NOV269000PE", "360ONE25NOV261000CE", "M&M24NOV263100CE", "MIDCPNIFTY12NOV2613000PE"].map(liveOpt);
out.not = ["NIFTY", "NIFTY-FUT", "RELIANCE", "NIFTY12NOV26", "CRUDEOIL-MCX", "NIFTY12XXX2624500CE", "NIFTY12NOV2624500XX", "", "12NOV2624500CE"].map(liveOpt);
out.keys = ["30DEC26", "05JAN27", "12NOV26", "19NOV26"].map(liveExpiryKey);
""")
    o = out["opts"]
    assert o[0] == {"u": "NIFTY", "e": "12NOV26", "k": 24500, "t": "CE"}
    assert o[1] == {"u": "BANKNIFTY", "e": "29DEC26", "k": 52000.5, "t": "PE"}
    assert o[2]["u"] == "BAJAJ-AUTO" and o[2]["k"] == 9000 and o[2]["t"] == "PE"
    assert o[3] == {"u": "360ONE", "e": "25NOV26", "k": 1000, "t": "CE"}              # digits at the start of a name are not an expiry
    assert o[4]["u"] == "M&M" and o[5]["u"] == "MIDCPNIFTY" and o[5]["k"] == 13000
    assert out["not"] == [None] * 9
    assert out["keys"][2] < out["keys"][3] < out["keys"][0] < out["keys"][1]          # 12 Nov < 19 Nov < 30 Dec < 5 Jan, across a year


@needs_node
def test_chains_are_grouped_by_underlying_expiry_and_strike_from_the_names_on_the_board(tmp_path):
    out = run(tmp_path, r"""
const q = (n) => [n, { ltp: 1, age_s: 1 }];
const data = { quotes: Object.fromEntries(["NIFTY", "NIFTY-FUT", "NIFTY12NOV2624500CE", "NIFTY12NOV2624500PE", "NIFTY12NOV2624550CE", "NIFTY19NOV2624500CE", "BAJAJ-AUTO24NOV269000CE", "RELIANCE"].map(q)) };
const c = liveChains(data);
out.under = Object.keys(c).sort();
out.exps = Object.keys(c.NIFTY).sort();
out.strikes = Object.keys(c.NIFTY["12NOV26"]).sort();
out.sides = c.NIFTY["12NOV26"][24500];
out.half = c.NIFTY["12NOV26"][24550];
out.bajaj = c["BAJAJ-AUTO"]["24NOV26"][9000];
""")
    assert out["under"] == ["BAJAJ-AUTO", "NIFTY"] and out["exps"] == ["12NOV26", "19NOV26"] and out["strikes"] == ["24500", "24550"]
    assert out["sides"] == {"CE": "NIFTY12NOV2624500CE", "PE": "NIFTY12NOV2624500PE"} and out["half"] == {"CE": "NIFTY12NOV2624550CE"}
    assert out["bajaj"] == {"CE": "BAJAJ-AUTO24NOV269000CE"}


def test_the_instrument_view_is_wired_to_the_key_the_rows_and_the_back_button_and_cannot_trade():
    i, j = APP.index("// ---- one instrument:"), APP.index("function liveBuild()")
    view = APP[i:j]
    assert 'fetch("/live/series?name=" + encodeURIComponent(name), { headers: { Authorization: "Bearer " + key }' in view      # read with the key, as the snapshot is
    assert "onclick: () => liveOpen(n)" in APP and 'tabindex: "0"' in APP and "e.key === \"Enter\"" in APP                       # a row opens it, by touch and by keyboard
    assert 'id: "lv-detail", hidden: true' in APP and "$(\"#lv-list\").hidden = !!L.sel" in APP and "liveOpen(null)" in view      # the list returns
    assert "fetch(\"/live/series" in APP[APP.index("async function renderLive()"):]                                               # the open instrument's series is read with every refresh
    code = re.sub(r"//[^\n]*", "", view)                                                           # comments say what the view cannot do; only the code is checked
    assert "/api/" not in code and not re.search(r"\b(order|orders|place|submit|buy|sell|trade)\b|POST", code, re.I)          # whole words: "border-top" is not an order
