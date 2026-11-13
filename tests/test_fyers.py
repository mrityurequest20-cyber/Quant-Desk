"""The Fyers feed (docs/FEEDS.md): the automatic login (deploy/fyers_autologin.py), the token store (deploy/fyers-token.sh), the MCX and currency poller
(quantdesk/data/fyers_feed.py) and the workflow that runs them. Fyers itself is never contacted: every answer is a local stand-in, shaped as Fyers' SDK
(fyers_apiv3 3.2.1) and its documentation describe them."""
import ast
import datetime as dt
import hashlib
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
import fyers_autologin as FA  # noqa: E402
from quantdesk.data import fyers_feed as F  # noqa: E402

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
ENV = {"FYERS_APP_ID": "ABCD1234-100", "FYERS_SECRET_ID": "app-secret-XYZ", "FYERS_REDIRECT_URI": "https://example.org/cb", "FYERS_CLIENT_ID": "XY01234",
       "FYERS_PIN": "4321", "FYERS_TOTP_SECRET": "JBSWY3DPEHPK3PXP"}
ACCESS = "eyJhbGciOiJIUzI1NiJ9.ACCESS-token_value.sig"
REFRESH = "eyJhbGciOiJIUzI1NiJ9.REFRESH-token_value.sig"
SESSION = "eyJhbGciOiJIUzI1NiJ9.SESSION-token_value.sig"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------------------------------------------- the login

class FakeFyers:
    """Answers the five login calls and the refresh call. `refuse` names the calls that fail."""

    def __init__(self, refuse=(), v3_token=True):
        self.calls, self.refuse, self.v3_token = [], set(refuse), v3_token

    def __call__(self, url, body, bearer=None):
        self.calls.append((url, body, bearer))
        name = url.rsplit("/", 1)[-1]
        if name in self.refuse:
            return 400, {"s": "error", "code": -1001, "message": "Invalid pin " + ENV["FYERS_PIN"] + " " + "x" * 40}     # a careless echo: must not reach a log
        if name == "validate-refresh-token":
            return 200, {"s": "ok", "code": 200, "message": "", "access_token": ACCESS}
        if name == "send_login_otp_v2":
            return 200, {"s": "ok", "code": 200, "request_key": "RK1"}
        if name == "verify_otp":
            return 200, {"s": "ok", "code": 200, "request_key": "RK2"}
        if name == "verify_pin_v2":
            return 200, {"s": "ok", "code": 200, "data": {"access_token": SESSION}}
        if name == "token":
            if "api-t1" in url and not self.v3_token:
                return 404, {"s": "error", "code": 404, "message": "not found"}
            return 308, {"s": "ok", "code": 308, "Url": "https://example.org/cb?s=ok&code=200&auth_code=AUTHCODE123456789012345&state=quantdesk"}
        if name == "validate-authcode":
            return 200, {"s": "ok", "code": 200, "access_token": ACCESS, "refresh_token": REFRESH}
        return 404, {}


def _run(tmp_path, send, refresh=None, env=ENV, today=dt.date(2026, 11, 13)):
    out = tmp_path / "login.json"
    args = ["--out", str(out)]
    if refresh is not None:
        (tmp_path / "refresh").write_text(refresh)
        args += ["--refresh-in", str(tmp_path / "refresh")]
    return FA.main(args, env=env, send=send, today=today), out


