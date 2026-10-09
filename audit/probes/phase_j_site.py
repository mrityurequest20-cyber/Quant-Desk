"""Phase J: build the published site (the same publish_site the workflow runs) from a COPY of an account directory.

Read-only: the source directory is copied into a fresh temp runtime; nothing is written back. Sources used in Phase J:
  prod      a copy of the journal branch at the 10-09 close (journal.db, memory.json, data/)
  8a / 8b   journals the engine itself wrote in Phase I's synthetic crash scenarios (phase_i_evidence.py: j.db, broker.json)
  safe      a synthetic session put into safe mode by the engine (built here)
  kill      a synthetic session with the file kill switch set (built here)

    python audit/probes/phase_j_site.py SRC_DIR OUT_DIR
    python audit/probes/phase_j_site.py --make safe|kill OUT_DIR
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from quantdesk.config import Config, DEFAULT_CONFIG  # noqa: E402
from quantdesk.web.export_site import publish_site  # noqa: E402


def build(src: Path, out: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="j-site-"))
    acct = tmp / "rt" / "intraday"
    acct.mkdir(parents=True)
    for name in ("journal.db", "memory.json", "broker.json", "data", "reviews"):
        p = src / name
        if p.is_dir():
            shutil.copytree(p, acct / name, ignore=lambda d, n: [x for x in n if x == "chains"])
        elif p.exists():
            shutil.copy(p, acct / name)
    if not (acct / "journal.db").exists() and (src / "j.db").exists():   # the synthetic harnesses name it j.db
        shutil.copy(src / "j.db", acct / "journal.db")
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    # production always has this record (intraday/account.ensure_account); the synthetic harness journals don't, and
    # without it the API's "pending capital" rule would replace cash and equity with the configured capital
    from quantdesk.journal.journal import Journal
    j = Journal(acct / "journal.db")
    if j.get_state("intraday_account") is None:
        j.set_state("intraday_account", {"capital": float(cfg.get("intraday.capital")), "since": "2026-09-01"})
    j.close()
    return publish_site(cfg, "live", out)


def make(kind: str) -> Path:
    """A synthetic engine run whose LAST heartbeat shows the state (written by the engine, not by hand)."""
    import phase_h_det_tests as H
    bars, days = H.world()
    day = days[-1]
    tmp = Path(tempfile.mkdtemp(prefix=f"j-{kind}-"))
    eng = H.make(tmp, bars, day)
    eng.start_session(day)
    H.advance(eng, "10:30")
    eng._open(H.spread_plan(eng), 1, [], H.view(eng), {}, eng.feed.now())
    if kind == "safe":
        eng.enter_safe_mode(eng.feed.now(), "3 steps failed in a row, last: ReadTimeout('kotak quotes')")
    elif kind == "kill":
        eng.kill_file.parent.mkdir(parents=True, exist_ok=True)
        eng.kill_file.write_text("stop")
    H.advance(eng, "10:40")
    eng.journal.commit()
    return tmp


if __name__ == "__main__":
    if sys.argv[1] == "--make":
        src = make(sys.argv[2])
        print(build(src, Path(sys.argv[3])))
    else:
        print(build(Path(sys.argv[1]), Path(sys.argv[2])))
