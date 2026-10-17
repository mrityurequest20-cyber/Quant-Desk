"""The live HAR volatility forecast: vol_forecast_v1's C_har (autolearn/volstudy.py) on the desk's own 1-minute bars.

The pre-registered study fitted a HAR log regression per horizon (30m / 60m / 120m / to the close) on 13 years of index
minutes and passed its locked 2019-26 test on both indices (docs/EXTERNAL_DATA.md). This module runs that model, not a
look-alike: the features and the fit are volstudy's own functions (`grid`, `rows`, `fit_har`, `predict_c`).

Where the coefficients come from: fitted OFFLINE on the external minutes, with the spec's own training window (every
session up to the spec's dev end, 2018-12-31: exactly what the locked test used), and stored as a small JSON file
(`python -m quantdesk autolearn vol-har-fit`, default runtime/research/vol_har_v1.json). The desk does not refit at
session start: the 6 sessions of 1-minute bars it loads are too few for a 5-regressor fit per horizon and a minute-of-day
profile, and a fit on them would be a different, untested model. Point in time: the file records the last session it
was trained on, and the desk refuses it unless that is before the session being traded.

Live, each forecast uses only completed bars before `now` and the 5 prior complete sessions, at the minute the last
bar completed (the study evaluated every 15 minutes; any minute from 09:30 to 15:00 is the same model).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ..autolearn import volstudy as V

SCHEMA = 1
BAR = pd.Timedelta(minutes=1)
FIRST, LAST = min(V.DECISIONS), max(V.DECISIONS)       # 09:30 … 15:00: the decision points the study covered
MIN_BARS = 360                                         # a session is complete at the study's own acceptance bound
MAX_MISSING_TODAY = V.N_MIN - MIN_BARS


# ---- offline: fit and store the coefficients ----------------------------------------------------------------------
def fit_coefs(grids: dict, dev_end: dt.date, spec: str = "", spec_sha256: str = "", dataset: str = "") -> dict:
    """C_har per symbol on every session up to `dev_end` (the spec's training window); `grids` as volstudy.prepare()."""
    out = {"schema": SCHEMA, "model": "C_har", "spec": spec, "spec_sha256": spec_sha256, "dataset": dataset,
           "dev_end": str(dev_end), "symbols": {}}
    for sym, (days, r, miss, opens) in grids.items():
        train = np.array([d <= dev_end for d in days])
        s, fit, _ = V.fit_har(sym, days, r, miss, opens, train)
        out["symbols"][sym] = {"profile": s.tolist(), "fit": fit, "sessions": int(train.sum()),
                               "trained_through": str(max(d for d, t in zip(days, train) if t))}
    return out


def save_coefs(path, coefs: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(coefs, indent=1))
    tmp.replace(p)


def load_coefs(path) -> tuple[dict | None, str]:
    """(coefficients, "") or (None, why not)."""
    p = Path(path)
    if not p.exists():
        return None, f"no coefficients file {p.name} (python -m quantdesk autolearn vol-har-fit)"
    try:
        c = json.loads(p.read_text())
    except (ValueError, OSError) as exc:
        return None, f"coefficients file unreadable ({exc!s:.80})"
    if c.get("schema") != SCHEMA or c.get("model") != "C_har" or not isinstance(c.get("symbols"), dict):
        return None, "coefficients file is not a C_har schema-1 file"
    return c, ""


# ---- live ---------------------------------------------------------------------------------------------------------
class HarVol:
    """One symbol's HAR forecaster, from its entry in the coefficients file."""

    def __init__(self, entry: dict):
        self.profile = np.asarray(entry["profile"], float)
        self.fit = entry["fit"]
        self.trained_through = dt.date.fromisoformat(entry["trained_through"])

    @classmethod
    def for_session(cls, coefs: dict, sym: str, day: dt.date) -> tuple["HarVol | None", str]:
        e = (coefs.get("symbols") or {}).get(sym)
        if e is None:
            return None, f"no coefficients for {sym}"
        try:
            h = cls(e)
        except (KeyError, ValueError, TypeError):
            return None, f"coefficients for {sym} are malformed"
        if len(h.profile) != V.N_MIN:
            return None, f"coefficients for {sym} are malformed"
        if h.trained_through >= day:
            return None, f"the fit for {sym} ends {h.trained_through}, not before the session {day}"
        return h, ""

    def forecast(self, bars: pd.DataFrame, now: pd.Timestamp) -> tuple[dict | None, str]:
        """Variance of the log-return path over the next 30m / 60m / 120m / to the close, from completed 1m bars before
        `now`. → ({"m": minutes elapsed, "minutes": {h: n}, "var": {h: variance}}, "") or (None, why not)."""
        day = now.date()
        b = bars[bars.index + BAR <= now]
        if b.empty or b.index[-1].date() != day:
            return None, "no bars yet today"
        if (b.index.date == day).sum() < FIRST:
            return None, f"before {FIRST} minutes of the session"
        prior = sorted(d for d in set(b.index.date) if d < day)[-V.PRIOR_DAYS:]
        if len(prior) < V.PRIOR_DAYS:
            return None, f"needs {V.PRIOR_DAYS} prior sessions of bars"
        days, r, miss, opens = V.grid(b[np.isin(b.index.date, prior + [day])][["open", "close"]])
        miss = np.array(miss, dtype=bool)                      # writable (pandas hands back a read-only view)
        if len(days) != V.PRIOR_DAYS + 1 or days[-1] != day:
            return None, "needs 5 prior sessions of bars"
        if ((~miss[:-1]).sum(1) < MIN_BARS).any():
            return None, "a prior session is incomplete"
        seen = np.flatnonzero(~miss[-1])
        m = int(seen[-1]) + 1
        if m < FIRST:
            return None, f"before {FIRST} minutes of the session"
        if m > LAST:
            return None, "after the last studied decision point (15:00)"
        if miss[-1, :m].sum() > MAX_MISSING_TODAY:
            return None, "too many of today's minutes are missing"
        miss[-1, m:] = False                                   # the future is not "missing": nothing past `m` is used
        d = V.rows("", days, r, miss, opens, self.profile, decisions=[m])
        d = d[(d["day"] == day).to_numpy()].copy()
        if d.empty:
            return None, "the prior sessions are not consecutive"
        d["lF_B"] = np.log(np.maximum(d["F_B"], V.FLOOR))
        f = V.predict_c(d, self.fit)
        ok = np.isfinite(f) & (f > 0)
        if not ok.any():
            return None, "no horizon could be forecast"
        hz = d["horizon"].to_numpy()[ok]
        return {"m": m, "minutes": dict(zip(hz, d["minutes"].to_numpy()[ok].astype(int).tolist())),
                "var": dict(zip(hz, f[ok].tolist()))}, ""
