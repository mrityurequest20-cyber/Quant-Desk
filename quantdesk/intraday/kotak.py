"""Kotak Neo market data for the desk: live option bid/ask, option chains, expiries and 1-minute candles.

Uses only the Trade API endpoints that authenticate with the app's consumer key alone (the `Authorization`
header): quotes, option chain, expiries and historical candles. So: no TOTP, no MPIN, no daily login, and no
static IP. SEBI's static-IP rule (in force from 1 Apr 2026) covers the order APIs, which this module never
calls: the desk stays a paper desk, and prices its paper fills off Kotak's live order book.

Endpoints follow Kotak's official SDK (github.com/Kotak-Neo/kotak-neo-python 3.0.x, docs/functions/market_data).
The live option chain answers in a compact shape the docs don't show (seen 2 Oct 2026): legs under "inst" with
"strkPrc", quotes as o/h/l/c/pc/vol, and OI as cur/prev/chg where "chg" is the *price* change. `count` is strikes
on each side of the money (20 → 41 strikes). Both shapes parse. Limits: the docs say 50 instruments a quotes
call (the live API took 25) and 25 requests a second; 1-minute candles go back 30 days.

Key: KOTAK_CONSUMER_KEY — Neo app or web → More → Trade API → generate an application → copy its token.
`python -m quantdesk intraday kotak-check` shows what the key can see."""
from __future__ import annotations

import datetime as dt
import os
import time
import urllib.parse
from collections import Counter

import numpy as np
import pandas as pd

from .chains import COLUMNS, DEPTH, ChainSource, IntradayPricer, fill_iv
from .feeds import IST, YahooIntradayFeed, normalise_bars, session_bounds

BASE = "https://mis.kotaksecurities.com"
QUOTES_PER_CALL = 25        # docs say 50, but the live API refused 50 on 2 Oct 2026 and took 25; halves on "max value"
# indices are quoted by name on the cash segment (Kotak's SFeed/quotes docs)
INDEX = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "FINNIFTY": "Nifty Fin Service",
         "MIDCPNIFTY": "NIFTY MID SELECT", "INDIAVIX": "INDIA VIX", "SENSEX": "SENSEX", "BANKEX": "BANKEX"}
BSE = {"SENSEX", "BANKEX"}                    # BSE's index options: bse_fo contracts, the index on bse_cm


def segments(underlying: str) -> tuple[str, str]:
    """(derivatives segment, cash segment) an underlying trades on at Kotak."""
    return ("bse_fo", "bse_cm") if underlying in BSE else ("nse_fo", "nse_cm")


def _fo(underlying: str) -> dict:
    """The exchange argument for a BSE underlying; NSE's is the endpoints' default."""
    return {"exchange": "bse_fo"} if underlying in BSE else {}


class KotakError(RuntimeError):
    pass


def _f(x) -> float:
    """Kotak sends numbers as strings ("166.7500"); missing values as None, "" or "-"."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v if np.isfinite(v) else float("nan")


def _error(body) -> str | None:
    """The error message in a Kotak response, or None. Errors come back in several shapes."""
    if not isinstance(body, dict):
        return None
    for k in ("Error", "error", "Error Message", "errMsg"):
        if body.get(k):
            e = body[k]
            if isinstance(e, list) and e and isinstance(e[0], dict):
                e = e[0].get("message", e[0])
            return str(e)
    if str(body.get("status", "")).upper() == "ERROR" or "fault" in body:
        f = body.get("fault") or {}
        return str(f.get("message") or f or body)
    if "data" not in body and "code" in body and "message" in body and str(body["code"]) not in ("200", "0"):
        return f"{body['code']}: {body['message']}"
    return None


def chain_parts(body) -> tuple[dict, list, list]:
    """(common data, calls, puts) from an option-chain response, wherever they sit (docs: under "data")."""
    todo = [body]
    while todo:
        x = todo.pop(0)
        if isinstance(x, dict):
            calls, puts = x.get("call", x.get("calls")), x.get("put", x.get("puts"))
            if isinstance(calls, list) or isinstance(puts, list):
                return x.get("common_data") or x.get("commonData") or {}, calls or [], puts or []
            todo += [v for v in x.values() if isinstance(v, (dict, list))]
        elif isinstance(x, list):
            todo += [v for v in x if isinstance(v, (dict, list))]
    return {}, [], []


def best(q: dict, side: str) -> float:
    """Best bid ('buy') or offer ('sell') from a quote's 5-level depth; NaN when the book is empty."""
    lv = ((q.get("depth") or {}).get(side) or [{}])[0] or {}
    v = _f(lv.get("price"))
    return v if v > 0 else float("nan")


