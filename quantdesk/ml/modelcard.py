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
from pathlib import Path

CARD_VERSION = 1
STATUSES = ("offline", "shadow", "applied")
REQUIRED = ("model_id", "version", "spec", "code_commit", "data", "training_window", "settings", "variants_tried", "baseline", "oos", "leakage_tests", "status")
OPTIONAL = ("shadow_sessions_graded", "rolling_score", "weaknesses", "demotion_rule", "last_demotion_check", "owner_apply", "registry_ref")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class MissingProvenance(ValueError):
    """The run record lacks something a card requires. `problems` lists every one, so the run can be fixed in one pass."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("no model card: " + "; ".join(problems))


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def check_run(run: dict) -> list[str]:
    """Every reason `run` cannot become a card (empty if none)."""
    p: list[str] = []
    for k in REQUIRED:
        if k not in run or run[k] in (None, "", [], {}):
            p.append(f"missing required field: {k}")
    if p:
        return p                                                                    # the checks below assume the fields are there
    if not _ID.match(str(run["model_id"])):
        p.append("model_id must be 1 to 64 characters of letters, digits, _ . -")
    if not str(run["version"]).strip():
        p.append("version is empty")
    spec = run["spec"]
    if not (isinstance(spec, dict) and spec.get("file") and _HEX64.match(str(spec.get("sha256", "")))):
        p.append("spec needs a file and a 64-hex sha256")
    if not _HEX40.match(str(run["code_commit"])):
        p.append("code_commit must be a full 40-hex commit (not a branch, a short hash or 'dirty')")
    data = run["data"]
    if not isinstance(data, dict) or not data:
        p.append("data needs at least one tier")
    else:
        for tier, d in data.items():
            if not (isinstance(d, dict) and d.get("manifest") and d.get("digest") and d.get("status")):
                p.append(f"data tier {tier}: manifest, digest and status (verified or external_unverified) are required")
    w = run["training_window"]
    if not (isinstance(w, dict) and all(_DAY.match(str(w.get(k, ""))) for k in ("start", "end", "cutoff"))):
        p.append("training_window needs start, end and cutoff as YYYY-MM-DD")
    elif not (w["start"] <= w["end"] <= w["cutoff"]):
        p.append("training_window must satisfy start <= end <= cutoff (nothing after the cut-off may be trained on, and grading starts after it)")
    s = run["settings"]
    if not (isinstance(s, dict) and "seed" in s and "params" in s):
        p.append("settings needs params and seed")
    if not (isinstance(run["variants_tried"], int) and not isinstance(run["variants_tried"], bool) and run["variants_tried"] >= 1):
        p.append("variants_tried must be an integer >= 1 (the number of variants tried in total, this one included)")
    b = run["baseline"]
    if not (isinstance(b, dict) and b.get("name") and b.get("version")):
        p.append("baseline needs a name and a version")
    o = run["oos"]
    if not isinstance(o, dict):
        p.append("oos must be an object")
    else:
        need = ("metric", "model", "baseline", "diff", "interval", "n_sessions")
        gaps = [k for k in need if k not in o]
        if gaps:
            p.append("oos is missing: " + ", ".join(gaps))
        else:
            iv = o["interval"]
            if not (isinstance(iv, (list, tuple)) and len(iv) == 2 and all(_finite(x) for x in iv) and iv[0] <= iv[1]):
                p.append("oos.interval must be [low, high], finite, low <= high")
            elif not (_finite(o["diff"]) and iv[0] <= o["diff"] <= iv[1]):
                p.append("oos.diff must be finite and inside oos.interval")
            if not (_finite(o["model"]) and _finite(o["baseline"])):
                p.append("oos.model and oos.baseline must be finite numbers")
            if not (isinstance(o["n_sessions"], int) and o["n_sessions"] >= 1):
                p.append("oos.n_sessions must be an integer >= 1 (a session is the unit)")
    lt = run["leakage_tests"]
    if not (isinstance(lt, list) and lt and all(isinstance(x, str) and x.strip() for x in lt)):
        p.append("leakage_tests must list the tests that passed")
    if run["status"] not in STATUSES:
        p.append(f"status must be one of {STATUSES}")
    elif run["status"] == "applied" and not _owner_apply_ok(run.get("owner_apply")):
        p.append("status applied needs owner_apply (by, ts and the registered rule): only the owner's switch makes a model applied")
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
    run = {k: v for k, v in card.items() if k not in ("card_version", "digest")}
    p = check_run(run)
    body = _canon({k: v for k, v in card.items() if k != "digest"})
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
             f"interval [{c['oos']['interval'][0]:+.6g}, {c['oos']['interval'][1]:+.6g}], {c['oos']['n_sessions']} sessions")),
         ("Leakage tests passed", lambda c: ", ".join(c["leakage_tests"])),
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
    body = "\n".join(f"| {k} | {str(v).replace('|', '/')} |" for k, v in rows)
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
    if jp.exists():
        if jp.read_text() != text:
            raise FileExistsError(f"{jp.name} already exists with different content: a changed model is a new version, not an edited card")
        return jp, mp
    jp.write_text(text)
    mp.write_text(render_markdown(card))
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
    """The model's score against its baseline over the last `window` graded predictions. Each outcome has `loss` and `baseline_loss` (lower is better).
    `gain` > 0 means the model beat its baseline; a non-finite loss is counted and left out, never repaired."""
    if window < 1:
        raise ValueError("window must be >= 1")
    ok = [o for o in outcomes if _finite(o.get("loss")) and _finite(o.get("baseline_loss"))]
    last = ok[-window:]
    n = len(last)
    out = {"n": n, "window": window, "dropped_non_finite": len(outcomes) - len(ok), "mean_loss": None, "mean_baseline_loss": None, "gain": None}
    if n:
        out["mean_loss"] = sum(o["loss"] for o in last) / n
        out["mean_baseline_loss"] = sum(o["baseline_loss"] for o in last) / n
        out["gain"] = out["mean_baseline_loss"] - out["mean_loss"]
    return out


def should_demote(grade: dict, min_n: int = 30) -> bool:
    """ROADMAP rule 6: an applied model whose rolling score falls below its baseline drops back to shadow by itself. Needs `min_n` graded predictions;
    with fewer there is no verdict (False). Demotion only tightens, so it needs no approval."""
    return bool(grade["n"] >= min_n and grade["gain"] is not None and grade["gain"] < 0)
