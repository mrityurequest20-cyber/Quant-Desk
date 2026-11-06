"""deploy/journal.sh is restore-only: the retired paper desk's record comes back from the `journal` branch, checked, and no
code path can write that branch any more (the desk and its `save` mode were retired on 6 Nov 2026). Run for real against
a local bare remote."""
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def sh(cmd, cwd, env=None, check=True):
    e = {**os.environ, **GIT, **(env or {})}
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        e.pop(k, None)
    r = subprocess.run(cmd, cwd=cwd, env=e, shell=isinstance(cmd, str), capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"{cmd} -> {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


@pytest.fixture()
def clone(tmp_path):
    """A clone holding deploy/journal.sh, whose origin is a bare repo with a `journal` branch (3 trades)."""
    remote, seed, work = tmp_path / "remote.git", tmp_path / "seed", tmp_path / "work"
    sh(["git", "init", "-q", "--bare", str(remote)], tmp_path)
    sh(["git", "init", "-q", str(seed)], tmp_path)
    db = seed / "intraday" / "journal.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, x TEXT)")
        c.executemany("INSERT INTO trades (x) VALUES (?)", [("t",)] * 3)
    sh("git checkout -q -b journal && git add -A && git commit -qm j && git remote add origin ../remote.git "
       "&& git push -q origin journal", seed)
    sh(["git", "clone", "-q", str(remote), str(work)], tmp_path)
    (work / "deploy").mkdir()
    (work / "deploy" / "journal.sh").write_bytes((ROOT / "deploy" / "journal.sh").read_bytes())
    (work / "deploy" / "journal.sh").chmod(0o755)
    return work, remote


def _head(remote):
    return sh(["git", "rev-parse", "journal"], remote).stdout.strip()


def test_restore_brings_back_the_record_and_checks_it(clone):
    work, _ = clone
    r = sh("deploy/journal.sh restore", work)
    assert "integrity check passed" in r.stdout
    with sqlite3.connect(work / "runtime" / "intraday" / "journal.db") as c:
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 3


def test_a_corrupt_journal_fails_the_restore(clone, tmp_path):
    work, remote = clone
    seed = tmp_path / "seed"
    (seed / "intraday" / "journal.db").write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)
    sh("git commit -qam broken && git push -q origin journal", seed)
    r = sh("deploy/journal.sh restore", work, check=False)
    assert r.returncode != 0


def test_there_is_no_save_and_the_branch_is_never_written(clone):
    work, remote = clone
    before = _head(remote)
    sh("deploy/journal.sh restore", work)
    r = sh("deploy/journal.sh save 'close'", work, check=False)
    assert r.returncode == 2 and "usage: journal.sh restore" in r.stderr
    assert _head(remote) == before
    assert "push" not in (ROOT / "deploy" / "journal.sh").read_text()


def test_no_workflow_saves_the_journal():
    import re
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert "journal.sh save" not in text, wf.name
        for line in re.findall(r"push-dir\.sh[^\n]*", text):               # the generic publisher is never pointed at the journal branch
            assert not re.search(r"\bjournal\b", line.split("push-dir.sh", 1)[1].split('"')[0]), (wf.name, line)
