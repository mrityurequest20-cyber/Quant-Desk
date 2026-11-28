"""Reading the public warehouse (Parquet tables built from NSE's and BSE's own end-of-day files).

Tables used (one file per period, `{table}_{period}.parquet`, as Quant-Desk's warehouse release keeps them):
  fo_bhav          NSE index futures and options, daily (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50)
  fo_stock_opts    every F&O stock's futures and nearest two option expiries (strikes within +-30%), daily
  fo_stock_far     the same for each stock's third expiry (the far month); read together with fo_stock_opts
  bse_fo_bhav      BSE index futures and options (SENSEX, BANKEX), daily, from 2024
  cm_bhav          NSE's cash-market day by stock: OHLC, volume, delivery (from Oct 2019)
  global_daily     international benchmarks (WTI, gold, Henry Hub, dollar, US rates, USDINR) from Yahoo
  nse_index_close  NSE's official index OHLC (the spot NSE's index options settle on), and India VIX
  participant_oi   FII / DII / Pro / Client open interest by product, daily
  fii_dii          FII and DII cash-market net buying, Rs crore (NSE publishes only the latest day: short history)
  corp_events      board meetings and results from NSE's event calendar
  nse_holidays     the exchange's trading holidays

Everything here is public exchange data. Nothing licensed (broker feeds) is read.
"""
from __future__ import annotations

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from .. import universe as U

OPT_COLS = ["date", "symbol", "kind", "expiry", "strike", "open", "high", "low", "close", "settle",
            "underlying", "oi", "chg_oi", "contracts", "lot", "src"]
# Before NSE's UDiFF bhavcopy (stocks: 8 Jul 2024) the stock file had no spot column; the warehouse filled
# `underlying` with the near-month future's close ("old-fut"). That is fine for returns and for the move to expiry
# (the future converges to spot), but it is not spot: basis and carry are not computed from it.
PROXY_SRC = {"old-fut"}
RELEASE_API = "https://api.github.com/repos/mrityurequest20-cyber/Quant-Desk/releases/tags/warehouse"
TABLES = ("fo_bhav", "fo_stock_opts", "fo_stock_far", "cm_bhav", "global_daily", "macro_events", "bse_fo_bhav", "nse_index_close", "participant_oi", "participant_vol",
          "fii_dii", "corp_events", "nse_holidays", "gift_nifty")


def fetch(dest: Path, tables=TABLES, workers: int = 8) -> int:
    """Download the public warehouse tables (GitHub release assets) into dest. Returns the number fetched."""
    dest.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(RELEASE_API, timeout=60) as r:
        assets = json.load(r)["assets"]
    want = [a for a in assets if a["name"].rsplit("_", 1)[0] in tables]

    def one(a):
        p = dest / a["name"]
        if p.exists() and p.stat().st_size == a["size"]:
            return 0
        urllib.request.urlretrieve(a["browser_download_url"], p)
        return 1

    with ThreadPoolExecutor(workers) as ex:
        return sum(ex.map(one, want))


