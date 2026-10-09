"""Phase L: what the GitHub Pages deployment record says about publish latency (read-only).

Input: the `pages-build-deployment` workflow-run listings (GitHub Actions API, list_workflow_runs, read-only), saved as
JSON. Each run is triggered by a push to gh-pages; created_at ≈ the push, updated_at = the deployment finished.

What this can measure: the build+deploy time of each push, and the realised cadence of deployments during sessions.
What it cannot: the CDN edge cache (max-age) after deployment, the delay between `export-site` and the push, or what a
given viewer's browser saw. Those stay unresolved.

    python audit/probes/phase_l_pages_latency.py OUT.json RUNS_PAGE1.json [RUNS_PAGE2.json ...]
"""
import json
import statistics as st
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

IST = timedelta(hours=5, minutes=30)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main(out: Path, files):
    runs, total = {}, None
    for f in files:
        d = json.loads(Path(f).read_text())
        total = d.get("total_count", total)
        for r in d["workflow_runs"]:
            runs[r["id"]] = r
    rows = sorted(({"id": r["id"], "created": r["created_at"], "updated": r["updated_at"], "conclusion": r["conclusion"],
                    "head_sha": r["head_sha"], "secs": (ts(r["updated_at"]) - ts(r["created_at"])).total_seconds()}
                   for r in runs.values()), key=lambda x: x["created"])
    ok = [x["secs"] for x in rows if x["conclusion"] == "success"]
    q = lambda v, p: sorted(v)[min(len(v) - 1, int(p * len(v)))]  # noqa: E731
    per_day = defaultdict(list)
    for x in rows:
        t = ts(x["created"]) + IST
        if (9, 15) <= (t.hour, t.minute) <= (15, 45) and t.weekday() < 5:
            per_day[str(t.date())].append(t)
    cadence = {}
    for d, v in sorted(per_day.items()):
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(v, v[1:])]
        cadence[d] = {"deployments_in_session": len(v), "first_ist": v[0].strftime("%H:%M:%S"), "last_ist": v[-1].strftime("%H:%M:%S"),
                      "gap_min_median": round(st.median(gaps), 2) if gaps else None, "gap_min_max": round(max(gaps), 2) if gaps else None}
    res = {"runs_total_reported": total, "runs_listed": len(rows), "first": rows[0]["created"], "last": rows[-1]["created"],
           "conclusions": dict(Counter(x["conclusion"] for x in rows)),
           "build_deploy_seconds": {"n": len(ok), "median": st.median(ok), "p90": q(ok, 0.9), "p99": q(ok, 0.99), "max": max(ok), "min": min(ok)},
           "session_cadence_by_day": cadence,
           "not_measurable": ["CDN/edge caching after deployment", "export-site → push delay inside run-session.sh",
                              "what any viewer's browser actually rendered and when"],
           "runs": rows}
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "runs"}, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2:])
