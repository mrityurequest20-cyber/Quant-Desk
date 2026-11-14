"""The Fyers feed: MCX and currency prices, and their OPTION CHAINS, every five seconds, to the private live relay (docs/FEEDS.md).

The owner's split of 13 Nov 2026: Kite carries indices, stocks and options; **Fyers carries MCX** (and is currency's
second feed); Kotak stands behind everything. The relay's `feeds.routes` decides what is shown; this only pushes, under
the desk's own names (`CRUDEOIL-MCX`, `USDINR-CDS`, as the Kite recorder names them) and with the feed code `f`.

What it reads, all with GET and the day's token (deploy/fyers_autologin.py):
  * Fyers' public symbol master for MCX commodities and NSE currency derivatives, once at the start, to find the nearest
    unexpired future of every commodity and currency pair (Kite's rule: kite_universe._near_futures);
  * `/data/quotes` for all of them, 50 symbols a call (Fyers' limit), every cycle: last price, best bid and offer,
    volume, percent change;
  * `/data/depth` for the owner's watchlist names (config `desk.watchlist.commodities` and `.currencies`), a few a
    cycle in turn: five levels a side and the open interest, for the instrument page's ladder.

Fyers' limits: a per-second and a per-minute cap, and a user who breaks the per-minute cap more than three times in a
day is blocked for the rest of it. So every call goes through `Limiter` (well under the caps), and a 429 stops the feed
for the day at once instead of trying again.

DISPLAY ONLY, like the Kite live push: nothing is written to disk, nothing is read by the paper desk's decisions
except through the relay's quotes, and no order, position, holding, funds or profile endpoint is named in this file
(a test checks). The token is never printed, logged or put in an error.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque

from .live_push import book_from_tick

DATA = "https://api-t1.fyers.in/data"
MASTERS = {      # (JSON, CSV) per segment: the JSON first, the CSV if the JSON cannot be read
    "mcx": ("https://public.fyers.in/sym_details/MCX_COM_sym_master.json", "https://public.fyers.in/sym_details/MCX_COM.csv"),
    "cds": ("https://public.fyers.in/sym_details/NSE_CD_sym_master.json", "https://public.fyers.in/sym_details/NSE_CD.csv"),
}
HOSTS = {"api-t1.fyers.in", "public.fyers.in"}
SUFFIX = {"mcx": "MCX", "cds": "CDS"}
EXCHANGE = {"mcx": "MCX", "cds": "NSE"}
QUOTE_BATCH = 50
INTERVAL_S = 5.0
DEPTH_PER_CYCLE = 2
CHAINS_PER_CYCLE = 3                  # option chains (one call each), in turn: each watchlist commodity and currency every few cycles
CHAIN_STRIKES = 8
PER_SECOND, PER_MINUTE = 5, 100       # our own caps, about half of what Fyers allows, so a burst never comes near theirs
TIMEOUT_S = 10.0
SESSIONS = {"mcx": (dt.time(8, 59), dt.time(23, 59)), "cds": (dt.time(8, 59), dt.time(17, 5))}    # MCX to 23:30 or 23:55 (US daylight saving), currency to 17:00
AUTHORITY_ENDS = dt.date(2027, 12, 31)                                                           # docs/AUTONOMY.md: the owner's Fyers data exception ends on this date
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TICKER = re.compile(r"^(MCX|NSE):([A-Z][A-Z0-9&]*?)(\d{2})([A-Z]{3})FUT$")                     # MCX:CRUDEOIL26DECFUT, NSE:USDINR26NOVFUT
CURRENCY = re.compile(r"^[A-Z]{6}$")                                                             # USDINR, EURUSD: not the interest-rate futures on the same segment


class Blocked(Exception):
    """Fyers answered 429: the user is blocked for the day. The feed stops."""


class Refused(Exception):
    """Fyers refused the token (401 or 403): today's login is not valid. The feed stops."""


