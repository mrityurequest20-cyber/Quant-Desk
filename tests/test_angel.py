"""The Angel One feed (docs/FEEDS.md): the automatic login (deploy/angel_autologin.py), the hand-off (deploy/angel-export.sh), the currency poller
(quantdesk/data/angel_feed.py) and the workflow. Angel One itself is never contacted: every answer is a local stand-in shaped as SmartAPI's own SDK
(smartapi-python 1.5.5) and its documentation describe them."""
import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import angel_autologin as AL  # noqa: E402
from quantdesk.data import angel_feed as A  # noqa: E402

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
ENV = {"ANGEL_API_KEY": "apikeyQ1w2", "ANGEL_CLIENT_CODE": "R123456", "ANGEL_MPIN": "8642", "ANGEL_TOTP_SECRET": "JBSWY3DPEHPK3PXP"}
JWT = "eyJhbGciOiJIUzUxMiJ9.SESSION-jwt_value.sig"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


class FakeLogin:
    def __init__(self, ok=True, bearer=False):
        self.calls, self.ok, self.bearer = [], ok, bearer

    def __call__(self, url, body, hdrs):
        self.calls.append((url, body, hdrs))
        if not self.ok:
            return 200, {"status": False, "message": "Invalid MPIN " + ENV["ANGEL_MPIN"], "errorcode": "AB1007", "data": None}
        return 200, {"status": True, "message": "SUCCESS", "errorcode": "", "data": {"jwtToken": ("Bearer " if self.bearer else "") + JWT,
                                                                                     "refreshToken": "R" * 40, "feedToken": "F" * 40}}


def _main(tmp_path, send, env=ENV, today=dt.date(2026, 11, 13)):
    out = tmp_path / "angel.json"
    return AL.main(["--out", str(out)], env=env, send=send, today=today), out


def test_totp_matches_the_rfc_6238_vectors():
    for t, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924")):
        assert AL.totp(RFC_SECRET, t) == code


