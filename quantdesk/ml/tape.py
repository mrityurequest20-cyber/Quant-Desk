"""P0.2 for tier T2 (docs/ML_PHASE0.md): the desk's own point-in-time option-chain tape → a registered, hash-checked dataset.

T1/T1b (`intake.py`) imports somebody else's bars. T2 is different in kind: it is our own recording (`<day>_<part>_chains.parquet`, one row per strike per snapshot, from the
Kotak chain feed), archived in the `chains-YYYY` releases. This module gives it what the other tiers have, and nothing more:

- **A manifest, or no data.** `import_tape` reads a folder of tape files and writes one `manifest.json`: for every file its name, sha256, row count, session day, part, time range,
  underlyings, sources, and what is wrong with it **counted, never repaired**. `load` refuses a dataset without a manifest, a manifest that no longer hashes to its digest, a file
  that is missing or whose bytes changed, and any use outside `ALLOWED_USES`.
- **Referenced, not copied.** Broker-feed data stays where it is (a runner, a private release). The manifest holds names, hashes and counts only, so it can sit in a run artifact
  or a model card's provenance; the data cannot.
- **A file that is not a tape is rejected with its reason** and never enters the manifest: a missing column, no timezone on `ts`, rows from a day other than the one in the file's
  name, an unknown part, an empty file.
- **Provenance everywhere.** Every row loaded carries `tier = "T2"` and its `source_file`. The model-chain fallback (`source != "kotak"`) is fabricated data (audit F-01): `load`
  drops it by default and says how many rows it dropped; so it does for snapshots with an implausible open-interest print or open-interest change (the same bound as `oi.OI_MAX`), the
  repeats of an exactly identical row, **every row of a key (ts, underlying, expiry, strike, source) recorded twice with different values** (both are quarantined: which one is right
  is not ours to pick) and rows outside the cash session. Repeats are looked for across the files of one session day, not only inside one file. Nothing is clipped or filled.
- **In time order.** `load` returns rows sorted by underlying, expiry, ts, strike (stable), and a `session` column (IST date), so a `shift` or `diff` per group never reads a later
  snapshot as an earlier one; the morning and afternoon files are not concatenated in file-name order.
- **Content-addressed and immutable.** The dataset's folder name is a hash of the file list; the same files give the same manifest, one more session is a different dataset, and a
  manifest is written once.

It does not decide what the tape is worth: no claim, gate or promotion rests on a manifest. Consumers (the OI shadow reads the tape through `oi.py` and its own pinned code) are
unchanged.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ..data.external_aeron import ForbiddenUse, ImmutableViolation
from . import intake as I

log = logging.getLogger(__name__)
IMPORTER_VERSION = "ml-tape-2"
SCHEMA = 1
TIER = "T2"
STATUS = "internal_recording"
ALLOWED_USES = ("oi_shadow", "option_research", "feature_building", "replay")
NOT_FOR = ("Broker-feed data: never published, never placed in a release or a model card (hashes and counts only), never joined to another tier without its provenance column, and not "
           "evidence for a gate or a promotion by itself.")
DROP_ORDER = ("model_source", "implausible_oi_snapshot", "implausible_doi_snapshot", "exact_duplicate", "conflicting_key", "outside_session")
OI_MAX = 1e12                                                        # equal to oi.OI_MAX (a test holds them equal)
SESSION_OPEN_MIN, SESSION_CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30
KEY = ["ts", "underlying", "expiry", "strike", "source"]
NUMERIC = ["spot", "strike", "ce_ltp", "ce_bid", "ce_ask", "ce_iv", "ce_oi", "ce_doi", "ce_vol", "pe_ltp", "pe_bid", "pe_ask", "pe_iv", "pe_oi", "pe_doi", "pe_vol",
           "ce_bidq", "ce_askq", "pe_bidq", "pe_askq"]
REQUIRED = ["ts", "underlying", "expiry", "source"] + NUMERIC
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(morning|afternoon)(?:-\d+)?_chains\.parquet$")


class TapeError(ValueError):
    pass


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _bad_oi(df: pd.DataFrame) -> np.ndarray:
    """Rows carrying an implausible OI print (infinite, negative or above OI_MAX); a missing print is no fault."""
    bad = np.zeros(len(df), dtype=bool)
    for c in ("ce_oi", "pe_oi"):
        x = df[c].to_numpy(float)
        with np.errstate(invalid="ignore"):
            bad |= np.isinf(x) | (x < 0) | (x > OI_MAX)
    return bad


def _bad_doi(df: pd.DataFrame) -> np.ndarray:
    """Rows carrying an implausible change in OI (infinite or beyond OI_MAX either way; the change may be negative); the recorder's corruption hits it as it hits OI."""
    bad = np.zeros(len(df), dtype=bool)
    for c in ("ce_doi", "pe_doi"):
        x = df[c].to_numpy(float)
        with np.errstate(invalid="ignore"):
            bad |= np.isinf(x) | (np.abs(x) > OI_MAX)
    return bad