def test_totp_matches_the_rfc_6238_vectors():
    for t, code in ((59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")):
        assert FA.totp(RFC_SECRET, t) == code
    assert FA.totp("gezd gnbv gy3t qojq gezd gnbv gy3t qojq", 59) == "287082"


def test_the_app_hash_is_sha256_of_app_id_colon_secret_as_fyers_own_sdk_computes_it():
    assert FA.app_hash("ABCD1234-100", "s") == hashlib.sha256(b"ABCD1234-100:s").hexdigest()


def test_a_stored_refresh_token_and_the_pin_are_enough_on_most_days(tmp_path, capsys):
    fake = FakeFyers()
    rc, out = _run(tmp_path, fake, refresh=REFRESH)
    assert rc == 0 and [c[0].rsplit("/", 1)[-1] for c in fake.calls] == ["validate-refresh-token"]
    url, body, _ = fake.calls[0]
    assert url == "https://api-t1.fyers.in/api/v3/validate-refresh-token"
    assert body == {"grant_type": "refresh_token", "appIdHash": FA.app_hash(ENV["FYERS_APP_ID"], ENV["FYERS_SECRET_ID"]), "refresh_token": REFRESH, "pin": "4321"}
    assert json.loads(out.read_text()) == {"access": ACCESS, "refresh": REFRESH, "how": "refresh"}
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    printed = capsys.readouterr().out
    assert ACCESS not in printed and REFRESH not in printed


def test_a_refused_refresh_token_falls_back_to_the_full_totp_login_once(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(FA.time, "time", lambda: 1_700_000_010.0)                    # 20 s left in the TOTP window: no wait
    fake = FakeFyers(refuse={"validate-refresh-token"})
    rc, out = _run(tmp_path, fake, refresh=REFRESH)
    names = [c[0].rsplit("/", 1)[-1] for c in fake.calls]
    assert rc == 0 and names == ["validate-refresh-token", "send_login_otp_v2", "verify_otp", "verify_pin_v2", "token", "validate-authcode"]
    by = {c[0].rsplit("/", 1)[-1]: c for c in fake.calls}
    assert by["send_login_otp_v2"][1] == {"fy_id": "WFkwMTIzNA==", "app_id": "2"}                                       # base64 of the client id
    assert by["verify_otp"][1] == {"request_key": "RK1", "otp": FA.totp(ENV["FYERS_TOTP_SECRET"], 1_700_000_010.0)}
    assert by["verify_pin_v2"][1] == {"request_key": "RK2", "identity_type": "pin", "identifier": "NDMyMQ=="}           # base64 of the PIN
    url, body, bearer = by["token"]
    assert url == "https://api-t1.fyers.in/api/v3/token" and bearer == SESSION
    assert body["fyers_id"] == "XY01234" and body["app_id"] == "ABCD1234" and body["appType"] == "100" and body["redirect_uri"] == ENV["FYERS_REDIRECT_URI"]
    assert by["validate-authcode"][1] == {"grant_type": "authorization_code", "appIdHash": FA.app_hash("ABCD1234-100", "app-secret-XYZ"), "code": "AUTHCODE123456789012345"}
    assert json.loads(out.read_text()) == {"access": ACCESS, "refresh": REFRESH, "how": "totp"}
    printed = capsys.readouterr().out
    assert "4321" not in printed and "x" * 25 not in printed                           # Fyers' message is cleaned: the PIN it echoed and the long run are gone


def test_without_a_refresh_token_it_logs_in_with_totp_and_the_older_token_host_is_the_second_way(tmp_path, monkeypatch):
    monkeypatch.setattr(FA.time, "time", lambda: 1_700_000_010.0)
    fake = FakeFyers(v3_token=False)
    rc, out = _run(tmp_path, fake)
    assert rc == 0 and [c[0] for c in fake.calls if c[0].endswith("/token")] == list(FA.TOKEN_URLS)
    assert json.loads(out.read_text())["how"] == "totp"


def test_a_code_about_to_expire_is_not_sent_it_waits_for_the_next_window(monkeypatch):
    clock = [1_700_000_038.0]                                                           # 1700000038 % 30 = 28: 2 s left
    waits = []
    fake = FakeFyers()
    FA.totp_login("A-100", "s", "C", "1", ENV["FYERS_TOTP_SECRET"], "https://x", send=fake, now=lambda: clock[0],
                  sleep=lambda s: (waits.append(s), clock.__setitem__(0, clock[0] + s)))
    assert waits and waits[0] >= 2


def test_a_wrong_pin_fails_once_and_says_which_secret_to_check_without_showing_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(FA.time, "time", lambda: 1_700_000_010.0)
    fake = FakeFyers(refuse={"verify_pin_v2"})
    rc, out = _run(tmp_path, fake)
    printed = capsys.readouterr().out
    assert rc == 1 and not out.exists() and "FYERS_PIN" in printed and "4321" not in printed
    assert sum(1 for c in fake.calls if c[0].endswith("verify_pin_v2")) == 1


def test_without_the_secrets_or_after_the_authority_ends_it_does_nothing_and_succeeds(tmp_path, capsys):
    fake = FakeFyers()
    rc, out = _run(tmp_path, fake, env={k: v for k, v in ENV.items() if k != "FYERS_PIN"})
    assert rc == 0 and not out.exists() and not fake.calls and "FYERS_PIN" in capsys.readouterr().out
    rc, out = _run(tmp_path, fake, today=dt.date(2027, 12, 31))
    assert rc == 0 and not out.exists() and not fake.calls


def test_a_totp_key_that_is_not_base32_is_named_not_tried(tmp_path, capsys):
    fake = FakeFyers()
    rc, _ = _run(tmp_path, fake, env={**ENV, "FYERS_TOTP_SECRET": "not base32 !!1"})
    assert rc == 1 and not fake.calls and "FYERS_TOTP_SECRET" in capsys.readouterr().out


def test_it_sends_to_fyers_api_hosts_over_https_only():
    for url in ("http://api-t1.fyers.in/api/v3/x", "https://evil.example/api/v3/x", "https://api-t1.fyers.in.evil.example/x"):
        with pytest.raises(FA.LoginError):
            FA.post(url, {})


def _imports(path: Path) -> set:
    mods = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods


def test_the_process_that_holds_the_pin_imports_only_the_standard_library():
    mods = _imports(ROOT / "deploy" / "fyers_autologin.py")
    assert mods <= set(sys.stdlib_module_names) | {"__future__"}, mods - set(sys.stdlib_module_names)


def test_nothing_in_the_fyers_code_can_trade_or_read_the_account():
    banned = re.compile(r"/(orders?|positions|holdings|funds|profile|tradebook|multi-order|multileg|gtt|logout|convert)\b|place_order|exit_positions")
    for f in ("deploy/fyers_autologin.py", "quantdesk/data/fyers_feed.py", "deploy/fyers-token.sh", ".github/workflows/fyers-feed.yml"):
        assert not banned.search((ROOT / f).read_text()), f
    with pytest.raises(ValueError):
        F.FyersData("A-100", "t").get("/orders", {})


# ---------------------------------------------------------------------------------------------------------------- the contracts

def _epoch(d: str, hh=23, mm=30) -> str:
    y, m, dd = map(int, d.split("-"))
    return str(int(dt.datetime(y, m, dd, hh, mm, tzinfo=IST).timestamp()))


MCX_JSON = {
    "MCX:CRUDEOIL26NOVFUT": {"symTicker": "MCX:CRUDEOIL26NOVFUT", "underSym": "CRUDEOIL", "expiryDate": _epoch("2026-11-19")},
    "MCX:CRUDEOIL26DECFUT": {"symTicker": "MCX:CRUDEOIL26DECFUT", "underSym": "CRUDEOIL", "expiryDate": _epoch("2026-12-17")},
    "MCX:CRUDEOILM26NOVFUT": {"symTicker": "MCX:CRUDEOILM26NOVFUT", "underSym": "CRUDEOILM", "expiryDate": _epoch("2026-11-19")},
    "MCX:GOLD26NOVFUT": {"symTicker": "MCX:GOLD26NOVFUT", "underSym": "GOLD", "expiryDate": _epoch("2026-11-12")},          # expired yesterday
    "MCX:GOLD26DECFUT": {"symTicker": "MCX:GOLD26DECFUT", "underSym": "GOLD", "expiryDate": _epoch("2026-12-04")},
    "MCX:CRUDEOIL26NOV5800CE": {"symTicker": "MCX:CRUDEOIL26NOV5800CE", "underSym": "CRUDEOIL", "expiryDate": _epoch("2026-11-17")},   # an option: not a future
}
CDS_CSV = "\n".join([
    f"101,USDINR 26 Nov FUT,0,1,0.0025,,0900-1700|,2026-11-12,{_epoch('2026-11-26', 12, 15)},NSE:USDINR26NOVFUT,12,13,1001,USDINR,",
    f"102,USDINR 26 Dec FUT,0,1,0.0025,,0900-1700|,2026-11-12,{_epoch('2026-12-29', 12, 15)},NSE:USDINR26DECFUT,12,13,1002,USDINR,",
    f"103,EURINR 26 Nov FUT,0,1,0.0025,,0900-1700|,2026-11-12,{_epoch('2026-11-26', 12, 15)},NSE:EURINR26NOVFUT,12,13,1003,EURINR,",
    f"104,GS 2032 FUT,1,1,0.0025,,0900-1700|,2026-11-12,{_epoch('2026-11-26', 12, 15)},NSE:763GS203226NOVFUT,12,13,1004,763GS2032,",     # an interest-rate future: not a currency
])


def test_the_nearest_unexpired_future_of_each_commodity_and_currency_under_the_desks_names():
    c = F.parse_master_json("mcx", MCX_JSON) + F.parse_master_csv("cds", CDS_CSV)
    near = F.near_futures(c, dt.date(2026, 11, 13))
    assert {n: x["ticker"] for n, x in near.items()} == {
        "CRUDEOIL-MCX": "MCX:CRUDEOIL26NOVFUT", "CRUDEOILM-MCX": "MCX:CRUDEOILM26NOVFUT", "GOLD-MCX": "MCX:GOLD26DECFUT",
        "EURINR-CDS": "NSE:EURINR26NOVFUT", "USDINR-CDS": "NSE:USDINR26NOVFUT"}
    assert F.near_futures(c, dt.date(2026, 11, 19))["CRUDEOIL-MCX"]["ticker"] == "MCX:CRUDEOIL26NOVFUT"        # expiry day still counts, as in Kite's rule
    assert F.near_futures(c, dt.date(2026, 11, 20))["CRUDEOIL-MCX"]["ticker"] == "MCX:CRUDEOIL26DECFUT"


def test_the_master_is_read_from_fyers_hosts_only_and_the_csv_is_the_second_way():
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
        seen.append(req.full_url)
        if req.full_url.endswith(".json"):
            raise OSError("404")
        return R(CDS_CSV.encode() if "NSE_CD" in req.full_url else b"")
    got, notes = F.load_contracts(opener)
    assert {c["under"] for c in got} == {"USDINR", "EURINR"} and any("mcx" in n for n in notes)
    assert all(u.startswith("https://public.fyers.in/") for u in seen)
    with pytest.raises(ValueError):
        F.fetch_text("https://example.org/x.json", opener)


# ---------------------------------------------------------------------------------------------------------------- the prices

def _quote(n, lp, bid=None, ask=None, vol=1000, chp=0.5, tt=None):
    v = {"lp": lp, "volume": vol, "chp": chp, "tt": tt or _epoch("2026-11-13", 10, 0)}
    if bid is not None:
        v.update(bid=bid, ask=ask)
    return {"n": n, "s": "ok", "v": v}


def test_quotes_become_the_relays_display_fields():
    obj = {"s": "ok", "d": [_quote("MCX:CRUDEOIL26NOVFUT", 5812.0, 5811.0, 5813.0), _quote("MCX:GOLD26DECFUT", 77000.0, 77010.0, 77005.0),
                            {"n": "MCX:X", "s": "error", "v": {"errmsg": "invalid"}}]}
    got, odd = F.parse_quotes(obj)
    assert got["MCX:CRUDEOIL26NOVFUT"] == {"ltp": 5812.0, "bid": 5811.0, "ask": 5813.0, "vol": 1000.0, "chg": 0.5, "t": "2026-11-13 10:00:00"}
    assert "bid" not in got["MCX:GOLD26DECFUT"] and got["MCX:GOLD26DECFUT"]["ltp"] == 77000.0        # a crossed quote keeps its price, not its book
    assert "MCX:X" not in got and odd == []


def test_an_answer_of_a_new_shape_is_reported_by_its_key_names_never_its_values():
    got, odd = F.parse_quotes({"s": "ok", "d": [{"n": "MCX:A", "s": "ok", "v": {"last": 5812.5, "secret_number": 1234567}}]})
    assert got == {} and odd and "last" in odd[0] and "5812" not in " ".join(odd) and "1234567" not in " ".join(odd)
    got, odd = F.parse_quotes({"data": []})
    assert got == {} and "data" in odd[0]


def test_depth_gives_five_levels_a_side_and_the_open_interest():
    t = "MCX:CRUDEOIL26NOVFUT"
    rec = {"bids": [{"price": 5811 - i, "volume": 10 + i, "ord": 2} for i in range(6)], "ask": [{"price": 5813 + i, "volume": 20, "ord": 1} for i in range(5)],
           "oi": 12345, "ltp": 5812}
    book, odd = F.parse_depth({"s": "ok", "d": {t: rec}}, t)
    assert odd == [] and book["bid"] == 5811 and book["ask"] == 5813 and book["bid_qty"] == 10 and book["oi"] == 12345
    assert len(book["d"]["b"]) == 5 and book["d"]["a"][0] == [5813, 20, 1]
    book, _ = F.parse_depth({"d": {t: {**rec, "asks": rec["ask"], "ask": None}}}, t)                  # the plural spelling works too
    assert book["ask"] == 5813
    book, odd = F.parse_depth({"d": {t: {"buy": [], "oi": 5}}}, t)
    assert "bid" not in book and odd and "buy" in odd[0]


class FakeAPI:
    def __init__(self, prices, block_after=None):
        self.prices, self.calls, self.block_after = prices, [], block_after

    def get(self, path, params):
        self.calls.append((path, dict(params)))
        if self.block_after is not None and len(self.calls) > self.block_after:
            raise F.Blocked()
        if path == "/options-chain-v3":
            return CHAIN.get(params["symbol"], {"s": "ok", "data": {"expiryData": [], "optionsChain": []}})
        if path == "/quotes":
            return {"s": "ok", "d": [_quote(t, *self.prices[t]) for t in params["symbols"].split(",") if t in self.prices]}
        t = params["symbol"]
        lp, bid, ask = self.prices[t]
        return {"s": "ok", "d": {t: {"bids": [{"price": bid, "volume": 5, "ord": 1}], "ask": [{"price": ask, "volume": 7, "ord": 1}], "oi": 99}}}


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
        return {"pushes_ok": 1}


def _chain_row(k, t, ltp, bid, ask, oi):
    return {"strike_price": k, "option_type": t, "ltp": ltp, "bid": bid, "ask": ask, "oi": oi, "volume": 1200, "ltpchp": 1.5, "symbol": f"X{k}{t}"}


CHAIN = {
    "MCX:CRUDEOIL26NOVFUT": {"s": "ok", "code": 200, "data": {"expiryData": [{"date": "17-11-2026", "expiry": _epoch("2026-11-17", 23, 30)}],
                             "optionsChain": [{"strike_price": -1, "option_type": "", "ltp": 5812.0, "symbol": "MCX:CRUDEOIL26NOVFUT"},
                                              _chain_row(5800, "CE", 92.0, 91.5, 92.5, 4400), _chain_row(5800, "PE", 80.0, 79.5, 80.5, 3900),
                                              _chain_row(5850, "CE", 70.0, 70.5, 70.0, 100)]}},                     # a crossed book: price kept, book dropped
    "NSE:USDINR26NOVFUT": {"s": "ok", "code": 200, "data": {"expiryData": [{"date": "20-11-2026", "expiry": _epoch("2026-11-20", 12, 30)}],
                           "optionsChain": [_chain_row(84.25, "PE", 0.0425, 0.04, 0.045, 90000), _chain_row(84.5, "CE", 0.11, 0.1075, 0.1125, 150000)]}},
}


NAMES = {"CRUDEOIL-MCX": {"seg": "mcx", "ticker": "MCX:CRUDEOIL26NOVFUT", "expiry": dt.date(2026, 11, 19)}, "GOLD-MCX": {"seg": "mcx", "ticker": "MCX:GOLD26DECFUT", "expiry": dt.date(2026, 12, 4)},
         "USDINR-CDS": {"seg": "cds", "ticker": "NSE:USDINR26NOVFUT", "expiry": dt.date(2026, 11, 26)}}
PRICES = {"MCX:CRUDEOIL26NOVFUT": (5812.0, 5811.0, 5813.0), "MCX:GOLD26DECFUT": (77000.0, 76990.0, 77010.0), "NSE:USDINR26NOVFUT": (84.5, 84.4975, 84.5025)}


def test_a_cycle_pushes_each_changed_quote_once_with_its_segment_and_book():
    api, push = FakeAPI(dict(PRICES)), FakePusher()
    feed = F.FyersFeed(api, NAMES, ["CRUDEOIL-MCX", "USDINR-CDS", "SILVER-MCX"], push, depth_per_cycle=1, now=lambda: dt.datetime(2026, 11, 13, 10, 0, tzinfo=IST))
    assert feed.cycle() == 3
    q = dict(push.got)
    assert q["CRUDEOIL-MCX"]["e"] == "2026-11-19" and q["USDINR-CDS"]["e"] == "2026-11-26"          # the contract each name holds, for the paper desk
    assert q["CRUDEOIL-MCX"]["s"] == "mcx" and q["USDINR-CDS"]["s"] == "cds" and q["CRUDEOIL-MCX"]["oi"] == 99 and q["CRUDEOIL-MCX"]["d"]["b"] == [[5811.0, 5, 1]]
    assert "d" not in q["GOLD-MCX"]                                                     # not on the watchlist: price only
    assert [p for p, _ in api.calls if p != "/options-chain-v3"] == ["/quotes", "/depth"] and api.calls[0][1]["symbols"].count(",") == 2
    push.got.clear()
    assert feed.cycle() == 1 and push.got[0][0] == "USDINR-CDS"                         # nothing moved but USDINR's book arrived (the depth turn moved on)
    push.got.clear()
    assert feed.cycle() == 0                                                             # nothing changed: nothing pushed, so the app sees an ageing price
    api.prices["MCX:GOLD26DECFUT"] = (77005.0, 76995.0, 77015.0)
    assert feed.cycle() == 1 and push.got[-1][0] == "GOLD-MCX"


def test_currency_is_not_polled_after_its_close_but_mcx_is_until_midnight():
    api, push = FakeAPI(dict(PRICES)), FakePusher()
    feed = F.FyersFeed(api, NAMES, [], push, now=lambda: dt.datetime(2026, 11, 13, 21, 0, tzinfo=IST))
    feed.cycle()
    assert "NSE:USDINR26NOVFUT" not in api.calls[0][1]["symbols"] and {n for n, _ in push.got} == {"CRUDEOIL-MCX", "GOLD-MCX"}


def test_quotes_go_fifty_symbols_a_call():
    names = {f"X{i}-MCX": {"seg": "mcx", "ticker": f"MCX:X{i}26NOVFUT", "expiry": dt.date(2026, 11, 19)} for i in range(120)}
    api = FakeAPI({c["ticker"]: (1.0, 0.9, 1.1) for c in names.values()})
    F.FyersFeed(api, names, [], FakePusher(), now=lambda: dt.datetime(2026, 11, 13, 10, 0, tzinfo=IST)).cycle()
    assert [len(p["symbols"].split(",")) for path, p in api.calls if path == "/quotes"] == [50, 50, 20]


def test_the_limiter_keeps_well_under_fyers_caps():
    clock = [0.0]
    lim = F.Limiter(per_second=5, per_minute=100, clock=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))
    for _ in range(250):
        lim.wait()
    assert clock[0] >= 120                                                              # 250 calls at 100 a minute take two minutes at least
    stamps = list(lim.calls)
    assert all(sum(1 for t in stamps if a <= t < a + 1) <= 5 for a in stamps)
    assert F.PER_MINUTE <= 100 and F.PER_SECOND <= 5


def test_a_429_stops_the_feed_for_the_day_and_the_pusher_is_stopped(monkeypatch):
    clock = [dt.datetime(2026, 11, 13, 10, 0, tzinfo=IST)]
    api = FakeAPI(dict(PRICES), block_after=3)
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: NAMES)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    push = FakePusher()
    rep = F.run("23:58", "A-100", "t", push, now=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=max(s, 5))))
    assert rep["stopped"].startswith("blocked") and push.started and push.stopped and len(api.calls) == 4


