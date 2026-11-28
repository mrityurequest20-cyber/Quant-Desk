"""News phase P2: what the market did after each story, measured from the warehouse and never by a model.

For every (story, instrument) pair: map the story to the first price that could have reacted to it, then read

  * ret       the instrument's log return over the reaction window
  * ar        the abnormal return: ret less beta x NIFTY's return over the same window (indices: ret itself)
  * z         ar in units of the instrument's own typical move (the 60-session std of daily abnormal returns)
  * vs_priced |ret| against the move options priced at the last close before the story (front ATM IV x sqrt(n/252))
  * d_iv      the change in front ATM IV over the window (vol points), and d_iv_z against its typical change
  * d_rr      the change in the 25-delta risk reversal (skew)
  * oi_chg    the change in futures open interest, and the build-up it makes with the price (long / short build-up,
              short covering, long unwinding)
  * drift5    the abnormal return over the next five sessions after the window: does the move continue or fade?

Timing (IST): a story with an exact time before 09:15 on a session day reacts in that session; between 09:15 and 15:30
also in that session (flagged in_session: part of the day's move came before it); after 15:30, or on a holiday, in the
next session. A story with only a day stamp (ts_quality "day") gets a two-session window, the day's session and the
next, because it could have landed before or after the close: the window is wider, never wrong.

The base is always the last close before the story could have been known, so the priced move and the IV are read
while the story was still ahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OPEN, CLOSE = (9, 15), (15, 30)
TYPICAL = 60


def window(ts: pd.Timestamp, quality: str, sessions: pd.DatetimeIndex) -> tuple[int, int, bool] | None:
    """(base, end, in_session) positions on the session calendar for a story at ts (UTC)."""
    t = pd.Timestamp(ts).tz_convert("Asia/Kolkata")
    day = pd.Timestamp(t.date())
    i = sessions.searchsorted(day)                               # the first session on or after the story's day
    on_session = i < len(sessions) and sessions[i] == day
    if quality != "exact":
        base, end = i - 1, i + 1
        in_sess = False
    else:
        hm = (t.hour, t.minute)
        if on_session and hm < OPEN:
            base, end, in_sess = i - 1, i, False
        elif on_session and hm <= CLOSE:
            base, end, in_sess = i - 1, i, True
        else:
            base = i if on_session else i - 1                     # after the close: that close is the base
            end, in_sess = base + 1, False
    if base < 0 or end >= len(sessions):
        return None
    return base, end, in_sess


def prepare(panel: pd.DataFrame, nifty: pd.Series | None, is_index: bool) -> pd.DataFrame:
    """The per-day columns reactions read, computed once per instrument. panel: the instrument's daily frame (close,
    iv_front, rr25, fut_oi, beta_n), indexed by session date."""
    p = panel.sort_index().copy()
    r = np.log(p["close"]).diff()
    if is_index or nifty is None:
        p["beta"] = 1.0
        ar1 = r
    else:
        rn = np.log(nifty.reindex(p.index)).diff()
        p["beta"] = p["beta_n"].clip(0, 3).fillna(1.0) if "beta_n" in p else 1.0
        ar1 = r - p["beta"].shift(1).fillna(1.0) * rn
    p["ar_sd"] = ar1.rolling(TYPICAL, min_periods=30).std().shift(1)
    if "iv_front" in p:
        p["div_sd"] = p["iv_front"].diff().rolling(TYPICAL, min_periods=30).std().shift(1)
    return p


def react(p: pd.DataFrame, nifty: pd.Series | None, ts, quality: str, is_index: bool) -> dict | None:
    s = p.index
    w = window(ts, quality, s)
    if w is None:
        return None
    b, e, in_sess = w
    n = e - b
    c0, c1 = p["close"].iat[b], p["close"].iat[e]
    if not (np.isfinite(c0) and np.isfinite(c1) and c0 > 0 and c1 > 0):
        return None
    ret = float(np.log(c1 / c0))
    out = {"base": str(s[b].date()), "end": str(s[e].date()), "n": int(n), "in_session": bool(in_sess), "ret": ret}
    if is_index or nifty is None:
        ar = ret
    else:
        nb, ne = nifty.get(s[b]), nifty.get(s[e])
        ar = ret - float(p["beta"].iat[b]) * float(np.log(ne / nb)) if nb and ne else None
    out["ar"] = ar
    sd = p["ar_sd"].iat[b]
    out["z"] = float(ar / (sd * np.sqrt(n))) if ar is not None and np.isfinite(sd) and sd > 0 else None
    iv0 = p["iv_front"].iat[b] if "iv_front" in p else np.nan
    if np.isfinite(iv0) and iv0 > 0:
        out["iv0"] = float(iv0)
        out["vs_priced"] = float(abs(ret) / (iv0 * np.sqrt(n / 252)))
        iv1 = p["iv_front"].iat[e]
        if np.isfinite(iv1):
            out["d_iv"] = float(iv1 - iv0)
            dsd = p["div_sd"].iat[b] if "div_sd" in p else np.nan
            out["d_iv_z"] = float((iv1 - iv0) / (dsd * np.sqrt(n))) if np.isfinite(dsd) and dsd > 0 else None
    if "rr25" in p:
        a, z = p["rr25"].iat[b], p["rr25"].iat[e]
        out["d_rr"] = float(z - a) if np.isfinite(a) and np.isfinite(z) else None
    if "fut_oi" in p:
        a, z = p["fut_oi"].iat[b], p["fut_oi"].iat[e]
        if np.isfinite(a) and np.isfinite(z) and a > 0:
            ch = float(z / a - 1)
            out["oi_chg"] = ch
            out["buildup"] = ("long build-up" if ret > 0 and ch > 0 else "short covering" if ret > 0
                              else "short build-up" if ch > 0 else "long unwinding")
    if e + 5 < len(s):
        r5 = float(np.log(p["close"].iat[e + 5] / c1))
        if not (is_index or nifty is None):
            n0, n5 = nifty.get(s[e]), nifty.get(s[e + 5])
            r5 = r5 - float(p["beta"].iat[e]) * float(np.log(n5 / n0)) if n0 and n5 else None
        out["drift5"] = r5
    return out


def reactions(events: pd.DataFrame, panels: dict[str, pd.DataFrame], kinds: dict[str, str]) -> pd.DataFrame:
    """events: id, ts, ts_quality, and `targets` (the instruments each story is about: a list). panels: symbol ->
    daily frame; kinds: symbol -> "index" | "stock" | "vix". One row per (story, instrument)."""
    nifty = panels["NIFTY"]["close"].sort_index() if "NIFTY" in panels else None
    prep = {s: prepare(p, nifty, kinds.get(s) != "stock") for s, p in panels.items() if len(p) > TYPICAL}
    rows = []
    for ev in events.itertuples():
        for sym in ev.targets:
            p = prep.get(sym)
            if p is None:
                continue
            r = react(p, nifty, ev.ts, ev.ts_quality, kinds.get(sym) != "stock")
            if r:
                rows.append({"id": ev.id, "symbol": sym, **r})
    return pd.DataFrame(rows)
