"""Every-minute option chains for every F&O stock, with quotes and the order book (`quantdesk data stock-tape`, record-stocks.yml).

Why: the index recorder keeps a chain snapshot of each index every minute; the F&O stocks had one end-of-day snapshot and minute candles of the near-the-money strikes. This records, for every F&O
stock (about 200: every underlying with a stock future in Kotak's F&O scrip master), every minute from the open to the close: the nearest expiry's chain around the money (LTP, volume, open interest,
best bid/offer and their sizes, implied volatility) AND the five-level order book of each contract in that window. Kotak only (consumer key, no login, no orders): the same chain source as the index tape.

How it fits in a minute: one chain is ~3 Kotak calls, so 200 stocks is ~600 calls a minute; one process cannot do that serially inside a minute. The stocks are split into SHARDS (stock k of the
sorted list goes to shard k mod N), each shard its own job with its own client, and the shards stagger their start inside the minute so they do not hit Kotak in the same second. A shard that
cannot finish a pass inside a minute simply records fewer minutes; the manifest says how many (coverage), and nothing else is affected.

Output per shard and half-day part: `<out>/<day>/chains/*.csv` (the tape's layout), `<out>/<day>/depth/<STOCK>_<expiry>_<HHMM>.csv` (the order books), compacted to
`<out>/_parts/<day>_<part>_{chains,tape,depth}.parquet` plus `<day>_<part>_manifest.json` (counts only). `consolidate` merges all of a day's parts into three files and one manifest."""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

from ..intraday.chains import load_chain
from ..intraday.feeds import session_bounds
from ..intraday.kotak import KotakOptionChain
from ..intraday.tape import ChainTape, completeness
from .archive import compact_day

NAME_OK = re.compile(r"^[A-Z0-9&-]{1,20}$")
EXPIRIES = 1                    # the nearest expiry of each stock (stock options are monthly)
STRIKES = 10                    # strikes each side of the money (Kotak wants a multiple of 10)
LEVELS = 5                      # order-book levels kept per contract
MIN_GAP = 0.2                   # seconds between one shard's Kotak calls (the other recorders and the relay share the key; the limit is 25 a second in all)
NOTE = ("every-minute chain (LTP, volume, open interest, best bid/offer and sizes) and five-level order book of the nearest expiry, around the money, of every F&O stock, from Kotak Neo; "
        "data collection only, nothing here trades")


def resolve(client) -> list[str]:
    """Every F&O stock: each underlying with a stock future in Kotak's F&O scrip master, sorted (so every shard and both halves of the day agree on the list)."""
    from ..intraday.kotak import scrip_master
    from .kotak_universe import stock_names
    return [n for n in stock_names(scrip_master(client, "nse_fo")) if NAME_OK.match(n)]


def shard_of(names: list[str], shard: int, shards: int) -> list[str]:
    if shards < 1 or not 0 <= shard < shards:
        raise ValueError(f"shard {shard} of {shards}")
    return sorted(names)[shard::shards]


def depth_writer(data_dir: Path):
    """The tape's `extra` hook: the order book of a snapshot to <day>/depth/<same name>.csv (one row per contract: strike, side, b1p..b5q, a1p..a5q)."""
    def write(ch: pd.DataFrame, path: Path) -> None:
        book = ch.attrs.get("depth") or []
        if not book:
            return
        day_dir = path.parent.parent
        out = day_dir / "depth" / path.name
        out.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(book).to_csv(out, index=False)
    return write


