"""The brief's inputs from disk and the network. Every network source fails soft: a dead feed is named in
`health` and the brief is built without it.

Disk: the warehouse tables (`deploy/premarket-data.sh` downloads them into one folder).
Network: Yahoo for overnight moves abroad (the desk's own global list), and the public RSS feeds the desk reads.
"""
from __future__ import annotations

import glob
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)


def _concat(folder: Path, pattern: str) -> pd.DataFrame | None:
    files = sorted(glob.glob(str(Path(folder) / pattern)))
    if not files:
        return None
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def load_warehouse(folder: Path) -> dict:
    """The tables the brief reads, from a folder of warehouse assets (any that are missing come back as None)."""
    f = Path(folder)
    return {"stock_opts": _concat(f, "fo_stock_opts_*.parquet"), "index_bhav": _concat(f, "fo_bhav_*.parquet"),
            "corp_events": _concat(f, "corp_events_*.parquet"), "index_close": _concat(f, "nse_index_close_*.parquet")}


def latest_month(df: pd.DataFrame | None, months: int = 1) -> pd.DataFrame | None:
    """The last `months` calendar months of a table (the universe and today's implied moves need only the latest)."""
    if df is None or df.empty:
        return df
    d = pd.to_datetime(df["date"])
    cut = (d.max().to_period("M") - (months - 1)).to_timestamp()
    return df[d >= cut]


def fetch_globals(health: dict, download=None) -> list[dict]:
    """Each market in the desk's global list: its last daily close and the change on the one before (Yahoo)."""
    from ..data.global_universe import GLOBAL
    try:
        if download is None:
            import yfinance as yf
            download = lambda tickers: yf.download(tickers, period="7d", interval="1d", progress=False,   # noqa: E731
                                                   auto_adjust=False, group_by="ticker", threads=True)
        tick = {spec["yahoo"]: key for key, spec in GLOBAL.items()}
        raw = download(list(tick))
    except Exception as exc:                                    # Yahoo down or rate-limited: no overnight block
        health["yahoo"] = f"fail {str(exc)[:80]}"
        return []
    out = []
    for t, key in tick.items():
        try:
            c = raw[t]["Close"].dropna() if isinstance(raw.columns, pd.MultiIndex) else raw["Close"].dropna()
        except KeyError:
            continue
        if len(c) >= 2 and c.iloc[-2]:
            spec = GLOBAL[key]
            out.append({"key": key, "name": spec["name"], "region": spec["region"], "kind": spec["kind"],
                        "last": float(c.iloc[-1]), "change": float(c.iloc[-1] / c.iloc[-2] - 1),
                        "asof": str(pd.Timestamp(c.index[-1]).date()), "india_prior": spec["india"]})
    health["yahoo"] = f"ok {len(out)} of {len(tick)}"
    return out


def fetch_headlines(health: dict, now: pd.Timestamp, fetch=None, sources=None, hours: int = 18) -> list[dict]:
    """Headlines from the desk's RSS sources, the last `hours` hours, de-duplicated by title."""
    from ..intraday import news as N
    sources = sources or N.DEFAULT_SOURCES
    if fetch is None:
        import requests

        def fetch(url):
            r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (QuantDesk pre-market brief)"})
            r.raise_for_status()
            return r.text
    seen, out = set(), []
    for src in sources:
        try:
            items = N.parse_feed(fetch(src["url"]), src["name"], now)
            health[f"rss:{src['name']}"] = f"ok {len(items)}"
        except Exception as exc:                                # one dead feed must not stop the rest
            health[f"rss:{src['name']}"] = f"fail {str(exc)[:60]}"
            continue
        for it in items:
            key = it.title.strip().lower()
            if key in seen or now - it.ts > pd.Timedelta(hours=hours):
                continue
            seen.add(key)
            out.append({"ts": str(it.ts), "source": it.source, "title": it.title, "link": it.link})
    return sorted(out, key=lambda x: x["ts"], reverse=True)
