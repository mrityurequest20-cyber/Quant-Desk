"""The alert rules (web/alertrules.js), shared by the browser and the desk's Worker."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def js(code: str):
    pre = f"global.LiveCore = require({json.dumps(str(WEB / 'livecore.js'))}); const A = require({json.dumps(str(WEB / 'alertrules.js'))});\n"
    r = subprocess.run(["node", "-e", pre + code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_saved_rules_are_merged_on_the_defaults_and_kept_in_range():
    r = js("console.log(JSON.stringify(A.mergeRules([{id:'big_move', on:false, mult:99}, {id:'iv_extreme', hi:0.2}, {id:'bogus'}])))")
    by = {x["id"]: x for x in r}
    assert set(by) == {"iv_extreme", "big_move", "gamma_flip", "curve_inverted", "ban", "mcx_move"}
    assert by["big_move"]["on"] is False and by["big_move"]["mult"] == 10 and by["iv_extreme"]["hi"] == 0.5


def test_ban_rules_fire_for_watchlist_stocks_only_at_end_of_day():
    ov = {"universe": [{"symbol": "SBIN", "kind": "stock"}, {"symbol": "NIFTY", "kind": "index"}], "live_base": {},
          "limits": {"available": True, "ban_date": "2026-11-27", "ban": ["SBIN", "IDEA"], "near": [{"symbol": "AXISBANK", "util": 0.93, "in_ban": False}]}}
    now = "Date.parse('2026-11-26T20:40:00+05:30')"
    r = js(f"console.log(JSON.stringify(A.evaluate({{}}, {json.dumps(ov)}, [], {now}, {{nse:false, eod:true}}).map(a => a.key)))")
    assert r == ["2026-11-26:ban:SBIN:2026-11-27", "2026-11-26:ban:AXISBANK:near"]           # IDEA is not on the watchlist
    assert js(f"console.log(JSON.stringify(A.evaluate({{}}, {json.dumps(ov)}, [], {now}, {{nse:false, eod:false}})))") == []


def test_keys_name_the_day_so_an_alert_repeats_only_the_next_day():
    ov = {"universe": [], "live_base": {}, "limits": {"available": True, "ban_date": "x", "ban": [], "near": [{"symbol": "AXISBANK", "util": 0.95, "in_ban": False}]}}
    a = js(f"console.log(JSON.stringify(A.evaluate({{}}, {json.dumps(ov)}, [], Date.parse('2026-11-26T21:00:00+05:30'), {{eod:true}})[0].key))")
    b = js(f"console.log(JSON.stringify(A.evaluate({{}}, {json.dumps(ov)}, [], Date.parse('2026-11-27T21:00:00+05:30'), {{eod:true}})[0].key))")
    assert a != b and a.startswith("2026-11-26") and b.startswith("2026-11-27")
