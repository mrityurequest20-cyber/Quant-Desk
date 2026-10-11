"""The risk governor: pure functions that adjust the intraday desk's effective risk limits, inside a hard envelope, and
only ever TIGHTEN them.

    effective limit = base × scale, clamped to min(cfg value, ceiling)           (no code path goes above that)
    s = max(floor, min(s_cap, s_R × s_DD, s_vol))     s is quantised DOWN to STEP, so a continuous drawdown does not
                                                      journal a change every minute

      s_cap  the earned ceiling on the scale (persisted; starts at `start_cap`; nothing here raises it, see earn_up)
      s_R    clip(0.5 + ΣR/(n+10), 0.25, 1) over the last 20 closed trades (Trade.r_multiple: pnl per rupee of the
             planned risk of the lots actually traded, so trading smaller does not change the record)
      s_DD   clip(1 − dd/0.10, 0.25, 1), dd = peak-to-date drawdown of paper equity
      s_vol  0.7 when the realised 30-minute range is > 1.5× its forecast, or India VIX > 1.5× its 20-session median
             (an input that is unavailable is neutral, 1.0). The forecast range is the Brownian expected range of the
             engine's 30-minute sigma (RANGE_PER_SIGMA × sigma_30m), because a range is not a sigma: against a bare
             sigma the rule would fire about half the time on an ordinary day.

    risk_per_trade × s · max_trades = max(1, round(base × s)) · max_open = 1 if s < 0.5 else base
    max_total_outlay × s · daily_loss_limit × max(s, 0.5)

Stand-downs (each only blocks or shrinks, never loosens): a day stand-down after 3 consecutive losing trades; a 60-minute
entry pause when the mean slippage of the last 3 entries exceeds 7.5% of premium; an unreliable feed (3+ WARN-or-worse
events today in data/quotes/engine, or any stale-feed halt) halves size and exposure and allows one position, to the close.

Modes (intraday.governor.mode): off (nothing) · shadow (computed and journaled, NO effect on trading) · tighten (the
effective limits are used, paper account only). In live mode (account.mode != paper) the limits stay identity and the
governor only journals proposals. Any exception is the engine's cue to use identity limits (log_fault: one log line per
process). This module imports the standard library only: no config writer, kill-switch code, account-mode setter or
credentials (tests/test_governor.py checks the imports), and the engine's halts (_blocked) and plan_gate are not its business.
"""
from __future__ import annotations

import copy
import datetime as dt
import logging
import math
import statistics

log = logging.getLogger(__name__)
_logged = False                                         # one log line per process

VERSION = 1
MODES = ("off", "shadow", "tighten")
FIELDS = ("risk_per_trade", "max_trades", "max_open", "max_exposure", "daily_loss")        # IntradayRisk attribute names
CEIL_KEY = {"risk_per_trade": "risk_per_trade", "max_trades": "max_trades_per_day", "max_open": "max_open",
            "max_exposure": "max_total_outlay", "daily_loss": "daily_loss_pct"}            # → intraday.governor.ceilings
INT_FIELDS = ("max_trades", "max_open")
UNRELIABLE_FIELDS = ("max_open", "risk_per_trade", "max_exposure")
STEP = 0.05
RANGE_PER_SIGMA = 2 * math.sqrt(2 / math.pi)            # E[range] of a Brownian path over its horizon, in sigmas
VOL_X, VIX_X, VIX_MIN_SESSIONS = 1.5, 1.5, 10
LOSS_STREAK, PAUSE_MIN, SLIP_LIMIT, SLIP_N = 3, 60, 0.075, 3
FEED_EVENTS = 3
LOG_CAP = 100


# ---- small helpers ----------------------------------------------------------------------------------------
def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _f(x, d):
    v = _num(x)
    return d if v is None else v


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def _quant(x):
    return round(math.floor(x / STEP + 1e-9) * STEP, 4)


def _ts(x):
    if not x:
        return None
    return x if isinstance(x, dt.datetime) else dt.datetime.fromisoformat(str(x))


def _r(x):
    return round(x, 6) if isinstance(x, float) else x


def log_fault(exc: BaseException) -> None:
    """The engine's one call when anything in the governor raised: it then uses identity limits."""
    global _logged
    if not _logged:
        _logged = True
        log.warning("risk governor failed (%r): identity limits, no change to trading", exc)


