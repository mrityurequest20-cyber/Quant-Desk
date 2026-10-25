"""The model card (P0.5 of docs/ML_PHASE0.md; the format is docs/ml/MODEL_CARD_TEMPLATE.md).

A card is the provenance record of one model run: which spec, which code, which data, trained up to which date, with which settings, after how many
variants, against which baseline, with what out-of-sample result and interval, after which leakage tests, and in which status. `build_card` returns the
card or **refuses**, naming every required field that is missing or inconsistent; a run without provenance has no card and so no status. Pure functions
over plain dicts; nothing here reads the journal, the engine or any broker, and nothing here can set a model live.

Status (docs/ML_ROADMAP.md rules 3 to 6): `offline` -> `shadow` is a recorded step; `shadow` -> `applied` needs the owner's switch recorded on the card
(`owner_apply`) and is refused without it; `applied` -> `shadow` (demotion) and anything -> `offline` need no approval, because they only tighten.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from datetime import date
from pathlib import Path

CARD_VERSION = 1
STATUSES = ("offline", "shadow", "applied")
REQUIRED = ("model_id", "version", "spec", "code_commit", "data", "training_window", "settings", "variants_tried", "baseline", "oos", "leakage_tests", "status")
OPTIONAL = ("shadow_sessions_graded", "rolling_score", "weaknesses", "demotion_rule", "last_demotion_check", "owner_apply", "registry_ref")
DATA_STATUSES = ("external_unverified", "external_verified", "verified")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{16,64}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_TIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class MissingProvenance(ValueError):
    """The run record lacks something a card requires. `problems` lists every one, so the run can be fixed in one pass."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("no model card: " + "; ".join(problems))


def _finite(x) -> bool:
    try:
        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    except OverflowError:                                                           # an int too large for a float is not a usable number either
        return False


def _int(x, lo: int = 1) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= lo


