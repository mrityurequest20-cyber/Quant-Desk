"""The published app replaces `fetch` with a shim that answers the app's /api/i/* calls from data.json (quantdesk/web/export_site.py LIVE_SHIM). The Live tab's calls to the
Worker's relay (/live/*) are not in data.json: they must go to the real network, with their headers (the key). They did not (the shim answered them with a 404 'not available on a
read-only site'), so on the real site the Live tab could never reach the relay, whatever the relay did. This runs the shim itself, as the page does."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantdesk.web import export_site as ES  # noqa: E402

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


def run(tmp_path, body: str, shim: str | None = None) -> dict:
    (tmp_path / "shim.js").write_text(shim if shim is not None else ES.LIVE_SHIM, encoding="utf-8")
    (tmp_path / "t.js").write_text(r"""
const fs = require("fs");
const calls = [];
globalThis.window = globalThis;
globalThis.location = { href: "https://qd.example/" };
globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init: init || null }); 
  if (String(url) === "data.json") return new Response(JSON.stringify({ state: { heartbeat: null }, live: false, short: "x", trades: [], reviews: {}, stats: {}, thoughts: [], news: [], chart: {}, trade: {} }), { status: 200, headers: { "content-type": "application/json" } });
  return new Response(JSON.stringify({ real: true, url: String(url) }), { status: 200, headers: { "content-type": "application/json" } }); };
(0, eval)(fs.readFileSync("shim.js", "utf8"));
const out = {};
(async () => {
""" + body + r"""
console.log(JSON.stringify(out));
})();
""", encoding="utf-8")
    r = subprocess.run(["node", "t.js"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_a_live_request_goes_to_the_real_network_with_its_key_and_an_api_call_is_still_answered_from_data_json(tmp_path):
    out = run(tmp_path, r"""
const KEY = { headers: { Authorization: "Bearer test-key" }, cache: "no-store" };
const live = await window.fetch("/live/snapshot", KEY);
out.live = { status: live.status, body: await live.json() };
const series = await window.fetch("/live/series?name=NIFTY", KEY);
out.series = (await series.json()).url;
const health = await window.fetch("/live/health", KEY);
out.health = health.status;
const api = await window.fetch("/api/i/stats");                            // an app call: answered from data.json, not by the network
out.api = { status: api.status, body: await api.json() };
const unknown = await window.fetch("/api/i/nothing-here");                 // not a live path and not in data.json: the shim's own 404
out.unknown = unknown.status;
const lookalike = await window.fetch("/liveness");                         // starts with /live but not /live/: not the relay's
out.lookalike = lookalike.status;
const news = await window.fetch("/news", KEY);                              // the news digest is the same private relay
out.news = news.status;
const newsLookalike = await window.fetch("/newsletter");                    // /newsletter and /news/x are not the digest
out.newsLookalike = newsLookalike.status;
out.calls = calls.map((c) => [c.url, c.init && c.init.headers && c.init.headers.Authorization || null]);
""")
    assert out["live"]["status"] == 200 and out["live"]["body"]["real"] is True               # it reached the network (the real fetch), not the shim's 404
    assert out["series"] == "/live/series?name=NIFTY" and out["health"] == 200
    assert out["api"]["status"] == 200 and out["unknown"] == 404 and out["lookalike"] == 404   # everything else behaves as before
    assert out["news"] == 200 and out["newsLookalike"] == 404                                   # /news goes to the real network with its key; a lookalike does not
    sent = {c[0]: c[1] for c in out["calls"]}
    assert sent["/live/snapshot"] == "Bearer test-key" and sent["/live/series?name=NIFTY"] == "Bearer test-key"      # the key travels with the request
    assert "data.json" in sent and "/api/i/stats" not in sent                                  # app calls never hit the network


@needs_node
def test_the_old_shim_would_have_failed_this_the_regression_that_hid_the_live_tab(tmp_path):
    old = ES.LIVE_SHIM.replace('if (path.startsWith("/live/") || path === "/news") return realFetch(url, init);', "")
    assert old != ES.LIVE_SHIM
    out = run(tmp_path, r"""
const r = await window.fetch("/live/snapshot", { headers: { Authorization: "Bearer k" } });
out.status = r.status;
""", shim=old)
    assert out["status"] == 404                                                                 # without the pass-through: exactly what the owner saw


def test_the_published_page_carries_the_pass_through(tmp_path):
    assert 'path.startsWith("/live/")' in ES.LIVE_SHIM and "return realFetch(url, init)" in ES.LIVE_SHIM
