"""deploy/paper_ledger.sh run for real against a local git remote: the first publish creates the branch, the second adds a commit WITHOUT touching the repository checkout (the bug a text test missed:
switching the checkout to the branch removed the code the verify step needs), a failed fetch of an existing branch never recreates it, and nothing new is not a commit. No network, no token."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "paper_ledger.sh"
pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("bash") is None, reason="git and bash are needed")


def sh(args, cwd, env=None, ok=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", **(env or {})})
    if ok:
        assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r


@pytest.fixture()
def remote(tmp_path):
    r = tmp_path / "remote.git"
    sh(["git", "init", "-q", "--bare", "-b", "main", str(r)], tmp_path)
    seed = tmp_path / "seed"
    seed.mkdir()
    sh(["git", "init", "-q", "-b", "main"], seed)
    (seed / "README").write_text("the repository\n")
    sh(["git", "add", "."], seed)
    sh(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"], seed)
    sh(["git", "remote", "add", "origin", str(r)], seed)
    sh(["git", "push", "-q", "origin", "main"], seed)
    return r


def run_script(mode, tmp_path, remote, account=None, extra_env=None, path=None):
    env = {"LEDGER_WORK": str(tmp_path / "work"), "LEDGER_REMOTE": str(remote), **({"ACCOUNT": str(account)} if account else {}), **(extra_env or {})}
    if path:
        env["PATH"] = path
    return sh(["bash", str(SCRIPT), mode], tmp_path, env=env, ok=False)


def acct(tmp_path, name, n):
    f = tmp_path / name
    f.write_text(json.dumps({"ledger": list(range(n))}))
    return f


def branch_files(remote, tmp_path):
    r = sh(["git", "--git-dir", str(remote), "ls-tree", "-r", "--name-only", "paper-ledger"], tmp_path)
    return r.stdout.split()


def branch_commits(remote, tmp_path):
    return len(sh(["git", "--git-dir", str(remote), "log", "--oneline", "paper-ledger"], tmp_path).stdout.split("\n")) - 1


def test_the_first_publish_creates_the_branch_and_the_second_adds_a_commit_without_touching_the_checkout(tmp_path, remote):
    checkout = tmp_path / "checkout"
    sh(["git", "clone", "-q", str(remote), str(checkout)], tmp_path)
    (checkout / "quantdesk.txt").write_text("the code the verify step needs\n")                 # stands in for quantdesk/: untracked, as the work in a runner is
    for day, n in ((1, 3), (2, 5)):
        f = run_script("fetch", tmp_path, remote)
        assert f.returncode == 0, f.stderr
        assert (tmp_path / "work" / ".git").exists() and not (checkout / ".paper-ledger").exists()
        p = run_script("push", tmp_path, remote, account=acct(tmp_path, f"a{day}.json", n))
        assert p.returncode == 0, p.stderr
        assert (checkout / "README").exists() and (checkout / "quantdesk.txt").exists()          # the repository checkout still has its files after every publish
    assert branch_files(remote, tmp_path) == ["account.json"] and branch_commits(remote, tmp_path) == 2
    assert json.loads(sh(["git", "--git-dir", str(remote), "show", "paper-ledger:account.json"], tmp_path).stdout)["ledger"] == [0, 1, 2, 3, 4]


def test_nothing_new_is_not_a_commit(tmp_path, remote):
    f = acct(tmp_path, "a.json", 3)
    for _ in range(2):
        assert run_script("fetch", tmp_path, remote).returncode == 0
        assert run_script("push", tmp_path, remote, account=f).returncode == 0
    assert branch_commits(remote, tmp_path) == 1


def test_a_branch_that_exists_but_cannot_be_fetched_is_never_created_again(tmp_path, remote):
    assert run_script("fetch", tmp_path, remote).returncode == 0
    assert run_script("push", tmp_path, remote, account=acct(tmp_path, "a.json", 3)).returncode == 0
    shim = tmp_path / "bin"
    shim.mkdir()
    real = shutil.which("git")
    g = shim / "git"
    g.write_text(f'#!/usr/bin/env bash\nfor a in "$@"; do if [ "$a" = fetch ]; then echo "simulated network failure" >&2; exit 128; fi; done\nexec {real} "$@"\n')
    g.chmod(g.stat().st_mode | stat.S_IEXEC)
    r = run_script("fetch", tmp_path, remote, path=f"{shim}:{os.environ['PATH']}")
    assert r.returncode == 1 and "could not be fetched" in r.stderr                              # it stops; it does not start an orphan branch that would be refused or, worse, replace history
    assert branch_commits(remote, tmp_path) == 1


def test_a_missing_account_or_directory_or_mode_is_an_error(tmp_path, remote):
    assert run_script("push", tmp_path, remote).returncode != 0
    assert run_script("nonsense", tmp_path, remote).returncode == 2
    r = sh(["bash", str(SCRIPT), "fetch"], tmp_path, env={"LEDGER_REMOTE": str(remote)}, ok=False)
    assert r.returncode != 0 and "LEDGER_WORK" in r.stderr


def test_the_token_is_masked_and_never_printed_or_written_to_config(tmp_path, remote):
    secret = "ghs_SECRETTOKENVALUE0123456789"
    r = run_script("fetch", tmp_path, remote, extra_env={"GH_TOKEN": secret})
    assert r.returncode == 0 and secret not in r.stdout + r.stderr and "::add-mask::" in r.stdout
    assert secret not in (tmp_path / "work" / ".git" / "config").read_text()
