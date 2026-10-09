"""Phase D: is the factor learning distinguishable from noise? (read-only; a copy of the journal's data)

1. Grades the journal's real factor reads with the production grader (learning.grade_factors) against the recorded
   bars, exactly as the close does (fresh memory, so only these sessions count).
2. Placebo: each (factor, symbol, session) direction series is multiplied by a random ±1. That keeps every factor's
   within-session persistence and the overlap of the 30-minute windows, and destroys any link to returns. Graded the
   same way, many times.
3. Reports how often noise produces the "graduations" the live desk acts on (shrunk hit rate ≥ 57.5% with ≥ 30
   graded reads = reliability ≥ 1.15, the analyst's and the brain's vote rule), and how persistent factor signs are.

usage: python audit/probes/phase_d_factor_placebo.py <journal_intraday_dir> [n_placebo]
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from quantdesk.intraday.learning import Memory, grade_factors  # noqa: E402
from quantdesk.intraday.recorder import SessionRecorder  # noqa: E402

jdir = Path(sys.argv[1])
N = int(sys.argv[2]) if len(sys.argv) > 2 else 300
with sqlite3.connect(f"file:{jdir / 'journal.db'}?mode=ro", uri=True) as c:
    th = pd.read_sql("SELECT ts, symbol, evidence FROM thoughts ORDER BY ts", c)
bars = SessionRecorder(jdir / "data").load_bars(["NIFTY", "BANKNIFTY"])
bars = {k: v.set_axis(v.index.as_unit("ns")) for k, v in bars.items()}
th["day"] = th["ts"].str[:10]
ev = [json.loads(x or "[]") for x in th["evidence"]]


def grade(evid) -> dict:
    t = th[["ts", "symbol"]].copy()
    t["evidence"] = [json.dumps(e) for e in evid]
    m = Memory(None)
    grade_factors(m, t, bars)
    return m.d["tables"].get("factor", {})


def summary(tab: dict) -> pd.DataFrame:
    rows = []
    for f, r in tab.items():
        hr = (r["hits"] + 10) / (r["n"] + 20)                          # PRIOR = 20 at 50%
        rows.append({"factor": f, "n": r["n"], "hit_shrunk": hr, "rel": float(np.clip(2 * hr, 0.5, 1.5))})
    return pd.DataFrame(rows)


real = summary(grade(ev))
grad = real[(real["n"] >= 30) & (real["rel"] >= 1.15)]
print(f"reads graded: {len(th)} over {th['day'].nunique()} sessions; factors {len(real)}")
print(real.sort_values("hit_shrunk", ascending=False).round(3).head(12).to_string(index=False))
print(f"REAL: factors that would graduate (n>=30, rel>=1.15): {len(grad)} {sorted(grad['factor'])}")

# persistence: consecutive same-sign reads per factor/symbol/day
runs = []
for (sym, day), g in th.groupby(["symbol", "day"]):
    seq: dict = {}
    for e in [ev[i] for i in g.index]:
        for x in e:
            seq.setdefault(x["factor"], []).append(np.sign(x["direction"]))
    for f, s in seq.items():
        s = [v for v in s if v != 0]
        if len(s) > 1:
            runs.append(np.mean([a == b for a, b in zip(s[:-1], s[1:])]))
print(f"factor sign persistence: P(next read same sign) mean {np.mean(runs):.3f}, median {np.median(runs):.3f}")

rng = np.random.default_rng(0)
keys = sorted({(x["factor"], s, d) for e, s, d in zip(ev, th["symbol"], th["day"]) for x in e})
max_hr, n_grad = [], []
for _ in range(N):
    flip = {k: rng.choice([-1.0, 1.0]) for k in keys}
    pe = [[{**x, "direction": x["direction"] * flip[(x["factor"], s, d)]} for x in e] for e, s, d in zip(ev, th["symbol"], th["day"])]
    p = summary(grade(pe))
    max_hr.append(p["hit_shrunk"].max())
    n_grad.append(int(((p["n"] >= 30) & (p["rel"] >= 1.15)).sum()))
max_hr, n_grad = np.array(max_hr), np.array(n_grad)
print(f"PLACEBO ({N} draws): max shrunk hit rate median {np.median(max_hr):.3f}, 95th pct {np.quantile(max_hr, .95):.3f}")
print(f"PLACEBO: graduations per draw mean {n_grad.mean():.2f}; P(>=1 graduation) {np.mean(n_grad >= 1):.3f}; "
      f"P(>= real count {len(grad)}) {np.mean(n_grad >= len(grad)):.3f}")
print(f"REAL max shrunk hit rate {real['hit_shrunk'].max():.3f} → placebo p = {np.mean(max_hr >= real['hit_shrunk'].max()):.3f}")
