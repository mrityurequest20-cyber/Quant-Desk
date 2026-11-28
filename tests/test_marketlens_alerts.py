"""MarketLens alerts in the desk's Worker (deploy/cloudflare/alerts.js, alertbook.js): the same rules as the app, sent once a
day per key through ntfy, only in market hours, and the app's route needs the owner's read key."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_cloudflare import stage_worker

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def test_the_workers_copies_are_the_apps_own_code():
    for name in ("livecore.js", "alertrules.js"):
        assert (ROOT / "deploy" / "cloudflare" / name).read_bytes() == (ROOT / "marketlens" / "web" / name).read_bytes(), name


HARNESS = r"""
import { AlertBook } from "./alertbook.js";
import { runAlerts, windows } from "./alerts.js";
import { handleLive } from "./live.js";
const store = new Map();
const state = { storage: { get: async (k) => (Array.isArray(k) ? new Map(k.map((x) => [x, store.get(x)])) : store.get(k)),
  put: async (k, v) => { if (typeof k === "object") for (const [a, b] of Object.entries(k)) store.set(a, b); else store.set(k, v); } } };
const book = new AlertBook(state);
const NOW = Date.parse("2026-11-26T11:00:00+05:30");                 // a trading Thursday, 11:00 IST
const quotes = { NIFTY: { ltp: 26300, chg: 2.0, age_s: 2 } };      // +2.0% with options at 14.4%: 2.2x the day's priced move
// a NIFTY front chain priced at 14.4% so the engine reads an IV
const N = (x) => 0.5 * (1 + Math.tanh(Math.sqrt(2 / Math.PI) * (x + 0.044715 * x ** 3)));
const exp = "2026-12-01", T = (Date.parse(exp + "T15:30:00+05:30") - NOW) / (365 * 86400e3), F = 26310;
for (let K = 25800; K <= 26800; K += 50) for (const cp of ["CE", "PE"]) {
  const s = 0.144, sq = s * Math.sqrt(T), d1 = (Math.log(F / K) + sq * sq / 2) / sq, d2 = d1 - sq, df = Math.exp(-0.065 * T);
  const px = cp === "CE" ? df * (F * N(d1) - K * N(d2)) : df * (K * N(-d2) - F * N(-d1));
  quotes[`NIFTY01DEC26${K}${cp}`] = { ltp: Math.max(0.05, Math.round(px * 20) / 20), vol: 1000, oi: 5000, age_s: 2, s: "opt" };
}
quotes["NIFTY-FUT"] = { ltp: F, oi: 1, age_s: 2 };
const ov = { universe: [{ symbol: "NIFTY", kind: "index" }], live_base: { NIFTY: { kind: "index", close: 25885, iv_front: Array(252).fill(0.13), gamma: { flip: 26200 } } },
  limits: { available: true, ban: [], near: [] } };
const pushes = [];
globalThis.fetch = async (url, init) => {
  url = String(url);
  if (url.endsWith("/data/overview.json")) return new Response(JSON.stringify({ ...ov, live_base: undefined }));
  if (url.endsWith("/data/live_base.json")) return new Response(JSON.stringify(ov.live_base));
  if (url.startsWith("https://ntfy.sh/")) { pushes.push({ title: init.headers.Title, body: init.body }); return new Response("{}"); }
  return new Response("no", { status: 404 });
};
const stub = { fetch: async (u, init = {}) => {
  const url = new URL(u);
  if (url.pathname === "/snapshot") return new Response(JSON.stringify({ quotes }));
  return book.handle(new Request(u, init), url, NOW);
} };
const env = { LIVE: { idFromName: () => "b", get: () => stub }, NTFY_TOPIC: "topic_for_tests_1", LIVE_READ_TOKEN: "r".repeat(30), LIVE_INGEST_TOKEN: "i".repeat(30), KOTAK_CONSUMER_KEY: "" };
const out = {};
out.first = await runAlerts({ scheduledTime: NOW }, env, {}, () => {});
out.pushes1 = pushes.length;
out.titles = pushes.map((p) => p.title);
out.second = await runAlerts({ scheduledTime: NOW + 600000 }, env, {}, () => {});
out.pushes2 = pushes.length;
out.night = await runAlerts({ scheduledTime: Date.parse("2026-11-26T02:00:00+05:30") }, env, {}, () => {});
out.sunday = windows(Date.parse("2026-11-29T11:00:00+05:30"));
out.mcx_evening = windows(Date.parse("2026-11-26T21:00:00+05:30"));
// the owner turns big_move off: the next day it is not sent
await book.handle(new Request("https://live/alerts/rules", { method: "PUT", body: JSON.stringify({ rules: [{ id: "big_move", on: false }, { id: "nope" }, { id: "iv_extreme", hi: 7 }] }) }), new URL("https://live/alerts/rules"), NOW);
const st = await (await book.handle(new Request("https://live/alerts/state"), new URL("https://live/alerts/state"), NOW)).json();
out.rules = st.rules; out.log_n = st.log.length;
out.third = await runAlerts({ scheduledTime: NOW + 86400000 }, env, {}, () => {});
// the app's route: the read key, or nothing
const pub = await handleLive(new Request("https://x/live/alerts"), { ...env, LIVE: env.LIVE });
out.pub_nokey = pub.status;
const pub2 = await handleLive(new Request("https://x/live/alerts", { headers: { authorization: "Bearer " + "r".repeat(30) } }), env);
out.pub_key = pub2.status;
process.stdout.write(JSON.stringify(out) + "\n");
"""


def test_alerts_are_pushed_once_a_day_in_market_hours_with_the_owners_rules(tmp_path):
    stage_worker(tmp_path)
    (tmp_path / "harness.mjs").write_text(HARNESS, encoding="utf-8")
    run = subprocess.run(["node", "harness.mjs"], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert out["first"]["ran"] and out["first"]["sent"] >= 2                      # the big move and the gamma flip
    titles = " | ".join(out["titles"])
    assert "NIFTY +2.00% today" in titles and "crossed its gamma flip" in titles
    assert out["pushes2"] == out["pushes1"]                                        # ten minutes later: nothing new
    assert out["night"]["ran"] is False and not out["sunday"]["nse"] and not out["sunday"]["mcx"]
    assert out["mcx_evening"]["mcx"] and not out["mcx_evening"]["nse"]
    assert {r["id"] for r in out["rules"]} == {"big_move", "iv_extreme"} and next(r for r in out["rules"] if r["id"] == "iv_extreme")["hi"] == 1
    assert out["log_n"] == out["pushes1"]
    assert "big_move" not in json.dumps(out["third"]) or out["third"]["sent"] <= 1   # the next day: only the gamma flip again
    assert out["pub_nokey"] == 401 and out["pub_key"] == 200
