"""The desk's research memory: what it has tried, why it believes what it believes, and what to test next.

All of it lives in files in the repository, so a fresh session (or a person) reads the same memory:

1. **Has this experiment been run?** Every pre-registered spec (docs/prereg/*.json) gets a *fingerprint*: a hash of its
   substance (instruments, structures, rules, tests, thresholds) with the free text (name, dates, rationale) left out
   and the wording normalised. Two specs with the same fingerprint are the same experiment. The test suite refuses a
   second one, so an identical experiment can't be registered twice, by the engineer or anyone else. A variant must
   differ in substance, and `check()` shows the nearest earlier specs so it can say how.
2. **Why does the desk believe it?** Each principle in docs/principles.json carries a `history`: every move up or down
   the evidence ladder, and every review that left it where it was, with the date, the reason and the registered result
   it rests on. `caveats` are the known weaknesses a later test must address. The suite checks the history agrees with
   the status.
3. **What next?** `proposals()` turns the ledger into the next tests, by fixed rules:
   - a caveat on a replicated principle first: it threatens an edge the desk relies on;
   - then replication of what is only "found";
   - then forward tests of what has replicated.
   A rejected principle is closed: an identical retest is refused by its fingerprint.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREREG = ROOT / "docs" / "prereg"
PRINCIPLES = ROOT / "docs" / "principles.json"
LADDER = ["hypothesis", "found", "replicated", "forward", "proven"]
STATUSES = set(LADDER) | {"rejected"}
FREE_TEXT = {"name", "registered", "why", "why_it_should_be_general", "note", "notes", "use", "changes", "law",
             "question", "not_a_new_search", "audits", "hypothesis", "rationale", "description", "motivation", "about",
             "title", "context", "role", "informational"}


def substance(obj):
    """The spec without its free text: keys sorted, free-text keys and private keys dropped, strings normalised."""
    if isinstance(obj, dict):
        return {k: substance(v) for k, v in sorted(obj.items()) if k not in FREE_TEXT and not str(k).startswith("_")}
    if isinstance(obj, list):
        return [substance(x) for x in obj]
    if isinstance(obj, str):
        return " ".join(obj.lower().split())
    return obj


def fingerprint(spec: dict) -> str:
    return hashlib.sha256(json.dumps(substance(spec), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def _pairs(obj, path="") -> set[str]:
    if isinstance(obj, dict):
        return set().union(*[_pairs(v, f"{path}/{k}") for k, v in obj.items()]) if obj else {path}
    if isinstance(obj, list):
        return set().union(*[_pairs(v, f"{path}[]") for v in obj]) if obj else {path}
    return {f"{path}={obj}"}


def similarity(a: dict, b: dict) -> float:
    """Jaccard overlap of the two specs' (path = value) pairs, substance only."""
    pa, pb = _pairs(substance(a)), _pairs(substance(b))
    return len(pa & pb) / len(pa | pb) if pa | pb else 1.0


def registry(folder: Path = PREREG) -> list[dict]:
    out = []
    for p in sorted(Path(folder).glob("*.json")):
        raw = p.read_bytes()
        spec = json.loads(raw)
        h = hashlib.sha256(raw).hexdigest()[:12]
        canon = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]   # autolearn/prereg.py's
        results = sorted(x.name for k in {h, canon}
                         for x in (Path(folder) / "results").glob(f"{spec.get('name', p.stem)}-{k}*.md"))
        out.append({"name": spec.get("name", p.stem), "file": p.name, "hash": h, "fingerprint": fingerprint(spec),
                    "registered": spec.get("registered"), "results": results, "spec": spec})
    return out


def duplicates(reg: list[dict]) -> list[list[str]]:
    by: dict[str, list[str]] = {}
    for r in reg:
        by.setdefault(r["fingerprint"], []).append(r["name"])
    return [v for v in by.values() if len(v) > 1]


def check(spec: dict, reg: list[dict] | None = None, top: int = 3) -> dict:
    """Is `spec` an experiment the desk has already run? Identical ones by fingerprint, then the nearest by substance."""
    reg = registry() if reg is None else reg
    fp = fingerprint(spec)
    same = [r["name"] for r in reg if r["fingerprint"] == fp and r["spec"] is not spec]
    near = sorted(((round(similarity(spec, r["spec"]), 3), r["name"]) for r in reg if r["fingerprint"] != fp), reverse=True)
    return {"fingerprint": fp, "identical": same, "nearest": near[:top]}


# ---- principles ---------------------------------------------------------------------------------------------------
def load_principles(path: Path = PRINCIPLES) -> dict:
    return json.loads(Path(path).read_text())


def history_problems(doc: dict) -> list[str]:
    """Where a principle's history and its status disagree, or a move has no reason or reference."""
    out = []
    for p in doc["principles"]:
        h = p.get("history") or []
        if p["status"] not in STATUSES:
            out.append(f"{p['id']}: unknown status {p['status']!r}")
        if not h:
            out.append(f"{p['id']}: no history")
            continue
        if h[-1]["to"] != p["status"]:
            out.append(f"{p['id']}: status {p['status']!r} but its history ends at {h[-1]['to']!r}")
        for e in h:
            if not e.get("reason") or not e.get("ref"):
                out.append(f"{p['id']}: the {e.get('date')} entry has no reason or no reference")
            if e.get("to") not in STATUSES:
                out.append(f"{p['id']}: the {e.get('date')} entry moves to unknown status {e.get('to')!r}")
        for a, b in zip(h, h[1:]):
            if b["from"] != a["to"]:
                out.append(f"{p['id']}: history jumps from {a['to']!r} to an entry starting at {b['from']!r}")
    return out


