"""History the brief reads from the data itself: each company's results reactions, and the indices' macro-event days.

**Implied move** (`atm_implied`): per symbol and session, the at-the-money straddle at closing prices, of the nearest
expiry at least `MIN_DTE` days away, over the price (`move`), and as an annualised volatility (`iv` = move / 0.8 /
sqrt(dte / 365); 0.8 ~ sqrt(2 / pi), the straddle-to-sigma factor).

**Results events** come from two places:
* the calendar (`results_calendar`): NSE's board meetings whose purpose mentions results. The meeting's session is
  D0; NSE does not say whether results land in or after market hours, so the reaction window is D-1's close to
  D+1's close (it holds the reaction either way, plus one ordinary session);
* the data's fingerprint (`inferred_results`), for years the calendar table does not cover: on the session results
  land, implied volatility on the same expiry collapses while the stock jumps. A session counts when IV falls by
  at least 12% and the move is at least 3x the stock's median of its previous 20 sessions. Measured against 144
  calendar results meetings of Oct 2026, those thresholds were right 86% of the time and found about a quarter of
  the events; the thresholds were chosen on the same season, so both numbers are optimistic. The reaction window
  is the session before to the session after. A calendar event within 3 sessions replaces an inferred one.

**Per event** (`results_history`): the move over the window, the IV before (D-1) against the stock's normal IV (the
median of sessions pre-30 to pre-10), the **event-implied move** (the variance above normal, over the time left:
sqrt(max(iv_pre^2 - iv_base^2, 0) x dte / 365)) and what a straddle bought at the window's start and sold at its end
returned at closing prices (no costs).

Closing prices only: the bhavcopy's open is the day's first trade, which for thin stock options is often a stale
print, and it made blind open-to-close returns look profitable where closing prices say they are not.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

MIN_DTE = 7
CRUSH = -0.12                       # IV change on the same expiry, session over session
JUMP = 3.0                          # |move| over the stock's median |move| of its previous 20 sessions
BASE_FROM, BASE_TO = 30, 10         # normal IV: median of sessions pre-30 .. pre-10
DEDUP_SESSIONS = 40                 # at most one inferred event per stock in this many sessions
CALENDAR_WINS_WITHIN = 3
SQRT_2_PI = 0.7979
MACRO_DATES = Path(__file__).with_name("macro_dates.json")


def _spot_table(o: pd.DataFrame) -> pd.Series:
    """(symbol, date) -> price: the bhavcopy's underlying, else the nearest future's close."""
    u = o[pd.to_numeric(o["underlying"], errors="coerce") > 0].groupby(["symbol", "date"])["underlying"].first() \
        if "underlying" in o else pd.Series(dtype=float)
    f = o[(o["kind"] == "FUT") & (o["close"] > 0)].sort_values("expiry").groupby(["symbol", "date"])["close"].first()
    return u.combine_first(f).astype(float)


def atm_implied(opts: pd.DataFrame, min_dte: int = MIN_DTE) -> pd.DataFrame:
    """symbol, date, expiry, dte, spot, strike, straddle, move, iv: one row per symbol-session that has an
    at-the-money call and put with closing prices on the nearest expiry at least `min_dte` days away."""
    cols = ["symbol", "date", "expiry", "dte", "spot", "strike", "straddle", "move", "iv"]
    if opts is None or len(opts) == 0:
        return pd.DataFrame(columns=cols)
    o = opts.copy()
    o["date"] = pd.to_datetime(o["date"])
    o["expiry"] = pd.to_datetime(o["expiry"])
    sp = _spot_table(o).rename("spot")
    o = o[o["kind"].isin(["CE", "PE"]) & (o["close"] > 0)]
    o = o.assign(dte=(o["expiry"] - o["date"]).dt.days)
    o = o[o["dte"] >= min_dte]
    if o.empty:
        return pd.DataFrame(columns=cols)
    near = o.groupby(["symbol", "date"])["expiry"].transform("min")
    o = o[o["expiry"] == near]
    p = o.pivot_table(index=["symbol", "date", "expiry", "dte", "strike"], columns="kind", values="close", aggfunc="first")
    if not {"CE", "PE"} <= set(p.columns):
        return pd.DataFrame(columns=cols)
    p = p.dropna(subset=["CE", "PE"]).reset_index().join(sp, on=["symbol", "date"])
    p = p[p["spot"] > 0]
    p["dist"] = (p["strike"] - p["spot"]).abs()
    p = p.loc[p.groupby(["symbol", "date"])["dist"].idxmin()]
    p["straddle"] = p["CE"] + p["PE"]
    p["move"] = p["straddle"] / p["spot"]
    p["iv"] = p["move"] / SQRT_2_PI / np.sqrt(p["dte"] / 365.0)
    return p[cols].sort_values(["symbol", "date"]).reset_index(drop=True)


def sessions_of(df: pd.DataFrame) -> list[pd.Timestamp]:
    return sorted(pd.to_datetime(df["date"]).unique())


def results_calendar(corp_events: pd.DataFrame | None, sessions: list[pd.Timestamp], symbols=None) -> pd.DataFrame:
    """symbol, meeting, d0 (the first session on or after the meeting), company, from NSE's event calendar."""
    cols = ["symbol", "meeting", "d0", "company", "source"]
    if corp_events is None or len(corp_events) == 0 or not sessions:
        return pd.DataFrame(columns=cols)
    c = corp_events.copy()
    c["date"] = pd.to_datetime(c["date"])
    c = c[c["purpose"].astype(str).str.contains("result", case=False)]
    if symbols is not None:
        c = c[c["symbol"].isin(set(symbols))]
    s = pd.DatetimeIndex(sessions)
    i = s.searchsorted(c["date"].values)
    c = c.assign(d0=[s[k] if k < len(s) else pd.NaT for k in i])
    c = c.dropna(subset=["d0"]).drop_duplicates(["symbol", "d0"])
    return pd.DataFrame({"symbol": c["symbol"].values, "meeting": c["date"].values, "d0": c["d0"].values,
                         "company": c.get("company", pd.Series([""] * len(c))).values, "source": "calendar"})


