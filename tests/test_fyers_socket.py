"""Fyers' Data Socket (quantdesk/data/fyers_socket.py; docs/FEEDS.md): the futures' quotes streamed, so they spend none of the data API's day budget.

What is pinned:
- the frames we send, byte for byte, as Fyers' Python SDK (fyers_apiv3 3.2.1, data_ws.py, MIT) builds them; the golden bytes below are worked out by hand from the SDK's
  own code, field by field;
- the frames we read: the login and subscription answers, Fyers' own messages, a topic's first snapshot, later updates, the null marker, price scaling, the
  acknowledgement count;
- the token's hsm_key; the symbol-token call;
- a real WebSocket round trip against a local server: log in, full mode, subscribe, quotes in, an acknowledgement and a ping out, and a reconnect when the server drops;
- the feed: while the socket delivers, no REST quote call is made and the whole day budget goes to the chains and books; when it stops, REST takes the quotes back;
  a future the socket does not carry stays on REST; the login check reports the socket; and the switch in config."""
from __future__ import annotations

import base64
import datetime as dt
import json
import struct
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

from quantdesk.config import Config
from quantdesk.data import fyers_feed as F
from quantdesk.data import fyers_socket as FS
from tests.test_fyers import NAMES, PRICES, FakeAPI, FakePusher

IST = F.IST
ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------------------------------------------- server frames, as Fyers sends them

def _f(fid, v: bytes) -> bytes:
    return struct.pack("!BH", fid, len(v)) + v


def _frame(kind: int, body: bytes) -> bytes:
    return struct.pack("!H", 1 + len(body)) + bytes([kind]) + body


def auth_resp(ok=True, ack=0) -> bytes:
    return _frame(1, bytes([2]) + _f(1, b"K" if ok else b"N") + _f(2, struct.pack(">I", ack)))


def sub_resp(ok=True) -> bytes:
    return _frame(4, bytes([1]) + _f(1, b"K" if ok else b"N"))


def custom(code: int, text: str) -> bytes:
    return _frame(51, bytes([2]) + _f(1, struct.pack("!i", code)) + _f(2, text.encode()))


def snapshot(tid: int, topic: str, vals: dict, mult=1, prec=2) -> bytes:
    row = [vals.get(k, FS.NULL) for k in FS.DATA_VAL]
    out = bytes([83]) + struct.pack("<H", tid) + bytes([len(topic)]) + topic.encode() + bytes([len(row)]) + struct.pack(f">{len(row)}i", *row)
    out += b"\x00\x00" + struct.pack(">H", mult) + bytes([prec])
    for s in ("MCX", "445566", "CRUDEOIL26NOVFUT"):
        out += bytes([len(s)]) + s.encode()
    return out


def update(tid: int, vals: dict) -> bytes:
    row = [vals.get(k, FS.NULL) for k in FS.DATA_VAL]
    return bytes([85]) + struct.pack("<H", tid) + bytes([len(row)]) + struct.pack(f">{len(row)}i", *row)


def data(number: int, *entries: bytes) -> bytes:
    body = struct.pack(">I", number) + struct.pack("!H", len(entries)) + b"".join(entries)
    return _frame(6, body)


def jwt(claims: dict) -> str:
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")
    return f"{enc({'alg': 'HS256'})}.{enc(claims)}.sig"


TOKEN = jwt({"hsm_key": "HSMKEY123", "exp": time.time() + 3600})
CRUDE = "sf|mcx_fo|445566"
USD = "sf|cde_fo|1234"
TOPICS = {CRUDE: "MCX:CRUDEOIL26NOVFUT", USD: "NSE:USDINR26NOVFUT"}


# ---------------------------------------------------------------------------------------------------------------- the frames we send

