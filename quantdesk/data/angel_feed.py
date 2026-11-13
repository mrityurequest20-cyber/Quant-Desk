"""The Angel One feed: currency futures, every five seconds, to the private live relay (docs/FEEDS.md).

The owner's split of 13 Nov 2026: Kite carries indices, stocks and options; Fyers carries MCX; **Angel One carries
currency**; Kotak stands behind everything. The relay's `feeds.routes` puts Angel One first for currency (`cds`); this
only pushes, under the desk's own names (`USDINR-CDS`, as the Kite recorder names them) and with the feed code `a`.

What it reads, with the day's session (deploy/angel_autologin.py) and SmartAPI's documented calls only:
  * Angel One's public instrument master (OpenAPIScripMaster.json), once at the start, for the nearest unexpired
    future (FUTCUR on CDS) of every currency pair: Kite's rule (kite_universe._near_futures);
  * the quote API in FULL mode (POST /rest/secure/angelbroking/market/v1/quote, 50 tokens a call), every cycle: last
    price, volume, open interest, percent change, and five levels of depth a side, all in one answer.

Our own rate cap is 2 calls a second and 40 a minute, far under SmartAPI's. A 429 stops the feed for the day; a refused
session (401, 403, or an AG8001/AG8002 "invalid/expired token" answer) stops it too.

DISPLAY ONLY, like the other feeds: nothing is written to disk, and no order, position, holding, funds or profile
endpoint is named in this file (a test checks). The session token and the API key are never printed or logged.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .fyers_feed import Limiter
from .live_push import book_from_tick

ROOT = "https://apiconnect.angelone.in"
QUOTE_PATH = "/rest/secure/angelbroking/market/v1/quote"
MASTER = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
HOSTS = {"apiconnect.angelone.in", "margincalculator.angelone.in"}
BATCH = 50
INTERVAL_S = 5.0
PER_SECOND, PER_MINUTE = 2, 40
TIMEOUT_S = 10.0
SESSION = (dt.time(8, 59), dt.time(17, 5))                     # currency trades 09:00 to 17:00
AUTHORITY_ENDS = dt.date(2027, 12, 31)                          # docs/AUTONOMY.md
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
CURRENCY = re.compile(r"^[A-Z]{6}$")
REFUSED_CODES = {"AG8001", "AG8002", "AG8003"}                  # invalid, expired, missing token


class Blocked(Exception):
    """HTTP 429: the feed stops for the day."""


class Refused(Exception):
    """The session was refused: today's login is not valid. The feed stops."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _headers(api_key: str, jwt: str) -> dict:
    return {"Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER", "X-SourceID": "WEB",
            "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1", "X-MACAddress": "00:00:00:00:00:00",
            "X-PrivateKey": api_key, "Authorization": "Bearer " + jwt, "User-Agent": "quantdesk-angel-data"}


class AngelData:
    """POST the quote API with the day's session. Nothing else is ever asked for."""

    def __init__(self, api_key: str, jwt: str, opener=None, limiter: Limiter | None = None):
        if not api_key or not jwt:
            raise ValueError("no Angel One API key or session")
        self._h = _headers(api_key, jwt)
        self._open = opener or urllib.request.build_opener(_NoRedirect).open
        self.limiter = limiter or Limiter(PER_SECOND, PER_MINUTE)
        self.calls = 0

    def quote(self, tokens: list[str]) -> dict:
        self.limiter.wait()
        self.calls += 1
        req = urllib.request.Request(ROOT + QUOTE_PATH, data=json.dumps({"mode": "FULL", "exchangeTokens": {"CDS": list(tokens)}}).encode(),
                                     method="POST", headers=self._h)
        try:
            with self._open(req, timeout=TIMEOUT_S) as r:
                raw = r.read(4 << 20)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                raise Blocked() from None
            if e.code in (401, 403):
                raise Refused() from None
            raise
        obj = json.loads(raw or b"{}")
        if isinstance(obj, dict) and str(obj.get("errorcode") or "") in REFUSED_CODES:
            raise Refused()
        return obj if isinstance(obj, dict) else {}


# ---------------------------------------------------------------------------------------------------------------- the contracts

def _expiry(s) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(s).strip().upper(), "%d%b%Y").date()        # 26NOV2026
    except ValueError:
        return None


def parse_master(rows) -> list[dict]:
    """Currency futures (FUTCUR on CDS) from the instrument master: [{under, expiry, token, symbol}]."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or r.get("exch_seg") != "CDS" or r.get("instrumenttype") != "FUTCUR":
            continue
        name, token, e = str(r.get("name") or "").strip().upper(), str(r.get("token") or "").strip(), _expiry(r.get("expiry"))
        if CURRENCY.match(name) and token.isdigit() and e:
            out.append({"under": name, "expiry": e, "token": token, "symbol": str(r.get("symbol") or "")[:40]})
    return out


def near_futures(contracts: list[dict], today: dt.date) -> dict[str, dict]:
    """{desk name: contract}: the nearest unexpired future of each currency pair, the same rule as Kite's."""
    best: dict[str, dict] = {}
    for c in contracts:
        if c["expiry"] >= today and (c["under"] not in best or c["expiry"] < best[c["under"]]["expiry"]):
            best[c["under"]] = c
    return {f"{u}-CDS": c for u, c in sorted(best.items())}


