"""The journal save's guards (C-01 shrink, C-12 lease) and the desk's kill-switch gate (C-08), run for real: the shell
scripts against a local bare remote, the gate's step script against a fake `gh`."""
import json
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest
import yaml

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


def _journal(path: Path, trades: int, thoughts: int, news: int = 0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        for t in ("trades", "fills", "decisions", "events", "thoughts", "news"):
            db.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY, x TEXT)")
        db.executemany("INSERT INTO trades (x) VALUES (?)", [("t",)] * trades)
        db.executemany("INSERT INTO thoughts (x) VALUES (?)", [("h",)] * thoughts)
        db.executemany("INSERT INTO news (x) VALUES (?)", [("n",)] * news)


@pytest.fixture()
def desk(tmp_path):
    """A clone with the deploy scripts, whose origin is a bare repo holding a `journal` branch with 3 trades."""
    remote, seed, work = tmp_path / "remote.git", tmp_path / "seed", tmp_path / "work"
    sh(["git", "init", "-q", "--bare", str(remote)], tmp_path)
    sh(["git", "init", "-q", str(seed)], tmp_path)
    _journal(seed / "intraday" / "journal.db", trades=3, thoughts=10)
    sh("git checkout -q -b journal && git add -A && git commit -qm j && git remote add origin ../remote.git "
       "&& git push -q origin journal", seed)
    sh(["git", "clone", "-q", str(remote), str(work)], tmp_path)
    (work / "deploy").mkdir()
    for f in ("journal.sh", "push-dir.sh", "journal_counts.py"):
        (work / "deploy" / f).write_bytes((ROOT / "deploy" / f).read_bytes())
        (work / "deploy" / f).chmod(0o755)
    return work, remote


def _head(remote):
    return sh(["git", "rev-parse", "journal"], remote).stdout.strip()


def test_a_normal_save_replaces_the_restored_commit(desk):
    work, remote = desk
    sh("deploy/journal.sh restore", work)
    _journal(work / "runtime" / "intraday" / "journal.db", trades=1, thoughts=5)      # the session adds to it
    before = _head(remote)
    sh("deploy/journal.sh save 'close'", work)
    assert _head(remote) != before
    assert (work / "runtime" / ".journal-restored-sha").read_text().strip() == _head(remote)   # a 2nd save leases on it


def test_a_save_smaller_than_the_restore_is_refused(desk):
    work, remote = desk
    sh("deploy/journal.sh restore", work)
    db = work / "runtime" / "intraday" / "journal.db"
    db.unlink()
    _journal(db, trades=1, thoughts=10)                                  # a partial/wrong journal: 1 trade, not 3
    before = _head(remote)
    r = sh("deploy/journal.sh save 'close'", work, check=False)
    assert r.returncode != 0 and "trades is 1, below the 3 restored" in r.stderr
    assert _head(remote) == before                                       # the only copy is untouched


def test_a_deliberate_reset_may_shrink(desk):
    work, remote = desk
    sh("deploy/journal.sh restore", work)
    db = work / "runtime" / "intraday" / "journal.db"
    db.unlink()
    _journal(db, trades=0, thoughts=0)
    sh("deploy/journal.sh save 'reset'", work, env={"JOURNAL_ALLOW_SHRINK": "1"})


def test_a_save_never_overwrites_another_jobs_save(desk, tmp_path):
    work, remote = desk
    sh("deploy/journal.sh restore", work)
    other = tmp_path / "other"                                           # a learning cycle saves meanwhile
    sh(["git", "clone", "-q", "-b", "journal", str(remote), str(other)], tmp_path)
    _journal(other / "intraday" / "journal.db", trades=2, thoughts=0)
    sh("git add -A && git commit -qm other && git push -q origin journal", other)
    theirs = _head(remote)
    _journal(work / "runtime" / "intraday" / "journal.db", trades=1, thoughts=0)
    r = sh("deploy/journal.sh save 'close'", work, check=False)
    assert r.returncode != 0 and "moved since it was restored" in r.stderr
    assert _head(remote) == theirs


# ---- C-02: the one shrink a verified prune may cause -----------------------------------------------------------------------
def _restored_with_news(work, news=8):
    """Restore, give the journal `news` headlines, and take the figures a real restore would have recorded."""
    sh("deploy/journal.sh restore", work)
    rt = work / "runtime"
    _journal(rt / "intraday" / "journal.db", trades=0, thoughts=0, news=news)
    figures = sh(["python3", "deploy/journal_counts.py", str(rt / "intraday" / "journal.db")], work).stdout
    (rt / ".journal-restored.json").write_text(figures)
    return rt, (rt / ".journal-restored-sha").read_text().strip()


def _pruned(rt, trades=3, thoughts=10, news=5):
    """The journal after a prune: news lost its oldest rows and VACUUM renumbered the rest, so the max id fell."""
    db = rt / "intraday" / "journal.db"
    db.unlink()
    _journal(db, trades=trades, thoughts=thoughts, news=news)


def _permit(rt, sha, pruned, version=1):
    (rt / ".journal-prune-permit.json").write_text(json.dumps({"version": version, "restored_sha": sha, "pruned": pruned}))


