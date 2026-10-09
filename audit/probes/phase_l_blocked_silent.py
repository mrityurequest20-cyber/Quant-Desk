"""Phase L synthetic fixture: an armed trigger hit while a halt is up leaves no record of the hit (read-only).

The exact 10-05 replay (as test_phase_k_probes) is stepped to 10:55; then a halt is raised on the engine instance
(health.safe_mode — the same field the reconcile failure and crash restore set) and 10:56 is stepped. Production's
10:56 bar reaches the armed trend_break level (Phase K, K-01). `_fire_armed` clears the armed list and returns None at
its `_blocked` check (engine.py:466-468), so no decision row and no thought records that the level was reached; the
minute's read then shows only the halt.

    python audit/probes/phase_l_blocked_silent.py JOURNAL_DIR CHAINS_DIR OUT.json      (JOURNAL_DIR holds intraday/)
"""
import datetime as dt
import json
import shutil
import sys
import tempfile
from pathlib import Path

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


def run(jdir: Path, cdir: Path, halt: bool) -> dict:
    day = dt.date(2026, 10, 5)
    tmp = Path(tempfile.mkdtemp(prefix="l-blk-"))
    acct = tmp / "rt" / "intraday"
    shutil.copytree(jdir / "intraday" / "data", acct / "data", ignore=lambda d, n: [x for x in n if x == "chains"])
    shutil.copy(jdir / "intraday" / "memory.json", acct / "memory.json")
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    u = cfg.get("intraday.underlyings")
    bars = SessionRecorder(acct / "data").load_bars(u + [cfg.get("universe.volatility_index")], upto=day)
    eng = IntradayEngine(cfg, ReplayFeed(bars, day), RecordedChains(snapshots(cdir, day, u)), Journal(acct / "j.db", autocommit_every=1),
                         IntradayBroker(cfg, starting_cash=500000, state_path=acct / "broker.json"), None, None, None, acct / "reviews",
                         memory=Memory(acct / "memory.json"))
    eng.start_session(day)
    while eng.feed.advance() and f"{eng.feed.now():%H:%M}" < "10:56":
        eng.step()
    armed_before = [a.to_record() for a in eng.armed.get("NIFTY", [])]
    if halt:
        eng.health["safe_mode"] = "synthetic halt raised by the Phase L probe"
    eng.step()
    eng.journal.commit()
    hb = eng.journal.get_state("intraday_live")
    q = lambda t: eng.journal.df(f"SELECT * FROM {t} WHERE substr(ts,12,5)='10:56'").to_dict("records")  # noqa: E731
    return {"halt": halt, "armed_before_1056": armed_before, "decisions_1056": q("decisions"),
            "thoughts_1056": [{"symbol": t["symbol"], "action": t["action"]} for t in q("thoughts")],
            "heartbeat_action_NIFTY": hb["views"]["NIFTY"]["action"], "heartbeat_armed": hb["armed"]}


if __name__ == "__main__":
    res = {"evidence_class": "synthetic fixture on the exact 10-05 replay (halt injected at 10:56)",
           "control_no_halt": run(Path(sys.argv[1]), Path(sys.argv[2]), False),
           "halted": run(Path(sys.argv[1]), Path(sys.argv[2]), True)}
    Path(sys.argv[3]).write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: (v if not isinstance(v, dict) else {x: y for x, y in v.items() if x != "armed_before_1056"}) for k, v in res.items()},
                     indent=1, default=str)[:3000])