def test_the_login_full_mode_subscription_and_ack_frames_match_the_sdk_byte_for_byte():
    # fyers_apiv3 3.2.1 __access_token_msg: !H (18 + len(key) + len(source) - 2), type 1, 4 fields: 1 key, 2 mode "P", 3 the byte 1, 4 the source
    assert FS.auth_msg("KEY", source="SRC") == b"\x00\x16\x01\x04" + b"\x01\x00\x03KEY" + b"\x02\x00\x01P" + b"\x03\x00\x01\x01" + b"\x04\x00\x03SRC"
    # __full_mode_msg: >H 0, type 12, 2 fields: 1 the channel's bit (>Q), 2 the byte 70
    assert FS.full_mode_msg(11) == b"\x00\x00\x0c\x02" + b"\x01\x00\x08" + (1 << 11).to_bytes(8, "big") + b"\x02\x00\x01\x46"
    # __subscription_msg: >H (18 + len(scrips) + len(access token) + len(source)), type 4, 2 fields: 1 the scrips (>H count, then each length-prefixed), 2 the channel
    scrips = b"\x00\x01" + bytes([11]) + b"sf|mcx_fo|1"
    assert FS.subscribe_msg(["sf|mcx_fo|1"], auth_len=10, source="SRC") == struct.pack(">H", 18 + 14 + 10 + 3) + b"\x04\x02" + b"\x01\x00\x0e" + scrips + b"\x02\x00\x01\x0b"
    # __ackowledgement_msg: >H 9, type 3, 1 field: id 1, >H 4, >I the message number
    assert FS.ack_msg(77) == b"\x00\x09\x03\x01\x01\x00\x04" + (77).to_bytes(4, "big")
    assert FS.PING == bytes([0, 1, 11]) and FS.URL == "wss://socket.fyers.in/hsm/v1-5/prod"


def test_the_hsm_key_comes_from_the_token_and_an_expired_or_odd_token_is_refused():
    assert FS.hsm_key(TOKEN) == "HSMKEY123"
    with pytest.raises(FS.SocketRefused):
        FS.hsm_key(jwt({"hsm_key": "K", "exp": time.time() - 10}))
    for bad in ("", "nodots", jwt({"exp": time.time() + 99}), jwt({"hsm_key": "", "exp": time.time() + 99})):
        with pytest.raises(FS.SocketRefused):
            FS.hsm_key(bad)


def test_the_symbol_token_call_posts_the_tickers_and_maps_fyers_tokens_to_topics():
    seen = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return self.body

    def opener(req, timeout=None):
        seen.append(req)
        return Resp(json.dumps({"s": "ok", "validSymbol": {"MCX:CRUDEOIL26NOVFUT": "1120261119445566", "NSE:USDINR26NOVFUT": "1012261126001234",
                                                          "BSE:ODD": "9999000000123"}, "invalidSymbol": ["MCX:NOPE"]}).encode())
    topics, bad = FS.symbol_topics("A-100", "TOK", ["MCX:CRUDEOIL26NOVFUT", "NSE:USDINR26NOVFUT", "MCX:NOPE"], opener=opener)
    assert topics == {"sf|mcx_fo|445566": "MCX:CRUDEOIL26NOVFUT", "sf|cde_fo|001234": "NSE:USDINR26NOVFUT"} and bad == ["MCX:NOPE"]
    req = seen[0]
    assert req.full_url == FS.TOKEN_API and req.get_method() == "POST" and req.get_header("Authorization") == "TOK"     # the bare token, as Fyers' SDK sends it here
    assert json.loads(req.data) == {"symbols": ["MCX:CRUDEOIL26NOVFUT", "NSE:USDINR26NOVFUT", "MCX:NOPE"]}
    with pytest.raises(ValueError):
        FS.symbol_topics("A-100", "TOK", ["X"], opener=lambda req, timeout=None: Resp(b'{"s": "error", "message": "bad"}'))
    with pytest.raises(FS.RateLimited):
        FS.symbol_topics("A-100", "TOK", ["X"], opener=lambda req, timeout=None: Resp(b'{"s": "error", "code": -429}'))
    import io
    import urllib.error

    def limited(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "x", {}, io.BytesIO(b""))
    with pytest.raises(FS.RateLimited):
        FS.symbol_topics("A-100", "TOK", ["X"], opener=limited)
    odd = lambda req, timeout=None: Resp(json.dumps({"s": "ok", "validSymbol": {}, "invalidSymbol": 5}).encode())
    assert FS.symbol_topics("A-100", "TOK", ["X"], opener=odd) == ({}, [])          # an odd answer is not a crash

    class Lim:
        n = 0

        def wait(self):
            Lim.n += 1
    FS.symbol_topics("A-100", "TOK", ["X"], opener=odd, limiter=Lim())
    assert Lim.n == 1                                                                   # through the REST feed's limiter


