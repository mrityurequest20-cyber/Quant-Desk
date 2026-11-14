"""Tail-risk models for the brief (owner, 13 Nov 2026: "Add Extreme value theory: tail-risk estimates"): every paper underlying's conditional EVT fit
(quantdesk/paper/tails.py), from the longest daily history the desk can get.

WHERE THE HISTORY COMES FROM
* Indices: NSE's official closes (the warehouse's nse_index_close), else Yahoo's index series.
* Stocks: Yahoo's split- and dividend-adjusted daily closes (SYMBOL.NS): an unadjusted split would read as a 50% crash.
* MCX commodities: the warehouse has no MCX history, so a PROXY: the international future in rupees (WTI x USD/INR for CRUDEOIL, COMEX gold x USD/INR for GOLD, ...).
  The MCX contract is that price, converted, plus local premium and duty; its RETURNS are the proxy's to a close approximation. Yahoo's continuous futures roll from one
  month to the next, and a roll can print a step that is not a return: non-positive prices (WTI, 20 April 2020) and single-day moves beyond MAX_ABS_RET are dropped.
* Currency futures: Yahoo's spot rates (USD/INR, EUR/INR, GBP/INR, JPY/INR); a near-month future's returns are spot's plus a slowly moving carry.
Every model says which source it came from (`src`).

Built once a day (the brief reuses the day's file: Yahoo is not asked fifteen times a morning). Pure functions here; the network lives in fetch_yahoo.
"""
from __future__ import annotations

import math

import pandas as pd

from ..paper import tails as TL

YEARS = 10
MAX_ABS_RET = 0.5                         # a daily log return beyond this is a roll or a bad print, not a market move
YAHOO_INDEX = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS", "MIDCPNIFTY": "NIFTY_MID_SELECT.NS", "SENSEX": "^BSESN"}
USDINR = "INR=X"
PROXY = {                                 # MCX underlying -> (Yahoo future, priced in US dollars: converted to rupees)
    "CRUDEOIL": ("CL=F", True), "CRUDEOILM": ("CL=F", True), "NATURALGAS": ("NG=F", True), "NATGASMINI": ("NG=F", True),
    "GOLD": ("GC=F", True), "GOLDM": ("GC=F", True), "SILVER": ("SI=F", True), "SILVERM": ("SI=F", True), "COPPER": ("HG=F", True),
    "USDINR": ("INR=X", False), "EURINR": ("EURINR=X", False), "GBPINR": ("GBPINR=X", False), "JPYINR": ("JPYINR=X", False),
}


def yahoo_ticker(u: str) -> str:
    if u in YAHOO_INDEX:
        return YAHOO_INDEX[u]
    if u in PROXY:
        return PROXY[u][0]
    return f"{u}.NS"


def tickers_for(underlyings) -> list[str]:
    """Every Yahoo series the models need (the dollar-priced proxies need USD/INR too)."""
    out = {yahoo_ticker(u) for u in underlyings}
    if any(PROXY.get(u, ("", False))[1] for u in underlyings):
        out.add(USDINR)
    return sorted(out)


def clean(s: pd.Series) -> pd.Series:
    """Positive closes by date; a day whose log move from the day before exceeds MAX_ABS_RET is dropped (with its move)."""
    s = pd.to_numeric(s, errors="coerce").dropna()
    s = s[s > 0].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if len(s) < 2:
        return s
    keep = [True]
    last = float(s.iloc[0])
    for v in s.iloc[1:]:
        ok = abs(math.log(float(v) / last)) <= MAX_ABS_RET
        keep.append(ok)
        if ok:
            last = float(v)
    return s[keep]


def series_for(u: str, index_close: pd.DataFrame | None, yahoo: dict) -> tuple[pd.Series | None, str | None]:
    """(daily closes, source) for one underlying, or (None, None)."""
    if index_close is not None and len(index_close) and u in YAHOO_INDEX:
        ic = index_close[index_close["symbol"] == u]
        if len(ic) >= TL.MIN_OBS:
            return clean(ic.set_index(pd.to_datetime(ic["date"]))["close"]), "nse_index_close"
    t = yahoo_ticker(u)
    s = yahoo.get(t)
    if s is None or len(s) < TL.MIN_OBS:
        return None, None
    if u in PROXY and PROXY[u][1]:
        fx = yahoo.get(USDINR)
        if fx is None or len(fx) < TL.MIN_OBS:
            return None, None
        both = pd.concat([clean(s), clean(fx)], axis=1, join="inner").dropna()
        return clean(both.iloc[:, 0] * both.iloc[:, 1]), f"proxy {t} x {USDINR} (Yahoo)"
    return clean(s), ("proxy " if u in PROXY else "") + f"{t} (Yahoo)"


def all_series(underlyings, index_close: pd.DataFrame | None, yahoo: dict) -> dict:
    """{u: (daily closes, source)} for every underlying with enough history (the tail models and the news analogues read the same series)."""
    out = {}
    for u in underlyings:
        s, src = series_for(u, index_close, yahoo)
        if s is not None and len(s) >= TL.MIN_OBS:
            out[u] = (s, src)
    return out


def build(underlyings, index_close: pd.DataFrame | None, yahoo: dict, series: dict | None = None) -> dict:
    """{u: tails.fit_series(...) + {"src", "from", "to"}} for every underlying with enough history."""
    out = {}
    for u, (s, src) in (series if series is not None else all_series(underlyings, index_close, yahoo)).items():
        fit = TL.fit_series([float(x) for x in s.values])
        if fit:
            out[u] = {**fit, "src": src, "from": str(pd.Timestamp(s.index[0]).date()), "to": str(pd.Timestamp(s.index[-1]).date())}
    return out


def fetch_yahoo(tickers, health: dict, download=None) -> dict:
    """{ticker: daily close Series} from Yahoo (YEARS of adjusted closes); what fails is left out and said in `health`."""
    try:
        if download is None:
            import yfinance as yf
            download = lambda tk: yf.download(tk, period=f"{YEARS}y", interval="1d", progress=False, auto_adjust=True,      # noqa: E731
                                              group_by="ticker", threads=True)
        raw = download(list(tickers))
    except Exception as exc:                                        # noqa: BLE001 - no Yahoo: the indices still have NSE's closes
        health["tails"] = f"fail yahoo {str(exc)[:80]}"
        return {}
    out = {}
    for t in tickers:
        try:
            c = raw[t]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
        except KeyError:
            continue
        c = pd.to_numeric(c, errors="coerce").dropna()
        if len(c):
            out[t] = c
    return out


def summary_line(tails: dict) -> str | None:
    """One line for the brief: the indices' 1-day 99% expected shortfall."""
    parts = []
    for u in ("NIFTY", "BANKNIFTY"):
        m = TL.Model.read(tails.get(u) or {})
        if m:
            parts.append(f"{u} {m.es_pct(0.99, 1):.1f}%")
    return ("Tail risk (EVT, 1-day 99% expected shortfall): " + ", ".join(parts) + ".") if parts else None