def move(doc: dict, pid: str, to: str, reason: str, ref: str, day: dt.date | None = None,
         caveats_add=(), caveats_clear=()) -> dict:
    """Record a move (or, with `to` equal to the current status, a review) of principle `pid`. Returns the entry."""
    if to not in STATUSES:
        raise ValueError(f"unknown status {to!r}")
    if not reason or not ref:
        raise ValueError("a move needs a reason and a reference to a registered result")
    p = next(x for x in doc["principles"] if x["id"] == pid)
    entry = {"date": str(day or dt.date.today()), "from": p["status"], "to": to,
             "kind": "review" if to == p["status"] else ("up" if _rank(to) > _rank(p["status"]) else "down"),
             "reason": reason, "ref": ref}
    p.setdefault("history", []).append(entry)
    p["status"] = to
    cav = [c for c in p.get("caveats", []) if c not in set(caveats_clear)]
    p["caveats"] = cav + [c for c in caveats_add if c not in cav]
    return entry


def _rank(status: str) -> int:
    return -1 if status == "rejected" else LADDER.index(status)


def proposals(doc: dict, reg: list[dict] | None = None) -> list[dict]:
    """The next tests the evidence calls for, most urgent first."""
    reg = registry() if reg is None else reg
    names = {r["name"] for r in reg}
    out = []
    for p in doc["principles"]:
        s, pid = p["status"], p["id"]
        for c in p.get("caveats", []) if s != "rejected" else []:
            relied = s in LADDER[2:]
            out.append({"rank": 1 if relied else 2, "principle": pid, "kind": "caveat", "test": c,
                        "why": f"{pid} is {s}" + ("; the desk relies on it and this weakness is untested" if relied
                                                   else "; this weakness stands between it and the next rung")})
        if s == "hypothesis":
            out.append({"rank": 3, "principle": pid, "kind": "find", "test": "a first registered test on real history",
                        "why": "an idea with no evidence either way"})
        elif s == "found":
            for item in p.get("pending") or ["held-out instruments it was never fitted to"]:
                out.append({"rank": 2, "principle": pid, "kind": "replicate", "test": item,
                            "why": f"{pid} is found on the instruments it came from; replication is the next rung"})
        elif s == "replicated":
            fwd = [a for a in p.get("applied_in", []) if any(n.split("_v")[0] in a for n in names)] or p.get("applied_in", [])
            if not fwd:
                out.append({"rank": 2, "principle": pid, "kind": "forward",
                            "test": "a forward paper sleeve on real quotes (a new expiry_seller-style spec)",
                            "why": f"{pid} replicated in history; only real quotes going forward can move it up"})
            for item in p.get("pending", []):
                out.append({"rank": 4, "principle": pid, "kind": "collect", "test": item,
                            "why": "running; evidence accumulates with each session"})
        elif s == "rejected":
            out.append({"rank": 9, "principle": pid, "kind": "closed",
                        "test": "none: an identical retest is refused by fingerprint",
                        "why": "rejected on a registered test; a variant must say what differs and why it could matter"})
    return sorted(out, key=lambda x: (x["rank"], x["principle"]))


def summary(doc: dict | None = None, reg: list[dict] | None = None) -> dict:
    doc = load_principles() if doc is None else doc
    reg = registry() if reg is None else reg
    moves = [dict(e, principle=p["id"]) for p in doc["principles"] for e in p.get("history", [])]
    return {"experiments": len({r["fingerprint"] for r in reg}), "specs": len(reg),
            "with_results": sum(bool(r["results"]) for r in reg), "duplicates": duplicates(reg),
            "history_problems": history_problems(doc), "moves": moves,
            "open_caveats": sum(len(p.get("caveats", [])) for p in doc["principles"]),
            "proposals": proposals(doc, reg)}


def render(s: dict, reg: list[dict]) -> str:
    out = ["# Research memory", "",
           f"{s['specs']} registered specs, {s['experiments']} distinct experiments (by fingerprint), "
           f"{s['with_results']} with a recorded result. Duplicates: {s['duplicates'] or 'none'}. "
           f"History problems: {s['history_problems'] or 'none'}.", "",
           "| spec | registered | fingerprint | results |", "|---|---|---|---|"]
    out += [f"| {r['name']} | {r['registered']} | `{r['fingerprint']}` | {', '.join(r['results']) or '–'} |" for r in reg]
    out += ["", "## How the beliefs moved", "", "| date | principle | move | reason | evidence |", "|---|---|---|---|---|"]
    out += [f"| {m['date']} | {m['principle']} | {m['from']} → {m['to']} ({m['kind']}) | {m['reason']} | {m['ref']} |"
            for m in s["moves"]]
    out += ["", f"## What to test next ({s['open_caveats']} open caveats)", ""]
    out += [f"{i}. **{p['principle']} · {p['kind']}:** {p['test']}. _{p['why']}._" for i, p in enumerate(s["proposals"], 1)]
    return "\n".join(out)