def test_the_symbol_token_call_refuses_redirects(monkeypatch):
    import urllib.request
    seen = {}

    def build(*handlers):
        seen["handlers"] = handlers

        class O:
            def open(self, req, timeout=None):
                raise OSError("stop here")
        return O()
    monkeypatch.setattr(urllib.request, "build_opener", build)
    with pytest.raises(OSError):
        FS.symbol_topics("A-100", "TOK", ["X"])
    assert FS._NoRedirect in seen["handlers"]


# ---------------------------------------------------------------------------------------------------------------- the frames we read

def test_the_decoder_reads_login_subscription_snapshots_updates_and_fyers_messages():
    d = FS.Decoder(TOPICS)
    assert d.feed(auth_resp(ok=True, ack=2)) == ({}, None) and d.authed is True and d.ack_every == 2
    d.feed(sub_resp(ok=True))
    assert d.subscribed is True
    d.feed(custom(51001, "Symbol limit exceeded for your plan"))
    assert d.messages == [51001]                                                       # the code only: Fyers' text never reaches the public summary
    snap = {"ltp": 581250, "bid_price": 581200, "ask_price": 581300, "bid_size": 5, "ask_size": 7, "vol_traded_today": 12000, "OI": 4400, "prev_close_price": 575000}
    quotes, ack = d.feed(data(1, snapshot(7, CRUDE, snap), snapshot(8, USD, {"ltp": 845025, "bid_price": 845000, "ask_price": 845050}, mult=1, prec=4)))
    assert ack is None
    q = quotes["MCX:CRUDEOIL26NOVFUT"]
    assert q == {"ltp": 5812.5, "bid": 5812.0, "ask": 5813.0, "bid_qty": 5, "ask_qty": 7, "vol": 12000, "chg": round((5812.5 / 5750 - 1) * 100, 4), "oi": 4400}
    assert quotes["NSE:USDINR26NOVFUT"]["ltp"] == 84.5025
    quotes, ack = d.feed(data(2, update(7, {"ltp": 581350})))                         # only the price moved: the null marker leaves the rest as they were
    assert ack == 2 and quotes["MCX:CRUDEOIL26NOVFUT"]["ltp"] == 5813.5 and quotes["MCX:CRUDEOIL26NOVFUT"]["oi"] == 4400 and "NSE:USDINR26NOVFUT" not in quotes
    quotes, ack = d.feed(data(3, update(7, {"ltp": 581350})))
    assert quotes == {} and ack is None                                                # nothing changed: nothing to push
    d.feed(data(4, update(99, {"ltp": 1})))                                            # an update for a topic never snapshotted
    assert d.unread == 1
    d.feed(b"\x00\x05\x06\x00")                                                        # a truncated frame: counted, never raised
    assert d.unread == 2


def test_a_crossed_or_empty_book_is_not_shown_and_a_refused_login_is_seen():
    d = FS.Decoder(TOPICS)
    q, _ = d.feed(data(1, snapshot(7, CRUDE, {"ltp": 100, "bid_price": 120, "ask_price": 110})))
    assert q["MCX:CRUDEOIL26NOVFUT"] == {"ltp": 1.0}
    d.feed(auth_resp(ok=False))
    assert d.authed is False


# ---------------------------------------------------------------------------------------------------------------- a real WebSocket round trip

