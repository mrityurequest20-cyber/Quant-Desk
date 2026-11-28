"""The Worker's /lens/ route (deploy/cloudflare/lens.js): serves MarketLens from its published branch, same origin as
the live relay; read-only; no path outside the site; correct content types."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

LENS = Path(__file__).resolve().parents[2] / "deploy" / "cloudflare" / "lens.js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run(script: str):
    code = f"import * as L from {json.dumps(LENS.as_uri())};\n{script}"
    r = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_paths():
    r = run("console.log(JSON.stringify(['/lens','/lens/','/lens/app.js','/lens/data/sym/M_M.json','/lens/../wrangler.jsonc',"
            "'/lens/%2e%2e/secret.js','/lens/.git/config','/lens/x.exe','/live/snapshot','/'].map(p => L.lensPath(p))));")
    assert r[0] == {"redirect": "/lens/"}
    assert r[1]["sub"] == "index.html" and r[1]["type"].startswith("text/html")
    assert r[2]["sub"] == "app.js" and r[3]["type"].startswith("application/json")
    assert r[4] == {"bad": True} and r[5] == {"bad": True} and r[6] == {"bad": True} and r[7] == {"bad": True}
    assert r[8] is None and r[9] is None                       # everything else is not this route's


def test_serving():
    r = run("""
const seen = [];
const fake = async (u, o) => { seen.push(u); return u.endsWith('/missing.js') ? new Response('', {status: 404}) : new Response('body', {status: 200, headers: {'content-type': 'text/plain'}}); };
const env = {LENS_ORIGIN: 'https://example.test/site/'};
const a = await L.handleLens(new Request('https://w.dev/lens/app.js'), env, fake);
const b = await L.handleLens(new Request('https://w.dev/lens/missing.js'), env, fake);
const c = await L.handleLens(new Request('https://w.dev/lens/app.js', {method: 'POST'}), env, fake);
const d = await L.handleLens(new Request('https://w.dev/live/snapshot'), env, fake);
console.log(JSON.stringify({a: [a.status, a.headers.get('content-type'), a.headers.get('cache-control'), await a.text()], b: b.status, c: c.status, d, seen}));
""")
    assert r["a"] == [200, "application/javascript; charset=utf-8", "no-cache", "body"]
    assert r["b"] == 404 and r["c"] == 405 and r["d"] is None
    assert r["seen"][0] == "https://example.test/site/app.js"