def test_the_documented_login_with_client_code_mpin_and_totp(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(AL.time, "time", lambda: 1_700_000_010.0)
    fake = FakeLogin(bearer=True)
    rc, out = _main(tmp_path, fake)
    assert rc == 0 and len(fake.calls) == 1
    url, body, hdrs = fake.calls[0]
    assert url == "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
    assert body == {"clientcode": "R123456", "password": "8642", "totp": AL.totp(ENV["ANGEL_TOTP_SECRET"], 1_700_000_010.0)}
    assert hdrs["X-PrivateKey"] == "apikeyQ1w2" and hdrs["X-UserType"] == "USER" and hdrs["X-SourceID"] == "WEB"
    assert json.loads(out.read_text()) == {"jwt": JWT} and oct(out.stat().st_mode & 0o777) == "0o600"        # "Bearer " stripped; refresh and feed tokens not kept
    assert JWT not in capsys.readouterr().out


def test_a_refused_login_fails_once_and_never_shows_the_mpin_even_when_angel_one_echoes_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(AL.time, "time", lambda: 1_700_000_010.0)
    fake = FakeLogin(ok=False)
    rc, out = _main(tmp_path, fake)
    printed = capsys.readouterr().out
    assert rc == 1 and not out.exists() and len(fake.calls) == 1 and "8642" not in printed and "AB1007" in printed and "Invalid MPIN" in printed


def test_without_the_secrets_or_after_the_authority_ends_it_does_nothing_and_succeeds(tmp_path):
    fake = FakeLogin()
    rc, out = _main(tmp_path, fake, env={k: v for k, v in ENV.items() if k != "ANGEL_MPIN"})
    assert rc == 0 and not out.exists() and not fake.calls
    rc, out = _main(tmp_path, fake, today=dt.date(2027, 12, 31))
    assert rc == 0 and not out.exists() and not fake.calls


def test_a_code_about_to_expire_waits_for_the_next_window():
    clock, waits = [1_700_000_038.0], []
    AL.login("k", "c", "1", ENV["ANGEL_TOTP_SECRET"], send=FakeLogin(), now=lambda: clock[0], sleep=lambda s: (waits.append(s), clock.__setitem__(0, clock[0] + s)))
    assert waits and waits[0] >= 2


def test_it_sends_to_angel_ones_api_host_over_https_only():
    for url in ("http://apiconnect.angelone.in/x", "https://evil.example/x", "https://apiconnect.angelone.in.evil.example/x"):
        with pytest.raises(AL.LoginError):
            AL.post(url, {}, {})


def test_the_process_that_holds_the_mpin_imports_only_the_standard_library():
    mods = set()
    for node in ast.walk(ast.parse((ROOT / "deploy" / "angel_autologin.py").read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            mods.add(node.module.split(".")[0])
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}


def test_nothing_in_the_angel_code_can_trade_or_read_the_account():
    banned = re.compile(r"/order/|placeOrder|modifyOrder|cancelOrder|getPosition|convertPosition|getHolding|getRMS|getProfile|/rms/|gtt|logout", re.I)
    for f in ("deploy/angel_autologin.py", "quantdesk/data/angel_feed.py", "deploy/angel-export.sh", ".github/workflows/angel-feed.yml"):
        assert not banned.search((ROOT / f).read_text()), f


# ---------------------------------------------------------------------------------------------------------------- the contracts and the prices

MASTER = [
    {"token": "1165", "symbol": "USDINR26NOVFUT", "name": "USDINR", "expiry": "26NOV2026", "strike": "-1.000000", "lotsize": "1", "instrumenttype": "FUTCUR", "exch_seg": "CDS"},
    {"token": "1170", "symbol": "USDINR26DECFUT", "name": "USDINR", "expiry": "29DEC2026", "strike": "-1.000000", "lotsize": "1", "instrumenttype": "FUTCUR", "exch_seg": "CDS"},
    {"token": "1180", "symbol": "EURINR26OCTFUT", "name": "EURINR", "expiry": "28OCT2026", "strike": "-1.000000", "lotsize": "1", "instrumenttype": "FUTCUR", "exch_seg": "CDS"},
    {"token": "1181", "symbol": "EURINR26NOVFUT", "name": "EURINR", "expiry": "26NOV2026", "strike": "-1.000000", "lotsize": "1", "instrumenttype": "FUTCUR", "exch_seg": "CDS"},
    {"token": "1190", "symbol": "USDINR26NOV84CE", "name": "USDINR", "expiry": "26NOV2026", "strike": "84.0", "lotsize": "1", "instrumenttype": "OPTCUR", "exch_seg": "CDS"},
    {"token": "1200", "symbol": "763GS2032", "name": "763GS2032", "expiry": "26NOV2026", "strike": "-1", "lotsize": "1", "instrumenttype": "FUTIRC", "exch_seg": "CDS"},
    {"token": "4000", "symbol": "CRUDEOIL26NOVFUT", "name": "CRUDEOIL", "expiry": "19NOV2026", "strike": "-1", "lotsize": "100", "instrumenttype": "FUTCOM", "exch_seg": "MCX"},
]


def test_the_nearest_unexpired_currency_future_of_each_pair_under_the_desks_names():
    near = A.near_futures(A.parse_master(MASTER), dt.date(2026, 11, 13))
    assert {n: c["token"] for n, c in near.items()} == {"EURINR-CDS": "1181", "USDINR-CDS": "1165"}
    assert A.near_futures(A.parse_master(MASTER), dt.date(2026, 11, 27))["USDINR-CDS"]["token"] == "1170"


def _row(tok, ltp, bid=None, ask=None, vol=1000, oi=500):
    r = {"exchange": "CDS", "tradingSymbol": "X", "symbolToken": tok, "ltp": ltp, "tradeVolume": vol, "opnInterest": oi, "percentChange": 0.12,
         "exchFeedTime": "13-Nov-2026 10:46:10"}
    if bid is not None:
        r["depth"] = {"buy": [{"price": bid - i * 0.0025, "quantity": 100 + i, "orders": 3} for i in range(5)],
                      "sell": [{"price": ask + i * 0.0025, "quantity": 200, "orders": 2} for i in range(5)]}
    return r


def test_a_full_quote_gives_price_book_and_oi_in_one_answer():
    got, odd = A.parse_quote({"status": True, "data": {"fetched": [_row("1165", 84.51, 84.5075, 84.5125)], "unfetched": []}})
    q = got["1165"]
    assert odd == [] and q["ltp"] == 84.51 and q["vol"] == 1000 and q["oi"] == 500 and q["chg"] == 0.12 and q["t"] == "2026-11-13 10:46:10"
    assert q["bid"] == 84.5075 and q["ask"] == 84.5125 and q["bid_qty"] == 100 and len(q["d"]["b"]) == 5
    got, _ = A.parse_quote({"status": True, "data": {"fetched": [_row("1165", 84.51, 84.52, 84.50)]}})      # crossed: the price stands, the book does not
    assert "bid" not in got["1165"] and "d" not in got["1165"]


def test_an_answer_of_a_new_shape_or_an_error_is_reported_by_key_names_never_values():
    got, odd = A.parse_quote({"status": False, "message": "Invalid Token 99999", "errorcode": "AB1010", "data": None})
    assert got == {} and "AB1010" in odd[0] and "99999" not in odd[0]
    got, odd = A.parse_quote({"status": True, "data": {"fetched": [{"symbolToken": "1", "lastPrice": 84.51}]}})
    assert got == {} and "lastPrice" in odd[0] and "84.51" not in odd[0]


class FakeAPI:
    def __init__(self, rows, refuse_after=None):
        self.rows, self.calls, self.refuse_after = rows, [], refuse_after

    def quote(self, tokens):
        self.calls.append(list(tokens))
        if self.refuse_after is not None and len(self.calls) > self.refuse_after:
            raise A.Refused()
        return {"status": True, "data": {"fetched": [self.rows[t] for t in tokens if t in self.rows]}}


class FakePusher:
    def __init__(self):
        self.got, self.started, self.stopped = [], False, False

    def update(self, n, q):
        self.got.append((n, q))

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def stats(self):
        return {}


NAMES = {"USDINR-CDS": {"token": "1165"}, "EURINR-CDS": {"token": "1181"}}


def test_a_cycle_pushes_changed_quotes_once_as_currency():
    api, push = FakeAPI({"1165": _row("1165", 84.51, 84.5075, 84.5125), "1181": _row("1181", 97.2, 97.19, 97.21)}), FakePusher()
    feed = A.AngelFeed(api, NAMES, push)
    assert feed.cycle() == 2 and all(q["s"] == "cds" and "d" in q for _, q in push.got)
    assert feed.cycle() == 0                                                            # nothing moved: nothing pushed
    api.rows["1165"] = _row("1165", 84.52, 84.5175, 84.5225)
    assert feed.cycle() == 1 and push.got[-1][0] == "USDINR-CDS"


def test_tokens_go_fifty_a_call():
    names = {f"P{i}-CDS": {"token": str(1000 + i)} for i in range(75)}
    api = FakeAPI({})
    A.AngelFeed(api, names, FakePusher()).cycle()
    assert [len(c) for c in api.calls] == [50, 25]


def test_the_data_client_sends_smartapis_headers_and_full_mode_and_stops_on_429_and_a_refused_session():
    import urllib.error
    seen = []

    class R:
        def __init__(self, b):
            self.b = b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return self.b

    def opener(req, timeout=None):
        seen.append(req)
        if opener.mode == "429":
            raise urllib.error.HTTPError(req.full_url, 429, "x", {}, None)
        return R(json.dumps({"status": False, "message": "Invalid Token", "errorcode": "AG8001", "data": None}).encode())
    opener.mode = "refused"
    api = A.AngelData("apikeyQ1w2", JWT, opener=opener, limiter=A.Limiter(clock=lambda: 0.0, sleep=lambda s: None))
    with pytest.raises(A.Refused):
        api.quote(["1165"])
    req = seen[0]
    assert req.full_url == "https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote" and req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer " + JWT and req.get_header("X-privatekey") == "apikeyQ1w2"
    assert json.loads(req.data) == {"mode": "FULL", "exchangeTokens": {"CDS": ["1165"]}}
    opener.mode = "429"
    with pytest.raises(A.Blocked):
        api.quote(["1165"])


def test_the_feed_stops_at_the_currency_close_or_when_the_session_is_refused(monkeypatch):
    rows = {"1165": _row("1165", 84.51, 84.5075, 84.5125)}
    monkeypatch.setattr(A, "load_contracts", lambda opener=None: [])
    monkeypatch.setattr(A, "near_futures", lambda c, d: NAMES)
    clock = [dt.datetime(2026, 11, 13, 16, 59, tzinfo=IST)]
    step = lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=max(s, 5)))     # noqa: E731
    api = FakeAPI(rows)
    monkeypatch.setattr(A, "AngelData", lambda *a, **k: api)
    push = FakePusher()
    rep = A.run("23:00", "k", JWT, push, now=lambda: clock[0], sleep=step)
    assert rep["stopped"] == "until" and clock[0] <= dt.datetime(2026, 11, 13, 17, 5, 5, tzinfo=IST) and push.started and push.stopped
    clock[0] = dt.datetime(2026, 11, 13, 10, 0, tzinfo=IST)
    api2 = FakeAPI(rows, refuse_after=2)
    monkeypatch.setattr(A, "AngelData", lambda *a, **k: api2)
    rep = A.run("14:50", "k", JWT, FakePusher(), now=lambda: clock[0], sleep=step)
    assert rep["stopped"] == "Angel One refused today's session" and len(api2.calls) == 3