class Warehouse:
    """Lazy, cached access to the warehouse folder, narrowed to MarketLens's universe."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._cache: dict[str, pd.DataFrame] = {}

    def files(self, table: str) -> list[Path]:
        # table names are prefixes of each other (fo_stock_opts vs fo_stocks), so match the period part exactly
        return sorted(p for p in self.root.glob(f"{table}_*.parquet")
                      if p.stem[len(table) + 1:][:1].isdigit())

    def _read(self, table: str, columns=None, symbols=None) -> pd.DataFrame:
        files = self.files(table)
        if not files:
            return pd.DataFrame(columns=columns or [])
        d = ds.dataset([str(f) for f in files], format="parquet")
        flt = ds.field("symbol").isin(list(symbols)) if symbols else None
        cols = [c for c in (columns or d.schema.names) if c in d.schema.names]
        df = d.to_table(columns=cols, filter=flt).to_pandas()
        for c in df.columns:
            if c in ("date", "expiry"):
                df[c] = pd.to_datetime(df[c]).dt.normalize()
            elif df[c].dtype != object and str(df[c].dtype).startswith("string"):
                df[c] = df[c].astype(object)
        return df

    # ---- derivatives ----
    def options(self, symbol: str) -> pd.DataFrame:
        """Every futures and options row for one underlying, all dates."""
        key = f"opt:{symbol}"
        if key not in self._cache:
            inst = U.BY_SYMBOL[symbol]
            if inst.exchange == "BSE":
                df = self._read("bse_fo_bhav", OPT_COLS, [symbol])
            elif inst.kind == "index":
                df = self._read("fo_bhav", OPT_COLS, [symbol])
            else:
                df = self._stock_options().get(symbol, pd.DataFrame(columns=OPT_COLS))
            self._cache[key] = df.sort_values(["date", "expiry", "kind", "strike"]).reset_index(drop=True)
        return self._cache[key]

    def _stock_options(self) -> dict[str, pd.DataFrame]:
        if "stockopts" not in self._cache:
            syms = [s.symbol for s in U.STOCKS]
            df = self._read("fo_stock_opts", OPT_COLS, syms)
            far = self._read("fo_stock_far", OPT_COLS, syms)              # the far month: absent until the warehouse has it
            if len(far):
                df = pd.concat([df, far], ignore_index=True).drop_duplicates(["date", "symbol", "kind", "expiry", "strike"])
            self._cache["stockopts"] = {s: g for s, g in df.groupby("symbol")}
        return self._cache["stockopts"]

    # ---- spot ----
    def cash(self, symbol: str) -> pd.DataFrame:
        """A stock's cash-market day (NSE's sec_bhavdata_full, equity series): OHLC, NSE's previous close, volume,
        turnover (Rs lakh), trades, delivered quantity and delivery %, indexed by date. Empty before the warehouse has
        the table, or for an index."""
        key = "cash:" + symbol
        if key not in self._cache:
            df = self._read("cm_bhav", None, [symbol])
            if len(df) and "series" in df:
                # one row a day: EQ, or the trade-for-trade series on the days a stock is in it
                df = df.assign(_p=df["series"].map({"EQ": 0, "BE": 1, "BZ": 2}).fillna(3)).sort_values(["date", "_p"])
                df = df.drop_duplicates("date").drop(columns="_p").set_index("date").sort_index()
            self._cache[key] = df
        return self._cache[key]

    def globals_(self) -> pd.DataFrame:
        """The international benchmarks (global_daily): date, ticker, name, OHLC, source."""
        if "glob" not in self._cache:
            self._cache["glob"] = self._read("global_daily")
        return self._cache["glob"]

    def index_close(self) -> pd.DataFrame:
        if "idx" not in self._cache:
            df = self._read("nse_index_close", ["date", "index", "open", "high", "low", "close"])
            self._cache["idx"] = df
        return self._cache["idx"]

    def spot(self, symbol: str) -> pd.DataFrame:
        """Daily spot OHLC (open/high/low may be NaN where only a close exists), indexed by date."""
        inst = U.BY_SYMBOL[symbol]
        if inst.index_name:
            ic = self.index_close()
            s = ic[ic["index"] == inst.index_name].drop(columns="index").drop_duplicates("date", keep="last")
            s = s.set_index("date").sort_index()
            if len(s):
                return s
        o = self.options(symbol)
        u = o.dropna(subset=["underlying"])
        u = u[u["underlying"] > 0]
        s = u.groupby("date")["underlying"].median().to_frame("close")
        for c in ("open", "high", "low"):
            s[c] = np.nan
        src = u.groupby("date")["src"].agg(lambda x: not set(x.astype(str)) & PROXY_SRC) if "src" in u else True
        s["true_spot"] = src
        # NSE's official cash close (sec_bhavdata_full, from 30 Sep 2019) wherever it exists: the F&O file's own
        # "underlying" is the near future's close before July 2024 (off by the futures premium, ~0.3%, and jumping on
        # roll days) and now and then off on its own; the exchange's closing price is the cash market's.
        cash = self.cash(symbol)
        if len(cash) and "close" in cash:
            c = cash.reindex(s.index)
            have = c["close"].notna() & (c["close"] > 0)
            for col in ("open", "high", "low", "close"):
                if col in c:
                    s.loc[have, col] = c.loc[have, col].astype(float)
            s.loc[have, "true_spot"] = True
        return s[["open", "high", "low", "close", "true_spot"]].sort_index()

    # ---- positioning and flows ----
    def participants(self) -> pd.DataFrame:
        if "poi" not in self._cache:
            self._cache["poi"] = self._read("participant_oi").sort_values(["date", "participant"])
        return self._cache["poi"]

    def participant_volume(self) -> pd.DataFrame:
        if "pvol" not in self._cache:
            self._cache["pvol"] = self._read("participant_vol").sort_values(["date", "participant"])
        return self._cache["pvol"]

    def macro_events(self) -> pd.DataFrame:
        """The global macro calendar (quantdesk/data/macro.py): date, time_ist, country, title, kind, impact, forecast,
        previous, source. Empty until the warehouse has the table."""
        if "macro" not in self._cache:
            self._cache["macro"] = self._read("macro_events")
        return self._cache["macro"]

    def fii_dii(self) -> pd.DataFrame:
        return self._read("fii_dii").sort_values(["date", "category"])

    def corp_events(self) -> pd.DataFrame:
        return self._read("corp_events")

    def holidays(self) -> pd.DataFrame:
        return self._read("nse_holidays")

    def gift_nifty(self) -> pd.DataFrame:
        return self._read("gift_nifty")