def test_a_real_websocket_session_logs_in_subscribes_streams_acks_pings_and_reconnects(monkeypatch):
    from websockets.sync.server import serve
    monkeypatch.setattr(FS, "PING_EVERY_S", 0.2)
    got, sessions = [], []

    def handler(ws):
        sessions.append(1)
        msgs = [ws.recv(), ws.recv()]
        got.extend(msgs)
        ws.send(auth_resp(ok=True, ack=2))
        got.append(ws.recv())                                                         # the subscription comes once the login is answered
        ws.send(sub_resp())
        ws.send(data(10, snapshot(7, CRUDE, {"ltp": 581250, "bid_price": 581200, "ask_price": 581300})))
        ws.send(data(11, update(7, {"ltp": 581300})))
        deadline = time.time() + 3
        while time.time() < deadline:
            try:
                got.append(ws.recv(timeout=0.3))
            except TimeoutError:
                continue
            if len(sessions) == 1 and FS.ack_msg(11) in got and FS.PING in got:
                return                                                                 # the first session ends: the client must reconnect
            if len(sessions) == 2:
                return

    with serve(handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        from websockets.sync.client import connect
        sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=lambda url: connect(f"ws://127.0.0.1:{port}", proxy=None), sleep=lambda s: time.sleep(0.05),
                              host=f"127.0.0.1:{port}")
        sock.start()
        deadline = time.time() + 8
        while time.time() < deadline and len(sessions) < 2:
            time.sleep(0.05)
        quotes = sock.latest()
        sock.stop()
        server.shutdown()
    assert got[0] == FS.auth_msg("HSMKEY123") and got[1] == FS.full_mode_msg()
    assert got[2] == FS.subscribe_msg(list(TOPICS), len("A-100") + 1 + len(TOKEN))
    assert FS.ack_msg(11) in got and FS.PING in got
    assert len(sessions) == 2 and sock.stats["connects"] == 2                         # dropped, then back by itself
    assert quotes["MCX:CRUDEOIL26NOVFUT"]["ltp"] == 5813.0
    assert "HSMKEY123" not in json.dumps(sock.stats) and TOKEN not in json.dumps(sock.stats)


# ---------------------------------------------------------------------------------------------------------------- the feed with the socket

class FakeSocket:
    def __init__(self, topics, quotes=None, delivering=True, seen=None):
        self.topics, self.q, self.up = dict(topics), dict(quotes or {}), delivering
        self.carried = set(self.topics.values()) if seen is None else set(seen)
        self.stats = {"connects": 1, "frames": 5, "unread": 0, "message_codes": []}
        self.stopped = False

    def delivering(self):
        return self.up

    def seen(self):
        return set(self.carried)

    def latest(self):
        out, self.q = self.q, {}
        return out

    def start(self):
        pass

    def stop(self):
        self.stopped = True


def test_while_the_socket_delivers_no_rest_quote_is_called_and_rest_takes_them_back_when_it_stops():
    api, push = FakeAPI(dict(PRICES)), FakePusher()
    on = {"MCX:CRUDEOIL26NOVFUT": "x", "MCX:GOLD26DECFUT": "y", "NSE:USDINR26NOVFUT": "z"}
    sock = FakeSocket({v: k for v, k in zip(on.values(), on)}, {"MCX:CRUDEOIL26NOVFUT": {"ltp": 5900.0, "bid": 5899.0, "ask": 5901.0, "oi": 777}})
    feed = F.FyersFeed(api, NAMES, ["CRUDEOIL-MCX"], push, depth_per_cycle=1, now=lambda: dt.datetime(2026, 11, 16, 10, 0, tzinfo=IST), socket=sock)
    feed.cycle()
    assert not any(p == "/quotes" for p, _ in api.calls)
    pushed = dict(push.got)
    assert pushed["CRUDEOIL-MCX"]["ltp"] == 5900.0 and pushed["CRUDEOIL-MCX"]["s"] == "mcx" and pushed["CRUDEOIL-MCX"]["e"] == "2026-11-19"
    assert feed.oi["CRUDEOIL-MCX"] == 777 and feed.stats["socket_rounds"] == 1
    sock.up = False
    feed.cycle()
    assert any(p == "/quotes" for p, _ in api.calls)                                   # the socket went quiet: REST carries the quotes again


