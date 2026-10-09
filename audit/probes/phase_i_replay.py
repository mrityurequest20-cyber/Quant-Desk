"""Phase I: can a recorded session be replayed from persisted evidence alone?

Inputs, all persisted artifacts, read-only, copied into a fresh temp runtime:
  - 1-minute bars recorded on the `journal` branch (runtime/intraday/data/<date>/*_1m.csv);
  - option-chain snapshots from the `chains-2026` release (<date>_<part>_chains.parquet);
  - the learning memory (memory.json) from the journal branch (its CURRENT state: the decision-time state is not kept).
Engine wiring = the repo's own `intraday replay` command (cli.cmd_replay): recorded chains, no news, no brain, no breadth,
no autolearn learner, no research priors (none of these inputs is persisted in replayable form).

Output: per-minute comparison of the replay's thoughts and decisions with the journal's.

    python audit/probes/phase_i_replay.py JOURNAL_DIR CHAINS_DIR 2026-10-05 > out.json
    python audit/probes/phase_i_replay.py JOURNAL_DIR CHAINS_DIR 2026-10-08 --drop-zero-prior-vix > out.json
  (without the flag, 10-06 … 10-09 raise ZeroDivisionError in engine._vix_state: the recorded prior-day VIX is all 0)
"""
import datetime as dt
import json
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from quantdesk.config import Config, DEFAULT_CONFIG  # noqa: E402
from quantdesk.data.archive import load_archive  # noqa: E402
from quantdesk.intraday.chains import COLUMNS, RecordedChains  # noqa: E402
from quantdesk.intraday.engine import IntradayEngine, run_replay  # noqa: E402
from quantdesk.intraday.feeds import ReplayFeed  # noqa: E402
from quantdesk.intraday.learning import Memory  # noqa: E402
from quantdesk.intraday.recorder import SessionRecorder  # noqa: E402
from quantdesk.intraday.sim import IntradayBroker  # noqa: E402
from quantdesk.journal.journal import Journal  # noqa: E402


def snapshots(chains_dir: Path, day: dt.date, unders) -> dict:
    df = load_archive(chains_dir, "chains", start=day, end=day)
    df = df[df["underlying"].isin(unders)]
    out = {}
    for (ts, u, exp), g in df.groupby(["ts", "underlying", "expiry"], sort=True):
        ch = g.set_index("strike").sort_index()
        ch = ch[[c for c in COLUMNS + ["ce_bidq", "ce_askq", "pe_bidq", "pe_askq"] if c in ch.columns]].astype(float)
        ch.attrs.update({"underlying": u, "spot": float(g["spot"].iloc[0]), "expiry": pd.Timestamp(exp).date(),
                         "ts": pd.Timestamp(ts), "source": str(g["source"].iloc[0])})
        out.setdefault(u, []).append(ch)
    return out


