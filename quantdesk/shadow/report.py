"""Summary, frequency plausibility, and the quarterly Parquet shards (`shadow-setups-YYYYQn`)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

NOT_INDEPENDENT = ("NOTE: these setups are NOT independent samples. NIFTY, BANKNIFTY, SENSEX, FINNIFTY and MIDCPNIFTY move "
                   "together, and several setups can fire on the same move; win rate and mean P&L below are descriptive "
                   "counts, not an edge estimate.")


def frequency(df: pd.DataFrame, usable: dict[str, int], ratio: float, ref=("NIFTY", "BANKNIFTY")) -> dict:
    """Setups per usable session per instrument against the NIFTY/BANKNIFTY median; flagged when `ratio`x more or less often.
    A flag is a sign the detector thresholds do not scale to that instrument. Nothing is tuned."""
    per = {}
    for n, sessions in usable.items():
        k = int((df["instrument"] == n).sum()) if len(df) else 0
        per[n] = {"setups": k, "sessions": sessions, "per_session": (k / sessions) if sessions else None}
    base = [v["per_session"] for n, v in per.items() if n in ref and v["per_session"]]
    med = float(np.median(base)) if base else None
    for n, v in per.items():
        if med is None or v["per_session"] is None:
            v["flag"] = "no NIFTY/BANKNIFTY baseline" if med is None and n not in ref else None
            continue
        if n in ref:
            v["flag"] = None
        elif v["per_session"] == 0:
            v["flag"] = f"fires 0 setups where the index median is {med:.2f} per session: thresholds may not scale"
        else:
            x = v["per_session"] / med
            v["flag"] = (f"fires {x:.1f}x as often as the NIFTY/BANKNIFTY median ({med:.2f}/session): thresholds may not scale"
                         if x >= ratio or x <= 1 / ratio else None)
    return {"median_index_per_session": med, "ratio": ratio, "per_instrument": per}


def summary(df: pd.DataFrame, quality: dict, ratio: float = 5.0) -> str:
    L = ["", "Shadow replay summary", ""]
    usable = {n: len(r["usable"]) for n, r in quality.items()}
    freq = frequency(df, usable, ratio)
    L.append(f"  {'instrument':<11} {'sessions':>8} {'setups':>6} {'labelled':>8} {'unlabelled':>10} {'win%net':>8} {'mean net':>10}  plausibility")
    for n, r in quality.items():
        sub = df[df["instrument"] == n] if len(df) else df
        lab = sub[sub["status"] == "labelled"] if len(sub) else sub
        win = f"{(lab['net_pnl'] > 0).mean():.0%}" if len(lab) else "-"
        mean = f"{lab['net_pnl'].mean():+,.0f}" if len(lab) else "-"
        fl = freq["per_instrument"][n]["flag"]
        tag = "EXCLUDED: " + r["instrument_excluded"] if r["instrument_excluded"] else ("FLAG: " + fl if fl else "ok")
        L.append(f"  {n:<11} {len(r['usable']):>3}/{len(r['sessions']):<4} {len(sub):>6} {len(lab):>8} {len(sub) - len(lab):>10} "
                 f"{win:>8} {mean:>10}  {tag}")
    if len(df):
        un = df[df["status"] != "labelled"]
        L += ["", "  Unlabelled by reason (the underlying label u_* may still exist; no price is ever made up):"]
        for why, k in un["unlabelled_reason"].fillna("?").str.replace(r"\d+(\.\d+)?[CP]E.*", "<leg>", regex=True).value_counts().items():
            L.append(f"    {k:>5}  {why}")
        L += ["", "  By setup type:"]
        for s, g in df.groupby("setup"):
            lab = g[g["status"] == "labelled"]
            L.append(f"    {s:<13} {len(g):>4} setups, {len(lab):>4} labelled"
                     + (f", {(lab['net_pnl'] > 0).mean():.0%} net wins, mean net {lab['net_pnl'].mean():+,.0f} per lot" if len(lab) else ""))
        blocked = df[~df["accepted_by_live_ceilings"]]
        L += ["", f"  Live ceilings would have blocked {len(blocked)} of {len(df)} setups "
                  f"({', '.join(f'{k} {v}' for k, v in blocked['would_have_been_refused_by'].str.split(',').explode().value_counts().items()) or 'none'}); "
                  f"they stay in the data, flagged."]
        if bool(df["lot_unverified"].any()):
            L.append("  Lot size unverified for: " + ", ".join(sorted(df[df["lot_unverified"]]["instrument"].unique())) + " (rupee P&L per lot is indicative)")
    L += ["", "  " + NOT_INDEPENDENT]
    return "\n".join(L)


def shard_name(day: dt.date) -> str:
    return f"shadow-setups-{day.year}Q{(day.month - 1) // 3 + 1}"


def write_shards(df: pd.DataFrame, out_dir: Path, replayed: dict[str, set[str]], store_for=None, say=print) -> list[str]:
    """One Parquet per quarter. Rows already in a shard for an (instrument, session) this run replayed are replaced; everything
    else is kept, so a partial re-run never loses other days. `replayed`: {instrument: {session, ...}} that passed the data
    checks. With `store_for(tag)` (a warehouse.ReleaseStore) the shard is pulled first, merged, and pushed under the same name."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    quarters = sorted({shard_name(dt.date.fromisoformat(s)) for v in replayed.values() for s in v})
    written = []
    for q in quarters:
        name = f"{q}.parquet"
        old = pd.DataFrame()
        if store_for:
            store_for(q).pull(out_dir, [name])
        if (out_dir / name).exists():
            old = pd.read_parquet(out_dir / name)
        new = df[df["session"].map(lambda s: shard_name(dt.date.fromisoformat(s)) == q)] if len(df) else df
        if len(old):
            drop = old.apply(lambda r: r["session"] in replayed.get(r["instrument"], set()), axis=1)
            old = old[~drop]
        merged = pd.concat([old, new], ignore_index=True) if len(old) or len(new) else new
        if not len(merged):
            continue
        merged = merged.drop_duplicates("setup_id", keep="last").sort_values(["session", "decision_time", "instrument", "setup"])
        merged.reset_index(drop=True).to_parquet(out_dir / name, index=False, compression="zstd")
        written.append(name)
        say(f"  wrote {name}: {len(merged):,} rows")
        if store_for:
            store_for(q).push(out_dir, [name], clobber=True)          # clobbers only the identical asset name
            say(f"  pushed {name} to release {q}")
    return written
