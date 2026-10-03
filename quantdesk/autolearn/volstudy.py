"""Pre-registered move-size study (docs/prereg/vol_forecast_v1.json): does the desk's VolForecaster forecast the
realised variance of the next 30m / 60m / 120m / to the close, and does a seasonal or HAR model do better?

For an option buyer the size of the move matters more than its direction, and size is predictable where direction
mostly is not. The desk's VolForecaster (intraday/quant.py) feeds the EV Monte Carlo that decides what it buys. Its
realised part has hand-set constants and treats every minute of the day as equally volatile. This study measures it
on 13 years of index minutes.

Candidates (only these three, fixed by the spec):
- A_desk: the desk's forecaster without IV;
- B_seasonal: A on returns scaled by the minute-of-day volatility profile;
- C_har: a HAR log regression on B and daily realised variances.
Selection is on dev yearly folds; a one-shot Diebold-Mariano lock runs on 2019 onward.

Uses: underlying_features, regime_research, development_folds (the dataset's ALLOWED_USES). There are no option prices
here, so nothing in this study speaks to option profitability.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..data import external_aeron as X
from .prereg import nw_t, spec_hash

N_MIN = 375
DECISIONS = list(range(15, 346, 15))               # minute index from 09:15: 09:30, 09:45 … 15:00
HORIZONS = {"30m": 30, "60m": 60, "120m": 120, "close": None}
LAM = 0.5 ** (1 / 30)                              # VolForecaster(halflife_min=30)
PRIOR_DAYS = 5
CANDIDATES = ["A_desk", "B_seasonal", "C_har"]
BUCKETS = [(15, 45, "09:30-10:00"), (45, 135, "10:00-11:30"), (135, 255, "11:30-13:30"), (255, 346, "13:30-15:00")]
FLOOR = 1e-12


def grid(bars1: pd.DataFrame) -> tuple[pd.Index, np.ndarray, np.ndarray, np.ndarray]:
    """1-minute bars of one symbol → (days, r [days × 375] within-day log returns, missing mask, opens)."""
    b = bars1.copy()
    ts = pd.to_datetime(b["ts"]) if "ts" in b.columns else pd.DatetimeIndex(b.index)
    ts = pd.DatetimeIndex(ts).tz_convert(X.IST) if pd.DatetimeIndex(ts).tz is not None else pd.DatetimeIndex(ts).tz_localize(X.IST)
    day = ts.date
    m = ((ts.hour * 60 + ts.minute) - (9 * 60 + 15)).to_numpy()
    keep = (m >= 0) & (m < N_MIN)
    df = pd.DataFrame({"day": day[keep], "m": m[keep], "open": b["open"].to_numpy(float)[keep],
                       "close": b["close"].to_numpy(float)[keep]})
    df = df.drop_duplicates(["day", "m"], keep="last")
    close = df.pivot(index="day", columns="m", values="close").reindex(columns=range(N_MIN))
    first_open = df.sort_values("m").groupby("day")["open"].first().reindex(close.index)
    missing = close.isna().to_numpy()
    c = close.ffill(axis=1).bfill(axis=1).to_numpy()
    o = first_open.to_numpy()
    r = np.empty_like(c)
    r[:, 0] = np.log(c[:, 0] / o)
    r[:, 1:] = np.diff(np.log(c), axis=1)
    return pd.Index(close.index), np.nan_to_num(r), missing, o


def profile(r2: np.ndarray) -> np.ndarray:
    """Minute-of-day variance profile, mean 1: each day's squared returns over that day's mean, averaged over days."""
    dm = r2.mean(1, keepdims=True)
    ok = dm[:, 0] > 0
    s = (r2[ok] / dm[ok]).mean(0)
    return s / s.mean()


def _ewma_upto(x: np.ndarray, decisions: list[int]) -> dict[int, np.ndarray]:
    """EWMA (VolForecaster weights, normalised) of each row's x[:, :m] for each decision minute m."""
    S = np.zeros(x.shape[0])
    W = 0.0
    out = {}
    want = set(decisions)
    for j in range(max(decisions)):
        S = LAM * S + x[:, j]
        W = LAM * W + 1.0
        if j + 1 in want:
            out[j + 1] = S / W
    return out