def main(journal_dir: Path, chains_dir: Path, day: dt.date, drop_zero_prior_vix: bool = False):
    tmp = Path(tempfile.mkdtemp(prefix="i-replay-"))
    rt = tmp / "rt"
    shutil.copytree(journal_dir / "intraday" / "data", rt / "intraday" / "data",
                    ignore=lambda d, names: [n for n in names if n == "chains"])
    dropped = []
    if drop_zero_prior_vix:          # documented substitution: production read prior days from Yahoo, not these zeros
        for f in sorted((rt / "intraday" / "data").glob("*/INDIAVIX_1m.csv")):
            v = pd.read_csv(f)["close"]
            if f.parent.name < str(day) and (v <= 0).mean() > 0.5:      # ≥ 50 % zero bars (10-05 … 10-07 here)
                f.unlink()
                dropped.append(f.parent.name)
    shutil.copy(journal_dir / "intraday" / "memory.json", tmp / "memory.json")
    cfg = Config.load(DEFAULT_CONFIG, overrides={"runtime": {"dir": str(rt)}})
    unders = cfg.get("intraday.underlyings")
    rec = SessionRecorder(rt / "intraday" / "data")
    bars = rec.load_bars(unders + [cfg.get("universe.volatility_index")], upto=day)
    snaps = snapshots(chains_dir, day, unders)
    j = Journal(tmp / "replay.db")
    eng = IntradayEngine(cfg, ReplayFeed(bars, day), RecordedChains(snaps), j,
                         IntradayBroker(cfg, starting_cash=500000, state_path=tmp / "broker.json"), None, None, None,
                         tmp / "reviews", memory=Memory(tmp / "memory.json"))
    run_replay(eng)
    j.commit()
    with sqlite3.connect(f"file:{journal_dir / 'intraday' / 'journal.db'}?mode=ro", uri=True) as c:
        prod_t = pd.read_sql("SELECT ts, symbol, bias, score, evidence, chain FROM thoughts WHERE substr(ts,1,10)=?", c,
                             params=(str(day),))
        prod_d = pd.read_sql("SELECT ts, strategy, symbol, detail FROM decisions WHERE substr(ts,1,10)=?", c,
                             params=(str(day),))
    rep_t = j.df("SELECT ts, symbol, bias, score, evidence, chain FROM thoughts")
    rep_d = j.df("SELECT ts, strategy, symbol, detail FROM decisions")
    key = lambda d: d.assign(k=d["ts"].astype(str).str[:16] + " " + d["symbol"])  # noqa: E731
    pt, rt_ = key(prod_t).set_index("k"), key(rep_t).drop_duplicates("k").set_index("k")
    common = pt.index.intersection(rt_.index)
    bias_eq, dscore, fac_only_prod, fac_only_rep, sign_agree, fac_n = 0, [], Counter(), Counter(), Counter(), Counter()
    for k in common:
        a, b = pt.loc[k], rt_.loc[k]
        if isinstance(a, pd.DataFrame):
            a = a.iloc[0]
        bias_eq += a["bias"] == b["bias"]
        dscore.append(abs(float(a["score"]) - float(b["score"])))
        ea = {e["factor"]: e["direction"] for e in json.loads(a["evidence"])}
        eb = {e["factor"]: e["direction"] for e in json.loads(b["evidence"])}
        for f in set(ea) - set(eb):
            fac_only_prod[f] += 1
        for f in set(eb) - set(ea):
            fac_only_rep[f] += 1
        for f in set(ea) & set(eb):
            fac_n[f] += 1
            sign_agree[f] += np.sign(ea[f]) == np.sign(eb[f])
    dk = lambda d: Counter((d["ts"].astype(str).str[:16] + " " + d["strategy"] + " " + d["symbol"]).tolist())  # noqa: E731
    pdk, rdk = dk(prod_d), dk(rep_d)
    return {
        "day": str(day), "substitution": {"dropped_all_zero_prior_vix_days": dropped}, "inputs": {"bar_days": sorted({str(x.date()) for x in bars[unders[0]].index}),
                                     "chain_snapshots": {u: len(v) for u, v in snaps.items()}},
        "thoughts": {"production": len(prod_t), "replay": len(rep_t), "same_minute_and_symbol": len(common),
                     "bias_equal": int(bias_eq),
                     "median_abs_score_diff": round(float(np.median(dscore)), 4) if dscore else None,
                     "max_abs_score_diff": round(float(np.max(dscore)), 4) if dscore else None},
        "factors_only_in_production": dict(fac_only_prod.most_common()),
        "factors_only_in_replay": dict(fac_only_rep.most_common()),
        "factor_sign_agreement": {f: f"{sign_agree[f]}/{fac_n[f]}" for f in sorted(fac_n)},
        "decisions": {"production": len(prod_d), "replay": len(rep_d),
                      "same_minute_strategy_symbol": sum((pdk & rdk).values()),
                      "production_only": sum((pdk - rdk).values()), "replay_only": sum((rdk - pdk).values())},
    }


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2]), dt.date.fromisoformat(sys.argv[3]),
                          "--drop-zero-prior-vix" in sys.argv), indent=1, default=str))
