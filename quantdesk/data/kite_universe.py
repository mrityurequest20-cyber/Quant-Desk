"""The wide Kite universe: every instrument the desk watches beyond the five core ones (kite_record.resolve_tokens).

Market data only; a pure builder over Kite's own instrument lists, so it needs no order method and nothing from the desk. It adds, in this priority order:

  1. the other index spots (FINNIFTY, MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX)
  2. the near-month future of EVERY NSE F&O underlying (indices and stocks), of every MCX commodity, every currency pair (CDS) and the BSE index futures
  3. the cash (spot) price of every NSE F&O stock
  4. index options: for NIFTY, BANKNIFTY, FINNIFTY and MIDCPNIFTY the nearest two expiries, the strikes within OPT_STEPS of the money, calls and puts

The option chain of an index is thousands of contracts, so only a window around the money is subscribed (the full chains are recorded each minute by the Kotak recorder).
Kite allows a limited number of instruments on one websocket (3,000 as far as I know; its documentation is not reachable from the build machine, so this is not
verified): the list is cut to MAX_SUBSCRIBE and the options go first, so the cut can never remove a future or a spot price.

Everything here is fail-soft. A missing exchange list, a missing index or an unreadable price skips that part and says so in `errors`; the five core instruments
and the recording never depend on this module. The result is a symbol -> token map plus a symbol -> meta map ({"s": segment, "kind", "name", "expiry", "strike"}).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd

MAX_SUBSCRIBE = 2500
OPT_FAMILIES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
OPT_EXPIRIES = 2
OPT_STEPS = 10
EXTRA_INDEX = {"FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MID SELECT", "NIFTYNXT50": "NSE:NIFTY NEXT 50",
               "SENSEX": "BSE:SENSEX", "BANKEX": "BSE:BANKEX"}
SPOT_FOR_OPTIONS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MID SELECT"}
SEGMENTS = ("idx", "eq", "fut", "bfo", "mcx", "cds", "opt")


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


def build_wide(kite, today: dt.date, core: dict[str, int], limit: int = MAX_SUBSCRIBE) -> tuple[dict[str, int], dict[str, dict], list[str]]:
    errors: list[str] = []
    tokens: dict[str, int] = {}
    meta: dict[str, dict] = {}
    taken = set(core.values())

    def add(sym: str, token, seg: str, kind: str, **kw) -> None:
        try:
            tok = int(token)
        except (TypeError, ValueError):
            return
        if sym in core or sym in tokens or tok in taken:
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
                    add(str(r.tradingsymbol), r.instrument_token, "opt", str(r.instrument_type), name=fam, expiry=str(expiry), strike=float(r.strike))

    room = max(0, int(limit) - len(core))
    if len(tokens) > room:
        errors.append(f"cut to the {limit}-instrument limit: {len(tokens) - room} options/stocks dropped")
        kept = list(tokens)[:room]
        tokens, meta = {k: tokens[k] for k in kept}, {k: meta[k] for k in kept}
    return tokens, meta, errors