def test_the_data_client_sends_fyers_header_and_turns_429_and_401_into_stops():
    import urllib.error
    seen = []

    def opener(req, timeout=None):
        seen.append(req)
        raise urllib.error.HTTPError(req.full_url, opener.code, "x", {}, None)
    opener.code = 429
    api = F.FyersData("ABCD1234-100", "TOKEN", opener=opener, limiter=F.Limiter(clock=lambda: 0.0, sleep=lambda s: None))
    with pytest.raises(F.Blocked):
        api.get("/quotes", {"symbols": "MCX:A"})
    assert seen[0].full_url.startswith("https://api-t1.fyers.in/data/quotes?") and seen[0].get_header("Authorization") == "ABCD1234-100:TOKEN"
    opener.code = 401
    with pytest.raises(F.Refused):
        api.get("/depth", {"symbol": "MCX:A", "ohlcv_flag": 1})


def test_the_watchlists_commodities_and_currencies_get_the_depth():
    assert F.depth_watch({"commodities": ["CRUDEOIL", "gold"], "currencies": ["USDINR"], "stocks": ["SBIN"]}) == ["CRUDEOIL-MCX", "GOLD-MCX", "USDINR-CDS"]


def test_fyers_pushes_as_feed_f_and_the_routes_put_it_first_for_mcx():
    from quantdesk.config import Config
    from quantdesk.data.live_push import PUSH_SOURCES
    assert "f" in PUSH_SOURCES
    cfg = Config.load(ROOT / "config" / "quantdesk.yaml")
    assert cfg.get("feeds.routes")["mcx"][0] == "f" and "f" in cfg.get("feeds.routes")["cds"]