def _whole_snapshot(df: pd.DataFrame, bad_rows: np.ndarray) -> np.ndarray:
    """A faulty row condemns every row of its snapshot (underlying, expiry, ts)."""
    if not len(df):
        return bad_rows
    snap = df.groupby(["underlying", "expiry", "ts"], sort=False, dropna=False).ngroup().to_numpy()
    bad_snap = np.zeros(snap.max() + 1, dtype=bool)
    np.logical_or.at(bad_snap, snap, bad_rows)
    return bad_snap[snap]


def _repeats(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(exact_duplicate, conflicting_key). The first of identical rows is kept and its repeats are exact duplicates; a key recorded with different values has all its rows flagged
    (none is preferred). `df` must have a default index; the content compared is the tape's own columns, not the provenance columns added at load."""
    exact = df[REQUIRED].duplicated(keep="first").to_numpy()
    u = df[REQUIRED].drop_duplicates()
    ck = u.loc[u.duplicated(KEY, keep=False), KEY].drop_duplicates()
    if not len(ck):
        return exact, np.zeros(len(df), dtype=bool)
    conf = df[KEY].merge(ck.assign(_c=True), on=KEY, how="left")["_c"].fillna(False).to_numpy(bool)
    return exact & ~conf, conf


def _flags(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Per-row fault flags, used both to count faults at import and to drop them at load. Nothing here changes a value. `df` has a default index."""
    local = df["ts"].dt.tz_convert(I.IST)
    minute = (local.dt.hour * 60 + local.dt.minute).to_numpy()
    exact, conflict = _repeats(df)
    return {"model_source": (df["source"] != "kotak").to_numpy(),
            "implausible_oi_snapshot": _whole_snapshot(df, _bad_oi(df)),
            "implausible_doi_snapshot": _whole_snapshot(df, _bad_doi(df)),
            "exact_duplicate": exact, "conflicting_key": conflict,
            "outside_session": ~((minute >= SESSION_OPEN_MIN) & (minute < SESSION_CLOSE_MIN))}


def check_file(path: Path) -> tuple[dict | None, list[str]]:
    """(record, []) for a tape file, or (None, reasons) if it is not one. The record counts faults; it never repairs them."""
    path = Path(path)
    m = NAME.match(path.name)
    if not m:
        return None, [f"{path.name}: not a tape file name (<day>_<morning|afternoon>[-runid]_chains.parquet)"]
    day, part = m.group(1), m.group(2)
    try:
        dt.date.fromisoformat(day)
        df = pd.read_parquet(path)
    except Exception as exc:
        return None, [f"{path.name}: not readable ({type(exc).__name__})"]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        return None, [f"{path.name}: missing columns {missing}"]
    if not len(df):
        return None, [f"{path.name}: no rows"]
    if not (isinstance(df["ts"].dtype, pd.DatetimeTZDtype)):
        return None, [f"{path.name}: ts has no timezone"]
    try:
        for c in NUMERIC:
            pd.to_numeric(df[c], errors="raise")
    except (TypeError, ValueError):
        return None, [f"{path.name}: a numeric column holds text"]
    days = set(df["ts"].dt.tz_convert(I.IST).dt.date.astype(str))
    if days != {day}:
        return None, [f"{path.name}: rows from {sorted(days)[:3]}, the file's name says {day}"]
    df = df.reset_index(drop=True).assign(**{c: pd.to_numeric(df[c]) for c in NUMERIC})
    fl = _flags(df)
    snaps = df.groupby(["underlying", "expiry", "ts"], sort=False, dropna=False).ngroup()
    both_quotes = (df["ce_bid"] > 0) & (df["ce_ask"] > 0), (df["pe_bid"] > 0) & (df["pe_ask"] > 0)
    rec = {"file": path.name, "day": day, "part": part, "sha256": _sha(path), "bytes": path.stat().st_size, "rows": int(len(df)),
           "ts_min": str(df["ts"].min()), "ts_max": str(df["ts"].max()), "snapshots": int(snaps.nunique()),
           "underlyings": {k: int(v) for k, v in df["underlying"].value_counts().sort_index().items()},
           "sources": {str(k): int(v) for k, v in df["source"].value_counts().sort_index().items()},
           "faults": {**{k: int(v.sum()) for k, v in fl.items()},
                      "crossed_quote_rows": int((both_quotes[0] & (df["ce_bid"] > df["ce_ask"]) | both_quotes[1] & (df["pe_bid"] > df["pe_ask"])).sum()),
                      "nonpositive_spot_rows": int((~(df["spot"] > 0)).sum()), "implausible_oi_rows": int(_bad_oi(df).sum()),
                      "implausible_doi_rows": int(_bad_doi(df).sum())}}
    return rec, []


def _day_check(files: list[dict], by_path: dict) -> dict:
    """What can only be seen across the files of one session day: the same key twice (identical or not) in two files, and the parts' time ranges overlapping."""
    if len(files) < 2:
        return {"files": len(files), "cross_file_exact_duplicate": 0, "cross_file_conflicting_key": 0, "parts_overlap_in_time": False}
    df = pd.concat([pd.read_parquet(by_path[f["file"]]) for f in files], ignore_index=True)
    df = df.assign(**{c: pd.to_numeric(df[c]) for c in NUMERIC})
    exact, conf = _repeats(df)
    inside = [f["faults"] for f in files]
    ranges = sorted((pd.Timestamp(f["ts_min"]), pd.Timestamp(f["ts_max"])) for f in files)
    return {"files": len(files), "cross_file_exact_duplicate": max(0, int(exact.sum()) - sum(x["exact_duplicate"] for x in inside)),
            "cross_file_conflicting_key": max(0, int(conf.sum()) - sum(x["conflicting_key"] for x in inside)),
            "parts_overlap_in_time": any(a[1] >= b[0] for a, b in zip(ranges, ranges[1:]))}


def identity(files: list[dict]) -> str:
    return hashlib.sha256(_canon({"importer": IMPORTER_VERSION, "schema": SCHEMA, "files": [(f["file"], f["sha256"], f["rows"]) for f in files]})).hexdigest()


def manifest_digest(man: dict) -> str:
    return hashlib.sha256(_canon({k: v for k, v in man.items() if k != "digest"})).hexdigest()


def import_tape(source: Path, out_root: Path, say=print) -> dict:
    """Register every tape file in `source`. Returns the manifest; writes it once under `<out_root>/tape/<version>-<identity[:12]>/manifest.json`."""
    source, out_root = Path(source), Path(out_root)
    paths = sorted(p for p in source.glob("*_chains.parquet")) if source.is_dir() else [source]
    files, rejected = [], []
    for p in paths:
        rec, why = check_file(p)
        (files if rec else rejected).append(rec if rec else {"file": p.name, "reasons": why})
    if not files:
        raise TapeError(f"{source}: no valid tape file" + (f" ({rejected[0]['reasons'][0]})" if rejected else ""))
    dup = sorted({(f["day"], f["part"]) for f in files if sum(1 for g in files if (g["day"], g["part"]) == (f["day"], f["part"])) > 1})
    if dup:
        raise TapeError(f"two files for the same session part {dup[:3]}: the archive holds one per part; refusing to guess which is right")
    by_path = {p.name: p for p in paths}
    day_checks = {d: _day_check([f for f in files if f["day"] == d], by_path) for d in sorted({f["day"] for f in files})}
    ident = identity(files)
    man = {"schema": SCHEMA, "dataset": f"{IMPORTER_VERSION}-{ident[:12]}", "identity": ident, "importer": IMPORTER_VERSION, "tier": TIER, "status": STATUS,
           "allowed_uses": list(ALLOWED_USES), "not_for": NOT_FOR, "source": "the desk's own chain recorder (Kotak chain feed), archived in the chains-YYYY releases",
           "referenced_not_copied": True, "code": I.code_commit(), "days": sorted({f["day"] for f in files}), "files": files, "rejected": rejected,
           "day_checks": day_checks, "totals": {"files": len(files), "rows": sum(f["rows"] for f in files), "snapshots": sum(f["snapshots"] for f in files),
                      "faults": {k: sum(f["faults"][k] for f in files) for k in files[0]["faults"]}}}
    man["digest"] = manifest_digest(man)
    ds = out_root / "tape" / man["dataset"]
    mp = ds / "manifest.json"
    if mp.exists():                                                  # the same files are the same dataset (the identity is a hash of them); the first registration stands
        return json.loads(mp.read_text())
    ds.mkdir(parents=True, exist_ok=True)
    with open(mp, "x") as fh:
        fh.write(json.dumps(man, indent=1, sort_keys=True, default=str))
    say(f"tape {man['dataset']}: {len(files)} file(s), {man['totals']['rows']:,} rows, {len(man['days'])} day(s), {len(rejected)} rejected")
    return man


def load(ds: Path, source: Path, use: str, days=None, clean: bool = True, expected_digest: str | None = None) -> pd.DataFrame:
    """The tape rows of a registered dataset for a declared use, read from `source` after every needed file is re-hashed. Refuses: no manifest, a manifest that does not hash to its
    digest (or to `expected_digest`), a folder whose name is not the manifest's identity, a missing or changed file, a use outside ALLOWED_USES. With `clean` (default) the faults the
    manifest counted are dropped from the result and counted in `attrs["dropped"]`; nothing is repaired either way."""
    ds, source = Path(ds), Path(source)
    if use not in ALLOWED_USES:
        raise ForbiddenUse(f"use {use!r} refused: tape data is for {ALLOWED_USES}. {NOT_FOR}")
    mp = ds / "manifest.json"
    if not mp.exists():
        raise TapeError(f"{ds}: no manifest.json: a tape dataset without a manifest is refused")
    man = json.loads(mp.read_text())
    if manifest_digest(man) != man.get("digest") or (expected_digest and man.get("digest") != expected_digest):
        raise ImmutableViolation(f"{ds.name}: the manifest does not hash to its digest" + (" / the expected one" if expected_digest else ""))
    if ds.name != man.get("dataset") or man.get("dataset") != f"{IMPORTER_VERSION}-{identity(man['files'])[:12]}":
        raise ImmutableViolation(f"{ds.name}: the folder name does not match what the manifest says this dataset is")
    want = [f for f in man["files"] if days is None or f["day"] in set(map(str, days))]
    by_day: dict[str, list[pd.DataFrame]] = {}
    for f in want:
        p = source / f["file"]
        if not p.exists():
            raise ImmutableViolation(f"{f['file']}: registered in {ds.name} but not found in {source}")
        if _sha(p) != f["sha256"]:
            raise ImmutableViolation(f"{f['file']}: its bytes no longer match the manifest")
        df = pd.read_parquet(p)
        by_day.setdefault(f["day"], []).append(df.assign(**{c: pd.to_numeric(df[c]) for c in NUMERIC}).assign(source_file=f["file"]))
    parts, dropped = [], {}
    for day in sorted(by_day):
        df = pd.concat(by_day[day], ignore_index=True)                  # the flags are computed over the whole session day, so a repeat across the morning and afternoon files is seen
        if clean:
            fl = _flags(df)
            drop = np.zeros(len(df), dtype=bool)
            for k in DROP_ORDER:                                        # first match: a row is counted under the first fault that names it
                dropped[k] = dropped.get(k, 0) + int((fl[k] & ~drop).sum())
                drop |= fl[k]
            df = df[~drop]
        parts.append(df)
    out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=REQUIRED + ["source_file"])
    if len(out):
        out = out.sort_values(["underlying", "expiry", "ts", "strike"], kind="stable").reset_index(drop=True)
        out["session"] = out["ts"].dt.tz_convert(I.IST).dt.date.astype(str)
    else:
        out["session"] = pd.Series(dtype=object)
    out["tier"] = TIER
    if any(dropped.values()):
        log.warning("tape %s: load dropped %s (first-match counts; the manifest counts every fault)", man["dataset"], {k: v for k, v in dropped.items() if v})
    out.attrs.update({"dataset": man["dataset"], "digest": man["digest"], "tier": TIER, "status": STATUS, "use": use, "not_for": NOT_FOR, "dropped": dropped})
    return out


def latest(out_root: Path) -> Path | None:
    d = Path(out_root) / "tape"
    c = sorted(p for p in d.glob(f"{IMPORTER_VERSION}-*") if (p / "manifest.json").exists()) if d.exists() else []
    return max(c, key=lambda p: json.loads((p / "manifest.json").read_text())["days"][-1]) if c else None
