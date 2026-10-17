"""Journal retention: archive, verify, then prune (finding C-02).

The journal branch is one force-pushed commit per run and GitHub refuses any file over 100 MB. Two things grow without
bound: `thoughts` and `news` in intraday/journal.db (~2 MB a session) and the plan-research studies in
intraday/autolearn/plan/studies/<id>/ (~8 MB each, one per research run). The owner's rule is that evidence is never
lost, so nothing is deleted until it sits in a dated, hash-recorded archive that has been reopened and checked:

  1. choose: `thoughts` / `news` rows dated before the cutoff, and the plan studies beyond the newest `keep_studies`;
  2. archive: the rows into a gzipped SQLite file (same schema), the studies into a tar.gz, both under `--out`;
  3. verify: reopen both, compare row counts, min/max ts and a content hash per table, and the sha256 of every
     archived study file against the file on disk. ANY mismatch aborts with nothing deleted;
  4. prune: delete exactly those rows (in the same locked transaction that was verified) and those study folders,
     then VACUUM.

Only `thoughts` and `news` are ever pruned. trades, fills, decisions, events, equity, checks and state are never
touched (they are the account's record and small), and neither is anything a plan-registry card, the lock or the
champion refers to.

A small ledger, intraday/retention.json, travels with the journal and says what was archived (counts, ranges, hashes,
which days of thoughts are gone). Readers that need old rows consult it: `quantdesk intraday learn --rebuild` refuses a
journal whose history is archived until `restore` has put it back, and the paper gate's session count adds the archived
days. `restore` puts the rows and the studies back from a manifest, verifying hashes first.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path

PRUNABLE = ("thoughts", "news")                     # the only tables this module ever deletes from
MIN_KEEP_DAYS = 14                                  # CLI floor: grading looks back 7 days, the site shows 3 sessions
LEDGER = "retention.json"
STUDY_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})-[0-9a-f]+$")
_TS_OK = "ts GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]*'"     # only well-formed timestamps are ever selected
_CHUNK = 1 << 20


class RetentionError(RuntimeError):
    """Verification or a safety check failed. Nothing was deleted."""


# ---- hashing --------------------------------------------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _row_json(row) -> bytes:
    return (json.dumps(list(row), separators=(",", ":"), ensure_ascii=False,
                       default=lambda o: "b64:" + o.hex() if isinstance(o, (bytes, bytearray)) else repr(o)) + "\n").encode()


def table_digest(db: sqlite3.Connection, table: str, where: str = "1=1", params=()) -> dict:
    """Row count, min/max ts and a sha256 over every row's full content, in primary-key order."""
    h, n = hashlib.sha256(), 0
    for row in db.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY id", params):
        h.update(_row_json(row))
        n += 1
    lo, hi = db.execute(f"SELECT MIN(ts), MAX(ts) FROM {table} WHERE {where}", params).fetchone()
    return {"rows": n, "min_ts": lo, "max_ts": hi, "sha256": h.hexdigest()}


# ---- selection ------------------------------------------------------------------------------------------------------
def _today_ist() -> dt.date:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)).date()


def reference_date(db: sqlite3.Connection, as_of: dt.date | None) -> dt.date:
    """The clock the cutoff counts back from: today, but never later than the newest thought/news in the journal, so an
    idle desk (or a wrong clock) cannot archive the whole record."""
    newest = []
    for t in PRUNABLE:
        d = db.execute(f"SELECT MAX(substr(ts,1,10)) FROM {t} WHERE {_TS_OK}").fetchone()[0]
        if d:
            newest.append(dt.date.fromisoformat(d))
    today = as_of or _today_ist()
    return min([today, *newest]) if newest else today


def _db_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


@dataclass
class StudyChoice:
    id: str
    path: Path
    bytes: int
    files: dict                                      # relpath -> {"bytes", "sha256"}


@dataclass
class Selection:
    cutoff: str
    reference: str
    where: str
    studies: list[StudyChoice] = field(default_factory=list)
    kept_studies: list[str] = field(default_factory=list)
    protected: dict = field(default_factory=dict)    # study id -> why it is not pruned
    warnings: list[str] = field(default_factory=list)