class Limiter:
    """At most `per_second` calls in any second and `per_minute` in any minute."""

    def __init__(self, per_second: int = PER_SECOND, per_minute: int = PER_MINUTE, clock=time.monotonic, sleep=time.sleep):
        self.ps, self.pm, self.clock, self.sleep = per_second, per_minute, clock, sleep
        self.calls: deque[float] = deque()

    def wait(self) -> None:
        while True:
            now = self.clock()
            while self.calls and now - self.calls[0] >= 60:
                self.calls.popleft()
            last_s = sum(1 for t in self.calls if now - t < 1)
            if len(self.calls) < self.pm and last_s < self.ps:
                self.calls.append(now)
                return
            gap = (self.calls[0] + 60 - now) if len(self.calls) >= self.pm else 1 - (now - self.calls[-self.ps])
            self.sleep(max(0.05, gap))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None                                                  # the Authorization header must never travel to another host


class FyersData:
    """GET a Fyers data endpoint with the day's token. Only /data/quotes and /data/depth are ever asked for."""

    PATHS = ("/quotes", "/depth", "/options-chain-v3")

    def __init__(self, app_id: str, token: str, opener=None, limiter: Limiter | None = None):
        if not app_id or not token:
            raise ValueError("no Fyers app id or token")
        self._auth = f"{app_id}:{token}"                              # Fyers' header: APP_ID:ACCESS_TOKEN (fyers_apiv3 FyersModel.header)
        self._open = opener or urllib.request.build_opener(_NoRedirect).open
        self.limiter = limiter or Limiter()
        self.calls = 0

    def get(self, path: str, params: dict) -> dict:
        if path not in self.PATHS:
            raise ValueError("not a market-data path")
        self.limiter.wait()
        self.calls += 1
        url = DATA + path + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"Authorization": self._auth, "version": "3", "Accept": "application/json", "User-Agent": "quantdesk-fyers-data"})
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
        if isinstance(obj, dict) and obj.get("code") in (-15, -16, -17, -8):          # Fyers' "token invalid / expired / not authenticated" codes, sent with HTTP 200
            raise Refused()
        return obj if isinstance(obj, dict) else {}


# ---------------------------------------------------------------------------------------------------------------- the contracts

def _expiry(v) -> dt.date | None:
    """Fyers gives the expiry as epoch seconds (a number or a string of digits); the IST date of it."""
    try:
        s = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(s) or s < 1e9 or s > 1e10:
        return None
    return dt.datetime.fromtimestamp(s, IST).date()


def _contract(seg: str, ticker: str, under: str | None, expiry) -> dict | None:
    m = TICKER.match(str(ticker or "").strip())
    if not m or m.group(1) != EXCHANGE[seg]:
        return None
    u = str(under or "").strip().upper() or m.group(2)
    if seg == "cds" and not CURRENCY.match(u):
        return None
    e = _expiry(expiry)
    if e is None:
        return None
    return {"seg": seg, "under": u, "expiry": e, "ticker": m.group(0)}


def parse_master_json(seg: str, obj) -> list[dict]:
    """The JSON master: a dict keyed by ticker (or a list) of records with symTicker, underSym and expiryDate."""
    recs = obj.items() if isinstance(obj, dict) else ((None, r) for r in (obj if isinstance(obj, list) else []))
    out = []
    for key, r in recs:
        if not isinstance(r, dict):
            continue
        c = _contract(seg, r.get("symTicker") or key, r.get("underSym"), r.get("expiryDate"))
        if c:
            out.append(c)
    return out


def parse_master_csv(seg: str, text: str) -> list[dict]:
    """The CSV master has no header row: the ticker is the field shaped like EXCHANGE:NAMEyyMONFUT, the expiry the field of ten digits (epoch seconds)."""
    out = []
    for row in csv.reader(io.StringIO(text)):
        ticker = next((f.strip() for f in row if TICKER.match(f.strip())), None)
        expiry = next((f.strip() for f in row if re.fullmatch(r"\d{10}", f.strip())), None)
        if ticker and expiry:
            c = _contract(seg, ticker, None, expiry)
            if c:
                out.append(c)
    return out


def near_futures(contracts: list[dict], today: dt.date) -> dict[str, dict]:
    """{desk name: contract}: the nearest unexpired future of each commodity and currency pair, the same rule as Kite's."""
    best: dict[tuple, dict] = {}
    for c in contracts:
        if c["expiry"] < today:
            continue
        k = (c["seg"], c["under"])
        if k not in best or c["expiry"] < best[k]["expiry"]:
            best[k] = c
    return {f"{u}-{SUFFIX[s]}": c for (s, u), c in sorted(best.items())}


