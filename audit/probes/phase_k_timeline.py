"""Phase K: a recorded session replayed minute by minute from persisted evidence, with the production 12:20 hand-over
emulated (persist → stop → a fresh engine on the same journal, broker and memory), snapshotting at each timeline
point: the engine's decision, the journal rows written, the heartbeat, and the published site (for rendering).

Inputs (copies, read-only): the journal branch (bars, memory.json) and chains-2026 parquet files, as phase_i_replay.
Engine wiring = the repo's `intraday replay` (no news, brain, breadth, learner, research priors): what is not persisted
can't be replayed (I-04). --drop-zero-prior-vix applies Phase I's documented VIX substitution.

    python audit/probes/phase_k_timeline.py JOURNAL_DIR CHAINS_DIR 2026-10-05 OUT_DIR [--drop-zero-prior-vix]

OUT_DIR/<label>/ gets a published site (data.json + app) per snapshot; OUT_DIR/timeline.json the snapshot records.
"""
import datetime as dt
import json
import shutil
import sys
import tempfile
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
from quantdesk.web.export_site import publish_site  # noqa: E402

IST = "Asia/Kolkata"


def main(jdir: Path, cdir: Path, day: dt.date, out: Path, drop_vix: bool):
    tmp = Path(tempfile.mkdtemp(prefix=f"k-tl-{day}-"))
    acct = tmp / "rt" / "intraday"
    shutil.copytree(jdir / "intraday" / "data", acct / "data", ignore=lambda d, n: [x for x in n if x == "chains"])
    shutil.copy(jdir / "intraday" / "memory.json", acct / "memory.json")
    dropped = []
    if drop_vix:
        for f in sorted((acct / "data").glob("*/INDIAVIX_1m.csv")):
            if f.parent.name < str(day) and (pd.read_csv(f)["close"] <= 0).mean() > 0.5:
                f.unlink()
                dropped.append(f.parent.name)
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(tmp / "rt")}})
    unders = cfg.get("intraday.underlyings")
    bars = SessionRecorder(acct / "data").load_bars(unders + [cfg.get("universe.volatility_index")], upto=day)
    chains = RecordedChains(snapshots(cdir, day, unders))
    jpath, bpath = acct / "journal.db", acct / "broker.json"
    j0 = Journal(jpath)
    j0.set_state("intraday_account", {"capital": float(cfg.get("intraday.capital")), "since": "2026-10-05"})  # as production
    j0.close()

    def engine(at: str | None):
        feed = ReplayFeed(bars, day)
        if at:
            feed.clock = pd.Timestamp(f"{day} {at}", tz=IST)
        return IntradayEngine(cfg, feed, chains, Journal(jpath, autocommit_every=1),
                              IntradayBroker(cfg, starting_cash=float(cfg.get("intraday.capital")), state_path=bpath),
                              None, None, None, acct / "reviews", memory=Memory(acct / "memory.json"))

    records, seen = [], set()

    def snap(eng, label: str, why: str):
        eng.journal.commit()
        now = eng.feed.now()
        site = out / label
        publish_site(cfg, "live", site)
        hb = eng.journal.get_state("intraday_live") or {}
        last = f"{now:%Y-%m-%d %H:%M}"
        rows = {t: eng.journal.df(f"SELECT * FROM {t} WHERE substr(ts,1,16)=?", (last,)).to_dict("records")
                for t in ("decisions", "thoughts", "events")}
        records.append({"label": label, "why": why, "feed_clock": str(now), "heartbeat_ts": hb.get("ts"),
                        "engine_last_action": dict(eng.last_action), "engine_armed": {u: [a.to_record() for a in v] for u, v in eng.armed.items() if v},
                        "health": {k: eng.health.get(k) for k in ("safe_mode", "reconcile", "consecutive_failures")},
                        "heartbeat_equity": hb.get("equity"), "heartbeat_day_start_equity": hb.get("day_start_equity"),
                        "heartbeat_actions": {u: v.get("action") for u, v in (hb.get("views") or {}).items()},
                        "heartbeat_armed": hb.get("armed"), "rows_this_minute": rows, "site": str(site)})

    eng = engine(None)
    eng.start_session(day)
    first_armed = first_reject = first_armed_reject = False
    morning = True
    while eng.feed.advance():
        eng.step()
        now = eng.feed.now()
        hm = f"{now:%H:%M}"
        if not records:
            snap(eng, "01_first_heartbeat", "first minute stepped (first heartbeat written)")
        if not first_armed and any(eng.armed.values()):
            first_armed = True
            snap(eng, "02_first_armed", "first minute with an armed setup")
        dec = eng.journal.df("SELECT detail, context FROM decisions WHERE substr(ts,1,16)=?", (f"{now:%Y-%m-%d %H:%M}",))
        if not first_armed_reject and dec["context"].str.contains('"armed"').any():
            first_armed_reject = True
            snap(eng, "03_armed_trigger_rejected", "an armed trigger reached its level and was rejected")
        if not first_reject and dec["detail"].str.startswith("EV below").any():
            first_reject = True
            snap(eng, "04_ev_rejection", "first EV-floor rejection")
        if morning and hm >= "12:20":                       # production: the morning job stops here (run_live handover)
            eng._persist()
            eng.journal.event(now, "INFO", "session", f"handed over at 12:20 with {len(eng.open_trades)} open position(s)")
            snap(eng, "05_handover_morning_last", "morning runner's last minute (persisted, then stopped)")
            eng.journal.close()
            morning = False
            eng = engine("12:21")                           # the afternoon runner: a fresh process, same files
            eng.start_session(day)
            eng.journal.commit()
            snap(eng, "06_handover_afternoon_restored", "afternoon runner started, before its first step")
            eng.step()
            snap(eng, "07_handover_afternoon_first_step", "afternoon runner's first stepped minute")
    snap(eng, "08_close_last_minute", "last stepped minute before the close")
    review = eng.end_session()
    eng.journal.commit()
    snap(eng, "09_after_end_session", "after end_session (square-off and review)")
    (out / "timeline.json").write_text(json.dumps({"day": str(day), "substitution": {"dropped_zero_prior_vix_days": dropped},
                                                   "records": records, "review_head": review[:400]}, indent=1, default=str))
    print(json.dumps([{k: r[k] for k in ("label", "feed_clock", "heartbeat_ts", "heartbeat_actions")} for r in records], indent=1, default=str))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), dt.date.fromisoformat(sys.argv[3]), Path(sys.argv[4]),
         "--drop-zero-prior-vix" in sys.argv)