# ---- config -----------------------------------------------------------------------------------------------
def settings(raw) -> dict:
    """intraday.governor, made safe: a missing section or an unknown mode is `off`; floor and cap live in [0, 1]."""
    g = raw if isinstance(raw, dict) else {}
    mode = g.get("mode", "off")
    ceil = g.get("ceilings") if isinstance(g.get("ceilings"), dict) else {}
    return {"mode": mode if mode in MODES else "off", "floor": _clip(_f(g.get("floor"), 0.25), 0.0, 1.0),
            "start_cap": _clip(_f(g.get("start_cap"), 0.5), 0.0, 1.0),
            "ceilings": {k: v for k, x in ceil.items() if (v := _num(x)) is not None and v >= 0}}


# ---- the rules --------------------------------------------------------------------------------------------
def s_r(rs) -> float:
    r = [v for v in (_num(x) for x in list(rs or [])[-20:]) if v is not None]
    return _clip(0.5 + sum(r) / (len(r) + 10), 0.25, 1.0)


def s_dd(equity, peak) -> float:
    e, p = _num(equity), _num(peak)
    if e is None or p is None or p <= 0:
        return 1.0
    return _clip(1 - max(0.0, 1 - e / p) / 0.10, 0.25, 1.0)


def s_vol(range_pct, sigma30_pct, vix, vix_med) -> float:
    rp, sg, v, m = _num(range_pct), _num(sigma30_pct), _num(vix), _num(vix_med)
    hot = (rp is not None and sg is not None and sg > 0 and rp > VOL_X * RANGE_PER_SIGMA * sg) \
        or (v is not None and m is not None and m > 0 and v > VIX_X * m)
    return 0.7 if hot else 1.0


def vix_median(hist, day) -> float | None:
    """Median of the last 20 sessions' VIX closes before `day`; None (neutral) with fewer than VIX_MIN_SESSIONS."""
    h = sorted((k, v) for k, x in (hist or {}).items() if k < str(day) and (v := _num(x)) is not None and v > 0)[-20:]
    return statistics.median(v for _, v in h) if len(h) >= VIX_MIN_SESSIONS else None


def scale(st: dict, obs: dict, gc: dict) -> tuple[float, dict]:
    """(s, parts): the effective scale and what produced it."""
    sr, sd = s_r(st.get("recent_r")), s_dd(obs.get("equity"), st.get("peak_equity"))
    vm = obs["vix_med"] if "vix_med" in obs else vix_median(st.get("vix_hist"), st["day"]["date"])
    sv = s_vol(obs.get("range_pct"), obs.get("fc_sigma30_pct"), obs.get("vix"), vm)
    cap = _clip(min(_f(st.get("s_cap"), gc["start_cap"]), gc["start_cap"]), 0.0, 1.0)     # earn_up is not built: never above start_cap
    name, raw = min((("s_cap", cap), ("s_R*s_DD", sr * sd), ("s_vol", sv)), key=lambda c: c[1])
    s = _quant(min(raw, 1.0))
    if s < gc["floor"]:
        s, name = gc["floor"], "floor"
    return s, {"s_cap": cap, "s_R": sr, "s_DD": sd, "s_vol": sv, "vix_med": vm, "binding": name}


def limits(base: dict, s: float, unreliable: bool, gc: dict) -> dict:
    """The effective limits: scaled, then clamped to min(cfg value, ceiling). A cfg value of None (no cap) is bounded by
    the ceiling alone. Nothing here can exceed that bound, whatever s is."""
    f = 0.5 if unreliable else 1.0
    out = {}
    for k in FIELDS:
        b, c = _num(base.get(k)), gc["ceilings"].get(CEIL_KEY[k])
        cap = min((x for x in (b, c) if x is not None), default=None)
        if cap is None:
            out[k] = None
            continue
        x = b if b is not None else cap
        v = {"risk_per_trade": x * s * f, "max_exposure": x * s * f, "daily_loss": x * max(s, 0.5),
             "max_trades": max(1, round(x * s)), "max_open": 1 if (s < 0.5 or unreliable) else x}[k]
        v = min(v, cap)
        out[k] = int(math.floor(v)) if k in INT_FIELDS else v
    return out


# ---- state ------------------------------------------------------------------------------------------------
def _new_day(day, base: dict) -> dict:
    return {"date": str(day), "consec": 0, "slips": [], "stale": False, "feed_events": 0, "unreliable": False,
            "last": {**{k: base.get(k) for k in FIELDS}, "standdown_until": None, "unreliable_feed": False}}


def new_state(day, gc: dict, base: dict, recent_r=None, peak=None) -> dict:
    return {"v": VERSION, "s_cap": gc["start_cap"], "since": str(day), "last_change": None, "standdown_until": None,
            "standdown_why": None, "recent_r": [round(x, 4) for x in (_num(r) for r in (recent_r or [])[-20:]) if x is not None],
            "peak_equity": _num(peak), "vix_hist": {}, "day": _new_day(day, base), "log": []}