def _read_text(p: Path, limit: int = 8_000_000) -> str:
    try:
        return p.read_text(errors="ignore") if p.stat().st_size <= limit else ""
    except OSError:
        return ""


def _json(p: Path):
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _study_order_key(d: Path) -> tuple:
    """Newest last: the study id's date, then the report's own 'at' stamp, then mtime, then the name. mtime is only a
    late tiebreak: the journal branch is restored by git on every run, so every file's mtime is the restore time."""
    m = STUDY_ID.match(d.name)
    rep = _json(d / "report.json") or {}
    return (m.group(1) if m else "", str(rep.get("at") or ""), d.stat().st_mtime, d.name)


def study_references(root: Path, study_ids: list[str]) -> tuple[dict, list[str]]:
    """Which studies something still points at: latest.json, the lock, and the cards, artifacts, events and champion of
    the plan registry (a card names its config_hash; the trial log says which study produced that configuration).
    Returns ({study id: why}, warnings). A champion whose study cannot be resolved is a warning: the caller then
    prunes no studies at all."""
    plan = root / "intraday" / "autolearn" / "plan"
    why: dict[str, str] = {}
    warnings: list[str] = []
    latest = _json(plan / "latest.json") or {}
    if latest.get("study"):
        why[str(latest["study"])] = "plan/latest.json"
    files = [p for p in (plan / "registry").rglob("*") if p.is_file()] if (plan / "registry").exists() else []
    files += [p for p in plan.glob("lock*") if p.is_file()]
    for extra in ("registry", "lockbox.json", "lockbox_access.jsonl"):
        p = root / "intraday" / "autolearn" / extra
        files += [q for q in p.rglob("*") if q.is_file()] if p.is_dir() else ([p] if p.is_file() else [])
    for p in files:
        text = _read_text(p)
        for sid in study_ids:
            if sid in text:
                why.setdefault(sid, f"referenced by {p.relative_to(root).as_posix()}")
    state = _json(plan / "registry" / "state.json") or {}
    models = [m for m in [state.get("champion"), state.get("rollback_target"), *(state.get("challengers") or [])] if m]
    if models:
        trials = []
        tp = plan / "trials.jsonl"
        for line in _read_text(tp, 200_000_000).splitlines():
            try:
                trials.append(json.loads(line))
            except ValueError:
                pass
        for mid in models:
            card = _json(plan / "registry" / "models" / mid / "card.json") or {}
            ch = card.get("config_hash")
            found = {str(t["study"]) for t in trials if ch and t.get("config_hash") == ch and t.get("study")}
            for sid in found:
                why.setdefault(sid, f"study that produced {mid}")
            if not found and mid == state.get("champion"):
                warnings.append(f"champion {mid}: its study cannot be identified from trials.jsonl; no study will be pruned")
    return why, warnings