def _day(x) -> bool:
    if not (isinstance(x, str) and _DAY.fullmatch(x)):
        return False
    try:
        date.fromisoformat(x)
    except ValueError:                                                              # 2026-13-45
        return False
    return True


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def check_run(run) -> list[str]:
    """Every reason `run` cannot become a card (empty if none). Format and consistency only: `check_against_repo` is what ties the spec hash and the code
    commit to the repository, and nothing here can know whether a run record was honestly written (the harness that writes them, P0.8, is what must)."""
    if not isinstance(run, dict):
        return ["the run record must be a JSON object"]
    p: list[str] = []
    for k in REQUIRED:
        if k not in run or run[k] in (None, "", [], {}):
            p.append(f"missing required field: {k}")
    if p:
        return p                                                                    # the checks below assume the fields are there
    if not (isinstance(run["model_id"], str) and _ID.fullmatch(run["model_id"])):
        p.append("model_id must be 1 to 64 characters of letters, digits, _ . -")
    if not (isinstance(run["version"], str) and _ID.fullmatch(run["version"])):
        p.append("version must be letters, digits, '_', '-' or '.', starting with a letter or digit, up to 64 characters (it is part of the file name)")
    spec = run["spec"]
    if not (isinstance(spec, dict) and isinstance(spec.get("file"), str) and spec["file"].strip() and isinstance(spec.get("sha256"), str)
            and _HEX64.fullmatch(spec["sha256"])):
        p.append("spec needs a file and a 64-hex sha256")
    if not (isinstance(run["code_commit"], str) and _HEX40.fullmatch(run["code_commit"])):
        p.append("code_commit must be a full 40-hex commit (not a branch, a short hash or 'dirty')")
    data = run["data"]
    if not isinstance(data, dict) or not data:
        p.append("data needs at least one tier")
    else:
        for tier, d in data.items():
            if not (isinstance(tier, str) and _TIER.fullmatch(tier)):
                p.append(f"data tier name {tier!r} must be letters, digits, _ . - (T1, T1b, T2 ...)")
            if not (isinstance(d, dict) and isinstance(d.get("manifest"), str) and d["manifest"].strip() and isinstance(d.get("digest"), str)
                    and _DIGEST.fullmatch(d["digest"]) and d.get("status") in DATA_STATUSES):
                p.append(f"data tier {tier}: a manifest name, a hex digest (16 to 64 characters) and a status in {DATA_STATUSES} are required")
    w = run["training_window"]
    if not (isinstance(w, dict) and all(_day(w.get(k)) for k in ("start", "end", "cutoff"))):
        p.append("training_window needs start, end and cutoff as real YYYY-MM-DD dates")
    elif not (w["start"] <= w["end"] <= w["cutoff"]):
        p.append("training_window must satisfy start <= end <= cutoff (nothing after the cut-off may be trained on, and grading starts after it)")
    s = run["settings"]
    if not (isinstance(s, dict) and "params" in s and _int(s.get("seed"), lo=-(2**63))):
        p.append("settings needs params and an integer seed")
    else:
        try:
            _canon(s["params"])
        except (ValueError, TypeError, OverflowError):
            p.append("settings.params must be plain JSON with finite numbers")
    if not _int(run["variants_tried"]):
        p.append("variants_tried must be an integer >= 1 (the number of variants tried in total, this one included)")
    b = run["baseline"]
    if not (isinstance(b, dict) and isinstance(b.get("name"), str) and b["name"].strip() and isinstance(b.get("version"), (str, int)) and str(b["version"]).strip()):
        p.append("baseline needs a name and a version")
    o = run["oos"]
    if not isinstance(o, dict):
        p.append("oos must be an object")
    else:
        need = ("metric", "model", "baseline", "diff", "interval", "interval_level", "interval_method", "n_sessions")
        gaps = [k for k in need if k not in o]
        if gaps:
            p.append("oos is missing: " + ", ".join(gaps))
        else:
            if not (isinstance(o["metric"], str) and o["metric"].strip()):
                p.append("oos.metric must name the metric")
            if not (isinstance(o["interval_method"], str) and o["interval_method"].strip()):
                p.append("oos.interval_method must say how the interval was made")
            if not (_finite(o["interval_level"]) and 0 < o["interval_level"] < 1):
                p.append("oos.interval_level must be a number between 0 and 1 (0.9 for a 90% interval)")
            iv = o["interval"]
            if not (isinstance(iv, (list, tuple)) and len(iv) == 2 and all(_finite(x) for x in iv) and iv[0] <= iv[1]):
                p.append("oos.interval must be [low, high], finite, low <= high")
            elif not (_finite(o["diff"]) and iv[0] <= o["diff"] <= iv[1]):
                p.append("oos.diff must be finite and inside oos.interval")
            if not (_finite(o["model"]) and _finite(o["baseline"])):
                p.append("oos.model and oos.baseline must be finite numbers")
            elif _finite(o["diff"]) and abs(o["diff"] - (o["model"] - o["baseline"])) > 1e-9 * max(1.0, abs(o["model"]), abs(o["baseline"])):
                p.append("oos.diff must equal oos.model - oos.baseline")
            if not _int(o["n_sessions"]):
                p.append("oos.n_sessions must be an integer >= 1 (a session is the unit)")
    lt = run["leakage_tests"]
    if not (isinstance(lt, list) and lt and all(isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip() for x in lt)):
        p.append("leakage_tests must be a list of {name, passed} for the tests that were run")
    else:
        failed = [x["name"] for x in lt if x.get("passed") is not True]
        if failed:
            p.append("leakage tests that did not pass: " + ", ".join(failed))
    if run["status"] not in STATUSES:
        p.append(f"status must be one of {STATUSES}")
    elif run["status"] == "applied" and not _owner_apply_ok(run.get("owner_apply")):
        p.append("status applied needs owner_apply (by, ts and the registered rule): only the owner's switch makes a model applied")
    return p


def check_against_repo(run: dict, root: Path) -> list[str]:
    """What a run record claims about the repository, checked against it: the spec file exists under `root` and hashes to `spec.sha256`, and
    `code_commit` is a commit of the repository. (Whether the tree the run used was clean is for the harness that writes the record.)"""
    p: list[str] = []
    root = Path(root).resolve()
    sp = (root / str(run["spec"]["file"])).resolve()
    if root not in sp.parents or not sp.is_file():
        p.append(f"spec file {run['spec']['file']} is not a file inside the repository")
    elif hashlib.sha256(sp.read_bytes()).hexdigest() != run["spec"]["sha256"]:
        p.append(f"spec file {run['spec']['file']} does not hash to spec.sha256 (the spec the run names is not the file in the repository)")
    try:
        ok = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{run['code_commit']}^{{commit}}"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        p.append(f"code_commit {run['code_commit'][:12]} is not a commit of this repository")
    return p


