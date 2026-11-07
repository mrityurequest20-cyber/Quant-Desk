"""The live view (display only): the Worker's relay (deploy/cloudflare/live.js, run under Node), the recorder's 5-second push (quantdesk/data/live_push.py),
the Live tab's wiring, and the guarantee that none of it can touch the recording or trading."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantdesk.data import kite_record as KR  # noqa: E402
from quantdesk.data import kite_universe as U  # noqa: E402
from quantdesk.data import live_push as LP  # noqa: E402

CORE_TOKENS = {"NIFTY": 256265, "BANKNIFTY": 260105, "INDIAVIX": 264969, "NIFTY-FUT": 1000, "BANKNIFTY-FUT": 2000}

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
GOOD_INGEST, GOOD_READ = "i" * 32, "r" * 32


# ---- the relay (Node) -----------------------------------------------------------------------------------------------------------------
def stage(tmp_path):
    for f in ("live.js", "kotak.js", "series.js"):
        shutil.copyfile(ROOT / "deploy" / "cloudflare" / f, tmp_path / ("live.mjs" if f == "live.js" else f))
    (tmp_path / "package.json").write_text('{"type": "module"}', encoding="utf-8")


HARNESS = r"""
import { handleLive, LiveBoard, clean, same, configured, readCapped } from "./live.mjs";
const mem = new Map();
const state = { storage: { get: async (k) => mem.get(k), put: async (k, v) => { mem.set(k, JSON.parse(JSON.stringify(v))); } }, blockConcurrencyWhile: async (fn) => fn() };
let board = new LiveBoard(state, {});
const LIVE = { idFromName: () => "board", get: () => ({ fetch: (u, init) => board.fetch(new Request(u, init)) }) };
const env = { LIVE, LIVE_INGEST_TOKEN: "%(I)s", LIVE_READ_TOKEN: "%(R)s" };
const call = async (method, path, { token, body, e = env } = {}) => {
  const r = await handleLive(new Request("https://qd.example" + path, { method, headers: token ? { authorization: "Bearer " + token } : {}, ...(body !== undefined ? { body: typeof body === "string" ? body : JSON.stringify(body) } : {}) }), e);
  if (r === null) return null;
  return { status: r.status, cc: r.headers.get("cache-control"), body: await r.json() };
};
const out = {};
out.notlive = await call("GET", "/data.json");
out.push = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: { NIFTY: { ltp: 24500.5, bid: 24500, ask: 24501, chg: 0.31, t: "2026-11-09T09:15:03+05:30", evil: "x" } } } });
out.read = await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN });
out.noauth_read = await call("GET", "/live/snapshot");
out.wrong_read = await call("GET", "/live/snapshot", { token: env.LIVE_INGEST_TOKEN });          // the ingest key does not read
out.wrong_push = await call("POST", "/live/ingest", { token: env.LIVE_READ_TOKEN, body: { quotes: { A: { ltp: 1 } } } });   // the read key does not write
out.badjson = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: "{nope" });
out.noltp = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: { A: { bid: 1 } } } });
out.badsym = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: { "<script>": { ltp: 1 } } } });
out.strltp = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: { A: { ltp: "1" } } } });
out.big = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: "x".repeat(600000) });
out.bigbytes = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: "é".repeat(300000) });          // 600 KB in bytes, 300 K characters
out.getingest = await call("GET", "/live/ingest", { token: env.LIVE_INGEST_TOKEN });
out.postsnap = await call("POST", "/live/snapshot", { token: env.LIVE_READ_TOKEN, body: {} });
out.other = await call("GET", "/live/other", { token: env.LIVE_READ_TOKEN });
// a second push of another symbol keeps the first; a partial push does not blank it
await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: { BANKNIFTY: { ltp: 52000 } } } });
out.merged = Object.keys((await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN })).body.quotes).sort();
// a chunked body with NO Content-Length is cut off at the cap: the stream is not read to the end
let pulled = 0;
const stream = new ReadableStream({ pull(c) { pulled += 1; if (pulled > 40) c.close(); else c.enqueue(new Uint8Array(100000).fill(120)); } });
const rs = await handleLive(new Request("https://qd.example/live/ingest", { method: "POST", headers: { authorization: "Bearer " + env.LIVE_INGEST_TOKEN }, body: stream, duplex: "half" }), env);
out.streamed = { status: rs.status, pulled };
// one bad name or quote is skipped and counted: it does not poison the rest of the push; a push with nothing usable is refused
out.mixed = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: { GOOD1: { ltp: 1 }, "bad name": { ltp: 2 }, GOOD2: { ltp: 3 }, NOLTP: { bid: 1 } } } });
out.mixedread = Object.keys((await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN })).body.quotes).filter((k) => k.startsWith("GOOD")).sort();
// a wide universe: 1200 quotes in one push keep their segment, a bad segment is dropped, odd names are harmless
const wide = {};
for (let i = 0; i < 1200; i++) wide["STK" + i] = { ltp: 100 + i, chg: 0.1, s: i %% 2 ? "eq" : "nonsense" };
Object.defineProperty(wide, "__proto__", { value: { ltp: 1 }, enumerable: true, configurable: true, writable: true });      // a real own key, as JSON.parse makes it
wide["constructor"] = { ltp: 2 };
out.widepush = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: JSON.stringify({ quotes: wide }) });
const ws = (await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN })).body;
out.wide = { count: ws.count, n: Object.keys(ws.quotes).length, s1: ws.quotes.STK1.s, s0: ws.quotes.STK0.s === undefined, ctor: ws.quotes.constructor.ltp, proto: Object.keys(ws.quotes).includes("__proto__") };
// the board never grows past its cap: 2500 + 2500 new names, the second push is partly refused
const a = {}, b = {};
for (let i = 0; i < 2500; i++) { a["A" + i] = { ltp: 1 }; b["B" + i] = { ltp: 1 }; }
await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: a } });
out.cap2 = await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: b } });
out.capcount = (await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN })).body.count;
// the Durable Object restarts: memory only, so the board starts empty and fills again from the next pushes
board = new LiveBoard(state, {});
out.restarted = (await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN })).body.count;
await call("POST", "/live/ingest", { token: env.LIVE_INGEST_TOKEN, body: { quotes: { NIFTY: { ltp: 5 } } } });
out.refilled = Object.keys((await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN })).body.quotes);
// off unless both secrets are set, long enough and different
out.off_missing = await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN, e: { ...env, LIVE_READ_TOKEN: "" } });
out.off_short = await call("GET", "/live/snapshot", { token: "short", e: { ...env, LIVE_READ_TOKEN: "short" } });
out.off_equal = await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN, e: { ...env, LIVE_INGEST_TOKEN: env.LIVE_READ_TOKEN } });
out.off_nobinding = await call("GET", "/live/snapshot", { token: env.LIVE_READ_TOKEN, e: { ...env, LIVE: undefined } });
out.same = [await same("abc", "abc"), await same("abc", "abd"), await same("", "")];
out.configured = configured(env);
console.log(JSON.stringify(out));
""" % {"I": GOOD_INGEST, "R": GOOD_READ}


@pytest.fixture(scope="module")
def relay(tmp_path_factory):
    if shutil.which("node") is None:
        pytest.skip("Node is not installed")
    d = tmp_path_factory.mktemp("relay")
    stage(d)
    (d / "run.mjs").write_text(HARNESS, encoding="utf-8")
    r = subprocess.run(["node", "run.mjs"], cwd=d, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


@needs_node
def test_only_live_paths_are_the_relays(relay):
    assert relay["notlive"] is None                                      # /data.json and the rest still go to Pages


@needs_node
def test_a_push_is_stored_and_read_back_with_ages_and_nothing_extra(relay):
    assert relay["push"]["status"] == 200
    q = relay["read"]["body"]["quotes"]["NIFTY"]
    assert q["ltp"] == 24500.5 and q["bid"] == 24500 and q["t"].startswith("2026-11-09") and "evil" not in q       # unknown fields are dropped
    assert 0 <= q["age_s"] < 5 and relay["read"]["body"]["newest_age_s"] < 5
    assert relay["read"]["cc"] == "no-store"


@needs_node
def test_each_key_opens_only_its_own_door(relay):
    assert relay["noauth_read"]["status"] == 401
    assert relay["wrong_read"]["status"] == 401                          # the recorder's key cannot read prices back
    assert relay["wrong_push"]["status"] == 401                          # the app's key cannot write them
    assert "NIFTY" not in json.dumps(relay["noauth_read"]) and "24500" not in json.dumps(relay["wrong_read"])


@needs_node
def test_bad_pushes_are_refused_and_change_nothing(relay):
    for k, status in (("badjson", 400), ("noltp", 400), ("badsym", 400), ("strltp", 400), ("big", 413), ("bigbytes", 413)):
        assert relay[k]["status"] == status, k
    assert relay["merged"] == ["BANKNIFTY", "NIFTY"]                     # none of the refused pushes added a symbol (the limit is bytes, not characters)
    assert relay["getingest"]["status"] == 405 and relay["postsnap"]["status"] == 405 and relay["other"]["status"] == 404


@needs_node
def test_a_chunked_body_without_content_length_is_cut_off_at_the_cap(relay):
    assert relay["streamed"]["status"] == 413 and relay["streamed"]["pulled"] < 15          # 40 chunks of 100 KB were on offer; the 512 KB cap stopped the read after about 6


@needs_node
def test_one_bad_name_does_not_poison_a_push(relay):
    assert relay["mixed"]["status"] == 200 and relay["mixed"]["body"]["dropped"] == 2 and relay["mixedread"] == ["GOOD1", "GOOD2"]


@needs_node
def test_pushes_merge_and_a_restart_starts_empty_and_refills(relay):
    assert relay["merged"] == ["BANKNIFTY", "NIFTY"]
    assert relay["restarted"] == 0 and relay["refilled"] == ["NIFTY"]    # memory only: the record of every tick is the recorder's Parquet


@needs_node
def test_a_wide_universe_goes_through_with_segments_and_odd_names_are_harmless(relay):
    assert relay["widepush"]["status"] == 200
    w = relay["wide"]
    assert w["n"] >= 1200 and w["s1"] == "eq" and w["s0"] is True        # a valid segment is kept, a bad one dropped
    assert w["ctor"] == 2 and w["proto"] is True                         # names like constructor and __proto__ are data, not code


@needs_node
def test_the_board_never_grows_past_its_cap(relay):
    assert relay["cap2"]["status"] == 200 and relay["cap2"]["body"]["refused"] > 0
    assert relay["capcount"] == 4000


@needs_node
def test_it_is_off_unless_both_secrets_are_set_long_and_different(relay):
    for k in ("off_missing", "off_short", "off_equal", "off_nobinding"):
        assert relay[k]["status"] == 503, k
    assert relay["configured"] is True and relay["same"] == [True, False, True]


def test_the_worker_imports_the_relay_and_exports_the_object_wrangler_binds():
    wk = (ROOT / "deploy/cloudflare/worker.js").read_text()
    assert 'import { armLive, handleLive, needsUniverse } from "./live.js"' in wk and 'export { LiveBoard } from "./live.js"' in wk
    assert wk.index("handleLive(request, env)") < wk.index('request.method !== "GET" && request.method !== "HEAD"')       # before the read-only 405
    cfg = json.loads(re.sub(r"^\s*//.*$", "", (ROOT / "wrangler.jsonc").read_text(), flags=re.M))
    assert cfg["durable_objects"]["bindings"] == [{"name": "LIVE", "class_name": "LiveBoard"}]
    assert cfg["migrations"][0]["new_sqlite_classes"] == ["LiveBoard"]


def test_the_relay_never_touches_pages_or_logs_a_secret():
    src = (ROOT / "deploy/cloudflare/live.js").read_text()
    assert "console." not in src and "ORIGIN" not in src
    assert "fetch(" not in src.replace("stub.fetch(", "").replace("async fetch(", "").replace('.fetch("https://live/arm"', "").replace('.fetch("https://live/needs-universe"', "")      # the relay's own object and nothing else: it never reaches out itself


# ---- the recorder's push (Python) -------------------------------------------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def tick(token=1, price=24500.0, change=0.3, bid=24499.0, ask=24501.0):
    return {"instrument_token": token, "last_price": price, "change": change, "volume_traded": 1000, "oi": 5,
            "exchange_timestamp": pd.Timestamp("2026-11-09 09:15:03", tz="Asia/Kolkata").to_pydatetime(),
            "depth": {"buy": [{"price": bid, "quantity": 50, "orders": 3}], "sell": [{"price": ask, "quantity": 60, "orders": 2}]}}


def test_quote_from_tick_keeps_display_fields_and_drops_bad_numbers():
    row = KR.tick_row(tick(), "NIFTY", pd.Timestamp("2026-11-09 09:15:04", tz="Asia/Kolkata"))
    q = LP.quote_from_tick(row, 0.3)
    assert q["ltp"] == 24500.0 and q["bid"] == 24499.0 and q["ask"] == 24501.0 and q["chg"] == 0.3 and q["t"].startswith("2026-11-09 09:15:03")
    assert set(q) <= set(LP.FIELDS) | {"t"}
    assert LP.quote_from_tick({"last_price": float("nan")}) is None and LP.quote_from_tick({}) is None


def test_it_is_off_without_both_settings_and_refuses_plain_http(monkeypatch):
    monkeypatch.delenv("LIVE_URL", raising=False)
    monkeypatch.delenv("LIVE_INGEST_TOKEN", raising=False)
    assert LP.LivePusher.from_env() is None
    monkeypatch.setenv("LIVE_URL", "https://x.example/live/ingest")
    assert LP.LivePusher.from_env() is None                               # no token
    monkeypatch.setenv("LIVE_INGEST_TOKEN", "t" * 30)
    assert LP.LivePusher.from_env() is not None
    monkeypatch.setenv("LIVE_URL", "http://x.example/live/ingest")
    assert LP.LivePusher.from_env() is None                               # the token is never sent in the clear


def test_only_changed_quotes_are_sent_and_a_quiet_market_sends_nothing():
    sent = []
    p = LP.LivePusher("https://x.example/live/ingest", "T" * 30, opener=lambda req, timeout: (sent.append(req), FakeResp())[1])
    p.update("NIFTY", {"ltp": 1.0})
    p.update("NIFTY", {"ltp": 2.0})                                      # the newest wins
    p.update("BANKNIFTY", {"ltp": 3.0})
    assert p.push_once() and len(sent) == 1
    assert json.loads(sent[0].data) == {"quotes": {"NIFTY": {"ltp": 2.0}, "BANKNIFTY": {"ltp": 3.0}}}
    assert sent[0].get_header("Authorization") == "Bearer " + "T" * 30 and sent[0].full_url.startswith("https://")
    assert p.push_once() and len(sent) == 1                               # nothing changed: nothing sent, so the relay's age keeps growing


def test_a_failed_push_is_counted_not_raised_keeps_the_quote_and_never_names_the_token():
    def boom(req, timeout):
        raise OSError("connection refused for https://x.example/live/ingest Bearer " + "T" * 30)
    p = LP.LivePusher("https://x.example/live/ingest", "T" * 30, opener=boom)
    p.update("NIFTY", {"ltp": 1.0})
    assert p.push_once() is False and p.failed == 1 and p.dirty == {"NIFTY": {"ltp": 1.0}}
    p.update("NIFTY", {"ltp": 9.0})                                      # a newer tick replaces the unsent one
    assert p.dirty["NIFTY"] == {"ltp": 9.0}
    assert p.last_error == "OSError" and "T" * 30 not in json.dumps(p.stats()) and "x.example" not in json.dumps(p.stats())
    p._open = lambda req, timeout: FakeResp(503)
    assert p.push_once() is False and p.last_error.startswith("HTTPError 503")


def _recorder(tmp_path, live):
    class WS:
        MODE_FULL = "full"

        def connect(self, threaded=True): pass
        def close(self): pass
        def subscribe(self, t): pass
        def set_mode(self, m, t): pass
    return KR.Recorder(tmp_path, {"NIFTY": 1, "BANKNIFTY": 2}, WS, live=live)


def test_the_recorder_feeds_the_push_and_a_broken_push_never_costs_a_recorded_tick(tmp_path):
    seen = []

    class Live:
        def update(self, sym, q): seen.append((sym, q["ltp"]))
    rec = _recorder(tmp_path / "a", Live())
    rec._on_ticks(None, [tick(1, 100.0), tick(2, 200.0), tick(99, 5.0)])      # token 99 is not subscribed
    assert seen == [("NIFTY", 100.0), ("BANKNIFTY", 200.0)] and rec.ticks == 2

    class Broken:
        def update(self, sym, q): raise RuntimeError("relay exploded")
    rec2 = _recorder(tmp_path / "b", Broken())
    rec2._on_ticks(None, [tick(1, 100.0), tick(2, 200.0)])
    assert rec2.ticks == 2 and len(rec2.rows) == 2                          # both ticks are still recorded
    assert rec2.flush() is not None


def test_run_starts_and_stops_the_push_and_records_its_counts(tmp_path):
    calls = []

    class Live:
        def start(self): calls.append("start")
        def stop(self): calls.append("stop")
        def stats(self): return {"pushes_ok": 3, "pushes_failed": 0, "last_error": None}
    rec = _recorder(tmp_path, Live())
    t0 = pd.Timestamp("2026-11-09 09:15", tz="Asia/Kolkata")
    clock = iter([t0, t0, t0 + pd.Timedelta(seconds=5), t0 + pd.Timedelta(seconds=5)] + [t0 + pd.Timedelta(seconds=9999)] * 20)
    rec.now = lambda: next(clock)
    rec.run(t0 + pd.Timedelta(seconds=2), sleep=lambda s: None)
    assert calls == ["start", "stop"]
    assert any(e["kind"] == "live" and e["pushes_ok"] == 3 for e in map(json.loads, (tmp_path / "events.jsonl").read_text().splitlines()))


def test_the_push_module_can_trade_nothing_and_holds_no_secret_in_the_source():
    for f in ("quantdesk/data/live_push.py", "deploy/cloudflare/live.js"):
        src = (ROOT / f).read_text()
        assert not re.search(r"place_order|modify_order|cancel_order|\.orders\(|\.positions\(|\.holdings\(|\.margins\(|\.profile\(|exit_order", src), f
    py = (ROOT / "quantdesk/data/live_push.py").read_text()
    assert not re.search(r"quantdesk\.(paper|engine|journal|risk|broker)|from \.\.(paper|engine|journal)", py)
    assert "print(" not in py


# ---- the app and the workflow ---------------------------------------------------------------------------------------------------------------
def test_the_service_worker_never_caches_live_prices():
    sw = (ROOT / "quantdesk/web/static/app/sw.js").read_text()
    assert "/live/" in sw and sw.index("/live/") < sw.index("e.respondWith(fetch(req)")


def test_the_live_tab_is_wired_in():
    app = (ROOT / "quantdesk/web/static/app/app.js").read_text()
    html = (ROOT / "quantdesk/web/static/app/index.html").read_text()
    assert '["live", "Live"]' in app and 'data-view="live"' in html and "renderLive" in app and "/live/snapshot" in app
    assert "5000" in app and "Authorization" in app and "qd.livekey" in app


def test_the_recorder_workflow_gives_the_push_only_its_token_and_url():
    text = (ROOT / ".github/workflows/kite-record.yml").read_text()
    assert text.count("LIVE_INGEST_TOKEN: ${{ secrets.LIVE_INGEST_TOKEN }}") == 2 and text.count("LIVE_URL: ${{ vars.LIVE_URL }}") == 2
    # only in the steps that run the recorder: never next to a Zerodha secret
    for step in re.split(r"\n      - name: ", text):
        if "LIVE_INGEST_TOKEN" in step:
            assert step.startswith("Record ticks") and not re.search(r"KITE_(PASSWORD|TOTP_SECRET|API_SECRET|USER_ID)", step)


def test_names_the_relay_would_refuse_never_enter_a_batch_and_the_relays_full_board_is_counted():
    sent = []

    class R(FakeResp):
        closed = False

        def __exit__(self, *a):
            self.closed = True
            return False

        def read(self, n=-1):
            assert not self.closed, "the body must be read inside the connection, before it is closed"
            return b'{"ok": true, "refused": 7}'
    p = LP.LivePusher("https://x.example/live/ingest", "T" * 30, opener=lambda req, timeout: (sent.append(json.loads(req.data)), R())[1])
    p.update("GOOD", {"ltp": 1.0})
    p.update("bad name", {"ltp": 2.0})
    p.update("x" * 41, {"ltp": 3.0})
    assert p.push_once() and list(sent[0]["quotes"]) == ["GOOD"] and p.skipped == 2 and p.refused == 7
    assert p.stats()["skipped_names"] == 2 and p.stats()["refused_by_relay"] == 7                   # in the run's events, not retried


def test_the_universe_never_subscribes_a_name_the_relay_could_not_show_and_never_reuses_a_token():
    from tests.test_kite_universe import FakeKite, TODAY, _inst, make_lists
    lists = make_lists()
    lists["NFO"] = lists["NFO"] + [_inst(70001, "WEIRD NAME", "FUT", "2026-11-24", sym="WEIRD NAME-FUT"), _inst(7000, "DUPE", "FUT", "2026-11-24")]
    lists["MCX"] = lists["MCX"] + [_inst(7000, "DUPEMCX", "FUT", "2026-11-28", exch="MCX")]            # the same token again, under another name
    toks, meta, _ = U.build_wide(FakeKite(lists=lists), TODAY, CORE_TOKENS)
    assert "WEIRD NAME-FUT" not in toks and "DUPE-FUT" in toks and "DUPEMCX-MCX" not in toks
    assert len(set(toks.values())) == len(toks)


def test_the_live_tab_shows_no_key_form_on_the_public_pages_address():
    app = (ROOT / "quantdesk/web/static/app/app.js").read_text()
    body = app[app.index("async function renderLive()"):]
    assert body.index("github") < body.index('store("qd.livekey")')              # checked before any key is read or asked for