def note_vix(st: dict, closes: dict, day) -> dict:
    """Fold earlier sessions' VIX closes into the rolling 20-session history (the engine only loads a few days)."""
    st = copy.deepcopy(st)
    h = st.setdefault("vix_hist", {})
    for k, x in (closes or {}).items():
        if (v := _num(x)) is not None and v > 0 and str(k) < str(day):
            h[str(k)] = round(v, 4)
    st["vix_hist"] = dict(sorted(h.items())[-20:])
    return st


def _roll(st: dict, day, base: dict) -> None:
    if st["day"]["date"] != str(day):
        st["day"], st["standdown_until"], st["standdown_why"] = _new_day(day, base), None, None


def _stand(st: dict, until, why: str) -> None:
    cur = _ts(st.get("standdown_until"))
    if cur is None or until > cur:
        st["standdown_until"], st["standdown_why"] = until.isoformat(), why


def on_open(st: dict, slip, now, gc: dict) -> dict:
    """An entry was filled; `slip` is its fill vs the plan's legs as a fraction of premium (entry_slippage)."""
    st = copy.deepcopy(st)
    d = st["day"]
    if (v := _num(slip)) is not None:
        d["slips"] = (d["slips"] + [round(v, 6)])[-SLIP_N:]
    if len(d["slips"]) >= SLIP_N and sum(d["slips"]) / len(d["slips"]) > SLIP_LIMIT:
        _stand(st, now + dt.timedelta(minutes=PAUSE_MIN),
               f"entry_pause: mean slippage of the last {SLIP_N} entries {sum(d['slips']) / len(d['slips']):.1%} > {SLIP_LIMIT:.1%}")
    return st


def on_close(st: dict, pnl, r, now, gc: dict) -> dict:
    """A trade closed: its R joins the record (last 20), and a third straight loss stands the desk down for the day."""
    st = copy.deepcopy(st)
    d = st["day"]
    if (v := _num(r)) is not None:
        st["recent_r"] = (st["recent_r"] + [round(v, 4)])[-20:]
    if (p := _num(pnl)) is not None:
        d["consec"] = d["consec"] + 1 if p < 0 else 0
    if d["consec"] >= LOSS_STREAK:
        _stand(st, now.replace(hour=23, minute=59, second=59, microsecond=0), f"day_standdown: {d['consec']} straight losing trades")
    return st


# ---- the decision -----------------------------------------------------------------------------------------
def tick(st: dict, obs: dict, base: dict, gc: dict, now) -> tuple[dict, dict]:
    """One look at the desk. obs: equity, range_pct, fc_sigma30_pct, vix (vix_med optional), feed_events, stale; anything
    missing or not finite is neutral. Returns (new state, decision); decision["changes"] are the only things to journal."""
    st = copy.deepcopy(st)
    obs = obs or {}
    _roll(st, now.date(), base)
    d = st["day"]
    eq = _num(obs.get("equity"))
    if eq is not None and eq > 0:
        st["peak_equity"] = max(_f(st.get("peak_equity"), eq), eq)
    d["feed_events"] = max(d["feed_events"], int(_f(obs.get("feed_events"), 0)))
    d["stale"] = d["stale"] or bool(obs.get("stale"))
    was = d["last"]["unreliable_feed"]
    d["unreliable"] = d["unreliable"] or d["stale"] or d["feed_events"] >= FEED_EVENTS
    s, parts = scale(st, obs, gc)
    lim = limits(base, s, d["unreliable"], gc)
    until = _ts(st["standdown_until"])
    hold = {"until": st["standdown_until"], "why": st["standdown_why"]} if until is not None and now < until else None
    rs = [x for x in (_num(v) for v in st["recent_r"][-20:]) if x is not None]
    pk = _num(st.get("peak_equity"))
    ev = {k: _r(v) for k, v in {
        "scale": s, "s_cap": parts["s_cap"], "s_R": parts["s_R"], "s_DD": parts["s_DD"], "s_vol": parts["s_vol"], "n_R": len(rs),
        "sum_R": sum(rs), "equity": eq, "peak": pk, "dd": max(0.0, 1 - eq / pk) if eq is not None and pk else 0.0,
        "range_pct": _num(obs.get("range_pct")), "fc_sigma30_pct": _num(obs.get("fc_sigma30_pct")), "vix": _num(obs.get("vix")),
        "vix_med": parts["vix_med"], "feed_events": d["feed_events"], "stale": d["stale"], "consec": d["consec"],
        "slips": d["slips"]}.items()}
    cur = {**lim, "standdown_until": st["standdown_until"], "unreliable_feed": d["unreliable"]}
    changes = _changes(d["last"], cur, parts, s, st, ev, was)
    if changes:
        st["log"] = (st["log"] + [{"ts": now.isoformat(), **c} for c in changes])[-LOG_CAP:]
        st["last_change"] = now.isoformat()
    d["last"] = cur
    return st, {"s": s, "parts": parts, "limits": lim, "unreliable": d["unreliable"], "hold": hold, "changes": changes, "evidence": ev}


