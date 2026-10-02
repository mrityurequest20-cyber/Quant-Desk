"""The Cloudflare Worker that serves the published site: its config is what Workers Builds needs, and the
Worker passes requests to GitHub Pages with live data uncached (run under Node when it's installed)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _config() -> dict:
    text = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    return json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))


def test_wrangler_config_is_deployable():
    c = _config()
    assert c["name"] == "quantdesk"                                 # must match the Worker in the dashboard
    assert (ROOT / c["main"]).is_file()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", c["compatibility_date"]) and c["compatibility_date"] >= "2024-11-11"
    assert c["vars"]["ORIGIN"].startswith("https://") and not c["vars"]["ORIGIN"].endswith("/")


HARNESS = r"""
import worker from "./worker.mjs";
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url: String(url), init });
  if (String(url).endsWith("/fonts")) {
    return new Response(null, { status: 301, headers: { location: "https://pages.example/Quant-Desk/fonts/" } });
  }
  return new Response("ok", { status: 200, headers: { "cache-control": "max-age=600", "content-type": "text/plain" } });
};
const env = { ORIGIN: "https://pages.example/Quant-Desk/" };
const last = () => calls[calls.length - 1];
const out = {};
let r = await worker.fetch(new Request("https://qd.example.workers.dev/data.json?t=1", { headers: { "if-none-match": '"e1"', cookie: "x=1" } }), env);
out.data = { status: r.status, cc: r.headers.get("cache-control"), url: last().url, cache: last().init.cache ?? null,
             inm: new Headers(last().init.headers).get("if-none-match"), cookie: new Headers(last().init.headers).get("cookie") };
r = await worker.fetch(new Request("https://qd.example.workers.dev/"), env);
out.root = { url: last().url, cc: r.headers.get("cache-control"), cache: last().init.cache ?? null, body: await r.text() };
r = await worker.fetch(new Request("https://qd.example.workers.dev/fonts"), env);
out.redirect = { status: r.status, location: r.headers.get("location") };
const n = calls.length;
r = await worker.fetch(new Request("https://qd.example.workers.dev/data.json", { method: "POST", body: "x" }), env);
out.post = { status: r.status, upstream: calls.length - n };
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_worker_passes_requests_to_pages(tmp_path):
    shutil.copyfile(ROOT / _config()["main"], tmp_path / "worker.mjs")
    (tmp_path / "harness.mjs").write_text(HARNESS, encoding="utf-8")
    run = subprocess.run(["node", "harness.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout.strip().splitlines()[-1])
    d = out["data"]
    assert d["url"] == "https://pages.example/Quant-Desk/data.json?t=1"          # path and query kept
    assert d["cache"] == "no-store" and d["cc"] == "no-cache"                    # live data: never edge-cached
    assert d["inm"] == '"e1"' and d["cookie"] is None                            # revalidation passes, cookies don't
    assert out["root"] == {"url": "https://pages.example/Quant-Desk/", "cc": "max-age=600", "cache": None, "body": "ok"}
    assert out["redirect"] == {"status": 301, "location": "https://qd.example.workers.dev/fonts/"}   # stays on Cloudflare
    assert out["post"] == {"status": 405, "upstream": 0}