def best_qty(q: dict, side: str) -> float:
    """The quantity (units, not lots) resting at the best bid ('buy') or offer ('sell'); NaN when unknown."""
    lv = ((q.get("depth") or {}).get(side) or [{}])[0] or {}
    v = _f(lv.get("quantity", lv.get("qty")))
    return v if v > 0 else float("nan")


class KotakClient:
    """The four consumer-key endpoints. Paces calls (well under 25/s) and retries a 429 once."""

    def __init__(self, consumer_key: str, session=None, base: str = BASE, timeout: float = 10.0, min_gap: float = 0.06):
        if not consumer_key:
            raise KotakError("no Kotak consumer key (set KOTAK_CONSUMER_KEY)")
        if session is None:
            import requests
            session = requests.Session()
        self.s = session
        self.s.headers.update({"Authorization": consumer_key, "accept": "application/json",
                               "Content-Type": "application/x-www-form-urlencoded"})
        self.base, self.timeout, self.min_gap = base.rstrip("/"), timeout, min_gap
        self._last = 0.0
        self.calls = Counter()
        self.last_body = None                                      # the last raw response, for kotak-check
        self.pct_query = False                                     # True: spaces as %20 and a literal "|" in queries
        self.batch = QUOTES_PER_CALL                               # quotes per call; halves when Kotak says "max value"

    @classmethod
    def from_env(cls, env=None, **kw) -> "KotakClient":
        env = os.environ if env is None else env
        return cls((env.get("KOTAK_CONSUMER_KEY") or "").strip(), **kw)

    def _get(self, path: str, params: dict | None = None):
        what = path.split("/")[0] if not path.startswith("script-details") else "quotes"
        for attempt in range(2):
            wait = self.min_gap - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            url = f"{self.base}/{path}"
            if params and self.pct_query:
                url += "?" + urllib.parse.urlencode(params, safe="|", quote_via=urllib.parse.quote)
                r = self.s.get(url, timeout=self.timeout)
            else:
                r = self.s.get(url, params=params, timeout=self.timeout)
            self._last = time.monotonic()
            self.calls[what] += 1
            if r.status_code in (429, 502, 503, 504) and attempt == 0:      # rate limit or a gateway blip: once more
                ra = _f(r.headers.get("Retry-After"))
                time.sleep(min(5.0, ra if ra > 0 else 1.0))
                continue
            break
        try:
            body = r.json()
        except ValueError:
            self.last_body = r.text[:2000]
            raise KotakError(f"{what}: HTTP {r.status_code}, not JSON: {r.text[:200]!r}") from None
        self.last_body = body
        err = _error(body)
        if r.status_code != 200 or err:
            raise KotakError(f"{what}: HTTP {r.status_code}: {err or str(body)[:200]}")
        return body

    # ---- endpoints -----------------------------------------------------------------------------------------
    def quotes(self, instruments: list[tuple[str, str]], kind: str = "all") -> list[dict]:
        """[(segment, token)] → quote dicts (ltp, 5-level depth, volume, OI, …), `self.batch` instruments a call."""
        out: list[dict] = []
        i = 0
        while i < len(instruments):
            chunk = instruments[i:i + self.batch]
            batch = ",".join(f"{seg}|{tok}" for seg, tok in chunk)
            try:
                body = self._get(f"script-details/1.0/quotes/neosymbol/{urllib.parse.quote(batch, safe='|,')}/{kind}")
            except KotakError as exc:
                if "max value" in str(exc).lower() and self.batch > 5:
                    self.batch = max(5, self.batch // 2)            # "Please set the Neo symbol max value to 50."
                    continue
                raise
            rows = body if isinstance(body, list) else (body.get("data") if isinstance(body, dict) else None) or []
            out += [q for q in rows if isinstance(q, dict)]
            i += len(chunk)
        return out

    def expiries(self, underlying: str, exchange: str = "nse_fo") -> list[dt.date]:
        body = self._get("market-data/1.0/watchlist/expiries", {"exchange": exchange, "underlying": underlying})
        raw = body.get("expiries") or (body.get("data") or {}).get("expiries") or []
        return sorted(dt.date.fromisoformat(str(x)[:10]) for x in raw)

    def option_chain(self, underlying: str, expiry: dt.date | None = None, count: int = 40,
                     exchange: str = "nse_fo") -> dict:
        p = {"exchange": exchange, "underlying": underlying, "instrument_type": "option", "count": int(count)}
        if expiry is not None:
            p["expiry"] = expiry.isoformat()
        return self._get("market-data/1.0/watchlist/option-chain", p)

    def candles(self, neosymbol: str, interval: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        """[timestamp, open, high, low, close, volume, oi] rows → bars indexed in IST (bar start)."""
        body = self._get("market-data/1.0/historical/details", {"neosymbol": neosymbol, "interval": interval,
                                                                "fromdate": start.isoformat(), "todate": end.isoformat()})
        rows = (body.get("data") or {}).get("candles") or []
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = pd.DataFrame([r[:6] for r in rows], columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df.pop("ts"), utc=True).dt.tz_convert(IST)
        return df.apply(pd.to_numeric, errors="coerce")


# ---- the option chain, from Kotak's live book ---------------------------------------------------------------
class KotakOptionChain(ChainSource):
    """Strikes and tokens from Kotak's option chain, then each contract's live bid/ask (and the index, so spot
    and the quotes are from the same instant) from the quotes endpoint: ~3 calls per underlying per refresh."""
    name = "kotak"

    def __init__(self, client: KotakClient, strikes: int = 20, refresh_min: int = 1):
        self.k = client
        self.count = max(10, int(round(strikes / 10)) * 10)       # strikes each side; the API wants a multiple of 10
        self.refresh_min = refresh_min
        self.tokens: dict[tuple, str] = {}                        # (underlying, expiry, strike, right) → "nse_fo|71472"
        self.lot: dict[str, int] = {}
        self._exp: dict[str, tuple[dt.date, list[dt.date]]] = {}

    def expiries(self, underlying: str) -> list[dt.date]:
        today = pd.Timestamp.now(tz=IST).date()
        hit = self._exp.get(underlying)
        if hit and hit[0] == today:
            return hit[1]
        exps = self.k.expiries(underlying, **_fo(underlying))
        if not exps:
            raise KotakError(f"no expiries for {underlying}")
        self._exp[underlying] = (today, exps)
        return exps

    def chain(self, underlying: str, expiry: dt.date, spot=None, ts=None, require_quotes: bool = True) -> pd.DataFrame:
        """`require_quotes`: no bid/ask anywhere is an error (in the session the desk can't price fills without one;
        outside it the book is simply empty)."""
        common, calls, puts = chain_parts(self.k.option_chain(underlying, expiry, self.count, **_fo(underlying)))
        lot = _f(common.get("mktLot"))
        if lot > 0:
            self.lot[underlying] = int(lot)
        rows: dict[float, dict] = {}
        toks: dict[str, tuple[float, str]] = {}
        for side, items in (("ce", calls), ("pe", puts)):
            for item in items:
                ins = item.get("instrument") or item.get("inst") or {}
                K = _f(ins.get("strikePrice", ins.get("strkPrc")))
                if not K > 0:
                    continue
                q, oi = item.get("quote") or {}, item.get("openInterest") or item.get("oi") or {}
                row = rows.setdefault(K, {c: np.nan for c in COLUMNS + DEPTH})
                row[f"{side}_ltp"] = _f(q.get("ltp"))
                row[f"{side}_vol"] = _f(q.get("volume", q.get("vol")))
                cur, prev = _f(oi.get("current", oi.get("cur"))), _f(oi.get("previous", oi.get("prev")))
                row[f"{side}_oi"] = cur
                # the live API's compact "oi.chg" carries the *price* change (ltp − prev close), so take current − previous
                row[f"{side}_doi"] = cur - prev if cur == cur and prev == prev else _f(oi.get("change"))
                tok = str(ins.get("neoSymbol") or "")
                if "|" in tok:
                    toks[tok] = (K, side)
                    self.tokens[(underlying, expiry, K, side.upper())] = tok
        if not rows:
            raise KotakError(f"empty option chain for {underlying} {expiry}")
        want = [tuple(t.split("|", 1)) for t in toks]
        idx, cash = INDEX.get(underlying), segments(underlying)[1]
        if idx:
            want.insert(0, (cash, idx))
        S, quoted = float("nan"), 0
        for q in self.k.quotes(want):
            seg, tok = str(q.get("exchange", "")), str(q.get("exchange_token", ""))
            if seg == cash:                                        # the only cash-segment name asked for: the index
                S = _f(q.get("ltp"))
                continue
            hit = toks.get(f"{seg}|{tok}")
            if hit is None:
                continue
            K, side = hit
            row = rows[K]
            b, a = best(q, "buy"), best(q, "sell")
            if b > 0 and a >= b:
                row[f"{side}_bid"], row[f"{side}_ask"] = b, a
                row[f"{side}_bidq"], row[f"{side}_askq"] = best_qty(q, "buy"), best_qty(q, "sell")
                quoted += 1
            for col, v in ((f"{side}_ltp", _f(q.get("ltp"))), (f"{side}_vol", _f(q.get("last_volume"))),
                           (f"{side}_oi", _f(q.get("open_int")))):
                if v > 0:
                    row[col] = v
        if quoted == 0 and require_quotes:
            raise KotakError(f"no bid/ask in Kotak's quotes for {underlying} {expiry} ({len(toks)} contracts asked)")
        df = pd.DataFrame.from_dict(rows, orient="index", columns=COLUMNS + DEPTH).astype(float).sort_index()
        df.index.name = "strike"
        if not S > 0:
            S = float(spot) if spot else np.nan
        df.attrs.update({"underlying": underlying, "spot": S, "expiry": expiry,
                         "ts": pd.Timestamp(ts) if ts is not None else pd.Timestamp.now(tz=IST),
                         "source": "kotak", "lot": self.lot.get(underlying), "quoted": quoted})
        return fill_iv(df, IntradayPricer())

    def live_quotes(self, instruments) -> dict[str, tuple[float, float]]:
        """Bid/ask right now for contracts seen in an earlier chain: {symbol: (bid, ask)}."""
        want: dict[str, str] = {}
        for inst in instruments:
            tok = self.tokens.get((inst.underlying, inst.expiry, float(inst.strike), inst.right))
            if tok:
                want[tok] = inst.symbol
        if not want:
            return {}
        out = {}
        for q in self.k.quotes([tuple(t.split("|", 1)) for t in want]):
            sym = want.get(f"{q.get('exchange')}|{q.get('exchange_token')}")
            b, a = best(q, "buy"), best(q, "sell")
            if sym and b > 0 and a >= b:
                out[sym] = (b, a)
        return out


# ---- futures ------------------------------------------------------------------------------------------------------
class KotakFutures:
    """Index and stock futures on Kotak (verified on a runner, 3 Oct 2026): every expiry from the chain endpoint's
    `instrument_type=fut` view (token, LTP, OHLC, OI; its `oi.chg` is the price change, as on the option chain),
    and 1-minute candles with real volume by token (`nse_fo|<token>`; no OI in candles). The contract used is the
    near month, rolled to the next one `roll_days` before expiry, when the volume moves."""

    def __init__(self, client: KotakClient, roll_days: int = 3):
        self.k, self.roll_days = client, roll_days
        self._c: dict[str, tuple] = {}

    def contracts(self, underlying: str) -> list[dict]:
        body = self.k._get("market-data/1.0/watchlist/option-chain",
                           {"exchange": "nse_fo", "underlying": underlying, "instrument_type": "fut", "count": 10})
        rows = body.get("future_contracts") or (body.get("data") or {}).get("future_contracts") or []
        out = []
        for r in rows:
            inst, q, oi = r.get("inst") or {}, r.get("quote") or {}, r.get("oi") or {}
            try:
                exp = dt.date.fromisoformat(str(inst.get("exp"))[:10])
            except ValueError:
                continue
            out.append({"token": str(inst.get("neoSymbol") or ""), "symbol": str(inst.get("symbol") or ""), "expiry": exp,
                        "ltp": _f(q.get("ltp")), "open": _f(q.get("o")), "high": _f(q.get("h")), "low": _f(q.get("l")),
                        "close": _f(q.get("c")), "prev_close": _f(q.get("pc")), "volume": _f(q.get("vol")),
                        "oi": _f(oi.get("cur")), "oi_prev": _f(oi.get("prev"))})
        if not out:
            raise KotakError(f"no futures for {underlying}")
        return sorted(out, key=lambda c: c["expiry"])

    def active(self, underlying: str, today: dt.date, fresh: list[dict] | None = None) -> dict:
        hit = self._c.get(underlying)
        cs = fresh or (hit[1] if hit and hit[0] == today else None) or self.contracts(underlying)
        self._c[underlying] = (today, cs)
        live = [c for c in cs if (c["expiry"] - today).days >= self.roll_days] or cs
        return live[0]

    def snapshot(self, underlying: str, today: dt.date) -> dict:
        """The active contract right now (LTP, OI), plus the next one for the term structure."""
        cs = self.contracts(underlying)
        a = self.active(underlying, today, cs)
        nxt = next((c for c in cs if c["expiry"] > a["expiry"]), None)
        return {**a, "next": nxt}

    def bars(self, underlying: str, start: dt.date, end: dt.date) -> pd.DataFrame:
        a = self.active(underlying, end)
        return normalise_bars(self.k.candles(a["token"], "1min", start, end))


# ---- 1-minute bars ------------------------------------------------------------------------------------------------
class KotakIntradayFeed(YahooIntradayFeed):
    """Live 1-minute index bars from Kotak's candles; any minute Kotak can't serve, Yahoo serves. History stays
    on Yahoo: longer, and what the research and the models were built on. After 5 failures in a row Kotak is
    rested for 15 minutes so a broken endpoint costs one wasted call a minute at most."""

    @property
    def name(self) -> str:
        """What actually served the bars (the review and the site show it)."""
        k, y = self.served["kotak"], self.served["yahoo"]
        if y and not k:
            return "yahoo (no kotak)"
        return f"kotak+yahoo ({y} of {k + y} polls from Yahoo)" if y else "kotak"

    def __init__(self, cfg, client: KotakClient):
        super().__init__(cfg)
        self.k = client
        self.fails = 0
        self.rest_until: pd.Timestamp | None = None
        self.served: Counter = Counter()
        self.last_error = ""
        self.fut = KotakFutures(client, int(cfg.get("intraday.futures.roll_days", 3) or 3))
        self.fut_bars: dict[str, pd.DataFrame] = {}
        self.fut_error = ""

    has_futures = True

    def _with_futures(self, symbol: str, df: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
        """The index bars with each minute's near-month futures volume on them (an index has none of its own), and
        the futures' own bars kept for the chart. On any failure the bars go back unchanged."""
        if df is None or df.empty or symbol not in INDEX or symbol == "INDIAVIX":
            return df
        try:
            fb = self.completed(self.fut.bars(symbol, start, end))
            self.fut_error = ""
        except Exception as exc:
            self.fut_error = f"{exc!s:.200}"
            return df
        if fb.empty:
            return df
        old = self.fut_bars.get(symbol)
        self.fut_bars[symbol] = fb if old is None or old.empty else \
            pd.concat([old, fb])[lambda x: ~x.index.duplicated(keep="last")].sort_index()
        out = df.copy()
        out["volume"] = fb["volume"].reindex(out.index).fillna(0.0).to_numpy(dtype=float)
        return out

    def history(self, symbol, days=5):
        h = super().history(symbol, days)
        if h is None or h.empty or symbol not in INDEX:
            return h
        return self._with_futures(symbol, h, h.index[0].date(), h.index[-1].date())

    has_ltp = True

    def ltp(self, symbols) -> dict[str, float]:
        """Each index's last traded price right now (one quotes call per index), for the engine's fast loop:
        armed entries fire and stops are checked on it every few seconds instead of once a minute."""
        out = {}
        for s in symbols:
            name = INDEX.get(s)
            for q in (self.k.quotes([("nse_cm", name)]) if name else []):
                p = _f(q.get("ltp"))
                if p == p and p > 0:
                    out[s] = p
        return out

    def kotak_bars(self, symbol: str, day: dt.date) -> pd.DataFrame:
        idx = INDEX.get(symbol)
        if idx is None:
            raise KotakError(f"no Kotak index name for {symbol}")
        return self.completed(normalise_bars(self.k.candles(f"nse_cm|{idx}", "1min", day, day)))

    def poll(self, symbol, since):
        now = self.now()
        if symbol in INDEX and (self.rest_until is None or now >= self.rest_until):
            try:
                df = self.kotak_bars(symbol, now.date())
                if df.empty and now >= session_bounds(now.date())[0] + pd.Timedelta(minutes=2):
                    raise KotakError("no candles yet for today")
                self.fails = 0
                self.served["kotak"] += 1
                df = self._with_futures(symbol, df, now.date(), now.date())
                return df if since is None else df[df.index > since]
            except Exception as exc:
                self.fails += 1
                self.last_error = f"{exc!s:.200}"
                if self.fails >= 5:
                    self.rest_until, self.fails = now + pd.Timedelta(minutes=15), 0
        self.served["yahoo"] += 1
        df = super().poll(symbol, since)
        return self._with_futures(symbol, df, now.date(), now.date()) if df is not None and len(df) else df


# ---- the scrip master ---------------------------------------------------------------------------------------------
def scrip_master(client: KotakClient, name: str = "nse_fo") -> pd.DataFrame:
    """One of Kotak's scrip-master CSVs (`nse_fo`, `nse_cm`, …; the file names carry a suffix like nse_cm-v1.csv) as a
    frame with clean column names. The file URLs come from the API; the files themselves download without the key."""
    import io
    body = client._get("script-details/1.0/masterscrip/file-paths")
    files = (body.get("data") or {}).get("filesPaths") or []
    url = next((f for f in files if f.rsplit("/", 1)[-1].split(".")[0].split("-")[0] == name), None)
    if not url:
        raise KotakError(f"no {name} file in the scrip master ({len(files)} files)")
    r = client.s.get(url, timeout=60, headers={"Authorization": ""})
    if r.status_code != 200:
        r = client.s.get(url, timeout=60)
    if r.status_code != 200 or len(r.content) < 1000:
        raise KotakError(f"scrip master {name}: HTTP {r.status_code}, {len(r.content)} bytes")
    df = pd.read_csv(io.BytesIO(r.content), low_memory=False)
    df.columns = [str(c).strip().rstrip(";") for c in df.columns]
    return df


# ---- what the key can see -----------------------------------------------------------------------------------------
def _raw(x, n: int = 700) -> str:
    import json
    try:
        t = json.dumps(x, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        t = str(x)
    return t[:n] + ("…" if len(t) > n else "")


def check(client: KotakClient, underlyings: list[str], say=print) -> bool:
    """Walk every endpoint the desk uses and say what came back (raw shapes too, when something looks off).
    True when quotes and the chain both work."""
    ok_quotes = ok_chain = False
    now = pd.Timestamp.now(tz=IST)
    t0 = time.time()
    index_tokens: dict[str, str] = {}
    try:
        qs = client.quotes([(segments(u)[1], INDEX[u]) for u in underlyings + ["INDIAVIX"] if u in INDEX], "all")
        for q in qs:
            up = _f(q.get("lstup_time"))
            age = f"{(now.timestamp() - up) / 60:,.0f} min old" if up > 1e9 else "no timestamp"
            say(f"  quotes  {q.get('display_symbol') or q.get('exchange_token')!s:<22} ltp {_f(q.get('ltp')):>10,.2f}  "
                f"({age}; token {q.get('exchange_token')!r})")
            index_tokens[str(q.get("display_symbol", ""))] = str(q.get("exchange_token", ""))
        if qs:
            say(f"          fields: {', '.join(sorted(qs[0]))}")
        ok_quotes = bool(qs)
        if not qs:
            say(f"  quotes  FAIL: empty response for the indices · raw {_raw(client.last_body)}")
    except Exception as exc:
        say(f"  quotes  FAIL {exc!s:.300}")
    o, c = session_bounds(now.date())
    market_open = now.weekday() < 5 and o <= now <= c
    if not market_open:
        say(f"  (market closed at {now:%a %H:%M} IST: option bids/asks may be empty; the desk needs them only in the session)")
    for u in underlyings:
        ch = KotakOptionChain(client, strikes=20)
        try:
            exps = ch.expiries(u)
            say(f"  expiry  {u:<9} {', '.join(f'{e:%a %d-%b}' for e in exps[:4])}")
            exp = next((e for e in exps if e > now.date()), exps[0])
        except Exception as exc:
            say(f"  expiry  {u:<9} FAIL {exc!s:.300}")
            continue
        try:
            df = ch.chain(u, exp, require_quotes=market_open)
        except Exception as exc:
            say(f"  chain   {u:<9} FAIL {exc!s:.200}")
            say(f"          raw: {_raw(client.last_body)}")
            # what does the endpoint give with fewer parameters?
            for label, kw in (("nearest expiry", {"expiry": None}), ("count 40", {"count": 40})):
                try:
                    body = client.option_chain(u, kw.get("expiry", exp), kw.get("count", 20))
                    c, calls, puts = chain_parts(body)
                    say(f"          {label}: {len(calls)} calls, {len(puts)} puts · raw {_raw(body, 400)}")
                except Exception as exc2:
                    say(f"          {label}: FAIL {exc2!s:.200}")
            continue
        S = df.attrs["spot"]
        atm = df.index[int(np.abs(df.index.to_numpy() - (S if S == S else df.index.to_numpy().mean())).argmin())]
        r = df.loc[atm]
        quoted = int((df[["ce_bid", "pe_bid"]] > 0).sum().sum())
        say(f"  chain   {u:<9} {exp:%d-%b}: {len(df)} strikes, {quoted} quoted contracts, lot {df.attrs.get('lot')}, "
            f"spot {S:,.2f}")
        say(f"          ATM {atm:,.0f} CE {r.ce_bid:,.2f} / {r.ce_ask:,.2f} (IV {r.ce_iv:.1f}%) · "
            f"PE {r.pe_bid:,.2f} / {r.pe_ask:,.2f} (IV {r.pe_iv:.1f}%)")
        from ..core.types import Instrument
        live = ch.live_quotes([Instrument.option(u, exp, float(atm), r_, ch.lot.get(u) or 1) for r_ in ("CE", "PE")])
        say(f"  live    {u:<9} {', '.join(f'{s} {b:,.2f}/{a:,.2f}' for s, (b, a) in live.items()) or 'no bid/ask right now'}")
        ok_chain = True
    # candles: the last week in one call; try the index by name, by its quote token, and two encodings
    start, end = now.date() - dt.timedelta(days=7), now.date()
    names = [f"nse_cm|{INDEX['NIFTY']}"]
    tok = next((t for k, t in index_tokens.items() if "nifty 50" in k.lower()), "")
    if tok and tok != INDEX["NIFTY"]:
        names.append(f"nse_cm|{tok}")
    worked = None
    for sym in names:
        for pct in (False, True):
            client.pct_query = pct
            try:
                raw = client.candles(sym, "1min", start, end)
            except Exception as exc:
                say(f"  candles {sym:<16} {'%20' if pct else '+  '} FAIL {exc!s:.160}")
                continue
            if len(raw):
                say(f"  candles {sym:<16} {'%20' if pct else '+  '} {len(raw)} one-minute bars, {raw.index[0]:%d-%b %H:%M} → "
                    f"{raw.index[-1]:%d-%b %H:%M}, last close {raw['close'].iloc[-1]:,.2f}")
                worked = worked or (sym, pct)
            else:
                say(f"  candles {sym:<16} {'%20' if pct else '+  '} no bars · raw {_raw(client.last_body, 300)}")
    client.pct_query = bool(worked and worked[1])
    if not worked:
        say("  candles none worked: live bars will come from Yahoo")
    futures_probe(client, underlyings[:1] or ["NIFTY"], now, say)
    breadth_probe(client, say)
    say(f"  quotes per call: {client.batch}")
    say(f"  {sum(client.calls.values())} calls in {time.time() - t0:.1f}s: "
        + ", ".join(f"{k} {v}" for k, v in client.calls.items()))
    return ok_quotes and ok_chain


def breadth_probe(client: KotakClient, say=print) -> int:
    """Index breadth's inputs (breadth.py): cash tokens from the F&O scrip master, then the fields it reads from each
    stock's quote. Returns how many of the NIFTY 50 (built-in list) have a token."""
    from .breadth import NIFTY50, cash_tokens, quote_row
    try:
        toks = cash_tokens(scrip_master(client, "nse_fo"), NIFTY50)
    except Exception as exc:
        say(f"  breadth FAIL scrip master: {exc!s:.200}")
        return 0
    miss = sorted(set(NIFTY50) - set(toks))
    say(f"  breadth tokens for {len(toks)} of {len(NIFTY50)} NIFTY 50 stocks" + (f"; none for {', '.join(miss)}" if miss else ""))
    pick = [s_ for s_ in ("RELIANCE", "HDFCBANK", "M&M", "BAJAJ-AUTO") if s_ in toks]
    try:
        for q in client.quotes([("nse_cm", toks[s_]) for s_ in pick], "all"):
            say(f"    nse_cm|{q.get('exchange_token')} {q.get('display_symbol')}: ltp {q.get('ltp')} change {q.get('change')} "
                f"per_change {q.get('per_change')} avg_cost {q.get('avg_cost')} ohlc {q.get('ohlc')} → {quote_row(q)}")
    except Exception as exc:
        say(f"  breadth FAIL quotes: {exc!s:.200}")
    return len(toks)


def futures_probe(client: KotakClient, underlyings, now, say=print) -> dict:
    """Index futures from Kotak: tokens from the scrip master, then live quotes (volume, OI) and 1-minute candles by
    token; also the raw `fut` chain response and a liquid stock (cash and options), for the stock universe."""
    import io
    found: dict = {}
    try:
        body = client._get("script-details/1.0/masterscrip/file-paths")
        files = (body.get("data") or {}).get("filesPaths") or []
        say(f"  scrip master: {len(files)} files: {', '.join(f.rsplit('/', 1)[-1] for f in files)}")
    except Exception as exc:
        say(f"  scrip master: FAIL {exc!s:.200}")
        files = []
    master = {}
    for name in ("nse_fo.csv", "nse_cm.csv"):
        url = next((f for f in files if f.endswith("/" + name)), None)
        if not url:
            continue
        for auth in (False, True):
            try:
                r = client.s.get(url, timeout=60, **({} if auth else {"headers": {"Authorization": ""}}))
                say(f"  {name}: HTTP {r.status_code}, {len(r.content) / 1e6:.1f} MB (auth {'on' if auth else 'off'})")
                if r.status_code == 200 and len(r.content) > 1000:
                    df = pd.read_csv(io.BytesIO(r.content), low_memory=False)
                    df.columns = [str(c).strip().rstrip(";") for c in df.columns]
                    master[name] = df
                    say(f"    columns: {', '.join(df.columns[:40])}")
                    break
            except Exception as exc:
                say(f"  {name}: FAIL {exc!s:.200}")
    fo = master.get("nse_fo.csv")
    if fo is not None:
        cols = {c.lower(): c for c in fo.columns}
        sym_col = next((cols[c] for c in ("psymbolname", "psymbol_name", "symbolname") if c in cols), None)
        typ_col = next((cols[c] for c in ("pinsttype", "instrumenttype", "pinst_type") if c in cols), None)
        for u in list(underlyings) + ["BANKNIFTY", "RELIANCE"]:
            rows = fo[(fo[sym_col].astype(str).str.upper() == u)] if sym_col else fo.head(0)
            futs = rows[rows[typ_col].astype(str).str.upper().str.startswith("FUT")] if typ_col is not None else rows.head(0)
            say(f"  {u} futures rows: {len(futs)}")
            for _, row in futs.head(3).iterrows():
                say(f"    {dict((k, row[k]) for k in fo.columns[:25])}")
            if len(futs):
                tokc = next((cols[c] for c in ("psymbol", "ptoken", "token") if c in cols), fo.columns[0])
                tok = str(futs.iloc[0][tokc]).split(".")[0]
                found.setdefault("tokens", {})[u] = tok
                try:
                    q = (client.quotes([("nse_fo", tok)]) or [{}])[0]
                    say(f"    quote nse_fo|{tok}: ltp {q.get('ltp')} last_volume {q.get('last_volume')} "
                        f"oi {q.get('open_int')} ohlc {q.get('ohlc')} lstup {q.get('lstup_time')}")
                except Exception as exc:
                    say(f"    quote nse_fo|{tok}: FAIL {exc!s:.200}")
                try:
                    raw = client.candles(f"nse_fo|{tok}", "1min", now.date() - dt.timedelta(days=5), now.date())
                    body = client.last_body
                    first = ((body.get("data") or {}).get("candles") or [[]])[:2] if isinstance(body, dict) else None
                    say(f"    candles nse_fo|{tok}: {len(raw)} bars, volume sum {raw['volume'].sum() if len(raw) else 0:,.0f}; "
                        f"raw rows {first}")
                    if len(raw):
                        found["candles"] = "nse_fo|<token>"
                except Exception as exc:
                    say(f"    candles nse_fo|{tok}: FAIL {exc!s:.200}")
    cm = master.get("nse_cm.csv")
    if cm is not None:
        cols = {c.lower(): c for c in cm.columns}
        for c in ("ptrdsymbol", "psymbolname"):
            if c in cols:
                hit = cm[cm[cols[c]].astype(str).str.upper().isin(["RELIANCE-EQ", "RELIANCE"])]
                say(f"  nse_cm RELIANCE rows by {c}: {len(hit)} · {hit.head(2).to_dict('records')}")
    try:
        body = client._get("market-data/1.0/watchlist/option-chain", {"exchange": "nse_fo", "underlying": "NIFTY",
                                                                       "instrument_type": "fut", "count": 10})
        say(f"  chain instrument_type=fut raw: {_raw(body, 900)}")
    except Exception as exc:
        say(f"  chain instrument_type=fut: FAIL {exc!s:.200}")
    try:
        exps = client.expiries("RELIANCE")
        say(f"  RELIANCE option expiries: {[str(e) for e in exps[:3]]}")
    except Exception as exc:
        say(f"  RELIANCE option expiries: FAIL {exc!s:.200}")
    say(f"  futures verdict: {found or 'nothing worked'}")
    return found