def _changes(old: dict, new: dict, parts: dict, s: float, st: dict, ev: dict, was_unreliable: bool) -> list[dict]:
    out = []
    why = (f"scale {s:.2f} (binding {parts['binding']}: s_cap {parts['s_cap']:.2f}, s_R {parts['s_R']:.2f}, s_DD {parts['s_DD']:.2f}, "
           f"s_vol {parts['s_vol']:.2f})" + ("; unreliable feed: one position, size and exposure ×0.5" if new["unreliable_feed"] else ""))
    for k in (*FIELDS, "standdown_until", "unreliable_feed"):
        o, n = old.get(k), new.get(k)
        if o == n or (isinstance(o, (int, float)) and isinstance(n, (int, float)) and math.isclose(o, n, rel_tol=1e-9, abs_tol=1e-12)):
            continue
        if k == "standdown_until":
            rule, reason = (st["standdown_why"] or "standdown").split(":")[0], st["standdown_why"]
        elif k == "unreliable_feed":
            rule, reason = "unreliable_feed", (f"{ev['feed_events']} WARN-or-worse events in data/quotes/engine today"
                                              + ("; a stale-feed halt today" if ev["stale"] else ""))
        elif new["unreliable_feed"] and not was_unreliable and k in UNRELIABLE_FIELDS:
            rule, reason = "unreliable_feed", why
        else:
            rule, reason = parts["binding"], why
        out.append({"rule": rule, "field": k, "old": _r(o), "new": _r(n), "reason": reason, "evidence": ev})
    return out


def effective(dec: dict, mode: str, account_mode, now=None):
    """(limits, hold_until, why) to hand to the risk engine, or (None, None, "") = identity. Only `tighten` mode on a
    paper account ever returns anything else; shadow, off and live only journal."""
    if mode != "tighten" or account_mode != "paper":
        return None, None, ""
    h = dec.get("hold")
    return dec["limits"], (_ts(h["until"]) if h else None), (h["why"] if h else "")


# ---- measurements the engine feeds in ----------------------------------------------------------------------------
def entry_slippage(legs_plan, entry_prices) -> float | None:
    """Fill vs plan as a fraction of the planned net premium; + is adverse (paid more, or collected less). legs_plan is
    meta["legs_plan"] of engine._open: (strike, right, ratio, price, iv, delta) per leg, ratio < 0 for a sold leg."""
    try:
        if not legs_plan or len(legs_plan) != len(entry_prices):
            return None
        plan = sum(float(l[2]) * float(l[3]) for l in legs_plan)
        fill = sum(float(l[2]) * float(p) for l, p in zip(legs_plan, entry_prices))
    except (TypeError, ValueError, IndexError):
        return None
    return _num((fill - plan) / abs(plan)) if abs(plan) > 0 else None


def realised_range_pct(highs, lows, close) -> float | None:
    """(highest high − lowest low) over the window, as a % of the last close."""
    h = [v for v in (_num(x) for x in highs) if v is not None]
    l = [v for v in (_num(x) for x in lows) if v is not None]
    c = _num(close)
    return (max(h) - min(l)) / c * 100 if h and l and c is not None and c > 0 else None


# ---- NOT BUILT: earn-up ----------------------------------------------------------------------------------------------
def earn_up(st: dict, record, gc: dict) -> dict:
    """STUB, deliberately unused and inert. Loosening ("earn-up", raising s_cap above start_cap as the live record earns
    it) is not part of this change and is not wired into tick() or the engine: today s_cap only ever stays where it is.
    Design for the later, separately reviewed PR: s_cap rises only in small steps (<= 0.1) after a minimum number of
    sessions and closed trades with a positive, significant R record (not on P&L), never past the ceilings in
    intraday.governor, never mid-session, never in live mode, and only with the owner's sign-off recorded in the journal;
    every rise is journaled with its evidence, and a drawdown or a stand-down takes it straight back."""
    return st
