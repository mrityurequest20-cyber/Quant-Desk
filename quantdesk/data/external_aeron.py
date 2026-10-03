"""External historical index minutes: github.com/aeron7/nifty-banknifty-intraday-data → validated, immutable Parquet.

What it is: one-minute NIFTY and BANKNIFTY *index* bars (no bid/ask, no options, no IV), 2007 → early 2023, in a
year / month / day text-file layout (`Symbol,YYYYMMDD,HH:MM,Open,High,Low,Close,Volume,OI`). Each bar is labelled
by its END minute: the session's regular bars run 09:16 … 15:30. A 09:08 pre-open print and 15:31+ post-close prints
surround them. The importer re-labels every bar by its START (09:15 … 15:29, the desk's convention). It detects the
labelling per file, so a start-labelled file is read correctly too.

What it may be used for (`ALLOWED_USES`): underlying-price features, direction research, regime research and
development-fold testing. It is NEVER:
- historical option-chain, bid/ask, IV or option-execution data;
- evidence to qualify an option strategy, a DTE change, paper-gate progress, a champion promotion or a profitability
  claim.
`load()` refuses any other declared use. The dataset's status is `external_unverified` until `verify()` passes:
randomly chosen sessions compared with an independent reference (Yahoo's daily index OHLC) against pre-declared
tolerances. Even `external_verified` data keeps the same use restrictions.

Layout (immutable: a partition is written once; a different source commit or importer version is a different dataset):

    <root>/aeron7/<importer version>-<source commit[:10]>/
        manifest.json         source URL and commit, importer version, every source file (path, sha256, symbol,
                              rows, sessions), every partition (sha256 of its content), validation per session
        1m/symbol=<S>/year=<Y>.parquet     accepted sessions, bar start in IST, OHLCV + OI + source_file
        5m/symbol=<S>/year=<Y>.parquet     resampled from the accepted minutes (n_1m = minutes in the bar)
        horizons/symbol=<S>.parquet        5-minute decision points: features + 30m / 60m / 120m / close labels
        quality.json, quality.md           coverage by year, missing-minute rates, duplicates, rejected files and sessions
        verification.json                  the independent check and the resulting status
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

SOURCE_URL = "https://github.com/aeron7/nifty-banknifty-intraday-data"
IMPORTER_VERSION = "aeron7-2"                                  # 2: reject 09:00-open (pre-Dec-2010) sessions
IST = "Asia/Kolkata"
FILES = {"NIFTY.txt": "NIFTY", "BANKNIFTY.txt": "BANKNIFTY"}          # index files only; *_F1/_F2 are futures
SYMBOL_ALIASES = {"NIFTY": "NIFTY", "NIFTY50": "NIFTY", "NIFTY 50": "NIFTY", "CNXNIFTY": "NIFTY",
                  "BANKNIFTY": "BANKNIFTY", "NIFTYBANK": "BANKNIFTY", "NIFTY BANK": "BANKNIFTY"}
COLUMNS = ["symbol", "date", "time", "open", "high", "low", "close", "volume", "oi"]
SESSION_START, SESSION_END = dt.time(9, 15), dt.time(15, 29)    # bar starts of the regular session (375 minutes)
SESSION_MINUTES = 375
MIN_MINUTES = 360                                                # a session needs 96% of its minutes to be accepted
JUMP = 0.05                                                      # a 5% move in one minute quarantines the session
UNVERIFIED, VERIFIED = "external_unverified", "external_verified"
ALLOWED_USES = frozenset({"underlying_features", "direction_research", "regime_research", "development_folds"})
FORBIDDEN_NOTE = ("external index minutes are not option-chain, bid/ask, IV or execution data, and never qualify an "
                  "option strategy, a DTE change, the paper gate, a promotion or a profitability claim")
YAHOO = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}
TOLERANCE = {"high": 0.002, "low": 0.002, "close": 0.003}       # relative; NSE's official close is computed, not a print
MIN_PASS_RATE, MIN_SAMPLED = 0.95, 50


class ImmutableViolation(RuntimeError):
    pass


class ForbiddenUse(ValueError):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def frame_hash(df: pd.DataFrame) -> str:
    """Content hash of a frame (index and values), stable across Parquet writers."""
    return _sha(pd.util.hash_pandas_object(df.reset_index(), index=False).to_numpy().tobytes()
                + ",".join(map(str, df.reset_index().columns)).encode())[:24]


def source_commit(root: Path) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def discover(root: Path) -> list[tuple[str, str]]:
    """(path relative to the source root, symbol) of every index file, in a stable order."""
    root = Path(root)
    out = []
    for p in sorted(root.rglob("*.txt")):
        if ".git" in p.parts:
            continue
        sym = FILES.get(p.name)
        if sym:
            out.append((p.relative_to(root).as_posix(), sym))
    return out


# ---- one file ---------------------------------------------------------------------------------------------------------
def read_file(path: Path, symbol: str) -> tuple[pd.DataFrame, dict]:
    """Raw rows → normalised minutes labelled by bar START (IST), and what was wrong with the file."""
    rep = {"rows_in": 0, "unparsed": 0, "wrong_symbol": 0, "bad_price": 0, "invalid_volume": 0, "volume_absent": 0,
           "zero_volume": 0, "out_of_order": 0, "label": None}
    raw = pd.read_csv(path, header=None, names=COLUMNS, dtype=str, skip_blank_lines=True, on_bad_lines="skip",
                      engine="python")
    rep["rows_in"] = int(len(raw))
    if raw.empty:
        return pd.DataFrame(), rep
    sym = raw["symbol"].astype(str).str.strip().str.upper().map(lambda s: SYMBOL_ALIASES.get(s, s))
    ts = pd.to_datetime(raw["date"].astype(str).str.strip() + " " + raw["time"].astype(str).str.strip(),
                        format="%Y%m%d %H:%M", errors="coerce")
    num = {c: pd.to_numeric(raw[c], errors="coerce") for c in ("open", "high", "low", "close", "volume", "oi")}
    df = pd.DataFrame({"ts": ts, "symbol": sym, **num})
    bad_parse = df["ts"].isna() | df[["open", "high", "low", "close"]].isna().any(axis=1)
    rep["unparsed"] = int(bad_parse.sum())
    wrong = ~bad_parse & (df["symbol"] != symbol)
    rep["wrong_symbol"] = int(wrong.sum())
    df = df[~bad_parse & ~wrong]
    t = df["ts"].to_numpy().astype("datetime64[ns]").astype("int64")
    rep["out_of_order"] = int((np.diff(t) < 0).sum()) if len(t) > 1 else 0
    o, h, l_, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    eps = 1e-9
    bad = ((np.minimum.reduce([o, h, l_, c]) <= 0) | (h + eps < l_) | (o > h + eps) | (o < l_ - eps) | (c > h + eps)
           | (c < l_ - eps))
    rep["bad_price"] = int(bad.sum())
    vol = df["volume"].to_numpy(float)
    vraw = raw.loc[df.index, "volume"]
    absent = vraw.isna() | (vraw.astype(str).str.strip() == "")
    rep["volume_absent"] = int(absent.sum())                      # older files have no volume / OI columns at all
    inv = (~absent.to_numpy() & ~np.isfinite(vol)) | (vol < 0)
    rep["invalid_volume"] = int(inv.sum())
    rep["zero_volume"] = int((vol == 0).sum())                    # normal for an index: counted, not rejected
    df = df[~bad & ~inv]
    # labelling: end-labelled files have regular bars 09:16 … 15:30; start-labelled 09:15 … 15:29
    tod = df["ts"].dt.time
    end_l = int((tod == dt.time(15, 30)).sum()) + int((tod == dt.time(9, 16)).sum())
    start_l = int((tod == dt.time(9, 15)).sum()) + int((tod == dt.time(15, 29)).sum())
    rep["label"] = "end" if end_l > start_l else "start"
    if rep["label"] == "end":
        df = df.assign(ts=df["ts"] - pd.Timedelta(minutes=1))
    df = df.assign(ts=df["ts"].dt.tz_localize(IST))
    return df.reset_index(drop=True), rep


def session_check(g: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One session's minutes from one file → (clean in-session minutes, validation)."""
    tod = g["ts"].dt.time
    inside = (tod >= SESSION_START) & (tod <= SESSION_END)
    v = {"rows": int(len(g)), "out_of_session": int((~inside).sum())}
    early = int(((tod >= dt.time(9, 0)) & (tod < SESSION_START)).sum())     # regular bars before 09:15: other session hours
    g = g[inside].sort_values("ts", kind="stable")
    dup = g.duplicated("ts", keep=False)
    same = g[dup].duplicated(["ts", "open", "high", "low", "close"], keep=False) if dup.any() else pd.Series(dtype=bool)
    v["duplicates"] = int(dup.sum() - g[dup]["ts"].nunique()) if dup.any() else 0
    conflicting = set(g[dup]["ts"][~same]) if dup.any() else set()
    v["conflicting_duplicates"] = int(len(conflicting))
    g = g[~g["ts"].isin(conflicting)].drop_duplicates("ts")       # a conflicting minute can't be trusted: dropped
    n = int(len(g))
    v["minutes"], v["missing_minutes"] = n, SESSION_MINUTES - n
    if n > 1:
        step = g["ts"].diff().dt.total_seconds().to_numpy()[1:] / 60
        v["longest_gap_min"] = float(step.max() - 1)
        r = np.abs(np.diff(np.log(g["close"].to_numpy(float))))
        v["max_1m_move"] = float(r.max())
    else:
        v["longest_gap_min"], v["max_1m_move"] = float(SESSION_MINUTES), 0.0
    day = g["ts"].iloc[0].date() if n else None
    why = []
    if day is not None and day.weekday() >= 5:
        why.append("weekend")
    if n < MIN_MINUTES:
        first = g["ts"].iloc[0].time() if n else None
        old_hours = first is not None and first >= dt.time(9, 50) and day is not None and day < dt.date(2011, 1, 1)
        why.append(f"short session ({n} of {SESSION_MINUTES} minutes)" + ("; NSE opened at 09:55 then" if old_hours else ""))
    if early >= 10:                                               # NSE opened at 09:00 until its Dec 2010 pre-open change
        why.append(f"09:00 session hours ({early} bars before 09:15): not comparable with today's 09:15 open")
    if v["max_1m_move"] > JUMP:
        why.append(f"{v['max_1m_move']:.1%} one-minute move")
    v["accepted"], v["reasons"] = not why, why
    return g, v