def inferred_results(implied: pd.DataFrame, crush: float = CRUSH, jump: float = JUMP, dedup: int = DEDUP_SESSIONS) -> pd.DataFrame:
    """symbol, react (the session whose close first shows the result), score, source='inferred'."""
    cols = ["symbol", "react", "score", "source"]
    if implied is None or implied.empty:
        return pd.DataFrame(columns=cols)
    v = implied.sort_values(["symbol", "date"]).copy()
    g = v.groupby("symbol")
    same = g["expiry"].shift() == v["expiry"]
    v["crush"] = np.where(same, v["iv"] / g["iv"].shift() - 1, np.nan)
    v["absret"] = (v["spot"] / g["spot"].shift() - 1).abs()
    v["typ"] = v.groupby("symbol")["absret"].transform(lambda s: s.rolling(20, min_periods=8).median().shift(1))
    v["jump"] = v["absret"] / v["typ"]
    hit = v[(v["crush"] <= crush) & (v["jump"] >= jump)].copy()
    if hit.empty:
        return pd.DataFrame(columns=cols)
    hit["score"] = (-hit["crush"]) * np.log1p(hit["jump"])
    pos = {t: i for i, t in enumerate(sessions_of(v))}
    keep = []
    for sym, h in hit.groupby("symbol"):
        taken: list[int] = []
        for r in h.sort_values("score", ascending=False).itertuples():
            k = pos[r.date]
            if all(abs(k - t) >= dedup for t in taken):
                taken.append(k)
                keep.append({"symbol": sym, "react": r.date, "score": float(r.score), "source": "inferred"})
    return pd.DataFrame(keep, columns=cols).sort_values(["symbol", "react"]).reset_index(drop=True)


