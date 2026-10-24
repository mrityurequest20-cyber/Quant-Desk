"""P0.2 (docs/ML_PHASE0.md): external 1-minute index bars → a validated, immutable, content-addressed dataset.

The first source is the owner's Kaggle set `debashis74017/nifty-50-minute-data` (NIFTY 50, NIFTY BANK, INDIA VIX; one CSV
per symbol, `date,open,high,low,close,volume`, bar START labels, 2015-01-09 to 2026-05-15). It is tier T1b of the data
tiers, `external_unverified` until the independent check of P0.6 passes, and it is underlying-price data only: never
option, bid/ask, IV or execution data, and never evidence for a gate or a promotion (the same `ALLOWED_USES` and
`FORBIDDEN_NOTE` as the aeron7 importer, which this module reuses rather than restates).

What the importer does that the rules in ML_PHASE0.md ask for:
- **Quarantine, don't repair.** A row that fails validity is dropped and counted; a session that fails is kept out and
  says why. Nothing is filled, smoothed or re-labelled except a timestamp stamped a few seconds past the minute (in this
  source, 2015 only), which is floored to its minute under a declared bound (`MAX_JITTER_S`) and counted.
- **Review, not a blanket drop, for real events.** A one-minute move above 5% or a run of 10+ stale bars is either a
  market event (13 Mar 2020: a circuit-breaker halt and a 6% rebound on resumption, in both indices in the same minute)
  or a data fault (10 Jul 2017: a 60 to 110 minute freeze). Only a person can tell, so those sessions are excluded by
  default and listed with evidence; `reviewed_sessions.json` admits one, and its hash is part of the dataset identity.
- **Provenance everywhere.** Every row carries its tier; every source file is recorded with its sha256; every partition
  with a canonical content hash; the dataset has one digest over all of it. A dataset without a manifest is refused by
  `load`, and so is one whose partitions no longer hash to the manifest.
- **Immutable and deterministic.** A partition is written once. Importing the same files with the same rules gives the
  same digest, and a different file, rule or reviewed list is a different dataset folder.

Layout:

    <root>/<source name>/<importer version>-<identity[:12]>/
        manifest.json     source files (sha256, row counts, drops), rules, every partition's hash, every session's
                          validation, the review queue, the dataset digest, the status
        1m/symbol=<S>/year=<Y>.parquet     accepted sessions: ts (IST, bar start), OHLC, volume, symbol, tier, source_file
        quality.json, quality.md           coverage by year, drops by reason, the review queue with its evidence
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.external_aeron import ALLOWED_USES, FORBIDDEN_NOTE, ForbiddenUse, ImmutableViolation

IMPORTER_VERSION = "ml-intake-1"
SCHEMA = 1
IST = "Asia/Kolkata"
TIER = "T1b"
UNVERIFIED, VERIFIED = "external_unverified", "external_verified"
REVIEWED_PATH = Path(__file__).with_name("reviewed_sessions.json")

HEADER = ["date", "open", "high", "low", "close", "volume"]
FIRST_MOD, LAST_MOD = 9 * 60 + 15, 15 * 60 + 29        # minute-of-day of the first and last regular bar starts
SESSION_MINUTES = 375
MIN_MINUTES = 360                                       # a session needs 96% of its minutes
MAX_JITTER_S = 15                                       # a stamp up to 15 s past the minute is floored; beyond it the row is dropped
JUMP = 0.05                                             # index: a one-minute move above 5% goes to review
CORROBORATE = 0.03                                      # the other index moved this much, the same way, within a minute: evidence
STALE_RUN = 10                                          # consecutive flat bars repeating the previous close: halt or frozen feed
REVIEW_CODES = ("jump", "stale_run")
HARD_CODES = ("weekend", "short_session")


class SourceFormatError(ValueError):
    """The source is not what the importer was written for (missing file, different header): nothing is guessed."""


class ReviewedListError(ValueError):
    pass


@dataclass(frozen=True)
class SourceFile:
    path: str                     # relative to the source root
    symbol: str
    kind: str = "index"           # "index": the jump rule applies; "vol_index": it does not (a volatility index is noisy by nature)


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    files: tuple[SourceFile, ...]
    licence: str = "unknown"
    redistributable: bool = False


KAGGLE_INDEX_MINUTES = Source(
    name="kaggle-debashis74017-index-minutes",
    url="https://www.kaggle.com/datasets/debashis74017/nifty-50-minute-data",
    files=(SourceFile("NIFTY 50_minute.csv", "NIFTY"), SourceFile("NIFTY BANK_minute.csv", "BANKNIFTY"),
           SourceFile("INDIA VIX_minute.csv", "INDIAVIX", kind="vol_index")))


# ---- hashing --------------------------------------------------------------------------------------------------------
def sha256_file(path: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def canonical_hash(df: pd.DataFrame) -> str:
    """Content hash of a frame that does not depend on the pandas version, the datetime unit (us or ns), the string
    dtype or how Parquet stored it: each column is reduced to a fixed little-endian form first. -0.0 is 0.0 and every
    NaN is one NaN. Column names, their order and the row count are part of the hash."""
    h = hashlib.sha256()
    h.update(f"{len(df)}|".encode())
    for c in df.columns:
        s = df[c]
        if isinstance(s.dtype, pd.DatetimeTZDtype):
            kind, b = "ts", pd.DatetimeIndex(s).tz_convert("UTC").as_unit("ns").asi8.astype("<i8").tobytes()
        elif pd.api.types.is_float_dtype(s):
            a = s.to_numpy("float64") + 0.0
            kind, b = "f8", np.where(np.isnan(a), np.nan, a).astype("<f8").tobytes()
        elif pd.api.types.is_integer_dtype(s):
            kind, b = "i8", s.to_numpy("int64").astype("<i8").tobytes()
        else:
            kind, b = "str", "\x00".join(map(str, s.tolist())).encode()
        h.update(f"{c}:{kind}:{len(b)}|".encode())
        h.update(b)
    return h.hexdigest()


# ---- reading one file -----------------------------------------------------------------------------------------------
def read_minutes(path: Path, symbol: str) -> tuple[pd.DataFrame, dict, dict]:
    """Raw rows → minutes labelled by bar start (tz-aware IST), what was dropped, and the drops per day.

    Dropped and counted: unparsable or non-finite rows, stamps more than MAX_JITTER_S past the minute, non-positive or
    inconsistent prices (open/close outside the high-low range, high < low), negative or fractional volume. Floored and
    counted: stamps 1 to MAX_JITTER_S seconds past the minute."""
    rep = {"rows_in": 0, "unparsed": 0, "ambiguous_timestamp": 0, "floored_seconds": 0, "bad_price": 0,
           "invalid_volume": 0, "out_of_order": 0, "zero_volume": 0}
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(raw.columns) != HEADER:
        raise SourceFormatError(f"{path.name}: header {list(raw.columns)} is not {HEADER}")
    rep["rows_in"] = int(len(raw))
    ts = pd.to_datetime(raw["date"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    num = {c: pd.to_numeric(raw[c], errors="coerce").to_numpy(float) for c in HEADER[1:]}
    ok_num = np.isfinite(np.column_stack(list(num.values()))).all(axis=1)
    parsed = ts.notna().to_numpy() & ok_num
    rep["unparsed"] = int((~parsed).sum())
    sec = ts.dt.second.fillna(0).to_numpy(int)
    ambiguous = parsed & (sec > MAX_JITTER_S)
    rep["ambiguous_timestamp"] = int(ambiguous.sum())
    rep["floored_seconds"] = int((parsed & ~ambiguous & (sec > 0)).sum())
    keep = parsed & ~ambiguous
    dropped_days: dict[str, int] = {}

    def drop(mask: np.ndarray, key: str) -> None:
        rep[key] = int(mask.sum())
        for d, k in ts[mask].dt.date.value_counts().items():
            dropped_days[str(d)] = dropped_days.get(str(d), 0) + int(k)

    drop(ambiguous, "ambiguous_timestamp")
    t = ts.dt.floor("min")
    o, h, l_, c, v = (num[k] for k in ("open", "high", "low", "close", "volume"))
    with np.errstate(invalid="ignore"):
        bad_price = keep & ((np.minimum.reduce([o, h, l_, c]) <= 0) | (h < l_) | (o > h) | (o < l_) | (c > h) | (c < l_))
        bad_vol = keep & ((v < 0) | (v != np.floor(v)))
    drop(bad_price, "bad_price")
    drop(bad_vol & ~bad_price, "invalid_volume")
    keep = keep & ~bad_price & ~bad_vol
    rep["zero_volume"] = int((keep & (v == 0)).sum())
    df = pd.DataFrame({"ts": t[keep].dt.tz_localize(IST), "open": o[keep], "high": h[keep], "low": l_[keep],
                       "close": c[keep], "volume": v[keep].astype("int64")}).reset_index(drop=True)
    a = pd.DatetimeIndex(df["ts"]).asi8
    rep["out_of_order"] = int((np.diff(a) < 0).sum()) if len(a) > 1 else 0
    return df, rep, dropped_days


# ---- one session ----------------------------------------------------------------------------------------------------
def longest_run(mask: np.ndarray) -> int:
    if not len(mask) or not mask.any():
        return 0
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())


def check_session(g: pd.DataFrame, day: dt.date, jump_rule: bool = True) -> tuple[pd.DataFrame, dict]:
    """One day's minutes from one file → (clean in-session minutes, the validation record).

    Hard rejections (the session is out): a weekend date; fewer than MIN_MINUTES of the 375 regular minutes.
    Review (out unless a reviewer admits it): a one-minute move above JUMP (index kinds only); STALE_RUN or more
    consecutive flat bars repeating the previous close. Minutes outside 09:15-15:29 are dropped and counted; a minute
    with two identical bars keeps one, with two different bars is dropped whole."""
    mod = (g["ts"].dt.hour * 60 + g["ts"].dt.minute).to_numpy()
    inside = (mod >= FIRST_MOD) & (mod <= LAST_MOD)
    v = {"day": str(day), "rows": int(len(g)), "out_of_session": int((~inside).sum())}
    g = g[inside].sort_values("ts", kind="stable")
    distinct = g.drop_duplicates(["ts", "open", "high", "low", "close"])
    v["duplicates"] = int(len(g) - len(distinct))
    clash = distinct["ts"].duplicated(keep=False)
    v["conflicting_duplicates"] = int(distinct.loc[clash, "ts"].nunique())
    g = distinct[~clash].reset_index(drop=True)
    n = int(len(g))
    v["minutes"], v["missing_minutes"] = n, SESSION_MINUTES - n
    m = (g["ts"].dt.hour * 60 + g["ts"].dt.minute).to_numpy() - FIRST_MOD
    c = g["close"].to_numpy(float)
    gaps = np.diff(m)
    v["longest_gap_min"] = int(gaps.max() - 1) if n > 1 else SESSION_MINUTES
    if n > 1:
        r = np.diff(np.log(c))
        i = int(np.argmax(np.abs(r)))
        v["max_1m_move"], v["max_1m_move_signed"] = float(abs(r[i])), float(r[i])
        v["max_1m_move_at"] = str(g["ts"].iloc[i + 1])
        flat = ((g["open"] == g["high"]) & (g["high"] == g["low"]) & (g["low"] == g["close"])).to_numpy()
        stale = flat[1:] & (c[1:] == c[:-1]) & (gaps == 1)
        v["longest_stale_run"], v["stale_bars"] = longest_run(stale), int(stale.sum())
    else:
        v["max_1m_move"], v["max_1m_move_signed"], v["max_1m_move_at"] = 0.0, 0.0, None
        v["longest_stale_run"], v["stale_bars"] = 0, 0
    hard, review = [], []
    if day.weekday() >= 5:
        hard.append("weekend")
    if n < MIN_MINUTES:
        hard.append("short_session")
    if jump_rule and v["max_1m_move"] > JUMP:
        review.append("jump")
    if v["longest_stale_run"] >= STALE_RUN:
        review.append("stale_run")
    v["hard_codes"], v["review_codes"] = hard, review
    v["status"] = "rejected" if hard else ("review" if review else "accepted")
    v["reasons"] = ([f"{n} of {SESSION_MINUTES} minutes" if c_ == "short_session" else c_ for c_ in hard]
                    + ([f"{v['max_1m_move']:.1%} one-minute move at {v['max_1m_move_at']}"] if "jump" in review else [])
                    + ([f"{v['longest_stale_run']} consecutive stale bars"] if "stale_run" in review else []))
    return g, v


# ---- the reviewed list ----------------------------------------------------------------------------------------------
def load_reviewed(path: Path | None = None) -> tuple[dict, str]:
    """{(symbol, day): entry} and the file's sha256. A malformed entry is an error, never skipped."""
    p = Path(path or REVIEWED_PATH)
    raw = p.read_bytes()
    doc = json.loads(raw)
    if doc.get("schema") != 1 or not isinstance(doc.get("sessions"), list):
        raise ReviewedListError(f"{p.name}: expected schema 1 and a list of sessions")
    out = {}
    for e in doc["sessions"]:
        need = {"symbol", "day", "codes", "decision", "evidence"}
        if not need <= set(e):
            raise ReviewedListError(f"{p.name}: entry {e!r} lacks {sorted(need - set(e))}")
        if e["decision"] != "admit" or not e["codes"] or not set(e["codes"]) <= set(REVIEW_CODES):
            raise ReviewedListError(f"{p.name}: {e['symbol']} {e['day']}: decision must be 'admit' with codes from {REVIEW_CODES}")
        if len(str(e["evidence"]).strip()) < 40:
            raise ReviewedListError(f"{p.name}: {e['symbol']} {e['day']}: the evidence is too thin to admit a session")
        dt.date.fromisoformat(e["day"])
        if (e["symbol"], e["day"]) in out:
            raise ReviewedListError(f"{p.name}: {e['symbol']} {e['day']} is listed twice")
        out[(e["symbol"], e["day"])] = e
    return out, hashlib.sha256(raw).hexdigest()


