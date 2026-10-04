"""Is the desk getting smarter? A daily snapshot of what it knows and how it's doing, compared week on week and with
the first snapshot, so the answer is a table rather than a feeling.

**The headline is the evidence level:** the highest rung any principle in docs/principles.json has reached.
- 1, found: real history;
- 2, replicated: held-out instruments;
- 3, forward: real quotes going forward;
- 4, proven: three months of paper money at registered size.

Below it sit:
- **knowledge:** principles by status, rejected ones included;
- **research throughput:** registered specs and recorded results;
- **the forward sleeves:** settled trades, P&L, cost gap, retirements, eligibility;
- **the paper account:** equity and drawdown;
- **data:** full sessions of real chain tape.

Each line says whether it improved, held or got worse, and in which direction better lies.

The afternoon job records a snapshot every session, kept with the journal in runtime/intraday/progress/history.jsonl.
The weekly Progress workflow posts the report as a comment on the "Desk progress" issue, where the owner follows it.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
LADDER = ["hypothesis", "found", "replicated", "forward", "proven"]
LEVEL_NAME = {0: "no edge found yet", 1: "found in real history", 2: "replicated on instruments it was never fitted to",
              3: "survives real quotes going forward", 4: "proven in the paper account"}
# KPI → (label, +1 when higher is better / −1 when lower is better)
KPIS = {"level": ("evidence level (0-4)", 1), "principles_tested": ("principles tested (incl. rejected)", 1),
        "principles_replicated_plus": ("principles replicated or better", 1), "results": ("registered results", 1),
        "sleeve_trades": ("forward sleeve trades settled", 1), "sleeve_pnl": ("forward sleeve P&L, ₹/lot", 1),
        "sleeves_eligible": ("sleeves eligible for the paper account", 1), "sleeves_retired": ("sleeves retired", -1),
        "equity": ("paper account equity, ₹", 1), "drawdown": ("paper drawdown from peak", -1),
        "tape_sessions": ("full sessions of real chain tape", 1), "open_bugs": ("open desk bugs", -1)}
FULL_TAPE = 300


def principles(path: Path = ROOT / "docs" / "principles.json") -> dict:
    p = json.loads(Path(path).read_text())["principles"] if Path(path).exists() else []
    counts = {s: sum(x["status"] == s for x in p) for s in LADDER + ["rejected"]}
    level = max([LADDER.index(x["status"]) for x in p if x["status"] in LADDER] or [0])
    return {"counts": counts, "level": level, "tested": sum(x["status"] != "hypothesis" for x in p),
            "replicated_plus": sum(x["status"] in LADDER[2:] for x in p)}


def snapshot(cfg, day: dt.date, gh=None) -> dict:
    from ..intraday.cli import paths
    from ..intraday.sleeves import ExpirySeller, specs
    from ..journal.journal import Journal
    p = paths(cfg, "live")
    pr = principles()
    snap = {"date": str(day), "level": pr["level"], "principle_counts": pr["counts"], "principles_tested": pr["tested"],
            "principles_replicated_plus": pr["replicated_plus"],
            "specs": len(list((ROOT / "docs" / "prereg").glob("*.json"))),
            "results": len(list((ROOT / "docs" / "prereg" / "results").glob("*.md")))}
    trades = pnl = eligible = retired = 0
    gaps = []
    for spec in specs():
        rep = ExpirySeller(cfg, cfg.runtime_dir / "intraday" / "sleeves", p["data"], spec=spec).report()
        for r in rep["rows"]:
            trades += r["n"]
            pnl += r["sum"]
            eligible += bool(r["eligible"])
            retired += bool(r["retired"])
            if r["n"]:
                gaps.append(r["gap_mean"])
    snap.update({"sleeve_trades": trades, "sleeve_pnl": round(pnl, 2), "sleeves_eligible": eligible,
                 "sleeves_retired": retired, "sleeve_cost_gap": round(sum(gaps) / len(gaps), 2) if gaps else None})
    j = Journal(p["journal"])
    try:
        eq = j.equity()
        acct = j.get_state("intraday_account") or {}
        closed = j.trades("closed")
    finally:
        j.close()
    if len(eq) and "equity" in eq:
        last, peak = float(eq["equity"].iloc[-1]), float(eq["equity"].cummax().iloc[-1])
    else:
        last = peak = float(acct.get("capital") or cfg.get("intraday.capital", 0))
    snap.update({"equity": round(last, 2), "drawdown": round(1 - last / peak, 4) if peak > 0 else 0.0,
                 "paper_trades": int(len(closed)), "paper_pnl": round(float(closed["pnl"].sum()), 2) if len(closed) else 0.0})
    full = 0
    for log in Path(p["data"]).glob("*/tape.csv"):
        try:
            ok = pd.read_csv(log, usecols=["ok"])["ok"].astype(str).str.lower() == "true"
        except Exception:
            continue
        full += int(ok.sum() >= FULL_TAPE)
    snap["tape_sessions"] = full
    snap["open_bugs"] = None
    if gh is not None:
        try:
            snap["open_bugs"] = sum(any(lb.get("name") == "desk:bug" for lb in i.get("labels", [])) for i in gh.open_issues())
        except Exception:
            pass
    return snap


def record(snap: dict, path: Path) -> list[dict]:
    """Append today's snapshot (a re-run the same day replaces it); returns the whole history."""
    path = Path(path)
    hist = [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []
    hist = [h for h in hist if h["date"] != snap["date"]] + [snap]
    hist.sort(key=lambda h: h["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(h) + "\n" for h in hist))
    return hist


def compare(curr: dict, prev: dict | None) -> list[tuple[str, object, object, str]]:
    out = []
    for k, (label, better) in KPIS.items():
        a, b = (prev or {}).get(k), curr.get(k)
        if a is None or b is None:
            verdict = "new" if b is not None else "–"
        elif b == a:
            verdict = "same"
        else:
            verdict = "improved" if (b - a) * better > 0 else "worse"
        out.append((label, a, b, verdict))
    return out


def baseline(hist: list[dict], days: int = 7) -> dict | None:
    """The latest snapshot at least `days` before the newest one (else the oldest)."""
    if len(hist) < 2:
        return None
    cut = str(dt.date.fromisoformat(hist[-1]["date"]) - dt.timedelta(days=days))
    older = [h for h in hist[:-1] if h["date"] <= cut]
    return older[-1] if older else hist[0]


def render(hist: list[dict]) -> str:
    cur = hist[-1]
    mark = {"improved": "⬆ improved", "worse": "⬇ worse", "same": "= same", "new": "new", "–": "–"}

    def v(x):
        return "–" if x is None else (f"{x:,.2f}" if isinstance(x, float) else f"{x:,}")
    out = [f"## Desk progress · {cur['date']}", "",
           f"**Evidence level {cur['level']}/4: {LEVEL_NAME[cur['level']]}.** Principles: "
           + ", ".join(f"{n} {s}" for s, n in cur["principle_counts"].items() if n) + ".", ""]
    for title, ref in (("Since last week", baseline(hist)), ("Since the first snapshot", hist[0] if len(hist) > 1 else None)):
        if ref is None:
            out += [f"_{title}: this is the first snapshot; the comparison starts with the next one._", ""]
            continue
        rows = compare(cur, ref)
        up = sum(r[3] == "improved" for r in rows)
        down = sum(r[3] == "worse" for r in rows)
        out += [f"### {title} ({ref['date']} → {cur['date']}): {up} improved, {down} worse", "",
                "| measure | then | now | verdict |", "|---|---:|---:|---|"]
        out += [f"| {lab} | {v(a)} | {v(b)} | {mark[ver]} |" for lab, a, b, ver in rows]
        out.append("")
    out.append("The level climbs only on registered evidence (docs/prereg); docs/principles.json says why each rung was reached.")
    return "\n".join(out)
