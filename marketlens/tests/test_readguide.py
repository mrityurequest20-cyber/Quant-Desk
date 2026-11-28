"""Every card in the app has a 'How to read this' guide (web/readguide.js): a new card without one fails here."""
import json
import re
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def titles():
    s = (WEB / "app.js").read_text(encoding="utf-8")
    out = set(re.findall(r'card\(\{ (?:level: "a", )?title: "([^"]+)"', s))
    m = re.search(r'title: \{ (vrp: "[^}]+) \}\[k\]', s)                     # the overview cards' titles come from a small map
    out |= set(re.findall(r'"([^"]+)"', m.group(1))) if m else set()
    out |= {"Running total since 2026-10-01", "Do BANKNIFTY's members move together?", "Brent crude: how much it moves",
            "Price, rebased to 100", "Where options are most unusual", "All instruments"}   # titles built at run time
    return sorted(out)


def test_every_card_title_has_a_reading_guide():
    ts = titles()
    assert len(ts) > 60
    js = f"const G = require({json.dumps(str(WEB / 'readguide.js'))}); const ts = {json.dumps(ts)};" \
         "console.log(JSON.stringify(ts.filter((t) => !G.find(t))));"
    missing = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert missing == []


def test_a_guide_has_all_three_parts_where_it_matters():
    js = f"const G = require({json.dumps(str(WEB / 'readguide.js'))}); const g = G.find('Volatility smile');" \
         "console.log(JSON.stringify(g));"
    g = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    assert g["shows"] and g["read"] and g["not"]