def corroborate(rec: dict, others: dict) -> list[str]:
    """Index symbols whose own bars moved the same way, by at least CORROBORATE, within a minute of this session's biggest
    move. Evidence for a reviewer that a move is the market's and not one series' fault; not proof (same provider)."""
    if "jump" not in rec["review_codes"] or not rec.get("max_1m_move_at"):
        return []
    t0, sign = pd.Timestamp(rec["max_1m_move_at"]), np.sign(rec["max_1m_move_signed"])
    out = []
    for sym, g in others.items():
        lr = np.log(g.set_index("ts")["close"]).diff().loc[t0 - pd.Timedelta(minutes=1): t0 + pd.Timedelta(minutes=1)]
        if ((np.sign(lr) == sign) & (lr.abs() >= CORROBORATE)).any():
            out.append(sym)
    return sorted(out)


# ---- the import -----------------------------------------------------------------------------------------------------
def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")
    tmp.replace(path)


def _write_once(df: pd.DataFrame, path: Path) -> str:
    h = canonical_hash(df)
    if path.exists():
        old = canonical_hash(pd.read_parquet(path))
        if old != h:
            raise ImmutableViolation(f"{path} exists with different content ({old[:12]} ≠ {h[:12]}): import into a new dataset")
        return h
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, compression="zstd", index=False)
    tmp.replace(path)
    return h