def forecasts(r: np.ndarray, s: np.ndarray, valid_prior: np.ndarray) -> dict[str, dict]:
    """Per decision minute: A's and B's per-minute variance and today's deseasonalised RV so far; rows are days."""
    r2 = r ** 2
    r2s = r2 / s
    day_mean = r2.mean(1)
    day_mean_s = r2s.mean(1)
    prior = pd.Series(day_mean).rolling(PRIOR_DAYS).mean().shift(1).to_numpy().copy()
    prior_s = pd.Series(day_mean_s).rolling(PRIOR_DAYS).mean().shift(1).to_numpy().copy()
    prior[~valid_prior], prior_s[~valid_prior] = np.nan, np.nan
    ea, eb = _ewma_upto(r2, DECISIONS), _ewma_upto(r2s, DECISIONS)
    csum_s = np.r_[0.0, np.cumsum(s)]
    out = {}
    for m in DECISIONS:
        k = m / (m + 60)
        out[m] = {"A": k * ea[m] + (1 - k) * prior, "B": k * eb[m] + (1 - k) * prior_s,
                  "today_s": r2s[:, :m].mean(1), "csum_s": csum_s}
    return out


def rows(sym: str, days: pd.Index, r: np.ndarray, missing: np.ndarray, opens: np.ndarray, s: np.ndarray) -> pd.DataFrame:
    """One row per (day, decision, horizon): targets and the A / B forecasts, plus C's regressors."""
    dd = pd.to_datetime(pd.Series(days)).diff().dt.days.to_numpy()
    consecutive = dd <= 4
    valid_prior = pd.Series(consecutive.astype(float)).rolling(PRIOR_DAYS).min().fillna(0).to_numpy() > 0
    r2 = r ** 2
    rv_day = r2.sum(1)
    prev_rv = np.r_[np.nan, rv_day[:-1]]
    prev5 = pd.Series(rv_day).rolling(PRIOR_DAYS).mean().shift(1).to_numpy()
    prev_close = np.r_[np.nan, (opens * np.exp(r.sum(1)))[:-1]]
    gap = np.where(consecutive, np.abs(np.log(opens / prev_close)), np.nan)
    f = forecasts(r, s, valid_prior)
    cs_r, cs_r2 = np.c_[np.zeros(len(r)), np.cumsum(r, 1)], np.c_[np.zeros(len(r)), np.cumsum(r2, 1)]
    cs_miss = np.c_[np.zeros(len(r)), np.cumsum(missing, 1)]
    parts = []
    for m in DECISIONS:
        fm = f[m]
        for h, mins in HORIZONS.items():
            end = N_MIN if mins is None else m + mins
            if end > N_MIN:
                continue
            n = end - m
            seas = fm["csum_s"][end] - fm["csum_s"][m]
            parts.append(pd.DataFrame({
                "symbol": sym, "day": days, "year": pd.to_datetime(pd.Series(days)).dt.year.to_numpy(), "m": m,
                "horizon": h, "minutes": n,
                "rv": cs_r2[:, end] - cs_r2[:, m], "ret": cs_r[:, end] - cs_r[:, m],
                "miss_frac": (cs_miss[:, end] - cs_miss[:, m]) / n,
                "F_A": fm["A"] * n, "F_B": fm["B"] * seas,
                "x_prev": np.log(np.maximum(prev_rv, FLOOR)), "x_prev5": np.log(np.maximum(prev5, FLOOR)),
                "x_today": np.log(np.maximum(fm["today_s"] * N_MIN, FLOOR)), "x_gap": np.nan_to_num(gap)}))
    d = pd.concat(parts, ignore_index=True)
    d = d[np.isfinite(d["F_A"]) & np.isfinite(d["F_B"]) & np.isfinite(d["x_prev5"]) & (d["miss_frac"] <= 0.2)]
    return d.reset_index(drop=True)


C_X = ["lF_B", "x_prev", "x_prev5", "x_today", "x_gap"]


def fit_c(train: pd.DataFrame) -> dict:
    """Per horizon OLS of log RV on C_X, with a smearing factor."""
    out = {}
    for h, g in train.groupby("horizon"):
        X_ = np.c_[np.ones(len(g)), g[C_X].to_numpy(float)]
        y = np.log(np.maximum(g["rv"].to_numpy(float), FLOOR))
        beta, *_ = np.linalg.lstsq(X_, y, rcond=None)
        res = y - X_ @ beta
        out[h] = {"beta": beta.tolist(), "smear": float(np.mean(np.exp(res)))}
    return out


def predict_c(d: pd.DataFrame, fit: dict) -> np.ndarray:
    out = np.full(len(d), np.nan)
    for h, p in fit.items():
        i = (d["horizon"] == h).to_numpy()
        X_ = np.c_[np.ones(i.sum()), d.loc[i, C_X].to_numpy(float)]
        out[i] = np.exp(X_ @ np.array(p["beta"])) * p["smear"]
    return out


