"""BANKNIFTY against NIFTY: which index is leading, and whether the leader keeps leading.

The desk trades both indices and so picks between them, until now implicitly. The ratio BANKNIFTY / NIFTY makes it
explicit (all in log terms, so a ratio move is BANKNIFTY's return minus NIFTY's):

* `rs_day`: the ratio since yesterday's close: BANKNIFTY's day minus NIFTY's;
* `rs_30`: the ratio in the last 30 minutes, and `z30`: that move in σ of the ratio's own 30-minute moves over the
  prior sessions (how unusual today's divergence is);
* `beta` / `corr`: BANKNIFTY's 1-minute returns on NIFTY's today (a beta well above 1 means a NIFTY move is a bigger
  BANKNIFTY move: the same view, more movement per rupee of premium).

Whether relative strength *persists* intraday (the index that led the last 30 minutes leads the next 30) is an
empirical question, so it is measured before it's used. `persistence_pairs` takes every 5-minute point of every
session in the bars (09:45–14:55): x = the ratio's last 30 minutes, y = its next 30. The learning loop accumulates
their correlation (overlap-adjusted: points 5 minutes apart over a 30-minute horizon count 1/6 each), seeded from the
bars the desk already loads. `preference()` acts only once that IC is positive with t ≥ 2: a plan that is long the
laggard or short the leader then has its conviction cut, and one with the leader (long) or the laggard (short) gets a
small lift. Until then relative strength is context in the read, nothing more.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

PAIR = ("BANKNIFTY", "NIFTY")           # the ratio is PAIR[0] / PAIR[1]
STEP, H = 5, 30                         # persistence: a point every 5 minutes, 30 minutes back and forward
CLIP_BPS = 150.0
MIN_N, MIN_T = 30.0, 2.0                # what the persistence record needs before the preference acts
CUT, LIFT = 0.8, 1.1                    # conviction against / with relative strength, once it's earned


def _ratio(a: pd.DataFrame, b: pd.DataFrame) -> pd.Series:
    """log(a / b) on the minutes both have, IST index (bar start)."""
    j = pd.concat([a["close"].rename("a"), b["close"].rename("b")], axis=1, join="inner").dropna()
    j = j[(j["a"] > 0) & (j["b"] > 0)]
    return np.log(j["a"] / j["b"])


def rel_strength(a: pd.DataFrame | None, b: pd.DataFrame | None, day, now: pd.Timestamp | None = None) -> dict | None:
    """The read for `day` (a = BANKNIFTY bars, b = NIFTY bars, 1-minute, with prior sessions for the history)."""
    if a is None or b is None or a.empty or b.empty:
        return None
    lr = _ratio(a, b)
    if now is not None:
        lr = lr[lr.index <= now]
    dates = np.array(lr.index.date)
    today, prior = lr[dates == day], lr[dates < day]
    if len(today) < 2 or prior.empty:
        return None
    cur = float(today.iloc[-1])
    out = {"pair": f"{PAIR[0]}/{PAIR[1]}", "ts": str(today.index[-1]), "rs_day": cur - float(prior.iloc[-1])}
    t = today.index[-1]
    ago = today[today.index <= t - pd.Timedelta(minutes=H)]
    if len(ago):
        out["rs_30"] = cur - float(ago.iloc[-1])
        s30 = _sigma30(prior)
        if s30:
            out["z30"] = out["rs_30"] / s30
            out["sigma30"] = s30
    ra = np.log(a["close"]).diff()
    rb = np.log(b["close"]).diff()
    j = pd.concat([ra.rename("a"), rb.rename("b")], axis=1, join="inner").dropna()
    j = j[j.index.date == day]
    if now is not None:
        j = j[j.index <= now]
    if len(j) >= 30 and j["b"].var() > 0:
        out["beta"] = float(j["a"].cov(j["b"]) / j["b"].var())
        out["corr"] = float(j["a"].corr(j["b"]))
    out["leader"] = PAIR[0] if out["rs_day"] > 0 else PAIR[1]
    return out


def _sigma30(prior: pd.Series, days: int = 10) -> float | None:
    """σ of the ratio's 30-minute moves (non-overlapping, within a session) over the last `days` prior sessions."""
    dates = np.array(prior.index.date)
    keep = sorted(set(dates))[-days:]
    moves = []
    for d in keep:
        x = prior[dates == d]
        x = x.resample(f"{H}min").last().dropna()
        moves += list(np.diff(x.to_numpy()))
    return float(np.std(moves, ddof=1)) if len(moves) >= 10 else None


