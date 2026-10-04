"""The organization's deterministic core (docs/ORG.md): the audit rota, the scorecard and the trust levels.

No language model runs here. The rota decides which department is audited each day and files that audit as a GitHub
issue labelled `desk:audit`, so the engineer's shift finds it without anyone asking. The scorecard
(docs/org/scorecard.jsonl, append-only, in git) records what each department found, fixed and missed. A department's
trailing 8-week score sets its trust, and its trust sets how much review its changes get and how often it is audited.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORECARD = ROOT / "docs" / "org" / "scorecard.jsonl"
LESSONS = ROOT / "docs" / "org" / "lessons.md"
LABEL = ("desk:audit", "5319e7")
POINTS = {"self_found": 3, "fixed": 2, "owner_found": -5, "regression": -3, "asked_owner": -2, "reverted": -2}
PENALTIES = {k for k, v in POINTS.items() if v < 0}
WINDOW_DAYS = 56
TRUSTED_AT = 10

DEPTS = {
    "data": {
        "name": "Data", "agent": "data-steward", "weekday": 0,
        "questions": [
            "Which recorded number would be wrong if one exchange file were partial, re-dated or silently re-published? "
            "Find one and re-derive it from the raw file by another route.",
            "Did any fetch in the last 7 days fail, come back empty or change schema? Is each gap a real gap or a day "
            "the exchange never published (data/audit.py UNPUBLISHED, with evidence)?",
            "Do last week's recorded 1-minute bars end on NSE's official close? Are the chain-tape quotes ever locked, "
            "crossed or stale?",
        ],
        "commands": ["python -m quantdesk warehouse-audit (or read Sunday's Study run)",
                     "python -m quantdesk data status"],
    },
    "orders": {
        "name": "Orders", "agent": "orders-desk", "weekday": 1,
        "questions": [
            "Was every leg opened last week filled at bid - 0.05 / ask + 0.05 of a real snapshot taken 15:10-15:25? "
            "Recompute three by hand from the recorded chain.",
            "Does every settled trade have an `official` event? Explain every settlement gap over 15 bps.",
            "Do skips cluster on stressed days? Is every eve the sleeves were due on recorded as an open or a skip?",
            "Does the paper account reconcile with closed trades and fees?",
        ],
        "commands": ["deploy/journal.sh restore", "python -m quantdesk intraday sleeves --report"],
    },
    "research": {
        "name": "Research", "agent": "research-reviewer", "weekday": 2,
        "questions": [
            "Take the top caveat on a principle at 'replicated' or above (python -m quantdesk experiments) and try to "
            "make it worse with data already on hand: another instrument, another period, the strictest cost.",
            "Does every result in docs/prereg/results match its spec's hash, and does each new one carry provenance?",
            "Does BACKLOG, README or principles.json claim more than a registered result supports anywhere?",
        ],
        "commands": ["python -m quantdesk experiments", "python -m pytest -o addopts='' -q tests/test_memory.py"],
    },
    "risk_compliance": {
        "name": "Risk & compliance", "agent": "risk-compliance", "weekday": 3,
        "questions": [
            "Can any code path place, enable or route a live order, or read broker credentials beyond the data feed?",
            "Did anything loosen intraday.risk, the drawdown halts or the loss budget since last week (git log -p "
            "config/)? Does any size exceed a registered spec?",
            "Could a secret reach a log, an artifact or a printed line? Grep the workflows and the last week's logs.",
            "Are workflow permissions the minimum each job needs (python deploy/check_workflows.py)?",
        ],
        "commands": ["python deploy/check_workflows.py", "git log --since='8 days ago' -p -- config/ quantdesk/execution"],
    },
    "architecture": {
        "name": "Architecture", "agent": "architect", "weekday": 4,
        "questions": [
            "Which tests are slowest or flaky (pytest --durations=25)? Which modules have no test?",
            "Where do two implementations of one rule (costs, settlement, strike picking, Newey-West) exist that could "
            "disagree? Prove they agree or file the defect.",
            "Which errors or warnings did last week's workflow logs carry? Which docs no longer match the code?",
            "Which department's defects keep recurring on the scorecard, and should that part be rebuilt?",
        ],
        "commands": ["python -m pytest -o addopts='' -q --durations=25", "python -m quantdesk org scorecard"],
    },
    "internal_audit": {
        "name": "Internal audit (the organization itself)", "agent": "internal-auditor", "weekday": 5,
        "questions": [
            "Which of this week's closed issues were closed without evidence? Re-open them.",
            "What could the owner (or any outside reviewer) ask this week that the desk has not asked itself? Ask it "
            "now and answer it with evidence.",
            "Is the scorecard honest: is every regression, revert and owner-found defect on it, each with a lesson?",
            "Did last week's plan (docs/org/plan.md) deliver its three outcomes? If not, why not?",
        ],
        "commands": ["python -m quantdesk org scorecard"],
    },
}
CHIEF = "chief_of_staff"
ENGINEERING = "engineering"
ALL_DEPTS = set(DEPTS) | {CHIEF, ENGINEERING}


# ---- the scorecard ------------------------------------------------------------------------------------------------
def load(path: Path = SCORECARD) -> list[dict]:
    p = Path(path)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def problems(events: list[dict], lessons: str | None = None) -> list[str]:
    """What makes the ledger untrustworthy: unknown departments or kinds, missing fields, and penalties with no lesson
    dated on or after them."""
    out = []
    dated = sorted(x[3:13] for x in (lessons or "").splitlines() if x.startswith("## ") and x[3:13].count("-") == 2)
    for i, e in enumerate(events, 1):
        for k in ("date", "dept", "kind", "what", "ref"):
            if not e.get(k):
                out.append(f"line {i}: no {k}")
        if e.get("dept") not in ALL_DEPTS:
            out.append(f"line {i}: unknown department {e.get('dept')!r}")
        if e.get("kind") not in POINTS:
            out.append(f"line {i}: unknown kind {e.get('kind')!r}")
        if lessons is not None and e.get("kind") in PENALTIES and not any(d >= str(e.get("date")) for d in dated):
            out.append(f"line {i}: a {e['kind']} on {e.get('date')} has no lesson dated on or after it in lessons.md")
    return out


def scores(events: list[dict], today: dt.date, window: int = WINDOW_DAYS) -> dict:
    """Per department: points over the trailing window, counts by kind, and the trust level they set."""
    start = today - dt.timedelta(days=window)
    out = {d: {"points": 0, "counts": {}} for d in sorted(ALL_DEPTS)}
    for e in events:
        if not (start < dt.date.fromisoformat(e["date"]) <= today) or e.get("kind") not in POINTS:
            continue
        o = out.setdefault(e["dept"], {"points": 0, "counts": {}})
        o["points"] += POINTS[e["kind"]]
        o["counts"][e["kind"]] = o["counts"].get(e["kind"], 0) + 1
    for o in out.values():
        o["trust"] = "probation" if o["points"] < 0 else "trusted" if o["points"] >= TRUSTED_AT else "standard"
    return out


def self_found_share(events: list[dict], since: dt.date | None = None) -> float | None:
    """Self-found defects / (self-found + owner-found): the north-star of an organization that audits itself."""
    ev = [e for e in events if since is None or dt.date.fromisoformat(e["date"]) >= since]
    s = sum(e["kind"] == "self_found" for e in ev)
    o = sum(e["kind"] == "owner_found" for e in ev)
    return round(s / (s + o), 4) if s + o else None


def render_scorecard(events: list[dict], today: dt.date) -> str:
    sc = scores(events, today)
    share = self_found_share(events)
    esc = sum(e["kind"] == "owner_found" and dt.date.fromisoformat(e["date"]) > today - dt.timedelta(days=30)
              for e in events)
    out = [f"# Scorecard · {today}", "",
           f"Self-found share (all time): **{'–' if share is None else f'{share:.0%}'}**. "
           f"Escapes (owner-found) in the last 30 days: **{esc}**.", "",
           f"| department | points ({WINDOW_DAYS} days) | trust | self-found | fixed | owner-found | other penalties |",
           "|---|---:|---|---:|---:|---:|---:|"]
    for d, o in sc.items():
        c = o["counts"]
        other = sum(c.get(k, 0) for k in ("regression", "asked_owner", "reverted"))
        out.append(f"| {d} | {o['points']:+d} | {o['trust']} | {c.get('self_found', 0)} | {c.get('fixed', 0)} | "
                   f"{c.get('owner_found', 0)} | {other} |")
    out += ["", "Trust: probation (below 0) means an internal-audit pass before every change ships, and a second audit "
            "each week; trusted (10 or more) means lighter gates (docs/ORG.md)."]
    return "\n".join(out)


# ---- the rota ------------------------------------------------------------------------------------------------------
def due(day: dt.date, events: list[dict]) -> list[str]:
    """The departments audited on `day`: the weekday's own, plus on Saturday every department on probation."""
    out = [k for k, v in DEPTS.items() if v["weekday"] == day.weekday()]
    if day.weekday() == 5:
        sc = scores(events, day)
        out += [k for k in DEPTS if k not in out and sc.get(k, {}).get("trust") == "probation"]
    return out


