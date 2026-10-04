"""Is the replication of L1 and L2 robust? The audit registered in docs/prereg/expiry_eve_law_v1_audit.json.

It takes the trades of expiry_eve_law_v1, rebuilt from the raw warehouse with the same code, and tries to break the
result. Each check removes one way the result could be an artefact:
- the t-statistic's lag length;
- a lucky stretch of weeks (block bootstrap);
- one instrument carrying the rest (leave one out);
- the cost assumption (costs ×2, ×3, and the break-even multiple);
- stale closing prices on illiquid strikes (a contracts floor);
- one good year, or a regime that has ended (SEBI's one-weekly-per-exchange rule from 20 Nov 2024);
- a few big weeks (the best 5% removed);
- testing two structures (Bonferroni).

The verdict rule is the spec's, fixed before the audit ran. Every check can only weaken the claim.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from . import laws as L
from .edges import hac_mean

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "docs" / "prereg" / "expiry_eve_law_v1_audit.json"
BOOT_REPS, BOOT_BLOCK, SEED = 10_000, 8, 20261004
LAGS = (0, None, 10, 20)                                       # None: the automatic rule
FLOORS = (100, 1000)                                           # contracts traded that day, per strike
REGIME = dt.date(2024, 11, 20)
T_ONE_SIDED, T_BONFERRONI = 1.645, 1.96


def load_spec(path: Path = SPEC_PATH) -> dict:
    raw = Path(path).read_bytes()
    spec = json.loads(raw)
    spec["_hash"] = hashlib.sha256(raw).hexdigest()[:12]
    return spec


def auto_lags(n: int) -> int:
    return max(1, math.floor(4 * (n / 100) ** (2 / 9)))


def weekly(tr: pd.DataFrame, col: str = "bps") -> pd.Series:
    """The pooled series: per ISO expiry week, the mean of `col` across the instruments that traded that week."""
    if tr.empty:
        return pd.Series(dtype=float)
    wk = pd.to_datetime(tr["expiry"]).dt.strftime("%G-%V")
    return tr.assign(wk=wk).groupby("wk")[col].mean().sort_index()


def stationary_bootstrap(x: np.ndarray, block: float = BOOT_BLOCK, reps: int = BOOT_REPS, seed: int = SEED) -> np.ndarray:
    """Politis-Romano: blocks of geometric length (mean `block`), wrapping around; returns each resample's mean."""
    x = np.asarray(x, dtype=float)
    n = len(x)
    rng = np.random.default_rng(seed)
    restart = rng.random((reps, n)) < 1.0 / block
    restart[:, 0] = True
    starts = rng.integers(0, n, size=(reps, n))
    pos = np.broadcast_to(np.arange(n), (reps, n))
    last = np.maximum.accumulate(np.where(restart, pos, 0), axis=1)
    idx = (np.take_along_axis(starts, last, axis=1) + pos - last) % n
    return x[idx].mean(axis=1)


def _mt(w: pd.Series, lags=None) -> dict:
    m, t, _ = hac_mean(w.to_numpy(dtype=float), lags)
    return {"weeks": int(len(w)), "mean_bps": float(m), "t": float(t)}


