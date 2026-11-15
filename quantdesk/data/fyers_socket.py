"""Fyers' Data Socket: MCX and currency futures STREAMED over one WebSocket, so their quotes spend none of the data API's day budget (docs/FEEDS.md).

Fyers' data APIs allow, on the Standard plan, 5,000 calls a day (fyers_feed.PLANS): spent on quotes, a price came every ~22 s. The Data Socket has no call budget,
only a symbol cap (Standard 100, Prime 5,000 per user, across connections: fyers.in/api-docs/v3/getting-started/plans-and-limits). This module subscribes the near-month
futures to it (32 contracts today) and keeps the latest quote of each; the REST feed then spends its whole budget on the option chains and books, and falls back to REST
quotes by itself whenever the socket is not delivering.

The wire protocol (binary "HSM" frames) follows Fyers' own Python SDK, fyers_apiv3 3.2.1 (FyersWebsocket/data_ws.py, MIT licence): the socket URL, the token message (the
access token's `hsm_key` claim), full mode on channel 11, subscription by HSM topic (`sf|<segment>|<exchange token>`, from POST /data/symbol-token), acknowledgements every
`ack_count` data messages, a ping every 10 s, and the data feed's field order and price scaling (value / (10^precision x multiplier)). The SDK itself is not used: it pins
old versions of requests, aiohttp and setuptools and pulls in AWS tooling; this file needs only `websockets`, already in requirements.txt. No cloud session that wrote this
could reach Fyers, so, as with the REST feed, the first real run is the test: anything the socket says that this cannot read is counted by its kind, never its value.

DISPLAY ONLY, like the REST feed: market data only, no order, position, holding, funds or profile message or endpoint (a test checks), nothing written to disk, and the
token never printed, logged or put in an error.
"""
from __future__ import annotations

import base64
import json
import struct
import threading
import time
import urllib.error
import urllib.request

URL = "wss://socket.fyers.in/hsm/v1-5/prod"
TOKEN_API = "https://api-t1.fyers.in/data/symbol-token"
SOURCE = "quantdesk-fyers-data"
CHANNEL = 11
PING = bytes([0, 1, 11])
PING_EVERY_S = 10.0
STALE_S = 60.0                         # no data frame for this long: the socket counts as not delivering, and the REST feed takes the quotes back
SYMBOL_CAP = {"standard": 100, "prime": 5000}
NULL = -2147483648                     # the HSM "no value" marker
EXCH_SEG = {"1010": "nse_cm", "1011": "nse_fo", "1120": "mcx_fo", "1210": "bse_cm", "1012": "cde_fo", "1211": "bse_fo", "1212": "bcs_fo", "1020": "nse_com"}
DATA_VAL = ("ltp", "vol_traded_today", "last_traded_time", "exch_feed_time", "bid_size", "ask_size", "bid_price", "ask_price", "last_traded_qty", "tot_buy_qty",
            "tot_sell_qty", "avg_trade_price", "OI", "low_price", "high_price", "Yhigh", "Ylow", "lower_ckt", "upper_ckt", "open_price", "prev_close_price")
PRICES = {"ltp", "bid_price", "ask_price", "avg_trade_price", "low_price", "high_price", "open_price", "prev_close_price"}
RECONNECT_MAX = 8                      # attempts in a row before the socket gives up for the run (the REST feed carries on)


class SocketRefused(Exception):
    """The token cannot be used on the socket (no hsm_key, or expired)."""


# ---------------------------------------------------------------------------------------------------------------- the token

