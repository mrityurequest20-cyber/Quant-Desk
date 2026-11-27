"""The exchange's position-limit rules for stock F&O: the ban list and market-wide position limits (MWPL).

NSE publishes, every evening, for the next session:
  * the securities in the F&O ban period: no new positions may be opened in them, only reduced (fo_secban_DDMMYYYY.csv)
  * each F&O stock's market-wide position limit, the open interest against it, and the room left (combineoi_DDMMYYYY)
A stock enters the ban when its open interest crosses 95% of its MWPL and leaves it when it falls back below 80%.
The ban itself is read from NSE's own list, never inferred from the percentage.

The files have changed shape over the years (SEBI moved MWPL to futures-equivalent open interest in 2025), so the
parsers find columns by what they mean, not by position, and fail loudly on a file they cannot read. The live probe
in .github/workflows/marketlens.yml fetches the real files on every pull request that touches MarketLens and runs
them through these parsers.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

BAN_ENTER = 0.95
BAN_EXIT = 0.80
# candidate locations, newest first: NSE has moved archive files before, so each is tried in order
BAN_PATHS = ("/content/fo/fo_secban_{d:%d%m%Y}.csv", "/archives/fo/sec_ban/fo_secban_{d:%d%m%Y}.csv")
MWPL_PATHS = ("/archives/nsccl/mwpl/combineoi_{d:%d%m%Y}.zip", "/archives/nsccl/mwpl/combineoi_{d:%d%m%Y}.csv",
              "/content/nsccl/combineoi_{d:%d%m%Y}.zip")


class FormatError(ValueError):
    """A file that arrived but could not be read as what it claims to be."""


# ---------------- parsers ----------------

def parse_ban(raw: bytes) -> list[str]:
    """NSE's ban file: a title line ('Securities in Ban For Trade Date 27-NOV-2026:'), then 'n,SYMBOL' lines, or
    'NIL' when nothing is banned. Returns the symbols (possibly none)."""
    text = raw.decode("utf-8", "replace").replace("\r", "")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines or "ban" not in lines[0].lower():
        raise FormatError(f"not a ban list: {lines[:1]}")
    out = []
    for ln in lines[1:]:
        parts = [p.strip().strip('"') for p in ln.split(",")]
        if len(parts) >= 2 and parts[0].isdigit() and re.fullmatch(r"[A-Z0-9&\-]+", parts[1]):
            out.append(parts[1])
        elif ln.upper().strip(",") == "NIL" or "nil" in ln.lower():
            continue
        else:
            raise FormatError(f"unexpected ban line: {ln!r}")
    if "nil" in lines[0].lower() and out:
        raise FormatError("ban file says NIL and lists symbols")
    return out


def _csv_bytes(raw: bytes) -> bytes:
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise FormatError(f"zip without a csv: {z.namelist()}")
            return z.read(names[0])
    return raw


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def parse_mwpl(raw: bytes) -> pd.DataFrame:
    """NSE's combined open interest file: per F&O stock its MWPL and the open interest counted against it (the
    futures-equivalent OI since SEBI's 2025 change, plain OI before). Returns symbol, mwpl, oi, util, limit_text."""
    df = pd.read_csv(io.BytesIO(_csv_bytes(raw)), dtype=str)
    cols = {c: re.sub(r"\s+", " ", c.strip().lower()) for c in df.columns}
    df = df.rename(columns=cols)

    def pick(*needles, avoid=()):
        for c in df.columns:
            if all(n in c for n in needles) and not any(a in c for a in avoid):
                return c
        return None

    sym = pick("nse symbol") or pick("symbol")
    mwpl = pick("mwpl")
    oi = pick("future", "equivalent") or pick("fut", "eq") or pick("open interest", avoid=("limit",))
    lim = pick("limit")
    if not (sym and mwpl and oi):
        raise FormatError(f"MWPL columns not found in {list(df.columns)}")
    out = pd.DataFrame({"symbol": df[sym].astype(str).str.strip().str.upper(), "mwpl": _num(df[mwpl]),
                        "oi": _num(df[oi])})
    out["limit_text"] = df[lim].astype(str).str.strip() if lim else ""
    out = out.dropna(subset=["mwpl", "oi"])
    out = out[(out["mwpl"] > 0) & (out["symbol"] != "")]
    if out.empty:
        raise FormatError("MWPL file had no usable rows")
    out["util"] = out["oi"] / out["mwpl"]
    if (out["util"] > 3).mean() > 0.2:                  # units mismatch, not a market state
        raise FormatError("MWPL utilisation implausible: columns misread")
    out.attrs["oi_column"] = oi
    return out.drop_duplicates("symbol").reset_index(drop=True)


# ---------------- fetching ----------------

def _first(nse, paths, day):
    from quantdesk.data.nse import NotPublished
    last = None
    for p in paths:
        try:
            raw, url = nse.archive(p.format(d=day))
            return raw, url
        except NotPublished as e:
            last = e
    raise last or FileNotFoundError(day)


