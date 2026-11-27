"""Reading the public warehouse (Parquet tables built from NSE's and BSE's own end-of-day files).

Tables used (one file per period, `{table}_{period}.parquet`, as Quant-Desk's warehouse release keeps them):
  fo_bhav          NSE index futures and options, daily (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50)
  fo_stock_opts    every F&O stock's futures and nearest two option expiries (strikes within +-30%), daily
  bse_fo_bhav      BSE index futures and options (SENSEX, BANKEX), daily, from 2024
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
            "underlying", "oi", "chg_oi", "contracts", "lot"]
RELEASE_API = "https://api.github.com/repos/mrityurequest20-cyber/Quant-Desk/releases/tags/warehouse"
TABLES = ("fo_bhav", "fo_stock_opts", "bse_fo_bhav", "nse_index_close", "participant_oi", "participant_vol",
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
            self._cache["stockopts"] = {s: g for s, g in df.groupby("symbol")}
        return self._cache["stockopts"]

    # ---- spot ----
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
        return s[["open", "high", "low", "close"]].sort_index()

    # ---- positioning and flows ----
    def participants(self) -> pd.DataFrame:
        if "poi" not in self._cache:
            self._cache["poi"] = self._read("participant_oi").sort_values(["date", "participant"])
        return self._cache["poi"]

    def participant_volume(self) -> pd.DataFrame:
        if "pvol" not in self._cache:
            self._cache["pvol"] = self._read("participant_vol").sort_values(["date", "participant"])
        return self._cache["pvol"]

    def fii_dii(self) -> pd.DataFrame:
        return self._read("fii_dii").sort_values(["date", "category"])

    def corp_events(self) -> pd.DataFrame:
        return self._read("corp_events")

    def holidays(self) -> pd.DataFrame:
        return self._read("nse_holidays")

    def gift_nifty(self) -> pd.DataFrame:
        return self._read("gift_nifty")
