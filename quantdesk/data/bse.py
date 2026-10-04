"""BSE's F&O bhavcopy: SENSEX and BANKEX futures and options, in the warehouse's fo_bhav shape (table bse_fo_bhav).

BSE publishes it daily in the common UDiFF format (the columns NSE's file uses). The archive starts on 1 Jan 2024;
earlier dates return BSE's HTML error page, which counts as not published.

One quirk, kept out of the table: on a contract's own expiry day BSE writes the index value into the expiring
options' price columns (an 81,300 call "closing" at 71,909.70 on 1 Oct 2026). Those prices are set to NaN. Open
interest, volume and the underlying stay. Settlement uses the underlying, as it does for NSE's contracts.
"""
from __future__ import annotations

import datetime as dt
import io
import time

import numpy as np
import pandas as pd

from .nse import UA, NotPublished, typed, udiff_rows

BSE_FROM = dt.date(2024, 1, 1)
SYMBOLS = ("SENSEX", "BANKEX")
URL = "https://www.bseindia.com/download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_{d:%Y%m%d}_F_0000.CSV"
PRICES = ["open", "high", "low", "close", "last", "settle"]


class BSE:
    def __init__(self, session=None, gap: float = 0.5):
        import requests
        self.s = session or requests.Session()
        self.s.headers.update({**UA, "referer": "https://www.bseindia.com/"})
        self.gap, self._last = gap, 0.0

    def fo_bhav(self, day: dt.date) -> tuple[bytes, str]:
        url = URL.format(d=day)
        if day < BSE_FROM:
            raise NotPublished(url)
        wait = self.gap - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        r = self.s.get(url, timeout=60)
        self._last = time.time()
        if r.status_code == 404 or r.content[:20].lstrip().startswith(b"<"):
            raise NotPublished(url)
        r.raise_for_status()
        return r.content, url


def parse_fo_bhav(b: bytes, day: dt.date, symbols=SYMBOLS) -> pd.DataFrame:
    raw = pd.read_csv(io.BytesIO(b), low_memory=False)
    raw.columns = [str(c).strip() for c in raw.columns]
    if "FinInstrmTp" not in raw.columns:
        raise ValueError(f"unrecognised BSE F&O bhavcopy columns: {list(raw.columns)[:8]}")
    out = typed(udiff_rows(raw, ("IDO", "IDF"), symbols, src="bse"), day)
    expiring = (out["kind"] != "FUT") & (out["expiry"] == day)
    out.loc[expiring, PRICES] = np.nan
    return out