def qlike(rv: np.ndarray, f: np.ndarray) -> np.ndarray:
    q = np.maximum(rv, FLOOR) / f
    return q - np.log(q) - 1


def score(d: pd.DataFrame) -> dict:
    """Per candidate: mean QLIKE (day-averaged), log bias, and the buyer's calibration by time-of-day bucket."""
    out = {}
    for c in CANDIDATES:
        f = d[f"F_{c[0]}"].to_numpy(float)
        loss = pd.Series(qlike(d["rv"].to_numpy(float), f)).groupby(d["day"].to_numpy()).mean()
        cal = {}
        for lo, hi, name in BUCKETS:
            i = ((d["m"] >= lo) & (d["m"] < hi)).to_numpy()
            pred = np.mean(np.sqrt(2 / np.pi) * np.sqrt(f[i]))
            cal[name] = float(np.mean(np.abs(d["ret"].to_numpy(float)[i])) / pred) if i.any() else None
        out[c] = {"qlike": float(loss.mean()), "log_bias": float(np.mean(np.log(np.maximum(d["rv"], FLOOR) / f))),
                  "move_ratio_by_time": cal}
    return out


def daily_loss(d: pd.DataFrame, c: str) -> pd.Series:
    return pd.Series(qlike(d["rv"].to_numpy(float), d[f"F_{c[0]}"].to_numpy(float))).groupby(d["day"].to_numpy()).mean()


def prepare(ds: Path, symbols, train_years: list[int] | None = None) -> dict[str, tuple]:
    bars = X.load(ds, "1m", symbols, use="regime_research")
    out = {}
    for sym in symbols:
        out[sym] = grid(bars[bars["symbol"] == sym])
    return out


def run(cfg, ds: Path, spec_path: Path, results_dir: Path, open_lock: bool = False, say=print, grids=None) -> dict:
    spec = json.loads(Path(spec_path).read_text())
    h = spec_hash(spec_path)
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{spec['name']}-{h[:12]}.json"
    prior = json.loads(out_path.read_text()) if out_path.exists() else {}
    if open_lock and prior.get("lock"):
        raise RuntimeError(f"the lock for {spec['name']} ({h[:12]}) was opened on {prior['lock']['opened']}: never again")
    dev_end = dt.date.fromisoformat(spec["dev"]["end"])
    lock_start = dt.date.fromisoformat(spec["lock"]["start"])
    grids = grids or prepare(ds, spec["symbols"])
    rep = {"spec": spec["name"], "spec_sha256": h, "evidence": "external_verified (underlying only)", "not_for": spec["not_for"],
           "sessions": {}, "dev": {}, "selected": {}, "lock": prior.get("lock")}

    def frame(sym, train_mask, test_mask):
        days, r, miss, opens = grids[sym]
        s = profile((r ** 2)[train_mask])
        d = rows(sym, days, r, miss, opens, s)
        d["lF_B"] = np.log(np.maximum(d["F_B"], FLOOR))
        dd = pd.Index(d["day"])
        tr, te = d[np.isin(dd, days[train_mask])], d[np.isin(dd, days[test_mask])].copy()
        te["F_C"] = predict_c(te, fit_c(tr))
        return te, s

    dev_scores: dict[str, dict] = {}
    for sym in spec["symbols"]:
        days = grids[sym][0]
        yrs = pd.to_datetime(pd.Series(days)).dt.year.to_numpy()
        dev = np.array([d <= dev_end for d in days])
        rep["sessions"][sym] = {"dev": int(dev.sum()), "lock": int((np.array([d >= lock_start for d in days])).sum()),
                                "first": str(days[0]), "last": str(days[-1])}
        for y in range(2013, dev_end.year + 1):
            te, _ = frame(sym, dev & (yrs < y), dev & (yrs == y))
            for hz, g in te.groupby("horizon"):
                sc = score(g)
                for c in CANDIDATES:
                    dev_scores.setdefault(hz, {}).setdefault(c, []).append(sc[c]["qlike"])
                    rep["dev"].setdefault(f"{sym} {hz}", {}).setdefault(c, {})[str(y)] = sc[c]
            say(f"  dev {sym} {y}: " + ", ".join(f"{hz} " + "/".join(f"{rep['dev'][f'{sym} {hz}'][c][str(y)]['qlike']:.3f}"
                                                                       for c in CANDIDATES) for hz in HORIZONS))
    for hz, per in dev_scores.items():
        means = {c: float(np.mean(v)) for c, v in per.items()}
        best = min(CANDIDATES, key=lambda c: (round(means[c], 12), CANDIDATES.index(c)))
        rep["selected"][hz] = {"candidate": best, "dev_mean_qlike": means}
        say(f"  selected {hz}: {best}  " + "  ".join(f"{c} {means[c]:.4f}" for c in CANDIDATES))
    if open_lock:
        from scipy.stats import norm
        res = {"opened": pd.Timestamp.now(tz=X.IST).isoformat(), "tests": {}}
        for sym in spec["symbols"]:
            days = grids[sym][0]
            te, s = frame(sym, np.array([d <= dev_end for d in days]), np.array([d >= lock_start for d in days]))
            for hz, g in te.groupby("horizon"):
                sel = rep["selected"][hz]["candidate"]
                sc = score(g)
                row = {"selected": sel, "scores": sc}
                if sel != "A_desk":
                    diff = (daily_loss(g, "A_desk") - daily_loss(g, sel)).to_numpy()
                    t = nw_t(diff)
                    row.update({"dm_t": t, "p_one": float(norm.sf(t)), "days": int(len(diff)),
                                "qlike_gain_pct": float(100 * diff.mean() / daily_loss(g, "A_desk").mean())})
                    row["passed"] = bool(row["p_one"] < 0.05)
                res["tests"][f"{sym} {hz}"] = row
                say(f"  LOCK {sym} {hz}: {sel} " + (f"t {row['dm_t']:+.2f} gain {row['qlike_gain_pct']:+.1f}% "
                                                    f"{'PASS' if row['passed'] else 'fail'}" if sel != "A_desk" else "(A kept)"))
            res.setdefault("profile", {})[sym] = {f"{9 + (15 + i) // 60:02d}:{(15 + i) % 60:02d}": round(float(v), 3)
                                                  for i, v in enumerate(s) if i % 15 == 0 or i < 5 or i > 365}
        rep["lock"] = res
    out_path.write_text(json.dumps(rep, indent=1, default=str))
    rep["path"] = str(out_path)
    return rep


