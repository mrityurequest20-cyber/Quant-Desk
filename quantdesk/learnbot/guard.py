"""`learnbot check-diff`: the guard every learnbot/ pull request has to pass (docs/LEARNBOT.md).

A research pull request from the learning bot may only ADD documents of three kinds: a new pre-registered spec, a dated
report, a note for the next run. Everything else is refused, so the bot cannot change code, configuration, a risk limit, a
workflow, a locked result or an existing file. The rule is an allow-list on purpose: a path nobody thought of is refused,
not waved through.

It judges only branches named learnbot/ (any case). It cannot make the bot use that name and it cannot stop a merge: the
routine's prompt, its token and main's ruleset do that (docs/LEARNBOT.md, "What the guard cannot do").

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
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

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
# `sleeves.specs()` loads every docs/prereg/expiry_seller_*.json as a paper sleeve with its own legs and sizes: that is an
# engineer pull request with a risk-compliance review, never a learnbot/ one
SLEEVE_SPEC = re.compile(r"docs/prereg/expiry_seller_.*\.json")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_DEPTH = 32                                     # real specs are a handful of levels deep; the memory recurses over them
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
# the generic shapes (sk-..., and key/secret/token = value) require three digits in the value: a random key has several, a
# hyphenated name like "..._v1_audit_spec" has one, so ordinary prose is not refused. A heuristic, not a vault.
SECRET = re.compile("|".join((
    r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"\bsk-(?:ant-|proj-)?(?=(?:[A-Za-z0-9_-]*\d){3})[A-Za-z0-9_-]{16,}", r"AKIA[0-9A-Z]{16}", r"(?i:aws_secret_access_key)\s*[:=]\s*[\"']?[A-Za-z0-9/+=]{30,}",
    r"AIza[0-9A-Za-z_-]{30,}", r"xox[baprs]-[A-Za-z0-9-]{10,}", r"hooks\.slack\.com/services/[A-Za-z0-9/]+",
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i:bearer)\s+[A-Za-z0-9._~+/=-]{20,}", r"://[^/\s:@]+:[^/\s@]{3,}@",
    r"(?i:api[_-]?key|secret|token|passwd|password|consumer[_-]?key|access[_-]?key|authorization)[\w\"']{0,20}\s*[:=]\s*"
    r"[\"']?(?=(?:[A-Za-z0-9/+_=.\-]*\d){3})[A-Za-z0-9/+_=.\-]{20,}")))
MONTHLY = re.compile(r"^docs/reports/(\d{4}-\d{2}-\d{2})_learnbot_monthly\.md$")
# the monthly report's required sections (docs/LEARNBOT.md); the quarter-month run adds the independent review
REPORT_SECTIONS = ("Milestones", "Models", "Data health", "Paper record", "Usage", "NEEDS OWNER")
REVIEW_SECTION = "Independent review"
REVIEW_MONTHS = (1, 4, 7, 10)
MIN_SECTION_CHARS = 8                              # "none" is enough; an empty heading is not


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


def _sections(text: str) -> dict[str, str]:
    """{heading (lower case): the text under it, up to the next heading of any level}."""
    parts = re.split(r"^#{1,3}\s+(.+?)\s*$", text, flags=re.M)
    return {parts[i].strip().lower(): parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def _report_problems(path: str, text: str) -> list[str]:
    m = MONTHLY.match(path)
    if not m:
        return []
    sections = _sections(text)
    need = list(REPORT_SECTIONS)
    try:
        if dt.date.fromisoformat(m.group(1)).month in REVIEW_MONTHS:
            need.append(REVIEW_SECTION)
    except ValueError:
        return [f"{ascii(path)}: the date in the file name is not a real date"]
    out = []
    for n in need:
        body = sections.get(n.lower())
        if body is None:
            out.append(f"{ascii(path)}: the monthly report has no '{n}' section")
        elif len(body.strip()) < MIN_SECTION_CHARS:
            out.append(f"{ascii(path)}: the '{n}' section is empty (under {MIN_SECTION_CHARS} characters)")
    return out


def _walk(o, depth: int = 0):
    """Every (depth, string) in a decoded JSON value, keys included; stops descending past MAX_DEPTH."""
    if isinstance(o, str):
        yield depth, o
    elif depth <= MAX_DEPTH and isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(k, depth + 1)
            yield from _walk(v, depth + 1)
    elif depth <= MAX_DEPTH and isinstance(o, list):
        for v in o:
            yield from _walk(v, depth + 1)


def _depth(o, d: int = 1) -> int:
    """Nesting depth, capped: anything beyond MAX_DEPTH is reported as MAX_DEPTH + 1 without walking further."""
    if d > MAX_DEPTH:
        return d
    kids = list(o.values()) if isinstance(o, dict) else o if isinstance(o, list) else []
    return max([d] + [_depth(k, d + 1) for k in kids if isinstance(k, (dict, list))])


def _spec_problems(path: str, data) -> list[str]:
    """Every docs/prereg/*.json is loaded by the research memory (and some by the sleeves), so its shape is checked here:
    a spec that parses but is not a mapping, has no name or date, nests deeper than the memory can recurse, or holds a string
    that cannot be encoded would break the desk's own jobs."""
    if not isinstance(data, dict):
        return [f"{ascii(path)}: a spec must be a JSON object"]
    out = []
    if data.get("name") != PurePosixPath(path).stem:
        out.append(f"{ascii(path)}: the spec's \"name\" must equal the file name without .json")
    if not (isinstance(data.get("registered"), str) and ISO_DATE.fullmatch(data["registered"])):
        out.append(f"{ascii(path)}: the spec needs \"registered\": \"YYYY-MM-DD\"")
    if _depth(data) > MAX_DEPTH:
        out.append(f"{ascii(path)}: nested more than {MAX_DEPTH} levels deep")
    else:
        for _, text in _walk(data):
            try:
                text.encode("utf-8")
            except UnicodeEncodeError:
                out.append(f"{ascii(path)}: a string in the spec is not valid text (a lone surrogate)")
                break
    return out


def _secret_in(text: str) -> bool:
    """The patterns run on the text as written, normalised (NFKC, zero-width characters dropped), and on every string a JSON
    file decodes to, so an escape or a hidden character does not hide a key."""
    def norm(t: str) -> str:
        return "".join(c for c in unicodedata.normalize("NFKC", t) if unicodedata.category(c) != "Cf")

    def strings(o, depth=0):
        if isinstance(o, str):
            yield o
        elif depth <= MAX_DEPTH and isinstance(o, dict):
            for k, v in o.items():
                yield from strings(k, depth + 1)
                yield from strings(v, depth + 1)
                if isinstance(v, str):
                    yield f"{k}: {v}"                      # a key and its value together, as a person would write them
        elif depth <= MAX_DEPTH and isinstance(o, list):
            for v in o:
                yield from strings(v, depth + 1)
    texts = [norm(text)]
    try:
        texts += [norm(x) for x in strings(json.loads(text))]
    except (ValueError, RecursionError):
        pass
    return any(SECRET.search(t) for t in texts)


def check_diff(base: str, head: str = "HEAD", branch: str | None = None, repo: Path = ROOT) -> Result:
    """Judge `head` against `base` (the pull request's merge-base diff). `branch` is the pull request's branch name; a
    branch that does not start with learnbot/ is not the learning bot's and is not judged here."""
    guessed = not branch
    try:
        branch = branch or _git(repo, "rev-parse", "--abbrev-ref", head).decode().strip()
    except subprocess.CalledProcessError:
        branch = ""
    res = Result(branch=branch)
    if guessed and branch in ("", "HEAD"):
        # a detached head, or a ref that does not exist: "not a learnbot branch" would pass a bad diff, so refuse to guess
        res.problems.append("could not tell which branch this is (detached head or unknown ref): pass --branch")
        return res
    if not branch.lower().startswith(BRANCH_PREFIX):
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
        kind = next((k for rx, k in ALLOWED if rx.fullmatch(path)), None)
        if ".." in Path(path).parts or path.startswith("/"):
            why = "not a plain repository path"
        elif SLEEVE_SPEC.fullmatch(path):
            why = "a sleeve spec starts a paper sleeve with its own legs and sizes: an engineer pull request, reviewed by risk-compliance"
        elif kind is None:
            why = _refused_because(path)
        elif r["status"] != "A":
            why = f"only new files may be added; this one is {'modified' if r['status'] == 'M' else 'deleted or retyped'}"
        elif r["mode"] != "100644":
            why = "a symlink, an executable or a submodule"
        if why:
            res.problems.append(f"{ascii(path)}: refused: {why}")
            continue
        res.files.append({"path": path, "kind": kind})
        try:
            raw = _git(repo, "show", f"{head}:{path}")
        except subprocess.CalledProcessError:
            res.problems.append(f"{ascii(path)}: could not be read from {head}")
            continue
        if len(raw) > MAX_BYTES:
            res.problems.append(f"{ascii(path)}: {len(raw):,} bytes; the limit is {MAX_BYTES:,}")
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            res.problems.append(f"{ascii(path)}: not UTF-8 text")
            continue
        if "\0" in text:
            res.problems.append(f"{ascii(path)}: binary content")
        if _secret_in(text):
            res.problems.append(f"{ascii(path)}: looks like it contains a secret (the match is not printed)")
        if path.endswith(".json"):
            try:
                data = json.loads(text)
            except (ValueError, RecursionError) as exc:
                res.problems.append(f"{ascii(path)}: not valid JSON (or nested too deeply): {type(exc).__name__}")
            else:
                if path.startswith("docs/prereg/"):
                    res.problems += _spec_problems(path, data)
        res.problems += _report_problems(path, text)
    return res


def render(res: Result) -> str:
    if res.skipped:
        return f"learnbot check-diff: '{res.branch or '(no branch)'}' is not a {BRANCH_PREFIX} branch; nothing to judge"
    head = f"learnbot check-diff: {res.branch}: " + ("PASS" if res.ok else "FAIL")
    lines = [head] + [f"  + {ascii(f['path'])} ({f['kind']})" for f in res.files] + [f"  ! {p}" for p in res.problems]
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
