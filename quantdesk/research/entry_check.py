"""expiry_eve_entry_v1 (docs/prereg/expiry_eve_entry_v1.json): is the history's entry price executable?

L1's history sells each leg at the eve's bhavcopy close minus a modelled cost (warehouse_research.leg_cost). The forward
sleeves (intraday/sleeves.py) sell the same rule's strikes at the real 15:20 bid minus a tick. For every eve a sleeve
opened, this pairs the two on the same two short strikes:

    d_bps = history credit (bps of the eve's official close) - executable credit (bps of the 15:20 index)

Positive d means the history assumed a better sale than the market offered. The test runs on the weekly series, once,
at the registered decision point. Until then the report shows counts only: nobody, the engineer included, can watch the
mean and stop when it looks good.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .edges import hac_mean
from .warehouse_research import leg_cost

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "docs" / "prereg" / "expiry_eve_entry_v1.json"
Z_POWER = 0.842                     # one-sided 80% power


def load_spec(path: Path = SPEC_PATH) -> dict:
    raw = Path(path).read_bytes()
    spec = json.loads(raw)
    spec["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return spec


# ---- the executable side: the sleeves' open events ----------------------------------------------------------------
def ledger_events(folder: Path) -> list[dict]:
    out = []
    for p in sorted(Path(folder).glob("*.jsonl")):
        out += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    return out


def eves(events: list[dict], spec: dict) -> pd.DataFrame:
    """One row per instrument and expiry from the earliest open event for it: its two short target-delta legs, the
    15:20 index, and the registered settlement if the trade has settled."""
    pop = spec["population"]
    start, target = dt.date.fromisoformat(pop["from"]), float(pop["target_delta"])
    settle = {e["id"]: e for e in events if e.get("event") == "settle"}
    rows, seen = [], set()
    for e in sorted((e for e in events if e.get("event") == "open"), key=lambda e: str(e.get("recorded_at", ""))):
        u, exp, day = e["underlying"], e["expiry"], dt.date.fromisoformat(e["day"])
        if u not in pop["instruments"] or day < start or (u, exp) in seen:
            continue
        short = {x["right"]: x for x in e["legs"] if x["qty"] < 0 and abs(abs(float(x["target"])) - target) < 1e-9}
        if set(short) != {"CE", "PE"}:
            continue
        seen.add((u, exp))
        spot = float(e["spot"])
        s = settle.get(e["id"], {})
        rows.append({"underlying": u, "expiry": dt.date.fromisoformat(exp), "day": day, "id": e["id"], "spot": spot,
                     "ce_strike": float(short["CE"]["strike"]), "pe_strike": float(short["PE"]["strike"]),
                     "ce_fill": float(short["CE"]["fill"]), "pe_fill": float(short["PE"]["fill"]),
                     "executable_credit_bps": (float(short["CE"]["fill"]) + float(short["PE"]["fill"])) / spot * 1e4,
                     "settle_registered": float(s["settle"]) if "settle" in s else float("nan")})
    return pd.DataFrame(rows)


# ---- the history's side: the warehouse --------------------------------------------------------------------------
def load_history(folder: Path, ev: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """The bhavcopy rows of the eves' instruments on the eve and expiry days, and NSE's official closes by symbol."""
    import pyarrow.parquet as pq
    folder = Path(folder)
    days = sorted(set(ev["day"]) | set(ev["expiry"])) if len(ev) else []
    months = sorted({f"{d:%Y-%m}" for d in days})
    parts = []
    for t in ("fo_bhav", "bse_fo_bhav"):
        for m in months:
            f = folder / f"{t}_{m}.parquet"
            if f.exists():
                parts.append(pq.read_table(f, columns=["date", "symbol", "kind", "expiry", "strike", "close", "underlying",
                                                       "contracts"],
                                           filters=[("symbol", "in", sorted(set(ev["underlying"])))]).to_pandas())
    opts = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(
        columns=["date", "symbol", "kind", "expiry", "strike", "close", "underlying", "contracts"])
    for c in ("date", "expiry"):
        opts[c] = pd.to_datetime(opts[c]).dt.date
    opts = opts[opts["date"].isin(days)]
    official: dict[str, dict] = {}
    for y in sorted({d.year for d in days}):
        f = folder / f"nse_index_close_{y}.parquet"
        if f.exists():
            ic = pd.read_parquet(f, columns=["date", "symbol", "close"])
            ic = ic[ic["symbol"].astype(str) != ""]
            for s, g in ic.groupby("symbol"):
                official.setdefault(s, {}).update(dict(zip(pd.to_datetime(g["date"]).dt.date, g["close"].astype(float))))
    return opts, official


def _level(opts: pd.DataFrame, official: dict, symbol: str, day: dt.date) -> tuple[float | None, str]:
    """The index level the history uses: NSE's official close, else the bhavcopy's own underlying (BSE)."""
    v = official.get(symbol, {}).get(day)
    if v is not None and v > 0:
        return float(v), "nse_index_close"
    u = pd.to_numeric(opts.loc[(opts["symbol"] == symbol) & (opts["date"] == day), "underlying"], errors="coerce").dropna()
    u = u[u > 0]
    return (float(u.median()), "bhavcopy underlying") if len(u) else (None, "no index level")


def pair(ev: pd.DataFrame, opts: pd.DataFrame, official: dict) -> pd.DataFrame:
    """Each eve with its history-convention credit on the same strikes, d_bps, and (secondary) the payouts."""
    rows = []
    for r in ev.itertuples(index=False):
        out = r._asdict()
        g = opts[(opts["symbol"] == r.underlying) & (opts["date"] == r.day) & (opts["expiry"] == r.expiry)]
        credit, why = 0.0, ""
        for right, K in (("CE", r.ce_strike), ("PE", r.pe_strike)):
            x = g[(g["kind"] == right) & np.isclose(g["strike"].astype(float), K)]
            c = pd.to_numeric(x["close"], errors="coerce")
            n = pd.to_numeric(x["contracts"], errors="coerce").fillna(0)
            ok = x[(c > 0) & (n > 0)]
            if ok.empty:
                why = f"{right} {K:.0f}: no traded bhavcopy row on the eve" if len(g) else "no bhavcopy for the eve yet"
                break
            px = float(pd.to_numeric(ok["close"]).iloc[0])
            credit += px - float(leg_cost(px))
        level, src = _level(opts, official, r.underlying, r.day)
        if not why and level is None:
            why = "no index level for the eve"
        out.update({"history_level": level, "history_level_source": src})
        if why:
            out.update({"excluded": why, "history_credit_bps": float("nan"), "d_bps": float("nan")})
        else:
            h = credit / level * 1e4
            out.update({"excluded": "", "history_credit_bps": h, "d_bps": h - r.executable_credit_bps})
        s_t, _ = _level(opts, official, r.underlying, r.expiry)
        out.update({"settle_official": s_t if s_t is not None else float("nan"),
                    "payout_official_bps": _payout(r, s_t), "payout_registered_bps": _payout(r, r.settle_registered)})
        rows.append(out)
    return pd.DataFrame(rows)


def _payout(r, s_t) -> float:
    """What the two short legs owe at settlement level s_t, in bps of the entry index."""
    if s_t is None or not math.isfinite(s_t):
        return float("nan")
    return (max(s_t - r.ce_strike, 0.0) + max(r.pe_strike - s_t, 0.0)) / r.spot * 1e4


# ---- the registered decision ------------------------------------------------------------------------------------
def _weekly(p: pd.DataFrame) -> pd.Series:
    wk = pd.to_datetime(p["expiry"]).dt.strftime("%G-%V")
    return p.assign(wk=wk).groupby("wk")["d_bps"].mean().sort_index()


def _decision_point(p: pd.DataFrame, n: int, min_weeks: int) -> int | None:
    """The smallest m >= n such that the first m eves span at least `min_weeks` expiry weeks, if reached."""
    wk = pd.to_datetime(p["expiry"]).dt.strftime("%G-%V").tolist()
    seen: set = set()
    for i, w in enumerate(wk, 1):
        seen.add(w)
        if i >= n and len(seen) >= min_weeks:
            return i
    return None


def _classify(p: pd.DataFrame, margin: float, crit: float) -> dict:
    w = _weekly(p).to_numpy(dtype=float)
    m, _, _ = hac_mean(w)
    t_hi = hac_mean(w - margin)[1]            # Newey-West se ignores a shift of the mean: t of (d - margin)
    t_lo = hac_mean(w + margin)[1]
    verdict = ("overstated" if t_hi > crit else "understated" if t_lo < -crit
               else "equivalent" if (t_lo > crit and t_hi < -crit) else "inconclusive")
    return {"eves": int(len(p)), "weeks": int(len(w)), "mean_d_bps": round(float(m), 3),
            "eve_mean_d_bps": round(float(p["d_bps"].mean()), 3), "eve_sd_d_bps": round(float(p["d_bps"].std(ddof=1)), 3),
            "t_vs_plus_margin": round(float(t_hi), 3), "t_vs_minus_margin": round(float(t_lo), 3), "verdict": verdict}


def decide(paired: pd.DataFrame, spec: dict) -> dict:
    ss, ts = spec["sample_size"], spec["test"]
    inc = paired[paired["d_bps"].notna()].sort_values(["day", "underlying"]).reset_index(drop=True) if len(paired) else paired
    n, cap = int(ss["n_eves"]), int(ss["n_cap"])
    k = int(len(inc))
    weeks = int(pd.to_datetime(inc["expiry"]).dt.strftime("%G-%V").nunique()) if k else 0
    res = {"eves": k, "excluded": int(len(paired) - k), "weeks": weeks, "n": n, "min_weeks": int(ss["min_weeks"])}
    if not k:
        return {**res, "status": "collecting"}
    if k >= int(ss["reestimate_after_eves"]):
        sd10 = float(inc["d_bps"].iloc[:int(ss["reestimate_after_eves"])].std(ddof=1))
        need = math.ceil(float(ss["reestimate_inflation"]) * ((float(ts["t_critical"]) + Z_POWER) * sd10
                                                              / float(ts["margin_bps"])) ** 2)
        n = min(cap, max(n, need))
        res.update({"n": n, "reestimated": True})
    m = _decision_point(inc, n, int(ss["min_weeks"]))
    if m is None:
        return {**res, "status": "collecting"}
    first = _classify(inc.iloc[:m], float(ts["margin_bps"]), float(ts["t_critical"]))
    if first["verdict"] != "inconclusive":
        return {**res, "status": "decided", "decided_at": m, "result": first}
    n2 = min(cap, max(int(ss["extend_once_to"]), n))
    m2 = _decision_point(inc, n2, int(ss["min_weeks"])) if n2 > m else None
    if n2 <= m:
        return {**res, "status": "decided", "decided_at": m, "result": first, "extension": "none possible (at the cap)"}
    if m2 is None:
        return {**res, "status": "extended: collecting", "first_look_at": m, "n": n2}
    final = _classify(inc.iloc[:m2], float(ts["margin_bps"]), float(ts["t_critical"]))
    return {**res, "status": "decided", "n": n2, "first_look_at": m, "first_look": first, "decided_at": m2, "result": final}


def run(warehouse: Path, sleeves: Path, spec_path: Path = SPEC_PATH) -> tuple[dict, pd.DataFrame]:
    spec = load_spec(spec_path)
    ev = eves(ledger_events(sleeves), spec)
    opts, official = load_history(warehouse, ev) if len(ev) else (pd.DataFrame(), {})
    paired = pair(ev, opts, official) if len(ev) else pd.DataFrame()
    res = {"spec": spec["name"], "spec_hash": spec["_hash"], **decide(paired, spec)}
    res["exclusions"] = (paired.loc[paired["excluded"] != "", "excluded"].str.replace(r"\d+", "#", regex=True)
                         .value_counts().to_dict() if len(paired) else {})
    res["by_instrument"] = (paired.groupby("underlying").size().to_dict() if len(paired) else {})
    done = paired.dropna(subset=["payout_official_bps", "payout_registered_bps"]) if len(paired) else paired
    res["secondary_settlement"] = ({"trades": int(len(done)), "mean_payout_gap_bps": round(float(
        (done["payout_registered_bps"] - done["payout_official_bps"]).mean()), 3)} if len(done) else {"trades": 0})
    if res["status"] == "decided":
        cut = paired[paired["d_bps"].notna()].sort_values(["day", "underlying"]).iloc[:res["decided_at"]]
        res["per_instrument"] = {u: {"eves": int(len(g)), "mean_d_bps": round(float(g["d_bps"].mean()), 3)}
                                 for u, g in cut.groupby("underlying")}
        res["decision"] = spec["decision"][res["result"]["verdict"]]
    return res, paired


def render(res: dict) -> str:
    out = [f"# Is the history's entry price executable? · {res['spec']} · spec {res['spec_hash']}", "",
           f"Status: **{res['status']}**. Eves paired: {res['eves']} (excluded {res['excluded']}), over {res['weeks']} "
           f"expiry weeks. Decision point: {res['n']} eves and {res['min_weeks']} weeks"
           + (" (n re-estimated after 10 eves, as registered)" if res.get("reestimated") else "") + ".", ""]
    if res["status"] != "decided":
        out += ["No mean, spread or t is shown before the decision point (the spec's interim rule).", ""]
    else:
        r = res["result"]
        if "first_look" in res:
            f = res["first_look"]
            out += [f"First look at {res['first_look_at']} eves: {f['verdict']} (weekly mean d {f['mean_d_bps']:+.2f} bps, "
                    f"t vs +2 {f['t_vs_plus_margin']:+.2f}, t vs -2 {f['t_vs_minus_margin']:+.2f}); extended once, as "
                    "registered.", ""]
        out += [f"**Verdict at {res['decided_at']} eves: {r['verdict']}.** Weekly mean d {r['mean_d_bps']:+.2f} bps over "
                f"{r['weeks']} weeks (per eve {r['eve_mean_d_bps']:+.2f}, sd {r['eve_sd_d_bps']:.2f}); t of (d − 2) "
                f"{r['t_vs_plus_margin']:+.2f}, t of (d + 2) {r['t_vs_minus_margin']:+.2f}, critical 1.645.", "",
                f"What follows (fixed in the spec): {res['decision']}.", "",
                "| instrument | eves | mean d, bps |", "|---|---:|---:|"]
        out += [f"| {u} | {v['eves']} | {v['mean_d_bps']:+.2f} |" for u, v in res["per_instrument"].items()]
        out.append("")
    if res.get("by_instrument"):
        out += ["Eves by instrument (all, incl. excluded): " + ", ".join(f"{u} {n}" for u, n in res["by_instrument"].items()), ""]
    if res.get("exclusions"):
        out += ["Excluded: " + "; ".join(f"{k} ({v})" for k, v in res["exclusions"].items()), ""]
    s = res.get("secondary_settlement") or {}
    if s.get("trades"):
        out += [f"Secondary (not tested): on {s['trades']} settled eves, the short legs owed {s['mean_payout_gap_bps']:+.2f} "
                "bps more on average at the sleeves' registered 15:00–15:29 settlement than at the official close "
                "(positive: the registered rule cost the seller).", ""]
    return "\n".join(out)
