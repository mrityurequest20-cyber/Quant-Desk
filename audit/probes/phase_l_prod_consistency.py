"""Phase L: production lower bounds for the decision-to-UI contradictions, from the persisted journal alone (read-only).

The heartbeat (`intraday_live`) is a single overwritten state row, so production screens can't be recounted; what is
persisted is every decision row and the SAMPLED thoughts (a thought is written on a bias change, a trade event or every
5 min). Counts below are therefore lower bounds, with their denominators.

    python audit/probes/phase_l_prod_consistency.py JOURNAL_DB OUT.json
"""
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

LEVEL = re.compile(r"(\w+) reached its level ([\d,]+\.\d\d)")


def main(db: Path, out: Path):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dec = pd.read_sql("SELECT id, ts, symbol, strategy, detail FROM decisions WHERE ts >= '2026-10-05' ORDER BY id", c)
    th = pd.read_sql("SELECT ts, symbol, action, score FROM thoughts WHERE ts >= '2026-10-05' ORDER BY id", c)
    dec["t"], th["t"] = pd.to_datetime(dec["ts"]), pd.to_datetime(th["ts"])
    th["m"] = th["t"].dt.floor("min")                                        # thoughts are stamped at the step (hh:mm:04)
    arm = dec[dec["detail"].str.contains("reached its level")]
    ev = dec[dec["detail"].str.startswith("EV below")]
    step_sec = Counter(int(t.second) for t in ev["t"])                       # the minute step's cadence (:04)
    res = {"denominators": {"decisions_since_reset": len(dec), "armed_trigger_rejections": len(arm),
                            "ev_floor_rejections": len(ev), "sampled_thoughts": len(th)},
           "path": {"ev_rejection_second_of_minute": dict(step_sec),
                    "armed_rejection_seconds": sorted(int(t.second) for t in arm["t"]),
                    "armed_off_step_cadence": int(sum(int(t.second) not in step_sec for t in arm["t"]))}}
    rows, cls1, cls5 = [], Counter(), Counter()
    for _, d in arm.iterrows():
        setup, lvl = LEVEL.search(d["detail"]).groups()
        same_min = th[(th["symbol"] == d["symbol"]) & (th["m"] == d["t"].floor("min"))]
        nxt_min = d["t"].floor("min") + pd.Timedelta(minutes=1)
        nx1 = th[(th["symbol"] == d["symbol"]) & (th["m"] == nxt_min)]
        nx5 = th[(th["symbol"] == d["symbol"]) & (th["t"] > d["t"]) & (th["t"] <= d["t"] + pd.Timedelta(minutes=5))]

        def kind(a):
            if a.startswith("armed:"):
                return "rearmed_same_setup_same_level" if f"{setup}:" in a and lvl in a else \
                       "rearmed_same_setup_new_level" if f"{setup}:" in a else "rearmed_other"
            if "no setup has triggered" in a:
                return "watching_no_setup_has_triggered"
            return a.split(":")[0][:30]
        k1 = kind(nx1["action"].iloc[0]) if len(nx1) else "no_sampled_thought_next_minute"
        k5 = kind(nx5["action"].iloc[0]) if len(nx5) else "no_sampled_thought_within_5min"
        cls1[k1] += 1
        cls5[k5] += 1
        rows.append({"ts": d["ts"], "symbol": d["symbol"], "setup": setup, "level": lvl,
                     "thought_recording_outcome": int(same_min["action"].str.contains("reached its level").sum()),
                     "next_minute_thought": k1, "first_thought_within_5min": k5,
                     "seconds_until_next_step": int((nxt_min - d["t"]).total_seconds()) + 4})
    res["armed"] = {"outcome_recorded_in_any_thought": int(sum(r["thought_recording_outcome"] > 0 for r in rows)),
                    "next_minute_sampled_thought": dict(cls1), "first_sampled_thought_within_5min": dict(cls5),
                    "tick_heartbeat_waiting_with_nothing_armed_seconds_total_by_code": int(sum(r["seconds_until_next_step"] for r in rows)),
                    "rows": rows}
    pup = ev["detail"].str.extract(r"is (\S+) with EV .*? at P\(up\) ([\d.]+) \[([^\]]+)\]")
    res["ev"] = {"structures": dict(Counter(pup[0])), "p_up_in_message": dict(Counter(pup[1])),
                 "message_p_up_not_0.50_while_nondirectional_evaluated_at_0.50": int(((pup[0] == "iron_fly") & (pup[1].astype(float) != 0.5)).sum()),
                 "p_source": dict(Counter(pup[2])),
                 "with_sampled_thought_same_minute": int(sum(((th["symbol"] == d["symbol"]) & (th["m"] == d["t"].floor("min"))).any()
                                                            for _, d in ev.iterrows()))}
    out.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps({k: v for k, v in res.items() if k != "armed"} | {"armed": {k: v for k, v in res["armed"].items() if k != "rows"}}, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