def audit_structure(h: pd.DataFrame, held: list[str], registered: dict | None, liquid: dict[int, pd.DataFrame]) -> dict:
    """Every check on one structure's held-out trades `h`; `liquid[floor]` are the same structure's trades rebuilt on
    strikes with at least `floor` contracts."""
    w = weekly(h)
    base = _mt(w)
    checks, info = {}, {}

    if registered:
        rp = registered["pooled"]
        same = (base["weeks"] == rp["weeks"] and round(base["mean_bps"], 2) == round(rp["mean_bps"], 2)
                and round(base["t"], 2) == round(rp["t"], 2))
        checks["0_reproduce"] = {"pass": bool(same), "detail": f"rebuilt {base['weeks']} weeks, {base['mean_bps']:+.2f} bps, "
                                 f"t {base['t']:.2f}; registered {rp['weeks']} weeks, {rp['mean_bps']:+.2f} bps, t {rp['t']:.2f}"}

    lag_t = {("auto=" + str(auto_lags(len(w)))) if k is None else str(k): _mt(w, k)["t"] for k in LAGS}
    checks["1_hac_lags"] = {"pass": all(t > T_ONE_SIDED for t in lag_t.values()),
                            "detail": ", ".join(f"lag {k}: t {t:.2f}" for k, t in lag_t.items())}

    boot = stationary_bootstrap(w.to_numpy(dtype=float))
    p5, p50 = float(np.percentile(boot, 5)), float(np.percentile(boot, 50))
    checks["2_block_bootstrap"] = {"pass": p5 > 0, "detail": f"{BOOT_REPS:,} resamples, mean block {BOOT_BLOCK} weeks: "
                                   f"5th pct {p5:+.2f} bps, median {p50:+.2f}, share ≤ 0: {(boot <= 0).mean():.2%}"}

    loo = {s: _mt(weekly(h[h["symbol"] != s])) for s in held if (h["symbol"] == s).any()}
    checks["3_leave_one_out"] = {"pass": bool(loo) and all(r["mean_bps"] > 0 for r in loo.values())
                                 and sum(r["t"] > T_ONE_SIDED for r in loo.values()) >= len(loo) - 1,
                                 "detail": ", ".join(f"−{s}: {r['mean_bps']:+.2f} bps t {r['t']:.2f}" for s, r in loo.items())}

    wc = weekly(h, "cost_bps")
    cost_rows = {m: _mt(weekly(h.assign(adj=h["bps"] - (m - 1) * h["cost_bps"]), "adj")) for m in (2, 3)}
    breakeven = 1 + w.mean() / wc.mean() if wc.mean() > 0 else float("inf")
    checks["4_costs"] = {"pass": cost_rows[2]["mean_bps"] > 0,
                         "detail": f"costs {wc.mean():.2f} bps a week on average; ×2: {cost_rows[2]['mean_bps']:+.2f} bps "
                                   f"(t {cost_rows[2]['t']:.2f}); ×3: {cost_rows[3]['mean_bps']:+.2f} bps "
                                   f"(t {cost_rows[3]['t']:.2f}); break-even at {breakeven:.1f}× costs"}

    liq = {f: _mt(weekly(x)) if len(x) else {"weeks": 0, "mean_bps": float("nan"), "t": float("nan")}
           for f, x in liquid.items()}
    f0 = FLOORS[0]
    checks["5_liquidity"] = {"pass": bool(liq.get(f0) and liq[f0]["mean_bps"] > 0 and liq[f0]["t"] > T_ONE_SIDED),
                             "detail": "; ".join(f"≥{f:,} contracts: {r['weeks']} weeks, {r['mean_bps']:+.2f} bps, t {r['t']:.2f}"
                                                 for f, r in liq.items())}

    yr = {}
    for y, g in h.groupby(pd.to_datetime(h["expiry"]).dt.year):
        wy = weekly(g)
        if len(wy) >= 20:
            yr[int(y)] = _mt(wy)
    pos = sum(r["mean_bps"] > 0 for r in yr.values())
    checks["6_years"] = {"pass": bool(yr) and pos >= 2 / 3 * len(yr),
                         "detail": f"positive in {pos} of {len(yr)} years: " + ", ".join(
                             f"{y} {r['mean_bps']:+.2f} ({r['weeks']}w, t {r['t']:.2f})" for y, r in yr.items())}

    ex = pd.to_datetime(h["expiry"]).dt.date
    now, before = _mt(weekly(h[ex >= REGIME])), _mt(weekly(h[ex < REGIME]))
    checks["7_current_regime"] = {"pass": now["mean_bps"] > 0,
                                  "detail": f"since {REGIME}: {now['weeks']} weeks, {now['mean_bps']:+.2f} bps, t {now['t']:.2f}; "
                                            f"before: {before['weeks']} weeks, {before['mean_bps']:+.2f} bps, t {before['t']:.2f}"}

    k = int(round(0.05 * len(w)))
    trimmed = w.sort_values().iloc[:len(w) - k] if k else w
    checks["8_trim_best_weeks"] = {"pass": float(trimmed.mean()) > 0,
                                   "detail": f"best {k} weeks removed: {trimmed.mean():+.2f} bps (from {w.mean():+.2f})"}

    checks["9_multiple_testing"] = {"pass": base["t"] > T_BONFERRONI,
                                    "detail": f"pooled t {base['t']:.2f} vs Bonferroni bar {T_BONFERRONI}"}

    info["cost_share"] = float(h["cost_bps"].mean() / h["credit_bps"].mean()) if h["credit_bps"].mean() > 0 else float("nan")
    fails = [c for c in checks if c != "0_reproduce" and not checks[c]["pass"]]
    if "0_reproduce" in checks and not checks["0_reproduce"]["pass"]:
        verdict = "found (reproduction failed)"
    elif len(fails) >= 2:
        verdict = "found (downgraded)"
    elif len(fails) == 1:
        verdict = "replicated, with a caveat"
    else:
        verdict = "replicated, robust"
    return {"base": base, "checks": checks, "info": info, "fails": fails, "verdict": verdict}