def rules() -> dict:
    return {"importer_version": IMPORTER_VERSION, "schema": SCHEMA, "timezone": IST, "timestamp": "bar start",
            "session": "09:15-15:29 bar starts (375 minutes)", "min_minutes": MIN_MINUTES, "max_jitter_s": MAX_JITTER_S,
            "jump": JUMP, "corroborate": CORROBORATE, "stale_run": STALE_RUN, "review_codes": list(REVIEW_CODES),
            "hard_codes": list(HARD_CODES), "header": HEADER}


def dataset_digest(man: dict) -> str:
    """One digest over everything that makes the data what it is. The import time, the status (which P0.6 changes when
    the independent check passes) and the source's version label (documentation: the file hashes are the identity) are
    not part of it."""
    core = {k: man[k] for k in ("schema", "importer_version", "rules", "reviewed_sha256", "partitions", "sessions")}
    core["source"] = {k: v for k, v in man["source"].items() if k != "version"}
    return hashlib.sha256(canonical_json(core)).hexdigest()


def dataset_dir(out_root: Path, src: Source, files: list[dict], reviewed_sha: str) -> Path:
    ident = hashlib.sha256(canonical_json({"files": sorted((f["path"], f["sha256"]) for f in files),
                                           "rules": rules(), "reviewed": reviewed_sha})).hexdigest()[:12]
    return Path(out_root) / src.name / f"{IMPORTER_VERSION}-{ident}"