def load_contracts(opener=None) -> list[dict]:
    u = urllib.parse.urlsplit(MASTER)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise ValueError("not Angel One's host")
    with (opener or urllib.request.build_opener(_NoRedirect).open)(urllib.request.Request(MASTER, headers={"User-Agent": "quantdesk-angel-data"}), timeout=120) as r:
        return parse_master(json.loads(r.read(256 << 20)))


# ---------------------------------------------------------------------------------------------------------------- the prices

def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _ist(s) -> str | None:
    try:
        return dt.datetime.strptime(str(s).strip(), "%d-%b-%Y %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")      # 13-Nov-2026 10:46:10
    except ValueError:
        return None


def parse_quote(obj: dict) -> tuple[dict[str, dict], list[str]]:
    """{token: display quote with its book} from a FULL quote answer ({"status": true, "data": {"fetched": [...]}}), and the key names of anything it could not read (never a value)."""
    data = obj.get("data")
    rows = data.get("fetched") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return {}, [f"quote: no data.fetched list (keys {sorted(obj)[:12]}, status {obj.get('status')!r}, errorcode {re.sub(r'[^A-Za-z0-9]', '', str(obj.get('errorcode') or ''))[:12]!r})"]
    out, odd = {}, []
    for r in rows:
        if not isinstance(r, dict) or not str(r.get("symbolToken") or ""):
            odd.append(f"quote: a row without symbolToken (keys {sorted(r)[:16] if isinstance(r, dict) else type(r).__name__})")
            continue
        q = {"ltp": _num(r.get("ltp")), "vol": _num(r.get("tradeVolume")), "oi": _num(r.get("opnInterest")), "chg": _num(r.get("percentChange"))}
        q = {k: v for k, v in q.items() if v is not None}
        if not q.get("ltp"):
            if "ltp" not in r:
                odd.append(f"quote: no 'ltp' (keys {sorted(r)[:20]})")
            continue
        if isinstance(r.get("depth"), dict):
            q.update(book_from_tick({"depth": r["depth"]}))          # SmartAPI's depth is Kite's shape: {"buy": [{price, quantity, orders}], "sell": [...]}
        elif "depth" not in r:
            odd.append(f"quote: no 'depth' (keys {sorted(r)[:20]})")
        t = _ist(r.get("exchFeedTime") or r.get("exchTradeTime"))
        if t:
            q["t"] = t
        out[str(r["symbolToken"])] = q
    return out, odd


class AngelFeed:
    def __init__(self, api: AngelData, names: dict[str, dict], pusher, now=lambda: dt.datetime.now(IST)):
        self.api, self.names, self.pusher, self.now = api, names, pusher, now
        self.by_token = {c["token"]: n for n, c in names.items()}
        self.last: dict[str, dict] = {}
        self.stats = {"cycles": 0, "calls": 0, "quotes": 0, "pushed": 0, "books": 0, "errors": 0, "shape": []}

    def cycle(self) -> int:
        tokens = [c["token"] for c in self.names.values()]
        sent = 0
        for i in range(0, len(tokens), BATCH):
            try:
                obj = self.api.quote(tokens[i:i + BATCH])
                self.stats["calls"] += 1
            except (Blocked, Refused):
                raise
            except Exception:                                         # noqa: BLE001 - a bad answer costs one cycle
                self.stats["errors"] += 1
                continue
            got, odd = parse_quote(obj)
            for o in odd:
                if o not in self.stats["shape"] and len(self.stats["shape"]) < 20:
                    self.stats["shape"].append(o)
            for tok, q in got.items():
                n = self.by_token.get(tok)
                if not n:
                    continue
                q = {**q, "s": "cds"}
                self.stats["quotes"] += 1
                self.stats["books"] += "d" in q
                key = {k: v for k, v in q.items() if k != "t"}
                if self.last.get(n) == key:
                    continue                                          # nothing changed: no push, so a quiet market shows as an ageing price
                self.last[n] = key
                self.pusher.update(n, q)
                sent += 1
        self.stats["cycles"] += 1
        self.stats["pushed"] += sent
        return sent


def _at(hhmm: str, day: dt.date) -> dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), IST)


def run(until: str, api_key: str, jwt: str, pusher, opener=None, now=lambda: dt.datetime.now(IST), sleep=time.sleep, interval: float = INTERVAL_S) -> dict:
    """Stream until `until` (HH:MM IST) or the currency close. Returns the run's counts (no price, no token)."""
    start = now()
    stop = min(_at(until, start.date()), dt.datetime.combine(start.date(), SESSION[1], IST))
    names = near_futures(load_contracts(opener), start.date())
    rep = {"day": str(start.date()), "contracts": len(names), "stopped": "until"}
    if not names:
        rep["stopped"] = "no currency futures in Angel One's instrument master"
        return rep
    feed = AngelFeed(AngelData(api_key, jwt, opener=opener), names, pusher, now=now)
    if now().time() < SESSION[0]:
        wait = (dt.datetime.combine(start.date(), SESSION[0], IST) - now()).total_seconds()
        if wait > 0:
            sleep(wait)
    pusher.start()
    try:
        while now() < stop:
            t0 = time.monotonic()
            try:
                feed.cycle()
            except Blocked:
                rep["stopped"] = "blocked by Angel One (HTTP 429): stopped for the day"
                break
            except Refused:
                rep["stopped"] = "Angel One refused today's session"
                break
            sleep(max(0.0, interval - (time.monotonic() - t0)))
    finally:
        pusher.stop()
    rep.update(feed.stats, calls=feed.api.calls, push=pusher.stats())
    return rep
