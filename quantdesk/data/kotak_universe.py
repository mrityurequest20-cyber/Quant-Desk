"""The Kotak live universe: what the relay's Kotak poller (deploy/cloudflare/kotak.js) is told to fetch, built from Kotak's own lists and pushed to the relay.

MARKET DATA ONLY. It reads Kotak's scrip master and its option-chain / expiry endpoints through `quantdesk.intraday.kotak.KotakClient` (the consumer key, no login) and
posts the result to the relay's `/live/universe` with the ingest token. It never calls an order, position, holding, margin or profile endpoint, and the key and the token
are never printed (a test greps this file for both).

What it lists, by the same names the Kite universe uses, so a price from either source lands on one row:
  * the index spots (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, INDIAVIX, SENSEX, BANKEX), each asked for by its Kotak name, one to a call
  * the cash price of every NSE F&O stock (name -> its cash token from the F&O scrip master's asset code)
  * the near-month future of every F&O underlying (stocks and the four NSE indices), `<NAME>-FUT`, from Kotak's own `instrument_type=fut` chain view
  * the option chains to poll: the nearest two expiries of each index (the chain call returns every strike near the money with last price, volume and open interest)
It is fail-soft by part: a scrip master that will not download, an underlying with no future, an index with no expiries, each skips only itself and is counted in `errors`;
a universe with nothing in it is the only failure. The relay keeps the last good universe if a day's build fails.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.request

from ..intraday.kotak import INDEX, KotakFutures, KotakError, _fo, scrip_master, segments
from .live_push import SYMBOL, _NoRedirect

STOCK_NAME = re.compile(r"^[A-Z0-9&_.-]{1,32}$")                 # an F&O stock's name: no colon, space or control character (it is printed in workflow log lines)

CHAIN_UNDERLYINGS = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX")
FUT_INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
CHAIN_EXPIRIES = 2
CHAIN_STRIKES = 10                                           # strikes each side of the money in one chain call
STOCK_CHAINS_MAX = 250                                       # F&O stocks whose option chain is polled (about 200 exist); the relay rotates them in the calls left over by the prices
STOCK_FAIL_RUN = 10                                          # consecutive failed expiry lookups after which the stock chains are given up for the day
STOCK_STRIKES = 3                                            # strikes each side of the money kept from a stock's chain: 14 option names a stock, not 42
MAX_QUOTES = 3000                                            # the relay's own cap


def _fo_exchange(underlying: str) -> str:
    return _fo(underlying).get("exchange", "nse_fo")


def stock_names(master) -> list[str]:
    """The F&O stocks: every underlying with a stock future (FUTSTK) in the F&O scrip master."""
    cols = {str(c).lower(): c for c in master.columns}
    sym, typ = cols.get("psymbolname"), cols.get("pinsttype")
    if not (sym and typ):
        raise KotakError("the F&O scrip master has no pSymbolName / pInstType columns")
    f = master[master[typ].astype(str).str.upper().eq("FUTSTK")]
    return sorted({str(s).strip().upper() for s in f[sym] if str(s).strip()})


def build(client, today: dt.date, say=print, fut_limit: int | None = None) -> dict:
    """The universe for `today`: {"asof", "count", "quotes", "chains", "errors"}. `fut_limit` caps the futures lookups (tests, a first dry run)."""
    from ..intraday.breadth import cash_tokens
    errors: list[str] = []
    quotes: list[dict] = []
    seen: set[str] = set()

    def add(n: str, s: str, g: str, t: str, one: bool = False) -> None:
        if n in seen or not SYMBOL.match(n) or not t:
            return
        seen.add(n)
        quotes.append({"n": n, "s": s, "g": g, "t": str(t), **({"one": True} if one else {})})

    for name, kotak_name in INDEX.items():                    # the index spots, by name (the answer carries the token, not the name: one to a call)
        add(name, "idx", segments(name)[1], kotak_name, one=True)

    names: list[str] = []
    try:
        master = scrip_master(client, "nse_fo")
        everyone = stock_names(master)
        names = [n for n in everyone if STOCK_NAME.fullmatch(str(n))]          # a name from a CSV is never printed or pushed unless it is a plain symbol
        if len(names) < len(everyone):
            errors.append(f"{len(everyone) - len(names)} F&O stock names were not plain symbols and were skipped")          # the count only, never the names
        tokens = cash_tokens(master, names)
        for n in names:
            if n in tokens:
                add(n, "eq", "nse_cm", tokens[n])
        missing = len(names) - len(tokens)
        if missing:
            errors.append(f"{missing} of {len(names)} F&O stocks have no cash token")
    except Exception as e:                                    # noqa: BLE001 - one source of names failing must not stop the rest
        errors.append(f"F&O scrip master: {type(e).__name__}")

    fut = KotakFutures(client)
    todo = [*names, *FUT_INDICES]
    if fut_limit is not None:
        todo = todo[:fut_limit]
    for u in todo:
        try:
            live = [c for c in fut.contracts(u) if c["expiry"] >= today and "|" in c["token"]]
            if not live:
                raise KotakError("no unexpired future")
            seg, tok = live[0]["token"].split("|", 1)
            add(f"{u}-FUT", "fut", seg, tok)
        except Exception as e:                                # noqa: BLE001
            errors.append(f"{u} future: {type(e).__name__}")

    chains: list[dict] = []
    for u in CHAIN_UNDERLYINGS:
        try:
            ex = _fo_exchange(u)
            exp = [d for d in client.expiries(u, exchange=ex) if d >= today][:CHAIN_EXPIRIES]
            if not exp:
                raise KotakError("no expiries")
            chains += [{"u": u, "x": ex, "e": d.isoformat()} for d in exp]
        except Exception as e:                                # noqa: BLE001
            errors.append(f"{u} expiries: {type(e).__name__}")

    failed_run = 0
    for i, u in enumerate(names[:STOCK_CHAINS_MAX]):           # every F&O stock's nearest expiry: its option chain, a few strikes either side of the money
        if failed_run >= STOCK_FAIL_RUN:                       # Kotak is refusing or not answering: do not spend minutes on 250 more calls that fail the same way
            errors.append(f"stock expiries stopped after {STOCK_FAIL_RUN} failures in a row; {len(names[:STOCK_CHAINS_MAX]) - i} stocks have no chain today")
            break
        try:
            exp = [d for d in client.expiries(u, exchange="nse_fo") if d >= today][:1]
            if not exp:
                raise KotakError("no expiries")
            chains.append({"u": u, "x": "nse_fo", "e": exp[0].isoformat(), "n": STOCK_STRIKES})
            failed_run = 0
        except Exception as e:                                # noqa: BLE001
            errors.append(f"{u} expiries: {type(e).__name__}")
            failed_run += 1

    quotes = quotes[:MAX_QUOTES]
    say(f"kotak-universe: {len(quotes)} instruments ({sum(1 for q in quotes if q['s'] == 'eq')} stocks, {sum(1 for q in quotes if q['s'] == 'fut')} futures, "
        f"{sum(1 for q in quotes if q['s'] == 'idx')} indices), {len(chains)} option chains, {len(errors)} gaps")
    return {"asof": today.isoformat(), "count": CHAIN_STRIKES, "quotes": quotes, "chains": chains, "errors": errors}


def universe_url(live_url: str) -> str:
    """The relay's universe endpoint from the recorder's LIVE_URL (https://<worker>/live/ingest -> https://<worker>/live/universe)."""
    if not str(live_url).startswith("https://") or not str(live_url).rstrip("/").endswith("/live/ingest"):
        raise ValueError("LIVE_URL must be the relay's https .../live/ingest address")
    return str(live_url).rstrip("/")[: -len("ingest")] + "universe"


def push(universe: dict, live_url: str, token: str, opener=None, timeout: float = 30.0) -> dict:
    """POST the universe (without its error list) to the relay with the ingest token. https only, never follows a redirect (the token would go with it)."""
    if not token:
        raise ValueError("no ingest token")
    body = {k: v for k, v in universe.items() if k != "errors"}
    req = urllib.request.Request(universe_url(live_url), data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token, "User-Agent": "quantdesk-universe"})
    open_ = opener or urllib.request.build_opener(_NoRedirect).open
    try:
        with open_(req, timeout=timeout) as r:
            answer = json.loads(r.read(65536) or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"the relay refused the universe: HTTP {e.code}") from None              # the status only: never the URL or token
    except Exception as e:                                                                         # noqa: BLE001
        raise RuntimeError(f"could not reach the relay: {type(e).__name__}") from None
    return answer
