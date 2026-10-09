"""How often does the autolearn cycle register a challenger on a pure random walk? (read-only; temp dirs)"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from test_autolearn import loader_of, market, sessions, ts  # noqa: E402

from quantdesk.autolearn.cycle import Cycle  # noqa: E402
from quantdesk.config import DEFAULT_CONFIG, Config  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
reg, rows = 0, []
for seed in range(N):
    tmp = Path(tempfile.mkdtemp(prefix="nullcyc-"))
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")},
                                                 "autolearn": {"bootstrap": {"samples": 300, "block_days": 3, "seed": 7}}})
    days = sessions(57, start="2026-07-20")
    bars = {"NIFTY": market(days, phi=0.0, seed=100 + seed), "BANKNIFTY": market(days, phi=0.0, seed=200 + seed, start=55000.0)}
    st = Cycle(cfg, now=ts(f"{days[-1]} 16:30"), loader=loader_of(bars), journal_path=tmp / "none.db",
               root=tmp / "al", say=None).run(["ingest", "dataset", "train", "validate", "register"])
    v = st["stages"]["validate"]["output"]
    r = st["stages"]["register"]["output"]["registered"]
    reg += bool(r)
    s = v["summary"].get("baseline", {})
    rows.append((seed, bool(r), s.get("auc"), s.get("expectancy_bps"), s.get("trades"), len(s.get("reasons") or [])))
for x in rows:
    print(x)
print(f"registered on a random walk: {reg}/{N}")