def fetch_text(url: str, opener=None) -> str:
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or u.hostname not in HOSTS:
        raise ValueError("not a Fyers host")
    with (opener or urllib.request.build_opener(_NoRedirect).open)(urllib.request.Request(url, headers={"User-Agent": "quantdesk-fyers-data"}), timeout=60) as r:
        return r.read(64 << 20).decode("utf-8", "replace")


def load_contracts(opener=None, segments=("mcx", "cds")) -> tuple[list[dict], list[str]]:
    out, notes = [], []
    for seg in segments:
        jurl, curl = MASTERS[seg]
        got: list[dict] = []
        try:
            got = parse_master_json(seg, json.loads(fetch_text(jurl, opener)))
        except Exception as e:                                       # noqa: BLE001 - the CSV is the second way
            notes.append(f"{seg}: JSON master unreadable ({type(e).__name__})")
        if not got:
            try:
                got = parse_master_csv(seg, fetch_text(curl, opener))
            except Exception as e:                                   # noqa: BLE001
                notes.append(f"{seg}: CSV master unreadable ({type(e).__name__})")
        if not got:
            notes.append(f"{seg}: no futures found in Fyers' symbol master")
        out += got
    return out, notes


# ---------------------------------------------------------------------------------------------------------------- the prices

def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _ist(tt) -> str | None:
    s = _num(tt)
    if s is None or s < 1e9 or s > 1e10:
        return None
    return dt.datetime.fromtimestamp(s, IST).strftime("%Y-%m-%d %H:%M:%S")


def parse_quotes(obj: dict) -> tuple[dict[str, dict], list[str]]:
    """{ticker: display quote} from a /data/quotes answer ({"d": [{"n": ticker, "s": "ok", "v": {...}}]}), and the key names of anything it could not read (never a value)."""
    out, odd = {}, []
    rows = obj.get("d")
    if not isinstance(rows, list):
        return {}, [f"quotes: no list under 'd' (keys {sorted(obj)[:12]})"]
    for r in rows:
        v = r.get("v") if isinstance(r, dict) else None
        n = (r.get("n") if isinstance(r, dict) else None) or (v.get("symbol") if isinstance(v, dict) else None)
        if not isinstance(v, dict) or not isinstance(n, str):
            odd.append(f"quotes: a row without 'n' and 'v' (keys {sorted(r)[:12] if isinstance(r, dict) else type(r).__name__})")
            continue
        if r.get("s") not in (None, "ok"):
            continue                                                 # a symbol Fyers does not know today: skipped, not a shape problem
        q = {"ltp": _num(v.get("lp")), "bid": _num(v.get("bid")), "ask": _num(v.get("ask")), "vol": _num(v.get("volume")), "chg": _num(v.get("chp"))}
        q = {k: x for k, x in q.items() if x is not None}
        if not q.get("ltp"):
            if "lp" not in v:
                odd.append(f"quotes: no 'lp' (keys {sorted(v)[:16]})")
            continue
        for k in ("bid", "ask"):
            if q.get(k, 1) <= 0:
                q.pop(k, None)
        if "bid" in q and "ask" in q and q["bid"] > q["ask"]:       # a crossed quote: its book is not shown
            q.pop("bid"), q.pop("ask")
        t = _ist(v.get("tt"))
        if t:
            q["t"] = t
        out[n] = q
    return out, odd


def parse_depth(obj: dict, ticker: str) -> tuple[dict, list[str]]:
    """The book and open interest of one /data/depth answer ({"d": {ticker: {"bids": [{price, volume, ord}], "ask": [...], "oi": ...}}}), in the shape the relay takes."""
    d = obj.get("d")
    rec = d.get(ticker) if isinstance(d, dict) else None
    if not isinstance(rec, dict) and isinstance(d, dict) and len(d) == 1:
        rec = next(iter(d.values()))
    if not isinstance(rec, dict):
        return {}, [f"depth: no record for the symbol (keys {sorted(d)[:6] if isinstance(d, dict) else sorted(obj)[:12]})"]

    def side(*names):
        for n in names:
            if isinstance(rec.get(n), list):
                return [{"price": lv.get("price"), "quantity": lv.get("volume", lv.get("qty", lv.get("quantity"))), "orders": lv.get("ord", lv.get("orders"))}
                        for lv in rec[n] if isinstance(lv, dict)]
        return None

    buy, sell = side("bids", "bid"), side("ask", "asks")
    odd = [] if buy is not None and sell is not None else [f"depth: no bid or ask list (keys {sorted(rec)[:20]})"]
    out = book_from_tick({"depth": {"buy": buy or [], "sell": sell or []}})
    oi = _num(rec.get("oi"))
    if oi is not None and oi >= 0:
        out["oi"] = oi
    return out, odd


