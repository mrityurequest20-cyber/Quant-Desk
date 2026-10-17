"""C-02, the durable home: archive -> upload to the journal-archive-YYYY release -> download back and verify -> prune.

`gh` is a fake on PATH that keeps release assets in a folder, so the real ReleaseStore, the real sqlite and the real
files run end to end; only the network is pretended. The fake can fail, refuse uploads, or hand back damaged bytes."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from quantdesk.journal import durable
from quantdesk.journal import retention as R
from test_retention import AS_OF, PROTECTED_TABLES, counts, make_runtime, study_files, table_hashes

ROOT = Path(__file__).resolve().parent.parent
TAG = "journal-archive-2026"

FAKE_GH = '''#!/usr/bin/env python3
import fnmatch, json, os, shutil, sys
from pathlib import Path
home, mode, a = Path(os.environ["FAKE_GH_DIR"]), os.environ.get("FAKE_GH_MODE", ""), sys.argv[1:]
with open(home / "calls.log", "a") as f:
    f.write(" ".join(a) + "\\n")
if mode == "down":
    print("HTTP 502: bad gateway", file=sys.stderr)
    sys.exit(1)
rel = home / "releases" / a[2]
if a[1] == "view":
    if not rel.is_dir():
        print("release not found", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"assets": [{"name": p.name} for p in sorted(rel.iterdir())]}))
elif a[1] == "create":
    rel.mkdir(parents=True, exist_ok=True)
elif a[1] == "upload":
    if mode == "noupload":
        print("HTTP 500", file=sys.stderr)
        sys.exit(1)
    for p in [Path(x) for x in a[3:] if not x.startswith("-")]:
        if (rel / p.name).exists() and "--clobber" not in a:
            print("asset under the same name already exists", file=sys.stderr)
            sys.exit(1)
        data = p.read_bytes()
        (rel / p.name).write_bytes(data + b"x" if mode == "mangle" else data)
elif a[1] == "download":
    pat, dest = a[a.index("--pattern") + 1], Path(a[a.index("--dir") + 1])
    dest.mkdir(parents=True, exist_ok=True)
    for p in rel.iterdir():
        if fnmatch.fnmatch(p.name, pat):
            data = p.read_bytes()
            (dest / p.name).write_bytes(data[:-1] + bytes([data[-1] ^ 1]) if mode == "mangle-down" else data)
'''


@pytest.fixture()
def gh(tmp_path, monkeypatch):
    home, bindir = tmp_path / "gh", tmp_path / "bin"
    home.mkdir()
    bindir.mkdir()
    (bindir / "gh").write_text(FAKE_GH)
    (bindir / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:/usr/bin:/bin")
    monkeypatch.setenv("FAKE_GH_DIR", str(home))
    monkeypatch.delenv("FAKE_GH_MODE", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    class Fake:
        release = home / "releases" / TAG

        def mode(self, m):
            monkeypatch.setenv("FAKE_GH_MODE", m)

        def calls(self):
            p = home / "calls.log"
            return p.read_text().splitlines() if p.exists() else []

    return Fake()


def runtime(tmp_path) -> Path:
    rt = make_runtime(tmp_path)
    (rt / ".journal-restored-sha").write_text("c0ffee\n")
    return rt


def retain(rt, ret=None, **kw):
    lines: list[str] = []
    res = durable.retain(rt, ret, as_of=kw.pop("as_of", AS_OF), say=lines.append, **kw)
    return res, lines


def unchanged(rt, before, studies_before):
    assert table_hashes(rt) == before and study_files(rt) == studies_before
    assert not (rt / durable.PERMIT).exists()


# ---- success ------------------------------------------------------------------------------------------------------------
def test_upload_verify_then_prune(tmp_path, gh):
    rt = runtime(tmp_path)
    before, studies_before, n_before = table_hashes(rt), study_files(rt), counts(rt)
    res, lines = retain(rt)
    assert res["status"] == "pruned", lines

    assets = {p.name: p for p in gh.release.iterdir()}
    man_name = f"archive-manifest-{AS_OF}.json"
    man = json.loads(assets[man_name].read_text())
    assert sorted(assets) == sorted([man["files"]["rows"]["name"], man["files"]["studies"]["name"], man_name])
    for kind in ("rows", "studies"):                       # the sha256 recorded is that of the file on the release
        assert R.sha256_file(assets[man["files"][kind]["name"]]) == man["files"][kind]["sha256"]
    assert man["journal_commit"] == "c0ffee" and man["verified"]
    assert man["tables"]["thoughts"]["rows"] > 0 and man["tables"]["thoughts"]["min_ts"] and man["tables"]["thoughts"]["max_ts"]
    assert len(man["studies"]["archive"]) == 3             # 6 studies, the newest 3 kept

    after = table_hashes(rt)
    for t in PROTECTED_TABLES:                             # the account's record is untouched, byte for byte
        assert after[t] == before[t], t
    n_after = counts(rt)
    for t in ("trades", "fills", "decisions", "events"):
        assert n_after[t] == n_before[t] > 0
    assert n_after["thoughts"] == n_before["thoughts"] - man["tables"]["thoughts"]["rows"]
    assert n_after["news"] == n_before["news"] - man["tables"]["news"]["rows"]
    assert set(studies_before) - set(study_files(rt)) and all(
        s.split("/")[0] in man["studies"]["archive"] for s in set(studies_before) - set(study_files(rt)))

    permit = json.loads((rt / durable.PERMIT).read_text())        # what the save's shrink guard is told
    assert permit["restored_sha"] == "c0ffee" and permit["release"] == TAG
    assert permit["pruned"] == {t: man["tables"][t]["rows"] for t in R.PRUNABLE}
    assert "--clobber" not in " ".join(c for c in gh.calls() if c.startswith("release upload"))


def _ids(db_path: Path, table: str) -> set:
    db = sqlite3.connect(db_path)
    try:
        return {r[0] for r in db.execute(f"SELECT id FROM {table}")}
    finally:
        db.close()


def test_what_is_on_the_release_restores_on_its_own(tmp_path, gh):
    rt = runtime(tmp_path)
    full = {t: _ids(rt / "intraday" / "journal.db", t) for t in R.PRUNABLE}
    retain(rt)
    fresh = tmp_path / "fresh"
    out = R.restore(gh.release / f"archive-manifest-{AS_OF}.json", fresh, say=lambda *_: None)
    assert out["thoughts"] > 0 and out["news"] > 0 and len(out["studies"]) == 3
    for t in R.PRUNABLE:                                  # what the journal kept + what the release holds = what there was
        kept, back = _ids(rt / "intraday" / "journal.db", t), _ids(fresh / "intraday" / "journal.db", t)
        assert not kept & back and kept | back == full[t]


# ---- verification fails or the network does: nothing is pruned, the job carries on ------------------------------------------------
@pytest.mark.parametrize("mode", ["mangle", "mangle-down"])
def test_a_copy_that_differs_from_what_was_uploaded_prunes_nothing(tmp_path, gh, mode):
    rt = runtime(tmp_path)
    before, studies_before = table_hashes(rt), study_files(rt)
    gh.mode(mode)
    res, lines = retain(rt)
    assert res["status"] == "failed" and "differs from what was uploaded" in res["error"]
    assert any(l.startswith("::warning::") for l in lines)
    unchanged(rt, before, studies_before)


@pytest.mark.parametrize("mode", ["down", "noupload"])
def test_a_gh_failure_prunes_nothing_and_does_not_raise(tmp_path, gh, mode):
    rt = runtime(tmp_path)
    before, studies_before = table_hashes(rt), study_files(rt)
    gh.mode(mode)
    res, lines = retain(rt)
    assert res["status"] == "failed" and any(l.startswith("::warning::") for l in lines)
    unchanged(rt, before, studies_before)


def test_the_cli_exits_zero_when_gh_is_down(tmp_path, gh):
    from quantdesk import cli as top
    rt = runtime(tmp_path)
    before, studies_before = table_hashes(rt), study_files(rt)
    gh.mode("down")
    top.main(["intraday", "retain", "--root", str(rt), "--as-of", AS_OF.isoformat()])      # returns: no SystemExit
    unchanged(rt, before, studies_before)


def test_an_unverifiable_restore_blocks_the_prune(tmp_path, gh, monkeypatch):
    """The download is byte-identical but does not restore into an empty journal: still no prune."""
    rt = runtime(tmp_path)
    before, studies_before = table_hashes(rt), study_files(rt)

    def bad_restore(*a, **k):
        raise R.RetentionError("restored rows differ from the archive")
    monkeypatch.setattr(R, "restore", bad_restore)
    res, _ = retain(rt)
    assert res["status"] == "failed" and "restored rows differ" in res["error"]
    unchanged(rt, before, studies_before)


# ---- re-runs and name clashes -----------------------------------------------------------------------------------------------
def test_a_second_run_is_a_no_op_and_uploads_nothing(tmp_path, gh):
    rt = runtime(tmp_path)
    retain(rt)
    uploads = [c for c in gh.calls() if c.startswith("release upload")]
    snapshot, studies = table_hashes(rt), study_files(rt)
    permit = (rt / durable.PERMIT).read_text()
    res, lines = retain(rt)
    assert res["status"] == "nothing to archive" and any("nothing to archive" in l for l in lines)
    assert [c for c in gh.calls() if c.startswith("release upload")] == uploads
    assert table_hashes(rt) == snapshot and study_files(rt) == studies
    assert (rt / durable.PERMIT).read_text() == permit                 # the permit of the first prune is not lost
    assert len(list(gh.release.iterdir())) == 3


def test_an_asset_already_on_the_release_is_never_overwritten(tmp_path, gh):
    rt = runtime(tmp_path)
    gh.release.mkdir(parents=True)
    other = gh.release / f"archive-manifest-{AS_OF}.json"
    other.write_text("an earlier run's manifest")
    res, _ = retain(rt)
    assert res["status"] == "pruned"
    assert other.read_text() == "an earlier run's manifest"
    assert (gh.release / f"archive-manifest-{AS_OF}_2.json").is_file() and res["manifest"]["durable"]["manifest"].endswith("_2.json")


def test_a_clash_that_appears_after_the_listing_is_refused(tmp_path, gh):
    """Another writer takes the name between the listing and the upload: the upload fails, nothing is pruned."""
    rt = runtime(tmp_path)
    before, studies_before = table_hashes(rt), study_files(rt)
    real = durable._store

    def racing(prefix, year, run):
        store = real(prefix, year, run)
        listed = store.assets

        def assets(strict=False):
            names = listed(strict)
            if strict:                                         # the real listing is done; then someone else uploads
                gh.release.joinpath(f"archive-manifest-{AS_OF}.json").write_text("someone else's")
            return names
        store.assets = assets
        return store
    durable._store = racing
    try:
        res, _ = retain(rt)
    finally:
        durable._store = real
    assert res["status"] == "failed" and "already exists" in res["error"]
    assert gh.release.joinpath(f"archive-manifest-{AS_OF}.json").read_text() == "someone else's"
    unchanged(rt, before, studies_before)


# ---- when it runs --------------------------------------------------------------------------------------------------------------
def test_not_due_off_the_weekly_day_touches_nothing(tmp_path, gh):
    rt = runtime(tmp_path)
    before = table_hashes(rt)
    res, lines = retain(rt, as_of=AS_OF - dt.timedelta(days=1))                   # a Thursday
    assert res["reason"] == "not due" and not gh.calls() and table_hashes(rt) == before
    assert any("not due" in l for l in lines)


@pytest.mark.parametrize("ret", [{"journal_mb": 0.001}, {"tree_mb": 0.001}])
def test_an_oversize_journal_or_tree_is_due_on_any_day(tmp_path, gh, ret):
    rt = runtime(tmp_path)
    res, _ = retain(rt, ret, as_of=AS_OF - dt.timedelta(days=1))
    assert res["status"] == "pruned"


def test_keep_days_cannot_be_set_below_the_floor(tmp_path, gh):
    rt = runtime(tmp_path)
    res, lines = retain(rt, {"keep_days": 3})
    assert any("below the floor" in l for l in lines) and res["manifest"]["keep_days"] == R.MIN_KEEP_DAYS


def test_disabled_does_nothing(tmp_path, gh):
    res, _ = retain(runtime(tmp_path), {"enabled": False})
    assert res["reason"] == "disabled" and not gh.calls()


def test_dry_run_prints_the_plan_and_changes_and_uploads_nothing(tmp_path, gh):
    rt = runtime(tmp_path)
    before, studies_before = table_hashes(rt), study_files(rt)
    res, lines = retain(rt, dry_run=True)
    text = "\n".join(lines)
    assert res["status"] == "dry-run" and "journal.db" in text and "nothing was changed" in text and TAG in text
    assert "thoughts:" in text and "studies: archive 3" in text and "tree " in text
    assert not gh.calls()
    unchanged(rt, before, studies_before)


# ---- the guard accepts exactly this prune ---------------------------------------------------------------------------------------
def test_the_save_guard_accepts_the_verified_prune_it_was_given(tmp_path, gh):
    rt = runtime(tmp_path)
    restored = tmp_path / "restored.json"
    guard = ROOT / "deploy" / "journal_counts.py"
    restored.write_text(subprocess.run([sys.executable, str(guard), str(rt / "intraday" / "journal.db")],
                                       capture_output=True, text=True, check=True).stdout)
    retain(rt)
    cmd = [sys.executable, str(guard), str(rt / "intraday" / "journal.db"), "--not-below", str(restored)]
    ok = subprocess.run([*cmd, "--pruned", str(rt / durable.PERMIT), "--restored-sha", "c0ffee"], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr


def test_a_failure_after_the_rows_are_committed_still_leaves_the_permit(tmp_path, gh, monkeypatch):
    """Risk review, 17 Oct: once the DELETE is committed the rows are gone; a later failure (VACUUM, a study's rmtree)
    used to leave no permit, so that day's save was refused. The permit is now written at the commit, exactly once."""
    rt = runtime(tmp_path)
    restored = tmp_path / "restored.json"
    guard = ROOT / "deploy" / "journal_counts.py"
    restored.write_text(subprocess.run([sys.executable, str(guard), str(rt / "intraday" / "journal.db")],
                                       capture_output=True, text=True, check=True).stdout)
    monkeypatch.setattr(R.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    res, lines = retain(rt)
    assert res["status"] == "failed" and "disk" in res["error"]
    permit = json.loads((rt / durable.PERMIT).read_text())
    man = json.loads(next(p for p in gh.release.iterdir() if p.name.startswith("archive-manifest")).read_text())
    assert permit["pruned"] == {t: man["tables"][t]["rows"] for t in R.PRUNABLE}      # once, not doubled
    cmd = [sys.executable, str(guard), str(rt / "intraday" / "journal.db"), "--not-below", str(restored),
           "--pruned", str(rt / durable.PERMIT), "--restored-sha", "c0ffee"]
    ok = subprocess.run(cmd, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr


# ---- the workflow --------------------------------------------------------------------------------------------------------------
def test_the_autolearn_step_is_wired_with_no_new_permission_or_secret():
    text = (ROOT / ".github" / "workflows" / "autolearn.yml").read_text(encoding="utf-8")
    wf = yaml.safe_load(text)
    live = yaml.safe_load((ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8"))
    assert wf["permissions"] == {"contents": "write"} and "permissions" not in wf["jobs"]["cycle"]
    assert "secrets." not in text
    steps = wf["jobs"]["cycle"]["steps"]
    idx = [i for i, s in enumerate(steps) if "intraday retain" in s.get("run", "")]
    save = next(i for i, s in enumerate(steps) if str(s.get("run", "")).startswith("deploy/journal.sh save"))
    assert len(idx) == 1 and idx[0] < save                              # pruned before the save that carries it
    step = steps[idx[0]]
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}"} and step.get("continue-on-error") is True
    assert "steps.restore.outcome == 'success'" in step["if"]
    # never while the desk trades: same concurrency group as live.yml, queued not cancelled, scheduled after the close
    assert wf["concurrency"] == live["concurrency"] == {"group": "live-desk", "cancel-in-progress": False}
    minute, hour = (int(x) for x in wf.get("on", wf.get(True))["schedule"][0]["cron"].split()[:2])
    assert (hour * 60 + minute + 330) % 1440 > 15 * 60 + 30            # 10:40 UTC = 16:10 IST, after the 15:30 close


def test_the_shipped_config_has_sane_retention_settings():
    from quantdesk.config import DEFAULT_CONFIG, Config
    ret = durable.settings(Config.load(DEFAULT_CONFIG).get("intraday.retention"))
    assert ret["enabled"] and ret["keep_days"] >= R.MIN_KEEP_DAYS and ret["keep_studies"] >= 1
    assert ret["release_prefix"] == "journal-archive" and ret["journal_mb"] < 60 < 80      # trips before the push's warn/refuse lines
    assert ret["weekday"] in range(5)
