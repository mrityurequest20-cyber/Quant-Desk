"""The Kotak live universe builder (quantdesk/data/kotak_universe.py), its push to the relay, the `data kotak-universe` command and its workflow. No network: a fake client
answers in the shapes quantdesk/intraday/kotak.py parses."""
from __future__ import annotations

import datetime as dt
import http.server
import json
import re
import threading
from pathlib import Path

import pandas as pd
import pytest

from quantdesk.data import kotak_universe as KU

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 9)


class FakeClient:
    """Just the three things the builder uses: `_get` (the chain endpoint's future view), `expiries`, and the scrip master (patched in)."""

    def __init__(self, fut_expiries=("2026-11-03", "2026-11-24", "2026-12-29"), no_future=(), bad_expiries=()):
        self.fut_expiries, self.no_future, self.bad_expiries, self.log = fut_expiries, set(no_future), set(bad_expiries), []

    def _get(self, path, params=None):
        self.log.append((path, dict(params or {})))
        u = params["underlying"]
        if u in self.no_future:
            return {"future_contracts": []}
        rows = [{"inst": {"neoSymbol": f"nse_fo|{abs(hash((u, e))) % 90000 + 10000}", "symbol": f"{u}{e}", "exp": e}, "quote": {"ltp": "1"}, "oi": {"cur": "1"}} for e in self.fut_expiries]
        return {"data": {"future_contracts": rows}}

    def expiries(self, underlying, exchange="nse_fo"):
        self.log.append(("expiries", {"underlying": underlying, "exchange": exchange}))
        if underlying in self.bad_expiries:
            raise RuntimeError("no expiries")
        return [dt.date.fromisoformat(x) for x in ("2026-11-03", "2026-11-10", "2026-11-17", "2026-11-24")]


@pytest.fixture
def master(monkeypatch):
    rows = [{"pSymbolName": n, "pInstType": "FUTSTK", "pAssetCode": 100 + i} for i, n in enumerate(("RELIANCE", "TCS", "M&M", "BAJAJ-AUTO", "NOTOKENCO"))]
    rows += [{"pSymbolName": "NIFTY", "pInstType": "FUTIDX", "pAssetCode": 999}, {"pSymbolName": "RELIANCE", "pInstType": "OPTSTK", "pAssetCode": 100}]
    df = pd.DataFrame(rows)
    df.loc[df["pSymbolName"] == "NOTOKENCO", "pAssetCode"] = 0
    monkeypatch.setattr(KU, "scrip_master", lambda client, name="nse_fo": df)
    return df


def by_name(u):
    return {q["n"]: q for q in u["quotes"]}


def test_the_universe_lists_indices_stocks_futures_and_chains_by_the_names_the_kite_universe_uses(master):
    u = KU.build(FakeClient(), TODAY, say=lambda *a: None)
    q = by_name(u)
    assert u["asof"] == "2026-11-09" and u["count"] == KU.CHAIN_STRIKES
    for n in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIAVIX", "SENSEX", "BANKEX"):
        assert q[n]["s"] == "idx" and q[n]["one"] is True                                    # asked for by name, one to a call
    assert q["NIFTY"]["g"] == "nse_cm" and q["SENSEX"]["g"] == "bse_cm" and q["NIFTY"]["t"] == "Nifty 50"
    assert {n for n, v in q.items() if v["s"] == "eq"} == {"RELIANCE", "TCS", "M&M", "BAJAJ-AUTO"}      # NOTOKENCO has no cash token: skipped, counted
    assert q["RELIANCE"]["g"] == "nse_cm" and q["RELIANCE"]["t"] == "100"
    assert {"RELIANCE-FUT", "TCS-FUT", "M&M-FUT", "BAJAJ-AUTO-FUT", "NIFTY-FUT", "BANKNIFTY-FUT", "FINNIFTY-FUT", "MIDCPNIFTY-FUT"} <= set(q)
    assert q["RELIANCE-FUT"]["s"] == "fut" and q["RELIANCE-FUT"]["g"] == "nse_fo" and q["RELIANCE-FUT"]["t"].isdigit()
    assert any("no cash token" in e for e in u["errors"])