def test_angel_one_pushes_as_feed_a_and_the_routes_put_it_first_for_currency():
    from quantdesk.config import Config
    from quantdesk.data.live_push import PUSH_SOURCES
    assert "a" in PUSH_SOURCES and Config.load(ROOT / "config" / "quantdesk.yaml").get("feeds.routes")["cds"][0] == "a"


# ---------------------------------------------------------------------------------------------------------------- the hand-off and the workflow

def _export(tmp_path, content):
    rt = tmp_path / "rt"
    rt.mkdir(exist_ok=True)
    if content is not None:
        (rt / "angel.json").write_text(content)
    env_f = tmp_path / "env"
    env_f.write_text("")
    r = subprocess.run(["bash", str(ROOT / "deploy" / "angel-export.sh")], capture_output=True, text=True,
                       env={**os.environ, "RUNNER_TEMP": str(rt), "GITHUB_ENV": str(env_f)})
    return r, env_f.read_text(), rt


def test_the_session_is_handed_over_masked_and_the_file_is_deleted(tmp_path):
    r, env, rt = _export(tmp_path, json.dumps({"jwt": JWT}))
    assert r.returncode == 0 and env.strip() == f"ANGEL_DATA_TOKEN={JWT}" and f"::add-mask::{JWT}" in r.stdout and not (rt / "angel.json").exists()