def persistence_pairs(a: pd.DataFrame | None, b: pd.DataFrame | None, after: str = "") -> pd.DataFrame:
    """(ts, x, y) for every 5-minute point of every complete session after the date `after` (YYYY-MM-DD): x the
    ratio's last 30 minutes, y its next 30, both in bps."""
    if a is None or b is None or a.empty or b.empty:
        return pd.DataFrame(columns=["x", "y"])
    lr = _ratio(a, b)
    rows = []
    for d, x in lr.groupby(lr.index.date):
        if str(d) <= after or len(x) < 300 or (x.index[-1].hour, x.index[-1].minute) < (15, 25):
            continue                                              # only whole sessions, each graded once
        g = x.resample("1min").last().ffill()
        for t in pd.date_range(f"{d} 09:45", f"{d} 14:55", freq=f"{STEP}min", tz=x.index.tz):
            if t - pd.Timedelta(minutes=H) not in g.index or t + pd.Timedelta(minutes=H) not in g.index or t not in g.index:
                continue
            x0, x1, x2 = g[t - pd.Timedelta(minutes=H)], g[t], g[t + pd.Timedelta(minutes=H)]
            rows.append((t, (x1 - x0) * 1e4, (x2 - x1) * 1e4))
    return pd.DataFrame(rows, columns=["ts", "x", "y"]).set_index("ts") if rows else pd.DataFrame(columns=["x", "y"])


def grade(mem, bars: dict) -> int:
    """Add every new whole session in `bars` to the persistence record (learning.Memory `rs`). Returns points added."""
    a, b = bars.get(PAIR[0]), bars.get(PAIR[1])
    rec = mem.d.setdefault("rs", {"s": [0.0] * 6, "upto": "", "days": 0})
    p = persistence_pairs(a, b, rec["upto"])
    if p.empty:
        return 0
    w = min(1.0, STEP / H)
    x, y = np.clip(p["x"].to_numpy(), -CLIP_BPS, CLIP_BPS), np.clip(p["y"].to_numpy(), -CLIP_BPS, CLIP_BPS)
    for k, v in enumerate((w * len(x), w * x.sum(), w * y.sum(), w * (x * x).sum(), w * (y * y).sum(), w * (x * y).sum())):
        rec["s"][k] += float(v)
    rec["days"] += len(set(p.index.date))
    rec["upto"] = str(max(p.index.date))
    return len(p)


def record(mem) -> dict | None:
    """{n, ic, t, days}: does the leader of the last 30 minutes lead the next 30?"""
    rec = (mem.d.get("rs") if mem is not None else None) or {}
    W, Sx, Sy, Sxx, Syy, Sxy = rec.get("s") or [0.0] * 6
    if W < 5:
        return None
    vx, vy = Sxx / W - (Sx / W) ** 2, Syy / W - (Sy / W) ** 2
    if vx <= 1e-12 or vy <= 1e-12:
        return None
    r = float(np.clip((Sxy / W - Sx * Sy / W ** 2) / math.sqrt(vx * vy), -0.999, 0.999))
    return {"n": round(W, 1), "ic": round(r, 4), "t": round(r * math.sqrt(max(W - 2, 0) / (1 - r * r)), 2),
            "days": rec.get("days", 0), "upto": rec.get("upto", "")}


def earned(rec: dict | None) -> bool:
    return bool(rec and rec["n"] >= MIN_N and rec["ic"] > 0 and rec["t"] >= MIN_T)


def preference(u: str, direction: int, rs: dict | None, rec: dict | None, min_z: float = 1.0) -> tuple[float, str] | None:
    """(conviction multiplier, note) for a plan on `u` in `direction` (+1 long / −1 short), or None when relative
    strength has nothing to say: its persistence isn't proven yet, or the last 30 minutes weren't unusual."""
    if not earned(rec) or not rs or rs.get("z30") is None or abs(rs["z30"]) < min_z or u not in PAIR or not direction:
        return None
    lead = PAIR[0] if rs["z30"] > 0 else PAIR[1]                   # leader over the last 30 minutes
    other = PAIR[1] if u == PAIR[0] else PAIR[0]
    with_it = (u == lead) == (direction > 0)                       # long the leader, or short the laggard
    m = LIFT if with_it else CUT
    side = "long" if direction > 0 else "short"
    return m, (f"relative strength: {lead} led {other if lead == u else u} by {abs(rs['rs_30']):.2%} in 30 min "
               f"({abs(rs['z30']):.1f}σ); {side} {u} {'goes with' if with_it else 'fights'} it → conviction ×{m:.2f} "
               f"(persistence IC {rec['ic']:+.3f}, t {rec['t']:+.1f})")


def describe(rs: dict | None) -> str | None:
    """One sentence for the read."""
    if not rs:
        return None
    s = f"{PAIR[0]} vs {PAIR[1]}: {rs['leader']} leading by {abs(rs['rs_day']):.2%} on the day"
    if rs.get("rs_30") is not None:
        s += f", {rs['rs_30']:+.2%} in 30 min" + (f" ({rs['z30']:+.1f}σ)" if rs.get("z30") is not None else "")
    if rs.get("beta") is not None:
        s += f"; β {rs['beta']:.2f}, ρ {rs['corr']:.2f} on 1-minute moves today"
    return s