def _owner_apply_ok(x) -> bool:
    return isinstance(x, dict) and all(str(x.get(k, "")).strip() for k in ("by", "ts", "rule"))


def build_card(run: dict) -> dict:
    """The card for a run, with its digest, or `MissingProvenance` naming everything wrong with the run."""
    problems = check_run(run)
    if problems:
        raise MissingProvenance(problems)
    card = {"card_version": CARD_VERSION, **{k: run[k] for k in REQUIRED}, **{k: run[k] for k in OPTIONAL if k in run}}
    card["digest"] = hashlib.sha256(_canon({k: v for k, v in card.items() if k != "digest"}).encode()).hexdigest()
    return card


def verify_card(card: dict) -> list[str]:
    """Problems with a stored card: it no longer builds, or its digest is not the digest of its content."""
    if not isinstance(card, dict):
        return ["a card must be a JSON object"]
    run = {k: v for k, v in card.items() if k not in ("card_version", "digest")}
    p = check_run(run)
    try:
        body = _canon({k: v for k, v in card.items() if k != "digest"})
    except (ValueError, TypeError, OverflowError):
        return p + ["the card holds content that is not plain JSON with finite numbers"]
    if card.get("digest") != hashlib.sha256(body.encode()).hexdigest():
        p.append("digest does not match the card's content (edited after it was built)")
    return p


_ROWS = (("Model id and version", lambda c: f"{c['model_id']} v{c['version']}"),
         ("Spec (file and sha256)", lambda c: f"{c['spec']['file']} `{c['spec']['sha256']}`"),
         ("Code commit", lambda c: f"`{c['code_commit']}`"),
         ("Data manifests and digests, by tier", lambda c: "; ".join(f"{t}: {d['manifest']} `{d['digest']}` ({d['status']})" for t, d in sorted(c["data"].items()))),
         ("Training window and cut-off date", lambda c: f"{c['training_window']['start']} to {c['training_window']['end']}, cut-off {c['training_window']['cutoff']}"),
         ("Settings and random seed", lambda c: f"seed {c['settings']['seed']}; {_canon(c['settings']['params'])}"),
         ("Variants tried in total", lambda c: str(c["variants_tried"])),
         ("Baseline and its version", lambda c: f"{c['baseline']['name']} {c['baseline']['version']}"),
         ("Out-of-sample result vs baseline, with the interval", lambda c: (
             f"{c['oos']['metric']}: model {c['oos']['model']:.6g}, baseline {c['oos']['baseline']:.6g}, difference {c['oos']['diff']:+.6g}, "
             f"{c['oos']['interval_level']:.0%} interval [{c['oos']['interval'][0]:+.6g}, {c['oos']['interval'][1]:+.6g}] ({c['oos']['interval_method']}), "
             f"{c['oos']['n_sessions']} sessions")),
         ("Leakage tests passed", lambda c: ", ".join(x["name"] for x in c["leakage_tests"])),
         ("Status", lambda c: c["status"]))


def render_markdown(card: dict) -> str:
    """The card in the template's layout (docs/ml/MODEL_CARD_TEMPLATE.md), optional rows only when present."""
    rows = [(k, f(card)) for k, f in _ROWS]
    for key, label in (("shadow_sessions_graded", "Shadow sessions graded so far"), ("rolling_score", "Rolling score"), ("weaknesses", "Known weaknesses and where it fails"),
                       ("demotion_rule", "Demotion rule"), ("last_demotion_check", "Last demotion check"), ("registry_ref", "Registry entry")):
        if card.get(key) not in (None, ""):
            rows.append((label, str(card[key]) if not isinstance(card[key], (dict, list)) else _canon(card[key])))
    if card.get("owner_apply"):
        rows.append(("Owner's apply switch", f"{card['owner_apply']['by']}, {card['owner_apply']['ts']}, rule: {card['owner_apply']['rule']}"))
    body = "\n".join(f"| {k} | {' '.join(str(v).replace('|', '/').split())} |" for k, v in rows)
    return f"# Model card: {card['model_id']} v{card['version']}\n\n| Field | Value |\n|---|---|\n{body}\n\nCard digest `{card['digest']}`.\n"


