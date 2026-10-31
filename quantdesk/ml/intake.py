"""P0.2 (docs/ML_PHASE0.md): external 1-minute index bars → a validated, immutable, content-addressed dataset.

The first source is the owner's Kaggle set `debashis74017/nifty-50-minute-data` (NIFTY 50, NIFTY BANK, INDIA VIX; one CSV
per symbol, `date,open,high,low,close,volume`, bar START labels, 2015-01-09 to 2026-05-15; volume is 0 in every row). It is
`external_unverified` until the independent check of P0.6 passes, and it is underlying-price data only: never option,
bid/ask, IV or execution data, and never evidence for a gate or a promotion (the same `ALLOWED_USES` and `FORBIDDEN_NOTE` as
the aeron7 importer, which this module reuses rather than restates).

What the importer does that the rules in ML_PHASE0.md ask for:
- **Quarantine, don't repair.** A row that fails validity is dropped and counted; a session that fails is kept out and says
  why. Nothing is filled, smoothed or re-labelled except a timestamp stamped a few seconds past the minute (in this source,
  2015 only), which is floored to its minute under a declared bound (`MAX_JITTER_S`) and counted.
- **Review, not a blanket drop, for real events.** A one-minute move above 5% (log return), a frozen feed (a run of 10+ stale
  bars, or 3% of the session stale), or a full-length weekend session (a Budget Saturday) is either a market event or a data
  fault. Only a person can tell, so those sessions are excluded by default and listed with their evidence and their rank by
  realised variance; `reviewed_sessions.json` admits one, bound to the source file and the facts that were reviewed, and its
  hash is part of the dataset identity.
- **Provenance everywhere.** Every row carries its tier; every source file is recorded with its sha256; every partition with a
  canonical content hash; the dataset has one digest over all of it, and `load()` recomputes it. A dataset without a manifest
  is refused, and so is one whose manifest or partitions no longer match their hashes.
- **Immutable and deterministic.** A partition is written once. Importing the same files with the same rules gives the same
  digest, and a different file, rule or reviewed list is a different dataset folder.

What the digest is and is not: it detects an accidental or careless change (a hand-edited partition, a hand-edited manifest, a
different source file). It cannot stop someone who rewrites a partition, its hash in the manifest and the manifest's digest
together (the folder name does not cover the partitions); for that, a spec records the digest it was run on and passes it to
`load(expected_digest=...)`, and the P0.6 record should carry a hash of the check's output.

Layout:

    <root>/<source name>/<importer version>-<identity[:12]>/
        manifest.json     source files (sha256, row counts, drops), rules, every partition's hash, every session's
                          validation, the reviewed list applied, the dataset digest, the code commit, the status
        1m/symbol=<S>/year=<Y>.parquet     accepted sessions: ts (IST, bar start), OHLC, volume, symbol, tier, source_file
        quality.json, quality.md           coverage by year, drops by reason, the review queue with its evidence
        verification.json                  written by P0.6 when the independent check passes; names the digest it checked
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.external_aeron import ALLOWED_USES, FORBIDDEN_NOTE, ForbiddenUse, ImmutableViolation

IMPORTER_VERSION = "ml-intake-2"
SCHEMA = 2
IST = "Asia/Kolkata"
TIER = "T1b"
UNVERIFIED, VERIFIED = "external_unverified", "external_verified"
REVIEWED_PATH = Path(__file__).with_name("reviewed_sessions.json")

HEADER = ["date", "open", "high", "low", "close", "volume"]
FIRST_MOD, LAST_MOD = 9 * 60 + 15, 15 * 60 + 29        # minute-of-day of the first and last regular bar starts
SESSION_MINUTES = 375
MIN_MINUTES = 360                                       # a session needs 96% of its minutes
MAX_EDGE_GAP = 5                                        # ...and its first and last bar within 5 minutes of the open and the close
MAX_JITTER_S = 15                                       # a stamp up to 15 s past the minute is floored; beyond it the row is dropped
MAX_UNPARSED_SHARE = 0.01                               # a file with more than 1% unparsable rows is not this format
JUMP = 0.05                                             # index: a one-minute log return above 5% goes to review
CORROBORATE = 0.03                                      # the other index moved this much, the same way, within a minute: evidence
STALE_RUN = 10                                          # consecutive flat bars repeating the previous close: halt or frozen feed
STALE_SHARE = 0.03                                      # ...or more than 3% of the session's bars stale, in however many runs
REVIEW_CODES = ("jump", "stale_run", "stale_share", "weekend_full")
HARD_CODES = ("weekend", "short_session", "truncated", "end_labelled")
OBSERVED = {"jump": "max_1m_move_at", "stale_run": "longest_stale_run", "stale_share": "stale_bars", "weekend_full": "minutes"}
EVIDENCE_MIN_CHARS, EVIDENCE_MIN_WORDS = 40, 6
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SourceFormatError(ValueError):
    """The source is not what the importer was written for (missing file, different header, unparsable): nothing is guessed."""


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
    """Content hash of a frame that does not depend on the pandas version, the datetime unit (us or ns), the string dtype or
    how Parquet stored it: each column is reduced to a fixed little-endian form first. -0.0 is 0.0 and every NaN is one NaN.
    A timestamp column's timezone is part of its kind (the same instants in UTC are a different column), strings are length
    prefixed (so a NUL inside one cannot shift a boundary), and bool is not int. Column names, their order and the row count
    are part of the hash."""
    h = hashlib.sha256()
    h.update(f"{len(df)}|".encode())
    for c in df.columns:
        s = df[c]
        if isinstance(s.dtype, pd.DatetimeTZDtype):
            kind, b = f"ts:{s.dt.tz}", pd.DatetimeIndex(s).tz_convert("UTC").as_unit("ns").asi8.astype("<i8").tobytes()
        elif pd.api.types.is_bool_dtype(s):
            kind, b = "bool", s.to_numpy("bool").astype("u1").tobytes()
        elif pd.api.types.is_float_dtype(s):
            a = s.to_numpy("float64") + 0.0
            kind, b = "f8", np.where(np.isnan(a), np.nan, a).astype("<f8").tobytes()
        elif pd.api.types.is_integer_dtype(s):
            kind, b = "i8", s.to_numpy("int64").astype("<i8").tobytes()
        else:
            enc = [str(x).encode() for x in s.tolist()]
            kind, b = "str", np.array([len(e) for e in enc], dtype="<u4").tobytes() + b"".join(enc)
        h.update(f"{c}:{kind}:{len(b)}|".encode())
        h.update(b)
    return h.hexdigest()


def _sig(x: float) -> float:
    """12 significant digits: the validation numbers in the manifest (and so the digest) must not depend on the last bit of a
    log() on another CPU or numpy build."""
    return float(f"{float(x):.12g}")


# ---- reading one file -----------------------------------------------------------------------------------------------
def read_minutes(path: Path, symbol: str) -> tuple[pd.DataFrame, dict, dict]:
    """Raw rows → minutes labelled by bar start (tz-aware IST), what was dropped, and the drops per day.

    Dropped and counted: unparsable or non-finite rows, stamps more than MAX_JITTER_S past the minute, non-positive or
    inconsistent prices (open/close outside the high-low range, high < low), negative or fractional volume. Floored and
    counted: stamps 1 to MAX_JITTER_S seconds past the minute. Refused outright: a different header, or a file that looks
    end-labelled (more bars at 15:30 than at 09:15: an end-labelled file has no 09:15 bar), which would shift every bar by a minute."""
    rep = {"rows_in": 0, "unparsed": 0, "ambiguous_timestamp": 0, "floored_seconds": 0, "bad_price": 0,
           "invalid_volume": 0, "out_of_order": 0, "zero_volume": 0}
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    if list(raw.columns) != HEADER:
        raise SourceFormatError(f"{path.name}: header {list(raw.columns)} is not {HEADER}")
    rep["rows_in"] = int(len(raw))
    ts = pd.to_datetime(raw["date"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    num = {c: pd.to_numeric(raw[c], errors="coerce").to_numpy(float) for c in HEADER[1:]}
    ok_num = np.isfinite(np.column_stack(list(num.values()))).all(axis=1)
    ts_ok = ts.notna().to_numpy()
    parsed = ts_ok & ok_num
    rep["unparsed"] = int((~parsed).sum())
    sec = ts.dt.second.fillna(0).to_numpy(int)
    ambiguous = parsed & (sec > MAX_JITTER_S)
    rep["floored_seconds"] = int((parsed & ~ambiguous & (sec > 0)).sum())
    keep = parsed & ~ambiguous
    t = ts.dt.floor("min")
    mod = (t.dt.hour * 60 + t.dt.minute).fillna(-1).to_numpy(int)
    if int((keep & (mod == LAST_MOD + 1)).sum()) > int((keep & (mod == FIRST_MOD)).sum()):
        raise SourceFormatError(f"{path.name}: more bars at 15:30 than at 09:15: the file looks end-labelled, not bar-start")
    per_day: dict[str, int] = {}

    def by_day(mask: np.ndarray) -> None:
        for d, k in ts[mask & ts_ok].dt.date.value_counts().items():
            per_day[str(d)] = per_day.get(str(d), 0) + int(k)

    by_day(~ok_num)                                           # an unparsable number on a row that does have a date
    rep["ambiguous_timestamp"] = int(ambiguous.sum())
    by_day(ambiguous)
    o, h, l_, c, v = (num[k] for k in ("open", "high", "low", "close", "volume"))
    with np.errstate(invalid="ignore"):
        bad_price = keep & ((np.minimum.reduce([o, h, l_, c]) <= 0) | (h < l_) | (o > h) | (o < l_) | (c > h) | (c < l_))
        bad_vol = keep & ((v < 0) | (v != np.floor(v))) & ~bad_price
    rep["bad_price"], rep["invalid_volume"] = int(bad_price.sum()), int(bad_vol.sum())
    by_day(bad_price | bad_vol)
    keep = keep & ~bad_price & ~bad_vol
    rep["zero_volume"] = int((keep & (v == 0)).sum())
    df = pd.DataFrame({"ts": t[keep].dt.tz_localize(IST), "open": o[keep], "high": h[keep], "low": l_[keep],
                       "close": c[keep], "volume": v[keep].astype("int64")}).reset_index(drop=True)
    a = pd.DatetimeIndex(df["ts"]).asi8
    rep["out_of_order"] = int((np.diff(a) < 0).sum()) if len(a) > 1 else 0
    return df, rep, per_day


# ---- one session ----------------------------------------------------------------------------------------------------
def longest_run(mask: np.ndarray) -> int:
    if not len(mask) or not mask.any():
        return 0
    d = np.diff(np.r_[0, mask.astype(np.int8), 0])
    return int((np.flatnonzero(d == -1) - np.flatnonzero(d == 1)).max())


def check_session(g: pd.DataFrame, day: dt.date, index_rules: bool = True) -> tuple[pd.DataFrame, dict]:
    """One day's minutes from one file → (clean in-session minutes, the validation record).

    Hard rejections (the session is out): fewer than MIN_MINUTES of the 375 regular minutes (a weekend one is also coded
    'weekend'); a first or last bar more than MAX_EDGE_GAP minutes from the open or the close ('truncated': a "to the close"
    label would sit on a session that does not reach the close); a 15:30 bar and no 09:15 bar ('end_labelled': every bar of
    that day would be a minute late, which the whole-file check in read_minutes cannot see in a file that mixes labellings).
    Review (out unless a reviewer admits it): a one-minute log return above JUMP and more than STALE_SHARE of the bars stale
    (both index kinds only: a volatility index is noisy and legitimately prints flat minutes); STALE_RUN or more consecutive
    flat bars repeating the previous close (every kind); a weekend date with a full session ('weekend_full': the Budget
    Saturdays are real sessions).
    Minutes outside 09:15-15:29 are dropped and counted; a minute with two identical bars keeps one, with two different bars
    is dropped whole. The record carries the session's realised variance, so a reviewer can see what excluding it costs."""
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
    v["head_gap_min"] = int(m[0]) if n else SESSION_MINUTES
    v["tail_gap_min"] = int(SESSION_MINUTES - 1 - m[-1]) if n else SESSION_MINUTES
    v["longest_gap_min"] = int(gaps.max() - 1) if n > 1 else SESSION_MINUTES
    if n > 1:
        r = np.diff(np.log(c))
        i = int(np.argmax(np.abs(r)))
        v["max_1m_move"], v["max_1m_move_signed"] = _sig(abs(r[i])), _sig(r[i])
        v["max_1m_move_at"] = str(g["ts"].iloc[i + 1])
        v["rv"] = _sig(np.sum(r * r))
        flat = ((g["open"] == g["high"]) & (g["high"] == g["low"]) & (g["low"] == g["close"])).to_numpy()
        stale = flat[1:] & (c[1:] == c[:-1]) & (gaps == 1)
        v["longest_stale_run"], v["stale_bars"] = longest_run(stale), int(stale.sum())
    else:
        v["max_1m_move"], v["max_1m_move_signed"], v["max_1m_move_at"], v["rv"] = 0.0, 0.0, None, 0.0
        v["longest_stale_run"], v["stale_bars"] = 0, 0
    weekend, short = day.weekday() >= 5, n < MIN_MINUTES
    hard = (["weekend"] if weekend and short else []) + (["short_session"] if short else [])
    if n and (v["head_gap_min"] > MAX_EDGE_GAP or v["tail_gap_min"] > MAX_EDGE_GAP):
        hard.append("truncated")
    if bool((mod == LAST_MOD + 1).any()) and not bool((mod == FIRST_MOD).any()):
        hard.append("end_labelled")
    found = set()
    if index_rules and v["max_1m_move"] > JUMP:
        found.add("jump")
    if v["longest_stale_run"] >= STALE_RUN:
        found.add("stale_run")
    if index_rules and n and v["stale_bars"] / n > STALE_SHARE:
        found.add("stale_share")
    if weekend and not short:
        found.add("weekend_full")
    review = [k for k in REVIEW_CODES if k in found]
    v["hard_codes"], v["review_codes"] = hard, review
    v["status"] = "rejected" if hard else ("review" if review else "accepted")
    v["reasons"] = ([f"{n} of {SESSION_MINUTES} minutes" if k == "short_session" else
                     f"first bar {v['head_gap_min']} min after the open, last bar {v['tail_gap_min']} min before the close"
                     if k == "truncated" else "a 15:30 bar and no 09:15 bar: the day looks end-labelled" if k == "end_labelled"
                     else k for k in hard]
                    + ([f"{v['max_1m_move']:.1%} one-minute log move at {v['max_1m_move_at']}"] if "jump" in review else [])
                    + ([f"{v['longest_stale_run']} consecutive stale bars"] if "stale_run" in review else [])
                    + ([f"{v['stale_bars']} of {n} bars stale"] if "stale_share" in review else [])
                    + ([f"weekend session with {n} minutes"] if "weekend_full" in review else []))
    return g, v