def test_a_future_the_socket_does_not_carry_stays_on_rest():
    api = FakeAPI(dict(PRICES))
    sock = FakeSocket({"x": "MCX:CRUDEOIL26NOVFUT", "y": "MCX:GOLD26DECFUT"})
    feed = F.FyersFeed(api, NAMES, [], FakePusher(), now=lambda: dt.datetime(2026, 11, 16, 10, 0, tzinfo=IST), socket=sock)
    feed.cycle()
    calls = [p for p, prm in api.calls if p == "/quotes"]
    assert calls and [prm["symbols"] for p, prm in api.calls if p == "/quotes"] == ["NSE:USDINR26NOVFUT"]


def test_a_streaming_standard_day_spends_the_whole_budget_on_chains_and_books(monkeypatch):
    from tests.test_fyers_budget import COM, CUR, DAY, Clock, TimedAPI
    names = {f"{c}-MCX": {"seg": "mcx", "ticker": f"MCX:{c}26NOVFUT", "expiry": dt.date(2026, 11, 19)} for c in COM}
    names.update({f"{c}-CDS": {"seg": "cds", "ticker": f"NSE:{c}26NOVFUT", "expiry": dt.date(2026, 11, 26)} for c in CUR})
    clock = Clock(dt.datetime.combine(DAY, dt.time(8, 59), IST))
    api = TimedAPI({c["ticker"]: (100.0, 99.9, 100.1) for c in names.values()}, clock)
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: names)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    monkeypatch.setattr(FS, "symbol_topics", lambda app_id, token, tickers, opener=None, limiter=None: ({f"t{i}": t for i, t in enumerate(tickers)}, []))
    reps = []
    for start, until in [("08:59", "14:15"), ("14:15", "20:05"), ("20:05", "23:58")]:
        h, m = (int(x) for x in start.split(":"))
        clock.t = max(clock.t, dt.datetime.combine(DAY, dt.time(h, m), IST))
        reps.append(F.run(until, "A-100", TOKEN, FakePusher(), watchlist={"commodities": COM, "currencies": CUR}, now=clock.now, sleep=clock.sleep, plan="standard",
                          use_socket=True, socket_factory=lambda app_id, token, topics: FakeSocket(topics)))
    n = Counter(p for _, p in api.at)
    assert n["/quotes"] == 0 and len(api.at) <= F.PLANS["standard"]["per_day"]
    assert n["/options-chain-v3"] + n["/depth"] >= 0.9 * F.PLANS["standard"]["per_day"]       # the quotes' share went to the chains and books
    seen: dict[str, list] = {}
    for (t, path), (_, params) in zip(api.at, api.calls):
        if path == "/options-chain-v3":
            seen.setdefault(params["symbol"], []).append(t)
    from itertools import pairwise
    day = [(b - a).total_seconds() for ts in seen.values() for a, b in pairwise([x for x in ts if dt.time(9, 30) <= x.time() <= dt.time(17, 5)])]
    assert max(day) < 300                                                               # every watchlist chain within five minutes by day (eight without the socket)
    assert all(r["socket_symbols"] == len(names) and r["socket"]["connects"] == 1 for r in reps)


