"""The wide Kite universe: every instrument the desk watches beyond the five core ones (kite_record.resolve_tokens).

Market data only; a pure builder over Kite's own instrument lists, so it needs no order method and nothing from the desk. It adds, in this priority order:

  1. the other index spots (FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX)
  2. the near-month future of EVERY NSE F&O underlying (indices and stocks), of every MCX commodity, every currency pair (CDS) and the BSE index futures
  3. the cash (spot) price of every NSE F&O stock
  4. index options: for NIFTY, BANKNIFTY, FINNIFTY and MIDCPNIFTY the nearest two expiries, the strikes within OPT_STEPS of the money, calls and puts
  5. stock options: for each stock on the desk's watchlist (config desk.watchlist.stocks) the nearest expiry, a few strikes either side of the money, calls and puts

The option chain of an index is thousands of contracts, so only a window around the money is subscribed (the full chains are recorded each minute by the Kotak recorder).
Kite allows a limited number of instruments on one websocket (3,000 as far as I know; its documentation is not reachable from the build machine, so this is not
verified): the list is cut to MAX_SUBSCRIBE and the options go first, so the cut can never remove a future or a spot price.

Everything here is fail-soft. A missing exchange list, a missing index or an unreadable price skips that part and says so in `errors`; the five core instruments
and the recording never depend on this module. The result is a symbol -> token map plus a symbol -> meta map ({"s": segment, "kind", "name", "expiry", "strike"}).
"""
from __future__ import annotations

import datetime as dt
import re

import pandas as pd

MAX_SUBSCRIBE = 2500
OPT_FAMILIES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
OPT_EXPIRIES = 2
OPT_STEPS = 10
EXTRA_INDEX = {"FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MID SELECT", "NIFTYNXT50": "NSE:NIFTY NEXT 50",
               "SENSEX": "BSE:SENSEX", "BANKEX": "BSE:BANKEX"}
SPOT_FOR_OPTIONS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MID SELECT"}
SEGMENTS = ("idx", "eq", "fut", "bfo", "mcx", "cds", "opt", "mopt", "copt")
NAME_OK = re.compile(r"^[A-Za-z0-9&_.:-]{1,40}$")                # what the live relay accepts as a symbol: an instrument named otherwise is not subscribed (it could never be shown)


_MON = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def option_name(underlying: str, expiry, strike: float, side: str) -> str:
    """The one name BOTH live sources use for an option (NIFTY12NOV2624500CE), so a price from Kite or from Kotak lands on the same row. Kite's own trading symbol
    (NIFTY2611224500CE for a weekly) is not Kotak's; this is derived from the contract's facts and is identical to `optionName` in deploy/cloudflare/kotak.js."""
    d = pd.Timestamp(expiry).date()
    k = int(strike) if float(strike).is_integer() else strike
    return f"{underlying}{d.day:02d}{_MON[d.month - 1]}{d.year % 100:02d}{k}{side}"


DEEP_MAX = 1200                                                  # FULL-mode subscriptions beyond the core five: a bound on the websocket's traffic, far under Kite's 3,000 a connection


def deep_symbols(meta: dict[str, dict], watchlist: dict | None, limit: int = DEEP_MAX) -> list[str]:
    """The wide-universe instruments to subscribe in Kite's FULL mode (price, open interest and five levels of order book) instead of QUOTE mode (price and volume only).

    Two groups, in this order, so a cut can only ever drop the second:
      1. every option on the board. A strategy can be priced, and a paper order filled, only against a real bid and offer; in QUOTE mode an option has neither, and no other
         feed on the board supplies one (Kotak's chain call returns the last price, volume and open interest, not the book).
      2. the desk's watchlist (config `desk.watchlist`): the cash price, the future, the MCX or the currency contract of each name the owner trades, for the depth on its page.
    Everything else stays in QUOTE mode: it is recorded and searchable, with no book."""
    names = {str(n).strip().upper() for group in (watchlist or {}).values() if isinstance(group, (list, tuple)) for n in group if str(n).strip()}
    options = [sym for sym, m in meta.items() if m.get("s") == "opt"]
    watched = [sym for sym, m in meta.items() if m.get("s") != "opt" and str(m.get("name") or "").upper() in names]
    return (options + watched)[:max(0, int(limit))]