def import_source(source_root: Path, out_root: Path, src: Source = KAGGLE_INDEX_MINUTES, version: str = "",
                  reviewed_path: Path | None = None, say=print) -> dict:
    """Read every file of `src`, validate, and write the immutable dataset and its manifest. Returns the manifest."""
    say = say or (lambda *a: None)
    source_root = Path(source_root)
    reviewed, reviewed_sha = load_reviewed(reviewed_path)
    files, frames, sessions, clean = [], {}, [], {}
    for fid, sf in enumerate(src.files):
        path = source_root / sf.path
        if not path.is_file():
            raise SourceFormatError(f"{sf.path} is missing from {source_root}")
        sha, size = sha256_file(path)
        df, rep, dropped = read_minutes(path, sf.symbol)
        entry = {"id": fid, "path": sf.path, "symbol": sf.symbol, "kind": sf.kind, "sha256": sha, "bytes": size, **rep}
        files.append(entry)
        n_days = 0
        for day, g in df.groupby(df["ts"].dt.date):
            g2, v = check_session(g, day, jump_rule=sf.kind == "index")
            v.update({"symbol": sf.symbol, "file_id": fid, "rows_dropped": dropped.get(str(day), 0)})
            sessions.append(v)
            clean[(sf.symbol, str(day))] = g2.assign(source_file=fid)
            n_days += 1
        entry["sessions"] = n_days
        say(f"  {sf.symbol}: {rep['rows_in']:,} rows, {n_days} days (dropped: "
            f"{rep['unparsed']} unparsed, {rep['bad_price']} bad price, {rep['ambiguous_timestamp']} ambiguous stamp; "
            f"floored {rep['floored_seconds']})")
    idx_syms = {f.symbol for f in src.files if f.kind == "index"}
    applied, seen = [], set()
    for v in sorted(sessions, key=lambda r: (r["symbol"], r["day"])):
        v["corroborated_by"] = corroborate(v, {s: clean[(s, v["day"])] for s in idx_syms - {v["symbol"]} if (s, v["day"]) in clean})
        e = reviewed.get((v["symbol"], v["day"]))
        v["reviewed"] = None
        if e is not None:
            seen.add((v["symbol"], v["day"]))
            if v["status"] == "review" and set(v["review_codes"]) <= set(e["codes"]):
                v["status"], v["reviewed"] = "accepted_reviewed", e["evidence"]
                applied.append(f"{v['symbol']} {v['day']}")
    sessions.sort(key=lambda r: (r["symbol"], r["day"]))
    ds = dataset_dir(out_root, src, files, reviewed_sha)
    parts = {}
    for sf in src.files:
        keep = [clean[(sf.symbol, v["day"])] for v in sessions
                if v["symbol"] == sf.symbol and v["status"] in ("accepted", "accepted_reviewed")]
        if not keep:
            continue
        m1 = pd.concat(keep).sort_values("ts", kind="stable").reset_index(drop=True)
        m1 = m1.assign(symbol=sf.symbol, tier=TIER)[["ts", "open", "high", "low", "close", "volume", "symbol", "tier", "source_file"]]
        for y, g in m1.groupby(m1["ts"].dt.year):
            g = g.reset_index(drop=True)
            p = ds / "1m" / f"symbol={sf.symbol}" / f"year={y}.parquet"
            parts[p.relative_to(ds).as_posix()] = {"sha256": _write_once(g, p), "rows": int(len(g))}
        say(f"  {sf.symbol}: {sum(1 for v in sessions if v['symbol'] == sf.symbol and v['status'].startswith('accepted'))} "
            f"sessions kept, {len(m1):,} minutes")
    man = {"schema": SCHEMA, "importer_version": IMPORTER_VERSION, "dataset": ds.name, "tier": TIER, "status": UNVERIFIED,
           "source": {"name": src.name, "url": src.url, "version": version, "licence": src.licence,
                      "redistributable": src.redistributable, "files": files},
           "allowed_uses": sorted(ALLOWED_USES), "not_for": FORBIDDEN_NOTE, "rules": rules(),
           "reviewed_sha256": reviewed_sha, "reviewed_applied": applied,
           "reviewed_unused": sorted(f"{s} {d}" for s, d in reviewed.keys() - seen),
           "partitions": parts, "sessions": sessions, "imported_at": str(pd.Timestamp.now(tz=IST))}
    man["digest"] = dataset_digest(man)
    prev = ds / "manifest.json"
    if prev.exists():
        old = json.loads(prev.read_text())
        if old.get("digest") != man["digest"]:
            raise ImmutableViolation(f"{prev}: the same dataset folder, a different digest ({old.get('digest', '?')[:12]} ≠ {man['digest'][:12]})")
        man["status"], man["imported_at"] = old.get("status", UNVERIFIED), old.get("imported_at", man["imported_at"])
    _write_json(prev, man)
    q = quality(man)
    _write_json(ds / "quality.json", q)
    (ds / "quality.md").write_text(render_quality(q, man))
    return man