def test_a_future_is_the_nearest_unexpired_one(master):
    c = FakeClient(fut_expiries=("2026-11-03", "2026-12-29", "2026-11-24"))
    u = KU.build(c, TODAY, say=lambda *a: None)
    got = by_name(u)["TCS-FUT"]["t"]
    expected = str(abs(hash(("TCS", "2026-11-24"))) % 90000 + 10000)                       # the 3 Nov contract has expired; 24 Nov is nearer than 29 Dec
    assert got == expected


def test_option_chains_are_the_nearest_two_unexpired_expiries_per_index_on_the_right_exchange(master):
    u = KU.build(FakeClient(), TODAY, say=lambda *a: None)
    by_u = {}
    for c in u["chains"]:
        if "n" not in c:                                                                   # the stock chains have a keep-count: they are tested below
            by_u.setdefault(c["u"], []).append(c)
    assert set(by_u) == set(KU.CHAIN_UNDERLYINGS)
    assert [c["e"] for c in by_u["NIFTY"]] == ["2026-11-10", "2026-11-17"] and all(c["x"] == "nse_fo" for c in by_u["NIFTY"])
    assert all(c["x"] == "bse_fo" for c in by_u["SENSEX"] + by_u["BANKEX"])


def test_every_fno_stock_gets_its_nearest_unexpired_expiry_chain_with_a_keep_count(master):
    u = KU.build(FakeClient(bad_expiries=("TCS",)), TODAY, say=lambda *a: None)
    stock = {c["u"]: c for c in u["chains"] if "n" in c}
    assert set(stock) == {"RELIANCE", "M&M", "BAJAJ-AUTO", "NOTOKENCO"}                      # TCS had no expiries: skipped and counted; every other F&O stock has one
    assert all(c["e"] == "2026-11-10" and c["x"] == "nse_fo" and c["n"] == KU.STOCK_STRIKES for c in stock.values())      # the nearest expiry that is not past
    assert any("TCS expiries" in e for e in u["errors"])
    assert not any("n" in c for c in u["chains"] if c["u"] in KU.CHAIN_UNDERLYINGS)          # an index chain has no keep-count: it runs in every cycle


def test_stock_chains_are_capped(master, monkeypatch):
    monkeypatch.setattr(KU, "STOCK_CHAINS_MAX", 2)
    u = KU.build(FakeClient(), TODAY, say=lambda *a: None)
    assert sum(1 for c in u["chains"] if "n" in c) == 2


def test_one_failure_skips_only_its_part_and_is_counted(master, monkeypatch):
    u = KU.build(FakeClient(no_future=("TCS",), bad_expiries=("FINNIFTY",)), TODAY, say=lambda *a: None)
    q = by_name(u)
    assert "TCS-FUT" not in q and "RELIANCE-FUT" in q and "FINNIFTY" in q                    # the index spot is still listed
    assert not any(c["u"] == "FINNIFTY" for c in u["chains"]) and any(c["u"] == "NIFTY" for c in u["chains"])
    assert any("TCS future" in e for e in u["errors"]) and any("FINNIFTY expiries" in e for e in u["errors"])
    monkeypatch.setattr(KU, "scrip_master", lambda client, name="nse_fo": (_ for _ in ()).throw(RuntimeError("download failed")))
    u = KU.build(FakeClient(), TODAY, say=lambda *a: None)
    assert not any(v["s"] == "eq" for v in u["quotes"]) and "NIFTY-FUT" in by_name(u) and any("scrip master" in e for e in u["errors"])      # no stocks, but the indices and their futures remain