def test_a_socket_that_cannot_start_leaves_the_rest_feed_as_it_was(monkeypatch):
    clock = dt.datetime(2026, 11, 16, 10, 0, tzinfo=IST)
    api = FakeAPI(dict(PRICES))
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: NAMES)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    t = [clock]
    run = lambda token: F.run("10:05", "A-100", token, FakePusher(), now=lambda: t[0], plan="standard", use_socket=True,        
                              sleep=lambda s: t.__setitem__(0, t[0] + dt.timedelta(seconds=max(s, 1))))

    def down(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(FS, "symbol_topics", down)
    rep = run(TOKEN)
    assert "socket" not in rep and any("could not start (OSError)" in n for n in rep["notes"]) and any(p == "/quotes" for p, _ in api.calls)
    monkeypatch.setattr(FS, "symbol_topics", lambda *a, **k: ({"x": "MCX:CRUDEOIL26NOVFUT"}, []))
    t[0], api.calls[:] = clock, []
    rep = run(jwt({"exp": time.time() + 99}))                                          # a token without an hsm_key: the socket is refused, REST carries on
    assert "socket" not in rep and any("Data Socket not used" in n for n in rep["notes"]) and any(p == "/quotes" for p, _ in api.calls)


def test_the_login_check_reports_the_socket(monkeypatch):
    api = FakeAPI(dict(PRICES))
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: NAMES)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    monkeypatch.setattr(FS, "symbol_topics", lambda *a, **k: ({"x": "MCX:CRUDEOIL26NOVFUT"}, []))
    rep = F.check("A-100", TOKEN, today=dt.date(2026, 11, 14), use_socket=True, sleep=lambda s: None,
                  socket_factory=lambda a, t, topics: FakeSocket(topics, {"MCX:CRUDEOIL26NOVFUT": {"ltp": 1.0}}))
    assert rep["result"] == "ok" and rep["socket"]["result"] == "ok" and rep["socket"]["quotes"] == 1 and rep["socket"]["symbols"] == 1
    rep = F.check("A-100", TOKEN, today=dt.date(2026, 11, 14), use_socket=True, sleep=lambda s: None, socket_wait_s=3,
                  socket_factory=lambda a, t, topics: FakeSocket(topics))
    assert rep["result"] == "ok" and rep["socket"]["result"] == "no quote came in time"       # the REST check still passes: the socket is a bonus


def test_the_desk_streams_by_default_and_the_cli_passes_the_switch(monkeypatch):
    cfg = Config.load(ROOT / "config" / "quantdesk.yaml")
    assert cfg.get("feeds.fyers_socket") is True
    from quantdesk.data import cli as C
    seen = {}
    monkeypatch.setattr(F, "run", lambda *a, **k: seen.update(k) or {"stopped": "until"})
    for k, v in {"FYERS_APP_ID": "A-100", "FYERS_DATA_TOKEN": "t", "LIVE_URL": "https://x.example", "LIVE_INGEST_TOKEN": "i" * 30}.items():
        monkeypatch.setenv(k, v)

    class Args:
        until, metrics, check = "23:58", None, False
    C.cmd_fyers_feed(cfg, Args())
    assert seen.get("use_socket") is True and seen.get("plan") == "standard"


def test_the_socket_code_names_only_fyers_data_hosts():
    text = (ROOT / "quantdesk/data/fyers_socket.py").read_text()
    import re
    hosts = set(re.findall(r"(?:https|wss)://([a-z0-9.-]+)", text))
    assert hosts == {"socket.fyers.in", "api-t1.fyers.in"}
    assert "order_ws" not in text and "OrderSocket" not in text and "/trade" not in text


def test_the_socket_counts_as_delivering_only_with_data_in_the_last_minute_and_never_once_stopped():
    t = [1000.0]
    sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=lambda url: None, clock=lambda: t[0])
    assert not sock.delivering()                                                       # nothing yet
    sock.last_data = t[0]
    assert sock.delivering()
    t[0] += FS.STALE_S + 1
    assert not sock.delivering()                                                       # a minute without data: REST takes the quotes back
    sock.last_data = t[0]
    sock.stop()
    assert not sock.delivering()


# ---------------------------------------------------------------------------------------------------------------- risk review of f5bdbb2 (VETO), each finding pinned

def test_a_handshake_redirected_away_from_fyers_sends_nothing_there():
    """V2: websockets follows redirects; the hsm_key must reach Fyers' host only. The redirect target must receive no frame."""
    from websockets.datastructures import Headers
    from websockets.http11 import Response
    from websockets.sync.server import serve
    other_got = []

    def other(ws):
        try:
            other_got.append(ws.recv(timeout=2))
        except Exception as e:                                                          # noqa: BLE001 - nothing arriving is the expected case
            other_got.append(None) if not isinstance(e, (TimeoutError, OSError)) and "ConnectionClosed" not in type(e).__name__ else None

    with serve(other, "127.0.0.1", 0) as b:
        pb = b.socket.getsockname()[1]
        threading.Thread(target=b.serve_forever, daemon=True).start()

        def redirect(connection, request):
            return Response(302, "Found", Headers([("Location", f"ws://127.0.0.1:{pb}/")]))
        with serve(lambda ws: None, "127.0.0.1", 0, process_request=redirect) as a:
            pa = a.socket.getsockname()[1]
            threading.Thread(target=a.serve_forever, daemon=True).start()
            from websockets.sync.client import connect
            sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=lambda url: connect(f"ws://127.0.0.1:{pa}/", proxy=None), host=f"127.0.0.1:{pa}")
            sock.start()
            sock._thread.join(timeout=10)
            a.shutdown()
        b.shutdown()
    assert other_got == [] and sock.stats["stopped"] == "the connection did not end on Fyers' host" and sock.stats["connects"] == 0


