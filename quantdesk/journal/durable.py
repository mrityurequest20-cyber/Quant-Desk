"""A durable home for the journal archive, and the weekly archive -> upload -> verify -> prune run (finding C-02).

retention.py archives thoughts/news and old plan studies to files, checks they reopen, then prunes. Those files used to
land on a runner that is thrown away, so nothing could be pruned safely. Here they go to a GitHub release,
`journal-archive-YYYY` (the same mechanism as `chains-YYYY`: `gh release upload`), together with the manifest (sha256 of
every file, rows per table and date range, the journal commit it came from). Before any row or study is deleted the
files are downloaded back from the release into a scratch folder, compared byte for byte (sha256) with what was
written, and restored into an empty journal with retention.restore's own checks (content hash per table, sha256 per
study file). Any failure leaves everything in place, prints a warning and returns: the desk's job never fails over
retention, and the next run tries again.

The prune runs inside archive()'s locked transaction (the `before_prune` hook), so exactly the rows that were uploaded
and verified are the rows that go. trades, fills, decisions and events are never touched (retention.PRUNABLE).

A verified prune leaves `<root>/.journal-prune-permit.json`, outside the saved tree. deploy/journal.sh hands it to
deploy/journal_counts.py, which then lets only thoughts/news fall by the rows that prune took out (VACUUM may renumber
news rowids, so their max-id figure can drop); every other shrink still refuses the save.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import retention as R

PERMIT = ".journal-prune-permit.json"
DEFAULTS = {"enabled": True, "release_prefix": "journal-archive", "keep_days": 21, "keep_studies": 3,
            "weekday": 4, "journal_mb": 40, "tree_mb": 150}
_MB = 1024 * 1024


def settings(section: dict | None) -> dict:
    return {**DEFAULTS, **(section or {})}


def _scrub(text: str) -> str:
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(k):
            text = text.replace(os.environ[k], "***")
    return text


def _why(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr or b"").decode(errors="replace")
        return _scrub(f"gh exited {exc.returncode}: {err.strip()[:300]}")
    return _scrub(f"{type(exc).__name__}: {exc}"[:500])


def tree_bytes(root: Path) -> int:
    base = root / "intraday"
    return sum(p.stat().st_size for p in base.rglob("*") if p.is_file() and not p.is_symlink()) if base.is_dir() else 0


def due(root: Path, ret: dict, as_of: dt.date) -> tuple[bool, str]:
    """At most weekly (the configured weekday), earlier only when the journal or the tree has outgrown its threshold."""
    jp = root / "intraday" / "journal.db"
    jb, tb = (jp.stat().st_size if jp.exists() else 0), tree_bytes(root)
    if jb > ret["journal_mb"] * _MB:
        return True, f"journal.db is {jb / _MB:.1f} MB (over {ret['journal_mb']} MB)"
    if tb > ret["tree_mb"] * _MB:
        return True, f"the journal tree is {tb / _MB:.1f} MB (over {ret['tree_mb']} MB)"
    if as_of.weekday() == ret["weekday"]:
        return True, f"weekly run day (weekday {ret['weekday']})"
    return False, (f"not the weekly run day (weekday {ret['weekday']}, today {as_of.weekday()}); journal.db {jb / _MB:.1f} MB "
                   f"and the tree {tb / _MB:.1f} MB are under {ret['journal_mb']} / {ret['tree_mb']} MB")


def _store(prefix: str, year: int, run):
    from ..data.warehouse import ReleaseStore
    return ReleaseStore(f"{prefix}-{year}", run=run, title=f"Journal archive {year}",
                        notes="Thoughts, news and plan studies archived out of the journal branch before they were pruned "
                              "(quantdesk/journal/durable.py): dated, hash-recorded files plus a manifest per run. "
                              "Restore with `quantdesk intraday archive --restore <manifest>`. Not a software release.")


def publish_and_verify(store, manifest: dict, out: Path, mpath: Path) -> dict:
    """Upload the archive files and the manifest (never overwriting), download them back and check they restore."""
    names = [f["name"] for f in manifest["files"].values()] + [mpath.name]
    want = {f["name"]: f["sha256"] for f in manifest["files"].values()}
    want[mpath.name] = R.sha256_file(mpath)
    store.ensure()
    clash = sorted(set(names) & set(store.assets(strict=True)))
    if clash:
        raise R.RetentionError(f"release {store.tag} already holds {', '.join(clash)}; not overwriting")
    store.push(out, names, clobber=False)
    with tempfile.TemporaryDirectory(prefix="journal-verify-") as d:
        dl, scratch = Path(d) / "download", Path(d) / "root"
        dl.mkdir()
        got = store.pull(dl, names)
        for n in names:
            if n not in got or not (dl / n).is_file():
                raise R.RetentionError(f"{n} is not on release {store.tag} after the upload")
            if R.sha256_file(dl / n) != want[n]:
                raise R.RetentionError(f"{n}: the copy downloaded from release {store.tag} differs from what was uploaded")
        res = R.restore(dl / mpath.name, scratch, say=lambda *_: None)     # hashes per table and per study file
        for t in R.PRUNABLE:
            if res[t] != manifest["tables"][t]["rows"]:
                raise R.RetentionError(f"{t}: restored {res[t]} rows from the release, expected {manifest['tables'][t]['rows']}")
        if sorted(res["studies"]) != sorted(manifest["studies"]["archive"]):
            raise R.RetentionError("the studies restored from the release are not the studies archived")
    return {"release": store.tag, "manifest": mpath.name, "sha256": want,
            "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


def write_permit(root: Path, manifest: dict) -> Path:
    sha = root / ".journal-restored-sha"
    restored = sha.read_text().strip() if sha.is_file() else ""
    try:                                                        # a second prune in the same job adds to the first
        prior = json.loads((root / PERMIT).read_text())
        prior = prior["pruned"] if prior["restored_sha"] == restored else {}
    except (OSError, ValueError, KeyError, TypeError):
        prior = {}
    permit = {"version": 1, "restored_sha": restored,
              "pruned": {t: manifest["tables"][t]["rows"] + int(prior.get(t, 0)) for t in R.PRUNABLE},
              "release": manifest["durable"]["release"], "manifest": manifest["durable"]["manifest"],
              "manifest_sha256": manifest["durable"]["sha256"][manifest["durable"]["manifest"]]}
    R._write_json_atomic(root / PERMIT, permit)
    return root / PERMIT


def retain(root: str | Path, ret: dict | None = None, as_of: dt.date | None = None, dry_run: bool = False,
           force: bool = False, run=subprocess.run, say=print) -> dict:
    """The scheduled run. Never raises over retention: a failure is a warning and nothing is pruned."""
    root, ret = Path(root), settings(ret)
    as_of = as_of or R._today_ist()
    res: dict = {"status": "skipped", "pruned": False}
    if not ret["enabled"]:
        say("retention: disabled (intraday.retention.enabled)")
        return {**res, "reason": "disabled"}
    keep_days = max(int(ret["keep_days"]), R.MIN_KEEP_DAYS)
    if keep_days != ret["keep_days"]:
        say(f"::warning::retention: keep_days {ret['keep_days']} is below the floor; using {R.MIN_KEEP_DAYS}")
    ok, why = due(root, ret, as_of)
    say(f"retention: {'due' if ok else 'not due'}: {why}")
    if not ok and not force and not dry_run:
        return {**res, "reason": "not due"}
    try:
        with tempfile.TemporaryDirectory(prefix="journal-archive-") as tmp:
            out = Path(tmp) / "out"
            kw = dict(keep_days=keep_days, keep_studies=int(ret["keep_studies"]), as_of=as_of, say=say)
            if dry_run:
                rep = R.archive(root, out, dry_run=True, **kw)
                tb = tree_bytes(root)
                after = rep.get("projected_size_after", {}).get("journal_db", rep["size_before"]["journal_db"])
                say(f"  durable home: release {ret['release_prefix']}-{as_of.year} (gh release upload, never overwriting); "
                    f"tree {tb / 1e6:.1f} MB -> "
                    f"{(tb - (rep['size_before']['journal_db'] - after) - rep.get('studies', {}).get('bytes', 0)) / 1e6:.1f} MB")
                return {**res, "status": "dry-run", "due": ok, "report": rep}
            store = _store(ret["release_prefix"], as_of.year, run)
            out.mkdir()
            for n in store.assets():                                    # names already on the release are never reused
                (out / n).touch()
            sha = root / ".journal-restored-sha"
            man = R.archive(root, out, extra={"journal_commit": sha.read_text().strip() if sha.is_file() else "unknown"},
                            before_prune=lambda m, o, mp: publish_and_verify(store, m, o, mp),
                            on_committed=lambda m: write_permit(root, m), **kw)   # once, the moment the rows are gone
            if man.get("pruned"):
                return {**res, "status": "pruned", "pruned": True, "manifest": man}
            return {**res, "status": "nothing to archive"}
    except Exception as exc:                                            # noqa: BLE001 - the desk's job must not fail over this
        say(f"::warning::journal retention did not complete (rows and studies are pruned only after their archive is verified on the release): {_why(exc)}")
        return {**res, "status": "failed", "error": _why(exc)}
