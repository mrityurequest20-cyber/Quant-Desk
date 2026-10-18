"""Wider data collection, beside the desk and never in it (collect-wide.yml; `quantdesk data collect-wide`).

Two things the live session does not record, and a health check that says whether each arrived:

1. **Option minutes for all five indices** (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY): Kotak's 1-minute candles
   (kotak_backfill.py; SENSEX on bse_fo/bse_cm). Kotak keeps ~30 days, so a run each evening keeps what it would forget.
2. **Option-chain quote snapshots of the most liquid F&O stocks** (config `collect_wide.stocks`): quotes are not
   historical, so they are captured live, once, at about 15:25 IST, in the same Parquet shape as the chain tape
   (archive.py), and pushed through the same archive path.

Release layout (GitHub caps a release near 1000 assets, so a release is a quarter, not a year or forever):
  option-minutes-2026Q4   <day>_options_<UNDERLYING>.parquet, <day>_index.parquet, <day>_futures.parquet, <day>_manifest.json,
                          <day>_health.json
  chains-2026Q4           <day>_wide-eod-<run>_chains.parquet   (the stocks; the desk's own tape stays on chains-YYYY)
`release_tag` is the one place that names them. Read it back with `gh release download <tag>` and archive.load_archive.

Nothing here trades, sizes or places an order; it reads Kotak with the same consumer key the desk uses for data and
every failure is a warning and a line in the health report, never an error exit.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..intraday.feeds import IST, session_bounds

DEFAULTS = {
    "indices": ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"],
    "stocks": [],
    "stock_expiries": 1,          # nearest N expiries per stock (stock options are monthly)
    "stock_strikes": 20,          # strikes each side of the money
    "minute_days": 3,             # days back each evening (overlap heals a missed day; Kotak serves ~30)
    "minute_expiries": 3,
    "minute_strikes": 20,
    "minutes_release": "option-minutes",
    "chains_release": "chains",
    "shard": "quarter",           # quarter | year
    "min_gap_sec": 0.25,          # slower than the desk's 0.06: this runs at 15:25 while the desk may still be polling
    "stock_deadline": "15:35",    # after this the book is empty: skip rather than record blanks
}


def settings(cfg) -> dict:
    raw = (cfg.get("collect_wide") if cfg is not None else None) or {}
    out = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    out["indices"] = [str(x).upper() for x in out["indices"]]
    out["stocks"] = [str(x).upper() for x in out["stocks"]]
    return out


def release_tag(prefix: str, day: dt.date, shard: str = "quarter") -> str:
    """option-minutes-2026Q4 (quarter) or option-minutes-2026 (year)."""
    return f"{prefix}-{day.year}Q{(day.month - 1) // 3 + 1}" if shard == "quarter" else f"{prefix}-{day.year}"


# ---- the stocks' chains ---------------------------------------------------------------------------------------------
def parity_spot(df: pd.DataFrame) -> float:
    """A stock's spot from its own chain (K + call − put at the strike where they are closest), because the chain
    endpoint quotes only an index's cash price. Needs both LTPs > 0; NaN when nothing qualifies."""
    ce, pe = df["ce_ltp"].to_numpy(dtype=float), df["pe_ltp"].to_numpy(dtype=float)
    ok = (ce > 0) & (pe > 0)
    if not ok.any():
        return float("nan")
    k = df.index.to_numpy(dtype=float)
    i = np.flatnonzero(ok)[np.argmin(np.abs(ce[ok] - pe[ok]))]
    return float(k[i] + ce[i] - pe[i])