# ---- the reviewed list ----------------------------------------------------------------------------------------------
def load_reviewed(path: Path | None = None) -> tuple[dict, str]:
    """{(symbol, day): entry} and the file's sha256. A malformed entry is an error, never skipped. An entry names the
    reviewer and the date, the source file it was reviewed on (sha256), and the facts it was reviewed against (`observed`:
    one number per code); it applies only while the session's file and facts are the same."""
    p = Path(path or REVIEWED_PATH)
    raw = p.read_bytes()
    doc = json.loads(raw)
    if doc.get("schema") != 2 or not isinstance(doc.get("sessions"), list):
        raise ReviewedListError(f"{p.name}: expected schema 2 and a list of sessions")
    out = {}
    need = {"symbol", "day", "codes", "decision", "evidence", "reviewer", "date", "file_sha256", "observed"}
    for e in doc["sessions"]:
        if not need <= set(e):
            raise ReviewedListError(f"{p.name}: entry {e!r} lacks {sorted(need - set(e))}")
        who = f"{e['symbol']} {e['day']}"
        if e["decision"] != "admit" or not e["codes"] or not set(e["codes"]) <= set(REVIEW_CODES):
            raise ReviewedListError(f"{p.name}: {who}: decision must be 'admit' with codes from {REVIEW_CODES}")
        ev = str(e["evidence"]).strip()
        if len(ev) < EVIDENCE_MIN_CHARS or len(ev.split()) < EVIDENCE_MIN_WORDS:
            raise ReviewedListError(f"{p.name}: {who}: the evidence is too thin to admit a session "
                                    f"(at least {EVIDENCE_MIN_CHARS} characters and {EVIDENCE_MIN_WORDS} words)")
        if not str(e["reviewer"]).strip():
            raise ReviewedListError(f"{p.name}: {who}: no reviewer named")
        for k in ("day", "date"):
            if not _ISO_DAY.match(str(e[k])):
                raise ReviewedListError(f"{p.name}: {who}: {k} must be YYYY-MM-DD, not {e[k]!r}")
            dt.date.fromisoformat(e[k])
        if not re.fullmatch(r"[0-9a-f]{64}", str(e["file_sha256"])):
            raise ReviewedListError(f"{p.name}: {who}: file_sha256 must be the source file's sha256")
        if set(e["observed"]) != {OBSERVED[k] for k in e["codes"]}:
            raise ReviewedListError(f"{p.name}: {who}: observed must hold exactly {sorted({OBSERVED[k] for k in e['codes']})}")
        if (e["symbol"], e["day"]) in out:
            raise ReviewedListError(f"{p.name}: {who} is listed twice")
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
    """Every pre-declared number and policy. Part of the dataset identity: changing any of them is a new importer version and
    a new dataset, never an edit."""
    return {"importer_version": IMPORTER_VERSION, "schema": SCHEMA, "timezone": IST, "timestamp": "bar start",
            "session": "09:15-15:29 bar starts (375 minutes)", "min_minutes": MIN_MINUTES, "max_edge_gap": MAX_EDGE_GAP,
            "max_jitter_s": MAX_JITTER_S, "max_unparsed_share": MAX_UNPARSED_SHARE, "jump": JUMP, "corroborate": CORROBORATE,
            "stale_run": STALE_RUN, "stale_share": STALE_SHARE, "review_codes": list(REVIEW_CODES), "hard_codes": list(HARD_CODES),
            "header": HEADER, "evidence_min": [EVIDENCE_MIN_CHARS, EVIDENCE_MIN_WORDS],
            "policy": {"dedupe": "identical bars in a minute collapse to one; two different bars in a minute: both dropped",
                       "bad_price": "non-positive, high < low, open or close outside the high-low range",
                       "stale_bar": "open = high = low = close = the previous close, on consecutive minutes",
                       "jump_statistic": "absolute one-minute log return of the close; indices only, not the volatility index",
                       "stale_share": "more than 3% of the bars stale; indices only, not the volatility index",
                       "labelling": "bar start; a file with more 15:30 bars than 09:15 bars is refused",
                       "weekend": "short: rejected; full-length: review"}}


