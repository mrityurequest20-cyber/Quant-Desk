"""TrueData Velocity 2.0 exports → audited, immutable, provenance-stamped Parquet (raw files are never modified).

The export arrives as text files: one per symbol, optionally under folders such as `Trade 1 Daily`, `Trade 1 Minute`,
`Trade 5 Minute` and `Trade 1 Tick`. Nothing about their layout is assumed. The importer reads each file's bytes and
records what it finds:
- line endings, header, fields per row;
- the date and time formats;
- whether the times sit in NSE's session in IST;
- the timeframe, from the timestamps themselves (the folder name is only a hint, and a conflict is reported);
- which numeric columns are genuinely populated.

The trailing numeric columns get no meaning (volume, open interest, …) unless their content supports one. All-zero
columns are reported as not populated.

Every malformed or suspicious row is kept visible:
- rejected rows are listed with line numbers and reasons;
- duplicates are counted (identical ones kept once, conflicting ones dropped);
- weekend sessions are flagged, not dropped.

Output, written once (re-importing the same files is a no-op, and changed content becomes a new batch):

  runtime/external/truedata/<importer>-<batch>/
      manifest.json   provider, source root and commit, importer version, batch, per file: path, size, sha256, schema,
                      timeframe, rows, rejects, duplicates, coverage, populated columns
      <timeframe>/symbol=<S>.parquet   normalised bars with the source timestamp, file and line of every row
      quality.json / quality.md        the audit, human-readable
      verification.json                the independent check (Yahoo daily) once run

Status `external_unverified` until `verify()` passes. Uses are restricted like the aeron7 dataset's:
- index candles are not option chains, bid/ask, IV, trade-by-trade footprint, aggressor volume or depth;
- they never qualify an option strategy, a paper gate or a promotion.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .base import DataProvider
from .external_aeron import ImmutableViolation, ForbiddenUse, YAHOO, _write_once, frame_hash, source_commit

PROVIDER = "truedata"
SOURCE = "TrueData Velocity 2.0 export"
IMPORTER_VERSION = "truedata-1"
IST = "Asia/Kolkata"
UNVERIFIED, VERIFIED = "external_unverified", "external_verified"
TIMEFRAME_HINTS = {"daily": "1d", "1 daily": "1d", "1 minute": "1m", "5 minute": "5m", "tick": "tick"}
SYMBOL_ALIASES = {"NIFTY": "NIFTY", "NIFTY 50": "NIFTY", "NIFTY50": "NIFTY", "NIFTY-I": "NIFTY",
                  "BANKNIFTY": "BANKNIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTYBANK": "BANKNIFTY"}
DATE_FORMATS = ["%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%b-%Y"]
TIME_FORMATS = ["%H:%M:%S", "%H:%M"]
SESSION = (dt.time(9, 15), dt.time(15, 30))
ALLOWED_USES = frozenset({"underlying_features", "direction_research", "regime_research", "development_folds",
                          "daily_backtest"})
FORBIDDEN_NOTE = ("TrueData index candles are not option-chain, bid/ask, IV, trade-by-trade footprint, aggressor volume "
                  "or order-book data, and never qualify an option strategy, a DTE change, a paper gate, a promotion or "
                  "a profitability claim")
TOLERANCE = {"open": 0.003, "high": 0.002, "low": 0.002, "close": 0.003}
MIN_PASS_RATE, MIN_COMPARED = 0.95, 50
MAX_EXAMPLES = 20


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def discover(root: Path) -> list[dict]:
    """Every data file under the export root (not .git, not README), with the folder's timeframe hint."""
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or ".git" in p.parts or p.suffix.lower() not in (".txt", ".csv"):
            continue
        hint = None
        for part in p.relative_to(root).parts[:-1]:
            low = part.lower()
            for k, tf in TIMEFRAME_HINTS.items():
                if low.endswith(k):
                    hint = tf
        sym = SYMBOL_ALIASES.get(p.stem.upper().strip(), p.stem.upper().strip())
        out.append({"path": p.relative_to(root).as_posix(), "symbol": sym, "timeframe_hint": hint})
    return out