def _windows(calendar: pd.DataFrame, inferred: pd.DataFrame, sessions: list[pd.Timestamp]) -> pd.DataFrame:
    """One row per event: symbol, source, d0 (calendar) or react (inferred), pre and post sessions."""
    pos = {t: i for i, t in enumerate(sessions)}
    rows, cal_at = [], {}
    for r in calendar.itertuples():
        k = pos.get(pd.Timestamp(r.d0))
        if k is None or k < 1 or k + 1 >= len(sessions):
            continue
        cal_at.setdefault(r.symbol, []).append(k)
        rows.append({"symbol": r.symbol, "source": "calendar", "event": sessions[k], "pre": sessions[k - 1], "post": sessions[k + 1]})
    for r in inferred.itertuples():
        k = pos.get(pd.Timestamp(r.react))
        if k is None or k < 1 or k + 1 >= len(sessions):
            continue
        if any(abs(k - c) <= CALENDAR_WINS_WITHIN for c in cal_at.get(r.symbol, [])):
            continue
        rows.append({"symbol": r.symbol, "source": "inferred", "event": sessions[k], "pre": sessions[k - 1], "post": sessions[k + 1]})
    return pd.DataFrame(rows, columns=["symbol", "source", "event", "pre", "post"])


def base_iv(implied: pd.DataFrame, symbol: str, at: pd.Timestamp, sessions: list[pd.Timestamp]) -> float:
    """The stock's normal IV before `at`: the median over sessions at-30 .. at-10 (before any run-up into an event)."""
    pos = {t: i for i, t in enumerate(sessions)}
    k = pos.get(pd.Timestamp(at))
    if k is None:
        k = int(pd.DatetimeIndex(sessions).searchsorted(pd.Timestamp(at)))
    lo, hi = max(0, k - BASE_FROM), max(0, k - BASE_TO)
    if hi <= lo:
        return float("nan")
    win = set(sessions[lo:hi])
    x = implied[(implied["symbol"] == symbol) & implied["date"].isin(win)]["iv"]
    return float(x.median()) if len(x) >= 5 else float("nan")


def event_implied_move(iv_now: float, iv_normal: float, dte: float) -> float:
    """The move the options price for the event alone: the variance above the stock's normal level, over the time left."""
    if not all(x == x for x in (iv_now, iv_normal, dte)) or dte <= 0:
        return float("nan")
    return float(np.sqrt(max(iv_now ** 2 - iv_normal ** 2, 0.0) * dte / 365.0))


def results_history(opts: pd.DataFrame, implied: pd.DataFrame, calendar: pd.DataFrame, inferred: pd.DataFrame) -> pd.DataFrame:
    """One row per past results event: symbol, source, event, pre, post, spot_pre, spot_post, move, iv_pre, iv_base,
    iem (event-implied move), straddle_pre, straddle_ret (bought at pre's close, sold at post's, same strike and
    expiry, closing prices, no costs; NaN when either leg has no close at post)."""
    cols = ["symbol", "source", "event", "pre", "post", "spot_pre", "spot_post", "move", "iv_pre", "iv_base", "iem",
            "straddle_pre", "straddle_ret"]
    if implied is None or implied.empty:
        return pd.DataFrame(columns=cols)
    sessions = sessions_of(implied)
    w = _windows(calendar, inferred, sessions)
    if w.empty:
        return pd.DataFrame(columns=cols)
    imp = implied.set_index(["symbol", "date"])
    o = opts[opts["kind"].isin(["CE", "PE"])].copy()
    o["date"] = pd.to_datetime(o["date"])
    o["expiry"] = pd.to_datetime(o["expiry"])
    px = o.set_index(["symbol", "date", "expiry", "strike", "kind"])["close"]
    px = px[~px.index.duplicated()]
    rows = []
    for r in w.itertuples():
        try:
            a, b = imp.loc[(r.symbol, r.pre)], imp.loc[(r.symbol, r.post)]
        except KeyError:
            continue
        ivb = base_iv(implied, r.symbol, r.pre, sessions)
        sell = [px.get((r.symbol, r.post, a["expiry"], a["strike"], k)) for k in ("CE", "PE")]
        sret = (sum(sell) / a["straddle"] - 1) if all(s is not None and s == s and s > 0 for s in sell) else float("nan")
        rows.append({"symbol": r.symbol, "source": r.source, "event": r.event, "pre": r.pre, "post": r.post,
                     "spot_pre": a["spot"], "spot_post": b["spot"], "move": abs(b["spot"] / a["spot"] - 1),
                     "iv_pre": a["iv"], "iv_base": ivb, "iem": event_implied_move(a["iv"], ivb, a["dte"]),
                     "straddle_pre": a["straddle"], "straddle_ret": sret})
    return pd.DataFrame(rows, columns=cols)