def test_only_names_the_relay_accepts_are_listed(master):
    u = KU.build(FakeClient(), TODAY, say=lambda *a: None)
    assert all(KU.SYMBOL.match(q["n"]) for q in u["quotes"]) and len({q["n"] for q in u["quotes"]}) == len(u["quotes"])


def test_the_dry_run_limit_caps_the_future_lookups(master):
    c = FakeClient()
    KU.build(c, TODAY, say=lambda *a: None, fut_limit=2)
    assert sum(1 for p, _ in c.log if "option-chain" in p) == 2


# ---- the push -------------------------------------------------------------------------------------------------------------------------------
def test_the_relays_universe_url_comes_from_live_url_and_only_over_https():
    assert KU.universe_url("https://qd.example.workers.dev/live/ingest") == "https://qd.example.workers.dev/live/universe"
    assert KU.universe_url("https://qd.example.workers.dev/live/ingest/") == "https://qd.example.workers.dev/live/universe"
    for bad in ("http://qd.example/live/ingest", "https://qd.example/other", ""):
        with pytest.raises(ValueError):
            KU.universe_url(bad)


class Resp:
    status = 200

    def __init__(self, body=b'{"ok": true, "quotes": 3, "chains": 1, "kotak": true}'):
        self.body = body

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=-1): return self.body


def test_the_push_sends_the_universe_without_its_errors_with_the_ingest_token():
    seen = []
    u = {"asof": "2026-11-09", "count": 10, "quotes": [{"n": "A", "s": "eq", "g": "nse_cm", "t": "1"}], "chains": [], "errors": ["secret-looking gap"]}
    ans = KU.push(u, "https://qd.example/live/ingest", "T" * 30, opener=lambda req, timeout: (seen.append(req), Resp())[1])
    req = seen[0]
    assert ans["kotak"] is True and req.full_url == "https://qd.example/live/universe" and req.get_header("Authorization") == "Bearer " + "T" * 30
    sent = json.loads(req.data)
    assert "errors" not in sent and sent["quotes"][0]["n"] == "A"
    with pytest.raises(ValueError):
        KU.push(u, "https://qd.example/live/ingest", "")