_MON = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def option_name(u: str, expiry: dt.date, strike: float, side: str) -> str:
    """The desk's one name for an option (kite_universe.option_name): CRUDEOIL17NOV265800CE, USDINR20NOV2684.25PE."""
    k = round(float(strike), 4)
    k = int(k) if k.is_integer() else k
    return f"{u}{expiry.day:02d}{_MON[expiry.month - 1]}{expiry.year % 100:02d}{k}{side}"


def _chain_expiry(data: dict) -> dt.date | None:
    """The chain's own expiry: the first of `expiryData` (the nearest, which is what a call without a timestamp returns)."""
    for e in (data.get("expiryData") or [])[:1]:
        if isinstance(e, dict):
            d = _expiry(e.get("expiry"))
            if d:
                return d
            try:
                return dt.datetime.strptime(str(e.get("date", "")), "%d-%m-%Y").date()
            except ValueError:
                return None
    return None


def parse_chain(obj: dict, u: str, label: str = "mopt") -> tuple[dict[str, dict], list[str]]:
    """{desk option name: quote} from an /options-chain-v3 answer ({"data": {"expiryData": [...], "optionsChain": [{strike_price, option_type, ltp, bid, ask, oi, volume, ltpchp}]}})."""
    data = obj.get("data") if isinstance(obj.get("data"), dict) else None
    rows = (data or {}).get("optionsChain") or (data or {}).get("options_chain")
    if not isinstance(rows, list):
        return {}, [f"chain: no data.optionsChain list (keys {sorted(obj)[:10]}{', data keys ' + str(sorted(data)[:12]) if data else ''})"]
    exp = _chain_expiry(data)
    if exp is None:
        return {}, [f"chain: no expiry in data.expiryData (keys {sorted(data)[:12]})"]
    out, odd = {}, []
    for r in rows:
        if not isinstance(r, dict):
            continue
        side = str(r.get("option_type") or "").upper()
        if side not in ("CE", "PE"):
            continue                                                 # the underlying's own row
        k, lp = _num(r.get("strike_price")), _num(r.get("ltp"))
        if k is None or k <= 0 or lp is None:
            if "strike_price" not in r:
                odd.append(f"chain: an option row without strike_price (keys {sorted(r)[:16]})")
            continue
        q = {"ltp": lp, "bid": _num(r.get("bid")), "ask": _num(r.get("ask")), "oi": _num(r.get("oi")), "vol": _num(r.get("volume")), "chg": _num(r.get("ltpchp")), "s": label}
        q = {kk: v for kk, v in q.items() if v is not None}
        if q.get("bid", 1) <= 0 or q.get("ask", 1) <= 0 or ("bid" in q and "ask" in q and q["bid"] > q["ask"]):
            q.pop("bid", None), q.pop("ask", None)
        if q["ltp"] > 0 or "bid" in q:
            out[option_name(u, exp, k, side)] = q
    return out, odd


# ---------------------------------------------------------------------------------------------------------------- the loop