def fetch(dest: Path, days: list[dt.date], nse=None, strict: bool = False, say=print) -> dict:
    """Download the ban list and MWPL files for the given days into dest (two Parquet tables, merged with what is
    already there). A day NSE has not published is skipped. strict: raise on any file that arrived but did not
    parse (the probe uses this)."""
    from quantdesk.data.nse import NSE, NotPublished
    nse = nse or NSE()
    dest.mkdir(parents=True, exist_ok=True)
    bans, mw, report = [], [], {"ban_days": 0, "mwpl_days": 0, "errors": [], "urls": set()}
    for d in days:
        for kind, paths, parse in (("ban", BAN_PATHS, parse_ban), ("mwpl", MWPL_PATHS, parse_mwpl)):
            try:
                raw, url = _first(nse, paths, d)
            except (NotPublished, FileNotFoundError):
                continue
            except Exception as e:                  # network trouble: the next run fills the gap
                report["errors"].append(f"{d} {kind}: {type(e).__name__}: {e}")
                continue
            try:
                parsed = parse(raw)
            except FormatError as e:
                report["errors"].append(f"{d} {kind}: {e}")
                if strict:
                    raise
                continue
            report["urls"].add(url.rsplit("/", 1)[0])
            if kind == "ban":
                bans += [{"date": pd.Timestamp(d), "symbol": s} for s in parsed]
                bans.append({"date": pd.Timestamp(d), "symbol": ""})     # a marker: this day's list was read
                report["ban_days"] += 1
            else:
                parsed.insert(0, "date", pd.Timestamp(d))
                mw.append(parsed)
                report["mwpl_days"] += 1
    _merge(dest / "rules_ban.parquet", pd.DataFrame(bans, columns=["date", "symbol"]), ["date", "symbol"])
    _merge(dest / "rules_mwpl.parquet", pd.concat(mw) if mw else pd.DataFrame(), ["date", "symbol"])
    report["urls"] = sorted(report["urls"])
    say(f"rules: {report['ban_days']} ban lists, {report['mwpl_days']} MWPL files, {len(report['errors'])} errors")
    return report


def _merge(path: Path, new: pd.DataFrame, key: list[str]) -> None:
    if new.empty:
        return
    if path.exists():
        new = pd.concat([pd.read_parquet(path), new]).drop_duplicates(key, keep="last")
    new.sort_values(key).to_parquet(path, index=False)


def load(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    b, m = Path(root) / "rules_ban.parquet", Path(root) / "rules_mwpl.parquet"
    ban = pd.read_parquet(b) if b.exists() else pd.DataFrame(columns=["date", "symbol"])
    mwpl = pd.read_parquet(m) if m.exists() else pd.DataFrame(columns=["date", "symbol", "mwpl", "oi", "util"])
    return ban, mwpl


# ---------------- what the app shows ----------------

def stock_block(symbol: str, ban: pd.DataFrame, mwpl: pd.DataFrame) -> dict | None:
    """For one stock: is it in the ban for the next session, how full its MWPL is, the trend, and the ban history."""
    if mwpl.empty and ban.empty:
        return None
    out: dict = {"symbol": symbol}
    read_days = sorted(ban.loc[ban["symbol"] == "", "date"].unique()) if len(ban) else []
    if read_days:
        last = read_days[-1]
        banned_days = ban.loc[(ban["symbol"] == symbol), "date"]
        out["ban_date"] = str(pd.Timestamp(last).date())
        out["in_ban"] = bool((banned_days == last).any())
        out["ban_days"] = int(banned_days.nunique())
        out["ban_window"] = len(read_days)
    m = mwpl[mwpl["symbol"] == symbol].sort_values("date") if len(mwpl) else mwpl
    if len(m):
        r = m.iloc[-1]
        out.update({"mwpl_date": str(pd.Timestamp(r["date"]).date()), "util": float(r["util"]),
                    "mwpl": float(r["mwpl"]), "oi": float(r["oi"]), "limit_text": str(r.get("limit_text", "")),
                    "history": {"d": [str(pd.Timestamp(x).date()) for x in m["date"]],
                                "util": [round(float(x), 4) for x in m["util"]]}})
        if len(m) > 5:
            out["util_chg5"] = float(m["util"].iat[-1] - m["util"].iat[-6])
    return out


def sentence(b: dict | None) -> str | None:
    if not b:
        return None
    if b.get("in_ban"):
        return (f"{b['symbol']} is in the F&O ban for the {b['ban_date']} session: no new positions can be opened, "
                f"only existing ones reduced, until its open interest falls back below 80% of the limit.")
    u = b.get("util")
    if u is None:
        return None
    s = f"{b['symbol']} has used {u * 100:.0f}% of its market-wide position limit (the ban starts at 95%)."
    if u >= 0.80:
        s += " It is close: a few busy sessions can put it in the ban, which freezes new positions."
    return s