def snapshot_stocks(src, stocks, data_dir: Path, n_expiries: int, now: pd.Timestamp, say=print) -> dict:
    """One chain per stock and nearest expiry → <data_dir>/<day>/chains/<SYM>_<expiry>_<HHMM>.csv (the tape's layout).
    `src` is a KotakOptionChain. Returns {stock: {"ok", "expiries", "strikes", "quoted", "error"}}."""
    from ..intraday.chains import IntradayPricer, fill_iv
    from ..intraday.tape import save_atomic, targets
    rep: dict[str, dict] = {}
    for s in stocks:
        r = rep[s] = {"ok": False, "expiries": 0, "strikes": 0, "quoted": 0, "error": None}
        try:
            for e in targets(src.expiries(s), n_expiries, now.date()):
                ch = src.chain(s, e, ts=now)
                if not float(ch.attrs.get("spot") or float("nan")) > 0:
                    ch.attrs["spot"] = parity_spot(ch)
                    if ch.attrs["spot"] > 0:
                        ch = fill_iv(ch, IntradayPricer())
                if not ch.attrs["spot"] > 0:
                    raise ValueError("no spot (no strike with both a call and a put LTP)")
                path = Path(data_dir) / str(now.date()) / "chains" / f"{s}_{e}_{now:%H%M}.csv"
                save_atomic(ch, path)
                r["expiries"] += 1
                r["strikes"] += len(ch)
                r["quoted"] += int(ch.attrs.get("quoted") or 0)
            r["ok"] = r["expiries"] > 0 and r["quoted"] > 0
            if not r["ok"]:
                r["error"] = "no expiry" if r["expiries"] == 0 else "no bid/ask"
        except Exception as exc:                                  # one stock's trouble never stops the rest
            r["error"] = f"{exc!s:.140}"
        say(f"  {s}: " + (f"{r['expiries']} expiry, {r['strikes']} strikes, {r['quoted']} quoted" if r["ok"]
                           else f"FAILED ({r['error']})"))
    return rep


# ---- health ---------------------------------------------------------------------------------------------------------
def health(day: dt.date, minutes_manifest: dict | None, stock_assets: list[str] | None, tape_assets: list[str] | None,
           indices, stocks_expected: int) -> list[dict]:
    """One row per source: {"source", "status": OK | MISSING | UNKNOWN, "detail"}.
    `minutes_manifest` is this run's kotak_backfill manifest (None: it did not run); the two asset lists are release
    listings (None: could not be read, which is UNKNOWN, not MISSING)."""
    rows = []
    for u in indices:
        rep = ((minutes_manifest or {}).get("underlyings") or {}).get(u)
        if minutes_manifest is None:
            rows.append({"source": f"minutes:{u}", "status": "UNKNOWN", "detail": "minutes step did not run"})
        elif not rep or not rep.get("bars"):
            err = next(iter((rep or {}).get("errors") or {}), "no contracts served")
            rows.append({"source": f"minutes:{u}", "status": "MISSING", "detail": f"no option bars ({err[:100]})"})
        elif str(rep.get("last", ""))[:10] != str(day):
            rows.append({"source": f"minutes:{u}", "status": "MISSING",
                         "detail": f"latest bar {str(rep.get('last'))[:16]}, not today ({rep.get('bars'):,} bars)"})
        else:
            rows.append({"source": f"minutes:{u}", "status": "OK",
                         "detail": f"{rep['bars']:,} bars, {rep.get('served')}/{rep.get('asked')} contracts"})
    if stock_assets is None:
        rows.append({"source": "stock_chains", "status": "UNKNOWN", "detail": "release not readable"})
    else:
        mine = [a for a in stock_assets if a.startswith(f"{day}_wide-eod") and a.endswith("_chains.parquet")]
        rows.append({"source": "stock_chains", "status": "OK" if mine else "MISSING",
                     "detail": f"{len(mine)} snapshot file(s) on the release for {stocks_expected} stocks asked"
                     if mine else "no end-of-day stock snapshot on the release"})
    if tape_assets is None:
        rows.append({"source": "desk_tape", "status": "UNKNOWN", "detail": "release not readable"})
    else:
        mine = [a for a in tape_assets if a.startswith(f"{day}_") and a.endswith("_chains.parquet")
                and "wide-eod" not in a]
        rows.append({"source": "desk_tape", "status": "OK" if mine else "MISSING",
                     "detail": f"{len(mine)} archived part(s) of the desk's chain tape" if mine
                     else "the live desk's chain tape was not archived"})
    return rows


def render(day: dt.date, rows: list[dict]) -> list[str]:
    return [f"HEALTH {day} {r['source']:<22} {r['status']:<8} {r['detail']}" for r in rows]


def write_health(day: dt.date, rows: list[dict], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{day}_health.json"
    p.write_text(json.dumps({"day": str(day), "rows": rows, "ok": all(r["status"] == "OK" for r in rows)}, indent=1))
    return p


def in_stock_window(now: pd.Timestamp, deadline: str) -> bool:
    """The book is live from the open to the close; past `deadline` (HH:MM, IST) the snapshot would be blank."""
    open_, _ = session_bounds(now.date())
    h, m = (int(x) for x in str(deadline).split(":"))
    return open_ <= now <= pd.Timestamp(dt.datetime.combine(now.date(), dt.time(h, m)), tz=IST)
