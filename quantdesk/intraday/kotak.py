"""Kotak Neo market data for the desk: live option bid/ask, option chains, expiries and 1-minute candles.

Uses only the Trade API endpoints that authenticate with the app's consumer key alone (the `Authorization`
header): quotes, option chain, expiries and historical candles. So: no TOTP, no MPIN, no daily login, and no
static IP. SEBI's static-IP rule (in force from 1 Apr 2026) covers the order APIs, which this module never
calls: the desk stays a paper desk, and prices its paper fills off Kotak's live order book.

Endpoints and response shapes follow Kotak's official SDK (github.com/Kotak-Neo/kotak-neo-python 3.0.x,
docs/functions/market_data). Limits from those docs: quotes take at most 50 instruments a call and the API
allows 25 requests a second; 1-minute candles go back 30 days.

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

from .chains import COLUMNS, ChainSource, IntradayPricer, fill_iv
from .feeds import IST, YahooIntradayFeed, normalise_bars, session_bounds

BASE = "https://mis.kotaksecurities.com"
QUOTES_PER_CALL = 50
# indices are quoted by name on the cash segment (Kotak's SFeed/quotes docs)
INDEX = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "FINNIFTY": "Nifty Fin Service",
         "MIDCPNIFTY": "NIFTY MID SELECT", "INDIAVIX": "INDIA VIX", "SENSEX": "SENSEX"}


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


def best(q: dict, side: str) -> float:
    """Best bid ('buy') or offer ('sell') from a quote's 5-level depth; NaN when the book is empty."""
    lv = ((q.get("depth") or {}).get(side) or [{}])[0] or {}
    v = _f(lv.get("price"))
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
            r = self.s.get(f"{self.base}/{path}", params=params, timeout=self.timeout)
            self._last = time.monotonic()
            self.calls[what] += 1
            if r.status_code == 429 and attempt == 0:
                ra = _f(r.headers.get("Retry-After"))
                time.sleep(min(5.0, ra if ra > 0 else 1.0))
                continue
            break
        try:
            body = r.json()
        except ValueError:
            raise KotakError(f"{what}: HTTP {r.status_code}, not JSON: {r.text[:200]!r}") from None
        err = _error(body)
        if r.status_code != 200 or err:
            raise KotakError(f"{what}: HTTP {r.status_code}: {err or str(body)[:200]}")
        return body

    # ---- endpoints -----------------------------------------------------------------------------------------
    def quotes(self, instruments: list[tuple[str, str]], kind: str = "all") -> list[dict]:
        """[(segment, token)] → quote dicts (ltp, 5-level depth, volume, OI, …), 50 instruments a call."""
        out: list[dict] = []
        for i in range(0, len(instruments), QUOTES_PER_CALL):
            batch = ",".join(f"{seg}|{tok}" for seg, tok in instruments[i:i + QUOTES_PER_CALL])
            body = self._get(f"script-details/1.0/quotes/neosymbol/{urllib.parse.quote(batch, safe='|,')}/{kind}")
            rows = body if isinstance(body, list) else (body.get("data") if isinstance(body, dict) else None) or []
            out += [q for q in rows if isinstance(q, dict)]
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
        body = self._get("market-data/1.0/watchlist/option-chain", p)
        return body.get("data") or {}

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

    def __init__(self, client: KotakClient, strikes: int = 40, refresh_min: int = 1):
        self.k = client
        self.count = max(10, int(round(strikes / 10)) * 10)       # the API wants a multiple of 10
        self.refresh_min = refresh_min
        self.tokens: dict[tuple, str] = {}                        # (underlying, expiry, strike, right) → "nse_fo|71472"
        self.lot: dict[str, int] = {}
        self._exp: dict[str, tuple[dt.date, list[dt.date]]] = {}

    def expiries(self, underlying: str) -> list[dt.date]:
        today = pd.Timestamp.now(tz=IST).date()
        hit = self._exp.get(underlying)
        if hit and hit[0] == today:
            return hit[1]
        exps = self.k.expiries(underlying)
        if not exps:
            raise KotakError(f"no expiries for {underlying}")
        self._exp[underlying] = (today, exps)
        return exps

    def chain(self, underlying: str, expiry: dt.date, spot=None, ts=None) -> pd.DataFrame:
        d = self.k.option_chain(underlying, expiry, self.count)
        common = d.get("common_data") or {}
        lot = _f(common.get("mktLot"))
        if lot > 0:
            self.lot[underlying] = int(lot)
        rows: dict[float, dict] = {}
        toks: dict[str, tuple[float, str]] = {}
        for side, key in (("ce", "call"), ("pe", "put")):
            for item in d.get(key) or []:
                ins = item.get("instrument") or item.get("inst") or {}
                K = _f(ins.get("strikePrice"))
                if not K > 0:
                    continue
                q, oi = item.get("quote") or {}, item.get("openInterest") or item.get("oi") or {}
                row = rows.setdefault(K, {c: np.nan for c in COLUMNS})
                row[f"{side}_ltp"] = _f(q.get("ltp"))
                row[f"{side}_vol"] = _f(q.get("volume", q.get("vol")))
                row[f"{side}_oi"] = _f(oi.get("current", oi.get("cur")))
                row[f"{side}_doi"] = _f(oi.get("change", oi.get("chg")))
                tok = str(ins.get("neoSymbol") or "")
                if "|" in tok:
                    toks[tok] = (K, side)
                    self.tokens[(underlying, expiry, K, side.upper())] = tok
        if not rows:
            raise KotakError(f"empty option chain for {underlying} {expiry}")
        want = [tuple(t.split("|", 1)) for t in toks]
        idx = INDEX.get(underlying)
        if idx:
            want.insert(0, ("nse_cm", idx))
        S, quoted = float("nan"), 0
        for q in self.k.quotes(want):
            seg, tok = str(q.get("exchange", "")), str(q.get("exchange_token", ""))
            if seg == "nse_cm":                                    # the only cash-segment name asked for: the index
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
                quoted += 1
            for col, v in ((f"{side}_ltp", _f(q.get("ltp"))), (f"{side}_vol", _f(q.get("last_volume"))),
                           (f"{side}_oi", _f(q.get("open_int")))):
                if v > 0:
                    row[col] = v
        if quoted == 0:
            raise KotakError(f"no bid/ask in Kotak's quotes for {underlying} {expiry} ({len(toks)} contracts asked)")
        df = pd.DataFrame.from_dict(rows, orient="index", columns=COLUMNS).astype(float).sort_index()
        df.index.name = "strike"
        if not S > 0:
            S = float(spot) if spot else np.nan
        df.attrs.update({"underlying": underlying, "spot": S, "expiry": expiry, "ts": pd.Timestamp.now(tz=IST),
                         "source": "kotak", "lot": self.lot.get(underlying)})
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
                return df if since is None else df[df.index > since]
            except Exception as exc:
                self.fails += 1
                self.last_error = f"{exc!s:.200}"
                if self.fails >= 5:
                    self.rest_until, self.fails = now + pd.Timedelta(minutes=15), 0
        self.served["yahoo"] += 1
        return super().poll(symbol, since)