class FyersFeed:
    def __init__(self, api: FyersData, names: dict[str, dict], depth_names: list[str], pusher, depth_per_cycle: int = DEPTH_PER_CYCLE, now=lambda: dt.datetime.now(IST)):
        self.api, self.names, self.pusher, self.now = api, names, pusher, now
        self.by_ticker = {c["ticker"]: n for n, c in names.items()}
        self.depth_names = [n for n in depth_names if n in names]
        self.per = max(0, int(depth_per_cycle))
        self.turn = 0
        self.chain_names = [n for n in self.depth_names]                    # the watchlist's commodities and currencies: their option chains, in turn
        self.chain_turn = 0
        self.chains_per = CHAINS_PER_CYCLE
        self.last_opt: dict[str, dict] = {}
        self.oi: dict[str, float] = {}
        self.last: dict[str, dict] = {}
        self.last_book: dict[str, dict] = {}
        self.stats = {"cycles": 0, "quote_calls": 0, "depth_calls": 0, "quotes": 0, "pushed": 0, "books": 0, "errors": 0, "shape": []}

    def _open(self, name: str) -> bool:
        a, b = SESSIONS[self.names[name]["seg"]]
        return a <= self.now().time() <= b

    def _note(self, odd: list[str]) -> None:
        for o in odd:
            if o not in self.stats["shape"] and len(self.stats["shape"]) < 20:
                self.stats["shape"].append(o)

    def cycle(self) -> int:
        """One round: quotes for every open contract, depth for the next few watchlist names; returns how many changed quotes went to the pusher."""
        live = [n for n in self.names if self._open(n)]
        quotes: dict[str, dict] = {}
        tickers = [self.names[n]["ticker"] for n in live]
        for i in range(0, len(tickers), QUOTE_BATCH):
            try:
                obj = self.api.get("/quotes", {"symbols": ",".join(tickers[i:i + QUOTE_BATCH])})
                self.stats["quote_calls"] += 1
            except (Blocked, Refused):
                raise
            except Exception:                                         # noqa: BLE001 - a bad answer costs one cycle, not the feed
                self.stats["errors"] += 1
                continue
            got, odd = parse_quotes(obj)
            self._note(odd)
            for t, q in got.items():
                if t in self.by_ticker:
                    quotes[self.by_ticker[t]] = q
        want = [n for n in self.depth_names if n in live]
        fresh: dict[str, dict] = {}                                   # books fetched in THIS cycle: only these are sent, so a ladder is never older than its timestamp says
        for _ in range(min(self.per, len(want))):
            n = want[self.turn % len(want)]
            self.turn += 1
            try:
                obj = self.api.get("/depth", {"symbol": self.names[n]["ticker"], "ohlcv_flag": 1})
                self.stats["depth_calls"] += 1
            except (Blocked, Refused):
                raise
            except Exception:                                         # noqa: BLE001
                self.stats["errors"] += 1
                continue
            book, odd = parse_depth(obj, self.names[n]["ticker"])
            self._note(odd)
            if book:
                fresh[n] = book
                self.stats["books"] += 1
                if "oi" in book:
                    self.oi[n] = book["oi"]
        want_c = [n for n in self.chain_names if n in live]
        opts: dict[str, dict] = {}
        for _ in range(min(self.chains_per, len(want_c))):
            n = want_c[self.chain_turn % len(want_c)]
            self.chain_turn += 1
            try:
                obj = self.api.get("/options-chain-v3", {"symbol": self.names[n]["ticker"], "strikecount": CHAIN_STRIKES})
                self.stats["chain_calls"] = self.stats.get("chain_calls", 0) + 1
            except (Blocked, Refused):
                raise
            except Exception:                                         # noqa: BLE001
                self.stats["errors"] += 1
                continue
            got, odd = parse_chain(obj, self.names[n]["under"] if "under" in self.names[n] else n.rsplit("-", 1)[0], "mopt" if self.names[n]["seg"] == "mcx" else "copt")
            self._note(odd)
            opts.update(got)
        for name, q in opts.items():                                  # an option is pushed when it moved, like everything else
            key = {k: v for k, v in q.items() if k != "t"}
            if self.last_opt.get(name) != key:
                self.last_opt[name] = key
                self.pusher.update(name, q)
                self.stats["options_pushed"] = self.stats.get("options_pushed", 0) + 1
        sent = 0
        for n, q in quotes.items():
            full = {**q, "s": self.names[n]["seg"], "e": self.names[n]["expiry"].isoformat()}      # the contract: a paper position records which month it holds
            if n in self.oi:
                full["oi"] = self.oi[n]                               # open interest moves slowly: the last one read stands between depth turns
            key = {k: v for k, v in full.items() if k != "t"}
            book = fresh.get(n)
            new_book = book is not None and book.get("d") != self.last_book.get(n)
            if self.last.get(n) == key and not new_book:
                continue                                              # nothing changed: no push, so a quiet market shows as an ageing price, not a fresh one
            self.last[n] = key
            if book is not None:                                      # the ladder and the bid/offer from the same book, read moments after the quote
                full.update({k: v for k, v in book.items() if k in ("d", "bid", "ask", "bid_qty", "ask_qty")})
                self.last_book[n] = book.get("d")
            self.pusher.update(n, full)
            sent += 1
        self.stats["cycles"] += 1
        self.stats["quotes"] += len(quotes)
        self.stats["pushed"] += sent
        return sent