def _parse(series: pd.Series, formats: list[str]) -> tuple[pd.Series, str | None]:
    """Try each format on the whole column; the first that parses every value wins (no guessing per row)."""
    best, best_fmt, best_ok = None, None, -1
    for f in formats:
        p = pd.to_datetime(series, format=f, errors="coerce")
        ok = int(p.notna().sum())
        if ok > best_ok:
            best, best_fmt, best_ok = p, f, ok
        if ok == len(series):
            break
    return best, best_fmt


def detect_timeframe(ts: pd.Series) -> str:
    """From the timestamps: one constant time and one row per date → daily; else the modal step within a day."""
    d = ts.dt.date
    if ts.dt.time.nunique() == 1 and not d.duplicated().any():
        return "1d"
    step = ts.groupby(d).diff().dt.total_seconds().dropna()
    if step.empty:
        return "unknown"
    mode = float(step.mode().iloc[0])
    return {60.0: "1m", 300.0: "5m"}.get(mode, "tick" if mode < 60 else f"{int(mode)}s")


def read_file(path: Path, symbol: str, hint: str | None = None) -> tuple[pd.DataFrame, dict]:
    """One export file → (accepted normalised rows, its audit). Nothing is dropped silently."""
    raw = Path(path).read_bytes()
    rep = {"bytes": len(raw), "sha256": _sha(raw), "crlf": raw.count(b"\r\n"), "lf_only": raw.count(b"\n") - raw.count(b"\r\n"),
           "symbol": symbol, "timeframe_hint": hint, "rejected": {}, "reject_examples": []}
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
        rep["encoding"] = "latin-1"
    lines = text.splitlines()
    rows = [(i + 1, ln) for i, ln in enumerate(lines) if ln.strip()]
    rep["lines"], rep["blank_lines"] = len(lines), len(lines) - len(rows)

    def reject(lineno, why, line):
        rep["rejected"][why] = rep["rejected"].get(why, 0) + 1
        if len(rep["reject_examples"]) < MAX_EXAMPLES:
            rep["reject_examples"].append({"line": lineno, "reason": why, "text": line[:120]})
    # header: a first row whose first field doesn't look like a date
    rep["header"] = None
    if rows and not re.match(r"^\s*\d", rows[0][1]):
        rep["header"] = rows[0][1][:200]
        rows = rows[1:]
    split = [(n, ln, [x.strip() for x in ln.split(",")]) for n, ln in rows]
    widths = pd.Series([len(f) for _, _, f in split]).value_counts().to_dict() if split else {}
    rep["fields_per_row"] = {int(k): int(v) for k, v in widths.items()}
    if not split:
        rep["schema"] = "empty"
        return pd.DataFrame(), rep
    width = max(widths, key=widths.get)
    if width < 6:
        rep["schema"] = f"unrecognised ({width} fields; expected date,time,open,high,low,close[,…])"
        for n, ln, _ in split:
            reject(n, "unrecognised schema", ln)
        return pd.DataFrame(), rep
    good = []
    for n, ln, f in split:
        if len(f) != width:
            reject(n, f"{len(f)} fields, expected {width}", ln)
        else:
            good.append((n, f))
    cols = ["date", "time", "open", "high", "low", "close"] + [f"extra_{i}" for i in range(1, width - 5)]
    df = pd.DataFrame([f for _, f in good], columns=cols)
    df["source_line"] = [n for n, _ in good]
    dates, dfmt = _parse(df["date"], DATE_FORMATS)
    times, tfmt = _parse(df["time"], TIME_FORMATS)
    rep["date_format"], rep["time_format"] = dfmt, tfmt
    rep["schema"] = "date,time,open,high,low,close" + "".join(f",extra_{i}" for i in range(1, width - 5))
    num_cols = ["open", "high", "low", "close"] + [c for c in cols if c.startswith("extra_")]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    bad_ts = dates.isna() | times.isna()
    bad_num = df[["open", "high", "low", "close"]].isna().any(axis=1)
    o, h, l, c = (df[x] for x in ["open", "high", "low", "close"])
    bad_ohlc = ~bad_num & ((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0) | (h < l) | (h < np.maximum(o, c) - 1e-9) |
                           (l > np.minimum(o, c) + 1e-9))
    for mask, why in ((bad_ts, "unparsable date/time"), (bad_num & ~bad_ts, "non-numeric price"),
                      (bad_ohlc & ~bad_ts, "invalid OHLC (≤0, high<low, or open/close outside the range)")):
        for i in np.flatnonzero(mask.to_numpy()):
            reject(int(df["source_line"].iat[i]), why, ",".join(str(x) for x in good[i][1]))
    keep = ~(bad_ts | bad_num | bad_ohlc)
    df = df[keep].copy()
    ts = pd.to_datetime(dates[keep].dt.strftime("%Y-%m-%d") + " " + times[keep].dt.strftime("%H:%M:%S"))
    df["source_ts"] = df["date"] + " " + df["time"]
    df["ts"] = ts.dt.tz_localize(IST)
    rep["out_of_order"] = int((df["ts"].diff().dt.total_seconds() < 0).sum())
    df = df.sort_values(["ts", "source_line"])
    dup_exact = df.duplicated(["ts"] + num_cols, keep="first")
    same_ts = df.duplicated("ts", keep=False) & ~df.duplicated(["ts"] + num_cols, keep=False)
    rep["duplicate_rows_identical"] = int(dup_exact.sum())
    conflicted = df["ts"][same_ts].unique()
    rep["duplicate_timestamps_conflicting"] = int(len(conflicted))
    for i in np.flatnonzero(df["ts"].isin(conflicted).to_numpy()):
        reject(int(df["source_line"].iat[i]), "conflicting rows for one timestamp", df["source_ts"].iat[i])
    df = df[~dup_exact & ~df["ts"].isin(conflicted)]
    tf = detect_timeframe(df["ts"]) if len(df) else "unknown"
    rep["timeframe"] = tf
    rep["timeframe_conflict"] = bool(hint and hint != tf)
    rep["rows_accepted"] = int(len(df))
    rep["rows_rejected"] = int(sum(rep["rejected"].values()))
    rep["first_ts"], rep["last_ts"] = (str(df["source_ts"].iat[0]), str(df["source_ts"].iat[-1])) if len(df) else (None, None)
    rep["populated"] = {c: {"nonzero": int((df[c].fillna(0) != 0).sum()), "missing": int(df[c].isna().sum()),
                            "distinct": int(df[c].nunique())} for c in num_cols if c.startswith("extra_")}
    rep["not_populated"] = [c for c, s in rep["populated"].items() if s["nonzero"] == 0]
    wd = df["ts"].dt.weekday
    rep["weekend_rows"] = sorted({str(x) for x in df.loc[wd >= 5, "ts"].dt.date})
    tod = df["ts"].dt.time
    if tf in ("1m", "5m", "tick"):
        inside = (tod >= SESSION[0]) & (tod <= SESSION[1])
        rep["outside_session_rows"] = int((~inside).sum())
        rep["ist_evidence"] = (f"{inside.mean():.1%} of timestamps fall inside 09:15–15:30, NSE's session in IST "
                               "(UTC timestamps would sit at 03:45–10:00)")
    else:
        rep["ist_evidence"] = (f"one bar per date stamped {df['time'].iat[0] if len(df) else '—'}: an end-of-day "
                               "marker, not a trade time; dates are NSE session dates")
    df["symbol"], df["timeframe"], df["provider"] = symbol, tf, PROVIDER
    keep_cols = ["symbol", "timeframe", "ts", "open", "high", "low", "close"] + \
                [c for c in num_cols if c.startswith("extra_")] + ["source_ts", "source_line", "provider"]
    return df[keep_cols].reset_index(drop=True), rep


