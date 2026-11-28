"""Which data sources Tier 3 can use, checked from the machine that will use them (GitHub Actions): `python -m marketlens
probe-sources`. Read-only GETs and one read-only POST (MCX's bhavcopy query); prints a report and never fails the job, so
the answer is in the log whatever it is.

  * NSE's cash-market bhavcopy with delivery (sec_bhavdata_full): the stock OHLC, volume and delivery table
  * NSE's index constituents API (free-float market cap per stock: index weights for implied correlation)
  * niftyindices.com's constituent lists (a second source for membership)
  * Yahoo (through yfinance): the international benchmarks for MCX and the macro board
  * MCX's public bhavcopy (futures and options with open interest): decides MCX route A or B
"""
from __future__ import annotations

import datetime as dt
import json

import requests

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9"}
YAHOO = {"WTI": "CL=F", "Brent": "BZ=F", "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F", "Henry Hub": "NG=F",
         "Dollar index": "DX-Y.NYB", "US 10y": "^TNX", "USDINR": "INR=X"}


def _last_weekday(n: int = 1) -> dt.date:
    d = dt.date.today()
    while n:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _get(url, **kw):
    try:
        r = requests.get(url, headers=UA, timeout=25, **kw)
        return {"status": r.status_code, "bytes": len(r.content), "head": r.content[:200].decode("utf-8", "replace")}
    except Exception as e:                                       # noqa: BLE001 - a probe reports, it never raises
        return {"error": f"{type(e).__name__}: {str(e)[:160]}"}


def probe() -> dict:
    out = {}
    from quantdesk.data import nse as N
    c = N.NSE()
    for back in (1, 2, 3):
        d = _last_weekday(back)
        try:
            b, url = c.archive(f"/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv")
            out["nse_cm_bhav"] = {"ok": True, "day": str(d), "rows": b.count(b"\n"), "head": b[:120].decode()}
            break
        except Exception as e:                                   # noqa: BLE001
            out["nse_cm_bhav"] = {"ok": False, "day": str(d), "error": f"{type(e).__name__}: {str(e)[:120]}"}
    for idx in ("NIFTY BANK", "NIFTY 50"):
        try:
            j, raw, url = c.api(f"/api/equity-stockIndices?index={idx.replace(' ', '%20')}")
            rows = j.get("data", [])
            keys = sorted(rows[1].keys()) if len(rows) > 1 else []
            sample = [{k: r.get(k) for k in ("symbol", "ffmc", "lastPrice")} for r in rows[1:4]]
            out[f"nse_index_api:{idx}"] = {"ok": bool(rows), "n": len(rows), "has_ffmc": "ffmc" in keys, "keys": keys[:30], "sample": sample}
        except Exception as e:                                   # noqa: BLE001
            out[f"nse_index_api:{idx}"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    out["niftyindices_banklist"] = _get("https://www.niftyindices.com/IndexConstituent/ind_niftybanklist.csv")
    try:
        import yfinance as yf
        res = {}
        for name, tk in YAHOO.items():
            try:
                h = yf.Ticker(tk).history(period="10d", interval="1d")
                res[name] = {"ok": len(h) > 0, "rows": len(h), "last": (str(h.index[-1].date()), float(h["Close"].iat[-1])) if len(h) else None}
            except Exception as e:                               # noqa: BLE001
                res[name] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        h = yf.Ticker("CL=F").history(start="2019-01-01", end="2019-02-01", interval="1d")
        res["history_2019"] = {"ok": len(h) > 0, "rows": len(h)}
        out["yahoo"] = res
    except Exception as e:                                       # noqa: BLE001
        out["yahoo"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    d = _last_weekday(1)
    out["mcx_page"] = _get("https://www.mcxindia.com/market-data/bhavcopy")
    try:
        r = requests.post("https://www.mcxindia.com/backpage.aspx/GetDateWiseBhavCopy",
                          headers={**UA, "Content-Type": "application/json", "Referer": "https://www.mcxindia.com/market-data/bhavcopy"},
                          data=json.dumps({"Date": f"{d:%Y%m%d}", "InstrumentName": "ALL"}), timeout=25)
        out["mcx_bhav_post"] = {"status": r.status_code, "bytes": len(r.content), "head": r.content[:300].decode("utf-8", "replace")}
    except Exception as e:                                       # noqa: BLE001
        out["mcx_bhav_post"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    return out


def main() -> int:
    rep = probe()
    print(json.dumps(rep, indent=1, default=str))
    return 0