def depth_watch(watchlist: dict) -> list[str]:
    """The desk names of the owner's watchlist commodities and currencies (config desk.watchlist)."""
    out = []
    for key, suffix in (("commodities", "MCX"), ("currencies", "CDS")):
        for x in (watchlist or {}).get(key) or []:
            n = str(x).strip().upper()
            if n:
                out.append(f"{n}-{suffix}")
    return out


def _at(hhmm: str, day: dt.date) -> dt.datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), IST)


def run(until: str, app_id: str, token: str, pusher, watchlist: dict | None = None, opener=None, now=lambda: dt.datetime.now(IST),
        sleep=time.sleep, interval: float = INTERVAL_S) -> dict:
    """Stream until `until` (HH:MM IST). Returns the run's counts (no price, no token)."""
    start = now()
    stop = _at(until, start.date())
    contracts, notes = load_contracts(opener)
    names = near_futures(contracts, start.date())
    rep = {"day": str(start.date()), "contracts": len(names), "notes": notes, "stopped": "until"}
    if not names:
        rep["stopped"] = "no contracts"
        return rep
    feed = FyersFeed(FyersData(app_id, token, opener=opener), names, depth_watch(watchlist or {}), pusher, now=now)
    first = min(a for a, _ in SESSIONS.values())
    if now().time() < first:                                          # before the open: sleep to it instead of polling a closed market
        wait = (dt.datetime.combine(start.date(), first, IST) - now()).total_seconds()
        if wait > 0:
            sleep(wait)
    pusher.start()
    try:
        while now() < stop:
            t0 = time.monotonic()
            try:
                feed.cycle()
            except Blocked:
                rep["stopped"] = "blocked by Fyers (HTTP 429): stopped for the day"
                break
            except Refused:
                rep["stopped"] = "Fyers refused today's token"
                break
            if all(now().time() > b for _, b in SESSIONS.values()):
                rep["stopped"] = "every session closed"
                break
            sleep(max(0.0, interval - (time.monotonic() - t0)))
    finally:
        pusher.stop()
    rep.update({k: v for k, v in feed.stats.items()}, calls=feed.api.calls, push=pusher.stats())
    return rep


class CountingPusher:
    """A pusher that sends nothing: it counts what a real one would have sent (the login check)."""

    def __init__(self):
        self.n, self.names = 0, set()

    def update(self, symbol: str, quote: dict | None) -> None:
        if quote:
            self.n += 1
            self.names.add(symbol)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def stats(self) -> dict:
        return {"would_push": self.n, "instruments": len(self.names)}


def check(app_id: str, token: str, watchlist: dict | None = None, opener=None, today: dt.date | None = None) -> dict:
    """ONE round against Fyers with today's token, sending nothing anywhere: proves the login, the instrument list, the quotes, a book and the option chains before
    the first real session (owner, 14 Nov 2026: "Confirm the broker integration status"). The clock is held at midday so every contract counts as open: on a weekend
    Fyers answers with the last prices. Returns counts only (no price, no token)."""
    day = today or dt.datetime.now(IST).date()
    contracts, notes = load_contracts(opener)
    names = near_futures(contracts, day)
    rep = {"day": str(day), "contracts": len(names), "notes": notes}
    if not names:
        rep["result"] = "no MCX or currency futures in Fyers' instrument list"
        return rep
    noon = dt.datetime.combine(day, dt.time(12, 0), IST)
    pusher = CountingPusher()
    feed = FyersFeed(FyersData(app_id, token, opener=opener), names, depth_watch(watchlist or {}), pusher, now=lambda: noon)
    try:
        feed.cycle()
        rep["result"] = "ok" if pusher.n else "logged in, but no quote came back"
    except Refused:
        rep["result"] = "Fyers refused the token"
    except Blocked:
        rep["result"] = "blocked by Fyers (HTTP 429)"
    c = feed.api.calls
    rep.update(feed.stats, calls=c if isinstance(c, int) else len(c), **pusher.stats())
    return rep