def dataset_digest(man: dict) -> str:
    """One digest over everything that makes the data what it is. The import time, the status (which P0.6 changes when the
    independent check passes), the source's version label and the code commit are not part of it."""
    core = {k: man[k] for k in ("schema", "importer_version", "rules", "reviewed_sha256", "partitions", "sessions")}
    core["source"] = {k: v for k, v in man["source"].items() if k != "version"}
    return hashlib.sha256(canonical_json(core)).hexdigest()


def identity(source: dict, rules_: dict, reviewed_sha: str) -> str:
    """The 12 hex characters in the folder name: what was read, under which rules and which reviewed list."""
    files = sorted((f["path"], f["sha256"]) for f in source["files"])
    meta = {k: source[k] for k in ("name", "url", "licence", "redistributable")}
    return hashlib.sha256(canonical_json({"files": files, "meta": meta, "rules": rules_, "reviewed": reviewed_sha})).hexdigest()[:12]


def code_commit() -> dict:
    here = Path(__file__).parent
    try:
        sha = subprocess.run(["git", "-C", str(here), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(here), "status", "--porcelain", "--", str(here)], capture_output=True,
                                    text=True, check=True).stdout.strip())
        return {"commit": sha or None, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def import_source(source_root: Path, out_root: Path, src: Source = KAGGLE_INDEX_MINUTES, version: str = "",
                  reviewed_path: Path | None = None, say=print) -> dict:
    """Read every file of `src`, validate, and write the immutable dataset and its manifest. Returns the manifest."""
    say = say or (lambda *a: None)
    source_root = Path(source_root)
    reviewed, reviewed_sha = load_reviewed(reviewed_path)
    files, sessions, clean = [], [], {}
    for fid, sf in enumerate(src.files):
        path = source_root / sf.path
        if not path.is_file():
            raise SourceFormatError(f"{sf.path} is missing from {source_root}")
        sha, size = sha256_file(path)
        df, rep, dropped = read_minutes(path, sf.symbol)
        if rep["rows_in"] == 0 or rep["unparsed"] / rep["rows_in"] > MAX_UNPARSED_SHARE:
            raise SourceFormatError(f"{sf.path}: {rep['unparsed']} of {rep['rows_in']} rows unparsable (more than "
                                    f"{MAX_UNPARSED_SHARE:.0%}): this is not the format the importer was written for")
        entry = {"id": fid, "path": sf.path, "symbol": sf.symbol, "kind": sf.kind, "sha256": sha, "bytes": size, **rep}
        files.append(entry)
        n_days = 0
        for day, g in df.groupby(df["ts"].dt.date):
            g2, v = check_session(g, day, index_rules=sf.kind == "index")
            v.update({"symbol": sf.symbol, "file_id": fid, "rows_dropped": dropped.get(str(day), 0)})
            sessions.append(v)
            clean[(sf.symbol, str(day))] = g2.assign(source_file=fid)
            n_days += 1
        entry["sessions"] = n_days
        if not any(s["symbol"] == sf.symbol and s["status"] == "accepted" for s in sessions):
            raise SourceFormatError(f"{sf.path}: not one session passes validation: this is not the data the importer was written for")
        say(f"  {sf.symbol}: {rep['rows_in']:,} rows, {n_days} days (dropped: "
            f"{rep['unparsed']} unparsed, {rep['bad_price']} bad price, {rep['ambiguous_timestamp']} ambiguous stamp; "
            f"floored {rep['floored_seconds']})")
    idx_syms = {f.symbol for f in src.files if f.kind == "index"}
    applied, seen, not_applied = [], set(), []
    for v in sorted(sessions, key=lambda r: (r["symbol"], r["day"])):
        v["corroborated_by"] = corroborate(v, {s: clean[(s, v["day"])] for s in idx_syms - {v["symbol"]} if (s, v["day"]) in clean})
        e = reviewed.get((v["symbol"], v["day"]))
        v["reviewed"] = None
        if e is None:
            continue
        seen.add((v["symbol"], v["day"]))
        who, needed = f"{v['symbol']} {v['day']}", set(v["review_codes"])
        if v["status"] != "review":
            not_applied.append({"session": who, "why": f"the session is {v['status']}, not in review"})
        elif not needed <= set(e["codes"]):
            not_applied.append({"session": who, "why": f"the entry covers {sorted(e['codes'])}, the session needs {sorted(needed)}"})
        elif e["file_sha256"] != files[v["file_id"]]["sha256"]:
            not_applied.append({"session": who, "why": "the source file is not the one that was reviewed"})
        elif any(e["observed"][OBSERVED[k]] != v[OBSERVED[k]] for k in needed):
            not_applied.append({"session": who, "why": "the session's facts are not the ones that were reviewed"})
        else:
            v["status"], v["reviewed"] = "accepted_reviewed", {"by": e["reviewer"], "on": e["date"], "evidence": e["evidence"]}
            applied.append(who)
    sessions.sort(key=lambda r: (r["symbol"], r["day"]))
    source = {"name": src.name, "url": src.url, "version": version, "licence": src.licence,
              "redistributable": src.redistributable, "files": files}
    ds = Path(out_root) / src.name / f"{IMPORTER_VERSION}-{identity(source, rules(), reviewed_sha)}"
    parts = {}
    for sf in src.files:
        keep = [clean[(sf.symbol, v["day"])] for v in sessions
                if v["symbol"] == sf.symbol and v["status"] in ("accepted", "accepted_reviewed")]
        m1 = pd.concat(keep).sort_values("ts", kind="stable").reset_index(drop=True)
        m1 = m1.assign(symbol=sf.symbol, tier=TIER)[["ts", "open", "high", "low", "close", "volume", "symbol", "tier", "source_file"]]
        for y, g in m1.groupby(m1["ts"].dt.year):
            g = g.reset_index(drop=True)
            p = ds / "1m" / f"symbol={sf.symbol}" / f"year={y}.parquet"
            parts[p.relative_to(ds).as_posix()] = {"sha256": _write_once(g, p), "rows": int(len(g))}
        say(f"  {sf.symbol}: {sum(1 for v in sessions if v['symbol'] == sf.symbol and v['status'].startswith('accepted'))} "
            f"sessions kept, {len(m1):,} minutes")
    man = {"schema": SCHEMA, "importer_version": IMPORTER_VERSION, "dataset": ds.name, "tier": TIER, "status": UNVERIFIED,
           "source": source, "allowed_uses": sorted(ALLOWED_USES), "not_for": FORBIDDEN_NOTE, "rules": rules(),
           "reviewed_sha256": reviewed_sha, "reviewed_applied": applied, "reviewed_not_applied": not_applied,
           "reviewed_unused": sorted(f"{s} {d}" for s, d in reviewed.keys() - seen),
           "partitions": parts, "sessions": sessions, "code": code_commit(), "imported_at": str(pd.Timestamp.now(tz=IST))}
    man["digest"] = dataset_digest(man)
    prev = ds / "manifest.json"
    if prev.exists():
        old = json.loads(prev.read_text())
        if old.get("digest") != man["digest"]:
            raise ImmutableViolation(f"{prev}: the same dataset folder, a different digest ({old.get('digest', '?')[:12]} ≠ {man['digest'][:12]})")
        man["status"], man["imported_at"], man["code"] = old.get("status", UNVERIFIED), old.get("imported_at", man["imported_at"]), old.get("code", man["code"])
        man["source"]["version"] = old["source"].get("version", version)
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
                     for f in man["source"]["files"]],
           "reviewed_not_applied": man.get("reviewed_not_applied", []), "reviewed_unused": man.get("reviewed_unused", [])}
    if s.empty:
        return out
    s["year"] = s["day"].str[:4]
    pool = s[s["status"].isin(["accepted", "accepted_reviewed", "review"])].copy()
    pool["rv_rank"] = pool.groupby("symbol")["rv"].rank(ascending=False, method="min").astype(int)
    pool["rv_of"] = pool.groupby("symbol")["rv"].transform("size")
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
            "conflicting_duplicate_minutes": int(g["conflicting_duplicates"].sum()), "identical_duplicate_rows": int(g["duplicates"].sum()),
            "by_year": {y: {"sessions": int(len(gy)), "accepted": int(gy["status"].isin(["accepted", "accepted_reviewed"]).sum())}
                        for y, gy in g.groupby("year")}}
    for r in pool[pool["status"] == "review"].to_dict("records"):
        out["review_queue"].append({k: r[k] for k in ("symbol", "day", "review_codes", "reasons", "corroborated_by", "longest_stale_run",
                                                       "stale_bars", "minutes", "max_1m_move", "max_1m_move_at", "rv", "rv_rank", "rv_of")})
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
         f"**Status: {q['status']}** (uses: {', '.join(man['allowed_uses'])}; {man['not_for']}). Digest `{q['digest'][:16]}`. "
         "Volume is not used: it is 0 in every row of this source.", ""]
    n_rev = len(q["review_queue"])
    if n_rev:
        top = min(q["review_queue"], key=lambda r: r["rv_rank"] / r["rv_of"])
        L += [f"**The default set excludes {n_rev} sessions in review; the highest-variance of them is {top['symbol']} {top['day']} "
              f"(rank {top['rv_rank']} of {top['rv_of']}). A study on the default set is censored at the tail until a reviewer admits "
              "them; say so in the spec.**", ""]
    for sym, b in q["by_symbol"].items():
        L += [f"## {sym}: {b['accepted']} of {b['sessions']} sessions kept ({b['first_day']} → {b['last_day']}), {b['review']} in review, "
              f"{b['rejected']} rejected {b['rejected_by_code']}; missing-minute rate {b['missing_minute_rate']:.3%}; minutes dropped for "
              f"two different bars in one minute: {b['conflicting_duplicate_minutes']} (identical repeats collapsed: {b['identical_duplicate_rows']})", ""]
    if q["review_queue"]:
        L += ["## Review queue (excluded until a reviewer admits them in reviewed_sessions.json, with evidence)", "",
              "| symbol | day | why | corroborated by | realised-variance rank |", "|---|---|---|---|---|"]
        for r in q["review_queue"]:
            L.append(f"| {r['symbol']} | {r['day']} | {'; '.join(r['reasons'])} | {', '.join(r['corroborated_by']) or '-'} | "
                     f"{r['rv_rank']} of {r['rv_of']} |")
        L.append("")
    if q["reviewed_not_applied"] or q["reviewed_unused"]:
        L += ["## Reviewed entries that did not apply", ""] + [f"- {r['session']}: {r['why']}" for r in q["reviewed_not_applied"]]
        L += [f"- {u}: no such session in this source" for u in q["reviewed_unused"]] + [""]
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
# The independent checks that can verify a dataset, each tied to the sha256 of the criteria file that was committed before the check ran
# (docs/ml/P0_6_criteria.md). A new criteria version is a new entry here, added by a reviewed change.
VERIFICATION_CRITERIA = {"p06-v1": "0958f8b96ce36fbac44921f326c3e649663dc1607e014ed99557ed6186bcf21c",           # its one run was void: no record under it exists
                         "p06-v2": "508534f5657190f3ca57ee1cd8dd76cbc81aedabcced056a421f9ad7a019b51b"}