# ---------------------------------------------------------------------------------------------------------------- the workflow and the token store

WF = yaml.safe_load((ROOT / ".github" / "workflows" / "fyers-feed.yml").read_text())


def test_the_pin_and_totp_key_reach_the_one_login_step_and_it_runs_standard_library_python():
    holders = [(j, s) for j, job in WF["jobs"].items() for s in job["steps"] if "FYERS_PIN" in json.dumps(s) or "FYERS_TOTP_SECRET" in json.dumps(s)]
    assert [(j, s["name"]) for j, s in holders] == [("token", holders[0][1]["name"])] and "Log in" in holders[0][1]["name"]
    step = holders[0][1]
    assert step["run"].startswith("/usr/bin/python3 -I -S deploy/fyers_autologin.py") and "GH_TOKEN" not in step["env"]
    assert "github.run_attempt == '1'" in step["if"] and "steps.gate.outputs.first == 'true'" in step["if"]
    gate = next(s for s in WF["jobs"]["token"]["steps"] if s.get("id") == "gate")
    assert gate["env"]["GATE_WORKFLOW"] == "fyers-feed.yml"


def test_only_the_token_job_may_write_and_no_job_keeps_git_credentials():
    assert WF["permissions"] == {"contents": "read"} and WF["jobs"]["token"]["permissions"]["contents"] == "write"
    for name, job in WF["jobs"].items():
        assert int(job["timeout-minutes"]) <= 358
        if name != "token":
            assert "permissions" not in job
        co = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@"))
        assert co["with"]["persist-credentials"] is False