class FakeWS:
    """A scripted connection: frames in order; "quiet" is a recv timeout; at the end the connection drops."""

    def __init__(self, script, host=FS.HOST):
        self.script, self.sent = list(script), []
        self.request = type("R", (), {"headers": {"Host": host}})()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send(self, b):
        self.sent.append(b)

    def recv(self, timeout=None):
        if not self.script:
            raise ConnectionError("dropped")
        x = self.script.pop(0)
        if x == "quiet":
            raise TimeoutError()
        return x


def _streaming_session():
    return FakeWS([auth_resp(), sub_resp(), data(1, snapshot(7, CRUDE, {"ltp": 581250}))])


def test_fyers_message_texts_never_reach_the_stats():
    """V1: the run summary is public; Fyers writes the text of its messages. Only the numeric code is kept."""
    text = "Symbol limit exceeded for ACCOUNT XY12345"
    ws = FakeWS([auth_resp(), custom(51001, text), sub_resp(), data(1, snapshot(7, CRUDE, {"ltp": 581250}))])
    sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=lambda url: ws, sleep=lambda s: None)
    try:
        sock._session()
    except ConnectionError:
        pass
    assert sock.stats["message_codes"] == [51001] and "XY12345" not in json.dumps(sock.stats) and "Symbol limit" not in json.dumps(sock.stats)


def test_eight_drops_spread_over_a_day_never_give_up_but_eight_failures_in_a_row_do():
    sessions = []

    def connect(url):
        sessions.append(1)
        if len(sessions) >= 12:
            sock._stop.set()
        return _streaming_session()                                                     # each logs in, streams a quote, then drops
    sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=connect, sleep=lambda s: None)
    sock._run()
    assert len(sessions) >= 12 and sock.stats["stopped"] is None                        # 12 drops, each after a working session: still going

    tries = []

    def broken(url):
        tries.append(1)
        if len(tries) > 3 * FS.RECONNECT_MAX:
            sock._stop.set()                                                            # a socket that never gives up fails this test, it does not hang it
        raise OSError("refused")
    sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=broken, sleep=lambda s: None)
    sock._run()
    assert sock.stats["stopped"] == f"gave up after {FS.RECONNECT_MAX} failed connections in a row" and sock.stats["last_error"] == "OSError"


def test_a_refused_login_stops_the_socket_without_retrying():
    tries = []
    sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=lambda url: tries.append(1) or FakeWS([auth_resp(ok=False)]), sleep=lambda s: None)
    sock._run()
    assert sock.stats["stopped"] == "the socket refused the login" and len(tries) == 1


def test_a_socket_that_goes_silent_is_opened_again():
    t = [0.0]

    def clock():
        t[0] += 1.0
        return t[0]
    opened = []

    def connect(url):
        opened.append(1)
        if len(opened) >= 2:
            sock._stop.set()
        return FakeWS([auth_resp(), sub_resp(), data(1, snapshot(7, CRUDE, {"ltp": 581250}))] + ["quiet"] * 200)
    sock = FS.FyersSocket("A-100", TOKEN, TOPICS, connect=connect, clock=clock, sleep=lambda s: None)
    sock._run()
    assert sock.stats["silent"] >= 1 and len(opened) >= 2