def write_card(folder: Path, card: dict) -> tuple[Path, Path]:
    """Write `<model_id>-<version>.card.json` and `.card.md` once. The same card again is a no-op; a different card for the same id and version raises
    (a new version is a new card), and a card that fails `verify_card` is not written."""
    problems = verify_card(card)
    if problems:
        raise MissingProvenance(problems)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{card['model_id']}-{card['version']}.card"
    jp, mp = folder / f"{stem}.json", folder / f"{stem}.md"
    text = json.dumps(card, indent=1, sort_keys=True) + "\n"
    md = render_markdown(card)
    if jp.exists():
        if jp.read_text() != text:
            raise FileExistsError(f"{jp.name} already exists with different content: a changed model is a new version, not an edited card")
        if not mp.exists() or mp.read_text() != md:                # the .md is derived from the card, so it is repaired, never trusted
            mp.write_text(md)
        return jp, mp
    mp.write_text(md)                                              # the .json is the commit marker: written last, so an interrupted write is redone, not half-kept
    try:
        with open(jp, "x") as f:                                   # exclusive: two writers of one id and version cannot both succeed
            f.write(text)
    except FileExistsError:
        if jp.read_text() != text:
            raise
    return jp, mp


def can_transition(old: str, new: str, owner_apply: dict | None = None) -> tuple[bool, str]:
    """Whether a status change is allowed. Only the owner's switch makes a model applied; only tightening is automatic."""
    if old not in STATUSES or new not in STATUSES:
        return False, f"unknown status ({old} -> {new})"
    if old == new:
        return True, "no change"
    if new == "applied":
        if old != "shadow":
            return False, "a model reaches applied only from shadow"
        return (True, "owner's switch recorded") if _owner_apply_ok(owner_apply) else (False, "applied needs the owner's switch (by, ts, rule)")
    return True, "tightening (to shadow or offline) needs no approval"


def rolling_grade(outcomes: list[dict], window: int = 60) -> dict:
    """The model's score against its baseline over the last `window` graded predictions, which the caller passes oldest first (the order is the
    caller's: this function does not sort). Each outcome has `loss` and `baseline_loss` (lower is better) and may name its `session`. `gain` > 0 means
    the model beat its baseline. A non-finite loss is counted (`dropped_non_finite`, within the same window) and left out of the means, never repaired."""
    if window < 1:
        raise ValueError("window must be >= 1")
    recent = list(outcomes)[-window:]
    ok = [o for o in recent if _finite(o.get("loss")) and _finite(o.get("baseline_loss"))]
    n = len(ok)
    out = {"n": n, "window": window, "dropped_non_finite": len(recent) - n, "sessions": len({o["session"] for o in ok}) if all("session" in o for o in ok) and ok else None,
           "mean_loss": None, "mean_baseline_loss": None, "gain": None}
    if n:
        out["mean_loss"] = sum(o["loss"] for o in ok) / n
        out["mean_baseline_loss"] = sum(o["baseline_loss"] for o in ok) / n
        out["gain"] = out["mean_baseline_loss"] - out["mean_loss"]
    return out


def should_demote(grade: dict, min_n: int = 30, max_bad_share: float = 0.2, min_sessions: int = 5) -> bool:
    """ROADMAP rule 6: an applied model whose rolling score falls below its baseline drops back to shadow by itself. A model whose predictions
    come out non-finite is not working: with `min_n` graded predictions of which `max_bad_share` or more are non-finite it is demoted too. Below
    `min_n` there is no verdict (False); and where the outcomes name their sessions, fewer than `min_sessions` distinct sessions is no verdict either
    (a session is the unit; one busy day is not 30 observations). Demotion only tightens, so it needs no approval."""
    bad, n = grade["dropped_non_finite"], grade["n"]
    if n + bad >= min_n and bad / (n + bad) >= max_bad_share:
        return True
    sessions = grade.get("sessions")
    if sessions is not None and sessions < min_sessions:
        return False
    return bool(n >= min_n and grade["gain"] is not None and grade["gain"] < 0)