# ---- the quality report ---------------------------------------------------------------------------------------------
def quality(man: dict) -> dict:
    s = pd.DataFrame(man["sessions"])
    out = {"dataset": man["dataset"], "digest": man["digest"], "status": man["status"], "by_symbol": {}, "review_queue": [],
           "files": [{k: f[k] for k in ("path", "symbol", "rows_in", "unparsed", "ambiguous_timestamp", "floored_seconds",
                                        "bad_price", "invalid_volume", "out_of_order", "zero_volume", "sessions")}
                     for f in man["source"]["files"]]}
    if s.empty:
        return out
    s["year"] = s["day"].str[:4]
    for sym, g in s.groupby("symbol"):
        kept = g[g["status"].isin(["accepted", "accepted_reviewed"])]
        rej = g[g["status"] == "rejected"]
        codes: dict[str, int] = {}
        for cs in rej["hard_codes"]:
            for c in cs:
                codes[c] = codes.get(c, 0) + 1
        out["by_symbol"][sym] = {
            "sessions": int(len(g)), "accepted": int(len(kept)), "review": int((g["status"] == "review").sum()),
            "rejected": int(len(rej)), "rejected_by_code": codes, "first_day": g["day"].min(), "last_day": g["day"].max(),
            "missing_minute_rate": float(kept["missing_minutes"].sum() / max(len(kept) * SESSION_MINUTES, 1)),
            "by_year": {y: {"sessions": int(len(gy)), "accepted": int(gy["status"].isin(["accepted", "accepted_reviewed"]).sum())}
                        for y, gy in g.groupby("year")}}
    for r in s[s["status"] == "review"].to_dict("records"):
        out["review_queue"].append({k: r[k] for k in ("symbol", "day", "review_codes", "reasons", "corroborated_by",
                                                       "longest_stale_run", "max_1m_move", "max_1m_move_at")})
    # the indices trade the same days: where they disagree about a day (present in one and not the other, or accepted in
    # one and not the other) one of the two series has a fault, which is evidence for a reviewer
    idx = sorted({f["symbol"] for f in man["source"]["files"] if f["kind"] == "index"})
    if len(idx) > 1:
        piv = s[s["symbol"].isin(idx)].pivot(index="day", columns="symbol", values="status").reindex(columns=idx).fillna("absent")
        diff = piv[piv.nunique(axis=1) > 1]
        out["index_disagreements"] = {"count": int(len(diff)),
                                      "first": [{"day": d, **r} for d, r in diff.head(50).to_dict("index").items()]}
    return out