# ---- the import ---------------------------------------------------------------------------------------------------------
def dataset_dir(out_root: Path, commit: str | None) -> Path:
    return Path(out_root) / "aeron7" / f"{IMPORTER_VERSION}-{(commit or 'nocommit')[:10]}"


def _write_once(df: pd.DataFrame, path: Path) -> str:
    """Write a partition the first time; afterwards only confirm it is identical (immutable)."""
    h = frame_hash(df)
    if path.exists():
        old = frame_hash(pd.read_parquet(path))
        if old != h:
            raise ImmutableViolation(f"{path} exists with different content ({old} ≠ {h}): import into a new dataset version")
        return h
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd")
    tmp.replace(path)
    return h


def to_5m(m1: pd.DataFrame) -> pd.DataFrame:
    """5-minute bars from accepted minutes, labelled by bar start (the desk's to_5m convention), with the minute count."""
    out = []
    for _, g in m1.groupby(m1["ts"].dt.date):
        s = g.set_index("ts")
        b = s.resample("5min", label="left", closed="left", origin="start_day", offset="15min").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "oi": "last"})
        b["n_1m"] = s["close"].resample("5min", label="left", closed="left", origin="start_day", offset="15min").count()
        out.append(b.dropna(subset=["close"]))
    if not out:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "oi", "n_1m"])
    return pd.concat(out)


