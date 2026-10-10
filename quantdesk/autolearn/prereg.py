"""Pre-registered intraday direction tests on the external index minutes (docs/prereg/intraday_direction_v1.json).

The spec fixes the hypotheses, the statistic, the dev / lock split and both decision rules before any of these tests
touch the data. Its sha256 is recorded with the results. The lock period is evaluated once: `run(..., open_lock=True)`
refuses when the results file for this spec already holds a lock result.

One trade a day at most per test, so days are the unit and nothing overlaps. This is direction research on index prices
(the dataset's ALLOWED_USES). There are no option prices here, so nothing in it qualifies an option strategy, a DTE
change, the paper gate, a promotion, or a profitability claim. The futures round trip is shown only as the size a move
would have to beat.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..data import external_aeron as X
from .evaluate import CostModel

TESTS = ["H1_intraday_momentum", "H2_first_half_hour_ex_gap", "H3_first_hour_continuation", "H4_large_gap",
         "H5_opening_range_breakout", "H6_momentum_high_vol", "H7_first_hour_high_vol"]
NW_LAGS = 5
GAP_MIN = 0.005
Q = 0.05


def spec_hash(path: Path) -> str:
    return hashlib.sha256(json.dumps(json.loads(Path(path).read_text()), sort_keys=True).encode()).hexdigest()


def _at(bars: pd.DataFrame, day: dt.date, hhmm: str) -> float:
    """Close of the 5-minute bar that ends at hh:mm (starts five minutes earlier)."""
    t = pd.Timestamp(f"{day} {hhmm}", tz=X.IST) - pd.Timedelta(minutes=5)
    return float(bars["close"].get(t, np.nan))


def day_table(bars5: pd.DataFrame) -> pd.DataFrame:
    """One row per session: the prices each hypothesis needs, the gap, prior realised vol and the H5 breakout."""
    b = bars5.sort_index()
    rows = []
    for day, g in b.groupby(b.index.date):
        g = g.droplevel(0) if isinstance(g.index, pd.MultiIndex) else g
        first, last = g.index[0], g.index[-1]
        if first.strftime("%H:%M") != "09:15" or last.strftime("%H:%M") != "15:25":
            continue
        orng = g.between_time("09:15", "09:40")
        after = g.between_time("09:45", "13:55")
        hi, lo = orng["high"].max(), orng["low"].min()
        brk = after[(after["close"] > hi) | (after["close"] < lo)]
        o_sig, o_px = 0, np.nan
        if len(brk):
            o_sig, o_px = (1 if brk["close"].iloc[0] > hi else -1), float(brk["close"].iloc[0])
        rows.append({"day": day, "open": float(g["open"].iloc[0]), "close": float(g["close"].iloc[-1]),
                     "p0920": _at(g, day, "09:20"), "p0945": _at(g, day, "09:45"), "p1015": _at(g, day, "10:15"),
                     "p1500": _at(g, day, "15:00"), "orb_sig": o_sig, "orb_px": o_px})
    d = pd.DataFrame(rows).set_index("day")
    if d.empty:
        return d
    gap_days = pd.Series(pd.to_datetime(d.index)).diff().dt.days.to_numpy()
    d["prev_close"] = d["close"].shift(1).where(gap_days <= 4)       # a rejected session in between: no previous close
    d["ret_cc"] = np.log(d["close"] / d["prev_close"])
    d["rv20"] = d["ret_cc"].rolling(20, min_periods=15).std().shift(1) * np.sqrt(252)
    d["gap"] = np.log(d["open"] / d["prev_close"])
    return d


def trades(d: pd.DataFrame, test: str, vol_cut: float | None = None) -> pd.DataFrame:
    """Per day: the signal and the trade's log return (signal × return is the test's r)."""
    if test in ("H1_intraday_momentum", "H6_momentum_high_vol"):
        sig, entry, exit_ = np.sign(np.log(d["p0945"] / d["prev_close"])), d["p1500"], d["close"]
    elif test == "H2_first_half_hour_ex_gap":
        sig, entry, exit_ = np.sign(np.log(d["p0945"] / d["open"])), d["p1500"], d["close"]
    elif test in ("H3_first_hour_continuation", "H7_first_hour_high_vol"):
        sig, entry, exit_ = np.sign(np.log(d["p1015"] / d["open"])), d["p1015"], d["close"]
    elif test == "H4_large_gap":
        sig = np.sign(d["gap"]).where(d["gap"].abs() >= GAP_MIN, 0.0)
        entry, exit_ = d["p0920"], d["close"]
    elif test == "H5_opening_range_breakout":
        sig, entry, exit_ = d["orb_sig"].astype(float), d["orb_px"], d["close"]
    else:
        raise KeyError(test)
    out = pd.DataFrame({"signal": sig, "entry": entry, "ret": np.log(exit_ / entry)}, index=d.index)
    if test in ("H6_momentum_high_vol", "H7_first_hour_high_vol"):
        out = out[d["rv20"] >= vol_cut]
    out = out[(out["signal"] != 0) & np.isfinite(out["ret"]) & np.isfinite(out["signal"])]
    out["r"] = out["signal"] * out["ret"]
    return out


def nw_t(r: np.ndarray, lags: int = NW_LAGS) -> float:
    r = np.asarray(r, float)
    n = len(r)
    if n < 10:
        return float("nan")
    e = r - r.mean()
    var = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(r.mean() / np.sqrt(var / n)) if var > 0 else float("nan")


def _p_two(t: float) -> float:
    from scipy.stats import norm
    return float(2 * norm.sf(abs(t))) if t == t else float("nan")


def bh(p: dict[str, float]) -> dict[str, float]:
    keys = [k for k, v in p.items() if v == v]
    ps = np.array([p[k] for k in keys])
    order = np.argsort(ps)
    m = len(ps)
    q = np.empty(m)
    run = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        run = min(run, ps[i] * m / rank)
        q[i] = run
    return {k: float(q[i]) for i, k in enumerate(keys)}


def stats(t: pd.DataFrame, hurdle: float) -> dict:
    r = t["r"].to_numpy(float)
    tt = nw_t(r)
    mean = float(r.mean() * 1e4) if len(r) else float("nan")
    return {"days": int(len(r)), "mean_bps": mean, "t_nw": tt, "p_two": _p_two(tt),
            "hit_rate": float((r > 0).mean()) if len(r) else None, "mean_abs_bps": float(np.abs(t["ret"]).mean() * 1e4) if len(r) else None,
            "cost_hurdle_bps": hurdle, "net_bps": mean - hurdle if len(r) else None,
            "by_year": {str(y): round(float(g["r"].mean() * 1e4), 2) for y, g in t.groupby(pd.to_datetime(t.index).year)}}


def run(cfg, ds: Path, spec_path: Path, results_dir: Path, open_lock: bool = False, say=print) -> dict:
    spec = json.loads(Path(spec_path).read_text())
    h = spec_hash(spec_path)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{spec['name']}-{h[:12]}.json"
    prior = json.loads(out_path.read_text()) if out_path.exists() else {}
    if open_lock and prior.get("lock"):
        raise RuntimeError(f"the lock for {spec['name']} ({h[:12]}) was opened on {prior['lock']['opened']}: never again")
    cost = CostModel.from_cfg(cfg)
    bars = X.load(ds, "5m", spec["symbols"], use="direction_research")
    dev0, dev1 = (dt.date.fromisoformat(spec["dev"][k]) for k in ("start", "end"))
    lk0, lk1 = (dt.date.fromisoformat(spec["lock"][k]) for k in ("start", "end"))
    rep = {"spec": spec["name"], "spec_sha256": h, "dataset": bars.attrs.get("dataset"), "evidence": bars.attrs.get("status"),
           "not_for": spec["not_for"], "dev": {}, "selected": [], "sessions": {}}
    tables, cuts = {}, {}
    for sym in spec["symbols"]:
        b = bars[bars["symbol"] == sym].drop(columns=["symbol"]) if "symbol" in bars.columns else bars
        d = day_table(b)
        idx = pd.Index(d.index)
        dev = d[(idx >= dev0) & (idx <= dev1)]
        lock = d[(idx >= lk0) & (idx <= lk1)]
        tables[sym] = (dev, lock)
        cuts[sym] = float(dev["rv20"].dropna().quantile(2 / 3))
        rep["sessions"][sym] = {"dev": int(len(dev)), "dev_range": [str(dev.index.min()), str(dev.index.max())],
                                "lock": int(len(lock)), "lock_range": [str(lock.index.min()), str(lock.index.max())],
                                "rv20_top_tercile_cut": cuts[sym]}
    p = {}
    for sym, (dev, _) in tables.items():
        for test in TESTS:
            t = trades(dev, test, cuts[sym])
            hurdle = cost.round_trip_bps(float(t["entry"].median()), sym) if len(t) else float("nan")
            s = stats(t, hurdle)
            rep["dev"][f"{test} {sym}"] = s
            p[f"{test} {sym}"] = s["p_two"]
    q = bh(p)
    for k, s in rep["dev"].items():
        s["bh_q"] = q.get(k)
        s["selected"] = bool(s["bh_q"] is not None and s["bh_q"] < Q and abs(s["mean_bps"]) > s["cost_hurdle_bps"])
        s["direction"] = ("follow" if s["mean_bps"] > 0 else "fade") if s["selected"] else None
        if s["selected"]:
            rep["selected"].append(k)
        say(f"  dev {k:40s} days {s['days']:5d} mean {s['mean_bps']:+7.2f} bps t {s['t_nw']:+5.2f} q {s['bh_q']:.3f} "
            f"hurdle {s['cost_hurdle_bps']:.1f}{'  SELECTED ' + s['direction'] if s['selected'] else ''}")
    rep["lock"] = prior.get("lock")
    same = lambda x: json.dumps(json.loads(json.dumps({k: v for k, v in x.items() if k not in ("lock", "path")},
                                                      default=str)), sort_keys=True)
    if prior.get("lock") and same(prior) != same(rep):
        # the result is frozen once its lock is opened: a re-run on other data, code or costs must not rewrite any of it
        # (dev results, selection, dataset, evidence, session counts) under a lock test that was run on the old one
        raise RuntimeError(f"{out_path.name}: the lock was opened on {prior['lock'].get('opened')} and this re-run's "
                           f"results differ (data, code or costs changed): the result is frozen; register a new spec")
    if open_lock:
        from scipy.stats import norm
        res = {"opened": pd.Timestamp.now(tz=X.IST).isoformat(), "tests": {}}
        for k in rep["selected"]:
            test, sym = k.rsplit(" ", 1)
            t = trades(tables[sym][1], test, cuts[sym])
            sgn = 1 if rep["dev"][k]["direction"] == "follow" else -1
            t = t.assign(r=t["r"] * sgn)
            hurdle = cost.round_trip_bps(float(t["entry"].median()), sym) if len(t) else float("nan")
            s = stats(t, hurdle)
            s["direction"] = rep["dev"][k]["direction"]
            s["p_one"] = float(norm.sf(s["t_nw"])) if s["t_nw"] == s["t_nw"] else None
            s["passed"] = bool(s["p_one"] is not None and s["p_one"] < 0.05 and (s["net_bps"] or 0) > 0)
            res["tests"][k] = s
            say(f"  LOCK {k:40s} days {s['days']:5d} mean {s['mean_bps']:+7.2f} bps t {s['t_nw']:+5.2f} "
                f"net {s['net_bps'] if s['net_bps'] is None else round(s['net_bps'], 2)} {'PASS' if s['passed'] else 'fail'}")
        if not rep["selected"]:
            res["note"] = "no test was selected on dev: nothing to evaluate; the lock is spent"
        rep["lock"] = res
    out_path.write_text(json.dumps(rep, indent=1, default=str))
    rep["path"] = str(out_path)
    return rep


def render(rep: dict) -> str:
    L = [f"# Pre-registered intraday direction tests: {rep['spec']}", "",
         f"Spec sha256 `{rep['spec_sha256']}` · dataset {rep['dataset']} · **evidence: {rep['evidence']}** · {rep['not_for']}.", ""]
    for sym, s in rep["sessions"].items():
        L.append(f"- {sym}: dev {s['dev']} sessions ({s['dev_range'][0]} → {s['dev_range'][1]}), lock {s['lock']} "
                 f"({s['lock_range'][0]} → {s['lock_range'][1]}); high-vol cut (rv20, dev top tercile) {s['rv20_top_tercile_cut']:.1%}")
    L += ["", "## Development period: every test", "",
          "| test | days | mean (bps) | t (NW) | BH q | hit rate | cost hurdle (bps) | selected |", "|---|---|---|---|---|---|---|---|"]
    for k, s in rep["dev"].items():
        L.append(f"| {k} | {s['days']} | {s['mean_bps']:+.2f} | {s['t_nw']:+.2f} | {s['bh_q']:.3f} | {s['hit_rate']:.3f} | "
                 f"{s['cost_hurdle_bps']:.1f} | {s['direction'] or '—'} |")
    L += ["", "## Locked period (opened once)", ""]
    lk = rep.get("lock")
    if not lk:
        L.append("Not opened.")
    elif not lk["tests"]:
        L.append(lk.get("note", "nothing selected"))
    else:
        L += ["| test | direction | days | mean (bps) | t (NW) | one-sided p | net of hurdle (bps) | verdict |", "|---|---|---|---|---|---|---|---|"]

        def f(x, fmt):
            return "—" if x is None or x != x else format(x, fmt)
        for k, s in lk["tests"].items():
            L.append(f"| {k} | {s['direction']} | {s['days']} | {f(s['mean_bps'], '+.2f')} | {f(s['t_nw'], '+.2f')} | "
                     f"{f(s['p_one'], '.4f')} | {f(s['net_bps'], '+.2f')} | {'**pass**' if s['passed'] else 'fail'} |")
        L.append(f"\nOpened {lk['opened']}.")
    return "\n".join(L) + "\n"