def effective_status(ds: Path, man: dict, symbols) -> str:
    """`external_verified` only if a verification record (written by the P0.6 check) names this manifest's digest, says it passed, names a check
    whose criteria hash it carries (`VERIFICATION_CRITERIA`), and lists the symbols it covered (`symbols_verified`); and then only for those
    symbols. Asked about `symbols` that the record does not cover (the volatility index, say), the answer is `external_unverified`; so is a
    record without `symbols_verified` or `criteria_sha256`. `symbols` is required: a caller names what it is about to use, and a whole-dataset
    question is asked by naming every symbol in it. The word in the manifest alone is not evidence."""
    if man.get("status") != VERIFIED:
        return UNVERIFIED
    vp = Path(ds) / "verification.json"
    try:
        rec = json.loads(vp.read_text())
    except (OSError, ValueError, RecursionError):                    # unreadable, not JSON, or nested so deep that the parser gives up
        return UNVERIFIED
    if not isinstance(rec, dict) or rec.get("digest") != man.get("digest") or rec.get("passed") is not True:
        return UNVERIFIED
    check = rec.get("check")
    if not isinstance(check, str) or VERIFICATION_CRITERIA.get(check) is None or rec.get("criteria_sha256") != VERIFICATION_CRITERIA[check]:
        return UNVERIFIED
    covered = rec.get("symbols_verified")
    if not (isinstance(covered, list) and covered and all(isinstance(c, str) and c for c in covered)):
        return UNVERIFIED
    asked = {symbols} if isinstance(symbols, str) else set(symbols)
    return VERIFIED if asked and asked <= set(covered) else UNVERIFIED