def hsm_key(token: str, now: float | None = None) -> str:
    """The access token's `hsm_key` claim (the token is a JWT; Fyers' SDK reads the same claim). Raises SocketRefused when there is none or the token has expired."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "==="))
        key, exp = claims["hsm_key"], float(claims["exp"])
    except (IndexError, KeyError, TypeError, ValueError):
        raise SocketRefused("the token carries no hsm_key") from None
    if not isinstance(key, str) or not key:
        raise SocketRefused("the token carries no hsm_key")
    if exp < (time.time() if now is None else now):
        raise SocketRefused("the token has expired")
    return key


def symbol_topics(app_id: str, token: str, tickers: list[str], opener=None, limiter=None) -> tuple[dict[str, str], list[str]]:
    """{HSM topic: Fyers ticker} for `tickers` (one POST /data/symbol-token call), and the tickers Fyers did not know."""
    if not tickers:
        return {}, []
    if limiter is not None:
        limiter.wait()
    req = urllib.request.Request(TOKEN_API, data=json.dumps({"symbols": list(tickers)}).encode(), method="POST",
                                 headers={"Authorization": f"{app_id}:{token}", "Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": SOURCE})
    open_ = opener or urllib.request.build_opener(_NoRedirect).open
    with open_(req, timeout=10.0) as r:
        obj = json.loads(r.read(1 << 20) or b"{}")
    if not isinstance(obj, dict) or obj.get("s") != "ok" or not isinstance(obj.get("validSymbol"), dict):
        raise ValueError("symbol-token answer not ok")
    out = {}
    for ticker, fytoken in obj["validSymbol"].items():
        if not (isinstance(ticker, str) and isinstance(fytoken, str) and len(fytoken) > 10):
            continue
        seg = EXCH_SEG.get(fytoken[:4])
        if seg:
            out[f"sf|{seg}|{fytoken[10:]}"] = ticker
    bad = [t for t in obj.get("invalidSymbol") or [] if isinstance(t, str)]
    return out, bad


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                                                  # the Authorization header must never travel to another host


# ---------------------------------------------------------------------------------------------------------------- the frames we send

def _field(fid: int, value: bytes) -> bytes:
    return struct.pack("!BH", fid, len(value)) + value


def auth_msg(key: str, source: str = SOURCE) -> bytes:
    """Request type 1, four fields: the HSM key, mode "P", 1, the client's name."""
    body = bytes([1, 4]) + _field(1, key.encode()) + _field(2, b"P") + _field(3, bytes([1])) + _field(4, source.encode())
    return struct.pack("!H", len(body)) + body


def full_mode_msg(channel: int = CHANNEL) -> bytes:
    """Request type 12: the channel's bit, and 70 (full mode: price, book top, volume, OI)."""
    return struct.pack(">HBB", 0, 12, 2) + _field(1, struct.pack(">Q", 1 << channel)) + _field(2, bytes([70]))


def subscribe_msg(topics: list[str], auth_len: int, channel: int = CHANNEL, source: str = SOURCE) -> bytes:
    """Request type 4: the topics, on the channel. The length prefix is computed as Fyers' SDK computes it (with the access token's and the client name's lengths)."""
    scrips = struct.pack(">H", len(topics)) + b"".join(bytes([len(t.encode("ascii"))]) + t.encode("ascii") for t in topics)
    body = bytes([4, 2]) + _field(1, scrips) + _field(2, bytes([channel]))
    return struct.pack(">H", 18 + len(scrips) + auth_len + len(source)) + body


def ack_msg(message_number: int) -> bytes:
    return struct.pack(">HBBBHI", 9, 3, 1, 1, 4, message_number)


# ---------------------------------------------------------------------------------------------------------------- the frames we read