def test_the_gate_counts_the_fyers_workflows_runs_when_asked(monkeypatch):
    import importlib
    import kite_login_gate as G
    monkeypatch.setenv("GATE_WORKFLOW", "fyers-feed.yml")
    assert importlib.reload(G).WORKFLOW == "fyers-feed.yml"
    monkeypatch.setenv("GATE_WORKFLOW", "something-else.yml")
    assert importlib.reload(G).WORKFLOW == "kite-record.yml"
    monkeypatch.delenv("GATE_WORKFLOW")
    assert importlib.reload(G).WORKFLOW == "kite-record.yml"


def _git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def _origin_with(tmp_path, payload: dict, key: str) -> Path:
    origin, seed = tmp_path / "origin.git", tmp_path / "seed"
    _git("init", "-q", "--bare", str(origin), cwd=tmp_path)
    seed.mkdir()
    _git("init", "-q", cwd=seed)
    _git("checkout", "-q", "-b", "fyers-token", cwd=seed)
    (seed / "p.json").write_text(json.dumps(payload))
    subprocess.run(["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-in", "p.json", "-out", "fyers_token.enc", "-pass", "env:K"], cwd=seed, check=True, env={**os.environ, "K": key})
    (seed / "p.json").unlink()
    _git("add", "fyers_token.enc", cwd=seed)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "t", cwd=seed)
    _git("push", "-q", str(origin), "fyers-token", cwd=seed)
    work = tmp_path / "work"
    _git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    return work


