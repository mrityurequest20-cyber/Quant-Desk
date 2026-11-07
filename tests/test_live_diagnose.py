"""The relay's 503 says why it is off (deploy/cloudflare/live.js `whyOff`): a state per piece and the names of its own settings, never a value, so an owner who can only use a
dashboard can see a misspelt name, a missing secret, a short string or two equal ones."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")

HEAD = r"""
import { handleLive, whyOff, configured } from "./live.mjs";
const out = {};
const LIVE = { idFromName: () => "b", get: () => ({ fetch: async () => new Response("{}") }) };
const get = async (env, path = "/live/snapshot", method = "GET") => { const r = await handleLive(new Request("https://x" + path, { method }), env); return { status: r.status, text: await r.text() }; };
const INGEST = "I".repeat(30) + "-secret-ingest", READ = "R".repeat(30) + "-secret-read";
"""


def run(tmp_path, body: str) -> dict:
    for f in (ROOT / "deploy" / "cloudflare").glob("*.js"):
        shutil.copyfile(f, tmp_path / ("live.mjs" if f.name == "live.js" else f.name))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")
    (tmp_path / "t.mjs").write_text(HEAD + body + "\nconsole.log(JSON.stringify(out));\n", encoding="utf-8")
    r = subprocess.run(["node", "t.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_the_503_names_what_is_missing_and_never_a_value(tmp_path):
    out = run(tmp_path, r"""
const cases = {
  nothing: { LIVE },
  noBinding: { LIVE_INGEST_TOKEN: INGEST, LIVE_READ_TOKEN: READ },
  oneMissing: { LIVE, LIVE_INGEST_TOKEN: INGEST },
  short: { LIVE, LIVE_INGEST_TOKEN: "short", LIVE_READ_TOKEN: READ },
  same: { LIVE, LIVE_INGEST_TOKEN: INGEST, LIVE_READ_TOKEN: INGEST },
  typo: { LIVE, LIVE_INJECT_TOKEN: INGEST, LIVE_READ_TOKEN: READ, KOTAK_CONSUMER_KEY: "k".repeat(20), GH_DISPATCH_TOKEN: "g".repeat(40), ORIGIN: "https://x" },
  blank: { LIVE, LIVE_INGEST_TOKEN: "   ", LIVE_READ_TOKEN: READ },
};
out.r = {};
for (const [k, env] of Object.entries(cases)) { const r = await get(env); out.r[k] = { status: r.status, body: JSON.parse(r.text), text: r.text }; }
out.on = (await get({ LIVE, LIVE_INGEST_TOKEN: INGEST, LIVE_READ_TOKEN: READ })).status;                // switched on: no 503, the key check answers instead
out.other = (await get({ LIVE }, "/data.json")).status === undefined;                                         // not a live path: handleLive does not answer (null)
""".replace('out.other = (await get({ LIVE }, "/data.json")).status === undefined;', 'out.other = await handleLive(new Request("https://x/data.json"), { LIVE });'))
    r = out["r"]
    assert all(v["status"] == 503 and v["body"]["error"] == "the live view is not switched on" for v in r.values())
    assert r["nothing"]["body"]["why"]["LIVE_INGEST_TOKEN"] == "missing" and r["nothing"]["body"]["why"]["LIVE_READ_TOKEN"] == "missing"
    assert r["nothing"]["body"]["why"]["different"] == "ok"                                              # two missing tokens are not "the same string"
    assert r["noBinding"]["body"]["why"]["LIVE_object"].startswith("missing") and r["noBinding"]["body"]["why"]["LIVE_READ_TOKEN"] == "ok"
    assert r["oneMissing"]["body"]["why"]["LIVE_READ_TOKEN"] == "missing" and r["oneMissing"]["body"]["why"]["LIVE_INGEST_TOKEN"] == "ok"
    assert r["short"]["body"]["why"]["LIVE_INGEST_TOKEN"].startswith("too short") and r["blank"]["body"]["why"]["LIVE_INGEST_TOKEN"] == "missing"
    assert r["same"]["body"]["why"]["different"].startswith("no:") and r["noBinding"]["body"]["why"]["different"] == "ok"
    t = r["typo"]["body"]["why"]
    assert t["LIVE_INGEST_TOKEN"] == "missing" and t["seen"] == ["KOTAK_CONSUMER_KEY", "LIVE", "LIVE_INJECT_TOKEN", "LIVE_READ_TOKEN"]      # the misspelt name shows; GH_DISPATCH_TOKEN and ORIGIN are not listed
    for v in r.values():                                                                                        # no value in any body, however it is configured
        assert "secret-ingest" not in v["text"] and "secret-read" not in v["text"] and "kkkkk" not in v["text"] and "gggg" not in v["text"]
    assert out["on"] == 401 and out["other"] is None                                                           # on: the key check answers (no key sent); other paths are not the relay's


@needs_node
def test_a_name_that_is_not_a_plain_setting_name_is_never_echoed_a_lowercase_typo_shows_and_a_failing_diagnosis_still_gives_the_503(tmp_path):
    out = run(tmp_path, r"""
const SECRET = "abcdef0123456789abcdef0123456789";
const env = { LIVE, ["LIVE_READ_TOKEN=" + SECRET]: "x", live_ingest_token: INGEST, ["LIVE" + "<script>\n"]: "y", KOTAK_CONSUMER_KEY: "k".repeat(20) };
const r = await get(env);
out.body = JSON.parse(r.text); out.text = r.text; out.status = r.status;
const many = { LIVE }; for (let i = 0; i < 40; i++) many["LIVE_EXTRA_" + i] = "z";
out.many = JSON.parse((await get(many)).text).why.seen.length;
// a diagnosis that throws: the 503 still comes back as JSON, without a why
const bad = { LIVE, get LIVE_INGEST_TOKEN() { throw new Error("boom"); } };
let thrown = null, st = null, txt = null;
try { const rr = await handleLive(new Request("https://x/live/snapshot"), { LIVE }); st = rr.status; } catch (e) { thrown = String(e); }
out.plain = { st, thrown };
// whyOff itself throwing (a getter that fails on the second read)
let n = 0; const flaky = { LIVE, get LIVE_INGEST_TOKEN() { n += 1; if (n > 1) throw new Error("boom"); return ""; } };
let r2 = null, e2 = null; try { const rr = await handleLive(new Request("https://x/live/snapshot"), flaky); r2 = { status: rr.status, body: await rr.json() }; } catch (e) { e2 = String(e); }
out.flaky = { r2, e2 };
""")
    assert out["status"] == 503 and SECRET_NOT_IN(out["text"])
    seen = out["body"]["why"]["seen"]
    assert "live_ingest_token" in seen and "KOTAK_CONSUMER_KEY" in seen and "LIVE" in seen                          # a lowercase typo shows
    assert out["many"] == 20                                                                                          # and the list is capped
    assert "(an unusual setting name)" in seen and not any("=" in k or "<" in k for k in seen)                       # a NAME=value or odd name is replaced, never echoed
    assert out["flaky"]["e2"] is None and out["flaky"]["r2"]["status"] == 503 and "why" not in out["flaky"]["r2"]["body"]      # whyOff failing: still the JSON 503


def SECRET_NOT_IN(text: str) -> bool:
    return "abcdef0123456789abcdef0123456789" not in text and "x".join("") == ""