HORIZONS = {"30m": 6, "60m": 12, "120m": 24, "close": None}      # in 5-minute bars; close = the session's last bar


def horizon_dataset(b5: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Decision points (every completed 5-minute bar) with the desk's features and one label per horizon:
    fwd_ret_<h> (log return to the horizon's end, same session), y_<h> (up?), label_end_<h> (when it's known)."""
    from ..autolearn.features import build_samples
    b = b5[["open", "high", "low", "close", "volume"]]
    s = build_samples(b, symbol, 0).reset_index(drop=True)
    close = b["close"].copy()
    close.index = close.index + pd.Timedelta(minutes=5)            # by bar end
    out = {f"{k}_{h}": np.full(len(s), np.nan, dtype=object if k == "label_end" else float)
           for h in HORIZONS for k in ("fwd_ret", "y", "label_end")}
    by_day = {d: c for d, c in close.groupby(close.index.date)}
    for d, idx in s.groupby(pd.DatetimeIndex(s["ts"]).date).groups.items():
        c = by_day.get(d)
        if c is None:
            continue
        cv, ct = c.to_numpy(float), c.index
        t = pd.DatetimeIndex(s.loc[idx, "ts"])
        i = np.searchsorted(ct.as_unit("ns").asi8, t.as_unit("ns").asi8, side="right") - 1
        for h, k in HORIZONS.items():
            j = np.full(len(i), len(cv) - 1) if k is None else i + k
            ok = (i >= 0) & (j < len(cv)) & (j > i)
            jj, ii = np.where(ok, j, 0), np.where(ok, i, 0)
            r = np.where(ok, np.log(cv[jj] / cv[ii]), np.nan)
            out[f"fwd_ret_{h}"][np.asarray(idx)] = r
            out[f"y_{h}"][np.asarray(idx)] = np.where(ok, (r > 0).astype(float), np.nan)
            out[f"label_end_{h}"][np.asarray(idx)] = np.where(ok, ct[jj], pd.NaT)
    s = s.assign(**{k: v for k, v in out.items() if not k.startswith("label_end")})
    for h in HORIZONS:
        s[f"label_end_{h}"] = pd.to_datetime(pd.Series(out[f"label_end_{h}"]), utc=True).dt.tz_convert(IST)
    return s


def import_dataset(source_root: Path, out_root: Path, say=print, symbols=("NIFTY", "BANKNIFTY")) -> dict:
    """Read every index file, validate, pick one file per session, write the immutable partitions and the manifest."""
    say = say or (lambda *a: None)
    source_root = Path(source_root)
    commit = source_commit(source_root)
    ds = dataset_dir(out_root, commit)
    files = [(p, s) for p, s in discover(source_root) if s in symbols]
    say(f"  {len(files)} index files from {SOURCE_URL} @ {(commit or '?')[:10]}")
    man_files, rejected_files, cands = [], [], {}
    for fid, (rel, sym) in enumerate(files):
        path = source_root / rel
        b = path.read_bytes()
        entry = {"id": fid, "path": rel, "symbol": sym, "sha256": _sha(b), "bytes": len(b)}
        try:
            df, rep = read_file(path, sym)
        except Exception as exc:                                    # an unreadable file loses only itself
            entry.update({"status": "rejected", "reason": f"unreadable: {exc!s:.120}"})
            man_files.append(entry)
            rejected_files.append(entry)
            continue
        entry.update(rep)
        if df.empty:
            entry.update({"status": "rejected", "reason": "no parseable rows"})
            man_files.append(entry)
            rejected_files.append(entry)
            continue
        sess = []
        for day, g in df.groupby(df["ts"].dt.date):
            clean, v = session_check(g)
            v.update({"day": str(day), "file_id": fid})
            sess.append(v)
            cands.setdefault((sym, day), []).append((v, clean.assign(source_file=fid)))
        entry.update({"status": "read", "sessions": len(sess), "first_day": sess[0]["day"], "last_day": sess[-1]["day"]})
        man_files.append(entry)
    # one file per session: the accepted one with the most minutes; disagreements between files are counted
    sessions, keep = [], {s: [] for s in symbols}
    for (sym, day), opts in sorted(cands.items()):
        opts.sort(key=lambda x: (x[0]["accepted"], x[0]["minutes"]), reverse=True)
        v, g = opts[0]
        conflicts = 0
        for v2, g2 in opts[1:]:
            m = g.merge(g2, on="ts", suffixes=("", "_b"))
            conflicts += int((np.abs(m["close"] / m["close_b"] - 1) > 5e-4).sum())
        rec = {"symbol": sym, "day": str(day), **{k: v[k] for k in ("minutes", "missing_minutes", "duplicates",
               "conflicting_duplicates", "out_of_session", "longest_gap_min", "max_1m_move", "accepted", "reasons")},
               "file_id": v["file_id"], "files": len(opts), "cross_file_conflicts": conflicts}
        if conflicts > 5:                                            # two sources for one session that disagree
            rec["accepted"] = False
            rec["reasons"] = rec["reasons"] + [f"{conflicts} minutes differ between source files"]
        sessions.append(rec)
        if rec["accepted"]:
            keep[sym].append(g[["ts", "open", "high", "low", "close", "volume", "oi", "source_file"]])
    parts = {}
    for sym in symbols:
        if not keep[sym]:
            continue
        m1 = pd.concat(keep[sym]).sort_values("ts").reset_index(drop=True)
        m1["symbol"] = sym
        for y, g in m1.groupby(m1["ts"].dt.year):
            p = ds / "1m" / f"symbol={sym}" / f"year={y}.parquet"
            parts[str(p.relative_to(ds))] = _write_once(g.reset_index(drop=True), p)
        b5 = to_5m(m1)
        for y, g in b5.groupby(b5.index.year):
            p = ds / "5m" / f"symbol={sym}" / f"year={y}.parquet"
            parts[str(p.relative_to(ds))] = _write_once(g, p)
        hz = horizon_dataset(b5[b5["n_1m"] == 5], sym)
        p = ds / "horizons" / f"symbol={sym}.parquet"
        parts[str(p.relative_to(ds))] = _write_once(hz.reset_index(drop=True), p)
        say(f"  {sym}: {m1['ts'].dt.date.nunique()} accepted sessions, {len(m1):,} minutes, {len(b5):,} 5-minute bars, "
            f"{len(hz):,} decision points")
    man = {"source_url": SOURCE_URL, "source_commit": commit, "importer_version": IMPORTER_VERSION,
           "imported_at": str(pd.Timestamp.now(tz=IST)), "dataset": ds.name, "status": UNVERIFIED,
           "allowed_uses": sorted(ALLOWED_USES), "not_for": FORBIDDEN_NOTE,
           "conventions": {"timezone": IST, "timestamp": "bar start", "session": "09:15–15:29 bar starts (375 minutes)",
                           "source_labelling": "bar end, detected per file", "min_minutes": MIN_MINUTES, "jump": JUMP},
           "files": man_files, "partitions": parts, "sessions": sessions}
    prev = ds / "manifest.json"
    if prev.exists():                                               # immutable: same source, same partitions
        old = json.loads(prev.read_text())
        if old.get("partitions") != parts:
            raise ImmutableViolation(f"{prev}: the partitions differ from the recorded ones")
        man["status"] = old.get("status", UNVERIFIED)
        man["imported_at"] = old.get("imported_at")
    _write_json(prev, man)
    q = quality(man)
    _write_json(ds / "quality.json", q)
    (ds / "quality.md").write_text(render_quality(q, man))
    return man


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, default=str))
    tmp.replace(path)


# ---- the data-quality report ---------------------------------------------------------------------------------------------
def quality(man: dict) -> dict:
    s = pd.DataFrame(man["sessions"])
    f = pd.DataFrame(man["files"])
    out = {"dataset": man["dataset"], "status": man["status"], "files": int(len(f)),
           "rejected_files": [{k: r.get(k) for k in ("path", "reason")} for r in man["files"] if r.get("status") == "rejected"],
           "by_year": {}, "by_symbol": {}}
    if s.empty:
        return out
    s["year"] = s["day"].str[:4]
    for (sym, y), g in s.groupby(["symbol", "year"]):
        acc = g[g["accepted"]]
        out["by_year"].setdefault(sym, {})[y] = {
            "sessions": int(len(g)), "accepted": int(len(acc)), "rejected": int((~g["accepted"]).sum()),
            "missing_minute_rate": float(acc["missing_minutes"].sum() / max(len(acc) * SESSION_MINUTES, 1)),
            "duplicates": int(g["duplicates"].sum()), "conflicting_duplicates": int(g["conflicting_duplicates"].sum()),
            "cross_file_conflicts": int(g["cross_file_conflicts"].sum()), "out_of_session_rows": int(g["out_of_session"].sum())}
    for sym, g in s.groupby("symbol"):
        acc = g[g["accepted"]]
        out["by_symbol"][sym] = {"sessions": int(len(g)), "accepted": int(len(acc)),
                                 "first_day": g["day"].min(), "last_day": g["day"].max(),
                                 "missing_minute_rate": float(acc["missing_minutes"].sum() / max(len(acc) * SESSION_MINUTES, 1)),
                                 "rejected_sessions": g[~g["accepted"]][["day", "reasons"]].to_dict("records")}
    if len(f):
        out["file_totals"] = {k: int(f[k].fillna(0).sum()) for k in ("rows_in", "unparsed", "wrong_symbol", "bad_price",
                                                                    "invalid_volume", "volume_absent", "zero_volume",
                                                                    "out_of_order") if k in f}
        out["labelling"] = {str(k): int(v) for k, v in f["label"].value_counts().items()} if "label" in f else {}
    return out


def render_quality(q: dict, man: dict) -> str:
    L = [f"# External index minutes — data quality ({q['dataset']})", "",
         f"Source: {man['source_url']} @ {man['source_commit']}. Importer {man['importer_version']}. **Status: {q['status']}** "
         f"(uses: {', '.join(man['allowed_uses'])}; {man['not_for']}).", "",
         f"Files: {q['files']} ({len(q['rejected_files'])} rejected). Row-level totals: {q.get('file_totals')}. "
         f"Labelling detected: {q.get('labelling')}.", ""]
    for sym, b in q["by_symbol"].items():
        L += [f"## {sym}: {b['accepted']} of {b['sessions']} sessions accepted ({b['first_day']} → {b['last_day']}), "
              f"missing-minute rate {b['missing_minute_rate']:.3%}", "",
              "| year | sessions | accepted | rejected | missing-minute rate | duplicates | conflicting | cross-file conflicts |",
              "|---|---|---|---|---|---|---|---|"]
        for y, r in sorted(q["by_year"].get(sym, {}).items()):
            L.append(f"| {y} | {r['sessions']} | {r['accepted']} | {r['rejected']} | {r['missing_minute_rate']:.3%} | "
                     f"{r['duplicates']} | {r['conflicting_duplicates']} | {r['cross_file_conflicts']} |")
        rej = b["rejected_sessions"]
        if rej:
            L += ["", f"Rejected sessions ({len(rej)}): " + "; ".join(f"{x['day']} ({', '.join(x['reasons'])})" for x in rej[:40])
                  + (" …" if len(rej) > 40 else "")]
        L.append("")
    if q["rejected_files"]:
        L += ["## Rejected files", ""] + [f"- {r['path']}: {r['reason']}" for r in q["rejected_files"]]
    return "\n".join(L) + "\n"


# ---- the independent check -------------------------------------------------------------------------------------------------
def yahoo_daily(symbol: str, start, end, tries: int = 2) -> pd.DataFrame:
    import yfinance as yf
    last = None
    for _ in range(tries):
        d = yf.download(YAHOO[symbol], start=str(pd.Timestamp(start).date()),
                        end=str((pd.Timestamp(end) + pd.Timedelta(days=1)).date()), interval="1d", progress=False,
                        auto_adjust=False)
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)
        d = d.rename(columns=lambda c: str(c).lower())
        if len(d) and {"high", "low", "close"} <= set(d.columns):
            d.index = pd.to_datetime(d.index).date
            return d[["high", "low", "close"]]
        last = list(d.columns)[:6]
    raise RuntimeError(f"reference unavailable for {symbol} (columns {last})")


def daily_from_minutes(m1: pd.DataFrame) -> pd.DataFrame:
    g = m1.groupby(m1["ts"].dt.date)
    return pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})


def verify(ds: Path, reference=yahoo_daily, n: int = 80, seed: int = 20261003, say=print,
           min_sampled: int = MIN_SAMPLED) -> dict:
    """Randomly chosen accepted sessions (seeded, per symbol) against an independent daily reference. Pre-declared
    tolerances (TOLERANCE); the dataset passes when, for every symbol, at least MIN_SAMPLED sessions were compared and
    at least MIN_PASS_RATE of them are within tolerance on high, low and close. Only then is its status
    external_verified, and even then its uses stay restricted to ALLOWED_USES."""
    say = say or (lambda *a: None)
    ds = Path(ds)
    man = json.loads((ds / "manifest.json").read_text())
    rng = np.random.default_rng(seed)
    res = {"reference": "Yahoo Finance daily OHLC (^NSEI, ^NSEBANK)", "tolerance": TOLERANCE, "seed": seed,
           "min_pass_rate": MIN_PASS_RATE, "min_sampled": min_sampled, "symbols": {}}
    ok_all = True
    for sym in sorted({s["symbol"] for s in man["sessions"]}):
        days = sorted(s["day"] for s in man["sessions"] if s["symbol"] == sym and s["accepted"])
        pick = sorted(str(x) for x in rng.choice(days, size=min(n, len(days)), replace=False)) if days else []
        m1 = load(ds, "1m", [sym], use="development_folds", allow_unverified=True)
        mine = daily_from_minutes(m1)
        try:
            ref = reference(sym, pick[0], pick[-1]) if pick else pd.DataFrame()
        except Exception as exc:                                    # no reference: the symbol can't pass (fail closed)
            say(f"  {sym}: {exc!s:.160}")
            ref = pd.DataFrame(columns=["high", "low", "close"])
            res.setdefault("errors", []).append(f"{sym}: {exc!s:.160}")
        rows = []
        for d in pick:
            d0 = dt.date.fromisoformat(d)
            if d0 not in ref.index or d0 not in mine.index:
                rows.append({"day": d, "compared": False})
                continue
            r = {"day": d, "compared": True}
            for k in ("high", "low", "close"):
                a, b = float(mine.at[d0, k]), float(ref.at[d0, k])
                r[f"{k}_ours"], r[f"{k}_ref"], r[f"{k}_rel_diff"] = a, b, (a / b - 1) if b else np.nan
            r["pass"] = all(abs(r[f"{k}_rel_diff"]) <= TOLERANCE[k] for k in TOLERANCE)
            rows.append(r)
        t = pd.DataFrame(rows)
        comp = t[t["compared"].astype(bool)].copy() if len(t) else t
        if len(comp):
            comp["pass"] = comp["pass"].astype(bool)
        rate = float(comp["pass"].mean()) if len(comp) else 0.0
        passed = len(comp) >= min_sampled and rate >= MIN_PASS_RATE
        ok_all &= passed
        res["symbols"][sym] = {"sampled": len(pick), "compared": int(len(comp)), "pass_rate": rate, "passed": passed,
                               "median_abs_diff": {k: float(comp[f"{k}_rel_diff"].abs().median()) for k in TOLERANCE} if len(comp) else {},
                               "failures": comp[~comp["pass"]].to_dict("records")[:30] if len(comp) else [],
                               "failures_by_year": comp[~comp["pass"]]["day"].str[:4].value_counts().to_dict() if len(comp) else {}}
        say(f"  {sym}: {len(comp)} sessions compared, {rate:.1%} within tolerance → {'pass' if passed else 'FAIL'}")
    res["status"] = VERIFIED if ok_all else UNVERIFIED
    res["at"] = str(pd.Timestamp.now(tz=IST))
    _write_json(ds / "verification.json", res)
    man["status"] = res["status"]
    _write_json(ds / "manifest.json", man)
    q = quality(man)
    _write_json(ds / "quality.json", q)
    (ds / "quality.md").write_text(render_quality(q, man))
    return res


# ---- use-restricted loading ------------------------------------------------------------------------------------------------
def load(ds: Path, kind: str, symbols, use: str, allow_unverified: bool = False) -> pd.DataFrame:
    """The dataset's 1m / 5m bars or horizon samples, for a declared use. Refuses any use outside ALLOWED_USES (option
    chains, bid/ask, IV, execution, or qualifying anything), and unverified data unless the caller says it accepts
    that (the result's attrs say which)."""
    if use not in ALLOWED_USES:
        raise ForbiddenUse(f"use {use!r} refused: {FORBIDDEN_NOTE}")
    ds = Path(ds)
    man = json.loads((ds / "manifest.json").read_text())
    if man.get("status") != VERIFIED and not allow_unverified:
        raise ForbiddenUse(f"{ds.name} is {man.get('status')}: run the verification first, or pass allow_unverified=True "
                           "for development-fold work and label the results as unverified")
    parts = []
    for sym in symbols:
        if kind == "horizons":
            p = ds / "horizons" / f"symbol={sym}.parquet"
            if p.exists():
                parts.append(pd.read_parquet(p))
            continue
        for p in sorted((ds / kind / f"symbol={sym}").glob("year=*.parquet")):
            df = pd.read_parquet(p)
            parts.append(df.assign(symbol=sym) if "symbol" not in df else df)
    out = pd.concat(parts) if parts else pd.DataFrame()
    out.attrs.update({"source": SOURCE_URL, "dataset": man["dataset"], "status": man.get("status"),
                      "evidence": man.get("status"), "use": use, "not_for": FORBIDDEN_NOTE})
    return out


def latest(out_root: Path) -> Path | None:
    d = Path(out_root) / "aeron7"
    c = sorted(p for p in d.glob(f"{IMPORTER_VERSION}-*") if (p / "manifest.json").exists()) if d.exists() else []
    return c[-1] if c else None