def _script(work, tmp_path, mode, key):
    run_tmp = tmp_path / "rt"
    run_tmp.mkdir(exist_ok=True)
    env_f, out_f = tmp_path / "env", tmp_path / "out"
    env_f.write_text(""), out_f.write_text("")
    r = subprocess.run(["bash", str(ROOT / "deploy" / "fyers-token.sh"), mode], cwd=work, capture_output=True, text=True,
                       env={**os.environ, "FYERS_SECRET_ID": key, "RUNNER_TEMP": str(run_tmp), "GITHUB_ENV": str(env_f), "GITHUB_OUTPUT": str(out_f)})
    return r, env_f.read_text(), out_f.read_text(), run_tmp


def test_todays_stored_token_is_exported_masked_and_the_refresh_token_is_handed_to_the_login(tmp_path):
    today = dt.datetime.now(IST).date().isoformat()
    work = _origin_with(tmp_path, {"day": today, "access": ACCESS, "refresh": REFRESH}, "k1")
    r, env, _, _ = _script(work, tmp_path, "export", "k1")
    assert r.returncode == 0 and env.strip() == f"FYERS_DATA_TOKEN={ACCESS}" and f"::add-mask::{ACCESS}" in r.stdout
    assert ACCESS not in r.stdout.replace(f"::add-mask::{ACCESS}", "")
    r, _, out, rt = _script(work, tmp_path, "load", "k1")
    assert "today=true" in out and (rt / "fyers_refresh").read_text() == REFRESH and oct((rt / "fyers_refresh").stat().st_mode & 0o777) == "0o600"