def render(rep: dict) -> str:
    L = [f"# Pre-registered move-size study: {rep['spec']}", "", f"Spec sha256 `{rep['spec_sha256']}` · **evidence: {rep['evidence']}** · {rep['not_for']}.", ""]
    for sym, s in rep["sessions"].items():
        L.append(f"- {sym}: {s['dev']} dev sessions, {s['lock']} lock sessions ({s['first']} → {s['last']})")
    L += ["", "## Selection on dev (mean QLIKE over 2013–2018 folds and both indices; lower is better)", "",
          "| horizon | A_desk | B_seasonal | C_har | selected |", "|---|---|---|---|---|"]
    for hz, s in rep["selected"].items():
        m = s["dev_mean_qlike"]
        L.append(f"| {hz} | {m['A_desk']:.4f} | {m['B_seasonal']:.4f} | {m['C_har']:.4f} | {s['candidate']} |")
    lk = rep.get("lock")
    L += ["", "## Locked period (opened once)", ""]
    if not lk:
        L.append("Not opened.")
    else:
        L += ["| index · horizon | selected | QLIKE A → selected | DM t | gain | verdict | move ratio by time, A | move ratio by time, selected |",
              "|---|---|---|---|---|---|---|---|"]
        for k, t in lk["tests"].items():
            sel = t["selected"]
            a, b = t["scores"]["A_desk"], t["scores"][sel]

            def mr(x):
                return " · ".join(f"{v:.2f}" for v in x["move_ratio_by_time"].values())
            L.append(f"| {k} | {sel} | {a['qlike']:.4f} → {b['qlike']:.4f} | {t.get('dm_t', float('nan')):+.2f} | "
                     f"{t.get('qlike_gain_pct', 0):+.1f}% | {'**pass**' if t.get('passed') else ('—' if sel == 'A_desk' else 'fail')} | {mr(a)} | {mr(b)} |")
        L += ["", "Move ratio = realised mean |move| ÷ the forecast's expected |move| (√(2/π)·σ), by 09:30–10:00 · 10:00–11:30 · "
              "11:30–13:30 · 13:30–15:00. 1.00 is calibrated; above 1 the forecast is too small, below 1 too big.",
              f"\nOpened {lk['opened']}."]
    return "\n".join(L) + "\n"