def test_a_missing_or_malformed_session_hands_over_nothing_and_succeeds(tmp_path):
    for content in (None, "not json", json.dumps({"jwt": "x\nINJECTED=1"})):
        r, env, _ = _export(tmp_path, content)
        assert r.returncode == 0 and env == ""


WF = yaml.safe_load((ROOT / ".github" / "workflows" / "angel-feed.yml").read_text())


def test_the_mpin_and_totp_key_reach_only_the_login_steps_which_run_standard_library_python():
    holders = [(j, s) for j, job in WF["jobs"].items() for s in job["steps"] if "ANGEL_MPIN" in json.dumps(s) or "ANGEL_TOTP_SECRET" in json.dumps(s)]
    assert [j for j, _ in holders] == ["feed-1", "feed-2"]
    for _, s in holders:
        assert s["run"].startswith("/usr/bin/python3 -I -S deploy/angel_autologin.py") and "github.run_attempt == '1'" in s["if"]
        assert set(s["env"]) == {"ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_MPIN", "ANGEL_TOTP_SECRET"}


def test_the_workflow_only_reads_and_the_second_job_logs_in_only_after_the_first_did():
    assert WF["permissions"] == {"contents": "read", "actions": "read"}
    for job in WF["jobs"].values():
        assert "permissions" not in job and int(job["timeout-minutes"]) <= 358
        assert next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))["with"]["persist-credentials"] is False
    assert WF["jobs"]["feed-2"]["if"] == "always() && needs.feed-1.outputs.login == 'success'"
    gate = next(s for s in WF["jobs"]["feed-1"]["steps"] if s.get("id") == "gate")
    assert gate["env"]["GATE_WORKFLOW"] == "angel-feed.yml"


def test_the_gate_and_the_watchdog_know_the_angel_one_feed(monkeypatch):
    import importlib
    import kite_login_gate as G
    monkeypatch.setenv("GATE_WORKFLOW", "angel-feed.yml")
    assert importlib.reload(G).WORKFLOW == "angel-feed.yml"
    monkeypatch.delenv("GATE_WORKFLOW")
    importlib.reload(G)
    wd = (ROOT / "deploy" / "cloudflare" / "watchdog.js").read_text()
    assert '{ at: "09:40", days: "trading", run: ranToday("angel-feed.yml", "Angel One feed (currency)", "P2", "W20"), check: "W20" }' in wd