def session_coverage(df: pd.DataFrame, tf: str) -> dict:
    """Intraday files: per-session bar counts against the session's expected bars (start- or end-labelled)."""
    if tf not in ("1m", "5m") or df.empty:
        return {}
    step = 1 if tf == "1m" else 5
    expect = 375 // step
    g = df.groupby(df["ts"].dt.date)
    first = g["ts"].min().dt.time.value_counts()
    label = "end" if first.index[0] > SESSION[0] else "start"
    counts = g.size()
    return {"label": label, "expected_per_session": expect, "sessions": int(len(counts)),
            "complete_sessions": int((counts >= expect).sum()),
            "missing_bars_total": int(np.maximum(expect - counts, 0).sum()),
            "missing_rate": float(np.maximum(expect - counts, 0).sum() / (expect * len(counts))),
            "worst": {str(k): int(v) for k, v in counts.nsmallest(5).items()}}


def batch_id(files: list[dict]) -> str:
    return _sha(json.dumps(sorted((f["path"], f["sha256"]) for f in files)).encode())[:12]


def import_export(source_root: Path, out_root: Path, say=print) -> dict:
    """Audit and import every file under `source_root`. Returns the manifest; writes nothing to the source."""
    source_root, out_root = Path(source_root), Path(out_root)
    found = discover(source_root)
    if not found:
        raise FileNotFoundError(f"no .txt/.csv files under {source_root}")
    frames, files = {}, []
    for f in found:
        df, rep = read_file(source_root / f["path"], f["symbol"], f["timeframe_hint"])
        rep["path"] = f["path"]
        rep["coverage"] = session_coverage(df, rep.get("timeframe"))
        files.append(rep)
        if len(df):
            frames.setdefault((rep["timeframe"], f["symbol"]), []).append(df)
        say(f"  {f['path']}: {rep.get('schema')} · {rep.get('timeframe')} · {rep.get('rows_accepted', 0)} rows accepted, "
            f"{rep.get('rows_rejected', 0)} rejected · {rep.get('first_ts')} → {rep.get('last_ts')}")
    bid = batch_id(files)
    ds = out_root / "truedata" / f"{IMPORTER_VERSION}-{bid}"
    man_path = ds / "manifest.json"
    if man_path.exists():
        old = json.loads(man_path.read_text())
        say(f"  batch {bid} already imported on {old['imported_at']}: verifying it is unchanged")
    partitions = {}
    for (tf, sym), parts in sorted(frames.items()):
        df = pd.concat(parts).sort_values("ts")
        clash = df.duplicated("ts", keep=False) & ~df.duplicated(["ts", "open", "high", "low", "close"], keep=False)
        if clash.any():                                   # the same bar from two files that disagree: keep neither
            df = df[~df["ts"].isin(df.loc[clash, "ts"])]
        df = df.drop_duplicates(["ts", "open", "high", "low", "close"])
        df["batch"] = bid
        partitions[f"{tf}/symbol={sym}.parquet"] = {"rows": int(len(df)), "hash": _write_once(df, ds / tf / f"symbol={sym}.parquet"),
                                                    "cross_file_conflicts": int(clash.sum())}
    man = {"provider": PROVIDER, "source": SOURCE, "source_root": str(source_root), "source_commit": source_commit(source_root),
           "importer_version": IMPORTER_VERSION, "batch": bid, "dataset": ds.name, "status": UNVERIFIED,
           "allowed_uses": sorted(ALLOWED_USES), "not_for": FORBIDDEN_NOTE, "files": files, "partitions": partitions,
           "imported_at": json.loads(man_path.read_text())["imported_at"] if man_path.exists() else
           pd.Timestamp.now(tz=IST).isoformat()}
    if man_path.exists():
        old = json.loads(man_path.read_text())
        man["status"] = old.get("status", UNVERIFIED)
        if old.get("partitions") != partitions:
            raise ImmutableViolation(f"{ds} exists with different partitions")
    ds.mkdir(parents=True, exist_ok=True)
    man_path.write_text(json.dumps(man, indent=1, default=str))
    (ds / "quality.md").write_text(render_quality(man))
    man["path"] = str(ds)
    return man