class Decoder:
    """Reads the socket's frames: the login and subscription answers, Fyers' own messages (code and text), and the data feed (a first full snapshot of each topic,
    then updates of the fields that changed). Keeps each topic's raw values and gives back the quotes that changed, in display units."""

    def __init__(self, topics: dict[str, str]):
        self.topics = dict(topics)                    # HSM topic -> Fyers ticker
        self.ids: dict[int, str] = {}                 # the socket's topic id -> HSM topic
        self.raw: dict[str, dict] = {}
        self.authed: bool | None = None
        self.subscribed: bool | None = None
        self.ack_every = 0
        self.since_ack = 0
        self.messages: list[tuple[int, str]] = []     # Fyers' own messages: (code, text), e.g. 51001, the plan's symbol limit
        self.unread = 0                               # frames or fields this could not read (counted, never shown)

    def feed(self, frame: bytes) -> tuple[dict[str, dict], int | None]:
        """One frame: ({ticker: quote that changed}, the message number to acknowledge or None)."""
        if len(frame) < 3:
            return {}, None
        kind = frame[2]
        try:
            if kind == 1:
                self._auth(frame)
            elif kind == 4:
                self.subscribed = frame[7:8] == b"K"
            elif kind == 51:
                self._custom(frame)
            elif kind == 6:
                return self._data(frame)
        except (struct.error, IndexError, UnicodeDecodeError, ValueError):
            self.unread += 1
        return {}, None

    def _auth(self, f: bytes) -> None:
        off = 5
        n = struct.unpack("!H", f[off:off + 2])[0]
        off += 2
        self.authed = f[off:off + n] == b"K"
        off += n + 1
        n = struct.unpack("!H", f[off:off + 2])[0]
        off += 2
        if n == 4:
            self.ack_every = struct.unpack(">I", f[off:off + 4])[0]

    def _custom(self, f: bytes) -> None:
        end = 2 + struct.unpack("!H", f[0:2])[0]
        off, code, text = 4, 0, ""
        for _ in range(f[3]):
            fid = f[off]
            n = struct.unpack("!H", f[off + 1:off + 3])[0]
            off += 3
            v = bytes(f[off:off + n])
            off += n
            if off > end:
                raise ValueError("truncated")
            if fid == 1 and n == 4:
                code = struct.unpack("!i", v)[0]
            elif fid == 2:
                text = v.decode("utf-8", errors="replace")[:120]
        self.messages.append((code, text))

    def _data(self, f: bytes) -> tuple[dict[str, dict], int | None]:
        ack = None
        number = struct.unpack(">I", f[3:7])[0]
        if self.ack_every > 0:
            self.since_ack += 1
            if self.since_ack >= self.ack_every:
                ack, self.since_ack = number, 0
        count = struct.unpack("!H", f[7:9])[0]
        off, changed = 9, set()
        for _ in range(count):
            kind = f[off]
            off += 1
            tid = struct.unpack("<H", f[off:off + 2])[0]
            off += 2
            if kind == 83:                                            # a topic's first full snapshot
                n = f[off]
                off += 1
                topic = f[off:off + n].decode("utf-8")
                off += n
                fields = f[off]
                off += 1
                vals = struct.unpack(f">{fields}i", f[off:off + 4 * fields])
                off += 4 * fields + 2
                mult = struct.unpack(">H", f[off:off + 2])[0]
                off += 2
                prec = f[off]
                off += 1
                for _ in range(3):                                    # exchange, exchange token, symbol: not needed (the topic says it)
                    off += 1 + f[off]
                if topic[:2] != "sf" or topic not in self.topics:
                    continue
                self.ids[tid] = topic
                self.raw[topic] = {"mult": mult or 1, "prec": prec, **{k: v for k, v in zip(DATA_VAL, vals) if v != NULL}}
                changed.add(topic)
            elif kind == 85:                                          # an update: every field again, the unchanged ones as they were
                fields = f[off]
                off += 1
                vals = struct.unpack(f">{fields}i", f[off:off + 4 * fields])
                off += 4 * fields
                topic = self.ids.get(tid)
                if topic is None:
                    self.unread += 1
                    continue
                r = self.raw[topic]
                for k, v in zip(DATA_VAL, vals):
                    if v != NULL and r.get(k) != v:
                        r[k] = v
                        changed.add(topic)
            elif kind == 76:                                          # lite mode: the price alone (not asked for; read if sent)
                topic = self.ids.get(tid)
                v = struct.unpack(">i", f[off:off + 4])[0]
                off += 4
                if topic is not None and v != NULL and self.raw[topic].get("ltp") != v:
                    self.raw[topic]["ltp"] = v
                    changed.add(topic)
            else:
                self.unread += 1
                break                                                 # a kind this cannot size: the rest of the frame cannot be read
        return {self.topics[t]: q for t in changed if (q := self.quote(t))}, ack

    def quote(self, topic: str) -> dict | None:
        """The topic's quote in the REST feed's display fields (fyers_feed.parse_quotes): ltp, bid, ask, sizes, volume, change %, OI."""
        r = self.raw.get(topic)
        if not r or not r.get("ltp"):
            return None
        scale = (10 ** r["prec"]) * r["mult"]
        px = {k: r[k] / scale for k in PRICES if k in r}
        q = {"ltp": px["ltp"]}
        if px.get("bid_price", 0) > 0 and px.get("ask_price", 0) > 0 and px["bid_price"] <= px["ask_price"]:
            q.update(bid=px["bid_price"], ask=px["ask_price"], bid_qty=r.get("bid_size"), ask_qty=r.get("ask_size"))
        if "vol_traded_today" in r:
            q["vol"] = r["vol_traded_today"]
        if px.get("prev_close_price"):
            q["chg"] = round((px["ltp"] / px["prev_close_price"] - 1) * 100, 4)
        if r.get("OI") is not None:
            q["oi"] = r["OI"]
        return {k: v for k, v in q.items() if v is not None}