def test_yesterdays_token_or_a_wrong_key_exports_nothing_and_still_succeeds(tmp_path):
    work = _origin_with(tmp_path, {"day": "2020-01-01", "access": ACCESS, "refresh": REFRESH}, "k1")
    r, env, _, _ = _script(work, tmp_path, "export", "k1")
    assert r.returncode == 0 and env == ""
    r, _, out, rt = _script(work, tmp_path, "load", "k1")
    assert "today=false" in out and (rt / "fyers_refresh").read_text() == REFRESH          # the refresh token is still good for a cheap login
    r, env, _, _ = _script(work, tmp_path, "export", "wrong-key")
    assert r.returncode == 0 and env == ""


def test_the_watchdog_says_when_the_fyers_feed_did_not_run_or_failed_morning_and_evening():
    wd = (ROOT / "deploy" / "cloudflare" / "watchdog.js").read_text()
    for at in ("09:40", "20:30"):
        assert f'{{ at: "{at}", days: "trading", run: ranToday("fyers-feed.yml", "Fyers feed (MCX, currency)", "P2", "W19"), check: "W19" }}' in wd


def test_a_ladder_is_sent_only_in_the_cycle_it_was_read_so_it_is_never_older_than_it_looks():
    api, push = FakeAPI(dict(PRICES)), FakePusher()
    feed = F.FyersFeed(api, NAMES, ["CRUDEOIL-MCX", "USDINR-CDS"], push, depth_per_cycle=1, now=lambda: dt.datetime(2026, 11, 13, 10, 0, tzinfo=IST))
    feed.cycle()
    assert "d" in dict(push.got)["CRUDEOIL-MCX"]
    push.got.clear()
    api.prices["MCX:CRUDEOIL26NOVFUT"] = (5820.0, 5819.0, 5821.0)                     # crude moves; this cycle's depth turn is USDINR's
    feed.cycle()
    q = dict(push.got)["CRUDEOIL-MCX"]
    assert "d" not in q and q["bid"] == 5819.0 and q["oi"] == 99                       # the fresh quote's bid/offer, the last OI, and no stale ladder (the relay keeps the old one with its age)



