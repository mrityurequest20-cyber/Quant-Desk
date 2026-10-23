"""Historical 1-minute option, index and futures candles from Kotak Neo: the intraday option history no free source has.

Kotak's candle endpoint serves about 30 days of 1-minute bars per contract, with volume, using the same consumer key
the desk already uses (no login, no orders). This module pulls them for:
- every strike within `strikes` of the money, both rights, for the nearest `expiries` expiries of each index;
- the index itself;
- the active futures contract.

Run it once to collect the last month. Then run it after every session (live.yml does): each contract's final days
before expiry are kept, which Kotak forgets 30 days later and which expired contracts can't be fetched for at all.

What this data is: **traded** minute bars (OHLC of trades, plus volume). It is not bid/ask quotes. A strike that
didn't trade in a minute has no bar, and an illiquid strike's close can be stale. Evidence class `real_trade_minutes`:
- right for intraday research, move and IV studies, and checking the cost model against the chain tape's real quotes;
- it does not qualify a strategy; only real point-in-time quotes do (autolearn/plans.py).

Output, one set per run (overlapping runs are de-duplicated on load by contract and minute):

  runtime/intraday/backfill/<as of>/options_<UNDERLYING>.parquet   ts, underlying, expiry, strike, right, token, OHLCV
  runtime/intraday/backfill/<as of>/index.parquet, futures.parquet
  runtime/intraday/backfill/<as of>/manifest.json                  contracts asked, served, empty, failed, coverage

Stock minutes (`stock_minutes`, `data stock-minutes`): the same candles for the cash series and the near-month future
of the most liquid F&O stocks, a cross-section of ~50 partly independent series for the learning system. Data only:
nothing trades stocks. Files beside the above (`stocks_cash.parquet`, `stocks_futures.parquet`, `stocks_manifest.json`),
kept on the `stock-minutes-YYYY` release.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from pathlib import Path

import pandas as pd

from ..intraday.breadth import cash_tokens
from ..intraday.feeds import IST
from ..intraday.kotak import INDEX, KotakError, KotakFutures, chain_parts, scrip_master, segments, _f, _fo

EVIDENCE = "real_trade_minutes"
COLS = ["ts", "underlying", "expiry", "strike", "right", "token", "open", "high", "low", "close", "volume"]
STOCK_COLS = ["ts", "symbol", "token", "expiry", "open", "high", "low", "close", "volume"]     # expiry: futures only
CHUNK_DAYS = 5
SESSION_BARS = 375                    # 09:15-15:30, one-minute bars


def contracts(client, underlying: str, n_expiries: int, strikes: int, today: dt.date) -> list[dict]:
    """Tokens for every strike within `strikes` of the money, CE and PE, for the nearest `n_expiries` expiries."""
    out = []
    count = max(10, int(round(strikes / 10)) * 10)
    kw = _fo(underlying)                                      # {} for NSE; {"exchange": "bse_fo"} for SENSEX/BANKEX
    for exp in [e for e in client.expiries(underlying, **kw) if e >= today][:n_expiries]:
        _, calls, puts = chain_parts(client.option_chain(underlying, exp, count, **kw))
        for right, items in (("CE", calls), ("PE", puts)):
            for item in items:
                ins = item.get("instrument") or item.get("inst") or {}
                k = _f(ins.get("strikePrice", ins.get("strkPrc")))
                tok = str(ins.get("neoSymbol") or "")
                if k > 0 and "|" in tok:
                    out.append({"underlying": underlying, "expiry": exp, "strike": k, "right": right, "token": tok})
    return out


def candles(client, token: str, start: dt.date, end: dt.date) -> tuple[pd.DataFrame, str | None]:
    """The whole window in one call; if Kotak refuses or returns nothing, in CHUNK_DAYS pieces."""
    try:
        df = client.candles(token, "1min", start, end, raw=True)
        if len(df):
            return df, None
    except Exception as exc:                                  # a long window may be refused: try it in pieces
        first_err = f"{exc!s:.120}"
    else:
        first_err = None
    parts, err = [], first_err
    d = start
    while d <= end:
        e = min(end, d + dt.timedelta(days=CHUNK_DAYS - 1))
        try:
            p = client.candles(token, "1min", d, e, raw=True)
            if len(p):
                parts.append(p)
        except Exception as exc:
            err = f"{exc!s:.120}"
        d = e + dt.timedelta(days=1)
    if not parts:
        return pd.DataFrame(), err
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index(), None


def _frame(df: pd.DataFrame, meta: dict, cols: list[str] = COLS) -> pd.DataFrame:
    out = df.reset_index().rename(columns={df.index.name or "index": "ts"})
    if "ts" not in out:
        out = out.rename(columns={out.columns[0]: "ts"})
    for k, v in meta.items():
        out[k] = v
    return out[[c for c in cols if c in out.columns]]


def _write(run: Path, man: dict, idx_parts: list, fut_parts: list) -> None:
    """Index, futures and manifest as they stand: rewritten after every underlying, so a later timeout loses nothing."""
    if idx_parts:
        pd.concat(idx_parts, ignore_index=True).to_parquet(run / "index.parquet", index=False, compression="zstd")
    if fut_parts:
        pd.concat(fut_parts, ignore_index=True).to_parquet(run / "futures.parquet", index=False, compression="zstd")
    (run / "manifest.json").write_text(json.dumps(man, indent=1, default=str))


def backfill(client, out_root: Path, underlyings=("NIFTY", "BANKNIFTY"), days: int = 30, n_expiries: int = 4,
             strikes: int = 20, today: dt.date | None = None, say=print, on_underlying=None) -> dict:
    """`on_underlying(u, run)` is called once an underlying's files and the manifest so far are on disk (the CLI
    uploads them to the release there, so a timeout on a later underlying never loses a finished one)."""
    today = today or pd.Timestamp.now(tz=IST).date()
    start = today - dt.timedelta(days=days)
    run = Path(out_root) / str(today)
    run.mkdir(parents=True, exist_ok=True)
    man = {"evidence": EVIDENCE, "as_of": str(today), "window": [str(start), str(today)], "underlyings": {},
           "note": "traded 1-minute bars (OHLC of trades, volume), not bid/ask quotes; research and cost calibration, "
                   "never strategy qualification"}
    idx_parts, fut_parts = [], []
    fut = KotakFutures(client)
    for u in underlyings:
        rep = {"asked": 0, "served": 0, "empty": 0, "failed": 0, "bars": 0, "errors": {}, "asked_by_expiry": {},
               "failed_by_expiry": {}, "failed_contracts": []}
        try:
            cs = contracts(client, u, n_expiries, strikes, today)
        except Exception as exc:
            rep["errors"]["contracts"] = f"{exc!s:.160}"
            man["underlyings"][u] = rep
            say(f"  {u}: no contracts ({exc!s:.100})")
            continue
        rep["asked"] = len(cs)
        rep["expiries"] = sorted({str(c["expiry"]) for c in cs})
        for c in cs:
            rep["asked_by_expiry"][str(c["expiry"])] = rep["asked_by_expiry"].get(str(c["expiry"]), 0) + 1
        parts = []
        for c in cs:
            df, err = candles(client, c["token"], start, today)
            if err and df.empty:
                rep["failed"] += 1
                rep["errors"][err] = rep["errors"].get(err, 0) + 1
                e = str(c["expiry"])                         # where they fail is the diagnosis: one error string hides it
                rep["failed_by_expiry"][e] = rep["failed_by_expiry"].get(e, 0) + 1
                rep["failed_contracts"].append({"expiry": e, "strike": c["strike"], "right": c["right"], "error": err})
            elif df.empty:
                rep["empty"] += 1
            else:
                rep["served"] += 1
                parts.append(_frame(df, c))
        if parts:
            opt = pd.concat(parts, ignore_index=True)
            opt.to_parquet(run / f"options_{u}.parquet", index=False, compression="zstd")
            rep["bars"] = int(len(opt))
            rep["sessions"] = int(opt["ts"].dt.date.nunique())
            rep["first"], rep["last"] = str(opt["ts"].min()), str(opt["ts"].max())
            rep["bars_by_expiry"] = {str(k): int(v) for k, v in opt.groupby("expiry").size().items()}
        bse = segments(u)[0] == "bse_fo"
        for kind, sym, holder in (("index", f"{segments(u)[1]}|{INDEX.get(u, u)}", idx_parts), ("futures", None, fut_parts)):
            if bse and kind == "futures":
                continue                                      # KotakFutures reads nse_fo only; BSE futures are not collected
            try:
                tok = sym or fut.active(u, today)["token"]
                df, err = candles(client, tok, start, today)
                if len(df):
                    holder.append(_frame(df, {"underlying": u, "token": tok}))
                    rep[f"{kind}_bars"] = int(len(df))
                elif err:
                    rep["errors"][f"{kind}: {err}"] = 1
            except Exception as exc:
                rep["errors"][f"{kind}: {exc!s:.100}"] = 1
        man["underlyings"][u] = rep
        say(f"  {u}: {rep['served']}/{rep['asked']} contracts with bars ({rep['empty']} empty, {rep['failed']} failed), "
            f"{rep['bars']:,} option bars over {rep.get('sessions', 0)} sessions; index {rep.get('index_bars', 0):,}, "
            f"futures {rep.get('futures_bars', 0):,} bars")
        man["calls"] = dict(getattr(client, "calls", {}) or {})
        _write(run, man, idx_parts, fut_parts)
        if on_underlying:
            on_underlying(u, run)
    man["calls"] = dict(getattr(client, "calls", {}) or {})
    _write(run, man, idx_parts, fut_parts)
    man["path"] = str(run)
    return man


def load(root: Path, kind: str = "options", underlying: str | None = None) -> pd.DataFrame:
    """Every run's files of one kind (`options`, `index`, `futures`, `stocks_cash`, `stocks_futures`), de-duplicated by
    contract and minute (later runs win)."""
    pat = f"options_{underlying}.parquet" if (kind == "options" and underlying) else (
        "options_*.parquet" if kind == "options" else f"{kind}.parquet")
    parts = [pd.read_parquet(p) for p in sorted(Path(root).glob(f"*/{pat}"))]
    if not parts:
        return pd.DataFrame(columns=STOCK_COLS if kind.startswith("stocks_") else COLS)
    df = pd.concat(parts, ignore_index=True)
    return df.drop_duplicates(["token", "ts"], keep="last").sort_values(["token", "ts"]).reset_index(drop=True)


def release_names(run: Path, stocks: bool = False) -> list[str]:
    """Release asset names for a run: <as of>_<file> (Parquet and the manifest). The option files and the stock files
    share a run folder but go to different releases."""
    return [p.name for p in sorted(Path(run).iterdir())
            if p.suffix in (".parquet", ".json") and p.name.startswith("stocks_") == stocks]


# ---- stock options: near-the-money window, grouped assets ----------------------------------------------------------------
STOCK_EVIDENCE = "real_trade_minutes"


def _ltp(item: dict) -> float:
    return _f((item.get("quote") or {}).get("ltp"))


def _strike(item: dict) -> float:
    ins = item.get("instrument") or item.get("inst") or {}
    return _f(ins.get("strikePrice", ins.get("strkPrc")))


def chain_spot(calls: list, puts: list) -> float:
    """A stock's price from its own chain by put-call parity (K + call - put where the two LTPs are closest): the chain
    endpoint carries no cash price for a stock. NaN when no strike has both a call and a put LTP > 0."""
    ce = {k: _ltp(i) for i in calls if (k := _strike(i)) > 0}
    pe = {k: _ltp(i) for i in puts if (k := _strike(i)) > 0}
    both = [k for k in ce if k in pe and ce[k] > 0 and pe[k] > 0]
    if not both:
        return float("nan")
    k = min(both, key=lambda x: abs(ce[x] - pe[x]))
    return float(k + ce[k] - pe[k])


def select_window(strikes, spot: float, n: int) -> tuple[list[float], str]:
    """The strikes within n steps of the money: the one nearest `spot` plus n each side (2n+1 in all, fewer at the edge of
    the chain). With no usable spot the chain's middle strike stands in for the money and the source says so (Kotak's
    chain is centred on the money; not verified without a key). -> (strikes, "spot" | "chain-middle")."""
    ks = sorted({float(k) for k in strikes if k == k and k > 0})
    if not ks:
        return [], "none"
    if spot == spot and spot and spot > 0:
        i, src = min(range(len(ks)), key=lambda j: abs(ks[j] - spot)), "spot"
    else:
        i, src = len(ks) // 2, "chain-middle"
    return ks[max(0, i - n): i + n + 1], src


def stock_contracts(client, underlying: str, n_expiries: int, window: int, today: dt.date,
                    spot: float | None = None) -> tuple[list[dict], dict]:
    """Near-the-money contracts of a stock: the nearest `n_expiries` live expiries, calls and puts, ATM +/- `window` strikes.
    The money comes from `spot` if given (e.g. the day's close), else from the chain's put-call parity, else the chain's
    middle strike. Tokens are Kotak's own neoSymbols from the chain endpoint, so no symbol format is assumed.
    -> (contracts, {"atm_source": ..., "spot": ...})"""
    out, info = [], {"atm_source": "none", "spot": None}
    count = max(10, int(-(-(window + 2) // 10)) * 10)              # the API wants a multiple of 10 strikes each side
    exps = [e for e in client.expiries(underlying) if e >= today][:n_expiries]
    for exp in exps:
        _, calls, puts = chain_parts(client.option_chain(underlying, exp, count))
        s = spot if spot and spot > 0 else chain_spot(calls, puts)
        keep, src = select_window([_strike(i) for i in calls + puts], s, window)
        info["atm_source"] = src if info["atm_source"] in ("none", src) else "mixed"
        info["spot"] = round(s, 2) if s == s and s else info["spot"]
        for right, items in (("CE", calls), ("PE", puts)):
            for item in items:
                ins = item.get("instrument") or item.get("inst") or {}
                k, tok = _strike(item), str(ins.get("neoSymbol") or "")
                if k in keep and "|" in tok:
                    out.append({"underlying": underlying, "expiry": exp, "strike": k, "right": right, "token": tok})
    return out, info


def asset_plan(n_indices: int, n_stocks: int, group_size: int, days_per_shard: int = 66, cap: int = 900) -> dict:
    """Release-asset budget of a quarterly shard. Per trading day: one options file per index, index, futures, the index
    manifest and the health file, plus one options file per stock GROUP and the stock manifest. Groups grow until the
    quarter fits under `cap` (the release limit is ~1000), so a long stock list never means a file per contract or stock."""
    base = n_indices + 4
    size = max(1, int(group_size))
    groups = -(-n_stocks // size) if n_stocks else 0
    while groups > 1 and (base + 1 + groups) * days_per_shard > cap:
        size += 1
        groups = -(-n_stocks // size)
    per_day = base + (groups + 1 if n_stocks else 0)               # + the stock manifest
    return {"group_size": size, "groups": groups, "per_day": per_day, "per_shard": per_day * days_per_shard,
            "cap": cap, "fits": per_day * days_per_shard <= cap}


def group_stocks(stocks: list[str], group_size: int) -> list[list[str]]:
    return [stocks[i:i + group_size] for i in range(0, len(stocks), group_size)]


def backfill_stocks(client, out_root: Path, groups: list[list[str]], days: int = 3, n_expiries: int = 2, window: int = 5,
                    today: dt.date | None = None, spots: dict | None = None, say=print, on_group=None) -> dict:
    """Stock option minutes: ATM +/- `window` strikes, nearest `n_expiries` expiries, calls and puts, one Parquet per
    GROUP of stocks (options_STOCKS-<k>.parquet) and one stock_manifest.json: never a file per contract or per stock.
    A stock that fails is a line in the manifest; the rest continue. Only live contracts are asked for."""
    today = today or pd.Timestamp.now(tz=IST).date()
    start = today - dt.timedelta(days=days)
    run = Path(out_root) / str(today)
    run.mkdir(parents=True, exist_ok=True)
    man = {"evidence": STOCK_EVIDENCE, "as_of": str(today), "window": [str(start), str(today)], "strike_window": window,
           "expiries": n_expiries, "groups": {f"STOCKS-{k + 1}": g for k, g in enumerate(groups)}, "stocks": {},
           "note": "traded 1-minute bars of near-the-money stock options (not bid/ask); research and cost calibration only"}
    for k, grp in enumerate(groups):
        parts = []
        for s in grp:
            rep = man["stocks"][s] = {"asked": 0, "served": 0, "empty": 0, "failed": 0, "bars": 0, "errors": {}}
            try:
                cs, info = stock_contracts(client, s, n_expiries, window, today, (spots or {}).get(s))
            except Exception as exc:
                rep["errors"]["contracts"] = f"{exc!s:.160}"
                say(f"  {s}: no contracts ({exc!s:.100})")
                continue
            rep.update(info, asked=len(cs), expiries=sorted({str(c["expiry"]) for c in cs}))
            sp = []
            for c in cs:
                df, err = candles(client, c["token"], start, today)
                if err and df.empty:
                    rep["failed"] += 1
                    rep["errors"][err] = rep["errors"].get(err, 0) + 1
                elif df.empty:
                    rep["empty"] += 1
                else:
                    rep["served"] += 1
                    sp.append(_frame(df, c))
            if sp:
                o = pd.concat(sp, ignore_index=True)
                rep["bars"], rep["first"], rep["last"] = int(len(o)), str(o["ts"].min()), str(o["ts"].max())
                parts.append(o)
            say(f"  {s}: {rep['served']}/{rep['asked']} contracts with bars ({rep['empty']} empty, {rep['failed']} failed), "
                f"{rep['bars']:,} bars, ATM from {rep.get('atm_source')}")
        if parts:
            pd.concat(parts, ignore_index=True).to_parquet(run / f"options_STOCKS-{k + 1}.parquet", index=False,
                                                           compression="zstd")
        man["calls"] = dict(getattr(client, "calls", {}) or {})
        (run / "stock_manifest.json").write_text(json.dumps(man, indent=1, default=str))
        if on_group:
            on_group(k, run)
    man["path"] = str(run)
    return man


# ---- stock minutes -------------------------------------------------------------------------------------------------
# The most liquid F&O stocks by near-month option turnover (late 2025). Used only when the warehouse's `fo_stocks`
# table is not at hand to rank on; `universe()` says which was used. The one place this list lives.
FALLBACK_UNIVERSE = (
    "RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "INFY", "TCS", "AXISBANK", "KOTAKBANK", "BHARTIARTL", "ITC",
    "LT", "TATASTEEL", "M&M", "MARUTI", "BAJFINANCE", "HINDUNILVR", "SUNPHARMA", "TMPV", "ADANIENT", "ADANIPORTS",
    "HCLTECH", "WIPRO", "TECHM", "NTPC", "POWERGRID", "ONGC", "COALINDIA", "JSWSTEEL", "HINDALCO", "VEDL",
    "INDUSINDBK", "BAJAJFINSV", "TITAN", "ULTRACEMCO", "ASIANPAINT", "DLF", "TRENT", "BEL", "HAL", "ETERNAL",
    "INDIGO", "PNB", "BANKBARODA", "CANBK", "IDFCFIRSTB", "TVSMOTOR", "EICHERMOT", "DRREDDY", "CIPLA", "SBILIFE")


def universe(fo_stocks: pd.DataFrame | None, today: dt.date, n: int = 50) -> tuple[list[str], dict]:
    """(symbols, how they were chosen). Ranked by `intraday.stocks.rank` on the sessions **before** `today` (the list
    for a day never uses that day's own liquidity); the fixed fallback list when there is no table, which also tops up
    a table with fewer than `n` stocks."""
    from ..intraday.stocks import rank
    info = {"source": "fallback", "n": n, "ranked_through": None}
    syms: list[str] = []
    if fo_stocks is not None and len(fo_stocks):
        df = fo_stocks[pd.to_datetime(fo_stocks["date"]) < pd.Timestamp(today)]
        if len(df):
            syms = [str(s) for s in rank(df, days=20, top=n).index]
            info["ranked_through"] = str(pd.to_datetime(df["date"]).max().date())
    if syms:
        info["source"] = "ranked"
    if len(syms) < n:
        if syms:
            info["source"] = "ranked+fallback"
        syms += [s for s in FALLBACK_UNIVERSE if s not in syms][:n - len(syms)]
    info["symbols"] = syms[:n]
    return syms[:n], info


class BudgetExceeded(RuntimeError):
    pass


class Paced:
    """The Kotak client behind a throttle (default 5 requests a second, a fifth of the 25/s limit), a retry with
    backoff for rate limits, gateway errors and dropped connections, and a time budget after which every call raises
    `BudgetExceeded` (so a run stops cleanly and records what it did not get to). Same `_get` / `candles` surface."""

    def __init__(self, client, rate: float = 5.0, budget_s: float = 720.0, retries: int = 2, backoff: float = 1.0,
                 sleep=time.sleep, clock=time.monotonic):
        self.k, self.gap, self.retries, self.backoff = client, 1.0 / rate, retries, backoff
        self._sleep, self._clock, self.deadline = sleep, clock, clock() + budget_s
        self._last = -1e9
        self.requests = self.retried = 0

    def __getattr__(self, name):
        return getattr(self.k, name)

    @property
    def out_of_time(self) -> bool:
        return self._clock() >= self.deadline

    def _call(self, fn, *a, **kw):
        for attempt in range(self.retries + 1):
            if self.out_of_time:
                raise BudgetExceeded("time budget used up")
            wait = self._last + self.gap - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            self.requests += 1
            try:
                return fn(*a, **kw)
            except Exception as exc:
                transient = not isinstance(exc, KotakError) or re.search(r"HTTP (429|5\d\d)", str(exc))
                if attempt >= self.retries or not transient:
                    raise
                self.retried += 1
                self._sleep(self.backoff * 2 ** attempt)

    def _get(self, path, params=None):
        return self._call(self.k._get, path, params)

    def candles(self, *a, **kw):
        return self._call(self.k.candles, *a, **kw)


def _outcome(rep: dict, kind: str, df: pd.DataFrame, err: str | None, out_of_time: bool) -> bool:
    """Record one series' outcome on the symbol's entry; True when it has bars."""
    if out_of_time and df.empty:
        rep[kind] = {"status": "not_attempted", "error": "time budget"}
    elif df.empty and err:
        rep[kind] = {"status": "failed", "error": err}
    elif df.empty:
        rep[kind] = {"status": "empty"}
    else:
        rep[kind] = {"status": "served", "bars": int(len(df)), "sessions": int(df.index.normalize().nunique())}
    return not df.empty


def _write_stocks(run: Path, man: dict, cash: list, fut: list) -> None:
    for name, parts in (("stocks_cash", cash), ("stocks_futures", fut)):
        if parts:
            pd.concat(parts, ignore_index=True).to_parquet(run / f"{name}.parquet", index=False, compression="zstd")
    (run / "stocks_manifest.json").write_text(json.dumps(man, indent=1, default=str))


def stock_minutes(client, out_root: Path, fo_stocks: pd.DataFrame | None = None, n: int = 50, days: int = 3,
                  today: dt.date | None = None, rate: float = 5.0, budget_s: float = 720.0, say=print,
                  sleep=time.sleep, clock=time.monotonic) -> dict:
    """1-minute candles for the cash series and the near-month future of the top `n` F&O stocks, last `days` days.
    A Kotak failure never raises: the symbol is recorded as failed, and when the time budget runs out the rest are
    recorded as not attempted. Files and manifest are on disk after every 10 symbols and at the end."""
    today = today or pd.Timestamp.now(tz=IST).date()
    start = today - dt.timedelta(days=days)
    run = Path(out_root) / str(today)
    run.mkdir(parents=True, exist_ok=True)
    syms, uni = universe(fo_stocks, today, n)
    man = {"evidence": EVIDENCE, "as_of": str(today), "window": [str(start), str(today)], "universe": uni,
           "stocks": {}, "stopped": None, "rate_per_s": rate, "budget_s": budget_s,
           "note": "traded 1-minute bars (OHLC of trades, volume), not bid/ask quotes; cash series and near-month "
                   "future per stock; data collection only, nothing trades stocks"}
    say(f"  stock universe: {len(syms)} from {uni['source']}"
        + (f" (sessions to {uni['ranked_through']})" if uni["ranked_through"] else ""))
    paced = Paced(client, rate=rate, budget_s=budget_s, sleep=sleep, clock=clock)
    cash, fut_parts = [], []
    tokens: dict[str, str] = {}
    try:                                   # the F&O master's pAssetCode is the stock's cash token; the cash master fills gaps
        tokens = cash_tokens(scrip_master(paced, "nse_fo"), syms)
        if set(syms) - set(tokens):
            tokens = {**cash_tokens(None, syms, scrip_master(paced, "nse_cm")), **tokens}
    except Exception as exc:               # the tokens found still work; the rest are recorded as missing
        man["tokens_error"] = f"{exc!s:.160}"
    fut = KotakFutures(paced)
    for i, sym in enumerate(syms):
        rep: dict = {}
        man["stocks"][sym] = rep
        if paced.out_of_time:
            rep["cash"] = rep["futures"] = {"status": "not_attempted", "error": "time budget"}
            continue
        tok = tokens.get(sym)
        if not tok:
            rep["cash"] = {"status": "failed", "error": "no cash token in the scrip master"}
        else:
            df, err = candles(paced, f"nse_cm|{tok}", start, today)
            if _outcome(rep, "cash", df, err, paced.out_of_time):
                cash.append(_frame(df, {"symbol": sym, "token": f"nse_cm|{tok}"}, STOCK_COLS))
        try:
            a = fut.active(sym, today, fut.contracts(sym))
            rep["future"] = {k: (None if a[k] != a[k] else a[k])                          # the session's OI, once a run
                             for k in ("token", "expiry", "ltp", "oi", "oi_prev")}
            df, err = candles(paced, a["token"], start, today)
            if _outcome(rep, "futures", df, err, paced.out_of_time):
                fut_parts.append(_frame(df, {"symbol": sym, "token": a["token"], "expiry": a["expiry"]}, STOCK_COLS))
        except Exception as exc:
            rep["futures"] = ({"status": "not_attempted", "error": "time budget"} if paced.out_of_time
                              else {"status": "failed", "error": f"{exc!s:.120}"})
        if (i + 1) % 10 == 0:
            _write_stocks(run, man, cash, fut_parts)
    # coverage: bars against a full session for each session any stock has (a halted or late-listed stock shows as a gap)
    for kind in ("cash", "futures"):
        ref = max((r[kind].get("sessions", 0) for r in man["stocks"].values() if kind in r), default=0)
        for r in man["stocks"].values():
            if kind in r and ref:
                r[kind]["coverage"] = round(min(1.0, r[kind].get("bars", 0) / (ref * SESSION_BARS)), 3)
    man["totals"] = {k: {"asked": len(syms), **{s: sum(1 for r in man["stocks"].values() if r.get(k, {}).get("status") == s)
                                                 for s in ("served", "empty", "failed", "not_attempted")}}
                     for k in ("cash", "futures")}
    if paced.out_of_time:
        left = [s for s, r in man["stocks"].items()
                if "not_attempted" in (r.get("cash", {}).get("status"), r.get("futures", {}).get("status"))]
        man["stopped"] = f"time budget ({budget_s:.0f}s) used up; not attempted: {', '.join(left) or 'none'}"
    man["requests"], man["retried"] = paced.requests, paced.retried
    man["calls"] = dict(getattr(client, "calls", {}) or {})
    _write_stocks(run, man, cash, fut_parts)
    man["path"] = str(run)
    t = man["totals"]
    say(f"  stocks: cash {t['cash']['served']}/{len(syms)} served ({t['cash']['empty']} empty, {t['cash']['failed']} failed), "
        f"futures {t['futures']['served']}/{len(syms)} ({t['futures']['empty']} empty, {t['futures']['failed']} failed); "
        f"{paced.requests} requests" + (f"; STOPPED: {man['stopped']}" if man["stopped"] else ""))
    return man
