"""`learnbot check-diff`: the guard every learnbot/ pull request has to pass (docs/LEARNBOT.md).

A research pull request from the learning bot may only ADD documents of three kinds: a new pre-registered spec, a dated
report, a note for the next run. Everything else is refused, so the bot cannot change code, configuration, a risk limit, a
workflow, a locked result or an existing file however its session goes. The rule is an allow-list on purpose: a path nobody
thought of is refused, not waved through.

The check reads git objects only. It never imports, runs or evaluates anything from the branch it is judging, and in CI it
runs from the BASE branch's code (see .github/workflows/learnbot-guard.yml), so a pull request cannot weaken the guard that
judges it.

Exit status: 0 = pass (or: not a learnbot/ branch, nothing to judge); 1 = at least one problem.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRANCH_PREFIX = "learnbot/"
MAX_FILES = 12
MAX_BYTES = 200_000
# what a learnbot/ pull request may ADD (nothing may be modified, renamed, deleted, or be a symlink or executable)
ALLOWED = (
    (re.compile(r"^docs/prereg/[a-z0-9_]+\.json$"), "a new pre-registered spec"),
    (re.compile(r"^docs/reports/\d{4}-\d{2}-\d{2}_[a-z0-9_]+\.(md|json)$"), "a dated report"),
    (re.compile(r"^docs/learnbot/[A-Za-z0-9_.-]+\.md$"), "a note for the next learning run"),
)
# why a path outside the allow-list is refused (the first matching prefix is quoted; any other path gets the default)
REFUSED_BECAUSE = (
    (".github/", "workflows, permissions and secrets are the owner's"),
    ("quantdesk/", "code changes go on an engineer branch with an independent reviewer, not a learnbot/ branch"),
    ("tests/", "tests belong with the code they test, on an engineer branch"),
    ("config/", "configuration (risk limits, modes, gates) is never the learning bot's to change"),
    ("deploy/", "deployment files are the owner's"),
    ("runtime/", "runtime data is never committed from a learnbot/ branch"),
    ("docs/prereg/results/", "recorded results are locked"),
    ("docs/AUTONOMY.md", "the autonomy rules are the owner's"),
    ("docs/LEARNBOT.md", "the learning bot's own rules are the owner's"),
    ("docs/principles.json", "a principle moves up the ladder on a registered result, in an engineer pull request"),
)
SECRET = re.compile(
    r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[ousr]_[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{16}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|(?i:api[_-]?key|secret|token|passwd|password)[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9/+_=-]{24,}")
MONTHLY = re.compile(r"^docs/reports/(\d{4}-\d{2}-\d{2})_learnbot_monthly\.md$")
# the monthly report's required sections (docs/LEARNBOT.md); the quarter-month run adds the independent review
REPORT_SECTIONS = ("Milestones", "Models", "Data health", "Paper record", "Usage", "NEEDS OWNER")
REVIEW_SECTION = "Independent review"
REVIEW_MONTHS = (1, 4, 7, 10)


@dataclass
class Result:
    branch: str
    skipped: bool = False
    files: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True).stdout


def _refused_because(path: str) -> str:
    for prefix, why in REFUSED_BECAUSE:
        if path.startswith(prefix):
            return why
    return "a learnbot/ pull request may only add a new spec, a dated report or a learning note"


def _changes(repo: Path, base: str, head: str) -> list[dict]:
    """Every path the head changes against the merge base, with git's own status and file modes."""
    out = _git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", f"{base}...{head}").split(b"\0")
    rows, i = [], 0
    while i < len(out) and out[i]:
        meta = out[i].decode().lstrip(":").split()
        rows.append({"status": meta[4][:1], "mode": meta[1], "path": out[i + 1].decode("utf-8", "replace")})
        i += 2
    return rows


def _report_problems(path: str, text: str) -> list[str]:
    m = MONTHLY.match(path)
    if not m:
        return []
    headings = {h.strip().lower() for h in re.findall(r"^#{1,3}\s+(.+?)\s*$", text, flags=re.M)}
    need = list(REPORT_SECTIONS)
    if dt.date.fromisoformat(m.group(1)).month in REVIEW_MONTHS:
        need.append(REVIEW_SECTION)
    return [f"{path}: the monthly report has no '{n}' section" for n in need if n.lower() not in headings]


def check_diff(base: str, head: str = "HEAD", branch: str | None = None, repo: Path = ROOT) -> Result:
    """Judge `head` against `base` (the pull request's merge-base diff). `branch` is the pull request's branch name; a
    branch that does not start with learnbot/ is not the learning bot's and is not judged here."""
    try:
        branch = branch or _git(repo, "rev-parse", "--abbrev-ref", head).decode().strip()
    except subprocess.CalledProcessError:
        branch = ""
    res = Result(branch=branch)
    if not branch.startswith(BRANCH_PREFIX):
        res.skipped = True
        return res
    try:
        rows = _changes(repo, base, head)
    except (subprocess.CalledProcessError, IndexError, ValueError) as exc:
        res.problems.append(f"could not read the diff of {head} against {base}: {exc}")
        return res
    if not rows:
        res.problems.append("the diff is empty")
    if len(rows) > MAX_FILES:
        res.problems.append(f"{len(rows)} files changed; a learnbot/ pull request is at most {MAX_FILES}")
    for r in rows:
        path, why = r["path"], None
        kind = next((k for rx, k in ALLOWED if rx.match(path)), None)
        if ".." in Path(path).parts or path.startswith("/"):
            why = "not a plain repository path"
        elif kind is None:
            why = _refused_because(path)
        elif r["status"] != "A":
            why = f"only new files may be added; this one is {'modified' if r['status'] == 'M' else 'deleted or retyped'}"
        elif r["mode"] != "100644":
            why = "a symlink, an executable or a submodule"
        if why:
            res.problems.append(f"{path}: refused: {why}")
            continue
        res.files.append({"path": path, "kind": kind})
        try:
            raw = _git(repo, "show", f"{head}:{path}")
        except subprocess.CalledProcessError:
            res.problems.append(f"{path}: could not be read from {head}")
            continue
        if len(raw) > MAX_BYTES:
            res.problems.append(f"{path}: {len(raw):,} bytes; the limit is {MAX_BYTES:,}")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            res.problems.append(f"{path}: not UTF-8 text")
            continue
        if "\0" in text:
            res.problems.append(f"{path}: binary content")
        if SECRET.search(text):
            res.problems.append(f"{path}: looks like it contains a secret (the match is not printed)")
        if path.endswith(".json"):
            try:
                json.loads(text)
            except ValueError as exc:
                res.problems.append(f"{path}: not valid JSON: {exc}")
        res.problems += _report_problems(path, text)
    return res


def render(res: Result) -> str:
    if res.skipped:
        return f"learnbot check-diff: '{res.branch or '(no branch)'}' is not a {BRANCH_PREFIX} branch; nothing to judge"
    head = f"learnbot check-diff: {res.branch}: " + ("PASS" if res.ok else "FAIL")
    lines = [head] + [f"  + {f['path']} ({f['kind']})" for f in res.files] + [f"  ! {p}" for p in res.problems]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """`python -m quantdesk.learnbot.guard`: the same check with the standard library only (the CI guard uses it)."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--branch")
    a = ap.parse_args(argv)
    res = check_diff(a.base, a.head, a.branch)
    print(render(res))
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