def test_a_save_after_a_verified_prune_passes(desk):
    work, remote = desk
    rt, sha = _restored_with_news(work)
    _pruned(rt)                                                          # news max id 8 -> 5; trades/thoughts untouched
    before = _head(remote)
    refused = sh("deploy/journal.sh save 'close'", work, check=False)    # without the permit that is a shrink like any other
    assert refused.returncode != 0 and "news_max_id is 5, below the 8 restored" in refused.stderr and _head(remote) == before
    _permit(rt, sha, {"news": 3})
    sh("deploy/journal.sh save 'close'", work)
    assert _head(remote) != before


@pytest.mark.parametrize("what,expect", [
    (dict(trades=2), "trades is 2, below the 3 restored"),                # the account's record is never excused
    (dict(news=4), "news_rows is 4, below the 5 restored"),               # more rows gone than the prune took out
    (dict(thoughts=9), "thoughts_max_id is 9, below the 10 restored"),    # a table the permit does not name
])
def test_the_permit_excuses_nothing_else(desk, what, expect):
    work, remote = desk
    rt, sha = _restored_with_news(work)
    _pruned(rt, **{"trades": 3, "thoughts": 10, "news": 5, **what})
    _permit(rt, sha, {"news": 3})
    before = _head(remote)
    r = sh("deploy/journal.sh save 'close'", work, check=False)
    assert r.returncode != 0 and expect in r.stderr and _head(remote) == before


@pytest.mark.parametrize("permit", [dict(sha="not-the-commit-restored"), dict(pruned={}), dict(version=2),
                                    dict(pruned={"trades": 1}), dict(pruned={"news": "3"})])
def test_a_permit_for_another_commit_or_another_table_is_ignored(desk, permit):
    work, remote = desk
    rt, sha = _restored_with_news(work)
    _pruned(rt)
    _permit(rt, permit.get("sha", sha), permit.get("pruned", {"news": 3}), permit.get("version", 1))
    before = _head(remote)
    r = sh("deploy/journal.sh save 'close'", work, check=False)
    assert r.returncode != 0 and "news_max_id is 5, below the 8 restored" in r.stderr and _head(remote) == before


# ---- C-08: the gate's kill-switch check --------------------------------------------------------------------------
def _gate_script():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "live.yml").read_text(encoding="utf-8"))
    step = wf["jobs"]["gate"]["steps"][0]
    return step["run"].replace("${{ github.event_name }}", "workflow_dispatch")


def _run_gate(tmp_path, runs, views, fail=False, resume=""):
    """`runs`: the cancelled run ids gh run list returns; `views`: id -> list of (step name, conclusion)."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (tmp_path / "views.json").write_text(json.dumps({str(k): v for k, v in views.items()}))
    (bindir / "gh").write_text(f"""#!/usr/bin/env python3
import json, sys
if {fail!r}:
    sys.exit(1)
a = sys.argv[1:]
views = json.load(open({str(tmp_path / 'views.json')!r}))
if a[:2] == ["run", "list"]:
    print("\\n".join(str(i) for i in {runs!r}))
elif a[:2] == ["run", "view"]:
    steps = views.get(a[2], [])
    print(sum(1 for n, c in steps if n.startswith("Trade (paper)") and c == "cancelled"))
""")
    (bindir / "gh").chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    sh(["bash", "-c", _gate_script()], tmp_path,
       env={"PATH": f"{bindir}:{os.environ['PATH']}", "GITHUB_OUTPUT": str(out), "RESUME": resume,
            "GITHUB_REPOSITORY": "o/r"})
    return out.read_text().strip().splitlines()[-1]


def test_the_gate_trades_on_a_normal_day(tmp_path):
    assert _run_gate(tmp_path, [], {}) == "go=true"


def test_a_superseded_pending_run_is_not_a_kill_switch(tmp_path):
    """GitHub cancels a run that was only pending when another queued in the group: it never ran a step."""
    assert _run_gate(tmp_path, [11], {11: []}) == "go=true"


def test_a_run_cancelled_while_trading_keeps_the_desk_stopped(tmp_path):
    assert _run_gate(tmp_path, [11], {11: [("Restore the journal", "success"),
                                           ("Trade (paper) until the hand-over", "cancelled")]}) == "go=false"


def test_the_owner_can_resume_after_a_cancel(tmp_path):
    assert _run_gate(tmp_path, [11], {11: [("Trade (paper) until the hand-over", "cancelled")]}, resume="1") == "go=true"


def test_the_gate_fails_closed_when_runs_cannot_be_read(tmp_path):
    assert _run_gate(tmp_path, [], {}, fail=True) == "go=false"


def test_a_failed_look_at_the_remote_retries_instead_of_giving_up(desk):
    """Push and ls-remote both failing on a blip used to read as 'branch moved' and abort the save at once."""
    work, remote = desk
    sh("deploy/journal.sh restore", work)
    _journal(work / "runtime" / "intraday" / "journal.db", trades=1, thoughts=0)
    script = (work / "deploy" / "push-dir.sh").read_text()
    flaky = script.replace('if git push -q "${force[@]}"', 'if [ "$i" -gt 1 ] && git push -q "${force[@]}"').replace(
        'git ls-remote origin "refs/heads/$branch"', 'false')
    (work / "deploy" / "push-dir.sh").write_text(flaky.replace("sleep $((i * 5))", "true"))
    before = _head(remote)
    sh("deploy/journal.sh save 'close'", work)             # first try fails, the look fails, the retry lands
    assert _head(remote) != before