def render_quality(q: dict, man: dict) -> str:
    L = [f"# Index minutes — data quality ({q['dataset']})", "",
         f"Source: {man['source']['name']} ({man['source']['url']}), version {man['source']['version'] or '?'}; licence "
         f"{man['source']['licence']}; redistributable: {man['source']['redistributable']}. Importer {man['importer_version']}. "
         f"**Status: {q['status']}** (uses: {', '.join(man['allowed_uses'])}; {man['not_for']}). Digest `{q['digest'][:16]}`.", ""]
    for sym, b in q["by_symbol"].items():
        L += [f"## {sym}: {b['accepted']} of {b['sessions']} sessions kept ({b['first_day']} → {b['last_day']}), {b['review']} in review, "
              f"{b['rejected']} rejected {b['rejected_by_code']}; missing-minute rate {b['missing_minute_rate']:.3%}", ""]
    if q["review_queue"]:
        L += ["## Review queue (excluded until a reviewer admits them in reviewed_sessions.json, with evidence)", "",
              "| symbol | day | why | corroborated by |", "|---|---|---|---|"]
        for r in q["review_queue"]:
            L.append(f"| {r['symbol']} | {r['day']} | {'; '.join(r['reasons'])} | {', '.join(r['corroborated_by']) or '-'} |")
        L.append("")
    dis = q.get("index_disagreements")
    if dis and dis["count"]:
        L += [f"## Days the indices disagree about ({dis['count']}; first {len(dis['first'])} shown)", ""]
        L += [f"- {r['day']}: " + ", ".join(f"{k} {v}" for k, v in r.items() if k != "day") for r in dis["first"][:25]] + [""]
    L += ["## Files", "", "| file | rows | unparsed | ambiguous stamp | floored | bad price | invalid volume | out of order |",
          "|---|---|---|---|---|---|---|---|"]
    for f in q["files"]:
        L.append(f"| {f['path']} | {f['rows_in']:,} | {f['unparsed']} | {f['ambiguous_timestamp']} | {f['floored_seconds']} | "
                 f"{f['bad_price']} | {f['invalid_volume']} | {f['out_of_order']} |")
    return "\n".join(L) + "\n"