# ---- what the key can see -----------------------------------------------------------------------------------------
def check(client: KotakClient, underlyings: list[str], say=print) -> bool:
    """Walk every endpoint the desk uses and say what came back. True when quotes and the chain both work."""
    ok_quotes = ok_chain = False
    now = pd.Timestamp.now(tz=IST)
    t0 = time.time()
    try:
        qs = client.quotes([("nse_cm", INDEX[u]) for u in underlyings + ["INDIAVIX"] if u in INDEX], "all")
        for q in qs:
            up = _f(q.get("lstup_time"))
            age = f"{(now.timestamp() - up) / 60:,.0f} min old" if up > 1e9 else "no timestamp"
            say(f"  quotes  {q.get('display_symbol') or q.get('exchange_token')!s:<22} ltp {_f(q.get('ltp')):>10,.2f}  ({age})")
        ok_quotes = bool(qs)
        if not qs:
            say("  quotes  FAIL: empty response for the indices")
    except Exception as exc:
        say(f"  quotes  FAIL {exc!s:.300}")
    for u in underlyings:
        ch = KotakOptionChain(client, strikes=20)
        try:
            exps = ch.expiries(u)
            say(f"  expiry  {u:<9} {', '.join(f'{e:%a %d-%b}' for e in exps[:4])}")
            exp = next(e for e in exps if e > now.date()) if any(e > now.date() for e in exps) else exps[0]
            df = ch.chain(u, exp)
            S = df.attrs["spot"]
            atm = df.index[int(np.abs(df.index.to_numpy() - (S if S == S else df.index.to_numpy().mean())).argmin())]
            r = df.loc[atm]
            quoted = int((df[["ce_bid", "pe_bid"]] > 0).sum().sum())
            say(f"  chain   {u:<9} {exp:%d-%b}: {len(df)} strikes, {quoted} quoted contracts, lot {df.attrs.get('lot')}, "
                f"spot {S:,.2f}")
            say(f"          ATM {atm:,.0f} CE {r.ce_bid:,.2f} / {r.ce_ask:,.2f} (IV {r.ce_iv:.1f}%) · "
                f"PE {r.pe_bid:,.2f} / {r.pe_ask:,.2f} (IV {r.pe_iv:.1f}%)")
            inst_sym = next(iter(ch.tokens.items()), None)
            if inst_sym:
                from ..core.types import Instrument
                (uu, ee, kk, rr), _ = inst_sym
                live = ch.live_quotes([Instrument.option(uu, ee, kk, rr, ch.lot.get(uu) or 1)])
                say(f"  live    {u:<9} {', '.join(f'{s} {b:,.2f}/{a:,.2f}' for s, (b, a) in live.items()) or 'FAIL: no live quote'}")
            ok_chain = True
        except Exception as exc:
            say(f"  chain   {u:<9} FAIL {exc!s:.300}")
    day = now.date()
    for back in range(6):                                          # today, or the last session with candles
        d = day - dt.timedelta(days=back)
        try:
            raw = client.candles(f"nse_cm|{INDEX['NIFTY']}", "1min", d, d)
        except Exception as exc:
            say(f"  candles NIFTY     FAIL {exc!s:.300} (live bars will come from Yahoo)")
            break
        if len(raw):
            say(f"  candles NIFTY     {d:%a %d-%b}: {len(raw)} one-minute bars, first {raw.index[0]:%H:%M}, "
                f"last {raw.index[-1]:%H:%M} close {raw['close'].iloc[-1]:,.2f}")
            break
    else:
        say("  candles NIFTY     no bars in the last 6 days (live bars will come from Yahoo)")
    say(f"  {sum(client.calls.values())} calls in {time.time() - t0:.1f}s: "
        + ", ".join(f"{k} {v}" for k, v in client.calls.items()))
    return ok_quotes and ok_chain