def compact_depth(day_dir: Path) -> pd.DataFrame:
    """The day's order-book files -> one long frame: ts, underlying, expiry, strike, side, b1p.."""
    parts = []
    for p in sorted((Path(day_dir) / "depth").glob("*.csv")):
        u, e, hhmm = p.stem.rsplit("_", 2)
        chain = Path(day_dir) / "chains" / p.name
        ts = pd.Timestamp(load_chain(chain).attrs["ts"]) if chain.exists() else None
        if ts is None:
            continue
        df = pd.read_csv(p)
        df.insert(0, "ts", ts)
        df.insert(1, "underlying", u)
        df.insert(2, "expiry", pd.Timestamp(e))
        parts.append(df)
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def run_shard(client, root: Path, shard: int, shards: int, part: str, until: dt.time | None = None, strikes: int = STRIKES, expiries: int = EXPIRIES, levels: int = LEVELS,
              min_gap: float = MIN_GAP, say=print, names: list[str] | None = None, source=None, clock=None, sleep=None) -> dict:
    """Record this shard's stocks until `until` (or the close), compact, and write the part's files and manifest. Returns the manifest. Never raises on a Kotak problem."""
    import time
    root = Path(root)
    data = root / "data"
    mine = shard_of(names if names is not None else resolve(client), shard, shards)
    src = source or KotakOptionChain(client, strikes=strikes, depth_levels=levels)
    offset = 5.0 + (50.0 * shard / max(shards, 1))                         # spread the shards over the first 55 seconds of the minute
    tape = ChainTape(src, data, {s: expiries for s in mine}, every_min=1.0, say=say, offset_s=offset, extra=depth_writer(data), clock=clock,
                     **({"sleep": sleep} if sleep else {}))
    now = tape.clock()
    rep = tape.run(until) if mine else {"day": str(now.date()), "minutes_in_span": 0, "series": {}}
    day_dir = data / str(now.date())
    open_, close = session_bounds(now.date())
    parts = root / "_parts"
    parts.mkdir(parents=True, exist_ok=True)
    frames = compact_day(day_dir) if day_dir.exists() else {}
    names_written = []
    for kind in ("chains", "tape"):
        if kind in frames:
            f = f"{now.date()}_{part}_{kind}.parquet"
            frames[kind].to_parquet(parts / f, index=False, compression="zstd")
            names_written.append(f)
    book = compact_depth(day_dir) if day_dir.exists() else pd.DataFrame()
    if len(book):
        f = f"{now.date()}_{part}_depth.parquet"
        book.to_parquet(parts / f, index=False, compression="zstd")
        names_written.append(f)
    man = manifest(rep, mine, shard, shards, part, str(now.date()), len(frames.get("chains", [])), len(book))
    (parts / f"{now.date()}_{part}_manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    man["files"] = names_written
    return man


def manifest(rep: dict, mine: list[str], shard: int, shards: int, part: str, day: str, chain_rows: int, depth_rows: int) -> dict:
    """Counts only: which stocks, how many minutes each got, failures. No price."""
    series = {k.split(" ")[0]: v for k, v in (rep.get("series") or {}).items()}
    return {"evidence": "stock_chain_tape", "source": "kotak", "day": day, "part": part, "shard": shard, "shards": shards, "note": NOTE,
            "stocks": len(mine), "recorded": sum(1 for s in mine if series.get(s, {}).get("minutes")), "span_minutes": rep.get("minutes_in_span"),
            "minutes": {s: int(series[s]["minutes"]) for s in mine if s in series}, "attempts": rep.get("attempts"), "failures": rep.get("failures"),
            "median_secs": rep.get("median_secs"), "top_errors": {str(k)[:80]: int(v) for k, v in (rep.get("top_errors") or {}).items()},
            "chain_rows": int(chain_rows), "depth_rows": int(depth_rows)}


def consolidate(parts_dir: Path, out_dir: Path, day: str) -> dict:
    """Merge all of one day's parts (every shard, both halves) into <day>_stock_chains.parquet, _stock_depth.parquet, _stock_tape.parquet and one manifest. Streams the big tables."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    parts_dir, out_dir = Path(parts_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written, rows = [], {}
    for kind in ("chains", "depth", "tape"):
        files = sorted(parts_dir.glob(f"{day}_*_{kind}.parquet"))
        if not files:
            continue
        cols: list[str] = []
        for f in files:
            for c in pq.read_schema(f).names:
                if c not in cols:
                    cols.append(c)
        out = out_dir / f"{day}_stock_{kind}.parquet"
        writer, n = None, 0
        for f in files:
            df = pd.read_parquet(f).reindex(columns=cols)
            tbl = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(out, tbl.schema, compression="zstd")
                schema = tbl.schema
            writer.write_table(tbl.cast(schema, safe=False) if tbl.schema != schema else tbl)
            n += len(df)
        if writer is not None:
            writer.close()
            written.append(out.name)
            rows[kind] = n
    mans = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(parts_dir.glob(f"{day}_*_manifest.json"))]
    per_stock: dict[str, int] = {}
    for m in mans:
        for s, n in (m.get("minutes") or {}).items():
            per_stock[s] = per_stock.get(s, 0) + int(n)
    span = max((int(m.get("span_minutes") or 0) for m in mans), default=0)
    total = {"evidence": "stock_chain_tape", "source": "kotak", "day": day, "note": NOTE, "parts": len(mans), "shards": max((int(m.get("shards") or 0) for m in mans), default=0),
             "stocks": sum(int(m.get("stocks") or 0) for m in mans if str(m.get("part", "")).startswith("morning")) or len(per_stock),
             "recorded": len(per_stock), "minutes_total": sum(per_stock.values()), "session_minutes": 375,
             "attempts": sum(int(m.get("attempts") or 0) for m in mans), "failures": sum(int(m.get("failures") or 0) for m in mans),
             "rows": rows, "files": written, "per_stock_minutes": per_stock}
    expected = total["stocks"] * total["session_minutes"]
    total["coverage"] = round(total["minutes_total"] / expected, 4) if expected else None
    (out_dir / f"{day}_stock_chains_manifest.json").write_text(json.dumps(total, indent=1), encoding="utf-8")
    return total


def publishable(m: dict) -> list[str]:
    """Reasons a consolidated manifest must not be published: it carries counts and stock names only."""
    bad = []
    allowed = {"evidence", "source", "day", "note", "parts", "shards", "stocks", "recorded", "minutes_total", "session_minutes", "attempts", "failures", "rows", "files", "per_stock_minutes", "coverage"}
    for k in m:
        if k not in allowed:
            bad.append(f"/{k}: not an allowed field")
    for k, v in (m.get("per_stock_minutes") or {}).items():
        if not NAME_OK.match(str(k)) or not isinstance(v, int) or isinstance(v, bool):
            bad.append(f"/per_stock_minutes/{k}")
    for k in ("parts", "shards", "stocks", "recorded", "minutes_total", "session_minutes", "attempts", "failures"):
        if k in m and (not isinstance(m[k], int) or isinstance(m[k], bool)):
            bad.append(f"/{k}: not a count")
    if len(m.get("per_stock_minutes") or {}) > 400 or len(m.get("files") or []) > 10:
        bad.append("too many entries")
    return bad