def choose_studies(root: Path, keep_studies: int) -> Selection:
    sel = Selection(cutoff="", reference="", where="")
    sdir = root / "intraday" / "autolearn" / "plan" / "studies"
    if not sdir.is_dir():
        return sel
    dirs = [d for d in sdir.iterdir() if d.is_dir() and not d.is_symlink()]
    recognised = sorted((d for d in dirs if STUDY_ID.match(d.name) and (d / "report.json").is_file()), key=_study_order_key)
    for d in dirs:
        if d not in recognised:
            sel.protected[d.name] = "not a finished study folder (no report.json or an unrecognised name)"
    refs, warns = study_references(root, [d.name for d in recognised])
    sel.warnings += warns
    newest = {d.name for d in recognised[max(0, len(recognised) - keep_studies):]} if keep_studies > 0 else set()
    for d in recognised:
        if d.name in newest:
            sel.kept_studies.append(d.name)
            sel.protected[d.name] = f"one of the newest {keep_studies}"
        elif d.name in refs:
            sel.kept_studies.append(d.name)
            sel.protected[d.name] = refs[d.name]
        elif warns:
            sel.kept_studies.append(d.name)
            sel.protected[d.name] = "champion's study unresolved"
        else:
            files = {}
            for p in sorted(d.rglob("*")):
                if p.is_symlink():
                    files = None
                    break
                if p.is_file():
                    files[p.relative_to(d).as_posix()] = {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
            if files is None:
                sel.kept_studies.append(d.name)
                sel.protected[d.name] = "contains a symlink"
                continue
            sel.studies.append(StudyChoice(d.name, d, sum(f["bytes"] for f in files.values()), files))
    return sel


# ---- archive writers ------------------------------------------------------------------------------------------------
def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.name.split(".", 1)
    for i in range(2, 1000):
        cand = path.with_name(f"{stem}_{i}.{suffix}")
        if not cand.exists():
            return cand
    raise RetentionError(f"no free name beside {path}")


def _gzip_file(src: Path, dst: Path) -> None:
    with open(src, "rb") as f, open(dst, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as z:
        shutil.copyfileobj(f, z, _CHUNK)
        z.flush()
    with open(dst, "rb") as f:
        os.fsync(f.fileno())


def _gunzip_file(src: Path, dst: Path) -> None:
    with gzip.open(src, "rb") as z, open(dst, "wb") as out:
        shutil.copyfileobj(z, out, _CHUNK)


def _schema(db: sqlite3.Connection, table: str) -> str:
    return db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in db.execute(f"PRAGMA table_info({table})")]


def _write_row_archive(src: sqlite3.Connection, tmp_db: Path, where: str, meta: dict) -> None:
    arc = sqlite3.connect(tmp_db)
    try:
        for t in PRUNABLE:
            arc.execute(_schema(src, t))
        arc.execute("CREATE TABLE retention_meta (key TEXT PRIMARY KEY, value TEXT)")
        arc.executemany("INSERT INTO retention_meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in meta.items()])
        for t in PRUNABLE:
            cols = _columns(src, t)
            q = ",".join("?" * len(cols))
            cur = src.execute(f"SELECT * FROM {t} WHERE {where} ORDER BY id")
            while rows := cur.fetchmany(5000):
                arc.executemany(f"INSERT INTO {t} ({','.join(cols)}) VALUES ({q})", rows)
        arc.commit()
    finally:
        arc.close()


def _write_study_archive(studies: list[StudyChoice], dst: Path) -> None:
    with open(dst, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as z, \
            tarfile.open(fileobj=z, mode="w") as tar:
        for s in studies:
            for rel in sorted(s.files):
                info = tar.gettarinfo(str(s.path / rel), arcname=f"studies/{s.id}/{rel}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = int(info.mtime)
                with open(s.path / rel, "rb") as f:
                    tar.addfile(info, f)
    with open(dst, "rb") as f:
        os.fsync(f.fileno())


# ---- verification ---------------------------------------------------------------------------------------------------
def verify_row_archive(gz: Path, expect: dict, scratch: Path) -> None:
    """Reopen the gzipped archive from disk; counts, ts range and content hash must match what will be deleted."""
    tmp = scratch / "verify-rows.db"
    try:
        _gunzip_file(gz, tmp)
        db = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        try:
            res = db.execute("PRAGMA integrity_check").fetchone()[0]
            if res != "ok":
                raise RetentionError(f"archive {gz.name} failed its integrity check: {res}")
            for t, want in expect.items():
                got = table_digest(db, t)
                if got != want:
                    raise RetentionError(f"archive {gz.name} table {t} does not match the rows to be deleted: "
                                         f"archive {got} vs journal {want}")
        finally:
            db.close()
    except (OSError, EOFError, zlib.error, sqlite3.Error) as exc:
        raise RetentionError(f"archive {gz.name} cannot be read back: {exc!r}") from exc
    finally:
        tmp.unlink(missing_ok=True)


def verify_study_archive(tgz: Path, studies: list[StudyChoice]) -> None:
    want = {f"studies/{s.id}/{rel}": meta["sha256"] for s in studies for rel, meta in s.files.items()}
    got: dict[str, str] = {}
    try:
        with tarfile.open(tgz, "r:gz") as tar:
            for m in tar:
                if not m.isfile():
                    raise RetentionError(f"{tgz.name}: unexpected member {m.name}")
                h = hashlib.sha256()
                f = tar.extractfile(m)
                while chunk := f.read(_CHUNK):
                    h.update(chunk)
                got[m.name] = h.hexdigest()
    except (OSError, EOFError, zlib.error, tarfile.TarError) as exc:
        raise RetentionError(f"{tgz.name} cannot be read back: {exc!r}") from exc
    if got != want:
        bad = sorted(set(got) ^ set(want) | {k for k in want.keys() & got.keys() if want[k] != got[k]})
        raise RetentionError(f"{tgz.name} does not match the study files on disk ({len(bad)} differ, e.g. {bad[:3]})")


# ---- the ledger that travels with the journal -------------------------------------------------------------------------
def ledger_path(journal_path: str | Path) -> Path:
    return Path(journal_path).parent / LEDGER


def read_ledger(journal_path: str | Path) -> dict:
    p = ledger_path(journal_path)
    try:
        led = json.loads(p.read_text())
        if isinstance(led, dict) and isinstance(led.get("runs"), list):
            return led
    except (OSError, ValueError):
        pass
    return {"version": 1, "runs": []}


def _write_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def archived_thought_days(journal_path: str | Path, since: str = "") -> set[str]:
    """Days of `thoughts` that were archived out of the journal (and not restored): they are still sessions the desk
    ran. The paper gate counts them."""
    days: set[str] = set()
    for r in read_ledger(journal_path)["runs"]:
        if not r.get("restored_at"):
            days |= {d for d in r.get("thought_days", []) if d >= since}
    return days


def history_archived(journal_path: str | Path) -> list[dict]:
    """Completed archive runs whose rows are not in the journal now. A full-history reader (learn --rebuild) must
    `restore` them first."""
    return [r for r in read_ledger(journal_path)["runs"] if r.get("status") == "done" and not r.get("restored_at")]


# ---- the run ------------------------------------------------------------------------------------------------------
def _dates(*ts: str | None) -> list[str]:
    return sorted({t[:10] for t in ts if t})


def _counts(db: sqlite3.Connection) -> dict:
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {n: db.execute(f"SELECT COUNT(*) FROM {n}").fetchone()[0] for n in sorted(names)}


def archive(root: str | Path, out: str | Path, keep_days: int = 30, keep_studies: int = 3, dry_run: bool = False,
            as_of: dt.date | None = None, vacuum: bool = True, say=print, extra: dict | None = None,
            before_prune=None, on_committed=None) -> dict:
    """Archive, verify, then prune. Returns the manifest (also written to `out` unless dry_run).

    `extra` is merged into the manifest (durable.py: the journal commit it came from). `before_prune(manifest, out, mpath)`
    runs once the archive is verified and the manifest is on disk, still inside the locked transaction: durable.py
    uploads it to its durable home and checks it restores from there. It returns a dict recorded in the manifest and
    the ledger under "durable"; anything it raises aborts with nothing deleted."""
    root, out = Path(root), Path(out)
    if keep_days < 1 or keep_studies < 0:
        raise ValueError("keep_days must be >= 1 and keep_studies >= 0")
    jpath = root / "intraday" / "journal.db"
    rep: dict = {"dry_run": dry_run, "journal": str(jpath), "keep_days": keep_days, "keep_studies": keep_studies,
                 "as_of": (as_of or _today_ist()).isoformat(), "pruned": False, "warnings": []}
    sel = choose_studies(root, keep_studies)
    rep["warnings"] += sel.warnings
    if not jpath.exists():
        rep["tables"], rep["note"] = {}, "no journal.db"
        db = None
    else:
        db = sqlite3.connect(jpath, isolation_level=None, timeout=60)
    try:
        tables: dict = {}
        where = "1=0"
        if db is not None:
            db.execute("BEGIN" if dry_run else "BEGIN IMMEDIATE")   # no writer can slip a row in between verify and delete
            ref = reference_date(db, as_of)
            cutoff = ref - dt.timedelta(days=keep_days)
            where = f"{_TS_OK} AND substr(ts,1,10) < '{cutoff.isoformat()}'"
            rep.update({"reference_date": ref.isoformat(), "cutoff": cutoff.isoformat()})
            for t in PRUNABLE:
                tables[t] = table_digest(db, t, where)
                tables[t]["kept_rows"] = db.execute(f"SELECT COUNT(*) FROM {t} WHERE NOT ({where}) OR ts IS NULL").fetchone()[0]
            before = _counts(db)
            rep["row_counts_before"] = before
            rep["tables"] = tables
        rep["size_before"] = {"journal_db": _db_size(jpath), "studies": sum(
            p.stat().st_size for p in (root / "intraday" / "autolearn" / "plan" / "studies").rglob("*") if p.is_file())
            if (root / "intraday" / "autolearn" / "plan" / "studies").is_dir() else 0}
        n_rows = sum(t["rows"] for t in tables.values())
        rep["studies"] = {"archive": [s.id for s in sel.studies], "kept": sel.kept_studies, "protected": sel.protected,
                          "bytes": sum(s.bytes for s in sel.studies)}
        if not n_rows and not sel.studies:
            if db is not None:
                db.execute("ROLLBACK")
            rep["note"] = "nothing to archive"
            say("retention: nothing to archive (journal and studies are within the retention window)")
            return rep

        if dry_run:
            rep["projected_size_after"] = _project(db, jpath, where, vacuum) if db is not None and n_rows else \
                {"journal_db": _db_size(jpath)}
            db.execute("ROLLBACK") if db is not None else None
            rep["projected_size_after"]["studies"] = rep["size_before"]["studies"] - rep["studies"]["bytes"]
            _say_plan(rep, say)
            return rep

        out.mkdir(parents=True, exist_ok=True)
        stamp = rep["as_of"]
        days = _dates(*[tables[t]["min_ts"] for t in tables], *[tables[t]["max_ts"] for t in tables])
        manifest: dict = {**rep, "version": 1, "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                          "files": {}, "verified": False, **(extra or {})}
        with tempfile.TemporaryDirectory(dir=out, prefix=".retention-") as scratch_s:
            scratch = Path(scratch_s)
            # 1. archive the rows
            if n_rows:
                name = _unique(out / f"journal-archive-{days[0]}_{days[-1]}.db.gz")
                tmp_db = scratch / "rows.db"
                _write_row_archive(db, tmp_db, where, {"as_of": stamp, "cutoff": rep["cutoff"], "keep_days": keep_days,
                                                       "source": "intraday/journal.db"})
                _gzip_file(tmp_db, name)
                tmp_db.unlink()
                manifest["files"]["rows"] = {"name": name.name, "bytes": name.stat().st_size, "sha256": sha256_file(name)}
                verify_row_archive(name, {t: {k: v for k, v in tables[t].items() if k != "kept_rows"} for t in PRUNABLE}, scratch)
            # 2. archive the studies
            if sel.studies:
                tgz = _unique(out / f"plan-studies-{stamp}.tar.gz")
                _write_study_archive(sel.studies, tgz)
                manifest["files"]["studies"] = {"name": tgz.name, "bytes": tgz.stat().st_size, "sha256": sha256_file(tgz)}
                verify_study_archive(tgz, sel.studies)
            manifest["verified"] = True
            manifest["studies"]["files"] = {s.id: s.files for s in sel.studies}
            mpath = _unique(out / f"archive-manifest-{stamp}.json")
            _write_json_atomic(mpath, manifest)            # the proof exists before anything is deleted
            say(f"retention: archived and verified -> {mpath}")
            if before_prune is not None:
                manifest["durable"] = before_prune(manifest, out, mpath)
                _write_json_atomic(mpath, manifest)

            # 3. record in the ledger (before deleting, so a crash never leaves rows gone and unrecorded)
            entry = {"at": manifest["created_at"], "status": "pending", "manifest": mpath.name, "cutoff": rep["cutoff"],
                     "archive": manifest["files"].get("rows", {}), "studies_archive": manifest["files"].get("studies", {}),
                     "tables": {t: {k: v for k, v in tables[t].items() if k != "kept_rows"} for t in PRUNABLE},
                     "thought_days": sorted({r[0] for r in db.execute(
                         f"SELECT DISTINCT substr(ts,1,10) FROM thoughts WHERE {where}")}) if n_rows else [],
                     "studies": [s.id for s in sel.studies], **({"durable": manifest["durable"]} if "durable" in manifest else {})}
            led = read_ledger(jpath)
            led["runs"].append(entry)
            _write_json_atomic(ledger_path(jpath), led)

            # 4. delete exactly the verified rows, in the same locked transaction, and check the books balance
            if n_rows and db is not None:
                for t in PRUNABLE:
                    cur = db.execute(f"DELETE FROM {t} WHERE {where}")
                    if cur.rowcount != tables[t]["rows"]:
                        raise RetentionError(f"{t}: deleted {cur.rowcount} rows, archived {tables[t]['rows']}")
                after = _counts(db)
                for t, n in before.items():
                    if (n if t not in PRUNABLE else n - tables[t]["rows"]) != after.get(t):
                        raise RetentionError(f"table {t} changed unexpectedly ({n} -> {after.get(t)})")
                db.execute("COMMIT")
                manifest["row_counts_after"] = after
                if on_committed is not None:          # the rows are gone from here on: whatever fails below (VACUUM, a
                    on_committed(manifest)            # study's rmtree), the caller must still be able to vouch for them
            elif db is not None:
                db.execute("ROLLBACK")
            if db is not None:
                db.close()
                db = None
            if n_rows and vacuum:
                v = sqlite3.connect(jpath, isolation_level=None)
                try:
                    v.execute("VACUUM")
                    if (res := v.execute("PRAGMA integrity_check").fetchone()[0]) != "ok":
                        raise RetentionError(f"journal failed its integrity check after pruning: {res}")
                finally:
                    v.close()
            # 5. delete the verified study folders (each re-hashed against the manifest first)
            removed, skipped = [], []
            for s in sel.studies:
                now = {p.relative_to(s.path).as_posix(): sha256_file(p) for p in s.path.rglob("*") if p.is_file()}
                if now != {r: m["sha256"] for r, m in s.files.items()}:
                    skipped.append(s.id)
                    continue
                shutil.rmtree(s.path)
                removed.append(s.id)
            manifest["studies"]["removed"], manifest["studies"]["skipped_changed_since_archive"] = removed, skipped
            manifest["pruned"] = True
            manifest["size_after"] = {"journal_db": _db_size(jpath), "studies": rep["size_before"]["studies"] - sum(
                s.bytes for s in sel.studies if s.id in removed)}
            _write_json_atomic(mpath, manifest)
            led = read_ledger(jpath)
            led["runs"][-1]["status"] = "done"
            led["runs"][-1]["studies"] = removed
            _write_json_atomic(ledger_path(jpath), led)
            say(f"retention: pruned {tables['thoughts']['rows']} thoughts, {tables['news']['rows']} news rows, "
                f"{len(removed)} studies; journal.db {rep['size_before']['journal_db'] / 1e6:.1f} -> "
                f"{manifest['size_after']['journal_db'] / 1e6:.1f} MB")
            return manifest
    except BaseException:
        if db is not None:
            try:
                db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        raise
    finally:
        if db is not None:
            db.close()


def _project(db: sqlite3.Connection, jpath: Path, where: str, vacuum: bool) -> dict:
    """The journal's size after pruning, measured on a scratch copy (the real file is untouched)."""
    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "journal.db"
        dst = sqlite3.connect(copy)
        db.backup(dst)
        dst.close()
        c = sqlite3.connect(copy, isolation_level=None)
        for t in PRUNABLE:
            c.execute(f"DELETE FROM {t} WHERE {where}")
        if vacuum:
            c.execute("VACUUM")
        c.close()
        return {"journal_db": copy.stat().st_size}


def _say_plan(rep: dict, say) -> None:
    say(f"retention (dry run): journal {rep['journal']}; reference {rep.get('reference_date')}, keep {rep['keep_days']} days "
        f"-> archive rows dated before {rep.get('cutoff')}")
    for t, d in rep["tables"].items():
        say(f"  {t}: {d['rows']} rows to archive ({d['min_ts']} .. {d['max_ts']}), {d['kept_rows']} kept")
    st = rep["studies"]
    say(f"  studies: archive {len(st['archive'])} ({st['bytes'] / 1e6:.1f} MB): {', '.join(st['archive']) or '-'}; "
        f"keep {len(st['kept'])}")
    for sid, why in st["protected"].items():
        say(f"    kept {sid}: {why}")
    for w in rep["warnings"]:
        say(f"  WARNING: {w}")
    pa = rep.get("projected_size_after", {})
    say(f"  journal.db {rep['size_before']['journal_db'] / 1e6:.1f} MB -> {pa.get('journal_db', 0) / 1e6:.1f} MB; "
        f"studies {rep['size_before']['studies'] / 1e6:.1f} MB -> {pa.get('studies', 0) / 1e6:.1f} MB")
    say("  nothing was changed")


# ---- restore -------------------------------------------------------------------------------------------------------
def restore(manifest_path: str | Path, root: str | Path, say=print) -> dict:
    """Put an archive run back: rows into thoughts/news (existing ids are kept as they are) and the studies into
    plan/studies. Every file is checked against the manifest's sha256 and every table against its content hash first."""
    mpath, root = Path(manifest_path), Path(root)
    man = json.loads(mpath.read_text())
    if not man.get("verified"):
        raise RetentionError("manifest is not marked verified")
    base = mpath.parent
    jpath = root / "intraday" / "journal.db"
    res = {"thoughts": 0, "news": 0, "studies": []}
    rows = man.get("files", {}).get("rows")
    stu = man.get("files", {}).get("studies")
    for f in (rows, stu):
        if f and sha256_file(base / f["name"]) != f["sha256"]:
            raise RetentionError(f"{f['name']}: sha256 differs from the manifest; refusing to restore")
    with tempfile.TemporaryDirectory() as d:
        scratch = Path(d)
        if rows:
            expect = {t: {k: v for k, v in man["tables"][t].items() if k != "kept_rows"} for t in PRUNABLE}
            verify_row_archive(base / rows["name"], expect, scratch)
            tmp = scratch / "rows.db"
            _gunzip_file(base / rows["name"], tmp)
            from .journal import Journal
            Journal(jpath).close()                                   # makes the file and the schema if the journal is new
            dst = sqlite3.connect(jpath, isolation_level=None, timeout=60)
            try:
                dst.execute("ATTACH DATABASE ? AS arc", (str(tmp),))
                dst.execute("BEGIN IMMEDIATE")
                for t in PRUNABLE:
                    cols = ",".join(_columns(dst, t))
                    cur = dst.execute(f"INSERT OR IGNORE INTO main.{t} ({cols}) SELECT {cols} FROM arc.{t}")
                    res[t] = cur.rowcount
                    got = table_digest(dst, f"main.{t}", f"id IN (SELECT id FROM arc.{t})")
                    want = table_digest(dst, f"arc.{t}")
                    if got != want:
                        raise RetentionError(f"{t}: restored rows differ from the archive (an id already in the journal "
                                             f"holds different content): {got} vs {want}")
                dst.execute("COMMIT")
                dst.execute("DETACH DATABASE arc")
            except BaseException:
                try:
                    dst.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            finally:
                dst.close()
        if stu:
            sdir = root / "intraday" / "autolearn" / "plan" / "studies"
            with tarfile.open(base / stu["name"], "r:gz") as tar:
                for m in tar:
                    target = (root / "intraday" / "autolearn" / "plan" / m.name).resolve()
                    if not str(target).startswith(str(sdir.resolve()) + os.sep) or not m.isfile():
                        raise RetentionError(f"unsafe member in {stu['name']}: {m.name}")
                    sid, rel = m.name.split("/", 2)[1:]
                    want = man["studies"]["files"][sid][rel]["sha256"]
                    if target.exists():
                        if sha256_file(target) != want:
                            raise RetentionError(f"{target} exists and differs from the archive; not overwriting")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    data = tar.extractfile(m).read()
                    if hashlib.sha256(data).hexdigest() != want:
                        raise RetentionError(f"{m.name}: content hash differs from the manifest")
                    target.write_bytes(data)
                    if sid not in res["studies"]:
                        res["studies"].append(sid)
    led = read_ledger(jpath)
    for r in led["runs"]:
        if r.get("manifest") == mpath.name:
            r["restored_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    _write_json_atomic(ledger_path(jpath), led)
    say(f"retention: restored {res['thoughts']} thoughts, {res['news']} news rows, {len(res['studies'])} studies from {mpath.name}")
    return res