def deterministic(day: dt.date) -> list[tuple[str, str]]:
    """Sunday's heavy audits on GitHub's runners, as (study, spec) for the Study workflow."""
    if day.weekday() != 6:
        return []
    jobs = [("warehouse-audit", ""), ("entry-check", "")]
    if day.day <= 7:                        # first Sunday of the month: the law audit, informational, on fresh data
        jobs.append(("law-audit", "docs/prereg/expiry_eve_law_v2_audit.json"))
    return jobs


def title(dept: str, day: dt.date) -> str:
    return f"[audit] {day} · {DEPTS[dept]['name']}"


def body(dept: str, day: dt.date, trust: str) -> str:
    d = DEPTS[dept]
    q = "\n".join(f"{i}. {x}" for i, x in enumerate(d["questions"], 1))
    c = "\n".join(f"- `{x}`" for x in d["commands"])
    return (f"The rota's audit for **{d['name']}** on {day} (docs/ORG.md). Department trust: **{trust}**.\n\n"
            f"Delegate it to the `{d['agent']}` agent (`.claude/agents/{d['agent']}.md`). Whoever built a thing does not "
            f"audit it.\n\n"
            f"**Attack these, as hypotheses that the desk is wrong:**\n{q}\n\n**Start from:**\n{c}\n\n"
            "**To close this issue:**\n"
            "- each finding with its evidence (file:line, command, output) and severity, filed as its own `desk-request` "
            "issue, and recorded as `self_found` in docs/org/scorecard.jsonl; or\n"
            "- \"no finding\", with what was checked and how.\n\n"
            "An audit left open for 2 days is flagged as overdue by the next rota.")