def coverage(opts: pd.DataFrame, tr: pd.DataFrame, held: list[str], official: dict | None = None) -> dict:
    """Informational: expiries in the data versus trades built, and where each trade's settlement level came from.
    An expiry whose contracts stop trading more than 3 days before its nominal date was re-dated by the exchange (the
    contracts moved to a new expiry weekday): it never reached expiry, so it is counted apart, not as a skip."""
    out = {}
    official = official or {}
    o = opts[opts["kind"].isin(["CE", "PE"])]
    und = opts.dropna(subset=["underlying"])[["symbol", "date"]].drop_duplicates()
    und_keys = set(zip(und["symbol"], pd.to_datetime(und["date"]).dt.date))
    for s in held:
        os_ = o[o["symbol"] == s]
        if os_.empty:
            continue
        last = pd.Timestamp(os_["date"].max())
        seen = os_.groupby("expiry")["date"].max()
        past = [e for e in seen.index if pd.Timestamp(e) <= last]
        redated = [e for e in past if (pd.Timestamp(e) - pd.Timestamp(seen[e])).days > 3]
        real = len(past) - len(redated)
        t = tr[(tr["symbol"] == s)]
        built = int(t["expiry"].nunique()) if len(t) else 0
        src = {"official": 0, "underlying": 0, "future": 0}
        off = official.get(s)
        cal = sorted(set(off.index) if off is not None else set()) or sorted(d for (x, d) in und_keys if x == s)
        for e in (t["expiry"].unique() if len(t) else []):
            e = pd.Timestamp(e).date()
            d = max((x for x in cal if x <= e), default=e)          # the settlement day (holiday-shifted expiries)
            if off is not None and d in off.index:
                src["official"] += 1
            elif (s, d) in und_keys:
                src["underlying"] += 1
            else:
                src["future"] += 1
        out[s] = {"expiries": real, "redated": len(redated), "traded": built,
                  "skip_rate": 1 - built / real if real else None,
                  "settled_on": {k: v / built for k, v in src.items()} if built else None}
    return out


def run(folder: Path, cfg=None, audit_spec: Path = SPEC_PATH) -> dict:
    """The audit registered at `audit_spec`, on the study its `study_spec` key names (expiry_eve_law_v1 by default:
    the first audit predates the key). The study's recorded result is the reproduction target."""
    aspec = load_spec(audit_spec)
    spec = L.load_spec(ROOT / aspec.get("study_spec", "docs/prereg/expiry_eve_law_v1.json"))
    rpath = ROOT / "docs" / "prereg" / "results" / f"{spec['name']}-{spec['_hash']}.json"
    registered = json.loads(rpath.read_text()) if rpath.exists() else None
    held = spec["held_out"]["instruments"]
    opts = L.load(folder, spec)
    fees_for = L.fees_factory(cfg)
    official = L.official_closes(folder, spec)
    tr = L.all_trades(opts, spec, held, fees_for, cfg, official)
    liquid = {}
    for f in FLOORS:
        thin = opts["kind"].isin(["CE", "PE"]) & (opts["contracts"] < f)
        liquid[f] = L.all_trades(opts[~thin], spec, held, fees_for, cfg, official)
    res = {"spec": aspec["name"], "spec_hash": aspec["_hash"], "audits": f"{spec['name']} ({spec['_hash']})",
           "structures": {}, "coverage": coverage(opts, tr[tr["strategy"] == "short_strangle_20d"] if len(tr) else tr, held,
                                                   official)}
    for key, v in spec["structures"].items():
        h = tr[tr["strategy"] == v["strategy"]] if len(tr) else tr
        liq = {f: (x[x["strategy"] == v["strategy"]] if len(x) else x) for f, x in liquid.items()}
        reg = registered["structures"].get(key) if registered else None
        res["structures"][key] = {"principle": aspec["applies_to"].get(key), "strategy": v["strategy"],
                                  **audit_structure(h, held, reg, liq)}
    return res


def render(res: dict) -> str:
    out = [f"# Robustness audit of L1 and L2 · {res['spec']} · spec {res['spec_hash']}", "",
           f"Audits {res['audits']}: the same trades, rebuilt from the raw warehouse, put through ten checks fixed "
           "before the audit ran. Every check can only weaken the claim.", ""]
    for key, s in res["structures"].items():
        b = s["base"]
        out += [f"## {s['principle']} · {key} ({s['strategy']}): **{s['verdict']}**", "",
                f"Pooled held-out series: {b['weeks']} weeks, {b['mean_bps']:+.2f} bps a week, t {b['t']:.2f}. "
                f"Trading costs are {s['info']['cost_share']:.0%} of the premium sold.", "",
                "| check | result | detail |", "|---|---|---|"]
        for name, c in s["checks"].items():
            out.append(f"| {name} | {'✅ pass' if c['pass'] else '❌ fail'} | {c['detail']} |")
        out += ["", f"Failed: {', '.join(s['fails']) or 'none'}.", ""]
    out += ["## Coverage (informational)", "",
            "| instrument | expiries that reached expiry | re-dated by the exchange | traded | skipped | settled on: official close / file's underlying / nearest future |",
            "|---|---:|---:|---:|---:|---|"]
    for sym, c in res["coverage"].items():
        sk = "–" if c["skip_rate"] is None else f"{c['skip_rate']:.0%}"
        so = c.get("settled_on")
        su = "–" if not so else " / ".join(f"{so[k]:.0%}" for k in ("official", "underlying", "future"))
        out.append(f"| {sym} | {c['expiries']} | {c.get('redated', 0)} | {c['traded']} | {sk} | {su} |")
    out += ["", "A nearest future is the index itself only when it expires that day; on a weekly expiry it is the monthly "
            "future, basis and all (the flaw expiry_eve_law_v2 corrects).", ""]
    return "\n".join(out)