# ---- use-restricted, integrity-checked loading ----------------------------------------------------------------------
def load(ds: Path, symbols, use: str, allow_unverified: bool = False) -> pd.DataFrame:
    """The dataset's 1-minute bars for a declared use. Refused: any use outside ALLOWED_USES; a folder without a
    manifest; unverified data unless the caller says it accepts that; a partition missing, extra, or no longer
    hashing to the manifest. The result's attrs carry the dataset, digest, status and the restriction."""
    if use not in ALLOWED_USES:
        raise ForbiddenUse(f"use {use!r} refused: {FORBIDDEN_NOTE}")
    ds = Path(ds)
    mp = ds / "manifest.json"
    if not mp.is_file():
        raise ForbiddenUse(f"{ds}: no manifest, so no provenance: refused")
    man = json.loads(mp.read_text())
    if man.get("status") != VERIFIED and not allow_unverified:
        raise ForbiddenUse(f"{ds.name} is {man.get('status')}: run the verification first, or pass allow_unverified=True "
                           "and label the results as unverified")
    on_disk = {p.relative_to(ds).as_posix() for p in (ds / "1m").rglob("*.parquet")}
    if on_disk != set(man["partitions"]):
        raise ImmutableViolation(f"{ds.name}: partitions on disk differ from the manifest "
                                 f"(extra {sorted(on_disk - set(man['partitions']))[:3]}, missing {sorted(set(man['partitions']) - on_disk)[:3]})")
    parts = []
    for sym in symbols:
        for rel in sorted(p for p in man["partitions"] if f"/symbol={sym}/" in f"/{p}"):
            df = pd.read_parquet(ds / rel)
            if canonical_hash(df) != man["partitions"][rel]["sha256"]:
                raise ImmutableViolation(f"{rel} no longer hashes to the manifest: the dataset was altered")
            parts.append(df)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    out.attrs.update({"source": man["source"]["url"], "dataset": man["dataset"], "digest": man["digest"],
                      "status": man["status"], "tier": man["tier"], "use": use, "not_for": FORBIDDEN_NOTE})
    return out


def latest(out_root: Path, src: Source = KAGGLE_INDEX_MINUTES) -> Path | None:
    d = Path(out_root) / src.name
    c = sorted(p for p in d.glob(f"{IMPORTER_VERSION}-*") if (p / "manifest.json").exists()) if d.exists() else []
    return c[-1] if c else None