def sync(gh, day: dt.date, events: list[dict], say=print) -> dict:
    """File today's audits (once each) and flag the overdue ones (once each)."""
    gh.ensure_label(*LABEL)
    gh.ensure_label("overdue", "b60205")
    sc = scores(events, day)
    done = {"created": [], "overdue": []}
    for dept in due(day, events):
        t = title(dept, day)
        if gh.issue_titled(t, LABEL[0]) is None:
            i = gh.create(t, body(dept, day, sc.get(dept, {}).get("trust", "standard")), [LABEL[0]])
            done["created"].append(i.get("number"))
    for i in gh.issues(LABEL[0], state="open"):
        opened = dt.date.fromisoformat(str(i.get("created_at", ""))[:10] or str(day))
        if (day - opened).days >= 2 and "overdue" not in {(x.get("name") if isinstance(x, dict) else x)
                                                          for x in i.get("labels", [])}:
            gh.comment(i["number"], f"Overdue on {day}: the rota's audits come before the routine queue "
                                    "(AUTONOMY.md, shift step 2).")
            gh.add_label(i["number"], "overdue")
            done["overdue"].append(i["number"])
    say(f"audits: filed {done['created'] or 'none'}, overdue {done['overdue'] or 'none'}")
    return done


def render_rota(day: dt.date, events: list[dict]) -> str:
    sc = scores(events, day)
    out = [f"## Audit rota · {day} ({day:%A})", ""]
    ds = due(day, events)
    out += [f"- {DEPTS[d]['name']} ({sc.get(d, {}).get('trust', 'standard')}): agent `{DEPTS[d]['agent']}`" for d in ds]
    out += [f"- Study run: {s}" + (f" ({p})" if p else "") for s, p in deterministic(day)]
    return "\n".join(out if len(out) > 2 else out + ["- nothing scheduled"])