def test_a_failed_push_names_neither_the_token_nor_the_address():
    import urllib.error

    def refuse(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", None, None)

    def down(req, timeout):
        raise OSError("could not connect to https://qd.example/live/universe with Bearer " + "T" * 30)
    for opener in (refuse, down):
        with pytest.raises(RuntimeError) as e:
            KU.push({"quotes": [], "chains": []}, "https://qd.example/live/ingest", "T" * 30, opener=opener)
        assert "T" * 30 not in str(e.value) and "qd.example" not in str(e.value)
    with pytest.raises(RuntimeError, match="HTTP 401"):
        KU.push({"quotes": [], "chains": []}, "https://qd.example/live/ingest", "T" * 30, opener=refuse)


def test_the_push_never_follows_a_redirect_with_its_token():
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_POST(self):
            hits.append(self.path)
            if self.path == "/live/universe":
                self.send_response(302); self.send_header("Location", "/elsewhere"); self.end_headers()
            else:
                self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    real = KU.universe_url
    KU.universe_url = lambda url: f"http://127.0.0.1:{srv.server_port}/live/universe"                 # the https rule is checked by universe_url; the opener's redirect rule is under test
    try:
        with pytest.raises(RuntimeError, match="HTTP 302"):
            KU.push({"quotes": [], "chains": []}, "https://x/live/ingest", "T" * 30)
    finally:
        KU.universe_url = real
        srv.shutdown()
    assert hits == ["/live/universe"]


# ---- the command --------------------------------------------------------------------------------------------------------------------------------
def test_the_command_needs_a_key_pushes_counts_only_and_fails_when_nothing_is_built(master, monkeypatch, capsys, tmp_path):
    from quantdesk.cli import main
    monkeypatch.delenv("KOTAK_CONSUMER_KEY", raising=False)
    with pytest.raises(SystemExit, match="no KOTAK_CONSUMER_KEY"):
        main(["data", "kotak-universe"])
    monkeypatch.setenv("KOTAK_CONSUMER_KEY", "kotak-secret-key-0123456789")
    monkeypatch.setenv("LIVE_URL", "https://qd.example/live/ingest")
    monkeypatch.setenv("LIVE_INGEST_TOKEN", "ingest-token-0123456789-abcdef")
    monkeypatch.setattr("quantdesk.intraday.kotak.KotakClient", lambda key, **k: FakeClient())
    pushed = []
    monkeypatch.setattr(KU, "push", lambda u, url, token, **k: (pushed.append((len(u["quotes"]), url, token)), {"quotes": len(u["quotes"]), "chains": len(u["chains"]), "kotak": True})[1])
    out = tmp_path / "u.json"
    main(["data", "kotak-universe", "--push", "--out", str(out)])
    text = capsys.readouterr().out
    assert pushed and pushed[0][0] > 10 and "pushed to the relay" in text
    assert "kotak-secret-key" not in text and "ingest-token" not in text and "qd.example" not in text
    saved = out.read_text()
    assert "kotak-secret-key" not in saved and "ingest-token" not in saved and json.loads(saved)["asof"]
    monkeypatch.delenv("LIVE_URL")
    with pytest.raises(SystemExit, match="needs LIVE_URL"):
        main(["data", "kotak-universe", "--push"])
    monkeypatch.setattr(KU, "build", lambda *a, **k: {"asof": "x", "count": 10, "quotes": [], "chains": [], "errors": ["Kotak down"]})
    with pytest.raises(SystemExit, match="nothing could be built"):
        main(["data", "kotak-universe"])


def test_the_module_can_trade_nothing_and_prints_no_secret():
    src = (ROOT / "quantdesk/data/kotak_universe.py").read_text()
    assert not re.search(r"place_order|modify_order|cancel_order|\.orders\(|\.positions\(|\.holdings\(|\.margins\(|\.profile\(|/orders|/portfolio", src)
    assert not re.search(r"quantdesk\.(paper|engine|journal|risk|broker)|from \.\.(paper|engine|journal)", src)
    assert "os.environ" not in src and not re.search(r"print\([^)]*(key|token)", src, re.I)               # the key and the token come in as arguments from the command and are never printed here


# ---- the workflow ----------------------------------------------------------------------------------------------------------------------------------
def test_the_workflow_is_read_only_pinned_and_holds_the_secrets_only_in_its_one_run_step():
    import yaml
    text = (ROOT / ".github/workflows/kotak-universe.yml").read_text()
    wf = yaml.load(text, Loader=yaml.BaseLoader)                                  # BaseLoader: a bare `on:` stays the string "on", not True
    assert wf["permissions"] == {"contents": "read"} and set(wf["on"]) == {"schedule", "workflow_dispatch"}
    assert len(wf["on"]["schedule"]) == 2
    steps = wf["jobs"]["build"]["steps"]
    assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", s["uses"]) for s in steps if "uses" in s)         # immutable pins
    holders = [s for s in steps if re.search(r"secrets\.", json.dumps(s))]
    assert len(holders) == 1 and set(holders[0]["env"]) == {"KOTAK_CONSUMER_KEY", "LIVE_URL", "LIVE_INGEST_TOKEN"}
    assert holders[0]["run"].strip() == "python -m quantdesk data kotak-universe --push"
    assert sorted(set(re.findall(r"secrets\.([A-Z_]+)", text))) == ["KOTAK_CONSUMER_KEY", "LIVE_INGEST_TOKEN"]


def test_a_scrip_master_name_that_is_not_a_plain_symbol_never_reaches_the_output(monkeypatch):
    """N5 of the #210 review: names come from a CSV and the gap lines are printed as workflow lines, so a '::' or a newline in one must go nowhere."""
    rows = [{"pSymbolName": n, "pInstType": "FUTSTK", "pAssetCode": 200 + i} for i, n in enumerate(("GOOD", "::error::x", "BAD\nNAME", "SPACED NAME"))]
    monkeypatch.setattr(KU, "scrip_master", lambda client, name="nse_fo": pd.DataFrame(rows))
    u = KU.build(FakeClient(), TODAY, say=lambda *a: None)
    text = json.dumps(u)
    assert "::ERROR::X" not in text.upper() and "BAD" not in text and "SPACED" not in text
    assert any(q["n"] == "GOOD" for q in u["quotes"])
    assert any("3 F&O stock names were not plain symbols" in e for e in u["errors"]) and not any("ERROR" in e for e in u["errors"])          # counted, never named


def test_the_stock_chain_constants_are_what_the_docs_say():
    assert KU.STOCK_STRIKES == 3 and KU.STOCK_CHAINS_MAX == 250 and KU.STOCK_FAIL_RUN == 10


def test_a_run_of_failed_expiry_lookups_stops_the_stock_chains_for_the_day(master, monkeypatch):
    rows = [{"pSymbolName": f"STK{i:03d}", "pInstType": "FUTSTK", "pAssetCode": 300 + i} for i in range(40)]
    monkeypatch.setattr(KU, "scrip_master", lambda client, name="nse_fo": pd.DataFrame(rows))
    client = FakeClient(bad_expiries=tuple(f"STK{i:03d}" for i in range(40)))
    u = KU.build(client, TODAY, say=lambda *a: None)
    asked = [c for c in client.log if c[0] == "expiries" and c[1]["underlying"].startswith("STK")]
    assert len(asked) == KU.STOCK_FAIL_RUN                                                  # it gave up after ten in a row, it did not ask forty
    assert any("stopped after 10 failures in a row; 30 stocks have no chain today" in e for e in u["errors"])
    assert not any("n" in c for c in u["chains"])
    assert sum(1 for e in u["errors"] if "stopped after" in e) == 1 and sum(1 for e in u["errors"] if "expiries" in e and "stopped" not in e) == 10      # one stop line, ten failure lines, nothing per remaining stock
    # one success resets the run: failures that are not consecutive never stop it
    ok = FakeClient(bad_expiries=tuple(f"STK{i:03d}" for i in range(0, 40, 2)))
    u2 = KU.build(ok, TODAY, say=lambda *a: None)
    assert sum(1 for c in u2["chains"] if "n" in c) == 20 and not any("stopped after" in e for e in u2["errors"])


def test_a_stock_name_the_relay_would_drop_from_a_chain_is_excluded_and_counted_here(monkeypatch):
    names = ("GOOD", "HAS.DOT", "X" * 25, "X" * 24)
    rows = [{"pSymbolName": n, "pInstType": "FUTSTK", "pAssetCode": 500 + i} for i, n in enumerate(names)]
    monkeypatch.setattr(KU, "scrip_master", lambda client, name="nse_fo": pd.DataFrame(rows))
    u = KU.build(FakeClient(), TODAY, say=lambda *a: None)
    chained = {c["u"] for c in u["chains"] if "n" in c}
    assert chained == {"GOOD", "X" * 24}                                                     # a dot or 25 characters would be dropped by the relay's chain rule: not sent
    assert any("2 F&O stocks have names the relay's chain rule does not accept" in e for e in u["errors"])        # counted, never named
    assert not any("not plain symbols" in e for e in u["errors"])                           # they are plain symbols: the relay takes them as quotes
    eq = {q["n"] for q in u["quotes"] if q["s"] == "eq"}
    fut = {q["n"] for q in u["quotes"] if q["s"] == "fut"}
    assert {"HAS.DOT", "X" * 25} <= eq and {"HAS.DOT-FUT", ("X" * 25) + "-FUT"} <= fut      # a name only the chain rule refuses keeps its spot and its future