def load(ds: Path, symbols, use: str, allow_unverified: bool = False, expected_digest: str | None = None) -> pd.DataFrame:
    """The dataset's 1-minute bars for a declared use. Refused: any use outside ALLOWED_USES; a folder without a manifest; a
    manifest whose digest does not recompute or whose folder name does not match its identity; unverified data unless the
    caller says it accepts that; a partition missing, extra, or no longer hashing to the manifest; a symbol that is not in
    the dataset; a digest other than `expected_digest` when the caller (a spec) names one. The result's attrs carry the
    dataset, digest, status, the restriction, and the sessions left out for review."""
    if use not in ALLOWED_USES:
        raise ForbiddenUse(f"use {use!r} refused: {FORBIDDEN_NOTE}")
    if isinstance(symbols, str):
        raise ValueError("symbols must be a non-empty list of symbols, not one string")
    symbols = list(symbols)                              # a generator is consumed once: validate and load the same list
    if not symbols:
        raise ValueError("symbols must be a non-empty list of symbols, not one string")
    if len(set(symbols)) != len(symbols):                # a symbol twice would hand every one of its rows back twice
        raise ValueError(f"symbols repeats a symbol: {sorted(s for s in set(symbols) if symbols.count(s) > 1)}")
    ds = Path(ds)
    mp = ds / "manifest.json"
    if not mp.is_file():
        raise ForbiddenUse(f"{ds}: no manifest, so no provenance: refused")
    man = json.loads(mp.read_text())
    if dataset_digest(man) != man.get("digest"):
        raise ImmutableViolation(f"{ds.name}: the manifest does not hash to its own digest: it was altered")
    if ds.name != f"{man['importer_version']}-{identity(man['source'], man['rules'], man['reviewed_sha256'])}" or man["dataset"] != ds.name:
        raise ImmutableViolation(f"{ds.name}: the folder name does not match what the manifest says this dataset is")
    if expected_digest is not None and man["digest"] != expected_digest:
        raise ImmutableViolation(f"{ds.name}: digest {man['digest'][:12]} is not the {expected_digest[:12]} that was asked for")
    status = effective_status(ds, man, symbols)
    if status != VERIFIED and not allow_unverified:
        raise ForbiddenUse(f"{ds.name} is {UNVERIFIED}: run the verification first, or pass allow_unverified=True "
                           "and label the results as unverified")
    on_disk = {p.relative_to(ds).as_posix() for p in (ds / "1m").rglob("*.parquet")}
    if on_disk != set(man["partitions"]):
        raise ImmutableViolation(f"{ds.name}: partitions on disk differ from the manifest "
                                 f"(extra {sorted(on_disk - set(man['partitions']))[:3]}, missing {sorted(set(man['partitions']) - on_disk)[:3]})")
    have = {f["symbol"] for f in man["source"]["files"]}
    for sym in symbols:
        if sym not in have or not any(f"/symbol={sym}/" in f"/{p}" for p in man["partitions"]):
            raise ValueError(f"{sym!r} is not in {ds.name} (it holds {sorted(have)})")
    parts = []
    for sym in symbols:
        for rel in sorted(p for p in man["partitions"] if f"/symbol={sym}/" in f"/{p}"):
            df = pd.read_parquet(ds / rel)
            if canonical_hash(df) != man["partitions"][rel]["sha256"]:
                raise ImmutableViolation(f"{rel} no longer hashes to the manifest: the dataset was altered")
            parts.append(df)
    out = pd.concat(parts, ignore_index=True)
    asked = set(symbols)
    # everything a consumer will quote comes from what the digest covers (the sessions) or from the rows, never from a manifest
    # field that sits outside it
    tiers = sorted(out["tier"].unique())
    out.attrs.update({"source": man["source"]["url"], "dataset": ds.name, "digest": man["digest"], "status": status,
                      "tier": tiers[0] if len(tiers) == 1 else tiers, "use": use, "not_for": FORBIDDEN_NOTE,
                      "excluded_review": [f"{s['symbol']} {s['day']}" for s in man["sessions"]
                                          if s["symbol"] in asked and s["status"] == "review"],
                      "admitted_reviewed": [f"{s['symbol']} {s['day']}" for s in man["sessions"]
                                            if s["symbol"] in asked and s["status"] == "accepted_reviewed"]})
    return out


def latest(out_root: Path, src: Source = KAGGLE_INDEX_MINUTES) -> Path | None:
    """The most recently imported dataset of this source (by the import time in its manifest), not the highest folder name."""
    d = Path(out_root) / src.name
    found = []
    for p in (d.glob(f"{IMPORTER_VERSION}-*") if d.exists() else []):
        if (p / "manifest.json").exists():
            found.append((json.loads((p / "manifest.json").read_text()).get("imported_at", ""), p.name, p))
    return sorted(found)[-1][2] if found else None