def test_option_chains_arrive_under_the_desks_option_names_with_bid_offer_and_oi():
    api, push = FakeAPI(dict(PRICES)), FakePusher()
    feed = F.FyersFeed(api, NAMES, ["CRUDEOIL-MCX", "USDINR-CDS"], push, depth_per_cycle=0, now=lambda: dt.datetime(2026, 11, 13, 10, 0, tzinfo=IST))
    feed.cycle()
    got = dict(push.got)
    assert got["CRUDEOIL17NOV265800CE"] == {"ltp": 92.0, "bid": 91.5, "ask": 92.5, "oi": 4400, "vol": 1200, "chg": 1.5, "s": "mopt"}          # an MCX option: Fyers' route
    assert got["USDINR20NOV2684.5CE"]["s"] == "copt"                                                                                       # a currency option: Angel One's route
    assert "bid" not in got["CRUDEOIL17NOV265850CE"] and got["CRUDEOIL17NOV265850CE"]["ltp"] == 70.0
    assert got["USDINR20NOV2684.25PE"]["bid"] == 0.04 and got["USDINR20NOV2684.5CE"]["oi"] == 150000      # decimal strikes, named as Kite names them
    assert [p["symbol"] for path, p in api.calls if path == "/options-chain-v3"] == ["MCX:CRUDEOIL26NOVFUT", "NSE:USDINR26NOVFUT"]
    push.got.clear()
    feed.cycle()
    assert not [n for n, _ in push.got if n.endswith(("CE", "PE"))]                             # nothing moved: no option pushed again


def test_an_unreadable_chain_is_reported_by_its_key_names():
    got, odd = F.parse_chain({"s": "ok", "data": {"chain": [1, 2]}}, "CRUDEOIL")
    assert got == {} and "chain" in odd[0]
    assert F.option_name("USDINR", dt.date(2026, 11, 20), 84.5, "CE") == "USDINR20NOV2684.5CE" and F.option_name("GOLD", dt.date(2026, 11, 25), 136000.0, "PE") == "GOLD25NOV26136000PE"