def render_quality(man: dict) -> str:
    L = [f"# TrueData export audit · batch {man['batch']} ({man['importer_version']})", "",
         f"Source: {man['source']} at `{man['source_root']}` (commit {str(man.get('source_commit'))[:10]}). "
         f"Status **{man['status']}**. {man['not_for']}.", "",
         "| file | bytes | sha256 | schema | timeframe | accepted | rejected | first → last | duplicates (identical / conflicting) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for f in man["files"]:
        L.append(f"| {f['path']} | {f['bytes']:,} | `{f['sha256'][:12]}` | {f.get('schema')} | {f.get('timeframe')}"
                 f"{' ⚠ folder says ' + str(f['timeframe_hint']) if f.get('timeframe_conflict') else ''} | "
                 f"{f.get('rows_accepted', 0)} | {f.get('rows_rejected', 0)} | {f.get('first_ts')} → {f.get('last_ts')} | "
                 f"{f.get('duplicate_rows_identical', 0)} / {f.get('duplicate_timestamps_conflicting', 0)} |")
    v = man.get("verification")
    if v:
        L += ["", f"## Independent check ({v.get('reference')}, {v['checked_at'][:16]}): "
                  f"{'passed' if v['passed'] else 'FAILED'}", "",
              f"Tolerances: {TOLERANCE} (relative). A weekday absent from both sides is a market holiday.", ""]
        for k, x in v.get("series", {}).items():
            L.append(f"- {k}: {x['compared']} dates compared, {x['pass_rate']:.1%} within tolerance; only in TrueData: "
                     f"{', '.join(x['only_in_truedata']) or 'none'}; only in the reference: {', '.join(x['only_in_reference']) or 'none'}.")
    L += ["", "## Per file", ""]
    for f in man["files"]:
        L.append(f"**{f['path']}**")
        L.append(f"- Layout: {f.get('fields_per_row')} fields per row; header: {f.get('header') or 'none'}; line endings: "
                 f"{f['crlf']} CRLF, {f['lf_only']} LF; date format `{f.get('date_format')}`, time format `{f.get('time_format')}`.")
        L.append(f"- Time zone: {f.get('ist_evidence')}.")
        if f.get("not_populated"):
            L.append(f"- Not populated (zero in every row, given no meaning): {', '.join(f['not_populated'])}.")
        pop = [c for c in f.get("populated", {}) if c not in f.get("not_populated", [])]
        if pop:
            L.append(f"- Populated extra columns (meaning not assumed): {', '.join(pop)}.")
        if f.get("weekend_rows"):
            L.append(f"- Weekend sessions kept and flagged: {', '.join(f['weekend_rows'])}.")
        if f.get("coverage"):
            c = f["coverage"]
            L.append(f"- Coverage: {c['sessions']} sessions, {c['complete_sessions']} complete; {c['missing_bars_total']} "
                     f"missing bars ({c['missing_rate']:.2%}); bars labelled by their {c['label']}.")
        if f.get("rejected"):
            L.append(f"- Rejected: {f['rejected']}; examples: " +
                     "; ".join(f"line {x['line']} ({x['reason']})" for x in f["reject_examples"][:5]) + ".")
        L.append("")
    return "\n".join(L) + "\n"


# ---- the independent check ------------------------------------------------------------------------------------------
def yahoo_daily_ohlc(symbol: str, start, end) -> pd.DataFrame:
    import yfinance as yf
    d = yf.download(YAHOO[symbol], start=str(pd.Timestamp(start).date()),
                    end=str((pd.Timestamp(end) + pd.Timedelta(days=1)).date()), interval="1d", progress=False, auto_adjust=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    d = d.rename(columns=lambda c: str(c).lower())
    if d.empty or not {"open", "high", "low", "close"} <= set(d.columns):
        raise RuntimeError(f"Yahoo returned nothing usable for {symbol}")
    d.index = pd.to_datetime(d.index).date
    return d[["open", "high", "low", "close"]]


def verify(ds: Path, reference=yahoo_daily_ohlc, say=print) -> dict:
    """Every daily bar against Yahoo's daily OHLC (pre-declared TOLERANCE). Dates present on one side only are listed:
    a weekday missing from both is a market holiday, not a gap. Passes when every symbol has ≥ MIN_COMPARED dates
    compared and ≥ MIN_PASS_RATE of them within tolerance. Intraday files are checked through their daily aggregate."""
    ds = Path(ds)
    man = json.loads((ds / "manifest.json").read_text())
    res = {"reference": "Yahoo Finance daily (^NSEI, ^NSEBANK)", "tolerance": TOLERANCE, "min_pass_rate": MIN_PASS_RATE,
           "checked_at": pd.Timestamp.now(tz=IST).isoformat(), "series": {}}
    ok_all = True
    for part in sorted(man["partitions"]):
        tf, sym = part.split("/")[0], part.split("symbol=")[1].removesuffix(".parquet")
        if sym not in YAHOO:
            continue
        df = pd.read_parquet(ds / part)
        if tf == "1d":
            mine = df.set_index(df["ts"].dt.date)[["open", "high", "low", "close"]]
        else:
            g = df.groupby(df["ts"].dt.date)
            mine = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
        ref = reference(sym, min(mine.index), max(mine.index))
        both = mine.index.intersection(ref.index)
        only_mine = sorted(str(x) for x in mine.index.difference(ref.index))
        only_ref = sorted(str(x) for x in ref.index.difference(mine.index))
        rel = (mine.loc[both] / ref.loc[both] - 1).abs()
        within = pd.concat([rel[c] <= TOLERANCE[c] for c in TOLERANCE if c in rel], axis=1).all(axis=1)
        fails = rel[~within]
        rate = float(within.mean()) if len(within) else 0.0
        passed = len(both) >= MIN_COMPARED and rate >= MIN_PASS_RATE
        ok_all &= passed
        res["series"][part] = {"compared": int(len(both)), "pass_rate": rate, "passed": passed,
                               "median_abs_gap": {c: float(rel[c].median()) for c in rel},
                               "only_in_truedata": only_mine, "only_in_reference": only_ref,
                               "failures": {str(k): {c: round(float(v), 5) for c, v in r.items()} for k, r in fails.head(20).iterrows()}}
        say(f"  {part}: {len(both)} compared, {rate:.1%} within tolerance, only in TrueData {only_mine[:5]}, "
            f"only in Yahoo {only_ref[:5]} → {'pass' if passed else 'FAIL'}")
    res["passed"] = bool(ok_all and res["series"])
    (ds / "verification.json").write_text(json.dumps(res, indent=1, default=str))
    man["status"] = VERIFIED if res["passed"] else UNVERIFIED
    man["verification"] = {"passed": res["passed"], "checked_at": res["checked_at"], "reference": res["reference"],
                           "series": {k: {x: v[x] for x in ("compared", "pass_rate", "passed", "only_in_truedata", "only_in_reference")}
                                      for k, v in res["series"].items()}}
    (ds / "manifest.json").write_text(json.dumps(man, indent=1, default=str))
    (ds / "quality.md").write_text(render_quality(man))
    return res


# ---- use-restricted loading -------------------------------------------------------------------------------------------
def latest(out_root: Path) -> Path | None:
    d = Path(out_root) / "truedata"
    c = sorted((p for p in d.glob(f"{IMPORTER_VERSION}-*") if (p / "manifest.json").exists()),
               key=lambda p: json.loads((p / "manifest.json").read_text())["imported_at"]) if d.exists() else []
    return c[-1] if c else None


def load(ds: Path, timeframe: str, symbols, use: str, allow_unverified: bool = False) -> pd.DataFrame:
    if use not in ALLOWED_USES:
        raise ForbiddenUse(f"use {use!r} refused: {FORBIDDEN_NOTE}")
    ds = Path(ds)
    man = json.loads((ds / "manifest.json").read_text())
    if man.get("status") != VERIFIED and not allow_unverified:
        raise ForbiddenUse(f"{ds.name} is {man.get('status')}: run `data truedata-verify` first, or opt in and label the "
                           "results unverified")
    parts = [pd.read_parquet(ds / timeframe / f"symbol={s}.parquet") for s in symbols
             if (ds / timeframe / f"symbol={s}.parquet").exists()]
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    out.attrs.update({"provider": PROVIDER, "dataset": man["dataset"], "status": man.get("status"), "use": use,
                      "not_for": FORBIDDEN_NOTE})
    return out


class TrueDataProvider(DataProvider):
    """The desk's daily-bar provider interface over the latest verified TrueData batch (data/base.py). Index volume is
    not in the export: the `volume` column the interface requires is 0.0 and the frame's attrs say so."""
    name = "truedata"

    def __init__(self, out_root: Path, allow_unverified: bool = False):
        self.ds = latest(out_root)
        if self.ds is None:
            raise FileNotFoundError("no TrueData import: run `quantdesk data truedata-import --source <export dir>` first")
        self.allow_unverified = allow_unverified

    def history(self, symbol: str, start, end=None) -> pd.DataFrame:
        df = load(self.ds, "1d", [symbol], use="daily_backtest", allow_unverified=self.allow_unverified)
        if df.empty:
            raise KeyError(f"{symbol} is not in TrueData batch {self.ds.name}")
        out = pd.DataFrame({c: df[c].to_numpy(float) for c in ["open", "high", "low", "close"]},
                           index=pd.DatetimeIndex(df["ts"].dt.tz_localize(None).dt.normalize()))
        out["volume"] = 0.0
        out = out.loc[pd.Timestamp(start):]
        out = out.loc[: pd.Timestamp(end)] if end is not None else out
        out.attrs.update({"provider": PROVIDER, "dataset": self.ds.name, "volume": "not provided by the export"})
        return out