def profile(history: pd.DataFrame, symbol: str, last: int = 8, sources=None) -> dict:
    """A company's own results record: how many, how far it moved, what the options had priced, what a straddle paid.
    `sources` keeps only events of those sources: inferred events are found *because* the stock jumped, so their moves
    overstate a typical results move and only calendar events give an unbiased comparison."""
    h = history[history["symbol"] == symbol]
    if sources is not None:
        h = h[h["source"].isin(set(sources))]
    h = h.sort_values("event")
    if h.empty:
        return {"n": 0}
    ratio = (h["move"] / h["iem"]).replace([np.inf, -np.inf], np.nan)
    return {"n": int(len(h)), "n_calendar": int((h["source"] == "calendar").sum()),
            "median_move": float(h["move"].median()), "median_iem": float(h["iem"].median()),
            "median_move_over_iem": float(ratio.median()) if ratio.notna().any() else float("nan"),
            "median_straddle_ret": float(h["straddle_ret"].median()) if h["straddle_ret"].notna().any() else float("nan"),
            "events": [{"date": pd.Timestamp(r.event).date().isoformat(), "source": r.source, "move": round(float(r.move), 4),
                        "iem": None if r.iem != r.iem else round(float(r.iem), 4),
                        "straddle_ret": None if r.straddle_ret != r.straddle_ret else round(float(r.straddle_ret), 3)}
                       for r in h.tail(last).itertuples()]}


# ---- macro events on the indices -----------------------------------------------------------------------------
def macro_dates(path: Path = MACRO_DATES) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def kind_of(name: str) -> str | None:
    n = name.lower()
    for key, words in (("rbi", ("rbi", "mpc")), ("fomc", ("fomc", "federal reserve")), ("budget", ("budget",)),
                       ("election", ("election", "exit poll"))):
        if any(w in n for w in words):
            return key
    return None


def macro_history(index_close: pd.DataFrame | None, dates: dict | None = None, symbols=("NIFTY", "BANKNIFTY")) -> dict:
    """kind -> symbol -> {n, median |close-to-close move| on the event's Indian session, the same on all sessions, the
    share of event sessions moving more than 1%, and the same on all}. FOMC dates are US dates: the Indian session
    that reacts is the next one."""
    if index_close is None or len(index_close) == 0:
        return {}
    dates = dates or macro_dates()
    ic = index_close.copy()
    ic["date"] = pd.to_datetime(ic["date"])
    out = {}
    for kind, spec in dates.get("kinds", {}).items():
        days = pd.to_datetime(spec.get("dates", []))
        res = {}
        for sym in symbols:
            s = ic[ic["symbol"] == sym].sort_values("date").drop_duplicates("date")
            if len(s) < 30:
                continue
            s = s.assign(absret=(s["close"] / s["close"].shift() - 1).abs()).dropna(subset=["absret"])
            idx = pd.DatetimeIndex(s["date"])
            k = idx.searchsorted(days, side="right" if spec.get("reacts") == "next_session" else "left")
            hit = sorted({idx[i] for i in k if i < len(idx)})
            e = s[s["date"].isin(hit)]
            if e.empty:
                continue
            res[sym] = {"n": int(len(e)), "median_move": float(e["absret"].median()), "median_move_all": float(s["absret"].median()),
                        "share_over_1pct": float((e["absret"] > 0.01).mean()), "share_over_1pct_all": float((s["absret"] > 0.01).mean())}
        if res:
            out[kind] = res
    return out