def test_a_contract_carried_but_not_yet_streamed_stays_on_rest():
    api = FakeAPI(dict(PRICES))
    sock = FakeSocket({"x": "MCX:CRUDEOIL26NOVFUT", "y": "MCX:GOLD26DECFUT", "z": "NSE:USDINR26NOVFUT"}, seen={"MCX:CRUDEOIL26NOVFUT"})
    feed = F.FyersFeed(api, NAMES, [], FakePusher(), now=lambda: dt.datetime(2026, 11, 16, 10, 0, tzinfo=IST), socket=sock)
    feed.cycle()
    sent = [prm["symbols"] for p, prm in api.calls if p == "/quotes"]
    assert sent and "MCX:CRUDEOIL26NOVFUT" not in sent[0] and "MCX:GOLD26DECFUT" in sent[0] and "NSE:USDINR26NOVFUT" in sent[0]


def test_the_chains_borrow_the_quotes_budget_only_while_the_socket_streams():
    clock = dt.datetime(2026, 11, 16, 10, 0, tzinfo=IST)
    qb, xb = F.DayBudget(4500, 0.55, lambda: clock), F.DayBudget(4500, 0.45, lambda: clock)
    qb.tokens = 5.0                                                                     # the quotes have budget, the chains none
    api = FakeAPI(dict(PRICES))
    sock = FakeSocket(dict(TOPICS), delivering=False)
    feed = F.FyersFeed(api, NAMES, ["CRUDEOIL-MCX"], FakePusher(), now=lambda: clock, quotes_budget=qb, extras_budget=xb, socket=sock)
    feed.cycle()
    assert not any(p in ("/options-chain-v3", "/depth") for p, _ in api.calls)          # not streaming: the chains do not drain the quotes' share
    sock.up = True
    api.calls.clear()
    feed.cycle()
    assert any(p == "/options-chain-v3" for p, _ in api.calls)                         # streaming: they may


def test_the_socket_takes_at_most_the_plans_symbols_and_its_call_is_counted(monkeypatch):
    names = {f"X{i:03d}-MCX": {"seg": "mcx", "ticker": f"MCX:X{i:03d}26NOVFUT", "expiry": dt.date(2026, 11, 19)} for i in range(150)}
    asked = {}

    def topics(app_id, token, tickers, opener=None, limiter=None):
        asked["n"] = len(tickers)
        return {f"t{i}": t for i, t in enumerate(tickers)}, []
    monkeypatch.setattr(FS, "symbol_topics", topics)

    class Api:
        calls, limiter = 0, None
    api, rep = Api(), {"notes": []}
    sock = F._start_socket("A-100", TOKEN, names, "standard", api, rep, factory=lambda a, t, tp: FakeSocket(tp))
    assert asked["n"] == FS.SYMBOL_CAP["standard"] == 100 and api.calls == 1 and rep["socket_symbols"] == 100 and sock is not None


def test_the_run_stops_the_socket_and_a_rate_limited_start_stops_the_day(monkeypatch):
    clock = [dt.datetime(2026, 11, 16, 10, 0, tzinfo=IST)]
    api = FakeAPI(dict(PRICES))
    monkeypatch.setattr(F, "load_contracts", lambda opener=None: ([], []))
    monkeypatch.setattr(F, "near_futures", lambda c, d: NAMES)
    monkeypatch.setattr(F, "FyersData", lambda *a, **k: api)
    monkeypatch.setattr(FS, "symbol_topics", lambda *a, **k: ({"x": "MCX:CRUDEOIL26NOVFUT"}, []))
    made = []
    run = lambda: F.run("10:02", "A-100", TOKEN, FakePusher(), now=lambda: clock[0], plan="standard", use_socket=True,
                        sleep=lambda s: clock.__setitem__(0, clock[0] + dt.timedelta(seconds=max(s, 1))),
                        socket_factory=lambda a, t, tp: made.append(FakeSocket(tp)) or made[-1])
    rep = run()
    assert made and made[0].stopped and rep["socket"]["connects"] == 1

    def limited(*a, **k):
        raise FS.RateLimited()
    monkeypatch.setattr(FS, "symbol_topics", limited)
    clock[0], api.calls[:] = dt.datetime(2026, 11, 16, 10, 0, tzinfo=IST), []
    rep = run()
    assert rep["stopped"].startswith("blocked by Fyers") and not any(p == "/quotes" for p, _ in api.calls)