# ---------------------------------------------------------------------------------------------------------------- the connection

class FyersSocket:
    """One Data Socket connection in a thread of its own: logs in, asks for full mode, subscribes the topics, answers the acknowledgements, pings every 10 s and
    reconnects (with a growing pause) when the connection drops. `latest()` gives the quotes that changed since the last call; `delivering()` says whether data has
    come in the last STALE_S seconds. Nothing here raises into the feed: a socket that cannot work leaves the REST feed doing what it did before."""

    def __init__(self, app_id: str, token: str, topics: dict[str, str], connect=None, clock=time.monotonic, sleep=time.sleep):
        self.key = hsm_key(token)
        self.auth_len = len(app_id) + 1 + len(token)
        self.topics = dict(topics)
        self._connect = connect or _ws_connect
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_data = None
        self.stats = {"connects": 0, "frames": 0, "quotes": 0, "acks": 0, "unread": 0, "messages": [], "stopped": None}
        self.decoder = Decoder(self.topics)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="fyers-socket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=15)

    def delivering(self) -> bool:
        t = self.last_data
        return t is not None and self.clock() - t < STALE_S and not self._stop.is_set()

    def latest(self) -> dict[str, dict]:
        with self._lock:
            out, self._pending = self._pending, {}
        return out

    def _run(self) -> None:
        fails = 0
        while not self._stop.is_set() and fails < RECONNECT_MAX:
            try:
                self._session()
                fails = 0
            except SocketRefused as e:
                self.stats["stopped"] = str(e)
                return
            except Exception as e:                                    # noqa: BLE001 - a dropped connection, a refused handshake: counted, retried
                fails += 1
                self.stats["last_error"] = type(e).__name__
            if not self._stop.is_set():
                self.sleep(min(60.0, 5.0 * fails))
        if fails >= RECONNECT_MAX:
            self.stats["stopped"] = f"gave up after {fails} failed connections"

    def _session(self) -> None:
        self.decoder = Decoder(self.topics)
        with self._connect(URL) as ws:
            self.stats["connects"] += 1
            ws.send(auth_msg(self.key))
            ws.send(full_mode_msg())
            subscribed, pinged = False, self.clock()
            while not self._stop.is_set():
                if self.clock() - pinged >= PING_EVERY_S:
                    ws.send(PING)
                    pinged = self.clock()
                try:
                    frame = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                if isinstance(frame, str):
                    continue
                self.stats["frames"] += 1
                quotes, ack = self.decoder.feed(bytes(frame))
                if self.decoder.authed is False:
                    raise SocketRefused("the socket refused the login")
                if self.decoder.authed and not subscribed:
                    ws.send(subscribe_msg(list(self.topics), self.auth_len))
                    subscribed = True
                if ack is not None:
                    ws.send(ack_msg(ack))
                    self.stats["acks"] += 1
                if quotes:
                    self.last_data = self.clock()
                    self.stats["quotes"] += len(quotes)
                    with self._lock:
                        self._pending.update(quotes)
                self.stats["unread"] = self.decoder.unread
                for code, text in self.decoder.messages[len(self.stats["messages"]):]:
                    if len(self.stats["messages"]) < 10:
                        self.stats["messages"].append({"code": code, "text": text})


def _ws_connect(url: str):
    from websockets.sync.client import connect
    return connect(url, open_timeout=15, close_timeout=5, max_size=1 << 22, user_agent_header=SOURCE)
