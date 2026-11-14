"""Which broker's feed the live relay shows for which kind of instrument (deploy/cloudflare/routes.js, config feeds.routes, docs/FEEDS.md). Display only."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from quantdesk.config import Config

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
CODES = {"z", "k", "u", "d", "a", "f"}                                     # routes.js SOURCES


def wrangler() -> dict:
    return json.loads(re.sub(r"^\s*//.*$", "", (ROOT / "wrangler.jsonc").read_text(), flags=re.M))


def test_the_worker_carries_exactly_the_configs_route_table():
    cfg = Config.load(ROOT / "config" / "quantdesk.yaml").get("feeds.routes")
    assert json.loads(wrangler()["vars"]["FEED_ROUTES"]) == cfg


def test_every_segment_has_a_route_of_known_feeds_and_kotak_is_the_last_resort_everywhere():
    routes = Config.load(ROOT / "config" / "quantdesk.yaml").get("feeds.routes")
    assert set(routes) == {"idx", "eq", "fut", "opt", "mcx", "cds", "mopt", "copt"}
    assert routes["mcx"][0] == routes["mopt"][0] == "f" and routes["cds"][0] == routes["copt"][0] == "a"     # owner, 13 Nov 2026: MCX from Fyers, currency from Angel One, options as futures
    for seg, r in routes.items():
        assert r and set(r) <= CODES and len(set(r)) == len(r), seg
        assert r[-1] == "k" and "z" in r, seg                                  # Kotak only when nothing else delivers; Kite behind every segment
    assert routes["opt"][0] == "z"                                             # options need a two-sided book: Kite's (Kotak's chain has none)
    assert routes["mcx"][0] == "f" and routes["cds"][0] == "a"                 # the owner's split (13 Nov 2026): Fyers for commodities, a third broker for currency


def test_the_push_side_and_the_relay_agree_on_which_feeds_may_push():
    from quantdesk.data.live_push import PUSH_SOURCES
    src = (ROOT / "deploy/cloudflare/routes.js").read_text()
    assert set(re.search(r"PUSH_SOURCES = new Set\(\[([^\]]*)\]\)", src).group(1).replace('"', "").replace(" ", "").split(",")) == set(PUSH_SOURCES)
    assert "k" not in PUSH_SOURCES                                             # the polled Kotak feed can never be posed as by a push


@needs_node
def test_until_a_new_feed_delivers_its_segment_shows_what_it_showed_before(tmp_path):
    shutil.copyfile(ROOT / "deploy/cloudflare/routes.js", tmp_path / "routes.mjs")
    routes = wrangler()["vars"]["FEED_ROUTES"]
    (tmp_path / "t.mjs").write_text(f"""import {{ parseRoutes, pick }} from './routes.mjs';
const R = parseRoutes({json.dumps(routes)});
const out = {{
  mcxNoFyers: pick([{{src: "z", age: 2}}, {{src: "k", age: 1}}], R.mcx, 60),          // Fyers holds nothing yet: Kite, as before (not the fresher Kotak)
  mcxFyers: pick([{{src: "z", age: 1}}, {{src: "f", age: 4}}, {{src: "k", age: 1}}], R.mcx, 60),
  mcxFyersDead: pick([{{src: "z", age: 1}}, {{src: "f", age: 400}}], R.mcx, 60),      // a dead Fyers is stepped over
  cdsAngel: pick([{{src: "a", age: 3}}, {{src: "f", age: 1}}, {{src: "z", age: 1}}], R.cds, 60),
  cdsKotakOnly: pick([{{src: "k", age: 9}}], R.cds, 60),                               // the last resort
  optKite: pick([{{src: "z", age: 30}}, {{src: "k", age: 1}}], R.opt, 60),
  allStale: pick([{{src: "z", age: 500}}, {{src: "k", age: 90}}], R.idx, 60),          // nobody fresh: the freshest of the route, with its age
  bad: parseRoutes('{{"mcx": ["f", "x", "f"], "zzz": ["z"]}}'), none: parseRoutes(""),
}};
console.log(JSON.stringify(out));""")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-1500:]
    o = json.loads(r.stdout)
    assert o["mcxNoFyers"] == "z" and o["mcxFyers"] == "f" and o["mcxFyersDead"] == "z"
    assert o["cdsAngel"] == "a" and o["cdsKotakOnly"] == "k" and o["optKite"] == "z" and o["allStale"] == "k"
    assert o["bad"] == {"mcx": ["f"]} and o["none"] is None                     # unknown codes, repeats and segments are dropped