def _frame(kite, exchange: str, errors: list[str]) -> pd.DataFrame:
    try:
        df = pd.DataFrame(kite.instruments(exchange))
    except Exception as e:                                           # noqa: BLE001 - one missing list must not stop the others
        errors.append(f"{exchange} instruments: {type(e).__name__}")
        return pd.DataFrame()
    if df.empty:
        errors.append(f"{exchange} instruments: none")
        return df
    if "expiry" in df:
        df = df.copy()
        df["expiry"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    return df


def _near_futures(df: pd.DataFrame, today: dt.date, exclude=()) -> list[tuple[str, int, dt.date]]:
    """(underlying name, token, expiry) of the nearest unexpired future of every underlying."""
    if df.empty or not {"instrument_type", "name", "expiry", "instrument_token"} <= set(df.columns):
        return []
    f = df[(df["instrument_type"] == "FUT") & df["expiry"].notna() & (df["expiry"] >= today) & df["name"].notna() & (df["name"] != "")]
    f = f[~f["name"].isin(exclude)].sort_values(["name", "expiry"])
    first = f.groupby("name", sort=True).head(1)
    return [(str(r.name_), int(r.instrument_token), r.expiry) for r in first.rename(columns={"name": "name_"}).itertuples()]


def build_wide(kite, today: dt.date, core: dict[str, int], limit: int = MAX_SUBSCRIBE, stock_options=(), stock_steps: int = 8, commodity_options=(), currency_options=(),
               fx_steps: int = 8) -> tuple[dict[str, int], dict[str, dict], list[str]]:
    errors: list[str] = []
    tokens: dict[str, int] = {}
    meta: dict[str, dict] = {}
    taken = set(core.values())

    def add(sym: str, token, seg: str, kind: str, **kw) -> None:
        try:
            tok = int(token)
        except (TypeError, ValueError):
            return
        if sym in core or sym in tokens or tok in taken or not NAME_OK.match(sym):
            return
        taken.add(tok)
        tokens[sym] = tok
        meta[sym] = {"s": seg, "kind": kind, **{k: v for k, v in kw.items() if v is not None}}

    # 1. the other index spots, and the prices the option windows are centred on
    prices: dict[str, float] = {}
    keys = sorted(set(EXTRA_INDEX.values()) | set(SPOT_FOR_OPTIONS.values()))
    try:
        ltp = kite.ltp(keys)
    except Exception as e:                                           # noqa: BLE001
        ltp = {}
        errors.append(f"index prices: {type(e).__name__}")
    for name, key in EXTRA_INDEX.items():
        if key in ltp and ltp[key].get("instrument_token") is not None:
            add(name, ltp[key]["instrument_token"], "idx", "index", name=name)
    for fam, key in SPOT_FOR_OPTIONS.items():
        px = (ltp.get(key) or {}).get("last_price")
        if isinstance(px, (int, float)) and px > 0:
            prices[fam] = float(px)

    # 2. the near-month futures of every underlying, per exchange
    nfo, bfo, mcx, cds = (_frame(kite, x, errors) for x in ("NFO", "BFO", "MCX", "CDS"))
    fno_names = []
    for name, token, expiry in _near_futures(nfo, today):
        add(f"{name}-FUT", token, "fut", "future", name=name, expiry=str(expiry))
        fno_names.append(name)
    for seg, df, suffix in (("bfo", bfo, "BFO"), ("mcx", mcx, "MCX"), ("cds", cds, "CDS")):
        for name, token, expiry in _near_futures(df, today):
            add(f"{name}-{suffix}", token, seg, "future", name=name, expiry=str(expiry))

    # 3. the cash price of every F&O stock (the F&O underlyings that are not indices)
    nse = _frame(kite, "NSE", errors)
    if not nse.empty and {"instrument_type", "tradingsymbol", "instrument_token"} <= set(nse.columns):
        eq = nse[(nse["instrument_type"] == "EQ")].drop_duplicates("tradingsymbol")
        want = set(fno_names) - set(OPT_FAMILIES) - set(EXTRA_INDEX)
        for r in eq[eq["tradingsymbol"].isin(want)].sort_values("tradingsymbol").itertuples():
            add(str(r.tradingsymbol), r.instrument_token, "eq", "stock", name=str(r.tradingsymbol))

    # 4. index options near the money, last because they are the first to be cut
    if not nfo.empty and {"instrument_type", "name", "strike", "tradingsymbol", "instrument_token"} <= set(nfo.columns):
        for fam in OPT_FAMILIES:
            spot = prices.get(fam)
            if spot is None:
                errors.append(f"{fam} options: no index price to centre on")
                continue
            o = nfo[(nfo["name"] == fam) & nfo["instrument_type"].isin(["CE", "PE"]) & nfo["expiry"].notna() & (nfo["expiry"] >= today)]
            for expiry in sorted(o["expiry"].unique())[:OPT_EXPIRIES]:
                oe = o[o["expiry"] == expiry]
                strikes = sorted(oe["strike"].dropna().unique())
                if not strikes:
                    continue
                atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
                keep = set(strikes[max(0, atm - OPT_STEPS): atm + OPT_STEPS + 1])
                for r in oe[oe["strike"].isin(keep)].sort_values(["strike", "instrument_type"]).itertuples():
                    add(option_name(fam, expiry, float(r.strike), str(r.instrument_type)), r.instrument_token, "opt", str(r.instrument_type), name=fam, expiry=str(expiry), strike=float(r.strike))

    # 5. the option chain of each watchlist stock (`stock_options`, config desk.watchlist.stocks): its nearest expiry, `stock_steps` strikes either side of the money. Last of all,
    #    so the cut below takes these before anything else.
    wanted = [n for n in dict.fromkeys(str(x).strip().upper() for x in (stock_options or ())) if n in set(fno_names) and n not in OPT_FAMILIES and n not in EXTRA_INDEX]
    if wanted and not nfo.empty and {"instrument_type", "name", "strike", "tradingsymbol", "instrument_token"} <= set(nfo.columns):
        try:
            sltp = kite.ltp([f"NSE:{n}" for n in wanted])
        except Exception as e:                                       # noqa: BLE001
            sltp = {}
            errors.append(f"stock prices for the option chains: {type(e).__name__}")
        steps = max(1, min(20, int(stock_steps)))
        for n in wanted:
            spot = (sltp.get(f"NSE:{n}") or {}).get("last_price")
            if not (isinstance(spot, (int, float)) and spot > 0):
                errors.append(f"{n} options: no price to centre on")
                continue
            o = nfo[(nfo["name"] == n) & nfo["instrument_type"].isin(["CE", "PE"]) & nfo["expiry"].notna() & (nfo["expiry"] >= today)]
            if o.empty:
                continue
            expiry = min(o["expiry"])
            oe = o[o["expiry"] == expiry]
            strikes = sorted(oe["strike"].dropna().unique())
            if not strikes:
                continue
            atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
            keep = set(strikes[max(0, atm - steps): atm + steps + 1])
            for r in oe[oe["strike"].isin(keep)].sort_values(["strike", "instrument_type"]).itertuples():
                add(option_name(n, expiry, float(r.strike), str(r.instrument_type)), r.instrument_token, "opt", str(r.instrument_type), name=n, expiry=str(expiry), strike=float(r.strike))

    # 6. MCX and currency options (owner, 13 Nov 2026: "MCX and currency options should be treated in the same way" as index and stock options): for each watchlist commodity
    #    and currency pair, its nearest option expiry, `fx_steps` strikes either side of its near-month future's price, under the same names as every option (option_name).
    #    MCX options are options on the future; currency options settle on the RBI reference rate. Last of all, so a cut takes these first.
    for want_names, ex_df, exch, label in ((commodity_options, mcx, "MCX", "MCX"), (currency_options, cds, "CDS", "currency")):
        names = [n for n in dict.fromkeys(str(x).strip().upper() for x in (want_names or ())) if n]
        if not names or ex_df.empty or not {"instrument_type", "name", "strike", "tradingsymbol", "instrument_token", "expiry"} <= set(ex_df.columns):
            continue
        futs = {n: t for n, t, _ in _near_futures(ex_df[ex_df["name"].isin(names)], today)}
        sym = ex_df.set_index("instrument_token")["tradingsymbol"].to_dict()
        try:
            fl = kite.ltp([f"{exch}:{sym[t]}" for t in futs.values() if t in sym]) if futs else {}
        except Exception as e:                                       # noqa: BLE001
            fl = {}
            errors.append(f"{label} future prices for the option chains: {type(e).__name__}")
        for n in names:
            t = futs.get(n)
            spot = (fl.get(f"{exch}:{sym.get(t)}") or {}).get("last_price") if t in sym else None
            if not (isinstance(spot, (int, float)) and spot > 0):
                errors.append(f"{n} options: no future price to centre on")
                continue
            o = ex_df[(ex_df["name"] == n) & ex_df["instrument_type"].isin(["CE", "PE"]) & ex_df["expiry"].notna() & (ex_df["expiry"] >= today)]
            if o.empty:
                continue
            expiry = min(o["expiry"])
            oe = o[o["expiry"] == expiry]
            strikes = sorted(oe["strike"].dropna().unique())
            if not strikes:
                continue
            atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
            keep = set(strikes[max(0, atm - fx_steps): atm + fx_steps + 1])
            for r in oe[oe["strike"].isin(keep)].sort_values(["strike", "instrument_type"]).itertuples():
                add(option_name(n, expiry, float(r.strike), str(r.instrument_type)), r.instrument_token, "mopt" if exch == "MCX" else "copt", str(r.instrument_type), name=n,
                    expiry=str(expiry), strike=float(r.strike))                  # their own route labels: Fyers (MCX) and Angel One (currency) are shown first

    room = max(0, int(limit) - len(core))
    if len(tokens) > room:
        errors.append(f"cut to the {limit}-instrument limit: {len(tokens) - room} options/stocks dropped")
        kept = list(tokens)[:room]
        tokens, meta = {k: tokens[k] for k in kept}, {k: meta[k] for k in kept}
    return tokens, meta, errors
