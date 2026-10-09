"""Phase L: what the fabricated India VIX vote changed in a session's decision stream (replay only, read-only).

Replays a recorded session twice from the same copies (phase_i_replay wiring, single process, no hand-over):
  as recorded   — the engine reads the zero VIX series as production did ("India VIX 0.00 (-100.0% today)", vote +1);
  without vote  — `_vix_state` on the engine INSTANCE returns None (the analyst then casts no VIX vote at all).
and compares, minute by minute: bias, score, conviction, the armed setups, and the decision rows.

This measures sensitivity in a replay; it is not a claim about what production would have done (production also ran
news, the brain, breadth and the learner, which a replay cannot reproduce: I-04).

    python audit/probes/phase_l_vix_counterfactual.py JOURNAL_DIR CHAINS_DIR 2026-10-05 OUT.json [--drop-zero-prior-vix]
"""
import datetime as dt
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from phase_i_replay import snapshots  # noqa: E402
from quantdesk.config import Config, DEFAULT_CONFIG  # noqa: E402
from quantdesk.intraday.chains import RecordedChains  # noqa: E402
from quantdesk.intraday.engine import IntradayEngine  # noqa: E402
from quantdesk.intraday.feeds import ReplayFeed  # noqa: E402
from quantdesk.intraday.learning import Memory  # noqa: E402
from quantdesk.intraday.recorder import SessionRecorder  # noqa: E402
from quantdesk.intraday.sim import IntradayBroker  # noqa: E402
from quantdesk.journal.journal import Journal  # noqa: E402


def run(jdir: Path, cdir: Path, day: dt.date, vote: bool, drop_vix: bool) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="l-vixcf-"))
    acct = tmp / "rt" / "intraday"
    shutil.copytree(jdir / "intraday" / "data", acct / "data", ignore=lambda d, n: [x for x in n if x == "chains"])
    shutil.copy(jdir / "intraday" / "memory.json", acct / "memory.json")
    if drop_vix:
        for f in sorted((acct / "data").glob("*/INDIAVIX_1m.csv")):
            if f.parent.name < str(day) and (pd.read_csv(f)["close"] <= 0).mean() > 0.5:
                f.unlink()
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    u = cfg.get("intraday.underlyings")
    bars = SessionRecorder(acct / "data").load_bars(u + [cfg.get("universe.volatility_index")], upto=day)
    eng = IntradayEngine(cfg, ReplayFeed(bars, day), RecordedChains(snapshots(cdir, day, u)), Journal(acct / "j.db", autocommit_every=1),
                         IntradayBroker(cfg, starting_cash=500000, state_path=acct / "broker.json"), None, None, None, acct / "reviews",
                         memory=Memory(acct / "memory.json"))
    if not vote:
        eng._vix_state = lambda: None
    eng.start_session(day)
    per = {}
    while eng.feed.advance():
        eng.step()
        now = f"{eng.feed.now():%H:%M}"
        per[now] = {s: {"bias": v.bias, "score": round(v.score, 4), "conv": round(v.conviction, 4),
                        "vix_vote": next((round(e.direction, 3) for e in v.evidence if e.factor == "vix"), None),
                        "armed": sorted((a.setup, round(a.level, 2)) for a in eng.armed.get(s, [])),
                        "action": (eng.last_action.get(s) or "")[:60]} for s, v in eng.views.items()}
    eng.journal.commit()
    dec = eng.journal.df("SELECT ts, symbol, strategy, detail FROM decisions").to_dict("records")
    return {"per_minute": per, "decisions": [{"ts": d["ts"][11:16], "symbol": d["symbol"], "setup": d["strategy"],
                                              "kind": "EV floor" if d["detail"].startswith("EV below") else d["detail"][:60]} for d in dec]}


def main(jdir, cdir, day, out, drop_vix):
    a, b = run(jdir, cdir, day, True, drop_vix), run(jdir, cdir, day, False, drop_vix)
    diff = Counter()
    ex = []
    common = sorted(set(a["per_minute"]) & set(b["per_minute"]))
    for m in common:
        for s in a["per_minute"][m]:
            x, y = a["per_minute"][m][s], b["per_minute"][m].get(s)
            if y is None:
                continue
            diff["symbol_minutes"] += 1
            diff["vix_vote_present_as_recorded"] += x["vix_vote"] is not None
            diff["vix_vote_+1_as_recorded"] += x["vix_vote"] == 1.0
            diff["bias_differs"] += x["bias"] != y["bias"]
            diff["armed_differs"] += x["armed"] != y["armed"]
            diff["action_kind_differs"] += x["action"].split(":")[0] != y["action"].split(":")[0]
            diff["score_abs_diff_sum"] += abs(x["score"] - y["score"])
            if x["bias"] != y["bias"] and len(ex) < 5:
                ex.append({"minute": m, "symbol": s, "as_recorded": x, "without_vote": y})
    key = lambda d: (d["ts"], d["symbol"], d["setup"], d["kind"])  # noqa: E731
    da, db = Counter(map(key, a["decisions"])), Counter(map(key, b["decisions"]))
    res = {"day": str(day), "evidence_class": "replay-exact counterfactual" if not drop_vix else "replay-subst counterfactual",
           "minutes_compared": len(common), "diff": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in diff.items()},
           "mean_abs_score_shift": round(diff["score_abs_diff_sum"] / max(diff["symbol_minutes"], 1), 4),
           "decisions_as_recorded": len(a["decisions"]), "decisions_without_vote": len(b["decisions"]),
           "decisions_only_as_recorded": sorted("|".join(k) for k in (da - db)),
           "decisions_only_without_vote": sorted("|".join(k) for k in (db - da)),
           "decision_kinds_as_recorded": dict(Counter(d["kind"][:30] for d in a["decisions"])),
           "decision_kinds_without_vote": dict(Counter(d["kind"][:30] for d in b["decisions"])),
           "bias_flip_examples": ex}
    Path(out).write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "bias_flip_examples"}, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), dt.date.fromisoformat(sys.argv[3]), sys.argv[4], "--drop-zero-prior-vix" in sys.argv)
